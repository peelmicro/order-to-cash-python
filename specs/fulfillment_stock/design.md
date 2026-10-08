# Design — `fulfillment_stock` (feature 17, Python 3.14 / SQLAlchemy 2.1 / asyncpg / PostgreSQL 18.6 / nats-py 2.16 / aiokafka 0.14, assessment #9)

> **Stack-specific.** This file is where the Python, SQLAlchemy, PostgreSQL, nats-py, aiokafka and `otc_cqrs` detail lives. Nothing here belongs in `specs/shared/`.
>
> **A port with a delta analysis.** #8's design (`../order-to-cash-dotnet/specs/fulfillment_stock/design.md`, 581 lines, its §15 ledger L1 – L13) and #7's (`../order-to-cash-nestjs/specs/fulfillment_stock/design.md`) were read first, with both review histories (#7 `progress/history.md` line 842: rejected once, an unplanned sub-clause mutation of FS5 survived 57 unit and 36 integration tests; #8 line 999: rejected twice, D1 *the rejected path's outbox row never observed* and D2 *the released fact's `reason` never opened*). Everything stack-agnostic is ported as content. The effort went into §3 (the ledger), §6 (PostgreSQL's locking is neither InnoDB's nor MS-SQL's: measured, not assumed), §8 (the responder and the error mapping Orders' saga decides on) and §10 (the copies and their parity guard).
>
> **Measurements made for this spec** (throwaway `postgres:18.6` container, the image the fixture and compose use; 2026-10-07): the default database collation is `en_US.utf8`, provider libc, and `SELECT 'PRD-0001' = 'prd-0001'` is **false**; `default_transaction_isolation` is `read committed`; `deadlock_timeout` is `1s`. A `SELECT … FOR UPDATE` on `reservations WHERE order_reference = X` while another transaction holds an **uncommitted** insert of such a row returned **0 rows in 0.989 ms** (no key-range lock exists). With the protocol of §6.2 (stock row locked first by the writer, which inserts a reservation and updates the counter, then commits after 3 s), a second transaction's `SELECT … FROM stock … FOR UPDATE` **blocked**, returned the **updated** counter, and its following reservation read returned **1** row. The same reads in the **opposite order** returned **0** reservations (a stale decision). The same protocol under `REPEATABLE READ` raised **`could not serialize access due to concurrent update`** (SQLSTATE 40001).

## 0. Scope

**In scope.** The `StockItem` aggregate and its `Reservation` child entity (pure domain, F1/F2/F4/F5 inside the aggregate); the order-scoped pure domain service that makes reservation all-or-nothing across lines (F3) and builds the three facts; the five NATS responders (`fulfillment.stock.check`, `.reserve`, `.release`, `.list`, `.replenish`) as one asyncio task class over one transport; the stock transactions with their lock protocol and the deadlock re-run (FS23); Fulfillment's copies of the outbox writer, relay and Kafka publisher, with a parity guard built now (§10); the first Fulfillment composition root, lifespan and readiness; the `otc_cqrs` registration carried from feature 43; the SA-4 lock as a repository method feature 18 reuses; the live walkthrough of the parked `ORD-000007` (FS17).

**Out of scope, and owned elsewhere.**

| Not here | Owner |
|---|---|
| `despatch.create`, `DespatchAdvice`, `DES-` allocation, `order.despatched.v1`, the release-versus-despatch race (R36, SA-4's despatch half) | feature 18 (§15) |
| Billing responders | features 19 – 22 |
| `traceparent`, `x-deadline-ms`, structlog, metrics, DLQ | feature 27 |
| The Gateway's `GET /stock`, `POST /stock/replenish`; R61's API row | features 25, 31 |
| The stock page's product name (#8 id 101) | feature 29 (§17) |
| Any Orders change | none needed: FS2 is feature 16's SO14 (`requirements.md` FS2 note) |

## 1. What already exists — checked, not assumed

**The phase-6 schema is sufficient: no migration.** Read from `services/fulfillment/src/otc_fulfillment/infrastructure/persistence/models.py` (lines 59 – 144) and checked column by column against this design:

| This design needs | Exists as |
|---|---|
| one row per `(company_code, product_code)`, unique | `stock` + `UniqueConstraint("company_code", "product_code")` (the per-row lock's index) |
| `units`, `reserved_units`, `low_stock_threshold` | `Integer` (PostgreSQL `integer`, int4) columns, each range-guarded with `QuantityOutOfRangeError` (`QUANTITY_COLUMNS`, lines 151 – 157) |
| reservations by order, with status | `reservations`, `Index("ix_reservations_order_reference_status", …)`; `order_reference varchar(20)`, `status varchar(20)` |
| reservation → stock | FK `stock_id → stock.id`, indexed |
| the outbox, `seq` identity, `json` payload | `outbox`, column-for-column Orders' (feature 11's parity) |
| `processed_events` | present, **unused** by this feature (§10.4) |
| `despatches.order_reference` unique (F8, feature 18) | present |

There is **no `CHECK (reserved_units <= units)`**, deliberately (phase 6, as #7 and #8): F1 lives in the aggregate so that a breach is a `stock.rejected.v1` fact, not a driver error. If the implementer finds a column missing, that is a design error to bring back here, never a migration to write.

**What Phase 8 built that this feature reuses** (shapes, not lines): Orders' responder (`services/orders/src/otc_orders/presentation/orders_create_responder.py`: inbox queue, one task per request, drain on stop with `return_exceptions=True`, fault logged by a done-callback — #8 id 50 already solved); Orders' composition root and runtime (`composition.py:100-464`: settings bundle, explicit registration, boot validation, one `AsyncExitStack`, readiness from task state and the NATS connection, the single-relay guard); Orders' unit of work (`infrastructure/persistence/unit_of_work.py:87-96`: `READ COMMITTED` pinned before the first statement, events cleared only after commit); the relay's deadlock classifier (`infrastructure/outbox/relay.py:46-48, 83-88, 137-150`); the generated wire models (`otc_contracts.generated.asyncapi`: `StockCheckRequestPayload` … `StockReplenishReplyPayload`, `StockView`, `PageInfo`, `ReservationRef`, `Shortage`, `RpcError`, `Code`), strict on integers (`packages/contracts/src/otc_contracts/wire.py`); the range guard as feature 207 left it.

## 2. Layout

```
services/fulfillment/src/otc_fulfillment/
  domain/
    __init__.py                    (kept)
    value_objects/__init__.py      (kept: the money guard's nested-domain sentinel)
    reservation.py                 ReservationStatus (enum.Enum, explicit tokens) + parse; Reservation entity; ReservationView
    stock_item.py                  StockItem(AggregateRoot): rehydrate, reserve, release, consume, replenish, record_order_fact, to_snapshot
    snapshot.py                    StockItemSnapshot, ReservationSnapshot (frozen, slots, kw_only; tuples)
    order_stock_reservation.py     reserve_order / release_order (pure), ReserveOrderInput, ReleaseOrderInput, StockContext, outcomes
    events.py                      StockEventBase, StockReserved, StockRejected, StockReleased (+ line/ref value types)
    errors.py                      the DomainError subclasses of §5.4
  application/
    __init__.py
    ports/clock.py                 COPY of Orders' (parity-guarded, §10.2)
    ports/ids.py                   IdSource (new() -> UniqueId)
    ports/stock_store.py           StockTransactions, StockTransaction, StockRepository, LockedStock, StockReads, StoreUnavailableError
    messages.py                    CheckStockQuery, ListStockQuery, ReserveStockCommand, ReleaseStockCommand, ReplenishStockCommand + result dataclasses
    handlers.py                    the five handler classes (thin)
    stock_reservation.py           the reserve / release transactional units (plain functions over ports)
    stock_replenishment.py         the replenish transactional unit
    scope.py                       FulfillmentScope (the dispatcher's S), MissingBindingError
  infrastructure/
    settings.py                    + OutboxRelaySettings, KafkaSettings, NatsSettings, ServerSettings, ResponderSettings
    clock.py                       COPY of Orders' SystemClock (parity-guarded)
    ids.py                         UuidIdSource
    persistence/                   models.py, range_guards.py, types.py, sequences.py UNCHANGED
    persistence/stock_mapper.py    rows <-> snapshots; the ONLY writer of stock / reservation integer columns (§9.2)
    persistence/stock_repository.py   lock protocol (§6), save, outbox drain
    persistence/stock_reads.py     availability + paged list (no lock, no write)
    persistence/stock_transactions.py   run(work): session, READ COMMITTED, commit, 40P01 re-run (§6.5)
    outbox/{errors,publisher,kafka_publisher,relay,relay_task,wire,writer}.py   COPIES of Orders' (§10)
    outbox/topic.py                FULFILLMENT_FACTS_TOPIC = "otc.fulfillment.facts.v1"
    outbox/payloads.py             narrow + build_fact for the three stock events (service-specific)
    messaging/subjects.py          the five subjects + FULFILLMENT_QUEUE_GROUP = "otc-fulfillment"
  presentation/
    app.py                         create_app(lifespan=...) with /health/live and /health/ready (Orders' shape)
    stock_responder.py             StockResponder: one task, five subscriptions, bound, drain (§8)
    stock_wire.py                  decode request -> message; result -> reply (generated models)
    stock_headers.py               x-correlation-id / x-request-id extraction (FS3)
    stock_rpc_errors.py            exception -> RpcError (§8.5)
  composition.py                   settings bundle, register_handlers, build_dispatcher, start_runtime, FulfillmentRuntime
  main.py                          the lifespan (`uvicorn otc_fulfillment.main:app`)
```

**Layering.** `domain` imports only the standard library modules the money guard allows (`collections.abc`, `dataclasses`, `datetime`, `enum`, `typing`) and `otc_shared_kernel`; no `otc_contracts`, no `otc_cqrs` (the `domain-purity` contract). `application` imports `otc_cqrs`, the domain and its own ports; it never imports `otc_contracts` (results are application dataclasses, mapped to wire models in `presentation/stock_wire.py`, Orders' `to_reply` shape). Only `infrastructure/outbox/kafka_publisher.py` imports aiokafka (`fact-producer-confinement`, `test_kafka_client_confinement.py`). The lifespan lives in `main.py`, outside the layers, because `presentation` may not reach aiokafka even through the root (CLAUDE.md, Architecture conventions).

## 3. The ported-idiom ledger

One row per idiom: *#7 relied on X; #8 supplied it with Y; in #9 it is supplied by Z*, each half cited, the guard named in `tasks.md` where #9 hand-builds the property.

| # | Property | #7 got it from | #8 supplied it by | #9 supplies it by | Guard (`tasks.md`) |
|---|---|---|---|---|---|
| L1 | **A blocking, current read** of the rows a decision depends on | `SELECT … FOR UPDATE` under InnoDB's default `REPEATABLE READ` (`apps/fulfillment/src/infrastructure/persistence/stock-item.repository.ts:44-50, 56-61`; `drizzle-unit-of-work.ts:75`) | `WITH (UPDLOCK, HOLDLOCK, ROWLOCK)` on every deciding read, `READ_COMMITTED_SNAPSHOT ON` (`src/Fulfillment/Infrastructure/Persistence/EfCoreStockItemRepository.cs:51, 68`) | `select(Stock)….with_for_update()` per stock row, then the order's reservations `FOR UPDATE`, at `READ COMMITTED` pinned per transaction. A locking read waits for the row's writer and then returns the **latest** committed version; each later statement takes a **fresh** snapshot, so the reservation read issued after the stock lock sees what the writer committed (measured, header). The order of the two reads is therefore load-bearing | D5 (protocol test) for `lock_for_reserve`, arm D5a; `test_fs25_the_release_lock_reads_…` for `lock_order_items` (the SA-4 release/despatch lock), arm R1; arms: reservations read first; `REPEATABLE READ` |
| L2 | **"No reservation yet for this order"** is protected against a concurrent insert | Partly: the idempotency read was scoped to the stock rows just locked (`stock-item.repository.ts:56-61`), so a reservation on a product **absent** from the request was invisible even sequentially | `HOLDLOCK` takes a key-range lock on the reservations read over **all** of the order's reservations (`EfCoreStockItemRepository.cs:68`; #8 `design.md` §5.2 `ExistingReservationsOfOrder`) | **Not fully portable: PostgreSQL has no key-range lock** (measured: 0 rows in 0.989 ms against an uncommitted insert). #9 reads **all** of the order's reservations after the stock locks (#8's scope, so the sequential re-issue with another product set is covered); a concurrent pair of reserves for one order with **disjoint** product sets is a residual — gate point **G1** | D6 (sequential, different product); arm: scope the read to the locked stock ids (#7's shape) |
| L3 | **A deterministic global lock order** across a multi-line order | One statement, `ORDER BY company_code, product_code … FOR UPDATE`, InnoDB locking in index order (`stock-item.repository.ts:44-50`) | One single-row locking statement per product in an application-fixed order (FS19; `EfCoreStockItemRepository.cs:51`) | One `SELECT … FOR UPDATE` per distinct `(company_code, product_code)`, issued in Python code-point order, identically for reserve, release, replenish and (feature 18) despatch. PostgreSQL would also lock in `ORDER BY` order (its locking node sits above the sort), but the per-row loop is chosen because its mutation is **observable**: locking in request order produces a deterministic deadlock in §13.3's constructed test, whereas deleting an `ORDER BY` leaves the unique index's order and stays green (#8's own G6 arm did) | E3 (unit), I3 (integration, deadlock count); arm: lock in request order |
| L4 | **Agreement between the application's notion of "same code" and the database's** | MySQL `utf8mb4_0900_ai_ci`: case- and accent-insensitive on both sides | Upper-cased ordinal sort, `OrdinalIgnoreCase` distinctness, because `SQL_Latin1_General_CP1_CI_AS` is case-insensitive (`EfCoreStockItemRepository.cs:72, 92, 133`) | PostgreSQL's deterministic libc collation is **case-sensitive** (measured), so distinctness is exact `==` and the sort is plain `sorted()`: the application and the database agree without normalising. A code differing only in letter case is a **different** item here, unlike #7 and #8 — gate point **G2** | E3 (two keys differing by case stay two), H12 (`prd-…` is `unknown_product`) |
| L5 | **Counters that cannot wrap or truncate** | JavaScript numbers (`apps/fulfillment/src/domain/stock-item.ts:196-198`) | In-domain `int.MaxValue` guards, `long` sums, `ClampToInt` on shortages (`src/Fulfillment/Domain/StockItem.cs:74-81, 165`; `OrderStockReservation.cs:250`) | Python `int` is exact and unbounded: the domain does **no** width arithmetic (availability by subtraction; sums exact; shortages report the exact summed `requested`, no clamp). The `integer` column width is enforced when `stock_mapper` assigns the attribute, by `range_guards.py` (feature 207): `QuantityOutOfRangeError` (a `DomainError`, code `quantity.out_of_range`) → `DOMAIN_ERROR`, transaction rolled back (FS20) | H10 (replenish overflow); arm: write `units` through `update(Stock).values(…)`, which bypasses the guard (the reply changes kind to `INTERNAL_ERROR`) |
| L6 | **"Insert or leave alone" atomically** | `INSERT … ON DUPLICATE KEY UPDATE` as the unit of atomicity (#8 `design.md` §15 L5, line 564) | Not needed and not rendered: rows loaded under a lock are updated by primary key | Same as #8: every `stock` and `reservations` row written was loaded under `FOR UPDATE` in the same transaction or is a new reservation (plain insert); no upsert, no check-then-insert, no `ON CONFLICT` in this service | D9: `test_write_path_population.py` `EXPECTED["fulfillment"]` classifies every write, so an upsert appears as an unclassified hit |
| L7 | **Concurrent handling of independent requests** | `@nestjs/microservices`' NATS server ran each `@MessagePattern` request on its own promise (`apps/fulfillment/src/main.ts:31-36`; `presentation/stock.controller.ts:90-184`) | `SemaphoreSlim(32)` acquired before a DI scope per request, in-flight tasks tracked (`src/Fulfillment/Presentation/StockRpcResponder.cs:50-51, 117-133, 175`) | Orders' responder shape (one task per request, `orders_create_responder.py:98-102`) **plus** an `asyncio.Semaphore(FULFILLMENT_MAX_CONCURRENT_REQUESTS)` acquired inside the request task **before** its unit of work opens a session; the engine's pool is sized from the same setting (`pool_size = bound + 1`, `max_overflow = 0`) so an admitted request never waits for a connection (§8.2). Orders' responder is unbounded; Fulfillment's requests hold row locks, which is why the bound is added | F6 (unit), H9 (held-lock integration); arms: serve inline; remove the semaphore |
| L8 | **A retryable failure is retried by the caller** | #7's orchestrator retried every code, so `CONFLICT` for a concurrency error was safe (`apps/fulfillment/src/presentation/rpc-error-mapper.ts:74-80`) | A closed mapping with `CONFLICT` banned; transient → `UNAVAILABLE` (`src/Fulfillment/Presentation/Rpc/StockErrorMapper.cs:55-60`) | Orders' `TERMINAL_RPC_ERROR_CODES` (`nats_saga_commands.py:65-75`) is #8's nine. §8.5's closed mapping: every transient store failure → `UNAVAILABLE`, anything unclassified → `INTERNAL_ERROR` (both retried), `CONFLICT` produced by **no** input; a deadlock is first re-run in-process (L14) | F4 (architecture test importing Orders' set); arm: map `StoreUnavailableError` to `CONFLICT` |
| L9 | **Publication order of facts written in one transaction** | MySQL `AUTO_INCREMENT` through the ORM batch | Per-row awaited insert (#8 L8) | Orders' writer, one `session.flush()` per row (`infrastructure/outbox/writer.py:57, 72`), copied byte-identically (§10) | C3 parity + Orders' existing `seq` tests |
| L10 | **A bare-JSON request/reply wire** | A hand-written `BareJsonNatsDeserializer` / `Serializer` pair (`main.ts:35-36`) | Nothing: raw bytes (#8 L9) | Nothing: `Msg.data` is `bytes`, `Msg.respond(bytes)`; request through `from_wire_json`, reply through `to_wire_json` | H8 (FS4) |
| L11 | **Declarative request validation** | `class-validator` DTOs | Hand-rolled `StockRequestValidator` (#8 L11) | The generated pydantic models (strict integers, lengths, patterns, enums, `minItems`) through `from_wire_json`; drift-tested against `asyncapi.yaml` by `packages/contracts/tests/test_generation_drift.py`. Two checks the schema cannot express are added at the edge: the two headers (FS3) and `orderReference` ≤ 20 characters (FS28) | F2 (one case per constraint, each `VALIDATION_FAILED`, nothing dispatched) |
| L12 | **One transaction per unit of work, no ambient session** | Drizzle's `TransactionContext` passed explicitly | The scoped `DbContext`'s ambient transaction | `StockTransactions.run(work)` opens one `AsyncSession` and one transaction per **attempt** and hands `work` a `StockTransaction` whose repository is bound to that session (Orders' `SqlAlchemyOrdersTransaction` shape, `unit_of_work.py:34-69`). No module-level session; the session is closed with the attempt | D7 (forced rollback leaves nothing) |
| L13 | **An in-transaction re-read after the lock is current** (#8 id 54) | InnoDB `REPEATABLE READ` is transaction-scoped, so #7 locked every re-read | `READ COMMITTED` + RCSI makes the snapshot statement-scoped (`src/Fulfillment/Infrastructure/Persistence/EfCoreUnitOfWork.cs:40`; the un-hinted re-read at `Application/DespatchCreationService.cs:67`; #8 `design.md` §15 L13) | `READ COMMITTED` **pinned** by `run()` before the first statement (`session.connection(execution_options={"isolation_level": "READ COMMITTED"})`, Orders' `unit_of_work.py:92`), never inherited. Statement-scoped snapshot, so feature 18's in-lock re-read is current; under `REPEATABLE READ` the stock lock itself raises 40001 (measured). **#8 id 54's warning applies verbatim, and this row is its #9 guard** | D5's isolation case; arm: pin `REPEATABLE READ` |
| L14 | **A deadlock victim** | Error reply, `INTERNAL_ERROR` by fall-through (`rpc-error-mapper.ts:100-104`); the orchestrator retried | `SqlException` 1205 → `UNAVAILABLE` (`StockErrorMapper.cs:59`); the orchestrator retried | Re-run in-process: `run()` catches a `DBAPIError` whose SQLSTATE is `40P01` (`sqlstate_of`, from the relay copy), sleeps 0.2 s, re-runs `work` from the start, at most 3 attempts; exhausted → `StoreUnavailableError` → `UNAVAILABLE` (FS23, §6.5). PostgreSQL aborts the victim's whole transaction, so only a whole re-run is possible | D4 (unit), I4 (real 40P01); arms: one attempt; re-run on 40001 |
| L15 | **Deterministic identifiers** (#8 id 49) | Reservation ids from a `() => UniqueId.generate()` passed in (`application/stock-reservation.handler.ts:72`); fact ids minted inside the kernel's `createDomainEvent` (`domain/stock-events.ts:10, 42-45`) | A `Func<UniqueId> newId` at all four sites only after id 49 and its follow-on (`src/Fulfillment/Domain/OrderStockReservation.cs:161, 181, 185, 234`) | `new_id: Callable[[], UniqueId]` is a required parameter of `reserve_order` and `release_order`, used at all four sites (reservation id, reserved, rejected, released event ids); the handler passes `scope.ids.new` | B7 (equality with supplied ids, per site); four separate arms. The handler's hand-over of the port is guarded separately (review round 1 D2): `unit/test_stock_reservation_service.py` › `test_fs24_the_reserve_uses_the_id_port_for_every_reservation_id_and_the_reserved_facts_event_id` and `test_fs24_the_release_uses_the_id_port_for_the_released_facts_event_id`, arms M1a (`stock_reservation.py:115`) and M1b (`:170`) |
| L16 | **Shutdown does not propagate one faulted reply** (#8 id 50) | Nest's lifecycle | Fixed after review (`StockRpcResponder.cs:68-79`, #8 id 50) | Orders' `run` / `_drain` / `_log_fault` (`orders_create_responder.py:69-108, 130-132`), ported | F7; arm: `gather` without `return_exceptions` |
| L17 | **The responder is reachable when startup returns** (#8 id 95) | `await app.startAllMicroservices()` (`main.ts:40`) | `ConnectAsync()` before use (#8 id 95's fix) | `nats.connect()` completes the handshake before returning, so #8's cold-connection shape cannot occur; the remaining gap is a SUB the server has not yet processed, closed by `await connection.flush()` after the last `subscribe` in `start()` (FS27) | F8 (call order); arm: delete the flush |
| L18 | **Event-loop affinity of engine, NATS client and producer** | One Node loop | Thread pool | Created in `start_runtime`, inside the lifespan's loop, and closed in it (Orders' `composition.py:363-369`); no aiokafka object built in `__init__` (the publisher copy); test hosts are function-scoped, every engine disposed in the loop that made it | H1's host fixture; `PytestUnraisableExceptionWarning` is an error |
| L19 | **Cancellation is never swallowed; one failure does not stop the others** | Promises | `OperationCanceledException` excluded from catches | `except Exception` only (never `BaseException` or bare); cancelling `run` cancels the request tasks and re-raises; a `CancelledError` during the 40P01 back-off propagates without a further attempt | F9, D4's cancellation case |
| L20 | **`Any` from untyped clients** | TypeScript types | C# types | nats-py ships `py.typed` (`Msg.headers: dict[str, str] | None`); asyncpg is reached only through SQLAlchemy's typed results; aiokafka only through the publisher copy's private `Protocol`. `mypy --strict` is the guard | quality.sh |
| L21 | **One serializer on the wire and in the outbox** | `JSON.stringify` | `JsonWire.Options` | `to_wire_json` / `from_wire_json` for every reply, every `RpcError` and every outbox payload; payload column through `RawJson` (`json`, not `jsonb`); `occurredAt` by `format_instant` | H8 (bytes), C3 (writer identical) |
| L22 | **A request value the column cannot hold** | MySQL strict mode raised at insert → `INTERNAL_ERROR` → retried | `nvarchar(20)` overflow → `SqlException` → `UNAVAILABLE` → retried | Refused at the edge: `orderReference` longer than 20 characters → `VALIDATION_FAILED` (terminal), because the wire pattern `^ORD-[0-9]{6,}$` has no maximum and `reservations.order_reference` is `varchar(20)`; codes are bounded by the schema's own `maxLength` (20 / 30 = the columns) | F2 (FS28); arm: drop the length check (the reply changes kind) |
| L23 | **An order reference is routed, not re-parsed** | #7's `OrderNumber` accepted every pattern-valid reference | Likewise | The order reference stays a `str` from the wire to the column; the kernel's canonical `OrderNumber` (which refuses `ORD-000000`) is never applied on this path (FS28, SO12's mirror) | H5 (`ORD-000000` reserved); arm: parse with `OrderNumber` |
| L24 | **The idempotent-consumer copy** | Copied, uncallable through a `never`-typed `ConsumerName` (`apps/fulfillment/src/infrastructure/messaging/idempotent-consumer.ts`) | Not copied (#8 `design.md` §9) | **Not copied** (§10.4): Fulfillment consumes no fact in any of the three builds (`saga.md` §5, line 296; #7 `main.ts:24-25`); the parity guard's case 3 requires a copy only from a write model that references `AIOKafkaConsumer` | J3: parity case 3 stays green with its literal `{"otc_orders"}` |
| L25 | **Relay-family copies stay identical** | Copies; code parity deferred to its feature 19 (#8 `design.md` §8.3, citing #7's gate row 5) | Copies with banners; parity deferred to feature 19 because the canonical named `OrdersDbContext` | Copies **byte-identical** to Orders' after the module docstring, modulo a two-entry literal token map; a parity test built **now** (§10.2), because #8's reason for deferring (a service-specific type in the canonical's constructor) does not exist in Python, where the only differences are import paths and the topic constant's name | C3 + its sentinels |
| L26 | **Integer division** | n/a | n/a | None in this feature's code. Paging offset is `(page - 1) * page_size`; milliseconds become seconds only in settings properties (Orders' `OutboxRelaySettings` shape). The money guard walks `otc_fulfillment.domain` (`tests/architecture/test_money_guard.py:56`) | quality.sh |

**Python porting questions answered** (CLAUDE.md): integer division — L26; JSON serialisation — L10, L21; event-loop affinity — L18; task cancellation and exception propagation — L16, L19, §8.3; typing gaps — L20; numeric width — L5, L22; case sensitivity — L4; transaction and isolation defaults — L1, L13; connection and concurrency — L7, L14; single-statement atomicity — L6.

## 4. Port the guards too

#8's tests of this mechanism, enumerated by file (`ls ../order-to-cash-dotnet/tests/Fulfillment.UnitTests/*.cs ../order-to-cash-dotnet/tests/Fulfillment.IntegrationTests/*.cs`, 59 files), classified. Despatch-only files (`DespatchAdviceTests`, `OrderDespatchTests`, `DespatchCreationServiceTests`, `DespatchCreateTests`) are feature 18's.

| #8 test | #9 |
|---|---|
| `StockItemTests`, `ReservationTests`, `OrderStockReservationTests` | **Ported** (`unit/domain/`), plus FS24's per-site provenance (B7) which #8 reached only after id 49 |
| `StockReservationHandlerTests` (FS5 any status, reply after commit, rollback) | **Ported** (`unit/test_stock_reservation_service.py`) |
| `StockReplenishServiceTests` | **Ported** (all-or-nothing) |
| `StockRpcErrorMapperTests` (FS21, reads Orders' set) | **Ported** as a cross-service architecture test (F4), importing `TERMINAL_RPC_ERROR_CODES` |
| `StockResponderHeaderTests` | **Ported** (F3) |
| `StockResponderConcurrencyTests` (unit + integration) | **Ported** (F6, H9) |
| `StockResponderShutdownTests` (#8 id 50) | **Ported** from Orders' equivalent (F7) |
| `StockLockOrderTests` | **Ported**, case-sensitive (E3) |
| `StockRequestValidatorTests` | **Replaced**: the generated models are the validator; one wire case per constraint (F2) |
| `StockRpcPayloadTests`, `AsyncApiSchema*` (#8 id 51: hand-retyped key lists) | **Not ported, avoided by construction**: no hand-written payload type exists; the generated models are drift-tested in `packages/contracts` |
| `StockSubjectsTests`, `FulfillmentFactTopicTests` | **Ported** (pyyaml over `asyncapi.yaml`, F1, C5) |
| `StockClaimProjectionTests` (literal column lists in raw SQL) | **Not applicable**: the locking reads are ORM `select(Stock)` statements, no literal column list exists |
| `FulfillmentDispatcherRegistrationTests` | **Ported** (G6), plus the behavioural registration guard (G8) |
| `FulfillmentProgramConfigurationTests` | **Ported** as the settings → adapter reach test (G4) and the per-variable settings test (G3) |
| `StockCheckTests`, `StockReserveTests`, `StockReserveRaceTests`, `StockReleaseIdempotencyTests`, `StockReplenishTests`, `StockListTests`, `StockWireTests`, `StockItemRepositoryTests`, `FulfillmentOutboxRelayTests` | **Ported** (group G/H), with #8's D1 and D2 closed by opening every emitted row (§13.2) |
| `FulfillmentResponderReadinessRaceTests` (#8 id 63, a paced wait in the fixture) | **Not applicable**: the fixture's host is reachable when `start()` returns (FS27); no wait loop exists to pace |
| `OutboxSeqIdentityTests`, schema / FK / index / round-trip tests | Already ported in phase 6 (`services/fulfillment/tests/integration/`) |
| `StockRpcResponderTraceContinuationTests`, `LogCorrelationTests`, `HealthProbesTests`, `MsSqlHealthCheckPoolingTests` | **Feature 27** (tracing, structured logging, health probes) |
| `FulfillmentDbContextFactoryTests`, `SqlExceptionFactory`, `CapturedConsole`, collection fixtures | **Not applicable** (EF Core / xUnit plumbing) |

## 5. The domain

### 5.1 `StockItem` — the aggregate root

```python
class StockItem(AggregateRoot):
    @classmethod
    def rehydrate(cls, snapshot: StockItemSnapshot) -> StockItem   # refuses F1 breach, negatives, foreign reservations
    company_code: str; product_code: str; units: int; reserved_units: int; low_stock_threshold: int
    available_units: int                                          # units - reserved_units, derived
    reservations: tuple[ReservationView, ...]                     # those LOADED (the order being handled)
    def can_reserve(self, units: int) -> bool                     # pure question (R31's shape)
    def reserve(self, *, reservation_id: UniqueId, order_reference: str, retailer_code: str, units: Quantity) -> Reservation
    def release(self, order_reference: str) -> tuple[Reservation, ...]
    def consume(self, order_reference: str) -> tuple[Reservation, ...]
    def replenish(self, quantity: Quantity) -> None
    def record_order_fact(self, fact: StockEvent) -> None         # refuses unless fact.aggregate_id == self.id
    def to_snapshot(self) -> StockItemSnapshot
```

- **`reserve`** raises `InsufficientStockError` when `units.value > self.units - self.reserved_units` (subtraction, R30), else appends one `reserved` reservation and adds its units. Emits nothing (the order-scoped fact is §5.3's).
- **`release`** moves this item's `reserved` reservations of the order to `released` and subtracts their units, returning them (empty when none was `reserved`, F5). It raises `ReservationTerminalError` and changes nothing if any of the order's reservations on this item is `consumed` (F4, FS10) — checked **before** any mutation.
- **`consume`** moves this item's `reserved` reservations of the order to `consumed` and subtracts their total from **both** `units` and `reserved_units` (FS11); emits nothing. No caller until feature 18.
- **`replenish`** adds to `units`, appends no event (R61). No width check here (L5).
- **F2 by construction.** `reserved_units` is never assigned from outside; every change is co-located with the reservation change it describes, and the repository writes both in one transaction (FS12). `rehydrate` trusts the stored counter (it is the authoritative cache) and loads only the order's reservations, as #8 (§3.1 of #8's design).
- Every mutation is all-or-nothing within the call: compute, check, then assign; a raised error leaves the aggregate unchanged (the R30 / R35 / FS10 tests compare `to_snapshot()` before and after).

### 5.2 `Reservation` and its state machine

`ReservationStatus` is a plain `enum.Enum` (not `StrEnum`) with the explicit tokens `reserved`, `released`, `consumed`, and `parse_reservation_status(token)` is a literal `dict` lookup after `type(token) is str`, raising `UnknownReservationStatusError` — the Orders `OrderStatus` convention (`specs/orders_aggregate/design.md` L1). `Reservation.release()` and `.consume()` are legal only from `RESERVED`; from either terminal they raise `ReservationTerminalError(from, to)` and change nothing (R35, F4). A `Reservation` is reachable only through its `StockItem`, which exposes frozen `ReservationView`s.

### 5.3 The order-scoped operation — pure functions, and the three facts

F3 is a rule across aggregates (one item per product), and R32/R33 demand **one** fact per order: it lives in `domain/order_stock_reservation.py` as two pure functions, never in a handler.

```python
def reserve_order(items: Mapping[str, StockItem], request: ReserveOrderInput, context: StockContext,
                  new_id: Callable[[], UniqueId]) -> ReserveOutcome   # Reserved | Rejected | NoCarrier
def release_order(items: Sequence[StockItem], request: ReleaseOrderInput, context: StockContext,
                  new_id: Callable[[], UniqueId]) -> ReleaseOutcome   # Released | AlreadyReleased
```

- `items` is keyed by the exact product code (L4). `ReserveOrderInput` carries `order_reference: str`, `company_code`, `retailer_code`, `lines: tuple[ReserveLine, ...]` (product code + `Quantity`), `correlation_id: UniqueId`. `StockContext` carries `occurred_at` (from the clock port) and `causation_id` (the `x-request-id`, FS3).
- **Carrier (FS13).** The item of the first request line that resolves to a known item; none → `NoCarrier` (the application raises `NoKnownStockItemError` → `NOT_FOUND`, §8.5). Released: the item of the first released reservation, in the order the items were passed (§6.3's lock order).
- **Evaluation before mutation.** Units are summed per product in first-appearance order (a `dict`, insertion-ordered); a product with no item is short with `available: 0` and sets `unknown_product` (FS8, which wins over `insufficient_stock`); any other product whose summed request exceeds `available_units` is short. Any shortage → one `StockRejected` whose `shortages` lists the short products only, in first-appearance order, `requested` the exact sum. Otherwise one `reserve` call **per line** (a repeated product yields two reservations) and one `StockReserved` whose `reservations` are the `ReservationRef`s in line order.
- **Ids (FS24).** Every reservation id and every event id comes from `new_id()`: four call sites, each guarded separately (B7).
- **Release.** Calls `release` on each item in the given order; the union non-empty → one `StockReleased` (`reason` = the request's, `retailer_code` from the first released reservation, `company_code` from the carrier); empty → `AlreadyReleased`, no fact (F5, FS9).
- Facts are recorded on the carrier with `record_order_fact`, which refuses a fact whose `aggregate_id` is not the item's own (`FactAggregateMismatchError`).

### 5.4 Events and errors

`domain/events.py` mirrors `otc_orders/domain/events.py`: frozen, slotted, keyword-only dataclasses over a `StockEventBase` (`event_id`, `aggregate_id`, `correlation_id`, `causation_id`, `occurred_at`), `EVENT_TYPE` class constants `stock.reserved.v1`, `stock.rejected.v1`, `stock.released.v1`, tuples for sequences, domain types only (no `otc_contracts`). Errors subclass `otc_shared_kernel.DomainError` with dotted lower-case codes in Orders' style: `InsufficientStockError` (`stock.insufficient`), `ReservationTerminalError` (`reservation.terminal`), `InvalidStockItemSnapshotError` (`stock_item.invalid_snapshot`), `FactAggregateMismatchError` (`stock.fact_aggregate_mismatch`), `UnknownReservationStatusError` (`reservation.unknown_status`). There is no overflow error in the domain (L5).

### 5.5 Invariants → where enforced → proven by

| Invariant | Enforced by | Proven by |
|---|---|---|
| F1 | `StockItem.reserve` (subtraction), `rehydrate` | R30 domain unit; FS6 race |
| F2 | co-located counter mutation; one transaction | FS12 unit + integration |
| F3 | `reserve_order` evaluates every product before any `reserve` | R33 domain unit (three items, third short); FS6 |
| F4 | `Reservation.release` / `.consume` | R35; FS10 |
| F5 | `StockItem.release` returns `()`; `release_order` emits nothing | R34 unit + integration; FS9 |

## 6. Transactions and locks

### 6.1 `stock.check` and `stock.list` — reads that hold nothing

`StockReads.availability(company_code, lines)` is one `select(Stock.product_code, Stock.units, Stock.reserved_units).where(company_code == …, product_code.in_(…))` in a short session (no `FOR UPDATE`, nothing written); per-line arithmetic in Python; an unknown product answers `available: 0, sufficient: false` (FS22); the overall `available` is true only when every line is sufficient. `StockReads.list(query)` applies the optional exact filters, expresses `below_threshold` as `Stock.units - Stock.reserved_units < Stock.low_stock_threshold` in SQL, orders by `company_code, product_code`, applies `offset((page - 1) * page_size).limit(page_size)`, and issues one `count()` for `PageInfo.total` (FS15). A plain `SELECT` under `READ COMMITTED` never waits for a row lock, which is R31's "non-locking".

### 6.2 `stock.reserve` — the authoritative claim

Inside one `StockTransactions.run(work)` attempt, in this order and nothing else:

```text
1. for (company_code, product_code) in sorted(set(keys of the request)):           # FS19, L3
       SELECT stock.* FROM stock WHERE company_code = :c AND product_code = :p FOR UPDATE   # one statement each
2. SELECT reservations.* FROM reservations WHERE order_reference = :ref ORDER BY id FOR UPDATE   # ALL of the order's, after 1
3. if any row from 2: reply already_reserved with exactly those rows as ReservationRefs   # FS5: no status filter, no domain call, nothing written
4. else: reserve_order(items, …)            # pure
5. Reserved:  new reservation rows (session.add), stock.reserved_units assigned, one outbox row (stock.reserved.v1)
   Rejected:  no stock or reservation write; one outbox row (stock.rejected.v1)
   NoCarrier: nothing written; NoKnownStockItemError raised -> rollback -> NOT_FOUND
6. COMMIT, then the reply (built from the outcome, returned only after run() returns)
```

Each lock statement is an ORM `select(Stock).where(…).with_for_update()`, so the row is a tracked instance and the update is an attribute assignment at flush (§9.2). The reservation read uses `ORDER BY id` so two transactions locking the same reservation rows lock them in one order.

**Why it is safe in PostgreSQL** (measured, header): a second reserve for the **same** order (a lost reply re-issued with the same stored bytes) waits at step 1 on the first's stock rows; once the first commits, step 1 returns the updated rows and step 2, a new statement with a fresh snapshot, sees the first's reservations → `already_reserved`. Two reserves for **different** orders and the last units: the second waits at step 1, reads the counter the first committed, and is rejected (FS6). Swapping steps 1 and 2 breaks the first case (the reservation read returns 0, measured), which is D5's arm.

**The residual (gate point G1).** Two **concurrent** reserves for one order whose product sets are **disjoint** lock disjoint stock rows, so neither waits and both can reserve. #8 was protected by `HOLDLOCK`'s key-range lock; PostgreSQL has none. It is unreachable from the system's own caller: Orders stores one `stock.reserve` payload per `(order_id, command)` and resends those exact bytes on every attempt (`specs/order_saga_orchestrator/design.md` L10, L21), so every re-issue names the same products; the sequential case with a different product set **is** covered (step 2 reads all of the order's reservations, D6).

**F3 versus `domain-model.md` §8 rule 6.** One transaction mutates one `StockItem` per distinct product; F3 wins, as #7's and #8's gates ruled (#8 `design.md` §4.2). Decided, not reopened.

### 6.3 `stock.release` — and SA-4's one lock

```text
0. NON-LOCKING pre-read, own short session: SELECT DISTINCT stock.company_code, stock.product_code
   FROM reservations JOIN stock ON stock.id = reservations.stock_id WHERE reservations.order_reference = :ref
   -> empty: reply already_released, released [] — no transaction, no fact (FS9)
1. lock those stock rows exactly as §6.2 step 1 (same order)                      # THE SA-4 LOCK
2. SELECT reservations … WHERE order_reference = :ref ORDER BY id FOR UPDATE
   -> a reservation whose stock_id is not among the locked rows: ConcurrentReservationChangeError (UNAVAILABLE, defensive)
3. release_order(items in lock order, …)    # ReservationTerminalError on a consumed row -> PRECONDITION_FAILED (FS10)
4. Released: reservation status + updated_at, stock.reserved_units, one outbox row (stock.released.v1); AlreadyReleased: nothing
```

**The SA-4 lock, stated precisely so feature 18 takes the same one:** *the `stock` rows of every item on which the order holds a reservation (any status), each locked by its own `SELECT … FOR UPDATE`, in code-point order of `(company_code, product_code)`, followed by the order's `reservations` rows `FOR UPDATE ORDER BY id`.* It is built once, as two methods: `StockReads.stock_keys_of_order(order_reference)` (step 0, its own short session, outside any transaction) and `StockRepository.lock_order_items(order_reference, keys) -> LockedStock` (steps 1 – 2, inside `run()`); `stock.release` uses exactly these two. Feature 18's `despatch.create` must call the same two; two transactions on one order then serialise on the first stock row, and whichever commits second decides on the first's committed reservations (release sees `consumed` → `PRECONDITION_FAILED`; despatch sees `released` → no reservation to consume). This is the property #7 already had (`stock-reservation.handler.ts:103, 108-109` and its despatch twin, #8 id 79) and #8 had by the same shape. FS25's integration test guards the release half; the race in both outcomes is feature 18's.

The step-0 pre-read decides only whether to open a transaction; the decision is re-made under the lock. Its race (a reservation created between step 0 and step 1) is unreachable: the saga issues `stock.release` only after `stock.reserved.v1` (R27) or for an operator cancel of a `stock_reserved` order, both after the reserve committed.

### 6.4 `stock.replenish`

Lock the named items exactly as §6.2 step 1; if any requested product has no row, raise `UnknownStockItemError(product_code)` **before** any mutation (FS14, all-or-nothing); `replenish` each (summing repeated lines); save — the mapper's assignment of `units` is where FS20's range guard fires; **no outbox row**. Not idempotent by design (a top-up is a delta; #8 `design.md` §4.5).

### 6.5 `StockTransactions.run(work)` — isolation and the 40P01 re-run

```python
DEADLOCK_ATTEMPTS = 3                 # the relay's (relay.py:47), total attempts
DEADLOCK_BACKOFF_SECONDS = 0.2        # the relay's (relay.py:48), before each re-run

async def run[T](self, work: Callable[[StockTransaction], Awaitable[T]]) -> T:
    attempt = 1
    while True:
        try:
            async with self._sessions() as session, session.begin():
                await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
                tx = SqlAlchemyStockTransaction(session, self._clock, self._outbox)
                result = await work(tx)
            tx.repository.clear_saved_events()          # only after the commit returned (OI9)
            return result
        except DBAPIError as error:
            state = sqlstate_of(error)
            if state == DEADLOCK_DETECTED and attempt < DEADLOCK_ATTEMPTS:
                log.warning(... attempt, sqlstate ...); attempt += 1
                await self._sleep(DEADLOCK_BACKOFF_SECONDS); continue
            if state in TRANSIENT_SQLSTATES: raise StoreUnavailableError(state) from error
            raise
        except (sqlalchemy.exc.TimeoutError, OSError) as error:   # pool timeout, refused connection
            raise StoreUnavailableError(type(error).__name__) from error
```

- `TRANSIENT_SQLSTATES` = `40P01` (exhausted), `40001`, `55P03` (`lock_not_available`), `57014` (`query_canceled`), `53300` (`too_many_connections`), and class `08` (connection exceptions) — a literal set in `stock_transactions.py`. Nothing but `40P01` is re-run (FS23).
- `work` is re-runnable by construction: it receives everything through `tx`, builds its aggregates from rows read in **this** attempt, mints ids per attempt, and performs no I/O outside the transaction (no NATS, no Kafka). The handlers' `work` closures are the only callers; `tasks.md` forbids a `work` that touches anything but `tx` and its own arguments.
- `_sleep` is injected (default `asyncio.sleep`) so the pacing is proven by a recorded call, a change of kind; a `CancelledError` raised in it propagates and no further attempt runs (L19).
- Orders' unit of work does **not** retry (its gate point G2: a retried block re-runs caller code the class cannot see). This one may, because its contract is the callable it is given; the difference is stated in the module docstring.
- **Budget.** Worst case three detections at `deadlock_timeout` 1 s plus two 0.2 s pauses ≈ 3.4 s plus the work, under the saga's 5 000 ms per attempt (`SAGA_COMMAND_TIMEOUT_MS`). A caller timeout is itself retried by Orders with the same `x-request-id`, and the re-issue is idempotent (FS5).
- **How a test produces a real `40P01`** (I4; Orders' `test_outbox_relay_deadlock.py` construction): the test's own connection takes `FOR UPDATE` on **P2**; a reserve for `[P1, P2]` locks P1 and waits on P2 — the test waits until `pg_locks` shows that request **ungranted**, never on a sleep; the test's connection then asks `FOR UPDATE` on **P1**: a cycle. The responder's backend waited first, so its `deadlock_timeout` expires first and it is the victim (`40P01`); attempt 2 waits on P1; the test rolls back; attempt 2 commits. The test asserts the test connection's own statement did not raise (so the victim was the responder), one WARNING record naming `40P01`, the reply `accepted`, and exactly one `stock.reserved.v1` row.

## 7. The application layer

### 7.1 Messages, handlers, registration

| Subject | Message (`otc_cqrs`) | Result (application dataclass) | Handler → unit |
|---|---|---|---|
| `fulfillment.stock.check` | `CheckStockQuery(Query[StockAvailability])` | per-line availability | `CheckStockHandler` → `StockReads.availability` |
| `fulfillment.stock.list` | `ListStockQuery(Query[StockPage])` | items + page info | `ListStockHandler` → `StockReads.list` |
| `fulfillment.stock.reserve` | `ReserveStockCommand(Command[ReserveResult])` | `accepted` / `rejected` / `already_reserved` + refs or shortages | `ReserveStockHandler` → `stock_reservation.reserve` |
| `fulfillment.stock.release` | `ReleaseStockCommand(Command[ReleaseResult])` | `released` / `already_released` + refs | `ReleaseStockHandler` → `stock_reservation.release` |
| `fulfillment.stock.replenish` | `ReplenishStockCommand(Command[ReplenishResult])` | the affected `StockView` data | `ReplenishStockHandler` → `stock_replenishment.replenish` |

`ReserveStockCommand` and `ReleaseStockCommand` carry `correlation_id` and `request_id` as `UniqueId`; the queries and replenish carry neither. `composition.register_handlers` registers the five, one plain statement each; `build_dispatcher` validates against `otc_fulfillment.application` (a message with zero or two handlers fails the boot); `start_runtime` builds every registered factory once against a real scope before anything listens (feature 43's carried item). No events, no `EventHandler`: Fulfillment owes no post-commit in-process hop; the relay is its only post-commit obligation.

### 7.2 Ports and scope

`StockTransactions.run(work)`; `StockTransaction.repository: StockRepository` with `lock_for_reserve(company_code, product_codes, order_reference) -> LockedStock`, `lock_order_items(order_reference, keys) -> LockedStock` (§6.3 steps 1 – 2), `lock_for_replenish(company_code, product_codes) -> dict[str, StockItem]`, `save() -> None` (syncs every loaded item and its reservations, drains every item's events into outbox rows). `LockedStock` carries `items: dict[str, StockItem]` (exact keys, lock order preserved) and `reservations_of_order: tuple[ReservationSnapshot, ...]` (all of the order's, FS5). `StockReads` never locks or writes: `availability`, `list`, and `stock_keys_of_order(order_reference)` (§6.3 step 0). `StoreUnavailableError` is the application-level transient refusal (no SQLAlchemy type crosses into `application` or `presentation`). `FulfillmentScope(transactions, reads, clock, ids)` refuses an unbound port at construction (Orders' `scope.py` shape).

`stock_reservation.release` calls `scope.reads.stock_keys_of_order` **before** `run()`; an empty result returns `already_released` without ever calling `run()` (FS9's "no transaction", observable with a fake in E4).

### 7.3 The transactional units

`stock_reservation.reserve(command, scope)`: `await scope.transactions.run(work)` where `work` = `lock_for_reserve` → `already_reserved` from `reservations_of_order` if non-empty (no domain call, no `save`) → else `reserve_order(…, new_id=scope.ids.new)` → `NoCarrier` raises `NoKnownStockItemError` → else `save()` → result. A business rejection is a **result**, never a raise (saga.md §7, SO6). `stock_reservation.release`: the pre-read (FS9 path returns without `run`), then `run` with the locked half, `release_order`, `save`. `stock_replenishment.replenish`: `run` with `lock_for_replenish`, all-or-nothing check, `replenish`, `save`.

## 8. Presentation — the responder

### 8.1 One task class, five subjects

`StockResponder` is Orders' `OrdersCreateResponder` generalised to a subject table: `start()` subscribes the five subjects (queue group `otc-fulfillment`, so replicas answer once) with one callback that only enqueues `(subject, msg)`, then **awaits `connection.flush()`** (FS27, L17); `run(stop)` is the task body the lifespan owns: the loop takes messages in order and serves each in its own task tracked in `in_flight`; on `stop` the subscriptions are unsubscribed, queued messages are still served, and `_drain` awaits every in-flight task with `return_exceptions=True`; `_log_fault` logs a request task that failed to reply; cancelling `run` cancels the request tasks and re-raises (L16, L19). The subject table is a `dict[str, Route]` literal in `stock_responder.py` so feature 18 adds `fulfillment.despatch.create` as one entry.

### 8.2 The bound (FS18, L7)

Each request task does `async with self._bound:` (an `asyncio.Semaphore(max_concurrent_requests)`) **before** its handler opens a session, and releases it in all cases. Requests beyond the bound wait as tasks, cheaply, holding no connection. The composition root creates the engine with `pool_size = max_concurrent_requests + 1` (the relay's session) and `max_overflow = 0`, so the number of sessions the responder can open never exceeds the pool and a request blocked on a row lock degrades into waiting, never into a pool timeout. `FULFILLMENT_MAX_CONCURRENT_REQUESTS` defaults to **16** and is refused below 1 at boot. (#8 chose 32 against ADO.NET's pool of 100; #9's figure is chosen against the per-service share of PostgreSQL's default `max_connections` of 100, with Orders' default pool of 5 + 10 alongside.)

### 8.3 Per request

```text
no reply subject           -> log WARNING, drop (Orders' rule)
empty body                 -> VALIDATION_FAILED
reserve / release          -> headers first (FS3): both present and UniqueId.parse-able, else VALIDATION_FAILED, nothing dispatched
decode                     -> from_wire_json(<generated request model>, data); ValueError -> VALIDATION_FAILED
edge checks                -> orderReference <= 20 chars (FS28); else VALIDATION_FAILED
dispatch                   -> dispatcher.send / ask with a fresh FulfillmentScope (a new unit of work per request)
reply                      -> to_wire_json(<generated reply model>)  |  to_wire_json(RpcError) via §8.5
```

Every exception of the request path becomes an `RpcError` reply; only a failure to send the reply escapes the request task (and is logged by `_log_fault`). `RpcError.correlationId` is set from `x-correlation-id` when present; `occurredAt` from the clock port.

### 8.4 Wire mapping (`stock_wire.py`)

Request → message: `order_reference` stays a `str` (L23); quantities become `Quantity` (the generated model already refused non-positive and non-integer values). Result → reply: `StockReserveReplyPayload(outcome=…, order_reference=…, reservations=[ReservationRef…] | None, shortages=[Shortage…] | None)` per the schema's "present when" notes; `StockReleaseReplyPayload(released=[])` for FS9 (an empty list is written, a `None` would be omitted); `StockView.available_units = units − reserved_units`.

### 8.5 The error mapping — every code is a saga decision

Orders' adapter splits the twelve codes: nine terminal (`TERMINAL_RPC_ERROR_CODES`, `nats_saga_commands.py:65-75`), three transient (`TIMEOUT`, `UNAVAILABLE`, `INTERNAL_ERROR`). Every failure this responder can answer:

| Failure | Code | Orders' class | #7 answered | #8 answered |
|---|---|---|---|---|
| Body not JSON / fails the generated model / missing or malformed header / `orderReference` > 20 chars | `VALIDATION_FAILED` | terminal | `VALIDATION_FAILED` (`rpc-error-mapper.ts:28-34`) | `VALIDATION_FAILED` |
| Reserve: no line resolves to a known item (`NoKnownStockItemError`, no carrier) | `NOT_FOUND` (+ `details.orderReference`) | **terminal** | `NOT_FOUND` (`:38-45`) — #7's orchestrator retried it | `NOT_FOUND`, terminal (#8 `design.md` §4.6) |
| Replenish: unknown product (`UnknownStockItemError`) | `NOT_FOUND` (+ `companyCode`, `productCode`) | n/a (not a saga command) | `NOT_FOUND` (`:46-53`) | `NOT_FOUND` |
| Release: a `consumed` reservation (`ReservationTerminalError`) | `PRECONDITION_FAILED` (+ `details.code`) | terminal (SA-4's "despatch wins") | `PRECONDITION_FAILED` (`:54-61`) | `PRECONDITION_FAILED` (`StockErrorMapper.cs:43`) |
| Any other `DomainError` — including `QuantityOutOfRangeError` from the range guard (FS20) | `DOMAIN_ERROR` (+ `details.code`) | terminal | `DOMAIN_ERROR` (`:89-96`) | `DOMAIN_ERROR` |
| Deadlock victim after 3 attempts; 40001; 55P03; 57014; 53300; class 08; pool timeout; refused connection (`StoreUnavailableError`) | `UNAVAILABLE` | transient | `INTERNAL_ERROR` by fall-through (`:100-104`) | `UNAVAILABLE` (`StockErrorMapper.cs:58-60`) |
| `ConcurrentReservationChangeError` (§6.3 defensive) | `UNAVAILABLE` | transient | **`CONFLICT`** (`:74-80`) — safe there, every code was retried | `UNAVAILABLE` |
| Anything else | `INTERNAL_ERROR` | transient | `INTERNAL_ERROR` | `INTERNAL_ERROR` |
| `CONFLICT`, `TIMEOUT`, `ORDER_NOT_CANCELLABLE`, `STOCK_UNAVAILABLE`, `INVOICE_NOT_PAYABLE`, `PAYMENT_MISMATCH` | **never produced** | — | `CONFLICT` produced (above) | `TIMEOUT` for its own deadline |

The `NOT_FOUND` row's consequence is #8's, accepted for the same reason (#8 `design.md` §4.6): the order stays `placed` with a `rejected` `stock.reserve` row; the seed makes it unreachable for demo data, which group I checks before the live walkthrough. A business rejection (`stock.rejected.v1`) is never an `RpcError`: it is the `rejected` outcome (SO6).

## 9. Persistence adapters

### 9.1 `stock_repository.py`

Implements §6's statements with ORM selects (`with_for_update()`), keeps an identity map of `(StockItem, Stock row, {reservation id: Reservation row})` per loaded item, and on `save()`: for each loaded item, `stock_mapper.apply(item, row)`; new reservations `session.add(Reservation(...))`; changed reservations by attribute assignment; then `OutboxWriter.write(session, events)` for **every** loaded item's events in raise order (the copy flushes per row, L9); events are cleared by `run()` only after the commit (OI9). `StockReads.stock_keys_of_order` uses its own `async with sessions()` block, closed before `run()` begins.

### 9.2 The write rule for guarded columns (feature 207's attachment)

`stock.units`, `stock.reserved_units` and `reservations.units` are written **only** by attribute assignment on a mapped instance (`row.units = item.units`) or the `Reservation(...)` constructor, both inside `stock_mapper.py`, with a plain `int` value. Never `update(Stock).values(...)`, never `insert(...).values(...)`, never `text()`, never a SQL expression (`Stock.units + n`): each of those bypasses the guard (`range_guards.py` docstring, lines 10 – 31). The rows are already locked, so a value assignment is exact; no atomic server-side increment is needed. `test_write_path_population.py` makes any other write path an unclassified hit (D9).

### 9.3 `stock_reads.py`

§6.1's two queries; sessions opened and closed per call; no transaction write, no `with_for_update`.

## 10. The outbox: copies, the parity guard, and consumers

### 10.1 What is copied

From `services/orders/src/otc_orders/`: `application/ports/clock.py`, `infrastructure/clock.py`, and `infrastructure/outbox/{errors,publisher,kafka_publisher,relay,relay_task,wire,writer}.py`. Service-specific, **not** copies: `infrastructure/outbox/topic.py` (`FULFILLMENT_FACTS_TOPIC = "otc.fulfillment.facts.v1"`, #7's constant name, `apps/fulfillment/src/infrastructure/outbox/kafka.config.ts:4`) and `infrastructure/outbox/payloads.py` (`narrow` + `build_fact` for the three stock events, `assert_never` over the union so feature 18's `OrderDespatched` is a type error until mapped). The `KafkaSettings` the publisher copy reads has the same field names as Orders' with the alias `FULFILLMENT_KAFKA_CLIENT_ID` (default `otc-fulfillment`, #7's and #8's value, `kafka.config.ts:31`; `src/Fulfillment/Infrastructure/FulfillmentOptions.cs:26`), so the copy's code is unchanged.

### 10.2 The parity guard — built now

`tests/architecture/test_outbox_copy_parity.py`: for each copied module, the Fulfillment file's text **after its module docstring** equals the Orders file's text after its docstring once a literal token map is applied to the copy: `{"otc_fulfillment": "otc_orders", "FULFILLMENT_FACTS_TOPIC": "ORDERS_FACTS_TOPIC"}`. The copy's docstring names its canonical. The member list and the module list are literals; a census asserts every file under `otc_fulfillment/infrastructure/outbox/` is either a listed copy or one of the two listed service-specific modules. Sentinels (temporary trees): a one-character change after the docstring fails; a missing copy fails; an extra unlisted outbox module fails; a token-map substitution in a non-identifier position (`"otc_fulfillment"` inside a log string the canonical does not have) fails. **Why now and not at feature 19 as #7 and #8 did:** their reason was that the canonical named a service-specific type in its constructor (#8 `design.md` §8.3), which a byte-identity check cannot see past without refactoring the canonical; in Python the only differences are the import paths and the topic constant, which a two-entry map covers. What this buys: the relay family's behaviour is proven once, by Orders' tests (feature 14's relay, deadlock, concurrency and wire suites), and this guard proves Fulfillment runs the same code; Fulfillment's own tests then prove only its wiring (FS16).

### 10.3 Relay deployment rule

At most one relay per process and no multi-worker server while `OUTBOX_RELAY_ENABLED=true` (outbox design §5.2): `composition.py` carries the same `assert_single_outbox_relay` / `_claim_relay_slot` as Orders' (`composition.py:181-230`), not a shared module (no fourth shared runtime package).

### 10.4 Consumers — none

Fulfillment consumes no fact in #7, #8 or #9 (`saga.md` §5; #7 `main.ts:24-25`; #8 `design.md` §9): `stock.reserve`, `stock.release` and `despatch.create` are commands. No `AIOKafkaConsumer`, no idempotent-consumer copy, `processed_events` unused. The parity guard (`services/orders/tests/unit/test_idempotent_consumer_parity.py`): **case 3** requires a copy only from a write model with a relational ledger that references `AIOKafkaConsumer` — Fulfillment has the ledger and only a producer, so its literal `{"otc_orders"}` stays true; **case 1** compares copies found, and Fulfillment has none. Neither case goes live in 17 or 18; both go live at **feature 23** `notifications_service`, which has a `processed_events` table (`otc_notifications/infrastructure/persistence/models.py`) and consumes seven facts (`saga.md` §5).

## 11. Composition, lifespan, settings, packages

### 11.1 Settings (`infrastructure/settings.py`)

| Class | Field ← variable | Default |
|---|---|---|
| `FulfillmentDatabaseSettings` | existing (unchanged) | — |
| `OutboxRelaySettings` | `OUTBOX_RELAY_ENABLED`, `OUTBOX_POLL_INTERVAL_MS`, `OUTBOX_BATCH_SIZE`, `OUTBOX_PUBLISH_TIMEOUT_MS` (Orders' names and defaults) | `true`, 250, 100, 5000 |
| `KafkaSettings` | `KAFKA_BROKERS`, `FULFILLMENT_KAFKA_CLIENT_ID` | `localhost:9092`, `otc-fulfillment` |
| `NatsSettings` | `NATS_URL` | `nats://localhost:4222` |
| `ServerSettings` | `WEB_CONCURRENCY` | 1 |
| `ResponderSettings` | `FULFILLMENT_MAX_CONCURRENT_REQUESTS` (≥ 1) | 16 |

Each field has a `validation_alias` and no `populate_by_name` (review_db_fulfillment A1). The deadlock constants are code constants, as the relay's.

### 11.2 `composition.py` and `main.py`

Orders' shape: `FulfillmentSettings` bundle and `load_settings()` (the only environment read); `register_handlers`, `_wire`, `build_dispatcher` (pure); `start_runtime(settings)`: single-relay check → dispatcher validated before anything opens → engine (`pool_size`, `max_overflow` per §8.2) → session factory → clock, id source → NATS connect → transactions, reads, repository factory → every registered factory built once against a real scope → `StockResponder.start()` (subscribe + flush) → tasks `nats-responder` and, when enabled, `outbox-relay` (publisher started first) → `FulfillmentRuntime` (readiness: a done task or a closed / reconnecting NATS connection is a reason; `stop()` sets the stop event, awaits both tasks, then closes the stack: producer, NATS drain, engine dispose). `main.py`'s lifespan calls `start_runtime(load_settings())` and stores the runtime on `app.state.runtime`; `presentation/app.py` gains `create_app(lifespan=…)` and `/health/ready` (Orders' file).

### 11.3 Packages

`services/fulfillment/pyproject.toml` gains `aiokafka` and `nats-py>=2.16.0` (Orders' pins, already in `uv.lock`); `uv lock` updates only workspace metadata. `Packages installed: none` (both already locked). No change to root `pyproject.toml`'s tool sections is needed: the import-linter contracts already name `otc_fulfillment` in all four of its contracts.

## 12. Architecture guards and censuses this feature touches

| Instrument | Change | Why |
|---|---|---|
| `tests/architecture/test_composition_env_reads.py` | `EXPECTED_ROOTS` gains `fulfillment`; `LOAD_SETTINGS_ROOTS` gains it; `EXPECTED_SETTINGS["fulfillment"]` = the six classes of §11.1 | #8 id 56 (recurred three times in Phase 8): written **with** the root |
| `tests/architecture/test_registration_behaviour.py` | `SERVICES` gains `fulfillment`, with its literal command / query tables | feature 43's carried item |
| `tests/architecture/test_write_path_population.py` | `EXPECTED["fulfillment"]` gains every new hit, counts read from `scan_service("fulfillment")`, each classified (guarded / not a write / no guarded column) | feature 207; §9.2 |
| `tests/architecture/test_kafka_client_confinement.py` | `EXPECTED_IMPORTERS` gains `otc_fulfillment.infrastructure.outbox.kafka_publisher` | the second producer |
| `tests/architecture/test_outbox_copy_parity.py` | **new** | §10.2 |
| `tests/architecture/test_fulfillment_rpc_error_retryability.py` | **new**, imports both services (tests are outside import-linter's `root_packages` contracts) | FS21, L8 |
| `test_range_guard_parity.py`, `test_money_guard.py`, `test_cqrs_registration_explicit.py`, idempotent-consumer parity | **no edit**; must stay green | the range guard is not touched; the domain imports only allowed roots; decorators used are the census's seven |

## 13. Testing

### 13.1 Files and levels

| File (under `services/fulfillment/tests/`) | Level | Proves |
|---|---|---|
| `unit/domain/test_stock_item.py`, `test_reservation.py`, `test_reservation_release.py`, `test_stock_replenishment.py`, `test_domain_tests_are_pure.py` | domain unit, pure | R30, R32 – R35, R61, FS8, FS10 – FS13, FS24; purity (Orders' `test_domain_tests_are_pure.py` ported) |
| `unit/test_stock_reservation_service.py`, `test_stock_replenishment_service.py` | unit, fakes | FS5, reply after commit, rollback, FS9 path opens no transaction, FS14 |
| `unit/test_stock_transactions.py` | unit, fake session factory | FS23 bound, pacing, non-40P01, cancellation |
| `unit/test_stock_lock_order.py` | unit | FS19 / L3 / L4 ordering |
| `unit/test_stock_responder.py`, `test_stock_requests.py`, `test_stock_subjects.py`, `test_fact_topic.py`, `test_stock_rpc_errors.py` | unit | FS3, FS18 bound, FS26, FS27, FS28, every schema constraint, every row of §8.5; subjects and topic from `asyncapi.yaml` |
| `unit/test_outbox_payloads.py`, `test_stock_mapper.py` | unit | the three payload mappings field by field; the write-boundary refusal (FS20's unit half) |
| `unit/test_fulfillment_settings_env.py` | unit | every variable reaches exactly its field (Orders' file ported, feature 210's alias closure) |
| `integration/test_stock_check.py`, `test_stock_reserve.py`, `test_stock_reserve_race.py`, `test_stock_release_idempotency.py`, `test_stock_replenish.py`, `test_stock_list.py`, `test_stock_wire.py`, `test_stock_responder_concurrency.py`, `test_stock_deadlock_retry.py` | integration (real PostgreSQL + NATS through the real lifespan) | R31, R34, FS3 – FS10, FS14, FS15, FS18 – FS20, FS22, FS23, FS25, FS28 |
| `integration/test_stock_repository.py` | integration (PostgreSQL) | FS12, FS19's protocol and isolation, D7 rollback |
| `integration/test_fulfillment_outbox_relay.py` | integration (+ Kafka) | FS16 |
| `integration/test_fulfillment_host_lifespan.py` | integration | boot validation, readiness, shutdown, the reach test, single relay |
| `tests/architecture/test_outbox_copy_parity.py`, `test_fulfillment_rpc_error_retryability.py` | architecture | L25, FS21 |

### 13.2 Fixtures and the synchronisation rule

The `NatsServer` / `nats_server` session fixture moves **unchanged** from `services/orders/tests/integration/conftest.py` (line 483) to the root `conftest.py`, beside Postgres and Kafka, so both services' suites share one Docker-held server; every subscriber a test makes (a host, a stand-in) is closed with that test, so the shared server never carries a stale `fulfillment.stock.*` subscriber into another test. A `fulfillment_host` factory fixture (function loop) boots the **real** `start_runtime` against `migrated_db`, the NATS server and, when asked, Kafka (relay disabled by default; the relay tests drive `run_once()` by hand); callers are raw `nats.connect()` clients. Integration suites pass with the developer stack down.

Synchronise only on **terminal or monotonic** evidence: the reply; an outbox row (written in the reply's transaction); a reservation's terminal status; a lock request seen **ungranted** in `pg_locks` / `pg_stat_activity.wait_event_type = 'Lock'` (for the constructed races); never on `reserved_units` mid-flight, never on a sleep.

**Every emitting or suppressing branch opens its row** (#8 D1, D2): the reserved, rejected and released outbox rows are each read back and every payload field and the envelope's `aggregateId`, `correlationId`, `causationId` asserted against **test-supplied, pairwise-distinct** values (order id ≠ request id ≠ carrier id; `companyCode` ≠ `retailerCode`; product codes none of which contains another, e.g. `PRD-A1`, `PRD-B2`, `PRD-C3`); each suppression (`already_reserved`, `already_released`, `NOT_FOUND`, `PRECONDITION_FAILED`, check, list, replenish) asserts zero rows **with a control row** in the same test (an emitting call whose row is seen), so the outbox read is shown able to see a row.

### 13.3 The constructed races (a change of kind, not of probability)

- **FS6.** The test's connection holds `FOR UPDATE` on the item (exactly enough units for one order); two reserves for different orders are sent; the test waits until **two** lock waits are ungranted, then commits. Correct code: both wait at the stock lock; the second reads the first's counter → one `accepted`, one `rejected`. Arm (drop `with_for_update` from the stock lock): both read before either writes, both then wait at their `UPDATE`, both decide `accepted` — deterministic, and the assertion "exactly one accepted" names it.
- **FS19 deadlock shape.** The test holds `FOR UPDATE` on P1 **and** P2; order A requests `[P1, P2]`, order B `[P2, P1]`; wait for two ungranted waits; commit. Correct code: both wait on P1, then run one after the other: zero deadlock-retry WARNING records. Arm (lock in request order): A gets P1 and B gets P2 when the test commits, each then waits on the other → one `40P01` → FS23 re-runs it → both still `accepted`, so the assertion is on the **WARNING count** (0 versus 1), which names the deadlock.
- **FS18.** The test holds `FOR UPDATE` on P1; reserve P1 is sent and seen waiting; reserve P2 is sent and must be **answered** while the first is still waiting; then the test commits and the first completes. Arm (serve inline in the loop): the second request times out.
- **FS25.** The test holds `FOR UPDATE` on one stock row of an order with reservations; `stock.release` is sent and must be seen **waiting** on that row (ungranted) before the test commits; then it completes. Arm (drop `with_for_update` from `lock_order_items`'s stock step): the release is never seen waiting and completes while the test still holds the lock.
- **FS23.** §6.5's construction.

### 13.4 Matrix name mapping

| `specs/shared/test-matrix.md` §4 path | #9 file |
|---|---|
| `fulfillment/domain/stock-item.spec` | `services/fulfillment/tests/unit/domain/test_stock_item.py` |
| `fulfillment/domain/reservation.spec` | `services/fulfillment/tests/unit/domain/test_reservation.py` |
| `fulfillment/domain/reservation-release.spec` | `services/fulfillment/tests/unit/domain/test_reservation_release.py` |
| `fulfillment/domain/stock-replenishment.spec` | `services/fulfillment/tests/unit/domain/test_stock_replenishment.py` |
| `fulfillment/integration/stock-check.spec` | `services/fulfillment/tests/integration/test_stock_check.py` |
| `fulfillment/integration/stock-release-idempotency.spec` | `services/fulfillment/tests/integration/test_stock_release_idempotency.py` |

## 14. The live stack — designed, not discovered (FS17)

**Pre-state** (`progress/current.md`; `progress/impl_order_saga_orchestrator.md` step 6): the developer database holds `ORD-000007` in `placed` with one `stock.reserve` row `parked`, re-attempted by Orders' sweeper on the capped park back-off (`SAGA_PARK_RETRY_CAP_MS` 900 000, sweeper every 30 s). No Orders change is needed: the headers already flow (FS2).

**Precondition read first.** The row's stored payload names `(companyCode, productCode)` pairs; each must exist in `otc_fulfillment.stock` (the seed is #7's and #8's dataset). If none resolves, the expected and correct observation is §8.5's `NOT_FOUND` → `rejected` row; if some are short, `stock.rejected.v1` → `cancelled` with no `stock.release` (R26). Either is recorded as observed, not reported as a failure.

**Expected, unattended,** once Orders (`uvicorn otc_orders.main:app --port 8101`) and Fulfillment (`uvicorn otc_fulfillment.main:app --port 8102`) are up: within one sweeper interval of the row's `next_attempt_at`, Orders re-issues `stock.reserve` with both headers; Fulfillment answers `accepted`; `otc_fulfillment.reservations` gains one `reserved` row per line; `stock.reserved_units` rises by the sums; `otc_fulfillment.outbox` gains one `stock.reserved.v1` that the relay stamps; the row becomes `sent`; the saga consumes the fact: `ORD-000007` → `stock_reserved`, one `credit.hold` row → no responder → `parked`. **Cross-service proof by query of both databases**: the outbox row's `correlation_id` equals `otc_orders.orders.id` and its `causation_id` equals the `stock.reserve` `saga_commands.id`. Then one fresh order through `orders.create` (the first acceptance answered by a real `stock.check` in #9) reaches `stock_reserved`. One negative check on a **throwaway** order reference: a raw `stock.reserve` without headers answers `VALIDATION_FAILED` — never against the parked row, whose `rejected` status would be irreversible. Hosts stopped by PID; the record goes to `progress/impl_fulfillment_stock.md` § Live boot.

## 15. Feature 18's boundary

Feature 18 has two acceptance items. **What 17 already delivers for them:** (1) *"reservations move to consumed"* — the domain transition (`StockItem.consume`, `Reservation.consume`, FS11, R35's `reserved → consumed` edge), the SA-4 lock (`StockReads.stock_keys_of_order` + `StockRepository.lock_order_items`), the mapper that persists a status and both counters, and `PRECONDITION_FAILED` for a terminal reservation; (2) *"order.despatched.v1 emitted via the outbox"* — Fulfillment's outbox writer, relay and publisher, running and parity-guarded, with `payloads.py`'s `assert_never` union ready for a fourth event. **What remains for 18, and why:** the `DespatchAdvice` aggregate (F6, F7) and the order-scoped `create_despatch`; the `DES-` allocator over the existing `sequences.py` constants; the sixth subject `fulfillment.despatch.create` (one entry in §8.1's table); `NoReservedStockForDespatchError` → `PRECONDITION_FAILED`; F8's layers (fast path, in-lock re-read under 17's pinned `READ COMMITTED` — #8 id 54, L13 — and the existing `despatches.order_reference` unique key); the release-versus-despatch race in **both** outcomes and the despatch half of FS25's lock test (#8 id 79); the `order.despatched.v1` payload mapping; the R36 matrix row. These need the despatch aggregate, which does not exist until 18.

## 16. Gate points, and what was decided without one

**The rule** (maintainer, Phase 8): where #7 and #8 decided the behaviour identically and only the mechanism is Python's, it is decided with citations; only a question they disagree on, or one #9's engine forces, goes to the gate, with a recommendation and evidence from a command.

### 16.1 Open for the gate

**Gate record:** the maintainer approved the spec on 2026-10-08 with G1, G2 and G3 decided **as recommended** below (G1: the concurrent-disjoint residual accepted, the sequential case covered; G2: exact, case-sensitive code matching; G3: #8's five candidates closed without an `SA-6`).

**G1 — a concurrent pair of reserves for one order naming disjoint product sets (FS5, L2).** *Engine-forced:* PostgreSQL has no key-range lock (measured: a `FOR UPDATE` read returned 0 rows in 0.989 ms against an uncommitted matching insert). #7 did not protect even the sequential case (its read was scoped to the locked stock rows, `stock-item.repository.ts:56-61`); #8 protected both through `HOLDLOCK` (`EfCoreStockItemRepository.cs:68`). **Recommendation: accept the concurrent-disjoint residual; cover the sequential case as #8 does** (all of the order's reservations read after the stock locks, D6). *Evidence:* the only caller sends one stored payload per `(order_id, command)` row, unchanged across attempts (`specs/order_saga_orchestrator/design.md` L10, L21), so two concurrent requests for one order always name the same products and serialise on the same stock rows; closing the residual needs an order-scoped `pg_advisory_xact_lock` taken first by reserve, release and despatch — a mechanism neither predecessor has, that feature 18 would also have to adopt, for a case no caller produces. *If overruled:* add the advisory lock as the first statement of `lock_for_reserve` and `lock_order_items` (keyed `hashtextextended(order_reference, 0)`), keep stock rows second, and add the disjoint-concurrent integration case; §6.2, §6.3 and tasks D2, D6 change.

**G2 — letter case of company and product codes (FS8, FS14, FS15, L4).** *Engine-forced:* #7's and #8's collations matched `prd-a1` to `PRD-A1`; PostgreSQL 18.6's default collation does not (measured: `'PRD-0001' = 'prd-0001'` is false). **Recommendation: exact, case-sensitive matching everywhere in Fulfillment** — no `lower()`, no `citext`, no upper-casing. *Evidence:* #9's Orders already compares these codes exactly (`services/orders/src/otc_orders/infrastructure/persistence/reference_catalog.py:24-53`, `==` and `in_`), so every code the saga sends Fulfillment is the catalogue's own spelling; normalising in Fulfillment alone would make the two services disagree on what "the same product" is; the difference from #7 and #8 is visible only to an operator typing a differently-cased code into stock list or replenish (feature 25), where it answers "no such item" rather than acting on the wrong one. *If overruled:* normalise case at the edge of both services (an Orders change outside this feature) or adopt a nondeterministic ICU collation by migration; either is its own backlog entry.

**G3 — #8's five promotion candidates** (`requirements.md` §4). **Recommendation: close all five without an `SA-6`.** *Evidence:* #7, #8 and #9 realise each identically (FS2/FS3, FS13, FS5, FS9/FS10, FS21 above); an amendment costs a byte-identical edit in three repositories, every README registry and every `progress/history.md`, and the trilogy has no fourth build for the sentence to protect — the reasoning the maintainer approved for feature 16's G3 on 2026-10-06. *If overruled:* the amendment is `SA-6`, committed on its own before this feature's implementation and applied to #7 and #8 in the same session.

### 16.2 Decided (with the reason, never offered as an option)

The FS reuse and its texts (§2 of `requirements.md`); F3 over rule 6 (#7 and #8 gates); the carrier rule (FS13); `already_reserved` on any status (FS5, #7's human ruling, #8 inherited); `NOT_FOUND` for no carrier and its terminal consequence (#8 §4.6; #9's Orders has #8's classification); `PRECONDITION_FAILED` for a consumed reservation (FS10, and SA-4's despatch-wins row); `CONFLICT` banned (#8 L7; Orders' set is #8's); replenish all-or-nothing and not idempotent (FS14); `stock.check` never errors on an unknown product (FS22); the SA-4 lock = the order's stock rows (both predecessors); stock rows locked before reservations (both); `READ COMMITTED` (forced: `REPEATABLE READ` raises 40001, measured); the per-row lock loop over a single statement (both correct here; the loop's mutation is observable, L3); no idempotent-consumer copy (#8, and nothing consumes, §10.4); the relay-family parity guard **now** (a deviation from both predecessors' deferral, because their reason does not exist in Python, L25); a concurrency bound sized to the pool (#8's reasoning, Python's pool, §8.2); deadlock re-run in-process (the feature's acceptance item 3, FS23); no `TIMEOUT` from a responder (`asyncapi.yaml`'s own description); the order reference never kernel-parsed (FS28, the saga's SO12 decision); no migration (§1).

## 17. Inherited findings → decision or task

| Finding | Disposition in #9 | Where |
|---|---|---|
| #8 id **49** (release fact minted its own id) **and its follow-on** (the property guarded at 1 of 4 sites; #8 feature 18's provenance test asserted `NotEqual`) | **Avoided**: `new_id` required at all four sites, each guarded by **equality** with a test-supplied id and armed separately | FS24; tasks B7; round 2: the two application seams (`stock_reservation.py` reserve and release) are guarded by `test_fs24_the_reserve_uses_the_id_port_…` and `test_fs24_the_release_uses_the_id_port_…`, each armed (M1a, M1b) |
| #8 id **50** (shutdown rethrew a faulted reply) | **Avoided** by porting Orders' drain | FS26; tasks F7 |
| #8 id **51** (hand-retyped payload key lists; three retyped copies of the `RpcError` enum) | **Avoided by construction**: generated models (drift-tested), the generated `Code` enum, and FS21's test imports Orders' terminal set rather than retyping it | L11; tasks F4 |
| #8 id **54** (un-hinted in-transaction re-read correct only under a statement-scoped snapshot) | **Avoided**: `READ COMMITTED` pinned per transaction, guarded and armed by `REPEATABLE READ`; the re-read itself is feature 18's and inherits the guard | L13; tasks D5 |
| #8 id **79** (SA-4's one-lock met by #7 with no guard) | **Split**: release half built and guarded here (FS25, armed); despatch half and the race in both outcomes carried to feature 18 (§15) | tasks I5; round 2: the order of the lock's two reads is guarded by `test_stock_repository.py::test_fs25_the_release_lock_reads_the_orders_reservations_only_after_the_stock_lock_…`, armed (R1) |
| #8 id **95** (cold NATS connection lost a reply) | **Avoided**: the cold shape cannot occur in nats-py; the subscription-propagation analogue is closed by `flush()` and guarded | FS27; tasks F8 |
| #8 id **101** (stock page repeats the product code) | **Assigned to feature 29** `web_app`: Fulfillment has no product name to send (`StockView` has none); the page must join the catalog name as #8's fix did. The leader should attach it to 29's acceptance | — |
| #8 id **46** (stock-check client had no `RpcError` discriminator) | **Already avoided in #9** by feature 15 (`nats_stock_availability.py:72-90`); FS22 kept | — |
| #8 id **63** (paced readiness wait in the test fixture) | **Not applicable**: FS27 makes the host reachable when `start()` returns | §4 |
| #8 feature 17 **D1** (rejected path's outbox row never observed) and **D2** (released `reason` never opened) | **Avoided**: every emitting branch's row is opened field by field against distinct supplied values, each armed by deletion **and** corruption | §13.2; tasks H3 – H7 |
| #8 feature 17 **A6** (a design claimed an instrument read the spec when it did not) | **Avoided**: every "reads `asyncapi.yaml`" claim in this spec names a test that does (`pyyaml`), and its arm substitutes a sibling address | tasks C5, F1 |
| #7 feature 17 rejection (FS5's "any status" untested; the sub-clause mutation survived) | **Avoided**: FS5 tested at unit **and** integration level, both armed by the status filter | tasks E4, H5 |
| #8 G6 (the lock-order arm stayed green) | **Avoided** by choosing the per-row loop whose mutation produces a deterministic deadlock (§13.3) | tasks I3 |
| #8 id **56** (settings → adapter reach; recurred three times in #9's Phase 8) | **Avoided** by writing the reach test with the composition root | tasks G4 |

## 18. Non-goals

No migration and no change to `models.py`, `range_guards.py`, `types.py`, `sequences.py` or `alembic/`. No change under `services/orders/src/`, `packages/` or another service's `src`. No idempotent-consumer copy, no Kafka consumer. No despatch code. No `traceparent`, `x-deadline-ms`, structlog or metrics. No edit to `specs/shared/` beyond column 5 of R30 – R35 and R61's domain half and the derived counts.
