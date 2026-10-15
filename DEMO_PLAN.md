# Two-minute submission demo

Use existing saved records. Do not rerun billing, void invoices, create invoices, or wait for optional agent scenarios during the recording.

| Time | Screen / action | Narration |
| --- | --- | --- |
| 0:00–0:15 | Overview: £800 outstanding, £200 approved adjustment, £0 collected | “CollectIQ is autonomous revenue recovery: agents investigate unpaid invoices, negotiate terms and execute policy-approved Stripe billing.” |
| 0:15–0:30 | Collections → Acme; show the customer message and structured proposal | “Acme disputed £200 of a £1,000 invoice because a contracted deliverable was incomplete, and requested two instalments.” |
| 0:30–0:50 | Inspect proposal/evidence; show actual Cognee retrieval references and HTTP receipts | “Dispute2Cash retrieves the contract and acceptance evidence from Cognee. Deterministic policy permits the £200 adjustment and validates £300 plus £500.” |
| 0:50–1:10 | Show all three actual invoice IDs/statuses in Collections or Stripe test dashboard | “Stripe confirms the original is void and the £300 and £500 replacements are open and unpaid. These are real test API objects. The stored second due date is 15 November, next calendar month.” |
| 1:10–1:25 | Show saved idempotency evidence and decision history | “A replay created zero new financial operations. Every decision and Stripe request is audited, and customer memories are isolated.” |
| 1:25–1:45 | Agent workspace → Scenario B saved result; show actual buyer offer, seller rejection, policy/history references | “PromisePay remembers a broken promise. The normal minimum is £240, but this customer's stricter policy requires £800 upfront. The simulated buyer has £250 authority, so the seller rejects. Memory changes the decision.” |
| 1:45–2:00 | Return to overview / repository README | “The orchestrator routes specialists, Cognee grounds decisions, and hard financial rules guard Stripe. Current agent demos are DRY_RUN; incomplete scenarios are labelled honestly.” |

Fallback: use the verified Acme invoice table, `artifacts/live-acceptance.json`, `artifacts/live-isolation.json`, and saved Scenario B transcript if a live cloud query is slow. Say explicitly that you are showing recorded actual API evidence.

Do not claim a payment was received. Do not claim Scenario C's corrected end-to-end negotiation is verified. The original invoice was verified as open/unpaid; do not claim it was actually overdue merely because the pitch scenario says overdue.

Suggested video title: **CollectIQ — Autonomous Revenue Recovery | Briefcase × Stripe Hackathon**
