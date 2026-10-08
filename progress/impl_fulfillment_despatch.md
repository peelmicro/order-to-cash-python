# Implementation report — feature 18 `fulfillment_despatch` (phase 9, `sdd: false`, full group)

Status: **`in_review`** (feature 18's `status` line only). `./quality.sh` exits **0** (final run after the last code change: 334 s, **2784 passed**, overall coverage 97.98 %, domain 99 %; `init.sh` exit 0). Baseline before any change (developer stack down, only `otcpy-n8n` up): exit 0, 316 s, **2690 passed**. Delta **+94**, counted by `pytest --collect-only` over the nine new files: unit 71 (`unit/domain/test_despatch.py` 17, `test_despatch_creation_service.py` 10, `test_despatch_wire.py` 38 [13 functions, parametrised], `test_despatch_payload.py` 3, `test_despatch_transactions.py` 3) and integration 23 (`test_despatch_create.py` 7, `test_despatch_number_allocator.py` 6, `test_despatch_race.py` 3, `test_despatch_store.py` 7); the two existing tests edited for a literal changed no count. Nothing was committed or pushed. **Packages installed: none.** No migration, no `models.py` / `range_guards.py` / `types.py` / `alembic/` edit (the unique-key arm touched `alembic/versions/0001_…py` temporarily and restored it from the backup with `cmp`), no `services/orders`, `packages`, other service, root `pyproject.toml`, `specs/fulfillment_stock/` or `CLAUDE.md` edit.

## 1. What was built

`despatch.create` end to end, the sixth subject of the one responder.

- **Domain.** `domain/despatch_advice.py` (`DespatchAdvice` aggregate root, `DespatchLine`, `line_order_key`): `create` refuses an empty line list (F6, `EmptyDespatchLinesError`, code `despatch.empty_lines`) and appends the one `OrderDespatched` before returning; nothing is minted inside it. `domain/order_despatch.py` (`despatch_order`, `Despatched` / `NothingToDespatch`): calls `StockItem.consume` on each item in lock order, builds one line per consumed reservation 1:1 (F7), mints the advice id, then one line id per reservation in consumption order, then the event id, all from the required `new_id`. `domain/events.py` gained `DespatchedLine`, `OrderDespatched(StockEventBase)` and `FulfillmentEvent = StockEvent | OrderDespatched` (the stock aggregate's `record_order_fact` still accepts only `StockEvent`); `domain/snapshot.py` gained `DespatchSnapshot` / `DespatchLineSnapshot`; `domain/errors.py` gained `EmptyDespatchLinesError`.
- **Application.** `application/despatch_creation.py` (`create`, `_despatch_work`, `NoReservedStockForDespatchError`); `CreateDespatchCommand` / `DespatchResult` in `messages.py`; `CreateDespatchHandler` in `handlers.py`; the ports `DespatchRepository`, `DespatchNumberAllocator`, `ConcurrentDespatchChangeError` and `StockReads.despatch_of_order` in `ports/stock_store.py`; `StockTransaction` now exposes `despatches` and `despatch_numbers` beside `repository`. The flow (module docstring): F8 fast path (no transaction) -> SA-4 pre-read `stock_keys_of_order` (none -> refuse) -> `run(work)`: **`lock_order_items`** (the very method `stock.release` calls) -> no `reserved` reservation: `consumed` present -> **in-lock re-read** of the advice -> reply it `created=False` (none found -> `ConcurrentDespatchChangeError`), else refuse -> allocate `DES-` -> `despatch_order` -> save the stock rows (status + both counters) -> save the advice, lines and fact.
- **Infrastructure.** `persistence/despatch_number_allocator.py` (the Orders allocator's three statements over `sequences.py`); `persistence/despatch_repository.py` (`load_despatch`, `SqlAlchemyDespatchRepository`: plain INSERTs, the outbox rows in the same session, `clear_saved_events` after the commit); `StockReads.despatch_of_order` (own short `READ COMMITTED` session); `stock_transactions.py` builds the despatch repository and the allocator on each attempt's session and clears their events after the commit (a new injectable `despatch_repository_factory`, the seam the fault injection uses); `outbox/payloads.py` maps `OrderDespatched` (`narrow` accepts it, `build_fact` has its fourth `match` arm under the same `assert_never`); `messaging/subjects.py` gained `DESPATCH_CREATE_SUBJECT`.
- **Presentation / composition.** `stock_responder.py`'s `ROUTES` gained one entry (`_despatch`: headers first, then decode, then dispatch); `stock_wire.py` `decode_despatch` / `despatch_reply` (the length edge check of FS28 applies); `stock_rpc_errors.py` two rows; `composition.py` one registration statement.

Files touched (all inside the brief's bounds; `git status --porcelain` classification in § 12).

## 2. Decisions and deviations (argued, none silent)

1. **Both headers required on `despatch.create`** (`x-correlation-id` = the order id, `x-request-id` = the saga command id), like reserve and release. The spec's request schema carries only `orderReference`, but R12 needs the fact's `correlationId` and `causationId`. #7 (`CreateDespatchCommand` carries `correlationId` / `requestId`) and #8 (`D/Application/DespatchCreationService.cs:136`, `CreateDespatchCommand(OrderReference, CorrelationId, RequestId)`, "extracted from the request's headers by the responder") agree. Live: no headers -> `VALIDATION_FAILED`.
2. **The fact's `aggregateId` is the despatch advice's own id** (#7 `despatch-events.ts` header comment, #8 `OrderDespatch.cs:84`), not a stock item's. Test: `test_fs24_the_advice_id_is_the_first_supplied_id_and_is_the_facts_aggregate_id` and the integration `fact["aggregate_id"] == advice["id"]`.
3. **Line ids are minted in the domain through `new_id`, and are guarded.** Both predecessors minted the `despatch_items` ids in infrastructure with an unseamed generator (#7 `despatch.repository.ts:64`, #8 `EfCoreDespatchRepository.cs:77`); #9's domain rule is "UUID keys generated in the domain" and #8's id 49 lesson is "a seam is a property only if every site uses it", so the line ids are a third mint-site kind (advice, line, event) and the repository mints nothing (arms I6, I7_v2).
4. **Canonical line order `(product_code, line id)`**, sorted in the aggregate and again in Python on reload. The line table has no position column and every `created_at` of one advice is the same instant, so #7's `ORDER BY created_at` (`despatch.repository.ts`, "orderBy(asc(despatchItems.createdAt))") would be a tie in #9; a database `ORDER BY product_code` would depend on the collation. The repeat (F8) therefore answers with the creation's line order (`test_fs24_every_id_…` asserts it after the reload; `test_f8_a_stored_advice_is_reloaded_in_the_canonical_line_order_…` inserts the rows in a non-canonical physical order; arms D13, I13).
5. **`ConcurrentDespatchChangeError` -> `UNAVAILABLE`** for "reservations are `consumed` but no advice exists". #7 raised a plain `Error` (-> `INTERNAL_ERROR`, `despatch-creation.handler.ts:88`), #8 `ConcurrentDespatchChangeError` -> `UNAVAILABLE` (`StockErrorMapper.cs`, `DespatchCreationService.cs:68`); both are transient in Orders' set, so the saga behaviour is the same; I adopted #8's named error.
6. **The F8 unique key is not reached by removing the in-lock re-read** (the brief expected it to be). See § 9: with the re-read removed the loser sees `consumed` and no `reserved` reservation, so it replies `UNAVAILABLE` (re-read gone) or `PRECONDITION_FAILED` (the whole branch gone); the unique key only meets a request that believes the order is still `reserved`, which needs the lock removed as well. The key's own claim is proved at the store level (§ 9, `I18`).
7. **`StockReads` gained `despatch_of_order`** (the F8 fast path's read) rather than a seventh port or a new scope field: `FulfillmentScope` keeps its four ports and the three existing test constructions of it are untouched. The SQL is shared with the in-lock re-read through one function (`load_despatch`), so the fast path and the re-read cannot disagree on the shape.
8. **`OrderDespatched` extends `StockEventBase`** (its name is now a misnomer; renaming a feature-17 type was out of scope). Flagged for the reviewer.
9. **Edits to feature-17 tests, named:** `unit/test_stock_responder.py` (the `[1] * 5`, `== 5` and `index == 5` literals became `len(ROUTES)`, with `assert len(ROUTES) == 6` stated once), `integration/test_fulfillment_host_lifespan.py` (the expected unregistered-handler list gained `CreateDespatchCommand`). I did **not** rename `test_fs4_…_on_all_five_subjects` or `test_f1_each_of_the_five_subjects_…`: they are accurate about the five stock subjects, and `specs/fulfillment_stock/requirements.md:140` and `tasks.md:107` cite them by name. The despatch counterparts are `test_fs4_the_despatch_reply_is_a_bare_compact_json_payload_…` and `test_despatch_wire.py`.
10. **Architecture-test edits, each because a pinned literal or census needs the new code:** `test_registration_behaviour.py` `TABLES["fulfillment"]` gained `CreateDespatchCommand` (seen red before the edit, § 8 `C2`, and in `.arm/impl18/registration_red_before.txt`: `At index 0 diff: '…CreateDespatchCommand' != '…ReleaseStockCommand'`); `test_write_path_population.py` `EXPECTED["fulfillment"]` gained `despatch_number_allocator.py` (`execute` x3, `text` x3) and `despatch_repository.py` (`add` x2), counts read from the scan's own failure output, each with its classification (arm `C3`); `test_fulfillment_rpc_error_retryability.py` `EVERY_INPUT` / `TRANSIENT_STORE_FAILURES` gained the two despatch errors (`>= 8` -> `>= 9`). `test_composition_env_reads.py` and `test_fulfillment_settings_env.py` need no edit: no settings class was added.
11. **`specs/shared/test-matrix.md`**: column 5 of R36 only (`TODO` -> `DONE` plus the named tests), and the derived counts: row 4 `6 / 0 / 2` -> `7 / 0 / 1`, total `30 / 1 / 32` -> `31 / 1 / 31` (R61's API half is still open, so its row is still not green).
12. **`sequences.py`'s docstring** said "the allocator proper is Phase 9"; it now names `despatch_number_allocator.py`. No SQL changed.

## 3. The ported-idiom ledger (CLAUDE.md "Porting from #7 and #8")

"#7 relied on X; #8 supplied it with Y; in #9 it is supplied by Z". Paths: `N` = `../order-to-cash-nestjs/apps/fulfillment/src`, `D` = `../order-to-cash-dotnet/src/Fulfillment`. Probed both ways where the row says so.

| # | Idiom | #7 relied on | #8 supplied | #9 supplies | Guard (arm) |
|---|---|---|---|---|---|
| L1 | id provenance: advice id, line ids, event id | `UniqueId.generate()` handed to the domain (`N/application/despatch-creation.handler.ts:109`, `N/domain/order-despatch.ts:68`); the **line ids** minted in the repository (`N/infrastructure/persistence/despatch.repository.ts:64`, unguarded) | `UniqueId.New` handed to the domain (`D/Application/DespatchCreationService.cs:94`), advice and event ids `newId()` (`D/Domain/OrderDespatch.cs:84,93`); the **line ids** `Guid.NewGuid()` in the repository (`D/Infrastructure/Persistence/EfCoreDespatchRepository.cs:77`, unguarded) | the required `new_id` parameter at **five** sites: `order_despatch.py` advice / line / event, the application's hand-over (`despatch_creation.py: new_id=scope.ids.new`), and the persistence mapping (`despatch_repository.py` uses `advice.id` / `line.id`, mints nothing) | `test_fs24_*` x4 (domain), `test_r36_creates_the_advice_under_the_lock_…` (application), `test_fs24_every_id_of_the_advice_…` (store, equality with supplied ids, then the repeat asks for none). Arms D1 D2 D3 D4 D4b D5 A1 I6 I7_v2 |
| L2 | the `DES-` allocator under `FOR UPDATE` | self-initialising counter, numeric `MAX` of the suffix, `SELECT … FOR UPDATE` + `UPDATE` (`N/infrastructure/persistence/despatch-number-allocator.ts:16` class, `:45` `.for('update')`; MySQL `ON DUPLICATE KEY UPDATE`) | `INSERT … SELECT … WHERE NOT EXISTS (… UPDLOCK, HOLDLOCK)` then `UPDLOCK, ROWLOCK` then advance (`D/Infrastructure/Persistence/EfCoreDespatchNumberAllocator.cs:28-55`); copied from the FIXED Orders allocator after #8 ids 45 / 47 | Orders' #9 allocator shape (`otc_orders/…/order_number_allocator.py`) over the existing `sequences.py` constants: seed `INSERT … WHERE NOT EXISTS … ON CONFLICT DO NOTHING` (one atomic statement), `SELECT … FOR UPDATE`, `UPDATE`; the session is the transaction's | the six ported allocator tests (§ 5). Arms I8 I9 I9b I10 I11 |
| L3 | F8 idempotent repeat, layer 1: the fast path | `findByOrderReference` first, no transaction (`N/application/despatch-creation.handler.ts:59`) | same (`D/Application/DespatchCreationService.cs:37`) | `scope.reads.despatch_of_order` before any transaction | unit `test_f8_the_fast_path_returns_…`, store `test_f8_the_fast_path_answers_a_repeat_from_a_plain_read` (a held stock row proves no lock is taken). Arms A3 I15. **Equivalent at the integration level** (X9): the in-lock layer answers the same reply, by design |
| L4 | F8 layer 2: the in-lock re-read | a re-read after `lockByIdsForOrder` (`N/…/despatch-creation.handler.ts:79-91`) whose correctness, **by my reading and not probed here**, rests on the isolation level being left at the engine's default (`N/…/drizzle-unit-of-work.ts:75` passes no isolation option) and on the first plain SELECT of the transaction being this re-read, after the lock (the earlier `findByOrderReference` ran on the pool, outside the transaction) | same code under SQL Server RCSI: `EfCoreUnitOfWork` opens `IsolationLevel.ReadCommitted` explicitly (`D/Infrastructure/Persistence/EfCoreUnitOfWork.cs:21,40`), which under RCSI makes the snapshot statement-scoped; the re-read at `DespatchCreationService.cs:67` is un-hinted (**#8 id 54**) | `SqlAlchemyStockTransactions.run` pins `READ COMMITTED` before the first statement of every attempt (`stock_transactions.py`), so the re-read in `_despatch_work` is a new statement with a new snapshot taken after `lock_order_items` was granted. Under `REPEATABLE READ` the **lock itself** fails with `40001` (measured by 17, and again by arm I4: the loser replies `UNAVAILABLE`, message `the stock store is temporarily unavailable (40001)`) | integration `test_f8_two_concurrent_despatches_…` (a held lock queues both; one `created: true`, one `created: false`, same advice). Arms I3a_v2 (re-read removed -> `UNAVAILABLE`), I3b_v2 (branch removed -> `PRECONDITION_FAILED`), I4_v2 (the pin -> `REPEATABLE READ`), A6 |
| L5 | F8 layer 3: the unique key as the last line | `uq_despatches_order_reference`, plain INSERT never an upsert (`N/…/despatch.repository.ts` header) | same constraint (`D/Infrastructure/Persistence/Configurations/DespatchConfiguration.cs:29`) | `despatches.order_reference` UNIQUE (feature 17's migration); `save` is plain INSERTs, no `ON CONFLICT`; a violation is `23505`, not transient, re-raised unchanged by `run`, rolls the attempt back, and is answered `INTERNAL_ERROR` (transient in Orders; the retry takes the fast path) | `test_f8_the_unique_key_refuses_a_second_advice_for_one_order_and_rolls_the_attempt_back` (+ control: a different order's advice is accepted by the same path), unit `test_f8_a_unique_violation_on_the_order_reference_is_internal_error_a_transient_answer`. Arm I18 |
| L6 | SA-4: one lock for release and despatch | `stockIdsOfOrder` + `lockByIdsForOrder` (`N/application/despatch-creation.handler.ts:64,70`), the same pair `stock.release` calls | `ProductCodesOfOrderAsync` + `LockForOrderAsync` (`D/Application/DespatchCreationService.cs:46,55`), the same `stock.release` calls | `StockReads.stock_keys_of_order` + `StockRepository.lock_order_items`, **the very two methods** `stock.release` calls (`design.md` 6.3), keys handed through `distinct_stock_keys` | race in both outcomes (`test_despatch_race.py`), the despatch-alone wait (`test_fs25_a_despatch_waits_…`), the read order (`test_despatch_store.py::test_fs25_the_despatch_lock_reads_…`, **#8 id 79's despatch half**). Arms I1a_v2 I1b_v2 I1c_v2 I2 A5 |
| L7 | the consume transition (`reserved -> consumed`, both counters) | `StockItem.consume` (feature 17 in #7), called per item by the pure order operation (`N/domain/order-despatch.ts:56`) | `OrderDespatch.Create` calls `item.Consume` (`D/Domain/OrderDespatch.cs:72`) | `StockItem.consume` (feature 17, FS11) called by `despatch_order`; the mapper persists status and both counters through the existing `apply_reservation` / `apply_item` | domain `test_r36_consumes_every_reserved_reservation_…` (statuses, `units` and `reserved_units` of each item, another order's reservation untouched), integration happy path. Arms S1 S2 S3 D6 A8 X3 |
| L8 | the outbox fact | one `order.despatched.v1` from the aggregate, drained inside the same transaction (`N/…/despatch.repository.ts:70`, `outboxRecorder.record(tx, despatch.pullDomainEvents())`) | `DespatchRepository.SaveAsync` drains the aggregate's one event into the outbox (`D/Application/DespatchCreationService.cs:111`) | `SqlAlchemyDespatchRepository.save` writes the outbox rows through the same `OutboxWriter` in the same session; the stock repository's `save` emits none (`consume` appends no event) | integration `len(outbox) == 2` (the reserve's fact and this one), unit payload mapping with distinct sources, **fault injection** (§ 6). Arms D14 I5 I17 P1 P2b P3 P4 |
| L9 | the reply shape | `DespatchCreateReplyPayload` with `created` and `lines` (`N/…/despatch-creation.handler.ts:21` `replyFromSnapshot`) | `BuildReply` / `BuildReplyFromAdvice` (`D/Application/DespatchCreationService.cs:40,70,113`) | generated `DespatchCreateReplyPayload` through `to_wire_json`: `created: false` is WRITTEN, `lines` always present; both reply paths (created / repeat) go through one `DespatchSnapshot` -> `despatch_reply` | `test_r36_the_despatch_reply_carries_every_field_…[True/False]`, `test_fs4_the_despatch_reply_is_a_bare_compact_json_payload_…`. Arms W5 W6 |
| L10 | Python: integer division, serialisation, loop affinity, cancellation, typing | n/a | n/a | no `/` in any new line (`grep -n ' / '` over the five new source files has no hit (exit 1)); the instant is the clock port's whole millisecond and goes through `to_wire_json` (never `isoformat`); every new async fixture is function-scoped and its engine is disposed in the loop that created it; the fault-injection `RaiseAfterSave` raises a plain `Exception` subclass (cancellation is not swallowed anywhere new); `mypy --strict` over the whole workspace passes with no `Any` leaking from the new code | `tests/architecture/test_money_guard.py` (the domain's AST guard) green; `quality.sh` step 3 |

## 4. The error table (every failure `despatch.create` can answer)

Orders' classes from `TERMINAL_RPC_ERROR_CODES` (`nats_saga_commands.py:65-75`): nine terminal, three transient (`TIMEOUT`, `UNAVAILABLE`, `INTERNAL_ERROR`).

| Failure | Code | Orders' class | #7 answered | #8 answered | Unit test / arm |
|---|---|---|---|---|---|
| body not JSON / fails the generated model / `orderReference` > 20 chars / a required header absent or malformed | `VALIDATION_FAILED` | terminal | `VALIDATION_FAILED` | `VALIDATION_FAILED` | `test_despatch_wire.py` (8 refused bodies, 7 header faults; nothing dispatched; arms W2 W4) |
| `NoReservedStockForDespatchError`: never reserved (pre-read empty) or every reservation released | `PRECONDITION_FAILED`, `details.orderReference` | terminal | `PRECONDITION_FAILED` (`N/presentation/rpc-error-mapper.ts:63-76`) | `PRECONDITION_FAILED` (`D/Presentation/Rpc/StockErrorMapper.cs:49`) | `test_r36_no_reserved_stock_is_precondition_failed_with_the_order_reference` (arms E1 E3) |
| `ConcurrentDespatchChangeError`: `consumed` reservations, no advice | `UNAVAILABLE` | transient | `INTERNAL_ERROR` (plain `Error`) | `UNAVAILABLE` | `test_f8_consumed_reservations_without_an_advice_are_unavailable_…`, architecture `test_fs21_…` (arm E2) |
| `ConcurrentReservationChangeError` (the lock's defensive branch) | `UNAVAILABLE` | transient | `CONFLICT` | `UNAVAILABLE` | feature 17's row, unchanged |
| deadlock victim after 3 attempts, `40001`, `55P03`, `57014`, `53300`, class `08`, pool timeout, refused connection (`StoreUnavailableError`) | `UNAVAILABLE` | transient | `INTERNAL_ERROR` | `UNAVAILABLE` | feature 17's rows, unchanged; the despatch work is re-run whole by `run()` on `40P01` |
| unique violation `23505` on `despatches.order_reference` (F8's last line) | `INTERNAL_ERROR` | transient | `INTERNAL_ERROR` (unmapped) | `UNAVAILABLE` (`DbUpdateConcurrencyException`/`SqlException` rows) | `test_f8_a_unique_violation_on_the_order_reference_is_internal_error_a_transient_answer`; the text never carries the SQL |
| `EmptyDespatchLinesError` (F6, defensive: `despatch_order` never builds an empty advice) | `DOMAIN_ERROR`, `details.code` | terminal | `DOMAIN_ERROR` | `DOMAIN_ERROR` | covered by the existing `DomainError` row; the aggregate's own F6 test |
| anything else | `INTERNAL_ERROR` (no exception text) | transient | `INTERNAL_ERROR` | `INTERNAL_ERROR` | feature 17's row |
| `CONFLICT`, `TIMEOUT`, `ORDER_NOT_CANCELLABLE`, `STOCK_UNAVAILABLE`, `INVOICE_NOT_PAYABLE`, `PAYMENT_MISMATCH` | never produced | | | | `test_no_row_of_the_mapping_produces_a_code_that_is_never_produced` (feature 17's, population unchanged) and architecture `test_fs21_no_input_produces_conflict` (population now includes both despatch errors) |

#7 and #8 agree on every row that matters to the saga (`PRECONDITION_FAILED` for the R36 refusal); they differ only on the inconsistency, where both are transient. No row needed a stop.

## 5. The allocator's tests: Orders' six, classified

`services/orders/tests/integration/test_order_number_allocator.py` has six tests; all six are ported to `services/fulfillment/tests/integration/test_despatch_number_allocator.py` against `despatch_number_sequences` / `DES-`. Seeding, MAX-scan cost and the sixteen-first-callers race of the SQL constants were already feature 17's (`test_fulfillment_counter_seed.py`, 5 tests, untouched); this file tests the allocator CLASS.

| Orders' test | Class | Port |
|---|---|---|
| `test_concurrent_allocations_in_separate_transactions_are_gap_free_and_unique` | ported | same name; 24 callers behind a barrier, one pooled connection each; arms I8 (advance by 0), I9b (no `FOR UPDATE`: 24 callers got `DES-000001`, then 23 x `DES-000002`) |
| `test_an_uncommitted_allocation_holds_the_next_allocator_back_and_it_gets_the_next_number` | ported | same name; the counter row exists first, as the original's comment requires; arm I9 (`'DES-000002' == 'DES-000003'`) |
| `test_a_rolled_back_transaction_burns_no_number` | ported | same name |
| `test_the_allocation_belongs_to_the_unit_of_work_s_transaction` | ported, **re-aimed** | `test_the_allocation_belongs_to_the_stock_transactions_transaction`: through `SqlAlchemyStockTransactions.run` and `tx.despatch_numbers`, the real path (Fulfillment has no `SqlAlchemyUnitOfWork`); arm I11 |
| `test_seeding_over_a_non_empty_orders_table_continues_above_its_maximum` | ported | `…_non_empty_despatches_table_…`; arm I10 (a `VALUES (1, 1)` seed) |
| `test_the_reference_grows_past_six_digits_instead_of_truncating` | ported | same name (`DES-1000000`) |

Not applicable: none; not ported: none.

## 6. Atomicity by fault injection (#7's proof), with its control

`test_despatch_store.py::test_j4_a_failure_after_the_advice_was_saved_leaves_no_advice_no_line_no_fact_no_burned_number_and_every_reservation_reserved`. Setup: two reserved orders on two products; the first despatch succeeds (so the counter row exists, `next_value` 2, one fact); the second runs with `despatch_repository_factory=RaiseAfterSave`, a subclass whose `save` runs the real `save` (header, lines, outbox row, all flushed) and THEN raises `InjectedFaultError`. After it: every table (`stock`, `reservations`, `despatches`, `despatch_items`, `despatch_number_sequences`, `outbox`) compared whole against its pre-fault copy, plus the faulted order's two reservations still `reserved`.

**The control** (`test_j4_control_the_probe_reports_an_orphan_fact_when_the_outbox_write_is_outside_the_transaction`): the same raise with the outbox written on its OWN session and committed at once (`AutonomousOutbox`, injected through the same factory seam) must leave `despatches == []` and exactly one `order.despatched.v1` outbox row with the supplied `event_id`: the probe sees an orphan. **The production arm** (I5): the repository's `save` moved to a separate session -> the atomicity test fails with `no fact (zero rows for the faulted order)` and the extra row `event_type: order.despatched.v1, aggregate_id: …0bd`.

## 7. SA-4, both outcomes, and F8's concurrent pair (all constructed, none repeated)

`test_despatch_race.py`: the test holds the first stock row, sends the request that must win, waits until it is seen UNGRANTED in `pg_stat_activity` (`Db.wait_for_lock_waiters`, 15 s bound, 20 ms poll), sends the loser, waits for the count to reach 2, and only then commits the hold. Row-lock waiters are served in arrival order.

- **release wins** -> release `released`, despatch `PRECONDITION_FAILED` (`details.orderReference`), no advice, reservations `released`, counters back to before (`10 / 1`, `20 / 2`), outbox `[stock.reserved.v1, stock.released.v1]`, no `DES-` counter row.
- **despatch wins** -> despatch `created: true`, release `PRECONDITION_FAILED` (`details.code == "reservation.terminal"`), reservations `consumed`, counters `7 / 1` and `15 / 2`, outbox `[stock.reserved.v1, order.despatched.v1]`.
- **the despatch alone waits** (`test_fs25_a_despatch_waits_for_a_transaction_holding_a_stock_row_of_the_order_before_reading_its_reservations`): the despatch half of #8 id 79's lock test, failing with a message that names the despatch.
- **the read order** (`test_despatch_store.py::test_fs25_the_despatch_lock_reads_the_orders_reservations_only_after_the_stock_lock_and_consumes_one_committed_while_it_waited`): a reservation inserted by the holder while the despatch waits must be consumed; arm I2 (swap the two reads in `lock_order_items`, as 17's R1 did) -> `the despatch read the order's reservations BEFORE the stock lock was granted: the reservation committed while it waited was not consumed`.
- **F8's concurrent pair** (`test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number`): both requests pass the fast path, queue on the held row, both seen ungranted; after the commit exactly one reply has `created: true`, one `created: false`, with the same reference, date and lines; one `despatches` row, two lines, one fact whose `causation_id` is the creating request's, `next_value` 2.

Arms (verbatim in the appendix): I1a_v2 / I1b_v2 / I1c_v2 (the stock `FOR UPDATE` removed) fail with `the despatch never waited on the held stock row: … so the despatch does not take the SA-4 lock (FS25)`, `fulfillment.stock.release never waited on the held stock row: it does not take the lock`, `fulfillment.despatch.create never waited on the held stock row: it does not take the lock`. **Removing the lock removes it for release and reserve too** (the lock lives in the shared `_lock_stock_rows`); the despatch-only claim is held by the despatch-named test and by A5 (the despatch hands the lock sorted distinct keys).

## 8. The three layers of F8 and what the unique key does (the brief's question)

| Arm | Reply of the losing request of the concurrent pair |
|---|---|
| I3a_v2: in-lock re-read replaced by `None` | `UNAVAILABLE`, message `order ORD-000042 holds consumed reservations but has no despatch advice` (transient; the retry answers from the fast path) |
| I3b_v2: the whole `CONSUMED` branch removed | `PRECONDITION_FAILED` (terminal; **wrong**, a legitimate idempotent repeat would be rejected by the saga) |
| I4_v2: `REPEATABLE READ` pinned instead | `UNAVAILABLE`, message `the stock store is temporarily unavailable (40001)` (#8 id 54's "permanent UNAVAILABLE", measured) |

In none of them does the unique key decide, because in each the loser reads the reservations AFTER the lock and sees `consumed`. The key is reached only by a transaction that believes the order is still `reserved`, which needs the lock gone as well (then the second transaction's INSERT fails `23505`, the attempt rolls back whole, and the reply is `INTERNAL_ERROR`, transient). I did not build a constructed race for that combination (it needs two transactions to read `reserved` concurrently with no lock to hold them, i.e. repetition); the key's own claim is proved directly: `test_f8_the_unique_key_refuses_a_second_advice_…` calls `tx.despatches.save` for an order that already has an advice, expects `IntegrityError` with sqlstate `23505`, and asserts every table is byte-identical afterwards; arm I18 (the constraint removed from the migration) -> `DID NOT RAISE IntegrityError`. The reply mapping for `23505` is a unit test.

## 9. Branch enumeration: every branch of the new code and the test that drives it

| Branch | Test (arm) |
|---|---|
| `create`: advice already exists -> reply it, `created=False`, no transaction, no pre-read | `test_f8_the_fast_path_returns_the_existing_advice_without_a_transaction_or_a_lock` (A3); store `test_f8_the_fast_path_answers_a_repeat_from_a_plain_read` (I15) |
| `create`: no reservation of the order at all -> refuse, no transaction | `test_r36_an_order_that_never_held_a_reservation_is_refused_without_a_transaction` (A4); integration `test_r36_an_order_that_holds_no_reservation_…` |
| `create`: keys -> `distinct_stock_keys` | `test_sa4_the_despatch_takes_the_release_lock_on_the_distinct_keys_in_code_point_order` (A5) |
| `_despatch_work`: a `reserved` reservation exists -> allocate, consume, save, reply `created=True` | `test_r36_creates_the_advice_under_the_lock_in_the_documented_order_with_the_supplied_ids` (A1 A2 A8 A9 A10 A13), integration happy path (X3 X8 I16 I17) |
| `_despatch_work`: no `reserved`, `consumed` present, re-read finds the advice -> `created=False` | `test_f8_a_repeat_that_raced_the_fast_path_is_answered_by_the_in_lock_re_read` (A6 A11), the concurrent pair (I3a_v2 I3b_v2 I4_v2) |
| `_despatch_work`: no `reserved`, `consumed` present, re-read finds nothing -> `ConcurrentDespatchChangeError` | `test_consumed_reservations_with_no_advice_are_a_transient_inconsistency_not_a_refusal` (A12) |
| `_despatch_work`: no `reserved` and no `consumed` (all released) -> refuse, nothing allocated | `test_r36_an_order_whose_reservations_were_all_released_is_refused_and_nothing_is_written` (A7); integration released-only |
| `_despatch_work`: `NothingToDespatch` (defensive) | `test_a_reserved_row_the_loaded_items_do_not_hold_despatches_nothing_and_is_refused` (B8) |
| `_despatch_work`: `Despatched` -> save stock then advice | same as the happy row |
| the reply only after `run()` returns; a rollback produces no reply | `test_the_reply_is_returned_only_after_run_returns`, `test_a_rollback_propagates_and_produces_no_reply` |
| `despatch_order`: consumed non-empty / empty; company and retailer from the first consumed reservation | `test_r36_*` x4 domain tests (D6 D8 D10 D11) |
| `DespatchAdvice.create`: F6 refusal / creation; the sort; the one fact | `test_f6_*` x2, `test_the_lines_are_held_in_the_canonical_order_…` (D12 D13 D14) |
| `load_despatch`: not found / found; the Python sort | store `test_f8_a_stored_advice_is_reloaded_in_the_canonical_line_order_…` (I13) and its control row (`despatch_of_order("ORD-000099") is None`) |
| `SqlAlchemyDespatchRepository.save`: header, lines, outbox, in the transaction | J4 (I5 I6 I7_v2) |
| `run()`: clear the despatch events after the commit / keep them on rollback | `test_the_despatch_events_are_cleared_only_after_the_commit_returned` (T1 T2), `…_kept_when_the_attempt_rolls_back` (T3 is the identity control, green) |
| `_despatch` route: headers first, decode, dispatch; refusals | `test_despatch_wire.py` (W1 W2 W3 W4) |
| `despatch_reply`: `created` true / false, lines | `test_r36_the_despatch_reply_carries_every_field_…[True/False]` (W5 W6) |
| `map_error`: two new rows, the unmapped `23505` | `test_despatch_wire.py` error table tests (E1 E2 E3) |
| `build_fact` / `narrow`: `OrderDespatched` | `test_despatch_payload.py` (P1 P2b P3 P4) |
| composition: the handler registered; the boot validation | architecture registration guard (C1 C2), host lifespan test (edited list) |

## 10. Inherited findings, avoided or recurred

| Finding | Disposition | Evidence |
|---|---|---|
| #8 id 54 (the un-hinted in-transaction re-read) | **avoided** | ledger L4: the pin is explicit in `run()`, the re-read sits after `lock_order_items`, and arm I4_v2 shows what `REPEATABLE READ` does (`40001` -> `UNAVAILABLE`) |
| #8 id 79 (SA-4's one lock; the read order) | **avoided** (despatch half; the release half was 17's) | L6, § 7, arms I1 I2 |
| #8's round-1 rejection: a test whose assertions contradicted its name (`NotEqual` where the name said "is minted by") | **avoided** | every `test_fs24_*` asserts EQUALITY with an id the test supplied; one arm per site (D1 D2 D3 D4/D4b crossed, I6 I7_v2 at the repository, A1 at the application). every new test name was read back against its assertions before submitting (the read-back found one misnamed local, `six` for a six-digit reference in `test_f2_the_boundary_values_of_the_despatch_request_are_accepted`, renamed `usual`; no assertion contradicted its name) |
| #8 id 49's lesson (count the sites when you add the seam) | **avoided**, with a count | five mint sites, enumerated by search: `grep -n 'new_id()\|UniqueId.new\|uuid4\|ids.new'` over the five new source files -> `order_despatch.py:64,66,69` (`advice_id`, the line comprehension, `event_id`), `despatch_creation.py:115` (`new_id=scope.ids.new`), and no hit in `despatch_repository.py`, `despatch_advice.py` or `despatch_number_allocator.py`; the writer's `uuid4()` for the outbox row's own primary key is the parity-guarded copy, unrelated to the fact's `event_id` |
| #8 id 45 / 47 (the counter seed's race and per-allocation scan cost) | **avoided** | the constants are feature 17's; the allocator class is tested at § 5 |
| #7's lock-protocol reuse (approved first pass, atomicity by fault injection) | **followed** | § 6 including the control |
| #8 id 49's second face / the "other lock-order" worry: despatch and reserve interleaving | not recurred | `lock_order_items` sorts through `distinct_stock_keys`; the allocator's counter row is taken AFTER every stock row on every path that takes it (only despatch takes it), so no cycle |

No inherited finding recurred.

## 11. Live check (also the manual test script)

Preconditions: `docker ps` before: `otcpy-n8n Up` only (`.arm/impl18/docker_before.txt`). `docker compose -p otcpy -f docker-compose.infra.yml start postgres nats kafka`; all three healthy. `psql` is not on the host: queries ran as `docker exec -e PGPASSWORD=… otcpy-postgres psql -U $POSTGRES_APP_USER -d <db>` after `set -a; . ./.env; set +a`.

**Order chosen: `ORD-000007`.** Why: it holds TWO `reserved` reservations on two stock rows of one company (`IBERFOODS`: `PRD-0001` x 2 `e0ac4713-…` and `PRD-0002` x 3 `1a1748cc-…`), so one live request exercises a multi-line advice and two stock rows locked in code-point order; `ORD-000008` holds one line (`PRD-0001` x 4 `f7f8d318-…`) and was left untouched as the control. Before: `despatches` 5 (`DES-000001..005`, seed), `despatch_number_sequences` empty (seeded lazily), `outbox` 14 rows (max `seq` 14), `IBERFOODS PRD-0001` units 500 / reserved 6, `PRD-0002` 495 / 3, `ORD-000007` and `ORD-000008` both `stock_reserved`, each with a `parked` `credit.hold` (Billing does not exist).

Hosts: `uv run uvicorn otc_fulfillment.main:app --port 8102` then `uv run uvicorn otc_orders.main:app --port 8101` (both `/health/ready` -> `{"status":"ready"}` 200).

The request (a raw NATS request with the order id as `x-correlation-id` and a fresh `x-request-id`; the script is a 10-line `nats-py` client, `nc.request("fulfillment.despatch.create", b'{"orderReference":"ORD-000007"}', headers=…)`):

```text
request headers: {'x-correlation-id': '223c1406-1fd8-45c8-99c5-88a738720414', 'x-request-id': '3d370996-0eaf-4e8e-a82f-bb4f84f7ff24'}
reply: {"orderReference":"ORD-000007","despatchReference":"DES-000006","despatchDate":"2026-10-08T08:31:10.482Z","created":true,"lines":[{"productCode":"PRD-0001","units":2},{"productCode":"PRD-0002","units":3}]}
```

After (`.arm/impl18/live/after1.txt`):

- `despatches`: `587c206a-632e-4959-afee-c4570c263866`, `DES-000006`, `ORD-000007`, `IBERFOODS`, `CarrefourEs`, `2026-10-08 08:31:10.482+00`; `despatch_items`: `c73a6359-…` `PRD-0001` x 2 and `0f53d2b6-…` `PRD-0002` x 3.
- reservations of `ORD-000007`: both `consumed` (`updated_at 08:31:10.497`); `ORD-000008`'s: still `reserved` (control).
- stock: `PRD-0001` units **498** / reserved **4** (500 - 2, 6 - 2); `PRD-0002` units **492** / reserved **0** (495 - 3, 3 - 3).
- counter: `despatch_number_sequences` `(1, 7)`.
- outbox: `seq 15`, `order.despatched.v1`, `aggregate_id 587c206a-…` (the advice), `correlation_id 223c1406-…` (= `otc_orders.orders.id` of `ORD-000007`), `causation_id 3d370996-…` (= the request id sent), `occurred_at 08:31:10.482`, **`published_at 08:31:10.568`** (86 ms later), payload `{"orderReference":"ORD-000007","despatchReference":"DES-000006","despatchDate":"2026-10-08T08:31:10.482Z","companyCode":"IBERFOODS","retailerCode":"CarrefourEs","lines":[…]}`.
- **Orders**: `otc_orders.processed_events` has `d765ec54-e3b8-4d26-af44-53890a323bd7` (the fact's `event_id`), consumer `orders.saga`, at `08:31:10.566`; the Orders log line is `saga fact ignored`; `ORD-000007` is still `stock_reserved` (not `confirmed`, so the saga legitimately skips the fact), and `saga_commands` is unchanged (4 rows). Not forced.
- **Repeat** (new `x-request-id`): reply identical with `"created":false`; counts after: `despatches` 6, `outbox` 15, `next_value` 7 (nothing moved).
- **Never reserved** (`ORD-000099`): `{"code":"PRECONDITION_FAILED","message":"despatch.create: order ORD-000099 holds no reservation in status \"reserved\": nothing to despatch","details":{"orderReference":"ORD-000099"},"correlationId":"223c1406-…","occurredAt":"2026-10-08T08:31:40.218Z"}`.
- **No headers**: `{"code":"VALIDATION_FAILED","message":"the x-correlation-id header is required","occurredAt":"2026-10-08T08:31:40.471Z"}`.

Teardown: both hosts stopped with `kill -TERM` of the two server PIDs (975924 Orders, 974209 Fulfillment; both logged `Application shutdown complete`); `pgrep -af "uvicorn otc_"` and `ss -ltn | grep :810[12]` empty; `docker compose … stop kafka nats postgres`; `docker ps` after: `otcpy-n8n Up 3 minutes (healthy)` only (`.arm/impl18/docker_after.txt`).

**Side effect on the developer databases (FS17 style):** `ORD-000007` now has an advice `DES-000006`, its reservations are `consumed` and `IBERFOODS` stock moved (498 / 4 and 492 / 0); `ORD-000008` was not touched. Recreate the dev database to repeat § 11.

## 12. `git status --porcelain`, classified against the bounds

Created by me (untracked): `services/fulfillment/src/otc_fulfillment/{application/despatch_creation.py, domain/despatch_advice.py, domain/order_despatch.py, infrastructure/persistence/despatch_number_allocator.py, infrastructure/persistence/despatch_repository.py}` and nine test files under `services/fulfillment/tests/` (`unit/domain/test_despatch.py`, `unit/test_despatch_{creation_service,wire,payload,transactions}.py`, `integration/test_despatch_{create,number_allocator,race,store}.py`): inside `services/fulfillment/**`.

Edited by me in place: feature 17's still-uncommitted files (all `services/fulfillment/src/**`, inside the bound): `domain/{events,errors,snapshot}.py`, `application/{messages,handlers}.py`, `application/ports/stock_store.py`, `infrastructure/persistence/{stock_reads,stock_transactions}.py`, `infrastructure/outbox/payloads.py`, `infrastructure/messaging/subjects.py`, `presentation/{stock_responder,stock_wire,stock_rpc_errors}.py`, `composition.py`; the tracked `infrastructure/persistence/sequences.py` (one docstring sentence); feature 17's tests `unit/test_stock_responder.py` and `integration/test_fulfillment_host_lifespan.py`; `tests/architecture/{test_registration_behaviour,test_write_path_population,test_fulfillment_rpc_error_retryability}.py` (named in § 2 item 10); `specs/shared/test-matrix.md` (R36's column 5 and the derived counts only); `feature_list.json` (line 343, `"status": "in_review"`, only); this report.

Modified before I started and **not** mine (they were in the session's initial `git status`): `.env.example`, `conftest.py`, `progress/current.md`, `progress/history.md`, `services/fulfillment/pyproject.toml`, `services/fulfillment/src/otc_fulfillment/infrastructure/settings.py`, `…/presentation/app.py`, `services/fulfillment/tests/integration/conftest.py`, `services/orders/tests/integration/conftest.py`, `tests/architecture/{test_composition_env_reads,test_kafka_client_confinement}.py`, `uv.lock`, and the untracked feature-17 and leader files (`progress/brief_*`, `premise_*`, `impl_fulfillment_stock.md`, `review_fulfillment_stock.md`).

Untouched, verified by `git status`: `models.py`, `range_guards.py`, `types.py`, `alembic/` (the I18 arm edited the migration and restored it with `cmp`), `services/orders/src`, `packages/`, every other service, root `pyproject.toml`, `specs/shared/` beyond the matrix, `specs/fulfillment_stock/`, `CLAUDE.md`, `progress/current.md`.

## 13. Things that surprised me, and what I could not do

- **The F8 arm the brief described does not make the unique key the savior** (§ 8). Stated as a finding, not worked around.
- **Removing "the lock call" is a shared-code mutation.** The despatch calls the same `lock_order_items` as release, and the lock is inside `_lock_stock_rows`; there is no despatch-only lock statement to delete without inventing one. The despatch-named failure messages and A5 are the despatch-specific guards.
- **Equivalent mutants, recorded rather than passed:** P2 (dropping `wire_instant` from the payload's `despatchDate`: `to_wire_json` truncates the instant itself, so the wire is unchanged; P2b corrupts the field instead) and X9 (deleting the fast path is invisible to the integration repeat test, because the in-lock layer answers the same reply; the fast path's claim is A3 and I15).
- **`otcpy-n8n` showed `Up 13 seconds (health: starting)` twice** while I was working (a restart loop of its own; it was `healthy` at the end). Not mine, noted for the leader.
- **Stale citations in 17's artefacts**: `specs/fulfillment_stock/requirements.md:140` / `tasks.md:107` name the `…all_five_subjects` test; untouched, still accurate.
- **No stop-and-report item.** #7 and #8 agree on every row of the error table and on the lock reuse; Python forced no difference the brief did not settle.

## 14. Arms: summary and the full log

87 arm runs (the appendix; `B8` was added last). **76 final arms seen red** (the failure names the claim, restored with `cmp`, same test green again); 7 of the 83 red runs were **superseded** by `_v2` re-runs (I1a, I1b, I1c, I3a, I3b, I4: red but the log line did not name the claim, or the test died on a `KeyError`, which I fixed by `.get("created")` and the assertion message listing both replies; I7: red through a foreign-key violation, not the provenance claim, so the `_v2` mutates both the header id and the lines' `despatch_id`); 1 **malformed** (T4: its mutation named an attribute that does not exist; superseded by T4b); 2 **equivalent mutants** recorded green (P2, X9); 1 **identity control** that must stay green (T3). Procedure for every run: `cp -p` of the file into the git-ignored `.arm/impl18/bak/`, sha256 recorded, exactly one replacement (the helper refuses a pattern that does not match the expected number of times), the ONE named test in its own process group (`start_new_session`, `killpg` on timeout), restore by `cp` + `cmp`, `__pycache__` under `services/fulfillment/src` and `.mypy_cache` removed, the same test re-run green. The helper is `.arm/impl18/armlib.py`; the scripts `arm_domain.py`, `arm_app.py`, `arm_infra.py`, `arm_infra2.py`, `arm_wire.py`, `arm_wire2.py`, `arm_tx.py`; the full output of each run from `I1a_v2` on is in `.arm/impl18/out/`. The first red of the registration guard, before the pinned literal was edited, is `.arm/impl18/registration_red_before.txt`.

Defeat-list rows that applied: 1 (delete: D6 D10 D12 D14 A3 A4 A8 A9 I16 I17 W1 C1), 2 (corrupt a supplied field: D7 D8 D9 D11 D16 D17 P1 P2b A2 W3 W5 X8), 3 (sibling identifier: D4/D4b crossed ids, the line-id order in D13/I13, E2 `CONFLICT` for `UNAVAILABLE`, I4 the sibling isolation level), 7 (drop an optional element: A7, X9 the optional fast path), 8 (a literal against a literal: every expected id in the new tests is a test-supplied value compared by equality; the control rows pair every negative), 9 (satisfy the closer half, leave the premise stale: the lock waits are observed ungranted in `pg_stat_activity`, never inferred from an earlier row), 12 (a path the population never drives: the defensive `NothingToDespatch` branch B8, the inconsistency branch A12, the `23505` path I18). Rows 4 – 6 and 10 – 11 do not apply: no syntax guard was added; the census and registration guards were edited, not replaced, and both were seen red before and after (C1 C2 C3).

### Appendix A — every arm run, verbatim (`.arm/impl18/arm_log.md`)


### D1_advice_id -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/order_despatch.py`; backup `.arm/impl18/bak/D1_advice_id__services__fulfillment__src__otc_fulfillment__domain__order_despatch.py`; sha256 `ca6779454e91f50b5343b15ede4f20356902c83966836e3f6ddbaa3aee8c00d5`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_fs24_the_advice_id_is_the_first_supplied_id_and_is_the_facts_aggregate_id`
- mutation: `advice_id = new_id()` -> `advice_id = UniqueId.new()`
- failure (verbatim, first lines):
```
E       AssertionError: assert UniqueId(valu...8b72dd680aa')) == UniqueId(valu...000000000ad'))
E         
E         Differing attributes:
E         ['value']
E         
E         Drill down into differing attribute value:
```

### D2_line_id -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/order_despatch.py`; backup `.arm/impl18/bak/D2_line_id__services__fulfillment__src__otc_fulfillment__domain__order_despatch.py`; sha256 `ca6779454e91f50b5343b15ede4f20356902c83966836e3f6ddbaa3aee8c00d5`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_fs24_each_line_id_is_the_supplied_id_of_its_reservation_in_consumption_order`
- mutation: `DespatchLine(id=new_id(),` -> `DespatchLine(id=UniqueId.new(),`
- failure (verbatim, first lines):
```
E       AssertionError: assert [('PRD-A1', U...3991d6df2')))] == [('PRD-A1', U...000000012')))]
E         
E         At index 0 diff: ('PRD-A1', UniqueId(value=UUID('4b4999b4-033c-4ea1-b3c9-9a1c398e3ab8'))) != ('PRD-A1', UniqueId(value=UUID('00000000-0000-4000-8000-000000000011')))
E         Use -v to get more diff
services/fulfillment/tests/unit/domain/test_despatch.py:195: AssertionError
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_fs24_each_line_id_is_the_supplied_id_of_its_reservation_in_consumption_order
```

### D3_event_id -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/order_despatch.py`; backup `.arm/impl18/bak/D3_event_id__services__fulfillment__src__otc_fulfillment__domain__order_despatch.py`; sha256 `ca6779454e91f50b5343b15ede4f20356902c83966836e3f6ddbaa3aee8c00d5`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_fs24_the_facts_event_id_is_the_last_supplied_id`
- mutation: `event_id = new_id()` -> `event_id = UniqueId.new()`
- failure (verbatim, first lines):
```
E       AssertionError: assert UniqueId(valu...d1f96a34bae')) == UniqueId(valu...000000000e5'))
E         
E         Differing attributes:
E         ['value']
E         
E         Drill down into differing attribute value:
```

### D4_crossed_ids -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/order_despatch.py`; backup `.arm/impl18/bak/D4_crossed_ids__services__fulfillment__src__otc_fulfillment__domain__order_despatch.py`; sha256 `ca6779454e91f50b5343b15ede4f20356902c83966836e3f6ddbaa3aee8c00d5`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_fs24_the_advice_id_is_the_first_supplied_id_and_is_the_facts_aggregate_id`
- mutation: `advice_id=advice_id,
        event_id=event_id,` -> `advice_id=event_id,
        event_id=advice_id,`
- note: crossed: advice and event ids swapped, both still from new_id()
- failure (verbatim, first lines):
```
E       AssertionError: assert UniqueId(valu...000000000e5')) == UniqueId(valu...000000000ad'))
E         
E         Differing attributes:
E         ['value']
E         
E         Drill down into differing attribute value:
```

### D4b_crossed_ids_event -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/order_despatch.py`; backup `.arm/impl18/bak/D4b_crossed_ids_event__services__fulfillment__src__otc_fulfillment__domain__order_despatch.py`; sha256 `ca6779454e91f50b5343b15ede4f20356902c83966836e3f6ddbaa3aee8c00d5`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_fs24_the_facts_event_id_is_the_last_supplied_id`
- mutation: `advice_id=advice_id,
        event_id=event_id,` -> `advice_id=event_id,
        event_id=advice_id,`
- note: same crossing, the event-id half
- failure (verbatim, first lines):
```
E       AssertionError: assert UniqueId(valu...000000000ad')) == UniqueId(valu...000000000e5'))
E         
E         Differing attributes:
E         ['value']
E         
E         Drill down into differing attribute value:
```

### D5_extra_mint -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/order_despatch.py`; backup `.arm/impl18/bak/D5_extra_mint__services__fulfillment__src__otc_fulfillment__domain__order_despatch.py`; sha256 `ca6779454e91f50b5343b15ede4f20356902c83966836e3f6ddbaa3aee8c00d5`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_fs24_the_operation_mints_exactly_one_id_per_site_and_no_more`
- mutation: `event_id = new_id()` -> `new_id()
    event_id = new_id()`
- failure (verbatim, first lines):
```
E       AssertionError: assert [UniqueId(val...0000000904'))] == [UniqueId(val...0000000903'))]
E         
E         Left contains one more item: UniqueId(value=UUID('00000000-0000-4000-8000-000000000904'))
E         Use -v to get more diff
services/fulfillment/tests/unit/domain/test_despatch.py:228: AssertionError
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_fs24_the_operation_mints_exactly_one_id_per_site_and_no_more
```

### D6_delete_consume -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/order_despatch.py`; backup `.arm/impl18/bak/D6_delete_consume__services__fulfillment__src__otc_fulfillment__domain__order_despatch.py`; sha256 `ca6779454e91f50b5343b15ede4f20356902c83966836e3f6ddbaa3aee8c00d5`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_consumes_every_reserved_reservation_of_the_order_lowers_both_counters_and_creates_one_advice_with_one_fact`
- mutation: `item.consume(request.order_reference)` -> `()`
- failure (verbatim, first lines):
```
E       assert False
E        +  where False = isinstance(NothingToDespatch(), Despatched)
services/fulfillment/tests/unit/domain/test_despatch.py:77: AssertionError
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_consumes_every_reserved_reservation_of_the_order_lowers_both_counters_and_creates_one_advice_with_one_fact
```

### D7_line_units -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/order_despatch.py`; backup `.arm/impl18/bak/D7_line_units__services__fulfillment__src__otc_fulfillment__domain__order_despatch.py`; sha256 `ca6779454e91f50b5343b15ede4f20356902c83966836e3f6ddbaa3aee8c00d5`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_f7_every_line_traces_one_to_one_to_a_consumed_reservation_of_the_order_with_its_units`
- mutation: `units=Quantity(reservation.units)` -> `units=Quantity(1)`
- failure (verbatim, first lines):
```
E       AssertionError: assert [('PRD-A1', 1...('PRD-B2', 1)] == [('PRD-A1', 3...('PRD-B2', 5)]
E         
E         At index 0 diff: ('PRD-A1', 1) != ('PRD-A1', 3)
E         Use -v to get more diff
services/fulfillment/tests/unit/domain/test_despatch.py:123: AssertionError
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_f7_every_line_traces_one_to_one_to_a_consumed_reservation_of_the_order_with_its_units
```

### D8_retailer_from_company -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/order_despatch.py`; backup `.arm/impl18/bak/D8_retailer_from_company__services__fulfillment__src__otc_fulfillment__domain__order_despatch.py`; sha256 `ca6779454e91f50b5343b15ede4f20356902c83966836e3f6ddbaa3aee8c00d5`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_the_fact_carries_the_requests_ids_the_clock_instant_the_reference_and_the_parties`
- mutation: `retailer_code=first_reservation.retailer_code` -> `retailer_code=first_item.company_code`
- failure (verbatim, first lines):
```
E       AssertionError: assert ('ACME-CO', 'ACME-CO') == ('RET-9', 'RET-9')
E         
E         At index 0 diff: 'ACME-CO' != 'RET-9'
E         Use -v to get more diff
services/fulfillment/tests/unit/domain/test_despatch.py:166: AssertionError
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_the_fact_carries_the_requests_ids_the_clock_instant_the_reference_and_the_parties
```

### D9_correlation_causation_swapped -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/order_despatch.py`; backup `.arm/impl18/bak/D9_correlation_causation_swapped__services__fulfillment__src__otc_fulfillment__domain__order_despatch.py`; sha256 `ca6779454e91f50b5343b15ede4f20356902c83966836e3f6ddbaa3aee8c00d5`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_the_fact_carries_the_requests_ids_the_clock_instant_the_reference_and_the_parties`
- mutation: `correlation_id=request.correlation_id,
        causation_id=context.causation_id,` -> `correlation_id=context.causation_id,
        causation_id=request.correlation_id,`
- failure (verbatim, first lines):
```
E       AssertionError: the order id the command carried
E       assert UniqueId(valu...0000000ca05')) == UniqueId(valu...0000000c0c0'))
E         
E         Differing attributes:
E         ['value']
E         
```

### D10_delete_nothing_branch -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/order_despatch.py`; backup `.arm/impl18/bak/D10_delete_nothing_branch__services__fulfillment__src__otc_fulfillment__domain__order_despatch.py`; sha256 `ca6779454e91f50b5343b15ede4f20356902c83966836e3f6ddbaa3aee8c00d5`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_an_order_holding_no_reserved_reservation_creates_no_advice_and_no_fact_and_changes_nothing[no reservation of the order at all]`
- mutation: `if not consumed:
        return NothingToDespatch()` -> ``
- failure (verbatim, first lines):
```
E       IndexError: list index out of range
services/fulfillment/src/otc_fulfillment/domain/order_despatch.py:61: IndexError
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_an_order_holding_no_reserved_reservation_creates_no_advice_and_no_fact_and_changes_nothing[no reservation of the order at all]
```

### D11_company_from_literal -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/order_despatch.py`; backup `.arm/impl18/bak/D11_company_from_literal__services__fulfillment__src__otc_fulfillment__domain__order_despatch.py`; sha256 `ca6779454e91f50b5343b15ede4f20356902c83966836e3f6ddbaa3aee8c00d5`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_the_fact_carries_the_requests_ids_the_clock_instant_the_reference_and_the_parties`
- mutation: `company_code=first_item.company_code` -> `company_code="CMP-X"`
- failure (verbatim, first lines):
```
E       AssertionError: assert ('CMP-X', 'CMP-X') == ('ACME-CO', 'ACME-CO')
E         
E         At index 0 diff: 'CMP-X' != 'ACME-CO'
E         Use -v to get more diff
services/fulfillment/tests/unit/domain/test_despatch.py:165: AssertionError
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_the_fact_carries_the_requests_ids_the_clock_instant_the_reference_and_the_parties
```

### D12_delete_f6_guard -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/despatch_advice.py`; backup `.arm/impl18/bak/D12_delete_f6_guard__services__fulfillment__src__otc_fulfillment__domain__despatch_advice.py`; sha256 `45652428c8dfc3082a74460c0dff85241b4aefefdd838afa2640692aab4d41d0`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_f6_an_advice_without_a_line_is_refused_and_records_no_fact`
- mutation: `if not lines:
            raise EmptyDespatchLinesError(order_reference)  # F6` -> ``
- failure (verbatim, first lines):
```
>       with pytest.raises(EmptyDespatchLinesError) as raised:
E       Failed: DID NOT RAISE EmptyDespatchLinesError
services/fulfillment/tests/unit/domain/test_despatch.py:321: Failed
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_f6_an_advice_without_a_line_is_refused_and_records_no_fact
```

### D13_delete_sort -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/despatch_advice.py`; backup `.arm/impl18/bak/D13_delete_sort__services__fulfillment__src__otc_fulfillment__domain__despatch_advice.py`; sha256 `45652428c8dfc3082a74460c0dff85241b4aefefdd838afa2640692aab4d41d0`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_the_lines_are_held_in_the_canonical_order_product_code_then_line_id`
- mutation: `ordered = tuple(sorted(lines, key=lambda ln: line_order_key(ln.product_code, ln.id)))` -> `ordered = tuple(lines)`
- failure (verbatim, first lines):
```
E       AssertionError: assert [(UniqueId(va...000021')), 4)] == [(UniqueId(va...000022')), 3)]
E         
E         At index 0 diff: (UniqueId(value=UUID('00000000-0000-4000-8000-000000000022')), 3) != (UniqueId(value=UUID('00000000-0000-4000-8000-000000000021')), 4)
E         Use -v to get more diff
services/fulfillment/tests/unit/domain/test_despatch.py:248: AssertionError
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_the_lines_are_held_in_the_canonical_order_product_code_then_line_id
```

### D14_delete_emission -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/despatch_advice.py`; backup `.arm/impl18/bak/D14_delete_emission__services__fulfillment__src__otc_fulfillment__domain__despatch_advice.py`; sha256 `45652428c8dfc3082a74460c0dff85241b4aefefdd838afa2640692aab4d41d0`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_consumes_every_reserved_reservation_of_the_order_lowers_both_counters_and_creates_one_advice_with_one_fact`
- mutation: `advice._raise_event(` -> `(lambda _e: None)(`
- failure (verbatim, first lines):
```
E       ValueError: not enough values to unpack (expected 1, got 0)
services/fulfillment/tests/unit/domain/test_despatch.py:94: ValueError
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_consumes_every_reserved_reservation_of_the_order_lowers_both_counters_and_creates_one_advice_with_one_fact
```

### D15_fact_aggregate_is_correlation -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/despatch_advice.py`; backup `.arm/impl18/bak/D15_fact_aggregate_is_correlation__services__fulfillment__src__otc_fulfillment__domain__despatch_advice.py`; sha256 `45652428c8dfc3082a74460c0dff85241b4aefefdd838afa2640692aab4d41d0`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_fs24_the_advice_id_is_the_first_supplied_id_and_is_the_facts_aggregate_id`
- mutation: `aggregate_id=advice_id,` -> `aggregate_id=correlation_id,`
- failure (verbatim, first lines):
```
E       AssertionError: assert UniqueId(valu...0000000c0c0')) == UniqueId(valu...000000000ad'))
E         
E         Differing attributes:
E         ['value']
E         
E         Drill down into differing attribute value:
```

### D16_fact_lines_corrupted -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/despatch_advice.py`; backup `.arm/impl18/bak/D16_fact_lines_corrupted__services__fulfillment__src__otc_fulfillment__domain__despatch_advice.py`; sha256 `45652428c8dfc3082a74460c0dff85241b4aefefdd838afa2640692aab4d41d0`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_f7_every_line_traces_one_to_one_to_a_consumed_reservation_of_the_order_with_its_units`
- mutation: `DespatchedLine(product_code=ln.product_code, units=ln.units.value)` -> `DespatchedLine(product_code=ln.product_code, units=1)`
- failure (verbatim, first lines):
```
E       AssertionError: assert (DespatchedLi...B2', units=1)) == (DespatchedLi...B2', units=5))
E         
E         At index 0 diff: DespatchedLine(product_code='PRD-A1', units=1) != DespatchedLine(product_code='PRD-A1', units=3)
E         Use -v to get more diff
services/fulfillment/tests/unit/domain/test_despatch.py:138: AssertionError
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_f7_every_line_traces_one_to_one_to_a_consumed_reservation_of_the_order_with_its_units
```

### D17_fact_date_is_unset_clock -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/despatch_advice.py`; backup `.arm/impl18/bak/D17_fact_date_is_unset_clock__services__fulfillment__src__otc_fulfillment__domain__despatch_advice.py`; sha256 `45652428c8dfc3082a74460c0dff85241b4aefefdd838afa2640692aab4d41d0`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_the_fact_carries_the_requests_ids_the_clock_instant_the_reference_and_the_parties`
- mutation: `occurred_at=despatch_date,` -> `occurred_at=correlation_id and despatch_date.replace(year=2001),`
- failure (verbatim, first lines):
```
E       AssertionError: assert datetime.datetime(2001, 10, 8, 9, 0, 0, 123000, tzinfo=datetime.timezone.utc) == datetime.datetime(2026, 10, 8, 9, 0, 0, 123000, tzinfo=datetime.timezone.utc)
E        +  where datetime.datetime(2001, 10, 8, 9, 0, 0, 123000, tzinfo=datetime.timezone.utc) = OrderDespatched(event_id=UniqueId(value=UUID('00000000-0000-4000-8000-0000000000e5')), aggregate_id=UniqueId(value=UUI...r_code='RET-9', lines=(DespatchedLine(product_code='PRD-A1', units=3), DespatchedLine(product_code='PRD-B2', units=5))).occurred_at
services/fulfillment/tests/unit/domain/test_despatch.py:159: AssertionError
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_the_fact_carries_the_requests_ids_the_clock_instant_the_reference_and_the_parties
```

### S1_consume_keeps_units -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/stock_item.py`; backup `.arm/impl18/bak/S1_consume_keeps_units__services__fulfillment__src__otc_fulfillment__domain__stock_item.py`; sha256 `d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_consumes_every_reserved_reservation_of_the_order_lowers_both_counters_and_creates_one_advice_with_one_fact`
- mutation: `self._units = self._units - total
        self._reserved_units = self._reserved_units - total
        return tuple(moving)

    def replenis` -> `self._reserved_units = self._reserved_units - total
        return tuple(moving)

    def replenish`
- note: consume no longer lowers on-hand units
- failure (verbatim, first lines):
```
E       assert (10, 1) == (7, 1)
E         
E         At index 0 diff: 10 != 7
E         Use -v to get more diff
services/fulfillment/tests/unit/domain/test_despatch.py:89: AssertionError
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_consumes_every_reserved_reservation_of_the_order_lowers_both_counters_and_creates_one_advice_with_one_fact
```

### S2_consume_keeps_reserved -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/stock_item.py`; backup `.arm/impl18/bak/S2_consume_keeps_reserved__services__fulfillment__src__otc_fulfillment__domain__stock_item.py`; sha256 `d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_consumes_every_reserved_reservation_of_the_order_lowers_both_counters_and_creates_one_advice_with_one_fact`
- mutation: `self._units = self._units - total
        self._reserved_units = self._reserved_units - total
        return tuple(moving)

    def replenis` -> `self._units = self._units - total
        return tuple(moving)

    def replenish`
- note: consume no longer lowers reserved_units
- failure (verbatim, first lines):
```
E       assert (7, 4) == (7, 1)
E         
E         At index 1 diff: 4 != 1
E         Use -v to get more diff
services/fulfillment/tests/unit/domain/test_despatch.py:89: AssertionError
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_consumes_every_reserved_reservation_of_the_order_lowers_both_counters_and_creates_one_advice_with_one_fact
```

### A1_new_id_not_the_port -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/A1_new_id_not_the_port__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_r36_creates_the_advice_under_the_lock_in_the_documented_order_with_the_supplied_ids`
- mutation: `new_id=scope.ids.new,` -> `new_id=UniqueId.new,`
- failure (verbatim, first lines):
```
E       AssertionError: the first id the application's source handed out
E       assert UniqueId(valu...7cdeffc2e6f')) == UniqueId(valu...000000000ad'))
E         
E         Differing attributes:
E         ['value']
E         
```

### A2_causation_is_correlation -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/A2_causation_is_correlation__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_r36_creates_the_advice_under_the_lock_in_the_documented_order_with_the_supplied_ids`
- mutation: `StockContext(occurred_at=now, causation_id=command.request_id)` -> `StockContext(occurred_at=now, causation_id=command.correlation_id)`
- failure (verbatim, first lines):
```
E       AssertionError: assert UniqueId(valu...000000000c0')) == UniqueId(valu...000000000ca'))
E         
E         Differing attributes:
E         ['value']
E         
E         Drill down into differing attribute value:
```

### A3_delete_fast_path -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/A3_delete_fast_path__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_f8_the_fast_path_returns_the_existing_advice_without_a_transaction_or_a_lock`
- mutation: `existing = await scope.reads.despatch_of_order(command.order_reference)
    if existing is not None:
        return DespatchResult(created=F` -> ``
- failure (verbatim, first lines):
```
E       AssertionError: assert True is False
E        +  where True = DespatchResult(created=True, despatch=DespatchSnapshot(id=UniqueId(value=UUID('00000000-0000-0000-0000-0000000000ad'))...spatchLineSnapshot(id=UniqueId(value=UUID('00000000-0000-0000-0000-000000000011')), product_code='PRD-A1', units=3),))).created
services/fulfillment/tests/unit/test_despatch_creation_service.py:234: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_creation_service.py::test_f8_the_fast_path_returns_the_existing_advice_without_a_transaction_or_a_lock
```

### A4_delete_no_keys_refusal -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/A4_delete_no_keys_refusal__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_r36_an_order_that_never_held_a_reservation_is_refused_without_a_transaction`
- mutation: `if not keys:
        raise NoReservedStockForDespatchError(command.order_reference)` -> ``
- failure (verbatim, first lines):
```
        with pytest.raises(NoReservedStockForDespatchError) as raised:
E       assert 1 == 0
E        +  where 1 = <services.fulfillment.tests.unit.test_despatch_creation_service.FakeTransactions object at 0x72b90f0ec2f0>.runs
E        +    where <services.fulfillment.tests.unit.test_despatch_creation_service.FakeTransactions object at 0x72b90f0ec2f0> = <services.fulfillment.tests.unit.test_despatch_creation_service.Rig object at 0x72b90f353cb0>.transactions
services/fulfillment/tests/unit/test_despatch_creation_service.py:250: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_creation_service.py::test_r36_an_order_that_never_held_a_reservation_is_refused_without_a_transaction
```

### A5_keys_not_distinct -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/A5_keys_not_distinct__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_sa4_the_despatch_takes_the_release_lock_on_the_distinct_keys_in_code_point_order`
- mutation: `keys=distinct_stock_keys(keys),` -> `keys=keys,`
- failure (verbatim, first lines):
```
E       AssertionError: assert [('ORD-000042..., 'PRD-B2')))] == [('ORD-000042..., 'PRD-B2')))]
E         
E         At index 0 diff: ('ORD-000042', (('ACME-CO', 'PRD-B2'), ('ACME-CO', 'PRD-A1'), ('ACME-CO', 'PRD-B2'))) != ('ORD-000042', (('ACME-CO', 'PRD-A1'), ('ACME-CO', 'PRD-B2')))
E         Use -v to get more diff
services/fulfillment/tests/unit/test_despatch_creation_service.py:268: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_creation_service.py::test_sa4_the_despatch_takes_the_release_lock_on_the_distinct_keys_in_code_point_order
```

### A6_delete_in_lock_re_read -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/A6_delete_in_lock_re_read__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_f8_a_repeat_that_raced_the_fast_path_is_answered_by_the_in_lock_re_read`
- mutation: `existing = await tx.despatches.find_by_order_reference(command.order_reference)` -> `existing = None`
- failure (verbatim, first lines):
```
>                   raise ConcurrentDespatchChangeError(command.order_reference)
E                   otc_fulfillment.application.ports.stock_store.ConcurrentDespatchChangeError: order ORD-000042 holds consumed reservations but has no despatch advice
services/fulfillment/src/otc_fulfillment/application/despatch_creation.py:80: ConcurrentDespatchChangeError
FAILED services/fulfillment/tests/unit/test_despatch_creation_service.py::test_f8_a_repeat_that_raced_the_fast_path_is_answered_by_the_in_lock_re_read
```

### A7_delete_released_refusal -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/A7_delete_released_refusal__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_r36_an_order_whose_reservations_were_all_released_is_refused_and_nothing_is_written`
- mutation: `raise NoReservedStockForDespatchError(command.order_reference)  # all released` -> `pass`
- failure (verbatim, first lines):
```
        with pytest.raises(NoReservedStockForDespatchError):
E       AssertionError: no re-read (nothing consumed), no number, no save
E       assert ['lock', 'allocate'] == ['lock']
E         
E         Left contains one more item: 'allocate'
E         Use -v to get more diff
```

### A8_delete_stock_save -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/A8_delete_stock_save__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_r36_creates_the_advice_under_the_lock_in_the_documented_order_with_the_supplied_ids`
- mutation: `await repository.save()  # the reservations' status and both counters; emits no fact` -> ``
- failure (verbatim, first lines):
```
E       AssertionError: assert ['lock', 'all...ave_despatch'] == ['lock', 'all...ave_despatch']
E         
E         At index 2 diff: 'save_despatch' != 'save_stock'
E         Right contains one more item: 'save_despatch'
E         Use -v to get more diff
services/fulfillment/tests/unit/test_despatch_creation_service.py:279: AssertionError
```

### A9_delete_advice_save -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/A9_delete_advice_save__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_r36_creates_the_advice_under_the_lock_in_the_documented_order_with_the_supplied_ids`
- mutation: `await tx.despatches.save(outcome.advice)  # the advice, its lines, its ONE fact` -> ``
- failure (verbatim, first lines):
```
E       AssertionError: assert ['lock', 'all... 'save_stock'] == ['lock', 'all...ave_despatch']
E         
E         Right contains one more item: 'save_despatch'
E         Use -v to get more diff
services/fulfillment/tests/unit/test_despatch_creation_service.py:279: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_creation_service.py::test_r36_creates_the_advice_under_the_lock_in_the_documented_order_with_the_supplied_ids
```

### A10_created_flag_false -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/A10_created_flag_false__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_r36_creates_the_advice_under_the_lock_in_the_documented_order_with_the_supplied_ids`
- mutation: `return DespatchResult(created=True, despatch=outcome.advice.to_snapshot())` -> `return DespatchResult(created=False, despatch=outcome.advice.to_snapshot())`
- failure (verbatim, first lines):
```
E       AssertionError: assert False is True
E        +  where False = DespatchResult(created=False, despatch=DespatchSnapshot(id=UniqueId(value=UUID('00000000-0000-0000-0000-0000000000ad')...spatchLineSnapshot(id=UniqueId(value=UUID('00000000-0000-0000-0000-000000000011')), product_code='PRD-A1', units=3),))).created
services/fulfillment/tests/unit/test_despatch_creation_service.py:280: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_creation_service.py::test_r36_creates_the_advice_under_the_lock_in_the_documented_order_with_the_supplied_ids
```

### A11_repeat_flag_true -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/A11_repeat_flag_true__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_f8_a_repeat_that_raced_the_fast_path_is_answered_by_the_in_lock_re_read`
- mutation: `return DespatchResult(created=False, despatch=existing)
        raise NoReservedStockForDespatchError(command.order_reference)  # all releas` -> `return DespatchResult(created=True, despatch=existing)
        raise NoReservedStockForDespatchError(command.order_reference)  # all release`
- failure (verbatim, first lines):
```
E       AssertionError: assert True is False
E        +  where True = DespatchResult(created=True, despatch=DespatchSnapshot(id=UniqueId(value=UUID('00000000-0000-0000-0000-0000000000d1'))...spatchLineSnapshot(id=UniqueId(value=UUID('00000000-0000-0000-0000-0000000000d2')), product_code='PRD-A1', units=3),))).created
services/fulfillment/tests/unit/test_despatch_creation_service.py:331: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_creation_service.py::test_f8_a_repeat_that_raced_the_fast_path_is_answered_by_the_in_lock_re_read
```

### A12_delete_inconsistency_raise -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/A12_delete_inconsistency_raise__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_consumed_reservations_with_no_advice_are_a_transient_inconsistency_not_a_refusal`
- mutation: `raise ConcurrentDespatchChangeError(command.order_reference)` -> `raise NoReservedStockForDespatchError(command.order_reference)`
- failure (verbatim, first lines):
```
        with pytest.raises(ConcurrentDespatchChangeError) as raised:
>                   raise NoReservedStockForDespatchError(command.order_reference)
E                   otc_fulfillment.application.despatch_creation.NoReservedStockForDespatchError: despatch.create: order ORD-000042 holds no reservation in status "reserved": nothing to despatch
services/fulfillment/src/otc_fulfillment/application/despatch_creation.py:80: NoReservedStockForDespatchError
FAILED services/fulfillment/tests/unit/test_despatch_creation_service.py::test_consumed_reservations_with_no_advice_are_a_transient_inconsistency_not_a_refusal
```

### A13_allocate_before_lock -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/A13_allocate_before_lock__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_r36_creates_the_advice_under_the_lock_in_the_documented_order_with_the_supplied_ids`
- mutation: `locked = await repository.lock_order_items(command.order_reference, keys)  # the SA-4 lock` -> `reference_early = await tx.despatch_numbers.next_reference()
    locked = await repository.lock_order_items(command.order_reference, keys)  `
- note: the number allocated before the lock: the documented order is lock -> allocate
- failure (verbatim, first lines):
```
E       AssertionError: assert ['allocate', ...ave_despatch'] == ['lock', 'all...ave_despatch']
E         
E         At index 0 diff: 'allocate' != 'lock'
E         Left contains one more item: 'save_despatch'
E         Use -v to get more diff
services/fulfillment/tests/unit/test_despatch_creation_service.py:279: AssertionError
```

### I1a_no_stock_lock_fs25_despatch -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_repository.py`; backup `.arm/impl18/bak/I1a_no_stock_lock_fs25_despatch__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_repository.py`; sha256 `1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9`
- test: `services/fulfillment/tests/integration/test_despatch_race.py::test_fs25_a_despatch_waits_for_a_transaction_holding_a_stock_row_of_the_order_before_reading_its_reservations`
- mutation: `.where(Stock.company_code == company_code, Stock.product_code == product_code)
                .with_for_update()` -> `.where(Stock.company_code == company_code, Stock.product_code == product_code)`
- note: the stock lock removed (shared by release/reserve/despatch): the despatch-named failure
- failure (verbatim, first lines):
```
E           asyncio.exceptions.CancelledError
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/.venv/lib/python3.14/site-packages/asyncpg/connect_utils.py:1102: CancelledError
exc_type = <class 'asyncio.exceptions.CancelledError'>
exc_val = CancelledError(), exc_tb = <traceback object at 0x778a5370fa80>
                if issubclass(exc_type, exceptions.CancelledError):
>                   raise TimeoutError from exc_val
```

### I1b_no_stock_lock_release_wins -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_repository.py`; backup `.arm/impl18/bak/I1b_no_stock_lock_release_wins__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_repository.py`; sha256 `1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9`
- test: `services/fulfillment/tests/integration/test_despatch_race.py::test_sa4_release_wins_the_despatch_finds_nothing_to_consume_and_creates_no_advice`
- mutation: `.where(Stock.company_code == company_code, Stock.product_code == product_code)
                .with_for_update()` -> `.where(Stock.company_code == company_code, Stock.product_code == product_code)`
- failure (verbatim, first lines):
```
            raise ValueError("Invalid delay: NaN (not a number)")
E           asyncio.exceptions.CancelledError
/home/juanpabloperez/.local/share/uv/python/cpython-3.14.8-linux-x86_64-gnu/lib/python3.14/asyncio/tasks.py:712: CancelledError
exc_type = <class 'asyncio.exceptions.CancelledError'>
exc_val = CancelledError(), exc_tb = <traceback object at 0x7626562dfc40>
                if issubclass(exc_type, exceptions.CancelledError):
```

### I1c_no_stock_lock_despatch_wins -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_repository.py`; backup `.arm/impl18/bak/I1c_no_stock_lock_despatch_wins__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_repository.py`; sha256 `1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9`
- test: `services/fulfillment/tests/integration/test_despatch_race.py::test_sa4_despatch_wins_the_release_answers_precondition_failed_and_changes_nothing`
- mutation: `.where(Stock.company_code == company_code, Stock.product_code == product_code)
                .with_for_update()` -> `.where(Stock.company_code == company_code, Stock.product_code == product_code)`
- failure (verbatim, first lines):
```
E           asyncio.exceptions.CancelledError
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/.venv/lib/python3.14/site-packages/asyncpg/connect_utils.py:1102: CancelledError
exc_type = <class 'asyncio.exceptions.CancelledError'>
exc_val = CancelledError(), exc_tb = <traceback object at 0x7a3a2e000480>
                if issubclass(exc_type, exceptions.CancelledError):
>                   raise TimeoutError from exc_val
```

### I2_swap_reads_fs25_despatch -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_repository.py`; backup `.arm/impl18/bak/I2_swap_reads_fs25_despatch__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_repository.py`; sha256 `1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9`
- test: `services/fulfillment/tests/integration/test_despatch_store.py::test_fs25_the_despatch_lock_reads_the_orders_reservations_only_after_the_stock_lock_and_consumes_one_committed_while_it_waited`
- mutation: `rows = await self._lock_stock_rows(keys)
        reservations = await self._lock_reservations_of(order_reference)
        locked_ids` -> `reservations = await self._lock_reservations_of(order_reference)
        rows = await self._lock_stock_rows(keys)
        locked_ids`
- failure (verbatim, first lines):
```
E       AssertionError: the despatch read the order's reservations BEFORE the stock lock was granted: the reservation committed while it waited was not consumed
E       assert {UUID('000000...): 'reserved'} == {UUID('000000...): 'consumed'}
E         
E         Omitting 1 identical items, use -vv to show
E         Differing items:
E         {UUID('00000000-0000-0000-0000-000000000072'): 'reserved'} != {UUID('00000000-0000-0000-0000-000000000072'): 'consumed'}
```

### I3a_no_in_lock_re_read -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/I3a_no_in_lock_re_read__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/integration/test_despatch_create.py::test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number`
- mutation: `existing = await tx.despatches.find_by_order_reference(command.order_reference)` -> `existing = None`
- note: the loser's reply with the re-read removed is UNAVAILABLE (transient), see the assertion text
- failure (verbatim, first lines):
```
            except TimeoutError:
E       KeyError: 'created'
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/fulfillment/tests/integration/test_despatch_create.py:257: KeyError
FAILED services/fulfillment/tests/integration/test_despatch_create.py::test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number
```

### I3b_no_consumed_branch -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/I3b_no_consumed_branch__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/integration/test_despatch_create.py::test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number`
- mutation: `if ReservationStatus.CONSUMED in statuses:` -> `if False:`
- note: the whole F8 in-lock branch removed: the loser answers PRECONDITION_FAILED (terminal)
- failure (verbatim, first lines):
```
            except TimeoutError:
E       KeyError: 'created'
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/fulfillment/tests/integration/test_despatch_create.py:257: KeyError
WARNING  otc_fulfillment.presentation.stock_responder:stock_responder.py:228 fulfillment.despatch.create refused: PRECONDITION_FAILED despatch.create: order ORD-000042 holds no reservation in status "reserved": nothing to despatch
FAILED services/fulfillment/tests/integration/test_despatch_create.py::test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number
```

### I4_repeatable_read_pin -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py`; backup `.arm/impl18/bak/I4_repeatable_read_pin__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_transactions.py`; sha256 `ecce609b483c6683973e93be143ad9aca1a5ddd54c8c171d6d286425bb608abf`
- test: `services/fulfillment/tests/integration/test_despatch_create.py::test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number`
- mutation: `"isolation_level": "READ COMMITTED"` -> `"isolation_level": "REPEATABLE READ"`
- note: #8 id 54: the in-lock re-read relies on the pinned READ COMMITTED
- failure (verbatim, first lines):
```
            except TimeoutError:
E       KeyError: 'created'
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/fulfillment/tests/integration/test_despatch_create.py:257: KeyError
FAILED services/fulfillment/tests/integration/test_despatch_create.py::test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number
```

### I5_outbox_outside_transaction -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/despatch_repository.py`; backup `.arm/impl18/bak/I5_outbox_outside_transaction__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__despatch_repository.py`; sha256 `6f876278ed29476c09fac89d2962555f88cc6bc037f033971b8b56ae24159ef0`
- test: `services/fulfillment/tests/integration/test_despatch_store.py::test_j4_a_failure_after_the_advice_was_saved_leaves_no_advice_no_line_no_fact_no_burned_number_and_every_reservation_reserved`
- mutation: `await self._outbox.write(self._session, advice.domain_events)` -> `async with AsyncSession(self._session.bind) as own, own.begin():
            await self._outbox.write(own, advice.domain_events)`
- failure (verbatim, first lines):
```
        with pytest.raises(InjectedFaultError):
E       AssertionError: no fact (zero rows for the faulted order)
E       assert [{'id': UUID(...000bd'), ...}] == [{'id': UUID(...000ad'), ...}]
E         
E         Left contains one more item: {'id': UUID('81deb598-e01b-41bf-9ca3-824ef550fbac'), 'event_id': UUID('00000000-0000-0000-0000-0000000000e6'), 'event_type': 'order.despatched.v1', 'aggregate_id': UUID('00000000-0000-0000-0000-0000000000bd'), ...}
E         Use -v to get more diff
```

### I6_repo_mints_line_id -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/despatch_repository.py`; backup `.arm/impl18/bak/I6_repo_mints_line_id__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__despatch_repository.py`; sha256 `6f876278ed29476c09fac89d2962555f88cc6bc037f033971b8b56ae24159ef0`
- test: `services/fulfillment/tests/integration/test_despatch_store.py::test_fs24_every_id_of_the_advice_its_lines_and_its_fact_is_a_supplied_id_in_minting_order`
- mutation: `id=line.id.value,` -> `id=UUID(bytes=__import__('os').urandom(16), version=4),`
- failure (verbatim, first lines):
```
E       AssertionError: assert [(UUID('35b63... 'PRD-A1', 3)] == [(UUID('00000... 'PRD-A1', 3)]
E         
E         At index 0 diff: (UUID('35b639a0-2214-44ef-b1ef-f2b8abbcff4a'), 'PRD-A1', 4) != (UUID('00000000-0000-0000-0000-000000000031'), 'PRD-A1', 4)
E         Use -v to get more diff
services/fulfillment/tests/integration/test_despatch_store.py:357: AssertionError
FAILED services/fulfillment/tests/integration/test_despatch_store.py::test_fs24_every_id_of_the_advice_its_lines_and_its_fact_is_a_supplied_id_in_minting_order
```

### I7_repo_mints_advice_id -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/despatch_repository.py`; backup `.arm/impl18/bak/I7_repo_mints_advice_id__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__despatch_repository.py`; sha256 `6f876278ed29476c09fac89d2962555f88cc6bc037f033971b8b56ae24159ef0`
- test: `services/fulfillment/tests/integration/test_despatch_store.py::test_fs24_every_id_of_the_advice_its_lines_and_its_fact_is_a_supplied_id_in_minting_order`
- mutation: `id=advice.id.value,
                despatch_reference` -> `id=UUID(int=0xBAD),
                despatch_reference`
- note: header id only; the lines' FK keeps pointing at the advice id, so this also breaks the FK: see the failure
- failure (verbatim, first lines):
```
E   asyncpg.exceptions.ForeignKeyViolationError: insert or update on table "despatch_items" violates foreign key constraint "fk_despatch_items_despatch_id_despatches"
E   DETAIL:  Key (despatch_id)=(00000000-0000-0000-0000-0000000000ad) is not present in table "despatches".
asyncpg/protocol/protocol.pyx:266: ForeignKeyViolationError
error = ForeignKeyViolationError('insert or update on table "despatch_items" violates foreign key constraint "fk_despatch_items_despatch_id_despatches"')
        if not isinstance(error, AsyncAdapt_asyncpg_dbapi.Error):
E                   sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_dbapi.ForeignKeyViolationError: insert or update on table "despatch_items" violates foreign key constraint "fk_despatch_items_despatch_id_despatches"
```

### I8_advance_by_zero -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/sequences.py`; backup `.arm/impl18/bak/I8_advance_by_zero__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__sequences.py`; sha256 `626545d979d1ec2fa7784bbed45020b93159b5a7b66f1c3b299f1582c0461f22`
- test: `services/fulfillment/tests/integration/test_despatch_number_allocator.py::test_concurrent_allocations_in_separate_transactions_are_gap_free_and_unique`
- mutation: `SET next_value = next_value + 1 WHERE id = 1"
)` -> `SET next_value = next_value + 0 WHERE id = 1"
)`
- failure (verbatim, first lines):
```
E       AssertionError: duplicate references: ['DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001']
E       assert 1 == 24
E        +  where 1 = len({'DES-000001'})
E        +    where {'DES-000001'} = set(['DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', 'DES-000001', ...])
services/fulfillment/tests/integration/test_despatch_number_allocator.py:73: AssertionError
FAILED services/fulfillment/tests/integration/test_despatch_number_allocator.py::test_concurrent_allocations_in_separate_transactions_are_gap_free_and_unique
```

### I9_lock_without_for_update -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/sequences.py`; backup `.arm/impl18/bak/I9_lock_without_for_update__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__sequences.py`; sha256 `626545d979d1ec2fa7784bbed45020b93159b5a7b66f1c3b299f1582c0461f22`
- test: `services/fulfillment/tests/integration/test_despatch_number_allocator.py::test_an_uncommitted_allocation_holds_the_next_allocator_back_and_it_gets_the_next_number`
- mutation: `"SELECT next_value FROM despatch_number_sequences WHERE id = 1 FOR UPDATE"` -> `"SELECT next_value FROM despatch_number_sequences WHERE id = 1"`
- failure (verbatim, first lines):
```
E       AssertionError: assert 'DES-000002' == 'DES-000003'
E         
E         - DES-000003
E         ?          ^
E         + DES-000002
E         ?          ^
```

### I9b_lock_without_for_update_concurrent -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/sequences.py`; backup `.arm/impl18/bak/I9b_lock_without_for_update_concurrent__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__sequences.py`; sha256 `626545d979d1ec2fa7784bbed45020b93159b5a7b66f1c3b299f1582c0461f22`
- test: `services/fulfillment/tests/integration/test_despatch_number_allocator.py::test_concurrent_allocations_in_separate_transactions_are_gap_free_and_unique`
- mutation: `"SELECT next_value FROM despatch_number_sequences WHERE id = 1 FOR UPDATE"` -> `"SELECT next_value FROM despatch_number_sequences WHERE id = 1"`
- failure (verbatim, first lines):
```
E       AssertionError: duplicate references: ['DES-000001', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002']
E       assert 2 == 24
E        +  where 2 = len({'DES-000001', 'DES-000002'})
E        +    where {'DES-000001', 'DES-000002'} = set(['DES-000002', 'DES-000001', 'DES-000002', 'DES-000002', 'DES-000002', 'DES-000002', ...])
services/fulfillment/tests/integration/test_despatch_number_allocator.py:73: AssertionError
FAILED services/fulfillment/tests/integration/test_despatch_number_allocator.py::test_concurrent_allocations_in_separate_transactions_are_gap_free_and_unique
```

### I10_seed_ignores_existing_references -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/sequences.py`; backup `.arm/impl18/bak/I10_seed_ignores_existing_references__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__sequences.py`; sha256 `626545d979d1ec2fa7784bbed45020b93159b5a7b66f1c3b299f1582c0461f22`
- test: `services/fulfillment/tests/integration/test_despatch_number_allocator.py::test_seeding_over_a_non_empty_despatches_table_continues_above_its_maximum`
- mutation: `"SELECT 1, COALESCE((SELECT MAX(CAST(substring(despatch_reference FROM 5) AS bigint)) "
    "FROM despatches), 0) + 1 "
    "WHERE NOT EXIST` -> `"VALUES (1, 1) "`
- failure (verbatim, first lines):
```
E       AssertionError: assert 'DES-000001' == 'DES-000043'
E         
E         - DES-000043
E         ?         ^^
E         + DES-000001
E         ?         ^^
```

### I11_allocator_outside_the_transaction -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py`; backup `.arm/impl18/bak/I11_allocator_outside_the_transaction__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_transactions.py`; sha256 `ecce609b483c6683973e93be143ad9aca1a5ddd54c8c171d6d286425bb608abf`
- test: `services/fulfillment/tests/integration/test_despatch_number_allocator.py::test_the_allocation_belongs_to_the_stock_transactions_transaction`
- mutation: `SqlAlchemyDespatchNumberAllocator(session)` -> `SqlAlchemyDespatchNumberAllocator(AsyncSession(session.bind))`
- failure (verbatim, first lines):
```
TIMEOUT: process group killed
```

### I13_reload_without_sort -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/despatch_repository.py`; backup `.arm/impl18/bak/I13_reload_without_sort__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__despatch_repository.py`; sha256 `6f876278ed29476c09fac89d2962555f88cc6bc037f033971b8b56ae24159ef0`
- test: `services/fulfillment/tests/integration/test_despatch_store.py::test_f8_a_stored_advice_is_reloaded_in_the_canonical_line_order_whatever_the_rows_physical_order`
- mutation: `key=lambda ln: line_order_key(ln.product_code, ln.id),` -> `key=lambda ln: 0,`
- failure (verbatim, first lines):
```
E       AssertionError: assert [(UniqueId(va... 'PRD-A1', 4)] == [(UniqueId(va... 'PRD-B2', 5)]
E         
E         At index 0 diff: (UniqueId(value=UUID('00000000-0000-0000-0000-000000000033')), 'PRD-B2', 5) != (UniqueId(value=UUID('00000000-0000-0000-0000-000000000031')), 'PRD-A1', 4)
E         Use -v to get more diff
services/fulfillment/tests/integration/test_despatch_store.py:434: AssertionError
FAILED services/fulfillment/tests/integration/test_despatch_store.py::test_f8_a_stored_advice_is_reloaded_in_the_canonical_line_order_whatever_the_rows_physical_order
```

### I15_fast_path_returns_none -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_reads.py`; backup `.arm/impl18/bak/I15_fast_path_returns_none__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_reads.py`; sha256 `6d2ad700ee104ffa0c0a9f838193acb2a1d0fa0752f0b553a88f787c9e58e2e8`
- test: `services/fulfillment/tests/integration/test_despatch_store.py::test_f8_the_fast_path_answers_a_repeat_from_a_plain_read`
- mutation: `return await load_despatch(session, order_reference)` -> `return None`
- failure (verbatim, first lines):
```
        it cancels fut and raises TimeoutError.  To prevent fut from being
        #     except asyncio.TimeoutError:
            except exceptions.CancelledError as exc:
                raise TimeoutError from exc
E   asyncio.exceptions.CancelledError
asyncpg/protocol/protocol.pyx:205: CancelledError
```

### I16_no_lines_saved -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/despatch_repository.py`; backup `.arm/impl18/bak/I16_no_lines_saved__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__despatch_repository.py`; sha256 `6f876278ed29476c09fac89d2962555f88cc6bc037f033971b8b56ae24159ef0`
- test: `services/fulfillment/tests/integration/test_despatch_create.py::test_r36_consumes_the_reservations_lowers_both_counters_creates_one_advice_and_writes_exactly_one_despatched_fact`
- mutation: `for line in advice.lines:
            self._session.add(
                DespatchItem(` -> `for line in ():
            self._session.add(
                DespatchItem(`
- failure (verbatim, first lines):
```
E       AssertionError: assert [] == [('PRD-A1', 3), ('PRD-B2', 5)]
E         
E         Right contains 2 more items, first extra item: ('PRD-A1', 3)
E         Use -v to get more diff
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/fulfillment/tests/integration/test_despatch_create.py:106: AssertionError
FAILED services/fulfillment/tests/integration/test_despatch_create.py::test_r36_consumes_the_reservations_lowers_both_counters_creates_one_advice_and_writes_exactly_one_despatched_fact
```

### I17_no_outbox_write -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/despatch_repository.py`; backup `.arm/impl18/bak/I17_no_outbox_write__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__despatch_repository.py`; sha256 `6f876278ed29476c09fac89d2962555f88cc6bc037f033971b8b56ae24159ef0`
- test: `services/fulfillment/tests/integration/test_despatch_create.py::test_r36_consumes_the_reservations_lowers_both_counters_creates_one_advice_and_writes_exactly_one_despatched_fact`
- mutation: `await self._outbox.write(self._session, advice.domain_events)` -> ``
- failure (verbatim, first lines):
```
E       ValueError: not enough values to unpack (expected 1, got 0)
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/fulfillment/tests/integration/test_despatch_create.py:121: ValueError
FAILED services/fulfillment/tests/integration/test_despatch_create.py::test_r36_consumes_the_reservations_lowers_both_counters_creates_one_advice_and_writes_exactly_one_despatched_fact
```

### I18_unique_key_removed -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/alembic/versions/0001_initial_fulfillment_schema.py`; backup `.arm/impl18/bak/I18_unique_key_removed__services__fulfillment__alembic__versions__0001_initial_fulfillment_schema.py`; sha256 `e1f8388ba9854a56b011a30a2f49b4f66e2dfba9c4de14146cf09880ab276a0e`
- test: `services/fulfillment/tests/integration/test_despatch_store.py::test_f8_the_unique_key_refuses_a_second_advice_for_one_order_and_rolls_the_attempt_back`
- mutation: `sa.UniqueConstraint("order_reference", name="uq_despatches_order_reference"),` -> ``
- note: the migration's unique constraint temporarily removed; restored from the backup (alembic/ is outside the edit bounds, this is an arm only)
- failure (verbatim, first lines):
```
>       with pytest.raises(IntegrityError) as raised:
E       Failed: DID NOT RAISE IntegrityError
services/fulfillment/tests/integration/test_despatch_store.py:229: Failed
FAILED services/fulfillment/tests/integration/test_despatch_store.py::test_f8_the_unique_key_refuses_a_second_advice_for_one_order_and_rolls_the_attempt_back
```

### I1a_v2 -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_repository.py`; backup `.arm/impl18/bak/I1a_v2__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_repository.py`; sha256 `1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9`
- test: `services/fulfillment/tests/integration/test_despatch_race.py::test_fs25_a_despatch_waits_for_a_transaction_holding_a_stock_row_of_the_order_before_reading_its_reservations`
- mutation: `.where(Stock.company_code == company_code, Stock.product_code == product_code)
                .with_for_update()` -> `.where(Stock.company_code == company_code, Stock.product_code == product_code)`
- note: v2: full output saved; supersedes I1a
- failure (verbatim, first lines):
```
E           asyncio.exceptions.CancelledError
E                   TimeoutError
E               Failed: the despatch never waited on the held stock row: no locking SELECT on stock was seen ungranted, so the despatch does not take the SA-4 lock (FS25)
FAILED services/fulfillment/tests/integration/test_despatch_race.py::test_fs25_a_despatch_waits_for_a_transaction_holding_a_stock_row_of_the_order_before_reading_its_reservations
```

### I1b_v2 -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_repository.py`; backup `.arm/impl18/bak/I1b_v2__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_repository.py`; sha256 `1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9`
- test: `services/fulfillment/tests/integration/test_despatch_race.py::test_sa4_release_wins_the_despatch_finds_nothing_to_consume_and_creates_no_advice`
- mutation: `.where(Stock.company_code == company_code, Stock.product_code == product_code)
                .with_for_update()` -> `.where(Stock.company_code == company_code, Stock.product_code == product_code)`
- note: v2; supersedes I1b
- failure (verbatim, first lines):
```
E           asyncio.exceptions.CancelledError
E                   TimeoutError
E               Failed: fulfillment.stock.release never waited on the held stock row: it does not take the lock
FAILED services/fulfillment/tests/integration/test_despatch_race.py::test_sa4_release_wins_the_despatch_finds_nothing_to_consume_and_creates_no_advice
```

### I1c_v2 -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_repository.py`; backup `.arm/impl18/bak/I1c_v2__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_repository.py`; sha256 `1088a62c0e5393a0c680fd00129eb68cf01139f6e9b4ae699c2c2f50fd0dddc9`
- test: `services/fulfillment/tests/integration/test_despatch_race.py::test_sa4_despatch_wins_the_release_answers_precondition_failed_and_changes_nothing`
- mutation: `.where(Stock.company_code == company_code, Stock.product_code == product_code)
                .with_for_update()` -> `.where(Stock.company_code == company_code, Stock.product_code == product_code)`
- note: v2; supersedes I1c
- failure (verbatim, first lines):
```
E           asyncio.exceptions.CancelledError
E                   TimeoutError
E               Failed: fulfillment.despatch.create never waited on the held stock row: it does not take the lock
FAILED services/fulfillment/tests/integration/test_despatch_race.py::test_sa4_despatch_wins_the_release_answers_precondition_failed_and_changes_nothing
```

### I3a_v2 -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/I3a_v2__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/integration/test_despatch_create.py::test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number`
- mutation: `existing = await tx.despatches.find_by_order_reference(command.order_reference)` -> `existing = None`
- note: v2; the in-lock re-read removed: the loser's reply is in the failure text
- failure (verbatim, first lines):
```
E       AssertionError: exactly one repeats: {'00000000-0000-0000-0000-0000000000a1': {'orderReference': 'ORD-000042', 'despatchReference': 'DES-000001', 'despatchDate': '2026-10-08T08:17:19.681Z', 'created': True, 'lines': [{'productCode': 'PRD-A1', 'units': 3}, {'productCode': 'PRD-B2', 'units': 5
E       assert 0 == 1
E        +  where 0 = len([])
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/fulfillment/tests/integration/test_despatch_create.py:260: AssertionError
FAILED services/fulfillment/tests/integration/test_despatch_create.py::test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number
```

### I3b_v2 -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/I3b_v2__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/integration/test_despatch_create.py::test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number`
- mutation: `if ReservationStatus.CONSUMED in statuses:` -> `if False:`
- note: v2; the whole F8 in-lock branch removed
- failure (verbatim, first lines):
```
E       AssertionError: exactly one repeats: {'00000000-0000-0000-0000-0000000000a1': {'orderReference': 'ORD-000042', 'despatchReference': 'DES-000001', 'despatchDate': '2026-10-08T08:17:41.361Z', 'created': True, 'lines': [{'productCode': 'PRD-A1', 'units': 3}, {'productCode': 'PRD-B2', 'units': 5
E       assert 0 == 1
E        +  where 0 = len([])
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/fulfillment/tests/integration/test_despatch_create.py:260: AssertionError
FAILED services/fulfillment/tests/integration/test_despatch_create.py::test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number
```

### I4_v2 -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py`; backup `.arm/impl18/bak/I4_v2__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_transactions.py`; sha256 `ecce609b483c6683973e93be143ad9aca1a5ddd54c8c171d6d286425bb608abf`
- test: `services/fulfillment/tests/integration/test_despatch_create.py::test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number`
- mutation: `"isolation_level": "READ COMMITTED"` -> `"isolation_level": "REPEATABLE READ"`
- note: v2; #8 id 54
- failure (verbatim, first lines):
```
E       AssertionError: exactly one repeats: {'00000000-0000-0000-0000-0000000000a1': {'orderReference': 'ORD-000042', 'despatchReference': 'DES-000001', 'despatchDate': '2026-10-08T08:18:02.998Z', 'created': True, 'lines': [{'productCode': 'PRD-A1', 'units': 3}, {'productCode': 'PRD-B2', 'units': 5
E       assert 0 == 1
E        +  where 0 = len([])
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/fulfillment/tests/integration/test_despatch_create.py:260: AssertionError
FAILED services/fulfillment/tests/integration/test_despatch_create.py::test_f8_two_concurrent_despatches_of_one_order_yield_one_advice_one_fact_and_one_number
```

### I7_v2 -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/despatch_repository.py`; backup `.arm/impl18/bak/I7_v2__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__despatch_repository.py`; sha256 `6f876278ed29476c09fac89d2962555f88cc6bc037f033971b8b56ae24159ef0`
- test: `services/fulfillment/tests/integration/test_despatch_store.py::test_fs24_every_id_of_the_advice_its_lines_and_its_fact_is_a_supplied_id_in_minting_order`
- mutation: `advice.id.value` -> `UUID(int=0xBAD)`
- note: v2: the header id AND the lines' despatch_id both become 0xBAD, so the FK holds and only the provenance claim breaks; supersedes I7
- failure (verbatim, first lines):
```
E       AssertionError: assert UUID('00000000-0000-0000-0000-000000000bad') == UUID('00000000-0000-0000-0000-0000000000ad')
E        +  where UUID('00000000-0000-0000-0000-0000000000ad') = <class 'uuid.UUID'>(int=173)
E        +    where <class 'uuid.UUID'> = uuid.UUID
services/fulfillment/tests/integration/test_despatch_store.py:355: AssertionError
FAILED services/fulfillment/tests/integration/test_despatch_store.py::test_fs24_every_id_of_the_advice_its_lines_and_its_fact_is_a_supplied_id_in_minting_order
```

### W1_route_dropped -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/presentation/stock_responder.py`; backup `.arm/impl18/bak/W1_route_dropped__services__fulfillment__src__otc_fulfillment__presentation__stock_responder.py`; sha256 `1eff8654d6bfc80f47318ffdb33d00fe3339da574c339d5f5afaef46badecffb`
- test: `services/fulfillment/tests/unit/test_despatch_wire.py::test_the_despatch_subject_is_one_entry_of_the_responders_subject_table`
- mutation: `DESPATCH_CREATE_SUBJECT: _despatch,` -> ``
- failure (verbatim, first lines):
```
E       AssertionError: assert 'fulfillment.despatch.create' in {'fulfillment.stock.check': <function _check at 0x7990d716ef00>, 'fulfillment.stock.reserve': <function _reserve at 0x...ock.release': <function _release at 0x7990d716f320>, 'fulfillment.stock.list': <function _list at 0x7990d716f060>, 
services/fulfillment/tests/unit/test_despatch_wire.py:143: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_wire.py::test_the_despatch_subject_is_one_entry_of_the_responders_subject_table
```

### W2_headers_not_required -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/presentation/stock_responder.py`; backup `.arm/impl18/bak/W2_headers_not_required__services__fulfillment__src__otc_fulfillment__presentation__stock_responder.py`; sha256 `1eff8654d6bfc80f47318ffdb33d00fe3339da574c339d5f5afaef46badecffb`
- test: `services/fulfillment/tests/unit/test_despatch_wire.py::test_fs3_despatch_replies_validation_failed_and_dispatches_nothing_when_a_header_is_missing_or_malformed[no headers at all]`
- mutation: `correlation = required_correlation(headers)  # the fact's correlationId / causationId (R12)` -> `correlation = required_correlation({'x-correlation-id': str(__import__('uuid').uuid4()), 'x-request-id': str(__import__('uuid').uuid4())})`
- failure (verbatim, first lines):
```
E       assert <Code.internal_error: 'INTERNAL_ERROR'> is <Code.validation_failed: 'VALIDATION_FAILED'>
E        +  where <Code.internal_error: 'INTERNAL_ERROR'> = RpcError(code=<Code.internal_error: 'INTERNAL_ERROR'>, message='The request could not be processed.', details=None, correlation_id=None, occurred_at=datetime.datetime(2026, 10, 8, 9, 0, 0, 123000, tzinfo=TzInfo(0))).code
E        +    where RpcError(code=<Code.internal_error: 'INTERNAL_ERROR'>, message='The request could not be processed.', details=None, correlation_id=None, occurred_at=datetime.datetime(2026, 10, 8, 9, 0, 0, 123000, tzinfo=TzInfo(0))) = from_wire_json(RpcError, b'{"code":"INTERNAL_ERROR","message":
E        +  and   <Code.validation_failed: 'VALIDATION_FAILED'> = Code.validation_failed
services/fulfillment/tests/unit/test_despatch_wire.py:169: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_wire.py::test_fs3_despatch_replies_validation_failed_and_dispatches_nothing_when_a_header_is_missing_or_malformed[no headers at all]
```

### W3_command_ids_swapped -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/presentation/stock_wire.py`; backup `.arm/impl18/bak/W3_command_ids_swapped__services__fulfillment__src__otc_fulfillment__presentation__stock_wire.py`; sha256 `e0f71b4aeb97ca2df64901e005dae7d64fa420014f28fc88a0bafdea5aec68ee`
- test: `services/fulfillment/tests/unit/test_despatch_wire.py::test_fs3_the_despatch_command_carries_the_correlation_and_request_ids_of_the_headers`
- mutation: `return CreateDespatchCommand(
        order_reference=_order_reference(request.order_reference),
        correlation_id=correlation.correlat` -> `return CreateDespatchCommand(
        order_reference=_order_reference(request.order_reference),
        correlation_id=correlation.request_`
- failure (verbatim, first lines):
```
E       AssertionError: assert CreateDespatc...00000000c0'))) == CreateDespatc...00000000ca')))
E         
E         Omitting 1 identical items, use -vv to show
E         Differing attributes:
E         ['correlation_id', 'request_id']
E         
E         Drill down into differing attribute correlation_id:
E           correlation_id: UniqueId(value=UUID('00000000-0000-0000-0000-0000000000ca')) != UniqueId(value=UUID('00000000-0000-0000-0000-0000000000c0'))...
```

### W4_no_length_edge_check -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/presentation/stock_wire.py`; backup `.arm/impl18/bak/W4_no_length_edge_check__services__fulfillment__src__otc_fulfillment__presentation__stock_wire.py`; sha256 `e0f71b4aeb97ca2df64901e005dae7d64fa420014f28fc88a0bafdea5aec68ee`
- test: `services/fulfillment/tests/unit/test_despatch_wire.py::test_f2_each_constraint_violation_of_the_despatch_request_is_refused_by_the_decoder[orderReference longer than the column]`
- mutation: `return CreateDespatchCommand(
        order_reference=_order_reference(request.order_reference),` -> `return CreateDespatchCommand(
        order_reference=request.order_reference,`
- failure (verbatim, first lines):
```
E       Failed: DID NOT RAISE InvalidStockRequestError
FAILED services/fulfillment/tests/unit/test_despatch_wire.py::test_f2_each_constraint_violation_of_the_despatch_request_is_refused_by_the_decoder[orderReference longer than the column]
```

### W5_created_constant -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/presentation/stock_wire.py`; backup `.arm/impl18/bak/W5_created_constant__services__fulfillment__src__otc_fulfillment__presentation__stock_wire.py`; sha256 `e0f71b4aeb97ca2df64901e005dae7d64fa420014f28fc88a0bafdea5aec68ee`
- test: `services/fulfillment/tests/unit/test_despatch_wire.py::test_r36_the_despatch_reply_carries_every_field_of_the_advice_and_the_created_flag[False]`
- mutation: `created=result.created,` -> `created=True,`
- failure (verbatim, first lines):
```
E       AssertionError: assert {'orderRefere...d': True, ...} == {'orderRefere...': False, ...}
E         
E         Omitting 4 identical items, use -vv to show
E         Differing items:
E         {'created': True} != {'created': False}
E         Use -v to get more diff
services/fulfillment/tests/unit/test_despatch_wire.py:236: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_wire.py::test_r36_the_despatch_reply_carries_every_field_of_the_advice_and_the_created_flag[False]
```

### W6_lines_reversed -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/presentation/stock_wire.py`; backup `.arm/impl18/bak/W6_lines_reversed__services__fulfillment__src__otc_fulfillment__presentation__stock_wire.py`; sha256 `e0f71b4aeb97ca2df64901e005dae7d64fa420014f28fc88a0bafdea5aec68ee`
- test: `services/fulfillment/tests/unit/test_despatch_wire.py::test_r36_the_despatch_reply_carries_every_field_of_the_advice_and_the_created_flag[True]`
- mutation: `for line in advice.lines
        ],
    )


def encode` -> `for line in reversed(advice.lines)
        ],
    )


def encode`
- failure (verbatim, first lines):
```
E       AssertionError: assert {'orderRefere...d': True, ...} == {'orderRefere...d': True, ...}
E         
E         Omitting 4 identical items, use -vv to show
E         Differing items:
E         {'lines': [{'productCode': 'PRD-B2', 'units': 5}, {'productCode': 'PRD-A1', 'units': 3}]} != {'lines': [{'productCode': 'PRD-A1', 'units': 3}, {'productCode': 'PRD-B2', 'units': 5}]}
E         Use -v to get more diff
services/fulfillment/tests/unit/test_despatch_wire.py:236: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_wire.py::test_r36_the_despatch_reply_carries_every_field_of_the_advice_and_the_created_flag[True]
```

### E1_no_reserved_is_unavailable -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/presentation/stock_rpc_errors.py`; backup `.arm/impl18/bak/E1_no_reserved_is_unavailable__services__fulfillment__src__otc_fulfillment__presentation__stock_rpc_errors.py`; sha256 `57a9b2b5e3e3a063cec4d281b138df6890997c476f9a7d034c18d57a62120a1f`
- test: `services/fulfillment/tests/unit/test_despatch_wire.py::test_r36_no_reserved_stock_is_precondition_failed_with_the_order_reference`
- mutation: `return rpc(
                Code.precondition_failed, str(error), {"orderReference": error.order_reference}
            )` -> `return rpc(Code.unavailable, str(error), {"orderReference": error.order_reference})`
- failure (verbatim, first lines):
```
E       AssertionError: assert <Code.unavailable: 'UNAVAILABLE'> is <Code.precondition_failed: 'PRECONDITION_FAILED'>
E        +  where <Code.unavailable: 'UNAVAILABLE'> = RpcError(code=<Code.unavailable: 'UNAVAILABLE'>, message='despatch.create: order ORD-000042 holds no reservation in st...00-0000-0000-0000000000c0'), occurred_at=datetime.datetime(2026, 10, 8, 9, 0, 0, 123000, tzinfo=datetime.timezone.utc)).code
E        +  and   <Code.precondition_failed: 'PRECONDITION_FAILED'> = Code.precondition_failed
services/fulfillment/tests/unit/test_despatch_wire.py:255: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_wire.py::test_r36_no_reserved_stock_is_precondition_failed_with_the_order_reference
```

### E2_inconsistency_is_conflict -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/presentation/stock_rpc_errors.py`; backup `.arm/impl18/bak/E2_inconsistency_is_conflict__services__fulfillment__src__otc_fulfillment__presentation__stock_rpc_errors.py`; sha256 `57a9b2b5e3e3a063cec4d281b138df6890997c476f9a7d034c18d57a62120a1f`
- test: `tests/architecture/test_fulfillment_rpc_error_retryability.py::test_fs21_every_transient_store_failure_maps_to_a_code_the_saga_adapter_retries`
- mutation: `case (
            StoreUnavailableError()` -> `case ConcurrentDespatchChangeError():
            return rpc(Code.conflict, str(error))
        case (
            StoreUnavailableError()`
- failure (verbatim, first lines):
```
E           AssertionError: ConcurrentDespatchChangeError(order ORD-000042 holds consumed reservations but has no despatch advice) is answered CONFLICT, which Orders' saga adapter treats as a terminal rejection
E           assert <Code.conflict: 'CONFLICT'> not in frozenset({<Code.conflict: 'CONFLICT'>, <Code.domain_error: 'DOMAIN_ERROR'>, <Code.invoice_not_payable: 'INVOICE_NOT_P...'NOT_FOUND'>, <Code.order_not_cancellable: 'ORDER_NOT_CANCELLABLE'>, <Code.payment_mismatch: 'PAYMENT_MISMATCH'>, ...})
tests/architecture/test_fulfillment_rpc_error_retryability.py:70: AssertionError
FAILED tests/architecture/test_fulfillment_rpc_error_retryability.py::test_fs21_every_transient_store_failure_maps_to_a_code_the_saga_adapter_retries
```

### E3_no_reserved_case_dropped -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/presentation/stock_rpc_errors.py`; backup `.arm/impl18/bak/E3_no_reserved_case_dropped__services__fulfillment__src__otc_fulfillment__presentation__stock_rpc_errors.py`; sha256 `57a9b2b5e3e3a063cec4d281b138df6890997c476f9a7d034c18d57a62120a1f`
- test: `services/fulfillment/tests/unit/test_despatch_wire.py::test_r36_no_reserved_stock_is_precondition_failed_with_the_order_reference`
- mutation: `case NoReservedStockForDespatchError():` -> `case ConnectionAbortedError():`
- failure (verbatim, first lines):
```
E       AssertionError: assert <Code.internal_error: 'INTERNAL_ERROR'> is <Code.precondition_failed: 'PRECONDITION_FAILED'>
E        +  where <Code.internal_error: 'INTERNAL_ERROR'> = RpcError(code=<Code.internal_error: 'INTERNAL_ERROR'>, message='The request could not be processed.', details=None, co...00-0000-0000-0000000000c0'), occurred_at=datetime.datetime(2026, 10, 8, 9, 0, 0, 123000, tzinfo=datetime.timezone.utc))
E        +  and   <Code.precondition_failed: 'PRECONDITION_FAILED'> = Code.precondition_failed
services/fulfillment/tests/unit/test_despatch_wire.py:255: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_wire.py::test_r36_no_reserved_stock_is_precondition_failed_with_the_order_reference
```

### P1_company_retailer_swapped -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/outbox/payloads.py`; backup `.arm/impl18/bak/P1_company_retailer_swapped__services__fulfillment__src__otc_fulfillment__infrastructure__outbox__payloads.py`; sha256 `7a310e04d4fc164a921e8a68fbc1c9ec9b56d3863a830bcb71266d18545d13d3`
- test: `services/fulfillment/tests/unit/test_despatch_payload.py::test_r36_the_despatched_fact_becomes_its_envelope_and_payload_with_every_field_equal_to_the_supplied_value`
- mutation: `company_code=event.company_code,
        retailer_code=event.retailer_code,
        lines=[_despatch_line` -> `company_code=event.retailer_code,
        retailer_code=event.company_code,
        lines=[_despatch_line`
- failure (verbatim, first lines):
```
E       AssertionError: assert {'orderRefere...'RET-77', ...} == {'orderRefere...'CMP-88', ...}
E         
E         Omitting 4 identical items, use -vv to show
E         Differing items:
E         {'companyCode': 'RET-77'} != {'companyCode': 'CMP-88'}
E         {'retailerCode': 'CMP-88'} != {'retailerCode': 'RET-77'}
E         Use -v to get more diff
services/fulfillment/tests/unit/test_despatch_payload.py:52: AssertionError
```

### P2_date_not_truncated -- GREEN (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/outbox/payloads.py`; backup `.arm/impl18/bak/P2_date_not_truncated__services__fulfillment__src__otc_fulfillment__infrastructure__outbox__payloads.py`; sha256 `7a310e04d4fc164a921e8a68fbc1c9ec9b56d3863a830bcb71266d18545d13d3`
- test: `services/fulfillment/tests/unit/test_despatch_payload.py::test_r36_the_despatch_date_in_the_payload_is_the_same_millisecond_as_the_envelopes`
- mutation: `despatch_date=wire_instant(event.despatch_date),` -> `despatch_date=event.despatch_date,`
- failure (verbatim, first lines):
```

```

### P3_lines_reversed -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/outbox/payloads.py`; backup `.arm/impl18/bak/P3_lines_reversed__services__fulfillment__src__otc_fulfillment__infrastructure__outbox__payloads.py`; sha256 `7a310e04d4fc164a921e8a68fbc1c9ec9b56d3863a830bcb71266d18545d13d3`
- test: `services/fulfillment/tests/unit/test_despatch_payload.py::test_r36_the_despatched_fact_becomes_its_envelope_and_payload_with_every_field_equal_to_the_supplied_value`
- mutation: `lines=[_despatch_line(line) for line in event.lines],` -> `lines=[_despatch_line(line) for line in reversed(event.lines)],`
- failure (verbatim, first lines):
```
E       AssertionError: assert {'orderRefere...'CMP-88', ...} == {'orderRefere...'CMP-88', ...}
E         
E         Omitting 5 identical items, use -vv to show
E         Differing items:
E         {'lines': [{'productCode': 'PRD-B2', 'units': 5}, {'productCode': 'PRD-A1', 'units': 3}]} != {'lines': [{'productCode': 'PRD-A1', 'units': 3}, {'productCode': 'PRD-B2', 'units': 5}]}
E         Use -v to get more diff
services/fulfillment/tests/unit/test_despatch_payload.py:52: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_payload.py::test_r36_the_despatched_fact_becomes_its_envelope_and_payload_with_every_field_equal_to_the_supplied_value
```

### P4_aggregate_id_is_correlation -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/outbox/payloads.py`; backup `.arm/impl18/bak/P4_aggregate_id_is_correlation__services__fulfillment__src__otc_fulfillment__infrastructure__outbox__payloads.py`; sha256 `7a310e04d4fc164a921e8a68fbc1c9ec9b56d3863a830bcb71266d18545d13d3`
- test: `services/fulfillment/tests/unit/test_despatch_payload.py::test_r36_the_despatched_fact_becomes_its_envelope_and_payload_with_every_field_equal_to_the_supplied_value`
- mutation: `aggregate_id=event.aggregate_id.value,` -> `aggregate_id=event.correlation_id.value,`
- failure (verbatim, first lines):
```
E       AssertionError: the despatch advice's own id
E       assert '00000000-000...-000000000003' == '00000000-000...-000000000002'
E         
E         - 00000000-0000-4000-8000-000000000002
E         ?                                    ^
E         + 00000000-0000-4000-8000-000000000003
E         ?                                    ^
services/fulfillment/tests/unit/test_despatch_payload.py:75: AssertionError
```

### C1_registration_dropped -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/composition.py`; backup `.arm/impl18/bak/C1_registration_dropped__services__fulfillment__src__otc_fulfillment__composition.py`; sha256 `75625c7da75e492e4d486427840bb6fc945cc481bd4480269ce48f1bbf9e3159`
- test: `tests/architecture/test_registration_behaviour.py::test_a_service_registers_only_from_its_composition_root_and_its_tables_match[fulfillment]`
- mutation: `registry.register_command(CreateDespatchCommand, CreateDespatchHandler)` -> ``
- failure (verbatim, first lines):
```
E       AssertionError: the probe could not run otc_fulfillment:
E         Traceback (most recent call last):
E           File "<string>", line 39, in <module>
E             dispatcher = composition.build_dispatcher()
E           File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/fulfillment/src/otc_fulfillment/composition.py", line 124, in build_dispatcher
E             return _wire()[0]
E                    ~~~~~^^
E           File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/fulfillment/src/otc_fulfillment/composition.py", line 116, in _wire
```

### C2_table_literal_without_despatch -- RED (expected red), restored green rerun exit 0
- file: `tests/architecture/test_registration_behaviour.py`; backup `.arm/impl18/bak/C2_table_literal_without_despatch__tests__architecture__test_registration_behaviour.py`; sha256 `c64eaf6edbe7ba60004ee6ef346f8f1d938f7d5ab9092f9c778f254ff72e28dc`
- test: `tests/architecture/test_registration_behaviour.py::test_a_service_registers_only_from_its_composition_root_and_its_tables_match[fulfillment]`
- mutation: `"ReplenishStockCommand",
                "CreateDespatchCommand",` -> `"ReplenishStockCommand",`
- note: the pinned literal without the new command (the instrument failing before the edit)
- failure (verbatim, first lines):
```
E       AssertionError: assert ['otc_fulfill...StockCommand'] == ['otc_fulfill...StockCommand']
E         
E         At index 0 diff: 'otc_fulfillment.application.messages.CreateDespatchCommand' != 'otc_fulfillment.application.messages.ReleaseStockCommand'
E         Left contains one more item: 'otc_fulfillment.application.messages.ReserveStockCommand'
E         Use -v to get more diff
tests/architecture/test_registration_behaviour.py:238: AssertionError
FAILED tests/architecture/test_registration_behaviour.py::test_a_service_registers_only_from_its_composition_root_and_its_tables_match[fulfillment]
```

### C3_census_without_despatch_repository -- RED (expected red), restored green rerun exit 0
- file: `tests/architecture/test_write_path_population.py`; backup `.arm/impl18/bak/C3_census_without_despatch_repository__tests__architecture__test_write_path_population.py`; sha256 `57b7f0979808356e19ee9ac654bd11f4a7da4cc5dcf2fd578beb9e333fb44c07`
- test: `tests/architecture/test_write_path_population.py::test_every_write_path_in_the_service_is_a_classified_literal[fulfillment]`
- mutation: `"infrastructure/persistence/despatch_repository.py": Counter({("call", "add"): 2}),` -> ``
- failure (verbatim, first lines):
```
E       AssertionError: services/fulfillment/src has an unclassified write path (or lost a classified one, or gained a second occurrence of one): add it to EXPECTED with its classification. Found: {'infrastructure/outbox/relay.py': Counter({('call', 'execute'): 1, ('call', 'update'): 1}), 'infrastru
E       assert {'infrastruct...d'): 2}), ...} == {'infrastruct...d'): 1}), ...}
E         
E         Omitting 7 identical items, use -vv to show
E         Left contains 1 more item:
E         {'infrastructure/persistence/despatch_repository.py': Counter({('call', 'add'): 2})}
E         Use -v to get more diff
tests/architecture/test_write_path_population.py:404: AssertionError
```

### P2b_date_corrupted -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/outbox/payloads.py`; backup `.arm/impl18/bak/P2b_date_corrupted__services__fulfillment__src__otc_fulfillment__infrastructure__outbox__payloads.py`; sha256 `7a310e04d4fc164a921e8a68fbc1c9ec9b56d3863a830bcb71266d18545d13d3`
- test: `services/fulfillment/tests/unit/test_despatch_payload.py::test_r36_the_despatch_date_in_the_payload_is_the_same_millisecond_as_the_envelopes`
- mutation: `despatch_date=wire_instant(event.despatch_date),` -> `despatch_date=wire_instant(event.occurred_at).replace(year=2001),`
- note: P2 (dropping wire_instant) is an EQUIVALENT mutant: to_wire_json truncates the instant itself, so the wire is unchanged; P2b corrupts the field instead
- failure (verbatim, first lines):
```
E       AssertionError: assert '2001-10-08T09:30:05.123Z' == '2026-10-08T09:30:05.123Z'
E         
E         - 2026-10-08T09:30:05.123Z
E         ?   ^^
E         + 2001-10-08T09:30:05.123Z
E         ?   ^^
services/fulfillment/tests/unit/test_despatch_payload.py:87: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_payload.py::test_r36_the_despatch_date_in_the_payload_is_the_same_millisecond_as_the_envelopes
```

### T1_despatch_events_never_cleared -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py`; backup `.arm/impl18/bak/T1_despatch_events_never_cleared__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_transactions.py`; sha256 `ecce609b483c6683973e93be143ad9aca1a5ddd54c8c171d6d286425bb608abf`
- test: `services/fulfillment/tests/unit/test_despatch_transactions.py::test_the_despatch_events_are_cleared_only_after_the_commit_returned`
- mutation: `despatches.clear_saved_events()` -> ``
- failure (verbatim, first lines):
```
E       AssertionError: assert ['begin', 'wo...mit', 'close'] == ['begin', 'wo...patch_events']
E         
E         Right contains one more item: 'clear_despatch_events'
E         Use -v to get more diff
services/fulfillment/tests/unit/test_despatch_transactions.py:89: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_transactions.py::test_the_despatch_events_are_cleared_only_after_the_commit_returned
```

### T2_despatch_events_cleared_before_commit -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py`; backup `.arm/impl18/bak/T2_despatch_events_cleared_before_commit__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_transactions.py`; sha256 `ecce609b483c6683973e93be143ad9aca1a5ddd54c8c171d6d286425bb608abf`
- test: `services/fulfillment/tests/unit/test_despatch_transactions.py::test_the_despatch_events_are_cleared_only_after_the_commit_returned`
- mutation: `)
                # the commit has returned: only now may the aggregates forget their events
                repository.clear_saved_events()` -> `)
                    despatches.clear_saved_events()
                repository.clear_saved_events()`
- failure (verbatim, first lines):
```
E       AssertionError: assert ['begin', 'wo...mit', 'close'] == ['begin', 'wo...patch_events']
E         
E         At index 2 diff: 'clear_despatch_events' != 'commit'
E         Use -v to get more diff
services/fulfillment/tests/unit/test_despatch_transactions.py:89: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_transactions.py::test_the_despatch_events_are_cleared_only_after_the_commit_returned
```

### T3_despatch_events_cleared_on_rollback -- GREEN (expected green), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py`; backup `.arm/impl18/bak/T3_despatch_events_cleared_on_rollback__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_transactions.py`; sha256 `ecce609b483c6683973e93be143ad9aca1a5ddd54c8c171d6d286425bb608abf`
- test: `services/fulfillment/tests/unit/test_despatch_transactions.py::test_the_despatch_events_are_kept_when_the_attempt_rolls_back`
- mutation: `except DBAPIError as error:
                state = sqlstate_of(error)` -> `except DBAPIError as error:
                state = sqlstate_of(error)`
- note: control row: an identity mutation must stay GREEN (the instrument reports green when nothing changed)
- failure (verbatim, first lines):
```

```

### T4_allocator_of_another_session -- RED (expected green), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py`; backup `.arm/impl18/bak/T4_allocator_of_another_session__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_transactions.py`; sha256 `ecce609b483c6683973e93be143ad9aca1a5ddd54c8c171d6d286425bb608abf`
- test: `services/fulfillment/tests/unit/test_despatch_transactions.py::test_the_transaction_hands_work_the_despatch_repository_and_an_allocator_of_its_session`
- mutation: `SqlAlchemyDespatchNumberAllocator(session)` -> `SqlAlchemyDespatchNumberAllocator(despatches._session)`
- note: control: the fake repository's own session IS the attempt's session, so this stays green; the real distinction is I11
- failure (verbatim, first lines):
```
E                   AttributeError: 'FakeDespatchRepository' object has no attribute '_session'. Did you mean: 'session'?
FAILED services/fulfillment/tests/unit/test_despatch_transactions.py::test_the_transaction_hands_work_the_despatch_repository_and_an_allocator_of_its_session
```

### T4b_allocator_of_no_session -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py`; backup `.arm/impl18/bak/T4b_allocator_of_no_session__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_transactions.py`; sha256 `ecce609b483c6683973e93be143ad9aca1a5ddd54c8c171d6d286425bb608abf`
- test: `services/fulfillment/tests/unit/test_despatch_transactions.py::test_the_transaction_hands_work_the_despatch_repository_and_an_allocator_of_its_session`
- mutation: `SqlAlchemyDespatchNumberAllocator(session)` -> `SqlAlchemyDespatchNumberAllocator(None)  # type: ignore[arg-type]`
- note: supersedes T4 (its mutation named a non-existent attribute: red for the wrong reason)
- failure (verbatim, first lines):
```
E       AssertionError: one session, one transaction
E       assert None is <services.fulfillment.tests.unit.test_despatch_transactions.FakeSession object at 0x71cb49844050>
E        +  where None = <otc_fulfillment.infrastructure.persistence.despatch_number_allocator.SqlAlchemyDespatchNumberAllocator object at 0x71cb49844590>._session
E        +  and   <services.fulfillment.tests.unit.test_despatch_transactions.FakeSession object at 0x71cb49844050> = <services.fulfillment.tests.unit.test_despatch_transactions.FakeDespatchRepository object at 0x71cb49844440>.session
services/fulfillment/tests/unit/test_despatch_transactions.py:129: AssertionError
FAILED services/fulfillment/tests/unit/test_despatch_transactions.py::test_the_transaction_hands_work_the_despatch_repository_and_an_allocator_of_its_session
```

### X3_status_not_persisted -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_mapper.py`; backup `.arm/impl18/bak/X3_status_not_persisted__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__stock_mapper.py`; sha256 `9028d00c4985f67cbc8cba2ebc76309b1b543a0d061a0092d02c8ec53ebafe20`
- test: `services/fulfillment/tests/integration/test_despatch_create.py::test_r36_consumes_the_reservations_lowers_both_counters_creates_one_advice_and_writes_exactly_one_despatched_fact`
- mutation: `row.status = view.status.value
    row.updated_at = now
    return True` -> `return True`
- failure (verbatim, first lines):
```
E       AssertionError: assert {'reserved'} == {'consumed'}
E         
E         Extra items in the left set:
E         'reserved'
E         Extra items in the right set:
E         'consumed'
E         Use -v to get more diff
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/fulfillment/tests/integration/test_despatch_create.py:109: AssertionError
```

### X8_header_company_is_retailer -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/despatch_repository.py`; backup `.arm/impl18/bak/X8_header_company_is_retailer__services__fulfillment__src__otc_fulfillment__infrastructure__persistence__despatch_repository.py`; sha256 `6f876278ed29476c09fac89d2962555f88cc6bc037f033971b8b56ae24159ef0`
- test: `services/fulfillment/tests/integration/test_despatch_create.py::test_r36_consumes_the_reservations_lowers_both_counters_creates_one_advice_and_writes_exactly_one_despatched_fact`
- mutation: `company_code=advice.company_code,
                retailer_code=advice.retailer_code,` -> `company_code=advice.retailer_code,
                retailer_code=advice.company_code,`
- failure (verbatim, first lines):
```
E       AssertionError: assert ('RET-9', 'ACME-CO') == ('ACME-CO', 'RET-9')
E         
E         At index 0 diff: 'RET-9' != 'ACME-CO'
E         Use -v to get more diff
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/fulfillment/tests/integration/test_despatch_create.py:104: AssertionError
FAILED services/fulfillment/tests/integration/test_despatch_create.py::test_r36_consumes_the_reservations_lowers_both_counters_creates_one_advice_and_writes_exactly_one_despatched_fact
```

### X9_fast_path_deleted_integration_F8_repeat -- GREEN (expected green), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/X9_fast_path_deleted_integration_F8_repeat__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/integration/test_despatch_create.py::test_f8_a_repeated_despatch_returns_the_existing_advice_changes_nothing_and_emits_no_second_fact`
- mutation: `existing = await scope.reads.despatch_of_order(command.order_reference)
    if existing is not None:
        return DespatchResult(created=F` -> ``
- note: EQUIVALENT at the integration level, by design: the in-lock layer answers the repeat; the fast path's claim is the unit test A3 and the store test I15
- failure (verbatim, first lines):
```

```

### S3_consume_ignores_status -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/domain/stock_item.py`; backup `.arm/impl18/bak/S3_consume_ignores_status__services__fulfillment__src__otc_fulfillment__domain__stock_item.py`; sha256 `d1d2765e5cf8483c9825c881a78e8ae8b8313ad478a462cf4875969fbcd185bc`
- test: `services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_an_item_holding_only_released_reservations_of_the_order_is_left_alone_among_reserved_ones`
- mutation: `if r.order_reference == order_reference and r.status is ReservationStatus.RESERVED
        ]
        total = sum(r.units for r in moving)
  ` -> `if r.order_reference == order_reference
        ]
        total = sum(r.units for r in moving)
        for reservation in moving:
          `
- failure (verbatim, first lines):
```
E           otc_fulfillment.domain.errors.ReservationTerminalError: A reservation that is 'released' cannot become 'consumed': 'released' and 'consumed' are terminal.
FAILED services/fulfillment/tests/unit/domain/test_despatch.py::test_r36_an_item_holding_only_released_reservations_of_the_order_is_left_alone_among_reserved_ones
```

### B8_defensive_nothing_branch -- RED (expected red), restored green rerun exit 0
- file: `services/fulfillment/src/otc_fulfillment/application/despatch_creation.py`; backup `.arm/impl18/bak/B8_defensive_nothing_branch__services__fulfillment__src__otc_fulfillment__application__despatch_creation.py`; sha256 `284595666fb121310920121943ba0f96224110bc3eb4728056884a6034872f8e`
- test: `services/fulfillment/tests/unit/test_despatch_creation_service.py::test_a_reserved_row_the_loaded_items_do_not_hold_despatches_nothing_and_is_refused`
- mutation: `# unreachable: a `reserved` reservation was just seen under the lock
            raise NoReservedStockForDespatchError(command.order_referen` -> `# unreachable: a `reserved` reservation was just seen under the lock
            return DespatchResult(created=False, despatch=None)  # type`
- failure (verbatim, first lines):
```
E       Failed: DID NOT RAISE NoReservedStockForDespatchError
FAILED services/fulfillment/tests/unit/test_despatch_creation_service.py::test_a_reserved_row_the_loaded_items_do_not_hold_despatches_nothing_and_is_refused
```
