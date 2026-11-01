"""M3: an uploaded call is a practice session of kind `review` (D43).

`practice_sessions` already has its RLS policy, so no new table or policy is needed. Existing rows
become `roleplay`. `consent_at` records when the uploader confirmed permission.
"""
from alembic import op

revision = "20261101_0005"
down_revision = "20261030_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE practice_sessions
            ADD COLUMN kind varchar(20) NOT NULL DEFAULT 'roleplay',
            ADD COLUMN consent_at timestamptz,
            ADD CONSTRAINT ck_practice_sessions_kind CHECK (kind IN ('roleplay', 'review'))
    """)


def downgrade() -> None:
    op.execute("DELETE FROM practice_sessions WHERE kind = 'review'")
    op.execute("""
        ALTER TABLE practice_sessions
            DROP CONSTRAINT ck_practice_sessions_kind,
            DROP COLUMN consent_at,
            DROP COLUMN kind
    """)
