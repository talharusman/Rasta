"""Queue integration for optional, read-only officer assistance."""
import asyncio
import hashlib
import io
import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select

from ai import documents, llm_assist
from ai.decision import DOC_GOOD, REASONS
from ai.services import ServiceError, _read_upload
from app.agent.ai_client import stub_enabled
from app.jobs.queue import AI_ASSIST_JOB, enqueue

from .integration import _case, _guard, _uuid, _request
from .models import Case, Decision, Document
from .services import Problem, audit, factory, settings

FIXTURE_MANIFEST = Path(__file__).resolve().parents[2] / 'docs' / 'gemini-fixtures' / 'manifest.json'
OUTCOMES = {
    'cleared': 'The automated checks passed. Officer approval is still required.',
    'needs_proof': 'The case needs more supporting evidence.',
    'human_review': 'The case needs an officer review.',
}
PROOFS = {'identity_proof': 'identity proof', 'income_proof': 'income proof'}


def _enabled(tenant_id):
    return llm_assist.active_provider() is not None and not stub_enabled() and tenant_id == settings.demo_tenant_id


def schedule(session, case, payload):
    if not _enabled(case.tenant_id):
        return
    generation = case.processing_generation
    enqueue(AI_ASSIST_JOB, {'case_id': str(case.id), 'generation': generation},
            dedupe_key=f'gemini-assist-{case.id}-{generation}', max_attempts=1, db=session)
    payload['ai_assist'] = {'status': 'queued', 'provider': llm_assist.active_provider()}


def _scope(session, case_id, generation):
    if session.get(Case, _uuid(case_id)) is None:
        return None, None, None
    case = _case(session, case_id, lock=True)
    decision = session.scalar(select(Decision).where(
        Decision.case_id == case.id, Decision.tenant_id == case.tenant_id,
        Decision.processing_generation == generation,
    ).with_for_update())
    if not decision or decision.payload.get('ai_assist', {}).get('status') != 'queued':
        return case, None, None
    if not _enabled(case.tenant_id):
        return case, decision, 'disabled'
    if case.processing_generation != generation or case.status != decision.payload['route']:
        return case, decision, 'case_changed'
    try:
        _guard(session, case)
    except Problem:
        return case, decision, 'consent_unavailable'
    return case, decision, None


def _snapshot(case_id, generation):
    with factory().begin() as session:
        case, decision, reason = _scope(session, case_id, generation)
        if reason or decision is None:
            return None
        payload = decision.payload
        analyzed = payload['auditor_trace']['steps'].get('analyze_document', {}).get('documents', [])
        selected = {}
        for item in analyzed:
            kind = item.get('type')
            if kind not in PROOFS or kind in selected or item.get('status') != 'ok':
                continue
            document = session.scalar(select(Document).where(
                Document.id == _uuid(item['id']), Document.case_id == case.id,
                Document.tenant_id == case.tenant_id, Document.type == kind,
            ))
            if document is not None:
                selected[kind] = {'id': str(document.id), 'path': document.file_path, 'sha256': document.sha256}
        return {'documents': selected, 'claim': dict(case.data), 'decision': payload}


@lru_cache(maxsize=1)
def _fixtures():
    return json.loads(FIXTURE_MANIFEST.read_text())['documents']


def _approved_image(kind, document):
    try:
        # Check the stored digest before reading a file, then verify its actual bytes.
        entry = _fixtures().get(document['sha256'])
        if not entry or entry['type'] != kind:
            return None
        data = _read_upload(document['path'])
        if hashlib.sha256(data).hexdigest() != document['sha256']:
            return None
        image = documents.load_image(data)
        if documents.image_quality(image)['quality'] < DOC_GOOD:
            return None
        clean = image.convert('RGB')
        clean.thumbnail((1600, 1600))
        with io.BytesIO() as buffer:
            clean.save(buffer, format='PNG')
            return buffer.getvalue(), entry['fields']
    except (OSError, ValueError, KeyError, ServiceError, documents.DocumentError):
        return None


def _facts(payload):
    facts = {'outcome': OUTCOMES[payload['route']]}
    for flag in payload.get('flags', []):
        if flag in REASONS:
            facts[f'flag_{flag}'] = REASONS[flag][0]
    for kind, label in PROOFS.items():
        if kind in payload.get('missing_evidence', []):
            facts[f'missing_{kind}'] = f'The case needs updated {label}.'
    return facts


def _save(case_id, generation, result):
    with factory().begin() as session:
        case, decision, reason = _scope(session, case_id, generation)
        if decision is None:
            return
        if reason:
            result = {'status': 'skipped', 'reason': reason}
        decision.payload = {**decision.payload, 'ai_assist': result}
        audit(session, _request(case), 'ai_assistance_finished', case.id,
              {'generation': generation, 'status': result['status'], 'reason': result.get('reason'),
               'model': result.get('model')}, actor_type='agent')


def fail_assistance(case_id, generation):
    _save(case_id, generation, {'status': 'fallback', 'reason': 'job_incomplete'})


async def run_assistance(case_id, generation):
    async def current():
        return await asyncio.to_thread(_snapshot, case_id, generation)

    snapshot = await current()
    provider = llm_assist.active_provider()
    if provider is None:
        await asyncio.to_thread(fail_assistance, case_id, generation)
        return
    result = {'status': 'fallback', 'provider': provider, 'model': llm_assist.model_name(provider),
              'documents': [], 'requests': [], 'summary': None}
    if snapshot is not None:
        for kind, doc in snapshot['documents'].items():
            approved = await asyncio.to_thread(_approved_image, kind, doc)
            if approved is None:
                continue
            if await current() is None:
                break
            image, expected = approved
            fields, meta = await llm_assist.extract(kind, image, expected, provider=provider, model=result['model'])
            result['requests'].append({'task': kind, **meta})
            if fields is None:
                continue
            claim = {**snapshot['claim'], 'date_of_birth': snapshot['claim'].get('dob')}
            conflicts = [
                key for key, value in fields.items()
                if value is not None and claim.get(key) is not None
                and ' '.join(str(value).lower().split()) != ' '.join(str(claim[key]).lower().split())
            ]
            result['documents'].append({'document_id': doc['id'], 'type': kind, 'fields': fields,
                                        'conflicts': conflicts, 'model': meta['model']})
        if await current() is not None:
            result['summary'], meta = await llm_assist.summarize(
                _facts(snapshot['decision']), provider=provider, model=result['model'],
            )
            result['requests'].append({'task': 'summary', **meta})
            failures = [request['reason'] for request in result['requests'] if request.get('reason')]
            has_fields = any(value is not None for doc in result['documents'] for value in doc['fields'].values())
            if result['summary'] or has_fields:
                result['status'] = 'partial' if failures else 'complete'
            if failures:
                result['reason'] = failures[0]
    await asyncio.to_thread(_save, case_id, generation, result)
