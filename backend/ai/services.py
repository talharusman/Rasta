# OWNER: Member 2
# The AI service's operations, one function per route. Routes stay thin; the logic
# lives in names.py, scam.py, documents.py, duplicates.py, decision.py, evaluation.py.
import base64
import binascii
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from . import data_sources, decision, documents, duplicates, evaluation, names, scam
from .decision import MODEL_VERSION


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.status, self.code, self.message, self.retryable = status, code, message, retryable


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


# ---------------------------------------------------------------------------
def scam_check(text: str, case_id: Any = None) -> Dict[str, Any]:
    t = time.perf_counter()
    res = scam.classify(text)
    return {
        "case_id": case_id,
        **res,
        "scam_flag": res["label"] == "likely_scam",       # Member 3's key
        "indicators": res["signals"],                     # Member 1's key
        "reasons": res["signals"],
        "false_alarm_rate": _false_alarm_note(),
        "model_version": MODEL_VERSION,
        "latency_ms": _ms(t),
    }


def _false_alarm_note() -> str:
    s = evaluation.scam_summary()
    return (f"{s['false_alarm_rate']:.0%} false alarms, {s['missed_scam_rate']:.0%} missed scams "
            f"on {s['test_cases']} synthetic test messages")


# ---------------------------------------------------------------------------
def match_identity(input_name: str, registry_name: Optional[str], mock_identity_id: Optional[str],
                   case_id: Any = None) -> Dict[str, Any]:
    if registry_name is None:
        rec = data_sources.registry_record(mock_identity_id)
        if rec is None:
            raise ServiceError(404, "IDENTITY_NOT_FOUND", f"No synthetic identity record for {mock_identity_id}")
        registry_name = rec["name"]
    res = names.match_names(input_name, registry_name)
    action = "proceed" if res["verdict"] == "confirmed" else "officer_review"
    explanation = {
        "confirmed": "The names match (allowing for common spelling differences).",
        "uncertain": "The names are similar but not the same. Identity cannot be confirmed without an officer.",
        "mismatch": "The names do not match. This is never treated as the same person automatically.",
        "insufficient_data": "A name is missing, so the identity cannot be compared.",
    }[res["verdict"]]
    return {
        "case_id": case_id,
        "name_match_score": res["score"],     # Member 3's key
        "match_score": res["score"],
        "verdict": res["verdict"],
        "action": action,
        "candidates": [{"name": registry_name, "score": res["score"], "mock_id": mock_identity_id}],
        "explanation": explanation,
        "notes": res["notes"],
        "thresholds": {"confirmed": names.CONFIRMED, "uncertain": names.UNCERTAIN},
        "model_version": MODEL_VERSION,
    }


# ---------------------------------------------------------------------------
def detect_duplicates(claim: Dict[str, Any]) -> Dict[str, Any]:
    try:
        res = duplicates.detect(claim)
    except duplicates.SourceUnavailable as exc:
        raise ServiceError(503, "SERVICE_UNAVAILABLE", f"Cannot check duplicates: {exc}", retryable=True)
    return {"case_id": claim.get("case_id"), **res, "model_version": MODEL_VERSION}


# ---------------------------------------------------------------------------
def evaluate(case_id: Any, rule_version: Any, inp: Dict[str, Any], rules: Optional[Dict[str, Any]] = None,
             flags: Optional[list] = None, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    t = time.perf_counter()
    out = decision.evaluate(case_id, rule_version, inp, supplied_rules=rules, tenant_id=tenant_id, extra_flags=flags)
    out["auditor_trace"]["latency_ms"] = _ms(t)
    return out


def explain(route: str, flags: list, case_id: Any = None, rule_version: Any = None, language: str = "en") -> Dict[str, Any]:
    res = decision.explain(route, flags)
    text = res["user_explanation_ur"] if language == "ur" else res["user_explanation"]
    return {"case_id": case_id, "route": route, "rule_version": rule_version, "language": language,
            **res, "user_explanation": text, "user_explanation_en": res["user_explanation"],
            "model_version": MODEL_VERSION}


# ---------------------------------------------------------------------------
# documents: find the bytes, then analyse
# ---------------------------------------------------------------------------
def _upload_root() -> Path:
    return Path(os.getenv("UPLOAD_DIR", "uploads")).resolve()


def _read_upload(path_str: str) -> bytes:
    root = _upload_root()
    path = Path(path_str)
    path = (path if path.is_absolute() else Path.cwd() / path).resolve()
    if root != path and root not in path.parents:
        raise ServiceError(422, "VALIDATION_ERROR", "file_path must be inside the upload folder")
    if not path.is_file():
        raise ServiceError(422, "DOCUMENT_NOT_FOUND", "The document file was not found")
    if path.stat().st_size > documents.MAX_BYTES:
        raise ServiceError(413, "FILE_TOO_LARGE", "Document larger than 10 MB")
    return path.read_bytes()


def _b64(value: str) -> bytes:
    if "," in value[:100] and value.lstrip().startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ServiceError(422, "VALIDATION_ERROR", "content_base64 is not valid base64")


def extract_document(*, doc_type: Optional[str], content: Optional[bytes] = None, content_base64: Optional[str] = None,
                     file_path: Optional[str] = None, document_id: Optional[str] = None, text: Optional[str] = None,
                     reported_quality: Optional[float] = None, expected: Optional[Dict[str, Any]] = None,
                     case_id: Any = None, document_id_for_reply: Optional[str] = None, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    t = time.perf_counter()
    source = None
    if content is None and content_base64:
        content, source = _b64(content_base64), "content_base64"
    elif content is not None:
        source = "upload"
    if content is None and file_path:
        content, source = _read_upload(file_path), "file_path"
    if content is None and document_id and reported_quality is None and text is None:
        if tenant_id and case_id is None:
            raise ServiceError(422, "VALIDATION_ERROR", "case_id is required for platform evidence")
        found = data_sources.document_file(document_id, case_id=case_id, tenant_id=tenant_id)
        if tenant_id and (not found.ok or not found.rows):
            raise ServiceError(503, "SERVICE_UNAVAILABLE", "The case evidence could not be retrieved", retryable=True)
        if found.ok and found.rows:
            try:
                content = _read_upload(found.rows[0]["file_path"])
            except (ServiceError, OSError):
                if tenant_id:
                    raise ServiceError(503, "SERVICE_UNAVAILABLE", "The case evidence is unavailable", retryable=True)
                raise
            source = "platform_document"
            doc_type = doc_type or found.rows[0].get("type")
    try:
        res = documents.analyse(doc_type, content, text=text, reported_quality=reported_quality, expected=expected)
    except documents.DocumentError as exc:
        raise ServiceError(422, "DOCUMENT_UNREADABLE", str(exc))
    fields = res["extracted_fields"]
    return {
        "case_id": case_id, "document_id": document_id_for_reply or document_id,
        **res,
        "fields": fields,               # Member 3's key
        "content_source": source,
        "ocr_engine": documents.ocr_engine(),
        "model_version": MODEL_VERSION,
        "latency_ms": _ms(t),
    }


def metrics(refresh: bool = False) -> Dict[str, Any]:
    return evaluation.metrics(refresh)
