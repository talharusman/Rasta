# OWNER: Member 1 (Platform Services & Business Logic)
import hashlib
import hmac
import json
import logging
import uuid
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import httpx
import jwt
from fastapi import Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shared import db as shared_db
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    User, Citizen, Case, Consent, Rule, Decision,
    History, Audit, Document
)


# --- Configuration ---
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=('.env', str(Path(__file__).resolve().parents[2] / '.env'), str(Path(__file__).resolve().parent / 'backend' / '.env')),
        extra='ignore'
    )
    database_url: str = ''
    supabase_url: str = ''
    supabase_publishable_key: str = ''
    supabase_jwt_audience: str = 'authenticated'
    supabase_jwt_algorithm: str = 'ES256'
    cors_origins: str = ''
    demo_tenant_id: uuid.UUID = uuid.UUID('11111111-1111-4111-8111-111111111111')
    demo_payout_amount: int = Field(default=25000, gt=0)
    internal_api_key: str = ''
    ai_base_url: str = ''
    ai_api_key: str = ''
    upload_dir: str = 'uploads'


settings = Settings()


# --- Exception Handling ---
class Problem(Exception):
    def __init__(self, status: int, code: str, message: str = 'Access not permitted', retryable: bool = False):
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


def fail(status: int, code: str, message: str = 'Access not permitted', retryable: bool = False):
    raise Problem(status, code, message, retryable)


# --- Database Session Factory ---
@lru_cache
def factory():
    if not settings.database_url:
        fail(503, 'SERVICE_UNAVAILABLE', 'DATABASE_URL is not configured', True)
    return shared_db.SessionLocal


def db():
    with factory()() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


DB = Annotated[Session, Depends(db, scope="function")]


# --- Supabase Auth & JWT Verification ---
@lru_cache
def jwks():
    return jwt.PyJWKClient(
        settings.supabase_url.rstrip('/') + '/auth/v1/.well-known/jwks.json',
        cache_keys=True,
        lifespan=300
    )


def actor(request: Request, session: DB, authorization: str = Header(default='')):
    if not settings.supabase_url:
        fail(503, 'SERVICE_UNAVAILABLE', 'Supabase is not configured', True)
    if not authorization.startswith('Bearer '):
        fail(401, 'UNAUTHENTICATED', 'Bearer token required')
    token = authorization[7:]
    try:
        if settings.supabase_jwt_algorithm not in ('ES256', 'RS256'):
            fail(503, 'SERVICE_UNAVAILABLE', 'Configure an asymmetric Supabase signing key')
        key = jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=[settings.supabase_jwt_algorithm],
            audience=settings.supabase_jwt_audience,
            issuer=settings.supabase_url.rstrip('/') + '/auth/v1',
            options={'require': ['sub', 'exp', 'iss', 'aud']}
        )
        user_id = uuid.UUID(claims['sub'])
    except (jwt.PyJWTError, ValueError):
        fail(401, 'UNAUTHENTICATED', 'Invalid or expired token')

    user = session.get(User, user_id)
    if not user or not user.is_active:
        fail(403, 'FORBIDDEN')
    request.state.actor = user
    return user


Actor = Annotated[User, Depends(actor)]


def roles(user: User, *allowed: str):
    if user.role not in allowed:
        fail(403, 'FORBIDDEN')


def get_resource(session: Session, model, identifier: uuid.UUID, tenant: uuid.UUID, lock: bool = False):
    query = select(model).where(model.id == identifier, model.tenant_id == tenant)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    value = session.scalar(query)
    if not value:
        fail(404, 'NOT_FOUND', 'Resource not found')
    return value


def citizen_access(session: Session, user: User, citizen_id: uuid.UUID, scope: str, lock: bool = True):
    citizen = get_resource(session, Citizen, citizen_id, user.tenant_id, lock)
    if user.role == 'citizen' and citizen.user_id == user.id:
        return citizen
    if user.role != 'helper':
        fail(403, 'FORBIDDEN')
    grants = session.scalars(
        select(Consent).where(
            Consent.tenant_id == user.tenant_id,
            Consent.citizen_id == citizen.id,
            Consent.grantee_id == user.id,
            Consent.scope == scope
        )
    ).all()
    if any(g.revoked_at is None for g in grants):
        return citizen
    fail(403, 'CONSENT_REVOKED' if grants else 'CONSENT_REQUIRED')


def processing(session: Session, citizen: Citizen):
    for scope in ('identity:verify', 'ai:process'):
        if not session.scalar(
            select(Consent.id).where(
                Consent.tenant_id == citizen.tenant_id,
                Consent.citizen_id == citizen.id,
                Consent.scope == scope,
                Consent.purpose == 'processing',
                Consent.revoked_at.is_(None)
            )
        ):
            fail(403, 'CONSENT_REQUIRED', 'Active identity and AI processing consent required')


def case_access(session: Session, user: User, identifier: uuid.UUID, scope: str = 'case:read', lock: bool = False):
    case = get_resource(session, Case, identifier, user.tenant_id)
    get_resource(session, Citizen, case.citizen_id, user.tenant_id, True)
    if lock:
        case = get_resource(session, Case, identifier, user.tenant_id, True)
    if user.role in ('citizen', 'helper'):
        citizen_access(session, user, case.citizen_id, scope)
    elif user.role == 'officer' and case.assigned_officer_id != user.id:
        fail(403, 'FORBIDDEN')
    elif user.role not in ('admin', 'auditor', 'officer'):
        fail(403, 'FORBIDDEN')
    if user.role == 'auditor' and scope != 'case:read':
        fail(403, 'FORBIDDEN')
    return case


def audit(session: Session, request: Request, action: str, resource, details: dict | None = None, actor_type: str = 'user'):
    user = getattr(request.state, 'actor', None)
    session.add(Audit(
        tenant_id=user.tenant_id if user else getattr(request.state, 'tenant_id', uuid.UUID(int=0)),
        actor_id=user.id if user else None,
        actor_type=actor_type,
        action=action,
        resource=str(resource),
        request_id=request.state.request_id,
        details=details or {}
    ))


def change(session: Session, request: Request, case: Case, status: str, notes: str = '', action: str = 'transition', actor_type: str = 'user'):
    previous = case.status
    case.status = status
    case.revision += 1
    session.add(History(
        tenant_id=case.tenant_id,
        case_id=case.id,
        actor_id=getattr(getattr(request.state, 'actor', None), 'id', None),
        action=action,
        previous_status=previous,
        status=status,
        notes=notes
    ))
    audit(session, request, action, case.id, {'previous_status': previous, 'status': status, 'notes': notes}, actor_type=actor_type)


def verify_revision(case: Case, expected: int):
    if case.revision != expected:
        fail(409, 'CASE_VERSION_CONFLICT', 'Reload case before retrying')


revision = verify_revision


def dump(row, exclude=()):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in exclude}


def detail(session: Session, case: Case):
    value = dump(case, ('request_hash', 'idempotency_key'))
    value['case_id'] = value.pop('id')
    dec = session.scalar(select(Decision).where(Decision.case_id == case.id, Decision.processing_generation == case.processing_generation))
    value['user_explanation'] = dec.payload['user_explanation'] if dec else None
    value['user_explanation_ur'] = dec.payload.get('user_explanation_ur') if dec else None
    if dec:
        value['decision'] = {key: dec.payload.get(key) for key in (
            'route', 'confidence', 'identity_verified', 'rule_version', 'model_version'
        )}
    value['documents'] = [dump(d, ('file_path', 'tenant_id')) for d in session.scalars(select(Document).where(Document.case_id == case.id))]
    return value


def active_rule(session: Session, tenant: uuid.UUID):
    rule = session.scalar(select(Rule).where(Rule.tenant_id == tenant, Rule.active.is_(True)))
    if not rule:
        fail(503, 'SERVICE_UNAVAILABLE', 'No active relief policy configured')
    return rule


def evaluate(session: Session, case: Case, rule: Rule, confidence: float | None, flags: list[str], identity_verified: bool):
    policy = rule.conditions_json
    docs = set(session.scalars(select(Document.type).where(Document.case_id == case.id)))
    missing = sorted((set(policy['required_documents']) | set(case.required_documents or [])) - docs)
    critical = {
        'identity_mismatch', 'identity_not_found', 'identity_service_unavailable',
        'duplicate_claim', 'potential_duplicate', 'fraud_indicator', 'scam_suspected',
        'service_unavailable', 'duplicate_check_incomplete', 'document_pdf_review',
    } | set(policy.get('critical_flags', []))
    if not identity_verified or critical.intersection(flags) or case.data.get('monthly_income', 0) > policy['max_monthly_income']:
        route = 'human_review'
    elif confidence is None or confidence < policy['proof_confidence_min']:
        route = 'human_review'
    elif missing:
        route = 'needs_proof'
    elif confidence >= policy['clear_confidence_min']:
        route = 'cleared'
    else:
        route = 'human_review'
    return route, missing


def service_auth(x_api_key: str = Header(default='')):
    if not settings.internal_api_key or not hmac.compare_digest(x_api_key, settings.internal_api_key):
        fail(403, 'FORBIDDEN')


Service = Annotated[None, Depends(service_auth)]


def ai_call(path: str, payload: dict):
    if not settings.ai_base_url or not settings.ai_api_key:
        fail(503, 'SERVICE_UNAVAILABLE', 'AI provider not configured', True)
    try:
        response = httpx.post(
            settings.ai_base_url.rstrip('/') + path,
            json=payload,
            headers={'X-API-Key': settings.ai_api_key},
            timeout=20
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        fail(503, 'SERVICE_UNAVAILABLE', 'AI provider unavailable', True)


def auth_call(path: str, payload: dict):
    if not settings.supabase_url or not settings.supabase_publishable_key:
        fail(503, 'SERVICE_UNAVAILABLE', 'Supabase Auth not configured')
    try:
        response = httpx.post(
            settings.supabase_url.rstrip('/') + '/auth/v1/' + path,
            headers={'apikey': settings.supabase_publishable_key},
            json=payload,
            timeout=15
        )
        if response.status_code in (400, 401, 403):
            fail(401, 'UNAUTHENTICATED', 'Invalid credentials or session')
        if response.status_code == 429:
            fail(429, 'RATE_LIMITED', 'Try again later', True)
        response.raise_for_status()
        data = response.json()
        return {key: data.get(key) for key in ('access_token', 'refresh_token', 'token_type', 'expires_in', 'expires_at')}
    except Problem:
        raise
    except (httpx.HTTPError, ValueError):
        fail(503, 'SERVICE_UNAVAILABLE', 'Supabase Auth unavailable', True)


# --- Request Schemas ---
class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(Input):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class Refresh(Input):
    refresh_token: str = Field(min_length=1)


class ClaimData(Input):
    name: str = Field(min_length=1, max_length=120)
    mock_identity_id: str = Field(pattern=r'^MOCK-', max_length=100)
    monthly_income: int = Field(ge=0)
    household_size: int = Field(ge=1, le=100)
    payment_account: str = Field(pattern=r'^MOCK-', max_length=100)
    dob: date | None = None
    citizen_phone: str | None = Field(default=None, pattern=r'^\+920[0-9]{9}$')


class CreateCase(Input):
    citizen_id: uuid.UUID
    claim_type: Literal['relief_payment'] = 'relief_payment'
    idempotency_key: str = Field(min_length=1, max_length=200)
    data: ClaimData


class Revision(Input):
    expected_revision: int = Field(ge=1)


class EditCase(Revision):
    data: ClaimData


class Assign(Revision):
    officer_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=2000)


class Review(Revision):
    action: Literal['approve', 'reject', 'ask_proof']
    notes: str = Field(min_length=1, max_length=2000)
    required_documents: list[Literal['identity_proof', 'income_proof']] = Field(default_factory=list)
    override_reason: str | None = Field(default=None, max_length=2000)


class Close(Revision):
    notes: str = Field(min_length=1, max_length=2000)


class RoleEdit(Input):
    role: Literal['citizen', 'helper', 'officer', 'admin', 'auditor']
    reason: str = Field(min_length=1, max_length=2000)


class Grant(Input):
    citizen_id: uuid.UUID
    grantee_id: uuid.UUID | None = None
    purpose: Literal['processing'] | None = None
    scope: Literal['case:read', 'case:write', 'document:upload', 'case:submit', 'scam:check', 'identity:verify', 'ai:process']

    @model_validator(mode='after')
    def target(self):
        proc = self.scope in ('identity:verify', 'ai:process')
        if proc != (self.purpose == 'processing') or proc == (self.grantee_id is not None):
            raise ValueError('Processing scopes require purpose only; sharing scopes require grantee only')
        return self


class Policy(Input):
    max_monthly_income: int = Field(ge=0)
    required_documents: list[Literal['identity_proof', 'income_proof']]
    clear_confidence_min: float = Field(ge=0, le=1)
    proof_confidence_min: float = Field(ge=0, le=1)
    critical_flags: list[str]

    @model_validator(mode='after')
    def thresholds(self):
        if self.proof_confidence_min > self.clear_confidence_min:
            raise ValueError('Invalid threshold order')
        return self


class Publish(Input):
    expected_version: int = Field(ge=1)
    conditions_json: Policy
    reason: str = Field(min_length=1, max_length=2000)


class CaseRef(Input):
    case_id: uuid.UUID


class Scam(Input):
    citizen_id: uuid.UUID
    text: str = Field(min_length=1, max_length=5000)
