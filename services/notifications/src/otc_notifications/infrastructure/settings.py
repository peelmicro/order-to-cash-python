"""Notifications database settings: the only place the connection URL is assembled.

Read from the same `.env` the compose file reads (`POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD`,
`POSTGRES_DB_NOTIFICATIONS`, `POSTGRES_HOST_PORT`), so the database name has one source of truth.
`NOTIFICATIONS_DATABASE_URL`, when set, wins outright (tests and deployments that carry a full URL).

There is NO password default (review_db_orders F5, #8 review_db_orders D6): with neither a full URL
nor `POSTGRES_APP_PASSWORD`, constructing the settings raises, so a service never boots on a
credential committed to source.
"""

from enum import StrEnum
from typing import Self

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class NotificationsDatabaseSettings(BaseSettings):
    # No `populate_by_name`: with it, pydantic-settings also reads the bare field names from the
    # environment, so an unrelated `$USER` (or `$HOST`, `$PORT`) would silently become the
    # database user (measured on this machine: `juanpabloperez`).
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str | None = Field(default=None, validation_alias="NOTIFICATIONS_DATABASE_URL")
    host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    port: int = Field(default=5432, validation_alias=AliasChoices("POSTGRES_HOST_PORT"))
    user: str = Field(default="otc_app", validation_alias="POSTGRES_APP_USER")
    # Absent means "not supplied", never a usable password: the validator below refuses it.
    password: str | None = Field(default=None, validation_alias="POSTGRES_APP_PASSWORD")
    database: str = Field(default="otc_notifications", validation_alias="POSTGRES_DB_NOTIFICATIONS")

    @model_validator(mode="after")
    def _a_credential_must_be_supplied(self) -> Self:
        if not self.database_url and not self.password:
            raise ValueError(
                "no database credential: set NOTIFICATIONS_DATABASE_URL or POSTGRES_APP_PASSWORD"
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


class KafkaSettings(BaseSettings):
    """Where the consumer connects. `KAFKA_BROKERS` is shared with the other services; the client
    id has its own variable, `NOTIFICATIONS_KAFKA_CLIENT_ID` (default `otc-notifications`, #7's
    and #8's value): the shared `KAFKA_CLIENT_ID` holds `otc-orders` in `.env`, so a shared name
    would put Orders' id on this connection.

    The client id is constrained to `^[A-Za-z0-9._-]+$` (BC34): aiokafka substitutes a default only
    for `None` and sends an empty string verbatim (measured), so an empty or blank variable must
    fail the boot, naming the variable.

    `group_id` is the consumer group (`NOTIFICATIONS_CONSUMER_GROUP`, #7's variable, default
    `notifications`, which is also the `processed_events` consumer name). The consumer reads from
    `latest`: Notifications owns no aggregate, so a fact the group never saw is an omission, not
    an inconsistency, and the durable ledger cannot prevent it because it only stops a duplicate
    of a fact already recorded; replaying a topic into a new group would e-mail history (#7 round
    2 and #8 `AutoOffsetReset.Latest`).

    No `populate_by_name`: a `validation_alias` per field.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    brokers: str = Field(default="localhost:9092", validation_alias="KAFKA_BROKERS")
    client_id: str = Field(
        default="otc-notifications",
        validation_alias="NOTIFICATIONS_KAFKA_CLIENT_ID",
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    group_id: str = Field(
        default="notifications",
        validation_alias="NOTIFICATIONS_CONSUMER_GROUP",
        pattern=r"^[A-Za-z0-9._-]+$",
    )


class SenderKind(StrEnum):
    CONSOLE = "console"
    SMTP = "smtp"


class SmtpSettings(BaseSettings):
    """Which `NotificationSender` adapter is bound, and how the SMTP one connects.

    `NOTIFICATIONS_SENDER` is the explicit choice (`console` | `smtp`), never inferred from whether
    a credential happens to be present (#8 `NotificationSenderKind`); `console` is the safe default.
    Mailpit (`MAILPIT_SMTP_HOST_PORT`, port 1025) enforces no authentication and no TLS locally.

    A PARTIAL credential pair (one of `SMTP_USER` / `SMTP_PASSWORD`) is refused at boot, whatever
    the sender: a half-configured pair is far more likely a copy-paste mistake than a choice, and
    falling back silently would make a demo irreproducible for invisible reasons (#7
    `smtp.config.ts`). `SMTP_PORT` must be a TCP port.

    No `populate_by_name`: a `validation_alias` per field.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sender: SenderKind = Field(default=SenderKind.CONSOLE, validation_alias="NOTIFICATIONS_SENDER")
    host: str = Field(default="localhost", validation_alias="SMTP_HOST")
    port: int = Field(default=1025, validation_alias="SMTP_PORT", ge=1, le=65535)
    from_email: str = Field(
        default="no-reply@order-to-cash.example", validation_alias="SMTP_FROM_EMAIL"
    )
    user: str | None = Field(default=None, validation_alias="SMTP_USER")
    password: str | None = Field(default=None, validation_alias="SMTP_PASSWORD")
    start_tls: bool = Field(default=False, validation_alias="SMTP_START_TLS")

    @model_validator(mode="after")
    def _a_credential_is_a_pair(self) -> Self:
        if bool(self.user) != bool(self.password):
            raise ValueError(
                "SMTP_USER and SMTP_PASSWORD must both be set or both be left unset: a partially "
                "configured credential pair is refused rather than silently ignored"
            )
        return self
