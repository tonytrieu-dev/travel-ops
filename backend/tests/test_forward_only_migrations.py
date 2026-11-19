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
