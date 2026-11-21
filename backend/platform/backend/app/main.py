import hashlib
import json
import logging
import uuid
from pathlib import Path
import httpx
from fastapi import FastAPI, Request, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func, or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from .models import *
from .platform import *
from .schemas import *

app = FastAPI(title='Public Relief Assistance Platform — SIMULATED', version='0.1.0')
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,allow_methods=['GET','POST','PATCH'],allow_headers=['Authorization','Content-Type'],expose_headers=['X-Request-ID'])
P='/api/v1'

@app.middleware('http')
async def request_id(request, call_next):
    request.state.request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers['X-Request-ID'] = request.state.request_id
    return response

def error_response(request,status,code,message,retryable=False):
    return JSONResponse(status_code=status,content={'error':{'code':code,'message':message,'retryable':retryable},'request_id':request.state.request_id})

@app.exception_handler(Problem)
async def problem_handler(request,exc):
    user=getattr(request.state,'actor',None)
    if user and exc.status in (403,404):
        try:
            with factory()() as session:
                session.add(Audit(tenant_id=user.tenant_id,actor_id=user.id,actor_type='user',action='access_denied',resource=request.url.path,outcome='denied',request_id=request.state.request_id,details={'code':exc.code}))
                session.commit()
        except SQLAlchemyError: logging.exception('Denied audit persistence failed')
    return error_response(request,exc.status,exc.code,exc.message,exc.retryable)

@app.exception_handler(RequestValidationError)
async def validation_handler(request,exc):
    return error_response(request,422,'VALIDATION_ERROR','Request fields are invalid')

@app.exception_handler(IntegrityError)
async def conflict_handler(request,exc):
    return error_response(request,409,'CONFLICT','Concurrent operation or constraint conflict; reload and retry')

@app.exception_handler(SQLAlchemyError)
async def database_handler(request,exc):
    logging.exception('Database operation failed')
    return error_response(request,503,'SERVICE_UNAVAILABLE','Database unavailable',True)

@app.get('/health')
def health(): return {'status':'ok','prototype':True}

@app.get('/ready')
def ready(session: DB):
    session.execute(text('SELECT 1'))
    if not settings.supabase_url or not settings.supabase_publishable_key: fail(503,'SERVICE_UNAVAILABLE','Auth is not configured')
    return {'status':'ready','ai_configured':bool(settings.ai_base_url)}

def auth_call(path,payload):
    if not settings.supabase_url or not settings.supabase_publishable_key: fail(503,'SERVICE_UNAVAILABLE','Supabase Auth not configured')
    try:
        response=httpx.post(settings.supabase_url.rstrip('/')+'/auth/v1/'+path,headers={'apikey':settings.supabase_publishable_key},json=payload,timeout=15)
        if response.status_code in (400,401,403): fail(401,'UNAUTHENTICATED','Invalid credentials or session')
        if response.status_code==429: fail(429,'RATE_LIMITED','Try again later',True)
        response.raise_for_status()
        data=response.json()
        return {key:data.get(key) for key in ('access_token','refresh_token','token_type','expires_in','expires_at')}
    except (httpx.HTTPError, ValueError): fail(503,'SERVICE_UNAVAILABLE','Supabase Auth unavailable',True)

@app.post(P+'/auth/login')
def login(body: Login): return auth_call('token?grant_type=password',body.model_dump())
@app.post(P+'/auth/refresh')
def refresh(body: Refresh): return auth_call('token?grant_type=refresh_token',body.model_dump())
@app.get(P+'/auth/me')
def me(user: Actor,session: DB):
    value=dump(user)
    value['citizen_id']=session.scalar(select(Citizen.id).where(Citizen.user_id==user.id,Citizen.tenant_id==user.tenant_id))
    return value

@app.get(P+'/users')
def users(user: Actor,session: DB,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0)):
    roles(user,'admin')
    return {'items':[dump(x) for x in session.scalars(select(User).where(User.tenant_id==user.tenant_id).order_by(User.id).limit(limit).offset(offset))]}
@app.patch(P+'/users/{identifier}/role')
def edit_role(identifier:uuid.UUID,body:RoleEdit,request:Request,user:Actor,session:DB):
    roles(user,'admin')
    # Lock all tenant admins to serialize last-admin checks.
    list(session.scalars(select(User).where(User.tenant_id==user.tenant_id,User.role=='admin').order_by(User.id).with_for_update()))
    target=get(session,User,identifier,user.tenant_id,True)
    if target.id==user.id: fail(409,'CONFLICT','Self role edits are disabled')
    if session.scalar(select(Citizen.id).where(Citizen.user_id==target.id)) and body.role!='citizen': fail(409,'CONFLICT','Citizen-linked accounts must remain citizens')
    target.role=body.role
    audit(session,request,'role_changed',identifier,{'role':body.role,'reason':body.reason})
    return dump(target)

@app.get(P+'/citizens')
def citizens(user:Actor,session:DB):
    roles(user,'citizen','helper')
    query=select(Citizen).where(Citizen.tenant_id==user.tenant_id)
    if user.role=='citizen': query=query.where(Citizen.user_id==user.id)
    else: query=query.where(Citizen.id.in_(select(Consent.citizen_id).where(Consent.tenant_id==user.tenant_id,Consent.grantee_id==user.id,Consent.scope=='case:read',Consent.revoked_at.is_(None))))
    return {'items':[dump(x) for x in session.scalars(query)]}

@app.post(P+'/cases',status_code=201)
def create_case(body:CreateCase,request:Request,user:Actor,session:DB):
    citizen_access(session,user,body.citizen_id,'case:write')
    hashed=hashlib.sha256(json.dumps(body.model_dump(mode='json'),sort_keys=True).encode()).hexdigest()
    old=session.scalar(select(Case).where(Case.tenant_id==user.tenant_id,Case.created_by==user.id,Case.idempotency_key==body.idempotency_key))
    if old:
        if old.request_hash!=hashed: fail(409,'IDEMPOTENCY_CONFLICT','Key already used for another request')
        return detail(session,old)
    case=Case(tenant_id=user.tenant_id,citizen_id=body.citizen_id,created_by=user.id,helper_id=user.id if user.role=='helper' else None,claim_type=body.claim_type,data=body.data.model_dump(),idempotency_key=body.idempotency_key,request_hash=hashed)
    session.add(case); session.flush()
    session.add(History(tenant_id=user.tenant_id,case_id=case.id,actor_id=user.id,action='created',status='draft',notes=''))
    audit(session,request,'case_created',case.id)
    return detail(session,case)

@app.get(P+'/cases')
def list_cases(user:Actor,session:DB,status:str|None=None,citizen_id:uuid.UUID|None=None,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0)):
    query=select(Case).where(Case.tenant_id==user.tenant_id)
    if user.role=='citizen': query=query.where(Case.citizen_id.in_(select(Citizen.id).where(Citizen.user_id==user.id,Citizen.tenant_id==user.tenant_id)))
    elif user.role=='helper': query=query.where(Case.citizen_id.in_(select(Consent.citizen_id).where(Consent.tenant_id==user.tenant_id,Consent.grantee_id==user.id,Consent.scope=='case:read',Consent.revoked_at.is_(None))))
    elif user.role=='officer': query=query.where(Case.assigned_officer_id==user.id)
    elif user.role not in ('admin','auditor'): fail(403,'FORBIDDEN')
    if status: query=query.where(Case.status==status)
    if citizen_id: query=query.where(Case.citizen_id==citizen_id)
    return {'items':[detail(session,c) for c in session.scalars(query.order_by(Case.created_at.desc(),Case.id).limit(limit).offset(offset))]}

@app.get(P+'/cases/review-queue')
def queue(user:Actor,session:DB,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0)):
    roles(user,'officer','admin')
    query=select(Case).where(Case.tenant_id==user.tenant_id,Case.status.in_(['cleared','human_review']))
    if user.role=='officer': query=query.where(or_(Case.assigned_officer_id==user.id,Case.assigned_officer_id.is_(None)))
    # Unassigned queue exposes metadata only, not citizen evidence.
    return {'items':[{'case_id':c.id,'status':c.status,'priority':c.priority,'revision':c.revision,'assigned_officer_id':c.assigned_officer_id,'created_at':c.created_at} for c in session.scalars(query.order_by(Case.priority.desc(),Case.created_at,Case.id).limit(limit).offset(offset))]}

@app.get(P+'/cases/{identifier}')
def get_case(identifier:uuid.UUID,user:Actor,session:DB): return detail(session,case_access(session,user,identifier))
@app.patch(P+'/cases/{identifier}')
def edit_case(identifier:uuid.UUID,body:EditCase,request:Request,user:Actor,session:DB):
    roles(user,'citizen','helper')
    case=case_access(session,user,identifier,'case:write',True); revision(case,body.expected_revision)
    if case.status not in ('draft','needs_proof'): fail(409,'INVALID_TRANSITION','Case is not editable')
    case.data=body.data.model_dump(); change(session,request,case,case.status,action='case_edited')
    return detail(session,case)
@app.post(P+'/cases/{identifier}/submit',status_code=202)
def submit(identifier:uuid.UUID,body:Revision,request:Request,user:Actor,session:DB):
    roles(user,'citizen','helper')
    case=case_access(session,user,identifier,'case:submit',True)
    if case.status in ('submitted','processing') and body.expected_revision==case.revision-1:
        job=session.scalar(select(Job).where(Job.case_id==case.id,Job.generation==case.processing_generation))
        return {'case_id':case.id,'status':case.status,'revision':case.revision,'run_id':job.id}
    revision(case,body.expected_revision)
    if case.status not in ('draft','needs_proof'): fail(409,'INVALID_TRANSITION','Case cannot be submitted')
    processing(session,get(session,Citizen,case.citizen_id,user.tenant_id))
    ClaimData.model_validate(case.data)
    case.processing_generation+=1
    change(session,request,case,'submitted',action='case_submitted')
    job=Job(tenant_id=user.tenant_id,case_id=case.id,generation=case.processing_generation)
    session.add(job); session.flush()
    return {'case_id':case.id,'status':case.status,'revision':case.revision,'run_id':job.id}
@app.post(P+'/cases/{identifier}/assign')
def assign(identifier:uuid.UUID,body:Assign,request:Request,user:Actor,session:DB):
    roles(user,'officer','admin')
    original=get(session,Case,identifier,user.tenant_id)
    get(session,Citizen,original.citizen_id,user.tenant_id,True)
    case=get(session,Case,identifier,user.tenant_id,True); revision(case,body.expected_revision)
    if case.status not in ('cleared','human_review','needs_proof'): fail(409,'INVALID_TRANSITION')
    if user.role=='officer' and (case.assigned_officer_id is not None or body.officer_id!=user.id): fail(403,'FORBIDDEN')
    officer=get(session,User,body.officer_id,user.tenant_id)
    if officer.role!='officer' or not officer.is_active: fail(422,'VALIDATION_ERROR','Choose an active officer')
    case.assigned_officer_id=officer.id; change(session,request,case,case.status,body.reason,'case_assigned')
    return detail(session,case)
@app.post(P+'/cases/{identifier}/review')
def review(identifier:uuid.UUID,body:Review,request:Request,user:Actor,session:DB):
    roles(user,'officer','admin')
    case=case_access(session,user,identifier,'case:write',True); revision(case,body.expected_revision)
    if case.status not in ('cleared','human_review'): fail(409,'INVALID_TRANSITION')
    if user.role=='admin' and not body.override_reason: fail(422,'VALIDATION_ERROR','Admin override reason required')
    if body.action=='approve':
        processing(session,get(session,Citizen,case.citizen_id,user.tenant_id))
        decision=session.scalar(select(Decision).where(Decision.case_id==case.id,Decision.processing_generation==case.processing_generation))
        if not decision: fail(409,'MISSING_EVIDENCE','No current decision')
        rule=get(session,Rule,decision.rule_version_id,user.tenant_id)
        outcome,missing=evaluate(session,case,rule,decision.payload['confidence'],decision.payload['flags'],decision.payload['identity_verified'])
        if outcome!='cleared' or missing: fail(409,'MISSING_EVIDENCE','Blocking checks require a new successful processing result')
    if body.action=='ask_proof' and not body.required_documents: fail(422,'VALIDATION_ERROR','Required document types must be specified')
    status={'approve':'approved','reject':'rejected','ask_proof':'needs_proof'}[body.action]
    case.required_documents=body.required_documents
    if status in ('approved','rejected'): case.final_outcome=status
    change(session,request,case,status,body.notes,'officer_'+body.action)
    if body.override_reason: audit(session,request,'admin_override',case.id,{'reason':body.override_reason})
    return detail(session,case)
@app.post(P+'/cases/{identifier}/close')
def close(identifier:uuid.UUID,body:Close,request:Request,user:Actor,session:DB):
    roles(user,'officer','admin')
    case=case_access(session,user,identifier,'case:write',True); revision(case,body.expected_revision)
    if case.status not in ('approved','rejected'): fail(409,'INVALID_TRANSITION')
    change(session,request,case,'closed',body.notes,'case_closed')
    return detail(session,case)
@app.get(P+'/cases/{identifier}/history')
def history(identifier:uuid.UUID,user:Actor,session:DB):
    case_access(session,user,identifier)
    return {'items':[dump(h) for h in session.scalars(select(History).where(History.case_id==identifier).order_by(History.created_at,History.id))]}

@app.post(P+'/cases/{identifier}/documents',status_code=201)
def upload(identifier:uuid.UUID,request:Request,user:Actor,session:DB,file:UploadFile=File(),type:Literal['identity_proof','income_proof']=Form(),expected_revision:int=Form()):
    roles(user,'citizen','helper')
    case=case_access(session,user,identifier,'document:upload',True); revision(case,expected_revision)
    if case.status not in ('draft','needs_proof'): fail(409,'INVALID_TRANSITION')
    content=file.file.read(5*1024*1024+1)
    if len(content)>5*1024*1024: fail(413,'FILE_TOO_LARGE','Maximum upload is 5 MiB')
    mime='application/pdf' if content.startswith(b'%PDF-') else 'image/png' if content.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if content.startswith(b'\xff\xd8\xff') else None
    if mime is None: fail(415,'UNSUPPORTED_MEDIA_TYPE','Use JPEG, PNG or PDF')
    root=Path(settings.upload_dir); root.mkdir(parents=True,exist_ok=True)
    path=root/str(uuid.uuid4()); path.write_bytes(content); path.chmod(0o600)
    doc=Document(tenant_id=user.tenant_id,case_id=case.id,file_path=str(path),type=type,content_type=mime,size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
    session.add(doc); change(session,request,case,case.status,action='document_uploaded'); session.flush()
    return {'document':dump(doc,('file_path',)),'revision':case.revision}
@app.get(P+'/cases/{identifier}/documents/{document_id}')
def download(identifier:uuid.UUID,document_id:uuid.UUID,user:Actor,session:DB):
    case_access(session,user,identifier)
    doc=get(session,Document,document_id,user.tenant_id)
    if doc.case_id!=identifier: fail(404,'NOT_FOUND')
    if not Path(doc.file_path).is_file(): fail(503,'SERVICE_UNAVAILABLE','Evidence storage unavailable')
    return FileResponse(doc.file_path,media_type=doc.content_type,filename=str(doc.id),headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

@app.get(P+'/consents')
def consents(user:Actor,session:DB,citizen_id:uuid.UUID|None=None):
    query=select(Consent).where(Consent.tenant_id==user.tenant_id)
    if user.role=='citizen': query=query.where(Consent.citizen_id.in_(select(Citizen.id).where(Citizen.user_id==user.id)))
    elif user.role=='helper': query=query.where(Consent.grantee_id==user.id)
    else: roles(user,'admin','auditor')
    if citizen_id: query=query.where(Consent.citizen_id==citizen_id)
    return {'items':[dump(c) for c in session.scalars(query.order_by(Consent.created_at.desc()))]}
@app.post(P+'/consents',status_code=201)
def grant(body:Grant,request:Request,user:Actor,session:DB):
    roles(user,'citizen')
    citizen=citizen_access(session,user,body.citizen_id,'case:write')
    if body.grantee_id:
        helper=get(session,User,body.grantee_id,user.tenant_id)
        if helper.role!='helper' or not helper.is_active: fail(422,'VALIDATION_ERROR','Grantee must be an active helper')
    old=session.scalar(select(Consent).where(Consent.citizen_id==citizen.id,Consent.scope==body.scope,Consent.grantee_id==body.grantee_id,Consent.purpose==body.purpose,Consent.revoked_at.is_(None)))
    if old: return dump(old)
    consent=Consent(tenant_id=user.tenant_id,**body.model_dump())
    session.add(consent); session.flush(); audit(session,request,'consent_granted',consent.id,{'scope':consent.scope})
    return dump(consent)
@app.post(P+'/consents/{identifier}/withdraw')
def withdraw(identifier:uuid.UUID,request:Request,user:Actor,session:DB):
    roles(user,'citizen')
    consent=get(session,Consent,identifier,user.tenant_id)
    citizen_access(session,user,consent.citizen_id,'case:write')
    if consent.revoked_at is None:
        consent.revoked_at=now(); audit(session,request,'consent_withdrawn',consent.id)
        if consent.purpose=='processing':
            for case in session.scalars(select(Case).where(Case.citizen_id==consent.citizen_id,Case.status.in_(['submitted','processing'])).order_by(Case.id).with_for_update()):
                change(session,request,case,'human_review','Processing consent withdrawn','processing_blocked')
                for job in session.scalars(select(Job).where(Job.case_id==case.id,Job.state.in_(['queued','processing']))): job.state='blocked'; job.error='CONSENT_REVOKED'
    return dump(consent)
@app.get(P+'/consents/access-check')
def access_check(citizen_id:uuid.UUID,scope:str,user:Actor,session:DB):
    if scope not in ('case:read','case:write','document:upload','case:submit','scam:check'): fail(422,'VALIDATION_ERROR','Unsupported sharing scope')
    try:
        citizen_access(session,user,citizen_id,scope)
        return {'allowed':True,'reason_code':None}
    except Problem as exc:
        if exc.status==404: raise
        return {'allowed':False,'reason_code':exc.code}

@app.get(P+'/rules')
def rules_list(user:Actor,session:DB):
    roles(user,'admin','officer','auditor')
    return {'items':[dump(r) for r in session.scalars(select(Rule).where(Rule.tenant_id==user.tenant_id,Rule.active.is_(True)))]}
@app.patch(P+'/rules/{identifier}',status_code=201)
def publish(identifier:uuid.UUID,body:Publish,request:Request,user:Actor,session:DB):
    roles(user,'admin')
    old=get(session,Rule,identifier,user.tenant_id,True)
    if not old.active or old.version!=body.expected_version: fail(409,'RULE_VERSION_CONFLICT','Reload active policy')
    old.active=False; session.flush()
    rule=Rule(tenant_id=user.tenant_id,policy_id=old.policy_id,rule_name=old.rule_name,version=old.version+1,conditions_json=body.conditions_json.model_dump(),active=True)
    session.add(rule); session.flush(); audit(session,request,'rule_published',rule.id,{'reason':body.reason,'previous_version':old.version})
    return dump(rule)
@app.get(P+'/rules/{identifier}/history')
def rule_history(identifier:uuid.UUID,user:Actor,session:DB):
    roles(user,'admin','officer','auditor')
    rule=get(session,Rule,identifier,user.tenant_id)
    return {'items':[dump(r) for r in session.scalars(select(Rule).where(Rule.tenant_id==user.tenant_id,Rule.policy_id==rule.policy_id).order_by(Rule.version.desc()))]}
@app.post(P+'/rules/evaluate')
def rule_evaluate(body:CaseRef,user:Actor,session:DB):
    roles(user,'admin','officer')
    case=case_access(session,user,body.case_id)
    rule=active_rule(session,user.tenant_id)
    # Preview cannot assert identity or replace an authoritative processing decision.
    route,missing=evaluate(session,case,rule,0,[],False)
    return {'case_id':case.id,'route':route,'rule_version':rule.version,'rule_version_id':rule.id,'missing_evidence':missing,'preview':True}

@app.get(P+'/audit-logs')
def audit_logs(user:Actor,session:DB,action:str|None=None,resource:str|None=None,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0)):
    roles(user,'admin','auditor')
    query=select(Audit).where(Audit.tenant_id==user.tenant_id)
    if action: query=query.where(Audit.action==action)
    if resource: query=query.where(Audit.resource==resource)
    return {'items':[dump(a) for a in session.scalars(query.order_by(Audit.created_at.desc(),Audit.id).limit(limit).offset(offset))]}
@app.get(P+'/cases/{identifier}/decision-trace')
def trace(identifier:uuid.UUID,user:Actor,session:DB,decision_id:uuid.UUID|None=None):
    roles(user,'admin','auditor','officer'); case_access(session,user,identifier)
    query=select(Decision).where(Decision.case_id==identifier,Decision.tenant_id==user.tenant_id)
    if decision_id: query=query.where(Decision.id==decision_id)
    decision=session.scalar(query.order_by(Decision.created_at.desc()))
    if not decision: fail(404,'NOT_FOUND','No decision available')
    return dump(decision)
@app.post(P+'/scam-checks',status_code=201)
def scam(body:Scam,request:Request,user:Actor,session:DB):
    citizen=citizen_access(session,user,body.citizen_id,'scam:check'); processing(session,citizen)
    payload=ai_call('/internal/ai/scam-check',{'text':body.text})
    if payload.get('label') not in ('likely_scam','uncertain','no_scam_indicators') or not isinstance(payload.get('confidence'),(float,int)) or not 0<=payload['confidence']<=1 or not isinstance(payload.get('indicators'),list): fail(503,'SERVICE_UNAVAILABLE','Invalid AI response')
    row=ScamCheck(tenant_id=user.tenant_id,citizen_id=citizen.id,payload={'text':body.text,**payload})
    session.add(row); session.flush(); audit(session,request,'scam_checked',row.id,actor_type='ai')
    return dump(row)
@app.get(P+'/scam-checks/{identifier}')
def scam_result(identifier:uuid.UUID,user:Actor,session:DB):
    row=get(session,ScamCheck,identifier,user.tenant_id); citizen_access(session,user,row.citizen_id,'scam:check')
    return dump(row)
@app.get(P+'/metrics/summary')
def metrics(user:Actor,session:DB):
    roles(user,'admin','auditor')
    counts=session.execute(select(Case.status,func.count()).where(Case.tenant_id==user.tenant_id).group_by(Case.status)).all()
    return {'cases_by_status':dict(counts),'total_cases':sum(count for _,count in counts)}

# Member 3 consumes these durable-job endpoints. Keys are server-only.
@app.get('/internal/jobs')
def jobs(service:Service,session:DB,limit:int=Query(20,ge=1,le=100)):
    return {'items':[dump(j) for j in session.scalars(select(Job).where(Job.state=='queued').order_by(Job.created_at).limit(limit))]}

def locked_run(session,identifier):
    job=session.get(Job,identifier)
    if not job: fail(404,'NOT_FOUND')
    case=get(session,Case,job.case_id,job.tenant_id)
    citizen=get(session,Citizen,case.citizen_id,job.tenant_id,True)
    case=get(session,Case,case.id,job.tenant_id,True)
    job=get(session,Job,identifier,job.tenant_id,True)
    return job,case,citizen

@app.post('/internal/jobs/{identifier}/start')
def start_job(identifier:uuid.UUID,request:Request,service:Service,session:DB):
    job,case,citizen=locked_run(session,identifier)
    request.state.tenant_id=case.tenant_id
    if job.generation!=case.processing_generation or case.status not in ('submitted','processing'): fail(409,'CASE_VERSION_CONFLICT','Job no longer current')
    processing(session,citizen)
    if job.state=='queued':
        rule=active_rule(session,case.tenant_id); job.rule_version_id=rule.id; job.state='processing'
        change(session,request,case,'processing',action='agent_started')
        audit(session,request,'agent_started',case.id,actor_type='agent')
    elif job.state!='processing': fail(409,'CONFLICT','Run is not executable')
    rule=get(session,Rule,job.rule_version_id,case.tenant_id)
    return {'run':dump(job),'case':detail(session,case),'rule':dump(rule),'citizen':dump(citizen)}
@app.post('/internal/jobs/{identifier}/decision')
def record_decision(identifier:uuid.UUID,body:Result,request:Request,service:Service,session:DB):
    job,case,citizen=locked_run(session,identifier)
    request.state.tenant_id=case.tenant_id
    processing(session,citizen)
    old=session.scalar(select(Decision).where(Decision.case_id==case.id,Decision.processing_generation==job.generation))
    if old:
        if old.payload.get('submitted_result')!=body.model_dump(mode='json'): fail(409,'IDEMPOTENCY_CONFLICT','Different result already recorded')
        return dump(old)
    if job.generation!=case.processing_generation or job.state!='processing' or case.status!='processing': fail(409,'CASE_VERSION_CONFLICT')
    rule=get(session,Rule,job.rule_version_id,case.tenant_id)
    if body.rule_version!=rule.version: fail(409,'RULE_VERSION_CONFLICT')
    route,missing=evaluate(session,case,rule,body.confidence,body.flags,body.identity_verified)
    # Never upgrade an AI recommendation to a less conservative route.
    rank={'cleared':0,'needs_proof':1,'human_review':2}
    if rank[body.route]>rank[route]: route=body.route
    payload=body.model_dump(mode='json'); payload['submitted_result']=body.model_dump(mode='json'); payload['route']=route
    if route!=body.route: payload['user_explanation']='Additional review or evidence is required by platform policy.'
    decision=Decision(tenant_id=case.tenant_id,case_id=case.id,processing_generation=job.generation,rule_version_id=rule.id,payload=payload)
    session.add(decision); case.required_documents=missing; job.state='completed'
    change(session,request,case,route,action='decision_recorded'); audit(session,request,'ai_decision',case.id,{'run_id':str(job.id),'rule_version':rule.version},actor_type='ai')
    session.flush(); return dump(decision)
@app.post('/internal/jobs/{identifier}/fail')
def fail_job(identifier:uuid.UUID,request:Request,service:Service,session:DB):
    job,case,citizen=locked_run(session,identifier)
    request.state.tenant_id=case.tenant_id
    if job.state in ('completed','blocked','failed'): return dump(job)
    job.state='failed'; job.error='SERVICE_UNAVAILABLE'
    if job.generation==case.processing_generation and case.status in ('submitted','processing'): change(session,request,case,'human_review','Processing service unavailable','agent_failed')
    audit(session,request,'agent_failed',case.id,actor_type='agent')
    return dump(job)
@app.get('/internal/cases/{identifier}/payment-authorization')
def payment_authorization(identifier:uuid.UUID,service:Service,session:DB):
    case=session.get(Case,identifier)
    if not case: fail(404,'NOT_FOUND')
    return {'case_id':case.id,'approved':case.final_outcome=='approved' and case.status in ('approved','closed'),'prototype':True}
