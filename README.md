<div align="center">
  <img src="static/brand/logo.png" alt="Dileep Adari" width="72" />

  # Medico Extractor

  **Turn a medical referral - a clean PDF or a smudged fax - into structured JSON in a few seconds.**

  [![CI](https://github.com/Dileepadari/Medico_Extractor/actions/workflows/ci.yml/badge.svg)](https://github.com/Dileepadari/Medico_Extractor/actions/workflows/ci.yml)
  [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
  [![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](https://www.python.org/)
</div>

---

Referral intake is copy-and-paste work: someone opens a fax, finds the patient's
name, hunts for the member ID, squints at the referring provider's phone number,
and retypes all of it into another system. Medico Extractor does that first pass.
Drop in a document, get back the fields - and the ones it genuinely cannot find
come back empty rather than invented.

Developers: setup, architecture and deployment live in **[DEVDOC.md](./DEVDOC.md)**.

## What it does

- **Reads scans, not just text PDFs.** Faxes, phone photos and native PDFs all go
  through the same path - the document is passed to Gemini's multimodal model
  directly, so there is no OCR step to misread a crooked page.
- **Returns a fixed shape, every time.** The response is validated against a typed
  schema before it leaves the server. No free-text parsing on your side.
- **Never guesses.** A field that isn't in the document comes back as `""`. An
  empty string is information; a plausible-looking wrong phone number is a bug.
- **Keeps nothing.** Uploads live in memory for the length of the request. Nothing
  is written to disk, and no document content or extracted value is ever logged.
- **Comes with a UI.** A drag-and-drop page is served at `/` - no build step, no
  separate frontend to deploy.

## What it extracts

| Section | Fields |
|---|---|
| Patient demographics | name, date of birth, phone, email |
| Primary insurance | member ID, group ID, insurance name, plan name |
| Secondary insurance | member ID, group ID |
| Referral source | provider name, clinic name, title, phone |
| Referral received date | date |

## Try it

Point a browser at your deployment (or `http://localhost:8000` when running
locally), drop in a referral, and press **Extract data**. Results appear as a
card per section, with **Copy JSON** and **Download JSON** for whatever comes
next in your workflow.

Accepted files: **PDF, JPEG, PNG, WebP**, up to **10 MB** by default.

## Use it from your own code

```bash
curl -X POST https://your-deployment/api/v1/extract \
  -F "file=@referral.pdf"
```

If the deployment is protected by an API key, add `-H "X-API-Key: <key>"`.

```json
{
  "data": {
    "patient_demographics": {
      "name": "Jane R. Doe",
      "dob": "01/15/1980",
      "phone": "(555) 019-8342",
      "email": ""
    },
    "primary_insurance": {
      "member_id": "ABC123456789",
      "group_id": "GRP987",
      "insurance_name": "Blue Cross Blue Shield",
      "plan_name": "PPO Choice Plus"
    },
    "secondary_insurance": { "member_id": "", "group_id": "" },
    "referral_source": {
      "provider_name": "Dr. Alan Smith",
      "clinic_name": "City General Hospital",
      "title": "MD",
      "phone": "555-1000"
    },
    "referral_received_date": { "date": "10/24/2023" }
  },
  "meta": {
    "request_id": "0f9a1c2e4b7d4a1e",
    "filename": "referral.pdf",
    "content_type": "application/pdf",
    "size_bytes": 84213,
    "model": "gemini-2.5-flash",
    "duration_ms": 3412
  }
}
```

`meta.request_id` is also returned as the `X-Request-ID` header, and it is the
one thing to quote when reporting a problem - it ties your request to the server
logs without exposing anything about the document.

### When something goes wrong

Errors always come back in the same envelope, so you can branch on `code`:

```json
{
  "error": {
    "code": "file_too_large",
    "message": "File exceeds the 10 MiB limit.",
    "request_id": "0f9a1c2e4b7d4a1e"
  }
}
```

| Status | `code` | What happened |
|---|---|---|
| 400 | `empty_file` | The upload contained no bytes. |
| 401 | `unauthorized` | The deployment requires an API key and none matched. |
| 413 | `file_too_large` | Over the configured size limit. |
| 415 | `unsupported_media_type` | Not a PDF or a supported image - checked against the file's actual bytes, not its name. |
| 422 | `validation_error` / `corrupt_document` | No `file` field, or a file that isn't readable as a document. |
| 429 | `rate_limited` | Over the per-client request budget; a `Retry-After` header says when to try again. |
| 502 | `model_error` | The extraction model failed after retries. |
| 503 | `model_not_configured` | The deployment has no model credentials. |
| 504 | `model_timeout` | The model didn't answer in time - usually a very large or very high-resolution scan. |

Interactive API docs are at `/docs` on any non-production deployment.

## Run it locally

You need Python 3.11+ and a [Google Gemini API key](https://aistudio.google.com/apikey).

```bash
git clone https://github.com/Dileepadari/Medico_Extractor.git
cd Medico_Extractor
make setup                      # virtualenv + dependencies + .env
echo 'GOOGLE_API_KEY=your-key' >> .env
make dev                        # http://localhost:8000
```

No system packages, no Tesseract, no Poppler - the model reads the document itself.

Prefer Docker?

```bash
cp .env.example .env            # then fill in GOOGLE_API_KEY
docker compose up --build
```

## A note on patient data

This service handles protected health information. It is built to hold documents
only in memory, to keep PHI out of logs entirely, and to send `no-store` on every
response - but **the deployment around it is what makes it compliant**. Before
putting real patient data through it, read the
[Handling patient data](./DEVDOC.md#handling-patient-data) section of the
developer guide: it covers the API key, CORS, TLS, and the business associate
agreement you need with your model provider.

## License

MIT - see [LICENSE](./LICENSE).
