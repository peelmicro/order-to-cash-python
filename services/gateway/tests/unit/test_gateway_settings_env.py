"""Every environment read of the Gateway, through pydantic-settings: each default, each refusal and
that each variable moves exactly its own field (the Projector's `test_projector_settings_env.py`,
extended to JWT, the operator, the login throttle, the issued-order window, the server and the
contract path). #8 defect D3 was JWT settings that existed nowhere: here the signing key has no
default and a short one is refused at boot.

Every test clears the variables it concerns and `chdir`s to an empty directory, so no developer
`.env` can supply a value. Loop scope: nothing here is async.
"""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings

from otc_gateway.composition import GatewaySettings, load_settings
from otc_gateway.infrastructure.settings import (
    DEFAULT_OPENAPI_PATH,
    DocsSettings,
    IssuedOrderWindowSettings,
    JwtSettings,
    LoginThrottleSettings,
    MongoSettings,
    NatsSettings,
    OperatorSettings,
    ServerSettings,
    SseSettings,
)

# variable -> (settings class, attribute, the default with the environment cleared)
DEFAULTS: dict[str, tuple[type[BaseSettings], str, Any]] = {
    "GATEWAY_HOST": (ServerSettings, "host", "0.0.0.0"),  # noqa: S104
    "GATEWAY_PORT": (ServerSettings, "port", 3001),
    "NATS_URL": (NatsSettings, "url", "nats://localhost:4222"),
    "GATEWAY_RPC_TIMEOUT_MS": (NatsSettings, "rpc_timeout_ms", 5000),
    "MONGO_HOST": (MongoSettings, "host", "localhost"),
    "MONGO_HOST_PORT": (MongoSettings, "port", 27017),
    "MONGO_INITDB_ROOT_USERNAME": (MongoSettings, "user", "otc_mongo_root"),
    "MONGO_DB_READMODEL": (MongoSettings, "database", "otc_read_model"),
    "GATEWAY_READ_MODEL_TIMEOUT_MS": (MongoSettings, "server_selection_timeout_ms", 5000),
    "JWT_ISSUER": (JwtSettings, "issuer", "order-to-cash"),
    "JWT_EXPIRES_IN": (JwtSettings, "expires_in", 3600),
    "GATEWAY_OPERATOR_USERNAME": (OperatorSettings, "username", "operator"),
    "GATEWAY_OPERATOR_DISPLAY_NAME": (OperatorSettings, "display_name", "Order-To-Cash Operator"),
    "GATEWAY_LOGIN_RATE_LIMIT": (LoginThrottleSettings, "limit", 10),
    "GATEWAY_LOGIN_RATE_WINDOW_MS": (LoginThrottleSettings, "window_ms", 60_000),
    "GATEWAY_ISSUED_ORDER_WINDOW_TTL_MS": (IssuedOrderWindowSettings, "ttl_ms", 300_000),
    "GATEWAY_ISSUED_ORDER_WINDOW_CAPACITY": (IssuedOrderWindowSettings, "capacity", 10_000),
    "GATEWAY_OPENAPI_PATH": (DocsSettings, "openapi_path", DEFAULT_OPENAPI_PATH),
    "GATEWAY_SSE_BUFFER_CAPACITY": (SseSettings, "buffer_capacity", 500),
    "GATEWAY_SSE_PING_INTERVAL_MS": (SseSettings, "ping_interval_ms", 15_000),
    "GATEWAY_SSE_CLIENT_QUEUE_CAPACITY": (SseSettings, "client_queue_capacity", 256),
}
NO_DEFAULT = ("JWT_SECRET", "GATEWAY_OPERATOR_PASSWORD", "MONGO_INITDB_ROOT_PASSWORD", "MONGO_URI")
GOOD_SECRET = "0123456789abcdef0123456789abcdef"  # exactly 32 bytes


@pytest.fixture
def required(clean_gateway_environment: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    clean_gateway_environment.setenv("JWT_SECRET", GOOD_SECRET)
    clean_gateway_environment.setenv("GATEWAY_OPERATOR_PASSWORD", "operator-password")
    clean_gateway_environment.setenv("MONGO_INITDB_ROOT_PASSWORD", "mongo-password")
    return clean_gateway_environment


@pytest.mark.parametrize("variable", sorted(DEFAULTS))
def test_each_variable_has_its_documented_default_with_the_environment_cleared(
    required: pytest.MonkeyPatch, variable: str
) -> None:
    cls, attribute, default = DEFAULTS[variable]

    assert getattr(cls(), attribute) == default


def test_the_default_openapi_path_is_this_checkouts_committed_contract() -> None:
    assert DEFAULT_OPENAPI_PATH.is_file()
    assert DEFAULT_OPENAPI_PATH.parts[-3:] == ("specs", "shared", "openapi.yaml")


def test_load_settings_builds_every_class_with_the_four_defaults_that_name_the_feature(
    required: pytest.MonkeyPatch,
) -> None:
    settings = load_settings()

    assert isinstance(settings, GatewaySettings)
    assert settings.server.port == 3001  # #8 id 96: GATEWAY_PORT, #7's default
    assert settings.jwt.signing_key == GOOD_SECRET
    assert settings.login_throttle.limit == 10
    assert settings.operator.secret_password == "operator-password"


@pytest.mark.parametrize(
    ("variable", "cls"),
    [
        ("JWT_SECRET", JwtSettings),
        ("GATEWAY_OPERATOR_PASSWORD", OperatorSettings),
    ],
)
def test_a_secret_with_no_default_fails_the_boot_naming_the_variable(
    clean_gateway_environment: pytest.MonkeyPatch, variable: str, cls: type[BaseSettings]
) -> None:
    clean_gateway_environment.setenv("JWT_SECRET", GOOD_SECRET)
    clean_gateway_environment.setenv("GATEWAY_OPERATOR_PASSWORD", "operator-password")
    clean_gateway_environment.delenv(variable)

    with pytest.raises(ValidationError) as raised:
        cls()

    assert variable in str(raised.value)


def test_no_mongo_password_and_no_uri_fails_naming_both(
    clean_gateway_environment: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError) as raised:
        MongoSettings()

    assert "MONGO_INITDB_ROOT_PASSWORD" in str(raised.value)
    assert "MONGO_URI" in str(raised.value)


def test_a_jwt_secret_shorter_than_32_bytes_is_refused_and_exactly_32_is_accepted(
    clean_gateway_environment: pytest.MonkeyPatch,
) -> None:
    clean_gateway_environment.setenv("JWT_SECRET", GOOD_SECRET[:-1])  # 31 bytes
    with pytest.raises(ValidationError) as raised:
        JwtSettings()
    assert "JWT_SECRET" in str(raised.value)
    assert "32 bytes" in str(raised.value)

    clean_gateway_environment.setenv("JWT_SECRET", GOOD_SECRET)
    assert JwtSettings().signing_key == GOOD_SECRET


def test_the_secret_length_is_counted_in_bytes_not_characters(
    clean_gateway_environment: pytest.MonkeyPatch,
) -> None:
    clean_gateway_environment.setenv("JWT_SECRET", "é" * 16)  # 16 characters, 32 bytes

    assert len(JwtSettings().signing_key) == 16


def test_an_empty_operator_password_is_refused(
    clean_gateway_environment: pytest.MonkeyPatch,
) -> None:
    clean_gateway_environment.setenv("GATEWAY_OPERATOR_PASSWORD", "")

    with pytest.raises(ValidationError, match="GATEWAY_OPERATOR_PASSWORD"):
        OperatorSettings()


@pytest.mark.parametrize(
    ("variable", "cls", "value"),
    [
        ("GATEWAY_PORT", ServerSettings, "0"),
        ("GATEWAY_PORT", ServerSettings, "65536"),
        ("GATEWAY_PORT", ServerSettings, "not-a-port"),
        ("GATEWAY_RPC_TIMEOUT_MS", NatsSettings, "0"),
        ("GATEWAY_READ_MODEL_TIMEOUT_MS", MongoSettings, "0"),
        ("JWT_EXPIRES_IN", JwtSettings, "0"),
        ("JWT_ISSUER", JwtSettings, ""),
        ("GATEWAY_LOGIN_RATE_LIMIT", LoginThrottleSettings, "0"),
        ("GATEWAY_LOGIN_RATE_LIMIT", LoginThrottleSettings, "abc"),
        ("GATEWAY_LOGIN_RATE_WINDOW_MS", LoginThrottleSettings, "-5"),
        ("GATEWAY_ISSUED_ORDER_WINDOW_TTL_MS", IssuedOrderWindowSettings, "0"),
        ("GATEWAY_ISSUED_ORDER_WINDOW_CAPACITY", IssuedOrderWindowSettings, "0"),
    ],
)
def test_a_value_that_would_silently_do_nothing_is_refused_naming_the_variable(
    required: pytest.MonkeyPatch, variable: str, cls: type[BaseSettings], value: str
) -> None:
    required.setenv(variable, value)

    with pytest.raises(ValidationError) as raised:
        cls()

    assert variable in str(raised.value)


def test_each_variable_set_to_a_sentinel_changes_exactly_the_field_that_reads_it(
    required: pytest.MonkeyPatch,
) -> None:
    sentinels: dict[str, str] = {
        "GATEWAY_HOST": "127.0.0.9",
        "GATEWAY_PORT": "38123",
        "NATS_URL": "nats://nats.sentinel:4999",
        "GATEWAY_RPC_TIMEOUT_MS": "1234",
        "MONGO_HOST": "mongo.sentinel",
        "MONGO_HOST_PORT": "27999",
        "MONGO_INITDB_ROOT_USERNAME": "user-sentinel",
        "MONGO_DB_READMODEL": "readmodel_sentinel",
        "GATEWAY_READ_MODEL_TIMEOUT_MS": "1234",
        "JWT_ISSUER": "issuer-sentinel",
        "JWT_EXPIRES_IN": "777",
        "GATEWAY_OPERATOR_USERNAME": "operator-sentinel",
        "GATEWAY_OPERATOR_DISPLAY_NAME": "Display Sentinel",
        "GATEWAY_LOGIN_RATE_LIMIT": "7",
        "GATEWAY_LOGIN_RATE_WINDOW_MS": "4321",
        "GATEWAY_ISSUED_ORDER_WINDOW_TTL_MS": "9876",
        "GATEWAY_ISSUED_ORDER_WINDOW_CAPACITY": "55",
        "GATEWAY_OPENAPI_PATH": "/sentinel/openapi.yaml",
        "GATEWAY_SSE_BUFFER_CAPACITY": "900",
        "GATEWAY_SSE_PING_INTERVAL_MS": "4321",
        "GATEWAY_SSE_CLIENT_QUEUE_CAPACITY": "55",
    }
    assert set(sentinels) == set(DEFAULTS)  # the literal covers every defaulted variable
    for variable, value in sentinels.items():
        cls, attribute, _ = DEFAULTS[variable]
        required.setenv(variable, value)
        settings = cls()
        read = getattr(settings, attribute)
        assert str(read) == value, variable
        # no OTHER field of that class moved
        for other, (other_cls, other_attribute, default) in DEFAULTS.items():
            if other_cls is cls and other != variable:
                assert getattr(settings, other_attribute) == default, (variable, other)
        required.delenv(variable)


def test_the_mongo_uri_is_assembled_with_reserved_characters_quoted_and_a_uri_wins(
    required: pytest.MonkeyPatch,
) -> None:
    required.setenv("MONGO_INITDB_ROOT_USERNAME", "u@s")
    required.setenv("MONGO_INITDB_ROOT_PASSWORD", "p@ss/w:rd")
    required.setenv("MONGO_HOST", "mongo.sentinel")
    required.setenv("MONGO_HOST_PORT", "27999")

    assert (
        MongoSettings().uri
        == "mongodb://u%40s:p%40ss%2Fw%3Ard@mongo.sentinel:27999/?authSource=admin"
    )

    required.setenv("MONGO_URI", "mongodb://uri-user:uri-pw@uri.sentinel:1/?authSource=x")
    assert MongoSettings().uri == "mongodb://uri-user:uri-pw@uri.sentinel:1/?authSource=x"


def test_a_bare_name_in_the_shell_never_becomes_a_setting(
    required: pytest.MonkeyPatch,
) -> None:
    """No `populate_by_name`: `$HOST`, `$PORT` and `$USER` are in every shell."""
    required.setenv("HOST", "shell.sentinel")
    required.setenv("PORT", "1")
    required.setenv("USER", "shell-user")

    assert ServerSettings().port == 3001
    assert ServerSettings().host == "0.0.0.0"  # noqa: S104
    assert MongoSettings().user == "otc_mongo_root"


def test_the_env_example_file_in_the_working_directory_is_read_not_the_developers(
    required: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("GATEWAY_PORT=39001\n", encoding="utf-8")

    assert ServerSettings().port == 39001  # `.env` in the CWD is a source...
    required.setenv("GATEWAY_PORT", "39002")
    assert ServerSettings().port == 39002  # ...and the process environment outranks it


# ------------------------------------------------------------------------------ the stream (R55)


def test_r55_a_client_queue_larger_than_the_replay_buffer_is_refused_naming_both_variables(
    required: pytest.MonkeyPatch,
) -> None:
    """A client that falls behind is disconnected and resumes from the buffer, which must hold
    everything its queue held: otherwise the resume is incomplete (a gap the contract does not
    allow: at-least-once)."""
    required.setenv("GATEWAY_SSE_BUFFER_CAPACITY", "10")
    required.setenv("GATEWAY_SSE_CLIENT_QUEUE_CAPACITY", "11")

    with pytest.raises(ValidationError) as refused:
        SseSettings()

    assert "GATEWAY_SSE_CLIENT_QUEUE_CAPACITY" in str(refused.value)
    assert "GATEWAY_SSE_BUFFER_CAPACITY" in str(refused.value)
    required.setenv("GATEWAY_SSE_CLIENT_QUEUE_CAPACITY", "10")
    assert SseSettings().client_queue_capacity == 10  # equal is allowed


@pytest.mark.parametrize(
    "variable",
    [
        "GATEWAY_SSE_BUFFER_CAPACITY",
        "GATEWAY_SSE_PING_INTERVAL_MS",
        "GATEWAY_SSE_CLIENT_QUEUE_CAPACITY",
    ],
)
def test_r55_a_stream_setting_of_zero_is_refused_because_it_would_silently_do_nothing(
    required: pytest.MonkeyPatch, variable: str
) -> None:
    required.setenv(variable, "0")

    with pytest.raises(ValidationError) as refused:
        SseSettings()

    assert variable in str(refused.value)
