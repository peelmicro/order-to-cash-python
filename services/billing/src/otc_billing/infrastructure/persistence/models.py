"""SQLAlchemy 2 models of `otc_billing` (infrastructure only; the domain never sees them).

Types follow the plan's delta table: `uuid` ids, `timestamptz(3)` instants, `varchar` states (never
a PostgreSQL enum), `json` (not `jsonb`) payloads, `bigint GENERATED ALWAYS AS IDENTITY` for
`outbox.seq`, and `bigint` for every money column (minor units): `credits.credit_limit`,
`credit_items.amount`, `invoices.amount/discount/total_amount`, `invoice_items.price`,
`payments.amount`. `currency_code` is `char(3)` (ISO 4217, #7 and #8 agree). Every constraint and
index is named by `NAMING_CONVENTION`, and the migration spells the same names out: the live
database, not this metadata, is what the tests read.

`payments` is append-only (no `updated_at`). `outbox` and `processed_events` are the definitions of
`otc_orders`, column for column (feature 11 proves it from the live catalogs of all four databases).

Indexes: the spec's own, plus `ix_invoice_items_invoice_id` and `ix_payments_invoice_id` (one per
foreign-key column that no spec index already covers; PostgreSQL creates none for a FK).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP as PG_TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from otc_billing.infrastructure.persistence.range_guards import (
    QuantityOutOfRangeError,
    install_range_guards,
)
from otc_billing.infrastructure.persistence.types import RawJson

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy's declarative contract
        datetime: PG_TIMESTAMP(timezone=True, precision=3),
        UUID: Uuid(as_uuid=True),
    }


def _ts() -> PG_TIMESTAMP:
    return PG_TIMESTAMP(timezone=True, precision=3)


class Credit(Base):
    __tablename__ = "credits"
    __table_args__ = (UniqueConstraint("retailer_code", "company_code"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    retailer_code: Mapped[str] = mapped_column(String(20))
    company_code: Mapped[str] = mapped_column(String(20))
    credit_limit: Mapped[int] = mapped_column(BigInteger)
    currency_code: Mapped[str] = mapped_column(CHAR(3))
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class CreditItem(Base):
    __tablename__ = "credit_items"
    __table_args__ = (
        Index("ix_credit_items_credit_id_order_reference", "credit_id", "order_reference"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    credit_id: Mapped[UUID] = mapped_column(ForeignKey("credits.id"))
    order_reference: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String(20))
    credit_date: Mapped[datetime] = mapped_column(_ts())
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (Index("ix_invoices_status_invoice_date", "status", "invoice_date"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    invoice_reference: Mapped[str] = mapped_column(String(20), unique=True)
    invoice_date: Mapped[datetime] = mapped_column(_ts())
    company_code: Mapped[str] = mapped_column(String(20))
    retailer_code: Mapped[str] = mapped_column(String(20))
    order_reference: Mapped[str] = mapped_column(String(20), unique=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    discount: Mapped[int] = mapped_column(BigInteger)
    total_amount: Mapped[int] = mapped_column(BigInteger)
    currency_code: Mapped[str] = mapped_column(CHAR(3))
    status: Mapped[str] = mapped_column(String(20))
    paid_at: Mapped[datetime | None] = mapped_column(_ts())
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    invoice_id: Mapped[UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    product_code: Mapped[str] = mapped_column(String(30))
    units: Mapped[int] = mapped_column(Integer)
    price: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class InvoiceNumberSequence(Base):
    __tablename__ = "invoice_number_sequences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    next_value: Mapped[int] = mapped_column(Integer)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    payment_reference: Mapped[str] = mapped_column(String(30), unique=True)
    invoice_id: Mapped[UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    currency_code: Mapped[str] = mapped_column(CHAR(3))
    value_date: Mapped[datetime] = mapped_column(_ts())
    source: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(_ts())


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        Index("ix_outbox_published_at_seq", "published_at", "seq"),
        Index("ix_outbox_published_at_occurred_at", "published_at", "occurred_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    event_id: Mapped[UUID] = mapped_column(unique=True)
    event_type: Mapped[str] = mapped_column(String(60))
    aggregate_id: Mapped[UUID] = mapped_column()
    correlation_id: Mapped[UUID] = mapped_column()
    causation_id: Mapped[UUID] = mapped_column()
    payload: Mapped[str] = mapped_column(RawJson())
    occurred_at: Mapped[datetime] = mapped_column(_ts())
    published_at: Mapped[datetime | None] = mapped_column(_ts())
    created_at: Mapped[datetime] = mapped_column(_ts())
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    trace_parent: Mapped[str | None] = mapped_column(String(64))


class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    __table_args__ = (UniqueConstraint("event_id", "consumer"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    event_id: Mapped[UUID] = mapped_column()
    consumer: Mapped[str] = mapped_column(String(50))
    processed_at: Mapped[datetime] = mapped_column(_ts())
    created_at: Mapped[datetime] = mapped_column(_ts())


# The range guard is installed here, on every integer column of every mapped class above, so that
# importing the models is what arms it. Classification of the 11 integer columns of this database:
# `invoice_items.units` is the one QUANTITY (code `quantity.out_of_range`). The seven money columns
# (`bigint`, minor units) and the three counters (`invoice_number_sequences.id/next_value`,
# `outbox.seq`) raise the generic `storage.integer_out_of_range`: a money value is bounded by
# `Money` (int64) in the domain, and there is no money-specific refusal code in `specs/shared/`.
QUANTITY_COLUMNS = {
    ("invoice_items", "units"): QuantityOutOfRangeError,
}
GUARDED_INTEGER_COLUMNS = install_range_guards(list(Base.registry.mappers), QUANTITY_COLUMNS)
