"""Assert runtime database credentials cannot dismantle append-only evidence."""
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.exc import DBAPIError

from app.config import get_settings


PROTECTED_TABLES = ("security_event", "booking_transition", "execution_event", "compliance_assessment")


def _denied_statements(table: str) -> tuple[str, ...]:
    return (
        f"UPDATE {table} SET id=id", f"DELETE FROM {table}",
        f"TRUNCATE {table}", f"ALTER TABLE {table} DISABLE TRIGGER ALL",
        f"DROP TABLE {table} CASCADE",
    )


async def _assert_statement_denied(connection, statement: str) -> None:
    """Each mutating statement must fail with insufficient-privilege (SQLSTATE 42501)."""
    transaction = await connection.begin()
    try:
        await connection.execute(text(statement))
    except DBAPIError as error:
        assert getattr(error.orig, "sqlstate", None) == "42501", str(error)
    else:
        raise AssertionError(f"runtime bypassed evidence protection: {statement}")
    finally:
        await transaction.rollback()


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as connection:
            for table in PROTECTED_TABLES:
                for statement in _denied_statements(table):
                    await _assert_statement_denied(connection, statement)
    finally:
        await engine.dispose()
    print("Runtime audit protections verified.")


if __name__ == "__main__":
    asyncio.run(main())
