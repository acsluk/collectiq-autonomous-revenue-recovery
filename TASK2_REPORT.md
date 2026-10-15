# CollectIQ Task 2 implementation and verification report

Status: implemented, with final corrected live verification outstanding. Do not treat Task 2 as fully accepted yet.

## Verified results and remaining checks

The existing Task 1 workflow passed real Cognee and Stripe checks. Acme's original invoice is void; the £300 and £500 replacement invoices remain open/unpaid. This means £800 is outstanding, not cash collected.

| Scenario | Real API result recorded | Remaining check |
| --- | --- | --- |
| A: £800 negotiation | Actual Cognee calls produced a £250/£550 counteroffer and a simulated-buyer acceptance in one round. | An earlier opening buyer message rejected its own initial offer. The opening protocol is now stricter; the corrected v2 run is not verified. |
| B: broken promise | Actual Cognee recall activated 100% upfront, causing a real model-generated rejection. Saved-decision recall and evidence-citing explanation also succeeded. | Final v2 replay remains to be run. |
| C: £750 dispute | Actual contract/delivery recall and Dispute2Cash supported a £150 adjustment, leaving £600. | PromisePay returned a rounded proposed upfront amount as the minimum. Deterministic validation stopped the workflow. The minimum/schema distinction is fixed locally; a corrected real run remains outstanding. |

The command approval for the corrected three-scenario real-API rerun was declined. No alternative tool or application path was used to bypass that decision. Local checks continued.

**71 unit/regression tests pass.** Unit fixtures are explicitly labelled and are not presented as successful external integrations. The new-case Stripe execution gate is implemented and tested for refusal without explicit authority; its opt-in financial execution has not been exercised for Task 2.

## Agent architecture

`AgentRunner` coordinates one persisted workflow:

`RECEIVED → INVESTIGATING → NEGOTIATING → VALIDATING → EXECUTING → COMPLETED`

`BLOCKED`, `REQUIRES_REVIEW`, and `FAILED` preserve errors and audit records. In DRY_RUN, EXECUTING means persisting the decision, not moving money.

- The **Orchestrator** uses actual Cognee reasoning and validated structured output to select a classification, specialist, action, evidence, uncertainty and financial risk. Six requested classifications are supported; routing does not use a keyword classifier.
- **Dispute2Cash** retrieves customer-scoped contract and delivery documents. Its proposed adjustment must equal the independently calculated undelivered line value and satisfy the policy cap. Missing or conflicting evidence stops for review.
- **PromisePay** recalls payment history and policy. The normal 30% minimum on £800 is £240. A broken promise activates the seeded stricter 100% rule. The initial offer, minimum acceptable upfront, preferred rounded counteroffer and maximum buyer authority are separate values.
- **Agent2Agent** makes actual model calls for separately instructed Seller and simulated Buyer roles, each with its own persistent session. Offers, counteroffers, acceptances, rejections and raw responses are saved. Three rounds is a hard limit.

The buyer is a simulated treasury representative for predefined synthetic customers. Its acceptance is not authorization from any real customer.

## Reasoning API and model actually reported

Reasoning uses authenticated `POST /api/v1/search` with `GRAPH_COMPLETION`. Each role receives a separate system instruction, customer dataset, role-specific session and JSON output contract. There is no fabricated completion or unavailable-endpoint fallback.

Cognee's real `GET /api/v1/sessions/cost-by-model?range=24h` returned HTTP 200 and reports the model alias **`litellm_proxy/litellm`**. Completion responses do not disclose the upstream model's identity. A specific upstream model name cannot be verified from these responses and is not claimed.

## Cognee persistence and evidence

Each customer has a separate deterministic dataset; role sessions are also separated. Retrieval is scoped by dataset, not by a natural-language customer filter. Returned dataset envelopes are validated.

Seeded synthetic contracts, policies, history, preferences and delivery evidence are stored through the real tenant's `add_text` endpoint, processed with `cognify`, and retrieved with `CHUNKS`. Each expected reference and content hash must appear in actual retrieval results before facts can influence a decision.

Saved records include customer, request, source references, complete conversation, proposed terms, policy validation, decision and explanation. Stripe identifiers are empty for DRY_RUN scenarios rather than invented. The explanation function retrieves the exact saved decision and content hash before generating an evidence-citing explanation.

SQLite holds execution state, reasoning-call replay records and the hash-linked delivery outbox. Cognee remains the primary persistent AI memory and retrieval system. Rejected model responses and recovered errors remain in the audit trail; they are not edited into apparent successes.

## Actual sample transcript

The following is from Scenario B's actual model responses, with financial integers in pence:

- **Simulated Buyer — OFFER:** £200 on 15 October 2026 and £600 on 15 November 2026. “Offer matches buyer authority (initial upfront 20,000 p, total 80,000 p) and customer preference for two instalments with the balance due next month.”
- **Seller — REJECT:** “Policy requires upfront >= full balance (80000 p) due to broken promise; buyer max upfront 25000 p is insufficient, so offer must be rejected.”

Its saved-decision explanation, retrieved from Cognee, cites `POLICY-B-001`, `HISTORY-B-001` and `PROMISE-B-PREVIOUS`. Under normal policy a £250/£550 plan passes; with the retrieved broken promise the required upfront becomes £800 and the same plan fails.

## Stripe actions and protected Acme state

Task 2 demonstrations performed **zero Stripe financial writes**. They use explicitly labelled synthetic invoice inputs with `stripe_invoice_id=null`; they never present those as Stripe responses.

The Task 1 invoice IDs preserved in the protected baseline are:

| Invoice | Role | Last verified state |
| --- | --- | --- |
| `in_1UQu83D8sEfWKTMaDWfdrmit` | £1,000 original | void |
| `in_1UQuBJD8sEfWKTMaU3vmcRla` | £300 replacement | open, unpaid |
| `in_1UQuBRD8sEfWKTMaJx1CzewP` | £500 replacement | open, unpaid |

The Task 2 runner has no automatic billing call. New test financial execution is a separate opt-in command requiring `--authorise-new-test-case`, an accepted and independently validated plan, a synthetic-customer allowlist and a new execution case. It cannot accept Acme's customer identifier. It reuses the working test-only HTTP client, durable idempotency and decision-before-write audit machinery.

The opt-in path creates its own new original and replacement drafts, verifies ownership, amount, collection settings and zero payments, retires only its own original and finalises the replacements. It does not collect payments. This optional path remains unverified against real APIs in Task 2; do not infer success from its unit refusal tests.

## Dashboard

The existing layout and navigation are retained. Agent workspace displays backend scenario states, selected strategy, actual seller/buyer messages, retrieved references, policy results, proposed settlement and execution status. The saved-decision explanation performs actual Cognee retrieval. Missing conversations and unsuccessful workflow states remain visible.

The browser was checked against real backend records. The initial runtime validation issues were discovered while inspecting the real dialogue and are disclosed above. The corrected protocol requires a new live run.

## Files created or changed for Task 2

- `backend/agents.py`: coordinated reasoning, retrieval, negotiation, persistence, replay and explanation.
- `backend/agent_policy.py`: typed financial/protocol validation and synthetic scenario definitions.
- `backend/agent_execution.py`: separately gated new-case Stripe test execution.
- `backend/agent_cli.py`: real scenario runner, explanation, model information and acceptance commands.
- `backend/tests/test_agents.py`: routing, financial, history, protocol, replay and failure tests.
- `backend/tests/test_core.py`: additional refusal test for externally voided originals.
- `backend/integrations.py`, `backend/memory.py`: role instructions and session-aware real reasoning calls.
- `backend/store.py`, `backend/engine.py`: persisted agent workflows and customer-scoped audit delivery.
- `backend/server.py`: agent run/explanation API and actual workflow state.
- `frontend/app.js`, `frontend/styles.css`: existing dashboard connected to actual agent results.
- `collectiq.ps1`, `README.md`, `TASK2_REPORT.md`: launch commands and documentation.

Credentials remain in ignored local configuration and were not committed or printed by application tooling. No Git commit was created.

## Run and resume verification

```powershell
.\collectiq.ps1 start
.\collectiq.ps1 test
.\collectiq.ps1 agents -Scenario all
.\collectiq.ps1 verify-agents
```

Open `http://127.0.0.1:8080/#agents`. Restart a running backend after Python source changes. Existing saved outcomes remain inspectable without rerunning financial operations.

With Python on PATH:

```text
python -m backend.agent_cli run --scenario all --output artifacts/task2-scenarios-v2.json
python -m backend.agent_cli verify --output artifacts/task2-acceptance.json
python -m backend.agent_cli why --workflow-id <completed-workflow-id> --output artifacts/task2-explanation.json
python -m backend.agent_cli model-info --output artifacts/task2-model-info.json
```

The corrected defaults use stable `task2-v2-*` request IDs. Replaying a completed workflow returns its persisted result; it does not issue duplicate bills. Prior v1 evidence remains available for inspection. Do not delete `data/collectiq.sqlite3` between retries.

The next acceptance step is the corrected real Cognee run, followed by `verify` to re-read Acme and check all three outcomes, round limits and replay behavior. No further Stripe financial execution is required to verify the DRY_RUN demonstration.
