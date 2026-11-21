"""Initial platform schema, manually authored; never run on application startup."""
from alembic import op
from migrations.platform_0001 import Base
revision='0001'
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    Base.metadata.create_all(op.get_bind())
    # Disable direct browser/PostgREST access; FastAPI owns authorization.
    for table in Base.metadata.sorted_tables:
        op.execute(f'REVOKE ALL ON TABLE "{table.name}" FROM anon, authenticated')
        op.execute(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY')
    for table in Base.metadata.sorted_tables:
        op.execute(f'ALTER TABLE "{table.name}" ADD CONSTRAINT "uq_{table.name}_tenant_id" UNIQUE (tenant_id,id)')
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            for fk in column.foreign_keys:
                target = fk.column.table.name
                op.execute(f'ALTER TABLE "{table.name}" ADD CONSTRAINT "fk_{table.name}_{column.name}_tenant" FOREIGN KEY (tenant_id,"{column.name}") REFERENCES "{target}" (tenant_id,id)')
    op.execute("ALTER TABLE users ADD CONSTRAINT valid_role CHECK (role IN ('citizen','helper','officer','admin','auditor'))")
    op.execute("ALTER TABLE cases ADD CONSTRAINT valid_status CHECK (status IN ('draft','submitted','processing','cleared','needs_proof','human_review','approved','rejected','closed'))")
    op.execute("ALTER TABLE consents ADD CONSTRAINT valid_consent_target CHECK ((grantee_id IS NOT NULL AND purpose IS NULL AND scope IN ('case:read','case:write','document:upload','case:submit','scam:check')) OR (grantee_id IS NULL AND purpose = 'processing' AND scope IN ('identity:verify','ai:process')))")
    op.execute('CREATE UNIQUE INDEX active_sharing_consent ON consents (tenant_id,citizen_id,grantee_id,scope) WHERE revoked_at IS NULL AND grantee_id IS NOT NULL')
    op.execute('CREATE UNIQUE INDEX active_processing_consent ON consents (tenant_id,citizen_id,purpose,scope) WHERE revoked_at IS NULL AND purpose IS NOT NULL')

def downgrade():
    Base.metadata.drop_all(op.get_bind())
