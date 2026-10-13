"""A5: every environment read of the Projector, through pydantic-settings, each default and each
refusal proven (Notifications' `test_notifications_settings_env.py`, ported to MongoDB, Kafka
and NATS).

Every test clears the variables it concerns and `chdir`s to an empty directory, so no developer
`.env` can supply a value. Loop scope: nothing here is async.
"""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings
from pymongo.uri_parser import parse_uri

from otc_projector.infrastructure.messaging.consumer_name import ConsumerName
from otc_projector.infrastructure.settings import (
    FactRetrySettings,
    KafkaSettings,
    MongoSettings,
    NatsSettings,
    TelemetrySettings,
)

# variable -> (settings class, attribute, the default with the environment cleared)
DEFAULTS: dict[str, tuple[type[BaseSettings], str, Any]] = {
    "MONGO_HOST": (MongoSettings, "host", "localhost"),
    "MONGO_HOST_PORT": (MongoSettings, "port", 27017),
    "MONGO_INITDB_ROOT_USERNAME": (MongoSettings, "user", "otc_mongo_root"),
    "MONGO_DB_READMODEL": (MongoSettings, "database", "otc_read_model"),
    "KAFKA_BROKERS": (KafkaSettings, "brokers", "localhost:9092"),
    "PROJECTOR_KAFKA_CLIENT_ID": (KafkaSettings, "client_id", "otc-projector"),
    "PROJECTOR_CONSUMER_GROUP": (KafkaSettings, "group_id", "projector"),
    "NATS_URL": (NatsSettings, "url", "nats://localhost:4222"),
    "OTEL_EXPORTER_OTLP_ENDPOINT": (TelemetrySettings, "otlp_endpoint", ""),
    "FACT_RETRY_MAX_ATTEMPTS": (FactRetrySettings, "max_attempts", 3),
    "FACT_RETRY_BACKOFF_MS": (FactRetrySettings, "backoff_ms", 500),
}
EVERY_VARIABLE = (*DEFAULTS, "MONGO_URI", "MONGO_INITDB_ROOT_PASSWORD")


@pytest.fixture
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    monkeypatch.chdir(tmp_path)  # an empty directory: no `.env` supplies a value
    for name in EVERY_VARIABLE:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def build_mongo(**values: str) -> MongoSettings:
    return MongoSettings.model_validate(values)


@pytest.mark.parametrize("variable", sorted(DEFAULTS))
def test_each_variable_has_its_documented_default_with_the_environment_cleared(
    clean_environment: pytest.MonkeyPatch, variable: str
) -> None:
    clean_environment.setenv("MONGO_INITDB_ROOT_PASSWORD", "baseline-password")
    cls, attribute, default = DEFAULTS[variable]
    assert getattr(cls(), attribute) == default


def test_the_default_consumer_group_is_the_ledgers_consumer_name() -> None:
    assert KafkaSettings().group_id == ConsumerName.PROJECTOR.value == "projector"


def test_mongo_uri_wins_outright(clean_environment: pytest.MonkeyPatch) -> None:
    clean_environment.setenv("MONGO_URI", "mongodb://uri-user:uri-pw@uri.sentinel:1/?authSource=x")
    clean_environment.setenv("MONGO_INITDB_ROOT_PASSWORD", "other-password")
    clean_environment.setenv("MONGO_HOST", "ignored.sentinel")
    assert MongoSettings().uri == "mongodb://uri-user:uri-pw@uri.sentinel:1/?authSource=x"


def test_no_password_and_no_uri_fails_naming_both_variables(
    clean_environment: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError) as raised:
        MongoSettings()
    message = str(raised.value)
    assert "MONGO_INITDB_ROOT_PASSWORD" in message
    assert "MONGO_URI" in message


def test_a_password_and_user_with_reserved_characters_round_trip_through_the_uri(
    clean_environment: pytest.MonkeyPatch,
) -> None:
    clean_environment.setenv("MONGO_INITDB_ROOT_USERNAME", "u@s")
    clean_environment.setenv("MONGO_INITDB_ROOT_PASSWORD", "p@ss/w:rd")
    clean_environment.setenv("MONGO_HOST", "mongo.sentinel")
    clean_environment.setenv("MONGO_HOST_PORT", "27999")
    parsed = parse_uri(MongoSettings().uri)
    assert parsed["username"] == "u@s"
    assert parsed["password"] == "p@ss/w:rd"
    assert parsed["nodelist"] == [("mongo.sentinel", 27999)]
    assert parsed["options"]["authSource"] == "admin"


@pytest.mark.parametrize("variable", ["PROJECTOR_KAFKA_CLIENT_ID", "PROJECTOR_CONSUMER_GROUP"])
@pytest.mark.parametrize("value", ["", "   ", "has space", "has/slash"])
def test_an_empty_or_blank_client_id_or_group_fails_naming_the_variable(
    clean_environment: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    clean_environment.setenv(variable, value)
    with pytest.raises(ValidationError) as raised:
        KafkaSettings()
    assert variable in str(raised.value)


def test_each_variable_set_to_a_sentinel_changes_exactly_the_field_that_reads_it(
    clean_environment: pytest.MonkeyPatch,
) -> None:
    clean_environment.setenv("MONGO_INITDB_ROOT_PASSWORD", "baseline-password")
    sentinels = {
        "MONGO_HOST": ("host", "mongo.sentinel"),
        "MONGO_INITDB_ROOT_USERNAME": ("user", "user-sentinel"),
        "MONGO_DB_READMODEL": ("database", "readmodel_sentinel"),
    }
    for variable, (attribute, value) in sentinels.items():
        clean_environment.setenv(variable, value)
        settings = MongoSettings()
        assert getattr(settings, attribute) == value
        others = {a for _, (a, _) in sentinels.items() if a != attribute}
        for other in others:
            assert getattr(settings, other) != getattr(settings, attribute)
        clean_environment.delenv(variable)
    clean_environment.setenv("KAFKA_BROKERS", "kafka.sentinel:19092")
    clean_environment.setenv("PROJECTOR_KAFKA_CLIENT_ID", "client-sentinel")
    clean_environment.setenv("PROJECTOR_CONSUMER_GROUP", "group-sentinel")
    clean_environment.setenv("NATS_URL", "nats://nats.sentinel:4333")
    kafka = KafkaSettings()
    assert (kafka.brokers, kafka.client_id, kafka.group_id) == (
        "kafka.sentinel:19092",
        "client-sentinel",
        "group-sentinel",
    )
    assert NatsSettings().url == "nats://nats.sentinel:4333"
    clean_environment.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otlp.sentinel:14318")
    assert TelemetrySettings().otlp_endpoint == "http://otlp.sentinel:14318"
    clean_environment.setenv("FACT_RETRY_MAX_ATTEMPTS", "7")
    clean_environment.setenv("FACT_RETRY_BACKOFF_MS", "271")
    retry = FactRetrySettings()
    assert (retry.max_attempts, retry.backoff_ms) == (7, 271)
    assert TelemetrySettings().otlp_endpoint == "http://otlp.sentinel:14318"
    # no other class moved: the endpoint is read by the telemetry class alone
    assert NatsSettings().url == "nats://nats.sentinel:4333"
    assert kafka.brokers == "kafka.sentinel:19092"


def test_no_settings_class_lets_a_bare_field_name_read_the_environment() -> None:
    for cls in (MongoSettings, KafkaSettings, NatsSettings, TelemetrySettings, FactRetrySettings):
        assert not cls.model_config.get("populate_by_name"), cls.__name__
        assert not cls.model_config.get("validate_by_name"), cls.__name__
        for name, field in cls.model_fields.items():
            assert field.validation_alias is not None, f"{cls.__name__}.{name}: implicit env name"


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("FACT_RETRY_MAX_ATTEMPTS", "0"),
        ("FACT_RETRY_MAX_ATTEMPTS", "11"),
        ("FACT_RETRY_MAX_ATTEMPTS", "-1"),
        ("FACT_RETRY_BACKOFF_MS", "-1"),
    ],
)
def test_fact_retry_refuses_a_value_outside_its_range_naming_the_variable(
    clean_environment: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    clean_environment.setenv(variable, value)

    with pytest.raises(ValidationError) as refused:
        FactRetrySettings()

    # the MESSAGE names the variable: pydantic also echoes the raw input (keyed by the variable) in
    # the rendered error, which would satisfy a `match=` on the text of the whole error
    [error] = refused.value.errors()
    assert variable in error["msg"], error["msg"]
    assert value in error["msg"], error["msg"]


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("FACT_RETRY_MAX_ATTEMPTS", "10"),
        ("FACT_RETRY_MAX_ATTEMPTS", "1"),
        ("FACT_RETRY_BACKOFF_MS", "0"),
    ],
)
def test_fact_retry_accepts_its_boundaries(
    clean_environment: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    clean_environment.setenv(variable, value)

    FactRetrySettings()


@pytest.mark.parametrize(
    ("attempts", "backoff_ms"),
    [("2", "299999"), ("10", "587")],
    ids=["two attempts, one millisecond under", "ten attempts, the last backoff that fits"],
)
def test_f2_a_worst_case_backoff_under_the_poll_interval_is_accepted(
    clean_environment: pytest.MonkeyPatch, attempts: str, backoff_ms: str
) -> None:
    clean_environment.setenv("FACT_RETRY_MAX_ATTEMPTS", attempts)
    clean_environment.setenv("FACT_RETRY_BACKOFF_MS", backoff_ms)

    FactRetrySettings()


@pytest.mark.parametrize(
    ("attempts", "backoff_ms", "worst_case_ms"),
    [("2", "300000", "300000"), ("10", "588", "300468")],
    ids=["two attempts, exactly at the interval", "ten attempts, the first backoff that is over"],
)
def test_f2_a_worst_case_backoff_that_reaches_the_poll_interval_is_refused_naming_both_variables(
    clean_environment: pytest.MonkeyPatch, attempts: str, backoff_ms: str, worst_case_ms: str
) -> None:
    clean_environment.setenv("FACT_RETRY_MAX_ATTEMPTS", attempts)
    clean_environment.setenv("FACT_RETRY_BACKOFF_MS", backoff_ms)

    with pytest.raises(ValidationError) as refused:
        FactRetrySettings()

    [error] = refused.value.errors()
    assert "FACT_RETRY_MAX_ATTEMPTS=" + attempts in error["msg"], error["msg"]
    assert "FACT_RETRY_BACKOFF_MS=" + backoff_ms in error["msg"], error["msg"]
    assert f"waits {worst_case_ms} ms" in error["msg"], error["msg"]
    assert "max_poll_interval_ms (300000)" in error["msg"], error["msg"]
