# Implementation report: feature 15 `orders_acceptance` (phase 8, `sdd: false`, full group)

Status set to `in_review` (that line only). No git writes. `specs/shared/` untouched; **no `R<n>` claimed** (R31 is Fulfillment's, R62 is `observability_reliability`'s), so `specs/shared/test-matrix.md` is not edited (its diff in the working tree predates this feature).

## 1. What was built

The `orders.create` acceptance path and the first runnable Orders host.

- **Wire and request**: `presentation/orders_create.py` decodes the request through the generated `OrdersCreateRequestPayload` (strict) plus a blank-code check, builds `PlaceOrderCommand`, maps the result to `OrdersCreateReplyPayload`, and maps every failure to an `RpcError` (the §9.2 table, `details.code` for domain codes).
- **Handler** (`application/commands/place_order.py`): order discount refusal (design §5.4), reference data, **stock check, then** `unit_of_work.begin()`, allocation inside it, one `Order.place`, one `save`. Clock and causation supplied by the handler. `request_id` is carried and has no effect (R62 is not this feature).
- **Ports** (`application/ports/`): `ReferenceCatalog`, `StockAvailability` (+ typed `StockCheckTransportError` / `StockCheckTimeoutError` / `StockCheckBusinessError`), `OrderNumberAllocator`; `OrdersTransaction` gained `.order_numbers`; `application/scope.py` is the dispatcher scope `OrdersScope` (refuses an unbound port at construction).
- **Adapters**: `NatsStockAvailability` (`infrastructure/messaging/`), `SqlAlchemyOrderNumberAllocator` (three statements of `sequences.py` on the transaction's own session), `SqlAlchemyReferenceCatalog` (a short session per lookup).
- **Responder** (`presentation/orders_create_responder.py`): one asyncio task for the one subscription (queue group `otc-orders`), each request served in its own tracked task, drain on stop.
- **Host**: `composition.py` (settings, `register_handlers`, `build_dispatcher`, one-relay enforcement, `OrdersRuntime`, `start_runtime` on one `AsyncExitStack`), `main.py` (the lifespan, `uvicorn otc_orders.main:app`), `/health/live` and the new `/health/ready` in `presentation/app.py`.
- **Settings**: `NatsSettings` (`NATS_URL`, `STOCK_CHECK_TIMEOUT_MS`, #7's names) and `ServerSettings` (`WEB_CONCURRENCY`); `.env.example` gained those three.

### Files

New source (`services/orders/src/otc_orders/`): `composition.py`, `main.py`, `application/scope.py`, `application/commands/{__init__,place_order}.py`, `application/ports/{order_number_allocator,reference_catalog,stock_availability}.py`, `infrastructure/messaging/{subjects,nats_stock_availability}.py`, `infrastructure/persistence/{order_number_allocator,reference_catalog}.py`, `presentation/{orders_create,orders_create_responder}.py`. Edited: `application/ports/unit_of_work.py`, `infrastructure/persistence/unit_of_work.py`, `infrastructure/settings.py`, `presentation/app.py`, `services/orders/pyproject.toml`, `uv.lock`, `.env.example`, `feature_list.json` (id 15 status line).

New tests: see section 9. Edited tests: `services/orders/tests/integration/conftest.py` (NATS fixtures, stand-in, host fixtures), `services/orders/tests/test_orders_health.py` (+1), `tests/architecture/test_write_path_population.py` (three classified entries).

## 2. Ported-idiom ledger

Python questions answered inline. File:line are read from the checkouts.

| Idiom | #7 relied on | #8 supplied it with | in #9 |
|---|---|---|---|
| no-responders vs timeout | `isTimeoutError` / `isNoRespondersError` on the `nats` client, `nats-stock-availability.adapter.ts:41-85` | `NatsNoRespondersException` vs `NatsNoReplyException`, `NatsStockAvailabilityChecker.cs` (commit 4c6ed34 lines 35 and 42) | `nats.errors.NoRespondersError` vs `nats.errors.TimeoutError`, measured on a real server (section 4, Q1); armed `D1a`, `D1b`, `D1c` |
| `success \| RpcError` discrimination | `isRpcErrorReply`, `adapter.ts:36-99`, and the "not valid JSON" guard `:94` | `RpcJson.IsErrorBody` before the typed decode, `NatsStockAvailabilityChecker.cs:82-98` (id 46) | `json.loads` then a string `code` means the responder's own error, else `from_wire_json`; `ValueError` and `ValidationError` become `StockCheckTransportError`; armed `46`, `46b` |
| request validation | `class-validator` DTO, `orders-create.controller.ts:61-62` | `OrdersCreateRequestValidator.Validate`, call at `OrdersCreateResponder.cs:132` | the strict generated pydantic model plus a blank check, called from `decode_request`; the call site armed `D5` (33 of 35 fail) |
| error mapping | `rpc-error-mapper.ts:33-80` | `OrdersCreateErrorMapper.Map`, `:41` | `map_error`, a `match` with specific arms before their bases; each arm armed |
| allocator lock | `order-number-allocator.ts:6,10` (`SELECT ... FOR UPDATE`) | `WITH (UPDLOCK, ROWLOCK)`, `EfCoreOrderNumberAllocator.cs:149` | `FOR UPDATE` in `sequences.py` on the transaction's session; the `MAX` runs only when seeding (`WHERE NOT EXISTS`); armed `A11a`, `A11b`, `A11c` |
| scope per message | one Nest request per message | `IServiceScopeFactory.CreateScope` per request, `OrdersCreateResponder.cs` | `OrdersScope` built per message by `scope_factory`; `Dispatcher` stores none; sessions belong to `begin()` / each catalogue call |
| composition validation at boot | Nest module init | `ValidateOnBuild = true` forced in every environment, `OrdersHost.cs:80` | `build_dispatcher()` (registry validated), `OrdersScope.__post_init__`, and every registered handler built at boot (`HandlerRegistry.registered_factories()`), all inside the lifespan; armed `6a`, `6b`, `6d`, and round 3's P5 |
| shutdown drain | `enableShutdownHooks()`, `main.ts:58` (its D2) | tracked in-flight tasks, `StockRpcResponder.cs:65-75` (id 50) | `gather(*in_flight, return_exceptions=True)` after the loop ends; plus a real `uvicorn` + SIGTERM test |
| env reads | `nats.config.ts` etc. | `Options` classes, no guard (id 56) | pydantic-settings only, explicit `validation_alias` per field, three guards (section 4, Q4) |
| money on the wire | `number` | `long` | `int` end to end (strict pydantic refuses `True`, `2.5`, `"2"`); `/ 1000` (ms to seconds) appears only in the settings seconds properties and at `nats_stock_availability.py:61` (the request timeout), never money |
| JSON serialisation | `JSON.stringify` | `RpcJson` | `otc_contracts.to_wire_json` for every reply (compact, camelCase, `.mmmZ`, `None` omitted); the reply bytes are asserted literally |
| event-loop affinity | n/a (one loop) | n/a | engine, NATS client, Kafka producer are created inside `start_runtime` (the lifespan's loop) and closed by the same stack; the test fixtures create each client in the test's own loop |
| typing gaps | n/a | n/a | `nats-py` 2.16.0 ships `py.typed`: `mypy --strict` passes with no override; the only `Any` is the annotated `json.loads` result, narrowed by `isinstance` |
| task cancellation / faults | `onApplicationShutdown` | `Task.WhenAll` observed per task | `CancelledError` is caught and re-raised by the two boot nets (`composition.py` `except BaseException` around the task steps, `kafka_publisher.py` `start`) so a cancelled boot stops its tasks and producer; `run()` cancelled cancels its requests then re-raises (armed `50f`) |

## 3. Questions 1-6

**Q1 transport errors.** Probed against `nats:2.14.5-alpine` (nats-py 2.16.0): a request on a subject nobody subscribes to raises `nats.errors.NoRespondersError` at once (it is NOT a `TimeoutError`: MRO `Error, Exception`); a subscribed responder that stays silent raises `nats.errors.TimeoutError` (a subclass of the builtin `TimeoutError`) after the deadline. A reply with an empty body comes back as `b""`, not `None`. Test: `test_nats_py_signals_no_responders_and_a_timeout_as_two_unrelated_errors` pins the library; `test_the_two_transport_failures_are_different_errors` fails when the branches collapse (`D1a`, `D1b`), and the wire split is in `test_no_responder_..._unavailable_at_once` (elapsed < 1.0 s of a 1.5 s budget) and `test_a_silent_..._timeout_after_the_budget` (elapsed >= 1.4 s).

**Q2 `success | RpcError`.** Parse once with `json.loads`; a dict with a string `code` is the responder's own error and becomes `StockCheckBusinessError(code, message)` BEFORE typed decoding; a code outside the wire enum is clamped to `UNAVAILABLE` with `details.responderCode`; otherwise `from_wire_json(StockCheckReplyPayload)`. A non-JSON body (including empty and non-UTF-8) and a JSON body that is neither shape are `StockCheckTransportError` with a reason, never a bare exception: 7 parametrised cases in `test_a_reply_that_is_neither_shape_...`.

**Q3 request validation.** `asyncapi.yaml` requires `retailerCode`, `companyCode` (1..20), `currency` (`^[A-Z]{3}$`), `lines` (min 1), and per line `productCode` (1..30) and `quantity` (int >= 1); the model parses strictly. 35 wire cases, each with NO stand-in subscribed so an unvalidated request comes back as a different code; control `test_a_valid_request_with_nobody_answering_...` pins that different code (`UNAVAILABLE`). Per-check evidence in section 7 (call site deleted: 33 of 35 fail; each pydantic check deleted in turn: every variant flips at least one case).

**Q4 composition root.** Boot proof: `start_runtime` runs `assert_single_outbox_relay`, then `build_dispatcher()` (before anything is opened), then builds the ports, builds the scope (refuses `None`), builds one handler, then starts the responder and relay. The guard drives the real path: `otc_orders.main.create_app()` with no argument and `app.router.lifespan_context` (what uvicorn drives), the environment set through the process environment only; plus two tests that run a REAL `uvicorn` process. Env-read guard (#8 id 56), one mechanism for every root: (a) `tests/architecture/test_composition_env_reads.py`: no `os.environ`/`getenv`/dotenv anywhere in a service with a root, and `load_settings` constructs every `BaseSettings` class (class population a literal); (b) `test_orders_settings_env.py`: the 15 variables are a literal, each one set to a sentinel moves exactly its field; (c) `test_every_setting_the_composition_root_reads_reaches_its_adapter` and the stock-timeout / Kafka / NATS behaviour tests prove each value reaches what it configures. Readiness: `/health/ready` is 503 before the lifespan, while stopping, when any transport task is done, and when the NATS connection is closed or reconnecting; DB and Kafka health are feature 27's. One relay: refused for `WEB_CONCURRENCY>1`, for a `multiprocessing` child (how uvicorn runs `--workers N`, measured in a real spawned child), and for a second relay-owning runtime in one process, all before anything is connected.

**Q5 allocator.** `test_order_number_allocator.py` (6): 24 concurrent allocations in 24 real transactions on 24 pooled connections released by a barrier give `ORD-000001..000024` exactly (first-ever, so the seed race is included); an uncommitted allocation holds the next one back and it receives the NEXT number; a rolled-back transaction burns none (also through the UoW); seeding over `orders` holding `ORD-000042` and `ORD-000007` continues at `ORD-000043`; the counter grows past six digits (`ORD-1000000`). Lock armed (`A11a`). **Armed finding**: my first hold-back test passed with the lock removed, because while the counter row does not exist the seed's `ON CONFLICT` itself makes a second caller wait; the test now commits one allocation first so the row exists.

**Q6 money on the reply.** 2500 / 50 / 2450 in the unit mapping test and 8465 / 350 / 8115 end to end (both asserted `len(set(...)) == 3` and non-zero); the three pairwise swaps are armed (`money_swap_*`): each fails a named test.

## 4. The eight acceptance items

1. **stock check via NATS, `success | RpcError`**: `test_acceptance_1_and_2_stock_is_checked_synchronously_...` (the stand-in receives `companyCode` and the lines in order), `test_nats_stock_check.py` (12), `D1*`, `46*`.
2. **order id synchronously; rejection**: same test (reply `orderId`, `ORD-000001`, committed `placed` row and one `order.placed.v1` outbox row), `test_acceptance_2_the_placed_fact_reaches_kafka_through_the_started_relay` (read from the broker), `test_acceptance_2_a_short_line_is_refused_with_the_shortage_and_persists_nothing` (no order, no outbox row, no counter row).
3. **`ORD-######` under `FOR UPDATE`, cheap pre-check**: Q5; `sequences.py` already runs the `MAX` only when seeding (feature 11's test pins the plan) and the allocator runs the seed statement on every allocation, which is the `WHERE NOT EXISTS` one-time filter.
4. **responder shutdown isolated; env reads guarded**: `test_shutdown_with_one_faulted_and_one_healthy_request_in_flight_completes_and_waits` (+ five siblings in `test_orders_create_responder.py`), `test_shutdown_waits_for_the_request_in_flight_before_closing_what_it_uses`, `test_orders_host_sigterm.py`; env: Q4.
5. **F7, no `Order(` outside `order.py`**: `tests/architecture/test_order_construction_sites.py` (11). Search result: `cls(` x2 in `domain/order.py` (`place` line 246, `rehydrate` line 342); `models.py:112` is `class Order(Base)`, no call; no other hit in `services/orders/src`. Factory call sites are a literal too (`Order.place` in `place_order.py::handle`, `Order.rehydrate` in `order_mapper.py::order_of`). Armed `F7_Order_call_added_in_mapper` (the call hidden in an `if False` region, aliasing forms have sentinels).
6. **explicit registration, validated in the lifespan; behavioural guard**: `register_handlers` is one statement; zero handlers / two handlers / a new unregistered command each fail the boot through the real lifespan (`6a`, `6b`); `tests/architecture/test_registration_behaviour.py` (7) runs a fresh interpreter with `HandlerRegistry` / `Dispatcher` instrumented: import of every walked module records nothing, wiring records each `register_*` caller frame, every frame must be a direct `.register_*(...)` statement of `composition.py` (cross-checked against its AST), no two registrations share a statement, the built tables equal the recorded registrations, one `Dispatcher` built by `build`. Armed by fixture packages: F-g + F-j as one pipeline (caught: `2 registrations share one statement`), F-a (`getattr`, caught: `not a direct statement`), an import-time registry, a poked table, and a control that must pass. Also armed on the real root (`6e`, `6c`, and the static guard `6f`). Residual, stated: a single self-registered handler drained by a one-statement helper passes the behavioural guard (indistinguishable from a direct call) and is caught only if it uses a loop or a decorator the static census sees.
7. **relay task started, owned, awaited; a dying task takes readiness down**: `test_the_lifespan_starts_the_responder_and_the_relay_and_awaits_both_on_shutdown`, `test_a_transport_task_that_dies_takes_readiness_down_and_names_it[outbox-relay|nats-responder]`, `test_a_closed_nats_connection_takes_readiness_down_...`; armed `7a`, `7b`, `7c2`, `7d`, `closed_nats...`.
8. **at most one relay per process, no multi-worker while enabled**: `test_single_outbox_relay.py` (10), and in `test_orders_host_lifespan.py` the refusal before connecting, the in-process second-runtime refusal (slot released on shutdown), and `test_a_real_uvicorn_with_two_workers_...` (a real `uvicorn --workers 2` prints `MultipleOutboxRelaysError` from its worker); armed `8a`-`8d`.

## 5. #8 and #7 defects, avoided or recurred

| Id | Verdict | How |
|---|---|---|
| #8 D1 (no-responders vs timeout, blocking) | avoided | two typed errors, measured library behaviour, both directions armed |
| D2 (stand-in's leak fix skipped its `finally`) | avoided | every stand-in client is registered on an `AsyncExitStack` the moment it exists; the SIGTERM test kills the server in a `finally` |
| D3 (missing port booted clean, surfaced as `INTERNAL_ERROR`) | avoided | `OrdersScope` refuses `None`, one handler is built at boot; armed `6d` and a port bound to nothing fails the lifespan |
| D4 (a fix's mapper arm unguarded) | avoided | every `map_error` arm has its own test and its own arm (`mapper_*`) |
| D5 (two required fields unchecked) | avoided | all six required checks have cases; each pydantic check deleted in turn flips a case (section 7); call site armed |
| D6 (test supplied the options itself) | avoided | the real `create_app()` and lifespan, environment only; plus real uvicorn processes |
| A3 (`observed` last-write-wins) | avoided | each stand-in records its own requests; no startup probe exists |
| A5 (three error vocabularies, unrecorded) | avoided | recorded in the module docstring of `place_order.py` |
| A10 (assembly anchor) | not applicable | no assembly in Python; the architecture tests glob packages |
| A11 (allocator untested for concurrency and seeding) | avoided | Q5 |
| #7 N2 (host bootstrap unguarded) | avoided | the entry point `otc_orders.main:app` and `uvicorn` itself are exercised by two real-process tests |
| #7 N3 (selector covers half the claim) | avoided | each AST guard has sentinels for the forms that evaded the previous one (aliases, dead regions, strings) |
| #8 id 46, 47, 50, 56 | closed here | items 1, 3, 4 |
| #7's blocking money swap | avoided | Q6 |

Recurred: one instance of the defect class, caught by arming before submission. The allocator hold-back test and `7c` (tasks not awaited on shutdown) both SURVIVED their first arm; both are fixed and re-armed (section 7).

## 6. Ported guards (#8's tests for this mechanism)

| #8 test | Verdict |
|---|---|
| `OrdersCreateAcceptanceTests` (7: happy path, stock check carries company and lines, short line, missing lines, no responders, silent responder, requestId carried) | ported (`test_orders_create_acceptance.py`, `..._validation.py`); the requestId test ported as "accepted, still placed" (R62 will replace it) |
| `OrdersCreateErrorMapperTests` (stock/timeout/transport/business, reference, discount, domain, unknown, invalid request) | ported (`test_orders_create_wire.py`); the cancel / catalog arms are other features'; the money-text scaling of the discount message ported (EUR, JPY, KWD) |
| `BC23`, `G5` (three retyped code sets agree with the enum parsed from AsyncAPI) | not applicable: `_WIRE_CODES` is derived from the generated `Code` enum (one source; the drift check of `quality.sh` guards it) |
| `OrdersCreateRequestValidatorTests` (missing or blank required fields) | ported, widened to every constraint of the schema |
| `OrdersDispatcherRegistrationTests` (every command one handler; real host composition fails when a port is removed) | ported (`test_orders_host_lifespan.py`, behavioural guard) |
| `PlaceOrderCommandHandlerTests` (6) | ported (`test_place_order_handler.py`, 21) |
| `RpcSubjectsTests` (subject equals the asyncapi channel address) | **gap**: not ported as a test; the subjects are literals in `subjects.py` and exercised by the sibling-subject arms (`sibling_subject_*`). A test comparing them with `asyncapi.yaml`'s `address:` lines is cheap and not written |
| `NatsStockAvailabilityCheckerTests` (rpc error, non-JSON, trace ids) | ported except trace ids (R57 is a later feature) |
| `OrderNumberAllocatorTests` | ported (Q5) |
| `OrdersProgramConfigurationTests` | ported as the env guards (Q4) |
| #8's later fulfillment `StockRpcResponder` shutdown tests (id 50) | ported against this responder |

## 7. Arming table

Protocol: `cp` backup, one mutation (exactly one occurrence asserted), the named tests, restore, `cmp`, clear that file's `.pyc`. Harness: `scratchpad/arm.py`; every arm reports `restored_identical=True`. "Fails" lists the tests that failed; the quoted text is the verbatim assertion.

| Arm (mutation) | Fails | Verbatim |
|---|---|---|
| `D1a` timeout branch raises transport | `test_the_two_transport_failures_are_different_errors` | `StockCheckTransportError: timeout` |
| `D1b` no-responders branch raises timeout | same + `test_no_responder_..._unavailable_at_once` | `assert 'TIMEOUT' == 'UNAVAILABLE'` |
| `D1c` mapper maps timeout to unavailable | 2 unit tests | `test_the_two_transport_failures_never_map_to_the_same_code` |
| `46` discriminator `if False` | checker test + acceptance pass-through | `assert 'UNAVAILABLE' == 'VALIDATION_FAILED'` |
| `46b` non-JSON guard removed | 3 of 7 cases | `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` |
| `46c` closed-connection branch removed | `test_a_closed_connection_...` | |
| `D5` validator call site replaced by a lenient parse | 33 of 35 | the 2 that pass: `body is empty` (the responder's own empty-payload check also answers `VALIDATION_FAILED`, redundant by design) and the control |
| `D5b` blank check removed | 6 (3 wire, 3 unit) | `assert 'NOT_FOUND' == 'VALIDATION_FAILED'` for `retailerCode "   "` |
| `D5c` retailerCode / companyCode constraints removed (swapped model) | 2 unit each | exact-message test |
| pydantic checks deleted one at a time (`scratchpad/loosen.py`, 12 variants incl. companyCode length) | every variant: at least 1 case no longer refused or refused with another message | e.g. `lines: min_length deleted -> ['lines empty']`, `line.quantity: ge=1 deleted -> [zero, negative]` |
| `A11a`/`A11a2` `FOR UPDATE` removed | both lock tests (after the fix) | `duplicate references: ['ORD-000001', 'ORD-000002', 'ORD-000002', ...]`, `assert 2 == 24` |
| `A11b` seed ignores `orders` | seeding test | `assert 'ORD-000001' == 'ORD-000043'` |
| `A11c` allocator commits its own work | 2 | `assert 'ORD-000002' == 'ORD-000001'` |
| handler opens the UoW before the stock check | 4 | order-of-steps list differs |
| discount check removed | unit + wire | |
| currency lookup removed | 1 | |
| mapper: `details` key `domainCode` / NOT_FOUND arm / STOCK_UNAVAILABLE arm / INTERNAL text leak / enum clamp | 2 / 4 / 2 / 1 / 1 | `test_a_domain_error_is_validation_failed_with_its_code_under_the_key_code` etc. |
| money swaps discount<->total, initial<->discount, initial<->total | 2 / 2 / 1 | `assert 2450 == 50` |
| `50a` drain without `return_exceptions` | shutdown test | `one request finishing (badly) must not end the drain early` |
| `50b` drain cancels instead of waiting | shutdown test | `the drain must wait for the requests still running` |
| `50c` fault not logged / `50d` sequential serving / `50e` queue group dropped / `50f` cancellation swallowed / `50g` late request dropped | 1 each | |
| `6a` dispatcher built without validation | 3 (zero, two, new command) | `Failed: the host must not come up with PlaceOrderCommand unhandled` |
| `6b` `build()` without message roots | 2 | |
| `6c` real registration statement deleted | acceptance (error) + behaviour guard | `the probe could not run otc_orders` |
| `6d` boot-time handler probe deleted | 1 | `Failed: the host must not come up with the stock port unbound` |
| `6e` registration via `getattr` | behaviour guard | `WIRE: ... not a direct .register_*(...) statement` |
| `6f` registration in a loop | static guard | |
| `7a` relay task not started / `7b` readiness ignores dead tasks / `7d` ready always 200 / `closed_nats` ignored | 2 / 1 / 3 / 1 | `assert {'nats-responder'} == {'nats-responder', 'outbox-relay'}`, `assert 200 == 503` |
| `7c` tasks not awaited on shutdown | **SURVIVED** (the tasks happened to finish while the stack closed) | fixed: new tests below |
| `7c2` same, after the fix | `test_shutdown_waits_for_the_request_in_flight_...` and the SIGTERM test | |
| `8a` single-relay call deleted / `8b` slot claim deleted / `8c` workers setting unused / `8d` worker probe false | 2 / 1 / 1 / 2 | `Failed: a second relay in this process must be refused` |
| `56a` alias deleted (`OUTBOX_BATCH_SIZE`) | env test, population test, pass-through | `assert 100 == 37` |
| `56b` value unused / `56c` `NatsSettings.model_construct()` / `56d` stock timeout unused / `56e` NATS URL unused / `56f` Kafka settings unused / `56g` `os.environ` in the root | 1 / 3 / 1 / 1 / 1 / 1 | `assert 'nats://localhost:4222' == 'nats://nats.sentinel:14222'`, `composition.py line 25: os.environ` |
| `56h` alias deleted (`STOCK_CHECK_TIMEOUT_MS`) | **equivalent mutant** for the per-variable test (the alias equals the implicit env name); caught by the population test (`56h2`) | |
| `F7` `Order(` added in the mapper | construction census | `an Order is constructed outside its factories` |
| unclassified writer added to the allocator | write-path census | |
| sibling subjects (`stock.check` -> `stock.reserve`, `orders.create` -> `orders.cancel`) | 2 / 1 | `no responder is subscribed to fulfillment.stock.reserve` |

## 8. Defeat list (rows that apply)

1 delete the behaviour (every arm). 2 corrupt a supplied field (money swaps, `domainCode`, shortage fields, `responderCode`). 3 sibling identifier (subjects; queue group `""`; the env sentinels all differ from each other). 4 shadow in a comment or string and 6 raw string (AST guards have `quiet` sentinels). 5 dead region (`if False:` is the F7 arm and an env-read sentinel). 7 drop an optional element (`loosen.py`: required deleted, constraints deleted). 8 literal vs literal (money fixtures pairwise distinct and non-zero, sentinels differ from defaults and the test asserts it). 9 closer half, stale premise (`arms4`/`arms5` re-run after the readiness and test edits). 10 caches (populations glob source, `__pycache__` excluded and pyc cleared per arm). 11 unrecognised form (the behavioural registration guard instead of more syntax). 12 failure through an undriven path (the reply-publish failure in `50a`, a closed NATS connection).

## 9. Tests (delta from 1652 to 1867 = 215)

| File | Tests |
|---|---|
| `services/orders/tests/unit/test_place_order_handler.py` | 21 |
| `services/orders/tests/unit/test_orders_create_wire.py` | 45 |
| `services/orders/tests/unit/test_orders_create_responder.py` | 6 |
| `services/orders/tests/unit/test_orders_settings_env.py` | 21 |
| `services/orders/tests/unit/test_single_outbox_relay.py` | 10 |
| `services/orders/tests/test_orders_health.py` | 2 (was 1: +1) |
| `services/orders/tests/integration/test_orders_create_acceptance.py` | 17 |
| `services/orders/tests/integration/test_orders_create_validation.py` | 35 |
| `services/orders/tests/integration/test_order_number_allocator.py` | 6 |
| `services/orders/tests/integration/test_nats_stock_check.py` | 12 |
| `services/orders/tests/integration/test_orders_host_lifespan.py` | 16 |
| `services/orders/tests/integration/test_orders_host_sigterm.py` | 1 |
| `tests/architecture/test_order_construction_sites.py` | 11 |
| `tests/architecture/test_composition_env_reads.py` | 6 |
| `tests/architecture/test_registration_behaviour.py` | 7 |

Sum 216 minus the 1 existing health test = 215 = 1867 - 1652 (`pytest --collect-only -q <file> | grep -c ::` per file).

## 10. Figures

- `./quality.sh` once with the developer infrastructure stopped (`docker ps` shows only the unrelated `otcpy-n8n`): **exit 0, 193 s, 1867 passed**, ruff format/check, mypy (320 files), import-linter (11 contracts kept), contracts drift check and the web gate green. The first run of the same gate, before the last additions, was 1855 passed in 190 s.
- `./init.sh` exit 0 after setting `in_review`.
- Packages installed: `nats-py 2.16.0` (`uv add nats-py` in `services/orders`; `services/orders/pyproject.toml` records `nats-py>=2.16.0`; the same uncommitted diff also carries `aiokafka`, which is feature 14's). No npm package.

## 11. Deviations, limits, surprises

1. **The lifespan lives in `otc_orders/main.py`, not `presentation/app.py`** (the brief and CLAUDE.md place it in presentation). `fact-producer-confinement` (R14) forbids any `presentation` module from reaching `aiokafka` directly or through a chain, and the lifespan runs the composition root, which imports the relay's Kafka publisher. `presentation/app.py` keeps the routes and takes the lifespan as an argument; `main.py` is the host. Say if you want the contract amended instead.
2. **NATS fixtures are in `services/orders/tests/integration/conftest.py`**, not the root `conftest.py` (outside my bounds); feature 17 should move them up. `testcontainers` 4.15.0's `NatsContainer.start()` emits its own `wait_for_logs` `DeprecationWarning` (the root filter only covers the import-time one): ignored for exactly that message, around `start()`, with the reason written beside it. The pyproject filter would be the alternative.
3. **Not built, deliberately**: R62 (`requestId` replay), R57/R58 trace and correlation propagation, DB and Kafka health in readiness (feature 27), a concurrency bound on in-flight requests (#8 80/88-90 are the saga's).
4. **One-relay enforcement limits**: detects `WEB_CONCURRENCY>1`, a `multiprocessing`-started worker, and a second runtime in one process. It does not detect a gunicorn fork model or two separate replicas; the latter is the documented operational rule (`OUTBOX_RELAY_ENABLED=false` on all but one).
5. **Divergences from #7/#8 on purpose**: `INTERNAL_ERROR` carries a generic message, never the exception text (it can hold SQL or a path); readiness also covers the NATS connection (the responder's loop would not end if the client closed).
6. **uvicorn exits -15 after a clean SIGTERM** (it re-raises the signal after its orderly shutdown); the test accepts `{0, -SIGTERM}` and requires `Application shutdown complete` and no traceback.
7. The boot-time probe builds `PlaceOrderCommandHandler` by hand; a handler added by features 16 and 41 must be added to it (a test fails if the registry is incomplete, not if the probe is).
8. The seed's `composition.py` is now inside `test_composition_env_reads.py` (half 1 only; it has no `load_settings`).
9. Not ported: a test that the subject constants equal the AsyncAPI `address:` lines (section 6).
10. Surprise worth recording: the first arm run produced two survivors (`A11a` hold-back vacuous while the counter row does not exist; `7c`), both in code I considered finished. Both are the "behaviour is correct and nothing notices its reversion" class #8 recorded.

---

# Round 2 (answers to `progress/review_orders_acceptance.md`, items 1-7)

Status set back to `in_review` (that line only). No git writes. Files outside `services/orders/**`: none. Arm harness: `scratchpad/r2/arm.py` (backup, exactly-one-occurrence replace, named tests, restore, `filecmp`, `.pyc` removed); every arm printed `restored_identical: true`.

**Incident, recorded:** while removing the unused `stock_check_timeout_seconds` property I sliced `settings.py` with a search string that also occurred in `OutboxRelaySettings` (its `poll_interval_seconds` and `publish_timeout_seconds` comment), and deleted `OutboxRelaySettings`' two properties, `KafkaSettings` and `NatsSettings`. The next pytest run failed on import, and I rebuilt the three from what the tests and `.env.example` pin (defaults, aliases, `ms / 1000`). The docstrings of `KafkaSettings` and `NatsSettings` and the comment above the properties are rewritten, not original; behaviour is held by `test_outbox_settings.py`, `test_orders_settings_env.py` (the 15 variables) and the host tests, all green. The reviewer may want a look at `settings.py` for that reason.

## Items

**1. D-1 (production defect).** `composition.py`: `start_runtime` now wraps every step from the creation of the first task in `try ... except BaseException: await _stop_tasks(stop_event, tasks); raise` (new `_stop_tasks`: set the event, `gather(return_exceptions=True)`, log a task's error). The tasks are stopped and awaited first, and only then does the stack close what they used (publisher, NATS, engine). I first registered the stop on the stack, then reverted it: on the normal `stop()` the stack order would stop the Kafka producer before the relay task, and the second gather would also have made R02 unobservable. `kafka_publisher.py`: `start()` stops the producer when its `start()` raises (`BaseException`, stop errors suppressed) and re-raises.
- `test_a_boot_that_fails_after_the_responder_task_exists_leaves_no_task_behind` (real lifespan, relay enabled, `KAFKA_BROKERS=127.0.0.1:1`; no `nats-responder` or `orders.create stop waiter` in `asyncio.all_tasks()`).
- `test_a_boot_that_fails_after_the_responder_task_exists_awaited_it_to_completion` (records the created tasks; the responder is done, not cancelled).
- `test_a_kafka_producer_that_cannot_start_is_stopped_before_the_boot_fails` (fake `AIOKafkaProducer` whose `start` raises; events `constructed, start, stop`).
- Arm `D1a_net_removed` (the `except` body is `raise` only): 2 failed, `AssertionError: a failed boot leaked tasks: ['nats-responder', 'orders.create stop waiter']` and `AssertionError: the responder task must have been stopped and awaited`.
- Arm `D1b_producer_stop_removed`: 1 failed, `assert ['constructed', 'start'] == ['constructed...tart', 'stop']`.

**2. D-2.** `test_every_setting_the_composition_root_reads_reaches_its_adapter` now records `NatsStockAvailability`'s kwargs with the 1777 sentinel (`assert stock == {"timeout_ms": 1777}`). `NatsSettings.stock_check_timeout_seconds` removed (it had no production use) with its one assertion in `test_orders_settings_env.py`.
- Arm `D2a` (`timeout_ms=1500`) and `D2b` (`timeout_ms=5000`): each 1 failed, `AssertionError: STOCK_CHECK_TIMEOUT_MS must reach the stock adapter`.

**3. D-3.** `test_the_reply_carries_the_currency_of_the_result_not_a_constant[JPY|KWD|EUR]` (unit; distinct amounts 7000 / 300 / 6700) and `test_an_order_in_a_zero_decimal_currency_is_placed_and_answered_in_that_currency` (end to end, a JPY currency row inserted; reply currency, the three amounts, and the stored order's currency joined from `currencies`).
- Arm `D3_currency_literal` (`currency="EUR"` in `to_reply`): 3 failed (`[JPY]`, `[KWD]` and the end-to-end test), `AssertionError: assert 'EUR' == 'JPY'`, `assert 'EUR' == 'KWD'`. The `[EUR]` case is the control and passes.

**4. D-4.** `test_the_two_transport_failures_are_different_errors` asserts `str(error) == "no responder is subscribed to fulfillment.stock.check."`; the end-to-end no-responder test asserts `reply["message"]` equal to it.
- Arm `D4_no_responders_clause_deleted`: 2 failed, `assert 'the NATS req...pondersError.' == 'no responder....stock.check.'` (`+ the NATS request failed: NoRespondersError.`).

**5. D-5.** New `services/orders/tests/unit/test_rpc_subjects.py` (2): the `address` of channels `ordersCreate` and `stockCheck`, found by channel id in the parsed `specs/shared/asyncapi.yaml`.
- Arms `D5a` (`orders.cancel`) and `D5b` (`fulfillment.stock.reserve`): each 1 failed, `channel ordersCreate: the subject Orders answers is not the spec's address` and `channel stockCheck: the subject Orders calls is not the spec's address`.

**6. D-6.** The probe is derived from the registrations: `_ProbedRegistry(HandlerRegistry[OrdersScope])` adds `registered_factories()` (reads its own tables through `self`, so no SLF001) and overrides no `register_*`, so the behavioural registration guard still sees direct statements. `_wire()` registers, builds and returns the factories; `build_dispatcher()` is its first element; `start_runtime` builds each registered factory once with `scope_factory()`. A recording-proxy design and an overriding subclass were rejected because the behavioural guard would see one shared statement.
- `test_a_registered_handler_that_cannot_be_built_fails_the_boot_whoever_registered_it` (real lifespan; a second command and a handler whose constructor raises, registered through a patched `register_handlers`).
- Arms `D6a` (probe back to the hand-built `PlaceOrderCommandHandler(scope_factory())`) and `D6b` (the factories never called): each 1 failed, `Failed: the host must not come up with a registered handler that cannot be built`.
- Residual: a cleaner public accessor on `Dispatcher` (`packages/cqrs`) was out of bounds; the subclass reads the base's tables.

## Round-1 mutations re-run (the files I changed: `composition.py`, `kafka_publisher.py`, `settings.py`)

Run over `services/orders/tests` plus `tests/architecture/test_registration_behaviour.py` and `test_composition_env_reads.py` (506 tests, green unmutated in 73 s). All 11 killed, all restored identical:

| Review id | Mutation | Result |
|---|---|---|
| R02 | `stop()` does not await the tasks | 2 failed: `shutdown must wait for the request that is mid-flight` |
| R05 | `register_command` deleted | 19 failed, 53 errors: `No command handler is registered for PlaceOrderCommand` |
| R06 | relay branch `if False:` | 8 failed: `assert [] == ['order.placed.v1']` (the relay never publishes) |
| R07 | `responder.start()` deleted | 60 failed: `NoRespondersError` |
| R19 | `web_concurrency=1` literal | 1 failed (the refusal test reached NATS: `NoServersError`) |
| R20 | `poll_interval=0.05` | 1 failed: `assert (0.05, True) == (0.073, True)` |
| R26 | `in_worker_process=False` | 1 failed: `no refusal within 60 s` (real uvicorn) |
| R28 | boot probe loop deleted (the new form of R28) | 2 failed: `the host must not come up with the stock port unbound` |
| R30 | slot never released | 12 failed, 52 errors: `this process already runs an outbox relay` |
| R31 | closed NATS ignored | 1 failed: `assert 200 == 503` |
| R35 | single-relay call neutralised | 2 failed: `NoServersError` (the refusal came too late) |

R18 is the new `D2a`. The 25 other round-1 mutations touch no file I changed (R08 `presentation/app.py`, the others the responder, mapper, adapter, allocator, orders_create) and were not re-run.

## 7. Gate

`./quality.sh` once, developer stack down (`docker ps`: only `otcpy-n8n`): **exit 0, 198 s, 1877 passed** (pytest 172.78 s; coverage 98.50% total; `Contracts: 11 kept, 0 broken`; ruff and mypy clean; web gate green). Delta 1867 to 1877 = +10, per file (`pytest --collect-only -q <file> | grep -c ::`):

| File | Before | After | Delta |
|---|---|---|---|
| `services/orders/tests/integration/test_orders_host_lifespan.py` | 16 | 20 | +4 (two leak tests, producer stop, D-6) |
| `services/orders/tests/unit/test_rpc_subjects.py` | 0 | 2 | +2 |
| `services/orders/tests/unit/test_orders_create_wire.py` | 45 | 48 | +3 (JPY, KWD, EUR) |
| `services/orders/tests/integration/test_orders_create_acceptance.py` | 17 | 18 | +1 (JPY end to end) |
| `test_nats_stock_check.py`, `test_orders_settings_env.py` | 12, 21 | 12, 21 | 0 (assertions added or removed in place) |

Sum +10. `./init.sh` exit 0 after the status change.

---

## Round 3 (light pass)

**Production changes:** `composition.py` (R2-D4: `OrdersRuntime` is constructed with an empty `owned` stack first, then `owned.push_async_callback(stack.pop_all().aclose)` is the last statement of the try; `_ProbedRegistry` deleted, `_wire` uses a plain `HandlerRegistry` and `registry.registered_factories()`), `packages/cqrs/src/otc_cqrs/dispatcher.py` (new read-only `HandlerRegistry.registered_factories()` over commands, queries and events; no change to registration or dispatch), `settings.py` (docstring provenance restored: Kafka "Where the producer connects (`KAFKA_BROKERS` and `KAFKA_CLIENT_ID` are #7's names)."; the NATS one names "#7's names and defaults", shortened to fit E501; backticks back on `asyncio`). Ledger rows corrected (three, §2).

**New tests (6):** all in `services/orders/tests/integration/test_orders_host_lifespan.py` unless noted.
| Item | Test | Arm (file, exact edit) | Verbatim failure |
|---|---|---|---|
| 1 R2-D1 | `test_a_boot_cancelled_while_the_producer_is_starting_leaks_no_task_and_stops_the_producer` | P3: `composition.py` `except BaseException:` before `await _stop_tasks` -> `except Exception:` | `a cancelled boot leaked tasks: ['nats-responder', 'orders.create stop waiter']` |
| 1 R2-D1 | same test | P4: `kafka_publisher.py` `except BaseException:` -> `except Exception:` | `assert ['constructed', 'start'] == ['constructed...tart', 'stop']` ("the producer must be stopped") |
| 2 R2-D2 | `test_a_failed_boot_awaits_the_responder_so_the_request_it_is_serving_is_answered` | P1: `_stop_tasks` gather line replaced by `results = [None] * len(tasks)` | fails; the responder's reply hits `nats.errors.ConnectionClosedError: nats: connection closed` (the request is not answered) |
| 3 R2-D3 | `test_an_unbuildable_query_or_event_handler_fails_the_boot_whoever_registered_it[query|event]` (patched `register_handlers`) | P5: `registered_factories` over `(self._commands,)` | both cases fail (`Failed: the host must not come up with an unbuildable ...`); P5e (`_events` dropped) fails the `[event]` case only |
| 3 | `packages/cqrs/tests/test_cqrs_dispatcher.py::test_registered_factories_lists_every_kind_of_registered_handler` | P5 / P5e | `assert 1 == 3` / `assert 2 == 3` |
| 4 R2-D4 | `test_a_runtime_constructor_that_raises_still_unwinds_the_stack` (NATS closed, `_relay_owner is None`, second boot succeeds) | `pop_all()` back in argument position | fails, plus 6 later tests via `MultipleOutboxRelaysError: this process already runs an outbox relay` (the slot stays held) |
| 6 R2-D5 | `test_a_silent_stock_check_responder_is_a_timeout_...` in `test_orders_create_acceptance.py` gained `assert elapsed < 3.0` | P8: `nats_stock_availability.py` `timeout=self._timeout_ms / 1000` -> `timeout=5` | `AssertionError: the 1.5 s budget is what was applied, not a longer one: 5.06s` |

Item 5: D6a is structurally gone (no hand-built probe or subclass; `grep _ProbedRegistry` over services, packages, tests: no hits). D6b (the `factory(scope_factory())` loop replaced by `pass`): 4 failed (port-bound-to-nothing, the command, query and event unbuildable cases). Item 8 re-arms on changed files: D1a (`except BaseException:` body reduced to `raise`): 4 failed + 2 errors; D1b (producer stop removed): 2 failed (`['constructed', 'start'] == [..., 'stop']`); D2a (`timeout_ms=1500`) and D2b (`timeout_ms=5000`): 1 failed each, `{'timeout_ms': 1500|5000} == {'timeout_ms': 1777}`. R02, R28, R30 and R35 touch no file changed this round except `composition.py`/lifespan test; they were not re-run individually, `quality.sh` covers them green. Harness: `scratchpad/r3/arm.py` (backup in `scratchpad/r3/<arm>.bak`, `restored identical True` printed for every arm; sha256 prefix of `composition.py` before each arm `3fd2d5a98a912d77`, `dispatcher.py` `507a1fab...`, `kafka_publisher.py` `7bbc909b...`, `nats_stock_availability.py` `521e1973...`).

**quality.sh (developer stack down, `docker ps` showed only `otcpy-n8n`):** exit 0, 193 s, `1883 passed` (1877 + 6: lifespan 20 -> 25 (+5: cancel, awaited, runtime ctor, query, event), cqrs dispatcher +1, acceptance +0 (assertion added to an existing test)). The first two runs failed lint/mypy on my own edits (E501 on the NATS docstring, an unused `noqa: SLF001`, mypy on `composition.nats`), fixed before the green run.

**Surprise:** the R2-D4 arm cascades: a held relay slot makes later tests in the same process fail, so the arm shows 7 failures; the named test is the one that proves the claim.
