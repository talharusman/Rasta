"""Add the Member 3 queue and provider tables and preserve legacy runs."""
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

# Snapshot of the nine Member 3 tables at integration time.
TABLES = (
    'agent_runs',
    'jobs',
    'mock_accounts',
    'mock_fixture_state',
    'mock_identity_records',
    'mock_sms_messages',
    'mock_transactions',
    'payment_requests',
    'worker_heartbeat',
)

DDL = (
    """CREATE TABLE agent_runs (
	id VARCHAR(36) NOT NULL, 
	case_id VARCHAR(64) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	mode VARCHAR(16) NOT NULL, 
	steps JSON NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	error TEXT, 
	triggered_by VARCHAR(64), 
	PRIMARY KEY (id)
)""",
    """CREATE INDEX ix_agent_runs_case_id ON agent_runs (case_id)""",
    """CREATE UNIQUE INDEX uq_agent_runs_one_running ON agent_runs (case_id) WHERE status = 'running'""",
    """REVOKE ALL ON TABLE agent_runs FROM anon, authenticated""",
    """ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY""",
    """CREATE TABLE jobs (
	id VARCHAR(36) NOT NULL, 
	kind VARCHAR(64) NOT NULL, 
	payload JSON NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	attempts INTEGER NOT NULL, 
	max_attempts INTEGER NOT NULL, 
	run_after TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_error TEXT, 
	dedupe_key VARCHAR(128), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (dedupe_key)
)""",
    """CREATE INDEX ix_jobs_due ON jobs (status, run_after)""",
    """CREATE INDEX ix_jobs_kind ON jobs (kind)""",
    """REVOKE ALL ON TABLE jobs FROM anon, authenticated""",
    """ALTER TABLE jobs ENABLE ROW LEVEL SECURITY""",
    """CREATE TABLE mock_accounts (
	acct VARCHAR(32) NOT NULL, 
	holder_nm VARCHAR(120) NOT NULL, 
	cit_id VARCHAR(32), 
	PRIMARY KEY (acct)
)""",
    """REVOKE ALL ON TABLE mock_accounts FROM anon, authenticated""",
    """ALTER TABLE mock_accounts ENABLE ROW LEVEL SECURITY""",
    """CREATE TABLE mock_fixture_state (
	id SERIAL NOT NULL, 
	state JSON NOT NULL, 
	PRIMARY KEY (id)
)""",
    """REVOKE ALL ON TABLE mock_fixture_state FROM anon, authenticated""",
    """ALTER TABLE mock_fixture_state ENABLE ROW LEVEL SECURITY""",
    """CREATE TABLE mock_identity_records (
	cit_id VARCHAR(32) NOT NULL, 
	full_nm VARCHAR(120) NOT NULL, 
	father_nm VARCHAR(120), 
	birth_dt VARCHAR(10), 
	gndr VARCHAR(1), 
	dist VARCHAR(60), 
	rec_status VARCHAR(16) NOT NULL, 
	PRIMARY KEY (cit_id)
)""",
    """REVOKE ALL ON TABLE mock_identity_records FROM anon, authenticated""",
    """ALTER TABLE mock_identity_records ENABLE ROW LEVEL SECURITY""",
    """CREATE TABLE mock_sms_messages (
	msg_id VARCHAR(40) NOT NULL,
	idempotency_key VARCHAR(128), 
	to_number VARCHAR(32) NOT NULL, 
	text TEXT NOT NULL, 
	ref VARCHAR(64), 
	dlr VARCHAR(8) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (msg_id),
	UNIQUE (idempotency_key)
)""",
    """REVOKE ALL ON TABLE mock_sms_messages FROM anon, authenticated""",
    """ALTER TABLE mock_sms_messages ENABLE ROW LEVEL SECURITY""",
    """CREATE TABLE mock_transactions (
	id SERIAL NOT NULL, 
	txn_ref VARCHAR(40) NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	case_id VARCHAR(64) NOT NULL, 
	amount NUMERIC(12, 2) NOT NULL, 
	account_id VARCHAR(32) NOT NULL, 
	approval_ref VARCHAR(128) NOT NULL, 
	status VARCHAR(8) NOT NULL, 
	rsn_cd VARCHAR(16), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (txn_ref), 
	UNIQUE (idempotency_key)
)""",
    """REVOKE ALL ON TABLE mock_transactions FROM anon, authenticated""",
    """ALTER TABLE mock_transactions ENABLE ROW LEVEL SECURITY""",
    """CREATE TABLE payment_requests (
	id SERIAL NOT NULL, 
	case_id VARCHAR(64) NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	amount NUMERIC(12, 2) NOT NULL, 
	account_id VARCHAR(32) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	transaction_id VARCHAR(64), 
	attempts INTEGER NOT NULL, 
	last_error TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (case_id), 
	UNIQUE (idempotency_key)
)""",
    """REVOKE ALL ON TABLE payment_requests FROM anon, authenticated""",
    """ALTER TABLE payment_requests ENABLE ROW LEVEL SECURITY""",
    """CREATE TABLE worker_heartbeat (
	id SERIAL NOT NULL, 
	last_seen TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)""",
    """REVOKE ALL ON TABLE worker_heartbeat FROM anon, authenticated""",
    """ALTER TABLE worker_heartbeat ENABLE ROW LEVEL SECURITY""",
)


def upgrade():
    op.rename_table('jobs', 'platform_processing_jobs')
    op.execute('ALTER TABLE platform_processing_jobs RENAME CONSTRAINT jobs_pkey TO platform_processing_jobs_pkey')
    op.execute('ALTER TABLE platform_processing_jobs ADD COLUMN submission_revision integer')
    op.execute('ALTER TABLE cases ADD COLUMN approved_amount integer')
    op.execute('ALTER TABLE notifications ADD COLUMN provider_message_id varchar(80)')
    for statement in DDL:
        op.execute(statement)
    op.execute("""
        INSERT INTO jobs (id, kind, payload, status, attempts, max_attempts, run_after,
                          dedupe_key, created_at, updated_at)
        SELECT replace(ledger.id::text, '-', ''), 'process_case',
               json_build_object('case_id', cases.id::text, 'generation', ledger.generation),
               'queued', 0, 4, now(),
               'process-' || cases.id::text || '-' || ledger.generation, now(), now()
        FROM platform_processing_jobs ledger JOIN cases ON cases.id = ledger.case_id
        WHERE cases.status = 'submitted' AND ledger.generation = cases.processing_generation
    """)
    op.execute("""
        WITH interrupted AS (
            UPDATE cases SET status = 'human_review', revision = revision + 1
            WHERE status = 'processing' RETURNING id, tenant_id
        ), history AS (
            INSERT INTO case_history (id, tenant_id, created_at, case_id, action, previous_status, status, notes)
            SELECT gen_random_uuid(), tenant_id, now(), id, 'legacy_processing_interrupted',
                   'processing', 'human_review', 'Processing interrupted during queue upgrade'
            FROM interrupted
        )
        INSERT INTO audit_logs (id, tenant_id, created_at, actor_type, action, resource,
                                outcome, request_id, details)
        SELECT gen_random_uuid(), tenant_id, now(), 'system', 'legacy_processing_interrupted',
               id::text, 'success', gen_random_uuid()::text, '{}'::jsonb FROM interrupted
    """)
    op.execute("""
        UPDATE platform_processing_jobs SET state = 'failed', error = 'Legacy processing interrupted'
        WHERE state = 'processing'
    """)


def downgrade():
    raise RuntimeError('Queue cutover is forward-only. Restore the pre-upgrade backup to roll back.')
