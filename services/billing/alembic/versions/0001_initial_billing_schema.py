"""otc_billing initial schema (hand-written, reviewed against the plan and Databases.EN.md).

Payloads are `json`, never `jsonb`. `outbox.seq` is `bigint GENERATED ALWAYS AS IDENTITY`. States,
types and sources are `varchar`. Instants are `timestamptz(3)`. Money (minor units) is `bigint`
from this first migration: `credits.credit_limit`, `credit_items.amount`, `invoices.amount`,
`invoices.discount`, `invoices.total_amount`, `invoice_items.price` and `payments.amount` (seven).
Three foreign keys: `credit_items.credit_id` and `payments.invoice_id` are NO ACTION on delete,
`invoice_items.invoice_id` is CASCADE; all are NO ACTION on update. `payments` is append-only (no
`updated_at`). `outbox` and `processed_events` are copied from `otc_orders`' migration. Nothing
from #8's later dead-letter migration is here.

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
        "credits",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("retailer_code", sa.String(20), nullable=False),
        sa.Column("company_code", sa.String(20), nullable=False),
        sa.Column("credit_limit", sa.BigInteger(), nullable=False),
        sa.Column("currency_code", sa.CHAR(3), nullable=False),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_credits"),
        sa.UniqueConstraint("code", name="uq_credits_code"),
        sa.UniqueConstraint(
            "retailer_code", "company_code", name="uq_credits_retailer_code_company_code"
        ),
    )

    op.create_table(
        "credit_items",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("credit_id", _uuid(), nullable=False),
        sa.Column("order_reference", sa.String(20), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("credit_date", _ts(), nullable=False),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_credit_items"),
        sa.ForeignKeyConstraint(
            ["credit_id"], ["credits.id"], name="fk_credit_items_credit_id_credits"
        ),
    )
    # (credit_id, order_reference) is the spec's index and also supports the FK column.
    op.create_index(
        "ix_credit_items_credit_id_order_reference",
        "credit_items",
        ["credit_id", "order_reference"],
    )

    op.create_table(
        "invoices",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("invoice_reference", sa.String(20), nullable=False),
        sa.Column("invoice_date", _ts(), nullable=False),
        sa.Column("company_code", sa.String(20), nullable=False),
        sa.Column("retailer_code", sa.String(20), nullable=False),
        sa.Column("order_reference", sa.String(20), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("discount", sa.BigInteger(), nullable=False),
        sa.Column("total_amount", sa.BigInteger(), nullable=False),
        sa.Column("currency_code", sa.CHAR(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("paid_at", _ts(), nullable=True),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_invoices"),
        sa.UniqueConstraint("invoice_reference", name="uq_invoices_invoice_reference"),
        sa.UniqueConstraint("order_reference", name="uq_invoices_order_reference"),
    )
    op.create_index("ix_invoices_status_invoice_date", "invoices", ["status", "invoice_date"])

    op.create_table(
        "invoice_items",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("invoice_id", _uuid(), nullable=False),
        sa.Column("product_code", sa.String(30), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        *_audit(),
        sa.PrimaryKeyConstraint("id", name="pk_invoice_items"),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name="fk_invoice_items_invoice_id_invoices",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_invoice_items_invoice_id", "invoice_items", ["invoice_id"])

    op.create_table(
        "invoice_number_sequences",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("next_value", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_invoice_number_sequences"),
    )

    op.create_table(
        "payments",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("payment_reference", sa.String(30), nullable=False),
        sa.Column("invoice_id", _uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency_code", sa.CHAR(3), nullable=False),
        sa.Column("value_date", _ts(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.UniqueConstraint("payment_reference", name="uq_payments_payment_reference"),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["invoices.id"], name="fk_payments_invoice_id_invoices"
        ),
    )
    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"])

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
        "payments",
        "invoice_number_sequences",
        "invoice_items",
        "invoices",
        "credit_items",
        "credits",
    ):
        op.drop_table(table)
