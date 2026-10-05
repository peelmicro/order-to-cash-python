# review_seed_job: feature 12 `seed_job` (Phase 7), Part B (full) and Part C tooling

**Verdict: REJECTED** (1 blocking defect, B1, in Part C's tooling). Part B, the seed, would be approvable as it stands: every concentration point I probed held, and 17 of my own mutations (none of them published by the implementer) failed by name. The one blocking defect is in `scripts/seed_parity.py`: `dump8` cannot run at all. Separately, acceptance item 5 is not met by any fix inside this round. See "What must change" and "Routing of acceptance 5".

Reviewer: Opus, 2026-10-05, about 16:55 to 17:10 (one session). `feature_list.json` id 12 set back to `in_progress` (one line, diff read).

## What I ran (and what I did not re-run)

* **`quality.sh` once**, with the 12 `otcpy` containers stopped (`docker stop`, then `ss -ltn` showed nothing on 5432/27017/9092/4222): **exit 0, `real 100.16`**, pytest `899 passed in 79.47s`, overall coverage 98.32%, domain coverage 98%, `lint-imports` 10 kept / 0 broken. Then I restarted the same 12 (`docker start` from the saved list, not by status filter, so the init jobs stayed exited), and all 12 were healthy. `./init.sh` exited 0, and section 5d reported `specs/shared/` byte-identical to #8 and #7.
* **Oracle provenance, re-derived on my own:** I wrote my own `tsx` script over #7's exported `CURRENCIES, PRODUCTS, RETAILERS, COMPANIES, CREDITS, STOCK, SAGAS` and `toTimelineDocument` (from `order-to-cash-nestjs/apps/seed`, using #7's own `node_modules/.bin/tsx`) and compared it with both checked-in fixtures and with #8's oracle as parsed JSON:
  ```
  timeline: mine==#9 fixture True  mine==#8 oracle True 6 6 6
  currencies True 3 3 / products True 12 12 / retailers True 7 7 / companies True 22 22
  credits True 154 154 / stock True 215 215 / sagas True 6 6
  ```
  (My script first wrote its two output files into #7's `apps/seed/`. I moved them to the scratchpad straight away, and `git -C order-to-cash-nestjs status --short` shows 0 lines.)
* The seed unit suite (`137 passed in 0.59s`, no containers) and the seed integration suite (`29 passed in 26.28s`, with `--durations`). I also ran the specific tests named in the arms below, each one alone.
* **Not re-run:** the implementer's 31 arms. I armed my own instead (next section). The live `python -m otc_seed` against the dev stack was not re-run: the CLI integration test runs the same entry point (`run()`) against migrated containers and checks `totalAdded 547`, then `0`. Part C's live run was not started (not authorised). #8's stack was not started.

## Arming (mine, none published by the implementer)

Protocol for every row: `cp` backup, a scripted replace that fails if the file did not change, `__pycache__` cleared, the ONE named test run, the file restored from the backup, `cmp` clean, caches cleared. After the last restore, `git status --short | md5sum` matched the hash taken before the first arm, and the touched suites were re-run green (`142 passed`).

| # | Mutation (production file) | Test | Verbatim failure |
|---|---|---|---|
| T1 | causation inferred from array position: `event["causationId"] = events[-1]["eventId"]` (`domain/timeline.py`) | `test_every_seeded_document_equals_number7s_field_by_field` | `ORD-000001 .events[4].causationId: seeded (<class 'str'>, '8611cdde-…'), #7 produced (<class 'str'>, 'bcd04aa8-…')` |
| T2 | sibling: `company.gln` <- `retailer.gln` | same | `ORD-000001 .company.gln: seeded (<class 'str'>, '5400000000010'), #7 produced (<class 'str'>, '5400000000218')` |
| T3 | `items[]` reordered by product code, descending | same | `ORD-000001 .items[0].name: seeded (…'Olive Oil 1L Case (12u)'), #7 produced (…'Pasta 500g Case (24u)')` |
| T4 | `detail` dropped (optional element) | same | `ORD-000006 .events[2].detail.reason: seeded None, #7 produced (<class 'str'>, 'simulated_cents_rule')` |
| T5 | `cancellationReason` `None` -> `""` | same | `ORD-000001 .cancellationReason: seeded (<class 'str'>, ''), #7 produced (<class 'NoneType'>, None)` |
| T6 | `updatedAt` taken from the last event | same | **passed: an equivalent mutant.** In all 6 oracle documents `updatedAt == max(events[].occurredAt)` (checked), so the output is identical. Not a guard gap |
| M1 | Mongo writer stores `orderDate` as a BSON datetime (`infrastructure/mongo.py`) | `test_the_documents_read_back_from_mongodb_equal_number7s_value_for_value` | `ORD-000001 .orderDate: seeded (<class 'datetime.datetime'>, …), #7 produced (<class 'str'>, '2026-06-01T09:00:00.000Z')` |
| M2 | Mongo writer stores `statusRank` as a float | same | `ORD-000001 .statusRank: seeded (<class 'float'>, 98.0), #7 produced (<class 'int'>, 98)` |
| S1 | seed `Table` forgets `orders.cancellation_reason` (`infrastructure/tables.py`) | `test_the_seed_definitions_equal_the_migrated_schema` | `"orders.cancellation_reason: seed expects None, database has ('VARCHAR(100)', True, False)"` |
| S2 | timestamp precision 3 -> 6 | same | `Left contains 19 more items, first extra item: "currencies.created_at: seed expects ('TIMESTAMP(6) WITH TIME ZONE', …), database has ('TIMESTAMP(3) WITH TIME ZONE', …)"` |
| S3 | `payments.invoice_id` FK gains `ON DELETE CASCADE` | same | `"payments fks: seed expects {(('invoice_id',), 'invoices', ('id',), 'CASCADE')}, database has {(… None)}"` |
| S4 | `products.ean` loses `unique` | same | `"products uniques: seed expects {('code',)}, database has {('ean',), ('code',)}"` |
| P1 | payload field corrupted ON THE WIRE, after validation: `availableCreditAfter 483870 -> 483871` (`infrastructure/payloads.py`) | `test_every_payload_is_semantically_equal_to_the_one_7_wrote` | `At index 5 diff: {… 'availableCreditAfter': 483871} != {… 'availableCreditAfter': 483870}` |
| P1b | same mutation | `test_every_row_of_every_table_equals_the_one_7_wrote` (real billing DB) | `AssertionError: outbox f8aafd6d-e1df-46c9-91d9-041300d6a6f7 … Differing items: {'payload': …}` |
| P3 | stored text re-serialised by `json.dumps(sort_keys=True)` (spacing and key order) | `test_the_stored_payloads_are_the_one_serializers_text_in_json_columns` | `assert '{"orderRefer...mount":16130}' == '{"buyerGln":...ount": 16130}'` |
| I1 | #7's shape: an upsert of every row that rewrites identical content (`ON CONFLICT DO UPDATE SET id = excluded.id`), report kept at 0 (`infrastructure/postgres.py`) | `test_running_the_seed_twice_changes_nothing` | `Differing items: {… 'despatch_items': [(…, '766')] …} != {… '763' …}` (the `xmin` changed) |
| R7 | `invoices.updated_at` = `invoice_date` instead of `paid_at` | `test_every_row_of_every_table_equals_the_one_7_wrote` | `invoices 772f43e4-… Differing items: {'updated_at': datetime(2026, 6, 1, 9, 4, …)} != {'updated_at': datetime(2026, 6, 2, 9, 0, …)}` |
| A1 | Part A: harness serialised by an `asyncio.Lock` around each caller's transaction, `gather` and barrier kept (`services/orders/.../test_orders_counter_seed.py`) | `test_sentinel_check_then_insert_seed_loses_the_race` | `AssertionError: the racy seed lost 0 of 16 callers, expected 15: the harness did not release the callers together…`; restored, `cmp` ok, file `2 passed in 4.21s` |
| W1 | a second write path in a new module, through an alias: `from sqlalchemy import insert as add_rows`; `run = conn.execute; await run(add_rows(table), rows)` | `test_write_path_population.py` (whole file) | **`11 passed`: NOT DETECTED.** Finding N1 |

Mutations that turned out equivalent, recorded so nobody counts them as arms: changing `creditLimit` in a payload (no payload carries that key), and `model.model_dump_json(by_alias=True)` instead of `to_wire_json` (the contracts' `WireModel` makes them byte-equal for all 12 seeded types, checked). P1 and P3 above are the non-equivalent replacements.

Defeat-list rows I applied to the value guards: 1 (T4, M-family), 2 (T5, R7, P1), 3 (T2), 7 (T4), reorder (T3), 11 (M1/M2: same value, different type; W1). Row 8 does not arise, because the expected side is a file I re-derived independently.

## Concentration points

1. **Dataset fidelity and oracle provenance: holds.** The oracle comes from executing #7's TypeScript, and I reproduced it myself (above). It equals #8's checked-in oracle. Every leaf of every timeline document is compared with its exact type, both on the unit path and on the MongoDB read-back. Every relational row of every seeded table is compared column by column against expected rows built from the oracle. The seed's column semantics (`created_at`/`updated_at` choices, the cancelled order's `notes`) match #7's writers (`billing-db.writer.ts:89-106`, `orders-db.writer.ts:118-144`, read).
2. **Timeline value guard (#8 D1): avoided, not recurred.** Six unpublished timeline mutations: five fail by path, and T6 is provably equivalent. Two infrastructure type mutations fail on the MongoDB read-back. The comparer covers the union of both sides' paths plus each dict's key set, so an extra key also fails (this closes #8's A2).
3. **Schema drift: guarded, and the guard is armed.** `schema_check.problems_in` runs against the root conftest's Alembic-migrated templates (`conftest.py:127-151`, `alembic command` on each service's `alembic.ini`), never a schema the seed created. My four drift mutations on the SEED side (S1-S4) all fail, naming the table and column. The implementer's 8 in-suite arms cover the DATABASE side. Not compared, by design: defaults, CHECK constraints, non-unique indexes. A CHECK the seed violates would fail loudly at insert time, so that is acceptable.
4. **Idempotence semantics: ruling and disposition.**
   * *Does `specs/shared/` decide it?* No. `requirements.md:593` makes "auth, seeding and gateway endpoints" product-level concerns. The acceptance ("idempotent — running twice is a no-op") decides only the back-to-back case, and #7, #8 and #9 all satisfy it.
   * *The three behaviours, read from the code (the leader's grep showed that #7 and #8 upsert; this is what their set clauses actually write):* **#7** `onDuplicateKeyUpdate` sets ONLY `updatedAt` (and `publishedAt` for outbox rows, `valueDate` for payments, `description` for order items: `writers/*.ts:61,79,97,115,144,161,189`, `billing-db.writer.ts:61,84,107,122,138,158`, `fulfillment-db.writer.ts:59,83,99,113,135`). So #7 does NOT reset units, status or limits. It rewinds `updated_at` to the seed instants, and Mongo's `replaceOne` (`mongo.writer.ts:211`) replaces each of the 6 seeded timeline documents whole. **#8** `EfUpsert` (`EfUpsert.cs:25-35`) re-applies every column: `FulfillmentSeedWriter.cs:39-46` writes `Units`, `ReservedUnits`, `LowStockThreshold`, `UpdatedAt` back to the seed values for all 215 stock rows, and likewise for statuses and limits. Mongo is `ReplaceOneAsync … IsUpsert` (`MongoSeedWriter.cs:162-165`). **#9** changes nothing that exists (insert-if-missing, `ON CONFLICT (id) DO NOTHING`, Mongo `$setOnInsert`).
   * *Observable difference (a re-run after live traffic):* #8 silently restocks every seeded stock row to 500 / 0 reserved while live reservations still exist, so stock and reservations disagree. #7 rewinds `updated_at` on all seeded rows and resets 6 timeline documents. #9 leaves the live state alone. Seeded orders are terminal, so no live event advances their documents, and the Mongo difference is therefore theoretical. The stock difference is real.
   * **Disposition: ACCEPT (deliberate divergence), with evidence:** the implementer's arms 15 and 17, my I1, `test_a_second_run_does_not_reset_state_a_live_order_changed`, and `test_a_document_the_projector_already_advanced_is_left_alone`. Restocking is the job of n8n workflow 3 through the API (`specs/shared/n8n-workflows.md` §5), not the seed's. **Re-open trigger:** (i) the maintainer wants a "re-seed resets the demo" semantic; or (ii) the Part C live diff shows `stock.units`/`reserved_units`/`updated_at` differences on the seeded subset, which must then be attributed to live traffic or to #8's resetting re-run, not to the seed (see N4). The ledger row must be corrected (N3): as written it implies that #7 resets live state, and #7 does not.
5. **Counter rows / proposed backlog 211.** #7 and #8 seed no counter rows either. Both avoid the collision in the ALLOCATOR: it self-seeds the counter lazily from the numeric MAX of the existing references. #7's `order-number-allocator.ts:56-70` (`max(cast(substring(order_reference, 5) as unsigned)) + 1`, numeric after #7's D6, because a string MAX goes backwards past 999999). #8's `EfCoreOrderNumberAllocator.cs` after id 45 (`impl_order_number_allocator_seed_race.md`: one atomic `INSERT … SELECT ISNULL(MAX(CAST(SUBSTRING(...)))…)+1 … WHERE NOT EXISTS (… WITH (UPDLOCK, HOLDLOCK))`). #9's Phase 6 counter SQL instead seeds the constant `VALUES (1, 1)` (`services/orders/src/otc_orders/infrastructure/persistence/sequences.py:12-14`; the fulfillment and billing copies follow the same shape). Its docstring (lines 5-9) says the advance happens in the caller's transaction, so a failed order burns no number. On a seeded database the first allocation would therefore return `ORD-000001`, the order insert would fail on the unique `order_reference`, the rollback would undo the advance, and **every** later order would fail the same way. The counter would never move. Text for the entry is below.
6. **Range guard, money, instants, serializer: hold.** The write-path population is `insert_missing` (pg_insert + execute) plus Mongo `update_one`/`create_index`. Each row passes `ensure_row_in_range` before any statement is built (the implementer's arm 18). Widths come from the column TYPES, and S1-S4 show those types are proved equal to the database. Money in the seed domain: no `/` (grep: 2 hits, both inside strings, `products.py:30` and `credits.py:81`). `//` appears once, on microseconds (`clock.py:42`), which is not money. No `float` or `Decimal`. The AST money guard covers `otc_seed/domain`. Instants: every datetime reachable from the dataset is whole milliseconds (`test_seed_instants.py`), and the domain formatter is pinned to `otc_contracts.format_instant`, so backlog 205 is not triggered. Outbox: the envelope is stored as columns, not bytes, so its byte-exactness is the relay's job (a later phase). The payload is written by `otc_contracts.to_wire_json` into a `json` column through a passthrough type, and P1/P3 show both mutation families fail. The weakness is N1.
7. **Part C tooling.** The seeded subset is a literal list (`scripts/seed_parity.py:58-114`: 6 refs and 6 ids, 3/12/7/22 codes, CR-000001..154, 11 + 17×12 stock pairs). Dumps are files with one sorted JSON line per row, UTF-8. Rows are read client-side and normalised (uuid case, `.mmmZ`, int money, canonical JSON payloads), with no aggregate or hash, and a test bans them. The literal-key and exact-count checks make a vacuous dump fail. **But `dump8` cannot run: B1.** The #9 half works (`test_the_nine_half_dumps_the_literal_subset_normalised` green; the implementer ran it live).
8. **quality.sh wall clock.** Measured: **100.16 s** (pytest 79.47 s, 899 tests). The implementer measured 104.66 s, after Part A 75.16 s, baseline 87.47 s. The seed adds 165 tests, and its 29 integration tests take 26.3 s on their own (a cold session, containers included). The per-test cost is about 0.6-1.5 s, because each test clones three templates, seeds 541 rows and drops them. Recommendation for the maintainer: **re-baseline the threshold at about 105 s for Phase 7 rather than cut seed guards.** The seed is a permanent new population, and its tests are the D1 guard. If a cut is wanted, the change of kind is a session-scoped **seeded template** per service (seed once into a template, `CREATE DATABASE … TEMPLATE` per test). Read-only assertions (every-row, published-outbox, payload text, Mongo read-back, partial index, parity #9 half: 6 tests) would then pay a clone instead of a seed, roughly 4-6 s. The implementer's estimate of 10 s for a module-scoped stack looks optimistic against the measured durations. For Phase 8 onwards, when more integration suites land, the scalable change is pytest-xdist with per-worker containers. That is a decision for the maintainer, not part of this feature.

## Defects

### B1 — BLOCKING. `dump8` cannot run: `sqlcmd` rejects its own argument list.

`scripts/seed_parity.py:436-470` (`sqlcmd()`, flags at :454 and :457) passes `-W` together with `-y 0`. I ran that exact argv against #8's own image, as a throwaway with `--network none`: `docker run --rm --network none --entrypoint /opt/mssql-tools18/bin/sqlcmd mcr.microsoft.com/mssql/server:2022-CU26-ubuntu-22.04 -S localhost -U x -P y -C -d otc_orders -h -1 -W -s $'\x1f' -y 0 -f 65001 -Q "SET NOCOUNT ON; SELECT 1"`. It printed **`Sqlcmd: The y and the W options are mutually exclusive.`** with `exit=1`, before any connection. The same argv without `-y 0` got past argument parsing (it failed on login, as expected with no server). This is not #8's stack: no compose, no volume, the network disabled.

Why it matters: the brief's contract for Part C is "the run is one command once authorised". As built, the first authorised command fails, and the obvious one-flag fixes are traps:
* Dropping `-y 0` brings back sqlcmd's default 256-character limit on `nvarchar(max)`, so #8's `payload` column would be truncated. That is exactly #8's `GROUP_CONCAT`/`STRING_AGG` lesson; `json.loads` would fail loudly, but the tool would still not work.
* Dropping `-W` keeps padding on fixed-width output, and `normalise` does `str(raw)` with no strip, so every row would differ.

The unit tests (`test_sqlcmd_output_is_parsed_with_utf8_text_nulls_and_blank_lines` and others) feed canned text, so they cannot see argv or output-format errors. That is defeat-list row 12: the failure is served through a path the population never drives.

### Non-blocking (dispositions)

* **N1 (fix in this round; cheap).** `services/seed/tests/unit/test_write_path_population.py` matches call names syntactically, so an aliased import (`insert as add_rows`) or a bound method (`run = conn.execute`) adds a write path the scan cannot see (W1: `11 passed`). That is defeat-list row 11. CLAUDE.md: "when a syntax guard keeps losing, test the behaviour". Suggested behaviour guard: spy `ensure_row_in_range` during one real seed run and assert it saw exactly the rows the databases gained (541 relational rows), or resolve `import … as` aliases and assignments of write callables in the AST walk. If it is not fixed in this round, file it as a backlog entry attached to `seed_job`.
* **N2 (fix in this round; cosmetic).** Stale test paths in docstrings, the D5/A1 class from #8's review recurring in miniature: `domain/timeline.py:10` (`tests/test_timeline_value_guard.py`), `domain/data/sagas.py:32` (`tests/test_payloads_against_contracts.py`), `domain/deterministic.py:6` (`services/seed/tests/test_deterministic_parity.py`), `domain/clock.py:6` (`tests/test_seed_instants.py`). All of them live under `tests/unit/`. `domain/clock.py:34` is also wrong in substance: it says `test_timeline_value_guard.py` pins the two formatters to each other, but `unit/test_seed_instants.py` is the file that does.
* **N3 (fix in this round; report only).** In `progress/impl_seed_job.md`, the ledger row "Upsert idempotence" and answer (c) say that #7 and #8 "use update" so that a re-run would reset units, status and limits. That is true of #8 and false of #7, which rewrites only `updated_at`/`published_at`/`value_date`/`description` (citations in point 4). Correct the "#7 relied on" half. The "#8 supplied" citation `OrdersSeedWriter.cs:36` is actually line 37.
* **N4 (fix in this round, with B1).** Part C's stock subset is all 215 stock rows, and every one of them is LIVE state: on #8's live database, `units`, `reserved_units` and `updated_at` reflect whatever demo traffic ran, or #8's resetting re-run. The diff will report those as parity failures. Either compare the seed-immutable columns only for the live-mutable tables (`stock`: id, codes, threshold, `created_at`) and report the live-mutable columns in a separate, non-failing section, or state the expected live-traffic differences in the script's docstring so the authorised run is read correctly. The orders subset is safe (the seeded orders are terminal).
* **N5 (route, backlog 212 below).** `domain/timeline.py` keeps LOCAL copies of projector-owned constants (`TIMELINE_ORDER_VERSION = 2`, `STATUS_RANK`, the `projector:` dedup prefix, the `uq_order_reference` partial index). They are guarded against #7's oracle only. Nothing will pin them to #9's own projector when it exists in Phase 12, and services cannot import each other. #7 relied on "kept in sync by inspection" (`mongo.writer.ts:113-123`).

## What must change before re-review

1. **B1:** make `dump8`'s sqlcmd invocation valid AND correct. Prove it against a throwaway SQL Server, without #8's stack and without #8's volumes: e.g. `docker run` `mcr.microsoft.com/mssql/server:2022-CU26-ubuntu-22.04` standalone, create one table holding a payload of over 256 characters, `Aldi España`, a NULL, a fixed-width `nvarchar(60)` and a `datetime2(3)`, then run the script's own `sqlcmd()` + `parse_sqlcmd()` + `render()` against it and show that the rendered line equals the #9-side rendering. Record the probe verbatim in the report, and arm it (e.g. put `-y 0` back next to `-W` and show the failure). An alternative that removes the class: read #8's MS-SQL through a client that returns typed rows (e.g. `sqlcmd -o` to a file in a format with explicit framing, or a Python TDS driver). If a driver is added, list it in `Packages installed:`.
2. **N4:** the live-mutable stock columns are handled or documented (see above).
3. **N1, N2, N3:** as dispositioned above; N1 may be routed to the backlog instead, if the implementer says so.
4. Nothing in Part B's behaviour needs to change. Re-review will re-run only the Part C tests, B1's probe and the N1 guard. The 17 arms above stay valid unless `timeline.py`, `mongo.py`, `tables.py`, `payloads.py` or `postgres.py` change; if they do, I re-arm.

## Routing of acceptance 5 (the leader's, not a sentence)

Acceptance 5 ("parity against #8's live databases by dumping rows to files and diffing them") **is not met** and will not be met by fixing B1: the live run is not authorised. After B1 is fixed, `done` requires one of two things. Either the maintainer authorises the live run (`MONGO_HOST_PORT=27018 docker compose -f ../order-to-cash-dotnet/docker-compose.infra.yml up -d mssql mongodb`; no `otcpy` container needs to stop; 1433 is free per the implementer's `ss -ltn`), or the maintainer gives an explicit disposition: "ACCEPTED, NOT FIXED", with the re-open trigger "#8's live stack is next started for any reason", or a numbered backlog entry for the live run attached to a feature that will be open then. The leader files whichever is chosen. #8 took the same deferral for its own item ("parity against #7's live MySQL", `review_seed_job.md:22, 198, 459`), and it was never closed. Do not let it become "the next feature".

## Proposed backlog entries (for the leader to file; I did not write `feature_list.json`)

* **211 — `number_allocators_start_above_existing_references`**, attached to `orders_acceptance` (15) for `ORD`, `fulfillment_despatch` (18) for `DES` and `billing_invoicing` (21) for `INV`. Text: "#9's counter seed SQL inserts the constant `next_value = 1` (`otc_orders/infrastructure/persistence/sequences.py:12-14`, and the fulfillment/billing copies). On a database the seed has run on, the first allocation returns `ORD-000001`/`DES-000001`/`INV-000001`, the insert fails on the unique reference, the rollback undoes the advance, and no order can ever be placed. #7 (`order-number-allocator.ts:56-70`, numeric MAX after its D6) and #8 (id 45, atomic `INSERT … SELECT MAX+1 WHERE NOT EXISTS … UPDLOCK, HOLDLOCK`) seed the counter from the numeric MAX of existing references. Acceptance: (a) the seed statement stays ONE atomic statement, `INSERT … SELECT 1, COALESCE(MAX(CAST(substring(<ref> FROM <prefix+1>) AS bigint)), 0) + 1 FROM <table> ON CONFLICT (id) DO NOTHING`, with a numeric, not string, MAX; (b) a test runs `otc_seed` (or inserts `ORD-000006`/`DES-000005`/`INV-000005`) and then allocates, expecting `ORD-000007`, `DES-000006`, `INV-000006`; (c) the 16-concurrent-first-callers test and the Part A sentinel stay green on the new statement; (d) a reference above 999999 is not compared as text (the #7 D6 case)." Found in this review; the seed's own docstrings (`sagas.py:19-22`, `README.md`) already state the constraint.
* **212 — `seed_timeline_constants_pinned_to_projector`**, attached to `projector_read_model` (24). Text: "The seed writes `timelineOrderVersion = 2`, the `STATUS_RANK` table (`placed 1 … paid 7, completed 98, cancelled 99`), `processedEventKeys` prefixed `projector:` and the partial unique index `uq_order_reference`, all as LOCAL copies (`services/seed/src/otc_seed/domain/timeline.py:25-43`, `infrastructure/mongo.py:21`), guarded only against #7's oracle. When the projector lands, a test must pin the projector's values to the literals the seed writes (no import across services: the same literals asserted in both services' tests, or one shared fixture under `tests/`), so a bump of the projector's version does not make every seeded document look stale." Found in this review (N5).

## `R<n>` / acceptance -> test mapping (verified by running, not by name)

`sdd: false`, so there are no `R<n>` ids. The mapping is against the 5 acceptance items and backlog 201's item.

| Acceptance | Tests (each run in this review) | Seen to fail |
|---|---|---|
| 1 deterministic ids, skipped index 12 commented | `unit/test_deterministic_parity.py::test_deterministic_id_matches_the_value_7s_typescript_produced`, `::test_the_skipped_hex_character_is_load_bearing`, `::test_the_datasets_own_ids_match_the_value_7_produced`; comment at `domain/deterministic.py:26-35` | implementer arms 9, 10 (not re-armed; the vectors equal my re-derived dataset's ids) |
| 2 same master data, GLNs, limits, stock | `unit/test_dataset_parity.py::test_master_data_rows_equal_number7s`, `integration/test_seed_databases.py::test_every_row_of_every_table_equals_the_one_7_wrote` | R7, P1b (mine) |
| 3 sample orders, cancelled order, timeline values | `unit/test_timeline_value_guard.py::test_every_seeded_document_equals_number7s_field_by_field`, `integration/test_seed_mongo.py::test_the_documents_read_back_from_mongodb_equal_number7s_value_for_value` | T1-T5, M1, M2 (mine) |
| 4 idempotent | `integration/test_seed_databases.py::test_running_the_seed_twice_changes_nothing`, `integration/test_seed_mongo.py::test_running_the_seed_twice_changes_no_document`, `integration/test_seed_cli.py::test_the_cli_seeds_the_stack_then_a_second_run_adds_nothing` | I1 (mine) |
| 5 parity vs #8 live | tooling only: `unit/test_seed_parity_tooling.py`, `integration/test_seed_parity_nine_half.py` | **not met** (B1; live run not authorised) |
| 201 item 3 | `unit/test_dataset_parity.py::test_every_saga_fact_equals_number7s`, `::test_the_seeded_causal_chain_is_number7s_one_link_shorter_than_a_live_saga`; text in `domain/data/sagas.py:7-17` and `services/seed/README.md` | T1 (mine; the causal chain differs) |

## Ported-idiom ledger (sdd: false, so it lives in `progress/impl_seed_job.md`)

The ledger is present, and its citations are correct except as noted in N3: `deterministic.ts:22`, `DeterministicId.cs:39` `"4" + hex[13..16]`, `Gs1Identifiers.cs:34`, `money-text.ts:24` (each read). Row probed: "reuse the service's schema, not available, own Core tables, guard = live-schema comparison". Probed with S1-S4: the guard executes the code the row is about, and it fails. The Python questions: integer division (none in the money domain; `divmod` in `money_text.py`); JSON serialisation (one serializer; P3 fails); event-loop affinity (engines and the client are built and disposed in the CLI's single `asyncio.run`, and the tests use function loops written beside the fixtures); cancellation (no tasks created); `Any` leaks (mypy strict green in `quality.sh`, no new override).

## Inherited #8 findings (for the effort entry)

| #8 finding | #9 |
|---|---|
| review D1 (timeline values unguarded) | **avoided**: leaf-and-type comparison on both the unit and Mongo paths; 7 non-equivalent mutations of mine fail |
| D3 (weak counts) | **avoided**: exact counts everywhere (`EXPECTED_COUNTS`, `test_dataset_counts.py`) |
| D5 / A1 (stale report/file references) | **recurred, minor**: N2 |
| D6 (pure tests in a container project) | **avoided**: `tests/unit` runs with no containers (`137 passed in 0.59s`) |
| A2 (`detail` extra key unseen) | **avoided**: the comparer covers the union of paths and dict key sets |
| A3 (idempotence checksum covers a subset) | **avoided**: every row of every table, plus `xmin` |
| #8's own deferral of the cross-assessment live parity | **at risk of recurring**: see "Routing of acceptance 5" |

## CHECKPOINTS.md

C1
- [x] harness files exist (`ls`)
- [x] progress/current.md, history.md exist
- [x] `.claude/agents/` holds the 7 agents
- [x] every agent declares a model, or states that it inherits (leader, reviewer and spec_author state it in `description`)
- [x] `./init.sh` exits 0 (after the stack restart)

C2
- [x] at most one feature `in_progress`: none at review time (12 was `in_review`); after this verdict, 12 alone
- [x] every status valid (python check: `invalid []`)
- [x] every `done` feature has passing tests (899 passed)
- [x] `progress/current.md` describes this session
- [x] no `blocked` features touched

C3
- [x] `lint-imports`: 10 kept, 0 broken (run, not eyeballed); `otc_seed.domain` imports no framework
- [x] no cross-service DB access or imports: the seed writes three services' databases by design, as a product-level one-shot job (#7 and #8 did the same); it imports no service package (independence contract kept) and owns its table copies under a drift guard
- [x] no shared runtime code beyond the three packages; `dependencies = []` in shared_kernel and cqrs (grep, 1 hit each)
- [x] no domain imports `otc_cqrs`
- [x] no float, Decimal or `/` in domain money (grep above; AST money guard green)
- [x] Kafka/NATS classification: the seed publishes nothing; its outbox rows are pre-published (`published_at` set, `test_every_seeded_outbox_row_is_already_published…`)
- [x] no stray debug logging or TODOs (grep: 0 hits in `services/seed/src` and `scripts/seed_parity.py`; the CLI's `print` is its documented report)

C4
- [x] `./quality.sh` passes (exit 0, 100.16 s, stack down)
- [x] domain tests pure
- [x] integration tests on testcontainers (`postgres:18.6`, `mongo:8.3.8`), green with the developer infrastructure down
- [x] coverage 98.32% overall, 98% domain
- [x] no Jest, Karma or Jasmine (quality.sh section 7 runs Vitest)

C5
- [x] no suspicious untracked files (none matching `*.tmp`, build output or `__pycache__` in `git status --untracked-files=all`)
- [ ] history.md effort entry: not applicable on rejection (written on approval)
- [x] `feature_list.json` reflects the true state (12 -> `in_progress`)
- [ ] human told what was done and how to test it: the leader's, after closing
- [x] Claude did not commit

C6: not applicable (`sdd: false`).

C7
- [x] `specs/shared/` byte-identical to #8 and #7 (init.sh 5d)
- [x] no deviation needing an SA-n (the idempotence divergence is product-level, `requirements.md:593`)
- [x] inherited #8 findings accounted for (table above)
- [ ] effort record: on approval
- n8n, API script, README benchmark: not this feature's subject

---

## Re-review — round 2

**Verdict: APPROVED, with acceptance 5 open pending the maintainer's ruling.** Blocking defects: 0. B1, N1, N2, N3 and N4 are closed; I checked each one by running something myself, listed below. As the leader instructed, `feature_list.json` id 12 stays `in_review`: the leader sets `done` after the maintainer rules on acceptance 5 (live parity against #8 is still not authorised). The `progress/history.md` effort entry goes in with that transition. Review effort for the record: round 1 about 16:55 to 17:10; round 2 began after the implementer's 17:19 end and closed at 17:22 by `date` (2026-10-05; one reviewer session, Opus).

Inputs: `progress/impl_seed_job.md` § "Round 2" (lines 198-237). Scope as round 1's item 4: B1, N4, N1, N2, N3. I did not re-run `quality.sh`; the implementer reports exit 0, 105.67 s, 904 passed, stack stopped. I ran only the affected files: `services/seed/tests/unit` (all of it, because docstrings changed in four domain modules), `integration/test_seed_parity_nine_half.py` and `integration/test_seed_write_path_behaviour.py`, giving **`144 passed in 8.45s`**.

### Are the round-1 arms still valid? (verified, not taken from the report)

I compared the files with my round-1 `cp` backups:
- `mongo.py`, `tables.py`, `payloads.py` and `postgres.py` are byte-identical (`cmp` silent).
- `domain/timeline.py` **differs** (`cmp`: byte 611, line 10). The `diff` is a single docstring line (`tests/test_timeline_value_guard.py` -> `tests/unit/test_timeline_value_guard.py`). An AST comparison with the module docstring removed gives `code-equal ignoring module docstring: True`.

So the implementer's sentence "timeline.py … unchanged" is wrong in letter but right in substance. All 17 round-1 arms still exercise the same code. I have no backups for the docstring edits in `sagas.py`, `deterministic.py` and `clock.py`, so I rely on the oracle-parity and vector tests passing (inside the 144) for those.

### B1 — closed

**My probe, independent of the implementer's.** I started a standalone container with `docker run -d --name rev-seedprobe-mssql -e ACCEPT_EULA=Y -p 127.0.0.1::1433 mcr.microsoft.com/mssql/server:2022-CU26-ubuntu-22.04`, with no compose, no `otcnet` volume and #8's stack untouched. In a fresh database I created two tables with **#8's own column types**, read from #8's migrations:
- `outbox` as in `Orders/…/20260901100855_InitialCreate.cs:47-59`: `uniqueidentifier`, `nvarchar(60)`, `nvarchar(max)` payload, `datetime2(3)`, `bigint IDENTITY`, `nvarchar(64)`;
- `stock` as in `Fulfillment/…/20260901103111_InitialCreate.cs:86-93`.

I filled them with **the seed's own rows**, built by `OrdersTarget._rows` / `FulfillmentTarget._rows`: all 17 orders-outbox rows and all 215 stock rows. I then ran the script's own `sqlcmd()` → `parse_sqlcmd()` → `check_subset()` → `render_files()` with the script's own `select_sql(spec)`. The #9 side was `render_files()` over the same Python values. Verbatim:

```
orders.outbox.jsonl: #8 17 lines, #9 17 lines, equal=True, longest line 941 chars
fulfillment.stock.jsonl: #8 215 lines, #9 215 lines, equal=True, longest line 167 chars
fulfillment.stock.live.jsonl: #8 215 lines, #9 215 lines, equal=True, longest line 173 chars
em-dash rows in #8 dump: 1 | España rows: 0
max raw payload chars: 497
ALL EQUAL: True
```

What this covers: payloads well over sqlcmd's default 256-character cut came back whole; the em dash survived; uppercase `uniqueidentifier`s were normalised; `datetime2(3)` text was normalised; the literal-key and count checks passed on the real T-SQL output; and `WHERE correlation_id IN ('…lowercase…')` matched `uniqueidentifier` columns. The argv flags are now `-S -U -P -C -d -s -y -f -Q` (no `-h`, no `-W`).

**Arm (not published by the implementer).** I changed `-y 0` to `-y 400`: a non-zero width, which is neither the round-1 pair nor a dropped flag. Result: **`orders.outbox.jsonl: expected 17 seeded rows, found 19`**. With a non-zero `-y`, sqlcmd prints its header and dash line again; those have the right field count, so `parse_sqlcmd` accepts them, and the literal row count catches them. I restored from the `cp` backup (`cmp` clean, `__pycache__` cleared) and re-ran green: `ALL EQUAL: True`.

**Equivalent mutant, recorded so nobody counts it as an arm:** `-f 65001` → `-f 1252` still gave `ALL EQUAL: True`, em dash intact. On this Linux `mssql-tools18` build the output codepage flag is inert for this path. It does no harm and the docstring makes no claim about it, so this is not a defect. If #8's container ever ships a sqlcmd that honours `-f`, the flag as written is the correct one.

Cleanup: `docker rm -f -v rev-seedprobe-mssql`. Afterwards `docker ps -a | grep -ci probe` gives `0`, 12 `otcpy` containers are up, and 0 `otcnet` containers are running.

The implementer's own probe found that `-y 0` also excludes `-h`. Round 1's fix hint missed that, and the implementer was right to drop both. The unit pin `test_the_sqlcmd_argv_never_pairs_dash_y_zero_with_dash_w_or_dash_h` holds the argv shape without a server. The behaviour proof is the probe above, which is not in the gate; that is acceptable for a one-shot tool.

### N4 — closed

`STOCK_LIVE_COLUMNS = ("units", "reserved_units", "updated_at")` (`scripts/seed_parity.py:147`). `render()` drops those columns from the failing file, and `render_live()` writes the identity `("id", "company_code", "product_code")` plus the live columns to `*.live.jsonl`. In `diff_dirs`, the line `identical = identical and live` only lets a difference through for a `.live.jsonl` file, and a file present on one side only still fails. Both halves render through `render_files` (`dump_eight` and `collect_nine`), so the two sides cannot render differently. My probe exercised both files on real T-SQL output (above). The three new tests are green: `test_stock_live_columns_are_in_the_live_section_and_not_in_the_failing_file`, `test_a_live_stock_difference_is_reported_but_never_fails_and_an_immutable_one_does`, `test_the_live_file_missing_on_one_side_still_fails`.

Residual, conservative, no action: only `stock` is classified as live. Any other column that #8's live traffic changed (for example a `credits.updated_at`, if #8 touches it) will show as a FAILING difference. That is the right direction for an unknown, and the operator attributes it at the authorised run.

### N1 — closed

`integration/test_seed_write_path_behaviour.py::test_every_row_the_engines_insert_passed_the_range_guard` uses a spy on `ensure_row_in_range`, an engine-level `before_cursor_execute` count of INSERTed rows, and the rows the databases gained. It requires all of them to be 541.

**Arm (not published by the implementer).** This is my round-1 W1 alias, now wired into the real flow for ONE table only, with the guard intact for every other table. In `insert_missing`, for `table.name == "currencies"`, I added `from sqlalchemy import insert as add_rows; run = conn.execute; await run(add_rows(table), list(rows)); return len(rows)` before the guard loop.
- `test_every_row_the_engines_insert_passed_the_range_guard`: **`AssertionError: the range guard saw 538 rows, not 541`**.
- `unit/test_write_path_population.py` against the same mutation: **`11 passed`**, so the AST scan is still blind to it. That is expected; its docstring now states this limit.

I restored from the `cp` backup; `cmp` against both the round-2 and the round-1 backup is clean.

Residual (no action): the wire counter recognises statements that begin with `INSERT`, so an UPDATE-shaped write would escape that counter. Any such write that changes a value is caught by the every-row value test, and any rewrite by the `xmin` idempotence dump.

### N2 — closed

`grep -rn "tests/test_" services/seed/src` has no hits. The four paths now point to `tests/unit/…`: `sagas.py:32`, `deterministic.py:6`, `clock.py:6`, `timeline.py:10`. `clock.py:34` now names `tests/unit/test_seed_instants.py`, the file that actually pins the two formatters to each other.

### N3 — closed

Ledger row "Upsert idempotence" (`impl_seed_job.md:117`) and answer (c) (`:91`) now state #7's actual set clauses with their citations (`updated_at` / `published_at` / `value_date` / `description`, plus `replaceOne` of the 6 documents) and #8's full re-apply (`EfUpsert.cs:25-35`, `FulfillmentSeedWriter.cs:39-46`, `OrdersSeedWriter.cs:37`). These match what I read in round 1.

### Backlog routing (round 1's proposals)

Filed by the leader (seen in `git diff feature_list.json`):
- **211** `number_allocators_start_above_existing_references`, attached to 15, 18 and 21;
- **212** `seed_timeline_constants_pinned_to_projector`, attached to 24.

Both texts carry the acceptance I proposed.

### Acceptance 5 (unchanged, routed)

The tooling is now runnable as one command per half: `dump8`, `dump9`, then `diff`. The flags are proved against #8's own SQL Server image and #8's own column types. The #8-vs-#9 diff itself has **not** been run. Closing id 12 as `done` needs the maintainer's ruling, as stated in round 1's "Routing of acceptance 5": either authorise the live run, or give an explicit "ACCEPTED, NOT FIXED" disposition with its re-open trigger, or a numbered backlog entry.

### CHECKPOINTS delta from round 1

- C4 `quality.sh`: not re-run by me; the implementer reports exit 0, 105.67 s, 904 passed, stack stopped. The affected files ran green here (144).
- C2 `feature_list.json` reflects the true state: id 12 `in_review`, awaiting the maintainer's ruling on acceptance 5.
- C5 history.md effort entry: pending the `done` transition (the leader's). Review effort is given above.
- C5: no stray files. The probe's scratch files are in the session scratchpad, and the throwaway container is removed.

## Review — round 3

**Verdict: REJECTED.** There are 2 blocking defects, both small: B1 is a fix to the test fixtures and B2 is a documentation row. Everything else in round 3 holds, and I checked it with commands of my own (listed below). Acceptance 5 is **met**, backlog 212's seed half is **met**, and backlog 211's SQL is **correct and the right shape**. What fails is one of 211's guards: it does not detect a sibling-column substitution, and that is a mutation family `CLAUDE.md` requires. Following the brief, `feature_list.json` id 12 goes back to `in_progress`; 211 and 212 stay `pending`. Review effort: 18:30 to 18:37 CEST, 2026-10-05, by `date` (one reviewer session, Opus).

Scope: the brief `brief_seed_job_round3.md`, the premise check `premise_seed_job_round3.md`, `impl_seed_job.md` § "Round 3" (lines 235-266), and the working tree. I did **not** re-run `quality.sh` (see item 4). I ran the affected files instead: the three `test_*_counter_seed.py` files, `tests/seed_counters`, `services/seed/tests/unit/test_read_model_constants.py` and `services/seed/tests/integration/test_seed_mongo.py`, giving **`29 passed in 23.28s`**. I also ran `lint-imports` (`Contracts: 10 kept, 0 broken`), `ruff check` and `ruff format --check` on the touched trees (`All checks passed!`, `135 files already formatted`), and `mypy --strict` on the new and changed modules (`Success: no issues found in 4 source files`).

### Did round 3 touch the files rounds 1–2 cover?

I compared the files with round 2's `cp` backups in `scratchpad/rev/`:
- `mongo.py`, `tables.py`, `payloads.py` and `postgres.py` are byte-identical (`diff`/`cmp` silent).
- `domain/timeline.py` differs **only in its module docstring**, which now names the fixture and feature 24. An AST comparison with the docstring removed gives `code-equal ignoring module docstring: True`.
- `test_seed_mongo.py`'s index test now reads its expected options from the fixture. That is a test change, not a behaviour change.

So the round-1 and round-2 arms still exercise the same code, and I did not re-review Parts A–C.

### 1. Acceptance 5: MET (zero failing differences)

**Is `out8` independent evidence, or #9's own output?** I ran an independent check, `scratchpad/r3/oracle_vs_out8.py`, which compares `out8` directly with **#7's oracle** (`services/seed/tests/fixtures/seed_dataset_from_number7.json`, `order_timeline_from_number7.json`) and does not use the script's diff. Verbatim:
```
currencies: EQUAL (3 vs #7 3)
products: EQUAL (12 vs #7 12)
retailers: EQUAL (7 vs #7 7)
companies: EQUAL (22 vs #7 22)
credits: EQUAL (154 vs #7 154)
stock (immutable): EQUAL (215 vs #7 215)
stock (live) rows differing from #7's seeded units: 5; ids identical: True
    OUTILFRANCE PRD-0007 units 492 reserved 0 updated_at 2026-09-18T14:58:40.840Z | #7 (500, 0)
    LONDONTOOLS PRD-0010 units 115 reserved 0 updated_at 2026-09-18T14:56:40.196Z | #7 (500, 0)
    OUTILFRANCE PRD-0004 units 496 reserved 0 updated_at 2026-09-18T14:58:40.840Z | #7 (500, 0)
    OUTILFRANCE PRD-0008 units 490 reserved 0 updated_at 2026-09-18T14:58:40.840Z | #7 (500, 0)
    OUTILFRANCE PRD-0006 units 492 reserved 0 updated_at 2026-09-18T14:58:40.840Z | #7 (500, 0)
orders: EQUAL (6 vs #7 6)
order_timeline documents (whole document): EQUAL (6 vs #7 6)
FAILS 0
```

Three facts show `out8` came from #8 and not from #9:
- `out8`'s live section holds values #9 cannot produce: five rows with `updated_at` 2026-09-18, where #9's `out9` has 500 and `2026-01-01T00:00:00.000Z`.
- #8's git log places its last live stack activity on that day: `feat(compose): full application stack` at 14:27 CEST and the Phase 24/25 demo work until 18:00 CEST.
- The file mtimes in `out8/` are spread over 18:19:05.1–06.9, one per sqlcmd/Mongo round trip. Every file in `out9/` was written at 18:19:11.54.

**Live-stock differences.** There are 5 rows: they explain all 4 hunks of `diff.txt`, the last of which covers two adjacent lines (162-163). All are `units`/`updated_at` changes from #8's own traffic. `reserved_units` is 0 throughout, and units are at or below 500, which is consistent with despatched reservations. The id set is identical. Classification: LIVE-STATE, not a seed difference.

**The subset is the literal list.** `scripts/seed_parity.py:65-125`: `ORDER_IDS`, `RETAILER_CODES`, `SAGA_COMPANIES`, `BASELINE_COMPANIES` and `SAGA_STOCK_PAIRS` are literals. `ORDER_REFERENCES`, `PRODUCT_CODES` and `CREDIT_CODES` are literal ranges. `check_subset` (`:374-397`) fails on any missing key and on any count other than the literal `expected`.

**Every file is non-empty with the expected count.** `wc -l` matches on both sides for all 20 files: 15/154/10/5/21/5, 5/10/12/11/215/215, 6, 22/3/11/6/17/12/7.

No containers were started by me. `docker ps -a | grep -E "^rev-|otcnet"` = 0 at the end.

### 2. Backlog 211: the SQL is correct; one guard is blind (B1)

**Correctness.** The statement is ONE atomic `INSERT … SELECT 1, COALESCE((SELECT MAX(CAST(substring(<ref> FROM 5) AS bigint)) FROM <t>), 0) + 1 WHERE NOT EXISTS (…) ON CONFLICT (id) DO NOTHING`:
- the MAX is numeric (`bigint`, wider than #8's `int`);
- the offset is right: `FROM 5` after a 4-character prefix.

The three files are in step. After masking the names, `diff` shows only the title, the "allocator proper is Phase N" line, and the pre-existing `ADVANCE_*` range-guard paragraph that orders does not have (`scratchpad/r3/{o,f,b}.txt`).

**The no-scan claim (#8 id 47), measured by me.** I ran a throwaway `postgres:18.6` (`rev-r3-pg`, since removed) with 200 000 `ORD-` rows and executed the **real `SEED_ORDER_SEQUENCE` imported from the module**:
- Real statement, counter row present: `InitPlan 1 -> Aggregate (never executed) -> Seq Scan on orders (never executed)`, `Conflicting Tuples: 0`, `Execution Time: 0.073 ms`.
- Real statement, counter row absent (inside a rolled-back transaction): `Seq Scan on orders (actual … rows=200000.00)`, `Tuples Inserted: 1`, `next_value` 200001.
- Unconditional aggregate, counter row present: `Seq Scan on orders (actual … rows=200000.00)`, `Conflicting Tuples: 1`, `Execution Time: 561.218 ms`.
- Aggregate + `WHERE NOT EXISTS` (the brief's warned shape), counter row present: `Result … One-Time Filter … -> Seq Scan on orders (never executed)`, but `Aggregate (actual … rows=1.00)` and `Conflicting Tuples: 1`. Its bare `SELECT` returns `1 | 1`, one row. The real statement's bare `SELECT` returns `(0 rows)`.

**The implementer's claim is confirmed.** The aggregate-on-`WHERE NOT EXISTS` shape also skips the scan, through a one-time filter, but it still emits a row, and that row's value is `1`. That leaves `ON CONFLICT` as the only thing between the steady state and a re-seed at 1. **The chosen select-list-subquery shape is the right one:** it emits nothing on the steady-state path. A `FROM (SELECT MAX…) m WHERE NOT EXISTS` subquery shape and a `HAVING NOT EXISTS` shape also skip the scan with `Conflicting Tuples: 0`, so the chosen shape is one of several valid ones, and the simplest.

**Concurrency.** The 16-first-callers tests and the one-round sentinels are green in all three files (inside the 29). **The serialised-harness arm on fulfillment** (it was published for orders only) used `asyncio.Barrier(1)` and a sequential loop in place of `gather`, and failed with: `AssertionError: the racy seed lost 0 of 16 callers, expected 15: the harness did not release the callers together, so it cannot prove the ON CONFLICT seed`. The 16-callers test passed under the serialised harness, as it should. Restored, `cmp` clean.

**My arms (none of them published).** Each followed the same protocol: `cp` backup, one mutation, one run, restore, `cmp` clean, `__pycache__` cleared.
- **`FROM 5` → `FROM 6`, fulfillment** (the leading digit is dropped). Only the (d) test fails: `assert 100000 == 1000001`. (c) passes, because `000005` → `00005` is still 5. So (d) is the only guard for the offset, and it holds.
- **`… , 0) + 1` → `… , 0)`, billing** (start at MAX, not MAX+1). Three tests fail: the 16-callers test `assert [0, 1, 2, 3, 4, 5, ...] == [1, 2, 3, 4, 5, 6, ...]`, (c) `assert [5, 6] == [6, 7]`, and (d) `assert 1000000 == 1000001`.
- **MAX moved into the `WHERE` clause, orders.** The mutant was `WHERE (SELECT MAX(…) FROM orders) IS NULL OR NOT EXISTS (…)`: the results are unchanged and the scan runs on every call. Only the scan test fails: `AssertionError: the steady-state path scans orders`. The plan has one `never executed` line and one scanning line (`Seq Scan on orders orders_1`). The probe's any-line semantics (`not all(...)`) catches it.
- **Sibling column, fulfillment** (`substring(despatch_reference FROM 5)` → `substring(order_reference FROM 5)`). **`8 passed in 13.12s`: the mutant SURVIVES** every fulfillment counter test and all three cross-service tests.
- **Sibling column, billing** (`invoice_reference` → `order_reference`). **`6 passed in 10.71s`: SURVIVES.**

#### B1 (blocking): the counter guards cannot see a sibling-column substitution

The defect is in `services/fulfillment/tests/integration/test_fulfillment_counter_seed.py:103-113` and `services/billing/tests/integration/test_billing_counter_seed.py:103-113`. Both `_insert_reference` helpers write `order_reference = f"ORD-{reference[4:]}"`: the order suffix **mirrors** the despatch or invoice suffix. `despatches.order_reference` and `invoices.order_reference` are `String(20)` columns in the same table with the same `XXX-######` format (`tables.py:183,234`). So a MAX over the wrong column gives exactly the expected 6/7 and 1000001.

The cross-service test cannot catch this either: the seeded data pairs `DES-00000n`/`INV-00000n` with `ORD-00000n` for n = 1..5 (read from `out9/fulfillment.despatches.jsonl` and `billing.invoices.jsonl`).

This breaks two rules:
- `CLAUDE.md` "Fixtures must not satisfy the assertion's relation by accident: equality → distinct values";
- the mandatory mutation family "substitute a valid sibling identifier".

The implementer's defeat-list row 3 entry ("sibling: `DES-`/`INV-` tables run the same arms", `impl_seed_job.md:260`) is not a sibling substitution. It runs the same mutations in three files, so that claim is wrong.

The production SQL is correct today. The guard is not done until it fails on this mutant.

#### B2 (blocking): no ported-idiom ledger rows for the 211 port

Backlog 211 ports #7's and #8's counter seeding into #9. Under `CLAUDE.md` ("Every port carries one line per idiom … in `progress/impl_<feature>.md` for `sdd: false`"), the ledger at `impl_seed_job.md:107-121` needs rows for it. It has none: round 3 cites #7 and #8 in prose only. The rows must each carry a file and line:
- **numeric MAX:** #7 `order-number-allocator.ts:67` `cast(… as unsigned)`; #8 `EfCoreOrderNumberAllocator.cs:138` and the despatch/invoice allocators `CAST(SUBSTRING(…) AS int)`; #9 `CAST(substring(… FROM 5) AS bigint)`. #9 deliberately differs from #8 in width (`int` → `bigint`).
- **single-statement seed under concurrency:** #8 id 45, `WHERE NOT EXISTS … WITH (UPDLOCK, HOLDLOCK)`; #9 `ON CONFLICT (id) DO NOTHING`.
- **steady-state no-scan:** #8 id 47, a C#-side `if (!sequenceRowAlreadyExists)` at `EfCoreOrderNumberAllocator.cs:128-146`. #8's despatch allocator, `EfCoreDespatchNumberAllocator.cs:30-42`, has no such branch; whether SQL Server skips the derived-table scan there was not probed by me and needs no claim. #9 uses an InitPlan gated by a one-time filter.

Each row also names its armed guard: the (d) test; the 16-callers test plus its sentinel; and the scan test plus its sentinel.

### 3. Backlog 212, seed half: MET

`tests/fixtures/read_model_constants.json` holds the collection, `timelineOrderVersion` 2, the 9-entry rank table, `processedEventKeyPrefix` `projector:`, and the index (name, key, unique, partial filter). These match `timeline.py:27,30,33-43,45` and `mongo.py:22,41-46`. `test_read_model_constants.py` asserts the constants and the written keys (50 keys, every one prefixed). `test_seed_mongo.py` asserts the live index options from the fixture.

My arms (fixture only; the implementer armed other values):
- `"collection": "order_timelines"` → `AssertionError: assert 'order_timelines' == 'order_timeline'` (`test_the_seed_collection_and_index_name_equal_the_fixture`).
- `partialFilterExpression` `$type` `"string"` → `"int"` → `assert SON([('orderR...'string')]))]) == {'orderRefere...type': 'int'}}` (`test_the_partial_unique_index_on_order_reference_exists_and_admits_placeholders`, against a real `mongo:8.3.8`).

Both were restored, `cmp` clean. The seed's values are unchanged (the timeline AST is equal), and the `timeline.py` docstring now names the fixture and feature 24's item.

### 4. `quality.sh`: one-line recommendation

**Accept 108.86 s as within the "~105 s" band. Do not cut for it.** +18 tests, including three real-seed runs, explain about 3 s, and load has moved this gate by several seconds before (99.8 vs 84.6 s, `progress/current.md:39`). Re-measure once at wrap-up with `/usr/bin/time`, and treat a reading above 110 s as a finding.

### Non-blocking notes

- **N1.** 211's acceptance item 1 writes the statement as `INSERT … SELECT 1, COALESCE(MAX(…)) … FROM <table> ON CONFLICT`. That is the scan-every-time shape, the one the tests use as a sentinel. The shipped shape is stricter and correct. When the leader closes 211, the entry's disposition should say the acceptance text is superseded by the no-scan shape (#8 id 47), so the literal text is not taken as the target.
- **N2.** In `tests/seed_counters/test_seeded_counters_start_above_references.py`, `assert reference == f"{PREFIX[database]}-{first:06d}"` compares a literal with a literal once `number == first` has held (defeat row 8). It is harmless but proves nothing; the reference-absent count that follows is the real claim.
- **N3.** The `otcnet-net` network the implementer reported as left over has been removed by the leader. I found no `otcnet` container.

### What must change before re-review

1. **B1.** In the fulfillment and billing `_insert_reference` helpers, give `order_reference` suffixes that are **distinct from, and larger than**, the despatch/invoice suffixes. For example, `ORD-{n + 500:06d}` for the (c) rows, and `ORD-2000000` beside `DES-/INV-1000000` for (d); the unique `order_reference` still needs distinct values. Then arm the sibling substitution (`despatch_reference`/`invoice_reference` → `order_reference`) in both services, with the failure recorded verbatim, and re-run the rest of each file green. Test-only; `sequences.py` does not change.
2. **B2.** Add the three ledger rows above to `impl_seed_job.md`'s ledger, each with the #7 and #8 halves read from the checkouts (file and line), and each naming its armed guard.

### CHECKPOINTS walked (round 3 delta)

- [x] C1 No change to `specs/shared/`; no spec amendment needed. 211 and 212 are filed backlog entries, not `specs/shared/` gaps.
- [x] C2 Traceability: 211(a) → the shape is in the code, plus the scan test; 211(b) → `test_the_max_scan_never_runs_when_the_counter_row_exists` ×3, armed (mine and theirs); 211(c) → `test_a_seeded_database_allocates_the_next_number` ×3 and `test_the_first_allocation_after_the_seed_job_is_above_the_seeded_references[orders|fulfillment|billing]`; 211(d) → `test_a_reference_above_six_digits_starts_the_counter_numerically` ×3, armed (text MAX theirs, offset mine); 211(e) → the 16-callers tests and the sentinels, with the serialised arm on orders (theirs) and fulfillment (mine); 212 → `test_read_model_constants.py` (6) and the index test. Acceptance 5 → `progress/evidence/seed_parity/`.
- [ ] C3 Tests are real and armed: **B1** (a sibling-column mutant survives 14 tests across two services).
- [x] C4 Architecture: `lint-imports` 10 kept. `tests/seed_counters` imports three services and the seed from a neutral tree; no service imports another.
- [ ] C5 Port ledger: **B2** (no rows for the 211 port).
- [x] C6 Conventions: ruff and mypy clean; raw SQL in infrastructure; no `float`, `/` or `Decimal`.
- [x] C7 Hygiene: no git writes; my arms restored with `cmp`; the throwaway container was removed; no stray file in the repository (`git status --porcelain` count unchanged at 49).

## Review — round 4

**Verdict: APPROVED. Blocking: 0.** Light fix round (test fixtures and ledger rows); I ran only the affected files: the three `test_*_counter_seed.py` files, `15 passed in 10.51s` after restore.

1. **B1 closed.** `_insert_reference` in fulfillment (line 113) and billing writes `order_reference = ORD-{int(suffix) + 5_000_000:07d}`, distinct from and larger than the DES/INV suffix. My arm, fulfillment only: `cp sequences.py` backup, `substring(despatch_reference FROM 5)` changed to `substring(order_reference FROM 5)`, ran `test_fulfillment_counter_seed.py -x`: `E assert [5000006, 5000007] == [6, 7]` / `At index 0 diff: 5000006 != 6`, `1 failed, 2 passed`. Restored, `cmp` clean, `__pycache__` cleared, green. The round-3 backups are gone from the scratchpad, so "unchanged by round 4" is shown by content: `grep` of all three `sequences.py` shows `order_reference` (orders), `despatch_reference` (fulfillment) and `invoice_reference` (billing) with `FROM 5` and `bigint`, and the arm restored byte-identically. Orders counter tests pass (included in the 15). Billing's arm is the implementer's record only; I did not re-run it.
2. **`tests/seed_counters/` pairing: sufficient.** The cross-service file asserts the seed-then-allocate relation across services, and the sibling-column mutant is now killed by the per-service files, which are the ones that own `sequences.py`; the paired fixture there is an accident of the relation but is not the sole guard.
3. **N2 closed.** `grep -rn 'first:06d' services/*/tests tests` returns nothing.
4. **B2 closed.** Three ledger rows exist (numeric MAX; single statement under concurrency; steady-state no-scan), each with #7 and #8 file:line halves and a named armed guard. Spot-checks against the checkouts: #7 `order-number-allocator.ts:63-78` (max select then `onDuplicateKeyUpdate`, confirmed not atomic); #8 `EfCoreInvoiceNumberAllocator.cs:30-45` (`INSERT ... WHERE NOT EXISTS ... UPDLOCK, HOLDLOCK`, confirmed); #8 `EfCoreOrderNumberAllocator.cs:127-146` (`if (!sequenceRowAlreadyExists)` branch, confirmed) and `EfCoreDespatchNumberAllocator.cs:28-42` (no branch, confirmed).

CHECKPOINTS delta: C3 [x], C5 [x]; all other boxes as in round 3. `feature_list.json`: ids 12 (was `in_progress`, not `in_review`), 211 and 212 set to `done`, three status lines only. The effort record in `progress/history.md` was not re-checked this round; the leader owns that append.
