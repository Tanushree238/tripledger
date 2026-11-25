# TripLedger — Travel & Expense MVP

A responsive three-role travel and expense workflow built with **FastAPI + React + PostgreSQL**.
The MVP uses India / INR (₹), seeded flight and hotel options, a mocked card feed, and a mocked accounting export.

## Run it

```bash
docker compose up --build
```

- Web app: http://localhost:5173
- API docs: http://localhost:8080/docs
- API health: http://localhost:8080/health

The database is seeded automatically on API startup. The demo identity is selected in the app's role switcher; this is intentionally a demo-only identity mechanism, not production authentication.

## Demo roles

- **Employee** — submit travel requests, create expenses, upload receipts, edit extracted fields, view status.
- **Manager** — review direct-report travel and expense requests, approve/reject with comments.
- **Finance** — see spend and exceptions, configure policy thresholds, export CSV, run mocked accounting export, reconcile mocked card transactions.

## Included workflows

- Travel requests with seeded flight/hotel options, estimated cost, and pre-approval.
- Policy engine with role/department/project limits, receipt threshold, and soft/hard flags.
- Expense submission with receipt upload and editable fields filled by local text extraction and OCR.
- Conditional approval steps (manager then finance when required), comments, and audit history.
- Finance dashboard, exception list, CSV export, mocked card feed, and accounting export.
- Seeded company, employees, managers, departments, projects, policies, travel requests, and expenses.

## Notes / production hardening

This is a runnable MVP, not a production deployment. Before production, add SSO/OIDC, server-side authorization, migrations, malware scanning and private object storage for receipts, immutable audit storage, idempotent integrations, rate limiting, CSRF protection if cookie auth is used, and real accounting/card/booking providers. The demo role selector sends `X-Demo-Role` and `X-Demo-User` headers and must be replaced.

## v1.3 AI foundation

### Policy Assistant search

Start the indexed `TE-Policy-Agent` on port 8001. If TripLedger runs in
Docker Desktop and the agent runs on the host, start the agent with
`python -m uvicorn app.main:app --host 0.0.0.0 --port 8001` so the container
can reach it. Compose defaults to `http://host.docker.internal:8001`.
When running TripLedger directly on the host, start its API on port 8080.
It defaults to `http://127.0.0.1:8001` for the agent. Override either default
with `POLICY_AGENT_URL` when needed.

In the Policy Assistant, try “What is the hotel limit for an L3 employee in
Mumbai in January?” The browser sends the question to TripLedger's
`POST /ai/policy-search` endpoint. TripLedger requests policy excerpts from
the agent and displays them with their references.

If the question mentions one distinct grade such as `L3`, TripLedger
passes that grade as a search filter. Broad questions and questions
comparing multiple grades search across grade bands.

For the demo, run `docker compose logs -f api` in a second terminal.
Each successful agent response appears on one `policy_search` line with
the trace ID, grade filter, elapsed time, and full evidence JSON.

### Receipt provider evaluation

Local extraction remains the default. To opt in to Azure Document Intelligence and send receipt files to its prebuilt receipt model, set `RECEIPT_EXTRACTION_MODE=azure` and configure `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` and `AZURE_DOCUMENT_INTELLIGENCE_KEY` in the local `.env`. Recreate the API container to apply the settings. Keep credentials out of version control.

Use `RECEIPT_EXTRACTION_MODE=azure-invoice` to process formal invoices with Azure's prebuilt invoice model. The benchmark also accepts `azure-invoice` as a provider argument. Both Azure modes suggest categories from extracted text using TripLedger's rules. A no-document response triggers local OCR. A multiple-document response asks for one document at a time.

The Azure pilot fills fields only when they meet initial confidence thresholds (0.85 for merchant and date, 0.90 for total). It requires an explicit INR currency code before filling the amount. Calibrate these thresholds on labeled receipts before using the provider as the default.

From the backend directory, run `python benchmark_receipts.py local /path/to/expected-extraction.json` and `python benchmark_receipts.py azure /path/to/expected-extraction.json` against the same anonymized set. The Azure command sends the listed receipts to the configured endpoint and requires the Azure variables in the process environment. Each manifest entry contains `file`, `merchant`, `date` (ISO), `currency`, and `total`. The benchmark compares merchant, date, and the amount that would be filled into the INR form. It counts wrong values, blanks, and extraction errors separately.

New receipts are processed inside the API container by Poppler and English Tesseract. Receipt preview reads PDF text from the first two pages and falls back to OCR on those pages if the text yields no usable fields. PNG and JPEG uploads use OCR directly. Rebuild the API image after changing extraction dependencies. Set `RECEIPT_EXTRACTION_MODE=mock` to preview only the bundled demo receipts. The preview leaves ambiguous values for manual entry and fills an amount only when it detects INR or Indian GST invoice markers and an unambiguous total.

Copy `.env.example` to `.env` if custom settings are needed. Run `docker compose up --build` without deleting volumes. The AI Assistant defaults to mock mode: two read-only tasks (general expense policy guidance and scoped expense totals), with session-only messages. Free-text is passed to real providers but ignored by the mock. No AI action writes to the database. AI failure returns 503; regular workflows remain independent. `/ai/health` reports configuration, not remote liveness.

The existing X-Demo-User identity mechanism is demo-only and permits impersonation; do not expose this app publicly or use real employee data without real authentication. AI scope is derived from that identity's database role, not a caller-supplied role. Only authorized aggregates and general policy settings are supplied as context; do not send confidential text to external providers without approval.

### Provisional team contract

Internal service POST `/execute`: body `{"request":{"task":"expense_summary","query":""},"context":{"role":"employee","department":"Sales","expense_count":2,"total_amount":3310,"exception_count":1,"policies":[]},"mode":"rag"}`. Response `{"answer":"...","provider":"rag","sources":[]}`. Set AI_MODE=baseline or rag and AI_SERVICE_URL to the internal service base URL. No real model service is included. Confirm schemas, service authentication, citation IDs and supported tasks before enabling real mode. No automatic retries or silent mock fallback. No new database migration is required for this slice.

### Validation

`cd backend && python -m unittest discover -s tests` after installing requirements. Four tests passed locally (SQLite, installed dependency versions); HTTP adapter tested with mocked transport. Frontend build, PostgreSQL, Docker and remote CI are not yet validated. Frontend dependency installation was blocked by unavailable npm cache/network. Production authentication, persistent conversations, RAG ingestion and write actions are deferred.
