import hashlib
import hmac
import json
import uuid
from functools import lru_cache
from typing import Annotated
import httpx
import jwt
from fastapi import Depends, Header, Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session
from .config import settings
from .models import User, Citizen, Consent, Audit, Case, History, Decision, Rule, Document

class Problem(Exception):
    def __init__(self, status, code, message='Access not permitted', retryable=False):
        self.status, self.code, self.message, self.retryable = status, code, message, retryable

def fail(status, code, message='Access not permitted', retryable=False):
    raise Problem(status, code, message, retryable)

@lru_cache
def factory():
    if not settings.database_url: fail(503, 'SERVICE_UNAVAILABLE', 'DATABASE_URL is not configured', True)
    return sessionmaker(create_engine(settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=5), expire_on_commit=False)

def db():
    with factory()() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
DB = Annotated[Session, Depends(db)]

@lru_cache
def jwks():
    return jwt.PyJWKClient(settings.supabase_url.rstrip('/') + '/auth/v1/.well-known/jwks.json', cache_keys=True, lifespan=300)

def actor(request: Request, session: DB, authorization: str = Header(default='')):
    if not settings.supabase_url: fail(503, 'SERVICE_UNAVAILABLE', 'Supabase is not configured', True)
    if not authorization.startswith('Bearer '): fail(401, 'UNAUTHENTICATED', 'Bearer token required')
    token = authorization[7:]
    try:
        if settings.supabase_jwt_algorithm not in ('ES256','RS256'): fail(503, 'SERVICE_UNAVAILABLE', 'Configure an asymmetric Supabase signing key')
        key = jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=[settings.supabase_jwt_algorithm], audience=settings.supabase_jwt_audience, issuer=settings.supabase_url.rstrip('/')+'/auth/v1', options={'require':['sub','exp','iss','aud']})
        user_id = uuid.UUID(claims['sub'])
    except (jwt.PyJWTError, ValueError): fail(401, 'UNAUTHENTICATED', 'Invalid or expired token')
    user = session.get(User, user_id)
    if not user or not user.is_active: fail(403, 'FORBIDDEN')
    request.state.actor = user
    return user
Actor = Annotated[User, Depends(actor)]

def roles(user, *allowed):
    if user.role not in allowed: fail(403, 'FORBIDDEN')

def get(session, model, identifier, tenant, lock=False):
    query = select(model).where(model.id == identifier, model.tenant_id == tenant)
    if lock: query = query.with_for_update()
    value = session.scalar(query)
    if not value: fail(404, 'NOT_FOUND', 'Resource not found')
    return value

def citizen_access(session, user, citizen_id, scope, lock=True):
    citizen = get(session, Citizen, citizen_id, user.tenant_id, lock)
    if user.role == 'citizen' and citizen.user_id == user.id: return citizen
    if user.role != 'helper': fail(403, 'FORBIDDEN')
    grants = session.scalars(select(Consent).where(Consent.tenant_id==user.tenant_id, Consent.citizen_id==citizen.id, Consent.grantee_id==user.id, Consent.scope==scope)).all()
    if any(g.revoked_at is None for g in grants): return citizen
    fail(403, 'CONSENT_REVOKED' if grants else 'CONSENT_REQUIRED')

def processing(session, citizen):
    for scope in ('identity:verify', 'ai:process'):
        if not session.scalar(select(Consent.id).where(Consent.tenant_id==citizen.tenant_id, Consent.citizen_id==citizen.id, Consent.scope==scope, Consent.purpose=='processing', Consent.revoked_at.is_(None))):
            fail(403, 'CONSENT_REQUIRED', 'Active identity and AI processing consent required')

def case_access(session, user, identifier, scope='case:read', lock=False):
    # Citizen lock is always acquired before case lock, including worker writes.
    case = get(session, Case, identifier, user.tenant_id)
    get(session, Citizen, case.citizen_id, user.tenant_id, True)
    if lock: case = get(session, Case, identifier, user.tenant_id, True)
    if user.role in ('citizen','helper'): citizen_access(session,user,case.citizen_id,scope)
    elif user.role == 'officer' and case.assigned_officer_id != user.id: fail(403,'FORBIDDEN')
    elif user.role not in ('admin','auditor','officer'): fail(403,'FORBIDDEN')
    if user.role=='auditor' and scope!='case:read': fail(403,'FORBIDDEN')
    return case

def audit(session, request, action, resource, details=None, actor_type='user'):
    user = getattr(request.state,'actor',None)
    session.add(Audit(tenant_id=user.tenant_id if user else getattr(request.state, 'tenant_id', uuid.UUID(int=0)), actor_id=user.id if user else None, actor_type=actor_type, action=action,resource=str(resource),request_id=request.state.request_id,details=details or {}))

def change(session, request, case, status, notes='', action='transition'):
    previous = case.status
    case.status = status
    case.revision += 1
    session.add(History(tenant_id=case.tenant_id,case_id=case.id,actor_id=getattr(getattr(request.state,'actor',None),'id',None),action=action,previous_status=previous,status=status,notes=notes))
    audit(session,request,action,case.id,{'previous_status':previous,'status':status,'notes':notes})

def revision(case, expected):
    if case.revision != expected: fail(409,'CASE_VERSION_CONFLICT','Reload case before retrying')

def dump(row, exclude=()):
    return {c.name:getattr(row,c.name) for c in row.__table__.columns if c.name not in exclude}

def detail(session, case):
    value = dump(case,('request_hash','idempotency_key'))
    value['case_id'] = value.pop('id')
    decision = session.scalar(select(Decision).where(Decision.case_id==case.id).order_by(Decision.created_at.desc()))
    value['user_explanation'] = decision.payload['user_explanation'] if decision else None
    value['documents'] = [dump(d,('file_path','tenant_id')) for d in session.scalars(select(Document).where(Document.case_id==case.id))]
    return value

def active_rule(session, tenant):
    rule = session.scalar(select(Rule).where(Rule.tenant_id==tenant,Rule.active.is_(True)))
    if not rule: fail(503,'SERVICE_UNAVAILABLE','No active relief policy configured')
    return rule

def evaluate(session, case, rule, confidence, flags, identity_verified):
    policy = rule.conditions_json
    docs = set(session.scalars(select(Document.type).where(Document.case_id==case.id)))
    missing = sorted((set(policy['required_documents']) | set(case.required_documents or [])) - docs)
    critical = {'identity_mismatch','potential_duplicate','fraud_indicator','identity_service_unavailable'} | set(policy['critical_flags'])
    if not identity_verified or critical.intersection(flags) or case.data['monthly_income']>policy['max_monthly_income']: route='human_review'
    elif confidence < policy['proof_confidence_min']: route='human_review'
    elif missing: route='needs_proof'
    elif confidence >= policy['clear_confidence_min']: route='cleared'
    else: route='human_review'
    return route, missing

def service_auth(x_api_key: str = Header(default='')):
    if not settings.internal_api_key or not hmac.compare_digest(x_api_key, settings.internal_api_key): fail(403,'FORBIDDEN')
Service = Annotated[None, Depends(service_auth)]

def ai_call(path, payload):
    if not settings.ai_base_url or not settings.ai_api_key: fail(503,'SERVICE_UNAVAILABLE','AI provider not configured',True)
    try:
        response = httpx.post(settings.ai_base_url.rstrip('/')+path,json=payload,headers={'X-API-Key':settings.ai_api_key}, timeout=20)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError,ValueError): fail(503,'SERVICE_UNAVAILABLE','AI provider unavailable',True)
