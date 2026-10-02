# Relay — Revenue Recovery

**An interactive sales operations prototype that turns neglected leads into a traceable recovery workflow — from reviewed follow-up to booking, attendance and collected cash.**

Relay gives sales teams a clear view of missed follow-up opportunities and the steps required to measure recovery outcomes. It demonstrates context-aware outreach review, lead exclusions, rep ownership, payment attribution and refund reconciliation in one compact workspace.

![Relay dashboard](preview.jpg)

## Features

- **Recovery queue:** search and filter fictional leads by lifecycle stage; inspect source, rep ownership, conversation context and contact permission.
- **Reviewed follow-ups:** editable SMS and email templates, with an explicit approval step.
- **Interactive lead journey:** simulate an interested reply, a booked demo, attendance and a settled payment.
- **Cash ledger:** trace sample payments to leads and reconcile gross collections, refunds and net collections.
- **Protected leads:** exclude opt-outs, active customers, active rep conversations and contacts without verified permission.
- **Recovery calculator:** explore how cohort size, additional booking rate, attendance, conversion and collected cash affect an illustrative outcome.
- **Presentation mode:** hide the navigation for a focused product walkthrough.
- **Browser persistence and CSV export:** retain sample actions locally and export clearly labelled fictional data.
- **Integration blueprint:** outline how Close CRM, HighLevel and payment events could support a real pilot.

## Demo scope

All names, activity and payment amounts are fictional. Relay is a front-end prototype: it does not connect to a CRM, generate messages with live AI, send outreach or process payments. Sample net collections are attributed amounts, not proof of incremental revenue or profit.

## Run locally

Open `index.html` in a modern browser. It includes its own styles, code and sample data, and needs no installation or internet connection. Browser storage retains sample actions where supported; use “Reset sample workspace” to start again.

Alternatively, serve the repository using Python:

```bash
python3 -m http.server 8765 --bind 127.0.0.1
```

Then open `http://127.0.0.1:8765` in your browser. This address is local to your computer. The repository can also be deployed to a static hosting service; it has no build step or third-party runtime dependencies.

## Technology

Built with vanilla JavaScript, CSS and semantic HTML. The single `index.html` includes the interface, sample data, workflow rules and calculations. Native browser APIs provide dialogs, local storage and CSV downloads.

| File | Purpose |
| --- | --- |
| `index.html` | Complete runnable demo |
| `preview.jpg` | Dashboard preview |
| `README.md` | Product overview, setup and walkthrough |

## A 60-second walkthrough

1. Start on Overview and explain that this is a concept using sample data.
2. Click “Walk through a recovery” to open Priya's neglected lead.
3. Review the conversation context. Switch between SMS and Email and edit the template.
4. Click “Approve demo follow-up,” then simulate the interested reply and demo attendance.
5. Simulate a $10,000 settled payment. Close the lead and open Cash ledger to show the matched collection.
6. Reopen Priya and simulate a refund to demonstrate the difference between gross and net collections.
7. Open Recovery queue, filter to Excluded, and show why an opted-out lead cannot enter outreach.
8. Use Playbook to change the illustrative recovery assumptions. Connections explains the planned integrations.

“Present” hides the sidebar for a cleaner screen recording. Turn it off to navigate between sections. The CSV export contains clearly labelled fictional leads and amounts.

## What a real pilot still needs

- Confirm the offer, CRM, pipeline stages, permissions and lead ownership rules.
- Review native CRM features and the AI department's existing work before building custom integrations.
- Add authenticated integrations, duplicate protection, scheduling, cancellation handling, human handoffs and an audit trail.
- Establish a control group and the collection/refund measurement window. Attributed collections alone do not prove incremental revenue.
- Account for refunds, commissions, financing costs and fulfilment costs before calculating profit.

## Verification

The recovery journey, refund reconciliation, search/status filtering and browser persistence were exercised in the local browser preview. Model checks cover blocked leads, invalid transitions, duplicate settlement protection, invalid payment/refund amounts and totals. The scenario calculator was checked against the $36,000 default calculation and a changed cohort size. The CSV action was exercised, but the in-app browser's download-completion check timed out, so file download completion is unverified in that browser.
