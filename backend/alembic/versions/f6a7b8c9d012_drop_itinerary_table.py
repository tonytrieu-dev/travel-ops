"""remove itinerary planning tables"""

from collections.abc import Sequence

from alembic import op

revision: str = "f6a7b8c9d012"
down_revision: str | None = "e47ab5e144df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("itinerary")


def downgrade() -> None:
    raise RuntimeError("Itinerary planning was intentionally removed; restore from a backup instead.")
