# OWNER: Member 3
# Deterministic case-processing pipeline. Sequence (team contract):
#   get_case_details -> check_consent -> verify_mock_identity -> match name -> analyze_document
#   -> check_scam_message (if a message) -> find_duplicate_claims -> evaluate_eligibility
#   -> evaluate_route (M2) -> record_decision -> needs_proof | human_review | cleared -> notify
# "cleared" means automated checks passed and carries NO financial authority.
# Every step is stored in agent_runs.steps and audited with actor_type="agent".
import asyncio
import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from shared import db as shared_db
from ai.decision import explain as explain_result

from . import notes, platform_bridge, tools
from .consent_config import PROCESSING_DEPARTMENT_ID, PROCESSING_SCOPE
from .models import AgentRun

logger = logging.getLogger("m3.agent.orchestrator")

RUN_TIMEOUT = 60.0
AGENT_ACTOR_ID = "case-processing-agent"

# Flags that force human_review no matter what the AI service says (safety rules 1 and 2).
CRITICAL_FLAGS = ("identity_mismatch", "identity_not_found", "duplicate_claim", "scam_suspected",
                  "service_unavailable", "duplicate_check_incomplete", "document_pdf_review")
BAD_STATUSES = ("unavailable", "malformed")
# These have a fallback (template text) or happen after the decision, so a failure
# is logged but does not count as "a check could not run".
NON_CRITICAL_STEPS = ("explain", "send_notification")


def agent_mode() -> str:
    mode = os.getenv("AGENT_MODE", "deterministic").strip().lower()
    if mode == "llm":
        # TODO: LLM-driven mode is not built; the deterministic pipeline is always what runs.
        logger.warning("AGENT_MODE=llm is not implemented yet; running deterministic")
    return "deterministic"


# ---------------------------------------------------------------------------
# agent_runs persistence (sync; called through asyncio.to_thread)
# ---------------------------------------------------------------------------
@contextmanager
def _session():
    session = shared_db.SessionLocal()  # looked up at call time
    try:
        yield session
    finally:
        session.close()


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _snapshot(r: AgentRun) -> Dict[str, Any]:
    return {"id": r.id, "case_id": r.case_id, "status": r.status, "mode": r.mode,
            "steps": list(r.steps or []), "started_at": _iso(r.started_at),
            "finished_at": _iso(r.finished_at), "error": r.error, "triggered_by": r.triggered_by}


def _running_run(s, case_id: str) -> Optional[AgentRun]:
    return s.execute(select(AgentRun).where(AgentRun.case_id == case_id, AgentRun.status == "running")).scalar_one_or_none()


def create_or_get_run(case_id: str, triggered_by: str = "system") -> Tuple[Dict[str, Any], bool]:
    """Returns (run, created). If a run for this case is already running, returns
    that run and created=False (guard against double processing). The database also
    enforces it with a partial unique index."""
    with _session() as s:
        existing = _running_run(s, case_id)
        if existing is not None:
            started = existing.started_at if existing.started_at.tzinfo else existing.started_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - started < timedelta(seconds=RUN_TIMEOUT + 30):
                return _snapshot(existing), False
            # a run that outlived its timeout means the process died: free the case
            existing.status, existing.error = "failed", "run abandoned (no finish recorded)"
            existing.finished_at = datetime.now(timezone.utc)
            s.commit()
        run = AgentRun(case_id=case_id, status="running", mode=agent_mode(), steps=[], triggered_by=triggered_by)
        s.add(run)
        try:
            s.commit()
        except IntegrityError:  # lost a race with a concurrent start
            s.rollback()
            winner = _running_run(s, case_id)
            if winner is None:
                raise
            return _snapshot(winner), False
        return _snapshot(run), True


def load_run(run_id: str) -> Optional[Dict[str, Any]]:
    with _session() as s:
        r = s.get(AgentRun, run_id)
        return _snapshot(r) if r else None


def _save_steps(run_id: str, steps: List[Dict[str, Any]]) -> None:
    with _session() as s:
        r = s.get(AgentRun, run_id)
        r.steps = list(steps)  # new list so the JSON change is detected
        s.commit()


def _finish_run(run_id: str, status: str, error: Optional[str]) -> Dict[str, Any]:
    with _session() as s:
        r = s.get(AgentRun, run_id)
        r.status, r.error, r.finished_at = status, error, datetime.now(timezone.utc)
        s.commit()
        return _snapshot(r)


# ---------------------------------------------------------------------------
@dataclass
class Ctx:
    run_id: str
    case_id: str
    generation: Optional[int] = None
    case: Dict[str, Any] = field(default_factory=dict)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    results: Dict[str, Any] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    requested_documents: List[str] = field(default_factory=list)
    overrides: List[str] = field(default_factory=list)
    trace_extra: Dict[str, Any] = field(default_factory=dict)
    ai_down: bool = False
    final_status: Optional[str] = None
    error: Optional[str] = None

    def flag(self, name: str) -> None:
        if name not in self.flags:
            self.flags.append(name)


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


async def _audit(ctx: Ctx, action: str, metadata: Dict[str, Any]) -> None:
    try:
        await asyncio.to_thread(platform_bridge.log_audit, "agent", AGENT_ACTOR_ID, action,
                                f"case:{ctx.case_id}", {"run_id": ctx.run_id, **metadata})
    except Exception:  # auditing must not stop the run
        logger.exception("audit failed for %s", action)


async def _record(ctx: Ctx, name: str, status: str, output: Dict[str, Any], started: float, started_at: str) -> None:
    stored = {k: v for k, v in output.items() if k != "case"}  # keep the whole case out of the trace
    ctx.steps.append({"step": name, "status": status, "started_at": started_at,
                      "duration_ms": int((time.perf_counter() - started) * 1000), "output": _jsonable(stored)})
    level = logging.WARNING if status in BAD_STATUSES else logging.INFO
    logger.log(level, "agent_step %s", json.dumps({"run_id": ctx.run_id, "case_id": ctx.case_id,
                                                   "step": name, "status": status}))
    await asyncio.to_thread(_save_steps, ctx.run_id, ctx.steps)
    await _audit(ctx, f"agent_step.{name}", {"status": status})


async def _step(ctx: Ctx, name: str, fn, *args, **kwargs) -> Dict[str, Any]:
    started, started_at = time.perf_counter(), datetime.now(timezone.utc).isoformat()
    if platform_bridge.is_live() and name in {
        "verify_mock_identity", "match_identity_name", "analyze_document", "check_scam_message",
        "find_duplicate_claims", "evaluate_route", "explain",
    }:
        await asyncio.to_thread(platform_bridge.live_call, "check_processing", ctx.case_id, ctx.generation)
    try:
        out = await fn(*args, **kwargs)
    except Exception as exc:  # a crashing tool is an unavailable tool, never a pass
        logger.exception("tool %s crashed", name)
        out = {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
    status = str(out.get("status"))
    await _record(ctx, name, status, out, started, started_at)
    if name == "check_consent":
        ctx.results.setdefault("check_consent", []).append(out)
    else:
        ctx.results[name] = out
    if status in BAD_STATUSES and name not in NON_CRITICAL_STEPS:
        ctx.flag("service_unavailable")
    return out


async def _skip(ctx: Ctx, name: str, reason: str, status: str = "skipped") -> Dict[str, Any]:
    out = {"status": status, "reason": reason}
    if status in BAD_STATUSES:
        out["error"] = reason
    await _record(ctx, name, status, out, time.perf_counter(), datetime.now(timezone.utc).isoformat())
    ctx.results[name] = out
    if status in BAD_STATUSES:
        ctx.flag("service_unavailable")
    return out


async def _ai_step(ctx: Ctx, name: str, fn, *args) -> Dict[str, Any]:
    """An AI-backed step. After the AI service has failed once in this run, the
    remaining AI steps are recorded as unavailable instead of waiting on it again."""
    if ctx.ai_down:
        return await _skip(ctx, name, "AI service was unavailable earlier in this run", "unavailable")
    out = await _step(ctx, name, fn, *args)
    if out.get("status") in BAD_STATUSES:
        ctx.ai_down = True
    return out


# ---------------------------------------------------------------------------
def _template_explanation(route: str, missing: List[str]) -> str:
    if route == "cleared":
        return "Your application passed the automated checks. An officer makes the final decision. (Prototype)"
    if route == "needs_proof":
        return "We need more information to continue: " + (", ".join(missing) or "additional documents") + ". (Prototype)"
    return "An officer will review your application personally. (Prototype)"


async def _finalize(ctx: Ctx, route: str, *, confidence=None, risk_score=None, rule_version=None,
                    model_version=None, user_explanation: Optional[str] = None, user_explanation_ur: Optional[str] = None,
                    m2_trace: Any = None,
                    reason: str = "", code: Optional[str] = None) -> None:
    case = ctx.case
    if platform_bridge.is_live() and (not user_explanation or not user_explanation_ur):
        localized = explain_result(route, ctx.flags)
        user_explanation = user_explanation or localized["user_explanation"]
        user_explanation_ur = user_explanation_ur or localized["user_explanation_ur"]
    if user_explanation is None:
        user_explanation = _template_explanation(route, ctx.missing)
    trace = {"steps": {k: _jsonable(v) for k, v in ctx.results.items() if k != "get_case_details"},
             "evaluate_trace": m2_trace, "overrides": list(ctx.overrides), **ctx.trace_extra}
    decision = {
        "route": route, "confidence": confidence, "risk_score": risk_score, "rule_version": rule_version,
        "model_version": model_version, "reason": reason, "user_explanation": user_explanation,
        "user_explanation_ur": user_explanation_ur,
        "flags": list(ctx.flags), "missing_evidence": list(ctx.missing),
        "requested_documents": list(ctx.requested_documents), "code": code,
        "auditor_trace": _jsonable(trace), "decided_by": "agent", "run_id": ctx.run_id,
    }
    if platform_bridge.is_live():
        tried = [s["step"] for s in ctx.steps if s["status"] != "skipped"]
        packet = notes.build_officer_packet(case, ctx.results, ctx.flags, ctx.overrides, tried, reason)
        decision.update(generation=ctx.generation, officer_note=notes.render_packet(packet))
    rec = await _step(ctx, "record_decision", tools.record_decision, ctx.case_id, decision)
    if rec.get("status") != "ok":
        raise RuntimeError(f"decision could not be recorded: {rec.get('error')}")

    if platform_bridge.is_live():
        ctx.final_status = rec["decision"]["route"]
        return

    tried = [s["step"] for s in ctx.steps if s["status"] not in ("skipped",)]
    if route == "needs_proof":
        out = await _step(ctx, "request_more_evidence", tools.request_more_evidence, ctx.case_id,
                          ctx.missing or ["additional_evidence"], user_explanation)
    elif route == "human_review":
        packet = notes.build_officer_packet(case, ctx.results, ctx.flags, ctx.overrides, tried, reason)
        out = await _step(ctx, "escalate_to_officer", tools.escalate_to_officer, ctx.case_id, packet)
    else:  # cleared: no money moves
        async def mark_cleared():
            try:
                await tools._bridge(platform_bridge.transition_case, ctx.case_id, "cleared", "agent",
                                    "automated checks passed; no financial authority")
            except Exception as exc:
                return tools._fail(exc, "could not mark cleared")
            return {"status": "ok", "to_status": "cleared"}
        out = await _step(ctx, "mark_cleared", mark_cleared)
    if out.get("status") != "ok":
        raise RuntimeError(f"could not apply route {route}: {out.get('error')}")
    ctx.final_status = route

    await _step(ctx, "send_notification", tools.send_notification, case, user_explanation)


async def _stop_for_consent(ctx: Ctx, out: Dict[str, Any]) -> None:
    code = out["status"] if out["status"] in ("CONSENT_REQUIRED", "CONSENT_REVOKED") else "service_unavailable"
    ctx.flag(code)
    reason = f"consent check for {out.get('who')} returned {out['status']}; the agent stopped before reading anything else"
    ctx.trace_extra["stopped_early"] = code
    # No AI call and no registry lookup after a consent problem: template explanation only.
    await _finalize(ctx, "human_review", reason=reason, code=code)


async def _pipeline(ctx: Ctx) -> None:
    # a) load the case; only "submitted" cases are processed
    got = await _step(ctx, "get_case_details", tools.get_case_details, ctx.case_id)
    if got.get("status") != "ok":
        ctx.final_status, ctx.error = "failed", got.get("error")
        return
    case = ctx.case = got["case"]
    valid_statuses = ("submitted", "processing") if platform_bridge.is_live() else ("submitted",)
    if got["case_status"] not in valid_statuses or (
        ctx.generation is not None and case.get("submission_count") != ctx.generation
    ):
        await _skip(ctx, "process_case", f"case status is '{got['case_status']}', not 'submitted'")
        ctx.final_status = "skipped"
        return

    async def go_processing():
        try:
            if platform_bridge.is_live():
                await tools._bridge(platform_bridge.live_call, "start_processing", ctx.case_id, ctx.generation)
            else:
                await tools._bridge(platform_bridge.transition_case, ctx.case_id, "processing", "agent",
                                    "agent started automated checks")
        except Exception as exc:
            return tools._fail(exc, "could not move case to processing")
        return {"status": "ok", "to_status": "processing"}

    if (await _step(ctx, "transition_processing", go_processing)).get("status") != "ok":
        raise RuntimeError("could not move case to processing")

    # b) consent: the processing department, and the helper if there is one
    grantees = [("department", PROCESSING_DEPARTMENT_ID)]
    if case.get("helper_id"):
        grantees.append(("helper", case["helper_id"]))
    for who, grantee in grantees:
        consent = await _step(ctx, "check_consent", tools.check_consent, case, grantee, PROCESSING_SCOPE, who)
        if consent.get("status") != "granted":
            return await _stop_for_consent(ctx, consent)

    # c) identity registry
    identity = await _step(ctx, "verify_mock_identity", tools.verify_mock_identity, case)
    id_status = identity.get("status")
    if id_status in ("mismatch",):
        ctx.flag("identity_mismatch")
    elif id_status == "not_found":
        ctx.flag("identity_not_found")
    elif id_status == "duplicate":
        ctx.flag("duplicate_claim")

    # d) name match (Member 2) when the registry gave us a name
    registry_name = (identity.get("record") or {}).get("name")
    match = None
    if registry_name:
        match = await _ai_step(ctx, "match_identity_name", tools.match_identity_name, case, registry_name)
    else:
        await _skip(ctx, "match_identity_name", "no registry name available")

    elig = {}
    if platform_bridge.is_live():
        elig = await _step(ctx, "evaluate_eligibility", tools.evaluate_eligibility, case)
    policy = elig.get("policy") or {}
    required = sorted(set(policy.get("required_documents") or []) | set(case.get("required_documents") or []))

    # e) documents
    document_quality = None
    if tools.field(case, "documents") or (platform_bridge.is_live() and required):
        if platform_bridge.is_live():
            docs = await _ai_step(ctx, "analyze_document", tools.analyze_document, case, required)
        else:
            docs = await _ai_step(ctx, "analyze_document", tools.analyze_document, case)
        for flag in docs.get("flags", []):
            ctx.flag(flag)
        ctx.requested_documents = docs.get("requested_documents", [])
        ctx.missing.extend(ctx.requested_documents)
        if docs.get("status") == "ok":
            document_quality = docs["document_quality"]
    else:
        ctx.missing.append("identity_document")
        await _skip(ctx, "analyze_document", "no documents attached: identity_document is missing")

    # f) attached message
    scam_flag = False
    if tools.field(case, "message", "scam_message"):
        scam = await _ai_step(ctx, "check_scam_message", tools.check_scam_message, case)
        scam_flag = scam.get("scam_flag") is True
        if scam_flag:
            ctx.flag("scam_suspected")
    else:
        await _skip(ctx, "check_scam_message", "no message attached")

    # g) duplicates
    dup = await _ai_step(ctx, "find_duplicate_claims", tools.find_duplicate_claims, case)
    duplicate_flag = dup.get("duplicate_flag") is True or id_status == "duplicate"
    if dup.get("duplicate_flag") is True:
        ctx.flag("duplicate_claim")

    if case.get("tenant_id") and dup.get("complete") is False:
        ctx.flag("duplicate_check_incomplete")

    if not platform_bridge.is_live():
        elig = await _step(ctx, "evaluate_eligibility", tools.evaluate_eligibility, case)
    rule_version = elig.get("rule_version")

    # i) routing (Member 2)
    inputs = {
        "identity_verified": id_status == "verified",
        "name_match_score": (match or {}).get("name_match_score") if (match or {}).get("status") == "ok" else None,
        "document_quality": document_quality,
        "duplicate_flag": duplicate_flag,
        "scam_flag": scam_flag,
        "monthly_income": case.get("monthly_income"),
        "household_size": case.get("household_size"),
    }

    async def evaluate():
        if case.get("tenant_id"):
            if not rule_version or not policy:
                return tools._fail(ValueError("Missing policy snapshot"), "Cannot evaluate case")
            return await tools.evaluate_route(ctx.case_id, rule_version, inputs, tenant_id=case["tenant_id"],
                                              policy=policy, flags=ctx.flags)
        return await tools.evaluate_route(ctx.case_id, rule_version, inputs)

    m2 = await _ai_step(ctx, "evaluate_route", evaluate)
    m2_ok = m2.get("status") == "ok"

    # j) safety overrides (M3_CONTEXT safety rules 1 and 2)
    route = m2["route"] if m2_ok else "human_review"
    if id_status != "verified" and "service_unavailable" not in ctx.flags and not any(
            f in ctx.flags for f in ("identity_mismatch", "identity_not_found", "duplicate_claim")):
        ctx.flag("identity_mismatch")
    critical = [f for f in ctx.flags if f in CRITICAL_FLAGS]
    reason_bits: List[str] = []
    if critical:
        ctx.overrides.append("safety_override")
        ctx.trace_extra["safety_override"] = True
        ctx.trace_extra["safety_override_detail"] = {
            "flags": critical, "ai_route": m2.get("route") if m2_ok else None, "changed_route": route != "human_review"}
        route = "human_review"
        reason_bits.append(f"safety override: {', '.join(critical)}")
    elif elig.get("failed_rules"):
        ctx.flag("eligibility_failed")
        ctx.overrides.append("eligibility_failed")
        route = "human_review"
        reason_bits.append(f"eligibility rules failed: {elig['failed_rules']}")
    else:
        for missing_field in elig.get("missing_fields", []):
            if f"field:{missing_field}" not in ctx.missing:
                ctx.missing.append(f"field:{missing_field}")
        if ctx.missing and route == "cleared":
            ctx.overrides.append("missing_evidence")
            route = "needs_proof"
            reason_bits.append(f"missing evidence: {ctx.missing}")
    if m2_ok:
        for f in m2.get("flags", []):
            ctx.flag(f)
    if route == "needs_proof" and not ctx.missing:
        ctx.missing.append("clearer_identity_document" if "document_quality_low" in ctx.flags else "additional_evidence")

    # explanation: Member 2's /explain, falling back to a short template
    explanation = explanation_ur = None
    if not ctx.ai_down:
        ex = await _ai_step(ctx, "explain", tools.explain, ctx.case_id, route, list(ctx.flags), rule_version)
        if ex.get("status") == "ok":
            explanation = ex["user_explanation"]
            explanation_ur = ex.get("user_explanation_ur")
    reason = "; ".join(reason_bits) or (f"AI route: {route}" if m2_ok else "AI evaluation unavailable")
    await _finalize(
        ctx, route, confidence=m2.get("confidence") if m2_ok else None,
        risk_score=m2.get("risk_score") if m2_ok else None, rule_version=rule_version,
        model_version=m2.get("model_version") if m2_ok else None, user_explanation=explanation,
        user_explanation_ur=explanation_ur,
        m2_trace=m2.get("auditor_trace") if m2_ok else None, reason=reason)
    # k) record_decision, l) route action and m) send_notification all run inside _finalize.

async def execute_run(snapshot: Dict[str, Any], generation: Optional[int] = None) -> Dict[str, Any]:
    """Runs the pipeline for an already-created run. Never raises."""
    ctx = Ctx(run_id=snapshot["id"], case_id=snapshot["case_id"], generation=generation)
    status, error = "failed", None
    await _audit(ctx, "agent_run.started", {"triggered_by": snapshot.get("triggered_by")})
    try:
        await asyncio.wait_for(_pipeline(ctx), timeout=RUN_TIMEOUT)
        status, error = ctx.final_status or "failed", ctx.error
    except asyncio.TimeoutError:
        error = f"run timed out after {RUN_TIMEOUT}s"
    except Exception as exc:
        logger.exception("agent run %s failed", ctx.run_id)
        error = f"{type(exc).__name__}: {exc}"
    finally:
        # Never leave a case stuck in "processing": hand it to an officer.
        try:
            current = await asyncio.to_thread(platform_bridge.get_case, ctx.case_id)
            if platform_bridge.is_live():
                if status == "failed":
                    packet = notes.build_error_packet(current, error or "Processing failed", [s["step"] for s in ctx.steps])
                    await asyncio.to_thread(platform_bridge.live_call, "stop_processing", ctx.case_id,
                                            ctx.generation, notes.render_packet(packet))
            elif tools.case_status(current) == "processing":
                error = error or "run ended while the case was still processing"
                packet = notes.build_error_packet(current, error, [s["step"] for s in ctx.steps])
                await asyncio.to_thread(platform_bridge.transition_case, ctx.case_id, "human_review",
                                        "agent", notes.render_packet(packet))
                status = "failed"
                await _audit(ctx, "agent_run.escalated_after_failure", {"error": error})
        except Exception:
            logger.exception("safety net could not inspect/escalate case %s", ctx.case_id)
        done = await asyncio.to_thread(_finish_run, ctx.run_id, status, error)
        await _audit(ctx, "agent_run.finished", {"status": status, "error": error, "steps": len(ctx.steps)})
    return done


async def process_case(case_id: str, triggered_by: str = "system", generation: Optional[int] = None) -> Dict[str, Any]:
    """Process one case and wait for the result. If a run for the case is already
    running, return that run instead of starting another."""
    snapshot, created = await asyncio.to_thread(create_or_get_run, case_id, triggered_by)
    if not created:
        return snapshot
    return await execute_run(snapshot, generation)
