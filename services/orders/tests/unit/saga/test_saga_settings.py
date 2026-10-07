"""`SagaSettings`: defaults, aliases and the refusals that name the setting (tasks 9.1, 9.2; SO16).

One test per validator, so each can be armed by deleting exactly one. Settings are built from the
environment through pydantic-settings only: a bare `$ENABLED` or `$INTERVAL_MS` must reach no field.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from otc_orders.infrastructure.settings import SagaSettings

VARIABLES = (
    "SAGA_COMMAND_TIMEOUT_MS",
    "SAGA_COMMAND_MAX_ATTEMPTS",
    "SAGA_COMMAND_BACKOFF_MS",
    "SAGA_COMMAND_LEASE_MS",
    "SAGA_PARK_RETRY_CAP_MS",
    "SAGA_SWEEPER_ENABLED",
    "SAGA_SWEEPER_INTERVAL_MS",
    "SAGA_PENDING_GRACE_MS",
    "SAGA_SWEEPER_BATCH_LIMIT",
    "SAGA_FAST_PATH_MAX_IN_FLIGHT",
    "SAGA_CONSUMER_ENABLED",
)


@pytest.fixture
def clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    monkeypatch.chdir(tmp_path)  # no developer `.env` can supply a value
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def refused(clean: pytest.MonkeyPatch, **environment: str) -> str:
    for name, value in environment.items():
        clean.setenv(name, value)
    with pytest.raises(ValidationError) as error:
        SagaSettings()
    return str(error.value)


def test_the_defaults_are_the_design_literals(clean: pytest.MonkeyPatch) -> None:
    settings = SagaSettings()

    assert (
        settings.command_timeout_ms,
        settings.command_max_attempts,
        settings.command_backoff_ms,
        settings.command_lease_ms,
        settings.park_retry_cap_ms,
        settings.sweeper_enabled,
        settings.sweeper_interval_ms,
        settings.pending_grace_ms,
        settings.sweeper_batch_limit,
        settings.fast_path_max_in_flight,
        settings.consumer_enabled,
    ) == (5000, 3, 500, 60_000, 900_000, True, 30_000, 10_000, 20, 256, True)
    assert settings.sweeper_interval_seconds == 30.0


def test_a_bare_enabled_or_interval_in_the_environment_reaches_no_field(
    clean: pytest.MonkeyPatch,
) -> None:
    clean.setenv("ENABLED", "false")
    clean.setenv("INTERVAL_MS", "7")
    clean.setenv("MAX_IN_FLIGHT", "1")

    settings = SagaSettings()

    assert settings.sweeper_enabled is True
    assert settings.consumer_enabled is True
    assert settings.sweeper_interval_ms == 30_000
    assert settings.fast_path_max_in_flight == 256


@pytest.mark.parametrize("value", ["0", "11", "-3"])
def test_the_attempt_count_outside_one_to_ten_is_refused_naming_the_setting(
    clean: pytest.MonkeyPatch, value: str
) -> None:
    message = refused(clean, SAGA_COMMAND_MAX_ATTEMPTS=value)
    assert "SAGA_COMMAND_MAX_ATTEMPTS" in message
    assert value in message


@pytest.mark.parametrize("value", ["0", "-1"])
def test_a_fast_path_maximum_below_one_is_refused_naming_the_setting(
    clean: pytest.MonkeyPatch, value: str
) -> None:
    message = refused(clean, SAGA_FAST_PATH_MAX_IN_FLIGHT=value)
    assert "SAGA_FAST_PATH_MAX_IN_FLIGHT" in message
    assert value in message


@pytest.mark.parametrize(
    "variable",
    [
        "SAGA_COMMAND_TIMEOUT_MS",
        "SAGA_COMMAND_BACKOFF_MS",
        "SAGA_COMMAND_LEASE_MS",
        "SAGA_PARK_RETRY_CAP_MS",
        "SAGA_SWEEPER_INTERVAL_MS",
        "SAGA_PENDING_GRACE_MS",
        "SAGA_SWEEPER_BATCH_LIMIT",
    ],
)
@pytest.mark.parametrize("value", ["0", "-5"])
def test_every_non_positive_duration_or_limit_is_refused_naming_the_setting(
    clean: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    message = refused(clean, **{variable: value})
    assert f"{variable} must be positive, got {value}" in message


def test_so16_a_lease_not_exceeding_the_worst_case_dispatch_refuses_to_start(
    clean: pytest.MonkeyPatch,
) -> None:
    # worst case at the defaults: 3 x 5000 + (500 + 1000) = 16 500 ms; the lease must be 2x that
    message = refused(clean, SAGA_COMMAND_LEASE_MS="32999")
    assert "SAGA_COMMAND_LEASE_MS=32999" in message
    assert "16500" in message
    assert "33000" in message

    clean.setenv("SAGA_COMMAND_LEASE_MS", "33000")
    assert SagaSettings().command_lease_ms == 33_000


def test_the_lease_rule_follows_the_configured_attempts_and_timeout(
    clean: pytest.MonkeyPatch,
) -> None:
    clean.setenv("SAGA_COMMAND_MAX_ATTEMPTS", "5")
    clean.setenv("SAGA_COMMAND_TIMEOUT_MS", "10000")
    # 5 x 10 000 + 500 x (2**4 - 1) = 57 500 ms; twice that is 115 000 ms > the default lease
    message = refused(clean)
    assert "57500" in message
    clean.setenv("SAGA_COMMAND_LEASE_MS", "115000")
    assert SagaSettings().command_lease_ms == 115_000
