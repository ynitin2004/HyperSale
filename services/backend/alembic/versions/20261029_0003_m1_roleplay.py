"""M1 roleplay loop: global catalog, practice sessions + transcript, reports + scores.

Ownership (ARCHITECTURE §3): `catalog` owns personas/scenarios/rubric_versions/drills,
`practice` owns practice_sessions/transcript_turns, `scoring` owns reports/criterion_scores.
No foreign key crosses from scoring into practice's tables beyond the session id it scores,
and no module reads another's tables directly; the FKs are integrity, not access paths.

Catalog tables are global product content (D30): RLS enabled with a read-all policy, and
the runtime role is left with SELECT only. Every tenant table gets the same ENABLE + FORCE +
USING/WITH CHECK policy shape as 0002.
"""
from alembic import op

revision = "20261029_0003"
down_revision = "20260824_0002"
branch_labels = None
depends_on = None

CATALOG_TABLES = ("personas", "rubric_versions", "scenarios", "drills")
TENANT_TABLES = ("practice_sessions", "transcript_turns", "reports", "criterion_scores")
RUNTIME_ROLES = ("hypersale_app",)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE personas (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            slug varchar(80) NOT NULL,
            name varchar(120) NOT NULL,
            title varchar(200) NOT NULL,
            company varchar(200) NOT NULL,
            voice varchar(80) NOT NULL,
            instructions text NOT NULL,
            prompt_version varchar(32) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_personas_slug_version UNIQUE (slug, prompt_version)
        )
    """)
    op.execute("""
        CREATE TABLE rubric_versions (
            version varchar(40) PRIMARY KEY,
            criteria jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE scenarios (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            slug varchar(80) NOT NULL,
            persona_id uuid NOT NULL REFERENCES personas(id),
            rubric_version varchar(40) NOT NULL REFERENCES rubric_versions(version),
            title varchar(200) NOT NULL,
            brief text NOT NULL,
            call_type varchar(40) NOT NULL,
            difficulty varchar(20) NOT NULL,
            applicable_criteria jsonb NOT NULL,
            featured boolean NOT NULL DEFAULT false,
            sort_order integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_scenarios_slug UNIQUE (slug)
        )
    """)
    op.execute("""
        CREATE TABLE drills (
            id varchar(60) PRIMARY KEY,
            criterion_id varchar(60) NOT NULL,
            title varchar(200) NOT NULL,
            instructions text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE practice_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            user_id uuid NOT NULL,
            scenario_id uuid NOT NULL REFERENCES scenarios(id),
            persona_id uuid NOT NULL REFERENCES personas(id),
            prompt_version varchar(32) NOT NULL,
            rubric_version varchar(40) NOT NULL,
            status varchar(20) NOT NULL DEFAULT 'created',
            provider varchar(40) NOT NULL,
            model_id varchar(120),
            session_ref varchar(120),
            cap_seconds integer NOT NULL,
            end_reason varchar(40),
            duration_ms integer,
            recorder_offset_ms integer,
            recording_chunks integer NOT NULL DEFAULT 0,
            recording_bytes integer NOT NULL DEFAULT 0,
            recording_mime varchar(80),
            timings jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            connected_at timestamptz,
            ended_at timestamptz
        )
    """)
    op.execute("""
        CREATE TABLE transcript_turns (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            session_id uuid NOT NULL REFERENCES practice_sessions(id) ON DELETE CASCADE,
            idx integer NOT NULL,
            speaker varchar(10) NOT NULL,
            text text NOT NULL,
            start_ms integer NOT NULL,
            end_ms integer NOT NULL,
            item_id varchar(80) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_transcript_turns_item UNIQUE (session_id, item_id),
            CONSTRAINT ck_transcript_turns_speaker CHECK (speaker IN ('rep', 'buyer'))
        )
    """)
    op.execute("""
        CREATE TABLE reports (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            session_id uuid NOT NULL REFERENCES practice_sessions(id) ON DELETE CASCADE,
            status varchar(20) NOT NULL DEFAULT 'pending',
            rubric_version varchar(40) NOT NULL,
            prompt_version varchar(40),
            model_id varchar(120),
            metrics_version varchar(20) NOT NULL,
            metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
            overall numeric(3, 2),
            drills jsonb NOT NULL DEFAULT '[]'::jsonb,
            error text,
            attempts integer NOT NULL DEFAULT 0,
            timings jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz,
            CONSTRAINT uq_reports_session UNIQUE (session_id)
        )
    """)
    op.execute("""
        CREATE TABLE criterion_scores (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            report_id uuid NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            criterion_id varchar(60) NOT NULL,
            outcome varchar(30) NOT NULL,
            score smallint,
            rationale text NOT NULL,
            evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
            verified boolean NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_criterion_scores_report_criterion UNIQUE (report_id, criterion_id),
            CONSTRAINT ck_criterion_scores_score CHECK (score IS NULL OR score BETWEEN 1 AND 5)
        )
    """)
    op.execute("""
        CREATE INDEX ix_scenarios_persona ON scenarios(persona_id)
    """)
    op.execute("""
        CREATE INDEX ix_practice_sessions_workspace_created
            ON practice_sessions(workspace_id, created_at)
    """)
    op.execute("""
        CREATE INDEX ix_practice_sessions_status ON practice_sessions(status)
    """)
    op.execute("""
        CREATE INDEX ix_transcript_turns_session ON transcript_turns(session_id, start_ms)
    """)
    op.execute("""
        CREATE INDEX ix_reports_workspace_created ON reports(workspace_id, created_at)
    """)
    op.execute("""
        CREATE INDEX ix_criterion_scores_report ON criterion_scores(report_id)
    """)

    for table in CATALOG_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY catalog_read ON {table} FOR SELECT USING (true)")

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (workspace_id = app_current_workspace()) "
            "WITH CHECK (workspace_id = app_current_workspace())"
        )

    # Default privileges (scripts/provision_runtime_roles.py) gave the runtime role DML on
    # new tables; catalog content is written only by the seed script as the owner (D30).
    for role in RUNTIME_ROLES:
        op.execute(f"""
            DO $$ BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                    REVOKE INSERT, UPDATE, DELETE ON personas, rubric_versions, scenarios, drills
                        FROM {role};
                END IF;
            END $$
        """)


def downgrade() -> None:
    for table in TENANT_TABLES + CATALOG_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
