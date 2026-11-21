# Member 3 — Infrastructure, Mocks & Deployment: Remaining Work
**Coder's Cup 2026 | RASTA Relief Platform**
> *Ref: UX Spec §06 Scenario 14 · Execution Plan §5 · Acceptance Tests §08, §09*

---

## What's Already Done ✅

| Item | Status |
|---|---|
| `POST /api/mock/nadra/verify` — returns verified/not found | ✅ |
| `POST /api/mock/raast/pay` — returns fake TXN | ✅ |
| `POST /api/mock/sms/send` — records simulated send | ✅ |
| `GET /api/mock/health` — health check | ✅ |
| `backend/mocks/fake_data.json` — synthetic people records | ✅ |

---

## What's Missing ❌

> [!CAUTION]
> **Deployment is non-negotiable.** The spec says explicitly: *"A deployed, functioning prototype is mandatory. Slides or video alone are insufficient."* The demo link must work from FAST-NUCES Karachi on November 23 without any local server running.

---

## 1. 🔴 LIVE DEPLOYMENT — Most Critical

**What to deploy**: The single FastAPI backend (`backend/main.py`) + React frontend (`frontend/`)

**Recommended stack** (free, fast):

```
Backend  → Railway.app  (auto-detects Python, sets PORT env var)
Frontend → Vercel.com   (auto-detects Vite/React)
Database → Already on Supabase ✅
```

### Backend deployment steps (Railway):

```bash
# 1. Add Procfile at repo root or backend/:
web: uvicorn main:app --host 0.0.0.0 --port $PORT

# 2. Add runtime.txt:
python-3.12

# 3. Set env vars in Railway dashboard:
DATABASE_URL=postgresql+psycopg://...  (from Supabase)
SUPABASE_URL=https://wpptgzhnzyfmctqmbnyy.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_KEY=...
SECRET_KEY=...
CORS_ORIGINS=https://your-vercel-app.vercel.app
```

### Frontend deployment steps (Vercel):

```bash
# In frontend/.env.production (or Vercel env vars):
VITE_API_URL=https://your-railway-app.up.railway.app
```

**Exit condition**: `curl https://your-railway-app.up.railway.app/api/mock/health` returns `{"service":"mock","status":"ok"}` from any device on any network.

---

## 2. 🔴 Mock Failure Fixtures — Judge Demo Requirement

**Spec §06 Scenario 14**: *"Admin selects a prepared mock NADRA timeout, duplicate record, or payment-account mismatch fixture → system runs normal workflow against deliberately failing mock → logs handling, retries, and final route."*

**What to build**: A fixture/mode switcher for mock services. The simplest approach is a **query param or header** that triggers a failure mode:

### Add to `mocks/routes.py`:

```python
class FailureMode(str, Enum):
    none = "none"
    timeout = "timeout"
    not_found = "not_found"
    mismatch = "mismatch"
    duplicate = "duplicate"

@router.post("/nadra/verify")
def nadra_verify(body: NadraRequest, failure_mode: FailureMode = FailureMode.none):
    if failure_mode == FailureMode.timeout:
        import time; time.sleep(30)  # triggers request timeout
        return {}
    if failure_mode == FailureMode.not_found:
        return {"verified": False, "note": "FAKE NADRA: Simulated record not found (fixture)"}
    if failure_mode == FailureMode.mismatch:
        return {
            "verified": False,
            "note": "FAKE NADRA: Name mismatch — submitted 'M. Ali', record shows 'Muhammad Ali Baig'",
            "name_on_record": "Muhammad Ali Baig"
        }
    # Normal path
    person = services.find_person(body.cnic)
    ...
```

### Add a fixture state endpoint (for Admin UI to call):

```python
# Global fixture state (in-memory for demo)
_fixture_mode = {"nadra": "none", "raast": "none", "sms": "none"}

@router.post("/fixtures/set")  # admin-only
def set_fixture(service: str, mode: str):
    _fixture_mode[service] = mode
    return {"set": True, "service": service, "mode": mode}

@router.get("/fixtures/current")
def get_fixtures():
    return _fixture_mode
```

**Demo scenario**: Admin UI → "Simulate NADRA Timeout" → citizen submits → status shows "Verification delayed" → audit log records `SERVICE_UNAVAILABLE` → case goes to human review (NOT auto-approve).

---

## 3. 🔴 Tool-Calling Agent — `/internal/agent/process-case`

**Execution Plan §5**: The agent orchestrates the full pipeline when M1 submits a case.

```
POST /internal/agent/process-case
  { "case_id": "...", "tenant_id": "..." }
```

**Agent tool sequence** (Execution Plan §5):
1. `get_case_details` — load case from DB
2. `check_consent` — verify helper consent if applicable
3. `verify_mock_identity` → call `POST /api/mock/nadra/verify`
4. `analyze_document` → call `POST /internal/ai/extract-document` (if doc uploaded)
5. `check_scam_message` → call `POST /internal/ai/scam-check` (if applicable)
6. `find_duplicate_claims` → call `POST /internal/ai/detect-duplicates`
7. `evaluate_eligibility` → call `POST /internal/ai/evaluate` with all results
8. `record_decision` → write Decision to DB via M1
9. `send_notification` → call `POST /api/mock/sms/send`

**You can implement this as**:
- A simple **sequential function** in Python (no LLM agent framework needed for hackathon)
- OR use **LangChain agent with tool-calling** for extra judging credit

**Minimum viable version** (sequential):
```python
@router.post("/internal/agent/process-case")
async def process_case(body: ProcessRequest):
    case = get_case_from_db(body.case_id)
    nadra = httpx.post("/api/mock/nadra/verify", json={"cnic": case.cnic}).json()
    ai = httpx.post("/internal/ai/evaluate", json={...}).json()
    update_case_status(body.case_id, ai["route"])
    httpx.post("/api/mock/sms/send", json={"phone": case.phone, "message": f"Status: {ai['route']}"})
    return {"status": "processed", "route": ai["route"]}
```

---

## 4. 🟡 Enhanced Mock Endpoints (Missing from Spec)

The execution plan defines more mock endpoints than currently implemented:

| Endpoint | Currently | Required |
|---|---|---|
| `GET /mock/nadra/records/{id}` | ❌ | Authorized synthetic record lookup |
| `POST /mock/raast/account-validate` | ❌ | Match mock account to beneficiary |
| `GET /mock/raast/transactions/{id}` | ❌ | Simulated transaction state lookup |
| `GET /mock/sms/messages/{id}` | ❌ | Delivery/failure status of a sent SMS |

### Add to `mocks/routes.py`:

```python
@router.get("/nadra/records/{identity_id}")
def nadra_record(identity_id: str):
    # Return synthetic full record for authorized lookup
    return {"mock_id": identity_id, "name": "...", "dob": "...", "note": "FAKE NADRA RECORD"}

@router.post("/raast/account-validate")
def raast_validate(body: AccountValidateRequest):
    # Return: account exists, name match, mock bank name
    return {"valid": True, "account": body.account, "note": "FAKE RAAST ACCOUNT"}

@router.get("/raast/transactions/{txn_id}")
def raast_txn_status(txn_id: str):
    return {"txn_id": txn_id, "status": "completed", "note": "FAKE RAAST TXN"}

@router.get("/sms/messages/{msg_id}")
def sms_status(msg_id: str):
    return {"msg_id": msg_id, "status": "delivered", "note": "FAKE SMS DELIVERY"}
```

---

## 5. 🟡 Idempotent Raast Payment

**Spec §08**: *"Repeated submissions and payment requests are idempotent."*
**Current**: Every `POST /mock/raast/pay` returns `FAKE-TXN-0001` hardcoded — no idempotency.

**Fix**: Store a `payment_account → txn_id` mapping in-memory or in DB:

```python
_raast_payments: dict[str, str] = {}  # account → txn_id

@router.post("/raast/pay")
def raast_pay(body: PayRequest):
    key = f"{body.cnic}:{body.amount}"
    if key not in _raast_payments:
        _raast_payments[key] = f"FAKE-TXN-{uuid4().hex[:8].upper()}"
    return {
        "status": "paid",
        "transaction_id": _raast_payments[key],  # same TXN on retry
        "cnic": body.cnic,
        "amount": body.amount,
        "note": "FAKE RAAST — idempotent"
    }
```

---

## 6. 🟡 Background Notification Job

**Execution Plan §5**: *"Reliable notifications/jobs, safe failures."*

**Minimum**: An APScheduler or FastAPI `BackgroundTask` that processes a notification queue:

```python
from fastapi import BackgroundTasks

@router.post("/internal/jobs/notifications")
def queue_notification(body: NotifRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(send_notification_job, body.case_id, body.message, body.phone)
    return {"queued": True}

def send_notification_job(case_id, message, phone):
    # Try SMS → if fails → log failure, do NOT raise or crash
    try:
        httpx.post(".../mock/sms/send", json={"phone": phone, "message": message})
        # update notification status to "delivered"
    except Exception as e:
        # update notification status to "failed"
        log_failure(case_id, str(e))
```

---

## 7. 🟡 `/health` and `/ready` Endpoints

**Execution Plan §5**: Liveness + readiness checks (needed for Railway/Render health check pings).

```python
@router.get("/health")
def health():
    return {"status": "ok", "service": "rasta-backend"}

@router.get("/ready")
def ready():
    # Check DB connection
    try:
        with get_session() as s:
            s.exec(select(1))
        return {"status": "ready", "db": "connected"}
    except:
        raise HTTPException(503, detail="DB not ready")
```

---

## Demo Scenario Walkthrough (What You Must Be Able to Show)

```
1. NORMAL FLOW
   Admin opens platform (deployed URL, not localhost)
   Citizen logs in → submits claim
   Agent process-case runs → NADRA verifies → AI evaluates → status updates
   Officer approves → Raast pay (idempotent) → SMS sent

2. FAILURE INJECTION (your fixture)
   Admin → sets NADRA mode to "timeout"
   New citizen submits claim
   Agent calls NADRA → times out → logs SERVICE_UNAVAILABLE
   Case status = "human_review" (NOT auto-approved)
   Judge sees: visible degraded state, not a crash

3. DUPLICATE GUARD
   Same citizen clicks submit twice
   Second request hits idempotency key → 409 or returns same case_id
   Raast pay called twice → returns same TXN_ID
```

---

## Judging Criteria Mapping

| Judging criterion | Your deliverable |
|---|---|
| *"Mock identity/payment/data services"* | NADRA ✅ Raast ✅ SMS ✅ — enhanced endpoints ❌ |
| *"Safe failures — timeout → not auto-approve"* | Fixture modes ❌ |
| *"Repeated submissions idempotent"* | Raast idempotency ❌ |
| *"Notifications/jobs"* | Background job ❌ |
| *"Live deploy — not localhost"* | 🔴 Not deployed |
| *"Service timeout → visible degraded state"* | Fixture + UI state ❌ |
| *"At least three extra platform features"* | officer queue ✅ rules ✅ low-bandwidth ✅ — notifications ❌ |

---

## Definition of Done (Execution Plan §10)

> Service mocks, adapters, agent workflow, retries, deployment, logs and controlled failures.

- [ ] Backend deployed on Railway (or equivalent) — public URL working
- [ ] Frontend deployed on Vercel — hits live backend
- [ ] `GET /ready` health check passes on deployment
- [ ] NADRA failure fixtures: `timeout`, `not_found`, `mismatch` modes
- [ ] `POST /fixtures/set` endpoint for Admin UI
- [ ] Raast idempotency (same CNIC+amount → same TXN ID)
- [ ] `POST /internal/agent/process-case` orchestrates the full pipeline
- [ ] Background notification job logs failures without crashing
- [ ] `GET /mock/raast/transactions/{id}` and `GET /mock/sms/messages/{id}`
