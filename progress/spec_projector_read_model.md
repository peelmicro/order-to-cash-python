# `projector_read_model` (id 24, phase 12, `sdd: true`) — spec pass (assessment #9, Python)

**Author:** `spec_author` · **Date:** 2026-10-11 · **Brief:** `progress/brief_spec_projector_read_model.md` (premise check `progress/premise_projector_read_model_spec.md`, its one FALSE item — lesson 8's location — corrected in the brief and followed here)
**Deliverables:** `specs/projector_read_model/{requirements,design,tasks}.md` (241 / 630 / 154 lines). `feature_list.json` not edited; the leader sets 24 to `spec_ready`. **`specs/shared/` not edited by this pass.** One spec amendment is **proposed** (`SA-6`, a description-only alignment of `openapi.yaml`), conditional on gate row G1 — §5.

**Normative range:** `R50` – `R53` (flipped by this feature); `R54`, `R55` (projector halves only; the rows stay `TODO`, scoped and ratified — row R1). `R11`, `R12`, `R17`, `R18` inherited `DONE`, not re-flipped; `R24`/`R28`'s causal-order clauses are `PR10`'s acceptance, their other halves features 31 and 32.
**Local ids:** #8's `PR1` – `PR28`, `PR30` – `PR45` reused (themselves #7's where they exist), each with a *#9 note* where the mechanism differs; `PR29` not reused (#8's reason holds: `timeline.py:63, 98-102`); **`PR46` – `PR52` new in #9**, each naming why #8 could not have faced it. 51 `PR` ids, traced in 26 rows of `requirements.md` §3 plus the six shared rows.
**Ported-idiom ledger:** `design.md` §10 — **65 boundaries enumerated, 65 rows**, both halves cited with file and line, "none" cited by search.
**#8 backlog:** regex over `../order-to-cash-dotnet/feature_list.json` → **27 hits**, one disposition each (`design.md` §13): 14 bear on 24 (the feature itself; 3 consumed — 8, 12, 57; 10 built and armed or avoided by construction with a named guard — 52, 58, 60, 65, 66, 68, 71, 85, 100, 105), 12 owned by a named later #9 feature (27, 29, 30, 31, 41, 69, 74, 75, 94, 102, 103, 104), 1 not applicable (78).
**Tasks:** **82**, of which **75 carry `[ARM]`**. The 7 unflagged: A2 (baseline run), A3 (leader-owned `.env.example`, recorded not performed), B1, E1, G1 (code boxes that name the tasks arming them), K8 (a green run), O5 (the report).
**Classification for the leader:** full group (persistence, the read-model wire contract, all fourteen facts, a shared-guard edit in Orders' tests) → Opus reviewer.

---

## 1. Evidence produced by command in this session

| # | Command (abridged) | Result |
|---|---|---|
| E1 | `sha256sum specs/shared/{openapi.yaml,asyncapi.yaml,requirements.md,domain-model.md,saga.md,test-matrix.md}` in all three repositories | the first five identical in #7, #8, #9 (`8dd55cf5…`, `56ec7c72…`, `694d71b1…`, `ef8a3ebf…`, `c2829f87…`); `test-matrix.md` differs, as its column 5 must |
| E2 | `python3 -I <scratchpad>/b8.py ../order-to-cash-dotnet/feature_list.json` (regex `projector\|read[ _-]?model\|readmodel\|order_timeline\|timeline\|causal\|causation\|placeholder\|status ?rank\|statusRank\|update signal\|uq_order_reference\|sole writer\|headerComplete\|processedEventKeys\|replay`, case-insensitive, over each entry serialised whole) | **27** ids: 8, 12, 24, 27, 29, 30, 31, 41, 52, 57, 58, 60, 65, 66, 68, 69, 71, 74, 75, 78, 85, 94, 100, 102, 103, 104, 105 |
| E3 | `docker run -d --rm --name otc9-probe-mongo -p 127.0.0.1::27017 mongo:8.3.8`; `.venv/bin/python -I <scratchpad>/probe/p1.py mongodb://127.0.0.1:32769/` | **M1** `$setOnInsert` of a whole document: top-level `_id` then lexicographic (`cancellationReason, company, currency, events, headerComplete, items, orderDate, orderId, orderReference, processedEventKeys, references, retailer, status, statusRank, timelineOrderVersion, totals, updatedAt`); nested `retailer` kept `code, name, gln`. **M3** a later pipeline `$set` (incl. dotted `retailer.code`) kept every position; a new key appended last. **M3b** `find_one_and_update` with the default returned the pre-update `status`. **M4** pipeline `$set` of `"retailer.code"` onto `retailer: null` → `{'code': 'R1'}`, no error. **M5** identical re-create OK; plain-unique vs existing partial `uq_order_reference` → `86 IndexKeySpecsConflict`; partial vs existing plain → `86 IndexKeySpecsConflict`; stored filter `{'$type': 'string'}`. **M6** two `orderReference: null` documents under the partial index: OK. **M7** `{"n": 5, "big": 2**31, "huge": 2**62}` stored as `int`, `Int64`, `Int64`. (Probe M2, a `$replaceWith` upsert, was malformed — `$type: "$_id"` is never missing on an upsert — and is relied on nowhere.) |
| E4 | same container, `probe/p2.py` | an entry with `detail.lastError = "$$NOW x"` placed unwrapped in a pipeline: `9 FailedToParse … 'NOW x' contains an invalid character for a variable name`; wrapped in `$literal`: stored verbatim. A scalar `"$status"` unwrapped stored `'placed'` (the document's own status); wrapped: `'$status'` |
| E5 | `.venv/bin/python -I -c "bson.encode({'x': uuid.uuid4()}); bson.encode({'x': 2**63}); bson.decode(bson.encode({'x': aware datetime}))"` | `ValueError: cannot encode native uuid.UUID with UuidRepresentation.UNSPECIFIED`; `OverflowError: MongoDB can only handle up to 8-byte ints`; `datetime.datetime(2026, 1, 1, 0, 0)` (naive) |
| E6 | `timeout 60 .venv/bin/python -I -c "await nats.connect('nats://127.0.0.1:1', connect_timeout=1)"`; again with `max_reconnect_attempts=2, reconnect_time_wait=0.5`; `grep -n DEFAULT_ nats/aio/client.py` | default: still connecting at 60 s, killed (`exit 143`); bounded: `NoServersError` in **1.01 s**; `DEFAULT_RECONNECT_TIME_WAIT = 2`, `DEFAULT_MAX_RECONNECT_ATTEMPTS = 60` (`client.py:91-92`), the initial-connect loop at `:616-640` |
| E7 | `grep -rn '\$literal'` over `../order-to-cash-nestjs/apps/projector/src` (`*.ts`, specs excluded) and `../order-to-cash-dotnet/src/Projector/Infrastructure/Persistence/*.cs` | #7: no hit; #8: no `$literal` operator — a wider `grep -rn literal` returns four lines, all comments using the English word (`InstantWire.cs:9`, `PlaceholderDocument.cs:28, 32`, `ReadModelCollection.cs:9`) |
| E8 | `grep -n` in `.venv/…/pymongo/asynchronous/collection.py` and `aiokafka/consumer/consumer.py` | `update_one(… upsert: bool = False` (`:1217`); `find_one_and_update(… upsert: bool = False, return_document: bool = ReturnDocument.BEFORE` (`:3522-3523`); `auto_offset_reset="latest"`, `enable_auto_commit=True` (`:246-247`) |
| E9 | `grep -n -A1 '^name = "…"' uv.lock`; `ls .venv/…/{nats,pymongo}/py.typed` | `aiokafka 0.14.0` (`:21-22`), `nats-py 2.16.0` (`:762-763`), `pymongo 4.18.2` (`:1179-1180`), **no `motor`**; both `py.typed` present |
| E10 | `grep -l '__tablename__ = "processed_events"' services/*/src/otc_*/infrastructure/persistence/models.py`; `ls services/*/src/otc_*/infrastructure/messaging/idempotent_consumer.py`; `grep -rl AIOKafkaConsumer services/*/src` | ledgers: orders, fulfillment, billing, notifications; consumer files: orders, notifications; Kafka consumers: orders, notifications |
| E11 | `grep -rn causation services/*/src`; `grep -n "triggering_event_id\|uuid4" …/orders/…` | every responder stamps its fact's `causationId` with the request id: `stock_reservation.py:92, 136`, `despatch_creation.py:90`, `credit_hold.py:116`, `credit_release.py:64`, `invoice_issue.py:131-132`; Orders sends `x-request-id` = the `saga_commands` row id (`nats_saga_commands.py:146`, `command_dispatcher.py:90`), a `uuid4()` (`command_queue.py:36`); the trigger is stored only in Orders' write model (`models.py:198`, `triggering_event_id`) |
| E12 | `grep -rIn "fact that caused this one"` over the three repositories (build output excluded at the source) | `specs/shared/openapi.yaml:1501` in all three; #7 `packages/contracts/src/generated/openapi.types.ts:952`; #8 `apps/web/src/generated/openapi.ts:747`; #9 nothing outside `specs/` |
| E13 | `grep -rln causation` over the responders' tests | #9 Fulfillment + Billing: 43 test files (25 source files); #8 `tests/Fulfillment.*`, `tests/Billing.*`: 20; #7 `apps/{fulfillment,billing}/src/**/*.spec.ts`: 29 |
| E14 | `grep -rIno "openapi\.yaml:1[5-9][0-9][0-9]\|openapi\.yaml:[2-9][0-9]{3}"` in each repository, `progress/` excluded | 0, 0, 0 — no line citation would shift if `SA-6` adds two lines at 1501 |
| E15 | `docker ps --format '{{.Names}}'` after `docker stop otc9-probe-mongo` | `otcpy-n8n` only; the developer stack was not started |
| E16 | `grep -rniE "nest\|drizzle\|nuxt\|mysql\|typescript\|dotnet\|efcore\|mssql\|csharp\|python\|fastapi\|sqlalchemy\|postgres\|angular" specs/shared/`, then dropping `honest`/`nested`/`earnest` | 3 hits, `openapi.yaml:435, 507, 1614`, all the identifier `TimelineStreamEntry` (`timeli`**`nest`**`ream`): not a stack term. `specs/shared/` was not edited by this pass |

---

## 2. Decided — inherited from #7 and #8, adopted (Python forces no difference)

| Decision | #7 | #8 | Where in #9 |
|---|---|---|---|
| The update signal is a NATS core publish on `readmodel.order.updated.<id>` / `readmodel.timeline.appended.<id>` | gate row 2 (approved) | gate row 3 (inherited) | design §7.1 |
| The NATS connection is established at boot, so a bad URL fails the boot, and `PR19` is never made to re-raise | eager `connect()` (`nats-client.ts:10`) | **gate row 1, GATE — APPROVED as recommended, 2026-09-07** (`PR45`) | `PR45`; the bound is the Python mechanism (§3) |
| The seed is allow-listed by name as the second writer | gate row 4 | gate row 4 | `PR20` |
| `uq_order_reference` is partial | gate row 1 (seed edited) | row 5 (inherited from its seed) | already partial in #9's seed (`mongo.py:39-44`): no seed edit |
| `R54`/`R55` split into projector and gateway/web halves | gate row 3 (the shared edit) | row 2 (RATIFY) | row R1 below |
| Idempotency as a documented variant inside the document | row 5 | row 7 | `PR23` – `PR26` |
| The dedup key repeats the `eventId` (the key is the pair) | row 6 | row 8 | design §6.2 |
| One `ProjectFactCommand`, not fourteen | row 15 | row 16 | `PR27` |
| `updatedAt` is the greatest `occurredAt` | row 11 | row 12 | `PR14` |
| The fourteen-row status table, terminal ranks 98/99 | row 12 | row 13 | `PR12` |
| No document → `202`; `headerComplete: false` → `200` | row 13 | row 14 | requirements §4 (feature 25's) |
| `earliest`, the opposite of Notifications | row 10 | row 11 | `PR5`, `PR38` |
| A failed signal is logged and swallowed | row 18 | row 19 | `PR19` |
| Amendment A1 folded in from the start | A1 (`requirements.md:61-69, 147-155`) | requirements header | requirements header; `PR10`, `PR30` – `PR35` |
| `PR29` (backfill) not ported | — | row 6 | requirements §2.11 |
| One routing table | — (two lists) | row 20 | `PR36` |

## 3. Forced by Python or by #9's own code, decided without the gate (the answer is the predecessors' property)

| Decision | Evidence | Where |
|---|---|---|
| The placeholder is created with `$setOnInsert`, as #9's seed creates its documents, not with #8's `$replaceWith`: the server then gives both writers the same lexicographic order | E3 M1, M3; `mongo.py:48-50`; #8 `PlaceholderDocument.cs:18-37` | design §3.2, ledger L12 |
| Every fact-derived value in the pipeline is `$literal`-wrapped | E4, E7 | `PR47`, ledger L14 |
| The placeholder's nested objects carry `null` leaves, never a `null` object | E3 M4; #7 `mongo-read-model-writer.ts:57-64` | `PR8`, ledger L13 |
| Integer widths follow the value, as the seed's do; not #8's Int64-always | E3 M7, E5; contracts bound money to int64 (`generated/asyncapi.py:133-135`) | design §3.1, ledger L23 |
| Ids are `str(UUID)`, instants `.mmmZ` strings | E5 | `PR41` |
| `nats.connect` wrapped in `asyncio.timeout` | E6 | `PR45`, ledger L45 |
| The fourteen arms live in `application`, not `domain` | `domain-purity` counts indirect imports (`pyproject.toml:170`); `otc_contracts` is pydantic | `PR28`, design §4.1 |
| `/health/live` and `/health/ready` exist (#8's projector had no HTTP surface) | #9 Notifications' `presentation/app.py`; the skeleton's own `/health/live` | `PR21` note, `PR50` |
| A registered type whose payload fails its model propagates (no commit) | #9 Notifications `notification_facts_consumer.py:15-18` | `PR4` |
| The parity guard gets #7's registry, which #8 did not port | §4 Q2 | `PR48`, design §6.5 |
| Indexes are read back and compared after creation | acceptance 3 | `PR52` |

---

## 4. Answers to the brief's questions

**Q1 — backlog 201.** Gate row G1 (§5). In short: the Projector **cannot** resolve a responder fact's command id to its trigger without a shared change — the command id is a `uuid4()` (E11), no fact carries it, and the only mapping is Orders' `saga_commands.triggering_event_id`, a write model `R54` forbids the projector to read. So (a) is necessarily an `SA-6` on `asyncapi.yaml` plus code in three services in each of three repositories; (b) needs no code change, and one description in `openapi.yaml` is then false and must be aligned.

**Q2 — the idempotent-consumer parity guard.** #9's guard discovers its population from files the implementer chooses to create (E10; `test_idempotent_consumer_parity.py:50-66, 120-150`): the OI12 flaw (#7 `history.md:974`). #7 closed it with a literal registry of every app plus a variant case requiring a `Behavioural conformance:` line naming an existing file (`idempotent-consumer.parity.spec.ts:68-77, 308-340, 493-530`); #8 did not port the registry — its case 4 skips a service without `IdempotentConsumer.cs` (`IdempotentConsumerParityTests.cs:99`) and the conformance-line check lives in the projector's own `VariantBannerTests.cs:18`. **#9 owes #7's registry, plus a cross-check against `asyncapi.yaml`'s declared consumers**, so the population is fixed by a literal and by the shared contract, never by the subject. **Yes, it changes the Orders guard** (test file only): design §6.5, `PR48`, tasks F1 – F3, six new premises armed.

**Q3 — inherited decisions.** NATS core publish: adopted (§2). Eager connect: #8's GATE row 1 was **approved as recommended** (`../order-to-cash-dotnet/progress/spec_projector_read_model.md:74-80`); adopted, and Python adds only the bound (E6). Seed allow-list and partial index: adopted. None is a gate question.

**Q4 — Python rows.** PyMongo async, not Motor (L19, E9); loop affinity of the client, the NATS connection and the consumer (L29, L49, design §8.3); atomic and replay-deterministic updates via one pipeline `$set` with `$sortArray`, `$ifNull`, `$literal` and a dict-ordered `sortBy` (design §5.3 – §5.4; no `/` anywhere, L64); stored instants equal to the seed's (L22, L65); cancellation (L43); `Any` confined to `infrastructure` (L30). Each row cites both halves and names an armed guard.

**Q5 — `R54`/`R55` halves.** This feature appends the projector half's evidence to both rows' existing two-half cells and leaves them `TODO`; features 25 (`R54` gateway half, `R55` gateway half), 26 (the stream) and 29 (the web half) close them. Matrix rule 3 (`test-matrix.md:22`) admits a scoped row only when ratified by someone other than its author: row R1 below, exactly as #7 (its row 3) and #8 (its row 2) did.

---

## 5. Open for the gate — one decision, one signature

### G1 — backlog 201 (acceptance 7): **recommendation (b)**, with `SA-6` aligning one `openapi.yaml` description

**The decision.** (a) Make a responder fact's `causationId` the `eventId` of the fact that triggered its command (an RPC header carrying the trigger, set by Orders from `saga_commands.triggering_event_id`, used by every responder), or (b) keep `R12`'s either-or (*"the `eventId` of the fact — or the identifier of the command"*, `requirements.md:133-136`) and have every claim about "caused by" describe what a live timeline shows: links between the facts Orders and Billing chain themselves.

**Recommendation: (b).** Strongest evidence: **(a) would create causal edges between facts stamped by different services' clocks, and the shared ordering rule cannot keep those edges cause-before-effect.** `R50` and `openapi.yaml`'s `TimelineEntry` (lines 1482 – 1491) order by `occurredAt` first and use an edge only inside a tie group; today every live edge lies inside one tie group because a derived fact reuses its trigger's instant (design §5.4: `step_table.py:89-92, 107-108`, `fact_handler.py:105-111`, `payment_register.py:138-143`), so the shared `R24` API invariant `assertCausalOrder` — "the cause precedes the effect" for every linked pair (`test-matrix.md:124`) — holds by construction. Under (a), `stock.reserved.v1` would name `order.placed.v1` across two clocks; any skew larger than the processing latency puts the effect first and fails that shared test, unless `PR10` is changed to rank edges above `occurredAt`, which contradicts `R50`. And the projector cannot do (a) on its own (§4 Q1).

**The counter-argument, stated rather than hidden.** `R12`'s purpose clause says the chain should be *"reconstructible from the facts alone"*. Under (b) it is, for every Orders-emitted fact and Billing's internal pair; across an RPC hop it is not — the link from a responder fact back to its trigger exists only in Orders' `saga_commands` table and in the trace (`R56` – `R57`). #7 and #8 shipped exactly this and closed `R12` `DONE` on the either-or text. (b) accepts it; (a) is what would remove it.

**Cost, in all three repositories.**

| | (a) | (b) |
|---|---|---|
| `specs/shared/` | `SA-6` on `asyncapi.yaml`: a new optional `RpcHeaders` header and its rule on the six fact-producing saga commands (`stock.reserve`, `stock.release`, `despatch.create`, `credit.hold`, `credit.release`, `invoice.issue`), and a rule for commands with no triggering fact (`orders.create`, the operator cancel's compensations, `payment.register`) | `SA-6` on `openapi.yaml`: one description (below) |
| Code per repository | Orders' command sender; Fulfillment's and Billing's header parsing and six handlers; their tests (E13: 43 files reference causation in #9's two responders, 20 in #8's, 29 in #7's); #7's and #8's operator-cancel paths | none; #7 and #8 regenerate one generated types file each (E12) |
| Repositories reopened | #7 and #8, both complete, as full-group (wire contract, saga) changes | #7 and #8 for a regeneration only |
| What it buys | "caused by" on six more fact types in the UI | — |

**`SA-6` under (b), byte for byte.** In `specs/shared/openapi.yaml`, identical in all three repositories (E1), replace lines 1501 – 1503:

```
            The `eventId` of the fact that caused this one; ties on `occurredAt` are ordered
            so that a fact follows its cause. Absent on an entry projected before this field
            existed.
```

with:

```
            The `eventId` of the fact — or the identifier of the command — that caused this
            one (R12). Only a fact's `eventId` can name another entry of the timeline: a fact
            produced by an RPC responder names the command that requested it, which is never
            an entry. Ties on `occurredAt` are ordered so that a fact follows a cause it names.
            Absent on an entry projected before this field existed.
```

(the `description: >-` line above them and the 12-space indent unchanged; `TimelineStreamEntry.causationId` says "Same field as `TimelineEntry.causationId`" and needs no edit). The file grows by two lines; no line citation of `openapi.yaml` beyond 1501 exists in any repository (E14). Applying it, per the SA convention: the leader edits the three copies byte-identically and confirms equal `sha256`; regenerates #7's `packages/contracts/src/generated/openapi.types.ts` and #8's `apps/web/src/generated/openapi.ts` and runs each repository's contracts drift check (the SA-2 lesson, #7 `history.md:1490`); runs #9's contracts tests (no generated #9 file carries the sentence, E12); commits it on its own, before this feature's implementation commit; adds the `SA-6` row to every README registry and an entry to every `progress/history.md`. `R12` is not reworded, and `requirements.md`, `domain-model.md` §7.1 (`:450`) and `asyncapi.yaml` (`:2184`) already state the either-or.

**What the ruling changes in this feature.** Nothing in the projector's code either way (`PR30` stores `causationId` verbatim). Task O3 replaces the seed README's pending sentence (`services/seed/README.md:21`) with the ruling. Backlog 201's acceptance 2 (README and UI claims) is feature 29's acceptance item 7, which this ruling feeds. **If the gate takes (a)**, it is a separate human-gated work item across three repositories (an asyncapi `SA-6` and its code), not this feature; task O3 says to stop and report.

### R1 — RATIFY (a signature, not a question)

Matrix rule 3(b) (`test-matrix.md:22`) requires the scoped `R54`/`R55` rows to be ratified by someone other than their author before this feature can close with them `TODO`. Approving this spec is that ratification; `requirements.md` §4 and task O2 cite this row as where it was given.

**2 open points: 1 GATE (G1), 1 RATIFY (R1).**

---

## 6. Notes for the leader (not gate points)

1. **`.env.example` (task A3, root config, yours):** a "Projector" block with `PROJECTOR_KAFKA_CLIENT_ID=otc-projector` and `PROJECTOR_CONSUMER_GROUP=projector` (#7's names, `../order-to-cash-nestjs/.env.example:144-145`) and the replay warning of design §2.2. The implementer will not edit it.
2. **A defect latent in #7 and #8 (E4, E7):** both projectors place fact text unwrapped into an aggregation pipeline, so an operator note beginning with `$` (SA-2 made free text reach that path) is either replaced by another field's value or fails the update with `FailedToParse` and blocks its partition. It is per-assessment code, not shared spec, in two completed repositories. Recommendation: record it in #9's history and the stack comparison as a predecessor finding; fix it there only if the maintainer asks. #9 builds the guard (`PR47`).
3. **nats-py's default initial connect (E6)** retries ≈120 s before failing. Orders, Fulfillment and Billing call `nats.connect(url)` with the defaults (`composition.py:333`, `:282`, `:290`), so a wrong `NATS_URL` should delay their boot failure by about two minutes — **measured on the client, not on those services' boots.** Recommendation: a five-minute check (boot one of them with `NATS_URL` on a closed port and time it) before deciding between a light fix in this phase (the same `asyncio.timeout` the projector uses) and acceptance; I did not run it, because it starts a service outside this pass's bounds.
4. **Effort baselines for the history entry:** #8 ≈5 h 04 min from first source file to verdict, rejected three times, every rejection on records (`../order-to-cash-dotnet/progress/history.md:1546`); #7 ≈3 h 41 min including its spec, rejected once on bookkeeping (`../order-to-cash-nestjs/progress/history.md:988`).
5. **Review classes to pre-empt** (both predecessors' reviews, mapped into `tasks.md`): a ledger engine claim probed one way (#8 D1/D4 → L10/L11 run both orders, H1); tests that cannot fail (#8 D2 → every guard has a named arm); a retired claim surviving elsewhere (#8 D5 → enumerate on the retired wording if any correction lands); a message naming a literal code (#8 A2/A8 → H1 asserts the raised code); a name promising an unexercised half (#8 A3, #7 N6 → G4 applies a reference-changing fact; J2 names `PR11` for what it proves); a box ticked over an undelivered clause (#8 A4, #7 N1 → the header's tick-or-reword rule); an exclusion list as control flow (#8 A5 → J7's declared literal); a replay that skips Kafka (#8 A6 → J6 goes through Kafka); transcribed sweep output (#8 A12 → M3 pastes); the seam never walked in one run (#7 N4 → N3); `current.md` stale (#7 N2/N11, #8 D3 → the leader's, at the transition).

## 7. Hand-over recorded for later features

- **25 `gateway_rest_auth`:** read `order_timeline` excluding `statusRank`, `processedEventKeys`, `timelineOrderVersion` (`PR33`); `events[].causationId` is public; placeholders (`headerComplete: false`, `orderReference: null`) appear in the list (#7 N7); no document → `202 ProjectionPending`.
- **26 `gateway_sse_push`:** subscribe `readmodel.order.updated.*` / `readmodel.timeline.appended.*` (or the single order's subjects); at-most-once; payloads are the generated `OrderStreamUpdate` / `TimelineStreamEntry` wire JSON.
- **27 `observability_reliability`:** a registered type with an invalid payload is redelivered forever until the DLQ wrapper exists (`PR4`); a duplicate `uq_order_reference` in the apply would be a poison record (#7 N8); after the retry wrapper lands, **re-run** `PR38`'s and I4's arms (#8 id 94); readiness bounds.
- **29 `web_app`:** "caused by" per G1's ruling (acceptance 7).
- **31 `api_tests`:** under (b) every live causal edge lies inside a tie group, so `assertCausalOrder` holds structurally; its minimum-edge count (#8 id 105: three on a completed happy path) applies.
- **41 `orders_cancel_responder`:** the note end to end (acceptance 4); the operator branch from `credit_approved`/`confirmed` adds a `credit.released.v1` → `order.cancelled.v1` tie group (`saga.md:306`), which `PR10` already orders.

---

## Gate ruling (2026-10-11, maintainer: "Approved")

**G1 — APPROVED as recommended: option (b).** R12's either-or is kept; no projector code depends on the ruling. **`SA-6`** is taken exactly as §5 writes it (one `TimelineEntry.causationId` description in `specs/shared/openapi.yaml`, applied byte-identically to #7, #8 and #9, generated files regenerated where they carry it, committed on its own before this feature's implementation commit, recorded in every README registry and every `progress/history.md`). Task O3 records the ruling in `services/seed/README.md`.

**R1 — RATIFIED.** `R54`/`R55` close this feature with their projector halves evidenced and the rows `TODO`, owned by features 25, 26 and 29.

**Notes §6 — rulings on the leader's recommendations.** (2) The `$`-prefixed note defect latent in #7 and #8 is recorded as a predecessor finding in #9's history and the Stack Comparison; #7 and #8 are not changed. (3) The unbounded `nats.connect` in Orders, Fulfillment and Billing is fixed in this phase as a **light** change, backlog **214**, attached to feature 24 (findings are fixed in the phase that detects them).
