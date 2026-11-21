# OWNER: Member 3
# Bridge to Member 1's platform functions (see M3_CONTEXT.md).
#
# Each function first looks for Member 1's REAL implementation; if it is not there
# yet it falls back to an in-memory STUB so Member 3 can test today.
# Callers must use module attributes (platform_bridge.get_case(...)), never
# "from ... import get_case", so tests can monkeypatch them.
#
# TODO(M1): Member 1's package is loaded by backend/main.py under the name
# "rasta_platform". Put the module(s) that will expose these functions in
# _M1_MODULES (first match wins), keeping the names and signatures below:
#   get_case(case_id) -> dict              (status as a lowercase state name)
#   check_consent(citizen_id, grantee_id, scope) -> bool | {"granted": bool, "reason": ...}
#   get_active_rules() -> {"version": str, "rules": [...]}
#   evaluate_rules(case, rules) -> {eligible, rule_version, failed_rules, missing_fields}
#   record_decision(case_id, decision: dict)
#   transition_case(case_id, to_status, actor, note)
#   log_audit(actor_type, actor_id, action, resource, metadata)
#   create_notification(case_id, recipient, message)
import importlib
import logging
import os
import secrets
import threading
from typing import Any, Callable, Dict, List, Optional

from fastapi import Header, HTTPException

logger = logging.getLogger("m3.platform_bridge")

_M1_MODULES = ("rasta_platform.services",)  # TODO(M1): confirm the real module path(s)

CASE_STATES = (
    "draft", "submitted", "processing", "cleared", "needs_proof",
    "human_review", "approved", "rejected", "closed",
)

_RESOLVED: Dict[str, Optional[Callable]] = {}


def _real(name: str) -> Optional[Callable]:
    """Member 1's real function, or None (then the stub is used). Cached."""
    if name not in _RESOLVED:
        found = None
        for module_name in _M1_MODULES:
            try:
                found = getattr(importlib.import_module(module_name), name, None)
            except ImportError:
                found = None
            if found:
                break
        _RESOLVED[name] = found
    return _RESOLVED[name]


def reset_resolution() -> None:
    """Forget cached lookups (e.g. after Member 1's module becomes importable)."""
    _RESOLVED.clear()


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


def get_active_rules() -> Dict[str, Any]:
    fn = _real("get_active_rules")
    if fn:
        return fn()
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
    fn = _real("evaluate_rules")
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


def create_notification(case_id: str, recipient: str, message: str) -> None:
    fn = _real("create_notification")
    if fn:
        return fn(case_id, recipient, message)
    with _LOCK:
        STUB_NOTIFICATIONS.append({"case_id": case_id, "recipient": recipient, "message": message})


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
