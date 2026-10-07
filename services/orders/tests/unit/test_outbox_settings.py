"""The outbox relay and Kafka settings (feature 14 task 3.3, `design.md` 10).

Backlog 210's shape: the fixture clears EVERY alias the settings classes declare, and a test proves
it, so the test passes with any of them exported in the shell; and no class has `populate_by_name`,
so a bare `$ENABLED` / `$BROKERS` never leaks in.
"""

from pathlib import Path

import pytest
from pydantic import AliasChoices
from pydantic_settings import BaseSettings

from otc_orders.infrastructure.settings import KafkaSettings, OutboxRelaySettings

ALIAS_VARIABLES = (
    "OUTBOX_RELAY_ENABLED",
    "OUTBOX_POLL_INTERVAL_MS",
    "OUTBOX_BATCH_SIZE",
    "OUTBOX_PUBLISH_TIMEOUT_MS",
    "KAFKA_BROKERS",
    "KAFKA_CLIENT_ID",
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ALIAS_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # no `.env` here: the repository's own must not supply a value


def _declared(*classes: type[BaseSettings]) -> set[str]:
    declared: set[str] = set()
    for settings_class in classes:
        for field in settings_class.model_fields.values():
            alias = field.validation_alias
            if isinstance(alias, str):
                declared.add(alias)
            elif isinstance(alias, AliasChoices):
                declared.update(choice for choice in alias.choices if isinstance(choice, str))
    return declared


def test_the_fixture_clears_every_alias_the_settings_classes_declare() -> None:
    assert _declared(OutboxRelaySettings, KafkaSettings) == set(ALIAS_VARIABLES)


def test_the_defaults_are_250_100_5000_true_localhost_9092_and_otc_orders() -> None:
    relay = OutboxRelaySettings()
    kafka = KafkaSettings()
    assert relay.poll_interval_ms == 250
    assert relay.batch_size == 100
    assert relay.publish_timeout_ms == 5000
    assert relay.enabled is True
    assert kafka.brokers == "localhost:9092"
    assert kafka.client_id == "otc-orders"
    assert relay.poll_interval_seconds == 0.25
    assert relay.publish_timeout_seconds == 5.0


def test_each_alias_overrides_its_field(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in (
        ("OUTBOX_RELAY_ENABLED", "false"),
        ("OUTBOX_POLL_INTERVAL_MS", "1500"),
        ("OUTBOX_BATCH_SIZE", "7"),
        ("OUTBOX_PUBLISH_TIMEOUT_MS", "750"),
        ("KAFKA_BROKERS", "broker-a:9092,broker-b:9092"),
        ("KAFKA_CLIENT_ID", "orders-two"),
    ):
        monkeypatch.setenv(name, value)
    relay = OutboxRelaySettings()
    kafka = KafkaSettings()
    assert (relay.enabled, relay.poll_interval_ms, relay.batch_size, relay.publish_timeout_ms) == (
        False,
        1500,
        7,
        750,
    )
    assert (kafka.brokers, kafka.client_id) == ("broker-a:9092,broker-b:9092", "orders-two")
    assert relay.poll_interval_seconds == 1.5
    assert relay.publish_timeout_seconds == 0.75


def test_bare_enabled_batch_size_brokers_and_client_id_change_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`populate_by_name` would make pydantic-settings read the bare field names."""
    for name, value in (
        ("ENABLED", "false"),
        ("BATCH_SIZE", "7"),
        ("POLL_INTERVAL_MS", "9"),
        ("PUBLISH_TIMEOUT_MS", "9"),
        ("BROKERS", "elsewhere:1"),
        ("CLIENT_ID", "someone-else"),
    ):
        monkeypatch.setenv(name, value)
    relay = OutboxRelaySettings()
    kafka = KafkaSettings()
    assert (relay.enabled, relay.batch_size, relay.poll_interval_ms) == (True, 100, 250)
    assert relay.publish_timeout_ms == 5000
    assert (kafka.brokers, kafka.client_id) == ("localhost:9092", "otc-orders")
