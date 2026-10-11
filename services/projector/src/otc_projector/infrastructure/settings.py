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
