"""Fulfillment database settings: the only place the connection URL is assembled.

Read from the same `.env` the compose file reads (`POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD`,
`POSTGRES_DB_FULFILLMENT`, `POSTGRES_HOST_PORT`), so the database name has one source of truth.
`FULFILLMENT_DATABASE_URL`, when set, wins outright (tests and deployments that carry a full URL).

There is NO password default (review_db_orders F5, #8 review_db_orders D6): with neither a full URL
nor `POSTGRES_APP_PASSWORD`, constructing the settings raises, so a service never boots on a
credential committed to source.
"""

from typing import Self

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class FulfillmentDatabaseSettings(BaseSettings):
    # No `populate_by_name`: with it, pydantic-settings also reads the bare field names from the
    # environment, so an unrelated `$USER` (or `$HOST`, `$PORT`) would silently become the
    # database user (measured on this machine: `juanpabloperez`).
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str | None = Field(default=None, validation_alias="FULFILLMENT_DATABASE_URL")
    host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    port: int = Field(default=5432, validation_alias=AliasChoices("POSTGRES_HOST_PORT"))
    user: str = Field(default="otc_app", validation_alias="POSTGRES_APP_USER")
    # Absent means "not supplied", never a usable password: the validator below refuses it.
    password: str | None = Field(default=None, validation_alias="POSTGRES_APP_PASSWORD")
    database: str = Field(default="otc_fulfillment", validation_alias="POSTGRES_DB_FULFILLMENT")

    @model_validator(mode="after")
    def _a_credential_must_be_supplied(self) -> Self:
        if not self.database_url and not self.password:
            raise ValueError(
                "no database credential: set FULFILLMENT_DATABASE_URL or POSTGRES_APP_PASSWORD"
            )
        return self

    @property
    def url(self) -> str:
        """The asyncpg URL (no sync driver exists in this service)."""
        if self.database_url:
            return self.database_url
        return URL.create(
            "postgresql+asyncpg",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
        ).render_as_string(hide_password=False)


class OutboxRelaySettings(BaseSettings):
    """The relay's knobs (Orders' variable names and defaults, shared: one `.env`, one relay shape).

    Same rule as `FulfillmentDatabaseSettings`: a `validation_alias` per field and NO
    `populate_by_name`, so a bare `$ENABLED` or `$BATCH_SIZE` in the shell never becomes a setting.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    enabled: bool = Field(default=True, validation_alias="OUTBOX_RELAY_ENABLED")
    poll_interval_ms: int = Field(default=250, validation_alias="OUTBOX_POLL_INTERVAL_MS")
    batch_size: int = Field(default=100, validation_alias="OUTBOX_BATCH_SIZE")
    publish_timeout_ms: int = Field(default=5000, validation_alias="OUTBOX_PUBLISH_TIMEOUT_MS")

    # The settings boundary: milliseconds become the float seconds `asyncio` takes. Not money.
    @property
    def poll_interval_seconds(self) -> float:
        return self.poll_interval_ms / 1000

    @property
    def publish_timeout_seconds(self) -> float:
        return self.publish_timeout_ms / 1000


class KafkaSettings(BaseSettings):
    """Where the producer connects. `KAFKA_BROKERS` is shared with Orders; the client id has its own
    variable, `FULFILLMENT_KAFKA_CLIENT_ID` (default `otc-fulfillment`, #7's and #8's value): the
    shared `KAFKA_CLIENT_ID` holds `otc-orders` in `.env`, so a shared name would put Orders' id on
    Fulfillment's connection.

    Same rule as `FulfillmentDatabaseSettings`: a `validation_alias` per field and NO
    `populate_by_name`.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    brokers: str = Field(default="localhost:9092", validation_alias="KAFKA_BROKERS")
    client_id: str = Field(
        default="otc-fulfillment", validation_alias="FULFILLMENT_KAFKA_CLIENT_ID"
    )


class NatsSettings(BaseSettings):
    """The NATS client's settings (`NATS_URL`: #7's name and default)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    url: str = Field(default="nats://localhost:4222", validation_alias="NATS_URL")


class ServerSettings(BaseSettings):
    """How many worker processes the server was told to run (`WEB_CONCURRENCY`, which uvicorn reads
    for its own `--workers` default). The composition root refuses more than one worker while the
    outbox relay is enabled (`outbox_and_idempotency/design.md` 5.2)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    web_concurrency: int = Field(default=1, validation_alias="WEB_CONCURRENCY")


class ResponderSettings(BaseSettings):
    """The responder's bound (`design.md` 8.2): the most `fulfillment.stock.*` requests handled at
    once. A bound below 1 would handle nothing, so it is refused at boot, naming the variable."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    max_concurrent_requests: int = Field(
        default=16, validation_alias="FULFILLMENT_MAX_CONCURRENT_REQUESTS"
    )

    @model_validator(mode="after")
    def _the_bound_is_at_least_one(self) -> Self:
        if self.max_concurrent_requests < 1:
            raise ValueError(
                "FULFILLMENT_MAX_CONCURRENT_REQUESTS must be at least 1 (a bound below 1 would "
                f"handle no request), got {self.max_concurrent_requests}"
            )
        return self
