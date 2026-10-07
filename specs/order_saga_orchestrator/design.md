# Design — `order_saga_orchestrator` (feature 16, Python 3.14 / SQLAlchemy 2.1 / asyncpg / aiokafka 0.14 / nats-py 2.16, assessment #9)

> **Where the value of this document is.** The requirements were inherited (`R19` – `R29`, `SO1` – `SO11`); the realisation was not. Everything below is #9's: which asyncio task consumes which topics and how its offset is committed, why aiokafka needs a `seek` that kafkajs and librdkafka did not, how a per-command task replaces #7's RxJS `mergeMap` and #8's channel worker pool, how PostgreSQL claims a command row and why the order row is locked `FOR UPDATE OF orders`, and where `Any` from aiokafka and nats-py is stopped. **§3 (the ported-idiom ledger) and §17 (the gate points) are what a reviewer should read first.**
>
> Authorities: `specs/shared/saga.md` (the whole document; this feature is its elaboration), `specs/shared/requirements.md` §3, `specs/shared/asyncapi.yaml` (the three fact channels, the six saga-command channels, `RpcHeaders`, `RpcError`), and — binding — [`specs/orders_aggregate/design.md`](../orders_aggregate/design.md) §7 (events), §9 (persistence contract: *"feature 16 loads a saga step's order under `SELECT … FOR UPDATE`"*), §10 (domain errors); [`specs/outbox_and_idempotency/design.md`](../outbox_and_idempotency/design.md) §4 (unit of work), §5.6 (the task shape this feature copies), §6 (the canonical idempotent consumer, used **unmodified**), §6.5 (the consumer shell designed for this feature), §7 (the `R16` seam). Citations of the predecessors are to the checkouts on disk: `../order-to-cash-nestjs` (#7) and `../order-to-cash-dotnet` (#8); #7 paths below are relative to `apps/orders/src/` unless stated, #8 paths to the repository root.

## 0. Scope

| In scope | Out of scope (owner) |
|---|---|
| One Kafka consumer task over the three fact topics, group `orders.saga` (§5) | `R16` retry-to-DLQ, `order.saga_failed.v1`, metrics, `traceparent` (27) |
| The step table as data, fourteen facts, four skips (§6) | SA-4's operator-cancel variants and `credit.release` owing rows (41) |
| The transactional unit over the canonical `IdempotentConsumer` (§7) | Terminal `RpcError` classification, `rejected` status (42) |
| The order-row lock for a saga step (§7.2) | The race against an operator cancel (41) |
| Ten fact commands, five dispatch-owed events, the `order_sagas` event handlers on `otc_cqrs` (§7.7) | The responders (17 – 22) |
| The fast path: per-command tasks, in-flight maximum, overflow to the durable path (§8) | `ORD-######` allocation and its A11 proof (15 in #9; #8 had put A11 in its 16) |
| The NATS saga-command adapter over feature 15's connection, six subjects, reply decode, headers (§9.1 – §9.4) | The NATS connection, its settings and the `orders.create` responder (15) |
| `saga_commands` enqueue / claim / mark sent / park, the sweeper task (§9.5 – §9.7) | Any migration (none is needed, §12.4) |
| `saga_ignored_facts` records for `R25` and `SO8` (§7.4) | Projector timeline, notifications (24, 23) |
| Three lifespan-owned tasks registered in feature 15's composition root (§12) | |

**Domain layer: untouched.** `mark_stock_reserved`, `approve_credit`, `confirm`, `mark_despatched`, `mark_invoiced`, `mark_paid`, `complete` and `cancel` (`services/orders/src/otc_orders/domain/order.py:362-472`) are exactly the surface `saga.md` §3 – §4 needs. If a step appears to need a new aggregate method, stop and report: it is a finding about feature 13.

## 1. Dependencies on feature 15 — the shapes assumed, not the lines

Feature 15 (`orders_acceptance`) is being implemented while this spec is written. This design depends on what feature 15's acceptance list (`feature_list.json` id 15, eight items) and its brief (`progress/brief_impl_orders_acceptance.md`) require it to build, and **cites no line of its unfinished files**. Each assumption below is checked as task 0.1; if one is false when feature 16 starts, the implementer stops and reports (the fix is an amendment to this spec, not an improvisation).

| # | Assumed shape | From |
|---|---|---|
| A1 | `services/orders/src/otc_orders/composition.py` builds the Orders `HandlerRegistry`, registers handlers explicitly, and calls `registry.build(<message roots>)` inside the lifespan, so a command with zero or two handlers fails the boot | 15 item 6 |
| A2 | The lifespan owns long-lived tasks (**leader amendment A2', 2026-10-07:** feature 15 placed the lifespan in `otc_orders/main.py`, outside `presentation`, because the `fact-producer-confinement` import-linter contract forbids presentation reaching aiokafka through the composition root — `progress/review_orders_acceptance.md` Q1, the shape #8's `src/Orders/OrdersHost.cs` had; the owned tasks are created by `composition.start_runtime`, and `presentation/app.py` keeps the routes. Read "feature 15's lifespan" in this design as `main.py` + `composition.start_runtime`): it creates each with a shared stop signal, awaits each on shutdown, and a task that ends unexpectedly takes readiness down | 15 items 4, 7 |
| A3 | One nats-py `Client`, connected inside the lifespan's loop, closed after every owned task has been awaited; reachable from the composition root | 15 brief "composition root", item 1 |
| A4 | NATS settings (URL) in `infrastructure/settings.py` under the same pydantic-settings rule (`validation_alias` per field, no `populate_by_name`), and one mechanism that guards every environment read reachable from the composition root (#8 id 56) | 15 item 4 |
| A5 | The stock-check client establishes, against a real NATS server, how nats-py signals *no responders* versus *timeout*, and decodes a reply as `success \| RpcError` with a malformed reply becoming a classified error (#8 ids 46, D1). If its decode helper is private to the stock-check client, task 4.1 moves it into `infrastructure/messaging/rpc_reply.py` **without changing feature 15's behaviour** (feature 15's tests stay green, unedited) so both clients share one decode | 15 items 1, brief Q1 – Q2 |
| A6 | A per-message dispatcher scope type `S` exists; this feature's handlers need the built `Dispatcher` reachable from it (`scope.dispatcher`) to publish post-commit events, and the attribute is added if absent | 15 item 6 |
| A7 | Integration fixtures `nats_server` / `nats_client` in `services/orders/tests/integration/conftest.py`, and a stand-in `fulfillment.stock.check` responder | 15 brief |

## 2. Layout

```
services/orders/src/otc_orders/
  application/
    ports/
      order_repository.py        + get_by_id_for_update(order_id) -> Order | None            (§7.2)
      unit_of_work.py            OrdersTransaction + .saga_commands, .ignored_facts          (§7.3)
      saga_commands.py           SagaCommands (six typed calls) + SagaCommandError family     (§9.2)
      saga_command_store.py      SagaCommandQueue (enqueue, in-transaction); SagaCommandLedger (claim / mark / park)  (§9.6)
      saga_ignored_facts.py      SagaIgnoredFactRecorder, IgnoredFactMarker                   (§7.4)
      fact_stream.py             FactMessage, FactStreamSubscriber                            (§5.1)
      saga_signal.py             SagaCommandRef, SagaCommandSignal (non-blocking)             (§8)
    saga/
      command_kind.py            SagaCommandKind (six members, wire tokens)                   (§9.1)
      fact.py                    SagaFact (the application DTO of one consumed fact)          (§5.5)
      step_table.py              Skip | Advance | Cancel; SAGA_STEPS; variants_for; step_for_status; map_release_reason; release_steps_from  (§6)
      command_payloads.py        build_command_payload(kind, order, fact) -> generated request model  (§9.4)
      fact_handler.py            SagaFactHandler.handle(fact) -> SagaFactResult               (§7.1)
      fact_commands.py           ten Handle<Fact>FactCommand(Command[SagaFactResult]); FACT_COMMANDS map  (§7.7)
      fact_command_handlers.py   one generic handler class, registered ten times; post-commit publish  (§7.7)
      dispatch_events.py         five dispatch-owed events                                     (§7.7)
      order_sagas.py             five EventHandler classes: event -> signal(SagaCommandRef)   (§7.7)
  infrastructure/
    settings.py                  + SagaSettings (with the SO16 lease validation)               (§12.3)
    persistence/order_repository.py   + get_by_id_for_update: FOR UPDATE OF orders            (§7.2)
    persistence/unit_of_work.py       transaction exposes .saga_commands, .ignored_facts      (§7.3)
    messaging/
      fact_topics.py             the three consumed topics                                     (§5.2)
      kafka_fact_subscriber.py   KafkaFactSubscriber — the ONLY module importing AIOKafkaConsumer  (§5.1 – §5.3)
      saga_subjects.py           the six saga-command subjects                                 (§9.1)
      nats_saga_commands.py      NatsSagaCommandsAdapter                                       (§9.2 – §9.3)
      rpc_reply.py               shared success | RpcError decode (only if A5 requires the move)
    saga/
      command_queue.py           SqlAlchemySagaCommandQueue (enqueue, ON CONFLICT DO NOTHING)  (§7.5)
      command_ledger.py          SqlAlchemySagaCommandLedger (try_claim, claim_due, mark_sent, park)  (§9.6)
      ignored_facts.py           SqlAlchemySagaIgnoredFactRecorder                             (§7.4)
      backoff.py                 in-line and park backoff, pure int arithmetic                 (§9.5)
      command_dispatcher.py      SagaCommandDispatcher.dispatch / dispatch_claimed             (§9.5)
      fast_path.py               SagaFastPath: SagaCommandSignal + run(stop)                    (§8)
      sweeper.py                 SagaCommandSweeper.run_once()                                 (§9.7)
      sweeper_task.py            SagaCommandSweeperTask.run(stop)                              (§9.7)
  presentation/
    saga_facts_consumer.py       SagaFactsConsumerTask.run(stop): parse, route, dispatcher.send  (§5.5)
  composition.py                 (feature 15's) + three owned tasks in start_runtime, registrations and wiring (§12.1, §12.2; A2')
  main.py                        (feature 15's lifespan; changed only if §12.1's shutdown order needs it)
```

**Why `SagaCommandQueue` and `SagaCommandLedger` are two ports.** The enqueue happens inside the fact's transaction and must be reachable only through the transaction object, as the repository is (outbox design L1); claim, mark and park are single statements outside any fact transaction, each in its own short session. One port with both would let a caller enqueue outside the fact's transaction, which is exactly what SO3's arming row (task 7.6) mutates.

**Why the consumer is split port-and-adapter.** As in #8 (#8 `design.md` §2): the presentation task stays testable without a broker, the offset contract (SO9) has one implementation to prove, and aiokafka's consumer surface is confined to one module (§13.1).

## 3. The ported-idiom ledger

*#7 relied on X; #8 supplied it with Y; in #9 it is supplied by Z.* Every "#7" and "#8" cell is read from the checkouts with a file and line. **Guard** names the `tasks.md` task; every guard on a property #9 hand-builds is an `[ARM]` task. A row whose behaviour #7 and #8 decided and whose mechanism only is Python's is **decided**, not a gate point (§17 states the rule).

| # | Idiom | #7 relied on | #8 supplied it with | #9 supplies it with | Guard |
|---|---|---|---|---|---|
| L1 | The offset commits only after the handler succeeded (SO9) | kafkajs does not commit a rejected `eachMessage`; Nest awaits the handler with no `try` (`main.ts:95-104`; `presentation/saga-facts.controller.ts:5-9`) | `EnableAutoOffsetStore = false`, `StoreOffset` after the handler (`src/Orders/Infrastructure/Messaging/Consumers/KafkaFactStreamSubscriber.cs:96, 134`) | `AIOKafkaConsumer(enable_auto_commit=False)` (aiokafka's default is `True`, `aiokafka/consumer/consumer.py:247`) and `await consumer.commit({tp: record.offset + 1})` only after the handler returns (§5.3) | 3.9, 3.10 |
| L2 | A failed record is not skipped by a later record of its partition | kafkajs re-fetches from the last resolved offset after a rejection (`main.ts:100-103`) | The throw exits `ConsumeAsync`; re-entry builds a new consumer that resumes from the committed offset (#8 `design.md` §3.3 item 5; `src/Orders/Presentation/SagaFactsConsumer.cs:51-62`) | **Not free:** aiokafka's fetch position is already past a record once it is returned, so after a failure the next fetch returns the *next* record, whose success would commit past the failed one. On failure: no commit, `consumer.seek(tp, record.offset)` (`consumer.py:755`), paced back-off, continue; and `getmany(max_records=1)` so no second record of that partition is in hand (§5.3) | 3.10 |
| L3 | Per-order ordering: one record at a time | `run: { partitionsConsumedConcurrently: 1 }` (`main.ts:112`) | One consume loop, serial across partitions (#8 `design.md` §3.4) | One task; each record's handler is awaited before the next fetch; no `create_task` per record | 3.6 |
| L4 | Broker group identity equals the dedup identity | `groupId: 'orders.saga'` (`main.ts:110`), but Nest appended `-server`, so the claim was false (#7 `progress/history.md` line 832, D5) | `GroupId = "orders.saga"` (`KafkaFactStreamSubscriber.cs:130`) | `group_id=ConsumerName.ORDERS_SAGA.value`, used verbatim by aiokafka; `client_id="otc-orders-saga"` (both predecessors' value), distinct from the relay's `otc-orders` | 3.11 |
| L5 | A first boot reads from the beginning (SO1) | `subscribe: { fromBeginning: true }` (`main.ts:111`) | `AutoOffsetReset.Earliest` (`KafkaFactStreamSubscriber.cs:132`) | `auto_offset_reset="earliest"` (default `"latest"`, `consumer.py:246`) | 3.4, 3.12 |
| L6 | The RPC issue is off the consume loop and concurrent across commands (SO10, SO13) | `@nestjs/cqrs` 11.0.3 `registerSaga` runs each command as `mergeMap(command => defer(() => this.commandBus.execute(command)))` (`node_modules/.pnpm/@nestjs+cqrs@11.0.3…/node_modules/@nestjs/cqrs/dist/event-bus.js:196`): `publish` returns before any dispatch finishes, and every dispatch runs concurrently, unbounded (`application/sagas/order.sagas.ts:86-168`; `application/commands/saga-dispatch.handlers.ts:22-23`) | A channel (capacity 1 024, `DropWrite`, `src/Orders/Infrastructure/Saga/ChannelSagaCommandSignal.cs:9`) drained by `DegreeOfParallelism` (8) loops (`SagaCommandDispatchWorker.cs:90`): off the loop, but bounded, so N stuck dispatches stall the N+1th (#8 ids 80, 88) | `otc_cqrs.Dispatcher.publish` awaits each handler in turn (`packages/cqrs/src/otc_cqrs/dispatcher.py:180-190`), so a literal port blocks. The `order_sagas` handlers call `SagaFastPath.signal`, which spawns **one task per command** in a `TaskGroup` owned by the fast-path task and returns at once; above an in-flight maximum the signal is dropped to the durable path, never queued (§8, gate G1) | 6.2, 6.3, 6.4, 13.4 |
| L7 | The fact's execution (trace) context reaches the dispatch | The `mergeMap` subscription runs synchronously inside `publish`, which `saga-facts.controller.ts:196-201` wraps in `otelContext.with(spanContext, …)`; Node's async context follows the promise chain | Lost across the channel hop; fixed by capturing `Activity.Current?.Id` on `SagaCommandRef` (`src/Orders/Application/Ports/ISagaCommandSignal.cs:30`; `progress/impl_saga_trace_context_fast_path_fix.md`) | `asyncio.Task` copies the **creating** task's `contextvars` context at creation (CPython `asyncio.Task(coro, context=None)`), and `signal` creates the task inside the fact handling, so the context arrives with no capture; OpenTelemetry's Python context is `contextvars`-based, which is what feature 27's `traceparent` will ride on. A queue drained by worker tasks would lose it, which is #8's defect in Python form (§11) | 6.5 |
| L8 | One dispatch's exception does not stop the others | `resilient()` resubscribes a branch on error (`order.sagas.ts:64-73`) | The worker logs a failed item and continues (#8 `tasks.md` H4) | A `TaskGroup` **cancels every sibling** when a child raises: each child body catches `Exception`, logs it with `correlationId` and `command`, and returns; same in the sweeper's batch group (§8.3, §9.7) | 6.6, 8.11 |
| L9 | Shutdown cancellation is not swallowed | n/a (no cancellation in the dispatcher) | `catch … when` excluding `OperationCanceledException` (`SagaFactsConsumer.cs:47`) | `asyncio.CancelledError` is a `BaseException`: only `except Exception` appears in this feature, never `except BaseException` or a bare `except:`; a cancelled dispatch leaves its row leased and the sweeper re-issues it after the lease | 6.7 |
| L10 | Enqueueing a command already owed is not an error | Initially a unique-key violation that poisoned the partition (#7 `progress/history.md` line 832, D1), then an idempotent `enqueue` (`application/saga-fact-handler.ts:191-207`) | Duplicate key 2601 / 2627 caught, entry detached (#8 `design.md` §6.3) | **The engine differs:** any error aborts a PostgreSQL transaction, so a caught violation would leave nothing usable. `pg_insert(SagaCommand).on_conflict_do_nothing(index_elements=["order_id", "command"]).returning(SagaCommand.id)`: no row back means already owed (outbox design L15's shape) | 7.4 |
| L11 | A row being dispatched is excluded from a concurrent claim (SO11) | `FOR UPDATE SKIP LOCKED` inside a short transaction released before the dispatch, and `dispatch()` re-reads the row with no claim (`infrastructure/saga/drizzle-saga-command-store.ts:110-129`; `infrastructure/saga/saga-command-dispatcher.ts:140-144`): no exclusion across the RPC | A lease in `next_attempt_at` set by a conditional `UPDATE` (`src/Orders/Infrastructure/Saga/EfCoreSagaCommandStore.cs:81, 124`; #8 `design.md` §6.3) | #8's lease, as one PostgreSQL statement per path: `UPDATE … WHERE … RETURNING` for the fast path; `UPDATE … WHERE id IN (SELECT … FOR UPDATE SKIP LOCKED LIMIT n) RETURNING` for the sweeper, at a pinned `READ COMMITTED` (§9.6) | 8.2, 8.3 |
| L12 | The sweeper issues the rows it claimed | No self-exclusion problem: no lease (`saga-command-sweeper.service.ts:87-95`) | First build: the sweeper's `DispatchAsync` re-claimed its own leased row and silently did nothing — the feature's only production defect (#8 `progress/history.md` line 840); fixed by `DispatchClaimedAsync` (`src/Orders/Infrastructure/Saga/SagaCommandDispatcher.cs:24-25`). Its batch was sequential, so later rows could outlive a 60 s lease | `dispatch_claimed(row)` from the sweeper, never `dispatch(order_id, kind)`; the batch is dispatched concurrently so every row finishes inside one lease; `SagaSettings` refuses a lease that does not exceed twice the worst-case dispatch (SO16, §9.7) | 8.7, 8.8, 9.2 |
| L13 | Instants for leases and back-off come from the clock port | `Date.now()` in the dispatcher (`saga-command-dispatcher.ts:210`; #7 D2) | An `IClock`-style abstraction (#8 `design.md` §6.2) | The existing `Clock` port (`application/ports/clock.py`) for `next_attempt_at`, the lease, `created_at`, `recorded_at`; never `datetime.now()` in this feature's code | 8.4 |
| L14 | Park back-off arithmetic | `Math.min(30_000 * 2 ** Math.max(0, parkCycles - 1), cap)`, JS numbers saturating to `Infinity` (`saga-command-dispatcher.ts:207-210`) | `Math.Min(30_000d * Math.Pow(2, parkCycles), cap)`, `double` (`EfCoreSagaCommandStore.cs:206-207`) | **Python's `int` is exact and unbounded:** `2 ** n` never saturates, it grows. `park_cycles = total_attempts // max_attempts` (floor division; `/` would make every later value a `float`), the exponent clamped to `≤ 31` **before** `**`, the result an `int` of milliseconds (§9.5) | 8.1 |
| L15 | In-line back-off | `backoffBaseMs * 2 ** (attempt - 1)` (`saga-command-dispatcher.ts:202`) | `BackoffMs * (1 << (attempt - 1))` (`SagaCommandDispatcher.cs:147`) | Same formula on `int`; `SAGA_COMMAND_MAX_ATTEMPTS` validated to `1 … 10` at boot | 8.1, 9.2 |
| L16 | *No responders* versus *timeout* are two errors | `ErrorCode.NoResponders` / `ErrorCode.Timeout` (`infrastructure/messaging/nats-saga-commands.adapter.ts:139-147`) | `NatsNoRespondersException` / `NatsNoReplyException` (`src/Orders/Infrastructure/Messaging/NatsSagaCommandsAdapter.cs:112, 118`) | `nats.errors.NoRespondersError` / `nats.errors.TimeoutError`. **Trap:** `nats.errors.TimeoutError` subclasses `asyncio.TimeoutError` (`nats/errors.py:27`), which is the builtin `TimeoutError`, so a bare `except TimeoutError` would also swallow any outer `asyncio.timeout` deadline as a NATS timeout: the adapter catches the two nats classes by name. Which nats-py raises when is feature 15's measurement against a real server (A5) | 4.3 |
| L17 | A malformed reply is a classified error (SO15) | `replyCodec.decode` inside its own `try`, rethrown as `SagaCommandTransportError` (`nats-saga-commands.adapter.ts:170-178`) | Missing until #8 id 110 (`NatsSagaCommandsAdapter.cs:131-143`, then a `catch (JsonException)` at `:148`) | One `except ValueError` around the whole decode: `json.JSONDecodeError` and `pydantic.ValidationError` both subclass `ValueError`, and a non-object JSON value is refused explicitly (§9.3) | 4.4, 4.6 |
| L18 | An `RpcError` body is told apart before typed decoding | An object with a string `code` (`nats-saga-commands.adapter.ts:65-67`) | `RpcJson.IsErrorBody` (`src/Orders/Infrastructure/Messaging/Rpc/RpcJson.cs:28-35`, cited by #8 id 110) | Parse once; a `dict` with a `str` `"code"` is an `RpcError` candidate validated against the generated `RpcError`; a code outside the twelve fails open to the retryable side, as both predecessors behave at run time (#8 `progress/history.md` line 892) | 4.4 |
| L19 | A fresh header container per request | `natsHeaders()` per call (`nats-saga-commands.adapter.ts:55-62`) | `new NatsHeaders` per call (`NatsSagaCommandsAdapter.cs:97`), guarded only after #8 id 48 | A new `dict[str, str]` literal per call. Concurrent per-command tasks share one adapter, so a shared mutated dict would race across an `await` — the hazard is live here, not latent as in #8 | 4.5 |
| L20 | One request identity per command, reused across retries | `requestId: row.id` (`saga-command-dispatcher.ts:151`) | `x-request-id` added in #8's feature 17 (#8 `progress/history.md`, fulfillment_stock entry) | `x-request-id = str(saga_commands.id)` and `x-correlation-id = str(order_id)` on every attempt, on both paths (SO14) | 5.4 |
| L21 | The stored request is the bytes sent | MySQL `json('payload')` normalises key order (`infrastructure/persistence/schema/saga-commands.schema.ts:52`) | `nvarchar(max)` preserves it (#8 `design.md` §6.3) | `saga_commands.payload` is `json` through `RawJson` (`models.py:197`; `persistence/types.py`): written with `to_wire_json(request_model)`, read back as text, sent as `text.encode("utf-8")`, never re-serialised | 7.5 |
| L22 | A consumed fact's instant is UTC milliseconds | `new Date(fact.occurredAt)` is an epoch, the offset is gone (`application/saga-steps.ts:48-53`) | `envelope.OccurredAt` passed as a `DateTimeOffset` with its offset (`SagaFactsConsumer.cs:178`) | pydantic's `AwareDatetime` keeps the offset and microseconds, and the domain refuses a non-UTC instant (`domain/instants.py:12-14`), so a valid `…+02:00` fact would raise forever. `SagaFact.occurred_at = wire_instant(envelope.occurred_at)` (UTC, truncated to whole ms, `otc_contracts/wire.py:62`) at the decode boundary (§5.6) | 3.13 |
| L23 | What is acknowledged unprocessed and what is redelivered | `parseFactEnvelope` checks presence of the seven fields; a failure is logged and acknowledged; payloads are cast, never validated (`saga-facts.controller.ts:59-82, 148-162`) | Envelope deserialised with typed ids and validated, a failure logged and acknowledged (`SagaFactsConsumer.cs:76-95`); a poison payload is retried, which #8's R16 test uses (`tests/Orders.IntegrationTests/SagaDeadLetterTests.cs:51-58`) | Envelope (`Envelope[dict[str, Any]]`) failure → log and acknowledge; per-fact payload validation (`FACT_MODELS[event_type]`) and `UniqueId` construction happen **inside** the processing unit, so their failure is a processing failure (redelivered here, dead-lettered by feature 27). This keeps feature 27's `R16` vehicle available (§5.5) | 3.7, 3.8 |
| L24 | A saga step's order load serialises against another writer of the same order (SO17) | A plain read (`infrastructure/persistence/order.repository.ts:32-34`, `findOne(…, forUpdate = false)`) under MySQL `REPEATABLE READ` | `UPDLOCK, ROWLOCK` on every `GetByIdAsync`, added for #8 id 62 (`src/Orders/Infrastructure/Persistence/EfCoreOrderRepository.cs:71-108`) | `select(OrderRow, Retailer, Company, Currency)….with_for_update(of=OrderRow)` → `FOR UPDATE OF orders`. **The engine differs:** a bare `FOR UPDATE` on the four-table join locks the joined retailer, company and currency rows too, serialising every saga step of one retailer (§7.2) | 7.1, 7.2 |
| L25 | A fact's reference never blocks its routing (SO12) | Lookup by `UniqueId.from(envelope.correlationId)` (`application/saga-fact-handler.ts:93-94`); the payload's `orderReference` is never parsed | Lookup by `CorrelationId` (`Guid`) | Lookup by `UniqueId(envelope.correlation_id)`; the payload's `order_reference` is a `str` checked by the wire pattern only; no `OrderNumber` is built from inbound data on the saga path, and every command's `orderReference` comes from the loaded aggregate (§5.5, §9.4) | 3.14, 10.4 |
| L26 | Self-produced facts are skipped without I/O (SO2) | Three skips (`application/saga-steps.ts:302-304`) | Four skips (#8 `design.md` §4.1) | Four: `FACT_MODELS` holds fourteen (`otc_contracts/facts.py:52-67`) | 2.3, 3.5 |
| L27 | `Any` from untyped clients | TypeScript types | C# types | aiokafka has no stubs (`[[tool.mypy.overrides]]` `aiokafka.*`, the only override); nats-py ships `py.typed` but `request(headers: Optional[Dict[str, Any]])` (`nats/aio/client.py:1119-1126`). `kafka_fact_subscriber.py` and `nats_saga_commands.py` type the calls they make through private `Protocol`s and return only `bytes`, our dataclasses or our errors; `mypy --strict` (`warn_return_any`) is the guard | 13.1 |
| L28 | Event-loop affinity of clients and engine | n/a (one Node loop) | n/a (thread pool) | `AIOKafkaConsumer`, the nats-py client and the asyncpg pool bind to the loop that creates them: `KafkaFactSubscriber.__init__` builds no aiokafka object (it is built and started inside `run`), the adapter receives feature 15's connected client and does no I/O at construction, and test fixtures create both in the test's own loop (§14.2) | 3.3 |
| L29 | Heartbeats survive a slow handler | kafkajs heartbeats between messages; budget sized under `sessionTimeout: 30000` (`main.ts:110`) | librdkafka heartbeats on its own thread; `max.poll.interval.ms` 300 000 binds (#8 `design.md` §3.2) | aiokafka heartbeats from a coroutine **on the same loop** (`session_timeout_ms=10000`, `max_poll_interval_ms=300000`, `consumer.py:252-254`): a synchronous call in a handler starves them. No sync driver exists in this service; the RPC is off the consume path (SO10), so a record's time is database time only | 3.6 |
| L30 | The sweeper loop never overlaps itself | A self-scheduling `setTimeout` chain (`infrastructure/saga/saga-command-sweeper.service.ts:78-121`) | `PeriodicTimer` (`SagaCommandSweeperBackgroundService.cs:26`) | The outbox relay task's shape (outbox design §5.6): `await sweeper.run_once()`, then `asyncio.wait_for(stop.wait(), timeout=interval)` | 8.9 |
| L31 | Identifier comparison is case-insensitive | `char(36)` strings; #7's `UniqueId.from` (`packages/shared-kernel/src/domain/unique-id.ts:6-7, 32`, per `progress/review_shared_kernel.md` Q1) | `Guid` values | `uuid.UUID` values on both sides of every comparison (pydantic parses the wire string; asyncpg returns `uuid.UUID`), so letter case cannot make an order unknown | 3.14 |

**Python porting questions answered** (CLAUDE.md): integer division — L14, L15 (`//` only; `/ 1000` appears once, at the settings boundary, as for the relay); JSON serialisation — L17, L18, L21 (one serializer, `to_wire_json` / `from_wire_json`, no `json.dumps` defaults, no `isoformat()`); event-loop affinity — L28, L29; task cancellation and exception propagation — L8, L9, §8.3, §12.1; typing gaps — L27.

## 4. Port the guards too

#8's tests of this mechanism, enumerated by content (`grep -rl "SagaStepTable\|SagaFactHandler\|SagaCommandDispatcher\|SagaCommandSweeper\|NatsSagaCommandsAdapter\|ChannelSagaCommandSignal\|SagaCommandDispatchWorker\|KafkaFactStreamSubscriber\|SagaFactsConsumer\|EfCoreSagaCommandStore\|OrderSagas\b" ../order-to-cash-dotnet/tests --include=*.cs`, 51 files), classified:

| #8 test | #9 |
|---|---|
| `Orders.UnitTests/SagaStepTableTests.cs` (fact × status, SO2, SO7, R21/R23/R26/R27) | **Ported** (`unit/saga/test_step_table.py`), fourteen facts × nine statuses |
| `SagaFactHandlerTests.cs` | **Ported** with fakes, plus the lock call (`get_by_id_for_update`, never `get_by_id`) |
| `SagaFactCommandHandlerTests.cs` | **Ported**: publish only on processed-with-enqueue |
| `OrderSagasTests.cs` | **Ported**: five events × five kinds, a swap must fail |
| `SagaCommandDispatcherTests.cs` | **Ported**: SO4 schedule, SO6, park, zero-row claim |
| `SagaCommandDispatchWorkerTests.cs` (SO10, id 80's head-of-line, id 90's floor) | **Ported** onto `SagaFastPath` (`unit/saga/test_fast_path.py`); the parallelism-floor case becomes the in-flight-maximum validation |
| `OrdersSagaDispatchValidationTests.cs` (id 90) | **Ported** as `SagaSettings` validation cases (`unit/saga/test_saga_settings.py`) |
| `SagaCommandSweeperLoopTests.cs` | **Ported** (relay-task shape) |
| `SagaFactTopicsTests.cs`, `SagaRpcSubjectsTests.cs` | **Ported**: constants equal the channel addresses read from `asyncapi.yaml` (pyyaml, as `ORDERS_FACTS_TOPIC`'s guard) |
| `SagaCommandPayloadTests.cs`, `AsyncApiSchema.PayloadRecords.cs` (id 51) | **Not ported, avoided by construction:** #9's request and reply models are generated from `asyncapi.yaml` and drift-tested (`packages/contracts/tests/test_generation_drift.py::test_the_committed_generated_files_equal_a_fresh_generation`); there is no hand-retyped key list to drift. What is ported is the builder's field mapping (`unit/saga/test_command_payloads.py`) |
| `NatsSagaCommandsAdapterTests.cs` (+ id 48 headers case) | **Ported**, plus SO15's per-defect cases |
| `KafkaFactStreamSubscriberConfigTests.cs` (earliest, group, client, store-after) | **Ported** onto the keyword arguments the subscriber passes (`unit/saga/test_kafka_fact_subscriber.py`) |
| `SagaFactsConsumerTests.cs` (routing, SO2, malformed, unknown type) | **Ported** |
| `Orders.IntegrationTests/SagaHappyPathTests`, `SagaPreconditionTests`, `SagaCompensationStockRejectedTests`, `SagaCompensationCreditRejectedTests`, `SagaCommandRetryTests`, `SagaCommandStoreTests`, `SagaConsumptionTests` | **Ported** (`integration/saga/…`), with #8 D1 – D4's corrections built in (§14.3) |
| `SagaCommandDispatchConcurrencyIntegrationTests.cs` (id 89) | **Ported** as SO13's integration case |
| `NatsSagaCommandsAdapterReplyDecodeGuardTests.cs` (id 110) | **Ported** as SO15's integration case, six subjects |
| `OperatorCancelRowLockConcurrencyTests.cs` | **Half ported:** the saga-side lock (two saga transactions on one order) is SO17 here; the operator-cancel side is feature 41's |
| `OperatorCancelRacesSagaForwardProgressTests.cs`, `OrdersCancelAcceptanceTests.cs`, `CancelOrderCommandHandlerTests.cs` | Not applicable: feature 41 |
| `SagaDeadLetterTests`, `SagaFirstParkDeadLetterTests`, `SagaCommandDeadLetterTests`, `SagaCommandDispatcherFirstParkTests`, `SagaFirstParkDeadLetterHandlerTests`, `FactRetryDispatcherTests`, `LogCorrelationTests`, `RealInfraMetricsProvenanceTests`, `OrderSagaFailureTests` | Not applicable: feature 27 |
| `Architecture.Tests/FactPublisherConfinementTests.cs` (+ #8's consumer rule, `design.md` §10) | **Ported** as `tests/architecture/test_kafka_client_confinement.py` (§13.1) |
| `Architecture.Tests/KafkaGroupHostWrappingTests.cs` (id 74: hosts that join a group must clear it) | **Ported in spirit:** one harness fixture is the only way saga integration tests start the consumer, and it clears the group at teardown (§14.3); a census test over `integration/saga/*.py` asserts no module constructs the consumer task directly |
| `OrderNumberAllocatorTests.cs` (#8's A11 debt) | Not applicable here: #9 placed A11 in feature 15 (its brief Q5) |
| Projector / Notifications / Gateway / Billing / Fulfillment hits | Not applicable: features 17 – 31 |

## 5. Consumption — how facts reach the orchestrator

### 5.1 One task for the Kafka transport, over a port

```python
@dataclass(frozen=True, slots=True)
class FactMessage:                      # application/ports/fact_stream.py
    topic: str; partition: int; offset: int; key: bytes | None; value: bytes
    headers: tuple[tuple[str, bytes], ...]          # kept for feature 27's traceparent

class FactStreamSubscriber(Protocol):
    async def run(self, handler: Callable[[FactMessage], Awaitable[None]], stop: asyncio.Event) -> None:
        """Deliver records one at a time; the handler runs to completion BEFORE the record's
        offset is committed; a handler that raises leaves the offset uncommitted and the record
        is delivered again (SO9)."""
```

`SagaFactsConsumerTask` (presentation) is the one Kafka-transport task in Orders: `run(stop)` calls `subscriber.run(self._handle, stop)`. It depends on the port, never on aiokafka (the `fact-producer-confinement` contract already forbids aiokafka in `presentation`). `KafkaFactSubscriber` is the one implementation and the one module that imports `AIOKafkaConsumer` (§13.1).

### 5.2 Configuration, and the budget re-derived for this client

```python
AIOKafkaConsumer(
    *SAGA_FACT_TOPICS,                         # otc.orders.facts.v1, otc.fulfillment.facts.v1, otc.billing.facts.v1
    bootstrap_servers=kafka.brokers,           # KAFKA_BROKERS (feature 14's setting)
    group_id=ConsumerName.ORDERS_SAGA.value,   # "orders.saga", verbatim (L4)
    client_id="otc-orders-saga",               # #7 main.ts:109, #8 the same
    enable_auto_commit=False,                  # SO9 (L1)
    auto_offset_reset="earliest",              # SO1 (L5)
)
```

- The three topic constants live in `infrastructure/messaging/fact_topics.py`, each equal to its channel's `address` in `asyncapi.yaml` (lines 93, 125, 152), read by test (task 2.5). `ORDERS_FACTS_TOPIC` already exists (`infrastructure/outbox/topic.py`) and is reused, not retyped.
- Topics are per service, not per fact, so routing is on `envelope.eventType`, never on the topic.
- **Budget.** #7 sized 3 × 5 s + 0.5 s + 1 s ≈ 16.5 s under kafkajs's 30 s session timeout; #8 re-derived that the binding constraint for librdkafka is `max.poll.interval.ms` (300 s). For aiokafka the binding constraint is the same 300 s (`consumer.py:252`), and heartbeats need the loop to be free (L29). Because the RPC runs in other tasks (§8), a record's time on the consume path is one database transaction. **The numbers stay #7's and #8's** (5 000 / 3 / 500) so the benchmark compares languages, not tuning; only the justification changes, and `command_dispatcher.py`'s module docstring records it.

### 5.3 The offset contract (SO9) — the aiokafka-specific part

```
consumer = AIOKafkaConsumer(...); await consumer.start()            # inside run(): loop affinity (L28)
try:
    while not stop.is_set():
        batch = await consumer.getmany(timeout_ms=poll_ms, max_records=1)   # bounded poll; stop observed each cycle
        for tp, records in batch.items():
            record = records[0]
            try:
                await handler(to_fact_message(record))
            except Exception:
                log ERROR (topic, partition, offset, exc_info)
                consumer.seek(tp, record.offset)                    # L2: never skip the failed record
                await pace(tp, record.offset)                       # 1 s, doubling per consecutive failure of that offset, cap 30 s
                continue
            try:
                await consumer.commit({tp: record.offset + 1})      # L1: only after success
            except CommitFailedError:                               # a rebalance revoked tp: the next owner redelivers; harmless (§6.3 layers)
                log WARNING
finally:
    await consumer.stop()
```

- **Why `max_records=1`.** With a larger batch, a failure at record *k* of a partition would leave records *k+1…* of that partition already in hand; processing them before the `seek` takes effect would reorder one order's facts. One record per poll is #7's `partitionsConsumedConcurrently: 1` and #8's single loop, expressed in aiokafka. The throughput cost is one fetch round-trip per record from the prefetch buffer (aiokafka prefetches; `getmany` with `max_records=1` drains it one record at a time, no extra network round-trip).
- **Pacing.** Until feature 27 a poisoned record holds its partition and is retried forever, as in #7 (kafkajs crash-loop on the offset, #7 D1) and #8 (re-enter after 2 s, `SagaFactsConsumer.cs:62`). The retry is paced: an injected `sleep` with 1 s doubling to a 30 s cap for consecutive failures of the same (`tp`, offset), reset on success. The unit test proves the pacing by a change of kind (the recorded sleep durations), not by timing (CLAUDE.md, retry loops).
- **What the handler is.** `SagaFactsConsumerTask._handle(message)`: §5.5's routing, then `await dispatcher.send(command, scope)`, whose return means the transaction committed (§7.1). The per-message `AsyncSession` is opened and closed inside `IdempotentConsumer.run_once` (outbox design §6.5), before the commit of the offset.
- **This is the one behaviour whose failure mode is silent loss**, so it is proven three ways (tasks 3.9, 3.10, 3.12): the committed offset read from the broker before and after; a restarted consumer redelivering the failed record (a genuine Kafka redelivery, not an in-process retry — #8 id 94); and a failing record followed by a succeeding one on the same partition, whose committed offset must never pass the failed record.

### 5.4 Ordering

The three topics have 6 partitions keyed by `correlationId` (feature 14, R15). One task, one record at a time, the handler awaited before the next poll: per-order order within one producing context is preserved across all partitions. Nothing is assumed across contexts: every step checks its precondition (saga.md §6 layer 2), and §6.3 argues why a fact can never be early on first delivery.

### 5.5 Envelope, routing, and where a payload failure lands

`SagaFactsConsumerTask._handle(message)`:

| Case, in this order | Behaviour | Requirement |
|---|---|---|
| The value is not JSON, not an object, or fails `Envelope[dict[str, Any]]` (`otc_contracts/envelope.py`: seven fields, UUID ids, `eventType` pattern, aware `occurredAt`) | ERROR log with topic / partition / offset and the value's length, then **return normally** (the offset commits). It cannot be deduplicated (no trustworthy `eventId`) or parked (no `correlationId`); redelivery cannot fix a producer bug | L23 |
| `eventType` is one of the four self-produced facts | Return with no dispatch, no transaction, no dedup row, no load | SO2 |
| `eventType` is not in `FACT_MODELS` | WARNING log (distinct from malformed), return | — |
| Otherwise | Build `Handle<Fact>FactCommand(envelope=…, topic=…)` from `FACT_COMMANDS[event_type]` and `await dispatcher.send(command, scope)` | §7.7 |

Inside the processing unit (the fact command handler, before `run_once`): the envelope is re-validated against `FACT_MODELS[event_type]` (the generated per-fact model with its typed payload), and `SagaFact` is built — `event_id=UniqueId(…)`, `correlation_id=UniqueId(…)` (refuses the nil UUID, `unique_id.py:22-24`), `occurred_at=wire_instant(…)`, `payload=<typed payload model>`. A failure there **raises**: no commit, paced redelivery (§5.3) here, dead-letter after feature 27. So a fact with a well-formed envelope and a poisoned payload or a nil `correlationId` is exactly the vehicle feature 27's `R16` case needs (#8 used the same shape, L23).

**SO12.** `StockReservedPayload.order_reference` and its siblings are `str` fields with the wire pattern `^ORD-[0-9]{6,}$` (`otc_contracts/generated/asyncapi.py:139-170`), which admits `ORD-000000`. Nothing on the saga path builds an `OrderNumber` (or any `BusinessReference`) from inbound data: the lookup is by `correlation_id`, and every outbound `orderReference` is `order.order_reference.value` from the loaded aggregate. Task 10.4 guards both halves: the behaviour (SO8 with #7's fixture, and a known order whose fact carries `ORD-000000`) and the structure (no `OrderNumber`/`BusinessReference` name is imported by any module under `application/saga/`, `presentation/saga_facts_consumer.py` or `infrastructure/saga/`, an AST scan with a sentinel).

### 5.6 Inbound instants

`occurred_at` of a consumed fact becomes the `occurred_at` of the transition and of any fact the step makes the aggregate raise (#7 `saga-steps.ts:48-53`, #8 `design.md` §4.1: *the fact's, never the clock's*). `asyncapi.yaml` describes `Instant` as UTC but its schema is `format: date-time` (lines 1890 – 1895), which admits an offset; the domain refuses a non-UTC instant (`domain/instants.py:12-14`). `wire_instant` converts to UTC and truncates to whole milliseconds, the same function the outbox uses (outbox design L14), so a `…T12:15:04.120456+02:00` fact advances the order and stamps `…T10:15:04.120Z` (task 3.13).

## 6. The step table as data

### 6.1 The table

`application/saga/step_table.py` — pure data and pure functions; it imports the domain, `otc_shared_kernel` and the generated payload models only (no SQLAlchemy, aiokafka, nats, FastAPI).

```python
@dataclass(frozen=True, slots=True)
class Skip: ...
@dataclass(frozen=True, slots=True, kw_only=True)
class Advance:
    precondition: OrderStatus
    apply: Callable[[Order, SagaFact], None] | None        # None => status deliberately unchanged (R19, R27)
    command_after: SagaCommandKind | None
@dataclass(frozen=True, slots=True, kw_only=True)
class Cancel:                                               # no command_after field: a cancel can owe nothing (R26)
    precondition: OrderStatus
    reason: Callable[[SagaFact], CancellationReason]
    compensation_steps: Callable[[SagaFact], tuple[CompensationStep, ...]]

SAGA_STEPS: Mapping[str, Skip | tuple[Advance | Cancel, ...]]
def variants_for(event_type: str) -> tuple[Advance | Cancel, ...] | Skip | None
def step_for_status(event_type: str, status: OrderStatus) -> Advance | Cancel | None   # equality only (R25)
```

The value for a consumed fact is a **tuple of variants**, each with its own precondition — #7's final shape (`application/saga-steps.ts:307-326`) — so feature 41 adds SA-4's variants as rows (`stock.released.v1` at `credit_approved` / `confirmed`, `credit.released.v1` at those statuses) without reshaping the table. In this feature every consumed fact has exactly one variant.

| Fact | Kind | Precondition | Aggregate call(s) | Owed after commit | Mismatch |
|---|---|---|---|---|---|
| `order.placed.v1` | advance | `PLACED` | none (R19) | `stock.reserve` | ignored (R25) |
| `stock.reserved.v1` | advance | `PLACED` | `mark_stock_reserved` | `credit.hold` | ignored |
| `stock.rejected.v1` | cancel | `PLACED` | `cancel(STOCK_REJECTED, ())` | **none, normatively** (R26) | ignored, still no release |
| `credit.approved.v1` | advance | `STOCK_RESERVED` | `approve_credit` then `confirm` — one load, one save, one `order.confirmed.v1` (R21) | `despatch.create` | ignored |
| `credit.rejected.v1` | advance | `STOCK_RESERVED` | none (R27) | `stock.release` (`reason = credit_rejected`) | ignored |
| `stock.released.v1` | cancel | `STOCK_RESERVED` | `cancel(map_release_reason(fact), release_steps_from(fact))` (R28, SO7) | none | ignored |
| `order.despatched.v1` | advance | `CONFIRMED` | `mark_despatched` | `invoice.issue` | ignored |
| `invoice.issued.v1` | advance | `DESPATCHED` | `mark_invoiced` | **none** (R23) | ignored |
| `payment.received.v1` | advance | `INVOICED` | `mark_paid` | none | ignored |
| `credit.released.v1` | advance | `PAID` | `complete` (R24) | none | ignored |
| `order.confirmed.v1`, `order.completed.v1`, `order.cancelled.v1`, `order.saga_failed.v1` | skip | — | — | — | — |

Fourteen rows, four skips. Every call passes `occurred_at=fact.occurred_at`, and `confirm` / `complete` / `cancel` pass `causation_id=fact.event_id` (R12). `map_release_reason`: `credit_rejected` → `CREDIT_REJECTED`, `order_cancelled` → `OPERATOR_CANCELLED` (a `match` over the generated `Reason1` enum with a `case _:` that raises, so a third reason added to the spec fails loudly); the aggregate itself refuses an illegal reason / status pair (`CancellationReasonNotApplicableError`). `release_steps_from(fact)` returns exactly one `CompensationStep(step=STOCK_RELEASED, event_id=fact.event_id, event_type="stock.released.v1", occurred_at=fact.occurred_at, summary=None)` (summary: gate point G2).

### 6.2 The wrong-precondition rule (R25)

`step_for_status` compares by **equality**: no ranges, no "or later". On mismatch: no aggregate mutation, no enqueue, no fact, a `saga_ignored_facts` row with observed and expected status in the dedup transaction, and the offset commits. Every row of saga.md §6's redelivery table follows from this rule plus the dedup layer, and task 10.3 sweeps that table literally.

### 6.3 Why ignoring an unmet-precondition fact loses nothing

Ignore-plus-dedup would permanently swallow a fact that arrived **early**. None can, for #7's and #8's two reasons (#8 `design.md` §4.4): (1) **commit-before-issue** (SO3): a command is enqueued in the transaction that makes its precondition durable and is issued only after commit, so no responder can emit the fact before the status it needs exists; (2) **per-partition order within one producing context**: the only trigger not caused by an orchestrator command is `payment.received.v1`, which Billing writes after `invoice.issued.v1` on the same partition, and `credit.released.v1` follows it in the same Billing transaction. So every unmet precondition in practice is a stale redelivery. Point (1) is gate point G3's candidate (a); it is realised here, not written into `specs/shared/`.

## 7. The transactional unit

### 7.1 `SagaFactHandler.handle(fact) -> SagaFactResult`

```
variants = variants_for(fact.event_type)
if variants is None or isinstance(variants, Skip): return SagaFactResult(PROCESSED, enqueued=None)    # defensive: §5.5 filters first
enqueued = None; ignored = False
async def work(tx):                                         # tx: the unit of work's transaction (§7.3)
    order = await tx.orders.get_by_id_for_update(fact.correlation_id)        # §7.2
    if order is None:                    record UNKNOWN_ORDER (SO8);         ignored = True; return
    step = step_for_status(fact.event_type, order.status)
    if step is None:                     record PRECONDITION_UNMET (R25);    ignored = True; return
    match step:
        case Advance():
            if step.apply is not None: step.apply(order, fact); await tx.orders.save(order)
            if step.command_after is not None:
                await tx.saga_commands.enqueue(owed_command(step.command_after, order, fact))   # either outcome reports it owed (§7.5)
                enqueued = step.command_after
        case Cancel():
            order.cancel(reason=step.reason(fact), compensation_steps=step.compensation_steps(fact),
                         occurred_at=fact.occurred_at, causation_id=fact.event_id)
            await tx.orders.save(order)
outcome = await idempotent_consumer.run_once(fact.event_id.value, ConsumerName.ORDERS_SAGA, work)
DUPLICATE -> SagaFactResult(DUPLICATE, None); ignored -> SagaFactResult(IGNORED, None); else SagaFactResult(PROCESSED, enqueued)
```

- The canonical `IdempotentConsumer` (`infrastructure/messaging/idempotent_consumer.py`) is used **unmodified**: dedup insert first, `work` in the same transaction (R17), `DUPLICATE` with nothing written (R18). It is parity-guarded and must not be edited.
- One transaction holds the dedup row, the aggregate change, its outbox rows and the owed-command row: R17 plus SO3 in one sentence.
- `save` is called only when the step mutated the aggregate (#7 saved always, `saga-fact-handler.ts:188`; an unchanged save is an `UPDATE` of identical values, and skipping it changes nothing observable). The row lock of §7.2 is taken either way.
- `enqueued` and `ignored` are closure variables (`nonlocal`) set only inside `work`; `run_once` never retries `work`, so they cannot carry a value from an aborted attempt.
- **No deadlock retry** in the unit of work (outbox design §12.1, G2, decided): a deadlock victim propagates, the offset is not committed, and the redelivery re-runs the whole step. The re-open trigger recorded there (*"a deadlock measured in an orders unit of work in feature 15 or 16"*) is watched by task 14.3.

### 7.2 The order-row lock (SO17)

`OrderRepository.get_by_id_for_update(order_id)` (new port method; `get_by_id` keeps its plain read for feature 15's callers):

```python
select(OrderRow, Retailer, Company, Currency).join(...).where(OrderRow.id == order_id.value).with_for_update(of=OrderRow)
# SELECT … FROM orders JOIN retailers … JOIN companies … JOIN currencies … WHERE orders.id = $1 FOR UPDATE OF orders
```

- **Why at all.** saga.md §6's three layers make one consumer safe; they do not serialise **two writers** of one order. Two exist or will: a redelivery processed by a second group member during a rebalance, and feature 41's operator cancel (#8 id 62, whose chosen defence kept exactly this lock, `EfCoreOrderRepository.cs:61-108`). Under PostgreSQL `READ COMMITTED` a plain `SELECT` never waits, so both writers would read the same status and both proceed. #9's own spec assigned this lock to this feature (`specs/orders_aggregate/design.md` §9).
- **Why `of=OrderRow`.** PostgreSQL's `FOR UPDATE` without `OF` locks a row of **every** table in the `FROM` clause. The order load joins three reference tables, so a bare lock would hold the retailer's row and serialise every saga step of every order of that retailer (and block any writer of the reference row). `OF orders` locks the one row that is the aggregate root.
- **Items are not locked.** Lines are written only through the aggregate, whose root row is locked first by every mutating path, so the root lock serialises them (the root-lock rule #8 relied on: its lock is on `dbo.orders` only, `EfCoreOrderRepository.cs:106`).
- The lock is held to commit or rollback, inside the step's transaction at the pinned `READ COMMITTED`; a second locker waits (`lock_timeout = 0`, the deployed default asserted by `test_fixture_matches_deployed_server.py`) and then reads the committed row, so its precondition check sees the first writer's status.
- Guards (tasks 7.1, 7.2): two transactions, the second observed **waiting** in `pg_locks` until the first commits, and then seeing the new status; a third connection locks the order's retailer row `FOR UPDATE NOWAIT` successfully while the order is held. Armed: drop `with_for_update` (the second does not wait); drop `of=` (the retailer `NOWAIT` fails, naming the retailer row).

### 7.3 The transaction object

`OrdersTransaction` (application port) gains two properties, implemented by `SqlAlchemyOrdersTransaction` over its own session:

```python
class OrdersTransaction(Protocol):
    @property
    def orders(self) -> OrderRepository: ...
    @property
    def saga_commands(self) -> SagaCommandQueue: ...          # enqueue only
    @property
    def ignored_facts(self) -> SagaIgnoredFactRecorder: ...
```

The collaborators are reachable only through the transaction (outbox design L1), so the enqueue and the record cannot sit in a second transaction. The `IdempotentConsumer`'s `SessionBound` requirement is unchanged (`.session` stays on the infrastructure class).

### 7.4 The ignored-fact record

`SqlAlchemySagaIgnoredFactRecorder.record(...)` adds a `SagaIgnoredFact` row through the transaction's session (ORM unit of work): `event_id`, `event_type`, `order_id` (`None` for `UNKNOWN_ORDER`), `correlation_id`, `observed_status` (`None` for unknown), `expected_status` (the sole variant's precondition; `None` when a fact type has several, #7 `saga-fact-handler.ts:86-87`), `marker` (`precondition_unmet` | `unknown_order`, an `enum.Enum` whose values fit `varchar(20)`), `recorded_at` (clock). A durable row, not a log line, because R25's test must read what was recorded and because "why did the saga ignore this?" is an operations question (#7 and #8 agree; gate G3 candidate (b)). It runs only inside a first-delivery `run_once`, so the dedup layer makes it idempotent. Every record is also logged with `correlationId`.

### 7.5 Enqueue — idempotent on the command's natural key

```python
pg_insert(SagaCommand).values(id=uuid4(), order_id=…, order_reference=order.order_reference.value, command=kind.value,
    payload=to_wire_json(request), triggering_event_id=fact.event_id.value, status="pending",
    created_at=now, updated_at=now)
  .on_conflict_do_nothing(index_elements=["order_id", "command"]).returning(SagaCommand.id)
```

- No row back means the command is already owed or already sent (`EnqueueOutcome.ALREADY_OWED`): not an error, logged at WARNING with `correlationId` (reaching it means a dedup record was lost, or a distinct-eventId duplicate arrived mid-compensation, #7 D1). Either outcome reports the command as owed, so the fast path re-signals the row that exists (a `sent` row is a no-op claim, a `pending`/`parked` one is dispatched).
- `attempts` is not written (server default `0`), so this ORM-enabled insert writes no guarded integer column (range guard residual, `range_guards.py:10-18`; census classification "no guarded column", §13.2).
- The payload is the generated request model serialised once by `to_wire_json` (L21).

### 7.6 "Every step recorded", and the redelivery sweep

| What happened | Durable record | Asserted by |
|---|---|---|
| A status progression | `outbox` row → fact on the stream → (feature 24) timeline | the happy-path and compensation tests |
| A fact deliberately ignored | `saga_ignored_facts` with both statuses, or `unknown_order` | `test_saga_preconditions.py` |
| A command owed, issued, parked or resumed | `saga_commands`: `status`, `attempts`, `last_error`, `next_attempt_at`, `sent_at` | `test_saga_command_retry.py`, `test_saga_command_ledger.py` |
| A redelivery absorbed | the `processed_events` row that already existed | feature 14's `test_r18_…` + `test_saga_preconditions.py` |

**The sweep (task 10.3)** realises saga.md §6's per-fact table row by row, on orders inserted at the post-processing status through the repository: each of the ten consumed facts published with a **new** event id (the dedup layer bypassed on purpose, so layer 2 is what is tested) → no status change, no command row, no outbox row, one `saga_ignored_facts` row with both statuses; plus the same-event-id case (layer 1, R18); plus `credit.rejected.v1` with a new event id while the order is still `stock_reserved` (precondition met, compensation in flight): exactly one `stock.release` row, the offset commits, nothing poisons (#7 D1).

### 7.7 Fact commands, dispatch-owed events and the `order_sagas` handlers

The shape is #7's and #8's, kept for the benchmark's one-to-one mapping (#8 `design.md` §5.5, *a deliberate parity cost*):

1. **Ten commands** `Handle<Fact>FactCommand(Command[SagaFactResult])` (`fact_commands.py`), each a frozen dataclass holding the validated envelope and the source topic; `FACT_COMMANDS: Mapping[str, type[...]]` maps the ten consumed event types (the four self-produced map to nothing).
2. **One handler class** `SagaFactCommandHandler` (`fact_command_handlers.py`) registered ten times in `composition.py` (ten explicit `register_command` statements; `test_cqrs_registration_explicit.py`'s composition-root rule). It builds `SagaFact` (§5.5), calls `SagaFactHandler.handle`, and **only when** the result is `PROCESSED` with an enqueued command — strictly after `run_once` returned, so after commit — publishes the matching dispatch-owed event through `scope.dispatcher.publish(event, scope)` (A6).
3. **Five dispatch-owed events** (`dispatch_events.py`, #8's names): `OrderPlacedFactRecorded`, `OrderMarkedStockReserved`, `CreditRejectionRecorded`, `OrderConfirmedBySaga`, `OrderMarkedDespatched`; frozen dataclasses with `order_id` and `triggering_event_id`. (`OrderConfirmedBySaga`, not #7's `OrderConfirmed`, because `otc_orders.domain.events.OrderConfirmed` exists.)
4. **Five `EventHandler`s** in `order_sagas.py` (#7's file name), each calling `signal.signal(SagaCommandRef(order_id, <its kind>))` and nothing else.

`register_event` accepts zero handlers silently (`dispatcher.py:93-101`: an event with no listener is not a boot error), so a missing `order_sagas` registration would drop the fast path without failing anything. Task 6.9 makes that a guard: publishing each of the five events through the **built** composition-root dispatcher yields exactly its own kind on a recording signal.

## 8. The fast path (SO10, SO13) — gate point G1

### 8.1 The model

`SagaFastPath` (infrastructure, implements the `SagaCommandSignal` port):

```python
class SagaFastPath:
    def __init__(self, *, dispatcher: DispatchesSagaCommands, max_in_flight: int) -> None
    def signal(self, ref: SagaCommandRef) -> None:          # synchronous, never blocks, never raises
        if self._group is None or self._in_flight >= self._max_in_flight:
            log WARNING "fast path full or stopped; the sweeper will issue it" (correlationId, command); return
        self._in_flight += 1
        self._group.create_task(self._run(ref))             # the caller's contextvars context is copied (L7)
    async def run(self, stop: asyncio.Event) -> None:       # owned by the lifespan (§12.1)
        async with asyncio.TaskGroup() as group:
            self._group = group
            await stop.wait()
            self._group = None
            for task in in-flight children: task.cancel()   # their rows stay leased; the sweeper re-issues after the lease
    async def _run(self, ref) -> None:
        try: await self._dispatcher.dispatch(ref.order_id, ref.kind)
        except Exception: log ERROR (correlationId, command, exc_info)          # L8: never kills the group
        finally: self._in_flight -= 1
```

- **No head-of-line blocking.** Each command is its own task; no command ever waits for another's dispatch. This is #7's `mergeMap` semantics (L6), not #8's bounded pool.
- **Bounded resources without waiting.** `SAGA_FAST_PATH_MAX_IN_FLIGHT` (default **256**, refused at boot below 1 — #8 id 90's silent-zero shape cannot occur, because a value that would dispatch nothing never starts) caps concurrent fast-path dispatches. A signal beyond it is **dropped to the durable path**, never queued: the row is already committed `pending`, and the sweeper issues it within `SAGA_PENDING_GRACE_MS + SAGA_SWEEPER_INTERVAL_MS` (10 s + 30 s = 40 s) of its commit. This is #8's `DropWrite` guarantee (*the in-process hop is only an optimisation over a durable queue that would deliver the same command anyway*), applied to tasks instead of a channel.
- **Worst case, arithmetically** (#8 id 88 asked for it). A fast-path command waits for no other command. Its own dispatch takes at most `MaxAttempts × TimeoutMs + Σ backoff` = 3 × 5 000 + 500 + 1 000 = **16 500 ms**; a dead subject answers *no responders* at once, so it occupies its task for the back-off sum only (1 500 ms). If 256 dispatches are in flight, the 257th command is issued by the sweeper within 40 000 ms of its commit, plus its own dispatch.
- **Per-order ordering.** No invariant relies on the order in which two commands of one order are dispatched: at most one command per (order, kind) exists (unique key); a later command is only owed after the fact caused by an earlier one has been processed; SA-4's contested release-versus-despatch is arbitrated by Fulfillment's lock regardless of arrival (saga.md §4.3); `credit.release` (feature 41) is owed only after `stock.released.v1`. #8 reached the same enumeration when it removed its single worker (#8 `design.md` §5.5, id 80 correction). Two tasks for the **same** row (a re-signal) are excluded by the claim (SO11): one wins, the other is a no-op.
- **Connection-pool interplay.** A dispatch holds a database connection only for its claim and its mark / park statements, never across the RPC. Under a burst, statements wait for the pool (`pool_timeout`); an expiry surfaces as a logged failed dispatch whose row stays leased and is re-issued by the sweeper after the lease. Stated, not hidden.

### 8.2 Why not the alternatives (for the gate)

(a) **#8's bounded worker pool** reproduces id 88's residual by construction (N stuck dispatches stall the N+1th), loses the trace context across the queue (L7, #8's own later defect) and needs a degree setting with a floor (id 90). (b) **Awaiting the dispatch in the event handler** puts the 16.5 s worst case on the consume loop (SO10 violated; heartbeats unaffected but every fact queues behind a dead responder). (c) **Unbounded tasks with no maximum** is #7 exactly, but a burst of slow commands would open unbounded concurrent requests and pool waits; the maximum costs one integer and turns overload into sweeper latency instead of resource exhaustion.

### 8.3 Exceptions and cancellation

A child's `Exception` is logged and contained (a `TaskGroup` would otherwise cancel every sibling, L8). `CancelledError` is never caught (L9): on shutdown the group cancels in-flight children; a child cancelled after the responder executed but before `mark_sent` leaves the row leased and the sweeper re-issues it after the lease — safe because responders are idempotent by (`orderReference`, operation). `signal` called after `run` has ended, or before it starts, drops to the durable path (it never raises into the fact handler, whose transaction has already committed).

## 9. Command issuing

### 9.1 Kinds and subjects

`SagaCommandKind` (`application/saga/command_kind.py`), an `enum.Enum` of six members with their wire tokens: `stock.reserve`, `stock.release`, `despatch.create`, `credit.hold`, `invoice.issue`, `credit.release`. `credit.release` is present because it is a saga command in `asyncapi.yaml` (`creditRelease`, line 439) and the adapter's surface and #8 id 110's guard are over six subjects; **no step owes it in this feature** (feature 41 adds the rows). `infrastructure/messaging/saga_subjects.py` maps each kind to its subject — `fulfillment.stock.reserve`, `fulfillment.stock.release`, `fulfillment.despatch.create`, `billing.credit.hold`, `billing.invoice.issue`, `billing.credit.release` — each equal to its channel's `address` read from `asyncapi.yaml` by test (task 4.2).

### 9.2 The port, the adapter and the error taxonomy

```python
class SagaCommands(Protocol):                    # application/ports/saga_commands.py
    async def reserve_stock(self, request: bytes, meta: SagaCommandMeta) -> StockReserveReplyPayload: ...
    async def release_stock(...) -> StockReleaseReplyPayload: ...
    async def create_despatch(...) -> DespatchCreateReplyPayload: ...
    async def hold_credit(...) -> CreditHoldReplyPayload: ...
    async def issue_invoice(...) -> InvoiceIssueReplyPayload: ...
    async def release_credit(...) -> CreditReleaseReplyPayload: ...

class SagaCommandError(Exception): subject: str                       # base; never caught by the domain
class SagaCommandTimeoutError(SagaCommandError)                       # retryable
class SagaCommandTransportError(SagaCommandError)                     # retryable (no responders, malformed reply)
class SagaCommandRpcError(SagaCommandTransportError): code: str       # a TRANSIENT RpcError reply (INTERNAL_ERROR, UNAVAILABLE, TIMEOUT); retryable
class SagaCommandBusinessRejectionError(SagaCommandError): code: str  # a TERMINAL RpcError reply; never retried (feature 42)
```

`request` is the stored payload bytes (L21): the adapter sends what was committed, never a re-serialisation. `NatsSagaCommandsAdapter` holds feature 15's connected client (A3), the timeout, and `nats_saga_commands.py`'s private `Protocol` typing the one call it makes (`request(subject, payload, timeout, headers) -> <msg with .data: bytes>`, L27).

| Observed | Raised | Retryable? |
|---|---|---|
| `nats.errors.NoRespondersError` | `SagaCommandTransportError` ("no responder is subscribed to this subject") | yes |
| `nats.errors.TimeoutError` | `SagaCommandTimeoutError` | yes |
| any other `nats.errors.Error` | `SagaCommandTransportError` (its message) | yes |
| a reply that is not JSON, not an object, or fails the subject's reply model (SO15) | `SagaCommandTransportError` naming the defect | yes |
| a reply that is an `RpcError` with a transient code (`INTERNAL_ERROR`, `UNAVAILABLE`, `TIMEOUT`) | `SagaCommandRpcError(code)` | yes |
| a reply that is an `RpcError` with a terminal business code (`VALIDATION_FAILED`, `NOT_FOUND`, `CONFLICT`, `PRECONDITION_FAILED`, `ORDER_NOT_CANCELLABLE`, `STOCK_UNAVAILABLE`, `INVOICE_NOT_PAYABLE`, `PAYMENT_MISMATCH`, `DOMAIN_ERROR`) | `SagaCommandBusinessRejectionError(code)` | **no — resolved on the first attempt** (feature 42) |
| a reply that is an `RpcError` with a code outside the twelve | `SagaCommandTransportError` with no `code` (L18, fails open) | yes |

> **Feature 42's amendment (§9.2).** The terminal set is `nats_saga_commands.TERMINAL_RPC_ERROR_CODES`, a `frozenset` of the generated `Code` enum: #7's and #8's nine, member for member (`nats-saga-commands.adapter.ts:79`, `NatsSagaCommandsAdapter.cs:179`). `asyncapi.yaml` describes only `TIMEOUT` (caller-produced), so no description forces a difference. `SagaCommandBusinessRejectionError` deliberately does not subclass `SagaCommandTransportError`, so no `except SagaCommandTransportError` can swallow it as retryable.
| a well-formed typed reply, any `outcome` including `rejected`, any idempotent-repeat outcome (`already_reserved`, `already_held`, `already_released`, `created: false`) | returned | n/a (SO6) |

The *no responders* / *timeout* split is the one #8 paid a blocking defect for in its feature 15 (D1) and the one feature 42 builds on; two distinct types keep it, and the trap of L16 (`nats.errors.TimeoutError` is a builtin `TimeoutError`) is why the adapter names the nats classes rather than catching `TimeoutError`.

### 9.3 Reply decode (SO15)

```
try:
    document = json.loads(reply.data)                          # ValueError (JSONDecodeError, UnicodeDecodeError)
    if not isinstance(document, dict): raise ValueError("reply is not a JSON object")
    if isinstance(document.get("code"), str):
        error = rpc_error_of(reply.data)                       # from_wire_json(RpcError, …); an unknown code -> ValueError -> transport (fails open, L18)
        raise SagaCommandRpcError(subject, error.code.value, error.message)
    return from_wire_json(reply_model, reply.data)             # pydantic.ValidationError is a ValueError
except ValueError as defect:
    raise SagaCommandTransportError(subject, f"malformed reply: {defect}") from defect
```

No success reply schema has a top-level `code` property (the six reply models, `generated/asyncapi.py:624-764`; `creditCode` is a different key), so the discriminator cannot misfire on a success; task 4.4 asserts that over the generated models rather than trusting this sentence. If feature 15 has put the `success | RpcError` decode in a shared helper (A5), this adapter calls it; the classification table above is the contract either way.

### 9.4 Payloads from the aggregate

`build_command_payload(kind, order, fact)` (`application/saga/command_payloads.py`) returns the **generated** request model, built from the loaded aggregate only (#7 `application/saga-command-payloads.ts:80-145`):

| Kind | Request fields |
|---|---|
| `stock.reserve` | `order_reference`, `retailer_code`, `company_code`, `lines = [{product_code, units: line.quantity.value} for line in order.lines]` |
| `stock.release` | `order_reference`, `reason = credit_rejected` (owed only by `credit.rejected.v1`; any other trigger raises) |
| `despatch.create` | `order_reference` |
| `credit.hold` | `order_reference`, `retailer_code`, `company_code`, `amount = Money(amount=order.total_amount.amount, currency=order.currency)` |
| `invoice.issue` | `order_reference`, `retailer_code`, `company_code`, `currency`, `lines = [{product_code, units, unit_price: line.unit_price.amount}]`, `discount = order.initial_discount.amount` |
| `credit.release` | `order_reference`, `retailer_code`, `company_code` (built and tested; owed by no step until feature 41) |

Every amount is an `int` of minor units copied from a `Money`; no arithmetic, no `Decimal`, no `float`. The generated models' `ge`/`le` bounds re-check int64 on construction.

### 9.5 The dispatcher and the retry policy (SO4, SO6)

```python
class SagaCommandDispatcher:
    async def dispatch(self, order_id: UniqueId, kind: SagaCommandKind) -> DispatchOutcome      # fast path: try_claim first
    async def dispatch_claimed(self, row: ClaimedCommand) -> DispatchOutcome                    # sweeper: no second claim (SO16)
```

`dispatch` claims through `ledger.try_claim(order_id, kind)`; no row back (absent, `sent`, `rejected`, or leased by someone else) is a **silent no-op** (`NOOP`). Then, for attempt 1 … `max_attempts`: call the port with the stored bytes and `SagaCommandMeta(correlation_id=order_id, request_id=row.id)`; a returned reply → `ledger.mark_sent(row.id)` → `SENT` (including `outcome: rejected`, SO6); a `SagaCommandBusinessRejectionError` (feature 42) → `ledger.reject(row.id, total_attempts=row.attempts + attempts_this_cycle, last_error)` → `REJECTED`, on **that** attempt, with no pause and no later attempt, logged at ERROR with `correlationId`, `command`, `attempts`, `code`, `last_error`; any other `SagaCommandError` → remember its message, `await sleep(in_line_backoff_ms(attempt) / 1000)` unless last. Exhausted → `ledger.park(row.id, total_attempts=row.attempts + attempts_this_cycle, last_error, next_attempt_at=clock.now() + park_backoff(total))` → `PARKED`, logged at ERROR with `correlationId`, `command`, `attempts`, `last_error`, `next_attempt_at` (the structured saga-failure entry of SO5). The order is never loaded or written here (R29).

> **Feature 42's amendment (§9.5).** `rejected` is a terminal row status. `reject` sets `status = 'rejected'`, `attempts`, `last_error` and clears `next_attempt_at`, and only on a `pending` or `parked` row. Every ledger status predicate now names its set (`CLAIMABLE = ('pending', 'parked')`): `try_claim`, `mark_sent`, `reject` and `park` use `status IN CLAIMABLE` (`park` was `status <> 'sent'`, which would have re-parked a `rejected` row), and `claim_due`'s two branches name `pending` and `parked`. The sweeper therefore never re-claims a `rejected` row, and `SweepResult` counts `rejected` separately. Feature 42 deliberately emits no `order.saga_failed.v1` and no dead letter (#7 and #8 deferred both to observability); a rejected row is visible as `SELECT * FROM saga_commands WHERE status = 'rejected'`.

`backoff.py`, pure and `int`-only (L14, L15):

```python
def in_line_backoff_ms(attempt: int, *, base_ms: int) -> int:            # base_ms * 2 ** (attempt - 1); attempt <= 10
def park_exponent(total_attempts: int, *, max_attempts: int) -> int:     # min(total_attempts // max_attempts, 31)
def park_backoff_ms(total_attempts: int, *, max_attempts: int, cap_ms: int) -> int:   # min(30_000 * 2 ** park_exponent(...), cap_ms)
```

The park formula is #8's (`30 s × 2^cycles`, first park retried after 60 s); #7's started one doubling lower. Gate point G2 records the choice. The `sleep` and the clock are injected, so unit tests run instantly with a fake.

| Setting (`SagaSettings`) | Env | Default | Meaning |
|---|---|---|---|
| `command_timeout_ms` | `SAGA_COMMAND_TIMEOUT_MS` | 5 000 | per-attempt NATS budget (feature 15's stock-check budget is the same) |
| `command_max_attempts` | `SAGA_COMMAND_MAX_ATTEMPTS` | 3 | in-line attempts before parking; `1 … 10` |
| `command_backoff_ms` | `SAGA_COMMAND_BACKOFF_MS` | 500 | base, doubling |
| `command_lease_ms` | `SAGA_COMMAND_LEASE_MS` | 60 000 | claim lease (SO11); must be ≥ 2 × worst-case dispatch (SO16) |
| `park_retry_cap_ms` | `SAGA_PARK_RETRY_CAP_MS` | 900 000 | park back-off cap |
| `sweeper_enabled` | `SAGA_SWEEPER_ENABLED` | `true` | |
| `sweeper_interval_ms` | `SAGA_SWEEPER_INTERVAL_MS` | 30 000 | |
| `pending_grace_ms` | `SAGA_PENDING_GRACE_MS` | 10 000 | SO3 crash window and SO13 overflow latency |
| `sweeper_batch_limit` | `SAGA_SWEEPER_BATCH_LIMIT` | 20 | gate point G2 |
| `fast_path_max_in_flight` | `SAGA_FAST_PATH_MAX_IN_FLIGHT` | 256 | SO13; `≥ 1` |
| `consumer_enabled` | `SAGA_CONSUMER_ENABLED` | `true` | §12.3 |

Names are #7's (`infrastructure/saga/saga.config.ts:12-24`) where #7 had the knob; the lease, the in-flight maximum and the consumer flag are #9's.

### 9.6 The ledger — claim, mark sent, park (SO11; `reject` is feature 42's)

All five statements run (`reject` is feature 42's amendment) in their own short session and transaction at a pinned `READ COMMITTED` (outbox design L2), outside any fact transaction:

```sql
-- try_claim (fast path): one row, lease taken, row returned
UPDATE saga_commands SET next_attempt_at = :lease_until, updated_at = :now
 WHERE order_id = :order_id AND command = :command AND status IN ('pending', 'parked')
   AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
RETURNING id, order_id, order_reference, command, payload::text, attempts, triggering_event_id

-- claim_due (sweeper): a batch, leases taken, rows returned, rows another claimer holds skipped
UPDATE saga_commands SET next_attempt_at = :lease_until, updated_at = :now
 WHERE id IN (SELECT id FROM saga_commands
               WHERE (status = 'pending' AND created_at <= :pending_cutoff AND (next_attempt_at IS NULL OR next_attempt_at <= :now))
                  OR (status = 'parked' AND next_attempt_at <= :now)
               ORDER BY created_at LIMIT :batch FOR UPDATE SKIP LOCKED)
RETURNING …

-- mark_sent
UPDATE saga_commands SET status = 'sent', sent_at = :now, next_attempt_at = NULL, updated_at = :now
 WHERE id = :id AND status IN ('pending', 'parked')

-- park (attempts checked with ensure_in_range before execution: an ORM-enabled update bypasses the attribute guard)
UPDATE saga_commands SET status = 'parked', attempts = :attempts, last_error = :last_error_truncated,
       next_attempt_at = :next_attempt_at, updated_at = :now
 WHERE id = :id AND status IN ('pending', 'parked')   -- feature 42's amendment: was `status <> 'sent'`

-- reject (feature 42's amendment; attempts checked with ensure_in_range before execution, as for park)
UPDATE saga_commands SET status = 'rejected', attempts = :attempts, last_error = :last_error_truncated,
       next_attempt_at = NULL, updated_at = :now
 WHERE id = :id AND status IN ('pending', 'parked')
```

- `next_attempt_at` carries two meanings that never collide (#8 `design.md` §6.3): when a parked row is next due, and when a claimed row's lease ends. No new column, no migration; the existing `(status, created_at)` and `(status, next_attempt_at)` indexes serve the predicates (`models.py:190-191`).
- The claim and the lease are **one statement**; the sub-select's `FOR UPDATE SKIP LOCKED` makes two concurrent sweepers take disjoint batches without waiting (the outbox relay's measured skip, outbox design §5.2), and the outer predicate is re-evaluated under `READ COMMITTED` for a row that changed meanwhile.
- `mark_sent`, `park` and `reject` are conditional (feature 42's amendment: `reject` added, and `park` changed from `<> 'sent'`): a row another claimer already marked `sent`, or that was resolved to `rejected`, is never moved by any of them (#7 `drizzle-saga-command-store.ts:189-191`). `last_error` is truncated to 2 000 characters.
- `sent` means "a reply was delivered", **never** "the saga advanced": advancement is the fact's job (saga.md §2).
- Written with SQLAlchemy Core-style `update(SagaCommand)` statements in `command_ledger.py`; the write-path census classifies each (§13.2).

### 9.7 The sweeper (SO5, SO16)

`SagaCommandSweeper.run_once()` claims a due batch (§9.6), then dispatches **every claimed row concurrently** in a `TaskGroup` through `dispatcher.dispatch_claimed(row)` — **never** `dispatch(order_id, kind)`, which would try to re-claim a row this sweeper already leases and silently do nothing (#8's production defect, L12), and **never** through the fast path or the `otc_cqrs` dispatcher, because the sweeper is the durability backstop and must not depend on the layer it backs up. Each child catches `Exception` (L8). `run_once` returns when every child has finished, so a sweep never overlaps its own rows.

`SagaCommandSweeperTask.run(stop)` is the relay task's loop (L30): `await sweeper.run_once()` (an `Exception` logged, the loop continues; `CancelledError` propagates), then the interruptible wait; `sweeper_enabled = false` returns at once.

**Why concurrent, and the boot check.** A claimed row's lease must outlive its dispatch, or another claimer may take the row while this sweep still holds it. Dispatching the batch concurrently bounds a sweep by one worst-case dispatch (16 500 ms) instead of `batch × 16 500 ms`; `SagaSettings` refuses to construct when `command_lease_ms < 2 × (max_attempts × timeout_ms + Σ backoff)` (60 000 ≥ 33 000 at the defaults), so the lease is never shorter than a dispatch by configuration. The residual (a dispatch delayed past its lease by a pool wait) can at worst issue one command twice concurrently, which responders absorb by idempotency; it is stated, not claimed away.

**Park is not dead.** Back-off is capped and indefinite, the outbox relay's stance (*giving up needs somewhere to give up to*, which is feature 27's). Every park, failed sweep and resumption logs `correlationId`, `command`, `attempts`, `last_error`; `SELECT * FROM saga_commands WHERE status = 'parked'` is the operator's view.

### 9.8 Seams for feature 27

1. **Consumer retry / DLQ:** wrap the call to `dispatcher.send` in `SagaFactsConsumerTask._handle` (the outbox design §7 seam, now reachable); envelope failures stay log-and-acknowledge, processing failures (§5.5) become retried then dead-lettered. Feature 27 must **re-run** this feature's SO9 arms after adding the wrapper (#8 id 94: an in-process retry satisfied a gate meant for a Kafka redelivery) — the leader should attach that to feature 27's acceptance.
2. **R29's dead-letter clause:** attach DLQ publication and the `order.saga_failed.v1` timeline entry to the **first** park transition (`command_ledger.park`), which needs the triggering envelope's bytes and topic: two nullable columns plus a `dead_lettered_at` marker, feature 27's migration (#7 added the same columns in its feature 27, `saga-commands.schema.ts:56-65`; #8 id 71 bullet 5).
3. **Metrics:** parked count and oldest-parked age are one `SELECT` over `saga_commands`.
4. **`traceparent`:** `FactMessage.headers` is kept; the adapter's header dict gains `traceparent` / `tracestate` from the current context, which the fast path already preserves (§11).

## 10. Compensation — two paths, different by design

- **Path A, `stock.rejected.v1`** (`placed` → `cancelled`): `cancel(STOCK_REJECTED, ())`. The empty step list is normative (R26: reservation is all-or-nothing). `Cancel` has no `command_after` field, so the absence of a release is structural; the integration test also asserts zero requests at the stand-in release responder and no `saga_commands` row, before and after a redelivery against `cancelled` (#7's D3: its wire-level R26 case survived the mutation the unit cases killed, so this feature arms the **integration** case too, task 11.6).
- **Path B, `credit.rejected.v1` → `stock.released.v1`** (release, **then** cancel): the first step changes no status and owes `stock.release` (`reason = credit_rejected`); only the release **fact** cancels, with one compensation step built from that fact (SO7). *"Pending compensation is a credit rejection"* (R28) is read from the fact's own `reason`, never from a saga-instance record (there is none: saga.md §1). Causal order is asserted on `causationId` chaining (the cancel's `causation_id` equals the release fact's `event_id`), not on arrival order.
- **The `order_cancelled` branch** of `map_release_reason` (operator cancellation from `stock_reserved`) exists, is unit-tested, and has **no producer until feature 41** — the "no live caller" case CLAUDE.md arms with double force (task 11.5).
- **SO6 on the wire:** a `credit.hold` answered `outcome: rejected` is marked `sent` after exactly one request; the rejection fact, not the reply, takes path B.

## 11. Trace context and headers (SO14)

**The headers.** Every request carries `x-correlation-id = str(order_id)` and `x-request-id = str(saga_commands.id)`, built in a fresh dict per call (L19, #8 id 48), identical on every attempt of one row and on both paths (L20). `RpcHeaders` marks `traceparent` required (`asyncapi.yaml` lines 2837 – 2838); this feature sends none, exactly as #7 and #8 at their feature 16, because no tracer exists until feature 27 (outbox design §12.2: *"no `traceparent` until feature 27"*, decided). The gap is recorded, not hidden.

**The context.** The property this feature owns is the substrate: the dispatch runs in a **copy of the context of the fact handling that owed it** (L7), because `signal` creates the task from inside that handling and asyncio copies the creator's `contextvars` at task creation. Feature 27's span context (OpenTelemetry Python stores it in a `ContextVar`) and its `correlationId` log binding (`structlog.contextvars`) will therefore arrive in the dispatch with no capture field. The sweeper path has no fact context; it binds `correlationId` from the row (and feature 27 decides whether a resumed command starts a linked trace). Guard (task 6.5): a `ContextVar` set in the signalling context is observed inside the dispatch; armed by creating the task with `context=contextvars.Context()`.

## 12. Lifespan, composition, settings, packages

### 12.1 Three owned tasks

Feature 15's lifespan (A2) gains, in start order: `SagaFastPath.run(stop)`, `SagaCommandSweeperTask.run(stop)`, then `SagaFactsConsumerTask.run(stop)` (the consumer last, so its first signal finds the fast path running). Shutdown sets the stop signal and awaits them in reverse: the consumer finishes its in-flight record (handler + commit) and stops aiokafka; the sweeper finishes its current batch; the fast path cancels in-flight dispatches and awaits their cancellation. Only then does feature 15 close the NATS client and dispose the engine, which every one of the three uses. Each task joins A2's readiness rule: an unexpected end takes readiness down (task 12.4 proves it for each of the three, by name).

### 12.2 Composition (`composition.py`, feature 15's file)

- Ten `register_command(Handle<Fact>FactCommand, factory)` statements, five `register_event(<event>, factory)` statements, each a distinct statement in `composition.py` (feature 15 item 6's behavioural registration guard counts them); the message roots passed to `build` include `otc_orders.application.saga.fact_commands`, so a missing or duplicate fact-command handler fails the boot.
- One `SagaFastPath`, one `SagaCommandDispatcher`, one `NatsSagaCommandsAdapter` over feature 15's client (A3, no second connection), one `SqlAlchemySagaCommandLedger` over the lifespan's `async_sessionmaker`, one `KafkaFactSubscriber`, one `SagaCommandSweeper`; the unit of work's transaction factory now builds the queue and the recorder over each transaction's session (§7.3). Settings are read through pydantic-settings only, and `SagaSettings` joins A4's environment-read guard population.

### 12.3 `SagaSettings`

The table of §9.5, one `validation_alias` per field, no `populate_by_name` (backlog 210's rule); milliseconds become seconds only in properties (`/ 1000`, a `float` for asyncio, the settings boundary). Model validators refuse: `command_max_attempts` outside `1 … 10`; `fast_path_max_in_flight < 1`; any non-positive interval, timeout, grace or cap; and the SO16 lease rule. **`SAGA_CONSUMER_ENABLED`** mirrors `OUTBOX_RELAY_ENABLED` (feature 14): it lets a process run without consuming facts (feature 15's acceptance tests boot the lifespan without a Kafka container); when `false` the boot logs a WARNING naming the setting, and the fast path and sweeper still run, so owed commands are still issued. Neither predecessor had it; it is a test-isolation knob, not a behaviour (§17 decided).

### 12.4 No migration, no new package

`saga_commands` and `saga_ignored_facts` exist since feature 9 with every column and index this design needs (`models.py:186-219`), checked column by column:

| Needed by | Column / index | Present |
|---|---|---|
| enqueue | `id`, `order_id`, `order_reference varchar(20)`, `command varchar(30)` (longest token `despatch.create`, 15), `payload json`, `triggering_event_id`, `status varchar(10)` default `pending`, `created_at`, `updated_at` | yes |
| park bookkeeping | `attempts integer` default 0, `last_error text`, `next_attempt_at timestamptz(3)`, `sent_at` | yes |
| lease (SO11) | `next_attempt_at`, no new column | yes |
| one command per (order, kind) | `UniqueConstraint("order_id", "command")` | yes |
| sweeper predicates | `ix_saga_commands_status_created_at`, `ix_saga_commands_status_next_attempt_at` | yes |
| feature 42's `rejected` | `status varchar(10)` (8 characters) | yes |
| R25 / SO8 record | `saga_ignored_facts`: nullable `order_id`, `observed_status varchar(20)` (longest `credit_approved`, 15), `expected_status`, `marker varchar(20)` (`precondition_unmet`, 18), index on `correlation_id` | yes |

**This feature adds no migration and must not.** aiokafka and nats-py are already dependencies of `services/orders/pyproject.toml` (feature 14, feature 15); pyyaml is already a dev dependency. The commit's `Packages installed:` reads *none*.

## 13. Architecture guards and censuses

### 13.1 Kafka client confinement (new: `tests/architecture/test_kafka_client_confinement.py`)

The `fact-producer-confinement` import-linter contract keeps aiokafka out of every `application` and `presentation`; it cannot say *which* infrastructure module may hold *which* client. The new test reads the AST of every `services/*/src/**/*.py` and asserts: the modules importing `aiokafka` are exactly the literal set `{otc_orders.infrastructure.outbox.kafka_publisher, otc_orders.infrastructure.messaging.kafka_fact_subscriber}`; the publisher imports no consumer name (`AIOKafkaConsumer`, `TopicPartition`, `ConsumerRecord`) and the subscriber no producer name (`AIOKafkaProducer`). Sentinels (a temporary tree): an aiokafka import in a comment or a string is not counted (AST, defeat rows 4 and 6), an `import aiokafka` inside `if TYPE_CHECKING:` **is** counted (row 5), an aliased `from aiokafka import AIOKafkaConsumer as C` is counted. Armed: an `AIOKafkaProducer` import added to the subscriber; an aiokafka import added to `infrastructure/saga/`. This is #8's two confinement rules (#8 `design.md` §10) in one instrument.

### 13.2 Census updates this code forces (counts read from the instruments, never predicted)

- `tests/architecture/test_write_path_population.py` — `EXPECTED["orders"]` gains one classified entry per new hit: the queue's `pg_insert` / `execute` (**no guarded column**: `attempts` is not written); the ledger's `update` / `execute` ×4 (`try_claim`, `claim_due`, `mark_sent`: **no guarded column**; `park`: **`ensure_in_range`** on `attempts` before execution); the recorder's `add` (**guarded**: ORM unit of work); any `text(` the `payload::text` read uses (**no guarded column**: a read). Docstrings and log messages must not contain DML-shaped text.
- `services/orders/tests/unit/test_idempotent_consumer_parity.py` — case 3 becomes live: Orders now references `AIOKafkaConsumer`. Its assertion message (*"today no service consumes facts"*) becomes false and is rewritten, and the case additionally asserts the computed set of consuming write models equals the literal `{"otc_orders"}` (the helper returns it; if it does not, it is extended to). Orders already carries the canonical copy, so `missing` stays empty.
- `tests/architecture/test_cqrs_registration_explicit.py` — `ALLOWED_DECORATORS` gains a decorator only if the census reports one (`dataclass`, `property` are already listed).
- `tests/architecture/test_money_guard.py` — unaffected: it covers `domain` and `shared_kernel`, and `domain/` does not change.
- `pyproject.toml` — no new import-linter contract (§13.1 is a test); `test_import_contract_coverage.py` therefore needs nothing.

## 14. Testing

### 14.1 Files and levels

| File (under `services/orders/tests/`) | Level | Infrastructure | Proves |
|---|---|---|---|
| `unit/saga/test_step_table.py` | unit | none | the full table, fourteen facts × nine statuses; SO2; SO7; R21 / R23 / R26 / R27 table rows |
| `unit/saga/test_fact_handler.py` | unit (fakes) | none | §7.1: duplicate, unknown order, precondition unmet, save then enqueue, the lock method used |
| `unit/saga/test_fact_command_handlers.py` | unit | none | publish only on processed-with-enqueue; `SagaFact` built from the envelope (UTC ms, typed payload) |
| `unit/saga/test_order_sagas.py` | unit | none | five events → five kinds; the composition-root registration of all five |
| `unit/saga/test_command_payloads.py` | unit | none | §9.4's mapping, distinct non-round amounts |
| `unit/saga/test_command_dispatcher.py` | unit (fakes) | none | SO4, SO6, park, no-op claim, `dispatch_claimed` never claims |
| `unit/saga/test_backoff.py` | unit | none | L14 / L15 arithmetic |
| `unit/saga/test_fast_path.py` | unit | none | SO10, SO13 (unit), SO14 context, containment, cancellation |
| `unit/saga/test_sweeper.py` | unit | none | concurrent batch, containment, loop shape, no overlap |
| `unit/saga/test_saga_facts_consumer.py` | unit (fakes) | none | §5.5 routing; SO2 |
| `unit/saga/test_kafka_fact_subscriber.py` | unit (fake consumer) | none | consumer options; commit-after; seek-on-failure; pacing; commit failure; ordering |
| `unit/saga/test_nats_saga_commands.py` | unit (fake client) | none | taxonomy, SO15 defects, headers |
| `unit/saga/test_saga_settings.py` | unit | none | defaults, aliases, validators, SO16 |
| `unit/saga/test_saga_topics_and_subjects.py` | unit | none | constants equal `asyncapi.yaml` addresses |
| `integration/saga/test_saga_happy_path.py` | integration | PG + Kafka + NATS | R19 – R24, acceptance item 1 |
| `integration/saga/test_saga_preconditions.py` | integration | PG + Kafka | R25, SO8, SO12, the redelivery sweep |
| `integration/saga/test_saga_compensation_stock_rejected.py` | integration | PG + Kafka + NATS | R26 |
| `integration/saga/test_saga_compensation_credit_rejected.py` | integration | PG + Kafka + NATS | R27, R28, SO6, SO7 |
| `integration/saga/test_saga_command_retry.py` | integration | PG + Kafka + NATS | R29 retry, SO3, SO5, SO16 |
| `integration/saga/test_saga_command_ledger.py` | integration | PG | SO11, enqueue idempotency, conditional marks |
| `integration/saga/test_saga_transactional_unit.py` | integration | PG | SO3 atomicity and commit-before-signal |
| `integration/saga/test_saga_consumption.py` | integration | PG + Kafka | SO1, SO9 ×2, group identity |
| `integration/saga/test_saga_fast_path_concurrency.py` | integration | PG + Kafka + NATS | SO13 (#8 id 89) |
| `integration/saga/test_saga_command_headers.py` | integration | PG + NATS | SO14 headers |
| `integration/saga/test_nats_saga_commands_reply_decode.py` | integration | NATS | SO15 (#8 id 110), six subjects |
| `integration/saga/test_saga_lifespan.py` | integration | PG + Kafka + NATS | the three tasks start, die → readiness, shut down in order |
| `integration/test_order_row_lock.py` | integration | PG | SO17 |
| `tests/architecture/test_kafka_client_confinement.py` (repo root) | architecture | none | §13.1 |

Names follow the matrix convention: `test_r<n>_…` for shared rows, `test_so<n>_…` for local ones (`requirements.md` §3 is the contract). Saga unit tests build orders through `Order.rehydrate` in their own `unit/saga/conftest.py` (the repository runs `--import-mode=importlib`, so they cannot import `unit/domain/conftest.py`'s fixtures).

### 14.2 Event loops and fixtures

Every async fixture keeps the repository default `loop_scope="function"`: the engine, the `AIOKafkaConsumer` (inside the subscriber's `run`), test producers and consumers, the nats-py client, and the lifespan under test are created and disposed in the test's own loop. The Kafka and NATS containers are session-scoped and synchronous. The root `conftest.py`'s `KAFKA_FACT_TOPICS` gains `otc.fulfillment.facts.v1` and `otc.billing.facts.v1` (6 partitions, replication factor 1, auto-creation is off); nothing else in that fixture changes. The suites must pass with the developer stack down (#8 id 104).

### 14.3 The harness, and how integration tests synchronise

- **One harness fixture** (`integration/saga/conftest.py`) starts the real lifespan (feature 15's `create_app()` with settings pointing at the containers and the test's knobs: short intervals, short timeouts, `SAGA_SWEEPER_ENABLED` per test) and is the only way a test starts the consumer; at teardown it stops the lifespan and deletes the `orders.saga` group so the next test starts clean (#8 id 74). Driving the real lifespan, not a hand-assembled set of objects, is #8 D6's lesson (*the test proved the container validates when asked, not that the host asks*).
- **Stand-in responders** (fixtures, six subjects): real nats-py subscriptions with programmable replies and request recording (subject, headers, raw bytes), a real subscribe-and-flush probe before returning (never a fixed delay), and the outbox side stood in for: after replying, the stand-in publishes the corresponding fact envelope to the real topic keyed by `correlationId` (built with `otc_contracts` models, fresh `eventId`, `causationId` = the request's `x-request-id`). **No stand-in under `src/`.**
- **Facts are selected by content** (the test's own correlation and event ids), never by position or topic count (#8 id 74).
- **Synchronise on durable terminal evidence, never on a transient live column** (#7's third-pass ruling, #7 `progress/history.md` line 838): a `saga_commands` row reaching `sent` / `parked`, a `processed_events` row for the fact's id, a `saga_ignored_facts` row for (`correlation_id`, `event_type`, `marker`), an `outbox` row of the expected type. Never poll `orders.status` for an intermediate status the saga passes through.
- **The wait's predicate is the assertion's predicate** (#8 D4): the wait helper takes the same predicate object the assertion then evaluates once more; its docstring names the trap (a weaker wait satisfied by an earlier iteration's row).
- **State gates before publishing** (#8 D3): a test that publishes a fact whose precondition overlaps a relay-published fact first waits for evidence that the earlier fact was consumed (e.g. the `stock.reserve` row exists), never a sleep.
- **Isolate before attributing** (#8 D5): a red run in this feature's own suite is explained only after the failing test has been looped under the mutation the new explanation implies; a control leg (the unfixed code through the same vehicle) is run before any "N/N green" claim.

## 15. The live stack — designed, not discovered

With phases 9 and 10 unbuilt, the deployed stack has **no responder on any of the six subjects**. Expected steady state, recorded rather than left to surprise: on first boot the consumer reads `otc.orders.facts.v1` from the earliest offset (SO1); every `order.placed.v1` already there (whatever orders feature 15's live verification placed; the topics may also be empty after a recreate) is processed: one `processed_events` row, no status change (R19), one `stock.reserve` row, one fast-path dispatch answering *no responders* three times in ≈1.5 s, then **parked**, re-attempted on capped back-off. An order placed live through `orders.create` behaves identically. When feature 17's responder appears, the next sweep succeeds unattended (the recovery story and the crash story are one mechanism). The implementer records the observed rows (or the choice of a clean slate, and why) in `progress/impl_order_saga_orchestrator.md` (task 14.2).

## 16. Feature boundaries

| Feature | What it inherits from this one | What it must do |
|---|---|---|
| **42** (built; see the amendments in §9.2 and §9.5) | `SagaCommandRpcError(code)`; the status writes in one module; `varchar(10)`; the sweeper's explicit status predicate | the nine-code terminal set over the generated `Code` enum, a `rejected` end state, the dispatcher short-circuit, the sweeper exclusion (`requirements.md` §5) |
| **41** | the variant-tuple table; `SagaCommandKind.CREDIT_RELEASE` and its payload builder; the order-row lock | SA-4's rows and the late-approval branch; the accepted-operator-cancel query guarded against a real database by substitution (#8 id 91); the race against forward progress in both outcomes (#8 id 62); the operator note (#8 id 71, with feature 24 for the timeline) |
| **27** | §9.8's four seams | `R16`, R29's dead-letter case (two columns + marker, its migration), metrics, `traceparent`; re-run the SO9 arms after the retry wrapper (#8 id 94) |
| **31 / 32** | — | R24's API half; R28's e2e half |

## 17. Gate points, and what was decided without one

**The rule.** A row where #7 and #8 decided the *behaviour* identically and only the *mechanism* is Python's (the ledger's L1 – L5, L8 – L13, L16 – L31) is decided, with its citations. A question goes to the gate only when #7 and #8 disagree on behaviour or handed the decision to #9.

### 17.1 Open for the gate

**Gate outcome (maintainer, 2026-10-06): approved — G1, G2 and G3 decided as recommended below** (G1 one task per command, maximum 256, overflow to the durable pending row; G2 #8's value for all three; G3 closed without an `SA-6`).

**G1 — the fast-path concurrency model (SO13).** *Disagreement:* #7 ran every dispatch concurrently and unbounded (`@nestjs/cqrs` `mergeMap`, L6); #8 ran a bounded pool of 8 behind a 1 024-slot channel and accepted id 88's residual (*N stuck dispatches stall the N+1th*). **Recommendation: one task per command in a lifespan-owned `TaskGroup`, an in-flight maximum (default 256, refused below 1), and a signal beyond the maximum dropped to the durable pending row, never queued** (§8). *Evidence:* acceptance item 5 says *"without head-of-line blocking"*, which #8's model does not meet by its own record (id 88); asyncio tasks copy the context, so the trace-context requirement is met without #8's later capture fix (L7); the drop-to-durable rule is #8's own `DropWrite` guarantee; the maximum turns a burst into bounded sweeper latency (≤ 40 s) instead of unbounded concurrent requests; no degree setting exists to misconfigure (#8 id 90). *If overruled toward #8's pool:* stop and re-spec §8, SO13 and tasks group 6.

**G2 — three parameters where #7 and #8 differ without a stated reason.** (a) `CompensationStep.summary` on the credit-rejection cancel: #7 `"stock released — reason: credit_rejected"` (`application/saga-steps.ts:134-145`), #8 `null` (`src/Orders/Application/Sagas/SagaStepTable.cs:118`). (b) Sweeper batch: #7 100 (`saga.config.ts:24`), #8 20 (#8 `design.md` §6.4). (c) Park back-off: #7 `30 s × 2^(cycles−1)`, #8 `30 s × 2^cycles`. **Recommendation: #8's value for all three** — #8 is #9's direct source, its wire output is what #9's parity tests are pinned to (summary `null` keeps `order.cancelled.v1` semantically equal to #8's), and none of the three is constrained by `specs/shared/` (summary is optional; batch and back-off satisfy SO5 either way). The env-variable names stay #7's.

**G3 — the two promotion candidates #7 raised and #8 handed to #9** (`requirements.md` §6): (a) commit-before-issue as a normative sentence in saga.md §6; (b) a durable medium for R25's record. **Recommendation: close both without an `SA-6`.** *Evidence:* all three builds realise both identically (#7 `saga-fact-handler.ts:92-216` and `saga-ignored-facts.repository.ts`; #8 `design.md` §4.4, §5.4; #9 §6.3, §7.4); an amendment costs a byte-identical edit in three repositories, every README registry and every `progress/history.md`, plus re-checking #7 and #8 against new wording; the trilogy has no fourth build for the sentence to protect; and R25's matrix case already reads *"records the observed and expected status"*, which every build asserts against a durable row. *If overruled:* the amendment is `SA-6`, written and committed on its own before this feature's implementation, applied to #7 and #8 in the same session.

### 17.2 Decided (#7 and #8 agree, or #8 superseded #7 with a recorded reason, and Python forces no difference)

The step table's rows and preconditions (0 divergences in #7, transcribed); the R29 split and the R16 deferral (§1.1 of `requirements.md`); commit-before-issue with a durable owed-command row and the sweeper as the guarantee (SO3); the in-line policy 5 000 / 3 / 500 (SO4); park-and-retry-forever until feature 27 (SO5); a business rejection is a resolved reply (SO6); the reason mapping and one compensation step from the observed fact (SO7); `unknown_order` acknowledged (SO8); a durable ignored-fact table (§7.4); idempotent enqueue on (`order_id`, `command`) (L10); #8's lease over #7's lease-less claim (L11, #8's recorded reason); `dispatch_claimed` for the sweeper (L12, #8's recorded defect); malformed envelope logged and acknowledged, poisoned processing redelivered (L23); one consumer, group `orders.saga`, earliest, one record at a time (L3 – L5); ten fact commands, five dispatch-owed events and the `order_sagas` handlers as a parity cost (§7.7); the order-row lock (#9's own approved spec, and #8's final state); 42's and 41's boundaries (§16); no migration (§12.4); no `traceparent` until feature 27 (§11); `SAGA_CONSUMER_ENABLED` (a #9 test-isolation knob modelled on #9's own `OUTBOX_RELAY_ENABLED`, no behaviour of the saga depends on it).

## 18. Inherited findings → decision or task

| Finding | Disposition in #9 | Where |
|---|---|---|
| #8 id **80** (single fast-path worker, head-of-line) | **Avoided**: per-command tasks; reproduced first with the sweeper disabled, armed by a sequential drain | tasks 6.3, 13.4 |
| #8 id **88** (parallelism bounds the stall) | **Avoided** by design (G1): no command waits for another; overflow drops to the durable path | tasks 6.4, 13.4 |
| #8 id **89** (concurrency asserted only at unit level) | **Avoided**: SO13 integration case through the real lifespan, real NATS, real table; armed by kind | task 13.4 |
| #8 id **90** (silent clamp, degree ≤ 0 dispatches nothing) | **Avoided**: no degree; `fast_path_max_in_flight < 1` refused at boot, named | task 9.2 |
| #8 id **110** (reply decode unguarded) | **Avoided**: SO15 at unit and integration level, six subjects | tasks 4.4, 4.6 |
| #8 id **48** (fresh headers per call unguarded) | **Avoided**: identity test over two calls | task 4.5 |
| #8 id **51** (hand-retyped payload key lists) | **Avoided by construction**: generated models, drift-tested | §4 |
| #8 id **94** (SO9 arm satisfied by an in-process retry) | **Avoided here**: SO9 reads the broker's committed offset and uses a restarted consumer; **carried** to feature 27 as "re-run SO9's arms after the retry wrapper" (leader to attach) | tasks 3.9, 3.10; §9.8 |
| #8 id **62** (operator cancel races forward progress) | **Split**: the saga-side lock built and armed here (SO17); the race and SA-4's both-outcome proofs are feature 41's (already in 41's acceptance item 3) | task 7.1; §16 |
| #8 id **71** (operator note; triggering envelope bytes) | **Assigned**: note → features 41 / 24; envelope bytes → feature 27's migration | §9.8, §16 |
| #8 id **91** (accepted-cancel query unguarded in #7) | **Assigned** to feature 41, which builds the query; the leader should attach "guarded against a real database, armed by substitution" to 41 | §16 |
| #8 feature 16 D1 (committed offset inferred) | Read from the broker | task 3.9 |
| #8 D2 (round 1) / production double-claim | `dispatch_claimed`; armed by substituting `dispatch` | task 8.8 |
| #8 D3 (unsynchronised publish racing the relay) | State gates | §14.3, task 10.3 |
| #8 D4 (wait weaker than the assertion) | Wait predicate = assertion predicate | §14.3, task 10.1 |
| #8 D5 (arming credited to the wrong defect) | Isolate before attributing; control leg | §14.3, task 14.4 |
| #7 D1 (duplicate enqueue poisons the partition) | `ON CONFLICT DO NOTHING`; the mid-compensation case in the sweep | tasks 7.4, 10.3 |
| #7 D2 (`Date.now()` in the dispatcher) | Clock port everywhere | task 8.4 |
| #7 D3 (R26's integration case survived) | R26 integration case armed | task 11.6 |
| #7 D5 (group id suffixed by the framework) | Group read back from the broker | task 3.11 |
| #7 third-pass ruling (transient-column wait) | Durable terminal evidence only | §14.3 |
| `review_shared_kernel.md` Q2 (`ORD-000000`) | SO12, behaviour + structure | task 10.4 |

## 19. Non-goals

No migration and no schema change (a missing column is a design error to bring back here). No change under `services/orders/src/otc_orders/domain/`, `services/orders/alembic/`, `packages/` or other services. No edit to the canonical `idempotent_consumer.py` or `consumer_name.py`. No `R16`, DLQ, `order.saga_failed.v1`, metrics or tracer (27). No terminal `RpcError` split (42). No SA-4 rows, no `orders.cancel` (41). No responder under `src/`. No edit to `specs/shared/` beyond column 5 of R19 – R29 and the derived counts, and none to `specs/orders_aggregate/` or `specs/outbox_and_idempotency/`.
