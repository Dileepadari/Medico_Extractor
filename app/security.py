"""API key verification and a small in-process rate limiter."""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque

from fastapi import Request

from app.config import Settings
from app.errors import RateLimitedError, UnauthorizedError
from app.middleware import client_ip

API_KEY_HEADER = "X-API-Key"


def verify_api_key(request: Request) -> None:
    """Reject the request unless it carries the configured API key.

    No-op when `API_KEY` is unset, which is the convenient default for local use.
    """
    settings: Settings = request.app.state.settings
    if settings.api_key is None:
        return

    expected = settings.api_key.get_secret_value()
    provided = request.headers.get(API_KEY_HEADER, "")
    if not provided:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()

    # Constant-time compare so a wrong key can't be discovered byte by byte.
    if not provided or not secrets.compare_digest(provided, expected):
        raise UnauthorizedError()


class SlidingWindowRateLimiter:
    """Fixed budget per sliding window, keyed by client IP.

    Deliberately in-process and dependency-free: it protects a single instance
    from a runaway client and from surprise model spend. It is *not* a
    distributed limiter - with N replicas the effective budget is N x the limit.
    Put a real limiter at the edge if you need an exact global cap.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.max_requests > 0 and self.window_seconds > 0

    def check(self, key: str, *, now: float | None = None) -> None:
        """Record a hit for `key`, raising `RateLimitedError` if it's over budget."""
        if not self.enabled:
            return

        now = time.monotonic() if now is None else now
        cutoff = now - self.window_seconds

        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= self.max_requests:
                retry_after = max(1, int(hits[0] + self.window_seconds - now) + 1)
                raise RateLimitedError(
                    f"Rate limit of {self.max_requests} requests per "
                    f"{self.window_seconds}s exceeded.",
                    retry_after=retry_after,
                )

            hits.append(now)
            self._prune(cutoff)

    def _prune(self, cutoff: float) -> None:
        """Drop idle keys so the map can't grow without bound. Caller holds the lock."""
        if len(self._hits) < 1024:
            return
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def enforce_rate_limit(request: Request) -> None:
    limiter: SlidingWindowRateLimiter = request.app.state.rate_limiter
    limiter.check(client_ip(request))
