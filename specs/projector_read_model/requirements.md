# `projector_read_model` — Requirements (assessment #9, Python)

> **The normative requirements for this feature are `R50` – `R55` in [`specs/shared/requirements.md`](../shared/requirements.md) §7** (lines 439 – 470), elaborated by [`domain-model.md`](../shared/domain-model.md) §7.1 (the envelope), §7.2 (the fourteen facts) and §7.3 (the projector is the only consumer of all fourteen); [`saga.md`](../shared/saga.md) §4.3 (the operator-cancel compensation branches, SA-4); [`asyncapi.yaml`](../shared/asyncapi.yaml) (the three fact topics, the `projectorConsumes*` operations at lines 672 – 720, `OrderCancelledPayload.note` from SA-2 at line 2627); and [`openapi.yaml`](../shared/openapi.yaml) (`TimelineEntry` with `causationId` and the amendment-A1 ordering rule at lines 1482 – 1518, `OrderDetail`, `ProjectionPending`, `OrderStreamUpdate`, `TimelineStreamEntry`). None of that is restated here.
>
> This file cites the `R<n>` ids it realises, **reuses #8's local `PR<n>` ids** (themselves #7's, checked one by one; `../order-to-cash-dotnet/specs/projector_read_model/requirements.md`) wherever the Python realisation satisfies the same obligation, marks each reuse whose mechanism differs with a *#9 note*, and adds `PR46` – `PR52`, each with the reason #8 could not have faced it. `PR29` is not reused, for #8's reason (§2.10).

> **Inherited, not re-owned.** `R11`/`R12` (envelope, correlation, causation) and `R17`/`R18` (idempotency) are `DONE` in `specs/shared/test-matrix.md` and are not re-flipped; `R17`/`R18` are satisfied here as a **documented variant** (`PR23` – `PR26`, `PR48`). `R24` and `R28`'s *causal order* clauses are the acceptance of `PR10`; their rows' remaining halves belong to features 31 and 32 and are not re-owned.

> **`R50`'s "ordered by `occurredAt`" and acceptance item 1's "ordered by the recorded causal edge, not by clock" are one rule, not two.** #7 reconciled them in its amendment **A1** (`../order-to-cash-nestjs/specs/projector_read_model/requirements.md:61-69`, `PR10` "amended by A1"), which `openapi.yaml`'s `TimelineEntry` description already carries in the shared contract: the timeline is ordered by `occurredAt` ascending (R50's primary key, never arrival order), and **within a tie group** — entries sharing one identical `occurredAt` — a fact follows the fact its `causationId` names; where no recorded edge separates two tied entries, `eventId` ascending. #8 folded A1 in from the start (`PR10`, `PR30` – `PR35`). Acceptance item 1 is read exactly as #7 and #8 read it: inside a tie group the clock cannot decide, so the recorded edge does, and nothing is ever ordered by arrival, by `eventType` or by a status. The primary key stays `occurredAt` because the shared rule says so; `design.md` §5.4 shows that every live causal edge in #9 lies inside one tie group (four sources, cited), so the two readings never disagree on live data.

> **Done gate.** This feature is `done` when: `R50`, `R51`, `R52`, `R53` are `DONE` in `test-matrix.md` §7 with real file and case names; `R54` and `R55` carry the projector half's evidence in their existing two-half Status cells and stay `TODO`, scoped and ratified under matrix rule 3 (§4; the ratification is gate record row R1); every `PR` row of §3 is `DONE` or carries a recorded, reviewer-accepted reason; every `[ARM]` task of `tasks.md` has a verbatim failure recorded in `progress/impl_projector_read_model.md`; acceptance items 1 – 8 of `feature_list.json` id 24 are each mapped to evidence in that record; and the gate's ruling on backlog 201 (gate record row G1) is applied.

---

## 1. Vocabulary local to this feature

| Term | Meaning here |
|---|---|
| **read-model document** | One MongoDB document in `otc_read_model.order_timeline`, `_id` = the order id = the fact's `correlationId` (`R12`), in **the shape `services/seed/src/otc_seed/domain/timeline.py:65-103` already writes** (`PR41`, `PR44`). |
| **placeholder** | A document created by a fact other than `order.placed.v1`: header unknown, `headerComplete: false` (`R53`, `PR8`). |
| **implied status / status rank** | `PR12`'s table: the status a fact proves has been reached (or none), totalised by an integer so `R52`'s "precedes" is a `$max`. Document-level only, never a timeline ordering key (`PR30`). |
| **tie group**, **causal edge**, **causal depth**, **fallback key** | As #8 `requirements.md` §1 defines them: entries sharing one `occurredAt`; *`p` caused `c`* iff `c.causationId == p.eventId` within the tie group; distance from a cause-less entry of the group; `eventId` ascending. |
| **timeline-order version** | `2`, equal to `tests/fixtures/read_model_constants.json`'s `timelineOrderVersion` (`PR40`). |
| **dedup key** | `"projector:<eventId>"` — `ConsumerName.PROJECTOR.value + ":"` + the id — in `processedEventKeys` (`PR23`). The prefix equals the constants file's `processedEventKeyPrefix`. |
| **the atomic apply** | The single `find_one_and_update` whose **filter is the idempotency check** and whose aggregation-pipeline update is the whole projection of one fact (`PR6`). |
| **update signal** | Two NATS core publishes (no reply subject, no responder) announcing that a document changed (`PR17`). Not a fact, not a command. |
| **the variant** | `services/projector/src/otc_projector/infrastructure/messaging/idempotent_consumer.py` — the MongoDB rendering of the idempotent-consumer pattern, registered as `documented-variant` in the Orders parity guard (`PR24`, `PR48`). |
| **literal-wrapped** | A value taken from a fact and placed in an aggregation-pipeline update inside `{"$literal": value}`, so the server never evaluates it as an expression (`PR47`). |

---

## 2. Local requirements

### 2.1 The consumer surface

**PR1.** THE SYSTEM SHALL consume the three fact topics `otc.orders.facts.v1`, `otc.fulfillment.facts.v1` and `otc.billing.facts.v1` through **one** asyncio Kafka consumer task over the projector's `FactStreamSubscriber` port, under the consumer group `projector`; and SHALL register **no** NATS subscription of any kind — no responder, no request, nothing carrying a reply subject. IF a NATS subscription or a fourth topic is introduced, THEN `PR1`'s structural test SHALL fail. *#9 note:* the task is owned by the runtime and awaited on shutdown (`CLAUDE.md` § Architecture), the Notifications shape (`services/notifications/src/otc_notifications/composition.py:199-216`).

**PR2.** THE SYSTEM SHALL handle **all fourteen** `eventType`s of `domain-model.md` §7.2, and SHALL prove that coverage in **both** directions against `otc_contracts.FACT_MODELS` (`packages/contracts/src/otc_contracts/facts.py:47-62`), the one registry whose own test already compares it against `asyncapi.yaml`: a registered type with no projection arm, and an arm for a type not registered, SHALL each fail a named test. *#9 note:* the arms are a `match` over the `FactEvent` union (`facts.py:30-45`) ending in `assert_never`, so `mypy --strict` also rejects a missing arm; a test runs `mypy` over a fixture that omits one (the shape of `services/billing/tests/unit/domain/test_invoice_state.py`'s `test_bi23_mypy_rejects_a_match_that_omits_a_case`).

**PR3.** IF a record's value cannot be parsed as a complete envelope (not JSON, not an object, any of the seven `R11` fields absent, null or empty, a non-UUID id, an `eventType` off-pattern, a naive `occurredAt`, or an empty value from a tombstone), THEN THE SYSTEM SHALL log one structured error carrying topic, partition, offset and reason, SHALL write nothing, SHALL publish no signal, and SHALL commit the record's offset.

**PR4.** IF a well-formed envelope carries an `eventType` that `FACT_MODELS` does not register, THEN THE SYSTEM SHALL log one structured error naming the type, SHALL write nothing, SHALL publish no signal and SHALL commit — never a bare `return`. IF a registered type's payload fails its generated model, THEN THE SYSTEM SHALL let the error propagate (no commit, paced redelivery), as #9's Notifications does (`notification_facts_consumer.py:15-18`); its dead-lettering is feature 27's (`R16`).

**PR5.** THE SYSTEM SHALL start a consumer group with no committed offset at the **earliest** offset (`auto_offset_reset="earliest"`, against aiokafka's default `"latest"`, `aiokafka/consumer/consumer.py:246`), because the read model is a derived store rebuilt by replay. Guarded by `PR38`.

### 2.2 The document, and the write that maintains it

**PR6.** THE SYSTEM SHALL apply each fact in exactly **two** MongoDB operations and no others: (1) `update_one({"_id": orderId}, {"$setOnInsert": <placeholder>}, upsert=True)`, a no-op by construction on an existing document; then (2) **one** `find_one_and_update` whose filter is `{"_id": orderId, "processedEventKeys": {"$ne": <dedupKey>}}`, whose update is **one** aggregation pipeline carrying the entire projection of the fact, with `return_document=ReturnDocument.AFTER` (`PR42`). THE SYSTEM SHALL NOT read the document in order to decide what to write. Proven by recording the driver's command stream (pymongo `monitoring.CommandListener`), the only way to prove the absence of a read.

**PR7.** WHEN two deliveries of the **same** `eventId` for one order are applied concurrently from **separate** `AsyncMongoClient` instances, THE SYSTEM SHALL apply exactly one and report the other `DUPLICATE`. WHEN two deliveries of **different** `eventId`s for one **absent** order are applied concurrently, THE SYSTEM SHALL end with exactly one document holding both entries; IF the losing upsert raises `pymongo.errors.DuplicateKeyError` on `_id`, THEN THE SYSTEM SHALL retry that one operation exactly once and SHALL NOT surface the error. Every other error propagates.

**PR8.** WHEN a fact is applied to an order that has no document, THE SYSTEM SHALL create one whose `_id` and `orderId` are the `correlationId` as a lowercase hyphenated string, `headerComplete` `false`, `status` `placed` with `statusRank` `0`, `timelineOrderVersion` current, `events`, `items` and `processedEventKeys` empty arrays, `updatedAt` the triggering fact's own `occurredAt`, and every other field present: `orderReference`, `orderDate`, `cancellationReason`, `currency` explicit `null`, and `retailer`, `company`, `totals`, `references` as **objects whose every leaf is an explicit `null`** — never a `null` object (`PR41`'s measured reason, design §3.3). Rank `0` is below `order.placed.v1`'s `1`.

**PR9.** THE SYSTEM SHALL set `headerComplete` to `true` only when `order.placed.v1` is applied, in the same atomic apply that writes `orderReference`, `orderDate`, `retailer.code`/`.gln`, `company.code`/`.gln`, `currency`, `totals` and `items` **unconditionally**. `retailer.name`, `company.name` and `items[].name` are on no fact and stay `null` in a projected document (`R54` forbids the lookup).

**PR10.** THE SYSTEM SHALL store `events` sorted by the causal timeline order — (1) `occurredAt` ascending; (2) a tie group is a maximal set of entries with one identical `occurredAt`; (3) within a tie group, `p` is the cause of `c` iff `c.causationId == p.eventId`, `p` in the group, `p ≠ c`; (4) causal depth `0` without a cause, else `1 + depth(cause)`, evaluated as a fixpoint over at most `|events|` rounds; (5) within a tie group, depth ascending, then `eventId` ascending — **re-sorting the whole array inside the atomic apply on every write**. THE SYSTEM SHALL NOT infer an edge from `eventType`, a status, a rank or arrival; the depth is computed and discarded inside the stage, never stored.

**PR30.** THE SYSTEM SHALL store the envelope's `causationId` verbatim, as a lowercase hyphenated string, on every entry it appends, and SHALL store no ordering key derived from `eventType` on any entry.

**PR31.** THE SYSTEM SHALL make `PR10`'s order total over every stored entry set without erroring, dropping or duplicating: a `causationId` naming nothing in the tie group (another group, a fact never received, a command id) means depth `0`; a cycle terminates deterministically with every entry present once; two tied entries no edge separates (including two siblings of one cause) order by `eventId`; an entry with **no** `causationId` is cause-less (`$ifNull`), not an error.

**PR11.** THE SYSTEM SHALL write `references.despatchReference`, `references.invoiceReference` and `references.paymentReference` only while null, inside the atomic apply, each from its own fact only (`R52`).

**PR12.** THE SYSTEM SHALL derive each fact's implied status and rank from this table and SHALL raise `status`/`statusRank` only when the new rank is strictly greater than the stored one:

| `eventType` | Implied status | Rank |
|---|---|---:|
| `order.placed.v1` | `placed` | 1 |
| `stock.reserved.v1` | `stock_reserved` | 2 |
| `credit.approved.v1` | `credit_approved` | 3 |
| `order.confirmed.v1` | `confirmed` | 4 |
| `order.despatched.v1` | `despatched` | 5 |
| `invoice.issued.v1` | `invoiced` | 6 |
| `payment.received.v1` | `paid` | 7 |
| `order.completed.v1` | `completed` | 98 |
| `order.cancelled.v1` | `cancelled` | 99 |
| `stock.rejected.v1`, `stock.released.v1`, `credit.rejected.v1`, `credit.released.v1`, `order.saga_failed.v1` | *(none)* | 0 |

The nine status → rank pairs SHALL equal `tests/fixtures/read_model_constants.json`'s `statusRank` (`PR40`).

**PR13.** THE SYSTEM SHALL set `cancellationReason` from `order.cancelled.v1` only, and only while null.

**PR14.** THE SYSTEM SHALL set `updatedAt` to the greatest `occurredAt` applied so far (`$max` over fixed-width `.mmmZ` strings), never a clock or an arrival time.

**PR15.** THE SYSTEM SHALL make every field of a document a pure function of the **set** of facts applied to it — independent of arrival order, delivery count, wall clock and generated identifiers. Consuming the topics twice, or a shuffled permutation with duplicates, SHALL produce a document whose **raw BSON bytes** are identical (element order included). `processedEventKeys` is stored sorted (`$sortArray`); no identifier is generated anywhere in the service (no `uuid4`, `UniqueId.new`); no counter, arrival index, partition or offset field exists on the document.

### 2.3 The human-readable summary (`R50`)

**PR16.** THE SYSTEM SHALL build each entry's `summary` and optional `detail` from the envelope alone, in pure functions with no read-model access and no clock, producing **#7's fourteen strings** (`../order-to-cash-nestjs/apps/projector/src/domain/summaries.ts`) for the same payloads; money via `otc_shared_kernel.format_money` (SA-5 exponent: `(9245, "EUR")` → `"92.45 EUR"`, `(5000, "JPY")` → `"5 000 JPY"`, `(12345, "BHD")` → `"12.345 BHD"`), the formatter the seed's summaries already use (`services/seed/src/otc_seed/domain/data/sagas.py:524`); `detail` only for `stock.rejected.v1` (`shortages`, `reason`), `stock.released.v1` (`released`, `reason`), `credit.rejected.v1` (`reason`, `requestedAmount`), `order.cancelled.v1` (`cancellationReason`, `compensationSteps`, and `note` per `PR46`) and `order.saga_failed.v1` (`command`, `attempts`, `lastError`).

### 2.4 The update signal (`R55`)

**PR17.** THE SYSTEM SHALL announce every applied change with two NATS **core publishes** on the one connection the runtime owns — `readmodel.order.updated.<orderId>` carrying `openapi.yaml`'s `OrderStreamUpdate` and `readmodel.timeline.appended.<orderId>` carrying `TimelineStreamEntry` (with `causationId`) — each serialised by `otc_contracts.to_wire_json` from the generated model, each with a fresh headers mapping carrying `x-correlation-id = <orderId>`.

**PR18.** THE SYSTEM SHALL publish the signal only after the atomic apply returned a document, built from that **post-apply** document; a suppressed redelivery produces no signal.

**PR19.** IF publishing fails, THEN THE SYSTEM SHALL log one structured error (`eventId`, `correlationId`, both subjects), SHALL NOT re-raise, and SHALL commit the fact: the apply already happened, so a redelivery would be suppressed and could never re-emit.

### 2.5 Sole writer, no write model (`R54`)

**PR20.** THE SYSTEM SHALL make `services/projector` the only runtime writer of `order_timeline`: within `services/*/src`, only `projector` and `seed` may call a pymongo **write-shaped** method (`insert_one`, `insert_many`, `update_one`, `update_many`, `replace_one`, `find_one_and_update`, `find_one_and_replace`, `find_one_and_delete`, `delete_one`, `delete_many`, `bulk_write`, `create_index`, `create_indexes`, `drop`, `drop_index`, `drop_indexes`, `drop_collection`, `create_collection`, `rename`), the seed allow-listed **by name with its reason inside the guard** (an offline fixture loader run before the system runs). The guard SHALL scan production source only, SHALL permit a read anywhere, SHALL prove non-vacuity on both allow-listed services and on a scratch tree, and SHALL state its limitations (a same-named unrelated method is a false positive; `$out`/`$merge` inside `aggregate` is a false negative).

**PR21.** THE SYSTEM SHALL give the projector no write-model access: no `sqlalchemy`, `asyncpg` or `alembic` dependency in `services/projector/pyproject.toml`, no `infrastructure/persistence/models.py` with a `processed_events` table, no NATS request to any subject. *#9 note:* #8's "no HTTP surface" clause is **not** reused: the projector serves exactly `/health/live` and `/health/ready` and no other route, the shape #9's Notifications set (`services/notifications/src/otc_notifications/presentation/app.py`) and the skeleton already has.

**PR22.** THE SYSTEM SHALL create, idempotently at boot and before the consumer starts, `uq_order_reference` (`{orderReference: 1}`, unique, `partialFilterExpression: {orderReference: {$type: "string"}}`) and `ix_status_updatedAt` (`{status: 1, updatedAt: -1}`). IF the server refuses a creation as conflicting — code `85` (`IndexOptionsConflict`) or `86` (`IndexKeySpecsConflict`; measured this session for a plain-versus-partial `uq_order_reference`, both creation orders) — THEN the boot SHALL fail with a message naming the index, the code the server actually raised and the `dropIndex` one-liner.

### 2.6 The idempotent-consumer variant

**PR23.** THE SYSTEM SHALL implement `R17`/`R18` as a documented variant whose ledger is the document's own `processedEventKeys`, written by the same single operation that applies the projection (`PR6`): one write, so the standalone `mongo:8.3.8` (no transactions) costs nothing.

**PR24.** THE SYSTEM SHALL own `services/projector/src/otc_projector/infrastructure/messaging/idempotent_consumer.py`, whose module docstring cites the canonical path literal `services/orders/src/otc_orders/infrastructure/messaging/idempotent_consumer.py`, carries a line beginning `Divergence:` and a line `Behavioural conformance: <repo-relative path>` naming a test file that **exists**; and SHALL own no `processed_events` table. *#9 note:* the Orders parity guard is **edited by this feature** (`PR48`), unlike #8's `PR24`, because #9's copy of it selects its population by a file the implementer chooses to create.

**PR25.** THE SYSTEM SHALL prove the variant against the five conformance cases over **real MongoDB**: (1) first call `PROCESSED`, post-apply work once; (2) same `(eventId, consumer)` `DUPLICATE`, work not run; (3) a **fresh instance over the same database** still `DUPLICATE`; (4) two distinct `eventId`s both run; (5) the same `eventId` under a **different** consumer name runs.

**PR26.** WHILE the conformance cases run, the subject SHALL be the real variant over the real driver, the pipeline a dedup-only `$set`, and the work the post-apply callback, counted (invoked once on `PROCESSED`, never on `DUPLICATE`).

### 2.7 The application shape

**PR27.** THE SYSTEM SHALL route every fact through `otc_cqrs` as **one** `ProjectFactCommand(Command[ProjectionOutcome])` carrying the parsed `FactEvent`, handled by **one** handler registered explicitly in `composition.py`; the registry is built over `otc_projector.application` and validated in the lifespan before any connection is opened, so zero or two handlers fail the boot.

**PR28.** THE SYSTEM SHALL keep `otc_projector.domain` free of every framework, store and wire dependency (import-linter `domain-purity`, `pyproject.toml:187-218`, already lists `otc_projector.domain`). *#9 note:* because `otc_contracts` is pydantic and `domain-purity` counts indirect imports, the fourteen-arm projection over the generated events lives in `application` (as #9's Notifications templates do); the domain holds the store-agnostic `ProjectionDelta` value objects, the rank table and the reference implementation of `PR10`'s rule.

### 2.8 Migration, and the wire (from A1)

**PR32.** WHEN the projector starts, THE SYSTEM SHALL bring every document to the current timeline-order version before consuming, selecting by `{timelineOrderVersion: {$ne: <current>}}` — never by presence or absence of a field — re-sorting `events` with the **same** expression the live apply uses, stamping the version and touching no other client-visible field; a document already current receives no write.

**PR35.** THE SYSTEM SHALL NOT invent a `causationId`; the migration's boot log SHALL report the number of documents migrated and how many of them still hold an entry with no `causationId`.

**PR33.** THE SYSTEM SHALL treat `events[].causationId` as part of the public read contract (stored on every entry, carried on every `timeline.appended` signal). `statusRank`, `processedEventKeys` and `timelineOrderVersion` are internal; feature 25 excludes them from every read.

**PR34.** WHERE the seed writes fixture documents, each entry SHALL carry `causationId` from the fixture's declared chain and the document SHALL be stamped current. **Satisfied by inheritance**: `services/seed/src/otc_seed/domain/timeline.py:63` and `:99`.

### 2.9 New in #8, reused

**PR36.** THE SYSTEM SHALL decide which facts it handles and how their payloads are typed from **one** table, `FACT_MODELS` (through `otc_contracts.parse_fact`), with **no** second list of `eventType` strings under `services/projector/src`; a scan of that tree for the fourteen literals SHALL classify every hit.

**PR37.** THE SYSTEM SHALL carry `eventId`, `eventType`, `correlationId`, `causationId` and `occurredAt` from the envelope to the stored entry and to both signal payloads, and every `order.placed.v1` header field to the document, such that corrupting or transposing any one copied field fails a named test with a sentinel value the test supplied. *#9 note:* the wire → command hop copies nothing by hand (the whole envelope is parsed by the generated model, Notifications' answer to #8 id 58); the entry, header and signal hops are hand-written and are the guarded ones.

**PR38.** THE SYSTEM SHALL build its consumer with `group_id == ConsumerName.PROJECTOR.value == "projector"`, `client_id == "otc-projector"` (both from settings, #7's variable names), `auto_offset_reset == "earliest"`, `enable_auto_commit == False`, and SHALL commit an offset only after the handler returned — proven on the options the runtime actually passes, and by an integration case where a raising handler leaves the committed offset unchanged, **read from the broker**, never inferred from a redelivery. *#9 note:* aiokafka's offset contract is an explicit `commit({tp: offset + 1})` plus `seek` on failure (Notifications' `kafka_fact_subscriber.py:7-13`), not #8's auto-commit of stored offsets.

**PR39.** THE SYSTEM SHALL create `uq_order_reference` with keys, uniqueness, name and partial filter identical to the seed's (`services/seed/src/otc_seed/infrastructure/mongo.py:39-44`), such that the seed's creation then the projector's, **and** the projector's then the seed's, raise nothing on one collection.

**PR40.** THE SYSTEM SHALL keep its timeline-order version, its nine status → rank pairs, its dedup-key prefix and its `uq_order_reference` definition equal to `tests/fixtures/read_model_constants.json` — the file the seed is pinned to (`services/seed/tests/unit/test_read_model_constants.py`) — asserted by tests that read the projector's own constants and the file, so bumping the projector's version alone fails a named test (acceptance 6, backlog 212's projector half).

**PR41.** THE SYSTEM SHALL write element names as camelCase literals equal to the seed's (`timeline.py:65-103`); every id as `str(UUID)` (lowercase, hyphenated — pymongo refuses a native `uuid.UUID` under its default representation, measured); every instant as a `.mmmZ` string from `otc_contracts.wire.format_instant` (never `isoformat()`, never a BSON date, which pymongo decodes naive, measured); every integer as the Python `int` the fact carries, so its BSON width is pymongo's by magnitude — Int32 below 2³¹, Int64 above (measured) — exactly as the seed's documents get theirs; `detail` built from the generated sub-models' JSON form (`model_dump(mode="json", by_alias=True)`), absent when the fact has none.

**PR42.** THE SYSTEM SHALL call `find_one_and_update` with `return_document=ReturnDocument.AFTER` (pymongo's default is `BEFORE`, `pymongo/asynchronous/collection.py:3523`, measured), and the `order.updated` signal's `status`, `references`, `cancellationReason` and `totals` SHALL equal the stored post-apply values.

**PR43.** THE SYSTEM SHALL run, in `start_runtime` and in this order, before the consumer task is created: the dispatcher's validation, a MongoDB round trip, index creation and verification (`PR22`, `PR52`), the timeline-order migration (`PR32`) and the NATS connection (`PR45`); IF any step raises, THEN the lifespan SHALL fail and everything already opened SHALL be closed. *#9 note:* ordering is statement order in one coroutine (as #7's `main.ts`), not #8's hosted-service registration order; it is guarded by an ordered call log.

**PR44.** THE SYSTEM SHALL, for each of the six seeded sagas, project that saga's own outbox facts (`SAGAS[i].orders_outbox`, `.fulfillment_outbox`, `.billing_outbox`, `services/seed/src/otc_seed/domain/data/sagas.py:174-180`) through the real writer into an empty collection, and the stored document SHALL equal the document the **real seed** stores for that saga (`MongoTimelineTarget.seed`), raw BSON element order and types included, on every field except this enumerated set: `retailer.name`, `company.name`, `items[].name` (master data, `PR9`) and `events[].detail` (the seed's hand-written subset; `PR16`'s builders are its oracle). The exclusion set SHALL be a declared literal the test asserts against.

**PR45.** WHEN the projector starts, THE SYSTEM SHALL establish the NATS connection to completion inside `start_runtime`, before the consumer starts, **within a bound**; IF it cannot, THEN the boot SHALL fail rather than run with every signal swallowed by `PR19`. It SHALL NOT be satisfied by making `PR19` re-raise. *#9 note:* `nats.connect` is eager (unlike #8's lazy `NatsConnection`), but with its defaults it keeps retrying 60 × 2 s before raising `NoServersError` (measured: still connecting after 60 s; with 2 attempts it raised in 1.01 s), so the bound is #9's own.

### 2.10 New in #9 — each names why #8 could not have faced it

**PR46 — SA-2: the operator note reaches the cancellation entry on every branch (acceptance 5).** WHEN `order.cancelled.v1` carries `note`, THE SYSTEM SHALL store it verbatim as `detail.note` of that entry, whatever the `cancellationReason` and whatever the `compensationSteps` (none, `[stock_released]`, `[stock_released, credit_released]` — `saga.md:219-221`); WHEN it carries none, `detail` SHALL have no `note` key. *Why new:* #8 closed it in backlog ids 66/71 after its projector shipped; #9 builds it in. The Orders half (a note travelling through each compensation chain end to end) is feature 41's acceptance 4.

**PR47 — fact text is never evaluated by the server.** THE SYSTEM SHALL place every value taken from a fact into the aggregation-pipeline update **literal-wrapped**, so a string beginning with `$` (an operator note `"$status"`, a `lastError` `"$$NOW x"`) is stored verbatim rather than evaluated as a field path or variable. *Why new:* measured this session on `mongo:8.3.8`: an unwrapped `"$status"` was stored as the document's own `status` value (`'placed'`), and an unwrapped `"$$NOW x"` failed the whole update with `FailedToParse` (code 9) — a poison record. Neither #7 (`grep '\$literal'` over `apps/projector/src`: no hit) nor #8 (no hit in `src/Projector/Infrastructure/Persistence`) wraps; SA-2 made free operator text reach the pipeline in both.

**PR48 — the parity guard's population is declared, not discovered.** THE SYSTEM SHALL classify **every** service package under `services/` in a literal registry in `services/orders/tests/unit/test_idempotent_consumer_parity.py` as `relational-copy`, `documented-variant` or `no-consumer`; SHALL fail when a package on disk is missing from it, when a registered package does not exist, when a mode disagrees with the files (a `no-consumer` that references `AIOKafkaConsumer`, a `relational-copy` without the ledger, a `documented-variant` with one), and when the set of consuming packages differs from the consumers `asyncapi.yaml`'s fact `receive` operations name (`Consumer name — orders.saga`, `— projector`, `— notifications`); and a `documented-variant` SHALL carry the canonical path, a `Divergence:` line and a `Behavioural conformance:` line naming a file that exists. *Why new:* #9's guard selects variants by `has_relational_ledger` and the presence of `idempotent_consumer.py` (`test_idempotent_consumer_parity.py:50, 137-150`) — #7's OI12 flaw (`../order-to-cash-nestjs/progress/history.md:974`), which #7 itself closed with exactly this registry (`apps/orders/src/infrastructure/messaging/idempotent-consumer.parity.spec.ts:68-77, 308-340, 493-530`) and #8 did not port (`tests/Orders.UnitTests/IdempotentConsumerParityTests.cs:99`).

**PR49 — registration proven by behaviour for this service (acceptance 8).** THE SYSTEM SHALL be a member of `tests/architecture/test_registration_behaviour.py`'s `SERVICES` with its `TABLES` literal (one command, no query, no event), so importing every module of `otc_projector` creates no registry and calls no `register_*`, every registration comes from a distinct statement of `composition.py`, and the built tables equal the recorded registrations; and THE SYSTEM SHALL fail its boot on zero and on two handlers, each proven by a test against this service's composition root.

**PR50 — readiness and shutdown.** THE SYSTEM SHALL answer `/health/ready` with `503` and its reasons while the consumer has not joined its group, after its task has ended for any reason, while the NATS connection is not connected, and while shutting down; and on shutdown SHALL stop the consumer after its in-flight record, cancel it after a bounded grace, await it, and close the NATS connection and the MongoDB client in the loop that opened them.

**PR51 — no process-wide state.** THE SYSTEM SHALL hold no deduplication or projection state outside MongoDB: no module-level mutable container and no instance attribute on the writer or the variant other than its collection handle. A runtime rebuilt in one process (new clients, new consumer) and a real process restart SHALL each suppress every already-applied fact. *Why new:* Phase 11's N2 — a runtime rebuilt in one process is not a process restart; the guard against a process-wide cache is named rather than assumed.

**PR52 — indexes checked against the server's stored specification (acceptance 3).** AFTER creating them, THE SYSTEM SHALL read the collection's stored index specifications and SHALL fail the boot, naming the index, IF `uq_order_reference` or `ix_status_updatedAt` differs in key, uniqueness or partial filter from the expected definition, or IF any **other** unique index covers `orderReference` (which would reject the second placeholder). *Why new:* #7 and #8 relied on the creation call's conflict error alone; a differently-named unique index on the same key raises no conflict for a create by name.

### 2.11 Deliberately not reused

**`PR29` (#7's legacy-document backfill)** is not ported, for #8's reason (#8 `requirements.md` §2.10): the seed has written `statusRank`, `processedEventKeys`, `timelineOrderVersion` and `causationId` since its first commit here too (`timeline.py:63, 98-102`), so a backfill filtered on `{statusRank: {$exists: false}}` could match nothing a writer produces. `PR6`'s pipeline stays total over any shape (`$ifNull` on every array and rank operand), and `PR32`'s migration is kept.

---

## 3. Traceability — local requirements to named tests

Shared `R50` – `R55` are traced in `specs/shared/test-matrix.md` §7. Paths below are under `services/projector/tests/` unless they start with `tests/` or `services/orders/`; `unit/` needs no container, `integration/` uses the root `conftest.py`'s Docker-held `mongo:8.3.8`, `apache/kafka:4.3.1` and `nats:2.14.5-alpine`.

| Id | Level | Test file › case | Status |
|---|---|---|---|
| **R50** | integration | `integration/test_timeline_projection.py` › `test_r50_appends_an_entry_carrying_event_id_event_type_occurred_at_and_a_summary_and_presents_the_timeline_ordered_by_occurred_at_rather_than_by_arrival` | DONE |
| **R51** | integration | `integration/test_timeline_projection.py` › `test_r51_leaves_the_read_model_document_unchanged_when_a_fact_with_an_already_present_event_id_is_redelivered` | DONE |
| **R52** | integration | `integration/test_out_of_order_facts.py` › `test_r52_appends_the_timeline_entry_without_regressing_the_document_status_or_overwriting_newer_references` | DONE |
| **R53** | integration | `integration/test_placeholder_document.py` › `test_r53_creates_a_placeholder_document_keyed_by_correlation_id_and_fills_in_the_header_fields_when_order_placed_is_consumed_later` | DONE |
| **R54** projector half | unit (structural) | `unit/test_read_model_sole_writer.py` › `test_r54_permits_a_read_model_write_only_in_the_projector_and_the_allow_listed_offline_fixture_loader_while_permitting_a_read_anywhere_and_declares_no_write_model_dependency_of_its_own` | DONE (projector half; the matrix row stays `TODO`, ratified: §4) |
| **R55** projector half | integration | `integration/test_update_signal.py` › `test_r55_emits_exactly_one_update_signal_per_applied_fact_on_a_per_order_channel_a_single_order_and_a_whole_stream_subscriber_both_receive_and_none_at_all_for_a_suppressed_redelivery` | DONE (projector half; the matrix row stays `TODO`, ratified: §4) |
| PR1, PR21 | unit (structural) | `unit/test_projector_consumes_only.py` › `test_pr1_one_kafka_consumer_task_over_the_three_fact_topics_and_no_nats_subscription_of_any_kind`, `test_pr21_no_write_model_dependency_no_ledger_table_no_nats_request_and_only_the_two_health_routes` | DONE |
| PR2 | unit | `unit/test_projection.py` › `test_pr2_projects_every_fact_models_entry_and_fails_in_both_directions_when_the_registry_and_the_match_disagree`; `unit/test_projection_exhaustiveness_mypy.py` › `test_pr2_mypy_rejects_a_projection_match_that_omits_a_fact` | DONE |
| PR3, PR4 | unit | `unit/test_projector_facts_consumer.py` › `test_pr3_a_malformed_envelope_is_logged_and_committed_with_no_dispatch`, `test_pr4_an_unregistered_event_type_is_logged_and_committed_never_silently`, `test_pr4_a_registered_type_with_an_invalid_payload_propagates` | DONE |
| PR5, PR38 | unit + integration | `unit/test_kafka_fact_subscriber_options.py` › `test_pr38_the_options_the_runtime_passes_are_earliest_projector_group_client_id_and_no_auto_commit`; `integration/test_offset_contract.py` › `test_pr38_a_raising_handler_leaves_the_committed_offset_unchanged_read_from_the_broker`, `test_pr5_a_fact_produced_before_the_group_ever_subscribed_is_projected` | DONE |
| PR6, PR41 | integration | `integration/test_projection_write.py` › `test_pr6_applies_one_fact_in_exactly_one_update_and_one_find_and_modify_issuing_no_read`, `test_pr41_element_names_order_and_bson_types_equal_the_seeds_document` | DONE |
| PR7 | integration | `integration/test_projection_concurrency.py` › `test_pr7_concurrent_deliveries_of_one_event_id_from_separate_clients_apply_exactly_once`, `test_pr7_concurrent_first_facts_for_an_absent_order_end_in_one_document_holding_both` | DONE |
| PR8, PR9 | integration | `integration/test_read_model_indexes.py` › `test_pr8_two_placeholders_with_null_order_reference_coexist`; `integration/test_placeholder_document.py` › `test_pr8_the_placeholder_holds_every_key_with_nested_objects_of_null_leaves`, `test_pr9_master_data_names_stay_null_in_a_projected_document`; `unit/test_placeholder.py` › `test_pr8_the_placeholder_is_total_over_the_seeds_key_set_with_nested_null_leaves` | DONE |
| PR10, PR30, PR31 | unit + integration | `unit/test_timeline_order_reference.py` › `test_pr10_the_reference_rule_orders_by_occurred_at_then_depth_then_event_id`; `integration/test_timeline_causal_order.py` › `test_r28_stock_released_precedes_the_order_cancelled_that_names_it_with_adversarial_event_ids`, `test_r24_the_completion_triple_is_stored_in_causal_order_with_adversarial_event_ids`, `test_pr10_the_pipeline_agrees_with_the_reference_rule_on_generated_entry_sets`, `test_pr31_a_cycle_a_foreign_cause_and_a_missing_causation_id_all_terminate_with_every_entry_once` | DONE |
| PR11, PR12, PR13 | unit + integration | `unit/test_delta_to_pipeline.py` › `test_pr11_a_reference_fact_fills_only_its_own_reference_if_null`, `test_pr13_cancellation_reason_is_filled_only_if_null`; `unit/test_projection.py` › `test_pr12_maps_each_of_the_fourteen_facts_to_the_tables_status_and_rank`; `integration/test_out_of_order_facts.py` › `test_pr11_each_reference_fact_fills_only_its_own_reference` | DONE |
| PR14, PR15 | integration | `integration/test_timeline_projection.py` › `test_pr14_updated_at_is_the_greatest_occurred_at_not_the_latest_arrival`; `integration/test_replay_determinism.py` › `test_pr15_replaying_the_topics_into_a_new_group_reproduces_byte_identical_documents`, `test_pr15_shuffled_and_duplicated_application_yields_byte_identical_documents` | DONE |
| PR16, PR46 | unit + integration | `unit/test_summaries.py` › `test_pr16_*` (one case per fact, whole string), `test_pr16_detail_is_present_only_for_the_five_named_facts`; `unit/test_projection.py` › `test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one`; `integration/test_timeline_projection.py` › `test_pr46_a_noted_operator_cancellation_stores_the_note_verbatim` | DONE |
| PR17, PR18, PR19, PR33, PR42 | unit + integration | `integration/test_update_signal.py` › `test_pr17_both_payloads_carry_openapis_required_fields_read_from_the_contract`, `test_pr33_the_timeline_appended_payload_carries_causation_id`, `test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references`; `unit/test_project_fact_handler.py` › `test_pr18_a_duplicate_publishes_nothing`, `test_pr19_a_publication_failure_is_logged_and_swallowed` | DONE |
| PR20 | unit (structural) | `unit/test_read_model_sole_writer.py` › `test_pr20_a_third_service_acquiring_a_write_shaped_call_fails_proved_on_a_scratch_tree` | DONE |
| PR22, PR39, PR52 | integration | `integration/test_read_model_indexes.py` › `test_pr22_creates_both_indexes_idempotently`, `test_pr22_a_plain_unique_index_of_the_same_name_fails_the_boot_naming_the_index_and_the_raised_code`, `test_pr39_the_seeds_index_then_the_projectors_and_the_reverse_raise_nothing`, `test_pr52_a_differently_named_unique_index_on_order_reference_fails_the_boot` (the other-index clause), `test_pr52_the_stored_partial_filter_is_compared_with_the_expected_definition` and `test_pr52_a_stored_non_unique_index_of_the_expected_name_fails_the_verification` (the stored-specification comparison: partial filter, uniqueness), `test_pr22_an_identical_index_under_another_name_fails_the_boot_naming_the_server_named_index` (code 85 names the server's index) | DONE |
| PR23, PR25, PR26 | integration | `integration/test_idempotent_consumer_conformance.py` › `test_pr25_case_1_…` – `test_pr25_case_5_…`, `test_pr26_the_post_apply_callback_runs_once_on_processed_and_never_on_duplicate` | DONE |
| PR24, PR48 | unit (structural) | `services/orders/tests/unit/test_idempotent_consumer_parity.py` › `test_pr48_every_service_package_is_registered_and_its_mode_matches_the_files_and_the_spec`, `test_case_4_a_variant_carries_a_divergence_banner_naming_the_canonical_and_an_existing_conformance_file` | DONE |
| PR27, PR49 | unit + architecture | `unit/test_composition.py` › `test_pr27_zero_handlers_fail_the_boot`, `test_pr27_two_handlers_fail_the_boot`; `tests/architecture/test_registration_behaviour.py` › `test_a_service_registers_only_from_its_composition_root_and_its_tables_match[projector]` | DONE |
| PR28 | architecture | `lint-imports` (`domain-purity`, `layers-projector`, `fact-producer-confinement`, `service-independence`) | DONE (`lint-imports`: 11 contracts kept, 0 broken, with the projector's `domain` populated) |
| PR32, PR35 | integration | `integration/test_timeline_order_migration.py` › `test_pr32_a_document_at_version_one_is_re_sorted_and_stamped`, `test_pr32_a_current_document_receives_no_write`, `test_pr35_never_invents_a_causation_id_and_reports_both_counts` | DONE |
| PR34 | — | satisfied by inheritance (`timeline.py:63, 99`), re-proven by PR44 | DONE (inherited; re-proven by PR44's six cases) |
| PR36 | unit (structural) | `unit/test_projection.py` › `test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set` | DONE |
| PR37 | unit | `unit/test_projection.py` › `test_pr37_every_envelope_field_reaches_the_entry_verbatim_sentinel_per_field`, `test_pr37_every_order_placed_field_reaches_the_header_verbatim_sentinel_per_field`; `unit/test_update_signal_payloads.py` › `test_pr37_every_field_reaches_both_signal_payloads_verbatim_sentinel_per_field` | DONE |
| PR40 | unit | `unit/test_read_model_constants.py` › `test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture` | DONE |
| PR43, PR45, PR50, PR51 | unit + integration | `unit/test_composition.py` › `test_pr43_start_runtime_runs_its_steps_in_order`; `integration/test_projector_lifespan.py` › `test_pr45_an_unreachable_nats_fails_the_boot_within_the_bound`, `test_pr50_readiness_drops_when_the_consumer_task_dies`, `test_pr50_shutdown_cancels_a_stuck_handler_after_the_grace`, `test_pr51_a_rebuilt_runtime_suppresses_every_applied_fact`; `unit/test_no_process_state.py` › `test_pr51_no_module_level_mutable_state_and_no_writer_state_beyond_the_collection` | DONE |
| PR44 | integration | `integration/test_seeded_oracle_parity.py` › `test_pr44_projecting_each_seeded_sagas_facts_reproduces_the_seeds_stored_document_except_the_declared_set` (six parametrised cases) | DONE |
| PR47 | unit + integration | `unit/test_delta_to_pipeline.py` › `test_pr47_every_fact_value_in_the_pipeline_is_literal_wrapped`; `integration/test_projection_write.py` › `test_pr47_dollar_prefixed_note_and_last_error_are_stored_verbatim` | DONE |

---

## 4. The `R54` / `R55` seam with features 25, 26 and 29

| Concern | Owner | Why |
|---|---|---|
| Writing `order_timeline`, the sole-writer guard, the indexes | **24** | `R54`'s "only writer" |
| Emitting the update signal | **24** | `R55`'s producer half |
| `GET /orders`, `GET /orders/{id}` from MongoDB only, excluding `statusRank`, `processedEventKeys`, `timelineOrderVersion` | **25** | `R54`'s consumer half (feature 25 acceptance 4) |
| `202 ProjectionPending`; serving `headerComplete: false` as `200` | **25** | `openapi.yaml` `/orders/{id}` |
| `/orders/stream` SSE, heartbeat, `Last-Event-ID` | **26** | the projector publishes; the Gateway holds the connection |
| The order-detail waiting state; "caused by" links | **29** | the web half of `R55`; backlog 201 item 2 |

`R54` and `R55` stay `TODO` at this feature's close. Under `test-matrix.md` rule 3 (line 22) they close only when **scoped and ratified**: the Status cell names the projector half's real tests, states the unproven leg in the requirement's own words (*"serve every order list and order detail query from the read model only"*; *"respond with an explicit 'projection pending' indication"*; the push channel's delivery to subscribed clients), and names the ratification — the human gate that approves this spec (gate record row R1). This is #7's split (its gate row 3) as #8 ratified it (its gate row 2).

---

## 5. Out of scope — restated so it is a decision, not an omission

- **No REST route** beyond `/health/live` and `/health/ready` (`PR21`).
- **No SSE, no replay buffer** — `PR17` publishes and stops.
- **No dead letter** beyond `PR3`/`PR4`'s log-and-commit; retry and `.dlq` are feature 27's. Carried for 27 (#7 review N8, #8 `requirements.md` §5): a duplicate-key error on `uq_order_reference` during the atomic apply (two order ids carrying one `orderReference`) is unreachable while `ORD-######` is unique and would be a poison record.
- **No OpenTelemetry** (`R56` – `R58`, feature 27).
- **No change to any fact, topic or envelope.** The two `readmodel.*` subjects are absent from `asyncapi.yaml`, inherited from #7's gate row 2 as #7 and #8 shipped them.
- **No edit** under `services/orders/src`, `services/fulfillment`, `services/billing`, `services/notifications`, `services/seed/src`, `services/gateway`, `packages/`, `apps/web` — with the named exceptions in `tasks.md`'s file list (the Orders parity test, three repository-level architecture guards, the seed's README sentence).
- **Backlog 201's decision** is the gate's (gate record row G1); its UI half is feature 29's acceptance item 7.
