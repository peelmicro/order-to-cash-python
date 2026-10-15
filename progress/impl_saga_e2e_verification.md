# impl: saga_e2e_verification (feature 28, phase 15, sdd: false, light / test-only)

Work window: 06:23 -> 06:41 CEST, 2026-10-13. Nothing under `services/`, `packages/`, `specs/`, `feature_list.json`, `progress/current.md` or the root `conftest.py` was changed (the three armed source edits were restored by `cp`; `cmp` clean, `git status` shows only `tests/saga_e2e/` as new beside the leader's two modified files).

## What was built

`tests/saga_e2e/` (new root directory; `uv run lint-imports`: 13 kept, 0 broken, so the independence contract does not object):

| File | Content |
|---|---|
| `conftest.py` | The `fleet` fixture (`loop_scope="function"`): private migrated copies of the Orders, Fulfillment and Billing databases from the root `migrated_database_from_template`, the REAL seed (`otc_seed.run_seed`: retailers, products, stock, credit lines), a fresh Mongo database, then the services' own `create_app()` with their own real lifespans, in the test's loop, booted in order **Fulfillment, Billing, Orders, Projector, Gateway** and exited in reverse by one `AsyncExitStack`. The Gateway is driven in-process over ASGI (`httpx.ASGITransport`), logged in as the operator. `Fleet` carries the typed readers (`rows`, `place`, `pay`, `wait_status`, `records`, `read_all`, `produce`, `observed_facts`, `facts_reach`, `eventually`). Support modules `tests/observability/dead_letter_support.py` is loaded by path (importlib mode) for the Kafka reader/producer. |
| `test_saga_paths.py` | items 1 and 2 |
| `test_redelivery_and_poison.py` | item 3 (two tests) |
| `test_one_trace_per_order.py` | item 4 (R56 composed-stack half) |

**Booted and why:** Fulfillment and Billing (the saga's participants, outbox relays on), Orders (responder, saga consumer, sweeper, relay), Projector (so `GET /orders/{id}` answers from the read model and its consumer is a second consumer of the poisoned topic), Gateway (the only entry the tests drive). **Not booted:** Notifications (no criterion observes an e-mail).

**Infrastructure:** root session fixtures only (`postgres_server` via the template factory, `mongo_server` via `fresh_mongo_database`, `kafka_server`, `nats_server`). The developer stack is down (`docker ps -a`: only `otcpy-n8n` is `Up`); no port 5432/27017/9092/4222 is referenced.

**Boundary choices (each written next to the code):**
- Kafka is ONE broker per session and the three fact topics and the group `orders.saga` are constants of the services, so before the fleet boots both consumer groups (`orders.saga`, and the Projector's, set here to a unique name) are committed at the END of the topics (manual assignment, no join). Tests select their records by order id (the Kafka key), never by position.
- Environment is set with `monkeypatch.setenv` before each `create_app()` (each lifespan reads its own `load_settings()`), cwd is an empty `tmp_path` and the `POSTGRES_*` variables are deleted, so a developer `.env` cannot supply a value.
- `FACT_RETRY_BACKOFF_MS=20` (default 500) so a poison does not cost seconds; attempts stay 3 (asserted as `x-attempts == 3`).
- Every wait is `Fleet.eventually`: a 100 ms paced probe with a 60 s bound that fails naming what never happened. No bare sleep anywhere in the tests.

## Criteria -> tests

| Item | Test | Proves |
|---|---|---|
| 1 happy path | `test_saga_paths.py::test_item1_a_placed_order_reaches_completed_after_a_payment_and_the_brokers_hold_exactly_the_nine_facts` | order reaches `invoiced` untouched, payment through the Gateway, `completed` in Orders' write model AND the Gateway-served read model (its `events` equal the nine fact types), brokers hold exactly the 9 literal facts, the reservation is `consumed` |
| 2 `.99` | `test_saga_paths.py::test_item2_a_dot_99_order_compensates_visibly_in_billing_fulfillment_and_orders` | three facts of three services: Billing's `credit.rejected.v1` reason `simulated_cents_rule` and `requestedAmount` 99; Fulfillment's reservation row `released` (units 1) plus the `stock.released.v1` fact; Orders' `cancellation_reason = credit_rejected`, status `cancelled`; the brokers hold exactly the 5 literal facts; no invoice and no despatch exist |
| 3a redelivery | `test_redelivery_and_poison.py::test_item3_an_already_processed_fact_delivered_again_changes_nothing_in_any_service` | the real `order.placed.v1` and `stock.reserved.v1` bytes republished on the same key (same partition), each followed by a fresh-`eventId` marker; positive marker = the marker's `saga_ignored_facts` row; asserts the order's ignored rows are exactly the two markers (a redelivery that slipped the guard would add its own) and the per-order footprint (8 row counts across the three databases) is unchanged and status still `completed` |
| 3b poison | `test_redelivery_and_poison.py::test_item3_a_poisoned_message_is_dead_lettered_byte_for_byte_by_both_consumers_and_the_partition_moves_on` | valid envelope with a bogus payload on the orders topic: dead-lettered byte for byte by BOTH consumers (`x-failed-consumer` = `orders.saga` and `projector`), `x-attempts` 3, `x-original-topic`, `eventId` equal; a valid fact behind it on the same key reached the saga (positive marker) and was not dead-lettered |
| 4 R56 | `test_one_trace_per_order.py::test_item4_r56_every_request_command_row_and_fact_of_one_order_carries_the_one_trace_id` | the Gateway requests (place AND pay) carry `traceparent 00-0af7651916cd43dd8448eb211c80319c-...`; the observed set of (kind, source, name) is asserted EQUAL to a literal set of 22: 9 outbox rows (Orders, Fulfillment, Billing `trace_parent`), 9 Kafka `traceparent` headers on the fact topics (read from the broker, key = order id), 4 `saga_commands.trace_parent` rows (`stock.reserve`, `credit.hold`, `despatch.create`, `invoice.issue`); every one carries the chosen trace id |
| 5 infrastructure down | the five tests ran with only `otcpy-n8n` up (`docker ps -a`) | testcontainers only |

## Ported-idiom ledger

| Idiom | Row |
|---|---|
| Composed fleet | #7 relied on spawned OS processes (`../order-to-cash-nestjs/progress/history.md:1059`, "real, separately-spawned `dist/main.js` processes"); #8 supplied it with in-process real hosts built from each service's static `CreateBuilder` (`../order-to-cash-dotnet/progress/impl_id28_saga_e2e_verification.md`, "Architecture - ported, not copied"); in #9 it is supplied by each service's `create_app()` + real lifespan entered in one `AsyncExitStack` in the test loop (`services/gateway/tests/integration/conftest.py:131-195` is the precedent). Guard: all five tests (they fail to start if any lifespan cannot boot). |
| Wait for the consumer group before publishing | #8 waited for the Orders group to be `Stable` (`impl_id28...md` "What broke" item 3); #9: the saga consumer joins in its lifespan and the fixture commits both groups at the end of the topics BEFORE any host boots, so nothing published by an earlier test is replayed and the first fact of the test is read from the committed position. Guard: `test_item3_an_already_processed_fact...` (`ignored_before == []`). |
| Positive marker, never a sleep | #8 `Criterion3`/`Criterion4` published a fresh fact on the same partition and waited for its `saga_ignored_facts` row (`SagaEndToEndVerificationTests.cs:229-420`); #9 does the same with a marker per redelivered topic (a marker on the orders partition says nothing about the fulfillment partition) and the same `saga_ignored_facts` table. Guard: arm (c). |
| Poison shape | #7: non-UUID `correlationId`; #8: bare JSON string where an object is declared (`Guid` field makes #7's unreachable); #9: a valid envelope whose payload does not validate (the S8b walkthrough's shape, `progress/impl_observability_reliability.md` S8b step 4). Guard: arm (b). |
| R56 identity | #7 composed its proof from outbox `traceParent` columns (spawned processes could not share a tracer); #8 read `outbox.trace_parent` and found three different ids, skipped on a real defect (`SagaCommandDispatchWorker` channel hand-off); #9 reads outbox rows, `saga_commands.trace_parent` AND the Kafka headers, and the fast-path hand-off holds (design L7/11): in #9 it is supplied by the dispatch task being created inside the consuming context (`command_dispatcher.py:118-125`, `_parent_of`). Guard: arm (a), which breaks exactly that line. |
| Event loop affinity | every async fixture is `loop_scope="function"`; engines, asyncpg connections, Kafka clients and the httpx client are created and closed in that loop; every lifespan exits (and awaits its tasks) in the `AsyncExitStack`. No module-level client. |
| JSON / timestamps | the republished/poison envelopes are re-serialised from the broker's bytes with `separators=(",", ":")`, `ensure_ascii=False`; the redelivery uses the broker's bytes untouched. |
| Cancellation on teardown | no test creates a task; the only tasks are the services' own, awaited by their lifespans on exit. A clean teardown is visible in the logs (`LeaveGroup request succeeded` for both groups). |

## #8 assertion classification (`SagaEndToEndVerificationTests.cs`)

| #8 assertion | Class |
|---|---|
| C1: POST /orders, poll to `invoiced`, register payment, poll `completed`, cross-check Orders row | ported (item 1; plus the broker fact set and the read-model timeline) |
| C2(a): Orders `cancellation_reason = credit_rejected` | ported |
| C2(b): Billing `credit.rejected.v1` reason `simulated_cents_rule` read from its outbox | ported, read from the broker record instead of the outbox row (the fact is what the contract promises) |
| C2(c): Fulfillment reservation row `released` | ported |
| C3: wait for a status of at least `stock_reserved` via a rank array (live saga can skip a poll tick) | not applicable: #9 waits for `invoiced`/`completed` and never needs an intermediate status |
| C3: republish real `order.placed.v1` byte for byte | ported (and extended to `stock.reserved.v1` on the fulfillment topic) |
| C3: second FRESH `order.placed.v1` as the marker, `saga_ignored_facts` row `precondition_unmet` | ported; #9 asserts the order's ignored rows are exactly the markers (stronger: detects an unguarded redelivery) and does not assert the `marker` text column |
| C3: exact row counts before/after for `saga_commands` and `reservations` | ported and widened to eight counts across the three databases |
| C4: `.dlq` copy byte-identical, `x-failed-consumer`, `x-original-topic`, `x-event-type` | ported except `x-event-type` (see "not asserted") |
| C4: well-formed unknown-order fact behind it, `saga_ignored_facts` `unknown_order` | ported (marker ignored row) |
| C5: R56 from `outbox.trace_parent` of three facts | ported and widened (22 observations, Kafka headers, command rows, explicit inbound `traceparent`); #8's was skipped for a production defect that does not recur here |

## Arms (three, light group), verbatim

Backups in `.arm/saga_e2e/` with sha256 (`arm_a.sha`, `arm_b.sha`, `arm_c.sha`); each restored by `cp`, `cmp` clean, `__pycache__` cleared, source `sha256` equal to the recorded value. One named test per arm.

**(a) R56**: `services/orders/src/otc_orders/infrastructure/saga/command_dispatcher.py` `_parent_of` returns `Context()` (a fresh root) where the live span is valid instead of `None`. `test_item4_r56_...` FAILED:

```
AssertionError: expected every observation in trace 0af7651916cd43dd8448eb211c80319c, differing: {('outbox row', 'orders', 'order.confirmed.v1'): 'b7c33ae333f99840821f49b13d774cfd', ('kafka header', 'orders', 'order.confirmed.v1'): 'b7c33ae333f99840821f49b13d774cfd', ('outbox row', 'fulfillment', 'stock.reserved.v1'): '846c5fdda11deadb82d2e606b9062eb7', ('outbox row', 'fulfillment', 'order.despatched.v1'): '7f0423eec93a541ad82eb664d302af3a', ('kafka header', 'fulfillment', 'stock.reserved.v1'): '846c5fdda11deadb82d2e606b9062eb7', ('kafka header', 'fulfillment', 'order.despatched.v1'): '7f0423eec93a541ad82eb664d302af3a', ('outbox row', 'billing', 'credit.approved.v1'): 'b7c33ae333f99840821f49b13d774cfd', ('outbox row', 'billing', 'invoice.issued.v1'): 'f78b8809aa38c11407d4131e4fcfa695', ('kafka header', 'billing', 'credit.approved.v1'): 'b7c33ae333f99840821f49b13d774cfd', ('kafka header', 'billing', 'invoice.issued.v1'): 'f78b8809aa38c11407d4131e4fcfa695', ('saga command row', 'orders', 'credit.hold'): '846c5fdda11deadb82d2e606b9062eb7', ('saga command row', 'orders', 'despatch.create'): 'b7c33ae333f99840821f49b13d774cfd', ('saga command row', 'orders', 'invoice.issue'): '7f0423eec93a541ad82eb664d302af3a'}
```

(13 of the 22 observations in other traces; the `order.placed`, `payment`, `credit.released`, `order.completed`, `stock.reserve` ones stay in the chosen trace, which shows the test localises the broken hop.)

**(b) DLQ**: `fact_retry.py`: the `await self._dead_letters.publish(` call replaced by building the value only (`_ = (DeadLetter(...))`), so the Orders saga never publishes. `test_item3_a_poisoned_message_...` FAILED:

```
TimeoutError: never happened within 60.0 s: both consumers dead-lettered the poison
```

**(c) Redelivery**: `idempotent_consumer.py`: `if inserted is None:` -> `if inserted is None and False:` (the (eventId, consumer) guard never reports a duplicate). `test_item3_an_already_processed_fact_...` FAILED:

```
AssertionError: a redelivered fact must be absorbed by the (eventId, consumer) guard: only the two markers are ignored
assert ['418c6a4b-37...6fb9e02fa00c'] == ['8650e941-dc...6fb9e02fa00c']
  Left contains 2 more items, first extra item: '8c48d981-0b07-4ffb-a4a1-52d22ff0ebe4'
```

The two extra items are the two redelivered facts reaching the status guard of a completed order. (The first arm-c run, before the assertion message existed, failed with the same two extra items.)

## Green runs

Command: `setsid --wait timeout -k 10 900 uv run pytest tests/saga_e2e -p no:cacheprovider --junitxml=.arm/saga_e2e/junit_run<n>.xml`

| Run | Exit | JUnit (`tests` / failures / errors / skipped) | Wall |
|---|---|---|---|
| 1 | 0 | 5 / 0 / 0 / 0 (pytest time 30.711 s) | 33 s |
| 2 | 0 | 5 / 0 / 0 / 0 (pytest time 28.812 s) | 31 s |

Also: `uv run ruff format --check` (1197 files already formatted), `ruff check` (all checks passed), `uv run mypy` (no issues in 977 source files), `uv run lint-imports` (13 kept, 0 broken), `tests/architecture` 703 passed (106.6 s; it scans `tests/`, no objection to the new directory). `quality.sh` was NOT run (the leader owns the full gate).

## Not done / not asserted

- `specs/shared/test-matrix.md` R56 row: not edited (outside my bounds). The leader should replace "composed-stack leg: feature 28" with `tests/saga_e2e/test_one_trace_per_order.py::test_item4_r56_every_request_command_row_and_fact_of_one_order_carries_the_one_trace_id` (and the R16/R17/R42 rows may cite items 2 and 3 as composed-stack complements).
- R56's second matrix leg ("e2e/trace-continuity: that same trace beginning at the inbound request and continuing through the CONSUMPTION of every fact") is covered at the data level (the request's id appears on the fact rows and headers and the `saga_commands` rows) but I did not read spans from Jaeger or an in-memory exporter: the fleet's lifespans build their own providers, and the S8b live walkthrough remains the span-level evidence (46 spans, 5 services, one trace). A consumer-span assertion would need a span processor injected into five runtimes (`start_runtime(span_processors=...)` exists for Orders only through `monkeypatch`); recorded as a deliberate scope limit.
- The Projector's side of redelivery (timeline entry count unchanged) and `x-event-type`, `x-error`, `x-first-failed-at` on the dead letter are not asserted here (they are proved per service by feature 27's `test_orders_dead_letter.py` / `test_projector_dead_letter.py`).
- The `payment.received` / `credit.released` / `order.completed` facts share the chosen trace because the test sends the SAME `traceparent` on the payment request. A payment request without one starts its own trace by design (R56 responder tests); this is a choice of the test, written in its docstring.
- Notifications is not in the fleet.

## Surprises and findings

1. **No production defect found.** #8's composed run found the fast-path trace hand-off broken; #9's holds on all 22 observations, and arm (a) shows the test would see a break (13 of 22 differ). No `xfail` was needed. Disposition: none; the inherited finding is **avoided**.
2. **Fixture artefact, not a defect:** a marker copied from a real `order.placed.v1` with only the order ids changed is dead-lettered by the Projector (the copied `orderReference` collides with the real order's document), so the first poison run showed THREE dead letters. The poison marker now carries its own `orderReference` (`ORD-900001`); noted so nobody reads it as a duplicate-DLQ defect.
3. Start-up noise: the fixture's `commit_group_at_end` right after the session broker's first group use logs `GroupCoordinatorNotAvailableError` / `NotCoordinatorForGroupError` retries; aiokafka retries internally and all runs were green. If it ever flakes, wait for the coordinator before committing (a `describe_consumer_groups` probe).
4. The fixture's `eventually` bound is 60 s; a broken behaviour therefore costs a minute per failing test (arm (b) took ~65 s).
5. `Fleet` methods are typed, but tests take `fleet: Any` because importlib mode makes `conftest.py` unimportable by name (the same convention as `stack: Any` in the Gateway suite).

Files: `/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/tests/saga_e2e/{conftest.py,test_saga_paths.py,test_redelivery_and_poison.py,test_one_trace_per_order.py}`, this report. Artefacts in `.arm/saga_e2e/` (git-ignored): backups, shas, `junit*.xml`, `run1.log`, `run2.log`.
