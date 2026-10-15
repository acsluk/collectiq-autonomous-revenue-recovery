# CollectIQ — Autonomous Revenue Recovery

**Track:** Track 2 — Agents That Collect  
**Side prize:** Best Use of Cognee Memory

**Tagline:** AI agents that investigate invoices, negotiate settlements and autonomously execute policy-approved billing through Stripe.

## Submission description

CollectIQ is an accounts receivable platform that coordinates specialist AI capabilities to recover legitimate revenue while preserving customer relationships. Its orchestrator selects a collection strategy; Dispute2Cash investigates contract and delivery evidence; PromisePay applies payment history and company repayment policy; and separately instructed seller and simulated buyer roles negotiate within explicit financial authority.

Cognee Cloud is the persistent intelligence layer. Customer-specific datasets hold contracts, policies, disputes, previous promises and decision records. Real retrieval returns evidence references and content hashes before those facts can influence a decision. A broken payment promise changes the applicable upfront requirement and therefore changes the negotiation outcome. Saved decisions can be recalled and explained with source references.

Financial execution uses genuine Stripe test-mode APIs. Deterministic code validates integer-pence amounts, supported adjustments, repayment schedules, customer ownership and invoice state before a write. Stable idempotency keys and a durable execution journal prevent duplicate billing. Models propose terms; they cannot bypass financial policy.

## What we actually verified

The Acme demonstration created a real £1,000 test invoice, retrieved supporting Cognee evidence, validated a £200 incomplete-deliverable reduction, and safely replaced the original with £300 and £500 unpaid test invoices. The original is void. Re-running that workflow created zero additional financial operations. Cognee retrieved the actual Stripe invoice IDs, and a live cross-customer isolation check passed.

Task 2 uses real Cognee model calls and defaults to DRY_RUN. Scenario A generated a £250/£550 agreement; Scenario B rejected an arrangement because recalled broken-promise history activated a stricter policy. Scenario C retrieved evidence supporting a £150 reduction on £750 but was stopped by validation when the model confused the minimum upfront with a rounded counteroffer. Corrections are implemented; the final corrected three-scenario live rerun is not verified. We do not claim all agent scenarios pass.

The replacements are **open and unpaid**. We demonstrate billing execution, not completed payment collection. New agent scenarios have made no Stripe financial writes.

## Why Cognee matters

Cognee is not a decorative chat log: retrieved customer contracts establish adjustment eligibility, retrieved policies bound instalments, and retrieved promise history changes a financial decision. Each customer has a separate dataset and role-specific reasoning sessions. Actual source references, retrieval receipts, decisions and explanations are visible in the audit history.

Reasoning uses Cognee's verified GRAPH_COMPLETION endpoint. Its usage API reports `litellm_proxy/litellm`; the upstream model identity is not disclosed.

## Technology

Python 3.12 standard-library backend, SQLite operational journal, buildless HTML/CSS/JavaScript interface, Cognee Cloud memory/reasoning, and Stripe test-mode invoicing. No production financial credentials are accepted. No package installation or frontend build is required.

## Links to supply in the form

- Public GitHub repository: use the verified publication URL from the final handoff; do not invent a URL.
- Demo video: record the two-minute plan in `DEMO_PLAN.md`, upload it, and paste the actual accessible link.
- Local demo: `http://127.0.0.1:8080/#collections` (local address, not a publicly accessible deployment).

## Limitations to disclose

- Synthetic hackathon customers, contracts and delivery evidence; genuine external API execution.
- Buyer representative is simulated and cannot authorise real customer payments.
- Agent scenarios default to DRY_RUN; no payment collection is claimed.
- Final corrected Task 2 live verification remains outstanding.
- Acme's stored verified dates are 15 October and **15 November 2026**, corresponding to the original next-calendar-month request. Do not call this exactly 30 days or alter the verified invoices for the video.

## Immediate submission checklist

1. Confirm the public repository opens without authentication.
2. Record/upload the two-minute demo and copy its real URL.
3. Paste the description above into the official submission form, choose Track 2 and the Cognee side prize if offered.
4. Supply the team/contact details requested by the actual form.
5. Submit before 21:00 Europe/London and save the confirmation.
