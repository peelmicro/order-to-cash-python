"""The seed's own SQLAlchemy Core definitions of the tables it writes: one `MetaData` per database.

The seed may not import a service's models (import-linter's independence contract), so these
definitions are hand-written copies. They are NOT trusted: `schema_check.verify_schema` compares
every one of them with the LIVE migrated database (columns, types, nullability, identity, primary
key, foreign keys, unique constraints), the seed runs it before writing anything (a database that
is not at head is refused with the missing/divergent item named), and
`tests/integration/test_seed_tables_match_migration.py` runs it against the real Alembic-migrated
templates of the three services. A migration that changes any of these tables fails that test.

Every column is declared, including those the seed never writes (`outbox.seq` is
`GENERATED ALWAYS AS IDENTITY`, `outbox.trace_parent`, `orders.request_id` are left to the
database), so that drift in a column the seed does not write is still visible.
"""

from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import CHAR
from sqlalchemy.dialects.postgresql import TIMESTAMP as PG_TIMESTAMP

from otc_seed.infrastructure.raw_json import RawJson


def _ts() -> PG_TIMESTAMP:
    return PG_TIMESTAMP(timezone=True, precision=3)


def _id() -> Column[Any]:
    return Column("id", Uuid(as_uuid=True), primary_key=True)


def _created_updated() -> list[Column[Any]]:
    return [
        Column("created_at", _ts(), nullable=False),
        Column("updated_at", _ts(), nullable=False),
    ]


def _outbox(metadata: MetaData) -> Table:
    return Table(
        "outbox",
        metadata,
        _id(),
        Column("event_id", Uuid(as_uuid=True), nullable=False, unique=True),
        Column("event_type", String(60), nullable=False),
        Column("aggregate_id", Uuid(as_uuid=True), nullable=False),
        Column("correlation_id", Uuid(as_uuid=True), nullable=False),
        Column("causation_id", Uuid(as_uuid=True), nullable=False),
        Column("payload", RawJson(), nullable=False),
        Column("occurred_at", _ts(), nullable=False),
        Column("published_at", _ts(), nullable=True),
        Column("created_at", _ts(), nullable=False),
        Column("seq", BigInteger, Identity(always=True), nullable=False, unique=True),
        Column("trace_parent", String(64), nullable=True),
    )


def _party(name: str, metadata: MetaData, code_length: int) -> Table:
    return Table(
        name,
        metadata,
        _id(),
        Column("code", String(code_length), nullable=False, unique=True),
        Column("name", String(100), nullable=False),
        Column("country", String(2), nullable=False),
        Column("vat", String(15), nullable=False),
        Column("gln", String(13), nullable=False),
        Column("currency_id", Uuid(as_uuid=True), ForeignKey("currencies.id"), nullable=False),
        Column("disabled_at", _ts(), nullable=True),
        *_created_updated(),
    )


ORDERS_METADATA = MetaData()
CURRENCIES = Table(
    "currencies",
    ORDERS_METADATA,
    _id(),
    Column("code", String(3), nullable=False, unique=True),
    Column("iso_number", String(3), nullable=False),
    Column("symbol", String(5), nullable=False),
    Column("decimal_points", Integer, nullable=False),
    *_created_updated(),
)
PRODUCTS = Table(
    "products",
    ORDERS_METADATA,
    _id(),
    Column("code", String(30), nullable=False, unique=True),
    Column("ean", String(13), nullable=False, unique=True),
    Column("name", String(100), nullable=False),
    Column("description", String(255), nullable=False),
    Column("price", BigInteger, nullable=False),
    Column("currency_id", Uuid(as_uuid=True), ForeignKey("currencies.id"), nullable=False),
    Column("disabled_at", _ts(), nullable=True),
    *_created_updated(),
)
RETAILERS = _party("retailers", ORDERS_METADATA, 20)
COMPANIES = _party("companies", ORDERS_METADATA, 20)
ORDERS = Table(
    "orders",
    ORDERS_METADATA,
    _id(),
    Column("order_reference", String(20), nullable=False, unique=True),
    Column("request_id", Uuid(as_uuid=True), nullable=True),
    Column("order_date", _ts(), nullable=False),
    Column("company_id", Uuid(as_uuid=True), ForeignKey("companies.id"), nullable=False),
    Column("retailer_id", Uuid(as_uuid=True), ForeignKey("retailers.id"), nullable=False),
    Column("currency_id", Uuid(as_uuid=True), ForeignKey("currencies.id"), nullable=False),
    Column("initial_amount", BigInteger, nullable=False),
    Column("initial_discount", BigInteger, nullable=False),
    Column("total_amount", BigInteger, nullable=False),
    Column("status", String(20), nullable=False),
    Column("cancellation_reason", String(100), nullable=True),
    Column("notes", Text, nullable=True),
    *_created_updated(),
    Index("uq_orders_request_id", "request_id", unique=True),
)
ORDER_ITEMS = Table(
    "order_items",
    ORDERS_METADATA,
    _id(),
    Column(
        "order_id", Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    ),
    Column("product_id", Uuid(as_uuid=True), ForeignKey("products.id"), nullable=False),
    Column("description", String(255), nullable=False),
    Column("price", BigInteger, nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("discount", BigInteger, nullable=False),
    *_created_updated(),
)
ORDERS_OUTBOX = _outbox(ORDERS_METADATA)

FULFILLMENT_METADATA = MetaData()
STOCK = Table(
    "stock",
    FULFILLMENT_METADATA,
    _id(),
    Column("company_code", String(20), nullable=False),
    Column("product_code", String(30), nullable=False),
    Column("units", Integer, nullable=False),
    Column("reserved_units", Integer, nullable=False),
    Column("low_stock_threshold", Integer, nullable=False),
    *_created_updated(),
    UniqueConstraint("company_code", "product_code"),
)
RESERVATIONS = Table(
    "reservations",
    FULFILLMENT_METADATA,
    _id(),
    Column("stock_id", Uuid(as_uuid=True), ForeignKey("stock.id"), nullable=False),
    Column("company_code", String(20), nullable=False),
    Column("retailer_code", String(20), nullable=False),
    Column("product_code", String(30), nullable=False),
    Column("order_reference", String(20), nullable=False),
    Column("units", Integer, nullable=False),
    Column("status", String(20), nullable=False),
    *_created_updated(),
)
DESPATCHES = Table(
    "despatches",
    FULFILLMENT_METADATA,
    _id(),
    Column("despatch_reference", String(20), nullable=False, unique=True),
    Column("despatch_date", _ts(), nullable=False),
    Column("company_code", String(20), nullable=False),
    Column("retailer_code", String(20), nullable=False),
    Column("order_reference", String(20), nullable=False, unique=True),
    *_created_updated(),
)
DESPATCH_ITEMS = Table(
    "despatch_items",
    FULFILLMENT_METADATA,
    _id(),
    Column(
        "despatch_id",
        Uuid(as_uuid=True),
        ForeignKey("despatches.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("product_code", String(30), nullable=False),
    Column("units", Integer, nullable=False),
    *_created_updated(),
)
FULFILLMENT_OUTBOX = _outbox(FULFILLMENT_METADATA)

BILLING_METADATA = MetaData()
CREDITS = Table(
    "credits",
    BILLING_METADATA,
    _id(),
    Column("code", String(30), nullable=False, unique=True),
    Column("retailer_code", String(20), nullable=False),
    Column("company_code", String(20), nullable=False),
    Column("credit_limit", BigInteger, nullable=False),
    Column("currency_code", CHAR(3), nullable=False),
    *_created_updated(),
    UniqueConstraint("retailer_code", "company_code"),
)
CREDIT_ITEMS = Table(
    "credit_items",
    BILLING_METADATA,
    _id(),
    Column("credit_id", Uuid(as_uuid=True), ForeignKey("credits.id"), nullable=False),
    Column("order_reference", String(20), nullable=False),
    Column("amount", BigInteger, nullable=False),
    Column("type", String(20), nullable=False),
    Column("credit_date", _ts(), nullable=False),
    *_created_updated(),
)
INVOICES = Table(
    "invoices",
    BILLING_METADATA,
    _id(),
    Column("invoice_reference", String(20), nullable=False, unique=True),
    Column("invoice_date", _ts(), nullable=False),
    Column("company_code", String(20), nullable=False),
    Column("retailer_code", String(20), nullable=False),
    Column("order_reference", String(20), nullable=False, unique=True),
    Column("amount", BigInteger, nullable=False),
    Column("discount", BigInteger, nullable=False),
    Column("total_amount", BigInteger, nullable=False),
    Column("currency_code", CHAR(3), nullable=False),
    Column("status", String(20), nullable=False),
    Column("paid_at", _ts(), nullable=True),
    *_created_updated(),
)
INVOICE_ITEMS = Table(
    "invoice_items",
    BILLING_METADATA,
    _id(),
    Column(
        "invoice_id",
        Uuid(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("product_code", String(30), nullable=False),
    Column("units", Integer, nullable=False),
    Column("price", BigInteger, nullable=False),
    *_created_updated(),
)
PAYMENTS = Table(
    "payments",
    BILLING_METADATA,
    _id(),
    Column("payment_reference", String(30), nullable=False, unique=True),
    Column("invoice_id", Uuid(as_uuid=True), ForeignKey("invoices.id"), nullable=False),
    Column("amount", BigInteger, nullable=False),
    Column("currency_code", CHAR(3), nullable=False),
    Column("value_date", _ts(), nullable=False),
    Column("source", String(20), nullable=False),
    Column("created_at", _ts(), nullable=False),
)
BILLING_OUTBOX = _outbox(BILLING_METADATA)
