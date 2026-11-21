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
