"""index security event denial windows"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "9a1b2c3d4e5f"
down_revision: str | None = "8f1a2b3c4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with context.get_context().autocommit_block():
        op.create_index(
            "ix_security_event_denial_window",
            "security_event",
            ["tenant_id", "device_id", "session_id", "decision", "created_at"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with context.get_context().autocommit_block():
        op.drop_index(
            "ix_security_event_denial_window",
            table_name="security_event",
            postgresql_concurrently=True,
        )
