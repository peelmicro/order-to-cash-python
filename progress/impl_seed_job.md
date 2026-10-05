# impl_seed_job: feature 12 `seed_job` (Phase 7), plus the gate-time cut

Status: **`in_review`** (`feature_list.json` id 12, one line edited, diff read). No stop condition was hit. Classification: Part A **light**, Part B **full**, Part C **tooling only** (the live run against #8 was not started; #8's stack was never started).

Wall clock (`date`): Part A 16:09:20 to 16:19:12 (baseline measurement 16:09:34, the sentinel rewrite, re-measure 16:19:12 to 16:20:27); Part B 16:20:36 (`uv add`) to 16:55 (last gate; the arming runs and the first full gate 16:36 to 16:41 are inside it); Part C 16:25 to 16:48, interleaved with B's arming (the #9 half verified end to end on the dev stack at 16:45 to 16:47).

## quality.sh timings (stack `otcpy` stopped each time; `/usr/bin/time -p`)

| Run | whole script | pytest | tests | note |
|---|---|---|---|---|
| Baseline (before anything) | **87.47 s** | 64.77 s | 734 | `real`, 12 containers stopped, nothing on 5432/27017/9092/4222 |
| After Part A | **75.16 s** | 53.28 s | 734 | the three sentinels at one round |
| After Part B (seed + Mongo container) | 99.30 s | 78.35 s | 884 | first full gate with the seed |
| After Part C tests (before trimming two redundant tests) | 107.55 s | 85.27 s | 901 | |
| **Final** | **104.66 s** | 80.46 s | **899** | the number to quote; run-to-run spread on this machine is about 5 s (99 to 108 s for near-identical suites) |

Attribution, honestly: Part A took 12.3 s off; the seed took about 24 s back (Docker-held `mongo:8.3.8` start about 4 s once, plus 168 seed tests of which 29 are integration at about 1.3 s each: three template copies, a seed, three `DROP DATABASE ... WITH (FORCE)`, a Mongo drop). **The final script is above the ~90 s threshold the Phase 6 wrap-up recorded (99.8 s)**; the net against that is +4.9 s. The cheap next cut, not taken here: a module-scoped seeded stack (`loop_scope="module"`) shared by the five read-only assertions, which would save about 10 s; I did not do it because it needs a module-loop variant of the root conftest's template factory.

## Part A: the gate-time cut (light)

The sentinel `test_sentinel_check_then_insert_seed_loses_the_race` (x3, `services/{orders,fulfillment,billing}/tests/integration/test_*_counter_seed.py`) used `rounds = 10` of 16 barrier-released callers and asserted "at least one round lost". The change is **of kind**: the racy statement now widens its own check-to-insert window, `DO $$ BEGIN IF NOT EXISTS (...) THEN PERFORM pg_sleep(0.5); INSERT ...; END IF; END $$`. Every caller the harness released together has passed the check before the first insert lands, so exactly `CALLERS - 1 = 15` of 16 lose to the unique key, in ONE round, and the assertion is `len(lost) == 15` (not `> 0`). A harness that serialised the callers would let the first one commit before the second checks and lose nobody.

* (i) Repeats: 6 runs of each file (the file's two tests), 18 runs, **18 passes** (`2 passed in 4.0 to 5.3 s`; most of that is the container). Run again after the final comment edit: 5 more per file, 15 passes.
* (ii) Arm (re-run after the final text, on all three files): `cp` backup, `asyncio.gather` replaced by a sequential loop and `asyncio.Barrier(CALLERS)` by `Barrier(1)` (a sequential loop cannot cross a 16-party barrier; the first arm I tried hung on it, and I killed it and restored from the backup, `cmp` clean), the ONE test:

```
== orders   E  AssertionError: the racy seed lost 0 of 16 callers, expected 15: the harness did not release the callers together, so it cannot prove the ON CONFLICT seed   (1 failed, 1 deselected in 3.54s)  restored (cmp ok)
== fulfillment   (same message, 3.48s)  restored (cmp ok)
== billing       (same message, 3.55s)  restored (cmp ok)
```

Stale-cache care: `*counter_seed*.pyc` deleted before every green re-run. The three files are 87 lines and kept in step (the only differences are the table names, as before). A `ruff` E501 and an S608 caught by the first gate were fixed before measuring (`pg_sleep(0.5)` is a literal in the string).

## Part B: the seed

### What was built

`python -m otc_seed` writes #7's and #8's dataset into `otc_orders`, `otc_fulfillment`, `otc_billing` (PostgreSQL) and the MongoDB `order_timeline` read model. 3 currencies, 12 products, 7 retailers, 22 companies, 154 credit lines, 215 stock rows, 6 sagas (5 completed + 1 cancelled), 11 order items, 11 reservations, 5 despatches (10 items), 5 invoices (10 items) and 5 payments, 15 credit ledger rows, 50 outbox rows, 6 timeline documents. Verified live on the dev stack: first run `totalAdded 547` (541 rows + 6 documents), second run `0`, exit 0 both times, 1.6 s.

### Counts derivation (re-derived, not copied)

Command (executes #7's own TypeScript; `tsx` from `order-to-cash-nestjs/apps/seed/node_modules/.bin`, script in the session scratchpad, nothing written in #7): `tsx derive.ts` over #7's `SAGAS`, `CURRENCIES`, `PRODUCTS`, `RETAILERS`, `COMPANIES`, `CREDITS`, `STOCK`. Output, verbatim:

```
timeline docs 6 currencies 3 products 12 retailers 7 companies 22 stock 215 credits 154
items 11 outbox 50
reservations 11 despatchItems 10 invoiceItems 10 creditItems 15 invoices 5 despatches 5
```

Every plan/#8 count agrees (3, 12, 7, 22, 215, 154, 6, 11, 50, 6). Cross-checks by structure: credits 7 + 7 x 21 = 154; stock 11 saga pairs + 17 baseline companies x 12 products = 215; outbox 17 + 12 + 21 = 50. The population claim is also a test: `unit/test_dataset_counts.py` and the exact-count `EXPECTED_COUNTS` in `integration/test_seed_databases.py`.

### Oracle first (#8's lesson, line 280)

Checked in **before any writer existed**: `services/seed/tests/fixtures/order_timeline_from_number7.json` (the 6 documents) and `seed_dataset_from_number7.json` (every master table, every saga row, every outbox payload, timeline entries, and the id/GLN/EAN vectors). Both were produced by executing #7's `toTimelineDocument` and #7's constants with `tsx` (node v24.19.0). **Independent re-derivation result:** the timeline fixture parsed-equals #8's checked-in `tests/Seed.IntegrationTests/OracleFixtures/order_timeline_from_number7.json` (`True`, 6 and 6 documents, both 720 lines and 24 989 bytes). The relational dataset file has no #8 counterpart; its provenance is the same execution of #7's TS.

### Files

| File | Change |
|---|---|
| `services/seed/src/otc_seed/domain/{deterministic,clock,money_text,timeline}.py`, `domain/data/{currencies,products,retailers,companies,credits,sagas,stock}.py` | new: the pure dataset (domain purity and the AST money guard cover them) |
| `services/seed/src/otc_seed/application/{__init__,dataset,ports,run_seed}.py` | new: `SeedDataset`, the `SeedTarget` port, `run_seed` (verify all, then write) |
| `services/seed/src/otc_seed/infrastructure/{tables,raw_json,range_check,schema_check,payloads,postgres,mongo,settings}.py` | new: Core tables, passthrough json type, range check, live-schema comparison, contract-validated payload writer, three relational targets, Mongo target, pydantic-settings |
| `services/seed/src/otc_seed/{composition,__main__}.py`, `presentation/cli.py` | new composition root, entry point, CLI (exit codes 0/1/2) |
| `services/seed/README.md` | new: commands, env vars, and backlog 201's seeded-vs-live note |
| `services/seed/tests/conftest.py`, `tests/fixtures/*.json` | oracle fixtures and the field-by-field timeline comparer |
| `services/seed/tests/unit/` (11 files, 122 tests plus 15 in the tooling file) and `tests/integration/` (6 files, 29 tests) | new; the stub `tests/test_seed_cli.py` is **deleted** (it asserted `main() == 0` with no work behind it) |
| `conftest.py` (root) | Mongo fixtures only: `mongo_server` (session, sync), `fresh_mongo_database` (function loop) |
| `services/{orders,fulfillment,billing}/tests/integration/test_*_counter_seed.py` | Part A |
| `services/seed/pyproject.toml`, `uv.lock` | `uv add --package otc-seed "sqlalchemy[asyncio]" asyncpg pymongo pydantic-settings` |
| `scripts/seed_parity.py` | Part C tooling |
| `feature_list.json` | line 216 (id 12) `in_progress` to `in_review` only |

Packages installed: **pymongo 4.18.2**, **dnspython 2.8.0** (pymongo's dependency) in the workspace venv and `uv.lock`. `sqlalchemy[asyncio]>=2.1.3`, `asyncpg>=0.31.0`, `pydantic-settings>=2.15.0` were already locked (other services); they are new to `services/seed/pyproject.toml` only. No npm package. No dependency added to `shared_kernel` or `cqrs`.

### Answers to the brief's questions

**(a) Where do the seed's table definitions come from, and what fails if they drift?** Hand-written SQLAlchemy Core `Table`s in `infrastructure/tables.py` (one `MetaData` per database), because import-linter forbids importing a service's models. They are not trusted: `infrastructure/schema_check.py::schema_problems` compares each table with the LIVE database: existence, per column the PostgreSQL type text, nullability and identity, the primary key, every foreign key (columns, referred table and columns, ON DELETE), the set of unique column sets. Used twice: at runtime (`PostgresTarget.verify`, run before any write; a database not at head or drifted is refused naming the table/column) and in `integration/test_seed_tables_match_migration.py`, which runs it against the root conftest's **Alembic-migrated templates** of the three services (never a schema the seed created). Running it found two real omissions in my first draft (`stock` and `credits` unique pairs). Armed 8 ways against the live database in the suite (a type widened, a column renamed, a nullability flipped, a new NOT NULL column, a varchar shortened, a unique dropped, an ON DELETE changed, a table dropped), each reported by name, plus the production arm below.

**(b) Range guard and the write-path population (backlog 204(a) style).** The seed cannot call `otc_orders`' `ensure_in_range`. `infrastructure/range_check.py::ensure_row_in_range` checks every integer column of a table, the width taken from the column TYPE of the seed's own table (exact `Integer` / `BigInteger` / `SmallInteger`, bool and non-int refused), and is called for every row by `postgres.insert_missing` before any statement exists. Population (`grep -n "insert(\|text(\|bulk_\|update_one\|create_index\|\.execute(" -r services/seed/src`, and the AST scan `unit/test_write_path_population.py`, which has sentinels for a plain call, `if False:`, `if TYPE_CHECKING:`, a `bulk_` helper, an attribute call and a nested function, and for comment/string non-hits):

| Hit | Classification |
|---|---|
| `infrastructure/postgres.py:62` `pg_insert(table)...on_conflict_do_nothing` | THE only insert; preceded by `ensure_row_in_range` for every row (`test_the_one_insert_path_checks_the_range_before_any_statement_exists`) |
| `postgres.py:59` `conn.execute(select(...))` | a SELECT of existing ids, no write |
| `mongo.py:48` `update_one(... $setOnInsert ...)` | BSON documents; no column width exists; money in the document is the same `int` |
| `mongo.py:39` `create_index` | no data |
| `mongo.py:3` | a docstring, not a call |

The guarded-column population is a literal in `unit/test_range_check.py` (13 tables, 21 columns, including `outbox.seq` which is never written) and the types it reads are proved equal to the live database by (a).

**(c) Idempotence.** Postgres, every table: rows keyed by DETERMINISTIC primary key; existing ids are read first and only missing rows are inserted, with `ON CONFLICT (id) DO NOTHING` kept as the concurrent-run safety. DO NOTHING rather than the upsert #7 and #8 use. #7 (`onDuplicateKeyUpdate`, `orders-db.writer.ts:61`) rewrites only `updated_at` (and `published_at` / `value_date` / `description` on outbox, payments, order items), so it does not reset units, status or limits, but it rewinds `updated_at` and replaces the 6 timeline documents whole (`mongo.writer.ts:211`). #8 (`UpsertAsync`, `OrdersSeedWriter.cs:37`, `EfUpsert.cs:25-35`) re-applies every column, so a re-run restocks all 215 stock rows to the seed values while live reservations exist. Stock units, order status and a projector-advanced timeline are live state, and a second run must not reset them (**a deliberate divergence from #8, and from #7 for `updated_at` and the timeline documents; re-open trigger: if a "refresh the seed" semantic is wanted, or the Part C live diff shows stock live-column differences that must be attributed**). A second run executes no INSERT, burns no identity value, and reports `added = 0`. MongoDB: `update_one({"_id": orderId}, {"$setOnInsert": document}, upsert=True)`. Test: `test_running_the_seed_twice_changes_nothing` dumps **every row of every table** as `(whole-row text, xmin)` (so a rewrite with identical content still shows) in the three databases, runs again, asserts report zeros and dump equality (`> 400` rows, non-vacuous); `test_running_the_seed_twice_changes_no_document` does the same for MongoDB documents; two more prove live state survives (`..._does_not_reset_state_a_live_order_changed`, `..._left_alone`).

**(d) Outbox payload serializer.** `infrastructure/payloads.py`: each domain payload (a wire-shaped dict) is parsed into the contract's payload model (the `payload` annotation of that event type's `FACT_MODELS` envelope, so no second list) with `from_wire_json` (a pattern or range violation fails the seed) and written by **`otc_contracts.wire.to_wire_json`**: compact, non-ASCII raw (the `-` in the cancelled order's notes is the raw em dash), camelCase, `.mmmZ`. `json.dumps` only carries the dict into the parse. Columns are `json`, and the `RawJson` passthrough type binds the text unchanged; read back with `payload::text`. The envelope is not stored by the outbox, so byte-exactness there is the relay's job (a later phase); the payload is **semantically equal to #7's for all 50 rows** (`test_every_payload_is_semantically_equal_to_the_one_7_wrote`).

**(e) Instants.** No seeded instant has a sub-millisecond part: all derive from three whole-second constants plus whole minute/second/day offsets; `unit/test_seed_instants.py` asserts it over **every datetime reachable from the dataset** (`> 200` found), plus agreement of the domain formatter with `otc_contracts.wire.format_instant`, and truncation-not-rounding. #8 fixes its instants the same way (whole-second constants); #7's are millisecond `Date`s. Backlog 205 is therefore not triggered by the seed.

**Mongo fixture (step 5).** `conftest.py` (root): `mongo_server` (session, sync, `testcontainers.community.mongodb.MongoDbContainer`, image `mongo:8.3.8`, container port 27017 with the host port assigned and held by Docker, no free-port picker) and `fresh_mongo_database` (`loop_scope="function"`, written beside it; a unique database name, dropped through an `AsyncMongoClient` opened and closed inside the fixture). Root, not `services/seed`, so the projector (Phase 12) reuses it with no service importing another, exactly the Postgres fixtures' reason. **No DeprecationWarning** came from `testcontainers.community.mongodb` (measured: the suite ran under `error::DeprecationWarning`), so **no filter was added** and `tests/architecture/test_warning_policy.py` is untouched and green.

**Configuration (step 6).** `composition.py` + `SeedSettings` (pydantic-settings only, no password default, no `populate_by_name`, `SecretStr`, `.env` read from the working directory). Manual test of the maintainer, exact commands from the repo root with the `otcpy` stack up (the dev databases are already at head `0001`, verified):

```
uv run python -m otc_seed        # reads ./.env: POSTGRES_APP_USER/PASSWORD, POSTGRES_HOST_PORT, MONGO_INITDB_ROOT_USERNAME/PASSWORD, MONGO_HOST_PORT, POSTGRES_DB_*, MONGO_DB_READMODEL
# first run prints {"added": {...}, "totalAdded": 547}; the second prints 0. Exit 0.
# not yet migrated: uv run alembic -c services/<orders|fulfillment|billing>/alembic.ini upgrade head
```

### Ported-idiom ledger

| Idiom | #7 relied on | #8 supplied | #9 supplies | Guard |
|---|---|---|---|---|
| Deterministic id with the skipped hex index 12 | `deterministic.ts:22` `4${hex.slice(13, 16)}` | `DeterministicId.cs:39` `hex[13..16]` | `hashlib.sha256`, `digest[13:16]`, commented as load-bearing | `test_the_skipped_hex_character_is_load_bearing`, 8 literal vectors; armed |
| Genuine GLN/EAN check digits | `makeGln` via `GLN.computeCheckDigit` + `GLN.of` (`deterministic.ts:34-47`) | `Gs1Identifiers.cs:34` | shared kernel `GLN.compute_check_digit` + `GLN(...)` round trip | GLN/EAN literal vectors; armed twice |
| Money text (`161.30 EUR`, space grouping) | `money-text.ts:24` | `MoneyText.Format` | `format_money`, `divmod` (no `/`), exponent from SA-5 table; `10 ** exponent` avoided (the money guard flags a non-literal exponent) | `test_money_text.py`; oracle summaries |
| Timestamp truncation and `.mmmZ` | `toISOString()` (ms `Date`) | whole-second `DateTimeOffset` | explicit `format_instant`, whole-ms constants | `test_seed_instants.py` |
| Integer division | JS number | `long` | no `/` in the seed domain | AST money guard (population includes `otc_seed/domain`) |
| Reuse the service's schema | imports each app's Drizzle schema + migrator (`orders-db.writer.ts:13-21`) | `ProjectReference` Orders/Fulfillment/Billing (`Seed.csproj`) | **not available**: own Core tables | live-schema comparison (a); import-linter contracts untouched, `lint-imports` 10 kept |
| Upsert idempotence | `onDuplicateKeyUpdate` rewriting ONLY `updatedAt` (+ `publishedAt` on outbox, `valueDate` on payments, `description` on order items): `orders-db.writer.ts:61,79,97,115`, `billing-db.writer.ts:61,84,107,122,138,158`, `fulfillment-db.writer.ts:59,83,99,113,135`; Mongo `replaceOne` (`mongo.writer.ts:211`) | `EfUpsert.cs:25-35` re-applies EVERY column (`FulfillmentSeedWriter.cs:39-46` restocks units/reserved/threshold/updated_at of all 215 stock rows); Mongo `ReplaceOneAsync … IsUpsert` (`MongoSeedWriter.cs:162-165`) | insert-if-missing, `DO NOTHING`; Mongo `$setOnInsert` | xmin dump test; **deliberate divergence** (c); the live-state columns are reported separately by the parity tool (N4) |
| `json` payload text | mysql `json` (normalised, leaked onto #7's wire) | `JsonSerializer` + `JsonWire.Options` | `to_wire_json` into `json` (not `jsonb`) | stored text == contract wire form |
| Event loop affinity | n/a | n/a | engines/client built and closed in the one `asyncio.run` of the CLI (`SeedRuntime.aclose`); tests build per function loop | fixtures with loop scopes written beside them; no loop warning |
| Task cancellation | n/a | n/a | no tasks created; nothing fire-and-forget | n/a |
| `Any` leaking from an untyped library | n/a | n/a | PyMongo and asyncpg are typed; `AsyncMongoClient[dict[str, Any]]`; mypy `--strict` clean, no new override | `mypy` green |
| Counter seed: numeric MAX (backlog 211) | `cast(substring(<ref>, prefix.length + 1) as unsigned)`: `order-number-allocator.ts:67`, `invoice-number-allocator.ts:30`, `despatch-number-allocator.ts:28` | `CAST(SUBSTRING(<ref>, Prefix.Length + 1, LEN - Prefix.Length) AS int)`: `EfCoreOrderNumberAllocator.cs:138`, `EfCoreInvoiceNumberAllocator.cs:39`, `EfCoreDespatchNumberAllocator.cs:35` | `CAST(substring(<ref> FROM 5) AS bigint)` in each `sequences.py`; **deliberate divergence from #8: `bigint`, not `int`** (matches the `bigint` counter column; no overflow at 2^31) | `test_a_reference_above_six_digits_starts_the_counter_numerically` x3 (text MAX arm, offset arm `FROM 6`); `test_a_seeded_database_allocates_the_next_number` x3 armed with the sibling-column substitution in Round 4 |
| Counter seed: single statement under concurrency (#8 id 45) | #7: NOT atomic: a separate `SELECT max(...)` then `INSERT ... ON DUPLICATE KEY UPDATE next_value = next_value` on every call (`order-number-allocator.ts:63-78`; `invoice-number-allocator.ts:27-41`; `despatch-number-allocator.ts:25-39`); the idempotent upsert, not the select, is what tolerates the race | `INSERT ... SELECT 1, seed.next_value FROM (MAX derived table) WHERE NOT EXISTS (SELECT 1 FROM <seq> WITH (UPDLOCK, HOLDLOCK) WHERE id = 1)`: `EfCoreInvoiceNumberAllocator.cs:36-45`, `EfCoreDespatchNumberAllocator.cs:32-41`, `EfCoreOrderNumberAllocator.cs:135-144` (id 45 review: `order-to-cash-dotnet/progress/review_order_number_allocator_seed_race.md`) | one `INSERT ... SELECT ... WHERE NOT EXISTS (...) ON CONFLICT (id) DO NOTHING`; PostgreSQL has no `HOLDLOCK`, the unique key on `id` is the arbiter | `test_sixteen_concurrent_first_callers_get_distinct_contiguous_numbers` x3 + `test_sentinel_check_then_insert_seed_loses_the_race` x3 (harness sentinel; serialised-harness arm on orders and fulfillment) |
| Counter seed: steady-state no-scan (#8 id 47) | #7: **none owed**: the MAX select runs on every call (`order-number-allocator.ts:63-69`, no guard) | C#-side `if (!sequenceRowAlreadyExists)` skips the statement in orders (`EfCoreOrderNumberAllocator.cs:127-146`); the despatch and invoice allocators have NO such branch and run the statement every call (`EfCoreDespatchNumberAllocator.cs:30-42`, `EfCoreInvoiceNumberAllocator.cs`); whether SQL Server skips the derived-table scan was not probed here | no application branch: the MAX is a select-list subquery under `WHERE NOT EXISTS`, so PostgreSQL plans an InitPlan that is `never executed` when the counter row exists (measured on `postgres:18.6`, see the reviewer's round 3 plan lines) | `test_the_max_scan_never_runs_when_the_counter_row_exists` x3 (plan probe) with the `SCANS_EVERY_TIME` sentinel shape inside it; armed (MAX moved into `WHERE`) |

### #8's seed tests classified

Unit (`Seed.UnitTests`): `DeterministicParityTests` (id vectors, stability, dataset ids, EAN, GLN, wart, GLN validates) **ported** (`test_deterministic_parity.py`; the wart test reconstructs `...-4250-...`; the `The_Seeded_Datasets_Own_Ids...` test ported with the first saga's id). `DatasetTests` (3 currencies, 10+ products, 7 retailers, 20+ companies, retailer credit, baseline credit pairs, 5+1 sagas, `.99`, GLN valid and unique, non-saga stock coverage, saga stock rows, non-negative) **ported** (`test_dataset_counts.py`, strengthened from `>= 10`/`>= 20` to exact counts). `TimelineMoneyFormattingTests` (3) **ported** (`test_money_text.py`). `SeedDbConfigTests` (7) and `SeedMongoConfigTests` (3): **ported in kind** (`test_seed_settings.py`: defaults, every variable, no password, plus the leak test for bare names); the MS-SQL connection-string builders are n/a. Integration (`SeedIntegrationTests`): `Migrations_Apply_Against_Fresh_Databases` **n/a** (the templates are the migrations; covered by the schema comparison); `Row_Counts_Match...` **ported and strengthened** (every row, not counts); `Running_The_Seed_Twice_Is_A_No_Op` **ported and strengthened** (xmin dump, not a checksum); `Order_Timeline_Documents_Carry_Every_Field_With_The_Right_Types` **deliberately not ported** (a shape test: superseded by the value test, #8's D1); `..._Match_The_Values_Number7s_ToTimelineDocument_Produced` **ported** (every leaf with its exact type, from MongoDB); `TheRelayFindsNoUnpublishedRecord...` **ported as the relay's own query** (`published_at IS NULL` count, no relay exists yet in #9).

### Arming table (defeat list; verbatim first failing line, restored from `cp` backup and `cmp`-confirmed each time, `__pycache__` cleared, green re-run)

Rows of the defeat list that apply to the timeline guard: 1 (delete: blank causation), 2 (corrupt a supplied field: total, headerComplete, credit limit, stock unit, GLN digit), 3 (sibling identifiers: namespace, collection, causation edge), 7 (drop an optional element: a dedup key), reorder (events, outbox), 11 (the comparer inspects behaviour, the leaves, not syntax). Rows 4, 5, 6, 8, 12 apply to the write-path scan (sentinels for comment, dead region, strings) and not to the value guard (its expected side is a file, so 8 does not arise); 9 and 10 do not apply (no stale premise, no build output in the population).

| # | Mutation (file) | Test | Failure |
|---|---|---|---|
| 1 | blank every `causationId` (`domain/timeline.py`) | unit field-by-field | `AssertionError: ORD-000001 .events[0].causationId: seeded (<class 'str'>, ''), #7 produced (<class 'str'>, '0914f64b-f91e-4af3-927c-f9227fb92077')` |
| 1b | same, read back from MongoDB | `test_the_documents_read_back_from_mongodb_equal_number7s_value_for_value` | same message |
| 2 | one total +1 | unit; Mongo | `ORD-000001 .totals.totalAmount: seeded (<class 'int'>, 16131), #7 produced (<class 'int'>, 16130)` |
| 3 | drop one `processedEventKeys` entry | unit; Mongo | `ORD-000001 .processedEventKeys[8]: seeded None, #7 produced (<class 'str'>, 'projector:f6cf96e0-6291-427a-9cac-992fe7d1e245')` |
| 4 | `headerComplete` True to False | unit | `ORD-000001 .headerComplete: seeded (<class 'bool'>, False), #7 produced (<class 'bool'>, True)` |
| 5 | reorder events 3 and 4 | unit | `ORD-000001 .events[3].eventId: seeded (<class 'str'>, '8a0fd807-...'), #7 produced (<class 'str'>, '8611cdde-...')` |
| 6 | credit limit 500 000 to 500 001 | unit parity; real billing DB | `AssertionError: assert [{'id': '5c62...S', ...}, ...] == [...]`; `AssertionError: credits 5c62308c-31fd-47ab-aa6f-a27cc545a36e` |
| 7 | stock `INITIAL_UNITS_ON_HAND` 501 | real fulfillment DB | `AssertionError: stock 20046a96-6f69-4c40-8e47-06ecb9fa1b0a` |
| 8 | GLN digit corrupted | dataset parity | `InvalidGlnError: '5400000000219' is not a valid GLN: check digit must be 8 (GS1 mod-10 over the first twelve)` (the kernel round trip refuses at import); with the round trip removed too: 6 `FAILED` (`test_make_gln_matches...[1-...]`, `test_master_data_rows_equal_number7s`, ...) |
| 9 | wart "tidied" `digest[12:15]` | parity | `AssertionError: assert '8a2ac568-094...-38acbce9724c' == '8a2ac568-094...-38acbce9724c'` |
| 10 | sibling: retailer namespace `company:` | parity | `assert 'bbb86169-669...-9b4951badb12' == '0e47f181-c92...-5c8d497768b1'` |
| 11 | sibling: collection `order_timelines` | unit; Mongo | `assert 'order_timelines' == 'order_timeline'`; `assert 0 == 6 + where 0 = len([])` |
| 12 | sibling: `stock.reserved` cites `order.confirmed` | dataset parity | `AssertionError: assert [{'id': '9b47...532dd7', ...}] == [...]` |
| 13 | postgres: every row rewritten with identical content, report still says 0 | `..._twice_changes_nothing` | `assert {'otc_test_ba...), ...], ...}} == {...}  Differing items:` (the `xmin` dump; the report check was bypassed on purpose) |
| 14 | postgres: second run writes `created_at = now()`, report 0 | same | same |
| 15 | postgres: `DO UPDATE SET` every column (the #7 shape) | `..._does_not_reset_state_a_live_order_changed` | `assert 0 == 3` |
| 16 | mongo: run-dependent `$set` | `..._twice_changes_no_document` | `AssertionError: assert [{'_id': '174...: 'EUR', ...}] == [...]` |
| 17 | mongo: `$set` instead of `$setOnInsert` | `..._projector_already_advanced_is_left_alone` | `assert 98 == 5` |
| 18 | range check deleted | `test_the_one_insert_path_checks_the_range_before_any_statement_exists` | `AssertionError: a statement was built for a row that is out of range` |
| 19 | `orders.total_amount` declared `Integer` | `test_the_seed_definitions_equal_the_migrated_schema` | `Left contains one more item: "orders.total_amount: seed expects ('INTEGER', False, False), database has ('BIGINT', False, False)"` |
| 20 | schema verification skipped | `..._refuses_to_write_into_a_diverging_database...` | `Failed: DID NOT RAISE SchemaDriftError` |
| 21 | serializer: `json.dumps` instead of `to_wire_json` | payload test | `assert '{"orderRefer...mount":16130}' == '{"orderRefer...ount": 16130}'` |
| 22 | write before verifying every target | run_seed unit | `At index 1 diff: 'seed:a' != 'verify:b'` |
| 23 | a second write path planted (raw `text()` in a new module) | `test_the_population_of_write_paths_is_the_expected_literal` | `AssertionError: assert {'infrastruct...'pg_insert')}} == {'infrastruct...update_one')}}` |
| 24 | password default added | settings | `Regex pattern did not match. Expected regex: 'no PostgreSQL credential'` |
| 25 | `populate_by_name=True` restored | settings leak test | `AssertionError: assert 'the-superuser' not in 'postgresql+...2/otc_orders'` |
| 26 | a target dropped from the composition root | `test_the_composition_root_builds_exactly_the_four_targets_in_write_order` | `RuntimeError: seed wiring: expected targets ['orders', 'fulfillment', 'billing', 'mongo'], got ['orders', 'fulfillment', 'mongo']` |
| 27 | outbox written in reverse | every-row test | `assert ['bc313686-f5...45632b3', ...] == ['fa7c567d-04...bd4c2d9', ...]` |
| 28 | outbox `published_at` NULL | relay-query test | `assert 17 == 0` |
| 29 | Part C: CR range one short | tooling unit | `AssertionError: assert ['CR-000001',...-000006', ...] == [...]` |
| 30 | Part C: instants without ms | #9 half integration | `AssertionError: assert '2026-06-01T09:00:00Z' == '2026-06-01T09:00:00.000Z'` |
| 31 | Part C: an order id off by one hex digit | tooling unit | `AssertionError: assert ['1741d5aa-cf...75b63039eda2'] == [...]` |

Arms that first passed and what that taught: arms 16 and 17 initially "passed" because my arm script replaced the FIRST occurrence of the pattern, which was in `mongo.py`'s docstring, not the code (the script now replaces all and fails loudly if the file did not change); and a first version of arm 16 used a `$set` with a constant perturbation, which writes the same value on both runs (so a constant is not "a changed value"; the second version is run-dependent). Arm 13/14's first versions failed on a `NameError`/missing column, i.e. not on the intended break; rebuilt until the failure named the claim. Arm 25 first passed because my settings test did not set the field NAMES' environment twins (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `MONGO_*`), which is exactly what the compose `.env` contains and what `populate_by_name` would have read; the test now sets them (this is the backlog 204(e) class and the superuser credential would have leaked).

### Backlog 201 item (seeded vs live chain)

Stated where the seed is documented: the module docstring of `domain/data/sagas.py` ("SEEDED CHAIN VERSUS LIVE CHAIN (backlog 201)") and `services/seed/README.md` (created; none existed). The chain is #7/#8's, unchanged: `unit/test_dataset_parity.py::test_every_saga_fact_equals_number7s` compares every `causationId` of every outbox row and timeline entry with #7's, and `test_the_seeded_causal_chain_is_number7s_one_link_shorter...` states the shape (2 roots in a completed saga, 1 in the cancelled; every other `causationId` is the `eventId` of an earlier fact).

## Part C: parity tooling (not run against #8)

`scripts/seed_parity.py` (`dump9`, `dump8`, `diff`), documented in its docstring. The seeded subset is a **literal list** in the script: 6 order references and their 6 order ids; 3 currency, 12 product, 7 retailer, 22 company codes; `CR-000001..CR-000154`; 215 stock pairs as 11 saga pairs + 17 baseline companies x 12 products. Tables (18 + 1 collection): orders `{currencies, products, retailers, companies, orders, order_items, outbox}`, fulfillment `{stock, reservations, despatches, despatch_items, outbox}`, billing `{credits, credit_items, invoices, invoice_items, payments, outbox}`, Mongo `order_timeline` by `orderReference`. One SQL text per table runs unchanged on PostgreSQL and T-SQL (`SELECT cols FROM t WHERE key IN (...)`, joins for the item tables, outbox by `correlation_id IN` the six order ids). Rows are read client-side, one JSON object per line (sorted keys, compact, non-ASCII raw, UTF-8 file), lines sorted; normalised: uuid lower, instants `.mmmZ` (T-SQL `2026-06-01 09:00:00.000` and PG datetimes alike), money `int`, json payloads parsed, `outbox.seq` omitted. Never a server-side aggregate (a test bans `STRING_AGG`, `GROUP_CONCAT`, `HASHBYTES`, `CHECKSUM`, `COUNT(`). A dump **fails** on a missing literal key or a wrong row count. #8's MS-SQL is read through `docker exec otcnet-mssql sqlcmd ... -f 65001 -s <US>` (no ODBC driver added to the workspace), parsed strictly (a line with the wrong field count is an error).

Verification: the **#9 half end to end on the dev stack**: `uv run python scripts/seed_parity.py dump9 <dir>` printed the 19 files with the literal counts (stock 215, credits 154, outbox 17/12/21, timeline 6), a second dump diffed identical (`diff` exit 0, "N rows identical" per file). In the suite: `unit/test_seed_parity_tooling.py` (15 tests: literals checked against the seed's dataset, normalisers, canned sqlcmd text with `Aldi España`/NULL/blank lines, wrong-field-count error, `diff` sentinels for a changed, missing and duplicated row, a one-sided file and two empty directories, `check_subset` failures) and `integration/test_seed_parity_nine_half.py`. **Not verified**: the #8 half (`dump8`) and the final #8-vs-#9 diff; the sqlcmd flags are checked against nothing live.

To run it once authorised (from #8's compose and `.env`): `#8` needs **`mssql` on 1433** (`MSSQL_HOST_PORT`, free now: `ss -ltn` shows only 5432 and 27017 in use) and **`mongodb` on 27017** by default, which collides with `otcpy-mongodb`; start #8's two services only, with `MONGO_HOST_PORT=27018 docker compose -f ../order-to-cash-dotnet/docker-compose.infra.yml up -d mssql mongodb` (the compose reads `${MONGO_HOST_PORT:-27017}`; a shell variable beats `.env`), so **no `otcpy` container has to stop**. The volumes `otcnet_mssql_data` and `otcnet_mongodb_data` exist (verified with `docker volume ls`). Then `MSSQL_APP_PASSWORD=... EIGHT_MONGO_URI='mongodb://otc_mongo_root:...@localhost:27018/?authSource=admin' uv run python scripts/seed_parity.py dump8 out8`, `dump9 out9`, `diff out8 out9`. Expect the first diff to be about benign normalisation I could not test against #8 (the JSON in #8's Mongo may carry fields in another shape).

## Acceptance (feature_list.json id 12 and backlog 201's item)

1. Deterministic ids, skipped index 12 commented: met (`deterministic.py`, `test_deterministic_parity.py`).
2. Same currencies, products, retailers, companies, GLNs, credit limits, stock: met, every row of every table equals #7's executed output (`test_dataset_parity.py` and the real-database test).
3. Sample orders, cancelled order, timeline documents with `headerComplete`, `statusRank`, `processedEventKeys` values tested: met (`test_timeline_value_guard.py`, the Mongo read-back; arms 1 to 5).
4. Idempotent: met (xmin dumps, Mongo, live state preserved; dev stack second run `0`).
5. Parity against #8's live databases: **tooling built, #9 half verified, the live #8 run not authorised and not done.** Do not close this item until the run is made.
6. Backlog 201 item 3: met (above).

## Surprises and things not done

* `./init.sh` and `quality.sh` both green at the end; the dev stack is back to the same 12 containers, all healthy. **Side effect to know about:** my first `docker start` used `--filter status=exited` and also started the two one-shot init jobs `otcpy-kafka-init` and `otcpy-n8n-init`; they re-ran idempotently (`all 6 spec-derived Kafka topic(s) verified present`, `Successfully imported 4 workflows`) and exited 0; they are exited again.
* The seed writes **no counter rows** (neither did #7 or #8; #8's allocator seeds its counter from `MAX(order_reference)`). Phase 8's allocators in #9 (`SEED_ORDER_SEQUENCE ... VALUES (1, 1)`) would hand out `ORD-000001` against an already-seeded order. Proposed backlog entry (next id is **211**; highest present is 210): "orders/fulfillment/billing number allocators start above the seeded references (orders 7, despatch 6, invoice 6): test seeds first, then allocates and expects `ORD-000007`, `DES-000006`, `INV-000006`", attached to `orders_acceptance` (15) with `fulfillment_despatch` and `billing_*` owning their allocators.
* `OrdersDatabaseSettings` still has a password default and `populate_by_name=True` (backlog 204(d)/(e), untouched by design); the seed's own settings do not, and the leak test shows why it matters here (the compose `.env` carries the superuser as `POSTGRES_USER`/`POSTGRES_PASSWORD`).
* The test-matrix has no seed rows (no spec for `seed_job`, `sdd: false`); traceability is by each test file's docstring R-map to the acceptance item. `specs/shared/` untouched.
* The CLI prints a plain JSON report and error lines, not structlog: a one-shot job with no request context; if the maintainer wants structlog JSON with `correlationId` here, it is a small follow-up.
* Not done: shared seeded stack to bring the gate back under ~90 s (above), the #8 half of Part C, `progress/history.md` (the leader's).

## Round 2 (fix round after the round-1 rejection)

Start 2026-10-05 17:11 CEST, end 17:19 CEST. **Files of the seed's behaviour (`timeline.py`, `mongo.py`, `tables.py`, `payloads.py`, `postgres.py`) are unchanged: the reviewer's 17 arms stay valid.** (`postgres.py` was edited only inside two arms and restored with `cmp`; its docstring/code is byte-identical to round 1.) Docstring-only edits touched `domain/timeline.py`, `domain/data/sagas.py`, `domain/deterministic.py`, `domain/clock.py` (N2).

### B1: `dump8`'s sqlcmd invocation — fixed and probed against a throwaway SQL Server
The review's fix hint was incomplete: `-y 0` is ALSO mutually exclusive with `-h` ("The -h and the -y 0 options are mutually exclusive"), so `-h -1 -W` all had to go. Measured: with `-y 0 -s <US> -f 65001` and neither `-h` nor `-W`, sqlcmd prints NO header and NO padding (a `nvarchar(60)` comes back unpadded, an int unpadded, NULL as `NULL`, a zero-row select prints nothing, a 426-char `nvarchar(max)` comes back whole). The argv is now built by `sqlcmd_argv()` (documented in its docstring) and `parse_sqlcmd`'s docstring was corrected. Tooling is unchanged otherwise: no dependency added (`Packages installed:` none).

Probe: `docker run -d --name seedprobe-mssql -e ACCEPT_EULA=Y -p 127.0.0.1::1433 mcr.microsoft.com/mssql/server:2022-CU26-ubuntu-22.04` (Docker assigned 127.0.0.1:32768; no compose, no volume, #8's stack not started). Table `t(id int, payload nvarchar(max), name nvarchar(60), note nvarchar(60) NULL, at datetime2(3), amt bigint)` with a 426-char payload, `Aldi España`, a NULL, `2026-06-01 09:00:00.123`, and a second short row (probe script: the script's own `sqlcmd()` + `parse_sqlcmd()` + `render()` for #8; `render()` on the same Python values for #9):
```
payload length in printed text: 400 (k) ; whole payload chars: 426
#8: {"amt":-5,"at":"2026-06-01T09:00:00.000Z","id":22,"name":"B","note":"n","payload":{}} ...
#9: {"amt":-5,"at":"2026-06-01T09:00:00.000Z","id":22,"name":"B","note":"n","payload":{}} ...
equal: True
#8: {"amt":12345,"at":"2026-06-01T09:00:00.123Z","id":1,"name":"Aldi España","note":null,"payload":{"k": ... xxxx","n":"Aldi España"}}
#9: {"amt":12345,"at":"2026-06-01T09:00:00.123Z","id":1,"name":"Aldi España","note":null,"payload":{"k": ... xxxx","n":"Aldi España"}}
equal: True
ALL EQUAL: True
```
Arms (backup, break, run, `cp` back, `cmp`):
* A, round-1 flags restored (`-h -1 -W` + `-y 0`): `sqlcmd failed (1): Sqlcmd: The y and the W options are mutually exclusive.`
* B, `-h -1 -W` kept and `-y 0` dropped: `json.decoder.JSONDecodeError: Unterminated string starting at: line 1 column 6 (char 5)` (payload cut at 256).
* C, only `-y 0` dropped (no `-h`/`-W`): `ValueError: invalid literal for int() with base 10: 'id         '` (header and padding come back).
* Restored (`cmp` clean), probe green again (`ALL EQUAL: True`). Container removed (`docker rm -f seedprobe-mssql`; `docker ps -a | grep -c seedprobe` = 0).
Also pinned without a server: `test_the_sqlcmd_argv_never_pairs_dash_y_zero_with_dash_w_or_dash_h` (argv has `-y 0`, no `-W`, no `-h`, `-f 65001`). Limit stated plainly: a canned-text unit test cannot see sqlcmd's behaviour; the probe above is the proof and is not re-run by quality.sh (needs an MS-SQL image; not added to the gate).

### N4: live-mutable stock columns — done
`Spec.live_columns` (`STOCK_LIVE_COLUMNS = units, reserved_units, updated_at`). `fulfillment.stock.jsonl` now holds the seed-immutable columns (id, company/product codes, `low_stock_threshold`, `created_at`) and still fails the diff on any difference; `fulfillment.stock.live.jsonl` holds the identity plus the three live columns, and `diff_dirs` reports a difference there as `LIVE-STATE DIFFERENCE (informational)` without failing (a file missing on one side still fails). Both halves (`collect_nine`, `dump_eight`) use `render_files`, so the two sides cannot diverge. Dumps are now 20 files (the integration test's 19 became 20). Tests: `test_stock_live_columns_are_in_the_live_section_and_not_in_the_failing_file`, `test_a_live_stock_difference_is_reported_but_never_fails_and_an_immutable_one_does` (includes the immutable-fails arm), `test_the_live_file_missing_on_one_side_still_fails`. Arms: `STOCK_LIVE_COLUMNS = ()` -> 2 tests fail; `identical = False` for live diffs -> `test_a_live_stock_difference_is_reported_but_never_fails...` fails. Restored, `cmp` clean.

### N1: behaviour guard — done
`integration/test_seed_write_path_behaviour.py::test_every_row_the_engines_insert_passed_the_range_guard`: one real seed run; spy on `ensure_row_in_range` (patched in `postgres`), an engine-level `before_cursor_execute` listener counting rows sent in INSERT statements (whatever name built them), and the rows the databases gained; all three must be 541 and wire == spy. Arms (in `postgres.py`, backup `cmp`-restored): (a) guard loop `rows[:-1]` -> `AssertionError: the range guard saw 523 rows, not 541`; (b) guard loop deleted and `pg_insert` replaced by an aliased `insert as add_rows` -> `AssertionError: the range guard saw 0 rows, not 541` (the syntactic scan only noticed because `pg_insert` disappeared, not because it saw the alias). The AST scan stays as a population map, with its limit written in its docstring.

### N2, N3 — done
N2: four stale paths now `tests/unit/...`; `clock.py:34` now names `tests/unit/test_seed_instants.py` (which imports `contracts_format_instant` and pins the pair). `grep -rn "tests/test_" services/seed/src` = no hits. N3: ledger row "Upsert idempotence" and answer (c) corrected (#7 rewrites only `updated_at`/`published_at`/`value_date`/`description` and replaces the 6 timeline documents; #8 re-applies every column; `OrdersSeedWriter.cs:37`).

### Gate
`./quality.sh` with the 12 otcpy containers stopped: exit 0, `real 105.67 s` (pytest 904 passed in 82.07 s; round 1 was 899 tests at 100.16 s, so +5 tests). Containers restarted, 12 up, 0 unhealthy; `./init.sh` exit 0. `feature_list.json` line 216 (id 12) -> `in_review` (diff read; 211/212 untouched). Surprise: sqlcmd with `-y 0` and no `-h` prints no header at all (measured on 2022-CU26; if a later sqlcmd prints one, the first parsed row fails loudly on `int('id')`).

## Round 3 (maintainer rulings at the gate: live parity, backlog 211, backlog 212 seed half)

Start 2026-10-05 18:18 CEST, end 18:29 CEST.

### Part 1: live parity against #8 (acceptance 5) - MET, zero failing differences
`MONGO_HOST_PORT=27018 docker compose -f docker-compose.infra.yml up -d mssql mongodb` in #8: `docker ps -a` showed only `otcnet-mssql` and `otcnet-mongodb` (plus the `otcnet-net` network); `docker inspect` mounts `otcnet_mssql_data` and `otcnet_mongodb_data` (Mongo also has an anonymous `/data/configdb` volume of its image). Both healthy in 8 s. Credentials were exported from #8's `.env` into the shell only (no file of this repository holds them; `grep` of the password over `progress/evidence/seed_parity` = no hit). Read-only: SELECTs through `docker exec ... sqlcmd` and Mongo finds.

The question (does #8 hold the seeded subset?) is answered by `dump8` itself, which fails on a missing literal key or a wrong row count: it ran to completion with the literal counts (6 order references, 154 credits, 215 stock rows, 6 timeline documents). No seeding of #8.

Evidence in `progress/evidence/seed_parity/` (`out8/`, `out9/`, `diff.txt`). `diff` exit 0. Rows per file, identical on both sides: billing.credit_items 15, credits 154, invoice_items 10, invoices 5, outbox 21, payments 5; fulfillment.despatch_items 10, despatches 5, outbox 12, reservations 11, stock 215; mongo.order_timeline 6; orders.companies 22, currencies 3, order_items 11, orders 6, outbox 17, products 12, retailers 7 (19 files "identical"). The 20th, `fulfillment.stock.live.jsonl` (215 vs 215 rows), reports 4 hunks, all `units`/`reserved_units`/`updated_at` of #8's stock rows that live traffic changed (e.g. LONDONTOOLS PRD-0010 units 115 vs 500, `updated_at` 2026-09-18 vs 2026-01-01): LIVE-STATE DIFFERENCE, informational by design. **Failing differences: 0.** Nothing to compare with #7's oracle, because nothing failed; no #8 divergence found. #8's containers removed with `rm -sf mssql mongodb` (no `-v`): `docker ps -a | grep -c otcnet` = 0, both volumes still listed.

### Part 2: backlog 211 - counters start above the existing references
New statement (three `sequences.py`, in step; diff after masking names shows only pre-existing differences):
`INSERT INTO <seq> (id, next_value) SELECT 1, COALESCE((SELECT MAX(CAST(substring(<ref> FROM 5) AS bigint)) FROM <table>), 0) + 1 WHERE NOT EXISTS (SELECT 1 FROM <seq> WHERE id = 1) ON CONFLICT (id) DO NOTHING`. One atomic statement, numeric MAX, `ORD-`/`DES-`/`INV-` are 4 characters (suffix from position 5).

**The brief's premise for (b) is wrong in PostgreSQL 18.6, measured:** `SELECT MAX(...) FROM t WHERE NOT EXISTS (...)` ALSO leaves the scan "never executed" (a one-time filter in a `Result` node under the Aggregate), but still emits one row and attempts a conflicting insert (`Conflicting Tuples: 1`). The chosen select-list-subquery shape skips the scan and emits no row (`InitPlan ... Aggregate (never executed) / Seq Scan on orders (never executed)`, `Conflicting Tuples: 0`). Unconditional aggregate (no `WHERE NOT EXISTS`) scans 5000 rows every call: that is the sentinel shape, and the tests say so.

Tests (per service, in `test_<svc>_counter_seed.py`): `test_a_seeded_database_allocates_the_next_number` (c: references 1..6 / 1..5 / 1..5 inserted with raw SQL; allocations 7,8 / 6,7 / 6,7), `test_a_reference_above_six_digits_starts_the_counter_numerically` (d: `999999` + `1000000` -> 1000001), `test_the_max_scan_never_runs_when_the_counter_row_exists` (b: `EXPLAIN (ANALYZE)` plan lines naming the table; sentinel shape must scan, real statement with counter row must be "never executed", real statement without the row must scan), the existing 16-concurrent test and the one-round race sentinel (e). Cross-service (c): `tests/seed_counters/test_seeded_counters_start_above_references.py`, real `run_seed` on migrated templates then each service's own SEED/LOCK/ADVANCE; seeded MAX derived: 6 / 5 / 5 (from `sagas.py` docstring and read back from the database in the test, `max(suffixes) == seeded_max`); first allocation `ORD-000007`, `DES-000006`, `INV-000006`, the counter table asserted empty before.

Arms (backup, break, ONE run, `cp` back, `cmp` clean, no `.bak` left), verbatim:
* unseeded `VALUES (1, 1)`: `assert [1, 2] == [7, 8]` / `[1, 2] == [6, 7]` (all three); `assert 1 == 1000001`; cross-service `assert 1 == 7`, `assert 1 == 6`, `assert 1 == 6`. (The scan test fails there too, `no scan of orders in the plan: the probe cannot tell scanned from skipped`.)
* text MAX (`CAST(MAX(substring(...)) AS bigint)`): only `assert 1000000 == 1000001` in all three (the (d) test; the others rightly pass).
* aggregate that scans every time: `AssertionError: the steady-state path scans orders` (`despatches`, `invoices`), `assert not True`; all other tests pass.
* non-atomic (no `ON CONFLICT`), orders: `UniqueViolationError('duplicate key value violates unique constraint "pk_order_number_sequences"')`, 15 more items, the 16-concurrent test.
* (e) serialised harness (barrier of 1, sequential gather), orders: `AssertionError: the racy seed lost 0 of 16 callers, expected 15: the harness did not release the callers together, so it cannot prove the ON CONFLICT seed`. Other two files carry the identical harness and were not re-armed separately (stated).
Defeat-list rows that apply: 1 (delete behaviour), 2 (corrupt: text MAX), 3 (sibling: `DES-`/`INV-` tables run the same arms), 12 (a path the population never drives: the cross-service test drives the real seed), 8 (fixtures: references distinct, 999999 vs 1000000 are not substrings-ranked equal). Docstrings of the three `sequences.py` updated. 204(a) untouched.

### Part 3: backlog 212 seed half
`tests/fixtures/read_model_constants.json`: collection, `timelineOrderVersion` (2), the 9-entry status-rank table, `processedEventKeyPrefix` (`projector:`), `orderReferenceIndex` (name, key, unique, partialFilterExpression). Enumerated from `timeline.py` and `mongo.py`. `services/seed/tests/unit/test_read_model_constants.py` (6 tests) asserts the seed's constants and the keys it writes equal the file; `test_seed_mongo.py`'s index test now reads the expected options from the fixture. Seed values unchanged; `timeline.py` comment now names the fixture and feature 24's last acceptance item. Arms, verbatim: seed-only `TIMELINE_ORDER_VERSION = 3`: `assert 2 == 3` (2 tests); file-only `"completed": 97`: `assert 98 == 97`; seed-only `"paid": 8`: status-rank table test fails; file-only prefix `projectr:`: `assert 'projector:' == 'projectr:'`; seed-only consumer: `assert 'projectr:' == 'projector:'`; seed-only index name `uq_order_ref`: `assert 'uq_order_reference' == 'uq_order_ref'`. Restored, `cmp` clean.

### Gate
`./quality.sh` with the 12 otcpy containers stopped: exit 0, **real 108.86 s** (above the ~105 s re-baselined threshold by 3.9 s; pytest 922 passed in 86.67 s, round 2 was 904: +18 tests = 3x3 service tests + 3 cross-service + 6 constants; log `progress/evidence/quality_round3.log`). Containers restarted, 12 healthy; `./init.sh` exit 0. `feature_list.json` not edited by me (id 12 already `in_review`). The `otcnet-net` network created by compose remains (unused, empty).

## Round 4 (light: test fixtures and ledger rows)

Start 18:45:28 CEST, end 18:47 CEST, 2026-10-05, by `date`.

- **B1.** `_insert_reference` in `test_fulfillment_counter_seed.py` and `test_billing_counter_seed.py` now writes `order_reference = ORD-{int(suffix) + 5_000_000:07d}` (distinct from and larger than the DES/INV suffix, still unique). Sibling arm (`sequences.py` backed up, `substring(<despatch|invoice>_reference FROM 5)` changed to `substring(order_reference FROM 5)`, ONE file run, restored, `cmp` clean, `__pycache__` cleared):
  - fulfillment: `E  assert [5000006, 5000007] == [6, 7]` / `At index 0 diff: 5000006 != 6` (`1 failed, 2 passed`, `-x`)
  - billing: `E  assert [5000006, 5000007] == [6, 7]` / `At index 0 diff: 5000006 != 6` (`1 failed, 2 passed`, `-x`)
  Both `sequences.py` files are byte-identical to before.
- **`tests/seed_counters/`:** it has the same blindness: the seeded data pairs `DES-/INV-00000n` with `ORD-00000n` (n = 1..5), so a MAX over `order_reference` gives the same 5 and 6. The per-service tests now cover the sibling mutation (the arms above), so that file is left as the cross-service claim and not changed for this. Orders has no sibling column of the same shape, so no orders arm.
- **N2.** The literal-vs-literal `assert reference == f"...-{first:06d}"` is removed; the `number == first` assertion and the reference-absent count remain.
- **B2.** Three ledger rows added (numeric MAX; single-statement seed under concurrency; steady-state no-scan), each citation read from the #7 and #8 checkouts. Note: #7's seed is not atomic (select then `ON DUPLICATE KEY UPDATE` every call), and #8's despatch and invoice allocators have no C# steady-state branch; both are stated in the rows.
- Run: counter-seed x3 + `tests/seed_counters`: `18 passed in 16.81s`; `ruff format --check`, `ruff check`, `mypy --strict` on the 3 touched files clean.
