# Developer Guide

Architecture, local setup, configuration and deployment for Medico Extractor.
For what the service does and how to call it, see [README.md](./README.md).

---

## Contents

- [Architecture](#architecture)
- [Project layout](#project-layout)
- [Local setup](#local-setup)
- [Configuration](#configuration)
- [Request lifecycle](#request-lifecycle)
- [The extraction service](#the-extraction-service)
- [Errors](#errors)
- [Logging and observability](#logging-and-observability)
- [Testing](#testing)
- [The frontend](#the-frontend)
- [Deployment](#deployment)
- [Handling patient data](#handling-patient-data)
- [Operations runbook](#operations-runbook)
- [Extending the schema](#extending-the-schema)

---

## Architecture

One FastAPI process. No database, no queue, no object storage - state would only
be PHI at rest, and there is nothing here that needs to outlive a request.

```
browser / API client
        │  multipart POST  (PDF or image)
        ▼
┌─────────────────────────────────────────────────────────┐
│ FastAPI (app/main.py)                                   │
│                                                          │
│  RequestContextMiddleware   request id, access log       │
│  SecurityHeadersMiddleware  nosniff, DENY, no-store, HSTS│
│  CORSMiddleware / GZip                                   │
│                                                          │
│  /healthz  /readyz          routers/health.py            │
│  /api/v1/extract            routers/extraction.py        │
│     ├── verify_api_key            security.py            │
│     ├── enforce_rate_limit        security.py            │
│     ├── read_upload               services/documents.py  │
│     └── ReferralExtractor.extract services/extractor.py  │
│                                          │               │
└──────────────────────────────────────────┼───────────────┘
                                           ▼
                              Gemini (structured output)
```

Three ideas hold the design together:

**Documents are never trusted and never persisted.** `services/documents.py` reads
the upload in 64 KiB chunks, aborts the moment it crosses the size limit, and
classifies the file by its magic bytes - the client's `Content-Type` is only a
hint. The bytes then live in one `ValidatedDocument` for the length of the
request and are dropped.

**The model returns a type, not text.** `ExtractedReferralData` is handed to
LangChain's `with_structured_output`, so Gemini fills in a schema rather than
producing prose that we then have to parse. Sending the document straight to a
multimodal model also removes the entire OCR pipeline (Tesseract, Poppler,
`pdf2image`, `PyPDF2`) that an earlier version of this project needed.

**Everything request-scoped hangs off `app.state`.** Settings, the extractor and
the rate limiter are attached in `create_app()`, so there are no module-level
globals, and tests can build as many differently-configured apps as they like in
one process.

## Project layout

```
app/
├── main.py              App factory, middleware stack, static mounting, lifespan
├── config.py            Settings (pydantic-settings) + startup warnings
├── schemas.py           Request/response models; also the model's output schema
├── errors.py            Typed AppError hierarchy + the handlers that render them
├── middleware.py        Request id / access log / security headers, client IP
├── security.py          API key check, sliding-window rate limiter
├── dependencies.py      FastAPI dependencies reading off app.state
├── logging_config.py    JSON + console formatters, request-id contextvar
├── routers/
│   ├── health.py        /healthz, /readyz
│   └── extraction.py    /extract
└── services/
    ├── documents.py     Upload reading, size limits, magic-byte sniffing
    └── extractor.py     Gemini client, retries, timeouts, error mapping

static/                  The bundled UI (no build step)
├── index.html
├── styles.css
├── app.js
├── favicon.png
└── brand/logo.png       Brand mark, shared with dileepadari.dev

api/index.py             Vercel entrypoint (re-exports app.main:app)
tests/                   pytest suite - never touches the network
```

## Local setup

Python 3.11 or newer. Nothing else - no system packages.

```bash
make setup                        # venv + deps + .env from .env.example
echo 'GOOGLE_API_KEY=your-key' >> .env
make dev                          # http://localhost:8000 with reload
```

Without `make`:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env               # then edit it
uvicorn app.main:app --reload
```

`make help` lists every target (`test`, `cov`, `lint`, `fix`, `docker-build`, …).

Get a key from [Google AI Studio](https://aistudio.google.com/apikey). The service
starts without one - `/healthz` stays green, `/readyz` reports `not_ready`, and
`/extract` returns `503 model_not_configured` - which is deliberate: a missing
variable should be visible and fixable, not a crash loop.

## Configuration

Everything is environment variables, parsed and validated by `app/config.py`.
`.env` is read in development; in production set real environment variables.
Full annotated list: [`.env.example`](./.env.example).

| Variable | Default | Notes |
|---|---|---|
| `GOOGLE_API_KEY` | – | Required for extraction. `SecretStr`, so it never appears in a repr or log. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Any multimodal Gemini model. |
| `GEMINI_TEMPERATURE` | `0.0` | Leave at 0 - this is transcription, not writing. |
| `GEMINI_TIMEOUT_SECONDS` | `90` | Per attempt. Must fit inside your platform's request timeout. |
| `GEMINI_MAX_RETRIES` | `2` | Retries *on top of* the first attempt, transient failures only. |
| `ENVIRONMENT` | `development` | `production` enables HSTS and hides `/docs`. |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | `console` is the readable local format. |
| `CORS_ORIGINS` | `*` | Comma-separated. Set explicit origins in production. |
| `SERVE_FRONTEND` | `true` | `false` for an API-only deployment; `/` then returns service info. |
| `ENABLE_DOCS` | unset | Overrides the "off in production" default. |
| `ROOT_PATH` | `""` | Set when a proxy mounts the app under a path prefix. |
| `MAX_UPLOAD_BYTES` | `10485760` | 10 MiB. Raise carefully - see the memory note below. |
| `ALLOWED_CONTENT_TYPES` | pdf, jpeg, png, webp | Checked against sniffed bytes. |
| `API_KEY` | unset | When set, `/extract` requires `X-API-Key` (or `Authorization: Bearer`). |
| `RATE_LIMIT_REQUESTS` | `30` | Per client IP per window. `0` disables. |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | |

`Settings.startup_warnings()` runs at boot and logs anything questionable - a
missing key, `CORS_ORIGINS=*` in production, an unauthenticated production
deployment, `DEBUG` left on. It warns rather than refuses: an operator can fix an
environment variable on a running instance, but not on one that won't boot.

**Memory.** Each in-flight request holds the file plus its base64 encoding, so
budget roughly `MAX_UPLOAD_BYTES × 2.4 × concurrent requests`. At the defaults,
one worker with a handful of concurrent uploads fits comfortably in 512 MB.

## Request lifecycle

`POST /api/v1/extract` in order:

1. **Request id.** `RequestContextMiddleware` reuses an inbound `X-Request-ID`
   (so a gateway's trace survives) or mints one, and puts it in a `ContextVar`
   that every log line for this request reads.
2. **API key.** `verify_api_key` no-ops when `API_KEY` is unset; otherwise it
   compares with `secrets.compare_digest`.
3. **Rate limit.** `enforce_rate_limit` checks a sliding window keyed by client
   IP (`X-Forwarded-For` first). In-process only - see the caveat in
   `SlidingWindowRateLimiter`'s docstring.
4. **Upload validation.** `read_upload` streams, caps, sniffs and normalises the
   filename (path components stripped, exotic characters replaced).
5. **Extraction.** `ReferralExtractor.extract` with retries and a timeout.
6. **Response.** `{data, meta}`, plus `X-Request-ID` and `Cache-Control: no-store`.

Both `/api/v1/extract` and the unversioned `/extract` are routed to the same
handler; the latter is kept out of the OpenAPI schema and exists only so the
original clients keep working. Version new behaviour under `/api/v2` rather than
changing `/api/v1`'s response shape.

## The extraction service

`app/services/extractor.py`:

- **Lazy client.** The Gemini client is built on first use, so importing the app
  needs no credentials. `warm_up()` during startup builds it ahead of the first
  real request; failure there is logged, not fatal.
- **Retries we control.** The provider SDK's own retries are disabled
  (`max_retries=0`) in favour of `tenacity` with exponential backoff. Only
  transient failures qualify - `_is_retryable` matches on rate limits, 5xx and
  connection resets. A schema or safety rejection fails immediately; retrying it
  would just spend money.
- **Timeout per attempt.** `asyncio.wait_for` wraps each `ainvoke`, so a hung
  connection can't hold a worker forever.
- **Errors don't leak.** `_client_message` maps provider exceptions to a short,
  safe sentence. The full exception text - which can contain a partial API key -
  is logged, never returned.
- **Blocks by media type.** PDFs are sent as `{"type": "file", …}` content blocks
  and images as `{"type": "image", …}`, both base64 with an explicit `mime_type`,
  which is unambiguous about how the provider should treat the payload.

Prompt changes belong in `SYSTEM_INSTRUCTION`. Keep the "never guess, return an
empty string" rule - downstream code and the UI both treat `""` as "absent", and
a model that invents a plausible member ID is worse than one that returns nothing.

## Errors

Every failure is an `AppError` subclass in `app/errors.py` carrying a status code,
a stable `code` and a client-safe `message`; `register_exception_handlers` renders
all of them - plus Starlette HTTP exceptions and validation errors - into one
envelope. The catch-all handler logs the traceback and returns a generic message
with the request id, so an unexpected exception can never leak internals to a
caller. There is a test for exactly that (`test_unexpected_error_does_not_leak_internals`).

To add an error: subclass `AppError`, set `status_code`/`code`/`message`, raise it,
and add the code to the README's table.

## Logging and observability

- **JSON by default**, `LOG_FORMAT=console` for humans. `logging_config.py` owns
  the root handler; uvicorn's access log is disabled because
  `RequestContextMiddleware` already logs each request with the id, status,
  duration and client IP.
- **`request_id` on every line**, via a `ContextVar` - including the final access
  log line, which is written before the context is reset.
- **No PHI, ever.** Loggers record file size, sniffed content type and the
  sanitised filename. Document bytes, prompts and extracted values are never
  logged at any level. Keep it that way when adding log statements.
- **Probes.** `/healthz` is liveness (always 200 while the process is up).
  `/readyz` is readiness and returns 503 when credentials are missing, so a
  misconfigured instance leaves the load balancer pool instead of restarting.

## Testing

```bash
make test          # or: venv/bin/python -m pytest
make cov           # with a coverage report
make lint          # ruff
```

The suite never makes a network call and needs no API key - `tests/conftest.py`
pops any real credentials out of the environment and swaps a `StubExtractor` onto
`app.state`. `make_client(**settings_overrides)` builds an app with whatever
configuration a test needs, which is how the production-only behaviours (HSTS,
hidden docs) are covered.

What's covered: routing and the unversioned alias, upload validation and
magic-byte spoofing, API key and rate limiting, the full error-code mapping,
retry classification and timeout handling, settings parsing, and secret redaction.

When adding a feature, add the test alongside it. `pytest` is configured with
`asyncio_mode = "auto"`, so `async def test_*` needs no decorator.

## The frontend

`static/` is plain HTML, CSS and ES5-compatible JavaScript - deliberately no build
step, no npm, no lockfile to keep current. FastAPI serves it from `/`, so the API
and the UI are the same origin and same deployment.

- `app.js` calls the same origin by default. Set `window.MEDICO_API_BASE` before
  the script tag to point it elsewhere.
- `SECTIONS` in `app.js` mirrors the response schema and drives the whole results
  layout; changing the schema means changing that array.
- Colours are CSS custom properties on `:root`, with a `prefers-color-scheme:
  dark` block overriding the tokens only. The accent (`#47266b`) is sampled from
  the brand mark.
- The mark sits on a constant white chip so the single-colour logo reads correctly
  in both themes without being recoloured.
- An optional API key field stores its value in `sessionStorage` - it dies with
  the tab, unlike `localStorage`.

To disable the UI entirely, set `SERVE_FRONTEND=false`; `/` then returns a small
JSON service descriptor.

## Deployment

### Docker (recommended)

```bash
docker build -t medico-extractor:latest .
docker run -p 8000:8000 --env-file .env medico-extractor:latest
# or
docker compose up --build
```

The image is a two-stage build on `python:3.12-slim`, runs as a non-root user,
carries a `HEALTHCHECK` against `/healthz`, and disables uvicorn's access log
(the app writes its own). `docker-compose.yml` adds `read_only: true`,
`no-new-privileges`, a memory limit and a 64 MB tmpfs for Starlette's multipart
spooling.

Scale with replicas rather than workers (`WEB_CONCURRENCY` exists if you need it):
one process per container keeps the memory ceiling predictable, since uploads are
buffered in memory. Remember the rate limiter is per process - N replicas means N
times the configured budget.

### Vercel

`api/index.py` re-exports the ASGI app and `vercel.json` rewrites every path to
it, so the UI, the docs and the API all come from one function.

```bash
vercel env add GOOGLE_API_KEY production
vercel env add ENVIRONMENT production      # "production"
vercel env add CORS_ORIGINS production     # your origin(s)
vercel env add API_KEY production          # strongly recommended
vercel --prod
```

`maxDuration` is 60s, so set `GEMINI_TIMEOUT_SECONDS` **below** that (45 is a
sensible value) - otherwise the platform kills the request before the app can
return its own `504 model_timeout`. Serverless instances are also short-lived and
independent, which makes the in-process rate limiter close to useless there; put
a limiter at the edge if you need one.

### Anything else (Railway, Fly, Render, a VM)

Run `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers`, set the
environment variables, and point the platform's health check at `/healthz` and
its readiness check, if it has one, at `/readyz`.

### Production checklist

- [ ] `ENVIRONMENT=production`
- [ ] `GOOGLE_API_KEY` set from a secret store, never a committed file
- [ ] `API_KEY` set - without it, anyone who can reach the URL can spend your quota
- [ ] `CORS_ORIGINS` limited to origins you own
- [ ] TLS terminated in front of the app, with `--proxy-headers` enabled
- [ ] `GEMINI_TIMEOUT_SECONDS` below the platform's request timeout
- [ ] Logs shipped somewhere searchable by `request_id`
- [ ] Alerts on `/readyz` failing and on 5xx rate
- [ ] A BAA in place with your model provider before real PHI flows

## Handling patient data

The application is built so that PHI has nowhere to accumulate:

- uploads exist only in memory, for the duration of one request;
- nothing is written to disk, and there is no database or cache;
- logs carry metadata only - size, sniffed type, sanitised filename, timings;
- every response sends `Cache-Control: no-store`, and `Referrer-Policy: no-referrer`
  keeps document context out of third-party referrer headers;
- the browser keeps the file only until the request completes, and the optional
  API key lives in `sessionStorage`.

What the application **cannot** do for you:

- **A BAA with your model provider.** Documents are sent to Google. Use an
  offering covered by a business associate agreement before processing real PHI.
- **TLS.** Terminate HTTPS in front of the app; HSTS is set in production but only
  helps once TLS exists.
- **Access control beyond a shared key.** `API_KEY` is a single shared secret. If
  you need per-user identity and audit trails, put a real gateway in front.
- **Retention rules for anything you do with the JSON afterwards.** Once the
  response leaves this service, it is your system's problem.

If you add a feature that stores anything - a cache, a job queue, an audit log -
that decision changes this service's compliance posture. Treat it as a design
review, not a patch.

## Operations runbook

| Symptom | Likely cause | What to do |
|---|---|---|
| `/readyz` 503, `model_credentials: missing` | `GOOGLE_API_KEY` unset in this environment | Set it and restart; check the boot warnings. |
| All extractions 502, logs say credentials rejected | Key revoked, wrong project, or model not enabled for it | Verify the key in AI Studio; check `GEMINI_MODEL` is available to it. |
| Sporadic 502s under load | Provider rate limits | Raise `GEMINI_MAX_RETRIES`, lower `RATE_LIMIT_REQUESTS`, or request more quota. |
| 504 on large scans | Multi-page high-DPI PDFs are slow | Raise `GEMINI_TIMEOUT_SECONDS` (staying under the platform timeout), or have clients downsample. |
| 413 on documents users consider normal | `MAX_UPLOAD_BYTES` too low for your fax sources | Raise it, and re-check the memory budget above. |
| 415 on a real PDF | The file isn't a PDF - often an `.html` error page saved with a `.pdf` name | Check the first bytes; the sniffer is right more often than the extension. |
| Container restarts in a loop | Something other than configuration - `/healthz` doesn't depend on credentials | Read the startup logs; a missing key alone never causes this. |
| Fields empty that are clearly in the document | Model or prompt issue | Reproduce with the same file, then adjust `SYSTEM_INSTRUCTION` - and add a test. |

Every error response carries a `request_id`. Search logs for it to get the whole
story of one request without needing the document itself.

## Extending the schema

Adding a field is four edits, in this order:

1. `app/schemas.py` - add the field with a `description` written as an instruction
   to the model ("… Empty if not found."), defaulting to `""`.
2. `static/app.js` - add it to the matching section in `SECTIONS`.
3. `README.md` - update the field table and the example response.
4. `tests/` - assert on the new field.

The same Pydantic model is both the API contract and the model's output schema, so
step 1 is what actually teaches Gemini to look for the field. If a whole new
section is needed, add a nested model, add it to `ExtractedReferralData` with a
`default_factory`, and add a new entry to `SECTIONS`.

Changing or removing an existing field is a breaking change: add `/api/v2` rather
than editing `/api/v1`'s shape.
