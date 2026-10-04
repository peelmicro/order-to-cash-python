#!/bin/sh
# Order-To-Cash — PostgreSQL bootstrap.
#
# Creates one database per service (database-per-service: no cross-database
# joins, no foreign key crossing a service boundary — see CLAUDE.md), n8n's
# own database, and the two login roles that use them.
#
# This is #7's mechanism recovered: the postgres image runs
# /docker-entrypoint-initdb.d/* against an empty data directory, exactly as
# the MySQL image did (#8's MS-SQL image had no hook and needed an entrypoint
# wrapper). It runs ONCE, on first init; it is nevertheless idempotent, so a
# manual re-run against a live server re-asserts the same state.
#
# Why a .sh file and not a .sql file (#7 review defect D5): a .sql init file
# is executed literally, with no access to the container environment, so the
# role and database names would be a second hardcoded copy of .env. A .sh
# file reads them directly and passes them to psql as variables — quoted by
# psql itself (:'v' for literals, :"v" for identifiers, format('%I')), never
# spliced into SQL by the shell.
#
# Ownership, not grants. Since PostgreSQL 15 the `public` schema is owned by
# pg_database_owner and nobody else may CREATE in it, so #7's
# `GRANT ALL PRIVILEGES ON db.*` has no PostgreSQL equivalent short of
# owning the database. otc_app owns the four otc_* databases because Alembic
# creates, alters and drops objects there; a migration/runtime role split is
# a production concern, and the README says so rather than this file
# pretending to it.
#
# n8n gets its own role (otc_n8n) owning its own database, and CONNECT is
# revoked from PUBLIC on all five. The isolation is therefore structural:
# n8n's role cannot even open an otc_* database, so a mistyped
# DB_POSTGRESDB_DATABASE fails at login instead of creating n8n's 129 tables
# beside the application's (Retail Order Tracker's lesson).

set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${POSTGRES_DB:-postgres}" \
  -v app_user="${POSTGRES_APP_USER:-otc_app}" \
  -v app_password="${POSTGRES_APP_PASSWORD:?POSTGRES_APP_PASSWORD must be set}" \
  -v n8n_user="${POSTGRES_N8N_USER:-otc_n8n}" \
  -v n8n_password="${POSTGRES_N8N_PASSWORD:?POSTGRES_N8N_PASSWORD must be set}" \
  -v db_orders="${POSTGRES_DB_ORDERS:-otc_orders}" \
  -v db_fulfillment="${POSTGRES_DB_FULFILLMENT:-otc_fulfillment}" \
  -v db_billing="${POSTGRES_DB_BILLING:-otc_billing}" \
  -v db_notifications="${POSTGRES_DB_NOTIFICATIONS:-otc_notifications}" \
  -v db_n8n="${POSTGRES_DB_N8N:-n8n}" \
  <<-'SQL'
	-- Roles. \gexec runs each row of the result as a statement, which is how
	-- psql makes CREATE ROLE / CREATE DATABASE conditional (neither accepts
	-- IF NOT EXISTS, and CREATE DATABASE cannot run inside a DO block).
	SELECT format('CREATE ROLE %I LOGIN', :'app_user')
	 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec
	SELECT format('CREATE ROLE %I LOGIN', :'n8n_user')
	 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'n8n_user') \gexec
	ALTER ROLE :"app_user" WITH LOGIN PASSWORD :'app_password';
	ALTER ROLE :"n8n_user" WITH LOGIN PASSWORD :'n8n_password';

	-- Databases: UTF-8 stated rather than inherited from template1; the
	-- collation is the cluster default. Owners as explained above.
	SELECT format('CREATE DATABASE %I OWNER %I ENCODING %L', d.name, d.owner, 'UTF8')
	  FROM (VALUES (:'db_orders', :'app_user'),
	               (:'db_fulfillment', :'app_user'),
	               (:'db_billing', :'app_user'),
	               (:'db_notifications', :'app_user'),
	               (:'db_n8n', :'n8n_user')) AS d(name, owner)
	 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = d.name) \gexec

	-- Nobody connects to a database by default; each owner may connect to
	-- its own. (The owner already holds CONNECT; the explicit GRANT documents
	-- intent and survives an ALTER DATABASE … OWNER TO.)
	SELECT format('REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC', name)
	  FROM unnest(ARRAY[:'db_orders', :'db_fulfillment', :'db_billing',
	                    :'db_notifications', :'db_n8n']) AS name \gexec
	SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I', name, :'app_user')
	  FROM unnest(ARRAY[:'db_orders', :'db_fulfillment', :'db_billing',
	                    :'db_notifications']) AS name \gexec
	GRANT CONNECT, TEMPORARY ON DATABASE :"db_n8n" TO :"n8n_user";
SQL
