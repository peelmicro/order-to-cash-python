# Review: feature 10 `db_fulfillment` (phase 6), full process (persistence)

**Verdict: APPROVED** (round 1). All three acceptance items, backlog 206 and 204(b)(c) are met. I re-armed every guard with mutations different from the implementer's, and probed the instruments for what they cannot see. There are no blocking or major findings. Two minor findings (one is a hole that the 204(c) pass-through opened), two advisories and seven nits each carry a disposition. Two backlog entries (207, 208) and one extension of 204 are proposed for the leader to file. I did not write them into `feature_list.json`.

Reviewer: Opus, 2026-10-05, 11:40 to 11:57 (from `date` at the first and last command).

## What I ran, and what I did not re-run

- **`./quality.sh` once, with the otcpy stack stopped.** One sequential run, nothing else running against Docker.
  - Before: `docker stop` on the 12 running `otcpy-*` containers. `docker ps --filter name=otcpy- -q | wc -l` = 0, and `ss -ltn` showed nothing on 5432, 9092, 4222 or 27017.
  - Result: exit 0, **69.5 s wall-clock**. ruff format clean (173 files), ruff check clean, mypy strict clean (136 source files), import-linter **10 kept / 0 broken**, **655 passed in 41.70 s**, total coverage 98.99 %, domain 100 % (267 statements, 54 branches), web gates green.
  - Containers started during the run (`docker events --since/--until` over the run window, `event=start`): **1 × `postgres:18.6`**, 1 × `testcontainers/ryuk:0.8.1`. The shared container holds.
  - After: `docker start` on the same 12 containers. 12 healthy, and `./init.sh` exits 0 (5d: shared spec byte-identical to #8 and #7, 6 files each).
- **Targeted run before probing.** `services/fulfillment`, the parity guard, orders' unit tests and orders' two changed integration files: 64 passed. Fulfillment plus parity collects 46 tests, matching the report.
- **The full suite was not run a second time.** The quality run is the full-suite claim. Every arm ran ONE named test (the parity arms ran its 3-test file).
- **Composed `otcpy-postgres`/`otc_fulfillment`, re-proved through the Alembic CLI** (URL resolved by `FulfillmentDatabaseSettings` from `.env`):
  - row count over the 7 tables was 0 before I touched it;
  - `downgrade base` (exit 0) left exactly `alembic_version:r alembic_version_pkc:i`, with 0 rows in `alembic_version`;
  - `upgrade head` (exit 0) restored 8 tables, 18 + 1 indexes and `outbox_seq_seq`; `version_num` = `0001`; every relation is owned by `otc_app`.
  - **Left at head.**

## CHECKPOINTS.md, boxes walked

**C1: the harness is complete**
- [x] Harness files, `progress/current.md`/`history.md`, 7 agents with models: `./init.sh` exit 0 checks all of these.

**C2: state is coherent**
- [x] No feature `in_progress`. Counter before my edit: 38 pending, 10 done, 1 in_review.
- [x] Every status is in `rules.valid_status`.
- [x] Done features have passing tests (655 passed).
- [x] `current.md` describes this session (feature 10, in_review, the 11:41 reviewer launch).
- [x] No `blocked` features.

**C3: architecture is respected**
- [x] `lint-imports` 10 kept. SQLAlchemy, asyncpg, alembic and pydantic-settings are imported only under `otc_fulfillment.infrastructure` and `alembic/`.
- [x] No cross-service DB access, and no service imports another. `grep -rn "otc_orders\|import otc_billing" services/fulfillment` gives 3 hits, all prose:
  - the migration docstring at `:7`;
  - a test comment at `test_fulfillment_schema_types.py:106`;
  - the `models.py` docstring at `:10`.

  The independence contract is kept.
- [x] No new shared runtime package. The guard is copied, per the leader's ruling, and a parity guard replaces the sharing.
- [x] No domain imports `otc_cqrs`. No domain code changed.
- [x] `shared_kernel` and `cqrs` are untouched.
- [x] No domain money arithmetic was touched, and fulfillment has no money columns.
- [x] No inter-service interaction added: N/A.
- [x] No debug logging and no context-free TODO: `grep -rnE "TODO|FIXME|XXX|print\(|breakpoint\(" services/fulfillment/src services/fulfillment/alembic tests/architecture/test_range_guard_parity.py` exits 1 with no hits. The sentinel's `print` is in a test and is intentional, as in orders.

**C4: verification is real**
- [x] `./quality.sh` green with the stack down.
- [x] Domain tests pure (no domain code).
- [x] testcontainers `postgres:18.6` from `testcontainers.community.postgres`, real engine, green with the developer infrastructure down. The port is Docker-held (root `conftest.py`, unchanged).
- [x] Coverage 98.99 % overall, 100 % domain.
- [x] No Jest, Karma or Jasmine.

**C5: the session closed cleanly**
- [x] No suspicious untracked files. `git status --porcelain` at the end equals the start-of-session snapshot entry for entry, my temporary billing probe directory is removed (`ls services/billing/src/otc_billing/infrastructure` → `__init__.py`), and the implementer's `test_tmp_old_tuple.py` is gone.
- [x] `history.md` entry with effort record (appended by me).
- [x] `feature_list.json`: id 10 → `done` (one line).
- [x] How-to-test is present (`impl_db_fulfillment.md` "How to test by hand").
- [x] No commit. `.git/index` mtime is 10:07:33, reflog HEAD is the 10:07 commit, and `git diff --cached` is empty.

**C6:** N/A (`sdd: false`).

**C7: second-reuse fidelity** (applicable boxes)
- [x] `specs/shared/` byte-identical (init.sh 5d), and `git diff --stat -- specs/` is empty.
- [x] No deviation needs an SA-n. Every type change is the plan's delta table.
- [x] No `R<n>` is claimed.
- [x] Inherited #8 findings are accounted for (below and in history).
- [x] Effort record complete.
- n8n, the API script and the README benchmark: N/A at this phase.

## The leader's questions, each answered from a command

### 1. Guard copies

- **Byte-identical?** Yes. `cmp` exits 0 for `range_guards.py` and for `types.py`, and the md5 is `8349af19…` for both guard copies and `04cbfe29…` for both `types.py`.
- **Population of members.** `MEMBERS = ("orders", "fulfillment")`, a closed literal. The file runs 3 tests: `range_guards.py` and `types.py` against the reference, plus a census.
- **My parity arms** (each different from the implementer's operator, `cache_ok` and comment edits):

  | Arm | Mutation | Result |
  |---|---|---|
  | a13 | `INT64_MAX = 2**63` in fulfillment's copy | `drifted from services/orders's copy` / `'-INT64_MAX = 2**63 - 1'`, 1 failed |
  | P2 | fulfillment's `types.py` deleted | `FileNotFoundError: ... persistence/types.py`, 1 failed. A missing copy fails; it is not skipped. |
  | P3 | an unlisted billing copy at `services/billing/.../infrastructure/persistence/range_guards.py` | `copies found ['billing', 'fulfillment', 'orders'], listed ['fulfillment', 'orders']`, 1 failed |
  | P1 | fulfillment's copy converted to CRLF (`cmp` then differs) | **3 passed.** The guard is line-equal, not byte-equal. See N5. |
  | P4 | a billing copy at `infrastructure/range_guards.py` (a sibling path) | **3 passed.** The census glob reaches one path only. See N5. |

- **Vacuity.** Not possible on an empty glob: `MEMBERS` is a literal, and the census asserts `found == set(MEMBERS)`, so a glob matching nothing fails. A one-member tuple would leave the parametrised test with no cases, but the census would still fail on the extra copy.
- **Quantity map passed at both install sites.**
  - Fulfillment: `models.py:151-158`, 5 columns.
  - Orders: `models.py:224-228`, `{("order_items", "quantity")}`.
  - The live catalog of the composed `otc_fulfillment` (my `information_schema` dump) holds exactly 8 integer columns: `stock.units/reserved_units/low_stock_threshold`, `reservations.units`, `despatch_items.units`, `despatch_number_sequences.id/next_value` and `outbox.seq`. That is the map's 5 quantities plus 3 counters. The population test reads the same set live, and my a11 arm proves it is live-derived (below).
- **Before/after of orders' `range_guards.py`.** The before is feature 9's reviewer backup `rev/backup.a15_off_by_one`; `cmp` shows it is identical to the feature 9 implementer's `.bak`. The diff touches four things, at exactly the line numbers feature 9's review quoted:
  - the docstring `:1` and `:10-13` (now `:10-28`);
  - the `ClauseElement` import;
  - the `SPECIFIC_ERRORS` constant, which moved to a parameter;
  - `_check` at `:99` (now `:116-118`).

  Orders' `models.py` changes only at the install call (`:221` → `:224-228`). Orders' `sequences.py` and `0001_initial_orders_schema.py` are `cmp`-identical to feature 9's backups. **The claim that orders was edited only for 204(b)(c) and the 206 back-port holds**: the other files modified after 11:24 are the three orders test files those items name.

### 2. 204(b)(c)

- **(b)** The docstring (`range_guards.py:10-19`, both copies) names `insert(Model).values`, `insert(Model), [dicts]`, `update(Model)` (`.where().values()` and bulk-by-PK), `bulk_insert_mappings`/`bulk_update_mappings` and raw `text()`. It cites the real test names, and "Core" now appears only in the sentence "not Core only".
- **My 10-path probe in fulfillment** (testcontainer `postgres:18.6`, value `2**31`, `probe_paths.py`):
  - **DOMAIN** `quantity.out_of_range`: constructor, attribute assignment, `session.merge`.
  - **DRIVER** `DBAPIError ... value out of int32 range`: `insert(Model).values`, `insert(Model), [dicts]`, `update(Model).where().values`, `update(Model), [dicts]` bulk-by-PK, `bulk_insert_mappings`, `bulk_update_mappings`, `text()`.
  - The docstring is accurate. The pin covers 4 of those 7 bypasses (N6).
- **(c)** A `ClauseElement` passes through (`range_guards.py:118`). The unit test exists in both services. **My arm a14** used a sibling-type substitution in orders' copy, `type(value).__name__ != "BinaryExpression"`, and it failed: `IntegerOutOfRangeError: <sqlalchemy.sql.elements.ColumnClause ...; attempts + 1> does not fit saga_commands.attempts`.
- **Did the pass-through open a hole? Yes, of one kind (F1).**
  - **Overflow: no hole.** `literal(2**31)`, `bindparam('x', 2**31)`, `cast(2**31, BigInteger)`, `type_coerce(2**31, Integer)` and `Stock.units + 2**31` all pass the guard, and the engine refuses each with a driver error. That is the documented residual: a driver error instead of a domain refusal.
  - **Type: a silent hole.** `literal(3.7)` was **accepted and stored as 4**. `Stock.units * 0.5` stored **0**, and `Stock.units + 0.6` stored **1**. The guard refuses a raw `3.7` ("bool and non-int values are refused too", `:74`), but the same value wrapped in an expression is silently rounded by PostgreSQL's numeric-to-integer assignment cast. The docstring says only that "an overflow there is the engine's refusal".
  - `literal('42')` and `literal(True)` are refused by the engine (ProgrammingError).

### 3. Backlog 206

- **The widened tuples are present in both services.**
  - FK: `confdeltype`, `confupdtype`, `condeferrable`, `condeferred` and `confmatchtype`, at `test_fulfillment_foreign_keys_and_indexes.py:111-112` and `test_orders_foreign_keys_and_indexes.py:44-45`.
  - Index: `am.amname`, at `:184` and `:142`.
  - `grep -rn "type: ignore"` over the orders file and `services/fulfillment` exits 1 (F7 is closed).
- **My arms in the orders back-port**, different from the implementer's `ON UPDATE CASCADE DEFERRABLE` and hash:

  | Arm | Mutation | Failure |
  |---|---|---|
  | o1 | `deferrable=True, initially="DEFERRED"` on `fk_order_items_order_id_orders` | `extra: [('order_items', ('order_id',), 'orders', ('id',), 'c', 'a', True, True, 's')]` |
  | o2 | `match="FULL"` on `fk_orders_company_id_companies` (only `confmatchtype` can see it) | `extra: [(... 'a', 'a', False, False, 'f')]` |
  | o3 | `postgresql_using="brin"` on `ix_orders_company_id` | `extra: [('orders', 'ix_orders_company_id', False, ('company_id',), None, 'brin')]` |

- **The green-before half.** The implementer's `arms_o206.out` shows the unwidened projection passing on both mutations; feature 9's review had already measured that blind spot.

### 4. Schema against Databases.EN.md §5, §4.3 and the plan's delta table (live catalog)

- **Columns.** From the composed `otc_fulfillment`, my `information_schema` + `format_type` dump: 52 columns over 7 tables plus `alembic_version`. Every name, order, length and nullability matches §5 and §4.3 under the delta:
  - ids are `uuid`;
  - instants are `timestamp(3) with time zone`, including `despatch_date`;
  - `outbox.published_at` and `trace_parent` are the only nullable columns;
  - `outbox.seq` is `bigint GENERATED ALWAYS`;
  - `payload` is `json`.

  Widths: `stock` 20/30; `reservations` 20/20/30/20, `status` 20; `despatches` 20 ×4; `despatch_items` 30; `outbox` 60/64; `processed_events` 50. These are #7's widths (`0000_nappy_mad_thinker.sql:1-73`).
- **Indexes.** 18, excluding `alembic_version_pkc`, read with `pg_get_indexdef`. They are §5's and §4.3's own, the two PK-less FK-supporting indexes, and the PKs. Column order is correct in every composite.
- **FKs.** 2: `reservations.stock_id → stock` (a, a, not deferrable, s) and `despatch_items.despatch_id → despatches` ON DELETE CASCADE.
- **Enums:** 0.
- **Disclosure.**
  - Disclosed: `uuid`, `timestamptz(3)`, identity, `retailer_code` width, NO ACTION, the 2 extra indexes, `causation_id`/`trace_parent`.
  - Not disclosed: two smaller items (N2) — §5 types `company_code`, `retailer_code` and `product_code` in `reservations` as bare "varchar", and only `retailer_code` is named; `despatch_number_sequences` is untyped in §5, and #7 used `id tinyint` (`0002_...sql:15`).
  - The F4 class recurred, smaller still.
- **Reliability-table parity with `otc_orders`, live, both composed databases.** A 6-query dump compared:
  - columns, with ordinal, `format_type`, nullability, every identity attribute, default, collation, storage and compression;
  - indexes, with uniqueness, primary-ness, NULLS NOT DISTINCT, ordered columns, `indnkeyatts`, `indoption`, `indclass` opclasses, predicate, access method and full `pg_get_indexdef`;
  - every constraint by name and definition;
  - the identity sequence's type, start, increment, min, max, cache and cycle;
  - the table owner and options;
  - the trigger count.

  **48 lines each, and `diff` is empty.** The instrument has a sentinel: `varying(50)`→`(51)` in one dump makes `diff -q` exit 1. My first attempt produced two empty files (heredoc without `docker exec -i`), which would have "matched". The sentinel and the 48-line count are what make this result real. Feature 11 will find nothing between these two.

### 5. Round trips

- `test_every_column_of_the_table_round_trips[<table>]` covers all 7 tables.
- `test_the_literal_rows_cover_every_mapped_table_and_use_distinct_values` closes the literal against the mapped tables and columns.
- Every column is asserted twice: via an independent asyncpg `SELECT *` (payload as `::text`), and via the ORM. Timestamps are included: 14 distinct whole-ms instants, one written at +02:00, all asserted `utcoffset() == 0` on the ORM read.
- Distinct values: ints and uuids are distinct by literal; strings and instants are asserted distinct per row.
- **My arm a1:** `Reservation.company_code`/`retailer_code` mapped onto each other's columns (a swap that the ORM read alone cannot see, because model and read agree). It failed on the independent read: `{'company_code': 'RET-R'} != {'company_code': 'CO-R'}`, `{'retailer_code': 'CO-R'} != {'retailer_code': 'RET-R'}`.

### 6. The implementer's three decisions: rulings

- **`low_stock_threshold` as a quantity: UPHELD.**
  - §5: "Replenishment trigger level", `int`, beside `units`/`reserved_units`.
  - #8 compares it in units: `EfCoreStockReadRepository.cs:66`, `s.Units - s.ReservedUnits < s.LowStockThreshold`.
  - #7 types it like the unit columns: `stock.schema.ts:28` `int(...)`.
  - The population test asserts the code per column, so a reclassification fails.
- **`reservations.stock_id` NO ACTION: UPHELD.**
  - #7: `ON DELETE no action` (`0000_nappy_mad_thinker.sql:75`).
  - #8: declares `ReferentialAction.Restrict` in EF (`InitialCreate.cs:145`), but its **live** catalog reads `NO_ACTION` (`../order-to-cash-dotnet/progress/review_db_fulfillment.md:99`; SQL Server has no RESTRICT).
  - So all three engines hold NO ACTION. My arm a2 (`ondelete="RESTRICT"`) fails the FK test with `'r'`, so the choice is pinned. The ledger's "#8 supplied Restrict" is half the story (N1).
- **The extra `confmatchtype`: UPHELD.** It strictly widens the tuple, feature 9's F3 named it, and it is the only member that sees `MATCH FULL`, as my arms a3 and o2 prove.

### 7. Counter seed

- **The concurrency is genuine.** 16 asyncpg connections are opened first, then released by `asyncio.Barrier(16)`, each running its own transaction. The harness is identical to orders' apart from names (`diff` after renaming: the docstring header only).
- **My arm c1:** the seed changed to the valid-looking sibling `ON CONFLICT (id) DO UPDATE SET next_value = 1`. It failed: `assert [1, 1, 1, 1, 1, 1, ...] == [1, 2, 3, 4, 5, 6, ...]`.
- **Sentinel:** run unmodified 3 times, it printed `racy seed lost the race in 10 of 10 rounds` each time (30 of 30).

### 8. The implementer's finding: orders' `populate_by_name=True`. CONFIRMED, and wider than reported

The probe ran from a directory without `.env`, with the `POSTGRES_*` variables unset:
- `OrdersDatabaseSettings().user` gave `juanpabloperez`, and `url` was `postgresql+asyncpg://juanpabloperez:***@localhost:5432/otc_orders`. The `USER=otc_app` control gave `otc_app`.
- With `USER=intruder HOST=evil.example PASSWORD=from-bare-PASSWORD`, orders resolved `intruder evil.example from-bare-PASSWORD`. **Bare `PASSWORD` leaks too.**
- Precedence: when the alias is set (`POSTGRES_APP_USER=otc_app`), the alias wins, but `HOST=evil` still became the host. **The repository's own `.env` defines no `POSTGRES_HOST`** (`grep -n "^POSTGRES_" .env`), so an exported `$HOST` reaches orders' URL even in the developer setup.
- Fulfillment's class, with the same environment, resolved `otc_app localhost`. Its absence of `populate_by_name` is correct.

See A1.

### 9. Wall-clock

- My run: **69.5 s** wall-clock, pytest 41.70 s. The implementer measured 61.0 s / 40.7 s, and feature 9 measured 45.8 s.
- One `postgres:18.6` container per run (docker events), so the shared container holds.
- The growth is the per-test `alembic upgrade head` into a fresh database: every integration test pays a migration. The pytest share grew about 1 s between our runs; the rest of the variance is outside pytest (web build, box load). See A2.

## Acceptance → test mapping I verified (by arming)

Protocol for every arm (`rev10/arm.py`):
1. `cp -p` a backup.
2. ONE exact replacement (asserted count = 1).
3. Clear `__pycache__` and `.mypy_cache`, then run ONE named test.
4. Restore from the backup and `filecmp` (identical every time).
5. Clear caches, then re-run green (every re-run exited 0).

| # | Item (unit) | Test | My mutation | Verbatim failure |
|---|---|---|---|---|
| 1 | migrations from empty (history) | `test_upgrade_downgrade_reupgrade_lifecycle` | `"outbox"` removed from `downgrade()`'s tuple | `Extra items in the left set: ('outbox_seq_seq', 'S') ('outbox', 'r')` |
| 2 | round trip (each table) | `test_every_column_of_the_table_round_trips[reservations]` | `company_code`↔`retailer_code` column mapping swapped | `{'company_code': 'RET-R'} != {'company_code': 'CO-R'}` |
| 3a | FK set (2) | `test_the_foreign_key_set_is_exactly_the_two_planned` | `ondelete="RESTRICT"` on reservations | `extra: [('reservations', ('stock_id',), 'stock', ('id',), 'r', 'a', False, False, 's')]` |
| 3b | FK set | same | `match="FULL"` on reservations | `extra: [(... 'a', 'a', False, False, 'f')]` |
| 4a | types (every column) | `test_every_column_of_every_table_has_the_planned_type` | `published_at` NOT NULL | `outbox.published_at: expected ('timestamp(3) with time zone', True, ''), live (..., False, '')` |
| 4b | identity | same | `Identity(always=False)` | `outbox.seq: expected ('bigint', False, 'identity:ALWAYS'), live ('bigint', False, 'identity:BY DEFAULT')` |
| 4c | payload type | `test_payload_columns_are_json_not_jsonb` | `payload` as `Text` | `assert {} == {('outbox', 'payload'): 'json'}` |
| 5a | index set (18) | `test_the_index_set_is_exactly_the_planned_one` | partial predicate `units > 0` on `ix_despatch_items_despatch_id` | `extra: [(... ('despatch_id',), '(units > 0)', 'btree')]` |
| 5b | index set | same | `INCLUDE (units)` on `ix_reservations_stock_id` | `extra: [(... ('stock_id', 'units'), None, 'btree')]` (caught, but as a key column: N/F2) |
| 5c | index set, blind-spot probe | same | `stock_id DESC` | **1 passed: not seen** (F2) |
| 6 | JSON bytes (write half) | `test_outbox_payload_is_read_back_byte_identical` | model `payload` as SQLAlchemy `JSON()` | `assert b'"{\\"orderR...' == b'{"orderRefe...'` / `At index 0 diff: b'"' != b'{'` |
| 7a | range guard population (live-derived) | `test_every_integer_column_of_the_live_database_is_guarded` | an unmodelled `despatches.line_count integer` in the migration only | `missing set(), extra {('despatches', 'line_count', 'integer')}` |
| 7b | parity guard | `test_range_guard_parity.py` | a13, P2, P3 above | as quoted in Q1 |
| 7c | 204(c) | orders `test_a_sql_expression_..._passes_through` | a14 above | as quoted in Q2 |
| 8 | counter + sentinel | `test_sixteen_concurrent_first_callers_...` / sentinel | c1 above; sentinel 3 × unmodified | as quoted in Q7 |
| 206 | widening, back-port | orders FK and index tests | o1, o2, o3 | as quoted in Q3 |

### Defeat-list rows (on the guards above)

| # | Row | Result |
|---|---|---|
| 1 | delete | a10 (downgrade), P2 (copy deleted): caught |
| 2 | corrupt a field | a1, a7, a8, c1: caught |
| 3 | substitute a sibling | a2 (RESTRICT), a14 (`BinaryExpression` for `ClauseElement`), o3 (brin): caught |
| 4, 5, 6 | comment, dead region, raw string | schema guards read the live catalog, so N/A. The parity guard compares every line, comments and strings included (the implementer armed a comment) |
| 7 | drop or alter an optional element | a3/o2 (match), a4 (predicate), a5b (INCLUDE): caught. **a5 (DESC) not caught: F2** |
| 8 | literal vs literal | one instance: `assert MONEY_COLUMNS == []` (N3). Every other expected set meets a live read |
| 9 | closer half / stale premise | the 206 pair (green on narrow, red on wide) |
| 10 | caches | cleared after every restore |
| 11 | form the instrument does not recognise | the parity guard does not see CRLF (P1), and the census does not see a copy at another path (P4): N5. The guard does not see a float-typed expression: F1 |
| 12 | failure through an undriven path | 7 ORM-enabled/raw paths probed, all reach the driver, documented; 4 are pinned (N6) |

## Ported-idiom ledger: claims checked

- Every "#9 supplies" cell is executed by its named test (arms above).
- **The row most likely to be assumed was "Reliability tables: same columns, indexes and names as orders".** I checked it from the two live catalogs (Q4): identical over 48 catalog facts, including identity-sequence parameters and opclasses.
- **The row that is half right is "#8 supplied `ReferentialAction.Restrict`".** That is true at the EF level only, and #8's live catalog says NO_ACTION (N1).
- **Missing lines (N2):** the widths of `reservations.company_code`/`product_code`, and the type of `despatch_number_sequences.id` (#7 `tinyint`).

## Findings and dispositions

Severity counts: **0 blocking, 0 major, 2 minor, 2 advisory, 7 nits.**

**F1. MINOR. The 204(c) pass-through admits non-integer expressions, and PostgreSQL rounds them silently.**
- **Where:** `range_guards.py:116-119` (both copies) and the docstring at `:21-24`.
- **Evidence** (my probe, live `postgres:18.6`):
  - `stock.units = literal(3.7)` → accepted, stored **4**;
  - `Stock.units * 0.5` → stored **0**;
  - `Stock.units + 0.6` → stored **1**;
  - the control: a raw `3.7` → `QuantityOutOfRangeError`.
- **Why it matters:**
  - The guard's own contract refuses non-int values (`:74`), and the docstring's residual covers only overflow. This class is corruption, not refusal.
  - A float-factor expression such as a percentage of `units` is a plausible Phase 9 replenishment write.
  - Overflow stays refused (by the engine), so nothing silently overflows.
- **Disposition:** ACCEPTED, NOT FIXED here, because no writer exists and 204(c) mandated the pass-through. Proposed backlog **207**, attached to **feature 17 `fulfillment_stock`**, the first writer of `stock.units`. Orders' `attempts` writer inherits it through 204's feature 16 note.
  - Pass a `ClauseElement` through only when its SQL type is in the `Integer` family (refuse `Numeric`/`Float`/`NullType`), or name the residual in the docstring and pin it.
  - Unit test: `Stock.units * 0.5` refused, armed by reverting.
  - Applied to every copy; the parity guard enforces that.
- **Re-open trigger:** any assignment of a non-literal expression to a guarded attribute before 207 closes.

**F2. MINOR. The widened index tuple is still blind to sort order, and conflates `INCLUDE` with key columns.**
- **Where:** `INDEX_QUERY` in both FK/index tests: there is no `indoption` and no `indnkeyatts`.
- **Evidence:**
  - a5: `stock_id DESC` stays **green**;
  - a5b: `INCLUDE (units)` is reported as key columns `('stock_id', 'units')`, the same tuple a composite key index would produce.
- **Why it matters:** defeat-list row 7, the same class as feature 9's F3, one attribute further. Feature 11 copies the instrument a third time. My parity dump already reads both attributes, so the fix is two columns.
- **Disposition:** proposed backlog **208**, attached to **feature 11 `db_billing`**. The tuple gains `indoption` and `indnkeyatts` (key vs INCLUDE), in billing's test and back-ported to orders' and fulfillment's, armed by a DESC index and by an INCLUDE-versus-composite pair that fails before and passes after.
- **Re-open trigger meanwhile:** any migration using `DESC`, `NULLS FIRST/LAST`, `postgresql_include` or an opclass.

**A1. ADVISORY (orders, outside this feature's bounds). `populate_by_name=True` leaks the bare `USER`, `HOST`, `PORT` and `PASSWORD` into `OrdersDatabaseSettings`.**
- **Where:** `services/orders/src/otc_orders/infrastructure/settings.py:14`. Measured in Q8. `HOST` leaks even with the repository `.env`, which defines no `POSTGRES_HOST`.
- **Disposition:** extend **204** with an item (e) — `populate_by_name` removed, and a test that sets `USER`, `HOST`, `PORT` and `PASSWORD` and asserts that none reach the URL (fulfillment's `test_the_password_from_the_environment_builds_the_asyncpg_url` is the model) — attached as 204 already is, to feature 15. The leader edits 204. **Feature 11's brief should say: copy fulfillment's settings class, not orders'.**

**A2. ADVISORY. `quality.sh` wall-clock: 45.8 s (feature 9), then 61.0 s (implementer), then 69.5 s (mine).**
- One container per run, so #8's per-suite-container cost is avoided. The remaining cost is one `alembic upgrade head` per integration test.
- #8's review projected a 3-minute gate. If feature 11 pushes past ~90 s, migrate once per session into a template database and `CREATE DATABASE … TEMPLATE` per test. That costs milliseconds and keeps isolation.
- **Disposition:** no entry. A note for the feature 11 brief, with re-open trigger "`quality.sh` > 90 s".

**N1. NIT. Ledger row "`reservations.stock_id` on delete".** "#8 supplied `ReferentialAction.Restrict` (`InitialCreate.cs:145`)" should add "live catalog NO_ACTION (`../order-to-cash-dotnet/progress/review_db_fulfillment.md:99`)". **Disposition:** the leader amends the ledger line in `impl_db_fulfillment.md`.

**N2. NIT. Two deviations from §5 / #7 are not on the ledger.**
- `reservations.company_code` `varchar(20)` and `product_code` `varchar(30)`: §5 says bare "varchar", and only `retailer_code` is disclosed.
- `despatch_number_sequences.id` is `integer`: §5 gives no type; #7 has `tinyint` (`0002_...sql:15`) and #8 `int`.

Both match #8, so they carry no risk. **Disposition:** ACCEPTED, NOT FIXED. The leader adds the two ledger lines (F4's class, recurring smaller).

**N3. NIT. `test_fulfillment_has_no_money_columns_and_one_bigint` asserts `MONEY_COLUMNS == []`, a literal against a literal** (defeat row 8). The bigint population beside it is the real, live assertion, but the implementer's row-8 claim is overstated by this line. **Disposition:** ACCEPTED, NOT FIXED (cosmetic).

**N4. NIT. `test_the_password_from_the_environment_builds_the_asyncpg_url` depends on the shell environment.** With `POSTGRES_HOST_PORT=5433` exported it fails (`- alhost:5432/otc_fulfillment`). The fixture clears only the two credential variables. **Disposition:** fold into 208: feature 11 copies this test, and its fixture should clear every alias variable.

**N5. NIT. The parity guard is line-equal, not byte-identical, and its census has one path.**
- A CRLF copy passes (P1).
- A copy at `infrastructure/range_guards.py` escapes the census (P4).
- `types.py` copies are not censused.

**Disposition:** ACCEPTED, NOT FIXED. Re-open trigger: feature 11 places billing's copy anywhere but `infrastructure/persistence/`.

**N6. NIT. The residual pin covers 4 of the 6 ORM-enabled paths its docstring names.** `update(Model), [dicts]` bulk-by-PK and `bulk_update_mappings` are named but not pinned; my probe confirms both bypass. **Disposition:** ACCEPTED, NOT FIXED. 204(a)'s per-hit classification at the first writer covers them.

**N7. NIT. The report says "9 import-linter contracts KEPT"; the run says `Contracts: 10 kept, 0 broken`.** **Disposition:** the leader corrects the figure in the history entry (I used 10).

## Proposed backlog entries and edits (for the leader; I edited only id 10's status)

- **207 `range_guard_expression_types`**, attached to feature 17 `fulfillment_stock`: F1.
- **208 `schema_instrument_widening_2`**, attached to feature 11 `db_billing`:
  - (a) the index tuple gains `indoption` and `indnkeyatts` in all three databases' tests, armed with DESC and an INCLUDE/composite pair (F2);
  - (b) the settings-test fixture clears every alias variable (N4).
- **204:** append item (e) (A1). Record in its note that (b) and (c) were closed by feature 10 in both copies (verified here), leaving (a), (d) and (e) for feature 15.
- **206:** set `done`. Every acceptance item is verified in Q3: the tuples in both services, each widening armed by the implementer and by me, and the `type: ignore` removed.
- **Ledger edits:** N1 and N2, in `impl_db_fulfillment.md`.

## What must change before re-review

Nothing: APPROVED.

## #8 inherited findings and advisories

- **#8 db_fulfillment A1 (no timestamp read-back): AVOIDED.** 14 instants are asserted on two independent reads, one written at +02:00, plus the rounding test.
- **A2 (count before diagnostic): AVOIDED.** `assert live == EXPECTED, diagnostic` comes before the count in both closed sets.
- **A3 (index checks presence-only): AVOIDED.** A closed set of 18, with the access method.
- **A4 (stale `current.md`): AVOIDED.** It names this feature and this review.
- **#8 id 44 (money width):** not applicable. The live catalog holds no money column, and the only bigint is `outbox.seq`.
- **#8 id 45 (counter seed race): AVOIDED.** Sentinel 30 of 30, and a sibling seed caught (c1).
- **#8 db_orders D1 (FKs undeclared, green suite): AVOIDED.** Closed set, armed by RESTRICT and by MATCH FULL.
- **#8 db_orders D2 (undisclosed type deviation): recurred, smaller** (N2).
- **#8 db_orders D6 (credential default): AVOIDED in fulfillment** (no default, armed by the implementer). It is still open in orders under 204(d), and widened by A1.
- **#8 ids 85 and 104:** AVOIDED. The port is Docker-held, and the run is green with the stack stopped.
- **#8 db_fulfillment timing risk (one container per suite): AVOIDED.** One container in a full run (docker events).
