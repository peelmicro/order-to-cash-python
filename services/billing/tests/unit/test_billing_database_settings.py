"""The database settings carry no password default (review_db_orders F5, #8 D6): with neither a
full URL nor `POSTGRES_APP_PASSWORD`, boot fails; with either, the URL is assembled.

Backlog 208(b): the fixture clears EVERY alias variable the settings read, so the test passes with
any of them exported in the shell (feature 10's fixture cleared two; a developer with
`POSTGRES_HOST_PORT=5433` exported saw the URL assertion fail on the port).
"""

from pathlib import Path

import pytest
from pydantic import AliasChoices, ValidationError

from otc_billing.infrastructure.settings import BillingDatabaseSettings

ALIAS_VARIABLES = (
    "BILLING_DATABASE_URL",
    "POSTGRES_HOST",
    "POSTGRES_HOST_PORT",
    "POSTGRES_APP_USER",
    "POSTGRES_APP_PASSWORD",
    "POSTGRES_DB_BILLING",
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ALIAS_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # no `.env` here: the repository's own must not supply a password


def test_the_fixture_clears_every_alias_the_settings_class_declares() -> None:
    declared: set[str] = set()
    for field in BillingDatabaseSettings.model_fields.values():
        alias = field.validation_alias
        if isinstance(alias, str):
            declared.add(alias)
        elif isinstance(alias, AliasChoices):
            declared.update(choice for choice in alias.choices if isinstance(choice, str))
    assert declared == set(ALIAS_VARIABLES)


def test_boot_fails_when_no_credential_is_supplied() -> None:
    with pytest.raises(ValidationError, match="no database credential"):
        BillingDatabaseSettings()


def test_the_password_from_the_environment_builds_the_asyncpg_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_APP_PASSWORD", "s3cr3t-value")
    # unrelated variables that share a field's bare name must not leak into the URL
    for name, value in (("USER", "someone-else"), ("HOST", "elsewhere"), ("PORT", "1")):
        monkeypatch.setenv(name, value)
    url = BillingDatabaseSettings().url
    assert url == "postgresql+asyncpg://otc_app:s3cr3t-value@localhost:5432/otc_billing"


def test_a_full_url_needs_no_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILLING_DATABASE_URL", "postgresql+asyncpg://u:p@h:1/d")
    assert BillingDatabaseSettings().url == "postgresql+asyncpg://u:p@h:1/d"
