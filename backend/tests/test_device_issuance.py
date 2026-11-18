"""Certificate provisioning never exposes the authority key to deployed material."""

from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.no_database
ISSUER = Path(__file__).resolve().parents[2] / "deploy" / "issue-device.py"


@pytest.mark.parametrize("device_id", ["../escape", "/tmp/escape", "--help", "-device", "CA", "SERVER"])
def test_device_id_cannot_select_paths_options_or_reserved_files(tmp_path: Path, device_id: str) -> None:
    result = subprocess.run(
        [sys.executable, str(ISSUER), "--", device_id], cwd=tmp_path, capture_output=True,
    )
    assert result.returncode != 0
    assert not (tmp_path / ".device-authority").exists()


def test_device_issuance_refuses_existing_password_symlink(tmp_path: Path) -> None:
    certificates = tmp_path / ".device-certificates"
    certificates.mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.write_text("preserve")
    (certificates / "device-test.password").symlink_to(unrelated)
    result = subprocess.run([sys.executable, str(ISSUER), "device-test"], cwd=tmp_path, capture_output=True)
    assert result.returncode != 0
    assert unrelated.read_text() == "preserve"
    assert not (tmp_path / ".device-authority").exists()


def test_device_issuance_refuses_ca_certificate_symlink(tmp_path: Path) -> None:
    certificates = tmp_path / ".device-certificates"
    certificates.mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.write_text("preserve")
    (certificates / "ca.crt").symlink_to(unrelated)
    result = subprocess.run([sys.executable, str(ISSUER), "device-test"], cwd=tmp_path, capture_output=True)
    assert result.returncode != 0
    assert unrelated.read_text() == "preserve"
    assert not (tmp_path / ".device-authority").exists()


def test_device_issuance_separates_authority_and_refuses_overwrite(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, str(ISSUER), "device-test"], cwd=tmp_path, capture_output=True)
    assert result.returncode == 0
    certificates = tmp_path / ".device-certificates"
    authority = tmp_path / ".device-authority"
    assert (authority / "ca.key").is_file()
    assert authority.stat().st_mode & 0o777 == 0o700
    assert not (certificates / "ca.key").exists()
    verification = subprocess.run([
        "openssl", "verify", "-CAfile", str(certificates / "ca.crt"),
        str(certificates / "device-test.crt"), str(certificates / "server.crt"),
    ], capture_output=True)
    assert verification.returncode == 0
    original_key = (certificates / "device-test.key").read_bytes()
    result = subprocess.run([sys.executable, str(ISSUER), "device-test"], cwd=tmp_path, capture_output=True)
    assert result.returncode != 0
    assert (certificates / "device-test.key").read_bytes() == original_key


def test_legacy_authority_in_deployable_directory_is_rejected(tmp_path: Path) -> None:
    certificates = tmp_path / ".device-certificates"
    certificates.mkdir()
    (certificates / "ca.key").write_text("legacy private key")
    result = subprocess.run([sys.executable, str(ISSUER), "device-test"], cwd=tmp_path, capture_output=True)
    assert result.returncode != 0
    assert b"Move" in result.stderr
    assert not (certificates / "device-test.key").exists()


def test_incomplete_server_pair_is_rejected(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, str(ISSUER), "device-test"], cwd=tmp_path, capture_output=True)
    assert result.returncode == 0
    certificates = tmp_path / ".device-certificates"
    (certificates / "server.crt").unlink()
    retry = subprocess.run([sys.executable, str(ISSUER), "another-device"], cwd=tmp_path, capture_output=True)
    assert retry.returncode != 0
    assert b"server.crt is missing" in retry.stderr
