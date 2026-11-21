# OWNER: Member 3
# Async client for Member 2's AI service: AI_BASE_URL + /internal/ai/<name>,
# header X-Service-Key, 10s timeout, ONE retry on 5xx / timeout / connection error.
#
# Failure contract: this module NEVER fakes a positive result.
#   service down/slow/4xx -> {"status": "unavailable", "error": "..."}
#   invalid JSON / not an object -> {"status": "malformed", "error": "..."}
# A successful response is returned as the parsed dict ("status": "ok" is added only
# if M2's body has no status of its own; M2's evaluate contract has none).
#
# AI_STUB=true returns deterministic local responses shaped like the contracts, so the
# agent can be tested before Member 2's service exists. The stubs are NOT a model.
#
# Request/response shapes other than /evaluate are not fixed by the team contract yet;
# the ones below are what the agent sends/expects. TODO(M2): confirm field names.
import asyncio
import difflib
import json
import logging
import os
import time
from typing import Any, Callable, Dict, Optional

import httpx

logger = logging.getLogger("m3.agent.ai_client")

TIMEOUT = 10.0
RETRY_DELAY = 0.5
_transport: Optional[httpx.AsyncBaseTransport] = None  # tests inject a fake service


def set_transport(transport: Optional[httpx.AsyncBaseTransport]) -> None:
    global _transport
    _transport = transport


def unavailable(error: str) -> Dict[str, Any]:
    return {"status": "unavailable", "error": error}


async def _post(name: str, payload: Dict[str, Any], case_id: Optional[str] = None) -> Dict[str, Any]:
    if os.getenv("AI_STUB", "").strip().lower() in ("1", "true", "yes"):
        return _STUBS[name](payload)

    base_url = os.getenv("AI_BASE_URL", "http://localhost:8000")
    headers = {"X-Service-Key": os.getenv("INTERNAL_SERVICE_KEY", "")}
    error = "unknown error"
    for attempt in (1, 2):
        started = time.perf_counter()
        status_code: Optional[int] = None
        try:
            async with httpx.AsyncClient(base_url=base_url, transport=_transport, timeout=TIMEOUT) as client:
                response = await asyncio.wait_for(
                    client.post(f"/internal/ai/{name}", json=payload, headers=headers), timeout=TIMEOUT)
            status_code = response.status_code
            if status_code >= 500:
                error = f"AI service returned HTTP {status_code}"
            elif status_code >= 400:  # our request is wrong: retrying will not help
                _log(name, attempt, status_code, started, case_id, f"HTTP {status_code}")
                return unavailable(f"AI service rejected the request (HTTP {status_code})")
            else:
                _log(name, attempt, status_code, started, case_id)
                try:
                    data = response.json()
                except ValueError:
                    return {"status": "malformed", "error": "AI response was not valid JSON"}
                if not isinstance(data, dict):
                    return {"status": "malformed", "error": "AI response was not a JSON object"}
                data.setdefault("status", "ok")
                return data
        except (TimeoutError, httpx.TimeoutException):
            error = f"AI service timed out after {TIMEOUT}s"
        except httpx.TransportError as exc:
            error = f"AI service connection error: {type(exc).__name__}"
        except Exception as exc:  # never raise to callers
            error = f"AI client error: {type(exc).__name__}"
        _log(name, attempt, status_code, started, case_id, error)
        if attempt == 1:
            await asyncio.sleep(RETRY_DELAY)
    return unavailable(error)


def _log(name: str, attempt: int, status_code: Optional[int], started: float,
         case_id: Optional[str], error: Optional[str] = None) -> None:
    line = {"service": "ai", "endpoint": f"POST /internal/ai/{name}", "attempt": attempt,
            "status_code": status_code, "duration_ms": int((time.perf_counter() - started) * 1000),
            "case_id": case_id}
    if error:
        line["error"] = error
    logger.log(logging.WARNING if error else logging.INFO, "ai_call %s", json.dumps(line))


async def extract_document(payload: Dict[str, Any]) -> Dict[str, Any]:
    """in: {case_id, document:{id,type,...}} -> {document_type, quality 0..1, fields}"""
    return await _post("extract-document", payload, payload.get("case_id"))


async def match_identity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """in: {case_id, input_name, registry_name} -> {name_match_score 0..1}"""
    return await _post("match-identity", payload, payload.get("case_id"))


async def detect_duplicates(payload: Dict[str, Any]) -> Dict[str, Any]:
    """in: {case_id, citizen_id, mock_identity_id, name, dob, account_id} -> {duplicate_flag, matches}"""
    return await _post("detect-duplicates", payload, payload.get("case_id"))


async def scam_check(payload: Dict[str, Any]) -> Dict[str, Any]:
    """in: {case_id, message} -> {scam_flag, score 0..1, reasons}"""
    return await _post("scam-check", payload, payload.get("case_id"))


async def evaluate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Team contract. in: {case_id, rule_version, input:{identity_verified, name_match_score,
    document_quality, duplicate_flag, scam_flag, monthly_income}}
    out: {case_id, route, confidence, risk_score, flags[], rule_version, model_version,
    user_explanation, auditor_trace}"""
    return await _post("evaluate", payload, payload.get("case_id"))


async def explain(payload: Dict[str, Any]) -> Dict[str, Any]:
    """in: {case_id, route, flags, rule_version} -> {user_explanation}"""
    return await _post("explain", payload, payload.get("case_id"))


# ---------------------------------------------------------------------------
# Deterministic stubs (AI_STUB=true). Simple, explainable rules, no randomness.
# ---------------------------------------------------------------------------
STUB_NAME_MATCH_OK = 0.8
_SCAM_WORDS = ("send money", "processing fee", "otp", "pin code", "click this link", "gift card", "verify your account")


def _stub_extract(p: Dict[str, Any]) -> Dict[str, Any]:
    doc = p.get("document") or {}
    quality = doc.get("quality")
    return {"status": "ok", "document_type": doc.get("type", "unknown"),
            "quality": float(quality) if quality is not None else 0.9, "fields": {}, "model_version": "stub-v1"}


def _stub_match(p: Dict[str, Any]) -> Dict[str, Any]:
    a, b = str(p.get("input_name", "")).casefold().strip(), str(p.get("registry_name", "")).casefold().strip()
    score = round(difflib.SequenceMatcher(None, a, b).ratio(), 2) if a and b else 0.0
    return {"status": "ok", "name_match_score": score, "model_version": "stub-v1"}


def _stub_duplicates(p: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "ok", "duplicate_flag": False, "matches": [], "model_version": "stub-v1"}


def _stub_scam(p: Dict[str, Any]) -> Dict[str, Any]:
    text = str(p.get("message", "")).casefold()
    reasons = [w for w in _SCAM_WORDS if w in text]
    return {"status": "ok", "scam_flag": bool(reasons), "score": min(1.0, 0.4 * len(reasons)),
            "reasons": reasons, "model_version": "stub-v1"}


def _stub_evaluate(p: Dict[str, Any]) -> Dict[str, Any]:
    inp = p.get("input") or {}
    flags = []
    if not inp.get("identity_verified"):
        flags.append("identity_not_verified")
    if inp.get("duplicate_flag"):
        flags.append("duplicate_claim")
    if inp.get("scam_flag"):
        flags.append("scam_suspected")
    score = inp.get("name_match_score")
    if score is None or score < STUB_NAME_MATCH_OK:
        flags.append("low_name_match")
    quality = inp.get("document_quality")
    doc_poor = quality is None or quality < 0.5
    if doc_poor:
        flags.append("document_quality_low")
    if any(f in flags for f in ("identity_not_verified", "duplicate_claim", "scam_suspected", "low_name_match")):
        route, confidence = "human_review", 0.9
    elif doc_poor:
        route, confidence = "needs_proof", 0.8
    else:
        route, confidence = "cleared", 0.95
    risk = min(1.0, 0.25 * len(flags))
    return {
        "case_id": p.get("case_id"), "route": route, "confidence": confidence, "risk_score": risk,
        "flags": flags, "rule_version": p.get("rule_version"), "model_version": "stub-v1",
        "user_explanation": _stub_text(route, flags),
        "auditor_trace": {"engine": "stub-v1", "input": inp, "flags": flags, "route": route},
    }


def _stub_text(route: str, flags: Any) -> str:
    return {
        "cleared": "Your application passed the automated checks and now waits for an officer.",
        "needs_proof": "We need a clearer or additional document to continue.",
        "human_review": "An officer will look at your application personally.",
    }.get(route, "Your application is being processed.")


def _stub_explain(p: Dict[str, Any]) -> Dict[str, Any]:
    return {"status": "ok", "user_explanation": _stub_text(str(p.get("route")), p.get("flags")),
            "model_version": "stub-v1"}


_STUBS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "extract-document": _stub_extract, "match-identity": _stub_match,
    "detect-duplicates": _stub_duplicates, "scam-check": _stub_scam,
    "evaluate": _stub_evaluate, "explain": _stub_explain,
}
