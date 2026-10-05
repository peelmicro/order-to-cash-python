"""SQLAlchemy 2 models of `otc_fulfillment` (infrastructure only; the domain never sees them).

Types follow the plan's delta table: `uuid` ids, `timestamptz(3)` instants, `varchar` states
(never a PostgreSQL enum), `json` (not `jsonb`) payloads, `bigint GENERATED ALWAYS AS IDENTITY` for
`outbox.seq`. Fulfillment has NO money column (Databases.EN.md section 5 has no cents column), so
every integer column here is a unit count or a counter. Every constraint and index is named by
`NAMING_CONVENTION`, and the migration spells the same names out: the live database, not this
metadata, is what the tests read.

`outbox` and `processed_events` are the definitions of `otc_orders`, column for column (section 3,
"byte-identical definitions"; feature 11 proves it from the live catalogs).

Indexes: the spec's own, plus one per foreign-key column (PostgreSQL creates none for a FK).
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
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP as PG_TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from otc_fulfillment.infrastructure.persistence.range_guards import (
    QuantityOutOfRangeError,
    install_range_guards,
)
from otc_fulfillment.infrastructure.persistence.types import RawJson

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


class Stock(Base):
    __tablename__ = "stock"
    __table_args__ = (UniqueConstraint("company_code", "product_code"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_code: Mapped[str] = mapped_column(String(20))
    product_code: Mapped[str] = mapped_column(String(30))
    units: Mapped[int] = mapped_column(Integer)
    reserved_units: Mapped[int] = mapped_column(Integer)
    low_stock_threshold: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (Index("ix_reservations_order_reference_status", "order_reference", "status"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    stock_id: Mapped[UUID] = mapped_column(ForeignKey("stock.id"), index=True)
    company_code: Mapped[str] = mapped_column(String(20))
    retailer_code: Mapped[str] = mapped_column(String(20))
    product_code: Mapped[str] = mapped_column(String(30))
    order_reference: Mapped[str] = mapped_column(String(20))
    units: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class Despatch(Base):
    __tablename__ = "despatches"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    despatch_reference: Mapped[str] = mapped_column(String(20), unique=True)
    despatch_date: Mapped[datetime] = mapped_column(_ts())
    company_code: Mapped[str] = mapped_column(String(20))
    retailer_code: Mapped[str] = mapped_column(String(20))
    order_reference: Mapped[str] = mapped_column(String(20), unique=True)
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class DespatchItem(Base):
    __tablename__ = "despatch_items"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    despatch_id: Mapped[UUID] = mapped_column(
        ForeignKey("despatches.id", ondelete="CASCADE"), index=True
    )
    product_code: Mapped[str] = mapped_column(String(30))
    units: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(_ts())
    updated_at: Mapped[datetime] = mapped_column(_ts())


class DespatchNumberSequence(Base):
    __tablename__ = "despatch_number_sequences"
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


# The range guard is installed here, on every integer column of every mapped class above, so that
# importing the models is what arms it. Every unit-count column carries the quantity code (including
# `stock.low_stock_threshold`: it is a unit level compared against `stock.units`, not a counter);
# `despatch_number_sequences.*` and `outbox.seq` raise the generic storage code.
QUANTITY_COLUMNS = {
    ("stock", "units"): QuantityOutOfRangeError,
    ("stock", "reserved_units"): QuantityOutOfRangeError,
    ("stock", "low_stock_threshold"): QuantityOutOfRangeError,
    ("reservations", "units"): QuantityOutOfRangeError,
    ("despatch_items", "units"): QuantityOutOfRangeError,
}
GUARDED_INTEGER_COLUMNS = install_range_guards(list(Base.registry.mappers), QUANTITY_COLUMNS)
