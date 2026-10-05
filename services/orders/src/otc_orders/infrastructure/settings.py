"""Orders database settings: the only place the connection URL is assembled (pydantic-settings).

Read from the same `.env` the compose file reads (`POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD`,
`POSTGRES_DB_ORDERS`, `POSTGRES_HOST_PORT`), so the database name has one source of truth.
`ORDERS_DATABASE_URL`, when set, wins outright (tests and deployments that carry a full URL).
"""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class OrdersDatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_url: str | None = Field(default=None, validation_alias="ORDERS_DATABASE_URL")
    host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    port: int = Field(default=5432, validation_alias=AliasChoices("POSTGRES_HOST_PORT"))
    user: str = Field(default="otc_app", validation_alias="POSTGRES_APP_USER")
    password: str = Field(default="otc_app_dev_password", validation_alias="POSTGRES_APP_PASSWORD")
    database: str = Field(default="otc_orders", validation_alias="POSTGRES_DB_ORDERS")

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
