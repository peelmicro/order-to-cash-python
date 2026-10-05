"""The models and the migration describe the same schema (Alembic's own autogenerate diff is empty).

This is a drift detector between two hand-maintained descriptions, NOT the proof of the schema: the
proof is the live-catalog tests (types, foreign keys, indexes), which never consult the models.
"""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from otc_billing.infrastructure.persistence.models import Base

pytestmark = pytest.mark.integration


def _diff(connection: Connection) -> list[object]:
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return list(compare_metadata(context, Base.metadata))


async def test_autogenerate_finds_no_difference_between_models_and_migrated_schema(
    engine: AsyncEngine,
) -> None:
    async with engine.connect() as connection:
        differences = await connection.run_sync(_diff)
    assert differences == []
