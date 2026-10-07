# Requirements — `order_saga_orchestrator` (feature 16, phase 8, `sdd: true`)

> **This is a pointer document.** `specs/shared/` was copied verbatim from #8 (with `SA-1` – `SA-5` applied) and is **read-only**. The shared requirements this feature realises, **R19 – R29**, are cited here by id and are **not restated**: `specs/shared/requirements.md` §3 (lines 171 – 235) is their single authority, elaborated by the **whole** of `specs/shared/saga.md` (step table §3.1, compensation §4, consumption map §5, idempotency layers and redelivery table §6, failure table §7) and by the saga command and fact schemas of `specs/shared/asyncapi.yaml`. Nothing below amends, rewords or reinterprets them. The value of this feature's specification is in [`design.md`](./design.md), which is stack-specific and was inherited from nowhere.
>
> **Local ids.** This file reuses #8's local ids **`SO1` – `SO11`** with their numbering unchanged (`SO1` – `SO8` are #7's, `SO9` – `SO11` are #8's; `../order-to-cash-dotnet/specs/order_saga_orchestrator/requirements.md` §2, lines 37 – 71), and #7's SO-numbered integration cases (`../order-to-cash-nestjs/apps/orders/src/saga-consumption.integration.spec.ts:68`, `saga-command-retry.integration.spec.ts:124`, `saga-preconditions.integration.spec.ts:183`) are ported case for case. Reusing an id is a claim that #9 owes the same obligation; where the Python / PostgreSQL / aiokafka / nats-py realisation is differently shaped, a *#9 note* says how. **`SO12` – `SO17` are new in #9**, each tied to an acceptance item of `feature_list.json` id 16 or to a #8 backlog finding, and each names why #7 and #8 did not carry it as a requirement.

## 1. Shared requirements realised

| Shared id | One-line reminder (authority: `specs/shared/requirements.md`) | Realised in #9 by | `design.md` |
|---|---|---|---|
| **R19** | `order.placed.v1` + `placed` → issue `stock.reserve` for every line, status unchanged | Step-table row `order.placed.v1`: `Advance(precondition=PLACED, apply=None, command_after=STOCK_RESERVE)`. The request's `lines` are built from the **loaded aggregate**'s `lines` (one request line per order line), so "for every line" is structural | §6.1, §9.4 |
| **R20** | `stock.reserved.v1` + `placed` → `stock_reserved`, issue `credit.hold` for the total | `Order.mark_stock_reserved(occurred_at=fact.occurred_at)` then an owed `credit.hold` whose `amount` is `{amount: order.total_amount.amount, currency}` (an `int`, never a `Decimal` or `float`) | §6.1, §9.4 |
| **R21** | `credit.approved.v1` + `stock_reserved` → `credit_approved` → `confirmed`, exactly one `order.confirmed.v1`, issue `despatch.create` | One step, one aggregate load and save: `approve_credit(...)` then `confirm(occurred_at=…, causation_id=fact.event_id)`. Only `confirm` raises an event (feature 13, `domain/order.py:367-391`), and the repository writes each event once (`order_repository.py:66-72`) | §6.1 |
| **R22** | `order.despatched.v1` + `confirmed` → `despatched`, issue `invoice.issue` | `mark_despatched(...)`, owed `invoice.issue` built from the aggregate (lines frozen from `confirmed`, R7) | §6.1, §9.4 |
| **R23** | `invoice.issued.v1` + `despatched` → `invoiced`, **no** further command | `mark_invoiced(...)`, `command_after=None`; the absence is a tested absence (no `saga_commands` row for the order after the step) | §6.1 |
| **R24** | `payment.received.v1` → `paid`; `credit.released.v1` + `paid` → `completed`, exactly one `order.completed.v1` | Two rows: `mark_paid(...)`, then `complete(occurred_at=…, causation_id=…)`. **The API half of this row's matrix entry stays `TODO`**: it belongs to feature 31 `api_tests` | §6.1 |
| **R25** | Unmet precondition → no state change, no command, no fact, recorded as ignored with observed and expected status | Equality comparison of `order.status` with the step's precondition; on mismatch a `saga_ignored_facts` row (`marker = precondition_unmet`, both statuses) written **in the same transaction as the dedup row**, then the offset commits. Table and index exist since feature 9 (`models.py:208-219`) | §6.2, §7.4 |
| **R26** | `stock.rejected.v1` + `placed` → cancel `stock_rejected`, **no** `stock.release` | `Cancel(precondition=PLACED, reason=STOCK_REJECTED, compensation_steps=())`; a `Cancel` row cannot owe a command by construction (the type has no `command_after` field). The "shall not" is proven at three levels: step table, no `saga_commands` row, zero requests observed by the stand-in release responder — including after a redelivery against `cancelled` | §6.1, §10 |
| **R27** | `credit.rejected.v1` + `stock_reserved` → issue `stock.release`, stay `stock_reserved` | `Advance(precondition=STOCK_RESERVED, apply=None, command_after=STOCK_RELEASE)` with request `reason = credit_rejected` | §6.1, §10 |
| **R28** | `stock.released.v1` + `stock_reserved` (credit-rejection compensation) → cancel `credit_rejected`, both steps visible in causal order; never cancel before the release fact | `Cancel` whose reason and compensation step are derived from the **observed fact's own payload** (`reason`) and envelope (SO7); causal order from `causation_id = fact.event_id` on `order.cancelled.v1` (R12) and per-partition order (R15). The **e2e half** stays `TODO` for feature 32 `e2e_playwright` | §6.1, §10 |
| **R29** | RPC timeout / transport error → retry with backoff, status unchanged; commands idempotent by (`orderReference`, operation); on exhaustion dead-letter the triggering fact + saga-failure timeline entry | **Split exactly as the shared matrix splits it** (inherited from #7, carried by #8, §1.1): the retry / backoff / status-unchanged clause here (SO4, SO5, the durable `saga_commands` row; idempotency is the responders' own, saga.md §6 layer 3); the **dead-letter clause** stays `TODO` for feature 27 `observability_reliability`, which attaches to the park transition (`design.md` §9.8) | §9 |

**Reusing an id is a claim.** Every row asserts the Python realisation satisfies the requirement #7's and #8's do. Three rows differ in mechanism, not in obligation, and the design argues each: R25's record is written through PostgreSQL's `INSERT` in the dedup transaction (no MS-SQL hint, no MySQL `json` normalisation); R29's retry runs in an asyncio task spawned per command rather than on #7's RxJS `mergeMap` or #8's channel worker pool (`design.md` §8); the order is loaded under `FOR UPDATE OF orders` rather than #7's plain read or #8's `UPDLOCK, ROWLOCK` (SO17).

### 1.1 The `R29` split and the `R16` deferral — inherited, not re-decided

#7 split `R29`'s matrix row at its own gate into a retry case and a dead-letter case (the latter deferred to `observability_reliability`); #8 inherited the amended row (#8 `requirements.md` §1.1). #9 inherits the same row unchanged (`specs/shared/test-matrix.md` §3, `R29`, two cases). `R16` (consumer retry → `<topic>.dlq` → acknowledge) was deferred to feature 27 at feature 14's gate (`specs/outbox_and_idempotency/requirements.md` §1.2); this feature builds the **first fact-stream consumer** in #9, which is the thing `R16` wraps, but does not claim `R16`. The interim behaviour of an exhausted command is SO5 (park, keep retrying on a capped schedule); the interim behaviour of a fact whose processing raises is SO9 (no commit, paced redelivery, the partition held). Both are #7's and #8's decisions, and Python forces no difference. **Decided, not open.**

### 1.2 What this feature does not realise, and who does

| Not here | Owner | Why there |
|---|---|---|
| Terminal-vs-retryable split of an `RpcError` reply (nine terminal codes, a `rejected` end state) | feature **42** `orders_saga_terminal_rejection_classification` | §5 below gives the split of its three items |
| SA-4's operator-cancellation variants: `stock.released.v1` at `credit_approved` / `confirmed` owing `credit.release`; `credit.released.v1` (`order_cancelled`) cancelling from those statuses; a late `credit.approved.v1` after an accepted operator cancel owing `credit.release` only | feature **41** `orders_cancel_responder` (its acceptance item 3 names SA-4's ordering and the late approval) | They have no producer until `orders.cancel` exists, and they need the accepted-cancel evidence query #8 id 91 says must be guarded against a real database. The table shape built here takes them as added rows, not as a reshape (`design.md` §6.1) |
| `<topic>.dlq`, dead-letter headers, `order.saga_failed.v1`, metrics, `traceparent` | feature **27** | `design.md` §9.8 lists the seams |
| The responders | features 17 – 22 | Integration tests use stand-ins under `tests/` only |
| R24's API half; R28's e2e half | features 31, 32 | Need the Gateway / the UI |

## 2. Local requirements

### 2.1 Reused from #7 and #8 (`SO1` – `SO11`)

Texts are #8's, verbatim (`../order-to-cash-dotnet/specs/order_saga_orchestrator/requirements.md` lines 43 – 69), line-unwrapped only.

**SO1.** WHEN the orchestrator starts with no committed offsets for its consumer group, THE SYSTEM SHALL consume each of the three fact topics from the earliest offset, so that facts published before the orchestrator first existed are processed rather than skipped.

> *#9 note.* aiokafka's default is `auto_offset_reset="latest"` (`aiokafka/consumer/consumer.py:246`, 0.14.0), so this is a change from the default, as it was in #8 (`largest`). The group id is the literal `orders.saga`, identical to `ConsumerName.ORDERS_SAGA.value`; aiokafka uses it verbatim (#7's framework appended `-server`, #7 `progress/history.md` line 832, defect D5).

**SO2.** WHEN the orchestrator receives one of the facts it produces itself (`order.confirmed.v1`, `order.completed.v1`, `order.cancelled.v1`, `order.saga_failed.v1`), THE SYSTEM SHALL acknowledge it without dispatching any command, without opening a transaction, without writing a `processed_events` record and without loading any aggregate (`saga.md` §5: consuming them would be a loop).

> *#9 note.* Four skips, as #8: `otc_contracts.FACT_MODELS` holds all fourteen facts (`packages/contracts/src/otc_contracts/facts.py:52-67`). #7 had three because `order.saga_failed.v1` did not exist in its feature 16.

**SO3.** WHEN a saga step both changes the order status and owes a follow-up command, THE SYSTEM SHALL commit the status change, the `processed_events` record, the `outbox` records and a durable **pending-command record** in one transaction, and SHALL issue the command only after that transaction has committed; IF the process crashes between the commit and the command issue — including before the in-process event-to-signal hop has run — THEN THE SYSTEM SHALL issue the command from the pending-command record on a later sweep, without re-consuming the fact; the durable pending-command record, **not** the in-process hop, is the delivery guarantee.

**SO4.** WHEN a command issued over the RPC transport times out or returns a transport error, THE SYSTEM SHALL retry it in line at most `MaxAttempts` times (default **3**) with exponential backoff starting at `BackoffMs` (default **500 ms**, doubling), each attempt bounded by `TimeoutMs` (default **5 000 ms**), while leaving the order status unchanged — refining `R29`'s "configured maximum" with this assessment's concrete policy.

> *#9 note.* Settings `SAGA_COMMAND_MAX_ATTEMPTS`, `SAGA_COMMAND_BACKOFF_MS`, `SAGA_COMMAND_TIMEOUT_MS` (#7's names, `../order-to-cash-nestjs/apps/orders/src/infrastructure/saga/saga.config.ts:12-15`). "Transport error" includes a reply that is not JSON, not an object, or fails its reply schema (SO15), and, after feature 42, an `RpcError` reply with a transient code (`INTERNAL_ERROR`, `UNAVAILABLE`, `TIMEOUT`) or with a code outside the twelve; a terminal business code is resolved on the first attempt, not retried (§5, `design.md` §9.2).

**SO5.** IF the in-line attempts of SO4 are exhausted, THEN THE SYSTEM SHALL mark the command **parked** — durably, with the accumulated attempt count, the last error and the next retry time — SHALL log a structured saga-failure entry carrying the `correlationId`, and SHALL leave the order in its last legal status; WHILE a command is parked, THE SYSTEM SHALL re-attempt it on a sweep interval with capped exponential backoff, indefinitely, so that the saga resumes without operator action once the responder becomes available. *(Interim stand-in for `R29`'s dead-letter clause until feature 27 — see `design.md` §9.7, §9.8.)*

**SO6.** WHEN a command reply reports a **business rejection** (`outcome: rejected` from `stock.reserve` or `credit.hold`), THE SYSTEM SHALL mark the command sent, SHALL NOT retry it, SHALL change no aggregate state, and SHALL await the corresponding rejection **fact** to take the compensation path (`saga.md` §2: a command's response never advances the saga; §7: a rejection is a domain outcome, not a failure).

**SO7.** WHEN `stock.released.v1` is received for an order in status `stock_reserved`, THE SYSTEM SHALL map the fact's `reason` to the cancellation reason (`credit_rejected` → `CreditRejected`, `order_cancelled` → `OperatorCancelled`) and SHALL pass a `compensationSteps` collection built from the observed compensating fact (`Step = StockReleased`, its `eventId`, `eventType`, `occurredAt`) into `Order.Cancel`, so the unwinding is auditable in the emitted `order.cancelled.v1` (`R28`; the aggregate never observes the compensating fact — the orchestrator supplies it).

> *#9 note.* `CancellationReason.CREDIT_REJECTED` / `OPERATOR_CANCELLED`, `CompensationStepKind.STOCK_RELEASED` (`domain/value_objects/`). The `order_cancelled` branch has no producer until feature 41 and is armed at unit level with double force (`tasks.md` 11.5). `summary` is left `None` (gate point G2, `design.md` §17).

**SO8.** IF a consumed fact's `correlationId` matches no order in the write model, THEN THE SYSTEM SHALL record the fact as ignored with an `unknown_order` marker, SHALL acknowledge it, and SHALL NOT throw — a fact can never legitimately precede its own order's row, because `order.placed.v1` commits with the order in one transaction before it is published (`R13`), so an unknown order is cross-environment residue, not an ordering problem.

> *#9 note.* Ported verbatim with #7's fixture, `orderReference: 'ORD-000000'` (`../order-to-cash-nestjs/apps/orders/src/saga-preconditions.integration.spec.ts:183-190`); SO12 is the property that makes that fixture pass in #9.

**SO9.** WHILE consuming the fact stream, THE SYSTEM SHALL advance the committed offset for a partition only **after** the handler for the message at that offset has returned successfully; IF the handler throws, THEN THE SYSTEM SHALL leave the committed offset unchanged so the message is redelivered, and SHALL NOT acknowledge it by any other means.

> *#9 note.* #7 got this from kafkajs (a rejected `eachMessage` is not committed), #8 constructed it (`EnableAutoOffsetStore = false`, `StoreOffset` after the handler). #9 constructs it differently again: `enable_auto_commit=False` (aiokafka's default is `True`, `consumer.py:247`), an explicit `commit({tp: offset + 1})` after the handler, **and a `seek` back to the failed offset**, because aiokafka's fetch position has already moved past a record once it is returned, so a later record of the same partition would otherwise succeed and commit past the failed one (`design.md` §5.3). #8 id 94 is why the test reads the committed offset from the broker and distinguishes a redelivery from an in-process retry.

**SO10.** WHILE a saga command is being issued or retried over the RPC transport, THE SYSTEM SHALL NOT occupy the fact-stream consume loop, so that a command whose responder is absent delays neither the consumption of unrelated facts nor the consumer group's liveness.

**SO11.** WHILE a saga command row is being dispatched, THE SYSTEM SHALL exclude it from any concurrent claim for a bounded lease; IF the dispatching process dies mid-attempt, THEN THE SYSTEM SHALL make the row claimable again once the lease has elapsed, so no command is stranded by a crash and none is dispatched twice concurrently by this process.

> *#9 note.* The lease is #8's (expressed in `next_attempt_at`, no new column); the claim is one PostgreSQL statement per path (`design.md` §9.6). SO16 adds the property #8's first build broke: the claimer that holds a row is never excluded by its own lease.

### 2.2 New in #9 (`SO12` – `SO17`)

**SO12.** WHEN a consumed fact carries an `orderReference` that the wire pattern `^ORD-[0-9]{6,}$` admits but the domain's canonical reference form refuses (for example `ORD-000000`), THE SYSTEM SHALL route the fact by its `correlationId` exactly as any other fact, and SHALL NOT refuse, retry or dead-letter it because of that reference.

> *Why new.* `feature_list.json` id 16 acceptance item 7, routed here by `progress/review_shared_kernel.md` Q2 (lines 78 – 81): #9's kernel parse refuses `ORD-000000`, which #7's and #8's did not, so neither predecessor could have faced it.

**SO13.** WHILE the dispatch of one saga command is in flight, THE SYSTEM SHALL NOT delay the fast-path dispatch of any other command behind it; IF the number of in-flight fast-path dispatches has reached the configured maximum, THEN THE SYSTEM SHALL leave the further command to the durable pending-command path (SO3) without waiting, and SHALL log that it did so.

> *Why new.* Acceptance item 5 (#8 ids 80, 88, 89, 90). #7 had the property free from `@nestjs/cqrs`'s `mergeMap` (`node_modules/.pnpm/@nestjs+cqrs@11.0.3…/node_modules/@nestjs/cqrs/dist/event-bus.js:196`) and wrote no requirement; #8 lost it, bounded it at eight, and recorded the residual as id 88. The concurrency model that satisfies it is gate point **G1** (`design.md` §8, §17).

**SO14.** WHEN the orchestrator issues a saga command, THE SYSTEM SHALL carry, on every attempt of that command and on the fast path and the sweeper path alike, the header `x-correlation-id` equal to the order id and the header `x-request-id` equal to one identifier per pending-command record, unchanged across retries of that record; and WHEN the fast path dispatches a command, THE SYSTEM SHALL run the dispatch in the execution context of the fact handling that owed it.

> *Why new.* Acceptance item 5's *"carrying trace context"*. The header meanings are `asyncapi.yaml`'s `RpcHeaders` (lines 2816 – 2838, *"A retry after a timeout reuses the same value"*). #8 lost the second clause across its channel hop and fixed it late (`progress/impl_saga_trace_context_fast_path_fix.md`); #7 never lost it. `traceparent` itself is feature 27's: the "execution context" is what it will ride on (`design.md` §11).

**SO15.** IF a reply to a saga command is not valid JSON, is not a JSON object, carries an `RpcError` body, or fails the reply schema of its subject, THEN THE SYSTEM SHALL classify the attempt as a transport error of that subject and SHALL NOT let a decoding exception escape the RPC adapter.

> *Why new.* Acceptance item 6 (#8 id 110: #8's adapter let a raw `JsonException` escape until its phase 25; #7's did not, `nats-saga-commands.adapter.ts:170-178`). The `RpcError` clause is the pre-42 shape (§5).

**SO16.** WHILE the sweeper holds the claim on a pending-command record, THE SYSTEM SHALL issue that command from the sweeper's own claim without claiming it again, and SHALL complete every dispatch of a sweep batch within the claim's lease; IF the configured lease does not exceed the worst-case duration of one dispatch, THEN THE SYSTEM SHALL refuse to start.

> *Why new.* Acceptance item 4 (*"a sweeper which never re-claims a row it already holds"*). #8's first build re-claimed its own row and silently dispatched nothing (#8 `progress/history.md` line 840); its sequential batch could also outlive its lease. #7 held no lease, so the question did not arise.

**SO17.** WHILE a saga step's transaction holds an order, THE SYSTEM SHALL make any other transaction that loads the same order for a mutation wait until the first commits or rolls back, and SHALL NOT lock any reference-data row read with the order.

> *Why new.* `specs/orders_aggregate/design.md` §9 (this repository's approved spec: *"feature 16 loads a saga step's order under `SELECT … FOR UPDATE`"*). #7 read plainly under MySQL `REPEATABLE READ`; #8 added `UPDLOCK, ROWLOCK` only in its phase 14 (#8 id 62, `EfCoreOrderRepository.cs:71-108`). The second clause is PostgreSQL's: a bare `FOR UPDATE` over the order's four-table join would also lock the retailer, company and currency rows (`design.md` §7.2).

## 3. Local traceability

The shared rows `R19` – `R29` are traced in [`specs/shared/test-matrix.md`](../shared/test-matrix.md) §3; the implementer writes **column 5 only**, citing the literal test function names below (#8 review D7), and updates the derived counts including the **Total** row (#7 review D6). `R24`'s API half, `R28`'s e2e half and `R29`'s dead-letter case stay `TODO`. Paths are under `services/orders/tests/`; every row starts `TODO`.

| Id | Level | Test file › case | Status |
|---|---|---|---|
| **R19** (shared row) | integration | `integration/saga/test_saga_happy_path.py` › `test_r19_issues_stock_reserve_for_every_line_on_order_placed_v1_and_leaves_the_order_in_placed` | DONE |
| **R20** (shared row) | integration | same file › `test_r20_moves_placed_to_stock_reserved_and_issues_credit_hold_for_the_order_total` | DONE |
| **R21** (shared row) | integration | same file › `test_r21_moves_stock_reserved_through_credit_approved_to_confirmed_emits_exactly_one_order_confirmed_v1_and_issues_despatch_create` | DONE |
| **R22** (shared row) | integration | same file › `test_r22_moves_confirmed_to_despatched_and_issues_invoice_issue` | DONE |
| **R23** (shared row) | integration | same file › `test_r23_moves_despatched_to_invoiced_and_issues_no_further_command_while_awaiting_a_remittance` | DONE |
| **R24** (shared row, integration half) | integration | same file › `test_r24_moves_invoiced_to_paid_then_paid_to_completed_and_emits_exactly_one_order_completed_v1` | DONE (integration half; API half TODO, feature 31) |
| **R25** (shared row) | integration | `integration/saga/test_saga_preconditions.py` › `test_r25_ignores_a_fact_whose_precondition_status_is_unmet_and_records_the_observed_and_expected_status` (parametrised over the ten consumed facts) | DONE |
| **R26** (shared row) | integration | `integration/saga/test_saga_compensation_stock_rejected.py` › `test_r26_cancels_with_reason_stock_rejected_and_issues_no_stock_release_command` | DONE |
| **R27** (shared row) | integration | `integration/saga/test_saga_compensation_credit_rejected.py` › `test_r27_issues_stock_release_as_the_first_compensation_step_and_leaves_the_order_in_stock_reserved` | DONE |
| **R28** (shared row, integration half) | integration | same file › `test_r28_cancels_with_reason_credit_rejected_only_after_stock_released_v1_arrives` | DONE (integration half; e2e half TODO, feature 32) |
| **R29** (shared row, retry case) | integration | `integration/saga/test_saga_command_retry.py` › `test_r29_retries_a_timed_out_command_with_backoff_without_changing_the_order_status_and_records_the_exhausted_attempts_durably` | DONE (retry case; dead-letter case TODO, feature 27) |
| acceptance item 1 | integration | `integration/saga/test_saga_happy_path.py` › `test_saga_reaches_invoiced_then_completed_from_orders_create_against_stand_in_responders` | DONE |
| **SO1** | integration | `integration/saga/test_saga_consumption.py` › `test_so1_first_boot_consumes_a_fact_published_before_the_consumer_group_ever_subscribed` | DONE |
| **SO2** | unit | `unit/saga/test_step_table.py` › `test_so2_the_four_self_produced_facts_map_to_skip`; `unit/saga/test_saga_facts_consumer.py` › `test_so2_a_self_produced_fact_is_acknowledged_with_no_dispatch_no_transaction_and_no_store_access` | DONE |
| **SO3** | integration + unit | `integration/saga/test_saga_command_retry.py` › `test_so3_a_pending_row_committed_with_no_fast_path_signal_is_issued_by_a_sweeper_cycle_and_the_saga_resumes`; `integration/saga/test_saga_transactional_unit.py` › `test_so3_the_owed_command_row_commits_and_rolls_back_with_the_status_change`, `test_so3_the_fast_path_is_signalled_only_after_the_owed_command_row_is_committed` | DONE |
| **SO4** | unit | `unit/saga/test_command_dispatcher.py` › `test_so4_retries_a_timed_out_command_up_to_max_attempts_with_the_configured_backoff_schedule` | DONE |
| **SO5** | integration | `integration/saga/test_saga_command_retry.py` › `test_so5_a_parked_command_is_reattempted_by_the_sweeper_and_sent_once_a_responder_appears` | DONE |
| **SO6** | integration + unit | `integration/saga/test_saga_compensation_credit_rejected.py` › `test_so6_a_business_rejected_credit_hold_is_marked_sent_and_never_retried`; `unit/saga/test_command_dispatcher.py` › `test_so6_a_business_rejection_is_marked_sent_after_exactly_one_attempt` | DONE |
| **SO7** | integration + unit | `integration/saga/test_saga_compensation_credit_rejected.py` › `test_so7_the_cancellation_carries_exactly_one_stock_released_step_built_from_the_observed_fact`; `unit/saga/test_step_table.py` › `test_so7_maps_both_release_reasons_and_builds_the_step_from_the_observed_fact` | DONE |
| **SO8** | integration | `integration/saga/test_saga_preconditions.py` › `test_so8_a_fact_whose_correlation_id_matches_no_order_is_recorded_unknown_order_and_acknowledged_without_throwing` | DONE |
| **SO9** | integration | `integration/saga/test_saga_consumption.py` › `test_so9_a_handler_that_throws_leaves_the_committed_offset_unchanged_and_a_restarted_consumer_redelivers_the_fact`, `test_so9_a_failed_record_is_never_committed_past_by_a_later_record_of_the_same_partition` | DONE |
| **SO10** | unit | `unit/saga/test_fast_path.py` › `test_so10_signalling_returns_before_the_rpc_issue_completes` | DONE |
| **SO11** | integration | `integration/saga/test_saga_command_ledger.py` › `test_so11_a_claimed_row_is_invisible_to_a_concurrent_claim_until_its_lease_elapses`, `test_so11_a_row_whose_lease_elapsed_is_claimable_again` | DONE |
| **SO12** | integration | `integration/saga/test_saga_preconditions.py` › `test_so12_a_fact_carrying_order_reference_ord_000000_is_routed_by_correlation_id_and_never_refused_by_the_reference_parse` | DONE |
| **SO13** | integration + unit | `integration/saga/test_saga_fast_path_concurrency.py` › `test_so13_a_command_whose_responder_never_answers_does_not_delay_another_orders_command`; `unit/saga/test_fast_path.py` › `test_so13_a_signal_beyond_the_in_flight_maximum_returns_at_once_and_leaves_the_row_to_the_sweeper` | DONE |
| **SO14** | integration + unit | `integration/saga/test_saga_command_headers.py` › `test_so14_every_attempt_carries_the_order_id_and_one_request_id_per_command_row_on_both_paths`; `unit/saga/test_fast_path.py` › `test_so14_the_dispatch_runs_in_the_context_of_the_fact_handling_that_owed_it` | DONE |
| **SO15** | integration + unit | `integration/saga/test_nats_saga_commands_reply_decode.py` › `test_so15_a_malformed_reply_on_every_saga_subject_is_a_transport_error_never_a_decode_exception`; `unit/saga/test_nats_saga_commands.py` › `test_so15_each_reply_defect_is_classified_as_a_transport_error_of_its_subject` | DONE |
| **SO16** | integration + unit | `integration/saga/test_saga_command_retry.py` › `test_so16_the_sweeper_issues_each_row_it_claimed_exactly_once_without_reclaiming_it`; `unit/saga/test_saga_settings.py` › `test_so16_a_lease_not_exceeding_the_worst_case_dispatch_refuses_to_start` | DONE |
| **SO17** | integration | `integration/test_order_row_lock.py` › `test_so17_a_second_transaction_loading_the_same_order_for_update_waits_for_the_first`, `test_so17_the_lock_holds_the_order_row_and_no_reference_data_row` | DONE |

**Case names are the contract** (matrix rule 4): a renamed test edits its row in the same change. Guard tests that prove a design property rather than a requirement are named in `tasks.md` and are not rows here.

## 4. Acceptance (from `feature_list.json` id 16)

| Acceptance item | Requirements |
|---|---|
| 1. happy path reaches `invoiced` against stubbed responders | R19 – R24, the acceptance-item-1 case |
| 2. `credit.rejected` releases stock and cancels; `stock.rejected` cancels without a release | R26 – R28, SO6, SO7 |
| 3. idempotent under event redelivery; every step recorded | R18 (feature 14's mechanism, exercised here), R25, SO8, the redelivery sweep (`design.md` §7.6) |
| 4. `saga_commands` pending / sent / parked + sweeper that never re-claims a row it holds | SO3, SO5, SO11, SO16, R29 |
| 5. fast-path dispatch without head-of-line blocking, carrying trace context (#8 ids 80, 88 – 90) | SO10, SO13, SO14 |
| 6. reply decode guarded (#8 id 110) | SO15 |
| 7. #7's SO8 ported verbatim with `ORD-000000`; the reference is never parsed ahead of the correlation lookup | SO8, SO12 |

## 5. Feature 42's boundary — the split, stated for scoping

> **Feature 42's amendment (this section).** The table below is the pre-42 split, kept as the record of what feature 16 delivered. Feature 42 has since delivered items 1 and 3 (the nine-code terminal set `TERMINAL_RPC_ERROR_CODES`, `SagaCommandBusinessRejectionError`, the dispatcher's first-attempt `ledger.reject`, the `rejected` status and every ledger status predicate: `try_claim`, `claim_due`, `mark_sent`, `park`, `reject`) and kept item 2 green. The current taxonomy is `design.md` §9.2 and §9.5. A terminal rejection leaves a log line and the `rejected` row, with no `order.saga_failed.v1` and no dead letter (#7 and #8 deferred both to observability).

Feature 42's three items, against what this feature's adapter and dispatcher delivered (before 42):

| Feature 42 item | Delivered here? | Reason |
|---|---|---|
| 1. a terminal business-outcome `RpcError` is classified terminal, not retried at capped backoff forever | **Half.** The adapter discriminates an `RpcError` body before typed decoding and raises `SagaCommandRpcError` carrying the decoded `code` (a member of the generated twelve-value `Code` enum; a code outside it fails validation and becomes a plain `SagaCommandTransportError` with no `code` — `design.md` §9.3 / L18, task 4.4; corrected by the leader from review round 1 Q5), so the classification is one pure function away. **The terminal set and the short-circuit are not built**: every `RpcError` is retryable here | #7 and #8 both shipped 16 with the un-split shape and closed it in 42 (#7 `progress/history.md` line 1091; #8 `progress/history.md` lines 872 – 913). Building the split here would empty feature 42 and make its effort row incomparable with both predecessors' rows, which is the benchmark this repository exists for. Python forces no difference |
| 2. a retryable transport failure (timeout, no responder) is still retried | **Yes, fully.** Timeout and no-responders are two distinct error types (SO4, `design.md` §9.2), and both, plus every SO15 defect, are retried and parked | It is this feature's SO4 / SO15. Feature 42 must keep it green and arm it against the split it adds |
| 3. a row receiving a terminal `RpcError` reaches a resolved end state | **No.** What is left in place for it: `saga_commands.status` is `varchar(10)` (`rejected` is 8 characters, `models.py:199`, no migration); the ledger's status writes are in one module (`infrastructure/saga/command_ledger.py`) with a closed status set; the sweeper's claim predicate names its statuses explicitly, so a fourth status is excluded unless added | Same reason as item 1 |

## 6. Promotion candidates — gate point G3, not applied

`specs/shared/` is read-only and this feature proposes **no `SA-6`**. Two candidates were raised by #7 and carried by #8 (#8 `requirements.md` §4): (a) commit-before-issue as a normative sentence in `saga.md` §6, and (b) naming a durable medium for `R25`'s "record the fact as ignored". #8 wrote *"worth promoting on #9's pass"* about (b), which hands the decision to this gate; the recommendation and its evidence are `design.md` §17 G3 (recommendation: close both without amendment).

## 7. What this feature changes outside its own directory

Listed per file in `tasks.md`'s file list (derived from `design.md` §2, §12, §13). In summary: `services/orders/src/otc_orders/{application,infrastructure,presentation}/**` and feature 15's `composition.py`; Orders tests; the root `conftest.py` (two more fact topics); three architecture guards (one new); `.env.example` (`SAGA_*`); `specs/shared/test-matrix.md` column 5 of R19 – R29 and the derived counts. **No migration, no new package, no change under `domain/`, `alembic/`, `packages/`**.
