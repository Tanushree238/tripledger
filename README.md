# TripLedger — Travel & Expense MVP

A responsive three-role travel and expense workflow built with **FastAPI + React + PostgreSQL**.
The MVP uses India / INR (₹), seeded flight and hotel options, a mocked card feed, and a mocked accounting export.

## Run it

```bash
docker compose up --build
```

- Web app: http://localhost:5173
- API docs: http://localhost:8000/docs
- API health: http://localhost:8000/health

The database is seeded automatically on API startup. The demo identity is selected in the app's role switcher; this is intentionally a demo-only identity mechanism, not production authentication.

## Demo roles

- **Employee** — submit travel requests, create expenses, upload receipts, edit extracted fields, view status.
- **Manager** — review direct-report travel and expense requests, approve/reject with comments.
- **Finance** — see spend and exceptions, configure policy thresholds, export CSV, run mocked accounting export, reconcile mocked card transactions.

## Included workflows

- Travel requests with seeded flight/hotel options, estimated cost, and pre-approval.
- Policy engine with role/department/project limits, receipt threshold, and soft/hard flags.
- Expense submission with receipt upload and editable OCR-style extracted fields (mock extraction).
- Conditional approval steps (manager then finance when required), comments, and audit history.
- Finance dashboard, exception list, CSV export, mocked card feed, and accounting export.
- Seeded company, employees, managers, departments, projects, policies, travel requests, and expenses.

## Notes / production hardening

This is a runnable MVP, not a production deployment. Before production, add SSO/OIDC, server-side authorization, migrations, malware scanning and private object storage for receipts, immutable audit storage, idempotent integrations, rate limiting, CSRF protection if cookie auth is used, and real accounting/card/booking providers. The demo role selector sends `X-Demo-Role` and `X-Demo-User` headers and must be replaced.

## v1.3 AI foundation

Copy `.env.example` to `.env` if custom settings are needed. Run `docker compose up --build` without deleting volumes. The AI Assistant defaults to mock mode: two read-only tasks (general expense policy guidance and scoped expense totals), with session-only messages. Free-text is passed to real providers but ignored by the mock. No AI action writes to the database. AI failure returns 503; regular workflows remain independent. `/ai/health` reports configuration, not remote liveness.

The existing X-Demo-User identity mechanism is demo-only and permits impersonation; do not expose this app publicly or use real employee data without real authentication. AI scope is derived from that identity's database role, not a caller-supplied role. Only authorized aggregates and general policy settings are supplied as context; do not send confidential text to external providers without approval.

### Provisional team contract

Internal service POST `/execute`: body `{"request":{"task":"expense_summary","query":""},"context":{"role":"employee","department":"Sales","expense_count":2,"total_amount":3310,"exception_count":1,"policies":[]},"mode":"rag"}`. Response `{"answer":"...","provider":"rag","sources":[]}`. Set AI_MODE=baseline or rag and AI_SERVICE_URL to the internal service base URL. No real model service is included. Confirm schemas, service authentication, citation IDs and supported tasks before enabling real mode. No automatic retries or silent mock fallback. No new database migration is required for this slice.

### Validation

`cd backend && python -m unittest discover -s tests` after installing requirements. Four tests passed locally (SQLite, installed dependency versions); HTTP adapter tested with mocked transport. Frontend build, PostgreSQL, Docker and remote CI are not yet validated. Frontend dependency installation was blocked by unavailable npm cache/network. Production authentication, persistent conversations, RAG ingestion and write actions are deferred.
