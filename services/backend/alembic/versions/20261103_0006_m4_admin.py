"""M4: invites (D45), workspace settings and retention (D46), spend limit and audit log (D47).

Ownership (ARCHITECTURE §3): `identity` owns invites, `platform` owns workspace_settings and
audit_events, `practice` owns the new `recording_deleted_at`. All three tables are tenant tables
with ENABLE + FORCE. Two policies differ from the usual shape:
  * invites can also be read by token hash, so an invitee who is not yet a member can open a link
    without a BYPASSRLS role;
  * audit_events has SELECT and INSERT policies only, so under FORCE RLS the runtime role cannot
    update or delete an event.
"""
from alembic import op

revision = "20261103_0006"
down_revision = "20261101_0005"
branch_labels = None
depends_on = None

RUNTIME_ROLES = ("hypersale_app", "hypersale_worker")
TENANT_CHECK = "workspace_id = app_current_workspace()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE workspace_settings (
            workspace_id uuid PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
            audio_retention_days integer DEFAULT 90,
            monthly_limit_microusd bigint DEFAULT 10000000,
            record_roleplay_audio boolean NOT NULL DEFAULT true,
            updated_by uuid,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_workspace_settings_retention
                CHECK (audio_retention_days IS NULL OR audio_retention_days BETWEEN 1 AND 3650),
            CONSTRAINT ck_workspace_settings_limit
                CHECK (monthly_limit_microusd IS NULL OR monthly_limit_microusd >= 0)
        )
    """)
    op.execute("""
        CREATE TABLE invites (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            email varchar(320) NOT NULL,
            role varchar(20) NOT NULL,
            token_hash varchar(64) NOT NULL,
            created_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            accepted_at timestamptz,
            accepted_by uuid,
            revoked_at timestamptz,
            CONSTRAINT uq_invites_token_hash UNIQUE (token_hash),
            CONSTRAINT ck_invites_role CHECK (role IN ('rep', 'manager', 'owner'))
        )
    """)
    op.execute("CREATE INDEX ix_invites_workspace_created ON invites(workspace_id, created_at)")
    op.execute("""
        CREATE TABLE audit_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            actor_user_id uuid,
            action varchar(60) NOT NULL,
            target_type varchar(40) NOT NULL,
            target_id varchar(80),
            detail jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_audit_events_workspace_created ON audit_events(workspace_id, created_at)")
    op.execute("ALTER TABLE practice_sessions ADD COLUMN recording_deleted_at timestamptz")

    for table in ("workspace_settings", "invites", "audit_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for table in ("workspace_settings", "invites"):
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({TENANT_CHECK}) WITH CHECK ({TENANT_CHECK})")
    # The join page has a token but no workspace yet: the token hash alone opens that one row.
    op.execute("""
        CREATE POLICY invite_by_token ON invites FOR SELECT
            USING (token_hash = NULLIF(current_setting('app.invite_token_hash', true), ''))
    """)
    op.execute(f"CREATE POLICY audit_read ON audit_events FOR SELECT USING ({TENANT_CHECK})")
    op.execute(f"CREATE POLICY audit_append ON audit_events FOR INSERT WITH CHECK ({TENANT_CHECK})")
    # Belt and braces where the runtime roles exist: no grant to change history either.
    for role in RUNTIME_ROLES:
        op.execute(f"""
            DO $$ BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                    REVOKE UPDATE, DELETE ON audit_events FROM {role};
                END IF;
            END $$
        """)


def downgrade() -> None:
    op.execute("ALTER TABLE practice_sessions DROP COLUMN IF EXISTS recording_deleted_at")
    for table in ("audit_events", "invites", "workspace_settings"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
