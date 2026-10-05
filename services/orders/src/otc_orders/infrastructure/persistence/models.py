"""SQLAlchemy 2 models of `otc_orders` (infrastructure only; the domain never sees them).

Types follow the plan's delta table: `uuid` ids, `timestamptz(3)` instants, `varchar` states
(never a PostgreSQL enum), `bigint` money, `json` (not `jsonb`) payloads,
`bigint GENERATED ALWAYS AS IDENTITY` for `outbox.seq`. Every constraint and index is named by
`NAMING_CONVENTION`, and the migration spells the same names out: the live database, not this
metadata, is what the tests read.

Indexes: the spec's own, plus one per foreign-key column. PostgreSQL (unlike MySQL, which #7 ran on,
and EF Core, which #8 used) creates no index for a foreign key; the parent-delete check and the
"items of this order" read both need one.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP as PG_TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from otc_orders.infrastructure.persistence.range_guards import (
    QuantityOutOfRangeError,
    install_range_guards,
)
from otc_orders.infrastructure.persistence.types import RawJson

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


class Currency(Base):
    __tablename__ = "currencies"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(3), unique=True)
    iso_number: Mapped[str] = mapped_column(String(3))
    symbol: Mapped[str] = mapped_column(String(5))
    decimal_points: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class Product(Base):
    __tablename__ = "products"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    ean: Mapped[str] = mapped_column(String(13), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(255))
    price: Mapped[int] = mapped_column(BigInteger)
    currency_id: Mapped[UUID] = mapped_column(ForeignKey("currencies.id"), index=True)
    disabled_at: Mapped[datetime | None] = mapped_column(_ts())
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class Retailer(Base):
    __tablename__ = "retailers"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2))
    vat: Mapped[str] = mapped_column(String(15))
    gln: Mapped[str] = mapped_column(String(13))
    currency_id: Mapped[UUID] = mapped_column(ForeignKey("currencies.id"), index=True)
    disabled_at: Mapped[datetime | None] = mapped_column(_ts())
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2))
    vat: Mapped[str] = mapped_column(String(15))
    gln: Mapped[str] = mapped_column(String(13))
    currency_id: Mapped[UUID] = mapped_column(ForeignKey("currencies.id"), index=True)
    disabled_at: Mapped[datetime | None] = mapped_column(_ts())
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("uq_orders_request_id", "request_id", unique=True),
        Index("ix_orders_retailer_id_status", "retailer_id", "status"),
        Index("ix_orders_status_order_date", "status", "order_date"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    order_reference: Mapped[str] = mapped_column(String(20), unique=True)
    # R62: a plain unique index. PostgreSQL's default NULLS DISTINCT admits any number of NULLs.
    request_id: Mapped[UUID | None] = mapped_column()
    order_date: Mapped[datetime] = mapped_column(_ts())
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    retailer_id: Mapped[UUID] = mapped_column(ForeignKey("retailers.id"), index=True)
    currency_id: Mapped[UUID] = mapped_column(ForeignKey("currencies.id"), index=True)
    initial_amount: Mapped[int] = mapped_column(BigInteger)
    initial_discount: Mapped[int] = mapped_column(BigInteger)
    total_amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20))
    cancellation_reason: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"), index=True)
    description: Mapped[str] = mapped_column(String(255))
    price: Mapped[int] = mapped_column(BigInteger)
    quantity: Mapped[int] = mapped_column(Integer)
    discount: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class OrderNumberSequence(Base):
    __tablename__ = "order_number_sequences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    next_value: Mapped[int] = mapped_column(Integer)


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


class SagaCommand(Base):
    __tablename__ = "saga_commands"
    __table_args__ = (
        UniqueConstraint("order_id", "command"),
        Index("ix_saga_commands_status_created_at", "status", "created_at"),
        Index("ix_saga_commands_status_next_attempt_at", "status", "next_attempt_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    order_id: Mapped[UUID] = mapped_column()
    order_reference: Mapped[str] = mapped_column(String(20))
    command: Mapped[str] = mapped_column(String(30))
    payload: Mapped[str] = mapped_column(RawJson())
    triggering_event_id: Mapped[UUID] = mapped_column()
    status: Mapped[str] = mapped_column(String(10), server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(_ts())
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())
    sent_at: Mapped[datetime | None] = mapped_column(_ts())


class SagaIgnoredFact(Base):
    __tablename__ = "saga_ignored_facts"
    __table_args__ = (Index("ix_saga_ignored_facts_correlation_id", "correlation_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    event_id: Mapped[UUID] = mapped_column()
    event_type: Mapped[str] = mapped_column(String(60))
    order_id: Mapped[UUID | None] = mapped_column()
    correlation_id: Mapped[UUID] = mapped_column()
    observed_status: Mapped[str | None] = mapped_column(String(20))
    expected_status: Mapped[str | None] = mapped_column(String(20))
    marker: Mapped[str] = mapped_column(String(20))
    recorded_at: Mapped[datetime] = mapped_column(_ts())


# The range guard (acceptance item 5) is installed here, on every integer column of every mapped
# class above, so that importing the models is what arms it.
GUARDED_INTEGER_COLUMNS = install_range_guards(
    list(Base.registry.mappers),
    # (table, column) -> the more specific refusal; any other integer column raises the generic one
    {("order_items", "quantity"): QuantityOutOfRangeError},
)
