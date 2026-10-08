"""Every environment read of the Fulfillment service: through pydantic-settings, each one proven to
be read (Orders' `test_orders_settings_env.py` ported; #8 id 56; feature 210's alias closure).

The service reads its environment ONLY through `BaseSettings` classes, each field with an explicit
`validation_alias` (never a bare field name, which pydantic-settings would also look up as `$USER`,
`$HOST`...), all constructed in `composition.load_settings`. This test proves the halves about THIS
service's classes: the population of settings classes and variables is a literal, setting each
variable to a distinctive value changes exactly the field that reads it, and the defaults are the
documented ones. The other halves: `tests/architecture/test_composition_env_reads.py` (nothing else
reads the environment) and `integration/test_fulfillment_host_lifespan.py` (each value reaches the
adapter it configures).
"""

import dataclasses
import importlib
import pkgutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings

import otc_fulfillment
from otc_fulfillment.composition import FulfillmentSettings, load_settings

# variable -> (settings attribute path, the sentinel the test sets, the value read back).
# Sentinels differ from every default and from each other.
ENV: dict[str, tuple[str, str, Any]] = {
    "FULFILLMENT_DATABASE_URL": (
        "database.database_url",
        "postgresql+asyncpg://sentinel:pw@db.sentinel:6543/sentinel_db",
        "postgresql+asyncpg://sentinel:pw@db.sentinel:6543/sentinel_db",
    ),
    "POSTGRES_HOST": ("database.host", "pg.sentinel", "pg.sentinel"),
    "POSTGRES_HOST_PORT": ("database.port", "15432", 15432),
    "POSTGRES_APP_USER": ("database.user", "sentinel_user", "sentinel_user"),
    "POSTGRES_APP_PASSWORD": ("database.password", "sentinel-password", "sentinel-password"),
    "POSTGRES_DB_FULFILLMENT": (
        "database.database",
        "sentinel_fulfillment",
        "sentinel_fulfillment",
    ),
    "OUTBOX_RELAY_ENABLED": ("outbox.enabled", "false", False),
    "OUTBOX_POLL_INTERVAL_MS": ("outbox.poll_interval_ms", "73", 73),
    "OUTBOX_BATCH_SIZE": ("outbox.batch_size", "37", 37),
    "OUTBOX_PUBLISH_TIMEOUT_MS": ("outbox.publish_timeout_ms", "4321", 4321),
    "KAFKA_BROKERS": ("kafka.brokers", "kafka.sentinel:19092", "kafka.sentinel:19092"),
    "FULFILLMENT_KAFKA_CLIENT_ID": (
        "kafka.client_id",
        "otc-fulfillment-sentinel",
        "otc-fulfillment-sentinel",
    ),
    "NATS_URL": ("nats.url", "nats://nats.sentinel:14222", "nats://nats.sentinel:14222"),
    "WEB_CONCURRENCY": ("server.web_concurrency", "3", 3),
    "FULFILLMENT_MAX_CONCURRENT_REQUESTS": ("responder.max_concurrent_requests", "7", 7),
}
SETTINGS_CLASSES = {
    "FulfillmentDatabaseSettings",
    "KafkaSettings",
    "NatsSettings",
    "OutboxRelaySettings",
    "ResponderSettings",
    "ServerSettings",
}


def _settings_classes() -> dict[str, type[BaseSettings]]:
    """Every `BaseSettings` subclass defined anywhere under `otc_fulfillment` (modules imported)."""
    for module in pkgutil.walk_packages(otc_fulfillment.__path__, "otc_fulfillment."):
        importlib.import_module(module.name)
    found: dict[str, type[BaseSettings]] = {}
    stack = [BaseSettings]
    while stack:
        for subclass in stack.pop().__subclasses__():
            if subclass.__module__.startswith("otc_fulfillment"):
                found[subclass.__name__] = subclass
            stack.append(subclass)
    return found


def _aliases(cls: type[BaseSettings]) -> set[str]:
    names: set[str] = set()
    for name, field in cls.model_fields.items():
        alias = field.validation_alias
        assert alias is not None, (
            f"{cls.__name__}.{name} has no validation_alias: env name implicit"
        )
        choices = getattr(alias, "choices", None)
        names.update(c for c in choices) if choices else names.add(str(alias))
    return names


@pytest.fixture
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    monkeypatch.chdir(tmp_path)  # no `.env` of a developer can supply a value
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_the_population_of_settings_classes_is_exactly_the_literal() -> None:
    assert set(_settings_classes()) == SETTINGS_CLASSES


def test_the_population_of_environment_variables_is_exactly_the_literal() -> None:
    declared = set().union(*(_aliases(cls) for cls in _settings_classes().values()))
    assert declared == set(ENV), (
        f"declared but untested: {sorted(declared - set(ENV))}; "
        f"tested but not declared: {sorted(set(ENV) - declared)}"
    )


def test_no_settings_class_lets_a_bare_field_name_read_the_environment() -> None:
    for cls in _settings_classes().values():
        assert not cls.model_config.get("populate_by_name"), cls.__name__
        assert not cls.model_config.get("validate_by_name"), cls.__name__


def test_every_class_is_a_field_of_the_bundle_load_settings_builds() -> None:
    bundle_types = {f.type.__name__ for f in dataclasses.fields(FulfillmentSettings)}  # type: ignore[union-attr]
    assert bundle_types == SETTINGS_CLASSES


@pytest.mark.parametrize("variable", sorted(ENV))
def test_each_variable_is_read_into_its_own_field_and_no_other(
    clean_environment: pytest.MonkeyPatch, variable: str
) -> None:
    clean_environment.setenv("POSTGRES_APP_PASSWORD", "baseline-password")
    baseline = load_settings()
    path, sentinel, expected = ENV[variable]

    clean_environment.setenv(variable, sentinel)
    changed = load_settings()

    def read(settings: FulfillmentSettings, dotted: str) -> Any:
        owner, attribute = dotted.split(".")
        return getattr(getattr(settings, owner), attribute)

    assert read(changed, path) == expected
    assert read(baseline, path) != expected, "the sentinel must differ from the baseline"
    for other_variable, (other_path, _, _) in ENV.items():
        if other_path != path:
            assert read(changed, other_path) == read(baseline, other_path), (
                f"{variable} also moved {other_variable}'s field {other_path}"
            )


def test_the_kafka_client_id_is_not_the_shared_variable_orders_uses(
    clean_environment: pytest.MonkeyPatch,
) -> None:
    # `.env` holds `otc-orders` in KAFKA_CLIENT_ID: reading that name would put Orders' id on
    # Fulfillment's connection (the sibling-substitution mutation of G3)
    clean_environment.setenv("POSTGRES_APP_PASSWORD", "baseline-password")
    clean_environment.setenv("KAFKA_CLIENT_ID", "otc-orders")

    assert load_settings().kafka.client_id == "otc-fulfillment"


def test_an_unrelated_shell_variable_never_becomes_a_setting(
    clean_environment: pytest.MonkeyPatch,
) -> None:
    clean_environment.setenv("POSTGRES_APP_PASSWORD", "baseline-password")
    for name in ("USER", "HOST", "PORT", "PASSWORD", "URL", "BROKERS", "ENABLED", "CLIENT_ID"):
        clean_environment.setenv(name, "from-the-shell")

    settings = load_settings()

    assert settings.database.user == "otc_app"
    assert settings.database.host == "localhost"
    assert settings.nats.url == "nats://localhost:4222"
    assert settings.kafka.brokers == "localhost:9092"
    assert settings.kafka.client_id == "otc-fulfillment"
    assert settings.outbox.enabled is True


def test_the_defaults_are_the_documented_ones(clean_environment: pytest.MonkeyPatch) -> None:
    clean_environment.setenv("POSTGRES_APP_PASSWORD", "baseline-password")

    settings = load_settings()

    assert (settings.nats.url, settings.server.web_concurrency) == ("nats://localhost:4222", 1)
    assert (settings.kafka.brokers, settings.kafka.client_id) == (
        "localhost:9092",
        "otc-fulfillment",
    )
    assert (
        settings.outbox.enabled,
        settings.outbox.poll_interval_ms,
        settings.outbox.batch_size,
        settings.outbox.publish_timeout_ms,
    ) == (True, 250, 100, 5000)
    assert settings.responder.max_concurrent_requests == 16


@pytest.mark.parametrize("value", ["0", "-1"])
def test_a_concurrency_bound_below_one_is_refused_naming_the_variable(
    clean_environment: pytest.MonkeyPatch, value: str
) -> None:
    clean_environment.setenv("POSTGRES_APP_PASSWORD", "baseline-password")
    clean_environment.setenv("FULFILLMENT_MAX_CONCURRENT_REQUESTS", value)

    with pytest.raises(
        ValidationError, match="FULFILLMENT_MAX_CONCURRENT_REQUESTS must be at least 1"
    ):
        load_settings()
