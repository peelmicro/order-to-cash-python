# `projector_read_model` — Design (Python 3.14 / PyMongo async / aiokafka / nats-py, assessment #9)

> Stack-specific: #9's realisation of `R50` – `R55` and of `PR1` – `PR52` ([`requirements.md`](./requirements.md)); none of it belongs in `specs/shared/`. That file is the rule; this one is the mechanism, and nothing here adds to a rule. #8's design (`../order-to-cash-dotnet/specs/projector_read_model/design.md`, 741 lines) is the source of §4 – §7's *shape*; every algorithm clause is `PR10`'s and is re-derived, not transliterated. **§10 is the ported-idiom ledger; a reviewer reads it first.** Every "measured" below is a probe run in this spec session against a throwaway `mongo:8.3.8` container (`docker run --rm`, stopped afterwards) or the workspace's own installed drivers; the commands and outputs are in `progress/spec_projector_read_model.md` §1.

---

## 1. Scope, and what already exists

`services/projector` is a skeleton: `pyproject.toml` (fastapi, uvicorn, `otc-shared-kernel`, `otc-contracts`, `otc-cqrs`; no MongoDB, Kafka or NATS client), `presentation/app.py` (a lifespan that does nothing and `/health/live`), `tests/test_projector_health.py`, and empty layer packages. There is no `composition.py` and no `main.py`. The repository's guards already range over it: import-linter `domain-purity`, `fact-producer-confinement`, `layers-projector` and `service-independence` list `otc_projector` (`pyproject.toml:172-360`), and `tests/architecture/test_money_guard.py:56` lists `projector`. They become non-vacuous the moment real modules land.

This feature makes it the **third Kafka fact consumer** (after Orders' saga and Notifications), the **only runtime writer** of `otc_read_model.order_timeline`, and the only consumer of all fourteen facts (`domain-model.md` §7.3). It publishes an update signal on NATS, answers nothing, and owns no aggregate.

Three pieces of #9 are the reference implementations; this feature copies their shape:

| Concern | Copy from | Why |
|---|---|---|
| A consume-only host: settings, composition root, runtime, grace-then-cancel shutdown, readiness that drops when the task dies, the lifespan outside the layers | `services/notifications/src/otc_notifications/{composition,main}.py`, `presentation/app.py`, `infrastructure/messaging/kafka_fact_subscriber.py`, `presentation/notification_facts_consumer.py` (feature 23, phase 11) | the newest Kafka-consuming service; same "no outbox, no responder, no aggregate" shape |
| The offset contract with `earliest` | `services/orders/src/otc_orders/infrastructure/messaging/kafka_fact_subscriber.py:18, 114-117` | the only `earliest` consumer in #9 |
| The document, its index and its rendering | `services/seed/src/otc_seed/domain/timeline.py:27-103`, `infrastructure/mongo.py:16-53` (feature 12, phase 7) | the seed already writes this collection, at `timelineOrderVersion` 2, with `statusRank`, `processedEventKeys`, `events[].causationId` and the partial `uq_order_reference`. That is the shape; there is no second one |

**What #9 does not do that #7 did:** `PR29`'s backfill (requirements §2.11) and a seed edit (the seed's index is already partial, `mongo.py:39-44`).

---

## 2. Where everything lives

```
services/projector/
├── pyproject.toml                       + pymongo>=4.18.2, aiokafka>=0.14.0, nats-py>=2.16.0, pydantic-settings
├── src/otc_projector/
│   ├── composition.py                   load_settings, register_handlers, _wire, build_dispatcher,
│   │                                    ProjectorRuntime, start_runtime (the boot order, §8.1)
│   ├── main.py                          the lifespan + `app` (outside the layers, Notifications' shape)
│   ├── domain/                          ZERO framework, store or wire imports (PR28)
│   │   ├── projection_delta.py          TimelineEntryDelta, HeaderDelta, ItemDelta, ProjectionDelta
│   │   ├── status_rank.py               STATUS_RANK (the nine pairs), rank_of(status)
│   │   └── timeline_order.py            the REFERENCE implementation of PR10/PR31 (pure Python)
│   ├── application/
│   │   ├── messages.py                  ProjectFactCommand(Command[ProjectionOutcome]) — ONE command
│   │   ├── handlers.py                  ProjectFactHandler — project, apply, signal (PR18/PR19 here only)
│   │   ├── scope.py                     ProjectorScope(read_model, signals)
│   │   ├── outcome.py                   ProjectionOutcome {PROCESSED, DUPLICATE}
│   │   ├── projection.py                project(event: FactEvent) -> ProjectionDelta: fourteen arms, assert_never
│   │   ├── summaries.py                 the fourteen summary/detail builders (PR16, PR46)
│   │   └── ports/
│   │       ├── fact_stream.py           FactMessage, FactStreamSubscriber (Notifications' port, copied)
│   │       ├── read_model.py            ReadModelWriter, AppliedDocument (typed; no Any crosses it)
│   │       └── update_signal.py         UpdateSignalPublisher
│   ├── infrastructure/
│   │   ├── settings.py                  MongoSettings, KafkaSettings, NatsSettings (pydantic-settings only)
│   │   ├── messaging/
│   │   │   ├── consumer_name.py         COPY of services/orders/.../consumer_name.py, byte-identical
│   │   │   ├── fact_topics.py           the three topic literals (checked against asyncapi.yaml)
│   │   │   ├── kafka_fact_subscriber.py the ONLY module importing AIOKafkaConsumer; `earliest`
│   │   │   └── idempotent_consumer.py   THE VARIANT (PR23/PR24) — the docstring banner is load-bearing
│   │   ├── persistence/
│   │   │   ├── read_model_document.py   COLLECTION, field names, TIMELINE_ORDER_VERSION, placeholder()
│   │   │   ├── delta_to_pipeline.py     pure: (delta, dedup_key) -> [one $set stage], every value $literal
│   │   │   ├── timeline_order.py        the causal-order EXPRESSION, shared by apply and migration
│   │   │   ├── mongo_read_model_writer.py  the two operations (§5), DuplicateKeyError retried once
│   │   │   ├── read_model_indexes.py    create, then verify against the stored specification (PR22, PR52)
│   │   │   └── timeline_order_migration.py  PR32, PR35
│   │   └── signal/
│   │       └── nats_update_signal_publisher.py  PR17
│   └── presentation/
│       ├── app.py                       /health/live, /health/ready (create_app(lifespan=...))
│       └── projector_facts_consumer.py  ProjectorFactsConsumerTask: parse, route, dispatch (PR3, PR4)
└── tests/  unit/ (no container) · integration/ (root conftest's mongo_server, kafka_server, nats_server)
```

### 2.1 Packages

No package enters `uv.lock`: `pymongo 4.18.2` (seed), `aiokafka 0.14.0`, `nats-py 2.16.0` and `pydantic-settings` are already locked (`uv.lock:21-22, 762-763, 1179-1180`). The projector member gains the four as dependencies — a member-dependency edit, so the implementer makes it and runs `uv lock`; the commit's `Packages installed:` line reads "none (four existing packages added as dependencies of otc-projector)". **No `sqlalchemy`, `asyncpg`, `alembic`** (`PR21`). **No Motor**: it is deprecated in favour of PyMongo's own async API and absent from `uv.lock` (searched this session: no `name = "motor"` entry); PyMongo ships `py.typed`, as does `nats-py` (both checked in `.venv`), so the only `mypy` override stays `aiokafka.*` (`pyproject.toml:98-100`).

### 2.2 Configuration

Settings classes, each constructed once by `composition.load_settings()` (the env-read guard, §12):

| Class | Variables (default) | Note |
|---|---|---|
| `MongoSettings` | `MONGO_URI` (wins outright), `MONGO_HOST` (`localhost`), `MONGO_HOST_PORT` (`27017`), `MONGO_INITDB_ROOT_USERNAME` (`otc_mongo_root`), `MONGO_INITDB_ROOT_PASSWORD` (**no default**: absent with no URI fails the boot naming both variables), `MONGO_DB_READMODEL` (`otc_read_model`) | the seed's variable set (`services/seed/src/otc_seed/infrastructure/settings.py:47-54`). The seed assembles its URI with SQLAlchemy's `URL.create` (`:98-109`); the projector has no SQLAlchemy, so it quotes user and password with `urllib.parse.quote_plus` and appends `authSource=admin` (ledger L31) |
| `KafkaSettings` | `KAFKA_BROKERS` (`localhost:9092`), `PROJECTOR_KAFKA_CLIENT_ID` (`otc-projector`), `PROJECTOR_CONSUMER_GROUP` (`projector`), both `^[A-Za-z0-9._-]+$` | #7's variable names (`../order-to-cash-nestjs/apps/projector/src/infrastructure/messaging/kafka.config.ts:31-32`), Notifications' validation (`services/notifications/src/otc_notifications/infrastructure/settings.py:79-90`) |
| `NatsSettings` | `NATS_URL` (`nats://localhost:4222`) | as Billing (`services/billing/src/otc_billing/infrastructure/settings.py:106-111`) |

Bounds are module constants with a keyword override on `start_runtime` (Notifications' shape, `composition.py:75-76, 241-247`): `CONSUMER_STARTUP_SECONDS = 60.0`, `STOP_GRACE_SECONDS = 30.0`, `NATS_CONNECT_SECONDS = 10.0`.

**`.env.example` is the leader's** (root config; Phase 11's N4): a "Projector" block after Notifications' with `PROJECTOR_KAFKA_CLIENT_ID=otc-projector` and `PROJECTOR_CONSUMER_GROUP=projector`, and the warning that a new group **replays every retained fact from the beginning** (idempotent, so safe, but every probe fact ever injected into a dev topic is re-materialised). Every other variable already exists in `.env.example` except `MONGO_HOST`, which the seed already defaults to `localhost` and compose (feature 36) will set. `tasks.md` A3 routes it.

---

## 3. The document — the seed's, byte for byte

### 3.1 Fields, types and sources

| Path | BSON type | Source |
|---|---|---|
| `_id`, `orderId` | String, `str(UUID)` lowercase hyphenated | the envelope's `correlationId` (`R12`) |
| `orderReference`, `orderDate`, `currency` | String / explicit `null` | `order.placed.v1` (`orderDate` via `format_instant`) |
| `retailer.{code,name,gln}`, `company.{code,name,gln}` | String / `null` | `code` and `gln` from `order.placed.v1` (`retailerCode`/`buyerGln`, `companyCode`/`supplierGln`); `name` always `null` (`PR9`) |
| `status`, `statusRank` | String, Int32 | `PR12` |
| `cancellationReason` | String / `null` | `order.cancelled.v1`, if null |
| `totals.{initialAmount,initialDiscount,totalAmount}` | Int32 or Int64 by magnitude | `order.placed.v1` |
| `items[]` `{productCode, name, quantity, unitPrice, lineDiscount}` | String, `null`, Int32, Int32/Int64, Int32/Int64 | `order.placed.v1` `lines[]` |
| `references.{despatchReference,invoiceReference,paymentReference}` | String / `null` | their own facts, if null |
| `events[]` `{eventId, eventType, occurredAt, summary, detail?, causationId}` | §3.2 | every fact |
| `headerComplete` | Boolean | `false` in the placeholder, `true` from `order.placed.v1` |
| `updatedAt` | String `.mmmZ` | `$max` of `occurredAt` |
| `timelineOrderVersion` | Int32 `2` | `PR40` |
| `processedEventKeys` | Array of String, sorted | `PR23` |

Integer widths are not chosen here: PyMongo encodes a Python `int` as Int32 when it fits and Int64 otherwise, and raises `OverflowError` above 2⁶³ − 1 (measured: `{"n": 5, "big": 2**31, "huge": 2**62}` → `int`, `Int64`, `Int64`; `2**63` → `OverflowError: MongoDB can only handle up to 8-byte ints`). The seed writes plain `int`s through the same driver, so the projector writing the fact's `int` gives **the same widths as the seed's documents** — which `PR44` compares type by type. `MinorUnits` is bounded to int64 by the generated models (`packages/contracts/src/otc_contracts/generated/asyncapi.py:133-135`), so the overflow is refused at the wire before it reaches the driver. This is a deliberate non-parity with #8 (Int64 always, `DeltaToPipeline.cs`) and #7 (the node driver writes an integer above 2³¹ as a Double): BSON widths were never a trilogy parity claim — the REST wire reads an integer either way — and the claim that matters here is equality with the seed's own documents.

### 3.2 Element order, and why `$setOnInsert`

Element order is part of the shape because `PR15` compares raw BSON bytes and `PR44` compares against the seed's stored bytes. Measured on `mongo:8.3.8`:

| Probe | Result |
|---|---|
| M1 `update_one({_id}, {"$setOnInsert": <whole document>}, upsert=True)` | stored top-level order: `_id`, then the remaining keys **lexicographically** (`cancellationReason, company, currency, events, headerComplete, items, orderDate, orderId, orderReference, processedEventKeys, references, retailer, status, statusRank, timelineOrderVersion, totals, updatedAt`); nested objects keep their literal order (`retailer`: `code, name, gln`) |
| M3 a later pipeline `$set` of existing keys (incl. dotted `retailer.code`) | every existing key keeps its position; only a key that did not exist is appended at the end |

#8 found the same reordering and replaced its placeholder upsert with a pipeline `$replaceWith` to keep the seed class's declaration order (`../order-to-cash-dotnet/src/Projector/Infrastructure/Persistence/PlaceholderDocument.cs:18-37, 101-113`). #9's seed creates its documents with exactly that `$setOnInsert` (`services/seed/src/otc_seed/infrastructure/mongo.py:48-50`), so **the seed's stored documents are in the server's lexicographic order**, and the projector creates its placeholder with the same operator over the same key set: the server then gives both writers the identical order, for free and by the same rule. The obligations that keep it so: the placeholder is **total over the shape** (every top-level key, so no `$set` ever appends one, M3), and nested objects and entries are built as dict literals in the seed's order (`timeline.py:55-63, 70-94`).

### 3.3 The placeholder (`PR8`) and the nested-null trap

Measured (M4): a **pipeline** `$set` of `"retailer.code"` onto a document whose `retailer` is `null` silently **replaces** the null with `{"code": "R1"}` — no error, and `name`/`gln` vanish. (#8 records that the classic operator raises a path conflict instead, `PlaceholderDocument.cs:14-15`; not re-measured here, and #9 uses only the pipeline form.) So the placeholder writes `retailer`, `company`, `totals` and `references` as objects of explicit-`null` leaves — #7's `placeholderSkeleton` shape (`../order-to-cash-nestjs/apps/projector/src/infrastructure/persistence/mongo-read-model-writer.ts:57-64`) — never a `null` object. `PR8`'s test asserts the leaf sets after `order.placed.v1` is applied to a placeholder.

---

## 4. Domain and application — a projection, not an aggregate

### 4.1 Why the fourteen arms live in `application`

`otc_contracts` is pydantic, and import-linter's `domain-purity` forbids `pydantic` in every domain **including indirect chains** (`pyproject.toml:170, 187-218`), so a domain function typed on the generated events would violate it. #8 kept `FactProjection` in its domain because its contract records carry no serialiser dependency; #9's Notifications keeps its templates in `application` for this reason. The split:

- **`domain/`** — `ProjectionDelta` and its parts (frozen, slotted dataclasses: `int` minor units, `datetime` instants, `str` ids), `STATUS_RANK` and `rank_of`, and `timeline_order.causal_order(entries)`: the reference implementation of `PR10`/`PR31` in plain Python, which production never calls on the write path (the server sorts) and which the differential test (§11.3) uses as the oracle for the pipeline expression. ≥80% domain coverage is measured over these.
- **`application/projection.py`** — `project(event: FactEvent) -> ProjectionDelta`, a `match` with one `case <Model>Event():` arm per member of the `FactEvent` union (`packages/contracts/src/otc_contracts/facts.py:30-45`) and `case _: assert_never(event)`. `mypy --strict` rejects a missing arm; `PR2`'s runtime test closes the other direction against `FACT_MODELS`.

```python
# domain/projection_delta.py (shape)
@dataclass(frozen=True, slots=True)
class TimelineEntryDelta:
    event_id: str; event_type: str; occurred_at: datetime; summary: str
    causation_id: str; detail: Mapping[str, object] | None

@dataclass(frozen=True, slots=True)
class ProjectionDelta:
    order_id: str                     # = correlationId
    entry: TimelineEntryDelta
    implied_status: str | None        # None for the five status-less facts
    status_rank: int                  # 0 when implied_status is None
    cancellation_reason_if_absent: str | None
    despatch_reference_if_absent: str | None
    invoice_reference_if_absent: str | None
    payment_reference_if_absent: str | None
    header: HeaderDelta | None        # ONLY for order.placed.v1
```

`implied_status`/`status_rank` come from `PR12`'s table, applied in each arm; the rank of a status is `STATUS_RANK[status]`, the nine pairs pinned to `tests/fixtures/read_model_constants.json` (`PR40`).

### 4.2 The summaries (`PR16`, `PR46`)

Fourteen builders in `application/summaries.py`, every string #7's (`../order-to-cash-nestjs/apps/projector/src/domain/summaries.ts`, e.g. `:41, :56, :61, :102`), money via `otc_shared_kernel.format_money` (`packages/shared_kernel/src/otc_shared_kernel/money_text.py:11-20`: `divmod`, never `/`, SA-5 exponent):

| `eventType` | `summary` | `detail` |
|---|---|---|
| `order.placed.v1` | `Order {orderReference} placed for {retailerCode}` | — |
| `stock.reserved.v1` | `Stock reserved for {len(reservations)} line(s)` | — |
| `stock.rejected.v1` | `Stock rejected: {Σ(requested − available)} unit(s) short on {shortages[0].productCode}` | `shortages`, `reason` |
| `stock.released.v1` | `{Σ units} unit(s) released back to stock` + `" (compensation)"` iff `reason == "credit_rejected"` | `released`, `reason` |
| `credit.approved.v1` | `Credit hold of {format_money(heldAmount, currency)} approved` | — |
| `credit.rejected.v1` | `Credit hold of {format_money(requestedAmount, currency)} rejected ({reason})` | `reason`, `requestedAmount` |
| `credit.released.v1` | `Credit exposure released — ` + `invoice paid` iff `reason == "invoice_paid"`, else `order cancelled` | — |
| `order.confirmed.v1` | `Order confirmed (ORDRSP)` | — |
| `order.despatched.v1` | `Despatch {despatchReference} created` | — |
| `invoice.issued.v1` | `Invoice {invoiceReference} issued` | — |
| `payment.received.v1` | `Payment {paymentReference} received` | — |
| `order.completed.v1` | `Order {orderReference} completed` | — |
| `order.cancelled.v1` | `Order {orderReference} cancelled ({cancellationReason})` | `cancellationReason`, `compensationSteps`, `note` **only when present** (`PR46`) |
| `order.saga_failed.v1` | `Saga command "{command}" dead-lettered after {attempts} attempt(s)` | `command`, `attempts`, `lastError` |

The implementer copies each string from #7's file and the seed's (`services/seed/src/otc_seed/domain/data/sagas.py:510, 524, 566, 762, 824, 838, 854`), and records any disagreement between those two as a finding rather than choosing silently. `detail`'s nested values are the generated sub-models' JSON form (`model_dump(mode="json", by_alias=True)`: camelCase, `.mmmZ` instants, `envelope.py:7-10`), so a `compensationSteps[].occurredAt` is the same text the wire carried.

**`PR46`, branch by branch.** The projector does not branch on `cancellationReason`; the requirement is that nothing in its path drops or alters `note` for any shape the saga can produce (`saga.md:219-221`):

| Branch | `cancellationReason` | `compensationSteps` | `note` |
|---|---|---|---|
| operator, while `placed` | `operator_cancelled` | `[]` | present (and a variant without) |
| operator, while `stock_reserved` | `operator_cancelled` | `[stock_released]` | present |
| operator, while `credit_approved`/`confirmed` | `operator_cancelled` | `[stock_released, credit_released]` | present, including non-ASCII (`"Cliente pidió anulación"`) and a `$`-prefixed text (`PR47`) |
| saga, stock rejected | `stock_rejected` | `[]` | absent → no `note` key |
| saga, credit rejected | `credit_rejected` | `[stock_released]` | absent → no `note` key |

Orders already emits `note` when the aggregate has one (`services/orders/src/otc_orders/infrastructure/outbox/payloads.py:117`, `domain/events.py:87`); the responder that supplies an operator's note is feature 41, whose acceptance 4 owns the end-to-end leg.

---

## 5. The write — exactly two operations

### 5.1 Phase 1 — bring the document into existence

```python
await collection.update_one(
    {"_id": order_id},
    {"$setOnInsert": placeholder(order_id, occurred_at_wire)},   # total over the shape (§3.2, §3.3)
    upsert=True,                                                 # NOT the default (update_one: upsert=False)
)
```

A no-op on an existing document. Its one race — two first facts for an absent order — could make one insert lose with `pymongo.errors.DuplicateKeyError` (code 11000) on `_id`: caught **here only**, the operation retried **exactly once** (it can then only match), every other error propagated. *Measured in implementation (record §4.2 finding 1): on `mongo:8.3.8` the server retries a lost `_id` upsert itself — 4,800 racing upserts raised 0 `DuplicateKeyError` — so the retry is unreachable there and is kept as `PR7`'s conditional clause, guarded by unit arms only.* Not delegated to `retryWrites`: the compose stack and the test container are standalone servers, where no driver retries (ledger L8).

### 5.2 Phase 2 — the atomic apply

```python
applied = await collection.find_one_and_update(
    {"_id": order_id, "processedEventKeys": {"$ne": dedup_key}},   # THE IDEMPOTENCY CHECK
    delta_to_pipeline(delta, dedup_key),                            # ONE $set stage (§5.3)
    return_document=ReturnDocument.AFTER,                           # NOT the default (BEFORE)
)
# None     -> DUPLICATE: nothing written, no signal (R51, PR18)
# a mapping -> PROCESSED: exactly this fact, exactly once; converted to AppliedDocument here
```

Measured (M3b): with the default, the call returned the **pre-update** `status`. A deletion probe cannot see that default — a non-match is `None` either way — which is why `PR42` exists and is armed by removing `return_document` (task G4). Under two concurrent same-`eventId` applies, the server re-evaluates the losing `findAndModify`'s predicate after the write conflict and matches nothing (a server property, identical across the trilogy, proven not assumed by `PR7`). Every field's new value is a monotone function of the old value and the fact (`$max`, `$ifNull`, a full re-sort), which is what makes `PR15` and `R52` hold under any arrival order.

### 5.3 The pipeline — one `$set` stage, every fact value literal-wrapped

`delta_to_pipeline(delta, dedup_key) -> list[dict[str, object]]` is pure and unit-tested on its emitted tree. With `L(x) = {"$literal": x}`:

```python
[{"$set": {
  "processedEventKeys": {"$sortArray": {"input": {"$setUnion": [{"$ifNull": ["$processedEventKeys", []]}, L([dedup_key])]}, "sortBy": 1}},
  "events": timeline_order_expression({"$concatArrays": [{"$ifNull": ["$events", []]}, [L(entry)]]}),
  "statusRank": {"$max": [{"$ifNull": ["$statusRank", 0]}, L(rank)]},
  "status": {"$cond": [{"$gt": [L(rank), {"$ifNull": ["$statusRank", 0]}]}, L(implied_status), "$status"]},
  "references.despatchReference": {"$ifNull": ["$references.despatchReference", L(despatch_or_none)]},
  "references.invoiceReference":  {"$ifNull": ["$references.invoiceReference",  L(invoice_or_none)]},
  "references.paymentReference":  {"$ifNull": ["$references.paymentReference",  L(payment_or_none)]},
  "cancellationReason":           {"$ifNull": ["$cancellationReason",           L(reason_or_none)]},
  "updatedAt": {"$max": [{"$ifNull": ["$updatedAt", L(occurred_at_wire)]}, L(occurred_at_wire)]},
  "timelineOrderVersion": L(TIMELINE_ORDER_VERSION),
  # only when delta.header (order.placed.v1), unconditional (PR9):
  "orderReference": L(...), "orderDate": L(...), "retailer.code": L(...), "retailer.gln": L(...),
  "company.code": L(...), "company.gln": L(...), "currency": L(...),
  "totals.initialAmount": L(...), "totals.initialDiscount": L(...), "totals.totalAmount": L(...),
  "items": L([...]), "headerComplete": L(True),
}}]
```

- **Why `$literal` (`PR47`).** Measured (p2): inside a pipeline, an unwrapped string beginning with `$` is a field path and one beginning with `$$` a variable. An operator note `"$status"` placed unwrapped was stored as the document's own `status` (`'placed'`); an entry whose `lastError` was `"$$NOW x"` failed the whole update with `FailedToParse` (code 9) — redelivered forever, a poison record. Both are stored verbatim when wrapped. Neither predecessor wraps (§10 L14); SA-2 is what put free operator text on this path. The rule is total, not selective: **every** value derived from the delta is wrapped, so the guard can be structural (no fact-derived leaf outside a `$literal`) rather than a list of risky fields.
- **Every array and rank operand is `$ifNull`-guarded**: `$setUnion`/`$concatArrays` fail on a missing field, and a missing `$statusRank` compares as `null`, below every number (#7 hit it live, `delta-to-pipeline.ts:3-6`).
- **`status` uses a strict `$gt`, `statusRank` uses `$max`**, both against the pre-update document within one stage; for a status-less fact (`rank` 0) both are no-ops, so the stage keeps one shape.
- **Dotted outputs** (`"retailer.code"`) set only the named leaf of an existing object (§3.3).
- **`timelineOrderVersion` is stamped on every write.**

### 5.4 The causal timeline order (`PR10`, `PR30`, `PR31`)

`requirements.md` `PR10` is the rule. `infrastructure/persistence/timeline_order.py` holds **one** function, `timeline_order_expression(entries_input)`, called by the live apply (input: the stored array plus the new entry) and by the migration (input: the stored array). It is #8's expression (`TimelineOrder.cs:92-114`; #7's `delta-to-pipeline.ts:63-151`), restated:

```python
{"$let": {"vars": {"all": entries_input}, "in": {"$let": {
  "vars": {"ranked": {"$reduce": {
     "input": "$$all",                                          # |all| relaxation rounds
     "initialValue": {"$map": {"input": "$$all", "as": "e", "in": {"$mergeObjects": ["$$e", {"__depth": 0}]}}},
     "in": {"$map": {"input": "$$value", "as": "e", "in": {"$let": {
         "vars": {"cause": {"$arrayElemAt": [{"$filter": {"input": "$$value", "as": "p", "cond": {"$and": [
             {"$eq": ["$$p.occurredAt", "$$e.occurredAt"]},                     # same tie group
             {"$ne": ["$$p.eventId", "$$e.eventId"]},                           # never itself
             {"$eq": ["$$p.eventId", {"$ifNull": ["$$e.causationId", None]}]},  # PR31: no causationId -> no cause
         ]}}}, 0]}},
         "in": {"$mergeObjects": ["$$e", {"__depth": {"$min": [{"$size": "$$all"},
                 {"$add": [{"$ifNull": ["$$cause.__depth", -1]}, 1]}]}}]}}}}}}},
  "in": {"$map": {"input": {"$sortArray": {"input": "$$ranked", "sortBy": {"occurredAt": 1, "__depth": 1, "eventId": 1}}},
                  "as": "e", "in": {"$unsetField": {"field": "__depth", "input": "$$e"}}}}}}}}
```

- **Python-specific:** `sortBy` is a dict whose key order **is** the sort-key order; it is written as a literal in that order and `PR10`'s unit test asserts `list(sortBy) == ["occurredAt", "__depth", "eventId"]`. `$unsetField` keeps the entry's other keys in place (`detail` cannot be dropped by a re-projection).
- `$sortArray` needs server 5.2+, `$unsetField` 5.0+; the stack is `mongo:8.3.8` in compose (`docker-compose.infra.yml:135`) and in the root conftest (`conftest.py:69`). No `$function`, no server-side JavaScript.
- `$$cause` absent ⇒ depth `0`: one expression covers a foreign cause, a missing fact, a self-edge and an absent `causationId`. A cycle terminates because the `$reduce` is bounded (exactly `|entries|` rounds), not because of the `$min` cap, which never binds (record §4.2 finding 2; kept to mirror #7 and #8); `$map` preserves cardinality.
- **The live tie groups this rule orders in #9** (a derived fact reuses its trigger's `occurredAt` verbatim, so every live causal edge lies inside one tie group):

| Tie group | Source |
|---|---|
| `credit.approved.v1` → `order.confirmed.v1` | `services/orders/src/otc_orders/application/saga/step_table.py:89-92` (`confirm(occurred_at=fact.occurred_at, causation_id=fact.event_id)`) |
| `stock.released.v1` → `order.cancelled.v1` (`R28`), and `stock.rejected.v1` → `order.cancelled.v1` | `application/saga/fact_handler.py:105-111` (`cancel(..., occurred_at=fact.occurred_at, causation_id=fact.event_id)`) |
| `payment.received.v1` → `credit.released.v1` → `order.completed.v1` (`R24`) | `services/billing/src/otc_billing/application/payment_register.py:138-143` (the release reuses the payment's instant and cites its `event_id`, #8 id 57); `step_table.py:107-108` |

Responder facts (`stock.reserved.v1`, `credit.approved.v1`, …) cite their command's request id (`stock_reservation.py:92`, `credit_hold.py:116`), which names no entry: they are cause-less here, and their `occurredAt` (the responder's clock) never ties with their trigger's except by coincidence. That is backlog 201, and the gate record's row G1.

The seed's fixtures place every fact at a distinct instant, so `PR44`'s oracle exercises **no** tie group; `PR10`'s proof is §11.3's adversarial cases and the differential test.

### 5.5 What is not used, and why

| Rejected | Why |
|---|---|
| `find_one` then `replace_one` of a document rebuilt in Python | a read-then-write: lost update under concurrency (the seed's single-threaded offline `$setOnInsert` is not this) |
| A `processed_events` table in a fifth PostgreSQL database | §6.3 — weaker, not dearer |
| A multi-document transaction | unavailable on the standalone server, and one document is strictly better |
| `$push` with `$each`/`$sort` plus `$addToSet` | cannot express `R52`'s conditional status in the same operation |
| A pipeline `$replaceWith` placeholder (#8's) | would give a different element order from the seed's `$setOnInsert` documents (§3.2) |
| Selective `$literal` on "risky" fields only | a list of risky fields is a guess; total wrapping is checkable (`PR47`) |

---

## 6. Idempotency — the documented variant (`PR23` – `PR26`, `PR48`)

### 6.1 The class

`infrastructure/messaging/idempotent_consumer.py`, the path the parity guard resolves. Its module docstring is the banner:

```
"""VARIANT OF services/orders/src/otc_orders/infrastructure/messaging/idempotent_consumer.py (R17, R18).

Divergence: the ledger is not a `processed_events` row inside a PostgreSQL transaction; it is the
`processedEventKeys` array of the read-model document itself, written by the SAME single
`find_one_and_update` that applies the projection. There is no transaction to share: the mark and
the effect are the same bytes in the same write (design.md 6.3).

Behavioural conformance: services/projector/tests/integration/test_idempotent_consumer_conformance.py
"""
```

```python
class ConsumptionOutcome(enum.Enum): PROCESSED = "processed"; DUPLICATE = "duplicate"

class IdempotentConsumer:
    def __init__(self, collection: AsyncCollection[dict[str, Any]]) -> None: ...   # the ONLY attribute (PR51)
    async def run_once(self, *, scope_id: str, event_id: UUID, consumer: ConsumerName,
                       stages: Callable[[str], list[dict[str, object]]],
                       after_applied: Callable[[Mapping[str, Any]], Awaitable[None]]) -> ConsumptionOutcome: ...
```

`stages` is a parameter and the work is a **post-apply callback** (#7 and #8 §6.2): the canonical runs `work` inside the transaction; here there is none, and a work that returned the stages would run before the write — on duplicates too — failing conformance case 2. The callback runs exactly once on `PROCESSED`, never on `DUPLICATE`, and it is where the signal is published, which makes "no signal for a suppressed redelivery" structural.

### 6.2 The dedup key

`f"{ConsumerName.PROJECTOR.value}:{event_id}"`. `consumer_name.py` is a byte-identical copy of Orders' (the closed vocabulary `{orders.saga, projector, notifications}`, `services/orders/src/otc_orders/infrastructure/messaging/consumer_name.py`), so conformance case 5 uses `ConsumerName.NOTIFICATIONS` without inventing a name, and `PR40` checks `ConsumerName.PROJECTOR.value + ":"` against the constants file's prefix.

### 6.3 Why not a fifth relational database

The canonical's guarantee is that the mark and the effect commit together (`R17`). Here the effect is in MongoDB; a mark in PostgreSQL shares no transaction with it, so a crash between them marks an event that was never projected — a silently missing entry no redelivery can repair. The variant has no window. #7 (its gate row 5) and #8 (its gate row 7) chose it for the same reason.

### 6.4 The five conformance cases

`tests/integration/test_idempotent_consumer_conformance.py`, real `mongo:8.3.8`, the real class, a dedup-only stage, a counter as the callback: (1) `PROCESSED`, counter 1; (2) same call `DUPLICATE`, counter still 1; (3) **a new `IdempotentConsumer` over a new `AsyncMongoClient` on the same database** → `DUPLICATE`; (4) two distinct `eventId`s both run; (5) the same `eventId` under `ConsumerName.NOTIFICATIONS` runs. Each case asserts the returned outcome **and** the counter — the attempt, not only the residue.

### 6.5 The Orders parity guard — what #9 owes and why it is edited here (`PR48`)

**The question.** `services/orders/tests/unit/test_idempotent_consumer_parity.py` discovers its population from files: copies are packages with a `processed_events` table **and** `idempotent_consumer.py` (`:50-66`); case 3 examines only packages with the table (`:120-134`, `:280-302`); case 4's variants are packages **without** the table that **happen to have** `idempotent_consumer.py` (`:137-150`). A projector that named its variant file anything else, or deduplicated nowhere, would be examined by no case and every case would pass. That is #7's OI12 flaw exactly (`../order-to-cash-nestjs/progress/history.md:974`: *"the copy-vs-variant discriminator is … the existence of a file the implementer chooses whether to create"*).

**How #7 and #8 guarded it.** #7 rebuilt OI12 after its feature 23 rejection: a literal registry `SERVICE_IDEMPOTENCY_MODE` classifying **every** app (`apps/orders/src/infrastructure/messaging/idempotent-consumer.parity.spec.ts:68-77`), a case failing on an unregistered app (`:308-317`), a case holding each mode honest against the files (`:319-340`), and a variant case requiring a `Behavioural conformance:` line naming a file that exists (`:493-530`). #8 did **not** port the registry: its case 4 skips any service without `IdempotentConsumer.cs` (`tests/Orders.UnitTests/IdempotentConsumerParityTests.cs:99`), and it put the conformance-line check in the projector's own `VariantBannerTests` (`tests/Projector.UnitTests/VariantBannerTests.cs:18`) — a file in the subject's own test tree. #9 inherited #8's shape.

**What #9 owes: a population no subject chooses.** The guard is edited (this feature's file scope) to:

1. `IDEMPOTENCY_MODE`, a literal over every package under `services/`: `orders`, `notifications` → `relational-copy`; `projector` → `documented-variant`; `fulfillment`, `billing`, `gateway`, `seed` → `no-consumer`.
2. **Registry vs disk:** the set of `services/*/src/otc_*` packages equals the registry's keys (a new package fails until classified; a stale entry fails).
3. **Registry vs spec:** the consumer names in `asyncapi.yaml`'s `receive` operations on the three fact channels (the `summary: Consumer name — <name>.` lines, `:613, :628, :652, :677, :699, :712, :726, :749, :759` — read as text, as the guard already reads files) map through a literal `{"orders.saga": "orders", "projector": "projector", "notifications": "notifications"}` to exactly the packages whose mode is not `no-consumer`. The projector cannot be reclassified `no-consumer` while the spec says it consumes.
4. **Mode vs files:** `relational-copy` ⇒ the ledger table and a byte-identical copy (cases 1 and 3, now selected by mode); `documented-variant` ⇒ **no** ledger table **and** `infrastructure/messaging/idempotent_consumer.py` exists (absence now fails instead of skipping) **and** its banner cites the canonical path, a `Divergence:` line and a `Behavioural conformance: <path>` line naming a file that exists; `no-consumer` ⇒ no module of the package references `AIOKafkaConsumer`.
5. Existing cases 1, 2 and 3 keep their assertions; their populations become registry-derived. Their docstrings say so.

The new premises (§12) are each armed on a temporary tree. This edit changes only `services/orders/tests/unit/test_idempotent_consumer_parity.py`; nothing under `services/orders/src` moves.

---

## 7. The update signal (`R55`, `PR17` – `PR19`, `PR42`, `PR45`)

### 7.1 The transport — inherited, not re-decided

NATS core publish on `readmodel.order.updated.<orderId>` and `readmodel.timeline.appended.<orderId>`: #7's gate row 2 (approved), inherited by #8 (its gate row 3). Its reasons hold in Python unchanged: NATS's delivery semantics, which `openapi.yaml` `/orders/stream` already accepts; fan-out to every Gateway replica, which one Kafka consumer group cannot do; and `?orderId=` as a subscription. It widens "Kafka carries facts, NATS carries RPC" to "…and publish-only read-model signals", mitigated by having no responder, no reply subject and nothing awaiting it.

### 7.2 Shape

Two publishes per applied fact, from the post-apply document:

- `readmodel.order.updated.<orderId>` → `otc_contracts.generated.openapi.OrderStreamUpdate` (`event_id`, `order_id`, `order_reference`, `status`, `cancellation_reason`, `references`, `totals`, `occurred_at`; `openapi.yaml` requires `eventId`, `orderId`, `status`, `occurredAt`).
- `readmodel.timeline.appended.<orderId>` → `TimelineStreamEntry` (`event_id`, `causation_id`, `order_id`, `order_reference`, `event_type`, `occurred_at`, `summary`).

Serialised by `to_wire_json` (`packages/contracts/src/otc_contracts/wire.py:175`): camelCase, compact, non-ASCII raw, `.mmmZ`, explicit `null` only where the spec declares the field nullable. The generated models already mirror `openapi.yaml`, so #8's projector-owned signal records (`src/Projector/Application/Signals/`) have no #9 counterpart. Each publish passes a **new** headers dict `{"x-correlation-id": order_id}`.

### 7.3 Failure, and the connection

`PR19` (log and swallow) is correct only if a misconfigured broker fails the **boot**, otherwise every signal is swallowed forever on a green suite. #8's gate ruled this (row 1, approved: connect eagerly, `PR45`). #9's `nats.connect` **is** eager, but measured: with `max_reconnect_attempts=2` an unreachable URL raised `NoServersError` in 1.01 s; with the defaults (`DEFAULT_MAX_RECONNECT_ATTEMPTS = 60`, `DEFAULT_RECONNECT_TIME_WAIT = 2`, `nats/aio/client.py:91-92`, retried by the loop at `:616-640`) it was still connecting when the 60 s probe was killed. So `start_runtime` wraps the connect in `asyncio.timeout(nats_connect_seconds)` and re-raises with a message naming `NATS_URL` and the bound; the default `max_reconnect_attempts` is left for runtime reconnects. A publish while reconnecting is buffered by the client; while closed it raises and is swallowed by `PR19`; readiness reports the connection state (`PR50`, Billing's shape, `services/billing/src/otc_billing/composition.py:236-241`).

---

## 8. Wiring

### 8.1 `start_runtime` — the boot order (`PR43`)

One coroutine, in this statement order, every opened resource pushed onto one `AsyncExitStack` (Notifications' shape, `composition.py:241-306`):

1. `_wire()` — register, build over `otc_projector.application`, collect the factories. A missing or duplicate handler fails here, before any connection.
2. `AsyncMongoClient(settings.mongo.uri)`; `stack.push_async_callback(client.close)`; `await db.command("ping")` (a real round trip, the seed's `verify`, `mongo.py:31-33`).
3. `await ensure_indexes(collection)` then `await verify_indexes(collection)` (`PR22`, `PR52`).
4. `await migrate_timeline_order(collection)` (`PR32`, `PR35`), logging both counts.
5. `async with asyncio.timeout(...)`: `connection = await nats.connect(settings.nats.url, error_cb=…, disconnected_cb=…, reconnected_cb=…)` (callbacks log; no default printing); `stack.push_async_callback(_close_nats, connection)` (drain, Billing's `_close_nats`).
6. Build the adapters (`IdempotentConsumer`, `MongoReadModelWriter`, `NatsUpdateSignalPublisher`), the scope factory, and **build every registered factory once** (`registered_factories()`), so a missing binding raises in the lifespan.
7. Create the consumer task, `await _await_consumer_ready(...)` (joined, positions resolved, or the task's own error, or `TimeoutError`).
8. Build `ProjectorRuntime`; `owned.push_async_callback(stack.pop_all().aclose)` last.

A failure at any step stops and awaits the task (if created) and closes what was opened, in reverse. `PR43`'s unit test drives `start_runtime` with recording fakes for the five externals and asserts the call log's order exactly; its integration half asserts that when `start_runtime` returns, both indexes exist and a version-1 document has been migrated.

### 8.2 The dispatcher (`PR27`, `PR49`)

```python
def register_handlers(registry: HandlerRegistry[ProjectorScope]) -> None:
    registry.register_command(ProjectFactCommand, ProjectFactHandler)   # one statement, no loop
```

`build_dispatcher()` is pure, so `tests/architecture/test_registration_behaviour.py` can run it (§12). One command, not fourteen: the behaviour is uniform in `eventType` and all fourteen variations live in `project` (#7 gate row 15, #8 gate row 16). The handler: `delta = project(command.event)`; `return await scope.read_model.apply(delta, after_applied=...)`, the callback publishing the signal inside `try/except Exception` that logs (`PR19`) — the only place a publication failure is caught.

### 8.3 Runtime, readiness and shutdown (`PR50`)

`ProjectorRuntime.unready_reasons()` (Notifications' `composition.py:179-190` plus Billing's NATS clause): shutting down; a task done while running; the subscriber not ready; the NATS connection closed or reconnecting. `/health/ready` serves it. `stop()`: set the stop event, wait `STOP_GRACE_SECONDS`, cancel what is still pending, await all, then close the stack (NATS drain, MongoDB client close) — all in the lifespan's loop. `asyncio.CancelledError` is a `BaseException`, so the subscriber's `except Exception` around the handler never swallows a cancel. A cancel between the apply and the publish loses that one signal: the offset is not committed, the redelivery is suppressed, so no signal is ever re-emitted — the bounded loss `PR19` already accepts.

### 8.4 `main.py` and `presentation/app.py`

`main.py` is Notifications' (`main.py:1-34` of that service): `lifespan` loads settings, starts the runtime, stores it on `app.state.runtime`, stops it on exit; `create_app()` passes it to `presentation.app.create_app(lifespan=...)`. The skeleton's `presentation/app.py` becomes that `create_app` with `/health/live` and `/health/ready`; it imports no adapter (the `fact-producer-confinement` contract forbids `presentation` reaching aiokafka even through the composition root). `tests/test_projector_health.py` keeps its liveness case and gains the readiness ones.

---

## 9. The consumer (`PR1` – `PR5`, `PR36` – `PR38`)

`ProjectorFactsConsumerTask.handle(message)` (Notifications' `notification_facts_consumer.py:50-68`, with the routing difference below):

1. `from_wire_json(Envelope[dict[str, Any]], message.value)`; `ValueError` → ERROR log with topic/partition/offset/length → return (offset committed) — `PR3`. An empty value (a tombstone, `value=None` → `b""`, `kafka_fact_subscriber.py:173`) lands here.
2. `parse_fact(message.value)` (`facts.py:71-78`); `UnknownFactTypeError` → ERROR log naming the type → return — `PR4`. Any other validation error of a registered type propagates (no commit; paced redelivery; feature 27 dead-letters).
3. `await dispatcher.send(ProjectFactCommand(event=fact), scope_factory())`.

There is **no** filter table: Notifications needs `NOTIFIED_FACTS` because it acts on seven; the projector acts on all, so `FACT_MODELS` (through `parse_fact`) is the only table and the `FactEvent` union the only list (`PR36`). `eventType` lookup is an exact `dict` key; an upper-case variant never reaches it, because the envelope's pattern `^[a-z]+\.[a-z_]+\.v[0-9]+$` (`envelope.py`) refuses it first (`PR3`), so `PR4`'s test uses pattern-valid siblings: `order.shipped.v1` and `order.placed.v2`.

`KafkaFactSubscriber` is Notifications' file with three differences, each asserted on `consumer_options()` — the dict the runtime passes to `AIOKafkaConsumer`: `auto_offset_reset="earliest"` (its default is `"latest"`, `aiokafka/consumer/consumer.py:246`); `group_id`/`client_id` from `KafkaSettings`; topics `PROJECTOR_FACT_TOPICS` (three literals, compared with `asyncapi.yaml` by a unit test, Notifications' `fact_topics.py` precedent). Kept verbatim: `enable_auto_commit=False` (default `True`, `:247`), `getmany(max_records=1)`, commit `offset + 1` only after the handler returned, `seek` back and paced retry on failure, positions resolved before `ready`, the consumer built inside `run` (loop affinity) and stopped in `finally`, aiokafka typed through a private `Protocol`.

---

## 10. The ported-idiom ledger

> **How it was produced.** The boundaries were enumerated first, from the artefacts: #8's 54 rows (`design.md` §10), #7's projector source tree (45 files), #9's three driver packages as installed, and the brief's Python questions (integer division, JSON serialisation, loop affinity, cancellation, `Any`). **65 boundaries were listed; 65 rows follow**, dismissed ones included. Each row: *#7 relied on X; #8 supplied it with Y; in #9 it is supplied by Z*, both halves with a file and line. **Guard** names the test that must be seen to fail (`tasks.md` carries it `[ARM]`); `—` means the same mechanism supplies it on every side and there is nothing to hand-build. Where a claim involves two parties, the row states which way it was probed.

### 10.1 The server (`mongo:8.3.8` in all three)

| # | Boundary | #7 | #8 | #9 | Guard |
|---|---|---|---|---|---|
| L1 | Single-document atomicity of `findAndModify` | the server | the server | the server | — |
| L2 | A write conflict re-evaluates the predicate; the same-`eventId` loser matches nothing | the server | the server (`design.md` §5.2) | the server; **the client shape differs** (asyncio, one loop) so it is proven | `PR7` same-`eventId` case, separate `AsyncMongoClient`s |
| L3 | Two upserts on an absent `_id`: one `E11000` | hand retry, `mongo-read-model-writer.ts:130-160`, code `11000` at `idempotent-consumer.ts:25` | hand retry, `MongoReadModelWriter.cs:68` | hand retry on `DuplicateKeyError`, Phase 1 only | `PR7` absent-order case; E2's "Phase-2 duplicate is not retried" case |
| L4 | `$setOnInsert` is a no-op on match | the server | the server | the server | `PR6` command stream |
| L5 | Pipeline updates, `$sortArray` (5.2), `$unsetField` (5.0) | the server | the server | the server, pinned `conftest.py:69` | `PR10` stage-tree unit test |
| L6 | `$setUnion`'s order is unspecified | `$sortArray`, `delta-to-pipeline.ts:181-182` | `$sortArray`, `DeltaToPipeline.cs:32-36` | `$sortArray` | `PR15` raw-BSON replay |
| L7 | A missing `$statusRank` compares as `null` (below every number) | `$ifNull`, `delta-to-pipeline.ts:206, 212` | `$ifNull`, `DeltaToPipeline.cs:52, 63` | `$ifNull` on every array and rank operand | `PR6`/§5.3 stage-tree test asserts each `$ifNull` |
| L8 | Standalone: no transactions, no retryable writes | designed around (`mongo-read-model-writer.ts:130`) | `design.md` §5.1 note | same; the variant needs none | `PR23` |
| L9 | Unique indexes compare nulls equal | partial index, its gate row 1 | inherited from its seed (`ReadModelIndexes.cs:34`) | inherited from the seed (`mongo.py:39-44`) | `PR8` two-placeholder case |
| L10 | Conflict code for a same-name index with different options | code 85 only, `read-model-indexes.ts:22` | 85 **or** 86, `ReadModelIndexes.cs:73` (its L11 correction) | 85 or 86; **measured 86** (`IndexKeySpecsConflict`) for plain-vs-partial **in both creation orders** | `PR22` refusal case asserts the code the server raised, not a literal |
| L11 | `$type` alias in the partial filter | wrote `'string'`, `read-model-indexes.ts:33` | builder's numeric code; the server compares equivalently, stores as created (its L12, two corrections) | the seed and the projector both write the literal `{"$type": "string"}`; measured stored form `{'$type': 'string'}` | `PR39`, **both creation orders** |
| L12 | `$setOnInsert` stores top-level keys lexicographically after `_id` | object literal insert, `mongo-read-model-writer.ts:139` | replaced by pipeline `$replaceWith`, `PlaceholderDocument.cs:18-37, 101-113` | the seed uses `$setOnInsert` (`mongo.py:48-50`), so the projector does too: same rule, same order (measured M1) | `PR41` element-sequence case; `PR44` raw order vs the seed |
| L13 | Pipeline dotted `$set` onto a `null` parent replaces it silently | nested null leaves, `mongo-read-model-writer.ts:57-64` | nested leaves; classic operator errors instead, `PlaceholderDocument.cs:14-15` | nested null leaves (measured M4) | `PR8` nested-leaf case |
| L14 | A `$`-prefixed string inside a pipeline is evaluated | **none** — no `$literal` under `apps/projector/src` (searched) | **none** — no `$literal` in `src/Projector/Infrastructure/Persistence` (searched) | every delta value `$literal`-wrapped (measured p2) | `PR47` unit (structural) + integration |
| L15 | Write concern | node default acknowledged | `WriteConcern.Acknowledged`, not overridden | PyMongo default `w=1`, not overridden | — (no override exists; `PR6`'s stream would show one) |
| L16 | Read concern / preference | standalone primary | identical, dismissed | identical, dismissed: no read on the write path | — |
| L17 | 16 MB document limit | ≤ 14 entries | dismissed | dismissed: redeliveries are suppressed, so ≤ 14 entries | — |
| L18 | Binary string comparison for `$max`/`$sortArray` | simple collation | same | same; relies on fixed-width `.mmmZ` (L22) | `PR14` |

### 10.2 The driver (PyMongo 4.18.2 async vs `mongodb` node / MongoDB.Driver 3.11.1)

| # | Boundary | #7 | #8 | #9 | Guard |
|---|---|---|---|---|---|
| L19 | Which async driver | `mongodb` (`mongo-client.ts:14-16`) | MongoDB.Driver | `pymongo.AsyncMongoClient` (the seed's, `services/seed/src/otc_seed/composition.py:46`); Motor deprecated and absent from `uv.lock` | A4: `pyproject` names `pymongo`, not `motor`; `uv.lock` has no `motor` |
| L20 | Element names | JS keys | string constants, `ReadModelCollection.cs:37` | dict-literal keys equal to the seed's (`timeline.py:65-103`) | `PR41`; `PR44` |
| L21 | Identifier encoding | strings | `ToString("D")` | `str(UUID)`; a native `uuid.UUID` **raises** under PyMongo's default representation (measured) | `PR41` type case |
| L22 | Instant encoding | `.toISOString()` strings (envelope pass-through, `fact-projection.ts:207`) | `InstantWire.cs:16` | `otc_contracts.wire.format_instant` (`wire.py:47`); a BSON date decodes **naive** (measured) | `PR41` regex case; `PR14` |
| L23 | Integer width | Int32, else Double | `long` → Int64 always | `int` by magnitude, Int32 / Int64, `OverflowError` above 2⁶³−1 (measured) — equal to the seed's | `PR44` BSON types; `PR41` `2**31` case |
| L24 | `find_one_and_update` returns the post-image | `returnDocument: 'after'`, `idempotent-consumer.ts:63` | `ReturnDocument.After`, `IdempotentConsumer.cs:59` | `ReturnDocument.AFTER`; default `BEFORE`, `collection.py:3523` (measured M3b) | `PR42` (only it fails; S5) |
| L25 | Phase 1 upserts | `{ upsert: true }`, `mongo-read-model-writer.ts:140` | `IsUpsert = true`, `MongoReadModelWriter.cs:62` | `upsert=True`; default `False`, `collection.py:1217` | `R53` case |
| L26 | Recognising a duplicate key | code 11000 | `ServerErrorCategory.DuplicateKey` | `pymongo.errors.DuplicateKeyError`, `_id` only | `PR7`; E2 |
| L27 | Proving the absence of a read | `monitorCommands: true`, `projection-write.integration.spec.ts:26` | `ClusterConfigurator`, `ProjectionWriteTests.cs:34` | `pymongo.monitoring.CommandListener` via `event_listeners=` | `PR6` |
| L28 | What "concurrent" means in a test | one client; its reviewer opened 12 | separate clients (its L24) | separate `AsyncMongoClient`s, `asyncio.gather` | `PR7` |
| L29 | Event-loop affinity of the client | one Node loop | thread-safe client | the client is created in `start_runtime` and closed by its stack in the lifespan's loop; tests build their own per loop (root `conftest.py` docstring) | `PR51` scan (no module-level client); H6 two-loop case |
| L30 | `Any` from the driver | TS types | `BsonDocument` | documents are `Mapping[str, Any]` inside `infrastructure` only; the writer returns `AppliedDocument` | `PR51`/C1 AST case: no `Any` in `domain` or `application/ports` |
| L31 | Credentials in the URI | `encodeURIComponent`, `mongo.config.ts:23-24` | `Uri.EscapeDataString`, `ProjectorOptions.cs:18, 31` | `urllib.parse.quote_plus` (the seed uses SQLAlchemy `URL.create`, `settings.py:102-109`, unavailable here) | A5: a password with `@ / :` round-trips through `pymongo.uri_parser.parse_uri` |
| L32 | `detail`'s nested payload | plain object | `JsonWire` → `BsonDocument.Parse` | `model_dump(mode="json", by_alias=True)` | `PR41` detail keys/instants case |
| L33 | Entry key order | object literal | declaration order | dict insertion order, the seed's (`timeline.py:55-63`) | `PR41` entry sequence |
| L34 | Sorted `processedEventKeys` vs the seed's | `$sortArray` | `$sortArray` vs `StringComparer.Ordinal` | `$sortArray` vs the seed's `sorted()` (`timeline.py:100`): same order for ASCII keys | `PR44` |

### 10.3 Kafka (aiokafka 0.14.0)

| # | Boundary | #7 | #8 | #9 | Guard |
|---|---|---|---|---|---|
| L35 | Start a new group at the beginning | `fromBeginning: true`, `main.ts:71` | `AutoOffsetReset.Earliest`, `KafkaFactStreamSubscriber.cs:113` | `auto_offset_reset="earliest"`; default `"latest"`, `consumer.py:246` | `PR38` options; `PR5` integration |
| L36 | Commit only after the handler | `eachMessage` | `EnableAutoOffsetStore=false` + `StoreOffset`, `:115` | `enable_auto_commit=False` (default `True`, `:247`) + commit after, `seek` on failure | `PR38` read from the broker |
| L37 | Group equals the ledger's consumer name | `'projector'`, `kafka.config.ts:32` | `"projector"`, `:111` | `PROJECTOR_CONSUMER_GROUP` default `"projector"` == `ConsumerName.PROJECTOR.value` | `PR38` |
| L38 | Distinct client id | `'otc-projector'`, `kafka.config.ts:31` | `"otc-projector"`, `:112` | `PROJECTOR_KAFKA_CLIENT_ID`, pattern-validated (BC34) | `tests/architecture/test_kafka_client_ids.py` extended |
| L39 | No ordering across topics | broker | broker | broker | `PR15` reverse-arrival case |
| L40 | Nothing synchronous on the loop | Node | `Task.Yield` before `Subscribe` | aiokafka heartbeats on the same loop: no sync driver (`pymongo.MongoClient` never imported) | K6 AST case |
| L41 | A malformed record or a tombstone | `parseFactEnvelope`, `projector-facts.controller.ts:63-64` | `ValidateEnvelope`, `ProjectorFactsConsumer.cs:174-175` | `Envelope[dict]` via `from_wire_json`; `None` → `b""` | `PR3` |
| L42 | Ready only once consuming | n/a | host start | positions resolved before `ready` (Notifications) | `PR50` |
| L43 | Cancellation on shutdown | host | host tokens | grace, then `cancel()`, awaited; `CancelledError` not caught by `except Exception` | `PR50` stuck-handler case, `asyncio.timeout`-bounded |

### 10.4 NATS (nats-py 2.16.0)

| # | Boundary | #7 | #8 | #9 | Guard |
|---|---|---|---|---|---|
| L44 | Core publish, no reply | `connection.publish`, `nats-update-signal.publisher.ts:76-77` | `PublishAsync`, `NatsUpdateSignalPublisher.cs:51, 57` | `await nc.publish(subject, payload, headers=...)` | `PR1` (no `subscribe`/`request`) |
| L45 | A wrong URL fails the boot | `connect()` at boot, `nats-client.ts:10` | lazy; `ConnectAsync` in the bootstrap, `ReadModelBootstrap.cs:49` (its gate row 1) | eager, but ≈120 s of retries by default (measured; `client.py:91-92, 616-640`) → `asyncio.timeout` | `PR45` |
| L46 | Headers not shared | object literals | fresh `NatsHeaders`, `:65` | a new dict per publish | `PR37` signal case, two publishes |
| L47 | Wildcard fan-out | server | server | `nats:2.14.5-alpine` | `R55` (both subscribers) |
| L48 | Publishing while disconnected | — | — | buffered while reconnecting, raises once closed → `PR19`; readiness reports it | `PR19`; `PR50` |
| L49 | Loop affinity of the connection | Node | n/a | created in `start_runtime`, drained by its stack | H6 two-loop case |

### 10.5 Serialisation, language and host

| # | Boundary | #7 | #8 | #9 | Guard |
|---|---|---|---|---|---|
| L50 | Signal JSON | `JSONCodec` | `JsonWire.Options` | generated models + `to_wire_json` | `PR17` required fields from `openapi.yaml`; a non-ASCII note raw |
| L51 | Fourteen-way exhaustiveness | `switch` + `HANDLED_EVENT_TYPES`, `fact-projection.ts:51, 74` | CLR-type `switch` + `FactCatalog` | `match` over `FactEvent` + `assert_never`; `mypy` fixture | `PR2` (both directions + `mypy`) |
| L52 | One routing table | **two** lists (`:51, 74`) | `FactCatalog` only, `ProjectorFactsConsumer.cs:93` | `FACT_MODELS` via `parse_fact` only | `PR36` |
| L53 | Exact `eventType` match | JS key | `StringComparer.Ordinal` | `dict` key, behind the envelope's lower-case pattern | `PR4` (`order.placed.v2`); `PR3` (an upper-case variant) |
| L54 | Money never a float, never `/` | numbers | `long`, `DomainDecimalTests` | `int`; `format_money` uses `divmod`; the AST money guard (`test_money_guard.py:56`) covers the service | money guard armed (K5); `PR16` EUR/JPY/BHD |
| L55 | Bootstrap before the first poll | one function, `main.ts` | hosted-service order + `IHostedService` | statement order in `start_runtime` | `PR43` ordered call log |
| L56 | A missing handler is loud | Nest module init | `ValidateOnBuild`, `ProjectorHost.cs:50-56` | `HandlerRegistry.build` before any I/O | `PR27` zero/two |
| L57 | Registration by behaviour (F-g/F-j) | `@nestjs/cqrs` decorators | explicit `AddProjector` | `test_registration_behaviour.py` membership | `PR49` |
| L58 | Domain purity | ESLint | NetArchTest | import-linter `domain-purity` (indirect chains count) | K5 planted import; B4 |
| L59 | The Kafka client stays in one module | — | `FactConsumerConfinementTests` | `fact-producer-confinement` + `test_kafka_client_confinement.py` | §12 extension, armed |
| L60 | Sole writer | text scan, `read-model-sole-writer.spec.ts:7, 144` | write-shaped names | AST scan of attribute calls | `PR20` scratch tree |
| L61 | A parity oracle | none at implementation time | the seed's class map | the real seed writer's stored document | `PR44` |
| L62 | Constants shared with the seed | "in sync by inspection" (backlog 212's note) | reflection on `MongoSeedWriter` | `tests/fixtures/read_model_constants.json` | `PR40` (bump the projector's version alone) |
| L63 | Configuration only through settings | env in `kafka.config.ts` | options classes | pydantic-settings only | `test_composition_env_reads.py` extended |
| L64 | Integer division | — | — | none: depth arithmetic is server-side `$add`; the reference rule uses `int`; money uses `divmod` | money guard (`/` on a money name) |
| L65 | The stored instant vs the seed's | — | `InstantWire` | `format_instant` from contracts; the seed's own copy is pinned to it (`services/seed/tests/unit/test_seed_instants.py`) | `PR44`; `PR41` regex |

### 10.6 Where to spend review time

Four rows are present and correct on the path a deletion probe takes and wrong only under a condition the happy path never creates: **L24** (`BEFORE` keeps every signal count right and every signal stale), **L14** (wrong only for a `$`-prefixed text, which no fixture contains unless a test plants one), **L12** (a placeholder missing one key yields a correct document in the wrong element order, visible only to a byte comparison), and **L45** (correct on a good URL; a two-minute boot hang, or a silent signal loss if someone "fixes" it with `retry_on_failed_connect`). L10 and L11 are two-party claims and their guards run both creation orders.

---

## 11. Testing approach

- **Unit** (`services/projector/tests/unit/`, no container): the domain, `project`, the summaries, `delta_to_pipeline` and `timeline_order_expression` as emitted trees, the consumer's routing over a fake subscriber and a recording dispatcher, the settings, the composition's ordering and registration with fakes, and the structural guards.
- **Integration** (`tests/integration/`): the root `conftest.py`'s Docker-held `mongo_server`/`fresh_mongo_database`, `kafka_server` (the three topics, six partitions, `conftest.py:235-245`) and `nats_server` — never the developer stack (the suite passes with it down). Each test builds and closes its own clients in its own (function) loop; the loop scope is written beside every async fixture.

### 11.1 Binding rules

1. **Synchronise on terminal or monotonic evidence**: a key in `processedEventKeys`, `len(events) == N`, a terminal status, a received frame count — inside `asyncio.timeout(...)` whose message names the claim (Phase 11's N1: no timeout plugin here). Never a sleep, never an intermediate status.
2. **Observe the attempt, not only the residue**: the writer's returned outcome and a callback counter alongside the document.
3. **Fixtures must not satisfy the relation by accident**: in every ordering test the arrival order, the `occurredAt` order and the causal order differ from each other, and `eventId`s are chosen so that the `eventId` fallback alone would invert the expected result; `eventId`, `aggregateId`, `correlationId` and `causationId` are pairwise distinct in every envelope (#8 id 60); status tests use a terminal status whose rank differs from each plausible wrong one; money values are distinct and none contains another as a substring.

### 11.2 Restart model (Phase 11 N2)

Three different restarts, each named where it is used: (a) **runtime rebuilt in one process** — `stop()` then a new `start_runtime` (new `AsyncMongoClient`, new NATS connection, new aiokafka consumer, same group): every redelivered or replayed fact must be `DUPLICATE` (`PR51`); (b) **new consumer group** — replay from the beginning into the same database (all suppressed, documents byte-unchanged, zero frames) and into an empty database (byte-identical documents, `PR15`); (c) **process restart** — only in the live walkthrough (N4), where the uvicorn process is stopped and started. The gap between (a) and (c) — a process-wide cache that (a) cannot see — is closed structurally by `PR51`'s scan, not assumed.

### 11.3 How the ordering proofs bite

- **R28 and R24** with the live tie-group shapes (§5.4), `eventId`s chosen so the fallback alone inverts the order, delivered in the inverting order. Armed by removing `__depth` from `sortBy` — **both** must fail.
- **Differential**: for ≥ 200 entry sets generated by a seeded PRNG (ties, sibling edges, chains, cycles, foreign causes, absent `causationId`), the pipeline expression evaluated by the server (`db.aggregate([{"$documents": [{"events": entries}]}, {"$set": {"events": <expr>}}])` — no write) equals `domain.timeline_order.causal_order(entries)`. The seed and the first failing set are printed on failure.
- **Replay determinism (`PR15`)** goes **through Kafka** (#8's advisory A6 was that it did not): produce the facts of two orders, duplicated and shuffled across the three real topics; run the runtime with group `g1` into database A; replay with group `g2` into database B; compare each document's raw bytes (`RawBSONDocument.raw`). A second case applies every permutation-with-duplicates of one order's facts through the writer and compares bytes.

### 11.4 The seeded oracle (`PR44`)

For each of `SAGAS` (six), build envelopes from the saga's own outbox fixtures, apply them through the real writer into an empty collection, seed the same saga with the real `MongoTimelineTarget` into another, and compare the two stored documents' raw element sequence and BSON types field by field, excluding the declared literal `{"retailer.name", "company.name", "items[].name", "events[].detail"}` and nothing else; the test also asserts the exclusion literal is exactly that set (#8's advisory A5). Importing `otc_seed` from projector **tests** has a precedent (`services/seed/tests/integration/test_seeded_outbox_has_nothing_to_publish.py:20-21` imports `otc_orders`); import-linter's independence contract governs source packages only. Its blind spot, stated: no seeded tie group.

### 11.5 Every emission and suppression, armed twice

The projector emits no domain fact; the rule lands on the signal and on the two suppressions (a redelivery, a malformed or unknown record). Each is armed by **deleting** it and by **corrupting a field the test supplied** (`tasks.md` group L).

---

## 12. Shared guards this feature extends (an instrument change swaps its premises)

| Guard | Edit | New premises, each armed (`tasks.md` F2, F3, K3, K4, K5) |
|---|---|---|
| `services/orders/tests/unit/test_idempotent_consumer_parity.py` | §6.5 | P1 a package on disk missing from the registry fails; P2 a stale entry fails; P3 a `no-consumer` referencing `AIOKafkaConsumer` fails; P4 a `documented-variant` without its file fails (the OI12 opt-out); P5 a variant whose conformance line is missing or names a non-existent file fails; P6 a registry whose consuming set differs from `asyncapi.yaml`'s consumer names fails |
| `tests/architecture/test_registration_behaviour.py` | `SERVICES += ["projector"]`; `TABLES["projector"]` (one command); a census: `SERVICES` equals the composition roots that define `build_dispatcher` | the census fails when a service with `build_dispatcher` is missing from `SERVICES` |
| `tests/architecture/test_composition_env_reads.py` | `EXPECTED_ROOTS`, `LOAD_SETTINGS_ROOTS`, `EXPECTED_SETTINGS["projector"] = {"KafkaSettings", "MongoSettings", "NatsSettings"}` | an extra settings class, or a direct `os.environ` read in the projector, fails |
| `tests/architecture/test_kafka_client_confinement.py` | `EXPECTED_IMPORTERS += "otc_projector.infrastructure.messaging.kafka_fact_subscriber"` | a second projector module importing aiokafka fails |
| `tests/architecture/test_kafka_client_ids.py` | `PROJECTOR_KAFKA_CLIENT_ID`; five distinct defaults | the projector's default equal to Notifications' fails |
| import-linter, `test_money_guard.py` | none — they already list the projector | each made non-vacuous by a planted violation |

`tests/architecture/test_write_path_population.py` already excludes `projector` with its reason (`:59-63`) and is not edited; `test_cqrs_registration_explicit.py` is not edited unless a decorator outside `ALLOWED_DECORATORS` is needed, which the design avoids (no `@final`, no `@runtime_checkable`; `assert_never` is a function).

---

## 13. #8's backlog, classified

Command (this session): a regex over every entry of `../order-to-cash-dotnet/feature_list.json` serialised whole — `projector|read[ _-]?model|readmodel|order_timeline|timeline|causal|causation|placeholder|status ?rank|statusRank|update signal|uq_order_reference|sole writer|headerComplete|processedEventKeys|replay` (case-insensitive). **27 hits.** The regex is the population; the subject is the classification.

| Id | Subject | Disposition |
|---|---|---|
| 24 | the feature itself | this feature |
| 8 | contracts package | consumed (`FACT_MODELS`, generated stream models) |
| 12 | seed job | consumed: the document shape, the index, the constants file (`PR34`, `PR39`, `PR40`) |
| 52 | retroactive ledger for decode boundaries (incl. the projector's read path) | applies: AVOIDED by construction — §10 is written at port time; the decode boundary is L41/L50 |
| 57 | completion pair without a causal edge | applies: consumed (#9 Billing, `payment_register.py:142`); guarded by `R24`'s tie-group case |
| 58 | hand-written envelope copy unguarded | applies: AVOIDED — `PR37`, sentinel per field at the entry, header and signal hops |
| 60 | envelope fixture collisions | applies: AVOIDED — §11.1 rule 3; `tasks.md` I1 asserts the builders' distinctness |
| 65 | totals transposition survives (Gateway mapper) | applies in its projector form (#8's own sweep found `retailerCode`↔`companyCode` and `initialAmount`↔`initialDiscount` survivors in its projection): `PR37` header sentinels; the Gateway half is feature 25 |
| 66 | the operator note reaches the timeline | applies: built and armed, `PR46`; end to end is feature 41 |
| 68 | composition wiring unguarded | applies: AVOIDED — `tasks.md` H3 (each setting reaches the adapter it configures, Notifications' precedent) |
| 71 | the note survives every compensation branch | projector half: `PR46` per branch (§4.2); Orders half: feature 41 |
| 85 | fixtures self-assign host ports | applies: AVOIDED — root `conftest.py` Docker-held ports only; any private container in this feature likewise |
| 100 | timeline money read as minor units | applies: AVOIDED — `format_money` (SA-5), `PR16` EUR/JPY/BHD |
| 105 | the causal-order check is vacuous without `causationId` | the API helper is feature 31's; the projector half is `PR30`/`PR33`, armed by deleting the stored `causationId` |
| 27 | observability and reliability | owned by feature 27 (the projector's retry, DLQ, OTel) |
| 74, 75, 104 | DLQ test selection, `x-first-failed-at`, DLQ producer default | owned by feature 27 |
| 94 | a recorded offset arm stops killing once a retry wrapper exists | owned by feature 27: re-run `PR38`'s arm after the wrapper lands (noted in the hand-over) |
| 29, 30 | web app; web component tests | owned by features 29 and 30 (the waiting state, "caused by") |
| 31 | API tests | owned by feature 31 (`R24` API half, `R55` gateway half) |
| 41 | operator cancel responder | owned by feature 41 |
| 69, 102 | Gateway readiness pacing; problem-detail money | owned by feature 25 |
| 103 | web currency exponent | owned by feature 29 |
| 78 | C# doc-comment `cref`s never compiler-checked | not applicable: no XML doc comments; the Python analogue (a docstring-only edit) is the sweep's sentinel B |

27 rows of ids (some grouped): 24, 8, 12, 52, 57, 58, 60, 65, 66, 68, 71, 85, 100, 105, 27, 74, 75, 104, 94, 29, 30, 31, 41, 69, 102, 103, 78 — 27.

---

## 14. Live walkthrough (stated in advance; `tasks.md` N)

Against the developer stack with a fresh `projector` group from `earliest`:

- Recorded **before** the boot: the end offsets of the three topics; a count of records per `eventId` (the 16 duplicates from Phase 11's redelivery, `progress/current.md:21`); `order_timeline`'s document count and one seeded document in full; `getIndexes()`.
- The seeded facts are **not** on Kafka: the seed writes its outbox rows already published (`services/seed/tests/integration/test_seeded_outbox_has_nothing_to_publish.py`), so no seeded document is touched — verified by enumeration (every seeded `eventId` absent from every topic) before the boot.
- Expected after: every live order since Phase 8 has one document; for every document `len(events) == len(processedEventKeys)` and no `eventId` repeats (the duplicates suppressed); `ORD-000007` is `confirmed`; `ORD-000008`, `-010`, `-011` `completed`; `-009`, `-012` `cancelled`; every order whose `order.placed.v1` is not on a topic (probe facts, the Billing-only `ORD-000090` if it emitted any fact) is a `headerComplete: false` placeholder — recorded and explained one by one, not predicted.
- Expected absence: no new order, fact, outbox row or saga command; while one order is placed end to end, `nats sub 'readmodel.>'` shows the frames.
- A real process restart (N4): no entry appears twice anywhere.

---

## 15. Out of scope

`requirements.md` §5 in full. In particular: no route beyond the two health probes, no SSE, no DLQ, no OpenTelemetry, no change to a fact, topic or envelope, and no edit outside `tasks.md`'s file list.
