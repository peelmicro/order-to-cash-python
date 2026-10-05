"""Seed configuration: pydantic-settings only, no password default, no leaking bare variables.

R-map (feature_list.json id 12; backlog 204(d) and 204(e) applied to the seed; #8 review_db_orders
D6): with neither a full URL nor the password variable the settings refuse to build, and an
unrelated `USER`/`HOST`/`PORT` in the environment never reaches a URL.
"""

import pytest
from pydantic import AliasChoices, ValidationError

from otc_seed.infrastructure.settings import SeedSettings

_ALL = (
    "ORDERS_DATABASE_URL",
    "FULFILLMENT_DATABASE_URL",
    "BILLING_DATABASE_URL",
    "POSTGRES_HOST",
    "POSTGRES_HOST_PORT",
    "POSTGRES_APP_USER",
    "POSTGRES_APP_PASSWORD",
    "POSTGRES_DB_ORDERS",
    "POSTGRES_DB_FULFILLMENT",
    "POSTGRES_DB_BILLING",
    "MONGO_URI",
    "MONGO_HOST",
    "MONGO_HOST_PORT",
    "MONGO_INITDB_ROOT_USERNAME",
    "MONGO_INITDB_ROOT_PASSWORD",
    "MONGO_DB_READMODEL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "MONGO_USER",
    "MONGO_PASSWORD",
    "MONGO_PORT",
    "USER",
    "HOST",
    "PORT",
    "PASSWORD",
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ALL:
        monkeypatch.delenv(name, raising=False)


def test_the_fixture_clears_every_alias_the_settings_class_declares() -> None:
    """Backlog 210 (review_db_billing N1). `_ALL` is a superset on purpose: it also clears the bare
    names the leak test below sets, so equality would be wrong; what must hold is that no alias the
    class reads is missing from it (a variable exported in CI would otherwise change a test)."""
    declared: set[str] = set()
    for field in SeedSettings.model_fields.values():
        alias = field.validation_alias
        if isinstance(alias, str):
            declared.add(alias)
        elif isinstance(alias, AliasChoices):
            declared.update(choice for choice in alias.choices if isinstance(choice, str))
    assert declared, "the seed settings declare no alias: the check would be vacuous"
    assert declared <= set(_ALL), f"not cleared by the fixture: {sorted(declared - set(_ALL))}"


def _settings() -> SeedSettings:
    return SeedSettings(_env_file=None)  # type: ignore[call-arg]  # never the developer's .env


def test_no_credential_at_all_refuses_to_build() -> None:
    with pytest.raises(ValidationError, match="no PostgreSQL credential"):
        _settings()


def test_a_postgres_password_alone_still_needs_a_mongo_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_APP_PASSWORD", "pg-secret")
    with pytest.raises(ValidationError, match="no MongoDB credential"):
        _settings()


def test_the_urls_are_built_from_the_documented_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_APP_PASSWORD", "p@ss/word")
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_HOST_PORT", "6543")
    monkeypatch.setenv("POSTGRES_APP_USER", "seeder")
    monkeypatch.setenv("POSTGRES_DB_ORDERS", "o1")
    monkeypatch.setenv("POSTGRES_DB_FULFILLMENT", "f1")
    monkeypatch.setenv("POSTGRES_DB_BILLING", "b1")
    monkeypatch.setenv("MONGO_INITDB_ROOT_PASSWORD", "m:secret")
    monkeypatch.setenv("MONGO_HOST", "mongo.internal")
    monkeypatch.setenv("MONGO_HOST_PORT", "27999")
    monkeypatch.setenv("MONGO_INITDB_ROOT_USERNAME", "root1")
    settings = _settings()
    assert settings.orders_url == "postgresql+asyncpg://seeder:p%40ss%2Fword@db.internal:6543/o1"
    assert settings.fulfillment_url.endswith("@db.internal:6543/f1")
    assert settings.billing_url.endswith("@db.internal:6543/b1")
    assert settings.mongo_connection_uri == (
        "mongodb://root1:m%3Asecret@mongo.internal:27999?authSource=admin"
    )
    assert settings.mongo_database == "otc_read_model"


def test_the_defaults_are_the_compose_names_and_carry_no_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_APP_PASSWORD", "x")
    monkeypatch.setenv("MONGO_INITDB_ROOT_PASSWORD", "y")
    settings = _settings()
    assert settings.orders_url == "postgresql+asyncpg://otc_app:x@localhost:5432/otc_orders"
    assert settings.fulfillment_url.endswith("/otc_fulfillment")
    assert settings.billing_url.endswith("/otc_billing")
    assert SeedSettings.model_fields["postgres_password"].default is None
    assert SeedSettings.model_fields["mongo_password"].default is None


def test_a_full_url_wins_and_replaces_the_password_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORDERS_DATABASE_URL", "postgresql+asyncpg://u:p@h:1/o")
    monkeypatch.setenv("FULFILLMENT_DATABASE_URL", "postgresql+asyncpg://u:p@h:1/f")
    monkeypatch.setenv("BILLING_DATABASE_URL", "postgresql+asyncpg://u:p@h:1/b")
    monkeypatch.setenv("MONGO_URI", "mongodb://u:p@h:2/?authSource=admin")
    settings = _settings()
    assert settings.orders_url == "postgresql+asyncpg://u:p@h:1/o"
    assert settings.mongo_connection_uri == "mongodb://u:p@h:2/?authSource=admin"


def test_two_of_three_urls_are_not_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORDERS_DATABASE_URL", "postgresql+asyncpg://u:p@h:1/o")
    monkeypatch.setenv("FULFILLMENT_DATABASE_URL", "postgresql+asyncpg://u:p@h:1/f")
    monkeypatch.setenv("MONGO_URI", "mongodb://u:p@h:2")
    with pytest.raises(ValidationError, match="no PostgreSQL credential"):
        _settings()


def test_bare_user_host_port_and_password_never_reach_a_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_APP_PASSWORD", "pg")
    monkeypatch.setenv("MONGO_INITDB_ROOT_PASSWORD", "mg")
    monkeypatch.setenv("USER", "someone-else")
    monkeypatch.setenv("HOST", "elsewhere.example")
    monkeypatch.setenv("PORT", "9999")
    monkeypatch.setenv("PASSWORD", "wrong")
    # the compose `.env` carries the POSTGRES SUPERUSER as POSTGRES_USER / POSTGRES_PASSWORD: with
    # `populate_by_name` the field names `postgres_user` / `postgres_password` would read them
    monkeypatch.setenv("POSTGRES_USER", "the-superuser")
    monkeypatch.setenv("POSTGRES_PASSWORD", "superuser-secret")
    monkeypatch.setenv("MONGO_USER", "other-mongo-user")
    monkeypatch.setenv("MONGO_PASSWORD", "other-mongo-secret")
    monkeypatch.setenv("MONGO_PORT", "1")
    settings = _settings()
    for url in (settings.orders_url, settings.fulfillment_url, settings.billing_url):
        assert "someone-else" not in url
        assert "elsewhere.example" not in url
        assert "9999" not in url
        assert "wrong" not in url
        assert "the-superuser" not in url
        assert "superuser-secret" not in url
    assert "someone-else" not in settings.mongo_connection_uri
    assert "9999" not in settings.mongo_connection_uri
    assert "other-mongo" not in settings.mongo_connection_uri
    assert settings.postgres_user == "otc_app"
    assert settings.mongo_user == "otc_mongo_root"


def test_the_secrets_are_not_in_the_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_APP_PASSWORD", "very-secret-pg")
    monkeypatch.setenv("MONGO_INITDB_ROOT_PASSWORD", "very-secret-mongo")
    shown = repr(_settings())
    assert "very-secret" not in shown
