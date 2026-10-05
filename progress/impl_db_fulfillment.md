# Implementation report: feature 10 `db_fulfillment` (phase 6), full process

Status set to `in_review` (one line, `git diff feature_list.json` read: it shows `in_review` for id 10; the other hunks in that diff are the leader's uncommitted edits). `./quality.sh` green with the `otcpy` stack **stopped** (12 containers `docker stop`ped, nothing on 5432/9092): **655 passed, 40.7 s pytest, 61.0 s wall clock for the whole script** (feature 9 measured 45.8 s / 606 tests; +49 tests, and the four integration files' Alembic runs account for the rest; the box was also busier), total coverage 98.99 %, domain 100 %, 9 import-linter contracts KEPT. Stack restarted (`docker start`), all 12 containers healthy, `./init.sh` exits 0.

## Files

| File | Purpose |
|---|---|
| `services/fulfillment/pyproject.toml`, `uv.lock` | the four runtime deps (bare names, pins in the lock) |
| `services/fulfillment/alembic.ini`, `alembic/{env.py,script.py.mako}` | async Alembic, own `alembic_version`; URL from `config.attributes["url"]` or `FulfillmentDatabaseSettings` |
| `services/fulfillment/alembic/versions/0001_initial_fulfillment_schema.py` | hand-written: 7 tables, 2 FKs, 18 indexes, every name explicit |
| `.../otc_fulfillment/infrastructure/settings.py` | `FulfillmentDatabaseSettings`, no password default |
| `.../infrastructure/persistence/{__init__,models,range_guards,sequences,types}.py` | models (7 classes), copied guard and `RawJson`, counter SQL |
| `services/fulfillment/tests/integration/{conftest,test_fulfillment_*}.py` (7 test files), `tests/unit/test_fulfillment_range_guards.py`, `tests/unit/test_fulfillment_database_settings.py` | the tests (43) |
| `tests/architecture/test_range_guard_parity.py` | parity guard over the copies (3 tests) |
| `services/orders/.../persistence/range_guards.py`, `models.py` | 204(b)(c) fix; `install_range_guards` now takes the quantity map as a parameter |
| `services/orders/tests/unit/test_orders_range_guards.py`, `tests/integration/test_orders_quantity_range.py`, `test_orders_foreign_keys_and_indexes.py` | 204(c) unit test; residual pin widened and renamed; 206 back-port, `# type: ignore[type-arg]` removed |
| `progress/impl_db_fulfillment.md`, `feature_list.json` (id 10 only) | this report; status |

Root `conftest.py` and the `integration` marker are reused unchanged: no second container. `specs/shared/test-matrix.md`: no row changed (no R row is provable by a schema feature alone, same as feature 9).

## Packages installed (for the commit's `Packages installed:`)

`uv add --package otc-fulfillment "sqlalchemy[asyncio]" asyncpg alembic pydantic-settings`, then pins stripped to bare names like orders. Lock resolved the same versions as feature 9: **sqlalchemy 2.1.3** (`[asyncio]` extra, **greenlet 3.5.6**), **asyncpg 0.31.0**, **alembic 1.20.0** (+ **mako 1.4.3**), **pydantic-settings 2.15.0**. `uv.lock` +120 lines, all of them these packages. npm: none. Nothing added to `shared_kernel`/`cqrs`.

## Decisions

* **The guard is copied, and the copy is byte-identical.** To make the copy a parity-checkable file with an empty exception list, the service-specific part (which columns carry the quantity code) is no longer inside `range_guards.py`: `install_range_guards(mappers, specific_errors)` takes it, and each service's `models.py` passes it. Orders' `SPECIFIC_ERRORS` constant (used only by its own module) moved into its `models.py` as the argument. `cmp` of the two files: identical; `types.py` (`RawJson`) is also covered by the parity guard.
* **`stock.low_stock_threshold` is a quantity** (code `quantity.out_of_range`). Reason: it is a unit level that the replenishment rule compares with `units` and `reserved_units`, so it overflows like units do; Databases.EN.md §5 types all three the same. The five unit-count columns (`stock.units/reserved_units/low_stock_threshold`, `reservations.units`, `despatch_items.units`) carry the quantity code; `despatch_number_sequences.id/next_value` and `outbox.seq` are counters and carry the generic `storage.integer_out_of_range` (the population test asserts the code per column, so a mis-classification fails).
* **Integer population of `otc_fulfillment` is 8** (read live, closed literal): 5 quantities, 2 counter columns, `outbox.seq`.
* **FK widening also adds `confmatchtype`** (review F3 listed it; the brief named three attributes). One more tuple member, same arming.
* **Counter test:** `despatch_number_sequences` is a single-row table (`id = 1`); the plan's "counter rows" is satisfied across the databases, one table per database. The 16-caller test and sentinel are the same harness as orders'.
* **Settings: `populate_by_name` deliberately absent.** With it, pydantic-settings also reads bare field names from the environment: measured here, `$USER` (`juanpabloperez`) silently became the database user. See residual 1.
* **No password default:** `password: str | None = None` plus a `model_validator` that raises unless a full URL or a password is supplied (`None` means "not supplied", never a usable credential).

## Ported-idiom ledger

| Idiom | #7 relied on | #8 supplied | #9 supplies, guarded by |
|---|---|---|---|
| FK set (2) | 2 `FOREIGN KEY` lines in `apps/fulfillment/drizzle/0000_nappy_mad_thinker.sql:75-76` (0001/0002 add none, `grep -c` = 0) | 2 at `InitialCreate.cs:114` (despatch_items, cascade) and `:140` (reservations, Restrict) | 2 in the migration; `test_the_foreign_key_set_is_exactly_the_two_planned` (widened tuple) |
| `reservations.stock_id` on delete | `no action` (`0000_nappy_mad_thinker.sql:75`) | `ReferentialAction.Restrict` (`InitialCreate.cs:145`), but the live catalog is NO_ACTION (`../order-to-cash-dotnet/progress/review_db_fulfillment.md:99`; leader amendment, review N1) | `NO ACTION` ('a'), as #7 and orders' FKs; the spec is silent. Re-open if Phase 9 needs RESTRICT semantics (the difference only exists for deferred constraints, which none is) |
| `reservations.company_code` / `product_code` lengths (leader, review N2, ACCEPTED, NOT FIXED) | §5 gives bare `varchar` | `nvarchar(20)` / `nvarchar(30)` | `varchar(20)` / `varchar(30)`, matching #8 and the other code columns; guarded by the types test |
| `despatch_number_sequences.id` type (leader, review N2, ACCEPTED, NOT FIXED) | `tinyint` (`0002_...sql:15`) | `int` | `integer` (§5 gives no type; PostgreSQL has no `tinyint`); guarded by the types test |
| FK-column indexes | MySQL creates them implicitly | EF creates them (`IX_reservations_stock_id`, `IX_despatch_items_despatch_id`, `InitialCreate.cs:155,206`) | explicit `ix_reservations_stock_id`, `ix_despatch_items_despatch_id` (PostgreSQL does not); members of the closed index set |
| Unique `despatches.order_reference` | added late: `0002_despatch_number_sequence_and_order_reference_unique.sql` | in `InitialCreate.cs:162` | in 0001 (`uq_despatches_order_reference`); index set |
| Counter seed / lock | `ON DUPLICATE KEY UPDATE` (orders' allocator, `order-number-allocator.ts:25,74`); `0002_...sql` creates `despatch_number_sequences` | check-then-insert, raced (id 45) | `INSERT ... ON CONFLICT DO NOTHING` + `FOR UPDATE`; 16-caller test + sentinel (measured: racy seed lost 10 of 10 rounds) |
| Quantity width | `int` (`0000_nappy_mad_thinker.sql:6-8,22,42`) | `int` (`InitialCreate.cs:104,121,...`) | `integer` + ORM guard (quantity code); population test |
| Money | none in this database (0 `cents` rows in §5) | none | none; `test_fulfillment_has_no_money_columns_and_one_bigint` |
| Payload text | `json`, MySQL reordered keys (`...sql:60`) | `nvarchar(max)` (`InitialCreate.cs:55`) | `json` + `RawJson`; `test_outbox_payload_is_read_back_byte_identical` |
| Timestamps | `datetime` (second precision in `0000_...`, `0001` adds `(3)` only to `occurred_at`) | `datetime2(3)` | `timestamptz(3)` on every instant; round trip + rounding test |
| Outbox order | `bigint unsigned auto_increment` (`0001_outbox_causation_seq_trace_parent.sql`) | `bigint IDENTITY(1,1)` (`InitialCreate.cs:57`) | `bigint GENERATED ALWAYS AS IDENTITY`; types map row `identity:ALWAYS`, `test_outbox_seq_is_assigned_by_the_engine_and_strictly_increases` |
| Reliability tables | defined per app | defined per DbContext | same columns, indexes and names as orders (copied from its migration/model); feature 11 proves the parity from four live catalogs |
| Range guard | none (MySQL silently/strictly truncates) | none | ORM `set` listener; **copied**, parity guard in `tests/architecture/` |
| Alembic runner | drizzle-kit | EF `Migrate` | async template; every lifecycle test |

Deviations from Databases.EN.md (disclosed, F4's lesson): ids `uuid` not `char(36)`; every `datetime` is `timestamptz(3)` (the plan's delta table, incl. `despatches.despatch_date`); `outbox.seq` identity not "bigint unsigned autoincrement"; `reservations.retailer_code` `varchar(20)` (§5 says bare "varchar"; #7 and #8 agree on 20); `reservations.stock_id` FK is NO ACTION (spec silent); two FK-supporting indexes added beyond the spec's own; `outbox.causation_id`/`trace_parent` are in (the §4.3 definition), as in orders.

Guards of #8 enumerated by content (`FulfillmentDbContextTests` / `review_db_fulfillment.md`): FK presence check (ported, as the closed set with delete, update, deferrability, match); index presence checks (not ported, closed set instead: A3/A1); timestamp read-back (ported); count-before-diagnostic ordering (not ported: diagnostic first, A2).

## Acceptance mapping and arming

Every arm: backup, ONE mutation, the named test, restore, `cmp` (the arm script asserts equality and clears `__pycache__`), results in `arms_f1..f8.out`, `arms_o206.out`, `composed_f.out` in the scratchpad, quoted here.

| # | Item (unit) | Test(s) | Arm and verbatim result |
|---|---|---|---|
| 1 | migrations from empty (the history) | `test_upgrade_downgrade_reupgrade_lifecycle`, `test_no_postgres_enum_types` | Testcontainer 18.6: closed relation set after upgrade (7 tables + `alembic_version` + `outbox_seq_seq`), downgrade leaves exactly `{("alembic_version","r")}`, re-upgrade equal. Arms: sequences table not dropped: `Extra items in the left set: ('despatch_number_sequences', 'r')`; `stock` not dropped: `('stock', 'r')`; a view left behind: `('leftover', 'v')`. **Composed `otcpy-postgres`/`otc_fulfillment`** (`composed_f.out`): before 0 tables; `upgrade head` exit 0, `current` = `0001 (head)`, 8 tables; `downgrade base` exit 0, left `alembic_version`, 0 sequences/views/matviews; `upgrade head` exit 0, `alembic_version = 0001`; offline `--sql` prints 8 `CREATE TABLE`. Composed DB left at head (empty tables). |
| 2 | round trip (each of 7 tables) | `test_every_column_of_the_table_round_trips[<table>]` (7), `test_the_literal_rows_cover_every_mapped_table_and_use_distinct_values`, `test_outbox_seq_is_assigned_by_the_engine_and_strictly_increases` | Written through the ORM, read by an independent asyncpg connection (payload as `::text`) AND through the ORM; distinct value per column, whole-ms distinct instants, one instant written at +02:00 comes back UTC. Arms: stock `reserved_units`/`low_stock_threshold` columns swapped: `{'low_stock_threshold': 1202} != {'low_stock_threshold': 1303}`; despatches `created_at`/`updated_at` swapped: `{'updated_at': ...12, 6, 6, 13000...} != {'updated_at': ...12, 7, 7, 14000...}`; `outbox.published_at` mapped as naive timestamp: `can't subtract offset-naive and offset-aware datetimes`. |
| 3 | FK closed set (the FK set, 2) | `test_the_foreign_key_set_is_exactly_the_two_planned` | Widened 9-tuple (table, cols, ref table, ref cols, on delete, on update, deferrable, deferred, match). Arms: reservations FK deleted: `missing: [('reservations', ('stock_id',), 'stock', ('id',), 'a', 'a', False, False, 's')]`; despatch_items FK substituted to `stock` (a sibling table, chosen so the migration still runs): `missing: [('despatch_items', ..., 'despatches', ...)] extra: [('despatch_items', ('despatch_id',), 'stock', ('id',), 'c', ...)]`; cascade removed: `extra: [... 'a', 'a' ...]`; **ON UPDATE CASCADE DEFERRABLE**: `extra: [('reservations', ('stock_id',), 'stock', ('id',), 'a', 'c', True, False, 's')]`; deferrable initially deferred: `extra: [... 'a', 'a', True, True, 's')]`. (A first substitution to `despatches` failed on "relation does not exist" at migration time, not on the instrument; replaced by the `stock` one above.) |
| 4 | types (every column of every table) | `test_every_column_of_every_table_has_the_planned_type`, `test_fulfillment_has_no_money_columns_and_one_bigint`, `test_payload_columns_are_json_not_jsonb` | Literal map from the live catalog (`format_type`, nullability, identity/default). Arms: identity removed from `outbox.seq`: `outbox.seq: expected ('bigint', False, 'identity:ALWAYS'), live ('bigint', False, '')`; precision dropped on `outbox.occurred_at`: `expected ('timestamp(3) with time zone', False, ''), live ('timestamp with time zone', False, '')`; payload as JSONB: `outbox.payload: expected ('json', False, ''), live ('jsonb', False, '')` and `{('outbox','payload'): 'jsonb'} != {... 'json'}`; `despatch_items.units` as bigint: `expected ('integer', ...), live ('bigint', ...)`; `next_value` as bigint: `Extra items in the left set: ('despatch_number_sequences', 'next_value')`. **Money columns: none.** Command: `sed -n 194,240p "Order To Cash - Databases.EN.md" \| grep -c -i cents` prints `0` (§5 = lines 194-240, confirmed with `grep -n "^## "`: §6 starts at 241); the same grep over lines 41-150 (otc_orders) prints 6, as in feature 9. So the only `bigint` is `outbox.seq`. |
| 5 | index closed set (`pg_indexes`/`pg_index`, 18) | `test_the_index_set_is_exactly_the_planned_one` | Literal of 18 incl. the 2 FK-supporting indexes; widened with `pg_am.amname`. Arms: **hash index** on `ix_reservations_stock_id`: `extra: [('reservations','ix_reservations_stock_id', False, ('stock_id',), None, 'hash')]`; FK index deleted: `missing: [('despatch_items','ix_despatch_items_despatch_id', ...)]`; extra index: `extra: [('despatches','ix_despatches_company_code', ...)]`; column order swapped: both orders listed. |
| 6 | JSON bytes on `outbox.payload` | `test_outbox_payload_is_read_back_byte_identical` | `order.despatched.v1` golden payload with a non-ASCII product code, written by `otc_contracts.to_wire_json`; ORM read and `payload::text` read both byte-equal. Arm JSONB: `assert b'{"lines": [..."DES-000010"}' == b'{"orderRefe...,"units":6}]}'` / `At index 2 diff: b'l' != b'o'`. Also `test_instants_come_back_aware_utc_and_rounded_to_the_millisecond` (.123987 -> .124). |
| 7 | range guard | `test_every_integer_column_of_the_live_database_is_guarded`, `test_units_max_round_trips_and_max_plus_one_is_a_domain_error`, `test_residual_orm_enabled_dml_paths_bypass_the_guard_and_only_the_engine_refuses[x4]`, unit `test_fulfillment_range_guards.py` (12), `test_range_guard_parity.py` (3), `test_a_sql_expression_..._passes_through` (orders and fulfillment) | Check deleted (`ensure_in_range` returns): `got sqlalchemy.exc.DBAPIError: ... invalid input for query argument $7: 2147483648 (value out of int32 range)` (names the driver error); unit: `DID NOT RAISE QuantityOutOfRangeError`. **Population test:** `low_stock_threshold` skipped in the installer: `assert ['stock.low_stock_threshold'] == []`; its code demoted to generic: `'stock.low_stock_threshold: storage.integer_out_of_range'`; `reservations.units` key misspelled: `got ...IntegerOutOfRangeError: 2147483648 does not fit reservations.units`; bound `high + 1`: `DID NOT RAISE QuantityOutOfRangeError`. **Parity guard:** one comparison operator edited in fulfillment's `range_guards.py`: `drifted from services/orders's copy` / `['-    if type(value) is not int or not low <= value <= high:', ...]`; `cache_ok = False` in fulfillment's `types.py`: same message for `types.py`; a comment appended in **orders'** copy: same message (so the guard is symmetric). **204(c):** `and not isinstance(value, ClauseElement)` removed, in fulfillment's copy: `QuantityOutOfRangeError: <sqlalchemy.sql.elements.BinaryExpression object at 0x...> does not fit stock.units`; in orders' copy: `IntegerOutOfRangeError: <...BinaryExpression ...> does not fit saga_commands.attempts`. |
| 8 | counter test and sentinel | `test_sixteen_concurrent_first_callers_get_distinct_contiguous_numbers`, `test_sentinel_check_then_insert_seed_loses_the_race` | 16 separate connections behind an `asyncio.Barrier`. Arms: `FOR UPDATE` removed: `assert [1, 2, 2, 2, 2, 2, ...] == [1, 2, 3, 4, 5, 6, ...]`; racy `IF NOT EXISTS ... INSERT` seed swapped in: `Left contains 15 more items, first extra item: UniqueViolationError('duplicate key value violates unique constraint "pk_despatch_number_sequences"')`; seed value 2: `assert [2, 3, 4, 5, 6, 7, ...] == [1, 2, 3, 4, 5, 6, ...]`. **Sentinel armed** by swapping the racy seed for the `ON CONFLICT` one inside it: `AssertionError: the harness never saw the race: it cannot prove the ON CONFLICT seed`; unarmed it prints `racy seed lost the race in 10 of 10 rounds`. |
| 206 | widened instruments (fulfillment and orders back-port) | same FK/index tests in both services | **Green before, red now**, on orders' migration (`arms_o206.out`): `ON UPDATE CASCADE DEFERRABLE` on `products.currency_id`: the unwidened tuple (a temporary copy of the test projecting to the old 5 members, deleted afterwards) `1 passed`; the widened test: `extra: [('products', ('currency_id',), 'currencies', ('id',), 'a', 'c', True, False, 's')]`. Hash index on `ix_products_currency_id`: unwidened `1 passed`; widened: `extra: [(... 'hash')]`. `# type: ignore[type-arg]` removed (signature is `set[tuple[Any, ...]]`; `mypy --strict` clean). |
| extra | models vs migration drift | `test_autogenerate_finds_no_difference_between_models_and_migrated_schema` | Unique constraint removed from the model only: `('remove_constraint', UniqueConstraint(Column('company_code', ...), Column('product_code', ...)))`. Drift detector, not the schema proof. |
| extra | settings | `test_fulfillment_database_settings.py` (3) | Default password put back: `DID NOT RAISE ValidationError`; database default `otc_orders` (sibling): `- :5432/otc_fulfillment + :5432/otc_orders`; `populate_by_name=True`: `postgresql+asyncpg://someone-else:s3cr3t-value@elsewhere:1/otc_fulfillment`. |

## Defeat-list rows

| # | Row | Applies? |
|---|---|---|
| 1 | delete the behaviour | yes: FK, index, seed, lock, range check, guard installation, ClauseElement pass-through, password default |
| 2 | corrupt a supplied field | yes: swapped columns, bound `high + 1`, seed value 2, precision, widths, identity |
| 3 | substitute a sibling identifier | yes: FK to `stock`, `otc_orders` database name in settings, `unitz` key, hash vs btree, `low_stock_threshold` demoted to the generic code |
| 4, 5, 6 | shadow in comment / dead region / raw string | schema guards: N/A, they read the live catalog and live bytes, not source. **Parity guard** reads source: a comment-only edit (row 4) DOES fail it by design (the comparison is line by line, comments included), proven by the `# edited` arm; dead regions and strings are equally compared, so row 5/6 cannot hide a difference |
| 7 | drop an optional element | yes: `ondelete` dropped, `onupdate`/deferrable/hash added, one column skipped, the specific code dropped |
| 8 | literal vs literal | checked: every expected set is a literal compared with a live catalog or live bytes; the round-trip literal is compared with what asyncpg reads, never with itself; `test_the_literal_rows_cover...` closes the literal against the mapped tables |
| 9 | closer half satisfied, premise stale | the 206 pair is exactly this: the narrow tuple stayed green on the mutation; the widened one fails |
| 10 | caches in the population | `__pycache__` cleared by the arm script after every restore |
| 11 | form the instrument does not recognise | the guard is an attribute event: ORM-enabled DML is the unrecognised form (row 12) |
| 12 | failure through a path the population never drives | yes: 4 ORM-enabled DML paths pinned by `test_residual_orm_enabled_dml_paths_...` (insert values, insert list of dicts, `update(Model)`, `bulk_insert_mappings`), fails if a bypass is ever closed. Raw `text()` SQL is the fifth (`ADVANCE_DESPATCH_SEQUENCE`), named in `sequences.py` |

## #8 inherited advisories and findings

* **A1 (timestamp read-back): AVOIDED**, round-trip + rounding tests. **A2 (diagnostic before count): AVOIDED**, `assert live == EXPECTED, diagnostic` first. **A3 (index checks presence-only): AVOIDED**, closed set with access method.
* **#8 id 44 (money width): not applicable here** (no money column, asserted); **id 45 (seed race): AVOIDED**, armed; **review D1 (FKs undeclared with a green suite): AVOIDED**, closed set, armed by delete and substitute.
* **#8 id 85 / id 104:** AVOIDED, root conftest (Docker-held port), proven with the stack stopped.
* **#9 review_db_orders F1, F2, F3, F5, F7:** F1/F2 fixed in orders and the copy (204(b)(c)); F3/F7 fixed (206); F5 avoided in fulfillment (orders' 204(d) is still feature 15's).

## Residuals and proposed dispositions

1. **Orders' `OrdersDatabaseSettings` has the same `populate_by_name=True` defect that I measured here** (a bare `$USER` becomes the database user), in addition to its password default (204(d)). I did not touch it (bounds). Proposed: add it to backlog 204(d), whose fix rewrites that class anyway. Re-open trigger: any run of the orders Alembic CLI or service from a shell where `USER`, `HOST` or `PORT` is set and the URL is not supplied in full. Billing's settings (feature 11) should copy fulfillment's.
2. **The guard still covers ORM attribute assignment only**; the four ORM-enabled DML paths and raw SQL surface a driver error (pinned). `ADVANCE_DESPATCH_SEQUENCE` is raw SQL on a guarded counter column. Phase 9 prevention is by review: `grep -n "insert(\|update(\|text(\|bulk_" services/fulfillment/src`, one classification per hit, plus the pin test.
3. **A SQL expression assigned to a guarded attribute is not range-checked** (that is the 204(c) behaviour): an overflow there is the engine's refusal. Documented in the module docstring.
4. **The parity guard's `MEMBERS` is a closed literal** (`orders`, `fulfillment`): feature 11 must add `billing` to it when it copies the module, otherwise `test_every_service_that_carries_the_guard_is_a_listed_member` fails (intended). Promotion to a shared package remains barred by CLAUDE.md line 82.
5. **`reservations.stock_id` NO ACTION vs #8's Restrict**: see ledger; the spec is silent.
6. `outbox`/`processed_events` equality with orders is by construction (copied) and covered per database by this feature's own literal maps; the cross-database proof is feature 11's.
7. **`quality.sh` wall clock rose from 45.8 s to 61.0 s** (655 vs 606 tests; seven more Alembic-running integration files). Not a regression in a measured sense, noted for the benchmark.
8. `R62`-style matrix rows: none provable here; `test-matrix.md` untouched.

## How to test by hand

```
./init.sh && ./quality.sh                                   # stop the otcpy stack first to prove independence
uv run pytest services/fulfillment tests/architecture/test_range_guard_parity.py -q   # 46 tests; integration needs Docker
uv run alembic -c services/fulfillment/alembic.ini upgrade head     # reads .env (POSTGRES_APP_PASSWORD, POSTGRES_DB_FULFILLMENT)
docker exec otcpy-postgres psql -U postgres -d otc_fulfillment -c '\dt'
uv run alembic -c services/fulfillment/alembic.ini downgrade base && uv run alembic -c services/fulfillment/alembic.ini upgrade head
# arm one guard yourself: make `ix_reservations_stock_id` use postgresql_using="hash" in
# services/fulfillment/alembic/versions/0001_initial_fulfillment_schema.py, then
uv run pytest services/fulfillment/tests/integration/test_fulfillment_foreign_keys_and_indexes.py -q   # fails naming 'hash'
```

## Surprises

* The brief's "a ClauseElement passes through the guard" is the reverse of what the guard did: it *refused* the expression with a false "does not fit" message (review F2). The fix passes it through; the unit test is armed by reverting in both copies.
* Keeping the copy byte-identical needed one design change (the quantity map became a parameter) rather than an allow-list of differing lines; the allow-list exists and is empty.
* `populate_by_name=True` in pydantic-settings reads bare field names from the environment (`USER`). Orders carries it.
* Without `relationship()`, the unit of work cannot order inserts by FK, so the round-trip test flushes the parent row first (the Phase 9 repositories will have to do the same or declare relationships).
