"""The database settings carry no password default (review_db_orders F5, #8 D6): with neither a
full URL nor `POSTGRES_APP_PASSWORD`, boot fails; with either, the URL is assembled."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from otc_fulfillment.infrastructure.settings import FulfillmentDatabaseSettings

CREDENTIAL_VARIABLES = ("POSTGRES_APP_PASSWORD", "FULFILLMENT_DATABASE_URL")


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in CREDENTIAL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # no `.env` here: the repository's own must not supply a password


def test_boot_fails_when_no_credential_is_supplied() -> None:
    with pytest.raises(ValidationError, match="no database credential"):
        FulfillmentDatabaseSettings()


def test_the_password_from_the_environment_builds_the_asyncpg_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_APP_PASSWORD", "s3cr3t-value")
    # unrelated variables that share a field's bare name must not leak into the URL
    for name, value in (("USER", "someone-else"), ("HOST", "elsewhere"), ("PORT", "1")):
        monkeypatch.setenv(name, value)
    url = FulfillmentDatabaseSettings().url
    assert url == "postgresql+asyncpg://otc_app:s3cr3t-value@localhost:5432/otc_fulfillment"


def test_a_full_url_needs_no_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FULFILLMENT_DATABASE_URL", "postgresql+asyncpg://u:p@h:1/d")
    assert FulfillmentDatabaseSettings().url == "postgresql+asyncpg://u:p@h:1/d"
