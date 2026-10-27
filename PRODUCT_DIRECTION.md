# Relay: a proposal for a sales-operations pilot

The offer: **Find overlooked sales opportunities, give each one an accountable next step, and reconcile outcomes through to collected cash.**

AI can help build every feature in this roadmap. The commercial value would come from an implemented, maintained workflow inside the buyer's business, reliable source data, agreed rules and evidence of useful outcomes. Neither a custom interface nor complex code alone establishes a durable advantage or proves willingness to pay.

## What this version now demonstrates

- A compact operational overview inspired by the supplied dashboard references: restrained colour, segmented metric bars, an inspectable cash chart, source breakdowns, stage distribution and cohort comparisons.
- Owner/source filters and UTC collection windows of 7, 30 or 90 days, or all recorded time. Current pipeline signals remain current-state checks; selecting a collection window does not hide old operational problems.
- Six server-derived review checks: unknown/blocked delivery; eligible recovery without an owner; an elapsed appointment with attendance unrecorded; attendance without a recorded settlement; a quiet follow-up; and an eligible recovery opportunity.
- Every signal includes its evidence and suggested next action. Signals do not change contact permissions, send messages or estimate lost revenue.
- Existing lead review, appointment actions and settlement recording remain the way to resolve the underlying records. Signals are recalculated on workspace refresh.
- A CSV report with the active owner/source filters, explicit collection window, current pipeline signals, and underlying transactions. Exported text is protected against spreadsheet formula execution.

## Next work, in priority order

| Priority | Capability | Why a buyer might pay | Evidence needed before implementing |
| --- | --- | --- | --- |
| 1 | Continuous CRM reconciliation | Keep ownership, conversations, bookings and opt-outs current; surface discrepancies and conflicts rather than competing with rep workflows. | Current CRM, its identifiers and fields, available event/API access, update latency, a sample export and the team's handling rules. |
| 2 | Payment-provider reconciliation | Tie actual provider settlements and refunds to the relevant lead and recovery history; distinguish money recorded in the CRM from money independently confirmed. | Provider, test account/events, identifiers for matching, refund/dispute handling and an agreed definition of collected cash. |
| 3 | Assignment and escalation rules | Give each review task an owner, due time and escalation path; prevent duplicate ownership when setters, closers and automations overlap. | Team roles, handoff process, business hours, actual response targets and escalation ownership. |
| 4 | Integration health and incident handling | Show last successful sync, stale feeds, retries, duplicate events and unresolved delivery outcomes; alert an operator with a useful recovery path. | Expected freshness, failure handling, monitoring destination and the person responsible for incidents. |
| 5 | A credible recovery experiment | Compare an agreed treatment with a suitable control over a defined collection/refund window, with exclusions and baseline differences visible. | Cohort eligibility, assignment process, sample size, normal sales cycle, observation window and a shared success criterion. |

For external event integrations, plan signature verification, deduplication by provider event ID, replay and ordering handling, auditable matching, access boundaries and a reconciliation path for unmatched records. These are design requirements for future implementation, not current capabilities.

## What to avoid selling as the differentiator

A generic email-drafting chatbot, another follow-up sequence builder, or unsupported claims that every attributed payment is additional revenue. Close and HighLevel already provide workflow automation; HighLevel also documents natural-language workflow generation.

Sources checked 21 October 2026: [Close Workflows](https://help.close.com/feature-guide/workflows), [HighLevel Workflow AI Builder](https://help.gohighlevel.com/support/solutions/articles/155000006100), [HighLevel workflow settings](https://help.gohighlevel.com/support/solutions/articles/48001239875).

## Discovery for a sales team

1. Which CRM, booking tool and payment provider are in use today?
2. Show one lead that was neglected and one that was contacted by competing processes. What should have happened?
3. What does the AI/automation department already cover, and who maintains it?
4. Which recurring operational failure costs the most staff time or prevents reliable collection reporting?
5. Can the team provide a limited export or sandbox and agree on a measurable paid pilot?

Start with a read-only audit of one agreed cohort. Validate the flags against a team member's review before enabling any new outreach. Price a focused implementation and ongoing operation against validated business value, not speculative revenue or the number of automations.

## Current limits

The persistent product serves one trusted workspace using Flask, SQLite and a separate SMTP worker. A deployed Vercel walkthrough reuses its rules with isolated, browser-held sample data. CRM connections remain manual contact lookups and payments remain manually reconciled; no live customer service or new live integration has been deployed. There is no automatic incident notification, background analytics refresh, task acknowledgement workflow, role separation or multi-workspace isolation. Demo records are fictional. Comparisons are descriptive, not causal estimates.
