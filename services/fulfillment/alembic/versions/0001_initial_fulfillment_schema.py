"""otc_fulfillment initial schema (hand-written, reviewed against the plan and Databases.EN.md).

Payloads are `json`, never `jsonb`. `outbox.seq` is `bigint GENERATED ALWAYS AS IDENTITY`. States
are `varchar`. Instants are `timestamptz(3)`. There is no money column in this database. Two
foreign keys, both NO ACTION on update, and ON DELETE NO ACTION (`reservations.stock_id`) /
CASCADE (`despatch_items.despatch_id`). `outbox` and `processed_events` are copied from
`otc_orders`' migration. Nothing from #8's later dead-letter migration is here.

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


def _audit() -> list[sa.Column[datetime]]:
    return [
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "stock",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("company_code", sa.String(20), nullable=False),
        sa.Column("product_code", sa.String(30), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("reserved_units", sa.Integer(), nullable=False),
        sa.Column("low_stock_threshold", sa.Integer(), nullable=False),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_stock"),
        sa.UniqueConstraint(
            "company_code", "product_code", name="uq_stock_company_code_product_code"
        ),
    )

    op.create_table(
        "reservations",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("stock_id", _uuid(), nullable=False),
        sa.Column("company_code", sa.String(20), nullable=False),
        sa.Column("retailer_code", sa.String(20), nullable=False),
        sa.Column("product_code", sa.String(30), nullable=False),
        sa.Column("order_reference", sa.String(20), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_reservations"),
        sa.ForeignKeyConstraint(["stock_id"], ["stock.id"], name="fk_reservations_stock_id_stock"),
    )
    op.create_index("ix_reservations_stock_id", "reservations", ["stock_id"])
    op.create_index(
        "ix_reservations_order_reference_status", "reservations", ["order_reference", "status"]
    )

    op.create_table(
        "despatches",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("despatch_reference", sa.String(20), nullable=False),
        sa.Column("despatch_date", _ts(), nullable=False),
        sa.Column("company_code", sa.String(20), nullable=False),
        sa.Column("retailer_code", sa.String(20), nullable=False),
        sa.Column("order_reference", sa.String(20), nullable=False),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_despatches"),
        sa.UniqueConstraint("despatch_reference", name="uq_despatches_despatch_reference"),
        sa.UniqueConstraint("order_reference", name="uq_despatches_order_reference"),
    )

    op.create_table(
        "despatch_items",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("despatch_id", _uuid(), nullable=False),
        sa.Column("product_code", sa.String(30), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_despatch_items"),
        sa.ForeignKeyConstraint(
            ["despatch_id"],
            ["despatches.id"],
            name="fk_despatch_items_despatch_id_despatches",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_despatch_items_despatch_id", "despatch_items", ["despatch_id"])

    op.create_table(
        "despatch_number_sequences",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("next_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_despatch_number_sequences"),
    )

    op.create_table(
        "outbox",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("event_id", _uuid(), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("aggregate_id", _uuid(), nullable=False),
        sa.Column("correlation_id", _uuid(), nullable=False),
        sa.Column("causation_id", _uuid(), nullable=False),
        sa.Column("payload", pg.JSON(), nullable=False),
        sa.Column("occurred_at", _ts(), nullable=False),
        sa.Column("published_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("trace_parent", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox"),
        sa.UniqueConstraint("event_id", name="uq_outbox_event_id"),
        sa.UniqueConstraint("seq", name="uq_outbox_seq"),
    )
    op.create_index("ix_outbox_published_at_seq", "outbox", ["published_at", "seq"])
    op.create_index("ix_outbox_published_at_occurred_at", "outbox", ["published_at", "occurred_at"])

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
    for table in (
        "processed_events",
        "outbox",
        "despatch_number_sequences",
        "despatch_items",
        "despatches",
        "reservations",
        "stock",
    ):
        op.drop_table(table)
