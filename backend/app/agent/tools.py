# OWNER: Member 3
# The agent's tools: one async function each. Every tool returns a dict with a
# "status" and never raises. The agent has no tool that moves money or grants a
# final decision (officers do that), and this module must never import the payment
# provider; tests/test_m3_agent.py enforces both.
#
# Case fields the tools read (TODO(M1): align with Member 1's real case dict):
#   id, status, citizen_id, helper_id, mock_identity_id, applicant_name, dob,
#   monthly_income, documents:[{id,type,quality?}], message, citizen_phone
import asyncio
import inspect
from typing import Any, Dict, List, Optional

from app.integrations.providers import registry

from . import ai_client, notes, platform_bridge


def field(case: Dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if case.get(name) not in (None, ""):
            return case[name]
    return default


def case_status(case: Dict[str, Any]) -> str:
    raw = case.get("status")
    raw = getattr(raw, "value", raw)
    return str(raw).strip().lower() if raw is not None else ""


def mask(recipient: Optional[str]) -> Optional[str]:
    return None if not recipient else "***" + str(recipient)[-4:]


async def _bridge(fn, *args):
    """Run a (possibly blocking, possibly async) bridge function without blocking the loop."""
    result = await asyncio.to_thread(fn, *args)
    return await result if inspect.isawaitable(result) else result


def _fail(exc: BaseException, what: str) -> Dict[str, Any]:
    return {"status": "unavailable", "error": f"{what}: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
async def get_case_details(case_id: str) -> Dict[str, Any]:
    try:
        case = await _bridge(platform_bridge.get_case, case_id)
    except Exception as exc:
        return _fail(exc, "could not load case")
    if not isinstance(case, dict):
        case = dict(getattr(case, "__dict__", {}))
    return {
        "status": "ok",
        "case": case,  # the orchestrator keeps this out of the stored trace
        "case_status": case_status(case),
        "has_documents": bool(field(case, "documents", default=[])),
        "has_message": bool(field(case, "message", "scam_message")),
        "has_helper": bool(case.get("helper_id")),
    }


async def check_consent(case: Dict[str, Any], grantee_id: str, scope: str, who: str = "department") -> Dict[str, Any]:
    citizen_id = case.get("citizen_id")
    base = {"who": who, "grantee_id": grantee_id, "scope": scope}
    if not citizen_id:
        return {**base, "status": "CONSENT_REQUIRED", "error": "case has no citizen_id"}
    try:
        res = await _bridge(platform_bridge.check_consent, citizen_id, grantee_id, scope)
    except Exception as exc:
        return {**base, **_fail(exc, "consent check failed")}
    if isinstance(res, dict) and res.get("granted") is True:
        return {**base, "status": "granted"}
    reason = res.get("reason") if isinstance(res, dict) else None
    code = reason if reason in ("CONSENT_REQUIRED", "CONSENT_REVOKED") else "CONSENT_REQUIRED"
    return {**base, "status": code}


async def verify_mock_identity(case: Dict[str, Any]) -> Dict[str, Any]:
    identity_id = case.get("mock_identity_id")
    if not identity_id:
        return {"status": "not_found", "issues": ["no_identity_id_on_case"], "record": None}
    provider = registry.get_identity_provider()
    result = await provider.verify(identity_id, field(case, "applicant_name", "name", default=""),
                                   case.get("dob"))
    return {
        "status": result.status.value,
        "record": result.record.model_dump(mode="json") if result.record else None,
        "issues": list(result.issues),
        "latency_ms": result.latency_ms,
        "error": result.error,
    }


async def match_identity_name(case: Dict[str, Any], registry_name: str) -> Dict[str, Any]:
    """Sends the applicant's name and the registry's name to Member 2 for matching."""
    res = await ai_client.match_identity({
        "case_id": case.get("id"),
        "input_name": field(case, "applicant_name", "name", default=""),
        "registry_name": registry_name,
    })
    if res.get("status") != "ok" or not isinstance(res.get("name_match_score"), (int, float)):
        return {"status": res.get("status") if res.get("status") != "ok" else "malformed",
                "error": res.get("error", "no name_match_score in response")}
    return {"status": "ok", "name_match_score": float(res["name_match_score"]),
            "model_version": res.get("model_version")}


async def analyze_document(case: Dict[str, Any]) -> Dict[str, Any]:
    documents: List[Dict[str, Any]] = field(case, "documents", default=[]) or []
    if not documents:
        return {"status": "skipped", "reason": "no_documents"}
    qualities, analyzed = [], []
    for doc in documents:
        if platform_bridge.is_live():
            await _bridge(platform_bridge.live_call, "check_processing", case["id"], case["submission_count"])
        res = await ai_client.extract_document({"case_id": case.get("id"), "document": doc})
        if res.get("status") != "ok" or not isinstance(res.get("quality"), (int, float)):
            return {"status": res.get("status") if res.get("status") != "ok" else "malformed",
                    "error": res.get("error", "no quality in response"), "documents": analyzed}
        qualities.append(float(res["quality"]))
        analyzed.append({"id": doc.get("id"), "type": res.get("document_type"), "quality": float(res["quality"])})
    return {"status": "ok", "document_quality": min(qualities), "documents": analyzed}


async def check_scam_message(case: Dict[str, Any]) -> Dict[str, Any]:
    message = field(case, "message", "scam_message")
    if not message:
        return {"status": "skipped", "reason": "no_message"}
    res = await ai_client.scam_check({"case_id": case.get("id"), "message": message})
    if res.get("status") != "ok" or not isinstance(res.get("scam_flag"), bool):
        return {"status": res.get("status") if res.get("status") != "ok" else "malformed",
                "error": res.get("error", "no scam_flag in response")}
    return {"status": "ok", "scam_flag": res["scam_flag"], "score": res.get("score"),
            "reasons": res.get("reasons", [])}


async def find_duplicate_claims(case: Dict[str, Any]) -> Dict[str, Any]:
    res = await ai_client.detect_duplicates({
        "case_id": case.get("id"), "citizen_id": case.get("citizen_id"),
        "mock_identity_id": case.get("mock_identity_id"),
        "name": field(case, "applicant_name", "name", default=""), "dob": case.get("dob"),
        "account_id": case.get("account_id"),
    })
    if res.get("status") != "ok" or not isinstance(res.get("duplicate_flag"), bool):
        return {"status": res.get("status") if res.get("status") != "ok" else "malformed",
                "error": res.get("error", "no duplicate_flag in response")}
    return {"status": "ok", "duplicate_flag": res["duplicate_flag"], "matches": res.get("matches", [])}


async def evaluate_eligibility(case: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if platform_bridge.is_live():
            rules = await _bridge(platform_bridge.get_active_rules, case['id'], case['submission_count'])
        else:
            rules = await _bridge(platform_bridge.get_active_rules)
        result = await _bridge(platform_bridge.evaluate_rules, case, rules)
    except Exception as exc:
        return _fail(exc, "rule evaluation failed")
    return {
        "status": "ok",
        "eligible": bool(result.get("eligible")),
        "rule_version": result.get("rule_version") or rules.get("version"),
        "failed_rules": list(result.get("failed_rules", [])),
        "missing_fields": list(result.get("missing_fields", [])),
    }


_ROUTES = ("cleared", "needs_proof", "human_review")


async def evaluate_route(case_id: str, rule_version: Optional[str], inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Member 2 /internal/ai/evaluate. A reply that does not match the contract is
    treated as malformed, never as a route."""
    res = await ai_client.evaluate({"case_id": case_id, "rule_version": rule_version, "input": inputs})
    if res.get("status") in ("unavailable", "malformed"):
        return {"status": res["status"], "error": res.get("error")}
    if res.get("route") not in _ROUTES:
        return {"status": "malformed", "error": f"evaluate returned route {res.get('route')!r}"}
    return {
        "status": "ok", "route": res["route"], "confidence": res.get("confidence"),
        "risk_score": res.get("risk_score"), "flags": list(res.get("flags") or []),
        "rule_version": res.get("rule_version") or rule_version, "model_version": res.get("model_version"),
        "user_explanation": res.get("user_explanation"), "auditor_trace": res.get("auditor_trace"),
    }


async def explain(case_id: str, route: str, flags: List[str], rule_version: Optional[str]) -> Dict[str, Any]:
    res = await ai_client.explain({"case_id": case_id, "route": route, "flags": flags, "rule_version": rule_version})
    text = res.get("user_explanation")
    if res.get("status") != "ok" or not isinstance(text, str) or not text.strip():
        return {"status": res.get("status") if res.get("status") != "ok" else "malformed",
                "error": res.get("error", "no user_explanation in response")}
    return {"status": "ok", "user_explanation": text}


async def request_more_evidence(case_id: str, missing: List[str], message: str = "") -> Dict[str, Any]:
    note = "Agent asked for more evidence: " + (", ".join(missing) if missing else "unspecified")
    try:
        await _bridge(platform_bridge.transition_case, case_id, "needs_proof", "agent", note)
    except Exception as exc:
        return _fail(exc, "could not move case to needs_proof")
    return {"status": "ok", "missing": list(missing), "to_status": "needs_proof"}


async def escalate_to_officer(case_id: str, packet: Dict[str, Any]) -> Dict[str, Any]:
    try:
        await _bridge(platform_bridge.transition_case, case_id, "human_review", "agent", notes.render_packet(packet))
    except Exception as exc:
        return _fail(exc, "could not move case to human_review")
    return {"status": "ok", "to_status": "human_review", "packet": packet}


async def record_decision(case_id: str, decision: Dict[str, Any]) -> Dict[str, Any]:
    try:
        persisted = await _bridge(platform_bridge.record_decision, case_id, decision)
    except Exception as exc:
        return _fail(exc, "could not record decision")
    return {"status": "ok", "route": decision.get("route"), "decision": persisted}


async def send_notification(case: Dict[str, Any], message: str) -> Dict[str, Any]:
    case_id = case.get("id")
    phone = field(case, "citizen_phone", "phone")
    out: Dict[str, Any] = {"recipient": mask(phone)}
    sms_status = "no_phone"
    if phone:
        sent = await registry.get_notification_provider().send(phone, message, case_id)
        sms_status = sent.status.value
        out.update(message_id=sent.message_id, error=sent.error)
    try:
        await _bridge(platform_bridge.create_notification, case_id, phone or str(case.get("citizen_id")), message)
        out["in_app"] = "ok"
    except Exception as exc:
        out["in_app"] = f"unavailable: {type(exc).__name__}"
    out["status"] = sms_status
    return out


# The complete list of what the agent may do.
TOOLS = {
    "get_case_details": get_case_details,
    "check_consent": check_consent,
    "verify_mock_identity": verify_mock_identity,
    "match_identity_name": match_identity_name,
    "analyze_document": analyze_document,
    "check_scam_message": check_scam_message,
    "find_duplicate_claims": find_duplicate_claims,
    "evaluate_eligibility": evaluate_eligibility,
    "evaluate_route": evaluate_route,
    "explain": explain,
    "request_more_evidence": request_more_evidence,
    "escalate_to_officer": escalate_to_officer,
    "record_decision": record_decision,
    "send_notification": send_notification,
}
