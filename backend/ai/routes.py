# OWNER: Member 2 (decisions, scam check, OCR, name matching, explanations)
#
# Public  (/api/ai):      GET /health, POST /decide, GET /metrics
# Internal (/internal/ai): scam-check, extract-document, match-identity, detect-duplicates,
#                          evaluate, explain, metrics
# Internal routes need a service key, either header:
#   X-Service-Key = INTERNAL_SERVICE_KEY   (Member 3's agent)
#   X-API-Key     = AI_API_KEY             (Member 1's platform)
# No key configured -> every internal call is refused (fail closed).
import json
import logging
import os
import secrets
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError

from shared.schemas import Decision, Route

from . import services
from .schemas import DuplicatesIn, EvaluateIn, EvaluateInput, ExplainIn, ExtractIn, MatchIn, ScamIn
from .services import ServiceError

logger = logging.getLogger("m2.ai.routes")


def _error(status: int, code: str, message: str, retryable: bool = False) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "retryable": retryable},
                         "request_id": uuid.uuid4().hex}, status_code=status)


class AIRoute(APIRoute):
    """Turns our errors (and validation errors) into the team error format.
    Any unexpected crash becomes a 500, so callers fall back to a human officer."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def wrapped(request: Request):
            try:
                return await handler(request)
            except ServiceError as exc:
                return _error(exc.status, exc.code, exc.message, exc.retryable)
            except RequestValidationError as exc:
                problems = "; ".join(f"{'.'.join(str(p) for p in e.get('loc', [])[1:]) or 'body'}: {e.get('msg')}"
                                     for e in exc.errors())
                return _error(422, "VALIDATION_ERROR", problems or "invalid request")
            except Exception:
                logger.exception("AI route crashed: %s", request.url.path)
                return _error(500, "AI_INTERNAL_ERROR", "The AI service could not answer", retryable=True)

        return wrapped


def require_service_key(x_service_key: Optional[str] = Header(None),
                        x_api_key: Optional[str] = Header(None)) -> None:
    for got, env in ((x_service_key, "INTERNAL_SERVICE_KEY"), (x_api_key, "AI_API_KEY")):
        want = os.getenv(env, "")
        if want and got and secrets.compare_digest(got.encode(), want.encode()):
            return
    raise ServiceError(403, "FORBIDDEN", "internal service key required")


public = APIRouter(prefix="/api/ai", tags=["ai"], route_class=AIRoute)
internal = APIRouter(prefix="/internal/ai", tags=["ai-internal"], route_class=AIRoute,
                     dependencies=[Depends(require_service_key)])


# ---------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------
@public.get("/health")
def health():
    return {"service": "ai", "status": "ok", "model_version": services.MODEL_VERSION}


_TO_SHARED = {"cleared": Route.AUTO, "needs_proof": Route.ASK_MORE, "human_review": Route.HUMAN}


@public.post("/decide", response_model=Decision)
def decide(body: Optional[Dict[str, Any]] = Body(default=None)):
    """Frontend-facing decision. Body: the /evaluate payload, or just its "input" fields.
    An empty body has nothing verified, so it always goes to a human."""
    body = body or {}
    raw = body.get("input") if isinstance(body.get("input"), dict) else body
    try:
        inp = EvaluateInput.model_validate(raw)
    except ValidationError as exc:
        raise ServiceError(422, "VALIDATION_ERROR", str(exc.errors()[0].get("msg")))
    res = services.evaluate(body.get("case_id"), body.get("rule_version"), inp.model_dump(exclude_none=False))
    return Decision(route=_TO_SHARED[res["route"]], reason=res["user_explanation"], confidence=res["confidence"])


@public.get("/metrics")
def public_metrics(refresh: bool = Query(False)):
    """Measured results on synthetic test data (no personal data)."""
    return services.metrics(refresh)


# ---------------------------------------------------------------------------
# internal
# ---------------------------------------------------------------------------
@internal.post("/scam-check")
def scam_check(body: ScamIn):
    return services.scam_check(body.content, body.case_id)


@internal.post("/match-identity")
def match_identity(body: MatchIn):
    return services.match_identity(body.input_name if body.input_name is not None else body.submitted_name,
                                   body.registry_name, body.mock_identity_id, body.case_id)


@internal.post("/detect-duplicates")
def detect_duplicates(body: DuplicatesIn):
    return services.detect_duplicates(body.model_dump())


@internal.post("/evaluate")
def evaluate(body: EvaluateIn):
    return services.evaluate(body.case_id, body.rule_version, body.input.model_dump(), body.rules,
                             body.flags, body.tenant_id)


@internal.post("/explain")
def explain(body: ExplainIn):
    return services.explain(body.route, body.flags, body.case_id, body.rule_version, body.language)


_EXTRACT_DOC = {
    "requestBody": {"content": {
        "application/json": {"schema": ExtractIn.model_json_schema()},
        "multipart/form-data": {"schema": {"type": "object", "properties": {
            "file": {"type": "string", "format": "binary"},
            "document_type": {"type": "string", "example": "id_card"},
            "text": {"type": "string", "description": "optional: text already read from the document"},
            "expected": {"type": "string", "description": 'optional JSON of form values, e.g. {"name": "Muhammad Ali"}'},
            "case_id": {"type": "string"},
        }, "required": ["file"]}},
    }, "required": True},
}


@internal.post("/extract-document", openapi_extra=_EXTRACT_DOC)
async def extract_document(request: Request):
    """JSON {case_id, document:{id,type,quality?,file_path?,content_base64?,text?}} (Member 3),
    or multipart with a file + document_type (upload preview)."""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise ServiceError(422, "VALIDATION_ERROR", "multipart field 'file' is required")
        content = await upload.read(services.documents.MAX_BYTES + 1)
        expected = None
        if form.get("expected"):
            try:
                expected = json.loads(str(form.get("expected")))
            except ValueError:
                raise ServiceError(422, "VALIDATION_ERROR", "'expected' must be a JSON object")
            if not isinstance(expected, dict):
                raise ServiceError(422, "VALIDATION_ERROR", "'expected' must be a JSON object")
        return services.extract_document(doc_type=form.get("document_type"), content=content,
                                         text=form.get("text") or None, expected=expected,
                                         case_id=form.get("case_id"))
    try:
        raw = await request.json()
    except ValueError:
        raise ServiceError(422, "VALIDATION_ERROR", "send JSON or multipart/form-data")
    try:
        body = ExtractIn.model_validate(raw)
    except ValidationError as exc:
        raise ServiceError(422, "VALIDATION_ERROR", "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'body'}: {e['msg']}" for e in exc.errors()))
    doc = body.document
    return services.extract_document(
        doc_type=(doc.type if doc else None) or body.document_type,
        content_base64=(doc.content_base64 if doc else None) or body.content_base64,
        file_path=doc.file_path if doc else None,
        document_id=doc.id if doc else None,
        text=(doc.text if doc else None) or body.text,
        reported_quality=doc.quality if doc else None,
        expected=body.expected, case_id=body.case_id, tenant_id=body.tenant_id)


@internal.get("/metrics")
def internal_metrics(refresh: bool = Query(False)):
    return services.metrics(refresh)


# main.py mounts this one router (it does `app.include_router(ai_router)`).
router = APIRouter()
router.include_router(public)
router.include_router(internal)
