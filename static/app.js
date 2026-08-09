/* Medico Extractor - frontend.
 *
 * Talks to the same origin by default, so the page works unchanged in local
 * development, on a preview deploy and in production. Override with
 * `window.MEDICO_API_BASE = "https://api.example.com"` before this script loads.
 */

(function () {
  "use strict";

  var API_BASE = (window.MEDICO_API_BASE || "").replace(/\/+$/, "");
  var EXTRACT_URL = API_BASE + "/api/v1/extract";
  var READY_URL = API_BASE + "/readyz";

  var MAX_BYTES = 10 * 1024 * 1024;
  var ACCEPTED = [
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
  ];

  /* Mirrors the response schema; drives the whole results layout. */
  var SECTIONS = [
    {
      id: "patient_demographics",
      title: "Patient demographics",
      wide: true,
      fields: [
        { key: "name", label: "Name" },
        { key: "dob", label: "Date of birth" },
        { key: "phone", label: "Phone" },
        { key: "email", label: "Email" },
      ],
    },
    {
      id: "primary_insurance",
      title: "Primary insurance",
      fields: [
        { key: "member_id", label: "Member ID" },
        { key: "group_id", label: "Group ID" },
        { key: "insurance_name", label: "Insurance name" },
        { key: "plan_name", label: "Plan name" },
      ],
    },
    {
      id: "secondary_insurance",
      title: "Secondary insurance",
      fields: [
        { key: "member_id", label: "Member ID" },
        { key: "group_id", label: "Group ID" },
      ],
    },
    {
      id: "referral_source",
      title: "Referral source",
      fields: [
        { key: "provider_name", label: "Provider name" },
        { key: "clinic_name", label: "Clinic name" },
        { key: "title", label: "Title" },
        { key: "phone", label: "Phone" },
      ],
    },
    {
      id: "referral_received_date",
      title: "Referral received date",
      fields: [{ key: "date", label: "Date" }],
    },
  ];

  var el = {
    dropzone: document.getElementById("dropzone"),
    fileInput: document.getElementById("fileInput"),
    fileHint: document.getElementById("fileHint"),
    extractBtn: document.getElementById("extractBtn"),
    resetBtn: document.getElementById("resetBtn"),
    status: document.getElementById("status"),
    statusText: document.getElementById("statusText"),
    alert: document.getElementById("alert"),
    alertText: document.getElementById("alertText"),
    alertMeta: document.getElementById("alertMeta"),
    results: document.getElementById("results"),
    resultsMeta: document.getElementById("resultsMeta"),
    cards: document.getElementById("cards"),
    copyBtn: document.getElementById("copyBtn"),
    downloadBtn: document.getElementById("downloadBtn"),
    badge: document.getElementById("serviceBadge"),
    apiKeyInput: document.getElementById("apiKeyInput"),
    settings: document.getElementById("settings"),
  };

  var selectedFile = null;
  var lastPayload = null;

  /* ---------------------------------------------------------------- utils */

  function formatBytes(bytes) {
    if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    return Math.max(1, Math.round(bytes / 1024)) + " KB";
  }

  function isBlank(value) {
    return typeof value !== "string" || value.trim() === "";
  }

  function showAlert(message, meta) {
    el.alertText.textContent = message;
    el.alertMeta.textContent = meta || "";
    el.alert.classList.add("is-visible");
  }

  function clearAlert() {
    el.alert.classList.remove("is-visible");
    el.alertText.textContent = "";
    el.alertMeta.textContent = "";
  }

  function setBusy(busy, message) {
    el.status.classList.toggle("is-visible", busy);
    if (message) el.statusText.textContent = message;
    el.extractBtn.disabled = busy || !selectedFile;
    el.resetBtn.disabled = busy || (!selectedFile && !lastPayload);
    el.dropzone.setAttribute("aria-disabled", busy ? "true" : "false");
  }

  /* --------------------------------------------------------- file handling */

  function selectFile(file) {
    clearAlert();

    if (!file) return;

    if (file.size === 0) {
      showAlert("That file is empty. Pick a different document.");
      return;
    }
    if (file.size > MAX_BYTES) {
      showAlert(
        "That file is " +
          formatBytes(file.size) +
          ". The limit is " +
          formatBytes(MAX_BYTES) +
          "."
      );
      return;
    }
    /* Browsers leave `type` blank for some scanner output; the server sniffs the
       real type either way, so an unknown type is not rejected here. */
    if (file.type && ACCEPTED.indexOf(file.type) === -1) {
      showAlert("Unsupported file type: " + file.type + ".");
      return;
    }

    selectedFile = file;
    el.fileHint.innerHTML = "";
    var strong = document.createElement("strong");
    strong.textContent = file.name;
    el.fileHint.appendChild(strong);
    el.fileHint.appendChild(
      document.createTextNode(" · " + formatBytes(file.size))
    );
    setBusy(false);
  }

  function resetAll() {
    selectedFile = null;
    lastPayload = null;
    el.fileInput.value = "";
    el.fileHint.innerHTML =
      "PDF, JPEG, PNG or WebP · up to " + formatBytes(MAX_BYTES);
    el.results.classList.remove("is-visible");
    el.cards.innerHTML = "";
    el.resultsMeta.textContent = "";
    clearAlert();
    setBusy(false);
  }

  /* ------------------------------------------------------------- rendering */

  function renderResults(payload) {
    var data = payload.data || {};
    var meta = payload.meta || {};

    el.cards.innerHTML = "";

    SECTIONS.forEach(function (section) {
      var values = data[section.id] || {};

      var card = document.createElement("div");
      card.className = "card" + (section.wide ? " card--wide" : "");

      var title = document.createElement("div");
      title.className = "card__title";
      title.textContent = section.title;
      card.appendChild(title);

      var fields = document.createElement("div");
      fields.className = "fields" + (section.wide ? " fields--four" : "");

      section.fields.forEach(function (field) {
        var raw = values[field.key];
        var empty = isBlank(raw);

        var group = document.createElement("div");
        group.className = "field";

        var label = document.createElement("div");
        label.className = "field__label";
        label.textContent = field.label;

        var value = document.createElement("div");
        value.className = "field__value" + (empty ? " is-empty" : "");
        value.textContent = empty ? "Not found in document" : raw.trim();

        group.appendChild(label);
        group.appendChild(value);
        fields.appendChild(group);
      });

      card.appendChild(fields);
      el.cards.appendChild(card);
    });

    var bits = [];
    if (meta.model) bits.push(meta.model);
    if (typeof meta.duration_ms === "number") {
      bits.push((meta.duration_ms / 1000).toFixed(1) + "s");
    }
    if (meta.request_id) bits.push("req " + meta.request_id);
    el.resultsMeta.textContent = bits.join("  ·  ");

    el.results.classList.add("is-visible");
    el.results.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  /* ------------------------------------------------------------- API calls */

  function apiHeaders() {
    var headers = {};
    var key = el.apiKeyInput.value.trim();
    if (key) headers["X-API-Key"] = key;
    return headers;
  }

  async function extract() {
    if (!selectedFile) return;

    clearAlert();
    el.results.classList.remove("is-visible");
    setBusy(true, "Extracting with Gemini - this usually takes a few seconds…");

    var body = new FormData();
    body.append("file", selectedFile);

    try {
      var response = await fetch(EXTRACT_URL, {
        method: "POST",
        headers: apiHeaders(),
        body: body,
      });

      var payload = null;
      try {
        payload = await response.json();
      } catch (_) {
        /* Non-JSON body (a proxy error page, most likely). */
      }

      if (!response.ok) {
        var error = (payload && payload.error) || {};
        var requestId =
          error.request_id || response.headers.get("X-Request-ID") || "";
        showAlert(
          error.message || "Extraction failed (HTTP " + response.status + ").",
          requestId ? "request id: " + requestId : ""
        );
        if (error.code === "unauthorized") el.settings.open = true;
        return;
      }

      lastPayload = payload;
      renderResults(payload);
    } catch (err) {
      showAlert(
        "Could not reach the extraction service. Check your connection and try again.",
        String(err && err.message ? err.message : err)
      );
    } finally {
      setBusy(false);
    }
  }

  async function checkReadiness() {
    try {
      var response = await fetch(READY_URL, { headers: { Accept: "application/json" } });
      var body = await response.json();
      if (response.ok && body.status === "ready") {
        el.badge.dataset.state = "ready";
        el.badge.textContent = body.environment === "production" ? "Live" : body.environment;
      } else {
        el.badge.dataset.state = "down";
        el.badge.textContent = "Not configured";
      }
    } catch (_) {
      el.badge.dataset.state = "down";
      el.badge.textContent = "Offline";
    }
  }

  /* --------------------------------------------------------------- wiring */

  el.dropzone.addEventListener("click", function () {
    el.fileInput.click();
  });

  el.fileInput.addEventListener("change", function () {
    selectFile(el.fileInput.files[0]);
  });

  ["dragenter", "dragover"].forEach(function (name) {
    el.dropzone.addEventListener(name, function (event) {
      event.preventDefault();
      el.dropzone.classList.add("is-dragging");
    });
  });

  ["dragleave", "dragend", "drop"].forEach(function (name) {
    el.dropzone.addEventListener(name, function () {
      el.dropzone.classList.remove("is-dragging");
    });
  });

  el.dropzone.addEventListener("drop", function (event) {
    event.preventDefault();
    if (event.dataTransfer && event.dataTransfer.files.length) {
      selectFile(event.dataTransfer.files[0]);
    }
  });

  /* Stop the browser from navigating away when a file misses the dropzone. */
  window.addEventListener("dragover", function (e) { e.preventDefault(); });
  window.addEventListener("drop", function (e) { e.preventDefault(); });

  el.extractBtn.addEventListener("click", extract);
  el.resetBtn.addEventListener("click", resetAll);

  el.copyBtn.addEventListener("click", async function () {
    if (!lastPayload) return;
    var text = JSON.stringify(lastPayload.data, null, 2);
    try {
      await navigator.clipboard.writeText(text);
      el.copyBtn.textContent = "Copied";
      setTimeout(function () { el.copyBtn.textContent = "Copy JSON"; }, 1500);
    } catch (_) {
      showAlert("Clipboard access was blocked. Use Download JSON instead.");
    }
  });

  el.downloadBtn.addEventListener("click", function () {
    if (!lastPayload) return;
    var blob = new Blob([JSON.stringify(lastPayload.data, null, 2)], {
      type: "application/json",
    });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    var base = (lastPayload.meta && lastPayload.meta.filename) || "referral";
    link.href = url;
    link.download = base.replace(/\.[^.]+$/, "") + ".json";
    link.click();
    URL.revokeObjectURL(url);
  });

  /* sessionStorage, not localStorage: the key dies with the tab. */
  el.apiKeyInput.value = sessionStorage.getItem("medico_api_key") || "";
  el.apiKeyInput.addEventListener("change", function () {
    var value = el.apiKeyInput.value.trim();
    if (value) sessionStorage.setItem("medico_api_key", value);
    else sessionStorage.removeItem("medico_api_key");
  });

  resetAll();
  checkReadiness();
})();
