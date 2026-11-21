# OWNER: Member 3
# Bridge to Member 1's platform functions (see M3_CONTEXT.md).
# Everything here is a STUB until Member 1 exposes the real functions.
# Swap the bodies for real imports/calls; keep the signatures stable.
import logging
import os
import secrets
from typing import Any, Dict, List, Optional

from fastapi import Header, HTTPException

logger = logging.getLogger("m3.platform_bridge")

# In-memory record of audit calls made while log_audit is still a stub.
# Tests read this. Remove when Member 1's audit log is wired in.
STUB_AUDIT_LOG: List[Dict[str, Any]] = []


def get_case(case_id: str) -> Dict[str, Any]:
    # TODO(M1): call the real get_case(case_id).
    raise NotImplementedError("TODO(M1): get_case")


def check_consent(citizen_id: str, grantee_id: str, scope: str) -> bool:
    # TODO(M1): call the real check_consent(citizen_id, grantee_id, scope).
    raise NotImplementedError("TODO(M1): check_consent")


def get_active_rules() -> Dict[str, Any]:
    # TODO(M1): call the real get_active_rules().
    raise NotImplementedError("TODO(M1): get_active_rules")


def record_decision(case_id: str, decision: Dict[str, Any]) -> None:
    # TODO(M1): call the real record_decision(case_id, decision).
    raise NotImplementedError("TODO(M1): record_decision")


def transition_case(case_id: str, to_status: str, actor: str, note: str = "") -> None:
    # TODO(M1): call the real transition_case(case_id, to_status, actor, note).
    raise NotImplementedError("TODO(M1): transition_case")


def log_audit(
    actor_type: str,
    actor_id: str,
    action: str,
    resource: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """PLACEHOLDER: logs and keeps an in-memory copy.
    TODO(M1): replace with the real log_audit(actor_type, actor_id, action,
    resource, metadata) so entries reach the persistent audit log."""
    entry = {
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action,
        "resource": resource,
        "metadata": metadata or {},
    }
    STUB_AUDIT_LOG.append(entry)
    logger.info("AUDIT (stub) %s", entry)


def create_notification(case_id: str, recipient: str, message: str) -> None:
    # TODO(M1): call the real create_notification(case_id, recipient, message).
    raise NotImplementedError("TODO(M1): create_notification")


# ---------------------------------------------------------------------------
# STUB admin dependency.
# Member 1 has no admin-role dependency yet (only the Role.ADMIN enum in
# shared/schemas.py). Until they do, fail closed: require the internal service
# key. TODO(M1): replace with Member 1's real admin dependency, e.g.
#   from <platform auth module> import require_admin
# and return its user object (needs at least an "id").
# ---------------------------------------------------------------------------
def require_admin(x_service_key: Optional[str] = Header(None)) -> Dict[str, str]:
    expected = os.getenv("INTERNAL_SERVICE_KEY", "")
    if not expected or not x_service_key or not secrets.compare_digest(
        x_service_key, expected
    ):
        raise HTTPException(status_code=403, detail="admin required (STUB dependency)")
    return {"id": "stub-admin", "role": "ADMIN"}
