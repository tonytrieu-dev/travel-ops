"""index security event compliance windows"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "8f1a2b3c4d5e"
down_revision: str | None = "6e0a2c4d8f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with context.get_context().autocommit_block():
        op.create_index(
            "ix_security_event_tenant_created_at",
            "security_event",
            ["tenant_id", "created_at"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with context.get_context().autocommit_block():
        op.drop_index(
            "ix_security_event_tenant_created_at",
            table_name="security_event",
            postgresql_concurrently=True,
        )
