"""otc_notifications initial schema: `processed_events` and nothing else.

The durable ledger that makes a duplicate send impossible (Databases.EN.md section 7). The table is
the definition of `otc_orders`' `processed_events`, column for column. No outbox, no sequence, no
foreign key: this service has no aggregate and emits no fact.

Revision ID: 0001
Revises:
Create Date: 2026-10-05
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts() -> sa.types.TypeEngine[datetime]:
    return pg.TIMESTAMP(timezone=True, precision=3)


def _uuid() -> sa.Uuid[uuid.UUID]:
    return sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "processed_events",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("event_id", _uuid(), nullable=False),
        sa.Column("consumer", sa.String(50), nullable=False),
        sa.Column("processed_at", _ts(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_processed_events"),
        sa.UniqueConstraint("event_id", "consumer", name="uq_processed_events_event_id_consumer"),
    )


def downgrade() -> None:
    op.drop_table("processed_events")
