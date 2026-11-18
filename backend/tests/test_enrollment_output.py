"""Enrollment output is confined and exclusive before any credentials change."""

from pathlib import Path
import sys

import pytest

from scripts import enroll_identity

pytestmark = pytest.mark.no_database


@pytest.mark.parametrize("filename", ["../escape", "/tmp/escape", "nested/output", ".."])
def test_enrollment_rejects_paths_before_prompting(
    monkeypatch: pytest.MonkeyPatch, filename: str,
) -> None:
    monkeypatch.setattr(sys, "argv", ["enroll_identity", "--email", "user@example.test", "--provisioning-file", filename])
    monkeypatch.setattr(enroll_identity, "getpass", lambda _prompt: pytest.fail("unsafe path reached password prompt"))
    with pytest.raises(SystemExit) as rejection:
        enroll_identity.main()
    assert rejection.value.code == 2


def test_enrollment_writes_private_output_and_refuses_overwrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    directory = tmp_path / "provisioning"
    monkeypatch.setattr(enroll_identity, "PROVISIONING_DIRECTORY", directory, raising=False)
    monkeypatch.setattr(sys, "argv", ["enroll_identity", "--email", "user@example.test", "--reset-mfa", "--provisioning-file", "enrollment-uri"])
    enrollments = []

    async def enroll(email: str, password: str, *, reset_mfa: bool) -> str:
        enrollments.append(email)
        return "otpauth://test"

    monkeypatch.setattr(enroll_identity, "_enroll", enroll)
    enroll_identity.main()
    output = directory / "enrollment-uri"
    assert output.read_text() == "otpauth://test\n"
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(SystemExit):
        enroll_identity.main()
    assert enrollments == ["user@example.test"]
    assert output.read_text() == "otpauth://test\n"
