"""Every environment read of the Orders service (#8 id 56): through pydantic-settings, each one
proven to be read.

The mechanism, chosen once for every composition root (feature 15; later services inherit it): a
service reads its environment ONLY through `BaseSettings` classes, each field with an explicit
`validation_alias` (never a bare field name, which pydantic-settings would also look up as `$USER`,
`$HOST`...), all constructed in `composition.load_settings`. This test proves the two halves that
are about THIS service's classes: the population of settings classes and fields is a literal, and
setting each variable to a distinctive value changes exactly the field that reads it. The other
halves live elsewhere: `tests/architecture/test_composition_env_reads.py` (nothing else reads the
environment; `load_settings` constructs every class) and
`tests/integration/test_orders_host_lifespan.py` (each value reaches the adapter it configures).

Deleting a `validation_alias`, a field, or the class from `load_settings` fails a named test below.
"""

import dataclasses
import importlib
import pkgutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings

import otc_orders
from otc_orders.composition import OrdersSettings, load_settings

# variable -> (settings attribute path, the sentinel the test sets, the value read back).
# Sentinels differ from every default and from each other.
ENV: dict[str, tuple[str, str, Any]] = {
    "ORDERS_DATABASE_URL": (
        "database.database_url",
        "postgresql+asyncpg://sentinel:pw@db.sentinel:6543/sentinel_db",
        "postgresql+asyncpg://sentinel:pw@db.sentinel:6543/sentinel_db",
    ),
    "POSTGRES_HOST": ("database.host", "pg.sentinel", "pg.sentinel"),
    "POSTGRES_HOST_PORT": ("database.port", "15432", 15432),
    "POSTGRES_APP_USER": ("database.user", "sentinel_user", "sentinel_user"),
    "POSTGRES_APP_PASSWORD": ("database.password", "sentinel-password", "sentinel-password"),
    "POSTGRES_DB_ORDERS": ("database.database", "sentinel_orders", "sentinel_orders"),
    "OUTBOX_RELAY_ENABLED": ("outbox.enabled", "false", False),
    "OUTBOX_POLL_INTERVAL_MS": ("outbox.poll_interval_ms", "73", 73),
    "OUTBOX_BATCH_SIZE": ("outbox.batch_size", "37", 37),
    "OUTBOX_PUBLISH_TIMEOUT_MS": ("outbox.publish_timeout_ms", "4321", 4321),
    "KAFKA_BROKERS": ("kafka.brokers", "kafka.sentinel:19092", "kafka.sentinel:19092"),
    "KAFKA_CLIENT_ID": ("kafka.client_id", "otc-orders-sentinel", "otc-orders-sentinel"),
    "NATS_URL": ("nats.url", "nats://nats.sentinel:14222", "nats://nats.sentinel:14222"),
    "STOCK_CHECK_TIMEOUT_MS": ("nats.stock_check_timeout_ms", "1777", 1777),
    "WEB_CONCURRENCY": ("server.web_concurrency", "3", 3),
    # Feature 16: the saga's eleven knobs. Each sentinel keeps the lease rule satisfied (one
    # variable moves at a time, the others stay at their defaults), differs from its default, and
    # the booleans can only be `false`.
    "SAGA_COMMAND_TIMEOUT_MS": ("saga.command_timeout_ms", "4123", 4123),
    "SAGA_COMMAND_MAX_ATTEMPTS": ("saga.command_max_attempts", "4", 4),
    "SAGA_COMMAND_BACKOFF_MS": ("saga.command_backoff_ms", "611", 611),
    "SAGA_COMMAND_LEASE_MS": ("saga.command_lease_ms", "70001", 70001),
    "SAGA_PARK_RETRY_CAP_MS": ("saga.park_retry_cap_ms", "888888", 888888),
    "SAGA_SWEEPER_ENABLED": ("saga.sweeper_enabled", "false", False),
    "SAGA_SWEEPER_INTERVAL_MS": ("saga.sweeper_interval_ms", "31337", 31337),
    "SAGA_PENDING_GRACE_MS": ("saga.pending_grace_ms", "12345", 12345),
    "SAGA_SWEEPER_BATCH_LIMIT": ("saga.sweeper_batch_limit", "41", 41),
    "SAGA_FAST_PATH_MAX_IN_FLIGHT": ("saga.fast_path_max_in_flight", "99", 99),
    "SAGA_CONSUMER_ENABLED": ("saga.consumer_enabled", "false", False),
}
SETTINGS_CLASSES = {
    "NatsSettings",
    "KafkaSettings",
    "OrdersDatabaseSettings",
    "OutboxRelaySettings",
    "SagaSettings",
    "ServerSettings",
}


def _settings_classes() -> dict[str, type[BaseSettings]]:
    """Every `BaseSettings` subclass defined anywhere under `otc_orders` (modules imported)."""
    for module in pkgutil.walk_packages(otc_orders.__path__, "otc_orders."):
        importlib.import_module(module.name)
    found: dict[str, type[BaseSettings]] = {}
    stack = [BaseSettings]
    while stack:
        for subclass in stack.pop().__subclasses__():
            if subclass.__module__.startswith("otc_orders"):
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
    bundle_types = {f.type.__name__ for f in dataclasses.fields(OrdersSettings)}  # type: ignore[union-attr]
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

    def read(settings: OrdersSettings, dotted: str) -> Any:
        owner, attribute = dotted.split(".")
        return getattr(getattr(settings, owner), attribute)

    assert read(changed, path) == expected
    assert read(baseline, path) != expected, "the sentinel must differ from the baseline"
    for other_variable, (other_path, _, _) in ENV.items():
        if other_path != path:
            assert read(changed, other_path) == read(baseline, other_path), (
                f"{variable} also moved {other_variable}'s field {other_path}"
            )


def test_an_unrelated_shell_variable_never_becomes_a_setting(
    clean_environment: pytest.MonkeyPatch,
) -> None:
    clean_environment.setenv("POSTGRES_APP_PASSWORD", "baseline-password")
    for name in ("USER", "HOST", "PORT", "PASSWORD", "URL", "BROKERS", "ENABLED"):
        clean_environment.setenv(name, "from-the-shell")

    settings = load_settings()

    assert settings.database.user == "otc_app"
    assert settings.database.host == "localhost"
    assert settings.nats.url == "nats://localhost:4222"
    assert settings.kafka.brokers == "localhost:9092"
    assert settings.outbox.enabled is True


def test_the_defaults_are_the_documented_ones(clean_environment: pytest.MonkeyPatch) -> None:
    clean_environment.setenv("POSTGRES_APP_PASSWORD", "baseline-password")

    settings = load_settings()

    assert (settings.nats.url, settings.nats.stock_check_timeout_ms) == (
        "nats://localhost:4222",
        5000,
    )
    assert settings.server.web_concurrency == 1


@pytest.mark.parametrize("value", ["", " ", "otc orders", "otc/orders"])
def test_bc34_an_empty_or_blank_client_id_fails_naming_the_variable(
    clean_environment: pytest.MonkeyPatch, value: str
) -> None:
    clean_environment.setenv("POSTGRES_APP_PASSWORD", "baseline-password")
    clean_environment.setenv("KAFKA_CLIENT_ID", value)

    try:
        load_settings()
    except ValidationError as error:
        message = str(error)
    else:
        pytest.fail(f"BC34: KAFKA_CLIENT_ID={value!r} was accepted: the service would boot with it")
    assert "KAFKA_CLIENT_ID" in message, "the failure does not name the variable"
    # the control: a well-formed id is accepted
    clean_environment.setenv("KAFKA_CLIENT_ID", "otc-orders-Ok_1.v2")
    assert load_settings().kafka.client_id == "otc-orders-Ok_1.v2"
