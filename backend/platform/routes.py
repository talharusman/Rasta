# OWNER: Member 1 (Platform Routes)
import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, or_, select
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

from .models import (
    Audit, Case, Citizen, Consent, Decision, Document,
    History, Job, Notification, Rule, ScamCheck, User, now
)
from app.jobs.queue import enqueue_disbursement, start_case_processing
from .integration import notify_review, payment_summary
from .services import (
    Actor, Assign, CaseRef, ClaimData, Close, CreateCase, DB,
    EditCase, Grant, Login, Problem, Publish, Refresh,
    Review, Revision, RoleEdit, Scam, Service, active_rule, audit, auth_call,
    case_access, change, citizen_access, detail, dump, evaluate,
    factory, fail, get_resource, processing, verify_revision,
    roles, settings
)


class PlatformRoute(APIRoute):
    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def custom_handler(request: StarletteRequest) -> StarletteResponse:
            if not hasattr(request.state, 'request_id'):
                request.state.request_id = str(uuid.uuid4())
            try:
                response = await original_handler(request)
                response.headers['X-Request-ID'] = request.state.request_id
                return response
            except Problem as exc:
                user = getattr(request.state, 'actor', None)
                if user and exc.status in (403, 404):
                    try:
                        with factory()() as session:
                            session.add(Audit(
                                tenant_id=user.tenant_id,
                                actor_id=user.id,
                                actor_type='user',
                                action='access_denied',
                                resource=request.url.path,
                                outcome='denied',
                                request_id=request.state.request_id,
                                details={'code': exc.code}
                            ))
                            session.commit()
                    except Exception:
                        logging.exception('Denied audit persistence failed')
                res = JSONResponse(
                    status_code=exc.status,
                    content={
                        'error': {'code': exc.code, 'message': exc.message, 'retryable': exc.retryable},
                        'request_id': request.state.request_id
                    }
                )
                res.headers['X-Request-ID'] = request.state.request_id
                return res

        return custom_handler


router = APIRouter(route_class=PlatformRoute)
P = '/api/v1'


# --- Health & Readiness ---
@router.get('/api/platform/health', tags=['platform'])
def platform_health():
    return {"service": "platform", "status": "ok"}


# --- Authentication & User Identity ---
@router.post(P + '/auth/login', tags=['auth'])
def login(body: Login):
    return auth_call('token?grant_type=password', body.model_dump())


@router.post(P + '/auth/refresh', tags=['auth'])
def refresh(body: Refresh):
    return auth_call('token?grant_type=refresh_token', body.model_dump())


@router.get(P + '/auth/me', tags=['auth'])
def me(user: Actor, session: DB):
    value = dump(user)
    value['citizen_id'] = session.scalar(
        select(Citizen.id).where(Citizen.user_id == user.id, Citizen.tenant_id == user.tenant_id)
    )
    return value


@router.get(P + '/users', tags=['users'])
def users(user: Actor, session: DB, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    roles(user, 'admin')
    return {
        'items': [
            dump(x) for x in session.scalars(
                select(User).where(User.tenant_id == user.tenant_id).order_by(User.id).limit(limit).offset(offset)
            )
        ]
    }


@router.patch(P + '/users/{identifier}/role', tags=['users'])
def edit_role(identifier: uuid.UUID, body: RoleEdit, request: Request, user: Actor, session: DB):
    roles(user, 'admin')
    list(session.scalars(select(User).where(User.tenant_id == user.tenant_id, User.role == 'admin').order_by(User.id).with_for_update()))
    target = get_resource(session, User, identifier, user.tenant_id, True)
    if target.id == user.id:
        fail(409, 'CONFLICT', 'Self role edits are disabled')
    if session.scalar(select(Citizen.id).where(Citizen.user_id == target.id)) and body.role != 'citizen':
        fail(409, 'CONFLICT', 'Citizen-linked accounts must remain citizens')
    target.role = body.role
    audit(session, request, 'role_changed', identifier, {'role': body.role, 'reason': body.reason})
    return dump(target)


# --- Citizens & Cases ---
@router.get(P + '/citizens', tags=['citizens'])
def citizens(user: Actor, session: DB):
    roles(user, 'citizen', 'helper')
    query = select(Citizen).where(Citizen.tenant_id == user.tenant_id)
    if user.role == 'citizen':
        query = query.where(Citizen.user_id == user.id)
    else:
        query = query.where(Citizen.id.in_(
            select(Consent.citizen_id).where(
                Consent.tenant_id == user.tenant_id,
                Consent.grantee_id == user.id,
                Consent.scope == 'case:read',
                Consent.revoked_at.is_(None)
            )
        ))
    return {'items': [dump(x) for x in session.scalars(query)]}


@router.post(P + '/cases', status_code=201, tags=['cases'])
def create_case(body: CreateCase, request: Request, user: Actor, session: DB):
    citizen_access(session, user, body.citizen_id, 'case:write')
    claim = body.model_dump(mode='json')
    for field in ('citizen_phone', 'dob'):
        if claim['data'][field] is None:
            del claim['data'][field]
    hashed = hashlib.sha256(json.dumps(claim, sort_keys=True).encode()).hexdigest()
    old = session.scalar(
        select(Case).where(
            Case.tenant_id == user.tenant_id,
            Case.created_by == user.id,
            Case.idempotency_key == body.idempotency_key
        )
    )
    if old:
        if old.request_hash != hashed:
            fail(409, 'IDEMPOTENCY_CONFLICT', 'Key already used for another request')
        return detail(session, old)
    case = Case(
        tenant_id=user.tenant_id,
        citizen_id=body.citizen_id,
        created_by=user.id,
        helper_id=user.id if user.role == 'helper' else None,
        claim_type=body.claim_type,
        data=body.data.model_dump(mode="json"),
        idempotency_key=body.idempotency_key,
        request_hash=hashed
    )
    session.add(case)
    session.flush()
    session.add(History(
        tenant_id=user.tenant_id,
        case_id=case.id,
        actor_id=user.id,
        action='created',
        status='draft',
        notes=''
    ))
    audit(session, request, 'case_created', case.id)
    return detail(session, case)


@router.get(P + '/cases', tags=['cases'])
def list_cases(
    user: Actor,
    session: DB,
    status: str | None = None,
    citizen_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    query = select(Case).where(Case.tenant_id == user.tenant_id)
    if user.role == 'citizen':
        query = query.where(Case.citizen_id.in_(
            select(Citizen.id).where(Citizen.user_id == user.id, Citizen.tenant_id == user.tenant_id)
        ))
    elif user.role == 'helper':
        if citizen_id:
            citizen_access(session, user, citizen_id, 'case:read')
        query = query.where(Case.citizen_id.in_(
            select(Consent.citizen_id).where(
                Consent.tenant_id == user.tenant_id,
                Consent.grantee_id == user.id,
                Consent.scope == 'case:read',
                Consent.revoked_at.is_(None)
            )
        ))
    elif user.role == 'officer':
        query = query.where(Case.assigned_officer_id == user.id)
    elif user.role not in ('admin', 'auditor'):
        fail(403, 'FORBIDDEN')

    if status:
        query = query.where(Case.status == status)
    if citizen_id:
        query = query.where(Case.citizen_id == citizen_id)
    return {
        'items': [
            {**detail(session, c), 'payment': payment_summary(session, c) if c.approved_amount else None}
            for c in session.scalars(
                query.order_by(Case.created_at.desc(), Case.id).limit(limit).offset(offset)
            )
        ]
    }


@router.get(P + '/cases/review-queue', tags=['cases'])
def review_queue(user: Actor, session: DB, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    roles(user, 'officer', 'admin')
    query = select(Case).where(Case.tenant_id == user.tenant_id, Case.status.in_(['cleared', 'human_review']))
    if user.role == 'officer':
        query = query.where(or_(Case.assigned_officer_id == user.id, Case.assigned_officer_id.is_(None)))
    return {
        'items': [
            {
                'case_id': c.id,
                'status': c.status,
                'priority': c.priority,
                'revision': c.revision,
                'assigned_officer_id': c.assigned_officer_id,
                'created_at': c.created_at,
            }
            for c in session.scalars(query.order_by(Case.priority.desc(), Case.created_at, Case.id).limit(limit).offset(offset))
        ]
    }


@router.get(P + '/cases/{identifier}', tags=['cases'])
def get_case(identifier: uuid.UUID, user: Actor, session: DB):
    case = case_access(session, user, identifier)
    return {**detail(session, case), 'payment': payment_summary(session, case)}


@router.patch(P + '/cases/{identifier}', tags=['cases'])
def edit_case(identifier: uuid.UUID, body: EditCase, request: Request, user: Actor, session: DB):
    roles(user, 'citizen', 'helper')
    case = case_access(session, user, identifier, 'case:write', True)
    verify_revision(case, body.expected_revision)
    if case.status not in ('draft', 'needs_proof'):
        fail(409, 'INVALID_TRANSITION', 'Case is not editable')
    case.data = body.data.model_dump(mode="json")
    change(session, request, case, case.status, action='case_edited')
    return detail(session, case)


@router.post(P + '/cases/{identifier}/submit', status_code=202, tags=['cases'])
def submit(identifier: uuid.UUID, body: Revision, request: Request, user: Actor, session: DB):
    roles(user, 'citizen', 'helper')
    case = case_access(session, user, identifier, 'case:submit', True)
    if case.processing_generation:
        job = session.scalar(select(Job).where(
            Job.case_id == case.id, Job.generation == case.processing_generation,
        ))
        if job is not None and (
            job.submission_revision == body.expected_revision
            or (job.submission_revision is None and case.status == 'submitted'
                and body.expected_revision == case.revision - 1)
        ):
            return {'case_id': case.id, 'status': case.status, 'revision': case.revision, 'run_id': job.id}
    verify_revision(case, body.expected_revision)
    if case.status not in ('draft', 'needs_proof'):
        fail(409, 'INVALID_TRANSITION', 'Case cannot be submitted')
    processing(session, get_resource(session, Citizen, case.citizen_id, user.tenant_id))
    ClaimData.model_validate(case.data)
    case.processing_generation += 1
    change(session, request, case, 'submitted', action='case_submitted')
    job = Job(tenant_id=user.tenant_id, case_id=case.id, generation=case.processing_generation,
              submission_revision=body.expected_revision)
    session.add(job)
    session.flush()
    start_case_processing(str(case.id), case.processing_generation, db=session)
    return {'case_id': case.id, 'status': case.status, 'revision': case.revision, 'run_id': job.id}


@router.post(P + '/cases/{identifier}/assign', tags=['cases'])
def assign(identifier: uuid.UUID, body: Assign, request: Request, user: Actor, session: DB):
    roles(user, 'officer', 'admin')
    original = get_resource(session, Case, identifier, user.tenant_id)
    get_resource(session, Citizen, original.citizen_id, user.tenant_id, True)
    case = get_resource(session, Case, identifier, user.tenant_id, True)
    verify_revision(case, body.expected_revision)
    if case.status not in ('cleared', 'human_review', 'needs_proof'):
        fail(409, 'INVALID_TRANSITION')
    if user.role == 'officer' and (case.assigned_officer_id is not None or body.officer_id != user.id):
        fail(403, 'FORBIDDEN')
    officer = get_resource(session, User, body.officer_id, user.tenant_id)
    if officer.role != 'officer' or not officer.is_active:
        fail(422, 'VALIDATION_ERROR', 'Choose an active officer')
    case.assigned_officer_id = officer.id
    change(session, request, case, case.status, body.reason, 'case_assigned')
    return detail(session, case)


@router.post(P + '/cases/{identifier}/review', tags=['cases'])
def review(identifier: uuid.UUID, body: Review, request: Request, user: Actor, session: DB):
    roles(user, 'officer', 'admin')
    case = case_access(session, user, identifier, 'case:write', True)
    verify_revision(case, body.expected_revision)
    if case.status in ('approved', 'rejected', 'closed'):
        fail(409, 'VALIDATION_ERROR', f'Case is already {case.status}')
    if case.status not in ('cleared', 'human_review'):
        fail(409, 'INVALID_TRANSITION')
    if user.role == 'admin' and not body.override_reason:
        fail(422, 'VALIDATION_ERROR', 'Admin override reason required')
    if body.action == 'approve':
        processing(session, get_resource(session, Citizen, case.citizen_id, user.tenant_id))
        dec = session.scalar(
            select(Decision).where(Decision.case_id == case.id, Decision.processing_generation == case.processing_generation)
        )
        if not dec:
            fail(409, 'MISSING_EVIDENCE', 'No current decision')
        rule = get_resource(session, Rule, dec.rule_version_id, user.tenant_id)
        outcome, missing = evaluate(
            session, case, rule, dec.payload['confidence'], dec.payload['flags'], dec.payload['identity_verified']
        )
        if outcome != 'cleared' or missing:
            fail(409, 'MISSING_EVIDENCE', 'Blocking checks require a new successful processing result')
    if body.action == 'ask_proof' and not body.required_documents:
        fail(422, 'VALIDATION_ERROR', 'Required document types must be specified')
    status = {'approve': 'approved', 'reject': 'rejected', 'ask_proof': 'needs_proof'}[body.action]
    case.required_documents = body.required_documents
    if status in ('approved', 'rejected'):
        case.final_outcome = status
    change(session, request, case, status, body.notes, 'officer_' + body.action)
    if body.override_reason:
        audit(session, request, 'admin_override', case.id, {'reason': body.override_reason})
    if status == 'approved':
        case.approved_amount = settings.demo_payout_amount
        enqueue_disbursement(str(case.id), db=session)
    else:
        message = ('Your application needs additional documents.' if status == 'needs_proof'
                   else 'Your application was not approved. See the case for details.')
        notify_review(session, case, message)
    return {**detail(session, case), 'payment': payment_summary(session, case)}


@router.post(P + '/cases/{identifier}/close', tags=['cases'])
def close(identifier: uuid.UUID, body: Close, request: Request, user: Actor, session: DB):
    roles(user, 'officer', 'admin')
    case = case_access(session, user, identifier, 'case:write', True)
    verify_revision(case, body.expected_revision)
    if case.status not in ('approved', 'rejected'):
        fail(409, 'INVALID_TRANSITION')
    payment = payment_summary(session, case) if case.status == 'approved' else None
    if payment and payment['status'] in ('queued', 'pending'):
        fail(409, 'INVALID_TRANSITION', 'Payment must settle before closing this case')
    change(session, request, case, 'closed', body.notes, 'case_closed')
    return detail(session, case)


@router.get(P + '/cases/{identifier}/history', tags=['cases'])
def history(identifier: uuid.UUID, user: Actor, session: DB):
    case_access(session, user, identifier)
    rows = session.scalars(select(History).where(History.case_id == identifier)
                           .order_by(History.created_at, History.id))
    items = []
    for row in rows:
        item = dump(row)
        if user.role in ('citizen', 'helper') and row.action in ('decision_recorded', 'agent_failed'):
            item['notes'] = ''
        items.append(item)
    return {'items': items}


# --- Documents ---
@router.post(P + '/documents/preview', tags=['documents'])
def preview_document(
    user: Actor, session: DB, file: UploadFile = File(), citizen_id: uuid.UUID = Form(),
    consent: bool = Form(),
):
    from ai.services import ServiceError, extract_document

    roles(user, 'citizen', 'helper')
    if not consent:
        fail(403, 'CONSENT_REQUIRED', 'Confirm permission to analyze this synthetic photo')
    citizen = citizen_access(session, user, citizen_id, 'document:upload', lock=False)
    if user.role == 'helper':
        processing(session, citizen)
    content = file.file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        fail(413, 'FILE_TOO_LARGE', 'Maximum upload is 5 MiB')
    if not content.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff')):
        fail(415, 'UNSUPPORTED_MEDIA_TYPE', 'Preview requires a JPEG or PNG image')
    try:
        result = extract_document(doc_type='identity_proof', content=content)
    except ServiceError as exc:
        fail(exc.status, exc.code, exc.message, exc.retryable)
    return {key: result[key] for key in ('quality_ok', 'quality_note', 'extracted_fields', 'suggested_action')}


@router.post(P + '/cases/{identifier}/documents', status_code=201, tags=['documents'])
def upload(
    identifier: uuid.UUID,
    request: Request,
    user: Actor,
    session: DB,
    file: UploadFile = File(),
    type: Literal['identity_proof', 'income_proof'] = Form(),
    expected_revision: int = Form()
):
    roles(user, 'citizen', 'helper')
    case = case_access(session, user, identifier, 'document:upload', True)
    verify_revision(case, expected_revision)
    if case.status not in ('draft', 'needs_proof'):
        fail(409, 'INVALID_TRANSITION')
    content = file.file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        fail(413, 'FILE_TOO_LARGE', 'Maximum upload is 5 MiB')
    mime = 'application/pdf' if content.startswith(b'%PDF-') else 'image/png' if content.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if content.startswith(b'\xff\xd8\xff') else None
    if mime is None:
        fail(415, 'UNSUPPORTED_MEDIA_TYPE', 'Use JPEG, PNG or PDF')
    root = Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / str(uuid.uuid4())
    path.write_bytes(content)
    try:
        path.chmod(0o600)
    except Exception:
        pass
    doc = Document(
        tenant_id=user.tenant_id,
        case_id=case.id,
        file_path=str(path),
        type=type,
        content_type=mime,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest()
    )
    session.add(doc)
    change(session, request, case, case.status, action='document_uploaded')
    session.flush()
    return {'document': dump(doc, ('file_path',)), 'revision': case.revision}


@router.get(P + '/cases/{identifier}/documents/{document_id}', tags=['documents'])
def download(identifier: uuid.UUID, document_id: uuid.UUID, user: Actor, session: DB):
    case_access(session, user, identifier)
    doc = get_resource(session, Document, document_id, user.tenant_id)
    if doc.case_id != identifier:
        fail(404, 'NOT_FOUND')
    if not Path(doc.file_path).is_file():
        fail(503, 'SERVICE_UNAVAILABLE', 'Evidence storage unavailable')
    return FileResponse(
        doc.file_path,
        media_type=doc.content_type,
        filename=str(doc.id),
        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
    )


# --- Consents ---
@router.get(P + '/consents', tags=['consents'])
def consents(user: Actor, session: DB, citizen_id: uuid.UUID | None = None):
    query = select(Consent).where(Consent.tenant_id == user.tenant_id)
    if user.role == 'citizen':
        query = query.where(Consent.citizen_id.in_(select(Citizen.id).where(Citizen.user_id == user.id)))
    elif user.role == 'helper':
        query = query.where(Consent.grantee_id == user.id)
    else:
        roles(user, 'admin', 'auditor')
    if citizen_id:
        query = query.where(Consent.citizen_id == citizen_id)
    return {'items': [dump(c) for c in session.scalars(query.order_by(Consent.created_at.desc()))]}


@router.post(P + '/consents', status_code=201, tags=['consents'])
def grant(body: Grant, request: Request, user: Actor, session: DB):
    roles(user, 'citizen')
    citizen = citizen_access(session, user, body.citizen_id, 'case:write')
    if body.grantee_id:
        helper = get_resource(session, User, body.grantee_id, user.tenant_id)
        if helper.role != 'helper' or not helper.is_active:
            fail(422, 'VALIDATION_ERROR', 'Grantee must be an active helper')
    old = session.scalar(
        select(Consent).where(
            Consent.citizen_id == citizen.id,
            Consent.scope == body.scope,
            Consent.grantee_id == body.grantee_id,
            Consent.purpose == body.purpose,
            Consent.revoked_at.is_(None)
        )
    )
    if old:
        return dump(old)
    consent = Consent(tenant_id=user.tenant_id, **body.model_dump())
    session.add(consent)
    session.flush()
    audit(session, request, 'consent_granted', consent.id, {'scope': consent.scope})
    return dump(consent)


@router.post(P + '/consents/{identifier}/withdraw', tags=['consents'])
def withdraw(identifier: uuid.UUID, request: Request, user: Actor, session: DB):
    roles(user, 'citizen')
    consent = get_resource(session, Consent, identifier, user.tenant_id)
    citizen_access(session, user, consent.citizen_id, 'case:write')
    if consent.revoked_at is None:
        consent.revoked_at = now()
        audit(session, request, 'consent_withdrawn', consent.id)
        if consent.purpose == 'processing' or consent.scope == 'case:submit':
            affected = [Case.citizen_id == consent.citizen_id, Case.status.in_(['submitted', 'processing'])]
            if consent.purpose != 'processing':
                affected.append(Case.helper_id == consent.grantee_id)
            for case in session.scalars(
                select(Case).where(*affected).order_by(Case.id).with_for_update()
            ):
                change(session, request, case, 'human_review', 'Processing consent withdrawn', 'processing_blocked')
                for job in session.scalars(
                    select(Job).where(Job.case_id == case.id, Job.state.in_(['queued', 'processing']))
                ):
                    job.state = 'blocked'
                    job.error = 'CONSENT_REVOKED'
    return dump(consent)


@router.get(P + '/consents/access-check', tags=['consents'])
def access_check(citizen_id: uuid.UUID, scope: str, user: Actor, session: DB):
    if scope not in ('case:read', 'case:write', 'document:upload', 'case:submit', 'scam:check'):
        fail(422, 'VALIDATION_ERROR', 'Unsupported sharing scope')
    try:
        citizen_access(session, user, citizen_id, scope)
        return {'allowed': True, 'reason_code': None}
    except Problem as exc:
        if exc.status == 404:
            raise
        return {'allowed': False, 'reason_code': exc.code}


# --- Rules & Policies ---
@router.get(P + '/rules', tags=['rules'])
def rules_list(user: Actor, session: DB):
    roles(user, 'admin', 'officer', 'auditor')
    return {
        'items': [
            dump(r) for r in session.scalars(
                select(Rule).where(Rule.tenant_id == user.tenant_id, Rule.active.is_(True))
            )
        ]
    }


@router.patch(P + '/rules/{identifier}', status_code=201, tags=['rules'])
def publish(identifier: uuid.UUID, body: Publish, request: Request, user: Actor, session: DB):
    roles(user, 'admin')
    old = get_resource(session, Rule, identifier, user.tenant_id, True)
    if not old.active or old.version != body.expected_version:
        fail(409, 'RULE_VERSION_CONFLICT', 'Reload active policy')
    old.active = False
    session.flush()
    rule = Rule(
        tenant_id=user.tenant_id,
        policy_id=old.policy_id,
        rule_name=old.rule_name,
        version=old.version + 1,
        conditions_json=body.conditions_json.model_dump(),
        active=True
    )
    session.add(rule)
    session.flush()
    audit(session, request, 'rule_published', rule.id, {'reason': body.reason, 'previous_version': old.version})
    return dump(rule)


@router.get(P + '/rules/{identifier}/history', tags=['rules'])
def rule_history(identifier: uuid.UUID, user: Actor, session: DB):
    roles(user, 'admin', 'officer', 'auditor')
    rule = get_resource(session, Rule, identifier, user.tenant_id)
    return {
        'items': [
            dump(r) for r in session.scalars(
                select(Rule).where(Rule.tenant_id == user.tenant_id, Rule.policy_id == rule.policy_id).order_by(Rule.version.desc())
            )
        ]
    }


@router.post(P + '/rules/evaluate', tags=['rules'])
def rule_evaluate(body: CaseRef, user: Actor, session: DB):
    roles(user, 'admin', 'officer')
    case = case_access(session, user, body.case_id)
    rule = active_rule(session, user.tenant_id)
    route, missing = evaluate(session, case, rule, 0, [], False)
    return {
        'case_id': case.id,
        'route': route,
        'rule_version': rule.version,
        'rule_version_id': rule.id,
        'missing_evidence': missing,
        'preview': True
    }


# --- Audits, Metrics, Scam Checks ---
@router.get(P + '/audit-logs', tags=['audit'])
def audit_logs(
    user: Actor,
    session: DB,
    action: str | None = None,
    resource: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    roles(user, 'admin', 'auditor')
    query = select(Audit).where(Audit.tenant_id == user.tenant_id)
    if action:
        query = query.where(Audit.action == action)
    if resource:
        query = query.where(Audit.resource == resource)
    return {
        'items': [
            dump(a) for a in session.scalars(
                query.order_by(Audit.created_at.desc(), Audit.id).limit(limit).offset(offset)
            )
        ]
    }


@router.get(P + '/cases/{identifier}/decision-trace', tags=['audit'])
def trace(identifier: uuid.UUID, user: Actor, session: DB, decision_id: uuid.UUID | None = None):
    roles(user, 'admin', 'auditor', 'officer')
    case = case_access(session, user, identifier)
    query = select(Decision).where(Decision.case_id == identifier, Decision.tenant_id == user.tenant_id)
    if decision_id:
        query = query.where(Decision.id == decision_id)
    decisions = list(session.scalars(query.order_by(Decision.created_at.desc())))
    if not decisions:
        fail(404, 'NOT_FOUND', 'No decision available')
    latest_decision = decisions[0]

    dec_list = []
    for d in decisions:
        d_dict = dump(d)
        rule = session.get(Rule, d.rule_version_id)
        if rule:
            d_dict['rule_version'] = rule.version
            d_dict['rule_name'] = rule.rule_name
        dec_list.append(d_dict)

    history_list = [
        dump(h) for h in session.scalars(
            select(History).where(History.case_id == identifier).order_by(History.created_at.asc())
        )
    ]

    audit_list = [
        dump(a) for a in session.scalars(
            select(Audit).where(
                Audit.tenant_id == user.tenant_id,
                Audit.resource.contains(str(identifier))
            ).order_by(Audit.created_at.asc())
        )
    ]

    res = dump(latest_decision)
    rule = session.get(Rule, latest_decision.rule_version_id)
    if rule:
        res['rule_version'] = rule.version
        res['rule_name'] = rule.rule_name
    res['case_id'] = identifier
    res['case_status'] = case.status
    res['final_outcome'] = case.final_outcome
    res['decisions'] = dec_list
    res['history'] = history_list
    res['audit_logs'] = audit_list
    return res


@router.post(P + '/scam-checks', status_code=201, tags=['scam'])
def scam(body: Scam, request: Request, user: Actor, session: DB):
    from .services import ai_call
    citizen = citizen_access(session, user, body.citizen_id, 'scam:check')
    processing(session, citizen)
    payload = ai_call('/internal/ai/scam-check', {'text': body.text})
    if (
        not isinstance(payload, dict)
        or payload.get('label') not in ('likely_scam', 'uncertain', 'no_scam_indicators')
        or type(payload.get('confidence')) not in (float, int)
        or not 0 <= payload['confidence'] <= 1
        or not isinstance(payload.get('indicators'), list)
        or not all(isinstance(item, str) for item in payload['indicators'])
        or any(not isinstance(payload.get(key), str) or not payload[key].strip()
               for key in ('explanation', 'recommended_action'))
    ):
        fail(503, 'SERVICE_UNAVAILABLE', 'The scam checker could not return a result. Try again.', True)
    row = ScamCheck(tenant_id=user.tenant_id, citizen_id=citizen.id, payload={'text': body.text, **payload})
    session.add(row)
    session.flush()
    audit(session, request, 'scam_checked', row.id, actor_type='ai')
    return dump(row)


@router.get(P + '/scam-checks/{identifier}', tags=['scam'])
def scam_result(identifier: uuid.UUID, user: Actor, session: DB):
    row = get_resource(session, ScamCheck, identifier, user.tenant_id)
    citizen_access(session, user, row.citizen_id, 'scam:check')
    return dump(row)


@router.get(P + '/metrics/summary', tags=['metrics'])
def metrics(user: Actor, session: DB):
    roles(user, 'admin', 'auditor')
    counts = session.execute(
        select(Case.status, func.count()).where(Case.tenant_id == user.tenant_id).group_by(Case.status)
    ).all()
    return {'cases_by_status': dict(counts), 'total_cases': sum(count for _, count in counts)}


# --- Notifications ---
@router.get(P + '/notifications', tags=['notifications'])
def notifications(user: Actor, session: DB):
    rows = session.scalars(select(Notification).where(
        Notification.tenant_id == user.tenant_id, Notification.recipient_id == user.id,
    ).order_by(Notification.created_at.desc()).limit(50))
    return {'items': [dump(row, ('deduplication_key', 'provider_message_id')) for row in rows]}


# --- Internal Service Integration ---
@router.get('/internal/cases/{identifier}/payment-authorization', tags=['internal'])
def payment_authorization(identifier: uuid.UUID, service: Service, session: DB):
    case = session.get(Case, identifier)
    if not case:
        fail(404, 'NOT_FOUND')
    return {
        'case_id': case.id,
        'approved': case.final_outcome == 'approved' and case.status == 'approved',
        'prototype': True
    }
