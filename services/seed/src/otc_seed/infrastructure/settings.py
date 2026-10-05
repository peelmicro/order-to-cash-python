"""Seed settings: the only place connection URLs are assembled (pydantic-settings).

Read from the same `.env` the compose file reads (`POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD`,
`POSTGRES_HOST`, `POSTGRES_HOST_PORT`, `POSTGRES_DB_ORDERS|FULFILLMENT|BILLING`, `MONGO_HOST`,
`MONGO_HOST_PORT`, `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD`,
`MONGO_DB_READMODEL`), so each database name has one source of truth. A full URL
(`ORDERS_DATABASE_URL`, `FULFILLMENT_DATABASE_URL`, `BILLING_DATABASE_URL`, `MONGO_URI`) wins
outright over its parts, for tests and deployments that carry one.

There is NO password default for either database server (review_db_orders F5, #8 D6): with neither
a full URL nor the password variable, constructing the settings raises, so the seed never connects
on a credential committed to source. No `populate_by_name`: with it pydantic-settings would also
read the bare field names (`USER`, `HOST`, `PORT`) from the environment.
"""

from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class SeedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    orders_database_url: SecretStr | None = Field(
        default=None, validation_alias="ORDERS_DATABASE_URL"
    )
    fulfillment_database_url: SecretStr | None = Field(
        default=None, validation_alias="FULFILLMENT_DATABASE_URL"
    )
    billing_database_url: SecretStr | None = Field(
        default=None, validation_alias="BILLING_DATABASE_URL"
    )
    postgres_host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_HOST_PORT")
    postgres_user: str = Field(default="otc_app", validation_alias="POSTGRES_APP_USER")
    postgres_password: SecretStr | None = Field(
        default=None, validation_alias="POSTGRES_APP_PASSWORD"
    )
    orders_database: str = Field(default="otc_orders", validation_alias="POSTGRES_DB_ORDERS")
    fulfillment_database: str = Field(
        default="otc_fulfillment", validation_alias="POSTGRES_DB_FULFILLMENT"
    )
    billing_database: str = Field(default="otc_billing", validation_alias="POSTGRES_DB_BILLING")

    mongo_uri: SecretStr | None = Field(default=None, validation_alias="MONGO_URI")
    mongo_host: str = Field(default="localhost", validation_alias="MONGO_HOST")
    mongo_port: int = Field(default=27017, validation_alias="MONGO_HOST_PORT")
    mongo_user: str = Field(default="otc_mongo_root", validation_alias="MONGO_INITDB_ROOT_USERNAME")
    mongo_password: SecretStr | None = Field(
        default=None, validation_alias="MONGO_INITDB_ROOT_PASSWORD"
    )
    mongo_database: str = Field(default="otc_read_model", validation_alias="MONGO_DB_READMODEL")

    @model_validator(mode="after")
    def _a_credential_must_be_supplied(self) -> Self:
        urls = (
            self.orders_database_url,
            self.fulfillment_database_url,
            self.billing_database_url,
        )
        if self.postgres_password is None and not all(urls):
            raise ValueError(
                "no PostgreSQL credential: set POSTGRES_APP_PASSWORD, or all of "
                "ORDERS_DATABASE_URL, FULFILLMENT_DATABASE_URL and BILLING_DATABASE_URL"
            )
        if self.mongo_password is None and self.mongo_uri is None:
            raise ValueError("no MongoDB credential: set MONGO_INITDB_ROOT_PASSWORD or MONGO_URI")
        return self

    def _postgres_url(self, full: SecretStr | None, database: str) -> str:
        if full is not None:
            return full.get_secret_value()
        password = self.postgres_password
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=password.get_secret_value() if password else None,
            host=self.postgres_host,
            port=self.postgres_port,
            database=database,
        ).render_as_string(hide_password=False)

    @property
    def orders_url(self) -> str:
        return self._postgres_url(self.orders_database_url, self.orders_database)

    @property
    def fulfillment_url(self) -> str:
        return self._postgres_url(self.fulfillment_database_url, self.fulfillment_database)

    @property
    def billing_url(self) -> str:
        return self._postgres_url(self.billing_database_url, self.billing_database)

    @property
    def mongo_connection_uri(self) -> str:
        if self.mongo_uri is not None:
            return self.mongo_uri.get_secret_value()
        password = self.mongo_password
        return URL.create(
            "mongodb",
            username=self.mongo_user,
            password=password.get_secret_value() if password else None,
            host=self.mongo_host,
            port=self.mongo_port,
            query={"authSource": "admin"},
        ).render_as_string(hide_password=False)
