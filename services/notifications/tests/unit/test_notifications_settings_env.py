"""Every environment read of the Notifications service: through pydantic-settings, each one proven
to be read (Billing's `test_billing_settings_env.py` ported; #8 id 56; feature 210's alias closure).

The population of settings classes and variables is a literal; setting each variable to a
distinctive value changes exactly the field that reads it; the defaults are the documented ones; a
partial SMTP credential pair is refused at boot. The other halves:
`tests/architecture/test_composition_env_reads.py` (nothing else reads the environment) and
`integration/test_notifications_host_lifespan.py` (each value reaches the adapter it configures).
"""

import dataclasses
import importlib
import pkgutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings

import otc_notifications
from otc_notifications.composition import NotificationsSettings, load_settings
from otc_notifications.infrastructure.settings import SenderKind

# variable -> (settings attribute path, the sentinel the test sets, the value read back).
ENV: dict[str, tuple[str, str, Any]] = {
    "NOTIFICATIONS_DATABASE_URL": (
        "database.database_url",
        "postgresql+asyncpg://sentinel:pw@db.sentinel:6543/sentinel_db",
        "postgresql+asyncpg://sentinel:pw@db.sentinel:6543/sentinel_db",
    ),
    "POSTGRES_HOST": ("database.host", "pg.sentinel", "pg.sentinel"),
    "POSTGRES_HOST_PORT": ("database.port", "15432", 15432),
    "POSTGRES_APP_USER": ("database.user", "sentinel_user", "sentinel_user"),
    "POSTGRES_APP_PASSWORD": ("database.password", "sentinel-password", "sentinel-password"),
    "POSTGRES_DB_NOTIFICATIONS": (
        "database.database",
        "sentinel_notifications",
        "sentinel_notifications",
    ),
    "KAFKA_BROKERS": ("kafka.brokers", "kafka.sentinel:19092", "kafka.sentinel:19092"),
    "NOTIFICATIONS_KAFKA_CLIENT_ID": (
        "kafka.client_id",
        "otc-notifications-sentinel",
        "otc-notifications-sentinel",
    ),
    "NOTIFICATIONS_CONSUMER_GROUP": ("kafka.group_id", "group-sentinel", "group-sentinel"),
    "NOTIFICATIONS_SENDER": ("smtp.sender", "smtp", SenderKind.SMTP),
    "SMTP_HOST": ("smtp.host", "smtp.sentinel", "smtp.sentinel"),
    "SMTP_PORT": ("smtp.port", "2525", 2525),
    "SMTP_FROM_EMAIL": ("smtp.from_email", "from@sentinel.example", "from@sentinel.example"),
    "SMTP_USER": ("smtp.user", "user-sentinel", "user-sentinel"),
    "SMTP_PASSWORD": ("smtp.password", "password-sentinel", "password-sentinel"),
    "SMTP_START_TLS": ("smtp.start_tls", "true", True),
    "OTEL_EXPORTER_OTLP_ENDPOINT": (
        "telemetry.otlp_endpoint",
        "http://otlp.sentinel:14318",
        "http://otlp.sentinel:14318",
    ),
    # Feature 27 (`R16`, S4.2): the fact consumer's retry knobs.
    "FACT_RETRY_MAX_ATTEMPTS": ("fact_retry.max_attempts", "7", 7),
    "FACT_RETRY_BACKOFF_MS": ("fact_retry.backoff_ms", "271", 271),
}
# The credential pair is only valid together: setting one of the two must also set the other.
PAIRED = {"SMTP_USER": "SMTP_PASSWORD", "SMTP_PASSWORD": "SMTP_USER"}
SETTINGS_CLASSES = {
    "FactRetrySettings",
    "NotificationsDatabaseSettings",
    "KafkaSettings",
    "SmtpSettings",
    "TelemetrySettings",
}


def _settings_classes() -> dict[str, type[BaseSettings]]:
    for module in pkgutil.walk_packages(otc_notifications.__path__, "otc_notifications."):
        importlib.import_module(module.name)
    found: dict[str, type[BaseSettings]] = {}
    stack = [BaseSettings]
    while stack:
        for subclass in stack.pop().__subclasses__():
            if subclass.__module__.startswith("otc_notifications"):
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
    monkeypatch.setenv("POSTGRES_APP_PASSWORD", "baseline-password")
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
    bundle_types = {f.type.__name__ for f in dataclasses.fields(NotificationsSettings)}  # type: ignore[union-attr]
    assert bundle_types == SETTINGS_CLASSES


@pytest.mark.parametrize("variable", sorted(ENV))
def test_each_variable_is_read_into_its_own_field_and_no_other(
    clean_environment: pytest.MonkeyPatch, variable: str
) -> None:
    baseline = load_settings()
    path, sentinel, expected = ENV[variable]

    clean_environment.setenv(variable, sentinel)
    if variable in PAIRED:
        clean_environment.setenv(PAIRED[variable], ENV[PAIRED[variable]][1])
    changed = load_settings()

    def read(settings: NotificationsSettings, dotted: str) -> Any:
        owner, attribute = dotted.split(".")
        return getattr(getattr(settings, owner), attribute)

    assert read(changed, path) == expected
    assert read(baseline, path) != expected
    expected_changed = {path}
    if variable in PAIRED:
        expected_changed.add(ENV[PAIRED[variable]][0])
    moved = {
        f"{owner.name}.{name}"
        for owner in dataclasses.fields(NotificationsSettings)
        for name in type(getattr(baseline, owner.name)).model_fields
        if getattr(getattr(baseline, owner.name), name)
        != getattr(getattr(changed, owner.name), name)
    }
    assert moved == expected_changed, f"{variable} moved {sorted(moved)}"


def test_the_documented_defaults(clean_environment: pytest.MonkeyPatch) -> None:
    settings = load_settings()
    assert settings.kafka.brokers == "localhost:9092"
    assert settings.kafka.client_id == "otc-notifications"
    assert settings.kafka.group_id == "notifications"
    assert settings.smtp.sender is SenderKind.CONSOLE, "the safe default: no I/O"
    assert (settings.smtp.host, settings.smtp.port) == ("localhost", 1025), "Mailpit's SMTP port"
    assert settings.smtp.from_email == "no-reply@order-to-cash.example"
    assert (settings.smtp.user, settings.smtp.password, settings.smtp.start_tls) == (
        None,
        None,
        False,
    )


@pytest.mark.parametrize("blank", ["", " ", "has space", "a/b"])
@pytest.mark.parametrize(
    "variable", ["NOTIFICATIONS_KAFKA_CLIENT_ID", "NOTIFICATIONS_CONSUMER_GROUP"]
)
def test_an_empty_or_malformed_client_id_or_group_fails_the_boot_naming_the_variable(
    clean_environment: pytest.MonkeyPatch, variable: str, blank: str
) -> None:
    clean_environment.setenv(variable, blank)
    with pytest.raises(ValidationError) as refused:
        load_settings()
    assert variable in str(refused.value)


@pytest.mark.parametrize("variable", ["SMTP_USER", "SMTP_PASSWORD"])
def test_a_partial_credential_pair_is_refused_naming_both_variables(
    clean_environment: pytest.MonkeyPatch, variable: str
) -> None:
    clean_environment.setenv(variable, "only-one-of-the-pair")
    with pytest.raises(ValidationError, match="SMTP_USER and SMTP_PASSWORD must both be set"):
        load_settings()


@pytest.mark.parametrize("port", ["0", "65536", "-1", "abc", ""])
def test_a_port_that_is_not_a_tcp_port_fails_the_boot(
    clean_environment: pytest.MonkeyPatch, port: str
) -> None:
    clean_environment.setenv("SMTP_PORT", port)
    with pytest.raises(ValidationError) as refused:
        load_settings()
    assert "SMTP_PORT" in str(refused.value)


def test_an_unknown_sender_kind_fails_the_boot(clean_environment: pytest.MonkeyPatch) -> None:
    clean_environment.setenv("NOTIFICATIONS_SENDER", "mailtrap")
    with pytest.raises(ValidationError) as refused:
        load_settings()
    assert "NOTIFICATIONS_SENDER" in str(refused.value)


def test_fact_retry_defaults_are_three_attempts_and_five_hundred_milliseconds(
    clean_environment: pytest.MonkeyPatch,
) -> None:
    settings = load_settings()

    assert (settings.fact_retry.max_attempts, settings.fact_retry.backoff_ms) == (3, 500)


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
        load_settings()

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

    load_settings()


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

    load_settings()


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
        load_settings()

    [error] = refused.value.errors()
    assert "FACT_RETRY_MAX_ATTEMPTS=" + attempts in error["msg"], error["msg"]
    assert "FACT_RETRY_BACKOFF_MS=" + backoff_ms in error["msg"], error["msg"]
    assert f"waits {worst_case_ms} ms" in error["msg"], error["msg"]
    assert "max_poll_interval_ms (300000)" in error["msg"], error["msg"]


def test_a_blank_or_whitespace_smtp_credential_is_none_and_a_real_pair_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from otc_notifications.infrastructure.settings import SmtpSettings

    for blank in ("", "   ", "\t"):
        monkeypatch.setenv("SMTP_USER", blank)
        monkeypatch.setenv("SMTP_PASSWORD", blank)
        settings = SmtpSettings(_env_file=None)  # type: ignore[call-arg]
        assert (settings.user, settings.password) == (None, None), repr(blank)
    monkeypatch.setenv("SMTP_USER", "u-real")
    monkeypatch.setenv("SMTP_PASSWORD", "p-real")
    kept = SmtpSettings(_env_file=None)  # type: ignore[call-arg]
    assert (kept.user, kept.password) == ("u-real", "p-real")
