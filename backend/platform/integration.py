"""Persistence boundary for the queue worker and case agent."""
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select

from ai.decision import explain

from .models import Audit, Case, Citizen, Consent, Decision, Document, Job, Notification, Rule
from .services import (
    Actor, active_rule, change, evaluate, factory, fail, get_resource, roles, settings,
)
from app.jobs.queue import enqueue_notification
from app.jobs.models import Job as QueueJob
from app.integrations.providers.models import PaymentRequest


def _uuid(value):
    return UUID(str(value))


def _request(case):
    return SimpleNamespace(state=SimpleNamespace(tenant_id=case.tenant_id, request_id=str(uuid4())))


def _case(session, case_id, lock=False):
    try:
        identifier = _uuid(case_id)
    except ValueError:
        fail(422, 'VALIDATION_ERROR', 'Invalid case ID')
    case = session.get(Case, identifier)
    if case is None:
        fail(404, 'NOT_FOUND', 'Case not found')
    if lock:
        get_resource(session, Citizen, case.citizen_id, case.tenant_id, True)
        case = session.scalar(select(Case).where(Case.id == case.id).with_for_update()
                              .execution_options(populate_existing=True))
    return case


def get_case(case_id):
    with factory()() as session:
        case = _case(session, case_id)
        docs = session.scalars(select(Document).where(
            Document.case_id == case.id, Document.tenant_id == case.tenant_id,
        ).order_by(Document.created_at.desc(), Document.id.desc()))
        latest = {}
        for doc in docs:
            latest.setdefault(doc.type, {'id': str(doc.id), 'type': doc.type, 'content_type': doc.content_type})
        return {
            'id': str(case.id), 'status': case.status, 'citizen_id': str(case.citizen_id),
            'tenant_id': str(case.tenant_id), 'claim_type': case.claim_type,
            'household_size': case.data.get('household_size'), 'required_documents': case.required_documents,
            'helper_id': str(case.helper_id) if case.helper_id else None,
            'mock_identity_id': case.data['mock_identity_id'], 'applicant_name': case.data['name'],
            'monthly_income': case.data['monthly_income'], 'account_id': case.data['payment_account'],
            'citizen_phone': case.data.get('citizen_phone'), 'approved_amount': case.approved_amount,
            'submission_count': case.processing_generation,
            'documents': list(latest.values()),
        }


def _consent(session, citizen_id, scope, helper_id=None):
    rows = session.scalars(select(Consent).where(
        Consent.citizen_id == citizen_id, Consent.scope == scope,
        Consent.grantee_id == helper_id, Consent.purpose == (None if helper_id else 'processing'),
    )).all()
    if any(row.revoked_at is None for row in rows):
        return {'granted': True, 'reason': 'ok'}
    return {'granted': False, 'reason': 'CONSENT_REVOKED' if rows else 'CONSENT_REQUIRED'}


def check_consent(citizen_id, grantee_id, scope):
    from app.agent.consent_config import PROCESSING_DEPARTMENT_ID, PROCESSING_SCOPE

    if scope != PROCESSING_SCOPE:
        return {'granted': False, 'reason': 'CONSENT_REQUIRED'}
    with factory()() as session:
        citizen_id = _uuid(citizen_id)
        if grantee_id == PROCESSING_DEPARTMENT_ID:
            for required in ('identity:verify', 'ai:process'):
                result = _consent(session, citizen_id, required)
                if not result['granted']:
                    return result
            return result
        return _consent(session, citizen_id, 'case:submit', _uuid(grantee_id))


def _guard(session, case):
    grants = [_consent(session, case.citizen_id, scope) for scope in ('identity:verify', 'ai:process')]
    if case.helper_id:
        grants.append(_consent(session, case.citizen_id, 'case:submit', case.helper_id))
    for grant in grants:
        if not grant['granted']:
            fail(403, grant['reason'], 'Processing consent is unavailable')


def _ledger(session, case, generation, states):
    if generation != case.processing_generation or case.status not in states:
        fail(409, 'CASE_VERSION_CONFLICT', 'Processing generation is no longer current')
    run = session.scalar(select(Job).where(Job.case_id == case.id, Job.generation == generation))
    if run is None:
        fail(409, 'CASE_VERSION_CONFLICT', 'Processing generation does not exist')
    return run


def check_processing(case_id, generation):
    with factory()() as session:
        case = _case(session, case_id, lock=True)
        _ledger(session, case, generation, ('processing',))
        _guard(session, case)


def start_processing(case_id, generation):
    with factory().begin() as session:
        case = _case(session, case_id, lock=True)
        run = _ledger(session, case, generation, ('submitted', 'processing'))
        _guard(session, case)
        if case.status == 'submitted':
            run.rule_version_id = active_rule(session, case.tenant_id).id
            run.state = 'processing'
            change(session, _request(case), case, 'processing', action='agent_started', actor_type='agent')


def get_active_rules(case_id, generation=None):
    with factory()() as session:
        case = _case(session, case_id)
        run = _ledger(session, case, generation, ('processing',))
        rule = get_resource(session, Rule, run.rule_version_id, case.tenant_id)
        return {**rule.conditions_json, 'version': rule.version, 'rules': [
            {'id': 'income_cap', 'field': 'monthly_income', 'op': 'lte',
             'value': rule.conditions_json['max_monthly_income']},
        ]}


def _notify(session, case, message, key, *, enqueue_sms=True):
    old = session.scalar(select(Notification).where(Notification.deduplication_key == key))
    if old:
        return str(old.id)
    citizen = get_resource(session, Citizen, case.citizen_id, case.tenant_id)
    row = Notification(case_id=case.id, tenant_id=case.tenant_id, recipient_id=citizen.user_id,
                       message=message, delivery_state='created', deduplication_key=key)
    session.add(row)
    session.flush()
    phone = case.data.get('citizen_phone')
    if phone and enqueue_sms:
        enqueue_notification(str(case.id), phone, message, key, db=session, notification_id=str(row.id))
    return str(row.id)


def notify_review(session, case, message):
    _notify(session, case, message, f'review-{case.id}-{case.revision}')


def create_notification(case_id, recipient, message, key=None):
    with factory().begin() as session:
        case = _case(session, case_id, lock=True)
        if recipient not in (case.data.get('citizen_phone'), str(case.citizen_id)):
            fail(403, 'FORBIDDEN', 'Notification recipient does not match the case')
        return _notify(session, case, message, key or f'notification-{uuid4()}', enqueue_sms=False)


def update_notification_state(notification_id, state, message_id=None):
    if state not in ('created', 'sent', 'delivered', 'resent', 'failed'):
        raise ValueError('Unknown notification state')
    with factory().begin() as session:
        row = session.get(Notification, _uuid(notification_id), with_for_update=True)
        if row is None:
            fail(404, 'NOT_FOUND', 'Notification not found')
        if state in ('sent', 'resent'):
            if row.provider_message_id == message_id and row.delivery_state in ('delivered', 'failed'):
                return
            if row.delivery_state != state or row.provider_message_id != message_id:
                row.attempts += 1
        row.delivery_state = state
        if message_id:
            row.provider_message_id = message_id


def record_decision(case_id, decision):
    with factory().begin() as session:
        case = _case(session, case_id, lock=True)
        generation = decision['generation']
        old = session.scalar(select(Decision).where(
            Decision.case_id == case.id, Decision.processing_generation == generation,
        ))
        if old is not None and old.payload.get('run_id') == decision['run_id']:
            return old.payload
        run = _ledger(session, case, generation, ('processing',))
        _guard(session, case)
        rule = get_resource(session, Rule, run.rule_version_id, case.tenant_id)
        if decision['rule_version'] is not None and str(decision['rule_version']) != str(rule.version):
            fail(409, 'RULE_VERSION_CONFLICT')
        payload = dict(decision)
        evidence = payload['auditor_trace']['steps'].get('verify_mock_identity') or {}
        payload['identity_verified'] = evidence.get('status') == 'verified'
        policy_route, missing = evaluate(session, case, rule, payload['confidence'],
                                         payload['flags'], payload['identity_verified'])
        rank = {'cleared': 0, 'needs_proof': 1, 'human_review': 2}
        route = max(payload['route'], policy_route, key=rank.__getitem__)
        document_types = {'identity_proof', 'income_proof'}
        requested = set(payload.get('requested_documents', [])) & document_types
        payload['missing_evidence'] = sorted(set(payload['missing_evidence']) | set(missing) | requested)
        if route != payload['route'] or not payload.get('user_explanation_ur'):
            explanation_flags = list(payload['flags'])
            if missing and 'required_proof_missing' not in explanation_flags:
                explanation_flags.append('required_proof_missing')
            payload.update({key: value for key, value in explain(route, explanation_flags).items()
                            if key in ('user_explanation', 'user_explanation_ur')})
        payload.update(route=route, rule_version=rule.version)
        case.required_documents = sorted(set(missing) | requested)
        if route == 'needs_proof' and not case.required_documents:
            case.required_documents = ['identity_proof']
        session.add(Decision(tenant_id=case.tenant_id, case_id=case.id,
                             processing_generation=generation, rule_version_id=rule.id, payload=payload))
        run.state = 'completed'
        change(session, _request(case), case, route,
               payload.get('officer_note', '') if route == 'human_review' else '',
               'decision_recorded', actor_type='agent')
        _notify(session, case, payload['user_explanation'], f'result-{case.id}-{generation}')
        return payload


def stop_processing(case_id, generation, note):
    with factory().begin() as session:
        case = _case(session, case_id, lock=True)
        if generation != case.processing_generation or case.status not in ('submitted', 'processing'):
            return case.status
        run = _ledger(session, case, generation, ('submitted', 'processing'))
        run.state, run.error = 'failed', note[:2000]
        change(session, _request(case), case, 'human_review', note, 'agent_failed', actor_type='agent')
        return case.status


def transition_case(case_id, to_status, actor, note=''):
    if actor != 'agent' or to_status != 'processing':
        fail(409, 'INVALID_TRANSITION', 'Agent results must use the generation-aware bridge')
    return start_processing(case_id, get_case(case_id)['submission_count'])


def log_audit(actor_type, actor_id, action, resource, metadata=None):
    metadata = dict(metadata or {})
    with factory().begin() as session:
        case_id = resource.removeprefix('case:') if resource.startswith('case:') else metadata.get('case_id')
        try:
            case = session.get(Case, _uuid(case_id)) if case_id else None
        except ValueError:
            case = None
        try:
            actor_uuid = _uuid(actor_id)
        except ValueError:
            actor_uuid = None
        tenant = case.tenant_id if case else settings.demo_tenant_id
        session.add(Audit(tenant_id=tenant, actor_id=actor_uuid, actor_type=actor_type,
                          action=action, resource=resource[:120], request_id=str(uuid4()),
                          details={'service_actor': actor_id, **metadata}))


def require_admin(user: Actor):
    roles(user, 'admin')
    return {'id': str(user.id), 'tenant_id': str(user.tenant_id)}


def payment_summary(session, case):
    request = session.scalar(select(PaymentRequest).where(PaymentRequest.case_id == str(case.id)))
    if request and request.status == 'success':
        return {'status': 'confirmed', 'transaction_id': request.transaction_id, 'amount': float(request.amount)}
    jobs = session.scalars(select(QueueJob).where(
        QueueJob.dedupe_key.in_([f'disburse-{case.id}', f'reconcile-{case.id}']),
    )).all()
    if not jobs and request is None:
        return None
    if request and request.status in ('requested', 'pending', 'unknown'):
        status = 'pending'
    elif any(job.status in ('queued', 'running') for job in jobs):
        status = 'queued'
    else:
        status = 'failed'
    return {'status': status, 'transaction_id': None, 'amount': case.approved_amount}
