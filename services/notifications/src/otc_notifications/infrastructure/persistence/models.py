"""SQLAlchemy 2 model of `otc_notifications`: `processed_events`, its ONLY table.

The durable ledger that makes a duplicate email impossible (Databases.EN.md section 7). The table
is the definition of `otc_orders`' `processed_events`, column for column (feature 11 proves it from
the live catalogs). There is no integer column and no payload column here, so this service carries
no range guard and no `RawJson` (decided in feature 11: a copy with nothing to guard would only be
one more file for the parity census to police).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import MetaData, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import TIMESTAMP as PG_TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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


class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    __table_args__ = (UniqueConstraint("event_id", "consumer"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    event_id: Mapped[UUID] = mapped_column()
    consumer: Mapped[str] = mapped_column(String(50))
    processed_at: Mapped[datetime] = mapped_column(_ts())
    created_at: Mapped[datetime] = mapped_column(_ts())
