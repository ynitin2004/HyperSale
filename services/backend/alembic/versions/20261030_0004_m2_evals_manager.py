"""M2: gold-set items and rater labels (D37), assignments (D39), member email (D39).

Ownership (ARCHITECTURE §3): `evals` owns eval_items/eval_labels, `coaching` owns assignments,
`identity` owns memberships. All three new tables are tenant tables with the same ENABLE +
FORCE + USING/WITH CHECK policy shape as 0002/0003.
"""
from alembic import op

revision = "20261030_0004"
down_revision = "20261029_0003"
branch_labels = None
depends_on = None

TENANT_TABLES = ("eval_items", "eval_labels", "assignments")


def upgrade() -> None:
    op.execute("ALTER TABLE memberships ADD COLUMN email varchar(320)")
    op.execute("""
        CREATE TABLE eval_items (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            item_key varchar(120) NOT NULL,
            source varchar(20) NOT NULL,
            scenario_slug varchar(80) NOT NULL,
            applicable_criteria jsonb NOT NULL,
            turns jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_eval_items_key UNIQUE (workspace_id, item_key)
        )
    """)
    op.execute("""
        CREATE TABLE eval_labels (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            item_id uuid NOT NULL REFERENCES eval_items(id) ON DELETE CASCADE,
            rater_user_id uuid NOT NULL,
            criterion_id varchar(60) NOT NULL,
            outcome varchar(30) NOT NULL,
            note text,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_eval_labels_rater UNIQUE (item_id, rater_user_id, criterion_id),
            CONSTRAINT ck_eval_labels_outcome
                CHECK (outcome IN ('1', '2', '3', '4', '5', 'insufficient_evidence'))
        )
    """)
    op.execute("CREATE INDEX ix_eval_labels_rater ON eval_labels(rater_user_id)")
    op.execute("""
        CREATE TABLE assignments (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            scenario_id uuid NOT NULL REFERENCES scenarios(id),
            assignee_user_id uuid NOT NULL,
            assigned_by uuid NOT NULL,
            due_at timestamptz,
            note varchar(500),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_assignments_workspace_assignee ON assignments(workspace_id, assignee_user_id)")

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (workspace_id = app_current_workspace()) "
            "WITH CHECK (workspace_id = app_current_workspace())"
        )


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("ALTER TABLE memberships DROP COLUMN IF EXISTS email")
