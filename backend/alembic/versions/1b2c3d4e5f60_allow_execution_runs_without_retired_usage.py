"""allow execution runs without retired usage counters"""

from collections.abc import Sequence

from alembic import op

revision: str = "1b2c3d4e5f60"
down_revision: str | None = "0a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Preserve historical values while allowing new execution runs to omit retired counters.
    op.alter_column("execution_run", "total_input_tokens", nullable=True)
    op.alter_column("execution_run", "total_output_tokens", nullable=True)


def downgrade() -> None:
    op.alter_column("execution_run", "total_output_tokens", nullable=False)
    op.alter_column("execution_run", "total_input_tokens", nullable=False)
