"""Queue lease columns, usage deduplication, and enforceable RLS policies.

0001 enabled row-level security but left three gaps: the table owner was still exempt
(`FORCE` was missing), policies had no `WITH CHECK` so a write could place a row in
another tenant, and membership lookup was impossible because resolving a workspace
requires reading the very table the workspace policy guards.
"""
from alembic import op

revision = "20260824_0002"
down_revision = "20260824_0001"
branch_labels = None
depends_on = None

TENANT_TABLES = ("workspaces", "memberships", "usage_events", "jobs")


def upgrade() -> None:
    op.execute("""
        ALTER TABLE jobs ADD COLUMN locked_by varchar(120);
    """)
    op.execute("""
        ALTER TABLE jobs ADD COLUMN heartbeat_at timestamptz;
    """)
    op.execute("""
        ALTER TABLE jobs ADD COLUMN max_attempts integer NOT NULL DEFAULT 5;
    """)
    op.execute("""
        ALTER TABLE usage_events ADD COLUMN dedupe_key varchar(160);
    """)
    op.execute("""
        -- NULL dedupe keys never compare equal, so unkeyed events stay insertable.
        ALTER TABLE usage_events
            ADD CONSTRAINT uq_usage_events_dedupe UNIQUE (workspace_id, dedupe_key);
    """)
    op.execute("""
        CREATE INDEX ix_jobs_heartbeat ON jobs(heartbeat_at);
    """)
    # The cost summary reads one workspace over a window; the bare workspace index
    # from 0001 is a prefix of this one and would only be dead weight.
    op.execute("""
        DROP INDEX IF EXISTS ix_usage_events_workspace;
    """)
    op.execute("""
        CREATE INDEX ix_usage_events_workspace_created
            ON usage_events(workspace_id, created_at);
    """)

    # Tenancy predicates live in one place so every policy reads the same way.
    op.execute("""
        CREATE OR REPLACE FUNCTION app_current_workspace() RETURNS uuid
        LANGUAGE sql STABLE
        SET search_path = pg_catalog
        AS $$ SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid $$;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION app_current_user() RETURNS uuid
        LANGUAGE sql STABLE
        SET search_path = pg_catalog
        AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;
    """)

    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # Without FORCE the table owner — which is the migration role — bypasses RLS,
        # so the "second boundary" would be off in exactly the deployment that matters.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY tenant_isolation ON workspaces
            USING (id = app_current_workspace())
            WITH CHECK (id = app_current_workspace());
    """)
    # Read own membership rows before a workspace is pinned; write only inside one.
    op.execute("""
        CREATE POLICY tenant_isolation ON memberships
            USING (workspace_id = app_current_workspace() OR user_id = app_current_user())
            WITH CHECK (workspace_id = app_current_workspace());
    """)
    op.execute("""
        CREATE POLICY tenant_isolation ON usage_events
            USING (workspace_id = app_current_workspace())
            WITH CHECK (workspace_id = app_current_workspace());
    """)
    op.execute("""
        CREATE POLICY tenant_isolation ON jobs
            USING (workspace_id = app_current_workspace())
            WITH CHECK (workspace_id = app_current_workspace());
    """)


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE workspaces DISABLE ROW LEVEL SECURITY")
    op.execute("""
        DROP FUNCTION IF EXISTS app_current_workspace();
    """)
    op.execute("""
        DROP FUNCTION IF EXISTS app_current_user();
    """)
    op.execute("""
        DROP INDEX IF EXISTS ix_jobs_heartbeat;
    """)
    op.execute("""
        DROP INDEX IF EXISTS ix_usage_events_workspace_created;
    """)
    op.execute("""
        CREATE INDEX ix_usage_events_workspace ON usage_events(workspace_id);
    """)
    op.execute("""
        ALTER TABLE usage_events DROP CONSTRAINT IF EXISTS uq_usage_events_dedupe;
    """)
    op.execute("""
        ALTER TABLE usage_events DROP COLUMN IF EXISTS dedupe_key;
    """)
    op.execute("""
        ALTER TABLE jobs DROP COLUMN IF EXISTS max_attempts;
    """)
    op.execute("""
        ALTER TABLE jobs DROP COLUMN IF EXISTS heartbeat_at;
    """)
    op.execute("""
        ALTER TABLE jobs DROP COLUMN IF EXISTS locked_by;
    """)
    for table in ("memberships", "usage_events", "jobs"):
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)"
        )
