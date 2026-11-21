"""Database bridge configured by the live app, with isolated test stubs."""
import logging
import os
import secrets
import threading
from typing import Any, Callable, Dict, List, Optional

from fastapi import Header, HTTPException

logger = logging.getLogger("m3.platform_bridge")

CASE_STATES = (
    "draft", "submitted", "processing", "cleared", "needs_proof",
    "human_review", "approved", "rejected", "closed",
)

_implementation = None


def configure(implementation) -> None:
    global _implementation
    _implementation = implementation


def is_live() -> bool:
    return _implementation is not None


def _real(name: str) -> Optional[Callable]:
    if not is_live():
        return None
    return getattr(_implementation, name)


def live_call(name, *args):
    if not is_live():
        raise RuntimeError("Platform bridge is not configured")
    return getattr(_implementation, name)(*args)


def reset_resolution() -> None:
    """Compatibility with standalone test fixtures; lookup is no longer cached."""


# ---------------------------------------------------------------------------
# In-memory stub state (used only when Member 1's function is missing)
# ---------------------------------------------------------------------------
_LOCK = threading.RLock()
STUB_AUDIT_LOG: List[Dict[str, Any]] = []
STUB_CASES: Dict[str, Dict[str, Any]] = {}
STUB_CONSENTS: Dict[tuple, str] = {}  # (citizen_id, grantee_id, scope) -> "granted" | "revoked"
STUB_DECISIONS: Dict[str, List[Dict[str, Any]]] = {}
STUB_TRANSITIONS: List[Dict[str, Any]] = []
STUB_NOTIFICATIONS: List[Dict[str, Any]] = []

# What the agent asks consent for (set in the case-processing agent; kept here
# so the stub helpers and the agent agree).
DEFAULT_RULES = {
    "version": "rules-v1",
    # TODO(M1): where the payout amount really lives (case field or active rules).
    # The disbursement job reads case["approved_amount"] / case["amount"] first, then this.
    "payout_amount": 25000,
    "rules": [{"id": "income_cap", "field": "monthly_income", "op": "lte", "value": 50000}],
}


def stub_reset() -> None:
    with _LOCK:
        for store in (STUB_AUDIT_LOG, STUB_TRANSITIONS, STUB_NOTIFICATIONS):
            store.clear()
        for store in (STUB_CASES, STUB_CONSENTS, STUB_DECISIONS):
            store.clear()


def stub_grant_consent(citizen_id: str, grantee_id: str, scope: str) -> None:
    STUB_CONSENTS[(citizen_id, grantee_id, scope)] = "granted"


def stub_revoke_consent(citizen_id: str, grantee_id: str, scope: str) -> None:
    STUB_CONSENTS[(citizen_id, grantee_id, scope)] = "revoked"


def stub_add_case(case: Dict[str, Any], grant_consent: bool = True) -> Dict[str, Any]:
    """Add a fake case. grant_consent=True also grants the processing department
    (and the helper, if any) consent for the agent's scope."""
    from .consent_config import PROCESSING_DEPARTMENT_ID, PROCESSING_SCOPE

    with _LOCK:
        STUB_CASES[case["id"]] = dict(case)
    if grant_consent and case.get("citizen_id"):
        stub_grant_consent(case["citizen_id"], PROCESSING_DEPARTMENT_ID, PROCESSING_SCOPE)
        if case.get("helper_id"):
            stub_grant_consent(case["citizen_id"], case["helper_id"], PROCESSING_SCOPE)
    return STUB_CASES[case["id"]]


# ---------------------------------------------------------------------------
# Bridge functions
# ---------------------------------------------------------------------------
def get_case(case_id: str) -> Dict[str, Any]:
    fn = _real("get_case")
    if fn:
        return fn(case_id)
    with _LOCK:
        if case_id not in STUB_CASES:
            raise KeyError(f"case not found: {case_id}")
        return dict(STUB_CASES[case_id])


def check_consent(citizen_id: str, grantee_id: str, scope: str) -> Dict[str, Any]:
    """Returns {"granted": bool, "reason": "ok" | "CONSENT_REQUIRED" | "CONSENT_REVOKED"}."""
    fn = _real("check_consent")
    if fn:
        res = fn(citizen_id, grantee_id, scope)
        if isinstance(res, dict):
            return res
        return {"granted": bool(res), "reason": "ok" if res else "CONSENT_REQUIRED"}
    state = STUB_CONSENTS.get((citizen_id, grantee_id, scope))
    if state == "granted":
        return {"granted": True, "reason": "ok"}
    return {"granted": False, "reason": "CONSENT_REVOKED" if state == "revoked" else "CONSENT_REQUIRED"}


def get_active_rules(case_id=None, generation=None) -> Dict[str, Any]:
    fn = _real("get_active_rules")
    if fn:
        return fn(case_id, generation)
    return dict(DEFAULT_RULES)


_OPS = {
    "lte": lambda a, b: a <= b, "lt": lambda a, b: a < b,
    "gte": lambda a, b: a >= b, "gt": lambda a, b: a > b,
    "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
    "in": lambda a, b: a in b,
}


def evaluate_rules(case: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    """-> {eligible, rule_version, failed_rules: [], missing_fields: []}.
    Rule shape: {"id", "field", "op": lte|lt|gte|gt|eq|ne|in|present, "value"}.
    A rule whose field is missing is a missing field, never a pass."""
    fn = getattr(_implementation, "evaluate_rules", None)
    if fn:
        return fn(case, rules)
    failed: List[str] = []
    missing: List[str] = []
    for rule in rules.get("rules", []):
        field, op, expected = rule.get("field"), rule.get("op"), rule.get("value")
        value = case.get(field)
        if value is None or value == "":
            if field not in missing:
                missing.append(field)
            continue
        if op == "present":
            continue
        check = _OPS.get(op)
        try:
            ok = bool(check and check(value, expected))
        except TypeError:
            ok = False
        if not ok:
            failed.append(str(rule.get("id", field)))
    return {
        "eligible": not failed and not missing,
        "rule_version": rules.get("version"),
        "failed_rules": failed,
        "missing_fields": missing,
    }


def record_decision(case_id: str, decision: Dict[str, Any]) -> None:
    fn = _real("record_decision")
    if fn:
        return fn(case_id, decision)
    with _LOCK:
        STUB_DECISIONS.setdefault(case_id, []).append(dict(decision))


def transition_case(case_id: str, to_status: str, actor: str, note: str = "") -> None:
    fn = _real("transition_case")
    if fn:
        return fn(case_id, to_status, actor, note)
    if to_status not in CASE_STATES:
        raise ValueError(f"unknown case status: {to_status}")
    with _LOCK:
        case = STUB_CASES.get(case_id)
        if case is None:
            raise KeyError(f"case not found: {case_id}")
        STUB_TRANSITIONS.append(
            {"case_id": case_id, "from": case.get("status"), "to": to_status, "actor": actor, "note": note}
        )
        case["status"] = to_status
        case["last_note"] = note


def log_audit(
    actor_type: str,
    actor_id: str,
    action: str,
    resource: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    fn = _real("log_audit")
    if fn:
        return fn(actor_type, actor_id, action, resource, metadata)
    entry = {
        "actor_type": actor_type, "actor_id": actor_id, "action": action,
        "resource": resource, "metadata": metadata or {},
    }
    with _LOCK:
        STUB_AUDIT_LOG.append(entry)
    logger.info("AUDIT (stub) %s", entry)


def create_notification(case_id: str, recipient: str, message: str, key=None) -> Optional[str]:
    """Returns the notification id (None if Member 1's function returns nothing)."""
    fn = _real("create_notification")
    if fn:
        return fn(case_id, recipient, message, key)
    with _LOCK:
        notification_id = f"notif-{len(STUB_NOTIFICATIONS) + 1}"
        STUB_NOTIFICATIONS.append({"id": notification_id, "case_id": case_id, "recipient": recipient,
                                   "message": message, "state": "created", "message_id": None})
    return notification_id


def update_notification_state(notification_id: str, state: str, message_id: Optional[str] = None) -> None:
    """state: created | sent | delivered | resent | failed.
    TODO(M1): add this to the notifications module (keep name and signature)."""
    fn = _real("update_notification_state")
    if fn:
        return fn(notification_id, state, message_id)
    with _LOCK:
        for item in STUB_NOTIFICATIONS:
            if item.get("id") == notification_id:
                item["state"] = state
                if message_id is not None:
                    item["message_id"] = message_id
                return
    raise KeyError(f"notification not found: {notification_id}")


# ---------------------------------------------------------------------------
# STUB admin dependency.
# Member 1 has no admin-role dependency yet. Until they do, fail closed: require the
# internal service key. TODO(M1): replace with Member 1's real admin dependency and
# return its user object (needs at least an "id").
# ---------------------------------------------------------------------------
def require_admin(x_service_key: Optional[str] = Header(None)) -> Dict[str, str]:
    expected = os.getenv("INTERNAL_SERVICE_KEY", "")
    if not expected or not x_service_key or not secrets.compare_digest(x_service_key, expected):
        raise HTTPException(status_code=403, detail="admin required (STUB dependency)")
    return {"id": "stub-admin", "role": "ADMIN"}
