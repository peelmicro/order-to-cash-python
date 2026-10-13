"""Gateway settings: each a `pydantic-settings` class constructed once by
`composition.load_settings()` (the env-read guard,
`tests/architecture/test_composition_env_reads.py`). Nothing else in the service reads the
environment, `python -m otc_gateway` included.

No `populate_by_name` anywhere: with it pydantic-settings also reads the bare field names from the
environment, so an unrelated `$HOST`, `$PORT` or `$USER` would silently become a setting. Names are
#7's (`apps/gateway`, `.env.example`) where #7 had the knob; a value that would silently do nothing
(a limit of 0, a secret too short to sign with) is refused at boot, naming the variable.
"""

from pathlib import Path
from typing import Self
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# `specs/shared/openapi.yaml` of this checkout: services/gateway/src/otc_gateway/infrastructure/ is
# five levels below the repository root.
DEFAULT_OPENAPI_PATH = Path(__file__).resolve().parents[5] / "specs" / "shared" / "openapi.yaml"

# RFC 7518 section 3.2: an HS256 key shorter than the hash output (32 bytes) is not a key.
MIN_JWT_SECRET_BYTES = 32


class ServerSettings(BaseSettings):
    """Where `python -m otc_gateway` listens (#8 id 96: a Gateway that ignored `GATEWAY_PORT`).

    `uvicorn otc_gateway.main:app --port N` is still the way to pick a port by hand; the entry point
    is what makes the configured one the default."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = Field(default="0.0.0.0", validation_alias="GATEWAY_HOST")  # noqa: S104 - n8n and the web BFF reach it from containers
    port: int = Field(default=3001, ge=1, le=65535, validation_alias="GATEWAY_PORT")


class NatsSettings(BaseSettings):
    """`NATS_URL` (#7's name) and the per-call RPC deadline (`GATEWAY_RPC_TIMEOUT_MS`, #7's name
    and default 5000; #8 `NatsOptions.DefaultTimeoutMs`)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    url: str = Field(default="nats://localhost:4222", validation_alias="NATS_URL")
    rpc_timeout_ms: int = Field(default=5000, ge=1, validation_alias="GATEWAY_RPC_TIMEOUT_MS")


class MongoSettings(BaseSettings):
    """The read model's connection: the Projector's variable set (`MONGO_URI` wins; else host, port,
    user and password). No password default."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_uri: SecretStr | None = Field(default=None, validation_alias="MONGO_URI")
    host: str = Field(default="localhost", validation_alias="MONGO_HOST")
    port: int = Field(default=27017, validation_alias="MONGO_HOST_PORT")
    user: str = Field(default="otc_mongo_root", validation_alias="MONGO_INITDB_ROOT_USERNAME")
    password: SecretStr | None = Field(default=None, validation_alias="MONGO_INITDB_ROOT_PASSWORD")
    database: str = Field(default="otc_read_model", validation_alias="MONGO_DB_READMODEL")
    # How long the driver looks for a server before a read fails (its own default is 30 s, which
    # would hold an HTTP request open for half a minute while MongoDB is down).
    server_selection_timeout_ms: int = Field(
        default=5000, ge=1, validation_alias="GATEWAY_READ_MODEL_TIMEOUT_MS"
    )

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


class JwtSettings(BaseSettings):
    """`JWT_SECRET`, `JWT_ISSUER` (#7's names) and `JWT_EXPIRES_IN` in whole SECONDS (#8's reading;
    #7 took a duration string). There is NO secret default: a Gateway never boots on a signing key
    committed to source (#8 defect D3: settings that existed nowhere)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Absent means "not supplied", never a usable key: the validator below refuses it.
    secret: SecretStr | None = Field(default=None, validation_alias="JWT_SECRET")
    issuer: str = Field(default="order-to-cash", min_length=1, validation_alias="JWT_ISSUER")
    expires_in: int = Field(default=3600, ge=1, validation_alias="JWT_EXPIRES_IN")

    @model_validator(mode="after")
    def _the_secret_can_sign(self) -> Self:
        if self.secret is None:
            raise ValueError("no signing key: set JWT_SECRET")
        if len(self.secret.get_secret_value().encode("utf-8")) < MIN_JWT_SECRET_BYTES:
            raise ValueError(
                f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes (RFC 7518 section 3.2)"
            )
        return self

    @property
    def signing_key(self) -> str:
        return "" if self.secret is None else self.secret.get_secret_value()


class OperatorSettings(BaseSettings):
    """The single operator (`openapi.yaml` `/auth/login`): `GATEWAY_OPERATOR_USERNAME` /
    `GATEWAY_OPERATOR_PASSWORD` (already in `.env.example`) and `GATEWAY_OPERATOR_DISPLAY_NAME`
    (#7's name). No password default."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    username: str = Field(
        default="operator", min_length=1, validation_alias="GATEWAY_OPERATOR_USERNAME"
    )
    # Absent means "not supplied", never a usable password: the validator below refuses it.
    password: SecretStr | None = Field(default=None, validation_alias="GATEWAY_OPERATOR_PASSWORD")
    display_name: str = Field(
        default="Order-To-Cash Operator", validation_alias="GATEWAY_OPERATOR_DISPLAY_NAME"
    )

    @model_validator(mode="after")
    def _the_password_is_not_blank(self) -> Self:
        if self.password is None or not self.password.get_secret_value():
            raise ValueError("no operator password: set GATEWAY_OPERATOR_PASSWORD")
        return self

    @property
    def secret_password(self) -> str:
        return "" if self.password is None else self.password.get_secret_value()


class LoginThrottleSettings(BaseSettings):
    """R63's per-assessment numbers: `GATEWAY_LOGIN_RATE_LIMIT` attempts per
    `GATEWAY_LOGIN_RATE_WINDOW_MS` per client address (#7's names and defaults, 10 per 60 s)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    limit: int = Field(default=10, ge=1, validation_alias="GATEWAY_LOGIN_RATE_LIMIT")
    window_ms: int = Field(default=60_000, ge=1, validation_alias="GATEWAY_LOGIN_RATE_WINDOW_MS")


class IssuedOrderWindowSettings(BaseSettings):
    """How long, and how many, order ids `POST /orders` handed out are remembered for R55's 202
    (`GATEWAY_ISSUED_ORDER_WINDOW_TTL_MS` 300000, `GATEWAY_ISSUED_ORDER_WINDOW_CAPACITY` 10000: #7's
    names and defaults, #8 `GatewayOptions`)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ttl_ms: int = Field(
        default=300_000, ge=1, validation_alias="GATEWAY_ISSUED_ORDER_WINDOW_TTL_MS"
    )
    capacity: int = Field(
        default=10_000, ge=1, validation_alias="GATEWAY_ISSUED_ORDER_WINDOW_CAPACITY"
    )


class DocsSettings(BaseSettings):
    """Where the COMMITTED contract is read from for `GET /docs` (`GATEWAY_OPENAPI_PATH`; the
    default is this checkout's `specs/shared/openapi.yaml`). A file that is not there fails the
    boot: a `/docs` that answers an empty page is a contract the reviewer cannot read."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openapi_path: Path = Field(
        default=DEFAULT_OPENAPI_PATH, validation_alias="GATEWAY_OPENAPI_PATH"
    )


class SseSettings(BaseSettings):
    """`GET /orders/stream` (feature 26): `GATEWAY_SSE_BUFFER_CAPACITY` (the replay buffer, 500) and
    `GATEWAY_SSE_PING_INTERVAL_MS` (the heartbeat, 15000) are #7's and #8's names and defaults
    (`../order-to-cash-dotnet/.env.example:253-254`). `GATEWAY_SSE_CLIENT_QUEUE_CAPACITY` is #9's:
    #8 fixed it at 256 in code (`StreamHub.cs`); here it is a setting because it must not exceed the
    replay buffer. A client whose queue fills is disconnected and resumes from its `Last-Event-ID`;
    that resume is complete only when the buffer still holds everything the queue held."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    buffer_capacity: int = Field(default=500, ge=1, validation_alias="GATEWAY_SSE_BUFFER_CAPACITY")
    ping_interval_ms: int = Field(
        default=15_000, ge=1, validation_alias="GATEWAY_SSE_PING_INTERVAL_MS"
    )
    client_queue_capacity: int = Field(
        default=256, ge=1, validation_alias="GATEWAY_SSE_CLIENT_QUEUE_CAPACITY"
    )

    @model_validator(mode="after")
    def _a_client_queue_fits_in_the_buffer(self) -> Self:
        if self.client_queue_capacity > self.buffer_capacity:
            raise ValueError(
                f"GATEWAY_SSE_CLIENT_QUEUE_CAPACITY ({self.client_queue_capacity}) must not exceed "
                f"GATEWAY_SSE_BUFFER_CAPACITY ({self.buffer_capacity}): a client that falls behind "
                "is disconnected and resumes from the buffer, which must hold what its queue held"
            )
        return self


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
