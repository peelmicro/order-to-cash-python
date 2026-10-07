# Design — `outbox_and_idempotency` (feature 14, Python 3.14 / SQLAlchemy 2.1 / asyncpg / aiokafka, assessment #9)

> **Where the value of this document is.** The requirements were inherited (`R11` – `R18`, `OI1` – `OI16`); the realisation was not. Everything below is #9's: which modules, which `AsyncSession` boundary, which isolation level and why PostgreSQL forces it, which SQL claims a row, how an asyncio task loops without overlapping, where `Any` from an untyped Kafka client is stopped, how a duplicate is detected without aborting a PostgreSQL transaction, and how the relay survives a deadlock and a poison row inside `run_once`. §2 (the ported-idiom ledger) and §12 (the gate points) are what a reviewer should read first.
>
> Authorities: `specs/shared/requirements.md` §2 (R11 – R18), `specs/shared/domain-model.md` §7.1 (envelope) and §8 rule 5 (*aggregates emit; infrastructure publishes*), `specs/shared/saga.md` §6, `specs/shared/asyncapi.yaml` (`ordersFacts` channel, `Envelope`, `FactHeaders`), and — binding — [`specs/orders_aggregate/design.md`](../orders_aggregate/design.md) §7.3 (the four events), §7.6 (collection and drain), §9 (the persistence contract). Citations of the predecessors are to the checkouts on disk: `../order-to-cash-nestjs` (#7) and `../order-to-cash-dotnet` (#8).

## 0. Scope

| In scope | Out of scope (owner) |
|---|---|
| `otc_shared_kernel.event_envelope` — the pure `R11` guard | Any other kernel change |
| `otc_contracts.envelope` — generic `Envelope[P]`; `otc_contracts.wire.wire_instant` | Generated code (`otc_contracts/generated/**` is never edited) |
| `otc_orders.application.ports` — `Clock`, `UnitOfWork` / `OrdersTransaction`, `OrderRepository` | Command and query handlers, the dispatcher wiring — features 15, 16 |
| `otc_orders.infrastructure.persistence` — unit of work, repository, row mapper | Order-number allocation (`sequences.py` stays as is) — feature 15 |
| `otc_orders.infrastructure.outbox` — payload mapper, writer, row → wire mapper, relay, relay task, Kafka publisher, topic, settings | Lag and DLQ-depth metrics, trace propagation — feature 27 |
| `otc_orders.infrastructure.messaging.idempotent_consumer` — **canonical** copy | The Kafka consumer task that calls it — feature 16; other services' copies — features 17 – 24 |
| One import-linter contract; census updates in four existing guards | `R16` (retry, backoff, `.dlq`) — feature 27 |

### 0.1 Designed here, built elsewhere

- **Lifespan wiring.** `services/orders/src/otc_orders/presentation/app.py` has an empty lifespan and there is no `composition.py`; CLAUDE.md makes `composition.py` the only place adapters are chosen, and feature 15 creates it (its acceptance item 6). #8 drew the identical line (#8 `design.md` §2.3: *"until feature 15 calls `AddOrdersOutbox`, the relay runs only in tests"*). So this feature ships the relay task and its factories, proven by tests that drive them directly; **feature 15 starts the task in the lifespan and awaits it on shutdown**. The leader should attach that sentence to feature 15's acceptance (this spec cannot edit `feature_list.json` beyond feature 14's status).
- **The consumer shell** (consumer group, offset commit after the transaction, one `AsyncSession` per message) — §6.5, built by feature 16.
- **The Fulfillment and Billing relays** — their `outbox` tables exist and are proven identical (`OI11`); their copies land with features 17 – 22, which also add the relay-family parity guard #8 added at the same point (#8 `tests/Orders.UnitTests/OutboxRelayParityTests.cs`).

## 1. Layout

```
packages/shared_kernel/src/otc_shared_kernel/
  event_envelope.py        EVENT_TYPE_PATTERN, IncompleteDomainEventEnvelopeError, validate_domain_event_envelope(...)

packages/contracts/src/otc_contracts/
  envelope.py              class Envelope[P](WireModel): the seven fields in asyncapi order
  wire.py                  + wire_instant(value) -> datetime   (truncate to whole ms; aware UTC only)

services/orders/src/otc_orders/application/ports/
  __init__.py
  clock.py                 class Clock(Protocol): def now(self) -> datetime
  order_repository.py      class OrderRepository(Protocol): save / get_by_id / get_by_reference
  unit_of_work.py          class OrdersTransaction(Protocol) (.orders); class UnitOfWork(Protocol) (.begin())

services/orders/src/otc_orders/infrastructure/
  clock.py                 SystemClock (wire_instant(datetime.now(UTC)))
  settings.py              + OutboxRelaySettings, KafkaSettings (pydantic-settings, no populate_by_name)
  persistence/unit_of_work.py   SqlAlchemyUnitOfWork, SqlAlchemyOrdersTransaction (.orders, .session)
  persistence/order_repository.py  SqlAlchemyOrderRepository
  persistence/order_mapper.py      rows <-> OrderSnapshot / Order (specs/orders_aggregate/design.md §9)
  outbox/__init__.py
  outbox/payloads.py       OrderEvent -> otc_contracts payload model (one function per event class)
  outbox/writer.py         OutboxWriter: events -> outbox rows (R11 guard, catalogue check, Envelope[P])
  outbox/wire.py           outbox row -> PublishableFact (key, value bytes, headers)
  outbox/publisher.py      FactPublisher (Protocol), PublishableFact, FactPublicationError
  outbox/kafka_publisher.py  KafkaFactPublisher — the ONLY module that imports aiokafka
  outbox/topic.py          ORDERS_FACTS_TOPIC = "otc.orders.facts.v1"
  outbox/relay.py          OutboxRelay.run_once() -> RelayResult; PoisonedRow; deadlock classifier
  outbox/relay_task.py     OutboxRelayTask.run(stop: asyncio.Event)
  messaging/__init__.py
  messaging/idempotent_consumer.py   CANONICAL: ConsumptionOutcome, IdempotentConsumer[T]
  messaging/consumer_name.py         per-service, identical path in every write model: ConsumerName (amendment A1, §6.4)
```

`services/orders/src/otc_orders/domain/**` gains nothing. The `FactPublisher` protocol is deliberately in `infrastructure.outbox`, not in `application.ports`: only the relay uses it, and placing it below `application` lets the existing `layers-orders` contract forbid any handler from reaching a publisher (§9.1). #8 put `IFactPublisher` in `Application/Ports` (#8 `design.md` §1), where a handler could have injected it; that is the one layout difference from #8 and it is deliberate.

## 2. The ported-idiom ledger

*#7 relied on X; #8 supplied it with Y; in #9 it is supplied by Z.* Every "#7" and "#8" cell is read from the checkouts, with a file and line. **Guard** names the `tasks.md` task; every guard on a property #9 hand-builds is an `[ARM]` task.

| # | Idiom | #7 relied on | #8 supplied it with | #9 supplies it with | Guard |
|---|---|---|---|---|---|
| L1 | One transaction spans aggregate rows, outbox rows and the dedup row | A branded `TransactionContext` threaded through `save(order, tx)` (`apps/orders/src/infrastructure/persistence/drizzle-unit-of-work.ts:10-11, 70-73`) | The scoped `DbContext` is the transaction; `EfCoreUnitOfWork` opens one `IDbContextTransaction` (`src/Orders/Infrastructure/Persistence/EfCoreUnitOfWork.cs:35-54`) | `UnitOfWork.begin()`: an async context manager owning **one** `AsyncSession` and one transaction; the repository and the session are reachable only through the transaction object it yields, so two collaborators cannot sit in two transactions. No module-level or `contextvars` session (CLAUDE.md: a session belongs to one request or message) | 3.10, 6.2 |
| L2 | Isolation of the claim and of the unit of work | InnoDB locking reads are *current* reads at its default `REPEATABLE READ`; `db.transaction(...)` is opened with no isolation argument (`outbox-relay.ts:121`) | `IsolationLevel.ReadCommitted` pinned explicitly (`OutboxRelay.cs:88`, `EfCoreUnitOfWork.cs:54`) | **The engine differs.** PostgreSQL at `REPEATABLE READ` raises `40001` on a locking read of a row a concurrent transaction updated and committed, where InnoDB reads the current version. Every transaction this feature opens pins `READ COMMITTED` per transaction (`await session.connection(execution_options={"isolation_level": "READ COMMITTED"})` before the first statement), never inheriting the engine's or server's default. Probed: the PostgreSQL direction only, by guard 4.11; the InnoDB direction is cited, not probed | 4.18 |
| L3 | A claim skips rows another relay holds | `FOR UPDATE SKIP LOCKED` (`outbox-relay.ts:128`) | `WITH (UPDLOCK, READPAST, ROWLOCK)` — MS-SQL has no `SKIP LOCKED` (`OutboxRelay.cs:111`) | `select(Outbox)…with_for_update(skip_locked=True)` → `FOR UPDATE SKIP LOCKED`, native as in #7. Skip-versus-block is **measured**, then armed the other way (§5.2) | 4.15, 4.17 |
| L4 | `seq` follows append order inside one transaction | One recorder `insert` per event in a loop (`apps/orders/src/infrastructure/outbox/outbox-recorder.ts:24`), MySQL `AUTO_INCREMENT` | EF Core batched `Add`s reordered `IDENTITY` (`Seq = 3,2,5,1,4`; #8 `progress/history.md` line 744); fixed by one awaited raw `INSERT` per row (`OutboxWriter.cs:40`) | SQLAlchemy's unit of work may batch same-table inserts (`insertmanyvalues`); #9 does not rely on its ordering: `session.add(row)` then `await session.flush()` **per outbox row**, in raise order, so PostgreSQL's identity counter is the only thing `seq` depends on. Whether one batched flush would also preserve order is measured and recorded, not relied on | 4.8 |
| L5 | Stamp only after acknowledgement | Stamp after the awaited publish (`outbox-relay.ts:211-218`) | `ExecuteUpdateAsync` after `PublishAsync` (`OutboxRelay.cs:159-169`) | Same order: publish (bounded), then `update(Outbox)…values(published_at=…)`, then commit | 4.7 |
| L6 | A failed publish leaves the claim transaction rolled back | **Commits** an empty transaction (`outbox-relay.ts:199-204`; #7 review D7) | `transaction.RollbackAsync` (`OutboxRelay.cs:155`) | A private `_CycleAborted` raised inside `async with session.begin()` rolls back; it is caught **outside** the block, logged, and turned into a result. The only commit is the success path. Observed, not inferred: the test counts `after_commit` / `after_rollback` session events | 4.11 |
| L7 | The publish is bounded | Initially dead configuration (#7 review D2), later `withPublishTimeout` (`outbox-relay.ts:29-43, 168`) | Linked `CancellationTokenSource.CancelAfter` (`OutboxRelay.cs:128-129`) | `async with asyncio.timeout(publish_timeout)` around the publish; the deadline raises `TimeoutError`, which the cycle treats as a publish failure | 4.11 |
| L8 | Shutdown cancellation is not a publish failure | n/a (no cancellation token in `runOnce`) | `catch … when (!(ex is OperationCanceledException && cancellationToken.IsCancellationRequested))` (`OutboxRelay.cs:135`) | `asyncio.CancelledError` is a `BaseException`: the cycle catches only `FactPublicationError` and `TimeoutError`, the loop only `Exception`; nothing in the feature writes `except BaseException` or a bare `except:`. A deadline of `asyncio.timeout` raises `TimeoutError`; an outer cancellation propagates as `CancelledError` and the session's context manager rolls back | 5.4 |
| L9 | A producer-internal retry neither reorders nor duplicates | kafkajs `idempotent: true`, `maxInFlightRequests: 1` (`apps/orders/src/infrastructure/outbox/kafka-fact-publisher.ts:21-22`) | `EnableIdempotence`, `Acks.All`, `MaxInFlight = 5` (`KafkaFactPublisher.cs:41-44`) | `AIOKafkaProducer(enable_idempotence=True, acks="all")`. aiokafka has no `max_in_flight` parameter; the implementer reads the installed aiokafka source, cites file and line for its per-partition in-flight behaviour in the impl report, and the unit guard asserts the keyword arguments the adapter passes | 4.4 |
| L10 | The partition key is the order id, rendered identically | `envelope.correlationId` string (`outbox-relay.ts:159`) | `Guid.ToString()` default `"D"` format (`OutboxRelay.cs:225`) | `str(correlation_id).encode("utf-8")`: lowercase, hyphenated, the golden envelopes' shape. aiokafka's default partitioner is murmur2; equality of partition numbers with #7/#8 is **not claimed** (nothing reads it) | 4.13 |
| L11 | The envelope is rebuilt from the stored row alone, instants as UTC | `outboxRowToEnvelope`, `toISOString()` (`apps/orders/src/infrastructure/outbox/outbox-envelope-mapper.ts:13-29`) | `JsonElement` pass-through, `new DateTimeOffset(row.OccurredAt, TimeSpan.Zero)` (`OutboxEnvelopeMapper.cs:28-43`) | `Envelope[dict[str, Any]]` built from the row's columns, `payload=json.loads(row.payload)`, written by `to_wire_json`. asyncpg returns `timestamptz` as an aware UTC `datetime`, and `format_instant` refuses a naive one, so #7's D4 / #8's implicit-offset class has no silent path | 3.13, 4.14 |
| L12 | The stored payload is the committed text | MySQL `json` normalises key order (CLAUDE.md: the artefact that leaked onto #7's wire) | `nvarchar(max)` preserves it | `json` column (never `jsonb`) via `RawJson`, read as `payload::text` so asyncpg's json codec never re-serialises it (`services/orders/src/otc_orders/infrastructure/persistence/types.py:1-27`; proven by `test_outbox_payload_is_read_back_byte_identical`) | existing + 4.14 |
| L13 | One serializer | `JSON.stringify` | `JsonWire.Options`, no second instance (`OutboxEnvelopeMapper.cs:43`) | `otc_contracts.to_wire_json` for the payload text **and** the envelope bytes (compact separators, `ensure_ascii=False`, `allow_nan=False`); `json.dumps` and `model_dump_json` appear nowhere on the outbox path; `json.loads` appears once, in the row → wire mapper | 4.14 |
| L14 | Instant precision agrees between store and wire | `Date` holds milliseconds | `datetime2(3)`, and #8's mapper converts in one place | `timestamptz(3)` **rounds** and `format_instant` **truncates**. `wire_instant` truncates to whole milliseconds, and the writer, the row mapper and `SystemClock` apply it to every instant before it is stored or enveloped (`OI19`) | 3.14 |
| L15 | Duplicate delivery is detected by the unique index, never by a `SELECT` | `ER_DUP_ENTRY` caught (`apps/orders/src/infrastructure/messaging/processed-events.repository.ts:25, 33-39`) | SQL errors 2601 / 2627 caught (`ProcessedEventLedger.cs:44-65`) | **The engine differs:** any error aborts a PostgreSQL transaction. `insert(processed_events).values(…).on_conflict_do_nothing(index_elements=["event_id","consumer"]).returning(id)`: no row back means duplicate, with no exception and no aborted state. A concurrent second insert of the same key waits on the first transaction and returns no row once it commits — the same serialisation #8 got from the index lock (`OI10`) | 6.4 – 6.6 |
| L16 | Events are cleared only after the commit | `pullDomainEvents()` (destructive) **before** the writes (`order.repository.ts:74`), safe only because callers re-derive the aggregate (#7 review D9: demonstrated, not guarded) | `ClearDomainEvents()` after `SaveChangesAsync` (`EfCoreOrderRepository.cs:143-147`) | The repository reads `order.domain_events` (non-destructive, `entity.py:42-44`) when it writes rows; the unit of work calls `clear_domain_events()` on every aggregate saved in the transaction **after** the commit returns. A retry from the same instance after a rollback therefore writes the events again, exactly once | 3.11 |
| L17 | A deadlock victim inside the relay | Not handled: the relay calls `db.transaction` directly (`outbox-relay.ts:121`), outside the unit of work's retry (`drizzle-unit-of-work.ts:27-31`), and the loop has no `catch` (`outbox-relay.service.ts:63-71`) | `DeadlockRetryExecutionStrategy`: error 1205 only, 3 attempts, 200 ms (`DeadlockRetryExecutionStrategy.cs:91-104`, used at `OutboxRelay.cs:80`) | `run_once` retries the whole cycle on SQLSTATE `40P01` only, 3 attempts, 200 ms (#8's numbers). The SQLSTATE is read from `sqlalchemy.exc.DBAPIError.orig.sqlstate` (SQLAlchemy 2.1.3 `dialects/postgresql/asyncpg.py:972-983`) through one typed helper | 4.6, 4.19 |
| L18 | Overlapping cycles are impossible | Self-scheduling `setTimeout` chain (`outbox-relay.service.ts:54-72`) | One loop over `PeriodicTimer` (`OutboxRelayBackgroundService.cs:25-30`) | One `while` loop: `await relay.run_once()`, then an interruptible sleep `await asyncio.wait_for(stop.wait(), timeout=interval)` (a self-scheduled `asyncio.sleep` that `stop` can cut short); never a fixed-interval timer, never a second task | 5.2 |
| L19 | A failed cycle does not kill the relay | No `catch` around `runOnce()`: an unhandled rejection crashes the process (#8 `feature_list.json` id 111 disposition) | `catch (Exception ex) when (ex is not OperationCanceledException)`, log, next tick (`OutboxRelayBackgroundService.cs:38-47`) | `except Exception` per cycle, logged with `exc_info`, then the next interval; `CancelledError` propagates (L8). #8's shape, chosen over #7's for the reason #8's 111 disposition records | 5.3 |
| L20 | Shutdown waits for the in-flight cycle | `onApplicationShutdown` awaits `inFlight` (`outbox-relay.service.ts:43-52`) | `StopAsync` waits for `ExecuteAsync` (#8 test `OI6_RelayLoop_StopAsyncWaitsForTheInFlightCycleToFinish`) | `stop.set()` ends the loop after the in-flight cycle completes (bounded by `OI14`); the owner awaits the task. A cycle is **not** cancelled mid-publish by a normal stop, because a cancellation after an acknowledgement and before the stamp turns into a duplicate on restart | 5.2 |
| L21 | A poison row | Reconstruction outside the publish `try` (`outbox-relay.ts:145-146`): escapes `runOnce` and crashes the process | Reconstruction outside the publish `try` (`OutboxRelay.cs:124`): escapes `RunOnceAsync`, caught by the loop, whole batch retried every tick | Caught **inside** `run_once`, per row: the clean prefix is published and stamped, the poison row and everything after it stay unstamped, nothing raises (`OI18`, gate point G1) | 4.12 |
| L22 | Only infrastructure may hold the producer client | ESLint rule scoped to `domain/` | NetArchTest `FactPublisherConfinementTests` | import-linter `forbidden` contract over every service's `application` and `presentation` (the `domain-purity` contract already covers `domain`); the `FactPublisher` protocol in `infrastructure.outbox` (§1) | 7.2 |
| L23 | Event-loop affinity of the producer and the engine | n/a: one Node loop | n/a: thread pool; DI scopes | `AIOKafkaProducer` and asyncpg pools bind to the loop that creates them. `KafkaFactPublisher.__init__` performs no I/O and constructs **no** aiokafka object; `start()` constructs and starts the producer inside the running loop, `stop()` stops it. The relay receives an `async_sessionmaker` and a publisher; it never creates an engine or a producer. Test fixtures create both in the test's own loop scope (§11.2) | 4.4 |
| L24 | `Any` from an untyped client | TypeScript types | C# types | `aiokafka.*` has `ignore_missing_imports` (the only mypy override, `pyproject.toml`); `kafka_publisher.py` is the only importer and types the three calls it makes through a private `Protocol`, returning only `None` or our own types; `DBAPIError.orig` is typed `BaseException` or `None`, read once through a helper returning a `str` or `None`. `mypy --strict` (`warn_return_any`) is the guard | 7.1 |
| L25 | Every future's exception is retrieved | One kafkajs `send` promise per batch | `await` of every `ProduceAsync` | The publisher awaits the per-record futures with `asyncio.gather(*futures, return_exceptions=True)` and raises `FactPublicationError` if any failed, so no "Future exception was never retrieved" is left behind (`PytestUnraisableExceptionWarning` is an error in this repository's pytest configuration) | 4.10 |
| L26 | `eventType`'s pattern is anchored at the end of the text | ECMAScript `$` (end of input) | `[GeneratedRegex(@"^[a-z]+\.[a-z_]+\.v[0-9]+$")]` (`src/SharedKernel/DomainEventEnvelope.cs:52-53`); whether .NET's `$` accepts a trailing newline was not probed and is not claimed | **Python's `re` `$` matches before a trailing `\n`**: probed this session, `re.match(r'^[a-z]+\.[a-z_]+\.v[0-9]+$', 'order.placed.v1\n')` matches, `re.fullmatch` does not, and the generated pydantic `Envelope` refuses it. The kernel guard uses `re.fullmatch` with the pattern written without anchors | 1.4 |
| L27 | Closed set of consumer names | String literal type | `enum ConsumerName` + tokens + `Parse` (#8 `design.md` §6.1) | `enum.Enum` (not `StrEnum`) with explicit values `orders.saga`, `projector`, `notifications`, the feature-13 convention (`specs/orders_aggregate/design.md` L1) | 6.6 |

**Python porting questions answered** (CLAUDE.md): integer division — none on this path (money is copied as `int` minor units; no arithmetic); JSON serialisation — L12, L13; event-loop affinity — L23; task cancellation and exception propagation — L8, L19, L20, L25; typing gaps — L24.

## 3. Port the guards too

#8's tests of this mechanism, enumerated by content (`grep -rl "OutboxRelay\|IdempotentConsumer\|OutboxWriter\|DomainEventEnvelope\|KafkaFactPublisher\|EfCoreUnitOfWork" ../order-to-cash-dotnet/tests --include=*.cs`, 45 files), classified:

| #8 test | #9 |
|---|---|
| `SharedKernel.UnitTests/DomainEventEnvelopeTests.cs` (accept, eight per-field refusals, accept-every-pattern) | **Ported**, plus the trailing-newline case (L26) |
| `OutboxAtomicityTests` › R13 ×2, OI9 | **Ported**; OI9 strengthened to retry from the same instance (#7 D9) |
| `OutboxEnvelopeTests` › R12, OI1 ×2, R11 catalogue | **Ported** |
| `OutboxRelayTests` › R14, OI2 ×2, OI3, OI8, OI14 | **Ported**; OI8 asserts the log records' fields; OI14 asserts rollback by session events |
| `OutboxRelayTests` › `OtcDlqDepth_…CallsTheGaugeExactlyOnce` | Not applicable: metrics are feature 27 |
| `OutboxRelayConcurrencyTests` › OI4, OI5, OI13 | **Ported**; OI13 split into the measured skip and the isolation pin |
| `OutboxRelayDeadlockTests` › the constructed deadlock victim | **Ported** as `OI17` with a PostgreSQL cycle (§5.7) |
| `DeadlockRetryExecutionStrategyTests` (five classifier cases) | **Ported** onto SQLSTATE (§5.7) |
| `IdempotentConsumerTests` › R17 ×2, R18, OI10, the per-pair case | **Ported**; R18 asserts all three negatives (#8 D2, D3) |
| `OutboxWireParityTests` › OI15 ×2, R11 published, SA2 ×2 | **Ported** (the SA-2 note cases included) |
| `FactPartitioningTests` › R15 | **Ported**, with a fixture whose two orders provably land on different partitions |
| `KafkaFactPublisherConfigTests` › OI7 | **Ported** onto the adapter's keyword arguments |
| `OutboxRelayLoopTests` › OI6 ×2 | **Ported**, plus survive-a-failed-cycle and propagate-cancellation |
| `IdempotentConsumerParityTests` (four cases) | **Ported**, with a temporary-tree sentinel so case 1 is not vacuous at n = 1 (#8 D4) |
| `OutboxClaimProjectionTests` | Deliberately not ported: EF's `FromSql` needs every mapped column listed by hand; #9's claim is `select(Outbox)`, so the projection is the mapper's, not a hand-kept list |
| `OrdersOutboxRegistrationTests` | Deliberately not ported here: there is no container; the composition root and its boot validation are feature 15's |
| `OrdersFactTopicTests` (inside #8 `tasks.md` E3) | **Ported**: the constant equals the `ordersFacts` channel `address` read from `asyncapi.yaml` |
| `Seed.IntegrationTests` › the relay finds nothing to publish in a seeded database | **Ported** to the seed's integration suite |
| `OutboxRelayParityTests`, `FactRetryDispatcherParityTests`, `TraceContextPropagationTests`, `MetricsExposureTests`, `RealInfraMetricsProvenanceTests`, Billing / Fulfillment / Projector / Gateway files | Not applicable: features 17 – 27 |

## 4. The writer — `R11`, `R12`, `R13`, `OI1`, `OI9`, `OI19`, `OI20`

### 4.1 Ports (`application/ports`)

```python
class Clock(Protocol):
    def now(self) -> datetime: ...                     # aware UTC, whole milliseconds

class OrderRepository(Protocol):
    async def save(self, order: Order) -> None: ...    # insert if new to this transaction's repository, else update
    async def get_by_id(self, order_id: UniqueId) -> Order | None: ...
    async def get_by_reference(self, reference: OrderNumber) -> Order | None: ...

class OrdersTransaction(Protocol):
    @property
    def orders(self) -> OrderRepository: ...

class UnitOfWork(Protocol):
    def begin(self) -> AbstractAsyncContextManager[OrdersTransaction]: ...
```

`begin()` commits on a clean exit, rolls back on any exception and re-raises it unchanged; it never swallows. The clock port lands here, not in feature 15, for the reason #7 and #8 both gave (#7 `tasks.md` C1, #8 `design.md` §4.6): the writer and the relay are its first users. `SystemClock.now()` returns `wire_instant(datetime.now(UTC))`.

### 4.2 `SqlAlchemyUnitOfWork`

Constructed with the lifespan's `async_sessionmaker[AsyncSession]` (`expire_on_commit=False`), a `Clock` and an `OutboxWriter`. `begin()`:

1. opens one `AsyncSession` (`async with sessions() as session`), then `async with session.begin()`;
2. pins the isolation level: `await session.connection(execution_options={"isolation_level": "READ COMMITTED"})` before any statement (L2);
3. yields a `SqlAlchemyOrdersTransaction` holding that session and a `SqlAlchemyOrderRepository` bound to it; the infrastructure class also exposes `.session` (the application protocol does not);
4. on a clean exit the `begin()` block commits; **after** the commit returns, it calls `clear_domain_events()` on every aggregate the repository saved (L16);
5. the session is closed when the block exits, success or failure.

**No retry.** The unit of work does not retry a deadlock or any other error: a retried delegate re-runs caller code this feature cannot see (its callers arrive in features 15 and 16). #7 and #8 disagree here, which makes it **gate point G2** (§12).

### 4.3 `SqlAlchemyOrderRepository` and the mapper

The adapter lands in this feature, reversing feature 13's "14 / 15" deferral exactly as #7 (#7 `progress/history.md` line 773, *"the reversal of feature 13's deferral of the repository adapter"*) and #8 (#8 `design.md` §4.3) both did: `R13` cannot be proven against a repository that does not exist, and written here `save` is written once, with its outbox drain.

- **Mapping** is `specs/orders_aggregate/design.md` §9, column by column: codes ↔ reference-table ids resolved inside the adapter (`retailers`, `companies`, `currencies`, `products`), money as `.amount` into `bigint`, `status` and `cancellation_reason` through the domain's parse functions, `description` `or ""` on write, totals written but never read into the aggregate, lines loaded and handed to `Order.rehydrate` (which sorts them). Every instant goes through `wire_instant` before it is assigned to a column (`OI19`).
- **`save(order)`**: the repository remembers which aggregates it loaded; an order it did not load is inserted (`orders` row, `order_items` rows), a loaded one is updated (the `orders` row, and `order_items` diffed by line id: insert new, update changed, delete removed). All writes go through the ORM unit of work, so `install_range_guards` fires on every integer column (backlog 204's population rule). Then it hands `order.domain_events` to `OutboxWriter.write(session, events)` and records the aggregate for the post-commit clear.
- **`Order(` is never constructed** outside `domain/order.py`: the mapper reaches an `Order` only through `Order.rehydrate`. (Feature 15 carries the armed guard for this, its acceptance item 5; nothing here should make it fail.)
- **`get_by_reference` is exercised** by a round-trip test (#7 review D5: delivered but untested), with a cancelled order so `notes`, `cancellation_reason` and line discounts are read back.

**`OI9`, guarded rather than demonstrated (#7 D9).** The test drives a real `Order.place(...)` through `uow.begin()`, forces a failure after the rows are provably inside the transaction, and then retries **with the same in-memory `Order` instance** in a new transaction: exactly one outbox row per event, never zero, and no `orders` row without its fact. Moving the clear before the commit (or draining with `pull_domain_events()` at save time) makes it fail.

### 4.4 From domain events to outbox rows — `OutboxWriter`

For each event in `order.domain_events`, in raise order:

1. **Narrow** with `match` over the `OrderEvent` union (`OrderPlaced | OrderConfirmed | OrderCompleted | OrderCancelled`, `domain/events.py`); `case _:` raises `UnmappedDomainEventError` naming the type (#8 `tasks.md` D1). Never `cast`, never `Any`.
2. **`R11` guard:** `validate_domain_event_envelope(event_id=…, event_type=type(event).EVENT_TYPE, aggregate_id=…, correlation_id=…, causation_id=…, occurred_at=…)` (§4.6).
3. **Catalogue membership:** `EVENT_TYPE` must be a key of `otc_contracts.FACT_MODELS` and the payload model built in step 4 must be the annotation of that fact model's `payload` field; otherwise `UndeclaredFactError` (#8 `OutboxEnvelopeTests` › `R11_Outbox_RefusesToStoreAFactWhoseEventTypeIsNotInTheDeclaredFactCatalogue`).
4. **Payload** via `outbox/payloads.py`, one function per event class: `Money` → `.amount` (`int`), `OrderNumber`/`GLN` → `.value`, `Quantity` → `.value`, `UniqueId` → `.value`, enums → `.value`, `CompensationStep` → the contracts model, every instant through `wire_instant`. **No `Decimal`, no `float`, no `/`** on this path.
5. **Envelope:** `Envelope[P](event_id=…, event_type=…, aggregate_id=…, correlation_id=…, causation_id=…, occurred_at=wire_instant(event.occurred_at), payload=payload)` — validation is the second, wire-level `R11` check (pattern, UUIDs, aware instant).
6. **Row:** `Outbox(id=uuid4(), event_id, event_type, aggregate_id, correlation_id, causation_id, payload=to_wire_json(envelope.payload), occurred_at=envelope.occurred_at, published_at=None, created_at=clock.now(), trace_parent=None)`; `seq` is never assigned (identity `ALWAYS`).
7. `session.add(row)`; `await session.flush()` — **one flush per row** (L4).

The row id is a fresh UUID, deliberately distinct from `event_id` (a row is a publication record; `outbox.event_id` is `UNIQUE`, so a double write of one event fails loudly). `trace_parent` stays `NULL` until feature 27.

### 4.5 `Envelope[P]` and `wire_instant` (`otc_contracts`) — `OI19`, `OI20`

```python
class Envelope[P](WireModel):
    event_id: UUID
    event_type: Annotated[str, Field(pattern="^[a-z]+\\.[a-z_]+\\.v[0-9]+$")]
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID
    occurred_at: AwareDatetime
    payload: P

def wire_instant(value: datetime) -> datetime:   # aware only; UTC; microsecond // 1000 * 1000
```

- **Where it lives.** Hand-written in `otc_contracts/envelope.py`, not in `generated/` (generated output is never edited and is drift-tested). The generated non-generic `Envelope` (`generated/asyncapi.py:114-121`) stays and is the drift reference: a test asserts the generic class's field names, order, aliases and `event_type` pattern equal the generated class's.
- **Who uses which.** The writer uses `Envelope[<payload model>]` (typed, validated); the relay uses `Envelope[dict[str, Any]]` (pass-through of the stored payload). One class, one field order.
- **The `203` item 2 cases** (unit, `packages/contracts/tests/test_envelope_generic.py`), on a test-local `WireModel` payload holding a `datetime` and a `list[datetime]`, the envelope built by `Envelope[Local].model_validate({..., "payload": payload.model_dump(mode="python")})`: `model_dump_json() == to_wire_json()`; no instant in either output has more than three fractional digits; a `model_copy(update={"<int field>": 89.34})` of the payload placed in an envelope is refused by `model_dump_json` **and** by `to_wire_json`. Armed by reverting `WireModel._serialize`'s `_holds_datetime` replacement, and separately its `model_validate` (`wire.py:126-138`).
- **`wire_instant`** truncates (never rounds), refuses a naive value, converts a non-UTC offset to UTC. `format_instant(wire_instant(x)) == format_instant(x)` for every aware `x` (property test over a microsecond sweep).

### 4.6 The `R11` guard (`otc_shared_kernel/event_envelope.py`)

```python
EVENT_TYPE_PATTERN = r"[a-z]+\.[a-z_]+\.v[0-9]+"      # asyncapi Envelope.eventType without its anchors

class IncompleteDomainEventEnvelopeError(DomainError):
    code = "domain_event_envelope.incomplete"           # #8's code (IncompleteDomainEventEnvelopeError.cs:14)

def validate_domain_event_envelope(*, event_id: UniqueId, event_type: str, aggregate_id: UniqueId,
                                   correlation_id: UniqueId, causation_id: UniqueId, occurred_at: datetime) -> None
```

Checks, each naming the field that failed: the four ids are `type(x) is UniqueId` with a non-nil value (a frozen dataclass does not stop `None` at run time, and `dataclasses.replace` bypasses `UniqueId`'s own check); `occurred_at` is a `datetime` with `utcoffset() == timedelta(0)` (a naive instant is "absent" for the wire); `event_type` is a `str` and `re.fullmatch(EVENT_TYPE_PATTERN, event_type)` (L26). Keyword arguments rather than a protocol the events must implement, so `domain/` does not change (#8 had to edit `OrderDomainEvent` to implement `IDomainEventEnvelope`). `payload` is not checked here (the kernel knows no JSON; the writer checks it, as in #8 `design.md` §4.7). A test reads `asyncapi.yaml` and asserts `"^" + EVENT_TYPE_PATTERN + "$"` equals `Envelope.eventType.pattern` there.

The kernel gains `re` as an import: `tests/architecture/test_money_guard.py`'s `ALLOWED_ROOTS` (a census, `test_money_guard.py:90-92`) gains `"re"` with its reason (pattern matching, no numeric API), and `packages/shared_kernel/tests/test_kernel_surface.py`'s `MODULE_NAMES` gains the new module and its exports.

## 5. The relay — `R14`, `R15`, `OI2` – `OI8`, `OI13` – `OI15`, `OI17`, `OI18`

### 5.1 Shape

```python
@dataclass(frozen=True, slots=True)
class PoisonedRow:
    event_id: UUID; correlation_id: UUID; seq: int; reason: str

@dataclass(frozen=True, slots=True)
class RelayResult:
    claimed: int; published: int; poisoned: PoisonedRow | None

class OutboxRelay:
    def __init__(self, *, sessions: async_sessionmaker[AsyncSession], publisher: FactPublisher,
                 clock: Clock, batch_size: int, publish_timeout: float) -> None
    async def run_once(self) -> RelayResult
```

A plain class: no base type, no decorator, no I/O at construction, callable from a test with no app. One `AsyncSession` and one transaction per cycle (not the unit of work: the relay writes no aggregate), opened and closed inside `run_once`.

### 5.2 The claim — `OI3`, `OI4`, `OI13`

```python
select(Outbox).where(Outbox.published_at.is_(None)).order_by(Outbox.seq).limit(batch_size).with_for_update(skip_locked=True)
```

emitted as `SELECT … FROM outbox WHERE outbox.published_at IS NULL ORDER BY outbox.seq LIMIT $1 FOR UPDATE SKIP LOCKED`, at a pinned `READ COMMITTED` (L2). The implementer records the SQL as emitted (echo or a `before_cursor_execute` capture) in the impl report.

- **Selection by nullability, never by cursor** (`OI3`): no stored high-water mark exists anywhere.
- **Re-evaluation under `READ COMMITTED`:** a row another relay stamped and committed after this statement's snapshot is re-checked when it is locked; `published_at IS NULL` is false, so it is excluded. That is why the level is pinned (`OI13`).
- **Skip versus block, measured** (acceptance item 2; #8 history line 743: measure, do not assert the expected answer). Test: relay A claims and holds (its fake publisher waits on an `asyncio.Event`); relay B, on its own engine, runs `run_once` under `asyncio.timeout(3)`; B must return a **disjoint**, non-empty batch, and its elapsed time is recorded. Armed the other way twice, each with a different diagnosis recorded verbatim: (1) `skip_locked=False` — B **blocks** until A releases (expected; the test's bound fires, naming *blocked*); (2) no `with_for_update` at all — B **duplicates** A's rows (`OI4`'s intersection becomes non-empty). Both tests drive **both** relays through the production `OutboxRelay` (#8's own guard-that-did-not-guard: its first `OI13` draft re-implemented the claim inline, history line 745).
- **No lease columns, no `NOLOCK` analogue:** a dropped connection releases PostgreSQL's row locks immediately, so `OI5` needs nothing else. Ordering *between* two relays is not claimed (#8 `design.md` §5.2): `OUTBOX_RELAY_ENABLED` exists so a scaled-out deployment runs one relay per write model, and `R15` is a single-relay guarantee.

### 5.3 The cycle, and its exits

```
async with sessions() as session:
    try:
        async with session.begin():                                    # one transaction
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            rows = (await session.scalars(claim)).all()
            facts, poisoned = build_prefix(rows)                       # §5.8
            if facts:
                try:
                    async with asyncio.timeout(publish_timeout):
                        await publisher.publish(facts)
                except (FactPublicationError, TimeoutError) as error:
                    raise _CycleAborted(rows, error) from error         # leaves begin() by rollback
                await session.execute(update(Outbox).where(Outbox.id.in_(ids)).values(published_at=clock.now()))
        return RelayResult(claimed=len(rows), published=len(facts), poisoned=poisoned)   # committed
    except _CycleAborted as aborted:
        log one ERROR line per claimed row (correlationId, eventId, seq, error)       # OI8
        return RelayResult(claimed=len(aborted.rows), published=0, poisoned=None)
```

- The **only** commit is the success path (L6, `OI14`, #7 D7). A cycle with nothing to stamp commits a read-only transaction, which releases its locks exactly as a rollback would.
- Publication failure and the timeout are the two caught exceptions; everything else (a database error other than the deadlock of §5.7, a programming error) propagates out of `run_once` to the loop (§5.6), and `CancelledError` propagates (L8).
- **Partial success inside a failed batch is possible and accepted** (at-least-once; deduplication is the consumer's, §6). #8 said the same (`design.md` §5.3).
- Logging is the standard library's `logging` with `extra={"correlationId": …, "eventId": …, "seq": …}`; structured JSON logging and the bound `correlationId` on every line are feature 27's (`feature_list.json` id 27: *"correlationId in every log line"*). The `OI8` test asserts the `LogRecord` attributes, not the message text.

### 5.4 Row → wire bytes — `OI1`, `OI15`, `R11` at the producer

`outbox/wire.py: to_publishable_fact(row: Outbox) -> PublishableFact` reads the row only:

```python
envelope = Envelope[dict[str, Any]](event_id=row.event_id, event_type=row.event_type, aggregate_id=row.aggregate_id,
                                    correlation_id=row.correlation_id, causation_id=row.causation_id,
                                    occurred_at=row.occurred_at, payload=json.loads(row.payload))
value = to_wire_json(envelope).encode("utf-8")
key = str(row.correlation_id).encode("utf-8")
headers = (("x-event-type", row.event_type.encode("utf-8")), ("content-type", b"application/json"))
```

- **No `traceparent` header** and `trace_parent` stays `NULL`: feature 27 owns `R56`/`R57`; publishing without the header `FactHeaders` marks required is the documented, dated gap #7 and #8 both shipped (#7 `progress/history.md` line 782; #8 `design.md` §5.3). A fabricated header would be worse.
- **Wire parity, three named assertions** (#8 `design.md` §5.5, adopted unchanged): (1) *the relay changed nothing* — a row whose columns and payload **text** come from `tests/fixtures/golden_envelopes/order_placed_v1.json`, relayed to a real broker, consumed, equals the golden file **byte for byte**; this is a pass-through claim, not a claim that #9 reproduces MySQL's key order; (2) *the payload is semantically #7's* — a real `Order` placed with the golden business values, its stored `payload` compared with `strict_json_differences` (the comparer of `packages/contracts/tests/strict_json.py`), key order asserted nowhere; (3) *every published envelope is complete* — seven fields in declared order, none absent/null/empty, `correlationId` the order id, `causationId` the id given to the aggregate.
- **Why parse and re-write rather than splice text.** Splicing the stored text into a hand-assembled envelope would be a second serializer; CLAUDE.md allows one. For text produced by `to_wire_json` (the writer) the parse/re-write is a fixed point (`test_round_trip_every_golden_parses_into_its_model_and_reserialises_equal` already shows the second generation is stable), and assertion (1) proves it for #7's bytes.

### 5.5 The publisher (`kafka_publisher.py`)

```python
class FactPublisher(Protocol):                       # outbox/publisher.py
    async def publish(self, facts: Sequence[PublishableFact]) -> None: ...   # all acknowledged, or FactPublicationError

class KafkaFactPublisher:                            # the only aiokafka importer
    def __init__(self, settings: KafkaSettings) -> None          # stores settings; constructs NO aiokafka object (L23)
    def producer_options(self) -> dict[str, object]               # what start() passes; the OI7 guard reads it
    async def start(self) -> None                                 # AIOKafkaProducer(**options); await start()
    async def stop(self) -> None
    async def publish(self, facts: Sequence[PublishableFact]) -> None
```

- Options: `bootstrap_servers`, `client_id` (`otc-orders`), `enable_idempotence=True`, `acks="all"` (`OI7`, L9).
- `publish`: for each fact, in order, `await producer.send(ORDERS_FACTS_TOPIC, value=…, key=…, headers=[…])` (returns a future; issuing sends sequentially preserves per-partition order), then `asyncio.gather(*futures, return_exceptions=True)`; any `BaseException` that is not `CancelledError` among the results → `FactPublicationError` carrying the event ids. aiokafka's own error types never cross the adapter.
- **One topic.** `ORDERS_FACTS_TOPIC = "otc.orders.facts.v1"`, guarded by a unit test that reads `specs/shared/asyncapi.yaml` (pyyaml, a dev dependency) and compares with the `ordersFacts` channel's `address` (`asyncapi.yaml:92-93`); arming with the sibling `otc.fulfillment.facts.v1` must name the intended break.

### 5.6 The loop task — `OI6`, L18 – L20

```python
class OutboxRelayTask:
    def __init__(self, relay: RunsOutboxOnce, *, poll_interval: float, enabled: bool) -> None
    async def run(self, stop: asyncio.Event) -> None:
        if not enabled: return
        while not stop.is_set():
            try:
                await relay.run_once()
            except Exception:
                log.exception("outbox relay cycle failed; next cycle after the poll interval")
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_interval)
            except TimeoutError:
                pass
```

`RunsOutboxOnce` is a one-method protocol, so the unit tests substitute a controllable fake (#7's `RunsOutboxOnce`, #8's `IOutboxRelay`). The owner (feature 15's lifespan) does `stop = asyncio.Event(); task = asyncio.create_task(relay_task.run(stop))` at startup and `stop.set(); await task` at shutdown — awaited, never fire-and-forget (CLAUDE.md *Async* row); a task that ends unexpectedly is visible to readiness through `task.done()` (feature 27).

### 5.7 Deadlock victim — `OI17` (#8 id 87)

```python
DEADLOCK_DETECTED = "40P01"; DEADLOCK_ATTEMPTS = 3; DEADLOCK_BACKOFF_SECONDS = 0.2

def sqlstate_of(error: BaseException) -> str | None      # DBAPIError → .orig.sqlstate; anything else → None

async def run_once(self) -> RelayResult:
    for attempt in range(1, DEADLOCK_ATTEMPTS + 1):
        try:
            return await self._cycle()
        except DBAPIError as error:
            if sqlstate_of(error) != DEADLOCK_DETECTED or attempt == DEADLOCK_ATTEMPTS:
                raise
            log.warning("outbox relay cycle was a deadlock victim; retrying", extra={"attempt": attempt})
            await asyncio.sleep(DEADLOCK_BACKOFF_SECONDS)
```

- **Only `40P01`.** Narrower than "every transient error", as #8 was narrower than SQL Server's transient list (`DeadlockRetryExecutionStrategy.cs:83-88`). `40001` cannot arise at the pinned `READ COMMITTED` for this statement shape; a dropped connection is `OI5`'s, not a retry's.
- **Why a retry is safe here and not in the unit of work:** the cycle writes no aggregate; a cycle that failed after a publish and before the commit is indistinguishable from `OI5`'s "died before stamping" path, which `R14` already accepts as at-least-once (#8's argument, `DeadlockRetryExecutionStrategy.cs:69-80`).
- **Is a deadlock reachable at all?** `SKIP LOCKED` means the claim never waits on a row lock, and the stamp touches only rows its own transaction holds, so two relays alone cannot form a cycle — as #8 established for its hint triple (`DeadlockRetryExecutionStrategy.cs:39-55`). A third party can: a session holding a table lock the stamp's `ROW EXCLUSIVE` conflicts with. **The constructed cycle** (deterministic, a change of kind, not of probability): A claims rows r1, r2 and its fake publisher waits; C (a raw asyncpg connection) takes `LOCK TABLE outbox IN SHARE MODE` (compatible with A's `ROW SHARE`, so granted); A is released, publishes, and its stamp blocks on C's `SHARE` lock — the test waits until `pg_locks` shows A's request ungranted; C then requests `SELECT … WHERE id = r1 FOR UPDATE` and blocks on A. A waited first, so A's `deadlock_timeout` (1 s default) expires first and A is the victim (`40P01`). A retries: its new claim skips r1 (now C's) and its stamp waits until the test ends C's transaction. Assertions: `run_once` returns a `RelayResult` (no exception), exactly one retry was logged, r2 is stamped, r1 is unstamped and is published by the next poll. The implementer first runs it **without** the retry and records the escaping `40P01` verbatim (#8 87's bullet 1: reproduce before fixing). If PostgreSQL picks C instead, that observation is recorded and the construction is adjusted until A is the victim by construction; the test must never pass by C being the victim.
- **Classifier unit cases** (port of `DeadlockRetryExecutionStrategyTests`): a `DBAPIError` whose `orig.sqlstate == "40P01"` → retried; `"40001"` → not; `"23505"` → not; a `DBAPIError` with `orig = None` → not; an unrelated `RuntimeError` → not.
- **The class, enumerated** (§8): every transaction-opening site this feature adds, and what a deadlock victim does there.

### 5.8 Poison row — `OI18` (#8 id 111, gate point G1)

`build_prefix(rows)` converts rows in `seq` order and stops at the first row whose conversion raises `ValueError` or `TypeError` (`json.JSONDecodeError`, `pydantic.ValidationError` and `UnicodeEncodeError` are all `ValueError` subclasses). It returns the facts before that row and a `PoisonedRow` for it. The cycle publishes and stamps the prefix, commits, logs one ERROR line for the poisoned row (event id, correlation id, seq, exception type and message) and returns `RelayResult(claimed, published=len(prefix), poisoned=…)`. **It raises nothing.** On the next poll the poisoned row is at the head of the claim, so nothing is published from that write model until it is repaired; the ERROR line repeats once per poll interval (paced by §5.6's sleep, so the retry rate is bounded and the count is not).

Reachable poison kinds in PostgreSQL (the `json` type rejects syntactically invalid JSON on input, so "corrupt bytes" is not one of them): a payload that is valid JSON but **not an object** (`[]`, `null`, `"x"`); an `event_type` that fails the pattern; a number that `json.loads` turns into `inf` (`1e400`), which `to_wire_json` refuses (`allow_nan=False`). The test plants each by raw SQL, parametrised.

Why the clean prefix is published rather than the whole batch blocked (#7 and #8 build every fact before publishing anything, so a poison row in position k also blocks rows 0 … k-1 that precede it): those rows are earlier facts, publishing them reorders nothing, and holding them back behind a later row would delay facts for no ordering benefit.

## 6. The idempotent consumer — `R17`, `R18`, `OI10`, `OI12`

### 6.1 Shape (canonical copy, `infrastructure/messaging/idempotent_consumer.py`)

```python
class ConsumerName(Enum):         ORDERS_SAGA = "orders.saga"; PROJECTOR = "projector"; NOTIFICATIONS = "notifications"
class ConsumptionOutcome(Enum):   PROCESSED = "processed"; DUPLICATE = "duplicate"

class SessionBound(Protocol):
    @property
    def session(self) -> AsyncSession: ...

class IdempotentConsumer[T: SessionBound]:
    def __init__(self, *, begin: Callable[[], AbstractAsyncContextManager[T]], clock: Callable[[], datetime]) -> None
    async def run_once(self, event_id: UUID, consumer: ConsumerName, work: Callable[[T], Awaitable[None]]) -> ConsumptionOutcome
```

```
try:
    async with begin() as tx:                                   # the service's unit of work
        inserted = (await tx.session.execute(
            pg_insert(PROCESSED_EVENTS)          # sqlalchemy.dialects.postgresql.insert.values(id=uuid4(), event_id=event_id, consumer=consumer.value,
                                            processed_at=clock(), created_at=clock())
            .on_conflict_do_nothing(index_elements=["event_id", "consumer"])
            .returning(PROCESSED_EVENTS.c.id))).first()       # FIRST statement of the transaction
        if inserted is None:
            raise _Duplicate()                                  # rolls the transaction back
        await work(tx)                                          # effects + outbox rows, same transaction
    return ConsumptionOutcome.PROCESSED
except _Duplicate:
    return ConsumptionOutcome.DUPLICATE
```

- **Insert first, no `SELECT` anywhere in the dedup path** (#7 and #8 agree; L15). The unique constraint `(event_id, consumer)` (`models.py:178`) is the guarantee. A concurrent second delivery's `INSERT … ON CONFLICT` waits on the first transaction's in-progress insertion; when the first commits it returns no row (`DUPLICATE`), when the first rolls back it inserts (`PROCESSED`). `OI10`'s test proves the wait happened (the second session is observed waiting in `pg_locks` before the first is released), so the concurrency is not vacuous.
- **`PROCESSED_EVENTS = table("processed_events", column("id"), column("event_id"), column("consumer"), column("processed_at"), column("created_at"))`** — a lightweight SQLAlchemy table, not a service's ORM class, so the file names no service (`OI12`). The conflict target is named explicitly, so a conflict on any **other** unique key (the primary key) still raises.
- **`ConsumerName`** is the closed set of `specs/shared/requirements.md`'s vocabulary; the column is `varchar(50)`, the longest token is 13 characters.
- **The caller acts on the outcome:** `DUPLICATE` → acknowledge, nothing else (`R18`); `PROCESSED` → acknowledge; an exception → do not acknowledge (feature 27's retry/DLQ wraps here, §7).

### 6.2 Composition with a handler's transaction

`begin` is the service's `UnitOfWork.begin` (its infrastructure transaction class satisfies both `OrdersTransaction` and `SessionBound`). A feature-16 saga step reads:

```python
outcome = await consumer.run_once(envelope.event_id, ConsumerName.ORDERS_SAGA, step)

async def step(tx: SqlAlchemyOrdersTransaction) -> None:
    order = await tx.orders.get_by_id(order_id)
    order.reserve_stock(...)                       # whatever feature 16 calls
    await tx.orders.save(order)                    # aggregate rows + outbox rows, same transaction as the dedup row
```

One transaction holds the dedup row, the aggregate change, the outbox rows and (feature 16) a `saga_commands` row: `R17` literally.

### 6.3 Where the code lives

Same reasoning and same outcome as #7 and #8 (#8 `design.md` §6.3): CLAUDE.md admits three shared runtime packages, none of which may hold SQLAlchemy code (`shared_kernel` and `cqrs` declare `dependencies = []`; `contracts` is the wire). So each service owns a copy; **Orders' is the canonical**, written here with the tests that prove it; features 17 – 24 copy it. The projector (MongoDB, feature 24) and notifications (no outbox, non-transactional send, feature 23) are the two known variants; their divergence is theirs to state.

### 6.4 The parity guard — `OI12`

> **Amendment A1 (leader, 2026-10-06, during implementation; #8's decided shape adopted).** §6.1 placed `ConsumerName` inside the canonical file, which case 2 below forbids (its values are `orders.saga`, `projector`, `notifications`). #8 kept the enum in a per-service file at an identical path in every write model (`../order-to-cash-dotnet/src/Orders/Application/Ports/ConsumerName.cs`, and the same path under `Projector/` and `Notifications/`), so its canonical `IdempotentConsumer.cs` names no service. #9 does the same: `ConsumerName` lives in `infrastructure/messaging/consumer_name.py`, the canonical imports it with exactly one relative import, `from .consumer_name import ConsumerName`, and case 2 allows that one import and otherwise scans the **whole** file after the banner (no excluded region). Wherever §6.1 and this section say the canonical holds `ConsumerName`, read this amendment.

`services/orders/tests/unit/test_idempotent_consumer_parity.py`, reading files as text (no import of other services, no container):

- **Normalised region: the banner only** — the module docstring and any comment lines before it. Python has no namespace line, so #8's second region does not exist here (#7's original single-region rule).
- **Case 1** — *every write model's copy is byte-identical to the canonical after the banner*: over every `services/*/src/otc_*/infrastructure/persistence/models.py` declaring `__tablename__ = "processed_events"` **and** having `infrastructure/messaging/idempotent_consumer.py`. At n = 1 it compares the canonical with itself and says so in its message. **Non-vacuous by sentinel:** the comparison function takes a root path; a second test builds a temporary tree with a canonical and a copy differing by one character outside the banner and asserts the function reports it (#8 D4).
- **Case 2** — *the canonical is adoptable verbatim*: outside the banner, no `orders`, `fulfillment`, `billing`, `notifications`, `projector`, `otc_` substring in any casing (#7's reviewer found `\b`-bounded matching misses `BillingDb`, #7 `progress/history.md` line 780), and every import is from the standard library or `sqlalchemy` (the file needs nothing else: ids come from `uuid4`, the clock is injected).
- **Case 3** — *every write model that consumes facts carries a copy*: a service whose models declare `processed_events` **and** whose `src` references `AIOKafkaConsumer` must have the file. Today no service has a consumer, so the computed set is empty and the case asserts that the computation ran over the real population (a sentinel tree with a consumer and no copy must fail).
- **Case 4** — *a variant carries a divergence banner*: an `idempotent_consumer.py` in a service with no relational `processed_events` is never compared; its banner must name the canonical's path and carry a line beginning `Divergence:`. Dormant until features 23/24; sentinel-tested on a temporary tree.

The copy/variant discriminator is read from the filesystem, never from a list of service names.

### 6.5 The consumer shell — designed here, built by feature 16

One `AsyncSession` per message, created by `begin()` and closed before the next message; the offset is committed only after `run_once` returns (`enable_auto_commit=False`); `PROCESSED` and `DUPLICATE` both commit the offset; an exception does not.

## 7. `R16` — the seam feature 27 attaches to

**This feature does:** retry publication indefinitely by construction (an unstamped row is reclaimed every poll, `R14`, `OI8`); bound each publish (`OI14`); log every publication failure and every poison row with `correlationId` and `eventId`; return `PROCESSED` / `DUPLICATE` and let exceptions propagate. **It does not:** consumer retry, backoff, attempt counting, `<topic>.dlq`, `x-failed-consumer` / `x-attempts` / `x-error`, metrics, traces. **Seams:** (1) consumer side — wrap `IdempotentConsumer.run_once`; nothing in §6 changes; (2) relay side — a poison row blocks its write model's outbox (§5.8); bounding it would need an `attempts` column and an outbox dead-letter path, a coordinated migration across three write models plus a re-run of `OI11` (#8 `design.md` §7 point 2), which is why §12 G1 recommends against it; (3) headers — `to_publishable_fact` builds the header tuple; feature 27 adds `traceparent` / `tracestate` and populates `trace_parent` at write time.

## 8. The deadlock class, enumerated (#8 id 87 bullet 2)

Every transaction-opening site this feature adds (`grep -n "\.begin()" services/orders/src` after implementation, one line per hit in the impl report):

| Site | Retries a deadlock victim? | What a victim does there |
|---|---|---|
| `OutboxRelay._cycle` | Yes, `40P01`, 3 attempts (§5.7) | Retried in `run_once`; on exhaustion propagates to the loop, which logs and continues |
| `SqlAlchemyUnitOfWork.begin` | No (G2) | Propagates to the caller (feature 15: an `RpcError`; feature 16: no offset commit, redelivery) |
| `IdempotentConsumer.run_once` | No (it is the unit of work) | As above; the dedup row rolls back with everything else, so redelivery re-runs the step |

The existing `sequences.py` and seed paths open no transaction of their own (they run inside the caller's) and are listed for completeness.

## 9. Architecture guards

### 9.1 `OI16` — a new import-linter contract

```toml
[[tool.importlinter.contracts]]
id = "fact-producer-confinement"
name = "No service's application or presentation layer imports the Kafka client (R14: only the relay's adapter publishes)"
type = "forbidden"
source_modules = ["otc_<svc>.application", "otc_<svc>.presentation", …]    # all seven services, listed explicitly
forbidden_modules = ["aiokafka"]
```

`include_external_packages = true` is already set, so `aiokafka` is visible to the graph. The `domain-purity` contract already forbids `aiokafka` in every `domain`. Armed twice: `import aiokafka` in an `otc_orders.application` module (this contract fails, naming it), and `from otc_orders.infrastructure.outbox.publisher import FactPublisher` in `otc_orders.application` (the existing `layers-orders` contract fails). A sentinel import in a **comment** or a string must not fail it (import-linter reads the import graph, not text), which is recorded, not armed.

### 9.2 Census updates this code forces (counts read from the instruments, never predicted)

- `tests/architecture/test_write_path_population.py` — `EXPECTED["orders"]` gains one classified entry per new hit: the writer's and repository's `add` calls (**guarded**: ORM unit of work, `install_range_guards` fires); the relay's stamp `update(` and `execute(` (**no guarded column**: writes `published_at` only); the idempotent consumer's `insert(` / `execute(` (**no guarded column**: `processed_events` has no integer column); the repository's `delete(` of removed `order_items` (**no guarded column**: a delete writes no value). Docstrings and log messages must not contain DML-shaped text, which the scan counts.
- `tests/architecture/test_money_guard.py` — `ALLOWED_ROOTS` gains `"re"` (§4.6), with the docstring's census sentence.
- `packages/shared_kernel/tests/test_kernel_surface.py` — `MODULE_NAMES["event_envelope"]` and the new `__init__` exports.
- `tests/architecture/test_cqrs_registration_explicit.py` — `ALLOWED_DECORATORS` gains any decorator the census reports that is not already listed (`asynccontextmanager`, `dataclass`, `property`, `staticmethod`, `classmethod`, `model_validator` already are), each with a reason. No handler-registering decorator may appear.

## 10. Configuration and packages

| Setting (env) | Default | Notes |
|---|---|---|
| `OUTBOX_RELAY_ENABLED` | `true` | One relay per write model in a scaled-out deployment (§5.2) |
| `OUTBOX_POLL_INTERVAL_MS` | `250` | #7's and #8's number |
| `OUTBOX_BATCH_SIZE` | `100` | Bounds the claim's open transaction |
| `OUTBOX_PUBLISH_TIMEOUT_MS` | `5000` | Enforced (`OI14`) |
| `KAFKA_BROKERS` | `localhost:9092` | #7's variable name (`../order-to-cash-nestjs/.env.example` line 117); compose's `KAFKA_HOST_PORT` stays the broker's own source of truth |
| `KAFKA_CLIENT_ID` | `otc-orders` | Fulfillment and billing will use distinct ids (#7 `.env.example` lines 118 – 126: `FULFILLMENT_KAFKA_CLIENT_ID`, `BILLING_KAFKA_CLIENT_ID`) |

Names are #7's (`../order-to-cash-nestjs/.env.example` lines 101 – 118); #8 used .NET's `Section:Key` binding for the same values. `OutboxRelaySettings` and `KafkaSettings` follow `OrdersDatabaseSettings`' rule: `validation_alias` per field, **no** `populate_by_name`, and a test that the fixture clears every alias the class declares (backlog 210's shape), so a bare `$ENABLED` or `$BROKERS` in the shell never leaks in. Millisecond settings are converted to seconds with `ms / 1000` **only** at the settings boundary into a `float` for `asyncio` (not money; the AST money guard covers domains, and this is infrastructure).

**New package:** `aiokafka` in `services/orders/pyproject.toml` (latest release installable on CPython 3.14; the exact version goes in the commit's `Packages installed:` line). No new test package: the Kafka container is driven through `testcontainers`' generic `DockerContainer`, already installed (§11.3). If aiokafka is measured to emit its own `DeprecationWarning` under `-W error`, one targeted `filterwarnings` line is added with the reason beside it, as for `testcontainers.community.nats`.

## 11. Testing

### 11.1 Files and levels

| File | Level | Infrastructure | Proves |
|---|---|---|---|
| `packages/shared_kernel/tests/test_event_envelope.py` | domain unit | none | R11 |
| `packages/contracts/tests/test_envelope_generic.py` | unit | none | OI20, `wire_instant`, generic ↔ generated drift |
| `services/orders/tests/unit/test_outbox_payloads.py` | unit | none | each event class → its payload model, every field, distinct values |
| `services/orders/tests/unit/test_outbox_relay_task.py` | unit | none | OI6, L19, L20, L8 |
| `services/orders/tests/unit/test_kafka_fact_publisher.py` | unit | none | OI7, OI8 (adapter), L23, the topic constant |
| `services/orders/tests/unit/test_deadlock_classifier.py` | unit | none | §5.7 classifier |
| `services/orders/tests/unit/test_outbox_settings.py` | unit | none | defaults, aliases, no `populate_by_name` leak |
| `services/orders/tests/unit/test_idempotent_consumer_parity.py` | unit | none | OI12 |
| `services/orders/tests/integration/test_order_repository.py` | integration | PostgreSQL | round trip, `get_by_reference`, update diff |
| `services/orders/tests/integration/test_outbox_atomicity.py` | integration | PostgreSQL | R13, OI9 |
| `services/orders/tests/integration/test_outbox_envelope.py` | integration | PostgreSQL | R12, OI1, OI19 |
| `services/orders/tests/integration/test_outbox_relay.py` | integration | PostgreSQL (+ Kafka for R14) | R14, OI2, OI3, OI8, OI14, OI18 |
| `services/orders/tests/integration/test_outbox_relay_concurrency.py` | integration | PostgreSQL (fake publishers) | OI4, OI5, OI13 |
| `services/orders/tests/integration/test_outbox_relay_deadlock.py` | integration | PostgreSQL | OI17 |
| `services/orders/tests/integration/test_fact_partitioning.py` | integration | PostgreSQL + Kafka | R15 |
| `services/orders/tests/integration/test_outbox_wire_parity.py` | integration | PostgreSQL + Kafka | OI15, R11 at the producer, SA-2 note present/absent |
| `services/orders/tests/integration/test_idempotent_consumer.py` | integration | PostgreSQL | R17, R18, OI10, per-pair dedup |
| `services/orders/tests/integration/test_fixture_matches_deployed_server.py` | integration | PostgreSQL | §11.4 |
| `services/seed/tests/integration/test_seeded_outbox_has_nothing_to_publish.py` | integration | the seed's existing fixture | the relay claims 0 from a seeded `otc_orders` |

Names follow the matrix convention feature 13 set: `test_r<n>_…` for shared rows, `test_oi<n>_…` for local ones (`requirements.md` §3 is the contract).

### 11.2 Event loops and fixtures

Every async fixture keeps the repository default `loop_scope="function"` unless stated beside it: the engine (existing `engine` fixture), any second engine for a second relay, the `AIOKafkaProducer` (through `KafkaFactPublisher.start()/stop()`), and the test consumer are created and disposed in the test's own loop. The Kafka **container** is session-scoped and synchronous (no loop). No fixture runs a server with reload.

Records on the shared topic are **selected by content** (the test's own event ids), never by position or count of the whole topic (#8 id 74's lesson); test consumers use explicit partition assignment from the beginning, no consumer group. "Published" is always **read from the broker**, never inferred from a stamped row.

### 11.3 Real Kafka

`apache/kafka:4.3.1`, the tag `docker-compose.infra.yml:159` pins. `testcontainers.community.kafka.KafkaContainer` cannot drive it: its start script runs `/etc/confluent/docker/configure` and `/launch` (testcontainers 4.15.0, `community/kafka/__init__.py:163-184`), which exist only in Confluent images. So the root `conftest.py` gains a session fixture over `testcontainers`' generic `DockerContainer` using #8's mechanism (#8 `tests/Orders.IntegrationTests/KafkaContainerFixture.cs:75-131`): the container's command waits for a script file; after start, the fixture reads the **Docker-assigned** host port and writes the script exporting `KAFKA_ADVERTISED_LISTENERS` with it, then `exec /etc/kafka/docker/run`; KRaft environment mirrors the compose service. Never a picked-free port (CLAUDE.md), never another image or a floating tag. The fixture creates `otc.orders.facts.v1` explicitly with **6 partitions, replication factor 1** (`.env.example` `KAFKA_TOPIC_PARTITIONS=6`, `KAFKA_TOPIC_REPLICATION_FACTOR=1`), because the broker has auto-creation off and one partition would make `R15` vacuous. The suite must pass with the developer stack down (#8 id 104).

### 11.4 The fixture against the deployed server (#8 note for #9; #8 D8)

The concurrency claims of this feature depend on four server settings. A test asserts, on a fixture-created database, the value each has in the deployed server (`docker-compose.infra.yml:78` sets `timezone=UTC`; the others are PostgreSQL defaults the compose file does not change): `timezone = UTC`, `default_transaction_isolation = read committed`, `lock_timeout = 0`, `deadlock_timeout = 1s`. A fixture change without an assertion is the guard that does not guard.

## 12. Gate points, and what was decided without one

### 12.1 Open for the gate (each a question #7 and #8 did not answer, or answered differently)

**G1 (DECIDED at the human gate, 2026-10-06: the recommendation below, approved by the maintainer) — the poison row (`OI18`).** *Question:* inside `run_once`, should a row that cannot become a valid envelope block its write model's outbox (publishing the clean prefix before it), or be skipped / parked so later rows flow? *Why #7/#8 could not decide it:* neither handled it inside the cycle; in both it escapes (#7 `outbox-relay.ts:145-146`, #8 `OutboxRelay.cs:124`) and #8's 111 disposition accepted the unbounded retry. **Recommendation: block at the row after publishing the clean prefix; no skip, no park** (§5.8). *Evidence:* skipping publishes later facts of the same order ahead of an earlier one, which `R15` and `OI8` forbid; parking needs an `attempts`/`parked_at` column, i.e. a coordinated migration across `otc_orders`, `otc_fulfillment`, `otc_billing` and a re-run of `OI11` (#8 `design.md` §7 point 2); the failure is loud (an ERROR line per poll naming the row); PostgreSQL's `json` type makes the poison classes narrow (§5.8). *If overruled toward parking:* stop and re-spec; the migration is not this feature's to add silently.

**G2 (DECIDED at the human gate, 2026-10-06: the recommendation below, approved by the maintainer) — deadlock retry in the unit of work.** *Question:* should `SqlAlchemyUnitOfWork.begin()` retry a deadlock victim? *Disagreement:* #7 retries the whole unit of work on `ER_LOCK_DEADLOCK` / `ER_LOCK_WAIT_TIMEOUT`, 3 attempts (`drizzle-unit-of-work.ts:27-31, 54-80`), safe *"only because every caller re-derives everything it needs … verified caller by caller"*; #8 forbids it (`EfCoreUnitOfWork`'s remarks; `DeadlockRetryExecutionStrategy.cs:69-73`: a retried delegate can commit aggregate rows whose drained events never reached the outbox). **Recommendation: no retry in the unit of work in this feature** (as #8); the relay's retry (`OI17`) is separate and is built. *Evidence:* the unit of work's callers do not exist yet (features 15, 16), so #7's precondition cannot be verified; L16 makes the drained-events hazard #8 feared impossible in #9, but a retried `begin()` block cannot re-run code the caller wrote outside it; feature 16's consumer already gets a retry from redelivery, and feature 17 carries its own `40P01` retry as an acceptance item. *Re-open trigger:* a deadlock measured in an orders unit of work in feature 15 or 16.

### 12.2 Decided (#7 and #8 agree, or #8 superseded #7 with a recorded reason, and Python forces no difference)

`R16` deferred to feature 27 (§1.2 of `requirements.md`); the repository adapter built here (§4.3); the clock port here (§4.1); `FOR UPDATE SKIP LOCKED` at a pinned `READ COMMITTED` (§5.2); stamp after acknowledgement, roll back on failure, bounded publish (§5.3); `seq` as the only ordering, selection by nullability (§5.2); idempotent producer keyed by `correlationId` (§5.5); no lease columns (§5.2); insert-first dedup with no `SELECT` (§6.1); per-service copies with a four-case parity guard (§6.3, §6.4); the byte-exact / semantic split on wire parity (§5.4); no `traceparent` until feature 27 (§5.4); `OUTBOX_*` defaults 250 / 100 / 5000 (§10); real Kafka from the compose tag through a generic container (§11.3); the relay loop survives a failed cycle (L19: #7 crashes, #8 continues; #8's 111 disposition records #7's shape as the weaker one, and nothing in Python favours a crash).

## 13. Inherited findings → decision or task

| Finding | Disposition in #9 | Where |
|---|---|---|
| #8 id **87** (deadlock victim escaped `RunOnceAsync`) | **Avoided**: `OI17`, reproduced before the fix, armed both ways | tasks 4.6, 4.19 |
| #8 id **111** (poison row, unverified) | **Decided at gate G1**; `OI18` proves the chosen behaviour inside `run_once` | task 4.12 |
| #8 D1 (stray zero-byte file shadowing the relay's path) | Closing task lists every untracked file and classifies it against `tasks.md`'s file list | task 8.4 |
| #8 D2, D3 (`R18`'s "no command" not asserted; order row not re-read) | `R18` test: the `work` writes an aggregate change, an outbox row **and** a `saga_commands` row, so all three negatives discriminate; the order row is re-read | task 6.4 |
| #8 D4 (three of `OI12`'s four cases vacuous at n = 1) | Temporary-tree sentinels for cases 1, 3, 4 | task 6.8 |
| #8 D5 (`progress/current.md` out of lockstep) | Leader-owned file; the implementer touches only feature 14's status line | task 8.6 |
| #8 D6 (package installed, named nowhere) | Impl report lists every `uv` package added, with version; no unused test package | tasks 1.1, 8.5 |
| #8 D7 (matrix cell cites a name pattern) | Column 5 cites literal function names | task 8.3 |
| #8 D8 (fixture changes without assertions) | §11.4's assertion | task 2.3 |
| #8 history finding 1 (skip vs block, measured) | Measured, armed both ways | task 4.17 |
| #8 history finding 2 (ORM reordered `seq`) | One flush per row; the batched shape measured and recorded | task 4.8 |
| #8 history finding 3 (OI13 draft re-implemented the claim) | Both relays are production `OutboxRelay` instances | tasks 4.15, 4.17 |
| #7 D1 (orphan migration snapshot) | Not applicable: no migration; task asserts `services/orders/alembic/versions/` is unchanged | task 8.4 |
| #7 D2 (publish timeout dead configuration) | `OI14` enforced and tested | task 4.11 |
| #7 D3 (unused Kafka test package) | No new test package; generic container | task 2.4 |
| #7 D4 (manual step published local time) | Manual steps use `now()` (a `timestamptz`) or an explicit `…Z` literal, never a `timestamp` without time zone | task 8.5 |
| #7 D5 (`findByReference` untested) | Repository round trip covers `get_by_reference` | task 3.8 |
| #7 D6 (matrix Total cell stale) | Derived counts including Total updated | task 8.3 |
| #7 D7 (failure committed an empty transaction) | L6; rollback observed through session events | task 4.11 |
| #7 D8 (`seq` typed nullable) | Already avoided by feature 9: `seq: Mapped[int]` (`models.py:172`) | — |
| #7 D9 (`OI9` demonstrated, not guarded) | Retry from the same instance | task 3.11 |
| #7 D10 (`R17` named case survived the mutation) | The `R17` case itself asserts the joint rollback, plus its sibling | task 6.2 |

## 14. Non-goals

No migration and no schema change (if one seems needed, it is a design error to bring back here). No `composition.py`, no lifespan wiring, no NATS (feature 15). No saga, no Kafka consumer (feature 16). No `R16`, no metrics, no traces, no structured-logging setup (feature 27). No `requestId` replay (`R62`, feature 27). No Fulfillment, Billing, Notifications or Projector code. No change under `services/orders/src/otc_orders/domain/`. No edit to `specs/orders_aggregate/` or to `specs/shared/` beyond matrix column 5 and its counts.
