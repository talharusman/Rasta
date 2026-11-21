import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Integer, Boolean, ForeignKey, UniqueConstraint, Index, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase): pass

def now(): return datetime.now(timezone.utc)

class Record(Base):
    __abstract__ = True
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class User(Record):
    __tablename__ = 'users'
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Citizen(Record):
    __tablename__ = 'citizens'
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    mock_identity_id: Mapped[str] = mapped_column(String(100))
    __table_args__ = (UniqueConstraint('tenant_id', 'mock_identity_id'),)

class Case(Record):
    __tablename__ = 'cases'
    citizen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('citizens.id'), index=True)
    helper_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))
    assigned_officer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    claim_type: Mapped[str] = mapped_column(String(40), default='relief_payment')
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(24), default='draft', index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    processing_generation: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    required_documents: Mapped[list] = mapped_column(JSONB, default=list)
    final_outcome: Mapped[str | None] = mapped_column(String(24))
    __table_args__ = (UniqueConstraint('tenant_id', 'created_by', 'idempotency_key'),)

class Consent(Record):
    __tablename__ = 'consents'
    citizen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('citizens.id'), index=True)
    grantee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id'))
    purpose: Mapped[str | None] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(40))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class Rule(Record):
    __tablename__ = 'rules'
    policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    rule_name: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer)
    conditions_json: Mapped[dict] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint('tenant_id', 'policy_id', 'version'), Index('one_active_policy', 'tenant_id', 'policy_id', unique=True, postgresql_where=active.is_(True)))

class Decision(Record):
    __tablename__ = 'decisions'
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('cases.id'), index=True)
    processing_generation: Mapped[int] = mapped_column(Integer)
    rule_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('rules.id'))
    payload: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint('case_id', 'processing_generation'),)

class History(Record):
    __tablename__ = 'case_history'
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('cases.id'), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(80))
    previous_status: Mapped[str | None] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24))
    notes: Mapped[str] = mapped_column(Text, default='')

class Audit(Record):
    __tablename__ = 'audit_logs'
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_type: Mapped[str] = mapped_column(String(20), default='user')
    action: Mapped[str] = mapped_column(String(100))
    resource: Mapped[str] = mapped_column(String(120))
    outcome: Mapped[str] = mapped_column(String(20), default='success')
    request_id: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)

class Document(Record):
    __tablename__ = 'case_documents'
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('cases.id'), index=True)
    file_path: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(40))
    content_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    processing_status: Mapped[str] = mapped_column(String(24), default='pending')

class Job(Record):
    __tablename__ = 'jobs'
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('cases.id'), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24), default='queued')
    rule_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('rules.id'))
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint('case_id', 'generation'),)

class ScamCheck(Record):
    __tablename__ = 'scam_checks'
    citizen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('citizens.id'))
    payload: Mapped[dict] = mapped_column(JSONB)

class Notification(Record):
    __tablename__ = 'notifications'
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('cases.id'))
    recipient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id'))
    message: Mapped[str] = mapped_column(Text)
    delivery_state: Mapped[str] = mapped_column(String(24), default='queued')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    deduplication_key: Mapped[str] = mapped_column(String(200), unique=True)
