# OWNER: Member 2
# Duplicate-claim detection. Compares a claim against
#   1. other open claims (platform `cases` table, plus claims this service has seen), and
#   2. the synthetic identity registry (two identity records that look like one person).
# Matching rules, strongest first:
#   same_identity            same mock identity id on another open claim      -> block
#   same_citizen             same citizen already has another open claim     -> block
#   shared_payment_account   same payment account on a claim for someone else -> officer_review
#   similar_name_same_dob    near-identical name + same birth date            -> officer_review
#   possible_duplicate_identity  another REGISTRY record, near-identical name + same birth date
import os
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from . import data_sources
from .names import match_names

NEAR_NAME = 0.90
MEMORY_LIMIT = 5000

_LOCK = threading.Lock()
_SEEN: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()  # claims seen by this process


class SourceUnavailable(Exception):
    """The case database could not be reached, so we cannot say 'no duplicate'."""


def reset_memory() -> None:
    with _LOCK:
        _SEEN.clear()


def _strict() -> bool:
    return os.getenv("AI_DUPLICATES_STRICT", "true").strip().lower() not in ("0", "false", "no")


def _same(a: Any, b: Any) -> bool:
    return a not in (None, "") and b not in (None, "") and str(a).strip().upper() == str(b).strip().upper()


def _remember(claim: Dict[str, Any]) -> None:
    if not claim.get("case_id"):
        return
    with _LOCK:
        _SEEN[str(claim["case_id"])] = {**claim, "status": claim.get("status") or "seen_by_ai"}
        _SEEN.move_to_end(str(claim["case_id"]))
        while len(_SEEN) > MEMORY_LIMIT:
            _SEEN.popitem(last=False)


def detect(claim: Dict[str, Any]) -> Dict[str, Any]:
    case_id = str(claim["case_id"]) if claim.get("case_id") else None
    identity = claim.get("mock_identity_id")
    sources: List[str] = []
    warnings: List[str] = []

    # Fill name / dob from the registry when the caller did not send them.
    reg_self = data_sources.registry_record(identity) if identity else None
    name = claim.get("name") or (reg_self or {}).get("name")
    dob = claim.get("dob") or (reg_self or {}).get("dob")

    # ---- 1. other open claims -------------------------------------------------
    others: Dict[str, Dict[str, Any]] = {}
    tenant_id = claim.get("tenant_id")
    platform = data_sources.platform_claims(tenant_id)
    if platform.ok:
        sources.append("platform_cases")
        for row in platform.rows:
            others[row["case_id"]] = row
    elif platform.unreachable or tenant_id:
        if _strict():
            raise SourceUnavailable(platform.error)
        warnings.append("The platform case database could not be checked for duplicates.")
    else:
        warnings.append("Platform case table not available here; only claims seen by this service were checked.")
    if tenant_id is None:
        with _LOCK:
            for cid, row in _SEEN.items():
                others.setdefault(cid, row)
        sources.append("ai_claim_memory")

    matches: List[Dict[str, Any]] = []
    for cid, other in others.items():
        if case_id and cid == case_id:
            continue
        if claim.get("claim_type") and other.get("claim_type") and other["claim_type"] != claim["claim_type"]:
            continue
        reasons = []
        if _same(identity, other.get("mock_identity_id")):
            reasons.append("same_identity")
        if _same(claim.get("citizen_id"), other.get("citizen_id")):
            reasons.append("same_citizen")
        if _same(claim.get("account_id"), other.get("account_id")) and not reasons:
            reasons.append("shared_payment_account")
        score = None
        if name and other.get("name"):
            score = match_names(name, other["name"])["score"]
            if not reasons and score >= NEAR_NAME and _same(dob, other.get("dob")):
                reasons.append("similar_name_same_dob")
        if reasons:
            matches.append({"type": reasons[0], "reasons": reasons, "case_id": cid,
                            "status": other.get("status"), "mock_identity_id": other.get("mock_identity_id"),
                            "name_score": score})

    # ---- 2. near-duplicate identity records in the registry -------------------
    registry = data_sources.registry_records()
    if registry.ok:
        sources.append(registry.origin)
        if name and dob:
            for rec in registry.rows:
                if _same(rec["mock_identity_id"], identity) or not _same(rec.get("dob"), dob):
                    continue
                score = match_names(name, rec["name"])["score"]
                if score >= NEAR_NAME:
                    matches.append({"type": "possible_duplicate_identity", "reasons": ["possible_duplicate_identity"],
                                    "case_id": None, "status": rec.get("status"),
                                    "mock_identity_id": rec["mock_identity_id"], "name_score": score})
    else:
        warnings.append("Identity registry not available; registry duplicates were not checked.")

    if tenant_id is None:
        _remember({"case_id": case_id, "citizen_id": claim.get("citizen_id"), "mock_identity_id": identity,
                   "name": name, "dob": dob, "account_id": claim.get("account_id"), "claim_type": claim.get("claim_type")})

    blocking = [m for m in matches if m["type"] in ("same_identity", "same_citizen")]
    first_claim = next((m for m in matches if m["case_id"]), None)
    if blocking:
        action = "block"
        explanation = "An active claim for this identity already exists. Duplicate submissions are not permitted."
    elif matches:
        action = "officer_review"
        kinds = sorted({m["type"] for m in matches})
        explanation = ("Possible duplicate found (" + ", ".join(k.replace("_", " ") for k in kinds) +
                       "). An officer must confirm these are different people before anything proceeds.")
    else:
        action = "officer_review" if warnings and tenant_id else "allow"
        explanation = ("The duplicate check could not be completed." if action == "officer_review"
                       else "No other open claim or identity record matched this claim.")
    return {
        "duplicate_flag": bool(matches),
        "duplicate_found": bool(matches),
        "matches": matches,
        "existing_case_id": first_claim["case_id"] if first_claim else None,
        "existing_status": first_claim["status"] if first_claim else None,
        "action": action,
        "explanation": explanation,
        "sources_checked": sources,
        "complete": not warnings,
        "warnings": warnings,
    }
