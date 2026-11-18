"""Enrollment output is confined and exclusive before any credentials change."""

from pathlib import Path
import asyncio
import os
import stat
import sys
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock

import pytest

from scripts import enroll_identity
from app.models import User
from app.services import identity_enrollment

pytestmark = pytest.mark.no_database


@pytest.mark.asyncio
async def test_delivery_reserves_private_file_before_staging_and_cleans_up_rejection(tmp_path):
    directory = tmp_path / "provisioning"
    session = AsyncMock()

    async def missing_account(statement):
        assert (directory / "uri").read_text() == ""
        assert directory.stat().st_mode & 0o777 == 0o700
        assert (directory / "uri").stat().st_mode & 0o777 == 0o600
        return None

    session.scalar.side_effect = missing_account
    with pytest.raises(ValueError, match="enabled existing account required"):
        await identity_enrollment.deliver_identity_enrollment(
            session, "missing@example.test", "chosen-password", directory, "uri",
        )
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    assert not (directory / "uri").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["write", "flush", "file_fsync", "directory_fsync", "cancelled", "commit", None])
async def test_enrollment_commits_only_after_durable_output(monkeypatch, tmp_path, failure):
    session = AsyncMock()
    events = []
    path = tmp_path / "uri"
    user = User(id=1, email="user@example.test", totp_secret="old-secret")
    session.scalar.return_value = user
    if failure == "cancelled":
        session.flush.side_effect = asyncio.CancelledError()

    class Output:
        def __init__(self, output):
            self.output = output

        def write(self, value):
            events.append("write")
            if failure == "write":
                self.output.write(value[:10])
                raise OSError("disk full")
            return self.output.write(value)

        def flush(self):
            events.append("flush")
            if failure == "flush":
                raise OSError("disk full")
            self.output.flush()

        def fileno(self):
            return self.output.fileno()

    @contextmanager
    def open_output(*arguments, **keywords):
        with open(*arguments, **keywords) as output:
            yield Output(output)

    synchronize = os.fsync

    def synchronize_output(descriptor):
        operation = "directory_fsync" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file_fsync"
        events.append(operation)
        if failure == operation:
            raise OSError("disk full")
        synchronize(descriptor)

    async def commit():
        assert events == ["write", "flush", "file_fsync", "directory_fsync"]
        assert path.read_text() == f"otpauth://totp/TravelOps:user%40example.test?secret={user.totp_secret}&issuer=TravelOps\n"
        if failure == "commit":
            raise OSError("commit outcome unknown")

    session.commit.side_effect = commit
    monkeypatch.setattr(identity_enrollment, "open", open_output, raising=False)
    monkeypatch.setattr(identity_enrollment.os, "fsync", synchronize_output)
    if failure:
        expected_error = asyncio.CancelledError if failure == "cancelled" else OSError
        expected_message = None if failure == "cancelled" else "commit outcome unknown" if failure == "commit" else "disk full"
        with pytest.raises(expected_error, match=expected_message):
            await identity_enrollment.deliver_identity_enrollment(
                session, "user@example.test", "chosen-password", tmp_path, "uri", reset_mfa=True,
            )
    else:
        await identity_enrollment.deliver_identity_enrollment(
            session, "user@example.test", "chosen-password", tmp_path, "uri", reset_mfa=True,
        )
    session.flush.assert_awaited_once()
    assert user.totp_secret != "old-secret"
    if failure and failure != "commit":
        session.commit.assert_not_awaited()
        session.rollback.assert_awaited_once()
        assert not path.exists()
    else:
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()
        assert path.read_text() == f"otpauth://totp/TravelOps:user%40example.test?secret={user.totp_secret}&issuer=TravelOps\n"


@pytest.mark.parametrize("filename", ["../escape", "/tmp/escape", "nested/output", "..", "", "a" * 129])
def test_enrollment_rejects_paths_before_prompting(
    monkeypatch: pytest.MonkeyPatch, filename: str,
) -> None:
    monkeypatch.setattr(sys, "argv", ["enroll_identity", "--email", "user@example.test", "--provisioning-file", filename])
    monkeypatch.setattr(enroll_identity, "getpass", lambda _prompt: pytest.fail("unsafe path reached password prompt"))
    with pytest.raises(SystemExit) as rejection:
        enroll_identity.main()
    assert rejection.value.code == 2


@pytest.mark.parametrize("configured_directory", [None, "", "mounted"])
def test_cli_writes_private_output_and_refuses_overwrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, configured_directory: str | None,
) -> None:
    directory = tmp_path / "provisioning"
    monkeypatch.setattr(enroll_identity, "PROVISIONING_DIRECTORY", directory)
    if configured_directory is None:
        monkeypatch.delenv("PROVISIONING_DIRECTORY", raising=False)
    else:
        if configured_directory:
            directory = tmp_path / configured_directory
        monkeypatch.setenv("PROVISIONING_DIRECTORY", str(directory) if configured_directory else "")
    monkeypatch.setattr(sys, "argv", ["enroll_identity", "--email", "user@example.test", "--reset-mfa", "--provisioning-file", "enrollment-uri"])
    session, engine = AsyncMock(), AsyncMock()
    user = User(id=1, email="user@example.test", totp_secret="old-secret")
    session.scalar.return_value = user

    @asynccontextmanager
    async def open_session():
        yield session

    monkeypatch.setattr(enroll_identity, "create_async_engine", lambda _url: engine)
    monkeypatch.setattr(enroll_identity, "async_sessionmaker", lambda *_arguments, **_keywords: open_session)
    enroll_identity.main()
    output = directory / "enrollment-uri"
    content = output.read_text()
    assert content == f"otpauth://totp/TravelOps:user%40example.test?secret={user.totp_secret}&issuer=TravelOps\n"
    assert user.totp_secret != "old-secret"
    assert directory.stat().st_mode & 0o777 == 0o700
    assert output.stat().st_mode & 0o777 == 0o600
    session.commit.assert_awaited_once()
    engine.dispose.assert_awaited_once()
    with pytest.raises(SystemExit) as rejection:
        enroll_identity.main()
    assert rejection.value.code == 2
    assert output.read_text() == content
    session.scalar.assert_awaited_once()
    session.commit.assert_awaited_once()
    assert engine.dispose.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", ["file_symlink", "directory_symlink"])
async def test_delivery_rejects_existing_files_and_symlinks_before_staging(monkeypatch, tmp_path, existing):
    directory = tmp_path / "provisioning"
    target = tmp_path / "untouched"
    target.write_text("preserve")
    if existing == "directory_symlink":
        directory.symlink_to(tmp_path, target_is_directory=True)
    else:
        directory.mkdir()
        (directory / "uri").symlink_to(target)
    staged = AsyncMock()
    monkeypatch.setattr(identity_enrollment, "enroll_identity", staged)
    with pytest.raises((ValueError, FileExistsError)):
        await identity_enrollment.deliver_identity_enrollment(
            AsyncMock(), "user@example.test", "chosen-password", directory, "uri",
        )
    staged.assert_not_awaited()
    assert target.read_text() == "preserve"
    if existing != "directory_symlink":
        assert (directory / "uri").read_text() == "preserve"


@pytest.mark.asyncio
async def test_delivery_validates_filename_without_the_cli(monkeypatch, tmp_path):
    staged = AsyncMock()
    monkeypatch.setattr(identity_enrollment, "enroll_identity", staged)
    with pytest.raises(ValueError, match="filename without directories"):
        await identity_enrollment.deliver_identity_enrollment(
            AsyncMock(), "user@example.test", "chosen-password", tmp_path, "../escape",
        )
    staged.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []
