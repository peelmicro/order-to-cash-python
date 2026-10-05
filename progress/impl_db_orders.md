# Implementation report: feature 9 `db_orders` (phase 6), full process

Status set to `in_review` (one line in `feature_list.json`, `git diff feature_list.json` read). `./quality.sh` green twice (developer stack up: 46.8 s; developer stack stopped: 45.8 s, 606 passed, total coverage 98.83 %, domain 100 %). `./init.sh` exits 0.

## What was built

| File | Purpose |
|---|---|
| `services/orders/pyproject.toml`, `uv.lock` | runtime deps added to the member |
| `services/orders/alembic.ini`, `alembic/env.py`, `alembic/script.py.mako` | async Alembic environment, URL from `config.attributes["url"]` or `OrdersDatabaseSettings`; own `alembic_version` |
| `services/orders/alembic/versions/0001_initial_orders_schema.py` | hand-written migration: 11 tables, 8 FKs, 37 indexes, explicit constraint names |
| `.../infrastructure/settings.py` | pydantic-settings `OrdersDatabaseSettings` (reads the compose `.env` names; `ORDERS_DATABASE_URL` overrides) |
| `.../infrastructure/persistence/models.py` | SQLAlchemy 2 models (11 classes), naming convention |
| `.../persistence/types.py` | `RawJson`: json column that stores and returns text |
| `.../persistence/range_guards.py` | write-boundary range guard (ORM attribute `set` listener on every integer column) + `IntegerOutOfRangeError` / `QuantityOutOfRangeError` (`DomainError` subclasses) |
| `.../persistence/sequences.py` | the three SQL strings of the counter (seed `ON CONFLICT DO NOTHING`, `FOR UPDATE`, advance) |
| `conftest.py` (repo root) | ONE session-scoped Docker-held `postgres:18.6`, `fresh_database` per test |
| `services/orders/tests/integration/{conftest,test_orders_*}.py` (8 files), `tests/unit/test_orders_range_guards.py` | the tests |
| root `pyproject.toml` | `markers = ["integration: ..."]`; `"conftest.py"` added to mypy `files`. `filterwarnings` NOT changed (measured: no new warning class from SQLAlchemy 2.1.3, asyncpg, Alembic 1.20 or testcontainers.community.postgres under `error::DeprecationWarning`; `tests/architecture/test_warning_policy.py` still green) |

`services/orders/tests/` was flat (only `test_orders_health.py`); I added `unit/` and `integration/` per plan line 455 and left the health test where it is (moving it is churn). Test files carry the `test_orders_` prefix so basenames stay unique across services (mypy).

Not done on purpose (bounds): no repositories, relay, allocator, handlers or composition wiring (Phase 8). #8's later `AddSagaCommandsDeadLetterColumns` columns (`dead_lettered_at`, `triggering_event_envelope`, `triggering_event_topic`) are NOT added: the feature that needs them owns that migration. No `specs/shared/` edit. `specs/shared/test-matrix.md`: no row changed, because no R row is provable by this feature alone (R62 there is the idempotent-replay behaviour, a Phase 8 test; the `request_id` index is only its storage leg, proven by `test_r62_*` below and left TODO in the matrix for the feature that proves the behaviour).

## Packages installed (for the commit's `Packages installed:`)

`uv add --package otc-orders sqlalchemy asyncpg alembic pydantic-settings`, then adjusted by hand. Member lists stay bare names, the idiom of the existing members (fastapi, uvicorn: exact pins live in the lock and, for tools, the root dev group). Resolved and locked: **sqlalchemy 2.1.3** (as the `sqlalchemy[asyncio]` extra, which adds **greenlet 3.5.6**; measured: without it `sqlalchemy.ext.asyncio` raises ImportError), **asyncpg 0.31.0**, **alembic 1.20.0** (+ **mako 1.4.3**), **pydantic-settings 2.15.0**. All equal the plan's line-690 pins. Nothing added to `shared_kernel` or `cqrs`. No sync driver (no psycopg).

## Decisions

* **Fixture placement (addendum 1).** Root `conftest.py`. Reason: pytest applies it to `tests/`, `packages/` and `services/` with no import between services, so the import-linter independence contract is untouched; a conftest under `tests/` would not reach `services/*/tests`, and a helper package imported from services would be a cross-service import. One `postgres:18.6` container per session, started lazily by the first test asking for `postgres_server`; `CREATE DATABASE otc_test_<uuid>` per test, `DROP ... WITH (FORCE)` after. Port is assigned and held by Docker (`with_exposed_ports`, no free-port picker; #8 id 85). Loop scopes are written beside each fixture (sync session fixture has no loop; `fresh_database`, `migrated_db`, `engine` are function-scoped and dispose in the same loop). Features 10/11 reuse `fresh_database` and add only their own `alembic_runner`. Measured `quality.sh` wall clock: 46.8 s with the stack up, 45.8 s stopped; pytest alone 25.7 s for 606 tests (the 18 new integration tests cost about 3 s each at most, container started once). Conftest modules are not importable by name under `--import-mode=importlib`, so the orders conftest declares a small `FreshDatabase` Protocol and tests annotate fixture parameters as `Any` (mypy strict stays on, no ignores).
* **Quantity column is `integer`** (#8 `InitialCreate.cs:252` `quantity` `int`; #7 `drizzle/0000_bizarre_champions.sql:83` `quantity int NOT NULL`). Plan and spec do not widen it.
* **FK-column indexes** (one per FK, 8) are added beyond the spec's own indexes. MySQL (#7) and EF Core (#8) index FK columns implicitly, PostgreSQL does not. The index set is closed as a literal of 37 (11 PK + 11 unique + 15 non-unique; counted by the test itself).
* **`orders.request_id`**: `uuid NULL`, plain unique index `uq_orders_request_id` (not partial). One migration (not #8's two) because #9 has no earlier history.
* **Range guard location:** an ORM attribute `set` listener installed over the mapper registry, so every `Integer`/`BigInteger` column of every mapped class is guarded (12 columns, closed against the live catalog), and a column added later is covered without anyone remembering. A listener raises at assignment, unwrapped; a `TypeDecorator` bind hook was rejected because SQLAlchemy wraps exceptions raised during bind processing in `StatementError` (the very "not a driver error" the criterion rules out).
* **Not placed in `shared_kernel`:** a pure `ensure_in_range` would be reusable by features 10/11, but `shared_kernel`'s public surface is pinned by `test_kernel_surface.py` and reviewed in phase 5; changing it is out of this feature's bounds. Features 10/11 will each carry their own copy of `range_guards.py` (about 100 lines). Proposed disposition: promote the pure function and the error classes to `shared_kernel` in one deliberate change before feature 11, or accept the duplication.

## Ported-idiom ledger

| Idiom | #7 relied on | #8 supplied | #9 supplies, guarded by |
|---|---|---|---|
| Counter seed | `INSERT ... ON DUPLICATE KEY UPDATE`, atomic per statement (`order-number-allocator.ts:25,74`) | `IF NOT EXISTS ... INSERT` check-then-act, raced (id 45; `EfCoreOrderNumberAllocator.cs:35,40`) | `INSERT ... ON CONFLICT DO NOTHING` in `sequences.py`; `test_sixteen_concurrent_first_callers_get_distinct_contiguous_numbers`, sentinel `test_sentinel_check_then_insert_seed_loses_the_race` |
| Row lock for allocation | `SELECT ... FOR UPDATE` (`order-number-allocator.ts:6`) | `UPDLOCK, ROWLOCK` | `SELECT ... FOR UPDATE` in `sequences.py`; same test (arm: lock removed) |
| Money width | `int` columns (`0000_bizarre_champions.sql:66`), safe-integer bound in the type | `bigint` after id 44, `InitialCreate.cs:158,211` | `bigint` from the first migration; `test_money_columns_are_bigint`, `test_every_column_of_every_table_has_the_planned_type` |
| JSON payload text | `json`, MySQL reordered keys (`0000_bizarre_champions.sql:96`) | `nvarchar(max)` preserved text (`InitialCreate.cs:53,89`) | `json` + `RawJson` passthrough (SQLAlchemy's asyncpg dialect `json.loads` a json column on read, measured); `test_outbox_payload_is_read_back_byte_identical` |
| `request_id` many NULLs | MySQL unique allows NULLs (`0005_sticky_goblin_queen.sql:5`) | filtered unique index (`AddOrdersRequestId.cs:21-25`) | plain unique index (NULLS DISTINCT default); `test_r62_*` |
| Outbox order | `bigint unsigned auto_increment` | `bigint IDENTITY(1,1)` | `bigint GENERATED ALWAYS AS IDENTITY`; types test row `identity:ALWAYS` |
| FK set | 8 at `0000_bizarre_champions.sql:114-121` | 8 at `InitialCreate.cs:141,167,193,223,229,235,260,266` (7 of 8 missing in review round 1) | 8 in the migration; closed-set test from `pg_constraint` |
| Timestamps | `datetime(3)` | `datetime2(3)` | `timestamptz(3)`; read-back test (rounds to the ms, aware UTC) |
| Quantity width | `int` | `int` (`Quantity.cs:23,35`, `InitialCreate.cs:252`) | `integer` + ORM guard; `test_quantity_*` |
| Country code (added by the leader from review F4, ACCEPTED, NOT FIXED) | `char(2)` (`0000_bizarre_champions.sql:33,48`) | `nvarchar(2)` (`InitialCreate.cs:130,182`) | `varchar(2)` (Databases.EN.md §4.1 says `char(2)`; the plan maps text to `varchar(n)`), guarded by the types test. Re-open if a parity test against #7's DDL types, or the seed job, needs blank-padded semantics |
| Migration commit | n/a (drizzle) | EF `Migrate` | async template, `engine.begin()`; every lifecycle test |

Guards of #8 enumerated: its FK closed-set assertion (ported, strengthened with `on delete` and diagnostics first); its index checks were presence-only (deliberately not ported: closed set instead); its allocator concurrency test (ported with a sentinel).

## Acceptance mapping and arming (each arm: backup, one mutation, named test run, restore with `cmp`, `__pycache__` cleared; the scripts compare restored file against the backup and assert equality; full verbatim outputs were captured in the leader-visible scratchpad `arms1.out`, `arms2.out`)

| # | Item (unit) | Test(s) | Arm and verbatim result |
|---|---|---|---|
| 1 | migration lifecycle (history) | `test_upgrade_downgrade_reupgrade_lifecycle`, `test_no_postgres_enum_types` in `test_orders_migration_lifecycle.py` | testcontainers 18.6: closed relation set after upgrade (11 tables + `alembic_version` + `outbox_seq_seq`), after downgrade exactly `{("alembic_version","r")}`, re-upgrade equals first upgrade. Composed run below. |
| 2 | types (every column) | `test_every_column_of_every_table_has_the_planned_type`, `test_money_columns_are_bigint`, `test_payload_columns_are_json_not_jsonb` | (a) `orders.total_amount` to `Integer`: `Left contains one more item: "orders.total_amount: expected ('bigint', False, ''), live ('integer', False, '')"`; dedicated: `{('orders','total_amount'): 'integer'} == {}`; also `products.price`. (b) `outbox.payload` to JSONB: `outbox.payload: expected ('json', False, ''), live ('jsonb', False, '')`. (c) `orders.order_date` precision dropped: `expected ('timestamp(3) with time zone', False, ''), live ('timestamp with time zone', False, '')`. Also `Identity(always=False)`: `expected ... 'identity:ALWAYS'), live ... 'identity:BY DEFAULT'`. Money population = literal 6, derived by `sed -n 41,150p "Order To Cash - Databases.EN.md" \| grep -n "cents"` (6 rows). |
| 3 | `request_id` (rows) | `test_r62_two_orders_with_null_request_id_both_insert`, `test_r62_two_equal_non_null_request_ids_violate_the_unique_index` | `NULLS NOT DISTINCT`: `UniqueViolationError: duplicate key value violates unique constraint "uq_orders_request_id" DETAIL: Key (request_id)=(null) already exists.` Non-unique index: `Failed: DID NOT RAISE UniqueViolationError`. Partial index: caught by the index-set test (`predicate '(request_id IS NOT NULL)'`), NOT by the NULL test (a partial unique index also admits NULLs; the index-set test is the guard for that shape). |
| 4 | FK set / index set | `test_the_foreign_key_set_is_exactly_the_eight_planned`, `test_the_index_set_is_exactly_the_planned_one` | FK deleted: `missing: [('orders', ('company_id',), 'companies', ('id',), 'a')]`; FK substituted to `retailers`: `Extra ... ('orders', ('company_id',), 'retailers', ('id',), 'a')`; cascade removed: `missing: [('order_items', ('order_id',), 'orders', ('id',), 'c')]`; index deleted: `missing: [('outbox', 'ix_outbox_published_at_seq', ...)]`; extra index: `extra: [('orders', 'ix_orders_status', False, ('status',), None)]`; column order swapped: both orders listed. Diagnostic is the assertion message and is evaluated before the count assertion (#8 A2). |
| 5 | counter seeding (concurrent callers) | `test_sixteen_concurrent_first_callers_get_distinct_contiguous_numbers`, `test_sentinel_check_then_insert_seed_loses_the_race` | 16 callers, separate connections, `asyncio.Barrier`. Racy seed (the #8 shape as a `DO $$ IF NOT EXISTS ... INSERT` block): sentinel measured `racy seed lost the race in 10 of 10 rounds`; in the main test: `UniqueViolationError ... "pk_order_number_sequences"` (15 of 16 callers). Seed deleted: `TypeError: int() argument ... not 'NoneType'` x16. `FOR UPDATE` removed: `assert [1, 2, 2, 2, 2, 2, ...] == [1, 2, 3, 4, ...]`. Seed value 2: `[2, 3, 4, ...] == [1, 2, 3, ...]`. |
| 6 | quantity range | `test_quantity_column_max_*` / `..._max_plus_one_is_a_domain_refusal_with_a_stable_code` (unit), `test_quantity_max_round_trips_and_max_plus_one_is_a_domain_error`, `test_every_integer_column_of_the_live_database_is_guarded`, `test_residual_a_core_insert_bypasses_the_guard_and_only_the_engine_refuses` | Check deleted: `AssertionError: got sqlalchemy.exc.DBAPIError: (sqlalchemy.dialects.postgresql.asyncpg.Error) invalid input for query argument $6: 2147483648 (value out of int32 range)` (names the driver error); population test then lists all 12 columns unguarded. Bound corrupted to `2**31`: `DID NOT RAISE QuantityOutOfRangeError`. Column widened to BigInteger: same. Specific code dropped: `IntegerOutOfRangeError: 2147483648 does not fit order_items.quantity`. One column skipped: `['order_items.discount'] == []`. Codes: `quantity.out_of_range` (quantity), `storage.integer_out_of_range` (every other integer/bigint column). |
| 7 | JSON bytes (plan line 967) | `test_outbox_payload_is_read_back_byte_identical`, `test_saga_command_payload_is_read_back_byte_identical` | Written by `otc_contracts.wire.to_wire_json` over the golden `order.placed.v1` payload with a non-ASCII description. `outbox.payload` as JSONB: `assert b'{"lines": [...Discount": 0}' == b'{"orderRefe...Amount":8934}'` / `At index 2 diff: b'l' != b'o'`. `saga_commands.payload` as JSONB: `At index 8 diff: b' ' != b'1'`. |
| 8 (addendum 3) | timestamp read-back | `test_instants_come_back_aware_utc_and_rounded_to_the_millisecond` | Measured: tz-aware UTC, `.123987` comes back `.124000`: ROUNDED, not truncated (the wire formatter truncates; the two differ for sub-ms input, so the domain should hand whole milliseconds). Arm: `occurred_at timestamptz(6)`: `datetime(...123987...) == datetime(...124000...)` fails. |
| extra | models vs migration drift | `test_autogenerate_finds_no_difference_between_models_and_migrated_schema` | Index removed from the model only: `('remove_index', Index('ix_orders_status_order_date', ...))`. This is a drift detector; the proof of the schema is the live-catalog tests. |

### Composed postgres run (acceptance 1, `otcpy-postgres`, database `otc_orders`, role `otc_app`, `ORDERS_DATABASE_URL=postgresql+asyncpg://otc_app:***@localhost:5432/otc_orders`)

```
alembic -c services/orders/alembic.ini current          -> 0001 (head)   [after first upgrade]; 12 tables in public
alembic -c services/orders/alembic.ini downgrade base   -> exit 0; pg_tables = alembic_version only; sequences/views/matviews = 0
alembic -c services/orders/alembic.ini upgrade head     -> exit 0; 12 tables; current = 0001 (head); alembic_version = 0001
alembic ... upgrade head --sql                          -> 12 CREATE TABLE (offline mode works)
```

The composed `otc_orders` database is left at head (empty tables). It is not exercised by pytest; the suite never touches port 5432.

### Developer stack down (#8 id 104)

All 12 `otcpy-*` containers were stopped (`docker stop`, not `down`: volumes and containers kept); `docker ps | grep -c otcpy-` = 0, nothing listening on 5432 or 9092; `./quality.sh` then passed (606 passed, 45.8 s). Containers were restarted afterwards (`docker start`), all healthy, `./init.sh` exit 0.

## Defeat-list rows

| # | Row | Applies? |
|---|---|---|
| 1 | delete the behaviour | yes, every guard (FK, index, seed, lock, range check, json column) |
| 2 | corrupt a supplied field | yes (seed value 2, bound `2**31`, precision, widths, identity mode) |
| 3 | substitute a sibling identifier | yes (FK to `retailers`, quantity as BigInteger, index column order) |
| 4, 5, 6 | shadow in a comment / dead region / triple-quoted string | N/A to the schema guards: they read the live catalog and the live bytes, not source text, so a decoy in source cannot satisfy them. The only source-reading instrument is none. |
| 7 | drop an optional element | yes (specific code dropped from the map, `ondelete` dropped, one column skipped by the guard) |
| 8 | literal vs literal | checked: expected sets are literals compared with the live catalog, never to each other; a fixture cannot satisfy by accident (distinct uuids, distinct column values) |
| 9 | closer half satisfied, premise stale | the partial-unique-index arm is the example: the NULL test still passed, the index-set test caught it |
| 10 | build output/caches join the population | `__pycache__` cleared around every arm |
| 11 | form the instrument does not recognise | the guard is an attribute event; Core `insert()` is the unrecognised form (row 12) |
| 12 | failure through a path the population never drives | yes: Core `insert()` and raw SQL bypass the ORM guard; pinned as a residual by `test_residual_a_core_insert_bypasses_...` (fails if the bypass is ever closed) |

## #8 inherited findings

* **id 44 (money column width): AVOIDED.** `bigint` for all 6 money columns of `otc_orders` in the first migration; literal-population test plus the full types map; armed with `integer`.
* **id 45 (counter seed race): AVOIDED.** `ON CONFLICT DO NOTHING`; 16 concurrent first callers; the racy shape measured failing 10 of 10 rounds, so the harness can see the race.
* **#8 review D1 (FKs undeclared with a green suite): AVOIDED.** Closed-set from `pg_constraint`, armed by delete and by substitute.
* **#8 id 85 (self-assigned ports): AVOIDED** (Docker-held). **#8 id 104 (suite hid behind a developer service): AVOIDED**, proven with the stack stopped.
* #8 advisories A1-A3 of db_fulfillment/db_billing: index set closed (A3/A1), timestamps asserted on read-back (A1), diagnostic before count (A2).

## Residuals and proposed dispositions

1. **Range guard covers ORM attribute assignment only.** Phase 8's repositories are not prevented, mechanically, from using Core `insert()` or raw SQL; the engine would then refuse with a wrapped driver error (pinned by `test_residual_a_core_insert_bypasses_the_guard_and_only_the_engine_refuses`). Phase 8 prevention is by convention plus that test; proposed: `orders_acceptance` review checks every write path (`grep -n "insert(\|text(" services/orders/src`) and the test stays as the marker. Every `bigint` column not written from a `Money` is covered by the same listener (12 columns), so `review_shared_kernel.md` Q3 "what stays owed" is closed for ORM writes, and open for Core/raw writes.
2. **`range_guards.py` will be duplicated in features 10/11** (see Decisions). Proposed: promote to `shared_kernel` in a deliberate change, or accept.
3. **`order_number_sequences` is created empty.** #8's allocator seeds from `MAX(order_reference)` of already-seeded orders (`EfCoreOrderNumberAllocator.cs` remark); the starting value for a database that was seeded by `seed` is a Phase 8/`seed` decision. `sequences.py` seeds `(1, 1)`.
4. **Alembic autogenerate drift test** compares models to migration; any custom type (`RawJson`) compares equal to JSON in the present Alembic version (measured: empty diff). A future Alembic that compares custom types differently would make it noisy, not silent.
5. **`.env` has no `POSTGRES_HOST`**; settings default `localhost`. Services in compose will need `ORDERS_DATABASE_URL` or `POSTGRES_HOST=postgres` (composition feature).
6. `R62` stays `TODO` in the test matrix by design (see above).

## How to test by hand

```
./init.sh && ./quality.sh
uv run pytest services/orders -q                       # 28 tests incl. 18 integration (needs Docker)
export ORDERS_DATABASE_URL=postgresql+asyncpg://otc_app:otc_app_dev_password@localhost:5432/otc_orders
uv run alembic -c services/orders/alembic.ini upgrade head
docker exec otcpy-postgres psql -U postgres -d otc_orders -c '\dt'
uv run alembic -c services/orders/alembic.ini downgrade base && uv run alembic -c services/orders/alembic.ini upgrade head
# arm one guard yourself: change `sa.BigInteger()` to `sa.Integer()` for orders.total_amount in
# services/orders/alembic/versions/0001_initial_orders_schema.py, then
uv run pytest services/orders/tests/integration/test_orders_schema_types.py -q   # must fail naming orders.total_amount
```

## Surprises

* `asyncpg` returns the `"char"` catalog type (`relkind`, `typtype`) as `bytes`; my first lifecycle test compared strings and an empty result looked like "upgrade did nothing" (exit 0, empty set). Cast to `text` in SQL. (I first blamed Alembic's commit and wrote a wrong comment; measured both `connect()` and `begin()` persist DDL on Alembic 1.20, comment corrected.)
* SQLAlchemy's asyncpg dialect installs a `json` codec that `json.loads` on read: a plain string-typed json column returns a `dict`, losing the bytes. `RawJson` casts to text on select.
* `sqlalchemy[asyncio]` is required (greenlet) in 2.1.3.
* The ORM attribute listener is the only place a domain refusal can surface unwrapped; bind-time hooks get wrapped in `StatementError`.
