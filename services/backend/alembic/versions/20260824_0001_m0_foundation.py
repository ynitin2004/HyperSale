"""M0 workspace, usage metering, and durable job foundation."""
from alembic import op

revision = "20260824_0001"
down_revision = None
branch_labels = None
depends_on = None


TENANT_TABLES = ("memberships", "usage_events", "jobs")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("""
        CREATE TABLE workspaces (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name varchar(200) NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
    """)
    op.execute("""
        CREATE TABLE memberships (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, user_id uuid NOT NULL, role varchar(20) NOT NULL DEFAULT 'rep', created_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_membership_workspace_user UNIQUE(workspace_id, user_id));
    """)
    op.execute("""
        CREATE TABLE usage_events (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, event_type varchar(80) NOT NULL, provider varchar(80), model_id varchar(120), input_units integer NOT NULL DEFAULT 0, output_units integer NOT NULL DEFAULT 0, cost_microusd integer NOT NULL DEFAULT 0, metadata jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now());
    """)
    op.execute("""
        CREATE TABLE jobs (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, type varchar(100) NOT NULL, state varchar(20) NOT NULL DEFAULT 'queued', attempts integer NOT NULL DEFAULT 0, idempotency_key varchar(160) NOT NULL, payload jsonb NOT NULL DEFAULT '{}'::jsonb, last_error text, run_after timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), CONSTRAINT uq_job_idempotency UNIQUE(workspace_id, idempotency_key));
    """)
    op.execute("""
        CREATE INDEX ix_memberships_user ON memberships(user_id);
    """)
    op.execute("""
        CREATE INDEX ix_usage_events_workspace ON usage_events(workspace_id);
    """)
    op.execute("""
        CREATE INDEX ix_jobs_claim ON jobs(state, run_after);
    """)
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jobs, usage_events, memberships, workspaces CASCADE")

