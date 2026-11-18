"""Enroll an existing local account after migration, preserving its ownership and policy."""

import argparse
import asyncio
import os
from getpass import getpass
from pathlib import Path
import re

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.repositories.credentials_repository import enroll_identity

PROVISIONING_DIRECTORY = (
    Path("/provisioning") if Path("/provisioning").is_dir()
    else Path(__file__).resolve().parents[2] / ".identity-provisioning"
)


def _provisioning_filename(filename: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", filename) is None:
        raise argparse.ArgumentTypeError("provisioning file must be a filename without directories")
    return filename


async def _enroll(email: str, password: str, *, reset_mfa: bool = False) -> str:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await enroll_identity(session, email, password, reset_mfa=reset_mfa)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--reset-mfa", action="store_true", help="Rotate MFA for an enrolled account and revoke sessions")
    parser.add_argument("--provisioning-file", required=True, type=_provisioning_filename,
                        help="New filename inside the private provisioning directory")
    arguments = parser.parse_args()
    password = "unused-password" if arguments.reset_mfa else getpass("New password (12–200 characters): ")
    if not arguments.reset_mfa and password != getpass("Confirm password: "):
        parser.error("passwords do not match")
    try:
        if PROVISIONING_DIRECTORY.is_symlink():
            parser.error("provisioning directory must not be a symbolic link")
        PROVISIONING_DIRECTORY.mkdir(mode=0o700, exist_ok=True)
        PROVISIONING_DIRECTORY.chmod(0o700)
        path = PROVISIONING_DIRECTORY / arguments.provisioning_file
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
            output.write(asyncio.run(_enroll(arguments.email, password, reset_mfa=arguments.reset_mfa)) + "\n")
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print("Account enrolled. Import the private provisioning URI into your authenticator, then delete the file.")


if __name__ == "__main__":
    main()
