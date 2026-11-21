# For Member 1 (Auth, Cases, Consent, Rules, Audit, Main API)

From Member 3. My part (mock services, adapters, agent, job queue) is built and tested
(90 tests, `python -m pytest tests -q` from the repo root). It runs today on **in-memory
stubs** for your functions. Nothing below needs you to change my code: you add things on
your side, tell me where they live, and I switch the bridge over.

You are the person who unblocks the most, so this list is the longest. Do it in order.

---

## 1. Mount my routers in `backend/main.py`  (5 minutes)

`main.py` is shared, so I did not touch it. **Shortest way, two lines** (mounts everything below
and runs the optional `M3_AUTO_SETUP=true` bootstrap that creates missing tables and demo data):

```python
from app.integrations.mount import mount_m3
mount_m3(app)
```

Or, equivalently, one by one:

```python
from app.integrations.mocks.router import (
    router as m3_mock_router,                # /mock/nadra|raast|sms/*
    internal_router as m3_mock_control_router,  # /internal/mock-control
    admin_router as m3_mock_admin_router,    # /api/v1/admin/mock-conditions
)
from app.agent.router import router as m3_agent_router   # /internal/agent/*
from app.jobs.router import router as m3_jobs_router     # /internal/jobs, /api/v1/admin/jobs, /health, /ready

app.include_router(m3_mock_router)
app.include_router(m3_mock_control_router)
app.include_router(m3_mock_admin_router)
app.include_router(m3_agent_router)
app.include_router(m3_jobs_router)
```

- Do **not** give the app a `lifespan=` argument. My job worker starts from my router's
  startup hook, and Starlette ignores that hook when a lifespan exists. (If you need a
  lifespan, call `app.jobs.worker.start()` / `stop()` from it instead.)
- `/health` and `/ready` now exist (in my jobs router). Do not add root-level duplicates.
- Replace the hard-coded CORS list with the `CORS_ORIGINS` env var (comma separated), so
  the Vercel domain can be added without a code change.
- Hazard: your folder `backend/platform/` shadows Python's built-in `platform` module
  whenever `backend/` is first on `sys.path` (running scripts from `backend/`). Run
  scripts from the repo root, or rename the folder if you can.

## 2. Add my 9 tables to your next Alembic migration

I wrote **no** migration. Make sure Alembic's `env.py` imports these so autogenerate sees them:

| Table(s) | Model list to import |
|---|---|
| `mock_identity_records`, `mock_accounts`, `mock_transactions`, `mock_sms_messages`, `mock_fixture_state` | `app.integrations.mocks.models.MOCK_MODELS` |
| `payment_requests` | `app.integrations.providers.models.PROVIDER_MODELS` |
| `agent_runs` (+ a **partial unique index** `WHERE status = 'running'`) | `app.agent.models.AGENT_MODELS` |
| `jobs`, `worker_heartbeat` | `app.jobs.models.JOB_MODELS` |

All use `shared.db.Base`. The partial index is declared in the model (`postgresql_where`),
so autogenerate should emit it. Check the migration contains
`CREATE UNIQUE INDEX uq_agent_runs_one_running ON agent_runs (case_id) WHERE status = 'running'`.

After migrating, seed the fictional demo data (from the repo root, with `backend` importable):

```
cd backend && python -m app.integrations.mocks.fixtures --reset
```

## 3. Expose these functions (the "bridge")

My code calls them through `backend/app/agent/platform_bridge.py`. It looks for them in
module `rasta_platform.services` (the name `main.py` gives your package). **Tell me the real
module path if it differs**, or just put them there. Names and signatures must match:

| Function | Returns / notes |
|---|---|
| `get_case(case_id)` | dict. Fields I read: `id`, `status` (**lowercase** contract name), `citizen_id`, `helper_id` (optional), `mock_identity_id`, `applicant_name`, `dob`, `monthly_income`, `documents` (`[{id, type, quality?}]`), `message` (optional text for the scam check), `citizen_phone`, `account_id`, `approved_amount` or `amount`, `submission_count`. Raise if the case does not exist. |
| `check_consent(citizen_id, grantee_id, scope)` | `bool`, or `{"granted": bool, "reason": "CONSENT_REQUIRED" or "CONSENT_REVOKED"}`. The agent asks for grantee `relief-processing`, scope `case_processing` (change in `agent/consent_config.py`, or env `PROCESSING_DEPARTMENT_ID` / `PROCESSING_CONSENT_SCOPE`), and again for the case's `helper_id`. |
| `get_active_rules()` | `{"version": "...", "rules": [{"id", "field", "op", "value"}]}`; `op` is one of `lte lt gte gt eq ne in present`. Optionally `"payout_amount"`. |
| `evaluate_rules(case, rules)` | optional (I have a built-in version): `{eligible, rule_version, failed_rules[], missing_fields[]}` |
| `record_decision(case_id, decision)` | `decision` keys: `route, confidence, risk_score, rule_version, model_version, reason, user_explanation, flags, missing_evidence, code, auditor_trace, decided_by, run_id`. Store `auditor_trace` as JSON. |
| `transition_case(case_id, to_status, actor, note)` | The agent uses actor `"agent"` and moves `submitted -> processing -> cleared / needs_proof / human_review`. The `note` for `human_review` is the officer notes packet (plain text): show it to officers. |
| `log_audit(actor_type, actor_id, action, resource, metadata)` | I write actor types `agent` and `system`. |
| `create_notification(case_id, recipient, message)` | **return the notification id** |
| `update_notification_state(notification_id, state, message_id=None)` | NEW. States: `created, sent, delivered, resent, failed`. |
| a real **admin-role dependency** | I use a fail-closed stub (`platform_bridge.require_admin`, needs the internal key). Give me the real FastAPI dependency; it must return a dict with at least `id`. |

When these exist, tell me and I run `platform_bridge.reset_resolution()`-style wiring and
re-run my tests against them. Until then everything runs on stubs.

## 4. Call my helpers from your routes

```python
from app.jobs.queue import start_case_processing, enqueue_disbursement, enqueue_notification

start_case_processing(case_id)   # at the end of POST /cases/{id}/submit (after the commit)
enqueue_disbursement(case_id)    # when an officer approves (after status "approved" is committed)
enqueue_notification(case_id, recipient, message)   # any other citizen message
```

- Use the **jobs** version of `start_case_processing`, not the one in `app/agent/router.py`
  (that one runs in-process and is only for local tests).
- Disbursement is safe to call twice: one job per case ever, and the payment adapter only
  pays a case whose status is exactly `approved`. `cleared` has **no** financial authority.
- Add `submission_count` to cases (increment on each submit). It makes double-submit dedupe exact.

## 5. Your side of the contract that does not match yet

- `shared/schemas.py` defines `CaseState` as `SUBMITTED, NEEDS_INFO, IN_REVIEW, APPROVED,
  REJECTED, PAID`. The **team contract** (and my code) uses
  `draft, submitted, processing, cleared, needs_proof, human_review, approved, rejected, closed`.
  Please align your `transition_case` and the DB values to the contract.
- Errors from your API should use the standard shape
  `{"error": {"code", "message", "retryable"}, "request_id"}` with the agreed codes.

## 6. Environment variables (add to `.env.example`, Railway and local `.env`)

`DATABASE_URL`, `INTERNAL_SERVICE_KEY`, `NADRA_MOCK_KEY`, `RAAST_MOCK_KEY`, `SMS_MOCK_KEY`,
`MOCK_BASE_URL` (same host as the app, e.g. `http://localhost:8000`), `AI_BASE_URL`,
`AI_STUB` (`true` until Member 2's service is ready), `CORS_ORIGINS`, `RUN_JOB_WORKER`,
`AGENT_MODE=deterministic`, optional `LLM_API_KEY`, `SENTRY_DSN`.
Run the job worker on **exactly one** process: `RUN_JOB_WORKER=true` there, unset elsewhere.
Never send any `*_MOCK_KEY` or `INTERNAL_SERVICE_KEY` to the browser.

## Optional

Call `get_payment_provider().validate_account(account_id, name)` (from
`app.integrations.providers.registry`) when a citizen enters an account, to warn on a
name mismatch. The agent does not use it.

## Done when

- [ ] Routers mounted, app starts, `GET /ready` is 200
- [ ] Migration applied with all 9 tables and the partial index, demo data seeded
- [ ] The bridge functions above exist and I have their module path
- [ ] Submit -> a `process_case` job appears -> case ends in `cleared`, `needs_proof` or `human_review`
- [ ] Approve -> exactly one mock transaction, even if you click twice
- [ ] Case states match the contract
