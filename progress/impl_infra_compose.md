# infra_compose (id 4, phase 4) — implementation record

**Process:** light (infra config). Implemented and closed by the leader: compose, `infra/` and root config are leader-editable (`CLAUDE.md`). No reviewer.

## What was built

- `docker-compose.infra.yml` — derived from #8's by targeted edits: 15 services (12 long-running, 2 one-shots `kafka-init` / `n8n-init`, `sonarqube` behind the `sonar` profile), `name: otcpy`, network `otcpy-net`. `mssql` replaced by `postgres:18.6`; n8n moved from SQLite to PostgreSQL through one YAML anchor (`x-n8n-database`) merged into both `n8n` and `n8n-init`; #8-specific comments (`dev-stack.sh`, `JwtOptions`, phase 20 paths) re-pointed or removed.
- `infra/postgres/init/01-create-databases.sh` — four `otc_*` databases owned by `otc_app`, the `n8n` database owned by `otc_n8n`, `CONNECT, TEMPORARY` revoked from `PUBLIC` on all five. Names and passwords from the environment, passed as psql variables (`:'v'`, `:"v"`, `format('%I')`), idempotent through `\gexec`.
- Nine files copied from #8 and `cmp`-identical to it: `infra/kafka/{Dockerfile,create-topics.sh}`, `infra/otel-collector/{Dockerfile,otel-collector-config.yaml}`, `infra/prometheus/prometheus.yml`, `infra/grafana/dashboards/order-to-cash-overview.json`, `infra/grafana/provisioning/{dashboards/dashboards.yml,datasources/datasources.yml}`, `infra/n8n/import-workflows-on-startup.sh`. Eight are also identical to #7's; the Grafana dashboard differs from #7's at line 45 (#8's phase 22 changed it), and #8's is the one #9 needs.
- `.env.example` scoped to phase 4; `.env` from it (git-ignored, `.gitignore:49`).

## Ported-idiom ledger

| Idiom | #7 relied on | #8 supplied it with | #9 supplies it with | Guard (armed) |
|---|---|---|---|---|
| Database bootstrap | `/docker-entrypoint-initdb.d` + `.sh` (`order-to-cash-nestjs/docker-compose.infra.yml:62`) | an entrypoint wrapper, the image has no hook (`order-to-cash-dotnet/docker-compose.infra.yml:83`) | `/docker-entrypoint-initdb.d` + `.sh` (`docker-compose.infra.yml:99`) | healthcheck count, below |
| Healthy only after bootstrap | TCP ping, socket trap documented (`nestjs/docker-compose.infra.yml:75`) | count of `sys.databases` (`dotnet/docker-compose.infra.yml:111`) | TCP **and** count of `pg_database` (`docker-compose.infra.yml:119`) | init-window probe: rc=1 *connection refused* until init completes, rc=0 after; sibling name `otc_notification` → rc=1 |
| App principal may create objects | `GRANT ALL PRIVILEGES` (`nestjs/infra/mysql/init/01-create-databases.sh:42`) | `db_owner` per database (`dotnet/infra/mssql/init/01-create-databases.sql:97`) | database `OWNER` (`infra/postgres/init/01-create-databases.sh:60`) — on PG ≥15 only the owner creates in `public` | `pg_database.datdba` = `otc_app` on all four (query) |
| n8n storage kept out of app databases | SQLite, after D4 dropped an unused MySQL db (`nestjs/docker-compose.infra.yml:427`) | SQLite (`dotnet/docker-compose.infra.yml:425`) | PostgreSQL `n8n` db, own role, `REVOKE CONNECT … FROM PUBLIC` (`infra/postgres/init/01-create-databases.sh:71`) | `otc_n8n` → each `otc_*`: *permission denied*; armed by `GRANT CONNECT … TO PUBLIC` on `otc_orders` → connects; restored → denied |
| Importer writes where the server reads | n/a (same SQLite volume) | same `DB_TYPE: sqlite` written twice (`dotnet/docker-compose.infra.yml:425,519`) | one anchor merged twice (`docker-compose.infra.yml:429,510`) | hazard shown: `n8n-init` with `DB_TYPE=sqlite` → fresh SQLite, "Successfully imported 4 workflows", rc=0 |

Python-port questions (integer division, JSON serialisation, event-loop affinity, cancellation, typing gaps): **not applicable** — no Python code in this feature. The `json`-vs-`jsonb` probe the plan attached to storage was repeated here on 18.6 (see below).

## Verification (all in this session, 2026-10-04)

- **Init-server probe (before trusting "the trap does not apply"):** throwaway `postgres:18.6` with a slow init script — TCP to 127.0.0.1 refused for the whole init window while the Unix socket and `pg_isready` reported *accepting connections*. Over the socket the `otc_*` count already read 4 while a later init script was still running. Both halves of the healthcheck are needed.
- **pg_hba:** `127.0.0.1/32 trust` inside the container (a wrong `PGPASSWORD` still passed), so the healthcheck carries no password.
- **Cold start, empty volumes, images cached and built:** run 1 **39.3 s**, run 2 (after `down -v`) **44.0 s** to 12 healthy + both one-shots exited 0. #7 35–42 s, #8 36 s. PostgreSQL alone: container start → bootstrap done and TCP listener up in **1.8 s** / **2.15 s** (from the engine log; Docker keeps only five health entries). `start_period: 15s` (~8×), `retries: 10` as steady-state detection.
- **RAM (idle, `docker stats`):** PostgreSQL **47.8 MiB** (#7 MySQL ~400 MB, #8 MS-SQL 1.04 GiB); stack total **1 277 MiB** across 12 containers (#8: 2 492 MiB).
- **State:** five databases, owners as designed, no `PUBLIC` ACL entry; roles `otc_app`, `otc_n8n` (non-superuser, no `CREATEDB`); `SHOW timezone` = UTC; cluster at `/var/lib/postgresql/18/docker` inside volume `otcpy_postgres_data`.
- **n8n isolation after `down -v` + `up`:** `otc_orders`, `otc_fulfillment`, `otc_billing`, `otc_notifications` → 0 tables each; `n8n` → 129 tables, 4 rows in `workflow_entity`; no SQLite file in the n8n volume.
- **Image digest:** `postgres:18.6` = `sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722`.
- **`.env.example` completeness, by enumeration:** compose reads 73 variables, `.env.example` declares 74; read-but-undeclared = ∅ except the expected literal `{OTC_GATEWAY_URL}` (documented as a commented override); declared-but-unread = `COMPOSE_PROJECT_NAME` (read by Compose itself), `MONGO_DB_READMODEL` (for the projector, as in #8).
- **`json` vs `jsonb` on 18.6:** `json` returned the input byte for byte; `jsonb` returned `{"a": 1, "buyer": {"gln": …, "name": "Müller"}, "orderId": …, "currency": …, "amountMinor": 1999}` — keys reordered (shorter first), a space after every `:` and `,`. Semantically equal. Confirms the `json` column decision on the pinned version.

## Deviations from the plan

- **A dedicated `otc_n8n` role** — the plan names only `otc_app`. Without it, n8n would log in as either the superuser or `otc_app`, and `otc_app` can create tables in every `otc_*` database, so a mistyped database name would put n8n's tables beside the application's. With its own role and `CONNECT` revoked from `PUBLIC`, that cannot happen (armed above).
- **Server `timezone=UTC`** via `command:` — not in the plan; one line so server-rendered timestamps read as the wire does.
- **`otc_app` owns the databases** rather than being granted privileges on them — the PostgreSQL 15+ equivalent of #7's `GRANT ALL`, as explained in the init script.
