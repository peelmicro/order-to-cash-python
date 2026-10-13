"""Projector settings: MongoDB, Kafka and NATS, each a `pydantic-settings` class constructed once by
`composition.load_settings()` (the env-read guard,
`tests/architecture/test_composition_env_reads.py`).

* `MongoSettings` reads the seed's variable set (`services/seed/src/otc_seed/infrastructure/
  settings.py:47-54`). `MONGO_URI` wins outright. Without it the URI is assembled from the host,
  port, user and password; the seed uses SQLAlchemy's `URL.create`, the projector has no SQLAlchemy,
  so user and password go through `urllib.parse.quote_plus` (a password such as `p@ss/w:rd` must
  survive the round trip: ledger L31). There is NO password default: neither a URI nor a password
  fails the boot, naming both variables.
* `KafkaSettings` follows Notifications' (`PROJECTOR_KAFKA_CLIENT_ID`, `PROJECTOR_CONSUMER_GROUP`,
  #7's variable names), each constrained to `^[A-Za-z0-9._-]+$`: aiokafka sends an empty client id
  verbatim, so an empty or blank variable must fail the boot, naming the variable.
* `NatsSettings` is Billing's (`NATS_URL`).

No `populate_by_name`: with it pydantic-settings also reads the bare field names from the
environment, so an unrelated `$USER` or `$HOST` would silently become a setting.
"""

from typing import Self
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The projector's consumer group is the dedup-key prefix's consumer name (`PR38`); the default is
# the literal `projector`, equal to `ConsumerName.PROJECTOR.value` (a unit test asserts it).
CLIENT_ID_PATTERN = r"^[A-Za-z0-9._-]+$"


class MongoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_uri: SecretStr | None = Field(default=None, validation_alias="MONGO_URI")
    host: str = Field(default="localhost", validation_alias="MONGO_HOST")
    port: int = Field(default=27017, validation_alias="MONGO_HOST_PORT")
    user: str = Field(default="otc_mongo_root", validation_alias="MONGO_INITDB_ROOT_USERNAME")
    # Absent means "not supplied", never a usable password: the validator below refuses it.
    password: SecretStr | None = Field(default=None, validation_alias="MONGO_INITDB_ROOT_PASSWORD")
    database: str = Field(default="otc_read_model", validation_alias="MONGO_DB_READMODEL")

    @model_validator(mode="after")
    def _a_credential_must_be_supplied(self) -> Self:
        if self.mongo_uri is None and self.password is None:
            raise ValueError("no MongoDB credential: set MONGO_INITDB_ROOT_PASSWORD or MONGO_URI")
        return self

    @property
    def uri(self) -> str:
        if self.mongo_uri is not None:
            return self.mongo_uri.get_secret_value()
        password = self.password.get_secret_value() if self.password is not None else ""
        return (
            f"mongodb://{quote_plus(self.user)}:{quote_plus(password)}"
            f"@{self.host}:{self.port}/?authSource=admin"
        )


class KafkaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    brokers: str = Field(default="localhost:9092", validation_alias="KAFKA_BROKERS")
    client_id: str = Field(
        default="otc-projector",
        validation_alias="PROJECTOR_KAFKA_CLIENT_ID",
        pattern=CLIENT_ID_PATTERN,
    )
    group_id: str = Field(
        default="projector",
        validation_alias="PROJECTOR_CONSUMER_GROUP",
        pattern=CLIENT_ID_PATTERN,
    )


class NatsSettings(BaseSettings):
    """The NATS client's settings (`NATS_URL`: #7's name and default)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    url: str = Field(default="nats://localhost:4222", validation_alias="NATS_URL")


class TelemetrySettings(BaseSettings):
    """Where traces and metrics are exported (`OTEL_EXPORTER_OTLP_ENDPOINT`, the OpenTelemetry
    standard name and #8's). A BASE URL (`http://host:4318`): the exporters append `/v1/traces` and
    `/v1/metrics`. EMPTY by default, which means no exporter at all, so nothing is sent to whatever
    listens on `localhost` (#8 id 104's shape).

    Same rule as the other settings classes: a `validation_alias` and NO `populate_by_name`. This is
    the only place the variable is read (FastAPI's own auto-configuration would read it too; every
    app switches that off, `tests/architecture/test_telemetry_wiring.py`).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    otlp_endpoint: str = Field(default="", validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT")


# What the fact subscriber configures as `max_poll_interval_ms` (it is aiokafka's default, written
# down so that the retry settings below and the subscriber read the SAME number).
CONSUMER_MAX_POLL_INTERVAL_MS = 300_000


class FactRetrySettings(BaseSettings):
    """How a fact consumer retries a record before it dead-letters it (`R16`, `OR1`).

    `FACT_RETRY_MAX_ATTEMPTS` is the number of times the record's processing is attempted (3 by
    default, 1 to 10: a value outside the range would either never process or retry for minutes
    while the partition is held). `FACT_RETRY_BACKOFF_MS` is the wait after the first failed attempt
    (500 by default); it doubles after every further failure and may be 0 (no wait). Both names are
    #7's and #8's.

    Same rule as the other settings classes: a `validation_alias` per field and NO
    `populate_by_name`. A value that would silently do something else is refused at boot, naming the
    variable and the value.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    max_attempts: int = Field(default=3, validation_alias="FACT_RETRY_MAX_ATTEMPTS")
    backoff_ms: int = Field(default=500, validation_alias="FACT_RETRY_BACKOFF_MS")

    @model_validator(mode="after")
    def _the_attempt_count_is_one_to_ten(self) -> Self:
        if not 1 <= self.max_attempts <= 10:
            raise ValueError(f"FACT_RETRY_MAX_ATTEMPTS must be 1..10, got {self.max_attempts}")
        return self

    @model_validator(mode="after")
    def _the_backoff_is_not_negative(self) -> Self:
        if self.backoff_ms < 0:
            raise ValueError(f"FACT_RETRY_BACKOFF_MS must not be negative, got {self.backoff_ms}")
        return self

    @model_validator(mode="after")
    def _the_worst_case_backoff_stays_under_the_consumers_poll_interval(self) -> Self:
        # Between attempts the record's partition is held, the consumer polls nothing and is
        # evicted from its group once `max_poll_interval_ms` has passed (aiokafka). The worst case
        # waits `backoff * (2^(attempts-1) - 1)`: whole milliseconds, integer arithmetic only.
        # Runs after the range checks above (a refused value never reaches this sum).
        if not 1 <= self.max_attempts <= 10 or self.backoff_ms < 0:
            return self
        worst_case_ms = self.backoff_ms * ((1 << (self.max_attempts - 1)) - 1)
        if worst_case_ms >= CONSUMER_MAX_POLL_INTERVAL_MS:
            raise ValueError(
                f"FACT_RETRY_MAX_ATTEMPTS={self.max_attempts} with FACT_RETRY_BACKOFF_MS="
                f"{self.backoff_ms} waits {worst_case_ms} ms between attempts in the worst case, "
                f"which reaches the consumer's max_poll_interval_ms "
                f"({CONSUMER_MAX_POLL_INTERVAL_MS}): the consumer would be evicted from its group "
                "while it retries"
            )
        return self
