# Member 1 — Platform & Backend Lead: Remaining Work
**Coder's Cup 2026 | RASTA Relief Platform**
> *Ref: UX Spec §01, §09, §10 · Execution Plan §3, §7 · Acceptance Tests §08*

---

## What's Already Done ✅

| Item | Status |
|---|---|
| 39 REST endpoints under `/api/v1` | ✅ |
| Supabase Auth integration (JWT login/me) | ✅ |
| All 12 SQLAlchemy models + Alembic migration applied | ✅ |
| 5 demo accounts seeded + profiles linked | ✅ |
| RBAC: role-gated routes (citizen/helper/officer/admin/auditor) | ✅ |
| Case lifecycle: create → submit → assign → review → close | ✅ |
| Consent grant + withdraw endpoints | ✅ |
| Rules versioning: PATCH `/rules/{id}` creates new version | ✅ |
| Audit log write on every action | ✅ |
| Metrics summary endpoint | ✅ |
| Scam check endpoint (`POST /scam-checks`) | ✅ |
| Document upload endpoint (`POST /cases/{id}/documents`) | ✅ |
| pytest: 5/5 passing | ✅ |

---

## What's Missing ❌ — Judging Impact

### 🔴 P0 — Non-Negotiable (judges will test these live via API)

#### 1. Consent enforcement at request time
**Spec**: *"Consent withdrawal actually denies future protected access, including direct API requests."*
**Current**: The `POST /consents/{id}/withdraw` stores `revoked_at` in DB. But no route actually **checks** consent before serving case data to a helper.

**What to add** in `platform/routes.py` / `platform/services.py`:

```python
# In any helper-scoped GET /cases or GET /cases/{id}:
def _check_helper_consent(helper_user_id, citizen_id, session):
    consent = session.exec(
        select(Consent).where(
            Consent.grantee_id == helper_user_id,
            Consent.citizen_id == citizen_id,
            Consent.revoked_at == None  # noqa
        )
    ).first()
    if not consent:
        raise HTTPException(403, detail={
            "error": {"code": "CONSENT_REVOKED", "message": "Access not permitted", "retryable": False}
        })
```

**Demo scenario**: Citizen revokes → judge calls `GET /api/v1/cases` with helper token → must get `403 CONSENT_REVOKED`, not `200`.

---

#### 2. Rule version written to every Decision record
**Spec**: *"A changed rule takes effect without a code change, while older decisions preserve their original rule version."*
**Current**: The `Decision` model has `rule_version` field. The `/cases/{id}/submit` endpoint triggers processing — but the AI stub doesn't write a decision record with `rule_version`.

**What to add**: When platform receives AI evaluation result (or while AI is a stub, write it yourself):

```python
# In services.py after case submission / AI callback:
active_rule = session.exec(select(Rule).where(Rule.is_active == True)).first()
decision = Decision(
    case_id=case.id,
    route="human_review",          # from AI
    confidence=0.65,               # from AI
    rule_version=active_rule.version if active_rule else 1,
    model_version="prototype-1",
    reason="Stub decision pending AI integration",
)
session.add(decision)
```

This ensures the **auditor trace** (`GET /cases/{id}/decision-trace`) returns `rule_version` and `model_version` — a specific judge checkpoint.

---

#### 3. `GET /cases/{id}/decision-trace` endpoint
**Spec**: *"Auditor sees inputs, versions, confidence, outcome and authorized actions."*
**Execution Plan §3**: `GET /cases/{id}/decision-trace` — Evidence and model/rule versions

**Current**: This endpoint is missing (not in `routes.py`).

**Add to `routes.py`**:
```python
@router.get("/cases/{case_id}/decision-trace")
def decision_trace(case_id: str, current_user=Depends(require_roles(["auditor","admin"]))):
    # Return: case status, all Decision records for this case,
    # each with rule_version, model_version, confidence, route, reason, timestamp
    # + all History entries for this case
    # + all AuditLog entries where resource contains case_id
```

---

#### 4. `GET /users` and `PATCH /users/{id}/role` (Admin user management)
**Execution Plan §3**: Admin-scoped user list + role edit.
**Current**: Missing from routes.

**Add**:
```python
@router.get("/users")  # admin only
@router.patch("/users/{user_id}/role")  # admin only: body = {"role": "officer"}
```

---

### 🟡 P1 — Judging Strength

#### 5. `GET /rules/{id}/history` — Historical rule versions
**Spec**: *"Previous values visible. Old decisions retain previous version."*
**Current**: `rules` table has `version` int. But no endpoint returns historical rule versions.

**Add**: Query all `Rule` rows for a given `rule_name` ordered by `version` desc — return as list.

---

#### 6. `POST /rules/evaluate` — Dry-run rule evaluation
**Execution Plan §3**: Evaluate a case input against the current rule without committing.
**What it does**: Takes `{monthly_income, nadra_verified, confidence}` → returns whether case would clear, need proof, or go to human review under the **currently active rule**.

This powers the **Admin "digital twin" preview** (bonus but high-scoring).

---

#### 7. Standard error codes on all routes
**Execution Plan §7**: Error shape `{"error": {"code": "CONSENT_REVOKED", ...}}`.
**Current**: Most errors return FastAPI default `{"detail": "..."}`.

Codes to implement:
- `CONSENT_REQUIRED` — no active consent found
- `CONSENT_REVOKED` — consent revoked
- `FORBIDDEN` — wrong role
- `MISSING_EVIDENCE` — case needs documents before submit
- `IDENTITY_MISMATCH` — name doesn't match NADRA record
- `DUPLICATE_CLAIM` — same CNIC + active case exists
- `SERVICE_UNAVAILABLE` — mock provider timeout
- `RULE_VERSION_CONFLICT` — concurrent rule edit collision

---

#### 8. Idempotency guard on `POST /cases/{id}/review` (Officer approve)
**Spec**: *"Repeated submissions and payment requests are idempotent."*
**Current**: An officer can POST to `/cases/{id}/review` twice and generate two decisions.

**Fix**: Check if case is already in `approved`/`rejected` state before processing:
```python
if case.status in ("approved", "rejected", "closed"):
    raise HTTPException(409, detail={"error": {"code": "VALIDATION_ERROR", "message": f"Case already {case.status}"}})
```

---

#### 9. `GET /cases/{id}/history` — Case transition history
**Execution Plan §3**: Case history transitions.
**Current**: The `History` model exists but no GET endpoint exposes it to frontend.

---

## Workflow to Implement

```
POST /cases/{id}/submit
  → check consent (if helper submitted)
  → trigger AI evaluation (call /internal/ai/evaluate via httpx)
  → store Decision record with rule_version + model_version
  → update case status (processing → cleared/needs_proof/human_review)
  → write audit log entry
  → trigger notification (call M3 agent)
```

The platform owns the **orchestration call** — it calls AI and mocks, they don't call themselves.

---

## Judging Criteria Mapping

| Judging criterion | Your endpoint / behavior |
|---|---|
| *"Secure login and RBAC"* | ✅ Done |
| *"Case status/history"* | ✅ create/submit/review ✅ — history GET ❌ |
| *"Consent: withdrawal blocks access"* | Backend revoke ✅ — enforcement on reads ❌ |
| *"Audit: immutable, role-restricted"* | ✅ Done |
| *"Rule versioning: new rule, preserved old version"* | Rule table ✅ — decision_trace shows it ❌ |
| *"REST API + Swagger docs"* | ✅ Swagger at `/docs` |
| *"Repeated submissions idempotent"* | Cases ✅ — officer review ❌ |
| *"Each decision = citizen explanation + audit trace"* | Decision model ✅ — trace endpoint ❌ |

---

## Definition of Done (from Execution Plan §10)

> Main API, migrations, role enforcement, case lifecycle, consent, versioned rules, audit, tests.

Your checklist:
- [ ] Consent check blocks helper reads after revocation
- [ ] Decision record written with `rule_version` + `model_version` on every evaluation
- [ ] `GET /cases/{id}/decision-trace` returns full trace
- [ ] `GET /cases/{id}/history` returns state transitions
- [ ] `GET /users` + `PATCH /users/{id}/role` working
- [ ] Officer review idempotent (409 on double-approve)
- [ ] Standard error codes on main failure paths
- [ ] At least 2 more pytest tests covering consent revocation + rule versioning
