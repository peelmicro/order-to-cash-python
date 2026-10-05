"""Notifications database settings: the only place the connection URL is assembled.

Read from the same `.env` the compose file reads (`POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD`,
`POSTGRES_DB_NOTIFICATIONS`, `POSTGRES_HOST_PORT`), so the database name has one source of truth.
`NOTIFICATIONS_DATABASE_URL`, when set, wins outright (tests and deployments that carry a full URL).

There is NO password default (review_db_orders F5, #8 review_db_orders D6): with neither a full URL
nor `POSTGRES_APP_PASSWORD`, constructing the settings raises, so a service never boots on a
credential committed to source.
"""

from typing import Self

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class NotificationsDatabaseSettings(BaseSettings):
    # No `populate_by_name`: with it, pydantic-settings also reads the bare field names from the
    # environment, so an unrelated `$USER` (or `$HOST`, `$PORT`) would silently become the
    # database user (measured on this machine: `juanpabloperez`).
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str | None = Field(default=None, validation_alias="NOTIFICATIONS_DATABASE_URL")
    host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    port: int = Field(default=5432, validation_alias=AliasChoices("POSTGRES_HOST_PORT"))
    user: str = Field(default="otc_app", validation_alias="POSTGRES_APP_USER")
    # Absent means "not supplied", never a usable password: the validator below refuses it.
    password: str | None = Field(default=None, validation_alias="POSTGRES_APP_PASSWORD")
    database: str = Field(default="otc_notifications", validation_alias="POSTGRES_DB_NOTIFICATIONS")

    @model_validator(mode="after")
    def _a_credential_must_be_supplied(self) -> Self:
        if not self.database_url and not self.password:
            raise ValueError(
                "no database credential: set NOTIFICATIONS_DATABASE_URL or POSTGRES_APP_PASSWORD"
            )
        return self

    @property
    def url(self) -> str:
        """The asyncpg URL (no sync driver exists in this service)."""
        if self.database_url:
            return self.database_url
        return URL.create(
            "postgresql+asyncpg",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
        ).render_as_string(hide_password=False)
