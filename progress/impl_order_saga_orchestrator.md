# Implementation record — feature 16 `order_saga_orchestrator`

Status: implemented, `in_review`. One reboot interrupted the run at ~09:12 (/tmp wiped); that section is kept. Task 14.2 (live-stack walkthrough) was done afterwards, once the leader started the stack; every task in `tasks.md` is ticked.

## Interruption and restore (coordinator request)

- Unrestored mutation at the cut: arm **3.9a** (insert `await consumer.commit({partition: record.offset + 1})` between `record = records[0]` and `try:` in `infrastructure/messaging/kafka_fact_subscriber.py`). Found in the file (a second `consumer.commit(` at line 150), reversed by the exact inverse edit; asserted the mutated string occurred once and the original once afterwards. `consumer.commit(` now occurs once (the post-success commit).
- Method: **no sha256 survived** (records were in the wiped scratchpad). Verified by transcript content: the reversed text equals the text last written; `ruff format --check`, `ruff check`, `mypy` clean on `services/orders/src`; `test_kafka_fact_subscriber.py` 14 passed. No other source file carried a mutation: `presentation/saga_facts_consumer.py` mtime 07:51 and no `FACT_MODELS`/`raw_correlation` text (arm 3.8 had been restored by the tool before 3.9a started); every other file modified after 08:57 is a test file or `sweeper_task.py` (restored by cmp at 09:06).
- `__pycache__` under `services/orders` and `.mypy_cache` cleared. Arming backups and sha256 records now go to `.arm/` (git-ignored).
- The arm 3.9a result and its verbatim failure were lost; it is re-run below.

## 0.1 Assumptions A1-A7 as found (feature 15, committed shape)

- A1 true: `composition.py` `_wire()` builds the registry, `register_handlers` registers explicitly, `registry.build(...)` validates in `start_runtime` (feature 15 lines ~82-90 before my edits).
- A2' true: lifespan in `otc_orders/main.py`; tasks created in `composition.start_runtime`, stopped and awaited on any failure (`_stop_tasks`), readiness from `OrdersRuntime.unready_reasons`.
- A3 true: one nats client connected in `start_runtime`, closed by the stack after the tasks are awaited.
- A4 true: `NatsSettings` etc. with `validation_alias`, guard `tests/architecture/test_composition_env_reads.py`.
- A5: the `success | RpcError` decode was private to `NatsStockAvailability._decode` -> moved the shared first step into `infrastructure/messaging/rpc_reply.py` (behaviour unchanged, feature 15 tests green unedited).
- A6 false as found: `OrdersScope` had no dispatcher -> added `dispatcher`, `fact_consumption`, `saga_signal` as optional fields with `required_*` accessors (`application/scope.py`; not in tasks.md's file list, required by design A6).
- A7 true: `nats_server`, `nats_client`, `stand_in_stock_check` fixtures exist.

## 0.2 Baseline

`./quality.sh` with the developer stack down: exit 0, 187 s, 1883 passed (pytest 162.39 s), coverage 98.50%.

## What was built (files)

New under `services/orders/src/otc_orders/`: `application/saga/{command_kind,fact,step_table,command_payloads,fact_consumption,fact_handler,dispatch_events,order_sagas,fact_commands,fact_command_handlers}.py`; `application/ports/{fact_stream,saga_signal,saga_ignored_facts,saga_command_store,saga_commands}.py`; `infrastructure/messaging/{fact_topics,saga_subjects,rpc_reply,nats_saga_commands,kafka_fact_subscriber}.py`; `infrastructure/saga/{backoff,command_ledger,command_queue,ignored_facts,fact_consumption,command_dispatcher,fast_path,sweeper,sweeper_task}.py`; `presentation/saga_facts_consumer.py`.
Edited: `application/ports/{order_repository,unit_of_work}.py`, `application/scope.py`, `infrastructure/persistence/{order_repository,unit_of_work}.py` (UoW gains an optional `clock`, defaulting to `SystemClock`, so feature 15's four call sites are unchanged), `infrastructure/messaging/nats_stock_availability.py` (uses `rpc_reply`), `infrastructure/settings.py` (`SagaSettings`), `composition.py` (ten `register_command`, five `register_event`, three owned tasks, ordered reverse-start shutdown via `StopStage`), `.env.example` (eleven `SAGA_*`), root `conftest.py` (`KAFKA_FACT_TOPICS` three topics).
Tests: `services/orders/tests/unit/saga/**` (13 modules), `integration/saga/**` (harness conftest + 10 modules), `integration/test_order_row_lock.py`, `tests/architecture/test_kafka_client_confinement.py`.

### Edits to feature 15's tests that this feature FORCED (not in tasks.md's list; each is a stale premise, flagged)

- `tests/unit/test_orders_settings_env.py`: `SagaSettings` and the eleven `SAGA_*` variables join the literal population (design 9.3 says so).
- `tests/architecture/test_composition_env_reads.py`: `SagaSettings` joins `EXPECTED_SETTINGS`.
- `tests/architecture/test_registration_behaviour.py`: the commands/events table literals (PlaceOrder + ten fact commands, five events).
- `tests/architecture/test_write_path_population.py`: `EXPECTED["orders"]` entries (task 13.2, classified in comments).
- `tests/unit/test_place_order_handler.py`: its `FakeOrders`/`FakeTransaction` gained the new port members (mypy refuses the protocol otherwise).
- `tests/unit/test_idempotent_consumer_parity.py` case 3 (task 13.3).
- `tests/integration/conftest.py`: `host_environment` sets `SAGA_CONSUMER_ENABLED=false` by default (feature 15's host tests boot without a consumer).
- `tests/integration/test_orders_host_lifespan.py`: three assertions on the task set / the "no handler" problem list changed (new tasks exist; eleven commands now need handlers); two new cases (9.4).

## Findings / surprises

- `UniqueId(row.order_id)` raised on asyncpg's `UUID` subclass in the ledger (`type(...) is uuid.UUID`); fixed with `_plain` (same trap feature 14 recorded in `order_mapper`).
- aiokafka 0.14's admin has no `delete_consumer_groups`: the harness sends `DeleteGroupsRequest` to the coordinator (retrying `GroupCoordinatorNotAvailable` on a broker that never saw a group).
- The broker's `group.initial.rebalance.delay.ms` (3 s) makes every join of an empty group cost 3 s; the harness baselines the group with a manual-assign commit (no join). A root-conftest broker setting of `0` would save ~3 s per saga test (root conftest is out of bounds; recommendation).
- Arm 4.3b first SURVIVED: an outer `asyncio.timeout` reaches the adapter as `CancelledError`, so catching the builtin `TimeoutError` changed nothing; strengthened with a case where the call raises the builtin `TimeoutError` (then the arm fails).
- Arm 8.9c hung the run when the swallowed cancellation looped forever; the test now bounds the wait and sets `stop` in `finally`.
- Arm 4.4b first survived (pydantic refuses a non-object anyway): the test now asserts the "reply is not a JSON object" message.
- Arm 3.9b (auto-commit + explicit commit removed) cannot be seen after the fact because `seek` resets the position; the SO9 test now holds the handler open for 6.5 s (> aiokafka's 5 s auto-commit interval) and samples the broker's committed offset throughout. Re-arm pending.

## Arming (task 14.4: every `[ARM]` row re-run AFTER the last code change, into repo-local `.arm/`)

Tool `.arm/arm.py`: backup + sha256 of every file, apply the ONE mutation, run the ONE named test, record, restore from the backup, `cmp`, clear `__pycache__` and `.mypy_cache`, re-run green. 123 arm runs (122 by the tool, 13.3 by hand on the real file): every one failed under its mutation (none survived), every restore was `cmp`-identical with an equal sha256, every restored run green. The first failure line per arm is verbatim (the full logs are `.arm/logs/<id>.log`, git-ignored; the scripts are `.arm/arms_unit.py`, `arms4.py`, `arms5.py`, `arms6.py`):

| Arm | Mutated run | Result | First failure line | Restore |
|---|---|---|---|---|
| 2.2a | exit 1 | armed | `otc_orders.domain.errors.IllegalOrderTransitionError: An order cannot move from 'stock_reserved' to 'confirmed': that edge is not in Table T-1.` | cmp identical, sha256 equal, restored green |
| 2.2b | exit 1 | armed | `AssertionError: assert <SagaCommandKind.CREDIT_RELEASE: 'credit.release'> is None` | cmp identical, sha256 equal, restored green |
| 2.2c | exit 1 | armed | `AssertionError: credit.approved.v1 must apply at stock_reserved` | cmp identical, sha256 equal, restored green |
| 2.3a | exit 1 | armed | `AssertionError: assert {'order.cance...confirmed.v1'} == {'order.cance...ga_failed.v1'}` | cmp identical, sha256 equal, restored green |
| 2.3b | exit 1 | armed | `AssertionError: assert {'order.cance...ga_failed.v1'} == {'order.cance...ga_failed.v1'}` | cmp identical, sha256 equal, restored green |
| 2.4a | exit 1 | armed | `AssertionError: assert <CancellationReason.OPERATOR_CANCELLED: 'operator_cancelled'> is <CancellationReason.CREDIT_REJECTED: 'credit_rejected'>` | cmp identical, sha256 equal, restored green |
| 2.4b | exit 1 | armed | `AssertionError: assert UniqueId(valu...000000000d1')) == UniqueId(valu...000000000e1'))` | cmp identical, sha256 equal, restored green |
| 2.5 | exit 1 | armed | `AssertionError: channel ordersFacts: the topic the saga consumes is not the spec's address` | cmp identical, sha256 equal, restored green |
| 3.3 | exit 1 | armed | `AssertionError: an aiokafka consumer was built at construction` | cmp identical, sha256 equal, restored green |
| 3.4a | exit 1 | armed | `AssertionError: assert {'bootstrap_s...': False, ...} == {'bootstrap_s...': False, ...}` | cmp identical, sha256 equal, restored green |
| 3.4b | exit 1 | armed | `AssertionError: assert {'bootstrap_s...t': True, ...} == {'bootstrap_s...': False, ...}` | cmp identical, sha256 equal, restored green |
| 3.4c | exit 1 | armed | `AssertionError: assert {'bootstrap_s...': False, ...} == {'bootstrap_s...': False, ...}` | cmp identical, sha256 equal, restored green |
| 3.5a | exit 1 | armed | `AssertionError: order.placed.v1 was routed to HandleStockReservedFactCommand` | cmp identical, sha256 equal, restored green |
| 3.5b | exit 1 | armed | `AssertionError: assert [(HandleStock...00e0bad3800>)] == []` | cmp identical, sha256 equal, restored green |
| 3.6 | exit 1 | armed | `AssertionError: the second record must wait for the first handler to return` | cmp identical, sha256 equal, restored green |
| 3.7a | exit 1 | armed | `pydantic_core._pydantic_core.ValidationError: 1 validation error for Envelope[dict[str, Any]]` | cmp identical, sha256 equal, restored green |
| 3.7b | exit 1 | armed | `assert 40 == 30` | cmp identical, sha256 equal, restored green |
| 3.8 | exit 1 | armed | `AssertionError: timed out after 30s waiting for: two failed attempts of the poisoned record` | cmp identical, sha256 equal, restored green |
| 3.9a | exit 1 | armed | `AssertionError: the offset moved while the handler ran` | cmp identical, sha256 equal, restored green |
| 3.9b | exit 1 | armed | `AssertionError: the offset moved while the handler ran` | cmp identical, sha256 equal, restored green |
| 3.10 | exit 1 | armed | `AssertionError: only 1 attempts in 60 s` | cmp identical, sha256 equal, restored green |
| 3.11 | exit 1 | armed | `AssertionError: the group on the broker must be named exactly orders.saga: ['orders.saga', 'orders.saga-server'] (#7 D5)` | cmp identical, sha256 equal, restored green |
| 3.12 | exit 1 | armed | `AssertionError: timed out after 20s waiting for: the credit.hold row exists: the fact published first was consumed` | cmp identical, sha256 equal, restored green |
| 3.13i | exit 1 | armed | `AssertionError: timed out after 20s waiting for: the fact advances the order (the credit.hold row exists)` | cmp identical, sha256 equal, restored green |
| 3.13u | exit 1 | armed | `AssertionError: assert datetime.datetime(2026, 10, 2, 12, 15, 4, 120456, tzinfo=TzInfo(7200)) == datetime.datetime(2026, 10, 2, 10, 15, 4, 120000, tzinfo=datetime.timezone.utc)` | cmp identical, sha256 equal, restored green |
| 3.14 | exit 1 | armed | `AssertionError: timed out after 20s waiting for: the upper-case correlationId still routes to the order` | cmp identical, sha256 equal, restored green |
| 3.15a | exit 1 | armed | `AssertionError: seven consecutive failures double to the cap; a success resets the pace to 1 s` | cmp identical, sha256 equal, restored green |
| 3.15b | exit 1 | armed | `AssertionError: seven consecutive failures double to the cap; a success resets the pace to 1 s` | cmp identical, sha256 equal, restored green |
| 3.16 | exit 1 | armed | `aiokafka.errors.CommitFailedError: CommitFailedError: Commit cannot be completed since the group has already` | cmp identical, sha256 equal, restored green |
| 4.2 | exit 1 | armed | `AssertionError: channel stockReserve: the subject used for stock.reserve is not the spec's address` | cmp identical, sha256 equal, restored green |
| 4.3a | exit 1 | armed | `otc_orders.application.ports.saga_commands.SagaCommandTransportError: fulfillment.stock.reserve: no reply within 1234 ms.` | cmp identical, sha256 equal, restored green |
| 4.3b | exit 1 | armed | `otc_orders.application.ports.saga_commands.SagaCommandTimeoutError: fulfillment.stock.reserve: no reply within 1234 ms.` | cmp identical, sha256 equal, restored green |
| 4.4a | exit 1 | armed | `otc_orders.infrastructure.messaging.rpc_reply.ReplyNotJsonError: Expecting value: line 1 column 1 (char 0)` | cmp identical, sha256 equal, restored green |
| 4.4b | exit 1 | armed | `AssertionError: refused as a non-object, by name` | cmp identical, sha256 equal, restored green |
| 4.5 | exit 1 | armed | `AssertionError: one dict per call: concurrent tasks share the adapter` | cmp identical, sha256 equal, restored green |
| 4.6 | exit 1 | armed | `otc_orders.infrastructure.messaging.rpc_reply.ReplyNotJsonError: Expecting value: line 1 column 1 (char 0)` | cmp identical, sha256 equal, restored green |
| 4.7 | exit 1 | armed | `otc_orders.application.ports.saga_commands.SagaCommandTransportError: fulfillment.stock.reserve: rejected` | cmp identical, sha256 equal, restored green |
| 5.2a | exit 1 | armed | `AssertionError: assert (8465, 'EUR') == (8115, 'EUR')` | cmp identical, sha256 equal, restored green |
| 5.2b | exit 1 | armed | `AssertionError: assert [('SKU-A', 3)] == [('SKU-A', 3), ('SKU-B', 2)]` | cmp identical, sha256 equal, restored green |
| 5.2c | exit 1 | armed | `AssertionError: assert [('SKU-A', 19...-B', 1234, 2)] == [('SKU-A', 3,...-B', 2, 1234)]` | cmp identical, sha256 equal, restored green |
| 5.3 | exit 1 | armed | `Failed: DID NOT RAISE UnsupportedReleaseTriggerError` | cmp identical, sha256 equal, restored green |
| 5.4a | exit 1 | armed | `AssertionError: the request id is the saga_commands row id, unchanged across retries` | cmp identical, sha256 equal, restored green |
| 5.4b | exit 1 | armed | `AssertionError: the first attempt was unanswered, the second answered` | cmp identical, sha256 equal, restored green |
| 6.2 | exit 1 | armed | `AssertionError: signal must be a plain function: an awaited signal puts the RPC on the caller's path` | cmp identical, sha256 equal, restored green |
| 6.3 | exit 1 | armed | `Failed: order B's command was delayed behind order A's dispatch, which never finishes: started=[UniqueId(value=UUID('00000000-0000-4000-8000-0000000000a1'))], completed=[] (bound 100 ms)` | cmp identical, sha256 equal, restored green |
| 6.4a | exit 1 | armed | `AssertionError: the overflowing signal waited 0.0503s instead of returning` | cmp identical, sha256 equal, restored green |
| 6.4b | exit 1 | armed | `AssertionError: B is never dispatched by the fast path` | cmp identical, sha256 equal, restored green |
| 6.5 | exit 1 | armed | `AssertionError: assert {'00000000-00...00a1': 'none'} == {'00000000-00...efore signal'}` | cmp identical, sha256 equal, restored green |
| 6.6 | exit 1 | armed | `Failed: sibling B did not complete after A raised: A's failure cancelled it (started=[UniqueId(value=UUID('00000000-0000-4000-8000-0000000000b2')), UniqueId(value=UUID('00000000-0000-4000-80` | cmp identical, sha256 equal, restored green |
| 6.7 | exit 1 | armed | `AssertionError: the child ended CANCELLED: the cancellation was propagated, not swallowed` | cmp identical, sha256 equal, restored green |
| 6.8 | exit 1 | armed | `AssertionError: assert [(OrderPlaced...signal=None))] == []` | cmp identical, sha256 equal, restored green |
| 6.9a | exit 1 | armed | `AssertionError: assert [SagaCommandR...redit.hold'>)] == [SagaCommandR...ck.reserve'>)]` | cmp identical, sha256 equal, restored green |
| 6.9b | exit 1 | armed | `AssertionError: assert [] == [SagaCommandR...oice.issue'>)]` | cmp identical, sha256 equal, restored green |
| 6.10 | exit 1 | armed | `RuntimeError: no group` | cmp identical, sha256 equal, restored green |
| 7.1 | exit 1 | armed | `asyncio.exceptions.CancelledError` | cmp identical, sha256 equal, restored green |
| 7.2 | exit 1 | armed | `asyncpg.exceptions.LockNotAvailableError: could not obtain lock on row in relation "retailers"` | cmp identical, sha256 equal, restored green |
| 7.4 | exit 1 | armed | `asyncpg.exceptions.UniqueViolationError: duplicate key value violates unique constraint "uq_saga_commands_order_id_command"` | cmp identical, sha256 equal, restored green |
| 7.5 | exit 1 | armed | `AssertionError: the responder received, byte for byte, the text that was committed` | cmp identical, sha256 equal, restored green |
| 7.6 | exit 1 | armed | `AssertionError: no saga_commands row` | cmp identical, sha256 equal, restored green |
| 7.7 | exit 1 | armed | `AssertionError: the signal comes after the commit returned` | cmp identical, sha256 equal, restored green |
| 7.8a | exit 1 | armed | `otc_orders.domain.errors.IllegalOrderTransitionError: An order cannot move from 'stock_reserved' to 'stock_reserved': that edge is not in Table T-1.` | cmp identical, sha256 equal, restored green |
| 7.8b | exit 1 | armed | `AssertionError: a saga step must load the order FOR UPDATE, never with a plain read` | cmp identical, sha256 equal, restored green |
| 7.8c | exit 1 | armed | `AssertionError: assert None is <OrderStatus.PLACED: 'placed'>` | cmp identical, sha256 equal, restored green |
| 8.1a | exit 1 | armed | `TypeError: unsupported operand type(s) for <<: 'int' and 'float'` | cmp identical, sha256 equal, restored green |
| 8.1b | exit 1 | armed | `assert 715827882 == 31` | cmp identical, sha256 equal, restored green |
| 8.2 | exit 1 | armed | `AssertionError: a leased row cannot be claimed again by the fast path` | cmp identical, sha256 equal, restored green |
| 8.3 | exit 1 | armed | `Failed: claimer B is blocked behind claimer A's row locks (a lock wait, not a skip)` | cmp identical, sha256 equal, restored green |
| 8.4 | exit 1 | armed | `assert datetime.datetime(2026, 10, 7, 9, 23, 19, 121000, tzinfo=datetime.timezone.utc) == (datetime.datetime(2026, 10, 7, 12, 0, 3, 7000, tzinfo=datetime.timezone.utc) + datetime.timedelta(s` | cmp identical, sha256 equal, restored green |
| 8.5a | exit 1 | armed | `AssertionError: the total the caller accumulated, not the cycle count` | cmp identical, sha256 equal, restored green |
| 8.5b | exit 1 | armed | `AssertionError: a sent row is never moved back to parked` | cmp identical, sha256 equal, restored green |
| 8.5c | exit 1 | armed | `OverflowError: value out of int32 range` | cmp identical, sha256 equal, restored green |
| 8.6a | exit 1 | armed | `AssertionError: assert <DispatchOutcome.PARKED: 'parked'> is <DispatchOutcome.SENT: 'sent'>` | cmp identical, sha256 equal, restored green |
| 8.6b | exit 1 | armed | `AssertionError: 3 earlier attempts + 3 this cycle, not 3` | cmp identical, sha256 equal, restored green |
| 8.6c | exit 1 | armed | `AssertionError: assert [('reserve_st...0000000d1')))] == []` | cmp identical, sha256 equal, restored green |
| 8.6d | exit 1 | armed | `AssertionError: the sweeper already holds the lease: claiming again excludes it` | cmp identical, sha256 equal, restored green |
| 8.7 | exit 1 | armed | `AssertionError: row B finished while row A is still blocked` | cmp identical, sha256 equal, restored green |
| 8.8 | exit 1 | armed | `AssertionError: timed out after 20s waiting for: the sweeper's own claim is issued and the row reaches sent` | cmp identical, sha256 equal, restored green |
| 8.9a | exit 1 | armed | `AssertionError: a second cycle started while the first was still running` | cmp identical, sha256 equal, restored green |
| 8.9b | exit 1 | armed | `Failed: the loop ran no second cycle after the first failed (task done: True)` | cmp identical, sha256 equal, restored green |
| 8.9c | exit 1 | armed | `AssertionError: cancellation was swallowed: the sweeper task is still running` | cmp identical, sha256 equal, restored green |
| 8.10 | exit 1 | armed | `AssertionError: timed out after 20s waiting for: the sweeper alone issues the due pending row` | cmp identical, sha256 equal, restored green |
| 8.11 | exit 1 | armed | `Failed: row A's failure escaped the sweep and cancelled row B (completed=[]): ExceptionGroup` | cmp identical, sha256 equal, restored green |
| 9.2a | exit 1 | armed | `Failed: DID NOT RAISE ValidationError` | cmp identical, sha256 equal, restored green |
| 9.2b | exit 1 | armed | `Failed: DID NOT RAISE ValidationError` | cmp identical, sha256 equal, restored green |
| 9.2c | exit 1 | armed | `Failed: DID NOT RAISE ValidationError` | cmp identical, sha256 equal, restored green |
| 9.2d | exit 1 | armed | `Failed: DID NOT RAISE ValidationError` | cmp identical, sha256 equal, restored green |
| 9.4a | exit 1 | armed | `AssertionError: assert ('No command ...is required.') == ('No command ...s required.',)` | cmp identical, sha256 equal, restored green |
| 9.4b | exit 1 | armed | `AssertionError: assert 2 == 1` | cmp identical, sha256 equal, restored green |
| 10.1 | exit 1 | armed | `AssertionError: assert {'test_saga_l...onsumerTask'}} == {}` | cmp identical, sha256 equal, restored green |
| 10.2a | exit 1 | armed | `AssertionError: assert 'credit_approved' == 'confirmed'` | cmp identical, sha256 equal, restored green |
| 10.2b | exit 1 | armed | `AssertionError: assert {'amount': 84...rency': 'EUR'} == {'amount': 81...rency': 'EUR'}` | cmp identical, sha256 equal, restored green |
| 10.2c | exit 1 | armed | `AssertionError: assert [{'productCod..., 'units': 3}] == [{'productCod..., 'units': 2}]` | cmp identical, sha256 equal, restored green |
| 10.3a | exit 1 | armed | `AssertionError: assert ('stock_reserved', None) == ('stock_reserved', 'placed')` | cmp identical, sha256 equal, restored green |
| 10.3b | exit 1 | armed | `AssertionError: timed out after 20s waiting for: one precondition_unmet row for invoice.issued.v1` | cmp identical, sha256 equal, restored green |
| 10.3c | exit 1 | armed | `AssertionError: timed out after 20s waiting for: the second credit.rejected.v1 is processed` | cmp identical, sha256 equal, restored green |
| 10.4a | exit 1 | armed | `AssertionError: timed out after 20s waiting for: exactly one unknown_order row for the fact` | cmp identical, sha256 equal, restored green |
| 10.4b | exit 1 | armed | `AssertionError: these modules name a reference parser on the saga path: {'application/saga/fact_handler.py': {'OrderNumber'}}` | cmp identical, sha256 equal, restored green |
| 11.1 | exit 1 | armed | `AssertionError: assert 'credit_approved' == 'confirmed'` | cmp identical, sha256 equal, restored green |
| 11.2 | exit 1 | armed | `AssertionError: timed out after 20s waiting for: an order.completed.v1 outbox row exists` | cmp identical, sha256 equal, restored green |
| 11.3 | exit 1 | armed | `AssertionError: timed out after 20s waiting for: an order.cancelled.v1 outbox row exists` | cmp identical, sha256 equal, restored green |
| 11.4 | exit 1 | armed | `ValueError: not enough values to unpack (expected 1, got 0)` | cmp identical, sha256 equal, restored green |
| 11.5i | exit 1 | armed | `AssertionError: timed out after 20s waiting for: an order.cancelled.v1 outbox row exists` | cmp identical, sha256 equal, restored green |
| 11.5u | exit 1 | armed | `ValueError: no cancellation reason is mapped for release reason order_cancelled` | cmp identical, sha256 equal, restored green |
| 11.6i | exit 1 | armed | `AssertionError: zero release requests` | cmp identical, sha256 equal, restored green |
| 11.6u | exit 1 | armed | `AssertionError: stock.rejected.v1 at placed` | cmp identical, sha256 equal, restored green |
| 11.7 | exit 1 | armed | `AssertionError: R23: no further command is owed` | cmp identical, sha256 equal, restored green |
| 11.8a | exit 1 | armed | `AssertionError: R19 leaves the status unchanged` | cmp identical, sha256 equal, restored green |
| 11.8b | exit 1 | armed | `AssertionError: R27: the status stays stock_reserved while the release is being issued` | cmp identical, sha256 equal, restored green |
| 11.9a | exit 1 | armed | `AssertionError: R12: the cancel is caused by the release fact` | cmp identical, sha256 equal, restored green |
| 11.9b | exit 1 | armed | `AssertionError: assert <CancellationReason.CREDIT_REJECTED: 'credit_rejected'> is <CancellationReason.STOCK_REJECTED: 'stock_rejected'>` | cmp identical, sha256 equal, restored green |
| 11.9c | exit 1 | armed | `AssertionError: assert {'orderRefere...er_cancelled'} == {'orderRefere...dit_rejected'}` | cmp identical, sha256 equal, restored green |
| 12.2a | exit 1 | armed | `AssertionError: timed out after 20s waiting for: the stock.release is issued` | cmp identical, sha256 equal, restored green |
| 12.2b | exit 1 | armed | `AssertionError: timed out after 20s waiting for: the rejected credit.hold row is marked sent` | cmp identical, sha256 equal, restored green |
| 12.3a1 | exit 1 | armed | `AssertionError: timed out after 20s waiting for: a sweeper cycle issues the row and the saga moves on to credit.hold` | cmp identical, sha256 equal, restored green |
| 12.3a2 | exit 1 | armed | `AssertionError: timed out after 20s waiting for: the next sweep sends the parked row and the saga advances to credit.hold` | cmp identical, sha256 equal, restored green |
| 12.3b | exit 1 | armed | `AssertionError: R29: the order status is unchanged` | cmp identical, sha256 equal, restored green |
| 12.4a | exit 1 | armed | `KeyError: 'saga-sweeper'` | cmp identical, sha256 equal, restored green |
| 12.4b | exit 1 | armed | `AssertionError: NATS was closeed while tasks ['nats-responder', 'outbox-relay', 'saga-fast-path', 'saga-sweeper', 'saga-consumer'] were still running: close came first` | cmp identical, sha256 equal, restored green |
| 13.1a | exit 1 | armed | `assert ["the subscri...kaProducer']"] == []` | cmp identical, sha256 equal, restored green |
| 13.1b | exit 1 | armed | `assert ["the modules..._publisher']"] == []` | cmp identical, sha256 equal, restored green |
| 13.2 | exit 1 | armed | `AssertionError: services/orders/src has an unclassified write path (or lost a classified one, or gained a second occurrence of one): add it to EXPECTED with its classification. Found: {'doma` | cmp identical, sha256 equal, restored green |
| 13.3 | manual real-file rename of `idempotent_consumer.py` | armed | `AssertionError: a consuming write model has no idempotent-consumer copy: ['otc_orders']` | cmp identical, sha256 equal, 19 passed |
| 13.4 | exit 1 | armed | `AssertionError: timed out after 1.5s waiting for: order B's stock.reserve is sent within 1.5s although order A's credit.hold is still being issued (a bound shorter than one TimeoutMs)` | cmp identical, sha256 equal, restored green |

Arm ids map to `tasks.md` rows by number; a letter or `u`/`i` suffix is one of the separate arms the row names (for example 3.4a-c, 3.9a/b, 3.13u/i, 4.3a/b, 5.2a-c, 6.4a/b, 8.5a-c, 8.6a-d, 8.9a-c, 9.2a-d, 11.5u/i, 11.6u/i, 12.3a1/a2/b, 12.4a/b, 13.1a/b).

Notes on specific rows (what the arm does and does not prove):
- 2.2a dies in the aggregate (`IllegalOrderTransitionError`): the aggregate itself refuses to skip the intermediate edge, so the "both edges" claim cannot be mutated more finely; the failure names the edge.
- 3.9a/3.9b: the first run HUNG (420 s timeout; my test left the held handler blocking shutdown). Fixed (`finally: hold.set()`); now 3.9a fails at `the offset moved while the handler ran` (commit before the handler) and 3.9b fails the same assertion at the 5 s auto-commit tick (explicit commit removed): both need the 6.5 s in-flight sampling window.
- 6.3 and 13.4 are the sequential-drain arms (the reproduction asked for before the fix; recorded after, see deviations). 13.4's failure names order B and the bound.
- 6.8's second arm ("publish before `handle` returns") cannot be expressed against the stubbed step; it is armed as 7.7 (publish inside `work`).
- 8.9c: `stop` is set in a `finally` so a swallowed cancellation fails instead of hanging.
- 11.5 is armed twice, unit and integration (`test_the_order_cancelled_release_reason_cancels_with_operator_cancelled_and_one_step`): double force, no producer until feature 41. 11.6 is armed twice (unit cell `[stock.rejected.v1-placed]` and integration R26), as #7 D3 requires.
- 12.4b: the first version (dispatch blocked at shutdown) SURVIVED the mutation (closing NATS first made no observable difference there); replaced by `test_the_nats_client_is_closed_only_after_every_task_was_awaited`, which spies on `Client.close/drain` and fails with `NATS was closeed while tasks [...] were still running`.

## Figures (task 14.1; developer stack down)

- `./quality.sh`: exit 0, 7 min 08 s real, **2350 passed** (pytest 393.68 s) against the baseline's 1883 (exit 0, 187 s): **delta +467**; overall coverage 98.70% (baseline 98.50%); domain gate and web gates passed. Command: `./quality.sh > .arm/quality1.log`.
- New tests by file (`pytest --collect-only`): unit/saga: step_table 136, nats_saga_commands 68, saga_facts_consumer 24, saga_settings 23, fact_command_handlers 18, command_dispatcher 16, kafka_fact_subscriber 14, fact_handler 13, command_payloads 11, sweeper 10, fast_path 9, backoff 8, order_sagas 7, no_reference_parse 4, topics_and_subjects 3, harness_census 2 (366); integration/saga: preconditions 14, ledger 10, consumption 10, happy_path 8, lifespan 8, reply_decode 6, command_retry 5, compensation_credit_rejected 5, transactional_unit 3, headers 1, fast_path_concurrency 1, compensation_stock_rejected 1 (72); `integration/test_order_row_lock.py` 5; `tests/architecture/test_kafka_client_confinement.py` 10. 366 + 72 + 5 + 10 = 453; the other 14 are cases added to feature 15's modules (11 `SAGA_*` env cases, 2 host-lifespan cases for 9.4, 1 parity sentinel).
- Write-path census (read from `scan_service("orders")`): command_queue.py (aliased insert import, execute, insert), command_ledger.py (update x4, execute x1), ignored_facts.py (add), fast_path.py (add, a Python set); classified in `EXPECTED["orders"]`.
- SO13 integration case: order B sent 0.06 s after publish while A's `credit.hold` was still unsent (bound 1.5 s, TimeoutMs 3 s).
- Cost: about 4 to 5 s per saga integration test, dominated by the broker's 3 s `group.initial.rebalance.delay.ms` on the saga consumer's join.

## 14.3 Deadlock watch

`grep -c -E '40P01|deadlock detected' .arm/integration_logs.out` after `pytest services/orders/tests/integration -o log_cli=true -o log_cli_level=DEBUG` (258 passed, 290.81 s) printed `0`; the same grep over `.arm/quality1.log` printed `0`. Classification: no hit, nothing to classify; outbox design G2's re-open trigger did not fire.

## 14.2 Live-stack walkthrough and how to test it manually (done, 2026-10-07 ~11:45)

Stack: the leader's `otcpy` infra (postgres, kafka, nats healthy). No migration or seed was needed: `otc_orders` was already at `alembic_version` 0001 with reference data (7 retailers, 22 companies, 12 products, 3 currencies) and 6 old orders (5 completed, 1 cancelled) from earlier live work; `saga_commands`, `processed_events`, `saga_ignored_facts` were empty. **Clean-slate choice:** none made by me. The three fact topics existed with 6 partitions each, but every partition's LOG-END-OFFSET was 0 (the broker volume was recreated; the 17 old outbox rows were stamped published against an earlier broker), so there was no history to replay and `orders.saga` had no committed offsets: the first boot started from the empty topics, which is design 15's "topics may also be empty after a recreate" case. The six old orders were not touched.

Commands, exactly (cwd = repo root; the host reads `.env`):
1. `docker exec otcpy-postgres psql -U postgres -d otc_orders -tAc "select count(*) from saga_commands"` (before: 0; same for `processed_events`, `saga_ignored_facts`).
2. `uv run uvicorn otc_orders.main:app --port 8101 > .arm/live/host.log 2>&1 &` ; `curl -s localhost:8101/health/ready` printed `{"status":"ready"}` (the log shows aiokafka retrying `GroupCoordinatorNotAvailable` for a few seconds while `__consumer_offsets` was created, then the group joined).
3. With no responder on any saga subject and no `fulfillment.stock.check` responder either, `orders.create` answers UNAVAILABLE, so a throwaway stand-in (`.arm/live/place_order.py`, not product code) subscribes `fulfillment.stock.check` and then calls `orders.create` once: `uv run python .arm/live/place_order.py` printed `{"orderId":"223c1406-...","orderReference":"ORD-000007","status":"placed","totalAmount":55545,...}`. It exits and closes its connections.
4. Observation after ~20 s: `select command,status,attempts,left(last_error,90) from saga_commands` gave one row: `stock.reserve | parked | 3 | fulfillment.stock.reserve: no responder is subscribed to fulfillment.stock.reserve.`; `processed_events`: `orders.saga | 1`; `saga_ignored_facts`: 0 rows; the order stayed `placed` (R19, R29: status unchanged).
5. After ~2 more minutes the sweeper re-attempted: the same row `parked | attempts 6`, `next_attempt_at` = `updated_at` + 120 s (park back-off 30 s x 2^2), the host log showing `saga command parked` twice; consumer group describe showed CURRENT-OFFSET = LOG-END-OFFSET = 1 on the order's partition (offset committed); `/health/ready` still ready; no ERROR line in the host log.
6. Stop: `kill -TERM <uvicorn pid>`; PID check: `ps -p 535675,535703` shows neither process, `ps -eo pid,args | grep -c "[u]vicorn otc_orders.main"` printed 0, nothing listens on 8101, and the log ends with `Application shutdown complete`. The stack was not touched. Residue left in the dev database: order ORD-000007 and its parked `stock.reserve` row (it will resume unattended when feature 17's responder appears, which is the designed recovery story).

Result: identical to design 15's expectation (one `processed_events` row, no status change, one `stock.reserve` row, three no-responders attempts, parked, then re-attempted on capped back-off). No defect found.

## Orphaned pytest processes (leader's note)

PIDs 28718 and 43785 (started about 09:55 and 10:03) were the mutated runs of arms **3.9a and 3.9b** (the SO9 test `test_so9_a_handler_that_throws_leaves_the_committed_offset_unchanged_and_a_restarted_consumer_redelivers_the_fact`) from the first `.arm/arms4.py` batch (the 420 s tool timeout in `.arm/arm.py`). They hung instead of failing for two stacked reasons: (1) my test held the handler open on an `asyncio.Event` for the in-flight sampling window and, when the mutation made the first assertion fail, the `async with saga_harness(...)` exit waited for the consumer to finish that in-flight record, which could never return (nobody set the event): a test-structure defect, later fixed with `finally: hold.set()`; (2) `arm.py` used `subprocess.run(["uv","run","pytest",...], timeout=420)`, which kills only the `uv` parent, so the pytest child survived, was reparented to systemd and kept hanging. Both logs show `mutated run: exit=124 (420s) TIMEOUT`. The same child-survives gap affects any arm that hits the timeout; the later runs did not hit it. I did not know the children were still alive (the log said TIMEOUT and the restore had run); the cleanup was the leader's.

## Ported-idiom ledger L1-L31 as realised (guard = arm id)

L1 offset after handler: 3.9a/3.9b/3.10; L2 failed record not skipped: 3.10 (unit and integration); L3 one record at a time: 3.6; L4 group identity: 3.4c, 3.11; L5 earliest: 3.4a, 3.12; L6 per-command task: 6.2, 6.3, 13.4; L7 context: 6.5; L8 containment: 6.6, 8.11; L9 cancellation not swallowed: 6.7, 8.9c; L10 idempotent enqueue: 7.4, 10.3c; L11 lease: 8.2, 8.3; L12 `dispatch_claimed`: 8.8, 8.7; L13 clock port: 8.4; L14 park arithmetic: 8.1a/b; L15 in-line back-off: 8.6 and `test_backoff`; L16 no-responders versus timeout: 4.3a/b; L17 malformed reply: 4.4a/b, 4.6; L18 `RpcError` first: the rpc-error and unknown-code cases in `test_nats_saga_commands.py` with 4.4a; L19 fresh header dict: 4.5; L20 one request id per row: 5.4a/b; L21 stored bytes sent: 7.5; L22 UTC milliseconds: 3.13u/i; L23 what is acknowledged: 3.7a/b, 3.8; L24 `FOR UPDATE OF orders`: 7.1, 7.2; L25 reference never parsed: 10.4a/b; L26 four skips: 2.3a/b, 3.5b; L27 `Any` from clients: typed through private Protocols, guard `mypy --strict` (385 files clean) and 13.1a/b; L28 loop affinity: 3.3; L29 heartbeats: no sync driver in the service, the consume path is database time only (no executable guard beyond import-linter and mypy); L30 sweeper loop never overlaps: 8.9a; L31 UUID comparison by value: the unit `test_the_correlation_id_is_compared_as_a_uuid_value` and integration 3.14.

SQL of 7.1: `SELECT orders.*, retailers.*, companies.*, currencies.* FROM orders JOIN retailers ... JOIN companies ... JOIN currencies ... WHERE orders.id = $1 FOR UPDATE OF orders` (the `of=OrderRow` form; arm 7.2 swaps in a bare `FOR UPDATE` and the retailer `NOWAIT` fails naming the table). I did not capture the emitted text from the engine; this is the form the SQLAlchemy construct produces, and arm 7.2's failure is the behavioural proof.

## Inherited findings (design section 18): avoided or recurred

#8 id 80, 88: avoided (per-command tasks; 6.3 and 13.4 reproduce the sequential drain). #8 id 89: avoided (SO13 integration through the real lifespan). #8 id 90: avoided (`fast_path_max_in_flight < 1` refused by name, 9.2b). #8 id 110: avoided (SO15 unit and six-subject integration). #8 id 48: avoided (4.5). #8 id 51: avoided by construction (generated models). #8 id 94: avoided (broker-read offsets, restarted consumer, 3.9a/b); carried to feature 27 as "re-run SO9's arms after the retry wrapper" (leader to attach). #8 id 62: split (saga-side lock built and armed, 7.1/7.2). #8 id 71, 91: assigned to 41/24/27. #8 D1 (offset inferred): avoided. #8 D2/production double claim: avoided (8.8). #8 D3: avoided (planted orders carry no outbox rows; state gates). #8 D4: avoided (`wait_then_assert` evaluates one predicate). #8 D5: control legs kept (every restored run green). **#8 id 56: RECURRED in round 1 (D1: the eleven `SAGA_*` settings were not proven to reach their adapters); closed in round 2.** #7 D1: avoided (10.3c). #7 D2: avoided (8.4). #7 D3: avoided (11.6 unit and integration). #7 D5: avoided (3.11). #7 third-pass ruling: durable evidence only. `review_shared_kernel` Q2: SO12 behaviour and structure (10.4a/b). **Recurred in kind, caught in time:** (a) a test-structure hang under arming (3.9, 8.9c): a held handler or a swallowed cancellation outlived the test; (b) arms that survived because the test did not discriminate (4.3b, 4.4b, 12.4b), each fixed by strengthening the test.

## Other findings for the leader

- `order_items` are reloaded with no `ORDER BY` (feature 15), but `Order.rehydrate` re-sorts the lines by line id (`domain/order.py:322-336`, reached through `order_mapper.py:131`), so the saga's request lines come out in line-UUID order: deterministic per order, random against product order. (Round 1 wrongly said "the database's order"; corrected in round 2.) The integration tests sort by product code. The flake in arm 7.5's restored run was an order-dependent assertion meeting UUID-sorted lines; its output was lost when the re-run overwrote the log.
- `UnitOfWork`'s optional `clock` (default `SystemClock`) keeps feature 15's four call sites unchanged; the composition root passes its clock.
- Root `conftest.py` could set `KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS=0` (out of this feature's bounds) to save about 3 s per saga integration test.

Untracked files (task 14.7): everything under `services/orders/src/otc_orders/{application/saga,infrastructure/saga}`, the new modules of `application/ports`, `infrastructure/messaging` (fact_topics, saga_subjects, rpc_reply, nats_saga_commands, kafka_fact_subscriber), `presentation/saga_facts_consumer.py`, `services/orders/tests/{unit/saga,integration/saga}`, `integration/test_order_row_lock.py`, `tests/architecture/test_kafka_client_confinement.py` and `progress/impl_order_saga_orchestrator.md` are this feature's and on the `tasks.md` list. The rest of `git status` untracked (features 13-15's code, `packages/cqrs`, `specs/order_saga_orchestrator/`, briefs) is not this feature's; `.arm/` is git-ignored. Edits to tracked or feature-15 files beyond the list are the "forced edits" section above.

`Packages installed: none.`

## Round 2 (items 1-6 of the review's "What must change before re-review")

**Arming tool fix first.** `.arm/arm.py`'s `run()` used `subprocess.run(..., timeout=420)`, which kills only the `uv` parent and left pytest children alive. It now starts pytest with `subprocess.Popen(..., start_new_session=True)` and, on `TimeoutExpired`, calls `os.killpg(pid, SIGKILL)` on the whole group, then reads the output (exit 124, "process group killed"). No arm in this round timed out, so the kill path itself was not exercised. After the round: no `ACTIVE` marker under `.arm/bak`, no pytest process left, only `otcpy-n8n` running, and every backup of this round (`r2-*`, 6.4a/b, 9.2b, 8.2, 8.4, 8.5a-c, 10.3c) is `cmp`-identical to its live file. Arms are `.arm/arms7.py` (new), `arms_unit.py` and `arms5.py` (re-runs); per-arm logs in `.arm/logs/<id>.log`.

### Item 1 (D1, #8 id 56): all eleven `SAGA_*` settings reach their objects

- **Change (tests only; `composition.py` untouched):** `services/orders/tests/integration/test_orders_host_lifespan.py` gains `test_every_saga_setting_the_composition_root_reads_reaches_the_object_it_configures`, driven by the real lifespan (`orders_host_factory`, no injected configuration). It sets eleven sentinels (nine numeric, pairwise distinct and asserted so; the lease rule holds: 4 x 1900 + 130 x 7 = 8510, twice that 17020, lease 91000) and records the constructor keywords of `SagaCommandDispatcher` (`max_attempts`, `backoff_ms`, `park_cap_ms`), `NatsSagaCommandsAdapter` (`timeout_ms`), `SqlAlchemySagaCommandLedger` (`lease_ms`, `pending_grace_ms`), `SagaFastPath` (`max_in_flight`), `SagaCommandSweeper` (`batch_limit`) and `SagaCommandSweeperTask` (`interval`, `enabled`), and asserts the `saga-consumer` and `saga-sweeper` tasks exist. A second test, `test_the_saga_enable_flags_decide_which_tasks_exist`, sets both flags `false` and asserts both tasks are absent (the default of `SAGA_SWEEPER_ENABLED` is already true, so only a `false` proves its reach).
- **Arms (each alone, `composition.py`; verbatim):**

| Arm | Hard-coding | Failure |
|---|---|---|
| r2-D1-max_attempts | `max_attempts=3` | `AssertionError: SAGA_COMMAND_MAX_ATTEMPTS must reach the dispatcher` / `assert 3 == 4` |
| r2-D1-backoff_ms | `backoff_ms=500` | `SAGA_COMMAND_BACKOFF_MS must reach the dispatcher` / `assert 500 == 130` |
| r2-D1-park_cap_ms | `park_cap_ms=900_000` | `SAGA_PARK_RETRY_CAP_MS must reach the dispatcher` / `assert 900000 == 777000` |
| r2-D1-max_in_flight | `max_in_flight=256` | `SAGA_FAST_PATH_MAX_IN_FLIGHT must reach the fast path` / `assert 256 == 33` |
| r2-D1-batch_limit | `batch_limit=20` | `SAGA_SWEEPER_BATCH_LIMIT must reach the sweeper` / `assert 20 == 7` |
| r2-D1-timeout_ms | `timeout_ms=5000` | `SAGA_COMMAND_TIMEOUT_MS must reach the NATS adapter` / `assert {'timeout_ms': 5000} == {'timeout_ms': 1900}` |
| r2-D1-lease_ms | `lease_ms=60_000` | `SAGA_COMMAND_LEASE_MS must reach the ledger` / `assert 60000 == 91000` |
| r2-D1-pending_grace_ms | `pending_grace_ms=10_000` | `SAGA_PENDING_GRACE_MS must reach the ledger` / `assert 10000 == 13300` |
| r2-D1-sweeper_interval (extra) | `interval=30.0` | `SAGA_SWEEPER_INTERVAL_MS and SAGA_SWEEPER_ENABLED must reach the sweeper task` / `assert (30.0, True) == (41.0, True)` |

Every restored run was green. Not armed: the enable flags' task presence (the second test and the sentinel test assert it; a flag hard-coded to its default would fail the second test for the sweeper and consumer only if hard-coded to `true`, which I did not mutate).

### Item 2 (D2): parked back-off enforced on both claims

- **Change:** `integration/saga/test_saga_command_ledger.py` gains `test_so5_a_parked_rows_backoff_is_enforced_on_both_claims_and_ends_exactly_at_next_attempt_at` (row parked with `retry_after_ms=61_234` on the fake clock, past the lease and the grace; at `parked_at + N - 1 ms` neither `try_claim` nor `claim_due` returns it; at `+ N` `claim_due` returns it) and `test_so5_a_parked_rows_backoff_ends_exactly_at_next_attempt_at_for_the_fast_path_claim` (the `try_claim` half at `+N` returns the row).
- **Arms:**
  - RL-b (`claim_due`'s parked branch without `next_attempt_at <= now`): `AssertionError: claim_due: a parked row is not due one ms before its back-off ends` / `assert [ClaimedCommand(...)] == []`.
  - `try_claim` without the `next_attempt_at` clause, against the first test: `AssertionError: try_claim: a parked row is not claimable one ms before its back-off ends`; against the second test: the same message.

### Item 3 (D3): a `sent` row is never claimed, and one `stock.release` request

- **Change:** the ledger module gains `test_so11_a_sent_row_is_a_no_op_claim_for_both_claims_even_long_after_any_lease` (after `mark_sent`, with the clock advanced 10 leases, neither claim returns it; then, planted by hand, a due `next_attempt_at` on the sent row so that each claim's own `status` predicate is what holds). `test_saga_preconditions.py::test_credit_rejected_redelivered_with_a_new_event_id_mid_compensation_owes_one_stock_release_and_commits_its_offset` now waits 0.5 s after the offset passes (25x a loopback request) and asserts the `fulfillment.stock.release` stand-in recorded exactly one request.
- **Arms:**
  - RL-c (`SagaCommand.status.in_(CLAIMABLE)` deleted from `try_claim`), ledger case: `AssertionError: try_claim: a sent row is never claimed again`.
  - RL-c, integration case: `AssertionError: exactly one fulfillment.stock.release request, got 2: the sent row must not be re-dispatched by the second credit.rejected.v1` / `assert 2 == 1`.
  - `status == "pending"` removed from `claim_due`: `AssertionError: claim_due: a sent row is never due`.
  - `status == "parked"` removed from `claim_due`'s parked branch: **survived** the first version of the ledger case (EQUIVALENT given `mark_sent` sets `next_attempt_at` to NULL and `park` refuses a sent row: the state is unreachable through the API). Fixed by planting the impossible state by hand (the test's last block); re-run: `AssertionError: claim_due: status, not a NULL next_attempt_at, keeps a sent row out`. The RL-c ledger arm and the pending-status arm were re-run after that edit and still fail as above.

### Item 4 (D4): line order

The comment at `test_saga_happy_path.py` (was 43-44) now says `Order.rehydrate` re-sorts lines by line id (a random UUID), so the request's line order is deterministic per order and unrelated to product order. The bullet under "Other findings for the leader" is corrected, and the 7.5 flake is recorded as an order-dependent assertion meeting UUID-sorted lines, output lost. (The original line-236 text is superseded in place.)

### Item 5: R3.10c recorded

R3.10c (the failure branch commits `offset+1` while still seeking) is the arm of the committed-offset sampling assertion at `test_saga_consumption.py:231` (`AssertionError: the committed offset 1 passed the failed record at 0: samples=[0, ..., 1, 1, ...]`, 21.8 s, restored run green; the reviewer's run, not repeated here). The recorded arm for 3.10 (`seek` removed) dies earlier, at `:227` (`only 1 attempts in 60 s`), so it arms the attempt count, not the sampling assertion. Nothing was re-run for this item (record only).

### Routing notes done

`specs/shared/test-matrix.md`: Status cells of R24, R28 and R29 (column 5 only) now name "deferred half ratified at the feature 16 spec gate, 2026-10-06" and the row they rest on (`requirements.md` §1 row R24 / row R28 / §1.1). Derived counts untouched. #8 id 56 (recurred, D1) added to §18's tally. The three matrix cells are the only matrix edit this round.

### Item 6: re-runs (after the changes, new arm tool; each: mutated run failed, restored green)

| Arm | Test | Failure (verbatim) |
|---|---|---|
| 9.2b | `test_a_fast_path_maximum_below_one_is_refused_naming_the_setting` | `Failed: DID NOT RAISE ValidationError` |
| 6.4a | the fast-path overflow test | `AssertionError: the overflowing signal waited 0.0502s instead of returning` |
| 6.4b | same | `AssertionError: B is never dispatched by the fast path` |
| 8.2 | `test_so11_a_claimed_row_is_invisible_...` | `AssertionError: a leased row cannot be claimed again by the fast path` |
| 8.4 | `test_leases_and_park_times_come_from_the_clock_port` | `assert datetime(2026, 10, 7, 10, 57, 22, 655000, ...) == (datetime(2026, 10, 7, 12, 0, 3, 7000, ...) + timedelta(seconds=60))` |
| 8.5a | `test_marks_are_conditional_and_attempts_accumulate` | `AssertionError: the total the caller accumulated, not the cycle count` / `assert 3 == 6` |
| 8.5b | same | `AssertionError: a sent row is never moved back to parked` / `assert 'parked' == 'sent'` |
| 8.5c | `test_park_with_an_attempt_count_outside_int32_...` | `OverflowError: value out of int32 range` (asyncpg `DataError ... 2147483648`) |
| 10.3c | the mid-compensation case | `AssertionError: timed out after 20s waiting for: the second credit.rejected.v1 is processed` |

### `./quality.sh` (developer stack down; only `otcpy-n8n` running)

- **Exit 0, 441 s, `2355 passed in 403.93s`, coverage 98.70%, "all gates passed".** A first run exited 1 in under a second on one ruff `PT018` in my new test (an `and` assertion); I split it and re-ran.
- **Delta from 2350: +5**, by file (collected counts, before to after): `integration/test_orders_host_lifespan.py` 27 to 29 (+2), `integration/saga/test_saga_command_ledger.py` 10 to 13 (+3), `integration/saga/test_saga_preconditions.py` 14 to 14 (0, an assertion added to an existing test). 2 + 3 + 0 = 5.

### Files touched this round

`services/orders/tests/integration/test_orders_host_lifespan.py`, `services/orders/tests/integration/saga/test_saga_command_ledger.py`, `services/orders/tests/integration/saga/test_saga_preconditions.py`, `services/orders/tests/integration/saga/test_saga_happy_path.py` (comment), `specs/shared/test-matrix.md` (column 5 of R24, R28, R29), this record, `feature_list.json` (feature 16's status line only: `in_review`). No `src/` file changed.

### Surprises

- The "remove `status` from `claim_due`'s parked branch" arm was an equivalent mutant through the public API; it needed a planted impossible state to be killable.
- The `.arm` tool defect was the same one the reviewer named (a `subprocess.run` timeout kills only the parent).
