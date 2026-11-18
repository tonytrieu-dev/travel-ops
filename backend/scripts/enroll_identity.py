"""Enroll an existing local account after migration, preserving its ownership and policy."""

import argparse
import asyncio
import os
from getpass import getpass
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.services.identity_enrollment import deliver_identity_enrollment, validate_provisioning_filename

PROVISIONING_DIRECTORY = Path(__file__).resolve().parents[2] / ".identity-provisioning"


async def _enroll(email: str, password: str, path: Path, *, reset_mfa: bool = False) -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await deliver_identity_enrollment(
                session, email, password, path.parent, path.name, reset_mfa=reset_mfa,
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--reset-mfa", action="store_true", help="Rotate MFA for an enrolled account and revoke sessions")
    parser.add_argument("--provisioning-file", required=True, type=validate_provisioning_filename,
                        help="New filename inside the private provisioning directory")
    arguments = parser.parse_args()
    password = "unused-password" if arguments.reset_mfa else getpass("New password (12–200 characters): ")
    if not arguments.reset_mfa and password != getpass("Confirm password: "):
        parser.error("passwords do not match")
    provisioning_directory = Path(os.environ.get("PROVISIONING_DIRECTORY") or PROVISIONING_DIRECTORY)
    try:
        asyncio.run(_enroll(
            arguments.email, password, provisioning_directory / arguments.provisioning_file,
            reset_mfa=arguments.reset_mfa,
        ))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print("Account enrolled. Import the private provisioning URI into your authenticator, then delete the file.")


if __name__ == "__main__":
    main()
