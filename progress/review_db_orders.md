# Review: feature 9 `db_orders` (phase 6), full process (persistence)

**Verdict: APPROVED** (round 1). All five acceptance items are met, and every guard was re-armed independently with mutations that differ from the implementer's. There are no blocking or major findings. Five minor findings, one advisory and three nits each carry a disposition below, and three backlog entries are proposed for the leader to file. I did not write them into `feature_list.json`.

Reviewer: Opus, 2026-10-05, 11:06 to 11:22 (from `date` at the first and last command).

## What I ran, and what I did not re-run

- **`./quality.sh` once, with the otcpy developer stack stopped** (one run, sequential, nothing else running against Docker).
  - Before the run: `docker stop` on the 12 running `otcpy-*` containers, then `docker ps --filter name=otcpy- -q | wc -l` = 0 and `ss -ltn` showed nothing on 5432, 9092, 4222 or 27017.
  - Result: exit 0 in 58 s. ruff format clean (150 files), ruff check clean, mypy strict clean (116 files), import-linter 10 kept / 0 broken, contracts drift clean, **606 passed**, total coverage 98.83 %, domain 100 % (267 statements, 54 branches), web gates green.
  - After the run: `docker start` on the same 12 containers, 12 healthy, `./init.sh` exit 0 (5d: shared spec byte-identical to #8 and #7 across 6 files).
- **`services/orders` alone,** twice: before the probes (28 passed, 14 s, stack up) and after every restore (28 passed).
- **The full suite was not run a second time.** The quality run above is the full-suite claim. Everything else was one named test per arm.
- **Unit-only run, with a control:**
  - `uv run pytest packages/shared_kernel services/orders/tests/unit` gave 300 passed, and `docker events --filter event=create` over that window showed **no container created**.
  - Control: one integration file created `testcontainers/ryuk:0.8.1` and `postgres:18.6`.
- **Composed postgres (acceptance 1, composed leg), re-proved by hand:**
  - Read-only first: `alembic_version` = `0001`, 12 tables, all owned by `otc_app`, 8 FKs.
  - Then `alembic downgrade base` on the empty `otc_orders`: the catalog held `alembic_version:r` and its pkey index only.
  - Then `alembic upgrade head`: 12 tables, `0001`. `alembic current` resolved the URL from `.env` through `OrdersDatabaseSettings` with no URL supplied.
- **Port ownership:** my own testcontainers probe printed `PortBindings: {'5432/tcp': [{'HostIp': '', 'HostPort': ''}]}`, so Docker assigns and holds the port (#8 id 85).

## CHECKPOINTS.md, boxes walked

**C1: the harness is complete**
- [x] Harness files exist.
- [x] `progress/current.md` and `progress/history.md` exist.
- [x] 7 agent definitions.
- [x] Models declared (init.sh).
- [x] `./init.sh` exits 0.

**C2: state is coherent**
- [x] No feature `in_progress`.
- [x] Every status is valid.
- [x] Done features have passing tests (606 passed).
- [x] `current.md` describes this session.
- [x] No `blocked` features.

**C3: architecture is respected**
- [x] `lint-imports` 10 kept: SQLAlchemy and asyncpg appear only under `otc_orders.infrastructure`.
- [x] No cross-service DB access: one database, FKs internal to `otc_orders`, no import of another service.
- [x] No new shared runtime package.
- [x] No domain imports `otc_cqrs` (unchanged; contract kept).
- [x] `shared_kernel` and `cqrs` still `dependencies = []` (untouched).
- [x] No domain money arithmetic touched.
- [x] No inter-service interaction added: N/A, nothing to classify.
- [x] No debug logging and no context-free TODO in the new files.

**C4: verification is real**
- [x] `./quality.sh` green, with the stack down.
- [x] Domain tests pure (no domain code changed).
- [x] testcontainers `postgres:18.6` from `testcontainers.community.postgres`, real engine, green with the developer infrastructure down.
- [x] Coverage gates met (98.83 % overall, 100 % domain).
- [x] No Jest, Karma or Jasmine.

**C5: the session closed cleanly**
- [x] No suspicious untracked files: `git status --porcelain --untracked-files=all` matches the start-of-review list exactly, and all `__pycache__` is git-ignored.
- [x] `history.md` entry with effort record (appended by me).
- [x] `feature_list.json` reflects the truth.
- [x] How-to-test is present (`impl_db_orders.md` "How to test by hand"); the leader relays it.
- [x] No commit: `.git/index` mtime is 10:07:33, before the session; reflog HEAD is the 10:07 commit; `git diff --cached` is empty.

**C6:** N/A (`sdd: false`).

**C7: second-reuse fidelity** (applicable boxes only)
- [x] `specs/shared/` byte-identical (init.sh 5d, `cmp` against both checkouts); `git diff --stat -- specs/` is empty.
- [x] No deviation needing an SA-n: `char(2)` → `varchar(2)` (finding F4) is a type translation the plan's delta table permits, not a spec change.
- [x] No `R<n>` is claimed. R62 stays TODO, correctly: only the storage leg is proven here.
- [x] Inherited #8 findings accounted for (below and in history).
- [x] Effort record complete, including what was not faster.
- n8n, the API script and the README benchmark: N/A at this phase.

## Acceptance item → test mapping I verified (by arming, not by reading)

Every arm used the same protocol:
1. `cp` a backup.
2. One mutation, asserted to replace exactly one occurrence.
3. Clear `__pycache__`, run ONE named test.
4. Restore from the backup and confirm with `cmp` (identical every time).
5. Clear `__pycache__` and `.mypy_cache`, re-run the same test green.

The helper and every backup are in the session scratchpad (`rev/arm.sh`).

| # | Item (unit) | Test | My mutation (different from the implementer's) | Verbatim failure |
|---|---|---|---|---|
| 1 | Lifecycle (history) | `test_upgrade_downgrade_reupgrade_lifecycle` | `downgrade()` stops dropping `saga_ignored_facts` | `Extra items in the left set: ('saga_ignored_facts', 'r')` |
| 2a | Types (every column) | `test_every_column_of_every_table_has_the_planned_type` | `order_items.discount` `BigInteger` → `Integer` in the migration | `order_items.discount: expected ('bigint', False, ''), live ('integer', False, '')` |
| 2b | Money population | `test_money_columns_are_bigint` | same | `{('order_items', 'discount'): 'integer'}` |
| 2c | Payload type | types test | `saga_commands.payload` → `JSONB` | `saga_commands.payload: expected ('json', False, ''), live ('jsonb', False, '')` |
| 2d | Identity | types test | `Identity(always=True)` removed from `outbox.seq` | `outbox.seq: expected ('bigint', False, 'identity:ALWAYS'), live ('bigint', False, '')` |
| 3 | `request_id` (rows) | `test_r62_*` | not re-armed: the implementer's three arms are fine, and the index-set test covers the partial/NNDISTINCT shapes | n/a |
| 4a | FK set | `test_the_foreign_key_set_is_exactly_the_eight_planned` | substitute: `order_items.product_id` → `orders.id` | `Extra items in the left set: ('order_items', ('product_id',), 'orders', ('id',), 'a')` / right: `... 'products' ...` |
| 4b | Index set | `test_the_index_set_is_exactly_the_planned_one` | substitute a sibling column: `ix_saga_commands_status_next_attempt_at` on `(status, created_at)` | `('saga_commands', 'ix_saga_commands_status_next_attempt_at', False, ('status', 'created_at'), None)` extra |
| 4c | Counter seed (callers) | `test_sixteen_concurrent_first_callers_get_distinct_contiguous_numbers` | `SEED_ORDER_SEQUENCE` replaced by #8's `IF NOT EXISTS … INSERT`, run 3 times | 3 of 3 failed: `Left contains 15 more items, first extra item: UniqueViolationError('duplicate key value violates unique constraint "pk_order_number_sequences"')` |
| 4d | Row lock | same | `FOR UPDATE` removed | `assert [1, 2, 2, 2, 2, 2, ...] == [1, 2, 3, 4, 5, 6, ...]` |
| 4e | Sentinel | `test_sentinel_check_then_insert_seed_loses_the_race` | unmodified, run 3 times with `-s` | `racy seed lost the race in 10 of 10 rounds` ×3 (30 of 30) |
| 5a | Quantity, specific code | `test_quantity_max_round_trips_and_max_plus_one_is_a_domain_error` | substitute: `SPECIFIC_ERRORS` keyed on `order_items.discount` | `assert <class '...IntegerOutOfRangeError'> is QuantityOutOfRangeError` |
| 5b | Guard population and bound | `test_every_integer_column_of_the_live_database_is_guarded` | off-by-one: `high + 1` accepted | `Left contains 12 more items, first extra item: 'currencies.decimal_points'` |
| 6a | JSON bytes, column | `test_saga_command_payload_is_read_back_byte_identical` | column `JSONB` | `At index 8 diff: b' ' != b'1'` |
| 6b | JSON bytes, write path (corrupt) | `test_outbox_payload_is_read_back_byte_identical` | model `Outbox.payload` typed as SQLAlchemy `JSON()` instead of `RawJson` | `assert b'"{\\"orderR...unt\\":8934}"' == b'{"orderRefe...Amount":8934}'`, i.e. the text was re-encoded as a JSON string |
| 7 | Timestamp read-back | `test_instants_come_back_aware_utc_and_rounded_to_the_millisecond` | `outbox.occurred_at` as `timestamp(3)` without time zone | `assert None is not None` (tzinfo) |

## Answers to the leader's questions, each from a command

**1. Write-boundary range guard**

- **Population.** The guard's population is *derived* by walking `Base.registry.mappers` and taking each column whose type class is exactly `SmallInteger`, `Integer` or `BigInteger`. Probe output: `GUARDED: [...] 12`.
  - The test's population is a *literal* of 12 `(table, column, data_type)` triples, compared for equality with the live `information_schema.columns` (integer, bigint, smallint). Each column is then probed at the live width's max (accepted) and max + 1 (refused).
  - The two populations agree. A model/migration width mismatch is caught in both directions: by this test (the max is refused, or max + 1 is accepted) and by the drift test (my control: `quantity` as `BigInteger` in the migration gave `modify_type`).
- **Write paths.** Results from my probe script against a real `postgres:18.6`, writing `quantity = 2**31` each time:

  | Path | Result |
  |---|---|
  | constructor kwargs + flush | **DOMAIN** `QuantityOutOfRangeError` |
  | attribute assignment on a loaded row + flush | **DOMAIN** |
  | `session.merge(transient)` | **DOMAIN** (merge copies through `set`) |
  | `session.execute(insert(OrderItem).values(...))` | DRIVER `DBAPIError ... value out of int32 range` |
  | `session.execute(insert(OrderItem), [dicts])` (ORM bulk INSERT) | DRIVER |
  | `session.execute(update(OrderItem).where(...).values(...))` | DRIVER |
  | `session.execute(update(OrderItem), [dicts])` (bulk by PK) | DRIVER |
  | legacy `bulk_insert_mappings` | DRIVER |
  | `text("UPDATE ...")` | DRIVER |

- **Is the declared residual the complete list?** Not as worded. See F1.
- **Is acceptance 5 met?** Yes, for the ORM unit-of-work paths: constructor, assignment and merge. Every ORM-enabled DML statement and every raw SQL statement surfaces the driver error.
- **An over-reach of my own finding.** The guard also refuses a valid write: `sc.attempts = SagaCommand.attempts + 1` raises `IntegerOutOfRangeError: <BinaryExpression ...> does not fit saga_commands.attempts`. See F2.

**2. Root `conftest.py`**

- **Unit-only run:** no container is created. The command and its control are above.
- **Loop scopes:**
  - `postgres_server` is a sync session fixture (no loop), documented in the module docstring.
  - `fresh_database` and `engine` have their loop scope in a comment beside them.
  - `migrated_db` and `parents` carry an explicit `loop_scope="function"` with no comment beside them. That is acceptable: the scope is written at the decorator.
- **Disposal:**
  - The `engine` fixture is disposed in its own function scope.
  - `env.py` disposes its engine inside the worker thread's `asyncio.run`.
  - Each raw asyncpg connection is closed in a `finally`.
- **Port:** held by Docker (`HostPort: ''`).
- **Stack down:** passes; re-proved once by me, above.

**3. Types test**

- The expected map is a literal, read live from `information_schema.columns` joined to `pg_attribute`/`format_type`. It never reads SQLAlchemy metadata (`grep` for `Base`/`metadata` in `test_orders_schema_types.py`: none).
- It is closed in both directions: the table set must be equal, and so must the column set of each table.
- It includes identity (`identity:ALWAYS`), `timestamp(3) with time zone` precision, nullability and defaults.
- My re-arms: 2a to 2d above.

**4. FK and index closure**

- Both are exact-set equalities, with the missing/extra diagnostic built before the count.
- My own substitutions: 4a and 4b.
- **Blind spots found (F3):**
  - `postgresql_using="hash"` on `ix_orders_company_id`: the index test stays **green**.
  - `onupdate="CASCADE", deferrable=True, initially="DEFERRED"` on `fk_orders_company_id_companies`: the FK test stays **green**.

**5. #8 id 45 counter test**

- The concurrency is genuine: 16 separate asyncpg connections opened first, then an `asyncio.Barrier(16)`, then 16 server-side transactions.
- The sentinel reproduced 10 of 10 rounds, three times (30 of 30).
- The main test with the racy seed failed 3 of 3, and with the lock removed failed once.

**6. JSON bytes guard**

- It uses `otc_contracts.to_wire_json` over the golden `order.placed.v1` payload with non-ASCII text.
- It compares `.encode("utf-8")` bytes, both through the ORM (`RawJson` casts to text) and through `payload::text`.
- Armed with `jsonb` (6a), and with a corrupted write path (6b).

**7. `test_orders_models_match_migration`**

- It runs Alembic's `compare_metadata` (with `compare_type=True`) between the model metadata and the live database the migration built. It is a drift detector.
- It **can** be green while the live schema is wrong:
  - when models and migration agree on a wrong schema;
  - when the difference is in timestamp precision. My probe: `order_date` as `timestamptz` without `(3)` in the migration only stays **green**.
- It does catch a `jsonb` payload (`modify_type ... JSONB`) and an integer width change.
- Its docstring says it is not the proof; the live-catalog tests are. See F8.

**8. Scope and git**

- All changes are inside the brief's bounds:
  - root `pyproject.toml`: an `integration` marker and `conftest.py` added to mypy `files`;
  - `services/orders/**` and `uv.lock`;
  - the root `conftest.py`, which addendum 1 requested.
- No `specs/shared/` edit, no repository, relay or allocator, no dead-letter columns.
- No git index or working-tree write: the index mtime and reflog predate the session, and the cached diff is empty.
- My own arms wrote only to files I restored with `cmp`. The final `git status` equals the initial one.

## Ported-idiom ledger: claims checked

- Every row's "#9 supplies" half is executed by the named test. I probed:
  - counter seed and lock (4c to 4e);
  - money width (2a, 2b);
  - JSON text (6a, 6b);
  - identity (2d);
  - FK set (4a);
  - timestamps (7).
- **Row most likely to be assumed: "#9 supplies `json` + `RawJson` passthrough".**
  - The claim is that SQLAlchemy's asyncpg dialect `json.loads` on read and passes text on write. The ledger does not state the write half.
  - My 6b probe proves the write half matters: the stock `JSON` type re-encodes the string.
  - The guard catches it.
- **Missing ledger line:** `country`. #7 is `char(2)` (`0000_bizarre_champions.sql:33,48`), #8 is `nvarchar(2)` (`InitialCreate.cs:130,182`), #9 is `varchar(2)`, and the ledger does not mention it. See F4.

## Findings and dispositions

Severity counts: **0 blocking, 0 major, 5 minor, 1 advisory, 3 nits.**

**F1. MINOR. The range-guard residual is under-stated.**
- **Where:** `services/orders/src/otc_orders/infrastructure/persistence/range_guards.py:9-13`, and `impl_db_orders.md` residual 1.
- **The over-claim:** the docstring says attribute assignment is "the only way Phase 8's repositories write rows through the mapped classes", and names the bypass as "Core `insert()`/`update()` or raw SQL".
- **What the probe shows:** five ORM-enabled paths taking the mapped class reach the engine unguarded and surface `DBAPIError`:
  - `session.execute(insert(Model).values(...))`;
  - `session.execute(insert(Model), [dicts])`, SQLAlchemy 2's recommended bulk insert;
  - `update(Model)` with `.where().values()`;
  - `update(Model)` bulk-by-PK;
  - `bulk_insert_mappings`.
- **The feature's own counter writer is one of them:** `sequences.py` `ADVANCE_ORDER_SEQUENCE` is raw SQL. So "`order_number_sequences.next_value` is guarded" holds only for a writer that does not exist.
- **A stale name:** the docstring cites `test_every_integer_column_is_guarded`, which does not exist; the test is `test_every_integer_column_of_the_live_database_is_guarded`.
- **Why it matters:** the residual pin (`test_residual_a_core_insert_bypasses_the_guard_and_only_the_engine_refuses`) and the proposed review check both describe the bypass as "Core". A Phase 8 author using `session.execute(insert(OrderItem), rows)` would reasonably believe they are on the guarded ORM path.
- **Disposition:** ACCEPTED, NOT FIXED in this feature (the acceptance criterion is met on the ORM unit-of-work path). Routed as proposed backlog **id 204**.

**F2. MINOR. The guard refuses a valid SQL-expression assignment.**
- **Where:** `range_guards.py:65` (`ensure_in_range`: `type(value) is not int` → refuse) via `_check` at `:99-100`.
- **Evidence:** `sc.attempts = SagaCommand.attempts + 1` raises `IntegerOutOfRangeError: <sqlalchemy.sql.elements.BinaryExpression object at 0x...> does not fit saga_commands.attempts`.
- **Why it matters:** this is SQLAlchemy's documented idiom for an atomic server-side increment, and the natural shape for the saga sweeper's `attempts`. The message is false: the value is not out of range, it is not a value at all.
- **Disposition:** fix with the first writer of `attempts` (pass a `ClauseElement` through, with a unit test). Routed in proposed backlog **id 204**.

**F3. MINOR. The closed-set tuples omit attributes a substitution can change.**
- **Where:** `test_orders_foreign_keys_and_indexes.py`.
  - `FK_QUERY` (`:33-47`) reads `confdeltype` but not `confupdtype`, `condeferrable`/`condeferred` or `confmatchtype`.
  - `INDEX_QUERY` (`:109-119`) does not read the access method (`pg_am.amname`).
- **Evidence:** both mutations stayed green (Q4 above).
- **Why it matters:** defeat-list row 7 (drop or alter an optional element). The FK/index instrument will be copied by features 10 and 11, so the gap would triple.
- **Disposition:** fix when the instrument is ported. Routed as proposed backlog **id 206**, attached to feature 10, which back-ports the widened tuple to this file in the same change. Re-open trigger meanwhile: any orders migration that uses `postgresql_using`, `onupdate`, `deferrable` or `match`.

**F4. MINOR. `retailers.country` and `companies.country` are `varchar(2)`; Databases.EN.md §4.1 says `char(2)`.**
- **Where:** migration `0001_initial_orders_schema.py:83`; locked in by `test_orders_schema_types.py:58,70`.
- **Context:** the deviation is not disclosed. #8 shipped `nvarchar(2)`, so #9 matches #8, not #7 or the document. #8's own review (D2) treated an undisclosed type deviation locked in by a test as blocking.
- **Why it is minor here:**
  - The plan's delta maps text to `varchar(n)`.
  - For exactly-two-letter ISO 3166 codes the two types store the same value, and `char` would add blank-padding semantics.
  - The table is not copied by features 10 and 11.
- **Disposition:** ACCEPTED, NOT FIXED. The leader adds one ledger line to `impl_db_orders.md`: *"#7 relied on `char(2)` (0000_bizarre_champions.sql:33,48); #8 supplied `nvarchar(2)` (InitialCreate.cs:130,182); #9 supplies `varchar(2)`, guarded by the types test"*. Re-open if a parity test against #7's DDL types, or the seed job, needs blank-padded semantics.

**F5. MINOR. #8 review D6 recurred: a credential default in source.**
- **Where:** `services/orders/src/otc_orders/infrastructure/settings.py:20`: `password: str = Field(default="otc_app_dev_password", ...)`. The same value is in `.env.example:34`.
- **Why it matters:** unlike #8's design-time factory, this is the runtime settings class. A service started without `POSTGRES_APP_PASSWORD` would silently use the dev password instead of failing at boot, which is what `CLAUDE.md` asks the composition root to do for a missing binding.
- **Disposition:** fix when the composition root first reads these settings (no default; boot fails if unset). Routed in proposed backlog **id 204**, attached to feature 15.

**F6. ADVISORY. Millisecond rounding in the engine versus truncation on the wire.**
- **Evidence:** `timestamptz(3)` rounds (`.123987` → `.124`, measured by the implementer and asserted), while `otc_contracts.wire.format_instant` truncates (`.123`).
- **Why it matters:** an instant held in memory and the same instant read back from the database serialise differently for sub-millisecond input. If the outbox envelope is ever built from the in-memory domain instant while a later reader uses the stored `occurred_at`, the two disagree by 1 ms.
- **Owner:** none today. `grep` on `feature_list.json` for millisecond/truncat finds nothing.
- **Disposition:** proposed backlog **id 205**, attached to feature 14 `outbox_and_idempotency`.

**F7. NIT.** `test_orders_foreign_keys_and_indexes.py:122` carries `# type: ignore[type-arg]`.
- The report says "mypy strict stays on, no ignores". The ignore is avoidable with `set[tuple[object, ...]]`.
- **Disposition:** fix in the same change as F3 (id 206).

**F8. NIT.** `test_autogenerate_finds_no_difference_between_models_and_migrated_schema` is blind to timestamp precision and to errors shared by model and migration.
- Its docstring disclaims being the proof, and the types test covers precision (implementer's arm 2c).
- **Disposition:** ACCEPTED, NOT FIXED. Re-open trigger: if anyone cites it as schema proof.

**F9. NIT.** `test_the_guard_does_not_touch_other_types` (`tests/unit/test_orders_range_guards.py`) asserts only that `None` passes; the name over-claims.
- **Disposition:** ACCEPTED, NOT FIXED (cosmetic).

**Observation, not a defect.** The guard is installed as an import-time side effect of `models.py:221`.
- `CLAUDE.md`'s "no import-time decorators" rule binds handler registration, not mapper events.
- Import-time installation is what makes the guard impossible to forget, so I accept it.
- If features 10 and 11 copy `range_guards.py` (implementer residual 2), the leader should decide on promotion to `shared_kernel` before feature 11, as the implementer proposed.

## Proposed backlog entries (for the leader to file; I did not edit `feature_list.json` beyond the status line)

**204 `orders_write_boundary_residuals`, attached to feature 15 `orders_acceptance`** (feature 16 inherits the `attempts` item). Acceptance:
- (a) Every write into a guarded integer column either goes through the ORM unit of work or calls `ensure_in_range` before execution. The population comes from `grep -n "insert(\|update(\|text(\|bulk_" services/orders/src`, with one classification per hit.
- (b) The `range_guards.py` docstring and the residual pin name the ORM-enabled DML paths (bulk insert, `update(Model)`, `bulk_*_mappings`), not "Core", and cite the real test name.
- (c) A `ClauseElement` assigned to a guarded attribute passes through, with a unit test (F2).
- (d) `OrdersDatabaseSettings.password` has no default, and boot fails when it is unset (F5).

**205 `instant_millisecond_agreement`, attached to feature 14 `outbox_and_idempotency`.**
- Instants are truncated to whole milliseconds before they are persisted or enveloped.
- A test writes a `.123987` instant through the outbox path and asserts that the envelope's `occurredAt` and the stored `occurred_at` agree (F6).

**206 `schema_instrument_widening`, attached to feature 10 `db_fulfillment`.**
- The FK closed-set tuple gains `confupdtype`, `condeferrable` and `condeferred`; the index tuple gains `pg_am.amname`.
- The change is applied to `otc_orders`' test in the same change, with the `type: ignore` removed (F3, F7).
- Each widening is armed with the mutation above (hash index; `ON UPDATE CASCADE DEFERRABLE`).

## What must change before re-review

Nothing: APPROVED. The leader files 204 to 206 and adds the F4 ledger line.

## #8 inherited findings

- **#8 id 44 (money column width): AVOIDED.** All 6 money columns are `bigint` from the first migration. Re-armed on a different column (`order_items.discount`) in both tests.
- **#8 id 45 (counter seed race): AVOIDED.** The fix is `ON CONFLICT DO NOTHING`, and the racy shape is reproducibly visible to the harness (30 of 30 sentinel rounds; 3 of 3 armed main-test runs).
- **#8 db_orders review D1 (7 of 8 FKs undeclared with a green suite): AVOIDED.** The FK set is closed from `pg_constraint`; I re-armed it by substitution.
- **#8 db_orders review D2 (sequence counter widened, undisclosed): AVOIDED.** `next_value integer`, per §4.2. **The undisclosed-deviation class recurred in a smaller form** (F4, `country`).
- **#8 db_orders review D4 (no closure on columns): AVOIDED.**
- **#8 db_orders review D6 (credential default in source): RECURRED** (F5).
- **#8 id 85 (self-assigned ports): AVOIDED.**
- **#8 id 104 (suite hid behind a developer service): AVOIDED.** I re-proved it with the stack stopped.
- **#8 db_fulfillment and db_billing advisories:** A1 (no timestamp read-back), A2 (count before diagnostic) and A3 (index presence-only) all **AVOIDED**.
