# Relay — Revenue Recovery

**A sales recovery workspace for finding pipeline gaps and following outcomes through to collected cash.**

Relay helps operators spot neglected leads, review the next follow-up, manage appointments, and reconcile settlements and refunds. Its dashboard connects each signal to the underlying lead and transaction history. A Flask API, SQLite database, and separate delivery worker power the persistent product; an isolated Vercel walkthrough makes the workflow easy to try.

[Product walkthrough](#two-minute-walkthrough) · [Screenshots](#screenshots) · [Run locally](#persistent-local-workspace) · [Architecture](#architecture)

![Relay recovery workspace](preview.jpg)

*Recovery overview with owner/source filters, recorded net collections, current pipeline stages and evidence-linked review signals. All names and amounts shown are fictional sample data.*

## Product capabilities

- **Operational overview:** owner/source filters, collection windows, an inspectable net-cash chart, source breakdowns and current stage distribution, all computed from saved records.
- **Explainable leak detector:** server-derived checks for delivery exceptions, missing recovery ownership, unrecorded attendance, attendance without a settlement, quiet follow-ups and eligible recovery opportunities. Flags link to the original lead and never grant outreach permission or assert lost revenue.
- **Operations report:** CSV export of filtered pipeline signals and collection-window transactions, with spreadsheet formula protection.
- **Server-side sign-in:** hashed passwords, expiring database sessions, HttpOnly cookies, CSRF protection and login attempt limits.
- **Lead management:** create/edit, search/filter, atomic CSV import, and spreadsheet-safe CSV export.
- **Reviewed recovery:** editable contextual email templates, permission evidence, ownership, human approval and scheduling.
- **Protection rules:** opt-outs, customers, active conversations, control leads, recent touches and missing permission evidence block recovery.
- **Durable delivery:** a separate worker rechecks protections and uses STARTTLS SMTP in live mode. Ambiguous delivery is never automatically retried.
- **Appointments:** booking, attendance, no-shows, cancellations, rescheduling and reviewed reminders. Changes cancel queued reminders; send-time checks verify the appointment snapshot.
- **Cash reconciliation:** integer cents, unique provider references, multiple settlements, linked refunds and enforced refund limits.
- **Pilot cohorts:** approximately 80/20 random assignment, fixed cohorts, unique booked leads, net collections and net collections per lead.
- **Audit history:** operators, timestamps, protection edits, approvals, delivery outcomes, appointments, settlements and refunds.
- **CRM contact lookup:** credential-gated Close and HighLevel import by contact ID. HighLevel includes location checks and a DND recheck before live sends. Imported contacts start without outreach permission.
- **Separate demo workspace:** fictional data and simulated delivery using the same database and scheduling rules.

## Screenshots

### Pipeline leak detector

Six explainable checks turn recorded pipeline gaps into a review queue. Operators can inspect the evidence and open the original lead before taking action.

![Relay pipeline leak detector with rule filters, evidence and suggested next steps](docs/images/leak-detector.jpg)

<details>
<summary>Mobile workspace</summary>
<br>
<img src="docs/images/mobile-workspace.jpg" alt="Relay recovery overview on a phone, with responsive navigation, metrics and collection charts" width="320">
</details>

These images show the deployed sample walkthrough. Collections are fictional, delivery is simulated, and edits belong to the visitor's browser.

## Run the demo

### Shareable Vercel walkthrough

[Open the hosted preview](https://relay-recovery-preview-5h65c1hvb-jr-3f25.vercel.app/). Deployment Protection is enabled; visitors need a current share link from the owner. Expiring access tokens are kept out of this repository. See [deployment notes](DEPLOYMENT.md).

The Vercel entrypoint `app.py` serves an isolated interactive walkthrough through
`relay/preview.py`. It reuses the product's Flask routes and business rules inside
a fresh temporary database for each operation. Only business records are returned
to the visitor's browser; users, sessions and credentials are never serialized.
Sample edits are stored in browser local storage and can be reset. No shared
customer database, live CRM import, email delivery or actual payment processing
is enabled. Use fictional data only.

The Vercel deployment source is an explicit allowlist: the preview entrypoint,
Python modules, static assets, requirements and Python version. Local databases,
environment files, Git metadata and prototype files are excluded. The persistent
single-workspace product below continues to use `wsgi.py` / `manage.py`.

### Persistent local workspace

Requires **Python 3.12+**. Node is only needed for the optional JavaScript syntax check.

```bash
git clone https://github.com/JuniorAJ1/relay-revenue-recovery.git
cd relay-revenue-recovery
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py serve
```

Open **http://127.0.0.1:8766/** and choose **Open demo workspace**. A database is seeded with 25 fictional leads and sample transactions. Changes survive refreshes and server restarts.

Demo mode is the default. It cannot import real CRM data or send messages. Its convenient demo login is available to anyone who can reach that demo instance; keep it local and keep real data in a separate live workspace.

Use **Delivery desk → Run demo worker** to process due demo jobs, or run a worker in another terminal:

```bash
source .venv/bin/activate
python manage.py worker
```

The worker polls every five seconds and processes up to 20 jobs per cycle. `python manage.py worker --once` runs one cycle.

## Two-minute walkthrough

1. Explore the overview: filter by owner or source, change the collection window, and select a chart date to inspect its transactions.
2. Open the leak detector and choose a signal to inspect its evidence and suggested next step.
3. Review an eligible lead's context and permission evidence. Generate a template, edit it, and approve a send time in your local timezone.
4. Inspect the delivery desk and run the demo worker for due jobs. Delivery is explicitly marked **simulated**.
5. Record a booked reply. Queued recovery emails are cancelled. Approve a reminder, then reschedule to see the old reminder cancelled.
6. Record attendance, a settlement with a unique reference, and a partial refund. Inspect the cash ledger and audit trail.
7. Refresh to confirm persistence. In the hosted walkthrough, use **Reset workspace** to restore the fictional starting records.

## Live pilot setup

This version serves **one trusted sales workspace**. Authenticated operators share records and permissions; there is no public signup or customer isolation.

Copy `.env.example` to `.env` and set:

```dotenv
DEMO_MODE=false
DATABASE_PATH=instance/live.sqlite3
SECRET_KEY=<random secret of at least 32 characters>
COOKIE_SECURE=true
APP_BASE_URL=https://your-relay-domain.example
LIVE_SEND_ENABLED=false
```

Use a fresh database: the app refuses to mix demo and live modes. Generate a secret using `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Never commit `.env` or databases.

Create operator accounts with interactive passwords:

```bash
python manage.py create-user --email you@example.com --name "Your name"
```

Run Gunicorn behind an HTTPS reverse proxy, and supervise a separate worker:

```bash
gunicorn --bind 127.0.0.1:8000 --workers 2 --timeout 60 wsgi:app
python manage.py worker
```

Configure `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_FROM`, and SMTP credentials. Test delivery and the public unsubscribe page before enabling `LIVE_SEND_ENABLED=true`. The worker appends a signed unsubscribe link; confirmation saves the recipient's preference and cancels queued emails.

Configure `CLOSE_API_KEY` or `HIGHLEVEL_TOKEN` plus `HIGHLEVEL_LOCATION_ID` for contact lookup. HighLevel uses `Version: v3`. Credentials stay on the server and are not returned to the browser or committed.

Imported contacts require a human to review CRM history, opt-outs, owner, customer status and permission evidence. Close lookup does not continuously synchronize unsubscribes or stages. Absence of a local opt-out does not establish permission. HighLevel delivery is blocked if its DND evidence is unavailable or changed.

### Delivery states

| State | Meaning |
| --- | --- |
| Queued | Approved and waiting for its due time |
| Simulated | Demo processed; nothing sent |
| Sent | SMTP accepted the message; inbox delivery is not confirmed |
| Blocked | Disabled/unconfigured delivery, rejection or changed protections; review a new job after resolving |
| Cancelled | Lead/appointment changed or an operator cancelled |
| Unknown | Timeout/interruption may have occurred after acceptance; reconcile provider records before another send |

There is no automatic retry for unknown outcomes. Use the delivery desk’s Reconcile action after checking SMTP records; evidence is required. Confirmed acceptance preserves the send, while a confirmed failure permits a new human-reviewed job. Queued reminders are cancelled on appointment changes; an email already in progress cannot be recalled. Writes serialize during the worker's send-time check and SMTP handoff. SQLite and one worker suit a small pilot, not a large multi-tenant service.

`Dockerfile` and `compose.yaml` package separate web/worker services with a shared named database volume. Copy `.env.example` to `.env` before `docker compose up --build`. The web port binds to loopback; HTTPS and a public domain require your reverse proxy. Docker packaging was not runtime-tested in the development environment.

Back up SQLite with its backup API and verify restores. Keep session records, databases and secrets outside Git. Changing `SECRET_KEY` invalidates unsubscribe links. Password reset and operator-removal screens are not included.

## CSV import

Required: `name,email`. Optional: `source,owner,phone,context,last_touch,consent,consent_note,opted_out,customer,active,cohort`.

Use ISO timestamps with timezone, booleans `true/false` or `1/0`, and cohorts `treatment/control`. Missing consent defaults to false; missing last touch defaults to now; a missing cohort is randomly assigned. Batches support up to 1,000 rows and 2 MB. Duplicate or invalid rows roll back the entire batch.

```csv
name,email,owner,last_touch,consent,consent_note,cohort
Example Lead,lead@example.com,Alex,2026-09-01T10:00:00+00:00,false,,treatment
```

This example imports a protected contact. Verify permission in the app before outreach.

## Architecture

```text
Browser → Flask API → SQLite (sessions, leads, jobs, appointments, payments, events)
                          ↑
                   Separate worker → SMTP
                   Contact lookup → Close / HighLevel
```

| Location | Responsibility |
| --- | --- |
| relay/app.py | HTTP API, authentication, exports and unsubscribe |
| relay/insights.py | Read-only pipeline rules and evidence for review signals |
| relay/service.py | Lead, appointment, scheduling and financial rules |
| relay/db.py | Schema, transactions and startup migration |
| relay/worker.py | Durable claiming, send-time checks and SMTP |
| relay/connectors.py | Read-only CRM contact adapters |
| relay/seed.py | Fictional demo data |
| app.py / relay/preview.py | Vercel entrypoint and isolated browser-held sample walkthrough |
| static/ | Separate frontend HTML, CSS and JavaScript |
| docs/images/ / preview.jpg | Screenshots of the deployed sample workspace |
| tests/ | API, ledger, scheduling, worker and adapter tests |
| prototype/ | Original standalone concept retained for reference |

## Verification

```bash
python -m unittest discover -s tests -v
node --check static/app.js
node --check static/dashboard.js
```

The 43 automated tests cover authentication/CSRF, login limits, mode separation, protected leads, atomic import, export injection protection, persistence, concurrent claiming, unsubscribe, SMTP TLS/message construction, unknown delivery, stale reminders, duplicate transactions and refund bounds, plus read-only insight rules, recent-send handling, flag resolution through appointment/payment APIs, isolated preview state, forbidden integration routes, snapshot validation, preview exports, and the full simulated preview workflow. SMTP and CRM adapters use mocks; real credentials were not available for live verification.

Browser verification covered approval, booking, reminder cancellation on reschedule, attendance, settlement, refund, and persistence after a server restart. The dashboard update was also checked at desktop and phone widths: owner/source filtering, an empty filter combination, collection windows, chart-to-transaction inspection, filtered queue navigation, leak-to-lead review, CSV download and every existing route. Browser warnings/errors were empty during the final pass. Pinned Python dependencies were checked with `pip-audit`; no known vulnerabilities were reported at the final scan. GitHub Actions runs the suite and JavaScript syntax check.

## Current boundaries

See [Product direction](PRODUCT_DIRECTION.md) for the proposed CRM reconciliation, payment evidence and operational ownership roadmap. The dashboard is a point-in-time snapshot: refresh to recalculate. Collection charts use UTC dates and show attributed net cash; current pipeline checks and cohort comparisons explicitly use all recorded time. No new live integration is implied by the overview.

Drafting uses **contextual templates, not an AI model**. SMS, OAuth onboarding, continuous CRM sync, automatic replies, calendar-provider sync, payment webhooks, multi-currency accounting, role-based access and multiple-workspace isolation are not implemented. Reply-based opt-outs require operator handling; the signed unsubscribe link updates the app automatically.

Transactions are **manually reconciled**; Relay neither processes payments nor independently confirms settlement. Cohort comparisons are descriptive and demo figures are fictional. Agree on selection, collection/refund windows and provider reconciliation before assessing incremental revenue.

API references: [Close authentication](https://developer.close.com/api/overview/api-key-authentication), [Close contact lookup](https://developer.close.com/api/resources/contacts/get), [HighLevel contact lookup](https://marketplace.gohighlevel.com/docs/ghl/contacts/get-contact/index.html).
