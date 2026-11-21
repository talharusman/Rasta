# OWNER: Member 1
import uuid
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import main
from rasta_platform.models import User, Citizen, Case, Consent, Decision, Rule, History, Audit
from rasta_platform.services import factory, actor

client = TestClient(main.app)


def test_health():
    response = client.get("/api/platform/health")
    assert response.status_code == 200
    assert response.json()["service"] == "platform"


def test_admin_user_management():
    with factory()() as session:
        admin = session.query(User).filter_by(role="admin").first()
        officer = session.query(User).filter_by(role="officer").first()
        citizen_user = session.query(User).filter_by(role="citizen").first()

    def mock_admin(request: Request):
        request.state.actor = admin
        return admin

    main.app.dependency_overrides[actor] = mock_admin

    # Admin listing users
    res = client.get("/api/v1/users")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) >= 5

    # Citizen-linked user cannot change role away from citizen
    fail_res = client.patch(
        f"/api/v1/users/{citizen_user.id}/role",
        json={"role": "officer", "reason": "Testing invalid promotion"}
    )
    assert fail_res.status_code == 409

    # Admin cannot edit their own role
    self_res = client.patch(
        f"/api/v1/users/{admin.id}/role",
        json={"role": "officer", "reason": "Self edit"}
    )
    assert self_res.status_code == 409

    main.app.dependency_overrides.clear()


def test_unauthorized_user_access_blocked():
    with factory()() as session:
        citizen_user = session.query(User).filter_by(role="citizen").first()

    def mock_citizen(request: Request):
        request.state.actor = citizen_user
        return citizen_user

    main.app.dependency_overrides[actor] = mock_citizen

    # Citizen cannot access admin user list
    res = client.get("/api/v1/users")
    assert res.status_code == 403

    main.app.dependency_overrides.clear()


def test_helper_consent_revocation_denial():
    with factory()() as session:
        helper = session.query(User).filter_by(role="helper").first()
        citizen = session.query(Citizen).first()

        # Ensure a revoked consent exists for this helper and citizen
        consent = session.query(Consent).filter_by(
            citizen_id=citizen.id,
            grantee_id=helper.id,
            scope="case:read"
        ).first()

        if not consent:
            consent = Consent(
                tenant_id=helper.tenant_id,
                citizen_id=citizen.id,
                grantee_id=helper.id,
                scope="case:read",
                purpose=None
            )
            session.add(consent)
            session.commit()

        # Revoke consent
        consent.revoked_at = consent.created_at
        session.commit()

    def mock_helper(request: Request):
        request.state.actor = helper
        return helper

    main.app.dependency_overrides[actor] = mock_helper

    # Querying cases specifically for this citizen must actively fail with 403 CONSENT_REVOKED
    res = client.get(f"/api/v1/cases?citizen_id={citizen.id}")
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "CONSENT_REVOKED"

    main.app.dependency_overrides.clear()


def test_officer_review_terminal_idempotency_guard():
    with factory()() as session:
        officer = session.query(User).filter_by(role="officer").first()
        citizen = session.query(Citizen).first()

        # Find or create a terminal case (approved/rejected) assigned to this officer
        case = session.query(Case).filter(Case.status.in_(["approved", "rejected"])).first()
        if not case:
            case = Case(
                tenant_id=officer.tenant_id,
                citizen_id=citizen.id,
                created_by=officer.id,
                assigned_officer_id=officer.id,
                status="approved",
                final_outcome="approved",
                revision=2,
                idempotency_key=str(uuid.uuid4()),
                request_hash="dummy"
            )
            session.add(case)
            session.commit()
        else:
            case.assigned_officer_id = officer.id
            session.commit()

        case_id = case.id
        rev = case.revision

    def mock_officer(request: Request):
        request.state.actor = officer
        return officer

    main.app.dependency_overrides[actor] = mock_officer

    # Attempting to re-review an already terminal case must fail with 409
    res = client.post(
        f"/api/v1/cases/{case_id}/review",
        json={"action": "approve", "notes": "Duplicate review attempt", "expected_revision": rev}
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] in ("VALIDATION_ERROR", "INVALID_TRANSITION")

    main.app.dependency_overrides.clear()


def test_auditor_decision_trace_enriched():
    with factory()() as session:
        auditor = session.query(User).filter_by(role="auditor").first()
        citizen = session.query(Citizen).first()
        rule = session.query(Rule).filter_by(active=True).first()

        # Create or find a case with a decision
        case = session.query(Case).first()
        dec = session.query(Decision).filter_by(case_id=case.id).first()
        if not dec:
            dec = Decision(
                tenant_id=case.tenant_id,
                case_id=case.id,
                processing_generation=case.processing_generation,
                rule_version_id=rule.id,
                payload={
                    "route": "cleared",
                    "confidence": 0.95,
                    "risk_score": 0.05,
                    "flags": [],
                    "rule_version": rule.version,
                    "model_version": "prototype-1",
                    "user_explanation": "All criteria met",
                    "auditor_trace": {"verified": True}
                }
            )
            session.add(dec)
            session.commit()

        case_id = case.id

    def mock_auditor(request: Request):
        request.state.actor = auditor
        return auditor

    main.app.dependency_overrides[actor] = mock_auditor

    res = client.get(f"/api/v1/cases/{case_id}/decision-trace")
    assert res.status_code == 200
    data = res.json()
    assert "case_id" in data
    assert "decisions" in data
    assert "history" in data
    assert "audit_logs" in data
    assert "rule_version" in data

    main.app.dependency_overrides.clear()
