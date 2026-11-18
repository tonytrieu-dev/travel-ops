from pathlib import Path
import runpy

import pytest

pytestmark = pytest.mark.no_database

VERSIONS = Path(__file__).parents[1] / "alembic" / "versions"


@pytest.mark.parametrize(
    "filename",
    [
        "5d9f1b3c4e67_retire_legacy_passwords.py",
        "6e0a2c4d8f10_retire_shared_totp.py",
    ],
)
def test_credential_retirement_downgrades_fail_explicitly(filename: str) -> None:
    downgrade = runpy.run_path(str(VERSIONS / filename))["downgrade"]
    with pytest.raises(RuntimeError, match="forward-only"):
        downgrade()


def test_trip_cleanup_preserves_runs_without_audit_events() -> None:
    source = (VERSIONS / "e2fd12c1788c_require_age_and_fitness_drop_budget.py").read_text()
    assert "agent_run.trip_request_id = trip_request.id" in source


def test_execution_run_retired_usage_columns_are_optional() -> None:
    source = (VERSIONS / "1b2c3d4e5f60_allow_execution_runs_without_retired_usage.py").read_text()
    assert 'op.alter_column("execution_run", "total_input_tokens", nullable=True)' in source
    assert 'op.alter_column("execution_run", "total_output_tokens", nullable=True)' in source
