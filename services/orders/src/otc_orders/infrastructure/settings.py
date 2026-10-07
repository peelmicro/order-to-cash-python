"""Orders database settings: the only place the connection URL is assembled (pydantic-settings).

Read from the same `.env` the compose file reads (`POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD`,
`POSTGRES_DB_ORDERS`, `POSTGRES_HOST_PORT`), so the database name has one source of truth.
`ORDERS_DATABASE_URL`, when set, wins outright (tests and deployments that carry a full URL).

There is NO password default (review_db_orders F5, #8 review_db_orders D6): with neither a full URL
nor `POSTGRES_APP_PASSWORD`, constructing the settings raises, so a service never boots on a
credential committed to source. The compose file and `.env.example` carry the development value;
a developer's `.env` supplies it to the Alembic CLI and the service.
"""

from typing import Self

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class OrdersDatabaseSettings(BaseSettings):
    # No `populate_by_name` (review_db_fulfillment A1): with it, pydantic-settings also reads the
    # bare field names from the environment, so an unrelated `$USER` (or `$HOST`, `$PORT`,
    # `$PASSWORD`) would silently become the database user (measured on this machine:
    # `juanpabloperez`).
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str | None = Field(default=None, validation_alias="ORDERS_DATABASE_URL")
    host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    port: int = Field(default=5432, validation_alias=AliasChoices("POSTGRES_HOST_PORT"))
    user: str = Field(default="otc_app", validation_alias="POSTGRES_APP_USER")
    # Absent means "not supplied", never a usable password: the validator below refuses it.
    password: str | None = Field(default=None, validation_alias="POSTGRES_APP_PASSWORD")
    database: str = Field(default="otc_orders", validation_alias="POSTGRES_DB_ORDERS")

    @model_validator(mode="after")
    def _a_credential_must_be_supplied(self) -> Self:
        if not self.database_url and not self.password:
            raise ValueError(
                "no database credential: set ORDERS_DATABASE_URL or POSTGRES_APP_PASSWORD"
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
    """The relay's knobs (names are #7's `.env.example` variables; defaults are #7's and #8's).

    Same rule as `OrdersDatabaseSettings`: a `validation_alias` per field and NO `populate_by_name`,
    so a bare `$ENABLED` or `$BATCH_SIZE` in the shell never becomes a setting.
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
    """Where the producer connects (`KAFKA_BROKERS` and `KAFKA_CLIENT_ID` are #7's names).

    Same rule as `OrdersDatabaseSettings`: a `validation_alias` per field and NO `populate_by_name`.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    brokers: str = Field(default="localhost:9092", validation_alias="KAFKA_BROKERS")
    client_id: str = Field(default="otc-orders", validation_alias="KAFKA_CLIENT_ID")


class NatsSettings(BaseSettings):
    """The NATS client's settings (`NATS_URL`, `STOCK_CHECK_TIMEOUT_MS`: #7's names and defaults).

    Same rule as `OrdersDatabaseSettings`: a `validation_alias` per field and NO `populate_by_name`.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    url: str = Field(default="nats://localhost:4222", validation_alias="NATS_URL")
    stock_check_timeout_ms: int = Field(default=5000, validation_alias="STOCK_CHECK_TIMEOUT_MS")


class ServerSettings(BaseSettings):
    """How many worker processes the server was told to run (`WEB_CONCURRENCY`, which uvicorn reads
    for its own `--workers` default). The composition root refuses more than one worker while the
    outbox relay is enabled (`outbox_and_idempotency/design.md` 5.2)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    web_concurrency: int = Field(default=1, validation_alias="WEB_CONCURRENCY")


class SagaSettings(BaseSettings):
    """The saga's knobs (`design.md` 9.5, 12.3). Names are #7's (`saga.config.ts:12-24`) where #7
    had the knob; the lease, the in-flight maximum and the consumer flag are #9's.

    Same rule as `OrdersDatabaseSettings`: a `validation_alias` per field and NO `populate_by_name`,
    so a bare `$ENABLED` or `$INTERVAL_MS` in the shell never becomes a setting. Every ms value is
    an `int`; milliseconds become seconds only in the properties, at the settings boundary.

    A value that would silently do nothing is refused at boot, naming the setting and the value: a
    maximum of in-flight dispatches below 1 (#8 id 90's shape), an attempt count outside 1..10, any
    non-positive duration, and a lease that does not outlast twice the worst-case dispatch (SO16).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    command_timeout_ms: int = Field(default=5000, validation_alias="SAGA_COMMAND_TIMEOUT_MS")
    command_max_attempts: int = Field(default=3, validation_alias="SAGA_COMMAND_MAX_ATTEMPTS")
    command_backoff_ms: int = Field(default=500, validation_alias="SAGA_COMMAND_BACKOFF_MS")
    command_lease_ms: int = Field(default=60_000, validation_alias="SAGA_COMMAND_LEASE_MS")
    park_retry_cap_ms: int = Field(default=900_000, validation_alias="SAGA_PARK_RETRY_CAP_MS")
    sweeper_enabled: bool = Field(default=True, validation_alias="SAGA_SWEEPER_ENABLED")
    sweeper_interval_ms: int = Field(default=30_000, validation_alias="SAGA_SWEEPER_INTERVAL_MS")
    pending_grace_ms: int = Field(default=10_000, validation_alias="SAGA_PENDING_GRACE_MS")
    sweeper_batch_limit: int = Field(default=20, validation_alias="SAGA_SWEEPER_BATCH_LIMIT")
    fast_path_max_in_flight: int = Field(
        default=256, validation_alias="SAGA_FAST_PATH_MAX_IN_FLIGHT"
    )
    consumer_enabled: bool = Field(default=True, validation_alias="SAGA_CONSUMER_ENABLED")

    @model_validator(mode="after")
    def _the_attempt_count_is_one_to_ten(self) -> Self:
        if not 1 <= self.command_max_attempts <= 10:
            raise ValueError(
                f"SAGA_COMMAND_MAX_ATTEMPTS must be 1..10, got {self.command_max_attempts}"
            )
        return self

    @model_validator(mode="after")
    def _the_fast_path_maximum_is_at_least_one(self) -> Self:
        if self.fast_path_max_in_flight < 1:
            raise ValueError(
                "SAGA_FAST_PATH_MAX_IN_FLIGHT must be at least 1 (a maximum below 1 would "
                f"dispatch nothing), got {self.fast_path_max_in_flight}"
            )
        return self

    @model_validator(mode="after")
    def _every_duration_and_limit_is_positive(self) -> Self:
        for name, value in (
            ("SAGA_COMMAND_TIMEOUT_MS", self.command_timeout_ms),
            ("SAGA_COMMAND_BACKOFF_MS", self.command_backoff_ms),
            ("SAGA_COMMAND_LEASE_MS", self.command_lease_ms),
            ("SAGA_PARK_RETRY_CAP_MS", self.park_retry_cap_ms),
            ("SAGA_SWEEPER_INTERVAL_MS", self.sweeper_interval_ms),
            ("SAGA_PENDING_GRACE_MS", self.pending_grace_ms),
            ("SAGA_SWEEPER_BATCH_LIMIT", self.sweeper_batch_limit),
        ):
            if value < 1:
                raise ValueError(f"{name} must be positive, got {value}")
        return self

    @model_validator(mode="after")
    def _the_lease_outlasts_twice_the_worst_case_dispatch(self) -> Self:
        # SO16: a claimed row's lease must outlive its dispatch, or another claimer may take the row
        # while this one still holds it. Integer arithmetic only (a floor of the worst case).
        worst_case_ms = (
            self.command_max_attempts * self.command_timeout_ms
            + self.command_backoff_ms * (2 ** (self.command_max_attempts - 1) - 1)
        )
        if self.command_lease_ms < 2 * worst_case_ms:
            raise ValueError(
                f"SAGA_COMMAND_LEASE_MS={self.command_lease_ms} must be at least twice the "
                f"worst-case dispatch ({worst_case_ms} ms = SAGA_COMMAND_MAX_ATTEMPTS x "
                "SAGA_COMMAND_TIMEOUT_MS plus the back-off sum), i.e. "
                f"{2 * worst_case_ms} ms"
            )
        return self

    @property
    def sweeper_interval_seconds(self) -> float:
        return self.sweeper_interval_ms / 1000
