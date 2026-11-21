# Deploying the prototype (Railway backend + Vercel frontend)

Owner: Member 3. Goal: a public link that works on judging day with no local server.
Everything here was checked locally: the real `backend/main.py` + my routes boots with the
Railway start command, `/ready` is green, and `python -m pytest tests -q` passes (104 tests).
I cannot deploy for you: it needs your Railway and Vercel accounts.

---

## 0. The only code change needed in shared files (get the team's OK)

`backend/main.py` is shared, so I did not edit it. Add **two lines** after the existing
`include_router` calls:

```python
from app.integrations.mount import mount_m3
mount_m3(app)
```

That mounts all of Member 3's routes (mocks, fixture switches, agent, jobs, `/health`,
`/ready`) and the job worker. Without it a deployment shows only the starter routes.
Do not give the app a `lifespan=` argument (it would silently disable the worker startup).

## 1. Backend on Railway

Files already in the repo root: `Dockerfile`, `railway.json`, `.dockerignore`, `Procfile`,
`runtime.txt`. Railway uses the Dockerfile (the Procfile is only a fallback).

1. Railway -> New Project -> Deploy from GitHub repo -> pick the repo and branch.
2. Variables (Settings -> Variables):

| Variable | Value |
|---|---|
| `DATABASE_URL` | Supabase connection string, **must start with `postgresql://`** (or `postgresql+psycopg2://`). **Not** `postgresql+psycopg://`: that driver is not installed and the app would crash on start. Supabase usually needs `?sslmode=require` at the end. |
| `PORT` | `8000` (fixed, so the next two can point at it) |
| `MOCK_BASE_URL` | `http://127.0.0.1:8000` (the adapters call the mocks inside the same container) |
| `AI_BASE_URL` | `http://127.0.0.1:8000` (Member 2's routes live in the same app) |
| `INTERNAL_SERVICE_KEY`, `NADRA_MOCK_KEY`, `RAAST_MOCK_KEY`, `SMS_MOCK_KEY` | four different random strings: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `JWT_SECRET` | random string (already used by `shared/config.py`) |
| `CORS_ORIGINS` | your Vercel URL (needs Member 1 to read this variable in `main.py`) |
| `RUN_JOB_WORKER` | `true` (on exactly one instance: keep Railway replicas at 1) |
| `M3_AUTO_SETUP` | `true` (creates missing M3 tables and loads the fictional demo data at start; harmless to leave on, never wipes anything) |
| `AI_STUB` | `true` until Member 2's `/internal/ai/*` routes exist, then remove it |
| `AGENT_MODE` | `deterministic` |

   Never put these in the frontend or in git.
3. Settings -> Networking -> Generate Domain.
4. **Exit check** (from any phone/network):
```
curl https://YOUR-APP.up.railway.app/api/mock/health   ->  {"service":"mock","status":"ok"}
curl https://YOUR-APP.up.railway.app/ready              ->  {"status":"ready","checks":{"database":"ok","worker":"ok"}}
```
5. After `/ready` works, change `healthcheckPath` in `railway.json` from `/` to `/ready`.

If Member 1's Alembic migration already created the tables, that is fine: `M3_AUTO_SETUP`
only creates what is missing. To run it by hand instead:
`cd backend && python -m app.integrations.create_tables && python -m app.integrations.mocks.fixtures`
(add `--reset` only to wipe the mock data, including mock payments).

## 2. Frontend on Vercel (Member 4 owns this)

- Import the repo, **Root Directory = `frontend`**, framework Vite.
- Environment variable `VITE_API_URL=https://YOUR-APP.up.railway.app`.
- Put the final Vercel URL into the backend's `CORS_ORIGINS`.
- Only if Member 4 agrees, add `frontend/vercel.json` so refreshing a page does not 404:
```json
{ "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }] }
```

## 3. The three judge scenarios, and what makes each work

1. **Normal flow.** Citizen submits -> `process_case` job -> agent: consent, NADRA, AI, rules
   -> `cleared` (use `MOCK-123456` with a document). Officer approves -> `disburse_case` job
   -> one Raast transaction -> SMS job.
2. **Failure injection (spec scenario 14).** Admin sets a switch
   (`PUT /api/v1/admin/mock-conditions`, e.g. `{"nadra_timeout": true}`; others:
   `nadra_outage`, `identity_mismatch`, `duplicated_response`, `malformed_response`,
   `raast_outage`, `sms_failure`, `latency_ms`). A new case then ends in `human_review` with
   flag `service_unavailable` after ~13 s, never `cleared`. Every attempt, retry and the final
   route are in the run's steps and the audit log. **Payment-account mismatch:** approve a
   case for `MOCK-200006` (account `MOCK-ACCOUNT-006` is held by "A. Siddiqi Traders"):
   payment is blocked, audited, and the case returns to an officer.
3. **Duplicate guard.** Submitting twice enqueues one job (needs `submission_count` on the
   case, see FOR_MEMBER_1), and approving twice creates one payment: same `Idempotency-Key`
   gives the same `txnRef`; a different amount under that key is refused (409).

## 4. If something is wrong

| Symptom | Likely cause |
|---|---|
| Crash at start, `No module named 'psycopg'` | `DATABASE_URL` starts with `postgresql+psycopg://`; use `postgresql://` |
| `/ready` says `worker: no heartbeat yet` | `RUN_JOB_WORKER` not `true`, or `mount_m3(app)` missing in `main.py` |
| `/ready` says `database: error` | wrong `DATABASE_URL`, or Supabase needs `?sslmode=require` |
| Browser CORS error | Vercel URL missing from `CORS_ORIGINS` (or `main.py` still has the hard-coded list) |
| Cases never leave `submitted` | nobody calls `app.jobs.queue.start_case_processing(case_id)` on submit (Member 1) |
| Everything goes to `human_review` with `service_unavailable` | `AI_STUB` off but Member 2's routes are not mounted, or `AI_BASE_URL` is wrong |
| Logs | one JSON line per provider attempt (`provider_call`), per agent step (`agent_step`), per AI call (`ai_call`); failed jobs log `job FAILED` |
