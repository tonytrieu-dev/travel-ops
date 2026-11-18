"""The host launcher confines output before handing off to Docker."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.no_database


@pytest.mark.parametrize("symlink", [False, True])
def test_launcher_prepares_private_output_without_following_symlinks(tmp_path, symlink):
    deployment = tmp_path / "project" / "deploy"
    deployment.mkdir(parents=True)
    launcher = deployment / "enroll-identity.sh"
    shutil.copyfile(Path(__file__).resolve().parents[2] / "deploy" / launcher.name, launcher)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    docker.chmod(0o700)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir(mode=0o755)
    provisioning = deployment.parent / ".identity-provisioning"
    if symlink:
        provisioning.symlink_to(unrelated, target_is_directory=True)
    result = subprocess.run(
        ["sh", str(launcher), "--email", "user+tag@example.test", "--provisioning-file", "uri"],
        cwd=tmp_path, env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"},
        capture_output=True, text=True,
    )
    assert unrelated.stat().st_mode & 0o777 == 0o755
    assert list(unrelated.iterdir()) == []
    if symlink:
        assert result.returncode != 0
        assert "symbolic link" in result.stderr
        assert result.stdout == "", "Docker must not run for a rejected host directory"
        return
    assert result.returncode == 0, result.stderr
    assert provisioning.stat().st_mode & 0o777 == 0o700
    assert result.stdout.splitlines() == [
        "compose", "-f", "compose.zero-trust.yml", "run", "--rm",
        "--user", f"{os.getuid()}:{os.getgid()}", "enroll",
        "--email", "user+tag@example.test", "--provisioning-file", "uri",
    ]
