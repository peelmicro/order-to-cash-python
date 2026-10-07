"""The test server must behave like the deployed one where this feature's claims depend on it
(`design.md` 11.4, #8 D8): a fixture change without an assertion is the guard that does not guard.

Every expected value is what the DEPLOYED server has: `timezone=UTC` is set by
`docker-compose.infra.yml:78` (`command: ["postgres", "-c", "timezone=UTC", ...]`); the other three
are PostgreSQL's own defaults, which the compose file does not change. The read is made on a
fixture-created database over a fresh connection, so a database-level `ALTER DATABASE ... SET`
(the arm) is visible.
"""

from typing import Protocol

import asyncpg
import pytest


class FreshDatabase(Protocol):
    @property
    def dsn(self) -> str: ...


DEPLOYED_SETTINGS = {
    "timezone": "UTC",  # docker-compose.infra.yml:78
    "default_transaction_isolation": "read committed",  # PostgreSQL default; compose leaves it
    "lock_timeout": "0",  # PostgreSQL default: wait forever; compose leaves it
    "deadlock_timeout": "1s",  # PostgreSQL default; OI17's constructed deadlock relies on it
}


@pytest.mark.parametrize("setting", sorted(DEPLOYED_SETTINGS))
async def test_the_fixture_server_has_the_setting_the_deployed_server_has(
    migrated_db: FreshDatabase, setting: str
) -> None:
    connection = await asyncpg.connect(migrated_db.dsn)
    try:
        # `setting` comes from the literal table above, never from input
        value = await connection.fetchval(f"SHOW {setting}")
    finally:
        await connection.close()
    assert value == DEPLOYED_SETTINGS[setting], (
        f"the fixture server's {setting} is {value!r}; the deployed server's is "
        f"{DEPLOYED_SETTINGS[setting]!r}"
    )
