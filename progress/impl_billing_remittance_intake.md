# Feature 22 `billing_remittance_intake` — implementation record

Classification: **full group** (money domain, saga facts, persistence). `sdd: false`: the design is the seam features 19 and 21 cut (`specs/billing_invoicing/design.md` §15.1, `specs/billing_credit/design.md` §15.3). Status set to `in_review`.

## 0. Result

`billing.payment.register` is built end to end and the order-to-cash cycle closes for the first time in #9: a live remittance moved `ORD-000008` and `ORD-000010` from `invoiced` to `completed` through Orders, with no change under `services/orders`. `./quality.sh`: baseline **exit 0, 387 s, 3415 passed**; final **exit 0, 423 s, 3492 passed (+77)**, coverage 97.47% (gate 60%). 83 mutations (arms) were run, each killed by a named test; two survived the first round and were fixed (§7.2).

Things the leader or reviewer must decide or know (details in §12): (1) a payment whose credit release has nothing outstanding is **refused** (`credit.not_outstanding`), not accepted-and-stranded (#8's N3); (2) a reference reused with **another amount or currency** is `PAYMENT_REFERENCE_REUSED`'s refusal, not a `duplicate` (`openapi.yaml` 673 says so; #7 and #8 compared the invoice only); (3) the three R49 refusals answer `INVOICE_NOT_PAYABLE` / `PAYMENT_MISMATCH` as the brief and design §15.1 require, where #7 and #8 (who agree with each other) answered `PRECONDITION_FAILED`; (4) the payment fact's `correlationId` is whatever `x-correlation-id` the caller sends, so the Gateway (feature 25/31) must send the ORDER id; (5) no `issued` invoice was left to show `PAYMENT_MISMATCH` live (proven in integration only).

## 1. Baseline

`./quality.sh` with only `otcpy-n8n` running (`docker ps` before: `otcpy-n8n Up 24 hours (unhealthy)`): **exit 0, 387 s, 3415 pytest passed**, web 1 file / 1 test, "quality.sh: all gates passed".
`git status --porcelain services/orders` before any edit: ` M services/orders/src/otc_orders/infrastructure/settings.py`, ` M services/orders/tests/unit/test_orders_settings_env.py` (feature 19's two settings files). After everything (including the live run): the same two lines and nothing else.

## 2. What was built

| Layer | File | Change |
|---|---|---|
| domain | `domain/invoice_snapshot.py` | `PaymentSnapshot` (a stored remittance as business values) |
| application | `application/payment_register.py` (new) | the transactional unit |
| application | `application/messages.py`, `errors.py`, `handlers.py`, `ports/invoice_store.py` | `RegisterPaymentCommand` / `PaymentRegisterResult` / `PaymentOutcome`; `InvoiceNotFoundError`, `PaymentReferenceReusedError`, `CreditNotOutstandingError`; `RegisterPaymentHandler`; `InvoiceRepository` gains `find_by_id`, `find_payment_by_reference`, `mark_paid`, `InvoiceReads` gains `find_by_id`, `find_by_invoice_reference`, `find_payment_by_reference` |
| infrastructure | `persistence/invoice_repository.py`, `invoice_mapper.py`, `invoice_reads.py`, `messaging/subjects.py` | `mark_paid` = the service's first and only `UPDATE` (`WHERE id = :id AND status = 'issued'`), the `payments` INSERT, the invoice's outbox rows; `23505` on `uq_payments_payment_reference` becomes `PaymentReferenceReusedError`; mapper and reads |
| presentation | `payment_wire.py` (new), `credit_responder.py`, `credit_rpc_errors.py` | decoder (valueDate cut to the millisecond with `wire_instant`), reply, route entry **without a rename**, error mapping |
| root | `composition.py` | one `register_command` statement |

No migration, no setting, no package. Outbox copies, `models.py`, `range_guards.py`, `types.py`, `sequences.py`, `clock` untouched (bounds). Test files: new `unit/test_payment_register_service.py` (27), `unit/test_payment_wire.py` (13), `unit/test_no_internal_payment_timer.py` (5), `integration/test_payment_register.py` (11), `test_payment_register_race.py` (3), `test_payment_register_broker.py` (1), `test_invoice_payment_repository.py` (6); extended `unit/test_credit_responder.py`, `test_credit_rpc_errors.py`, `test_credit_subjects.py`, `test_credit_hold_service.py`, `test_credit_release_service.py`, `test_invoice_issue_service.py` (the last three only gained fake methods the grown ports require), `integration/conftest.py` (`make_world`, `Db.payments_of/invoice_row/connect/hold_invoice`, `Decode.payment_register`), `integration/test_billing_host_lifespan.py`; `tests/architecture/test_write_path_population.py`, `test_billing_rpc_error_retryability.py`, `test_registration_behaviour.py` (their literals only); `specs/shared/test-matrix.md` R47 - R49 and the derived counts.

The sequence (`payment_register.register`): R48 fast path outside any transaction -> resolve the invoice UNLOCKED -> ONE clock read -> `run(work)`: (1) `lock_for_order` (the credits row, BI8's first lock) (2) `invoices.find_by_id`, the plain re-read after the lock (3) `invoices.find_payment_by_reference`, the authority dedup under the lock (4) `Invoice.mark_paid` -> `PaymentReceived` (5) `credit.release(INVOICE_PAID, CreditContext(causation_id = fact.event_id))` (6) `invoices.mark_paid` (UPDATE, INSERT, outbox row 1) (7) `credits.save` (release entry, outbox row 2).

## 3. Requirement to test map

| R | Proof | Test (all under `services/billing/tests/` unless a path says otherwise) |
|---|---|---|
| R47 | integration, real host, real NATS + PostgreSQL | `integration/test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction`; `::test_r47_the_invoice_can_be_named_by_its_reference_alone` |
| R47 | broker read-back (ordering, partition, key, causation) | `integration/test_payment_register_broker.py::test_r47_the_payment_fact_then_the_release_fact_reach_the_broker_in_order_keyed_by_the_order_id` |
| R47 / BI8 / id 57 | unit, ordered call log, ids, clock | `unit/test_payment_register_service.py::test_r47_bi8_resolves_unlocked_then_locks_credits_then_re_reads_then_updates`, `::test_r47_the_reply_is_accepted_with_the_paid_invoice_and_the_one_clock_read`, `::test_r47_payment_received_then_credit_released_with_the_net_amounts`, `::test_id57_the_release_is_caused_by_the_payment_fact_not_by_the_request`, `::test_bi34_the_ids_come_from_the_scope_port_in_the_order_the_units_mint_them` |
| R47 persistence | UPDATE touches only three columns, INSERT, fact | `integration/test_invoice_payment_repository.py::test_r47_mark_paid_updates_only_status_paid_at_and_updated_at_and_inserts_the_payment_and_the_fact` |
| BI8 | held lock + `FOR UPDATE NOWAIT` probe + re-read | `integration/test_payment_register_race.py::test_bi8_the_request_waits_for_the_credits_row_without_the_invoice_row_and_re_reads_after_it` |
| R48 | sequential repeat (by id and by reference), reuse for another invoice, reuse for another amount | `integration/test_payment_register.py::test_r48_a_repeated_reference_answers_the_original_outcome_and_writes_nothing`, `::test_r48_a_reference_reused_for_another_invoice_is_refused_and_writes_nothing`, `::test_r48_a_reference_reused_for_another_amount_is_refused_not_answered_duplicate` |
| R48 | two concurrent registrations; UNIQUE backstop across credit lines | `integration/test_payment_register_race.py::test_r48_two_concurrent_registrations_of_one_reference_yield_one_payment_and_one_fact_pair`, `::test_r48_a_reference_stored_by_a_competitor_on_another_credit_line_is_reused_not_internal_error`; `integration/test_invoice_payment_repository.py::test_r48_the_unique_constraint_on_the_payment_reference_is_the_reused_reference_refusal`, `::test_r48_the_reads_return_the_stored_payment_and_invoice_through_the_mapper`, `::test_r48_a_stored_payment_carries_its_own_currency_not_a_default` |
| R48 unit | fast path, under-lock dedup, reuse variants | `unit/test_payment_register_service.py::test_r48_*` (6 tests, 4 parametrised) |
| R49 | amount (3 wrong values), currency, second reference vs a paid invoice, each against a PRE-ATTEMPT baseline | `integration/test_payment_register.py::test_r49_a_mismatched_amount_is_rejected_with_nothing_changed`, `::test_r49_a_mismatched_currency_is_rejected_with_nothing_changed`, `::test_r49_a_second_reference_against_a_paid_invoice_is_rejected_with_nothing_changed`; unit `unit/test_payment_register_service.py::test_r49_*` |
| R49 codes | each refusal's `RpcError` code is tabulated and terminal | `tests/architecture/test_billing_rpc_error_retryability.py::test_r49_every_payment_refusal_is_answered_with_its_tabulated_terminal_code`, `::test_bc27_no_input_produces_conflict`; `unit/test_credit_rpc_errors.py::test_each_row_of_the_mapping_answers_its_code_and_details` |
| #8 N3 | release `None` is refused, nothing written | `unit/test_payment_register_service.py::test_n3_a_release_with_nothing_outstanding_refuses_the_payment_and_saves_nothing`; `integration/test_payment_register.py::test_n3_a_payment_for_an_order_whose_exposure_is_not_outstanding_is_refused_and_writes_nothing` |
| acceptance 2 | no internal payment timer (absence, with sentinels) | `unit/test_no_internal_payment_timer.py` (5 tests) |
| acceptance 4 | cycle closes, nothing under `services/orders` | §1 enumeration + §9 live |
| edge | wire, headers, registration, subjects | `unit/test_payment_wire.py`, `unit/test_credit_responder.py::test_r47_billing_payment_register_*`, `unit/test_credit_subjects.py`, `integration/test_billing_host_lifespan.py` (registry cases), `tests/architecture/test_registration_behaviour.py`, `test_write_path_population.py` |

R48 and R49 are API-level rows in `test-matrix.md` §6: their unit and integration halves are 22's and are DONE; each row's API half (`api/payment-idempotency.spec`, `api/payment-rejection.spec`) is named TODO for feature 31 `api_tests` (the route is feature 25), as #8's feature 31 did. R47 is an integration row and is DONE. Counts: `billing_invoicing` 2/0/3 -> 3/0/2, total 41/1/21 -> 42/1/20 (derived from column 5 one row at a time).

## 4. Fixtures: the plausible wrong values and why the expected value differs from each

- **Non-zero discount, payment = the NET.** gross 8465 = 3 x 1999 + 2 x 1234, discount 350, net 8115 (the integration `make_world` is built by the real `credit.hold` + `invoice.issue` through `issue_body`, which REFUSES a fixture whose three figures are not pairwise distinct, non-zero and substring-free). A payment of the gross (8465) is the R49 mismatch; net minus one (8114) and plus one (8116) are the other two wrong amounts; subtracting the discount twice is 7765.
- **Available credit differs from the limit and the pre-payment value.** limit 250 000, ANOTHER order holds 20 021: available 221 864 before, **229 979 after**; neither is the limit, the gross, the net, nor the 120 000 of an unrelated line. Live: limit 500 000, ORD-000007 holds 55 545: 285 993 before ORD-000010's payment, 344 459 after it, 444 455 after ORD-000008's.
- **Counts against baselines.** Every R48 / R49 / N3 assertion compares `state_of()` (table counts, the invoice row, the order's ledger) to its pre-attempt capture; the order's own hold and consume rows exist (`credit_items` baseline 3, never 0).
- **Identifiers pairwise different:** order id (correlation), request id, invoice id, credit line id (integration asserts four distinct UUIDs); in the unit rig `0xC0`, `0xD0`, `0x5001`, `0x1D`, `0xB1`.
- **The identity case cannot be satisfied by the amounts differing** (round-1 survivor, §7.2): `make_world(second=True, same_total=True)` gives the other invoice the same net 8115 from another gross (9321) and discount (1206).
- **`valueDate` carries microseconds and an offset** in the wire test (`.123987+02:00`): the stored column, the fact and the request must be the same millisecond (`wire_instant`), not rounded by `timestamptz(3)` (#8's N2).

## 5. The `RpcError` codes `billing.payment.register` answers (tabulated; a retry-or-reject decision each)

| Refusal | Error (code) | `RpcError` code | Gateway later maps it to (`openapi.yaml` 673 - 675) | Orders' saga adapter / caller retries? |
|---|---|---|---|---|
| malformed request or headers | `InvalidPaymentRequestError`, `InvalidCreditHeadersError` | `VALIDATION_FAILED` | 400 | no (terminal) |
| unknown invoice (or id and reference disagree) | `InvoiceNotFoundError` (`invoice.not_found`) | `NOT_FOUND` | 404 | no |
| already `paid`, another reference | `InvoiceAlreadyPaidError` (`invoice.already_paid`) | **`INVOICE_NOT_PAYABLE`** | 409 `INVOICE_ALREADY_PAID` | no |
| amount differs | `InvoicePaymentAmountMismatchError` (`invoice.payment_amount_mismatch`) | **`PAYMENT_MISMATCH`** | 422 `PAYMENT_MISMATCH` | no |
| currency differs | `InvoicePaymentCurrencyMismatchError` (`invoice.payment_currency_mismatch`) | **`PAYMENT_MISMATCH`** | 422 `PAYMENT_MISMATCH` | no |
| reference reused (other invoice / other amount or currency) | `PaymentReferenceReusedError` (`payment.reference_reused`) | `PRECONDITION_FAILED` | 409 `PAYMENT_REFERENCE_REUSED` | no |
| no outstanding exposure to release | `CreditNotOutstandingError` (`credit.not_outstanding`) | `PRECONDITION_FAILED` | 409 | no |
| deadlock victim, lost connection, lock timeout | `StoreUnavailableError` | `UNAVAILABLE` | 503 | **yes** |
| anything unclassified | any other exception (never the text) | `INTERNAL_ERROR` | 500 | **yes** |

Every `details` keeps `code` (so a #7-style Gateway that maps by `details.code` also works). `CONFLICT` is produced by no input (feature 19's `BC27`, asserted by `test_bc27_no_input_produces_conflict`, whose population grew from 24 to 27 `DomainError` subclasses). All seven non-retried codes are in Orders' `TERMINAL_RPC_ERROR_CODES` (`services/orders/src/otc_orders/infrastructure/messaging/nats_saga_commands.py:65-77`), read by the tests from that set, never retyped.

Decision record. The brief and design §15.1 (corrected by the premise check) name `INVOICE_NOT_PAYABLE` and `PAYMENT_MISMATCH` (`asyncapi.yaml:2856-2857`, the `RpcError` vocabulary of the shared contract) as the codes. **#7 and #8 agree with each other on something else**: all three of already-paid, amount mismatch and currency mismatch answer `PRECONDITION_FAILED` with `details.code` (#7 `apps/billing/src/presentation/rpc-error-mapper.ts:108-120`; #8 `src/Billing/Presentation/Rpc/BillingErrorMapper.cs:89-105`, both under the comment "feature 22 will map these"). The shared vocabulary has the two codes precisely for this subject and both are terminal, so following the brief costs nothing in saga behaviour; recorded as a divergence for the reviewer. For a reference reused: #7 `CONFLICT` (`rpc-error-mapper.ts:138-143`), #8 `PRECONDITION_FAILED` (`BillingErrorMapper.cs:145`, "deliberately never CONFLICT", `BC27`); #9 follows #8 because Billing answers no `CONFLICT` (feature 19 `BC27`, design 8.5).

## 6. "No internal payment timer anywhere" (acceptance 2): an absence claim, answered by search

Population: every Python source of `services/*/src` and `packages/*/src` (`generated/` excluded at the source: it is the contract's channel table), and every n8n workflow. Commands and full output (run in this session):

```text
$ grep -rnE "payment\.register|PAYMENT_REGISTER|RegisterPaymentCommand|register_payment|\.mark_paid\(" services/*/src packages/*/src n8n/workflows | grep -v "/generated/"
services/orders/src/otc_orders/application/saga/step_table.py:104:    order.mark_paid(occurred_at=fact.occurred_at)
services/seed/src/otc_seed/domain/data/sagas.py:11:(`order:<seq>:command:orders.create` / `order:<seq>:command:payment.register`), and every other fact
services/seed/src/otc_seed/domain/data/sagas.py:413:    payment_received_causation_id = deterministic_id(f"order:{sequence}:command:payment.register")
(hits under services/billing/ are classified in the call-site table, section 8: 28 lines, all Billing's own responder/handler/registration/decoder)

$ grep -rnE "asyncio\.sleep|call_later|call_at|threading\.Timer|apscheduler|aiocron|croniter|schedule\.every" services/*/src packages/*/src | grep -v /generated/
services/billing/src/otc_billing/infrastructure/outbox/relay.py:135:                await asyncio.sleep(DEADLOCK_BACKOFF_SECONDS)
services/fulfillment/src/otc_fulfillment/infrastructure/outbox/relay.py:135:                await asyncio.sleep(DEADLOCK_BACKOFF_SECONDS)
services/orders/src/otc_orders/infrastructure/outbox/relay.py:150:                await asyncio.sleep(DEADLOCK_BACKOFF_SECONDS)
services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py:104:        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
services/orders/src/otc_orders/infrastructure/saga/command_dispatcher.py:72:        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,

$ n8n trigger node types per workflow
1-order-generator.json ['n8n-nodes-base.scheduleTrigger']
2-payment-robot.json ['n8n-nodes-base.scheduleTrigger']
3-stock-replenishment.json ['n8n-nodes-base.scheduleTrigger']
4-burst.json ['n8n-nodes-base.webhook']
$ grep -l "/payments" n8n/workflows/*.json
n8n/workflows/2-payment-robot.json
$ grep -il "nats\|billing.payment" n8n/workflows/*.json
(exit 1 : no workflow names NATS or Billing's subject)
```

Classification, one per hit:

- `services/orders/.../step_table.py:104` `order.mark_paid(...)`: the ORDER aggregate's transition applied when the FACT `payment.received.v1` is consumed; a consumer, not a sender.
- `services/seed/.../sagas.py:11` and `:413`: a docstring and `deterministic_id("order:<seq>:command:payment.register")`, the seed deriving ids for historic fixture sagas; sends nothing at runtime.
- `asyncio.sleep` at `billing|fulfillment|orders .../outbox/relay.py` (3): the relay copies' DEADLOCK back-off; `fulfillment .../stock_transactions.py:104` and `orders .../command_dispatcher.py:72`: injectable `sleep` defaults pacing a RETRY of a stock transaction and of a saga command. None decides a payment; `payment.register` is not a saga command (`saga.md` §2: caller Gateway).
- n8n: `1-order-generator`, `2-payment-robot`, `3-stock-replenishment` are schedule-triggered, `4-burst` a webhook. Only `2-payment-robot` mentions `/payments`; it posts to the Gateway over HTTP (`OTC_GATEWAY_URL`), and no workflow names NATS or Billing's subject. The robot is the EXTERNAL bank, not a timer inside the system (`n8n-workflows.md` §4).

It is a guard, `unit/test_no_internal_payment_timer.py`, with the expected populations as literals and a **sentinel** (`test_the_search_catches_a_planted_timer_a_planted_caller_and_a_planted_schedule`): a scratch tree with a planted `asyncio.sleep` + `billing.payment.register` + `RegisterPaymentCommand(` under `services/orders/src`, a `generated/` decoy that must NOT be counted, and a planted schedule-triggered workflow; each claim's instrument must see its plant. Defeat-list rows applied: 4 (a pattern shadowed in a comment/string is counted, hence classified, never excluded), 10 (`__pycache__` and `generated/` excluded at the source), 11 (a syntax guard that loses is replaced by classification of every hit), 12 (a path the population never drives: the n8n side is read separately).

## 7. Arming

Protocol: `.arm/bc22/arm.py` (copy of the repo-local tool, backups in `.arm/bc22/bak/<arm>/`, `sha256` recorded, ONE named test per arm, the run in its own process group killed on timeout, restore by copy + `cmp`, `__pycache__` and `.mypy_cache` cleared, the test re-run green). Mutations are listed in `.arm/bc22/arms.py`, raw logs in `.arm/bc22/logs/`. **83 arms, all FAILED (armed), all restored (`cmp` identical, sha256 equal, test green again).** After the last arm the sources hash to the same values as before every arm (`sha256sum payment_register.py` = `fc3dcf23...`, `invoice_repository.py` = `d66f5f70...`). Feature 20's N1: every failure arrives in 1 - 14 s as an assertion or named exception; none is only a timeout or a connection error. The failure line is quoted verbatim (trimmed to 200 characters).

### 7.1 sha256 of each mutated source file (identical before every arm that mutated it)

| file | sha256 before every arm that mutated it (identical across arms) |
|---|---|
| `application/payment_register.py` | `fc3dcf232fa16d042268a9774aef19a76bd3434f3220ebf304f71e5c63837f33` |
| `composition.py` | `7e8591fee0951b787df5fa17ec10c6b4bb0c3c301c3add14491381a7e6458674` |
| `infrastructure/persistence/invoice_mapper.py` | `be31fdc0e5c2f9c2d61a8ff461cdcc5e5ba7b6bd2bee4937978a4c2c513a44de` |
| `infrastructure/persistence/invoice_reads.py` | `5c7d98123658c539bd25895f88ff86880f3224bb6ef23880ab4db6bc4ff88c28` |
| `infrastructure/persistence/invoice_repository.py` | `d66f5f7016a30e304a5fadbf071d93e12cc1944d6a28c992e763d13498cff6b3` |
| `presentation/credit_responder.py` | `c3e1b4c97562f48e2635989689777f2c0adfbd5ade33c26eded7a69ca393d0f1` |
| `presentation/credit_rpc_errors.py` | `7b7b369d202577c5aaeed1d3feb68c2f9fa1f901880b6682ce1ef3c85b853791` |
| `presentation/payment_wire.py` | `76cce4e86484e9257badf4c5b2f6c5c86c3f2b4cf72817a2d36b8151fa64d777` |

### 7.2 The two arms that survived round one, and the fix

- `C4-identity-not-compared` (drop `or not _identity_matches(command, invoice)` in `_duplicate`) survived `test_r48_a_reference_reused_for_another_invoice_is_refused_and_writes_nothing`: the second world's net (8910) differed from the first's (8115), so the amount clause refused anyway (a fixture satisfying the relation by accident). Fix: `make_world(second=True, same_total=True)` (same net, other gross and discount) plus the unit case `[changes0-another invoice id]`; re-armed: killed by both (`C4`, `C4c`). Log of the first round kept: `.arm/bc22/logs/C4-first-round-SURVIVED.log`.
- `G13-payment-snapshot-currency-corrupt` (mapper reads the currency as `'EUR'`) survived the read test because every fixture was EUR. Fix: `test_r48_a_stored_payment_carries_its_own_currency_not_a_default` (a USD invoice and payment); re-armed and killed. First round: `.arm/bc22/logs/G13-first-round-SURVIVED.log`.

### 7.3 The arming table

| # | arm | mutation (file: old → new) | killing test | verbatim failure message (first assertion line) | cmp identical / sha256 equal / restored green |
|---|---|---|---|---|---|
| 1 | A1-swap-emissions | `application/payment_register.py`: `    await tx.credits.save(credit)  # 7. outbox row 2: credit.released.…` → ``; `application/payment_register.py`: `    await tx.invoices.mark_paid(  # 6. outbox row 1: payment.received.…` → `    await tx.credits.save(credit)⏎    await tx.invoices.mark_paid(  # …` | `test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` | `AssertionError: R47: expected payment.received.v1 then credit.released.v1 in seq order, got ['credit.released.v1', 'payment.received.v1']` | yes / yes / yes |
| 2 | A1b-swap-emissions-unit | `application/payment_register.py`: `    await tx.credits.save(credit)  # 7. outbox row 2: credit.released.…` → ``; `application/payment_register.py`: `    await tx.invoices.mark_paid(  # 6. outbox row 1: payment.received.…` → `    await tx.credits.save(credit)⏎    await tx.invoices.mark_paid(  # …` | `test_payment_register_service.py::test_r47_bi8_resolves_unlocked_then_locks_credits_then_re_reads_then_updates` | `AssertionError: BI8 / R47: the calls are not lock the credits row, re-read, dedup, update, save credit` | yes / yes / yes |
| 3 | A2-release-caused-by-the-request | `application/payment_register.py`: `causation_id=fact.event_id` → `causation_id=command.request_id` | `test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` | `AssertionError: #8 id 57: credit.released.v1's causationId is not payment.received.v1's eventId` | yes / yes / yes |
| 4 | A2b-release-caused-by-the-request-unit | `application/payment_register.py`: `causation_id=fact.event_id` → `causation_id=command.request_id` | `test_payment_register_service.py::test_id57_the_release_is_caused_by_the_payment_fact_not_by_the_request` | `AssertionError: #8 id 57: credit.released.v1's causationId is not payment.received.v1's eventId` | yes / yes / yes |
| 5 | A2c-release-caused-by-the-request-broker | `application/payment_register.py`: `causation_id=fact.event_id` → `causation_id=command.request_id` | `test_payment_register_broker.py::test_r47_the_payment_fact_then_the_release_fact_reach_the_broker_in_order_keyed_by_the_order_id` | `AssertionError: #8 id 57: the broker's credit.released.v1 is not caused by payment.received.v1` | yes / yes / yes |
| 6 | A3-commit-invoice-without-the-release | `application/payment_register.py`: `    await tx.credits.save(credit)  # 7. outbox row 2: credit.released.…` → `` | `test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` | `AssertionError: R47: expected payment.received.v1 then credit.released.v1 in seq order, got ['payment.received.v1']` | yes / yes / yes |
| 7 | A3b-commit-invoice-without-the-release-unit | `application/payment_register.py`: `    await tx.credits.save(credit)  # 7. outbox row 2: credit.released.…` → `` | `test_payment_register_service.py::test_r47_bi8_resolves_unlocked_then_locks_credits_then_re_reads_then_updates` | `AssertionError: BI8 / R47: the calls are not lock the credits row, re-read, dedup, update, save credit` | yes / yes / yes |
| 8 | B1-lock-the-invoice-first | `application/payment_register.py`: `    credit = await tx.credits.lock_for_order(  # 1. THE FIRST LOCK` → `    await tx.invoices.find_by_id(target.id)⏎    credit = await tx.cred…`; `infrastructure/persistence/invoice_repository.py`: `select(InvoiceRow).where(InvoiceRow.id == invoice_id.value)` → `select(InvoiceRow).where(InvoiceRow.id == invoice_id.value).with_for_u…` | `test_payment_register_race.py::test_bi8_the_request_waits_for_the_credits_row_without_the_invoice_row_and_re_reads_after_it` | `AssertionError: BI8: the request holds the invoice row while it waits for the credits row (the lock order is inverted)` | yes / yes / yes |
| 9 | B1b-lock-the-invoice-first-unit | `application/payment_register.py`: `    credit = await tx.credits.lock_for_order(  # 1. THE FIRST LOCK` → `    await tx.invoices.find_by_id(target.id)⏎    credit = await tx.cred…` | `test_payment_register_service.py::test_r47_bi8_resolves_unlocked_then_locks_credits_then_re_reads_then_updates` | `AssertionError: BI8 / R47: the calls are not lock the credits row, re-read, dedup, update, save credit` | yes / yes / yes |
| 10 | B2-skip-the-re-read | `application/payment_register.py`: `snapshot = await tx.invoices.find_by_id(target.id)` → `snapshot = target` | `test_payment_register_race.py::test_bi8_the_request_waits_for_the_credits_row_without_the_invoice_row_and_re_reads_after_it` | `AssertionError: BI8: the request acted on the invoice it read BEFORE the credits lock; got {'code': 'UNAVAILABLE', 'message': 'the credit store is temporarily unavailable (the invoice was not issued w` | yes / yes / yes |
| 11 | B2b-skip-the-re-read-unit | `application/payment_register.py`: `snapshot = await tx.invoices.find_by_id(target.id)` → `snapshot = target` | `test_payment_register_service.py::test_bi8_the_decision_uses_the_re_read_after_the_lock_not_the_pre_lock_snapshot` | `Failed: DID NOT RAISE InvoiceAlreadyPaidError` | yes / yes / yes |
| 12 | B3-lock-args-swapped-unit | `application/payment_register.py`: `        target.retailer_code, target.company_code, target.order_refere…` → `        target.company_code, target.retailer_code, target.order_refere…` | `test_payment_register_service.py::test_r47_bi8_resolves_unlocked_then_locks_credits_then_re_reads_then_updates` | `AssertionError: assert [('SUPPLY-CO'...'ORD-000101')] == [('RETAIL-77'...'ORD-000101')]` | yes / yes / yes |
| 13 | B4-re-read-wrong-id-unit | `application/payment_register.py`: `tx.invoices.find_by_id(target.id)` → `tx.invoices.find_by_id(command.request_id)` | `test_payment_register_service.py::test_r47_bi8_resolves_unlocked_then_locks_credits_then_re_reads_then_updates` | `AssertionError: assert [UniqueId(val...00000000d0'))] == [UniqueId(val...0000005001'))]` | yes / yes / yes |
| 14 | B5-guard-on-the-update-removed | `infrastructure/persistence/invoice_repository.py`: `InvoiceRow.id == invoice.id.value, InvoiceRow.status == "issued"` → `InvoiceRow.id == invoice.id.value` | `test_invoice_payment_repository.py::test_mark_paid_on_an_invoice_that_is_not_issued_is_a_transient_failure_and_writes_nothing` | `Failed: DID NOT RAISE StoreUnavailableError` | yes / yes / yes |
| 15 | C1-no-fast-path | `application/payment_register.py`: `    if stored is not None:  # R48: a repeat is routine; no transaction…` → `    if stored is not None and False:` | `test_payment_register_service.py::test_r48_a_stored_reference_answers_duplicate_on_the_fast_path_with_no_transaction` | `AssertionError: R48: a fast-path hit opened a transaction` | yes / yes / yes |
| 16 | C2-no-dedup-under-the-lock | `application/payment_register.py`: `    if stored is not None:⏎        return _duplicate(command, snapshot…` → `    if False:⏎        return _duplicate(command, snapshot, stored)` | `test_payment_register_race.py::test_r48_two_concurrent_registrations_of_one_reference_yield_one_payment_and_one_fact_pair` | `AssertionError: BC32: expected a payment reply (an `outcome`), got {'code': 'INVOICE_NOT_PAYABLE', 'message': 'Invoice INV-000001 is already paid.', 'details': {'code': 'invoice.already_paid'}, 'corre` | yes / yes / yes |
| 17 | C2b-no-dedup-under-the-lock-unit | `application/payment_register.py`: `    if stored is not None:⏎        return _duplicate(command, snapshot…` → `    if False:⏎        return _duplicate(command, snapshot, stored)` | `test_payment_register_service.py::test_r48_a_reference_stored_by_a_competitor_under_the_lock_answers_duplicate` | `otc_billing.domain.invoice_errors.InvoiceAlreadyPaidError: Invoice INV-000042 is already paid.` | yes / yes / yes |
| 18 | C3-amount-not-compared | `application/payment_register.py`: `        or payment.amount != command.amount⏎` → `` | `test_payment_register.py::test_r48_a_reference_reused_for_another_amount_is_refused_not_answered_duplicate` | `AssertionError: BC32: expected an RpcError (a `code`), got {'outcome': 'duplicate', 'paymentReference': 'BANK-REF-7731', 'invoiceReference': 'INV-000001', 'orderReference': 'ORD-000101', 'invoiceStatu` | yes / yes / yes |
| 19 | C3b-amount-not-compared-unit | `application/payment_register.py`: `        or payment.amount != command.amount⏎` → `` | `test_payment_register_service.py::test_r48_a_stored_reference_used_to_mean_something_else_is_reused_not_a_duplicate` | `Failed: DID NOT RAISE PaymentReferenceReusedError` | yes / yes / yes |
| 20 | C4-identity-not-compared | `application/payment_register.py`: `        or not _identity_matches(command, invoice)⏎` → `` | `test_payment_register.py::test_r48_a_reference_reused_for_another_invoice_is_refused_and_writes_nothing` | `AssertionError: BC32: expected an RpcError (a `code`), got {'outcome': 'duplicate', 'paymentReference': 'BANK-REF-7731', 'invoiceReference': 'INV-000001', 'orderReference': 'ORD-000101', 'invoiceStatu` | yes / yes / yes |
| 21 | C4c-identity-not-compared-unit | `application/payment_register.py`: `        or not _identity_matches(command, invoice)⏎` → `` | `test_payment_register_service.py::test_r48_a_stored_reference_used_to_mean_something_else_is_reused_not_a_duplicate[changes0-another invoice id]` | `Failed: DID NOT RAISE PaymentReferenceReusedError` | yes / yes / yes |
| 22 | C4b-stored-payments-invoice-not-compared-unit | `application/payment_register.py`: `        payment.invoice_id != invoice.id⏎        or not` → `        not` | `test_payment_register_service.py::test_r48_a_reference_stored_for_another_invoice_under_the_lock_is_reused` | `Failed: DID NOT RAISE PaymentReferenceReusedError` | yes / yes / yes |
| 23 | C5-unique-violation-not-mapped | `infrastructure/persistence/invoice_repository.py`: `                raise PaymentReferenceReusedError(payment.payment_refe…` → `                raise` | `test_payment_register_race.py::test_r48_a_reference_stored_by_a_competitor_on_another_credit_line_is_reused_not_internal_error` | `AssertionError: R48: the UNIQUE backstop surfaced as {'code': 'INTERNAL_ERROR', 'message': 'The request could not be processed.', 'correlationId': 'ecf2582b-a4d6-4f6f-ab4d-9a2c885dc3a8', 'occurredAt':` | yes / yes / yes |
| 24 | C5b-unique-violation-not-mapped-repo | `infrastructure/persistence/invoice_repository.py`: `                raise PaymentReferenceReusedError(payment.payment_refe…` → `                raise` | `test_invoice_payment_repository.py::test_r48_the_unique_constraint_on_the_payment_reference_is_the_reused_reference_refusal` | `asyncpg.exceptions.UniqueViolationError: duplicate key value violates unique constraint "uq_payments_payment_reference"` | yes / yes / yes |
| 25 | C6-fast-path-arg-unit | `application/payment_register.py`: `find_payment_by_reference(command.payment_reference)⏎    if stored is …` → `find_payment_by_reference(command.invoice_reference or '')⏎    if stor…` | `test_payment_register_service.py::test_r47_bi8_resolves_unlocked_then_locks_credits_then_re_reads_then_updates` | `AssertionError: the fast path then the identity resolution, both outside the transaction` | yes / yes / yes |
| 26 | C7-lock-dedup-arg-unit | `application/payment_register.py`: `tx.invoices.find_payment_by_reference(command.payment_reference)` → `tx.invoices.find_payment_by_reference(command.invoice_reference or '')` | `test_payment_register_service.py::test_r47_bi8_resolves_unlocked_then_locks_credits_then_re_reads_then_updates` | `AssertionError: assert [''] == ['BANK-REF-7731']` | yes / yes / yes |
| 27 | D1-payment-amount-is-the-invoice-total | `application/payment_register.py`: `            amount=command.amount,⏎            value_date=command.valu…` → `            amount=snapshot.total_amount,⏎            value_date=comma…` | `test_payment_register.py::test_r49_a_mismatched_amount_is_rejected_with_nothing_changed` | `AssertionError: BC32: expected an RpcError (a `code`), got {'outcome': 'accepted', 'paymentReference': 'BANK-WRONG-8465', 'invoiceReference': 'INV-000001', 'orderReference': 'ORD-000101', 'invoiceStat` | yes / yes / yes |
| 28 | D1b-payment-amount-is-the-invoice-total-unit | `application/payment_register.py`: `            amount=command.amount,⏎            value_date=command.valu…` → `            amount=snapshot.total_amount,⏎            value_date=comma…` | `test_payment_register_service.py::test_r49_a_mismatched_amount_changes_nothing` | `Failed: DID NOT RAISE InvoicePaymentAmountMismatchError` | yes / yes / yes |
| 29 | D2-payment-currency-is-the-invoice-currency | `application/payment_register.py`: `            amount=command.amount,⏎            value_date=command.valu…` → `            amount=Money(command.amount.amount, snapshot.currency),⏎  …`; `application/payment_register.py`: `from otc_shared_kernel import UniqueId⏎` → `from otc_shared_kernel import Money, UniqueId⏎` | `test_payment_register.py::test_r49_a_mismatched_currency_is_rejected_with_nothing_changed` | `AssertionError: BC32: expected an RpcError (a `code`), got {'outcome': 'accepted', 'paymentReference': 'BANK-REF-7731', 'invoiceReference': 'INV-000001', 'orderReference': 'ORD-000101', 'invoiceStatus` | yes / yes / yes |
| 30 | D3-already-paid-not-refused | `application/payment_register.py`: `    invoice = Invoice.rehydrate(snapshot)⏎` → `    invoice = Invoice.rehydrate(replace(snapshot, state=Issued()))⏎`; `application/payment_register.py`: `from functools import partial⏎` → `from dataclasses import replace⏎from functools import partial⏎⏎from ot…` | `test_payment_register.py::test_r49_a_second_reference_against_a_paid_invoice_is_rejected_with_nothing_changed` | `AssertionError: assert 'PRECONDITION_FAILED' == 'INVOICE_NOT_PAYABLE'` | yes / yes / yes |
| 31 | D4-n3-none-discarded | `application/payment_register.py`: `    if released is None:⏎        raise CreditNotOutstandingError(invoi…` → `` | `test_payment_register.py::test_n3_a_payment_for_an_order_whose_exposure_is_not_outstanding_is_refused_and_writes_nothing` | `AssertionError: BC32: expected an RpcError (a `code`), got {'outcome': 'accepted', 'paymentReference': 'BANK-REF-7731', 'invoiceReference': 'INV-000001', 'orderReference': 'ORD-000101', 'invoiceStatus` | yes / yes / yes |
| 32 | D4b-n3-none-discarded-unit | `application/payment_register.py`: `    if released is None:⏎        raise CreditNotOutstandingError(invoi…` → `` | `test_payment_register_service.py::test_n3_a_release_with_nothing_outstanding_refuses_the_payment_and_saves_nothing` | `Failed: DID NOT RAISE CreditNotOutstandingError` | yes / yes / yes |
| 33 | E1-fact-valuedate | `application/payment_register.py`: `            value_date=command.value_date,⏎            source=command.…` → `            value_date=invoice_context.occurred_at,⏎            source…` | `test_payment_register_service.py::test_r47_payment_received_then_credit_released_with_the_net_amounts` | `AssertionError: assert ('BANK-REF-77...BOT: 'robot'>) == ('BANK-REF-77...BOT: 'robot'>)` | yes / yes / yes |
| 34 | E2-fact-source | `application/payment_register.py`: `            value_date=command.value_date,⏎            source=command.…` → `            value_date=command.value_date,⏎            source=PaymentS…`; `application/payment_register.py`: `from otc_billing.domain.invoice import Invoice, InvoiceContext, Paymen…` → `from otc_billing.domain.invoice import Invoice, InvoiceContext, Paymen…` | `test_payment_register_service.py::test_r47_payment_received_then_credit_released_with_the_net_amounts` | `AssertionError: assert ('BANK-REF-77...TEST: 'test'>) == ('BANK-REF-77...BOT: 'robot'>)` | yes / yes / yes |
| 35 | E3-fact-reference | `application/payment_register.py`: `            payment_reference=command.payment_reference,⏎            a…` → `            payment_reference=command.invoice_reference or 'X',⏎      …` | `test_payment_register_service.py::test_r47_payment_received_then_credit_released_with_the_net_amounts` | `AssertionError: assert ('X', datetim...BOT: 'robot'>) == ('BANK-REF-77...BOT: 'robot'>)` | yes / yes / yes |
| 36 | E4-fact-correlation | `application/payment_register.py`: `            source=command.source,⏎            correlation_id=command.…` → `            source=command.source,⏎            correlation_id=command.…` | `test_payment_register_service.py::test_r47_payment_received_then_credit_released_with_the_net_amounts` | `AssertionError: assert UniqueId(valu...000000000d0')) == UniqueId(valu...000000000c0'))` | yes / yes / yes |
| 37 | E5-row-valuedate | `application/payment_register.py`: `            amount=command.amount,⏎            value_date=command.valu…` → `            amount=command.amount,⏎            value_date=invoice_cont…` | `test_payment_register_service.py::test_r47_the_reply_is_accepted_with_the_paid_invoice_and_the_one_clock_read` | `AssertionError: assert datetime.datetime(2026, 10, 10, 10, 15, 31, 123000, tzinfo=datetime.timezone.utc) == datetime.datetime(2026, 10, 9, 0, 0, tzinfo=datetime.timezone.utc)` | yes / yes / yes |
| 38 | E6-row-source | `application/payment_register.py`: `            value_date=command.value_date,⏎            source=command.…` → `            value_date=command.value_date,⏎            source=PaymentS…`; `application/payment_register.py`: `from otc_billing.domain.invoice import Invoice, InvoiceContext, Paymen…` → `from otc_billing.domain.invoice import Invoice, InvoiceContext, Paymen…` | `test_payment_register_service.py::test_r47_the_reply_is_accepted_with_the_paid_invoice_and_the_one_clock_read` | `AssertionError: assert <PaymentSource.TEST: 'test'> is <PaymentSource.ROBOT: 'robot'>` | yes / yes / yes |
| 39 | E7-row-reference | `application/payment_register.py`: `            id=new_id(),⏎            payment_reference=command.payment…` → `            id=new_id(),⏎            payment_reference=command.invoice…` | `test_payment_register_service.py::test_r47_the_reply_is_accepted_with_the_paid_invoice_and_the_one_clock_read` | `AssertionError: assert 'X' == 'BANK-REF-7731'` | yes / yes / yes |
| 40 | E8-row-amount | `application/payment_register.py`: `            invoice_id=invoice.id,⏎            amount=command.amount,` → `            invoice_id=invoice.id,⏎            amount=Money(command.am…`; `application/payment_register.py`: `from otc_shared_kernel import UniqueId⏎` → `from otc_shared_kernel import Money, UniqueId⏎` | `test_payment_register_service.py::test_r47_the_reply_is_accepted_with_the_paid_invoice_and_the_one_clock_read` | `AssertionError: assert Money(amount=...urrency='EUR') == Money(amount=...urrency='EUR')` | yes / yes / yes |
| 41 | E9-row-invoice-id | `application/payment_register.py`: `            invoice_id=invoice.id,⏎            amount=command.amount,` → `            invoice_id=uid_wrong(),⏎            amount=command.amount,`; `application/payment_register.py`: `def _identity_matches` → `def uid_wrong() -> UniqueId:⏎    return UniqueId.parse('00000000-0000-…` | `test_payment_register_service.py::test_r47_the_reply_is_accepted_with_the_paid_invoice_and_the_one_clock_read` | `AssertionError: assert UniqueId(valu...000000000aa')) == UniqueId(valu...00000005001'))` | yes / yes / yes |
| 42 | E10-release-reason | `application/payment_register.py`: `CreditReleaseReason.INVOICE_PAID` → `CreditReleaseReason.ORDER_CANCELLED` | `test_payment_register_service.py::test_r47_payment_received_then_credit_released_with_the_net_amounts` | `AssertionError: assert <CreditReleaseReason.ORDER_CANCELLED: 'order_cancelled'> is <CreditReleaseReason.INVOICE_PAID: 'invoice_paid'>` | yes / yes / yes |
| 43 | E10b-release-reason-integration | `application/payment_register.py`: `CreditReleaseReason.INVOICE_PAID` → `CreditReleaseReason.ORDER_CANCELLED` | `test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` | `AssertionError: assert {'orderRefere...-000321', ...} == {'orderRefere...-000321', ...}` | yes / yes / yes |
| 44 | E11-release-correlation | `application/payment_register.py`: `        CreditReleaseReason.INVOICE_PAID,⏎        command.correlation_…` → `        CreditReleaseReason.INVOICE_PAID,⏎        command.request_id,` | `test_payment_register_service.py::test_r47_payment_received_then_credit_released_with_the_net_amounts` | `AssertionError: assert UniqueId(valu...000000000d0')) == UniqueId(valu...000000000c0'))` | yes / yes / yes |
| 45 | E12-clock-read-twice | `application/payment_register.py`: `invoice_context=InvoiceContext(occurred_at=now, causation_id=command.r…` → `invoice_context=InvoiceContext(occurred_at=scope.clock.now(), causatio…` | `test_payment_register_service.py::test_r47_the_reply_is_accepted_with_the_paid_invoice_and_the_one_clock_read` | `AssertionError: R47: the clock was read 2 times` | yes / yes / yes |
| 46 | E13-fact-caused-by-the-correlation | `application/payment_register.py`: `invoice_context=InvoiceContext(occurred_at=now, causation_id=command.r…` → `invoice_context=InvoiceContext(occurred_at=now, causation_id=command.c…` | `test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` | `AssertionError: assert 'd507c177-ca7...-bb190ea23636' == 'b7599e1f-cd6...-9893f92dc566'` | yes / yes / yes |
| 47 | E14-reply-outcome-always-accepted-unit | `application/payment_register.py`: `        outcome=PaymentOutcome.DUPLICATE,` → `        outcome=PaymentOutcome.ACCEPTED,` | `test_payment_register_service.py::test_r48_a_stored_reference_answers_duplicate_on_the_fast_path_with_no_transaction` | `AssertionError: assert <PaymentOutcome.ACCEPTED: 'accepted'> is <PaymentOutcome.DUPLICATE: 'duplicate'>` | yes / yes / yes |
| 48 | F1-resolution-ignores-the-id-pair | `application/payment_register.py`: `    if found is None or not _identity_matches(command, found):` → `    if found is None:` | `test_payment_register_service.py::test_an_unknown_invoice_is_not_found_and_opens_no_transaction` | `Failed: DID NOT RAISE InvoiceNotFoundError` | yes / yes / yes |
| 49 | F2-resolution-by-reference-uses-the-id | `application/payment_register.py`: `found = await reads.find_by_invoice_reference(command.invoice_referenc…` → `found = await reads.find_by_id(command.request_id)` | `test_payment_register_service.py::test_r47_the_invoice_is_resolved_by_reference_when_no_id_is_given` | `otc_billing.application.errors.InvoiceNotFoundError: No invoice matches id None and reference 'INV-000042'.` | yes / yes / yes |
| 50 | F3-missing-credit-line-not-refused | `application/payment_register.py`: `    if credit is None:⏎        raise CreditLineNotFoundError(target.re…` → `` | `test_payment_register_service.py::test_a_missing_credit_line_writes_nothing` | `AttributeError: 'NoneType' object has no attribute 'release'` | yes / yes / yes |
| 51 | G1-update-touches-every-issued-invoice | `infrastructure/persistence/invoice_repository.py`: `InvoiceRow.id == invoice.id.value, InvoiceRow.status == "issued"` → `InvoiceRow.status == "issued"` | `test_invoice_payment_repository.py::test_r47_mark_paid_updates_only_status_paid_at_and_updated_at_and_inserts_the_payment_and_the_fact` | `otc_billing.application.ports.credit_store.StoreUnavailableError: the credit store is temporarily unavailable (the invoice was not issued when it was marked paid)` | yes / yes / yes |
| 52 | G2-updated-at-not-moved | `infrastructure/persistence/invoice_repository.py`: `                updated_at=now,⏎` → `` | `test_invoice_payment_repository.py::test_r47_mark_paid_updates_only_status_paid_at_and_updated_at_and_inserts_the_payment_and_the_fact` | `AssertionError: updated_at was not moved` | yes / yes / yes |
| 53 | G3-paid-at-is-the-wall-clock | `infrastructure/persistence/invoice_repository.py`: `                paid_at=paid_at_of(invoice.state),` → `                paid_at=now,` | `test_invoice_payment_repository.py::test_r47_mark_paid_updates_only_status_paid_at_and_updated_at_and_inserts_the_payment_and_the_fact` | `AssertionError: assert ('paid', date...timezone.utc)) == ('paid', date...timezone.utc))` | yes / yes / yes |
| 54 | G4-payment-row-not-inserted | `infrastructure/persistence/invoice_repository.py`: `        self._session.add(invoice_mapper.new_payment_row(payment, now)…` → `` | `test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` | `AssertionError: R47: 0 payments rows for the paid invoice, not one` | yes / yes / yes |
| 55 | G5-payment-valuedate-corrupt | `infrastructure/persistence/invoice_mapper.py`: `        value_date=payment.value_date,⏎        source=payment.source.v…` → `        value_date=created_at,⏎        source=payment.source.value,` | `test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` | `AssertionError: R47: payments.value_date is 2026-10-10 04:25:40.223000+00:00, not the request's valueDate` | yes / yes / yes |
| 56 | G6-payment-source-corrupt | `infrastructure/persistence/invoice_mapper.py`: `source=payment.source.value,` → `source='test',` | `test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` | `AssertionError: assert 'test' == 'robot'` | yes / yes / yes |
| 57 | G7-payment-amount-corrupt | `infrastructure/persistence/invoice_mapper.py`: `        amount=payment.amount.amount,⏎        currency_code=payment.am…` → `        amount=payment.amount.amount + 1,⏎        currency_code=paymen…` | `test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` | `AssertionError: assert 8116 == 8115` | yes / yes / yes |
| 58 | G8-payment-currency-corrupt | `infrastructure/persistence/invoice_mapper.py`: `currency_code=payment.amount.currency,` → `currency_code='USD',` | `test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` | `AssertionError: assert 'USD' == 'EUR'` | yes / yes / yes |
| 59 | G9-payment-reference-corrupt | `infrastructure/persistence/invoice_mapper.py`: `        payment_reference=payment.payment_reference,⏎        invoice_i…` → `        payment_reference=payment.payment_reference + 'x',⏎        inv…` | `test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` | `AssertionError: assert 'BANK-REF-7731x' == 'BANK-REF-7731'` | yes / yes / yes |
| 60 | G10-reads-payment-filter-inverted | `infrastructure/persistence/invoice_repository.py`: `select(PaymentRow).where(PaymentRow.payment_reference == payment_refer…` → `select(PaymentRow).where(PaymentRow.payment_reference != payment_refer…` | `test_invoice_payment_repository.py::test_r48_the_reads_return_the_stored_payment_and_invoice_through_the_mapper` | `AssertionError: R48: the payment read by its reference found nothing` | yes / yes / yes |
| 61 | G11-reads-invoice-reference-filter | `infrastructure/persistence/invoice_repository.py`: `select(InvoiceRow).where(InvoiceRow.invoice_reference == invoice_refer…` → `select(InvoiceRow).where(InvoiceRow.order_reference == invoice_referen…` | `test_invoice_payment_repository.py::test_r48_the_reads_return_the_stored_payment_and_invoice_through_the_mapper` | `AssertionError: R48: the invoice read by its INV- reference found nothing` | yes / yes / yes |
| 62 | G12-payment-snapshot-source-corrupt | `infrastructure/persistence/invoice_mapper.py`: `        source=PaymentSource(row.source),` → `        source=PaymentSource.TEST,` | `test_invoice_payment_repository.py::test_r48_the_reads_return_the_stored_payment_and_invoice_through_the_mapper` | `AssertionError: assert (datetime.dat...TEST: 'test'>) == (datetime.dat...: 'operator'>)` | yes / yes / yes |
| 63 | G13-payment-snapshot-currency-corrupt | `infrastructure/persistence/invoice_mapper.py`: `amount=Money(row.amount, row.currency_code),` → `amount=Money(row.amount, 'EUR'),` | `test_invoice_payment_repository.py::test_r48_a_stored_payment_carries_its_own_currency_not_a_default` | `AssertionError: the payment came back as 8115 EUR` | yes / yes / yes |
| 64 | G14-reads-delegate-to-the-wrong-loader | `infrastructure/persistence/invoice_reads.py`: `return await load_invoice_by_id(session, invoice_id)` → `return None` | `test_invoice_payment_repository.py::test_r48_the_reads_return_the_stored_payment_and_invoice_through_the_mapper` | `AssertionError: R48: the invoice read by its id found nothing` | yes / yes / yes |
| 65 | G15-stray-update-population | `infrastructure/persistence/invoice_repository.py`: `class SqlAlchemyInvoiceRepository:` → `_STRAY = update(InvoiceRow)⏎⏎⏎class SqlAlchemyInvoiceRepository:` | `test_write_path_population.py::test_every_write_path_in_the_service_is_a_classified_literal[billing]` | `AssertionError: services/billing/src has an unclassified write path (or lost a classified one, or gained a second occurrence of one): add it to EXPECTED with its classification. Found: {'infrastructur` | yes / yes / yes |
| 66 | H1-route-entry-removed | `presentation/credit_responder.py`: `    PAYMENT_REGISTER_SUBJECT: _payment_register,⏎` → `` | `test_credit_subjects.py::test_the_six_subjects_are_pairwise_distinct_and_are_exactly_the_route_table` | `AssertionError: assert {'billing.cre...invoice.list'} == {'billing.cre...ent.register'}` | yes / yes / yes |
| 67 | H1b-route-entry-wrong-handler | `presentation/credit_responder.py`: `    PAYMENT_REGISTER_SUBJECT: _payment_register,` → `    PAYMENT_REGISTER_SUBJECT: _invoice_issue,` | `test_credit_responder.py::test_r47_billing_payment_register_dispatches_a_command_carrying_the_header_ids` | `AssertionError: R47: the payment route answered {'code': 'VALIDATION_FAILED', 'message': "invoice.issue request is invalid: 5 validation errors for InvoiceIssueRequestPayload\norderReference\n  Field ` | yes / yes / yes |
| 68 | H2-handler-registration-removed | `composition.py`: `    registry.register_command(RegisterPaymentCommand, RegisterPaymentH…` → `` | `test_billing_host_lifespan.py::test_the_billing_root_registers_every_message_and_a_missing_or_doubled_one_fails_by_name` | `otc_cqrs.errors.DispatcherValidationError: No command handler is registered for RegisterPaymentCommand. Exactly one is required.` | yes / yes / yes |
| 69 | H2b-handler-registration-removed-arch | `composition.py`: `    registry.register_command(RegisterPaymentCommand, RegisterPaymentH…` → `` | `test_registration_behaviour.py::test_a_service_registers_only_from_its_composition_root_and_its_tables_match[billing]` | `AssertionError: the probe could not run otc_billing:` | yes / yes / yes |
| 70 | H3-already-paid-answered-domain-error | `presentation/credit_rpc_errors.py`: `return rpc(Code.invoice_not_payable, error.message, {"code": error.cod…` → `return rpc(Code.domain_error, error.message, {"code": error.code})` | `test_credit_rpc_errors.py::test_each_row_of_the_mapping_answers_its_code_and_details[invoice already paid]` | `AssertionError: invoice already paid` | yes / yes / yes |
| 71 | H3b-already-paid-answered-domain-error-table | `presentation/credit_rpc_errors.py`: `return rpc(Code.invoice_not_payable, error.message, {"code": error.cod…` → `return rpc(Code.domain_error, error.message, {"code": error.code})` | `test_billing_rpc_error_retryability.py::test_r49_every_payment_refusal_is_answered_with_its_tabulated_terminal_code` | `AssertionError: InvoiceAlreadyPaidError is answered DOMAIN_ERROR, the table says INVOICE_NOT_PAYABLE` | yes / yes / yes |
| 72 | H4-mismatch-answered-precondition-failed | `presentation/credit_rpc_errors.py`: `return rpc(Code.payment_mismatch, error.message, {"code": error.code})` → `return rpc(Code.precondition_failed, error.message, {"code": error.cod…` | `test_credit_rpc_errors.py::test_each_row_of_the_mapping_answers_its_code_and_details[payment amount mismatch]` | `AssertionError: payment amount mismatch` | yes / yes / yes |
| 73 | H5-reused-answered-conflict | `presentation/credit_rpc_errors.py`: `            return rpc(⏎                Code.precondition_failed,⏎    …` → `            return rpc(⏎                Code.conflict,⏎               …` | `test_billing_rpc_error_retryability.py::test_bc27_no_input_produces_conflict` | `AssertionError: assert <Code.conflict: 'CONFLICT'> not in {<Code.conflict: 'CONFLICT'>, <Code.domain_error: 'DOMAIN_ERROR'>, <Code.internal_error: 'INTERNAL_ERROR'>, <Code.invoice_not_payable: 'INVOIC` | yes / yes / yes |
| 74 | H5b-reused-answered-unavailable-retried | `presentation/credit_rpc_errors.py`: `            return rpc(⏎                Code.precondition_failed,⏎    …` → `            return rpc(⏎                Code.unavailable,⏎            …` | `test_billing_rpc_error_retryability.py::test_r49_every_payment_refusal_is_answered_with_its_tabulated_terminal_code` | `AssertionError: PaymentReferenceReusedError is answered UNAVAILABLE, the table says PRECONDITION_FAILED` | yes / yes / yes |
| 75 | H6-not-outstanding-answered-internal | `presentation/credit_rpc_errors.py`: `        case CreditNotOutstandingError():⏎            return rpc(Code.…` → `        case CreditNotOutstandingError():⏎            return rpc(Code.…` | `test_billing_rpc_error_retryability.py::test_r49_every_payment_refusal_is_answered_with_its_tabulated_terminal_code` | `AssertionError: CreditNotOutstandingError is answered INTERNAL_ERROR, the table says PRECONDITION_FAILED` | yes / yes / yes |
| 76 | H7-not-found-answered-validation | `presentation/credit_rpc_errors.py`: `        case InvoiceNotFoundError():⏎            return rpc(⏎         …` → `        case InvoiceNotFoundError():⏎            return rpc(⏎         …` | `test_credit_rpc_errors.py::test_each_row_of_the_mapping_answers_its_code_and_details[invoice not found]` | `AssertionError: invoice not found` | yes / yes / yes |
| 77 | H8-wire-valuedate-not-truncated | `presentation/payment_wire.py`: `value_date=wire_instant(request.value_date),` → `value_date=request.value_date,` | `test_payment_wire.py::test_every_command_field_is_the_requests_own_value` | `AssertionError: assert datetime.datetime(2026, 10, 9, 13, 45, 10, 123987, tzinfo=TzInfo(7200)) == datetime.datetime(2026, 10, 9, 11, 45, 10, 123000, tzinfo=datetime.timezone.utc)` | yes / yes / yes |
| 78 | H9-wire-identity-check-removed | `presentation/payment_wire.py`: `    if request.invoice_id is None and request.invoice_reference is Non…` → `` | `test_payment_wire.py::test_a_request_that_fails_the_schema_or_the_edge_check_is_invalid` | `Failed: DID NOT RAISE InvalidPaymentRequestError` | yes / yes / yes |
| 79 | H10-wire-request-id-from-correlation | `presentation/payment_wire.py`: `        request_id=correlation.request_id,` → `        request_id=correlation.correlation_id,` | `test_payment_wire.py::test_every_command_field_is_the_requests_own_value` | `AssertionError: assert UniqueId(valu...000000000c0')) == UniqueId(valu...000000000d0'))` | yes / yes / yes |
| 80 | H11-wire-reply-paidat-dropped | `presentation/payment_wire.py`: `        paid_at=result.paid_at,` → `        paid_at=None,` | `test_payment_wire.py::test_the_reply_carries_the_outcome_the_references_the_status_and_the_millisecond_instant` | `AssertionError: assert {'outcome': '...-000101', ...} == {'outcome': '...-000101', ...}` | yes / yes / yes |
| 81 | H12-wire-amount-currency-corrupt | `presentation/payment_wire.py`: `amount=Money(request.amount.amount, request.amount.currency),` → `amount=Money(request.amount.amount, 'USD'),` | `test_payment_wire.py::test_every_command_field_is_the_requests_own_value` | `AssertionError: assert (8115, 'USD') == (8115, 'EUR')` | yes / yes / yes |
| 82 | W1-invoice-outbox-write-removed | `infrastructure/persistence/invoice_repository.py`: `        # The outbox rows join THIS session and transaction (R13); the…` → `        self._saved.append(invoice)⏎⏎    def clear` | `test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` | `AssertionError: R47: expected payment.received.v1 then credit.released.v1 in seq order, got ['credit.released.v1']` | yes / yes / yes |
| 83 | W2-invoice-outbox-write-wrong-events | `infrastructure/persistence/invoice_repository.py`: `        await self._outbox.write(self._session, invoice.domain_events)…` → `        await self._outbox.write(self._session, ())⏎        self._save…` | `test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` | `AssertionError: R47: expected payment.received.v1 then credit.released.v1 in seq order, got ['credit.released.v1']` | yes / yes / yes |

Defeat-list rows that apply to the guards of this feature and how each was handled: 1 delete the behaviour (A3, B2, C1, C2, D4, G4, W1, H1, H2), 2 corrupt a supplied field (E1 - E9, G5 - G9, H8, H12), 3 substitute a sibling identifier (B3 swaps the party pair, B4 the id, C6/C7 the reference, E9 a wrong invoice id, E11/E13 request vs correlation, H1b the sibling `invoice.issue` handler), 4 shadow in a comment or string (the timer guard classifies instead of excluding), 7 drop an optional element (H9: neither identifier), 8 literal to literal (none: every expected value is read back from the database, the broker or the reply), 9 satisfy the closer half and leave the premise stale (the R48 identity case, §7.2), 10 build output or caches (cleared before each arm, `generated/` excluded at the source), 12 a path the population never drives (the UNIQUE backstop and the post-lock re-read each have a constructed race; the repository's own guard has its own test). Not applicable: 5 and 6 (no syntax guard is the instrument for a behaviour here), 11 (the behaviour is tested). **Not mutated, and why:** the outbox writer's per-row `flush` (a parity-guarded copy outside the bounds; its effect is proved through the callers: A1 swaps the emissions and W1/W2 drop the invoice's write), the `Identity(always=True)` `seq` column (`models.py`, outside the bounds).

## 8. Call-site search (every site of every seam), one classification per hit

`grep -rnE "\.mark_paid\(|\.release\(|\bmark_paid\b|outbox\.write|PAYMENT_REGISTER_SUBJECT|_payment_register\b|payment_register\.register|new_payment_row|payment_snapshot\(|load_payment_by_reference|find_payment_by_reference|RegisterPaymentHandler|update\(InvoiceRow" services/billing/src` (non-comment hits):

| Hit | Classification | Killed by |
|---|---|---|
| `application/payment_register.py` `invoice.mark_paid(` (domain) | the one production caller of `Invoice.mark_paid` | A1 - A3, D1 - D3, E1 - E4 |
| `application/payment_register.py` `credit.release(` | the second production caller of `BuyerCredit.release` (the first: `credit_release.py:33`, feature 19, reason `ORDER_CANCELLED`) | A2, D4, E10, E11 |
| `application/payment_register.py` `tx.invoices.mark_paid(` | the one caller of the repository update | A1, A3, E5 - E9 |
| `application/payment_register.py` `find_payment_by_reference` x2 (`tx.` and `scope.invoice_reads.`) | the authority read under the lock; the fast path | C1, C2, C6, C7 |
| `application/handlers.py` `payment_register.register(` | handler delegation | H1b (a wrong delegate), H2 |
| `invoice_repository.py` `mark_paid` (def), `update(InvoiceRow)`, `session.add(new_payment_row(...))`, `outbox.write(` in `mark_paid` | the UPDATE, the INSERT and the writer call of the new path | B5, G1 - G4, W1, W2, G15 (a stray `update(` is an unclassified write path) |
| `invoice_repository.py` `outbox.write(` in `save` and `credit_repository.py:103` | pre-existing writer calls (features 19, 21) | feature 19 / 21 arms; unchanged here |
| `invoice_mapper.py` `new_payment_row`, `payment_snapshot` | the constructor of the `payments` row and its reverse | G5 - G9, G12, G13 |
| `invoice_reads.py` `find_by_id`, `find_by_invoice_reference`, `find_payment_by_reference`, `load_payment_by_reference` | the unlocked identity resolution and the fast path | G10, G11, G14, F1, F2 |
| `presentation/credit_responder.py` `PAYMENT_REGISTER_SUBJECT: _payment_register` and `_payment_register` | the route entry, no rename | H1, H1b |
| `composition.py` `register_command(RegisterPaymentCommand, RegisterPaymentHandler)` | explicit registration | H2, H2b |
| `credit_release.py:33` `credit.release(` | feature 19's caller (the `billing.credit.release` responder) | not touched here |
| `domain/invoice.py` `def mark_paid` and the docstrings | the definition and prose | n/a |

## 9. Live record (BI22 pattern; raw outputs `.arm/bc22/live/`)

Stack: `docker ps` before: `otcpy-n8n Up 24 hours (unhealthy)`; started `docker compose -p otcpy -f docker-compose.infra.yml start postgres nats kafka` (all healthy); hosts `uvicorn otc_billing.main:app --port 8103`, `otc_fulfillment.main:app --port 8102`, `otc_orders.main:app --port 8101` (each `/health/ready` 200); stopped by `kill -TERM` (each log ends `Application shutdown complete`, 0 `Traceback`, ports 8101 - 8103 free); `docker stop otcpy-kafka otcpy-nats otcpy-postgres`; `docker ps` after: `otcpy-n8n Up 24 hours (healthy)` only. Payments were sent over raw NATS with the walkthrough helper `nats_call.py` (not product code), `x-correlation-id` = the ORDER id.

### K1 pre-state

```text
== K1 pre-state, 2026-10-10T06:28:00+02:00
                  id                  | order_reference |  status   | total_amount 
--------------------------------------+-----------------+-----------+--------------
 1741d5aa-cfba-4205-a1c0-82e7a5cb8984 | ORD-000001      | completed |        16130
 cf826257-6521-4471-9292-d5a81919eba6 | ORD-000002      | completed |        10374
 321abe6d-ee7b-465f-86d7-d65d6707d131 | ORD-000003      | completed |        19450
 d69b8a2a-b0c8-47d5-bf66-82720335518c | ORD-000004      | completed |        23972
 6baf7a6d-aeff-46af-a629-8abe050c8699 | ORD-000005      | completed |        10055
 d8324836-41a0-44ab-8128-75b63039eda2 | ORD-000006      | cancelled |        24999
 223c1406-1fd8-45c8-99c5-88a738720414 | ORD-000007      | confirmed |        55545
 b7117514-a2a0-49e5-a41f-bab72062b246 | ORD-000008      | invoiced  |        99996
 c8a96a35-b360-4965-a92a-4c379ac81dca | ORD-000009      | cancelled |       374985
 9537652c-3e14-4491-a09a-6eea14bbf3de | ORD-000010      | invoiced  |        58466
(10 rows)

 invoice_reference | order_reference | status |        paid_at         | amount | discount | total_amount | currency_code |         updated_at         
-------------------+-----------------+--------+------------------------+--------+----------+--------------+---------------+----------------------------
 INV-000001        | ORD-000001      | paid   | 2026-06-02 09:00:00+00 |  16130 |        0 |        16130 | EUR           | 2026-06-02 09:00:00+00
 INV-000002        | ORD-000002      | paid   | 2026-06-03 09:00:00+00 |  10374 |        0 |        10374 | EUR           | 2026-06-03 09:00:00+00
 INV-000003        | ORD-000003      | paid   | 2026-06-04 09:00:00+00 |  19450 |        0 |        19450 | EUR           | 2026-06-04 09:00:00+00
 INV-000004        | ORD-000004      | paid   | 2026-06-05 09:00:00+00 |  23972 |        0 |        23972 | EUR           | 2026-06-05 09:00:00+00
 INV-000005        | ORD-000005      | paid   | 2026-06-06 09:00:00+00 |  10055 |        0 |        10055 | GBP           | 2026-06-06 09:00:00+00
 INV-000006        | ORD-000008      | issued |                        |  99996 |        0 |        99996 | EUR           | 2026-10-09 18:21:13.3+00
 INV-000007        | ORD-000010      | issued |                        |  59243 |      777 |        58466 | EUR           | 2026-10-09 18:22:04.826+00
(7 rows)

 payments | credit_items | outbox | unpublished 
----------+--------------+--------+-------------
        5 |           22 |     29 |           0
(1 row)

   [the 22-row credits listing is omitted: CR-000001 CarrefourEs/IBERFOODS limit 500000, committed 214007 = ORD-000007 55545 + ORD-000008 99996 + ORD-000010 58466; the other 21 lines are 0]



 order_reference |  type   | amount 
-----------------+---------+--------
 ORD-000008      | hold    |  99996
 ORD-000008      | consume |  99996
 ORD-000010      | hold    |  58466
 ORD-000010      | consume |  58466
(4 rows)

 completed_facts | outbox 
-----------------+--------
               5 |     25
(1 row)

```

### K2 the two registrations

```text
== K2 payments 2026-10-10T06:28:15+02:00
-- ORD-000010 / INV-000007 net 58466 (request cd29e1f0-a301-4100-8844-4e14e3ee5eb3)
{"outcome":"accepted","paymentReference":"LIVE-REF-000010","invoiceReference":"INV-000007","orderReference":"ORD-000010","invoiceStatus":"paid","paidAt":"2026-10-10T04:28:15.854Z"}
-- ORD-000008 / INV-000006 net 99996 (request 5b8ac55e-9249-4280-8afd-01e3d104f85e)
{"outcome":"accepted","paymentReference":"LIVE-REF-000008","invoiceReference":"INV-000006","orderReference":"ORD-000008","invoiceStatus":"paid","paidAt":"2026-10-10T04:28:16.121Z"}
```

### K3 the end state, read from both databases

```text
== K3 after-state 2026-10-10T06:28:31+02:00
 invoice_reference | order_reference | status |          paid_at           | total_amount | discount |         updated_at         
-------------------+-----------------+--------+----------------------------+--------------+----------+----------------------------
 INV-000006        | ORD-000008      | paid   | 2026-10-10 04:28:16.121+00 |        99996 |        0 | 2026-10-10 04:28:16.131+00
 INV-000007        | ORD-000010      | paid   | 2026-10-10 04:28:15.854+00 |        58466 |      777 | 2026-10-10 04:28:15.867+00
(2 rows)

 payment_reference | invoice_reference | amount | currency_code |       value_date       |  source  
-------------------+-------------------+--------+---------------+------------------------+----------
 LIVE-REF-000008   | INV-000006        |  99996 | EUR           | 2026-10-10 06:30:01+00 | operator
 LIVE-REF-000010   | INV-000007        |  58466 | EUR           | 2026-10-10 06:30:00+00 | operator
(2 rows)

 seq |     event_type      |             aggregate_id             |            correlation_id            |             causation_id             |               event_id               |        occurred_at         | published | avail_after | released |    reason    
-----+---------------------+--------------------------------------+--------------------------------------+--------------------------------------+--------------------------------------+----------------------------+-----------+-------------+----------+--------------
  30 | payment.received.v1 | 613c4458-e8c9-4470-818d-4fb63256dcf4 | 9537652c-3e14-4491-a09a-6eea14bbf3de | cd29e1f0-a301-4100-8844-4e14e3ee5eb3 | fd7b8802-a483-44e8-b445-1ec6ad67d2d2 | 2026-10-10 04:28:15.854+00 | t         |             |          | 
  31 | credit.released.v1  | 5c62308c-31fd-47ab-aa6f-a27cc545a36e | 9537652c-3e14-4491-a09a-6eea14bbf3de | fd7b8802-a483-44e8-b445-1ec6ad67d2d2 | 5998ca8b-5fdd-4c5f-add8-73033a5ebddc | 2026-10-10 04:28:15.854+00 | t         | 344459      | 58466    | invoice_paid
  32 | payment.received.v1 | e2bc577c-7ee2-45af-870a-e279a4411e7f | b7117514-a2a0-49e5-a41f-bab72062b246 | 5b8ac55e-9249-4280-8afd-01e3d104f85e | e413db3d-8e0b-4e06-a4cb-9a8b99acf8ee | 2026-10-10 04:28:16.121+00 | t         |             |          | 
  33 | credit.released.v1  | 5c62308c-31fd-47ab-aa6f-a27cc545a36e | b7117514-a2a0-49e5-a41f-bab72062b246 | e413db3d-8e0b-4e06-a4cb-9a8b99acf8ee | 643808d5-ff43-4771-a1c5-a7865f652cd9 | 2026-10-10 04:28:16.121+00 | t         | 444455      | 99996    | invoice_paid
(4 rows)

 order_reference |  type   | amount 
-----------------+---------+--------
 ORD-000008      | hold    |  99996
 ORD-000008      | consume |  99996
 ORD-000008      | release |  99996
 ORD-000010      | hold    |  58466
 ORD-000010      | consume |  58466
 ORD-000010      | release |  58466
(6 rows)

 payments | credit_items | outbox | unpublished 
----------+--------------+--------+-------------
        7 |           24 |     33 |           0
(1 row)

   code    | credit_limit | committed 
-----------+--------------+-----------
 CR-000001 |       500000 |     55545
(1 row)

 order_reference |  status   
-----------------+-----------
 ORD-000008      | completed
 ORD-000010      | completed
(2 rows)

 seq |     event_type     |             aggregate_id             |             causation_id             |        occurred_at         
-----+--------------------+--------------------------------------+--------------------------------------+----------------------------
  26 | order.completed.v1 | 9537652c-3e14-4491-a09a-6eea14bbf3de | 5998ca8b-5fdd-4c5f-add8-73033a5ebddc | 2026-10-10 04:28:15.854+00
  27 | order.completed.v1 | b7117514-a2a0-49e5-a41f-bab72062b246 | 643808d5-ff43-4771-a1c5-a7865f652cd9 | 2026-10-10 04:28:16.121+00
(2 rows)

 completed_facts | outbox 
-----------------+--------
               7 |     27
(1 row)

```

```text
== K3b orders consumed the facts in order 2026-10-10T06:28:42+02:00
               event_id               |  consumer   |        processed_at        
--------------------------------------+-------------+----------------------------
 fd7b8802-a483-44e8-b445-1ec6ad67d2d2 | orders.saga | 2026-10-10 04:28:16.101+00
 5998ca8b-5fdd-4c5f-add8-73033a5ebddc | orders.saga | 2026-10-10 04:28:16.141+00
 e413db3d-8e0b-4e06-a4cb-9a8b99acf8ee | orders.saga | 2026-10-10 04:28:16.381+00
 643808d5-ff43-4771-a1c5-a7865f652cd9 | orders.saga | 2026-10-10 04:28:16.392+00
(4 rows)

 order_reference |  status   |         updated_at         
-----------------+-----------+----------------------------
 ORD-000008      | completed | 2026-10-10 04:28:16.121+00
 ORD-000010      | completed | 2026-10-10 04:28:15.854+00
(2 rows)

-- orders log lines mentioning the two orders:
```

Reading: for each order the invoice is `paid` with `paid_at` set (equal to the reply's `paidAt` and to both facts' `occurred_at`), one `payments` row, `payment.received.v1` (seq 30 / 32) strictly before `credit.released.v1` (seq 31 / 33), both with the ORDER id as `correlation_id`, **the release's `causation_id` equal to the payment fact's `event_id`** (`fd7b8802...` for ORD-000010, `e413db3d...` for ORD-000008), the payment's `causation_id` the request id (`cd29e1f0...`, `5b8ac55e...`); `availableCreditAfter` 344 459 / 444 455 (not the 500 000 limit, not the 285 993 before); Orders consumed `payment.received.v1` then `credit.released.v1` (`processed_events` 16.101 then 16.141 for ORD-000010), both orders are `completed`, and each `order.completed.v1` (seq 26, 27) has the release's `event_id` as its `causation_id`; `order.completed.v1` count 5 -> 7, `unpublished` 0 in both outboxes.

### K4 the repeat and the rejections (nothing changed)

```text
== K4 before 2026-10-10T06:28:56+02:00
 payments | credit_items | outbox |                            invoices                             
----------+--------------+--------+-----------------------------------------------------------------
        7 |           24 |     33 | paid@2026-10-10 04:28:16.131+00,paid@2026-10-10 04:28:15.867+00
(1 row)

 orders_outbox | completed_facts 
---------------+-----------------
            27 |               7
(1 row)

-- repeat LIVE-REF-000010 against INV-000007 (request c63637e7-daec-4781-a78e-167e6119f669)
{"outcome":"duplicate","paymentReference":"LIVE-REF-000010","invoiceReference":"INV-000007","orderReference":"ORD-000010","invoiceStatus":"paid","paidAt":"2026-10-10T04:28:15.854Z"}
-- mismatched amount (gross 59243), NEW reference, against the PAID INV-000007
{"code":"INVOICE_NOT_PAYABLE","message":"Invoice INV-000007 is already paid.","details":{"code":"invoice.already_paid"},"correlationId":"9537652c-3e14-4491-a09a-6eea14bbf3de","occurredAt":"2026-10-10T04:28:56.750Z"}
-- the SAME reference LIVE-REF-000010 with another amount (59243)
{"code":"PRECONDITION_FAILED","message":"Payment reference 'LIVE-REF-000010' is already recorded for another invoice or another amount.","details":{"code":"payment.reference_reused","paymentReference":"LIVE-REF-000010"},"correlationId":"9537652c-3e14-4491-a09a-6eea14bbf3de","occurredAt":"2026-10-10T04:28:56.955Z"}
-- LIVE-REF-000010 against the OTHER invoice INV-000006
{"code":"PRECONDITION_FAILED","message":"Payment reference 'LIVE-REF-000010' is already recorded for another invoice or another amount.","details":{"code":"payment.reference_reused","paymentReference":"LIVE-REF-000010"},"correlationId":"b7117514-a2a0-49e5-a41f-bab72062b246","occurredAt":"2026-10-10T04:28:57.182Z"}
== K4 after 2026-10-10T06:29:01+02:00
 payments | credit_items | outbox |                            invoices                             
----------+--------------+--------+-----------------------------------------------------------------
        7 |           24 |     33 | paid@2026-10-10 04:28:16.131+00,paid@2026-10-10 04:28:15.867+00
(1 row)

 orders_outbox | completed_facts 
---------------+-----------------
            27 |               7
(1 row)

```

The repeat answered `duplicate` with the original `paidAt`. The mismatched amount (the gross 59243) was sent against the already-`paid` INV-000007, so it is refused by the paid check first (`INVOICE_NOT_PAYABLE`; the domain checks `paid` before the amount); **no `issued` invoice remained to show `PAYMENT_MISMATCH` live** (both were consumed by the two registrations; `PAYMENT_MISMATCH` is proven in `test_r49_a_mismatched_amount_is_rejected_with_nothing_changed` and `..._currency_...`). A reference reused with another amount and against the other invoice were both `PAYMENT_REFERENCE_REUSED`'s refusal. Every count (payments 7, credit_items 24, outbox 33, orders outbox 27, `order.completed.v1` 7, both invoices' `updated_at`) is identical before and after.

### K5 final state, and the register of altered live fixtures (extends `progress/impl_billing_credit.md` section 8 and `progress/impl_billing_invoicing.md` section 9)

```text
== K5 final fixture state 2026-10-10T06:29:09+02:00
 order_reference |  status   
-----------------+-----------
 ORD-000001      | completed
 ORD-000002      | completed
 ORD-000003      | completed
 ORD-000004      | completed
 ORD-000005      | completed
 ORD-000006      | cancelled
 ORD-000007      | confirmed
 ORD-000008      | completed
 ORD-000009      | cancelled
 ORD-000010      | completed
(10 rows)

 invoice_reference | order_reference | status |          paid_at           | total_amount 
-------------------+-----------------+--------+----------------------------+--------------
 INV-000001        | ORD-000001      | paid   | 2026-06-02 09:00:00+00     |        16130
 INV-000002        | ORD-000002      | paid   | 2026-06-03 09:00:00+00     |        10374
 INV-000003        | ORD-000003      | paid   | 2026-06-04 09:00:00+00     |        19450
 INV-000004        | ORD-000004      | paid   | 2026-06-05 09:00:00+00     |        23972
 INV-000005        | ORD-000005      | paid   | 2026-06-06 09:00:00+00     |        10055
 INV-000006        | ORD-000008      | paid   | 2026-10-10 04:28:16.121+00 |        99996
 INV-000007        | ORD-000010      | paid   | 2026-10-10 04:28:15.854+00 |        58466
(7 rows)

 payments | credit_items | releases | outbox | unpublished 
----------+--------------+----------+--------+-------------
        7 |           24 |        8 |     33 |           0
(1 row)

   code    | credit_limit | committed 
-----------+--------------+-----------
 CR-000001 |       500000 |     55545
(1 row)

 completed_facts | outbox | unpublished 
-----------------+--------+-------------
               7 |     27 |           0
(1 row)

```

Rows this walkthrough CHANGED in the developer databases (recreate them to repeat it):

- `otc_billing`: `invoices` `INV-000006` (ORD-000008) and `INV-000007` (ORD-000010) `issued` -> `paid` (`paid_at` 2026-10-10 04:28:16.121 / 15.854 UTC); `payments` 5 -> 7 (`LIVE-REF-000008`, `LIVE-REF-000010`); `credit_items` 22 -> 24 (a `release` of 99996 and of 58466); `outbox` 29 -> 33 (all published). `CR-000001`: committed exposure 214 007 -> 55 545 (only `ORD-000007`'s hold remains), available credit 285 993 -> 444 455.
- `otc_orders`: `ORD-000008` and `ORD-000010` `invoiced` -> `completed`; `outbox` 25 -> 27 (`order.completed.v1` x2, 5 -> 7), `processed_events` + 4.
- `otc_fulfillment`: untouched. Kafka topics carry the four new facts and the two completions; `otcpy-n8n` untouched. `ORD-000007` still stops at `confirmed`. **No `issued` invoice remains in the developer database**: a future live check of `PAYMENT_MISMATCH` needs a new order placed through `orders.create`.

## 10. Ported-idiom ledger (`sdd: false`, so it lives here)

| Idiom | #7 relied on | #8 supplied | In #9 it is supplied by | Guard (armed) |
|---|---|---|---|---|
| Lock order credits -> invoice | `payment-register.handler.ts:125-145`: `credits.lockForOrder` then `invoices.lockById` (a second, row lock) | `PaymentRegisterService.cs:83-90`: `LockForOrderAsync` then `LockByIdAsync` | the credits row ONLY (feature 21's BI8 binding, design §15.1): the invoice is resolved unlocked, the credits row locked, the invoice re-read plain; no invoice row lock, because the line lock serialises every payment of that line and the guarded `UPDATE ... WHERE status = 'issued'` is the backstop. Two engine claims probed both ways: the held-lock probe shows the request does NOT hold the invoice row while parked on the credits row, and the stale-snapshot case shows the guarded UPDATE fails closed (B2, G1) | B1, B2, B5 |
| The in-transaction re-read is un-hinted (#8 id 54) | n/a (row lock) | `FindPaymentByInvoiceIdAsync` un-hinted, correct because of the credit-row lock | `READ COMMITTED` pinned per call (`credit_transactions.py`), so the re-read after the lock is a fresh statement that sees a competitor's commit; two instances in this feature: `find_by_id` and `find_payment_by_reference` | B2, C2 |
| `markPaid` returns its event id (#8 id 57) | `payment-register.handler.ts:173,199-201` | `Invoice.MarkPaid` void at the time (the finding) | `Invoice.mark_paid` returns the `PaymentReceived` (feature 21); the caller passes `fact.event_id` as the release's `CreditContext.causation_id` | A2, A2b, A2c, E13 |
| Emission order = call order + insertion order | `invoices.markPaid` before `credits.save` (`:210-215`) | `MarkPaidAsync` awaited before `SaveChangesAsync` (`:144-145`), IDENTITY | the same call order, plus the `Identity(always=True)` `seq` (feature 19 L20). The writer's per-row `flush` does NOT carry the order on this path (review RV16: removing it survived); it matters only when one `write()` carries several events, which no Billing transaction does yet | A1, A1b, W1, W2 |
| Unique-constraint backstop for a competitor the lock does not serialise | `PaymentReferenceConflictError` from the unique index | `EfCoreInvoiceRepository.cs:258-266` catches `DbUpdateException` | `IntegrityError` from asyncpg, SQLSTATE `23505` AND the constraint name `uq_payments_payment_reference` in the message, raised in the repository's `flush` inside the `session.begin()` block, so the transaction rolls back whole | C5, C5b |
| A reused reference is not a success-shaped `duplicate` (#7 N11) | fixed after review | `IdentityMatches` (`:61,143-156`) | the same identity check on the fast path AND under the lock, extended to the amount and currency (`openapi.yaml` 673) | C3, C4, C4b, C4c |
| `release`'s `None` (#8 N3) | discarded | discarded | refused: `CreditNotOutstandingError`, the transaction rolls back (§12) | D4, D4b |
| Money in minor units | `Money.of` | `Money` | `Money` (`int`, frozen dataclass; `==` compares amount AND currency, which the amount/currency reuse check relies on and C3b / the currency parametrisation prove); no `/`, no `Decimal`, no `float` in the new code | C3, D1, D2 |
| Money text in errors (#8 id 102) | n/a | n/a | the domain errors render through `format_money` (feature 21 BI36); the new application errors name no amount | feature 21's BI36 guards (existing, untouched) |
| JSON / instants on the wire | ISO strings | ISO strings | the one serializer (`to_wire_json`), `wire_instant` truncating the request's `valueDate` to the millisecond BEFORE the column (`timestamptz(3)` ROUNDS) and the fact | H8, G5, E5 |
| Event-loop affinity | n/a | n/a | no engine or pool is created by this feature; the race tests open their competitor connections in the test's own loop and close them in `finally` | n/a |
| Cancellation / exception propagation | n/a | n/a | the unit of work raises through `session.begin()` (rollback); `run()` maps only DB transients to `StoreUnavailableError`; a `CancelledError` is not caught anywhere new | `test_a_rollback_after_work_yields_no_result` |

## 11. Inherited findings, avoided or recurred

| Finding | Outcome |
|---|---|
| #8 id 57 `completion_pair_has_no_causal_edge` | **avoided** (assigned to this feature): A2, A2b, A2c, E13; live K3 |
| #8 review N1 (the same, from the review) | **avoided** |
| #8 review N2 (`valueDate` corruptible with the suite green) | **avoided**: asserted on the row, the fact payload, the broker record, the decoder, and armed at both mapping sites (E1, E5, G5, H8) |
| #8 review N3 / #7 (release `None` discarded, the order strands at `paid`) | **avoided** by refusing (D4, D4b); a deviation from both predecessors, §12 |
| #8 review A1 (third R49 refusal has no responder-level test) | **avoided**: `test_r49_a_second_reference_against_a_paid_invoice_is_rejected_with_nothing_changed` through the real responder |
| #8 review A2 / id 54 (un-hinted re-read needs a ledger row) | **avoided**: two ledger rows (§10) |
| #8 review A3 (the ledger's blind spot for `sdd: false` features) | **avoided**: the ledger is §10 |
| #7 N11 (cross-invoice reuse answered a success-shaped `duplicate`) | **avoided** and extended to amount / currency |
| #8 id 48 (fresh `NatsHeaders`), 49 (release minted its own id), 53 / 55 (reply assertions that only throw), 63 (readiness retry loops) | **avoided**: no new adapter; ids come from the scope port at every site (BI34 test); every reply decode asserts its discriminating field first (`Decode.payment_register` asserts `outcome`, `Decode.error` `code`); the races wait on `pg_stat_activity`, never a sleep |
| #8 id 74 (broker test finds the first record on the topic) | **avoided**: records are selected by this test's own order id |
| #8 id 102 (money in raw minor units in a problem text) | **avoided**: the existing domain errors use `format_money` |
| #8 N12 (impl record count off by one), N13 (a stranded order in shared demo data) | **did not recur**: counts are from command output; the live run completed the two invoiced orders and recorded the remaining stranded one (`ORD-000007`, feature 19's register) |

## 12. Decisions the reviewer should look at, and things I could not do or that surprised me

1. **`release` returning `None` is refused** (`CreditNotOutstandingError`, `PRECONDITION_FAILED`). The brief says the `None` "must not be discarded"; the alternatives were to accept the payment and emit `payment.received.v1` alone (Orders then waits forever for `credit.released.v1`) or to refuse. I refused: nothing is written, the operator sees a named code. It is reachable only through a ledger already released (for example by `billing.credit.release`), proven in integration by doing exactly that. This is a divergence from #7 and #8, which discarded it.
2. **A reference reused with another amount or currency is refused, not `duplicate`.** `openapi.yaml` 673: "Same `paymentReference` reused for a different invoice or a different amount -> 409 `PAYMENT_REFERENCE_REUSED`". #7 and #8 compared the invoice identity only.
3. **The three R49 refusals answer `INVOICE_NOT_PAYABLE` / `PAYMENT_MISMATCH`** (§5), where #7 and #8 agreed on `PRECONDITION_FAILED`. The brief and design §15.1 prescribe it; `details.code` is kept.
4. **`correlationId` of the payment fact is the caller's `x-correlation-id`** (as in #7 and #8). The Billing fact's key (and the projector's timeline key) is the ORDER id, which the Gateway does not know from `POST /invoices/{id}/payments`. Feature 25 / 31 must send the order id as `x-correlation-id` (the invoice row does not store it). Not solvable in Billing without a schema change.
5. **The `payment_source` / `source` values and the `value_date` have no range check beyond the schema**; a year-1 or year-9999 `valueDate` with an offset is accepted by the schema and by `timestamptz`; not probed further.
6. **Nothing in the hold or a fixture changed in `services/orders`**; the live run needed no Orders change (acceptance 4). The `uv run` of the three hosts needs the infra postgres, nats, kafka only.
7. Surprise: the arm tool's key-line extraction reads `log[2]`, which is a log line (not the output) when an arm has two edits, so its console summary was empty for those arms; I extracted the verbatim lines from the raw logs instead (§7.3 is generated from `.arm/bc22/logs/`).
8. Surprise: `make_world` could not depend on `billing_host` (two hosts would share the queue group and a request could go to the wrong one), so tests start the host and the fixture starts none.

Not done: nothing in the brief. The API halves of R48 and R49 are feature 31's.

## 13. Second `./quality.sh` and the delta

Stack down (`docker ps`: `otcpy-n8n` only). **exit 0, 423 s, 3492 passed** (baseline 387 s, 3415): **+77 tests, +36 s**; coverage total 97.47% (gate 60%); ruff format and check clean; mypy `--strict` clean (593 source files); lint-imports clean; web 1 file / 1 test passed; "quality.sh: all gates passed". The +77 are the 66 collected in the seven new test files plus the parametrised rows added to the extended files.

## 14. Self-verification

- `tasks.md`: none (`sdd: false`); the five acceptance items: (1) idempotent by `payment_reference` -> R48 tests; (2) no internal payment timer -> §6 guard; (3) `payment.received.v1` and `credit.released.v1` caused by it (id 57) -> A2/A2b/A2c, K3; (4) the cycle closes without changes under `services/orders` -> §1 and §9; (5) BI8 lock order and the two outbox rows in order -> B1, B2, A1.
- `./init.sh` still exits 0 (run last, below).

Packages installed: none.

## Review findings

Light batch, N1 and N2 of `progress/review_billing_remittance_intake.md` §7.

- **N1:** `invoice_repository.py` `mark_paid` now wraps the UPDATE as `cast("CursorResult[Any]", await self._session.execute(...))` and tests `result.rowcount != 1`; the `# type: ignore[attr-defined]` is gone (`grep -rn "type: ignore" services/billing/src` is empty). The cast keeps the SQL byte-for-byte (same `WHERE`, same refusal), so no `.returning(...)`. Arm (backup `.arm/bc22f/`, sha256 `a2766700...6d2b`): dropping `InvoiceRow.status == "issued"` made `test_mark_paid_on_an_invoice_that_is_not_issued_is_a_transient_failure_and_writes_nothing` fail with `Failed: DID NOT RAISE StoreUnavailableError`; restored by `cp`, `cmp` clean, caches cleared, green.
- **N2:** `payment_register.py` docstring and the §10 "Emission order" row now say call order plus the `Identity` `seq` carry R47 here; the writer's per-row flush matters only when one `write()` carries several events (review RV16).
- Results: `test_invoice_payment_repository.py`, `test_payment_register.py`, `tests/architecture/test_write_path_population.py`: 90 passed (guard unaffected, statement still an `update(`); ruff check, ruff format --check and mypy clean on both sources.
