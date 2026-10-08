# Requirements — `fulfillment_stock` (feature 17, phase 9, `sdd: true`)

> **This is a pointer document.** `specs/shared/` was copied verbatim from #8 (with `SA-1` – `SA-5` applied) and is **read-only**. The shared requirements this feature realises are cited by id and **not restated**: `specs/shared/requirements.md` §4 (lines 237 – 300) is their single authority, elaborated by `specs/shared/domain-model.md` §4.1 – §4.2 (`StockItem`, `Reservation`, invariants **F1** – **F5**, the lifecycle table), `specs/shared/saga.md` §2 (command vocabulary and idempotency keys), §4.1 (*"the race is real and intentional"*), §4.2's SA-4 paragraph (lines 228 – 245: *"Fulfillment shall decide `stock.release` and `despatch.create` for one order under one lock"*), §5 (line 296, the consumption map) and §6 layer 3, and by `specs/shared/asyncapi.yaml` (the five `fulfillment.stock.*` channels, `RpcHeaders`, `RpcError` and its twelve-value `code` enum, the `StockReserved` / `StockRejected` / `StockReleased` payloads, the `fulfillmentFacts` topic). Nothing below amends, rewords or reinterprets them. The stack-specific value of this feature is in [`design.md`](./design.md).
>
> **Local ids.** This file reuses #8's local ids **`FS2` – `FS22`** with their numbering unchanged (`FS2` – `FS17` are #7's, `FS18` – `FS22` #8's; `../order-to-cash-dotnet/specs/fulfillment_stock/requirements.md` §1.2 – §1.10). Reusing an id is a claim that the Python / PostgreSQL / nats-py realisation owes the same obligation; each was checked against `design.md` before it was written down, and where the mechanism differs a *#9 note* says how. **`FS1` is not claimed**, for #8's reason (§1.1 of #8's file: #9's saga makes the same choice, `specs/order_saga_orchestrator/design.md` L10, and this feature makes no Orders change). **`FS23` – `FS28` are new in #9**, each tied to an acceptance item of `feature_list.json` id 17 or to a #8 backlog finding, and each says why #7 and #8 did not carry it.

## 1. Shared requirements realised

| Shared id | One-line reminder (authority: `specs/shared/requirements.md` §4) | Realised in #9 by | `design.md` |
|---|---|---|---|
| **R30** | `reservedUnits ≤ units`; a breaking operation is rejected in full (**F1**) | `StockItem.reserve` refuses by subtraction (`requested > units − reserved_units`), `StockItem.rehydrate` refuses a snapshot that breaks F1; no `CHECK` constraint (the phase-6 schema has none, and a constraint could not produce a `stock.rejected.v1` fact) | §5.1, §5.5 |
| **R31** | Availability check answers per line, mutates nothing, emits nothing | One plain `SELECT` in a short session at `READ COMMITTED`, no lock, no transaction write, no outbox row; an unknown product answers `available: 0, sufficient: false` (FS22) | §6.1, §9.3 |
| **R32** | Every line satisfiable → one reservation per line, `reservedUnits` up, exactly one `stock.reserved.v1` | `reserve_order` (pure domain service) under the stock-row locks of §6.2; one fact on the carrier item (FS13) | §5.3, §6.2 |
| **R33** | Any short line → no reservation, `reservedUnits` unchanged, `stock.rejected.v1` naming requested and available (**F3**) | `reserve_order` evaluates every product before mutating any item; shortages listed per product, requested = the summed units of that product's lines | §5.3 |
| **R34** | `stock.release` releases once; all already `released` → success no-op with no second fact (**F5**) | `release_order` under the SA-4 lock (§6.3); empty released set → `already_released`, nothing written | §5.3, §6.3 |
| **R35** | Only `reserved → released` / `reserved → consumed`; terminals are terminal (**F4**) | `Reservation.release` / `Reservation.consume` raise `ReservationTerminalError` from either terminal and change nothing | §5.2 |
| **R61** (domain half) | Replenishment adds on-hand `units` only, emits no fact | `StockItem.replenish` appends no domain event; the replenish transaction writes no outbox row; the column width is enforced at the write boundary (FS20) | §5.1, §6.4 |

**Reusing an id is a claim.** Every row asserts the Python realisation satisfies the requirement #7's and #8's do. Two rows differ in mechanism, not in obligation, and the design argues each: R30's arithmetic is unbounded Python `int` with the column width enforced by the write-boundary range guard rather than by #8's in-domain `int.MaxValue` guards (ledger L5); R32 / R33's lock is PostgreSQL `SELECT … FOR UPDATE` per stock row at a pinned `READ COMMITTED`, which supplies the current read #7 got from InnoDB and #8 from `UPDLOCK, HOLDLOCK` but **not** their key-range protection (ledger L2, gate point **G1**).

### 1.1 What this feature does not realise, and who does

| Not here | Owner | Why there |
|---|---|---|
| **R36** (`despatch.create`, `DespatchAdvice`, `order.despatched.v1`) | feature **18** `fulfillment_despatch` | This feature ships `StockItem.consume`, the `reserved → consumed` edge (R35), the SA-4 lock as a repository method, and the responder table that takes a sixth subject; nothing calls `consume` yet (`design.md` §15) |
| **R61**'s API half (`api/stock-replenishment.spec`) | feature **31** `api_tests` (the route itself is feature **25** `gateway_rest_auth`) | Needs the Gateway; the same split R1 has (`specs/shared/test-matrix.md`, scoped row R1) |
| The despatch half of SA-4 (`despatch.create` takes the same lock; the release-versus-despatch race in both outcomes) | feature **18** | This feature builds and guards the release half (FS25) |
| `traceparent` / `x-deadline-ms` on RPC headers, consumer DLQ, metrics | feature **27** | No responder reads them yet; no `TIMEOUT` is produced by a responder (`asyncapi.yaml` `RpcError.code`: *"`TIMEOUT` is produced by the caller"*) |
| `StockItem.productName` on the stock page (#8 id 101) | feature **29** `web_app` | Fulfillment owns stock by product code only; `asyncapi.yaml` `StockView` has no name field (`design.md` §17) |

## 2. Local requirements

### 2.1 Reused from #7 and #8 (`FS2` – `FS22`)

Texts are #8's, verbatim except where a `#9 note` is attached; line-unwrapped only.

**FS2.** WHEN the orchestrator issues any of the five saga commands over the RPC transport, THE SYSTEM SHALL carry the request headers `x-correlation-id` = the order id and `x-request-id` = the id of the durable `saga_commands` row being dispatched, and SHALL carry the same two values on every in-line retry and every sweeper re-issue of that row. The `stock.check` call made at order acceptance SHALL carry neither header, because no order exists yet.

> *#9 note.* **Already realised by feature 16**, which is why this feature makes no Orders change: `services/orders/src/otc_orders/infrastructure/messaging/nats_saga_commands.py:143-146` (a fresh header dict per call), proven by `services/orders/tests/integration/saga/test_saga_command_headers.py::test_so14_every_attempt_carries_the_order_id_and_one_request_id_per_command_row_on_both_paths` (SO14). The stock check sends no headers (`nats_stock_availability.py:58-62`). Cited here so FS3's premise is a checked fact, not an assumption.

**FS3.** WHEN Fulfillment emits a fact in response to a `stock.reserve` or `stock.release` command, THE SYSTEM SHALL set the fact's `correlationId` from the request's `x-correlation-id` header and its `causationId` from the request's `x-request-id` header (`R12`); IF either header is absent or is not a well-formed `UniqueId`, THEN THE SYSTEM SHALL reply `RpcError` `VALIDATION_FAILED`, SHALL mutate no stock item and SHALL emit no fact. `stock.check`, `stock.list` and `stock.replenish` SHALL require neither header.

**FS4.** THE SYSTEM SHALL accept each of the five `fulfillment.stock.*` requests as a **bare JSON** payload matching the AsyncAPI request schema — no framework packet envelope around it — and SHALL reply with a **bare JSON** success payload or a bare JSON `RpcError`, serialised through the one shared serializer; a responder SHALL never reply with anything else and SHALL never leave a request unanswered on any path it can reach.

> *#9 note.* The one serializer is `otc_contracts.to_wire_json` (compact, `ensure_ascii=False`, `.mmmZ` instants); requests are parsed by `from_wire_json` into the generated models (strict integers). "Never unanswered" excludes a message with no reply subject, which is logged and dropped exactly as Orders' responder does (`orders_create_responder.py:111-113`).

**FS5.** WHILE reservation rows already exist for the request's `orderReference` — **in any status**, including `released` and `consumed` — THE SYSTEM SHALL reply to `stock.reserve` with `outcome: already_reserved` carrying the existing reservation references, SHALL change no `reservedUnits`, SHALL create no reservation and SHALL emit no second `stock.reserved.v1`.

> *#9 note.* "Exist for the order" means every reservation row of the order, on any product — #8's reading (`StockLockResult.ExistingReservationsOfOrder`), not #7's (scoped to the stock rows just locked, `apps/fulfillment/src/infrastructure/persistence/stock-item.repository.ts:56-61`). The concurrent case with disjoint product sets is gate point **G1**.

**FS6.** WHEN executing `stock.reserve`, THE SYSTEM SHALL acquire an exclusive lock on every stock row named by the order's lines **before** evaluating availability or reading the order's existing reservations, so that IF two `stock.reserve` commands for different orders compete for the last units of one item concurrently, THEN exactly one commits a reservation and emits `stock.reserved.v1` and the other emits `stock.rejected.v1` naming the shortage — never both reserving, never a deadlock between them.

**FS7.** IF a line was reported `sufficient` by an earlier `stock.check` and is no longer satisfiable when `stock.reserve` runs, THEN THE SYSTEM SHALL reject per `R33` exactly as it would have without the earlier check — the check is a non-locking read that holds nothing (`R31`) and its reply is never a promise.

**FS8.** IF any line of a `stock.reserve` request names a `productCode` for which no stock item exists under the request's `companyCode`, THEN THE SYSTEM SHALL treat that line as short with `available: 0`, SHALL create no reservation for any line (`R33`, **F3**), and SHALL emit `stock.rejected.v1` with `reason: unknown_product`; WHEN every line names a known item and at least one is short, the reason SHALL be `insufficient_stock`.

> *#9 note.* "Exists" is exact equality of codes: PostgreSQL's deterministic collation does not equate letter-case variants, which #7's and #8's case-insensitive collations did (gate point **G2**).

**FS9.** WHEN `stock.release` is received for an `orderReference` that holds **no** reservation row at all, THE SYSTEM SHALL reply `outcome: already_released` with an empty `released` list, SHALL change no counter and SHALL emit no fact.

**FS10.** IF `stock.release` is received for an order whose reservations are in status `consumed`, THEN THE SYSTEM SHALL reply `RpcError` `PRECONDITION_FAILED`, SHALL change no reservation and no counter and SHALL emit no fact (**F4**, `R35`).

> *#9 note.* This is also SA-4's *"the despatch wins"* outcome seen from the release side (`saga.md` lines 240 – 245): Orders classifies `PRECONDITION_FAILED` as terminal (`nats_saga_commands.py:174`, the set at 65 – 75), so the `stock.release` row ends `rejected` and no `credit.release` is owed.

**FS11.** WHEN `consume(orderReference)` is invoked on a stock item holding reservations in status `reserved` for that order, THE SYSTEM SHALL set those reservations to `consumed`, SHALL decrease both `units` and `reservedUnits` by their total, and SHALL append **no** domain event.

**FS12.** THE SYSTEM SHALL reconstitute a `StockItem` from its stored `units`, `reservedUnits` and the reservation rows loaded with it, and after every committed `stock.reserve`, `stock.release` and `consume` transaction THE SYSTEM SHALL leave `reserved_units` equal to the sum of `units` over that item's reservations in status `reserved` (**F2**).

**FS13.** THE SYSTEM SHALL set the `aggregateId` of `stock.reserved.v1` and `stock.rejected.v1` to the id of the stock item named by the **first line** of the request that resolves to a known item, and the `aggregateId` of `stock.released.v1` to the id of the stock item of the first reservation released.

**FS14.** IF any line of a `stock.replenish` request names a `productCode` with no stock item under the request's `companyCode`, THEN THE SYSTEM SHALL reply `RpcError` `NOT_FOUND` naming that product and SHALL replenish **no** line of the request; WHEN every line is known, THE SYSTEM SHALL apply `R61` to each and reply the affected items as `StockView`s.

**FS15.** WHEN `stock.list` is received, THE SYSTEM SHALL reply `StockView` items with `availableUnits = units − reservedUnits`, ordered by `(companyCode, productCode)`, paged per `PageRequest` defaults (`page` 1, `pageSize` 25, maximum 200), filtered by `companyCode` and `productCode` when present, and WHERE `belowThreshold` is `true` SHALL return only items whose `availableUnits < lowStockThreshold`; the query SHALL mutate nothing and take no lock.

**FS16.** THE SYSTEM SHALL write `stock.reserved.v1`, `stock.rejected.v1` and `stock.released.v1` as outbox rows in the **same transaction** as the reservation rows and `reserved_units` changes they describe (`R13`), and SHALL publish them to `otc.fulfillment.facts.v1` **only** through Fulfillment's own outbox relay, keyed by `correlationId` (`R14`, `R15`).

**FS17.** WHEN the Fulfillment responders first start against the developer compose stack, whose `otc_orders.saga_commands` holds a `parked` `stock.reserve` row, THE SYSTEM SHALL answer the sweeper's next re-issue of that row **without operator action**, so that the order either gains reservation rows plus one published `stock.reserved.v1` and advances in Orders to `stock_reserved` with a new `credit.hold` row that parks (Billing does not exist yet), or receives `stock.rejected.v1` and moves to `cancelled` with **no** `stock.release` row (`R26`).

> *#9 note.* #9's pre-state is **one** row, `ORD-000007` (`progress/current.md`, Notes; `progress/impl_order_saga_orchestrator.md` step 6), not #8's four. Verified live, not by an automated test (`design.md` §14).

**FS18.** WHILE one `fulfillment.stock.*` request is being handled and is blocked — on a database row lock, on I/O, or on anything else — THE SYSTEM SHALL begin handling a further request on the same or another `fulfillment.stock.*` subject rather than serialising it behind the first, up to a bounded maximum of concurrently handled requests, and SHALL handle each request in its own unit of work so that no two in-flight requests share a database session.

**FS19.** WHEN a transaction takes locks on more than one stock row, THE SYSTEM SHALL take them **one row at a time, in a total order fixed by the application**, and SHALL take every read whose result decides idempotency or availability under an explicit lock; THE SYSTEM SHALL NOT depend on the query planner's row-access order, on an `ORDER BY` inside a locking statement, or on the ambient isolation level for either property.

> *#9 note.* The total order is the code-point order of the distinct `(company_code, product_code)` pairs with distinctness by exact equality — no upper-casing, because the database's own equality is exact here (ledger L4). The isolation level is pinned to `READ COMMITTED` by the transaction itself before its first statement, never inherited (ledger L13). The reservation read is `FOR UPDATE`, but PostgreSQL locks only rows that exist, so the property "a reservation being inserted for this order is seen" comes from the stock-row lock taken first, not from the reservation read (ledger L1, L2).

**FS20.** IF a `stock.replenish`, `stock.reserve` or reconstitution operation would compute a unit count outside the representable range of the stored counter, THEN THE SYSTEM SHALL raise a domain error carrying a stable code and change nothing — no counter SHALL ever wrap, become negative by arithmetic overflow, or silently truncate.

> *#9 note.* Python's `int` cannot wrap, so the hazard is the opposite of #8's: an exact value too wide for the `integer` column. The write-boundary range guard (`infrastructure/persistence/range_guards.py`, feature 207) raises `QuantityOutOfRangeError`, a `DomainError` with code `quantity.out_of_range`, when the mapper assigns the value; the transaction rolls back. Reachable only through `stock.replenish`: a reserve cannot raise a counter above `units` (F1), and a rehydrated row already fits its column.

**FS21.** IF a `stock.reserve` or `stock.release` transaction fails for a **transient** store reason — a deadlock victim after FS23's attempts, a connection failure, a lock or statement timeout — THEN THE SYSTEM SHALL reply with an `RpcError` whose `code` is `UNAVAILABLE` or `INTERNAL_ERROR`, and SHALL NOT reply with any of the nine codes `services/orders/src/otc_orders/infrastructure/messaging/nats_saga_commands.py` `TERMINAL_RPC_ERROR_CODES` (lines 65 – 75) classifies as a terminal business rejection.

> *#9 note.* #8's text also allowed `TIMEOUT`; a #9 responder never produces it (§1.1). The guard reads the terminal set from the Orders module itself, never a retyped list (`design.md` §8.5).

**FS22.** WHEN `stock.check` receives a well-formed request, THE SYSTEM SHALL answer with a `StockCheckReplyPayload` in every case — a `productCode` with no stock item under the request's `companyCode` SHALL be answered `available: 0, sufficient: false`, never as an error — and SHALL reserve an `RpcError` reply for a malformed request or an internal failure.

> *#9 note.* #8's reason for this requirement (its feature 46, an Orders checker that crashed on an error reply) is already closed in #9 by feature 15 (`nats_stock_availability.py:72-90`, `success | RpcError`). The requirement stays because it is the trilogy's behaviour, not a workaround.

### 2.2 New in #9 (`FS23` – `FS28`)

**FS23.** IF a `stock.reserve`, `stock.release` or `stock.replenish` transaction is chosen as a deadlock victim by the database (SQLSTATE `40P01`), THEN THE SYSTEM SHALL re-run the whole transaction from its first statement, up to **three** attempts in total, waiting **200 ms** before each re-run, and IF the third attempt is also a deadlock victim, THEN THE SYSTEM SHALL reply `RpcError` `UNAVAILABLE` having committed nothing and emitted nothing; THE SYSTEM SHALL NOT re-run a transaction for any other failure.

> *Why new.* `feature_list.json` id 17 acceptance item 3 (*"deadlock retry on 40P01"*). #7 answered a deadlock victim with `INTERNAL_ERROR` (the fall-through of `apps/fulfillment/src/presentation/rpc-error-mapper.ts:100-104`) and #8 with `UNAVAILABLE` (`src/Fulfillment/Presentation/Rpc/StockErrorMapper.cs:59`), both leaving the retry to the orchestrator. PostgreSQL aborts the victim's **whole** transaction, so a statement-level retry is impossible; the bound and pacing are the relay's (`services/orders/src/otc_orders/infrastructure/outbox/relay.py:46-48`).

**FS24.** THE SYSTEM SHALL take every identifier minted while reserving or releasing an order — each reservation id and the `eventId` of each `stock.reserved.v1`, `stock.rejected.v1` and `stock.released.v1` — from the identifier source the application supplies to the domain, so that a caller supplying known identifiers observes exactly those identifiers on the reservations and the facts.

> *Why new.* #8 id 49 (the release fact minted its own id) **and its follow-on**: #8's closure found the property guarded at one of four sites (#8 `progress/history.md`, stock_release_deterministic_event_id). #7 minted fact ids inside its kernel's event factory and had no seam.

**FS25.** WHEN `stock.release` is executed for an order, THE SYSTEM SHALL decide it while holding exclusive locks on the stock rows of **every item the order holds a reservation on**, taken per FS19, and IF one of those rows is locked by another transaction, THEN THE SYSTEM SHALL wait for that transaction to end before reading the order's reservations; this lock is the one `despatch.create` for the same order shall take (feature 18), so that `stock.release` and `despatch.create` for one order are decided under one lock (`saga.md` SA-4).

> *Why new.* SA-4 is shared prose without an `R` id; #8 id 79 found #7's half met with no guard. This makes the release half testable here; the despatch half and the race in both outcomes are feature 18's.

**FS26.** WHEN the Fulfillment host shuts down with requests in flight, THE SYSTEM SHALL stop accepting new requests, SHALL wait for every in-flight request to complete or fail, and IF sending the reply of one in-flight request fails, THEN THE SYSTEM SHALL log it and complete the shutdown without propagating that failure and without abandoning the others.

> *Why new.* #8 id 50 (`StockRpcResponder.StopAsync` rethrew a faulted reply out of host shutdown). #9's Orders responder already has the property (`orders_create_responder.py:89-108, 130-132`); this ports it rather than re-deriving it.

**FS27.** WHEN the Fulfillment host's startup has returned, THE SYSTEM SHALL already be subscribed to the five `fulfillment.stock.*` subjects at the RPC server, so that a request sent from any other connection after startup is delivered to the responder and is never answered *no responders*.

> *Why new.* #8 id 95 (a cold connection lost a reply). nats-py completes the connection handshake inside `nats.connect()`, so #8's shape cannot occur; the remaining gap is a subscription the server has not processed yet, which #7's framework closed by awaiting `startAllMicroservices()` (`apps/fulfillment/src/main.ts:40`).

**FS28.** WHEN a `stock.reserve` or `stock.release` request carries an `orderReference` that matches the wire pattern `^ORD-[0-9]{6,}$` and is at most 20 characters long, THE SYSTEM SHALL key the reservations by that exact string and SHALL NOT refuse the request because the shared kernel's canonical `OrderNumber` parse refuses it (for example `ORD-000000`); IF the `orderReference` is longer than 20 characters, THEN THE SYSTEM SHALL reply `VALIDATION_FAILED` and change nothing.

> *Why new.* The mirror of the saga's SO12 (`specs/order_saga_orchestrator/requirements.md` §2.2): #9's kernel refuses `ORD-000000`, which #7's and #8's did not, so neither predecessor faced it. The length clause is #9's: the wire pattern has no maximum and `reservations.order_reference` is `varchar(20)` (`models.py`), so an over-long reference would otherwise reach the engine as a transient error and be retried forever (ledger L22).

## 3. Local traceability

The shared rows are traced in [`specs/shared/test-matrix.md`](../shared/test-matrix.md) §4; the implementer writes **column 5 only** for `R30` – `R35` and `R61`'s domain half, citing literal test function names, and updates the derived counts including the **Total** row. `R36` and `R61`'s API half stay `TODO`. Paths are under `services/fulfillment/tests/` unless they start with `tests/`. Every row starts `TODO`; a row becomes `DONE` only when its test exercises the requirement's **distinguishing branch** and has been seen to fail under the arm `tasks.md` names.

| Id | Level | Test file › case | Status |
|---|---|---|---|
| **R30** (shared) | domain unit | `unit/domain/test_stock_item.py` › `test_r30_rejects_in_full_any_operation_that_would_push_reserved_units_above_units_and_changes_no_stock_item` | DONE |
| **R31** (shared) | integration | `integration/test_stock_check.py` › `test_r31_answers_per_line_without_mutating_a_stock_item_and_without_emitting_a_fact` | DONE |
| **R32** (shared) | domain unit | `unit/domain/test_reservation.py` › `test_r32_creates_one_reservation_per_line_increases_reserved_units_and_emits_exactly_one_stock_reserved_v1` | DONE |
| **R33** (shared) | domain unit | `unit/domain/test_reservation.py` › `test_r33_creates_no_reservation_at_all_and_emits_stock_rejected_v1_naming_requested_and_available_units_when_one_line_is_short` | DONE |
| **R34** (shared) | domain unit + integration | `unit/domain/test_reservation_release.py` › `test_r34_releases_the_reservations_decreases_reserved_units_and_emits_exactly_one_stock_released_v1`; `integration/test_stock_release_idempotency.py` › `test_r34_answers_success_and_emits_no_second_fact_when_every_reservation_is_already_released` | DONE |
| **R35** (shared) | domain unit | `unit/domain/test_reservation.py` › `test_r35_refuses_every_transition_out_of_released_and_out_of_consumed_and_changes_nothing` | DONE |
| **R61** (shared, domain half) | domain unit | `unit/domain/test_stock_replenishment.py` › `test_r61_increases_units_by_the_requested_quantity_leaves_reserved_units_and_every_reservation_unchanged_and_appends_no_domain_event` | DONE (domain half; API half: feature 31) |
| **FS2** | integration (Orders, feature 16) | `services/orders/tests/integration/saga/test_saga_command_headers.py` › `test_so14_every_attempt_carries_the_order_id_and_one_request_id_per_command_row_on_both_paths` | DONE (feature 16) |
| **FS3** | unit + integration | `unit/test_stock_responder.py` › `test_fs3_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_is_missing_or_malformed` (parametrised: two headers × missing/malformed × reserve/release); `integration/test_stock_reserve.py` › `test_fs3_stamps_correlation_id_from_the_header_and_causation_id_from_the_request_id_on_the_emitted_fact` | DONE |
| **FS4** | integration | `integration/test_stock_wire.py` › `test_fs4_answers_a_bare_json_request_with_a_bare_json_reply_on_all_five_subjects` (parametrised per subject), `test_fs4_answers_a_bare_json_rpc_error_on_a_validation_failure` | DONE |
| **FS5** | unit + integration | `unit/test_stock_reservation_service.py` › `test_fs5_short_circuits_to_already_reserved_on_a_reservation_in_any_status_calling_no_domain_function_and_saving_nothing` (parametrised `released`, `consumed`); `integration/test_stock_reserve.py` › `test_fs5_answers_already_reserved_with_the_existing_reservations_changing_no_counter_and_emitting_no_second_fact_when_reissued`, `test_fs5_answers_already_reserved_for_an_order_whose_only_reservation_is_already_released_reserving_nothing_new`, `test_fs5_answers_already_reserved_for_a_reissue_naming_a_different_product` | DONE |
| **FS6** | integration | `integration/test_stock_reserve_race.py` › `test_fs6_two_concurrent_reserves_for_the_last_units_yield_exactly_one_stock_reserved_and_one_stock_rejected` | DONE |
| **FS7** | integration | `integration/test_stock_reserve_race.py` › `test_fs7_a_line_reported_sufficient_by_stock_check_is_rejected_by_a_later_reserve_once_another_order_took_the_units` | DONE |
| **FS8** | domain unit | `unit/domain/test_reservation.py` › `test_fs8_rejects_the_whole_order_with_reason_unknown_product_and_available_zero_when_any_line_names_an_unstocked_product` | DONE |
| **FS9** | integration | `integration/test_stock_release_idempotency.py` › `test_fs9_answers_already_released_with_an_empty_list_and_emits_nothing_for_an_order_that_never_held_a_reservation` | DONE |
| **FS10** | domain unit + integration | `unit/domain/test_stock_item.py` › `test_fs10_refuses_to_release_a_consumed_reservation_and_changes_nothing`; `integration/test_stock_release_idempotency.py` › `test_fs10_replies_precondition_failed_and_emits_nothing_when_the_orders_reservations_are_consumed` | DONE |
| **FS11** | domain unit | `unit/domain/test_stock_item.py` › `test_fs11_consume_moves_the_orders_reservations_to_consumed_decreases_units_and_reserved_units_by_the_same_total_and_appends_no_event` | DONE |
| **FS12** | domain unit + integration | `unit/domain/test_stock_item.py` › `test_fs12_rehydrates_and_keeps_reserved_units_equal_to_the_sum_of_reserved_reservations_after_reserve_release_and_consume`; `integration/test_stock_repository.py` › `test_fs12_reserved_units_equals_the_sum_of_reserved_reservation_units_after_every_committed_operation` | DONE |
| **FS13** | domain unit | `unit/domain/test_reservation.py` › `test_fs13_stamps_the_first_known_lines_item_on_reserved_and_rejected_and_the_first_released_reservations_item_on_released` | DONE |
| **FS14** | integration | `integration/test_stock_replenish.py` › `test_fs14_replies_not_found_and_replenishes_no_line_when_any_line_names_an_unknown_product` | DONE |
| **FS15** | integration | `integration/test_stock_list.py` › `test_fs15_lists_stock_views_with_derived_available_units_pages_filters_and_below_threshold_without_locking_or_mutating` | DONE |
| **FS16** | integration | `integration/test_fulfillment_outbox_relay.py` › `test_fs16_publishes_a_reserve_transactions_fact_to_the_fulfillment_topic_keyed_by_correlation_id_and_stamps_it_only_after_acknowledgement` | DONE |
| **FS17** | live verification | `progress/impl_fulfillment_stock.md` § Live boot (`tasks.md` group K) | DONE (live walkthrough, 2026-10-08) |
| **FS18** | unit + integration | `unit/test_stock_responder.py` › `test_fs18_at_most_the_configured_number_of_requests_are_handled_at_once_and_the_next_starts_when_one_ends`, `test_fs18_each_request_gets_its_own_unit_of_work`; `integration/test_stock_responder_concurrency.py` › `test_fs18_answers_a_second_request_while_an_earlier_one_is_blocked_on_a_stock_row_lock_held_by_another_transaction` | DONE |
| **FS19** | unit + integration | `unit/test_stock_lock_order.py` › `test_fs19_orders_distinct_stock_keys_by_code_point_independently_of_request_order`; `integration/test_stock_reserve_race.py` › `test_fs19_two_multi_line_reserves_naming_the_same_products_in_opposite_order_both_succeed_with_no_deadlock`; `integration/test_stock_repository.py` › `test_fs19_the_reservation_read_made_after_the_stock_lock_sees_a_reservation_committed_while_it_waited`, `test_fs19_every_stock_transaction_runs_at_read_committed` | DONE |
| **FS20** | integration | `integration/test_stock_replenish.py` › `test_fs20_refuses_a_replenishment_that_would_overflow_the_unit_column_with_a_domain_error_and_changes_nothing` | DONE |
| **FS21** | architecture (cross-service) | `tests/architecture/test_fulfillment_rpc_error_retryability.py` › `test_fs21_every_transient_store_failure_maps_to_a_code_the_saga_adapter_retries`, `test_fs21_no_input_produces_conflict` | DONE |
| **FS22** | integration | `integration/test_stock_check.py` › `test_fs22_answers_an_unknown_product_with_available_zero_and_sufficient_false_never_with_an_rpc_error` | DONE |
| **FS23** | unit + integration | `unit/test_stock_transactions.py` › `test_fs23_a_deadlock_victim_is_rerun_at_most_three_times_paced_by_200_ms_then_unavailable`, `test_fs23_no_other_store_failure_is_rerun`; `integration/test_stock_deadlock_retry.py` › `test_fs23_a_real_40p01_on_a_reserve_is_rerun_and_the_reserve_is_accepted_once` | DONE |
| **FS24** | domain unit | `unit/domain/test_reservation.py` › `test_fs24_every_reservation_id_and_fact_event_id_is_the_one_the_id_source_supplied` (reserve, reject, release, each site separately); `unit/test_stock_reservation_service.py` › `test_fs24_the_reserve_uses_the_id_port_for_every_reservation_id_and_the_reserved_facts_event_id` and `test_fs24_the_release_uses_the_id_port_for_the_released_facts_event_id` (the application → domain hand-over) | DONE |
| **FS25** | integration | `integration/test_stock_release_idempotency.py` › `test_fs25_a_release_waits_for_a_transaction_holding_a_stock_row_of_the_order_before_reading_its_reservations` (the wait); `integration/test_stock_repository.py` › `test_fs25_the_release_lock_reads_the_orders_reservations_only_after_the_stock_lock_and_sees_a_reservation_committed_while_it_waited` (the read order, "before reading the order's reservations") | DONE |
| **FS26** | unit | `unit/test_stock_responder.py` › `test_fs26_shutdown_with_one_faulted_and_one_healthy_request_in_flight_completes_and_waits` | DONE |
| **FS27** | unit | `unit/test_stock_responder.py` › `test_fs27_start_flushes_after_the_last_subscription` | DONE |
| **FS28** | unit + integration | `unit/test_stock_requests.py` › `test_fs28_a_reference_longer_than_the_column_is_refused_as_validation_failed`; `integration/test_stock_reserve.py` › `test_fs28_reserves_for_ord_000000_which_the_kernel_parse_refuses` | DONE |

## 4. Spec amendments

**No `SA-6` is proposed by this feature.** #8 recorded five promotion candidates for a later shared pass (#8 `requirements.md` §3: the correlation carrier FS2/FS3, FS13 versus `domain-model.md` §8 rule 6, FS5's "existing", FS9/FS10's edges, FS21's retryability); #9 realises all five identically to #7 and #8. Whether to close them without an amendment is gate point **G3** (`design.md` §16.1), recommended *close*, on the precedent of feature 16's G3 (approved 2026-10-06). No requirement text in `specs/shared/` was found wrong or incomplete for this feature; G1 and G2 are realisation choices the shared text leaves open, not defects in it.
