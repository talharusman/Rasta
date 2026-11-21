"""Exercise the shared API, real platform bridge and Member 3 worker together."""
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.agent import platform_bridge
from app.integrations.mocks.fixtures import seed_mocks
from app.integrations.mocks.models import MockSmsMessage, MockTransaction
from app.integrations.providers import registry
from app.integrations.providers.http import ServiceClient
from app.integrations.providers.identity import MockNadraIdentityProvider
from app.integrations.providers.notification import MockSmsNotificationProvider
from app.integrations.providers.payment import MockRaastPaymentProvider
from app.jobs import handlers, worker
from app.jobs.models import Job as QueueJob
from shared import db


@compiles(JSONB, 'sqlite')
def _sqlite_jsonb(_type, _compiler, **_):
    return 'JSON'


@compiles(UUID, 'sqlite')
def _sqlite_uuid(_type, _compiler, **_):
    return 'CHAR(32)'


@pytest.fixture
def live(tmp_path, monkeypatch):
    from main import app
    from rasta_platform import integration, services
    from rasta_platform.models import Citizen, Rule, User

    engine = create_engine(f'sqlite:///{tmp_path / "integrated.db"}')

    @event.listens_for(engine, 'connect')
    def disable_legacy_transactions(connection, _):
        connection.isolation_level = None

    @event.listens_for(engine, 'begin')
    def begin_transaction(connection):
        connection.exec_driver_sql('BEGIN')

    db.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(db, 'SessionLocal', factory)
    monkeypatch.setattr(services.settings, 'database_url', str(engine.url))
    monkeypatch.setattr(services.settings, 'upload_dir', str(tmp_path / 'uploads'))
    services.factory.cache_clear()
    platform_bridge.configure(integration)
    for name, value in {
        'AI_STUB': 'true', 'NADRA_MOCK_KEY': 'nadra-test', 'RAAST_MOCK_KEY': 'raast-test',
        'SMS_MOCK_KEY': 'sms-test', 'INTERNAL_SERVICE_KEY': 'internal-test', 'RUN_JOB_WORKER': 'false',
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(handlers, 'CHECK_DELIVERY_DELAY', 0)
    seed_mocks(reset=True)
    tenant = services.settings.demo_tenant_id
    with factory.begin() as session:
        actors = {role: User(id=uuid4(), tenant_id=tenant, name=role.title(), role=role)
                  for role in ('citizen', 'helper', 'officer', 'admin', 'auditor')}
        session.add_all(actors.values())
        citizen_id = uuid4()
        session.add(Citizen(id=citizen_id, tenant_id=tenant, user_id=actors['citizen'].id,
                            name='Muhammad Ali', mock_identity_id='MOCK-123456'))
        session.add(Rule(tenant_id=tenant, policy_id=uuid4(), rule_name='Relief', version=1,
                         conditions_json={'max_monthly_income': 40000,
                                          'required_documents': ['identity_proof', 'income_proof'],
                                          'clear_confidence_min': 0.95, 'proof_confidence_min': 0.70,
                                          'critical_flags': []}))

    def actor(authorization: str = Header(default='')):
        if authorization not in actors:
            raise HTTPException(401)
        return actors[authorization]

    app.dependency_overrides[services.actor] = actor
    client = TestClient(app)

    def request(method, path, role='citizen', **kwargs):
        return client.request(method, f'/api/v1{path}', headers={'Authorization': role}, **kwargs)

    def provider(service, key):
        return ServiceClient(service, 'http://mock', key, transport=httpx.ASGITransport(app=app))

    monkeypatch.setattr(registry, 'get_identity_provider', lambda: MockNadraIdentityProvider(
        provider('nadra', 'nadra-test')))
    monkeypatch.setattr(registry, 'get_payment_provider', lambda: MockRaastPaymentProvider(
        provider('raast', 'raast-test')))
    monkeypatch.setattr(registry, 'get_notification_provider', lambda: MockSmsNotificationProvider(
        provider('sms', 'sms-test')))

    def count(model):
        with factory() as session:
            return session.scalar(select(func.count()).select_from(model))

    try:
        yield request, actors, citizen_id, count
    finally:
        app.dependency_overrides.pop(services.actor, None)
        platform_bridge.configure(None)
        services.factory.cache_clear()
        engine.dispose()


def _grant(request, citizen_id, scope, **target):
    response = request('POST', '/consents', json={'citizen_id': str(citizen_id), 'scope': scope, **target})
    assert response.status_code == 201, response.text
    return response.json()['id']


def _draft(request, citizen_id, role='citizen'):
    response = request('POST', '/cases', role, json={
        'citizen_id': str(citizen_id), 'idempotency_key': str(uuid4()), 'data': {
            'name': 'Muhammad Ali', 'mock_identity_id': 'MOCK-123456', 'monthly_income': 10000,
            'household_size': 3, 'payment_account': 'MOCK-ACCOUNT-001', 'citizen_phone': '+920000000001',
        },
    })
    assert response.status_code == 201, response.text
    return response.json()


def _submit(request, case, role='citizen'):
    response = request('POST', f"/cases/{case['case_id']}/submit", role,
                       json={'expected_revision': case['revision']})
    assert response.status_code == 202, response.text
    return response.json()


def _drain():
    async def run():
        for _ in range(10):
            if not await worker.run_once():
                return
        pytest.fail('Worker did not drain the queue')
    asyncio.run(run())


def test_claim_approval_payment_and_version_trace(live):
    request, actors, citizen_id, count = live
    for scope in ('identity:verify', 'ai:process'):
        _grant(request, citizen_id, scope, purpose='processing')
    case = _draft(request, citizen_id)
    case_id = case['case_id']
    for kind in ('identity_proof', 'income_proof'):
        upload = request('POST', f'/cases/{case_id}/documents',
                         data={'type': kind, 'expected_revision': case['revision']},
                         files={'file': ('mock.pdf', b'%PDF-synthetic', 'application/pdf')})
        assert upload.status_code == 201, upload.text
        case['revision'] = upload.json()['revision']
    assert _submit(request, case)['run_id'] == _submit(request, case)['run_id']
    assert count(QueueJob) == 1
    _drain()
    assert _submit(request, case)['status'] == 'cleared'
    assert count(MockTransaction) == 0
    queued = request('GET', '/cases/review-queue', 'officer').json()['items'][0]
    assigned = request('POST', f'/cases/{case_id}/assign', 'officer', json={
        'officer_id': str(actors['officer'].id), 'expected_revision': queued['revision'], 'reason': 'Review',
    })
    assert assigned.status_code == 200, assigned.text
    review = {'action': 'approve', 'notes': 'Evidence reviewed', 'expected_revision': assigned.json()['revision']}
    approved = request('POST', f'/cases/{case_id}/review', 'officer', json=review)
    assert approved.status_code == 200, approved.text
    assert approved.json()['payment']['status'] == 'queued'
    assert request('POST', f'/cases/{case_id}/review', 'officer', json=review).status_code == 409
    _drain()
    detail = request('GET', f'/cases/{case_id}').json()
    assert detail['payment']['status'] == 'confirmed'
    assert detail['payment']['transaction_id'].startswith('RAAST-')
    assert count(MockTransaction) == 1
    assert count(MockSmsMessage) == 2
    assert {row['delivery_state'] for row in request('GET', '/notifications').json()['items']} == {'delivered'}
    assert request('GET', '/admin/jobs', 'citizen').status_code == 403
    assert request('GET', '/admin/jobs', 'admin').json()['jobs']
    policy = request('GET', '/rules', 'admin').json()['items'][0]
    published = request('PATCH', f"/rules/{policy['id']}", 'admin', json={
        'expected_version': 1,
        'conditions_json': {**policy['conditions_json'], 'max_monthly_income': 20000},
        'reason': 'Demo policy change',
    })
    assert published.status_code == 201, published.text
    trace = request('GET', f'/cases/{case_id}/decision-trace', 'auditor').json()
    assert trace['rule_version'] == 1
    assert trace['payload']['model_version'] == 'stub-v1'


def test_helper_consent_blocks_queued_processing(live):
    request, actors, citizen_id, count = live
    for scope in ('identity:verify', 'ai:process'):
        _grant(request, citizen_id, scope, purpose='processing')
    grants = {scope: _grant(request, citizen_id, scope, grantee_id=str(actors['helper'].id))
              for scope in ('case:read', 'case:write', 'case:submit')}
    case_id = _submit(request, _draft(request, citizen_id, 'helper'), 'helper')['case_id']
    platform_bridge.live_call('start_processing', case_id, 1)
    for scope in ('case:submit', 'case:read'):
        assert request('POST', f"/consents/{grants[scope]}/withdraw").status_code == 200
    assert request('GET', f'/cases/{case_id}', 'helper').json()['error']['code'] == 'CONSENT_REVOKED'
    _drain()
    assert request('GET', f'/cases/{case_id}').json()['status'] == 'human_review'
    assert count(MockTransaction) == 0


def test_needs_proof_can_be_resubmitted(live):
    request, _, citizen_id, _ = live
    for scope in ('identity:verify', 'ai:process'):
        _grant(request, citizen_id, scope, purpose='processing')
    case_id = _submit(request, _draft(request, citizen_id))['case_id']
    _drain()
    path = f'/cases/{case_id}'
    case = request('GET', path).json()
    assert case['status'] == 'needs_proof'
    assert set(case['required_documents']) == {'identity_proof', 'income_proof'}
    for kind in case['required_documents']:
        upload = request('POST', f'{path}/documents',
                         data={'type': kind, 'expected_revision': case['revision']},
                         files={'file': ('mock.pdf', b'%PDF-synthetic', 'application/pdf')})
        assert upload.status_code == 201, upload.text
        case['revision'] = upload.json()['revision']
    _submit(request, case)
    _drain()
    assert request('GET', path).json()['status'] == 'cleared'
    trace = request('GET', f'{path}/decision-trace', 'auditor').json()
    assert {d['processing_generation'] for d in trace['decisions']} == {1, 2}
