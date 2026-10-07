# Premise check: brief_impl_orders_acceptance.md and brief_spec_order_saga_orchestrator.md (2026-10-06)

Verdict: DO NOT ACT until the two FALSE lines are settled. Counts: VERIFIED 38, FALSE 2, UNVERIFIABLE 3.

## FALSE
- Brief 1 line 3, "Feature 15 is `in_progress` (set by the leader)": the on-disk feature_list.json has id 15 `"status": "pending"` (python json load, printed id 15). The leader must set it before dispatch, or the implementer's "set to in_review" is a pending-to-in_review jump.
- Brief 1 line 8, `src/Orders/Presentation/Rpc/OrdersCreatePayloads.cs` among "#8's code (commit 4c6ed34)": it is in the commit (`git show --stat=200 4c6ed34` lists it, 31 lines) but is absent from #8's current tree (`ls` fails; `git ls-files | grep -i Payloads` shows `src/Contracts/Rpc/OrdersRpcPayloads.cs`). The brief says to read current versions too, and does not say this file moved.

## VERIFIED (command, decisive output)
- feature 15 has eight acceptance items: python json, 8 entries. Items 5-8 come from features 13 (F7), 43, 14, 14: ids 13/43/14 named in the items' text.
- feature 16 has seven acceptance items, the last being SO8 from review_shared_kernel Q2: python json, 7 entries.
- feature 42: sdd false, three items: python json.
- #8 specs/order_saga_orchestrator requirements/design/tasks are 99 / 613 / 136 lines: `wc -l`.
- #8 history.md 773-820 is feature 15's entry, 821-871 feature 16, 872-913 feature 42, 966 Phase 8 closing assessment: `sed -n` on boundary lines.
- 15's entry contains D1-D6 (rounds 1-3), A3, A5, A10, A11, #7's N2 and N3, "Notes for #9", "what fails if I revert this?", "Arm the call site": grep in 773-820.
- 16's entry says four review rounds and D1-D5, with a "Notes for #9": grep in 821-871.
- #7 history line 821 is feature 16's entry, line 838 is the third-pass durable-evidence ruling, line 1091 is feature 42: `sed -n`.
- #7 had "0 step-table divergences" against saga.md: #7 history line 824.
- #8 backlog 46 (RpcError discriminated before typed decoding), 47 (allocator scan cost), 50 (responder shutdown fault isolation), 56 (composition-root env reads unguarded), 80 (fast path head-of-line), 88 (parallelism bounds the stall), 89 (concurrency asserted nowhere), 90 (DegreeOfParallelism clamp), 110 (saga adapter reply decode guard), 62 (operator cancel races saga), 71 (operator note survives compensation), 91 (#7 hasAcceptedOperatorCancel has no DB guard), 48 (headers thread-safety guard), 51 (payload schema parity from asyncapi), 94 (SO9 recorded arm): subjects match, from #8 feature_list.json. The brief's one-line parentheticals (46, 47, 50, 56, 80, 88, 89, 90, 110) match.
- Ids 62/71/91 split between 16 and a later #9 cancel feature: #9 id 41 `orders_cancel_responder` exists, pending.
- #8 commit 4c6ed34 exists and its stat lists OrdersCreateResponder.cs, OrdersCreateErrorMapper.cs, OrdersCreateRequestValidator.cs, PlaceOrderCommandHandler.cs, PlaceOrderErrors.cs, NatsStockAvailabilityChecker.cs, EfCoreOrderNumberAllocator.cs, EfCoreOrderReferenceCatalog.cs, OrdersHost.cs, OrdersCreateAcceptanceTests.cs, StandInFulfillmentStockCheckResponder.cs, plus 3+ files under tests/Orders.UnitTests: `git show --stat`, `ls` (all exist at HEAD except the one above).
- #8 specs/orders_aggregate/design.md §9.2 starts at line 437 and ends 453 (§10 at 455); table has `details: { code: ... }` and `NOT_FOUND` with `{ field, value }`, `UNAVAILABLE` / `TIMEOUT` with subject; §10 is "Command-handler shape": sed 437-455.
- #9 specs/orders_aggregate/design.md §5.4 (line 186) says a non-zero orderDiscount is refused by feature 15's handler; §10 (line 305) "Domain errors" has twelve rows ("Twelve." in text): sed.
- #9 §9 persistence contract says feature 16 loads a saga step's order under `SELECT ... FOR UPDATE`: design.md line ~303.
- #7 files orders-create.controller.ts, rpc-error-mapper.ts exist; place-order handler is apps/orders/src/application/place-order.handler.ts: `ls`/`find`.
- #7 saga files saga-dispatch.* and saga-fact.* under application/commands, presentation/saga-facts.controller.ts, saga-preconditions.integration.spec.ts exist: `ls`/`find`.
- asyncapi.yaml: `address: orders.create` at 244, `address: fulfillment.stock.check` at 293, operations titles at 831 and 883, messages 1600-1660 (OrdersCreate/StockCheck request and reply), `RpcError` at 2840 with a closed twelve-value `code` enum: sed/grep.
- test-matrix.md: R19-R29 section, 11 rows: line 74 and 115.
- review_shared_kernel.md lines 78-81 are the Q2 / SO8 / ORD-000000 text: sed.
- #9 has no `services/orders/**/composition.py`: `find services/orders -name composition.py` is empty.
- #9 app.py has `/health/live` only and a stub lifespan: cat.
- #9 settings.py has no NATS settings: `grep -in nats` is empty. services/orders/pyproject.toml has no nats-py: dependency list is fastapi, uvicorn, otc-*, sqlalchemy, asyncpg, alembic, pydantic-settings, aiokafka.
- sequences.py runs the MAX only when seeding, and says "#8 id 47 shipped the MAX on every allocation": file lines 12-20.
- Files exist: unit_of_work.py, order_repository.py, order_mapper.py, sequences.py, outbox/relay_task.py with `OutboxRelayTask.run(self, stop: asyncio.Event)` (line 34), cqrs `HandlerRegistry.build` (dispatcher.py:93) and `Dispatcher` (144).
- NATS testcontainer filterwarnings exist in root pyproject.toml (line 120) and tests/architecture/test_warning_policy.py (test at line 15).
- Guard files exist: test_write_path_population.py, test_cqrs_registration_explicit.py, test_money_guard.py, range_guards.py and test_range_guard_parity.py.
- Baseline 1652 passed: progress/history.md:799 and progress/current.md:53 (feature 14 close, stack down).
- #9 outbox design §6.1-6.5 exists, with §6.5 "The consumer shell, designed here, built by feature 16": grep headings. `infrastructure/messaging/` holds idempotent_consumer.py and consumer_name.py.
- #9 models.py has `saga_commands` (SagaCommand) and `saga_ignored_facts` tables; payload columns use RawJson over type `json`, not `jsonb`: grep.
- contracts already has `RpcError`, `StockCheckRequestPayload`/`ReplyPayload`, `OrdersCreate*Payload` (generated/asyncapi.py), so the brief's "nothing in packages/" bound does not block item 1.
- #8 health checks arrived in its phase 14: #8 id 27 observability_reliability is phase 14.
- Brief 1 / brief 2 "Do not edit feature_list.json / the leader sets 16 to spec_ready": consistent with 15 and 16 both being pending now.

## UNVERIFIABLE
- "#8 found its library contradicting its own documentation" (nats-py/NATS.Net): the history text says so, but only a run against a real NATS server settles #9's library; that is the brief's own question 1.
- The Plan (Phase 8) bullets in brief 2: the Plan is an external private document, not on disk in the repo.
- "four launches lost to 529" and similar effort figures: not cited by the briefs; skipped.

## Brief-versus-acceptance conflicts (ids 15, 16, 42)
None found. Brief 1's file bounds (services/orders/**, tests/architecture/**, .env.example, matrix row, feature 15 status line) cover every item: F7 guard (tests/architecture + mapper), composition.py and the registration guard (services/orders, tests/architecture), the relay lifespan and one-relay enforcement (services/orders). Brief 2 forbids editing feature_list.json, which is consistent with 16's acceptance (no item requires an edit there). Brief 2 mandates tasks.md name pyproject/migration changes, and its "Write only specs/order_saga_orchestrator/**" bound does not forbid that.
Note: 15's item 6 requires a "behavioural registration guard" with frame-recording; brief 1 lists the file but gives no pointer to that item's detail beyond "all eight are acceptance criteria", which is adequate.
