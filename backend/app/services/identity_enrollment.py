"""Deliver private enrollment credentials durably before committing their activation."""

import os
from pathlib import Path
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.credentials_repository import enroll_identity


def validate_provisioning_filename(filename: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", filename) is None:
        raise ValueError("provisioning file must be a filename without directories")
    return filename


async def deliver_identity_enrollment(
    session: AsyncSession,
    email: str,
    password: str,
    directory: Path,
    filename: str,
    *,
    reset_mfa: bool = False,
) -> None:
    validate_provisioning_filename(filename)
    if directory.is_symlink():
        raise ValueError("provisioning directory must not be a symbolic link")
    directory.mkdir(mode=0o700, exist_ok=True)
    directory_descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fchmod(directory_descriptor, 0o700)
        with open(filename, "x", opener=lambda path, flags: os.open(
            path, flags | os.O_NOFOLLOW, 0o600, dir_fd=directory_descriptor,
        )) as output:
            try:
                provisioning_uri = await enroll_identity(session, email, password, reset_mfa=reset_mfa)
                output.write(provisioning_uri + "\n")
                output.flush()
                os.fsync(output.fileno())
                os.fsync(directory_descriptor)
            except BaseException:
                try:
                    await session.rollback()
                finally:
                    os.unlink(filename, dir_fd=directory_descriptor)
                raise
            # Once commit starts, its outcome may be unknown; preserve the complete URI.
            await session.commit()
    finally:
        os.close(directory_descriptor)
