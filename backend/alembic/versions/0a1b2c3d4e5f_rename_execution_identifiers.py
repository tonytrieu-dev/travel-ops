"""rename active execution identifiers"""

from collections.abc import Sequence

from alembic import op

revision: str = "0a1b2c3d4e5f"
down_revision: str | None = "f6a7b8c9d012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("agent_run", "execution_run")
    op.rename_table("agent_run_step", "execution_step")
    op.alter_column("execution_event", "agent_run_id", new_column_name="execution_run_id")
    op.alter_column("execution_step", "agent_run_id", new_column_name="execution_run_id")
    op.alter_column("execution_run", "model", new_column_name="provider")
    op.execute("ALTER INDEX ix_agent_run_trip_request_id RENAME TO ix_execution_run_trip_request_id")
    op.execute("ALTER INDEX ix_agent_run_step_agent_run_id RENAME TO ix_execution_step_execution_run_id")
    op.execute("ALTER INDEX ix_execution_event_agent_run_id RENAME TO ix_execution_event_execution_run_id")
    op.execute("ALTER TABLE execution_event RENAME CONSTRAINT fk_execution_event_agent_run TO fk_execution_event_execution_run")
    op.execute("ALTER TABLE execution_step RENAME CONSTRAINT agent_run_step_agent_run_id_fkey TO execution_step_execution_run_id_fkey")
    op.execute("ALTER TYPE agentstepkind RENAME TO executionstepkind")
    op.execute("ALTER TYPE executionstepkind RENAME VALUE 'MODEL' TO 'PROVIDER'")
    op.execute("ALTER TYPE executionstepkind RENAME VALUE 'TOOL' TO 'EXTERNAL_CALL'")


def downgrade() -> None:
    op.execute("ALTER TYPE executionstepkind RENAME VALUE 'PROVIDER' TO 'MODEL'")
    op.execute("ALTER TYPE executionstepkind RENAME VALUE 'EXTERNAL_CALL' TO 'TOOL'")
    op.execute("ALTER TYPE executionstepkind RENAME TO agentstepkind")
    op.execute("ALTER TABLE execution_step RENAME CONSTRAINT execution_step_execution_run_id_fkey TO agent_run_step_agent_run_id_fkey")
    op.execute("ALTER TABLE execution_event RENAME CONSTRAINT fk_execution_event_execution_run TO fk_execution_event_agent_run")
    op.execute("ALTER INDEX ix_execution_event_execution_run_id RENAME TO ix_execution_event_agent_run_id")
    op.execute("ALTER INDEX ix_execution_step_execution_run_id RENAME TO ix_agent_run_step_agent_run_id")
    op.execute("ALTER INDEX ix_execution_run_trip_request_id RENAME TO ix_agent_run_trip_request_id")
    op.alter_column("execution_run", "provider", new_column_name="model")
    op.alter_column("execution_step", "execution_run_id", new_column_name="agent_run_id")
    op.alter_column("execution_event", "execution_run_id", new_column_name="agent_run_id")
    op.rename_table("execution_step", "agent_run_step")
    op.rename_table("execution_run", "agent_run")
