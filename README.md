# CollectIQ

Executable accounts-receivable demo with Cognee Cloud as the primary persistent AI memory and real Stripe **test-mode** billing. Python 3.12+, standard library only; no package installation or frontend build required.

Task 2 coordinated agent implementation, real verification results, known issues and resume commands are documented in [TASK2_REPORT.md](TASK2_REPORT.md). The final corrected three-scenario live run is still outstanding; its command approval was declined. Local regression tests pass.

The Acme core workflow is the default integration target. The original single-invoice partial-payment implementation is preserved separately in `backend/engine.py` and `python -m backend.cli demo`.

## Run

On this Windows workspace, the launcher locates the bundled Python runtime automatically:

```powershell
.\collectiq.ps1 verify
.\collectiq.ps1 core
.\collectiq.ps1 start
```

Open **http://127.0.0.1:8080**. With Python on PATH, the equivalent commands are:

```text
python -m backend.cli verify --output artifacts/connectivity.json
python -m backend.cli core --output artifacts/acme-workflow.json
python -m backend.server
```

Run the core stages separately with `core-prepare`, `core-propose`, and `core-replace`. The stable default request ID resumes the same Acme case; it does not create a new case or invoice on each invocation. An explicit different `--request-id` requests a separate demo case.

## Credentials

Configure `STRIPE_SECRET_KEY`, `COGNEE_API_KEY`, `COGNEE_BASE_URL`, and optionally `COGNEE_TENANT_ID` in the process environment or ignored local `.env`. `.env.example` contains placeholders only. Environment variables take precedence. Restart the server after changing credentials.

Hidden-input setup is available without putting credentials in shell history:

```powershell
.\collectiq.ps1 configure-cognee
.\collectiq.ps1 configure-stripe
```

The backend sends `X-Api-Key` and `X-Tenant-Id` to the configured HTTPS Cognee tenant. Credentials are never returned to the browser, copied into audit events, or committed. Live Stripe key prefixes are rejected before network access, and Stripe responses must explicitly assert `livemode=false`.

## Acme workflow

Customer message: “We dispute £200 because a deliverable was incomplete. We can pay £300 now and £500 next month.”

1. Store an explicitly synthetic contract, financial policy, acceptance/dispute record and historical promise in Acme's own Cognee dataset.
2. Create and retrieve an application-owned Stripe test customer and unpaid £1,000 GBP invoice.
3. Index the customer dataset, retrieve matching evidence hashes, obtain actual graph-based reasoning, and build a structured proposal.
4. Enforce integer pence, £200 maximum adjustment, exact £300/£500 allocation and same-day-next-calendar-month due date. The Acme policy allows up to 45 days, covering 28–31-day calendar months. The older partial-payment demo retains its separate 30-day policy.
5. Create two replacement **drafts**. Re-read and verify the original invoice's ownership, currency, exact total, zero paid amount, zero credits, no externally attached payments, and disabled automatic advancement. Re-read both drafts and verify their amounts and settlement metadata.
6. Record the safeguards in Cognee. Void only this workflow's own verified unpaid original, confirm Stripe returned `status=void`, and then finalise the £300 and £500 replacements with automatic advancement disabled.
7. Save the actual Stripe IDs, statuses, proposal and explanation to Cognee. Confirm the replacements are open/unpaid and total £800 outstanding.

Replacement creation does **not** mean payment or settlement. The core command does not charge a payment method, send email, or claim cash was collected. The £200 difference is an evidence-backed reduction reflected in the replacement total; it is not represented as a Stripe credit note in this workflow.

The original is retired before replacements are finalised, avoiding duplicate open receivables. This is a resumable saga, not a cross-service transaction: an interruption can leave verified drafts or a void original with a pending replacement finalisation. Retry the **same request ID**. An externally modified invoice or uncertain operation outside the idempotency window stops for manual reconciliation. Stripe request IDs and every failure are preserved.

## Cognee memory and isolation

`backend/memory.py` provides `store_contract`, `store_policy`, `store_promise`, `store_dispute`, `store_decision`, `retrieve_evidence`, and `index`.

Every customer has a distinct deterministic dataset and session. Search always includes that dataset; returned dataset envelopes are checked and foreign datasets are rejected. A text-only customer filter is never the isolation boundary. The supplied cloud credential can access multiple datasets, so the backend is a trusted single-user service; this is not a multi-tenant authorization service.

The tenant's real OpenAPI schema determines the text-ingestion route. This tenant exposes JSON `POST /api/v1/add_text`; graph construction uses `POST /api/v1/cognify`, and retrieval/reasoning uses `POST /api/v1/search` with the deployed camelCase contract. Schema-advertised capabilities are reported separately from successful authenticated retrieval probes. A schema listing alone does not establish that a capability works.

SQLite is an execution journal, idempotency record and delivery outbox. It is not an AI memory fallback. Financial intent must be acknowledged by Cognee before a financial write, and failed delivery remains queued. A successful add means stored; indexing is a separate operation. Audit records form a verifiable SHA-256 chain; this detects local modification but does not provide an externally anchored or signed audit ledger.

## Checks and evidence

```powershell
.\collectiq.ps1 test
.\collectiq.ps1 acceptance
.\collectiq.ps1 isolation
```

Or:

```text
python -m unittest discover -s backend/tests -v
python -m backend.live_checks --phase acceptance
python -m backend.live_checks --phase isolation
node --check frontend/app.js
```

Unit tests use explicitly labelled fixtures and make no external API calls. The separate `live_checks` module uses the configured real Cognee and Stripe APIs. Acceptance re-fetches invoice statuses, checks there are exactly three case-owned invoices, retrieves actual Stripe IDs from Cognee and repeats the workflow to prove no new financial operation is created. Isolation stores a control marker in another customer dataset, confirms it is retrievable there and absent from Acme retrieval.

Sanitized live evidence is written to ignored `artifacts/*.json`; operational state is in ignored `data/collectiq.sqlite3`. The dashboard exposes the complete case history and downloadable audit JSON. Do not delete the operational journal between retries: it contains the financial execution and idempotency history.

## Local service boundary

The server binds only `127.0.0.1`, restricts Host and Origin, requires a session token for mutations, and serves an explicit static-file allowlist. There is no public deployment, background scheduler or production collections service. Use one application process for execution. Invoice changes initiated outside CollectIQ cannot be made atomic with the workflow; external payment activity must be reconciled before replacement.

## Source map

- `backend/integrations.py`: real HTTP clients, credential guards, schema discovery and Stripe idempotency.
- `backend/memory.py`: customer-scoped persistent memory.
- `backend/core.py`: Acme settlement proposal and safe replacement-invoice workflow.
- `backend/engine.py`, `backend/policy.py`: preserved collections orchestration, partial payments and bounded negotiation.
- `backend/store.py`: durable operational journal and hash-linked audit outbox.
- `backend/server.py`, `backend/cli.py`, `backend/live_checks.py`: dashboard API, CLI and real acceptance checks.
- `frontend/`: existing interactive dashboard, evidence inspection and audit history.

References: [Cognee API documentation](https://docs.cognee.ai/api-reference/introduction), [Stripe invoicing](https://docs.stripe.com/invoicing), [Stripe partial invoice payments](https://docs.stripe.com/invoicing/partial-payments), and the authenticated tenant OpenAPI schema saved with the live verification artifacts.
