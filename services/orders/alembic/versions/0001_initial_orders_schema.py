"""otc_orders initial schema (hand-written, hand-reviewed against the plan and Databases.EN.md).

Money is `bigint` from the first migration (#8 id 44 shipped `int` and amended its initial
migrations later). Payloads are `json`, never `jsonb`. `outbox.seq` is `bigint GENERATED ALWAYS AS
IDENTITY`. States are `varchar`. Instants are `timestamptz(3)`. `orders.request_id` (R62) is
nullable with a plain unique index (NULLS DISTINCT: any number of NULLs). Eight foreign keys.
Nothing from #8's later `AddSagaCommandsDeadLetterColumns` is here: the feature that needs those
columns owns that migration.

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
        "currencies",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("code", sa.String(3), nullable=False),
        sa.Column("iso_number", sa.String(3), nullable=False),
        sa.Column("symbol", sa.String(5), nullable=False),
        sa.Column("decimal_points", sa.Integer(), nullable=False),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_currencies"),
        sa.UniqueConstraint("code", name="uq_currencies_code"),
    )

    op.create_table(
        "products",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("ean", sa.String(13), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        sa.Column("currency_id", _uuid(), nullable=False),
        sa.Column("disabled_at", _ts(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("code", name="uq_products_code"),
        sa.UniqueConstraint("ean", name="uq_products_ean"),
        sa.ForeignKeyConstraint(
            ["currency_id"], ["currencies.id"], name="fk_products_currency_id_currencies"
        ),
    )
    op.create_index("ix_products_currency_id", "products", ["currency_id"])

    for party in ("retailers", "companies"):
        op.create_table(
            party,
            sa.Column("id", _uuid(), nullable=False),
            sa.Column("code", sa.String(20), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("country", sa.String(2), nullable=False),
            sa.Column("vat", sa.String(15), nullable=False),
            sa.Column("gln", sa.String(13), nullable=False),
            sa.Column("currency_id", _uuid(), nullable=False),
            sa.Column("disabled_at", _ts(), nullable=True),
            *_audit(),
            sa.PrimaryKeyConstraint("id", name=f"pk_{party}"),
            sa.UniqueConstraint("code", name=f"uq_{party}_code"),
            sa.ForeignKeyConstraint(
                ["currency_id"], ["currencies.id"], name=f"fk_{party}_currency_id_currencies"
            ),
        )
        op.create_index(f"ix_{party}_currency_id", party, ["currency_id"])

    op.create_table(
        "orders",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("order_reference", sa.String(20), nullable=False),
        sa.Column("request_id", _uuid(), nullable=True),
        sa.Column("order_date", _ts(), nullable=False),
        sa.Column("company_id", _uuid(), nullable=False),
        sa.Column("retailer_id", _uuid(), nullable=False),
        sa.Column("currency_id", _uuid(), nullable=False),
        sa.Column("initial_amount", sa.BigInteger(), nullable=False),
        sa.Column("initial_discount", sa.BigInteger(), nullable=False),
        sa.Column("total_amount", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("cancellation_reason", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.UniqueConstraint("order_reference", name="uq_orders_order_reference"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name="fk_orders_company_id_companies"
        ),
        sa.ForeignKeyConstraint(
            ["retailer_id"], ["retailers.id"], name="fk_orders_retailer_id_retailers"
        ),
        sa.ForeignKeyConstraint(
            ["currency_id"], ["currencies.id"], name="fk_orders_currency_id_currencies"
        ),
    )
    # A plain (non-partial) unique index: NULLS DISTINCT is PostgreSQL's default, so many NULLs fit.
    op.create_index("uq_orders_request_id", "orders", ["request_id"], unique=True)
    op.create_index("ix_orders_company_id", "orders", ["company_id"])
    op.create_index("ix_orders_retailer_id", "orders", ["retailer_id"])
    op.create_index("ix_orders_currency_id", "orders", ["currency_id"])
    op.create_index("ix_orders_retailer_id_status", "orders", ["retailer_id", "status"])
    op.create_index("ix_orders_status_order_date", "orders", ["status", "order_date"])

    op.create_table(
        "order_items",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("order_id", _uuid(), nullable=False),
        sa.Column("product_id", _uuid(), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("discount", sa.BigInteger(), nullable=False),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_order_items"),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_order_items_order_id_orders", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name="fk_order_items_product_id_products"
        ),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])

    op.create_table(
        "order_number_sequences",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("next_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_order_number_sequences"),
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

    op.create_table(
        "saga_commands",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("order_id", _uuid(), nullable=False),
        sa.Column("order_reference", sa.String(20), nullable=False),
        sa.Column("command", sa.String(30), nullable=False),
        sa.Column("payload", pg.JSON(), nullable=False),
        sa.Column("triggering_event_id", _uuid(), nullable=False),
        sa.Column("status", sa.String(10), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.Column("sent_at", _ts(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_saga_commands"),
        sa.UniqueConstraint("order_id", "command", name="uq_saga_commands_order_id_command"),
    )
    op.create_index("ix_saga_commands_status_created_at", "saga_commands", ["status", "created_at"])
    op.create_index(
        "ix_saga_commands_status_next_attempt_at", "saga_commands", ["status", "next_attempt_at"]
    )

    op.create_table(
        "saga_ignored_facts",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("event_id", _uuid(), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("order_id", _uuid(), nullable=True),
        sa.Column("correlation_id", _uuid(), nullable=False),
        sa.Column("observed_status", sa.String(20), nullable=True),
        sa.Column("expected_status", sa.String(20), nullable=True),
        sa.Column("marker", sa.String(20), nullable=False),
        sa.Column("recorded_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_saga_ignored_facts"),
    )
    op.create_index(
        "ix_saga_ignored_facts_correlation_id", "saga_ignored_facts", ["correlation_id"]
    )


def downgrade() -> None:
    # Children before parents; dropping a table drops its indexes and constraints with it.
    for table in (
        "saga_ignored_facts",
        "saga_commands",
        "processed_events",
        "outbox",
        "order_number_sequences",
        "order_items",
        "orders",
        "companies",
        "retailers",
        "products",
        "currencies",
    ):
        op.drop_table(table)
