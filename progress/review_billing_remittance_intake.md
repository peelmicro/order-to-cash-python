# Review — feature 22 `billing_remittance_intake` (phase 10, `sdd: false`, full group, round 1)

**Verdict: APPROVED** — 0 blocking defects; 2 non-blocking items to fix now as a LIGHT change (N1, N2); 1 routing item for the leader (R1, an acceptance item on feature 25); the three departures from #7 / #8 ruled KEEP (§2).

Reviewer: Opus. Inputs: `progress/brief_review_billing_remittance_intake.md`, its premise check (18 VERIFIED, the FALSE file count corrected in the brief), `progress/impl_billing_remittance_intake.md`, the implementer brief, `specs/shared/{requirements.md R47–R49, asyncapi.yaml, openapi.yaml 643–675, saga.md, domain-model.md}`, `specs/billing_invoicing/design.md` §15.1, `specs/billing_credit/design.md` §15.3, `CHECKPOINTS.md`, and the #7 / #8 checkouts.

## 1. What I ran (verification, not assumption)

| Run | Result |
|---|---|
| `./quality.sh`, developer stack down (`docker ps`: `otcpy-n8n` only, before and after) | **exit 0, 416 s, `3492 passed in 392.45s`**; ruff format 743 files clean, ruff check clean, `mypy --strict` "no issues found in 593 source files", import-linter **11 kept, 0 broken**, coverage 97.47 % overall (gate 60 %), domain 98 % (gate 80 %), web 1/1, "quality.sh: all gates passed". The implementer's 3415 → 3492 (+77) is confirmed. Log: `.arm/review22/quality.log` |
| `./init.sh` | exit 0; §5d "shared spec byte-identical to ../order-to-cash-dotnet across 6 file(s)" and the same for `../order-to-cash-nestjs`; no feature `in_progress` |
| `cmp` of every `specs/shared/*` against both checkouts | 6 of 7 identical; `test-matrix.md` differs; keyed by `R<n>`, columns 2 – 4 of all 63 rows equal #8's and #7's (only the Status column differs) |
| 18 + 4 = **22 reviewer mutations** (my own, `.arm/review22/mine.py`, `mine2.py`) | 20 killed by a named test, 2 survived (both explained, §5) |
| **5 of the implementer's 83 arms re-run**, chosen by `random.SystemRandom().sample(ids, 5)` over the 83 ids exec'd from `.arm/bc22/arms.py` (`.arm/review22/random_pick.txt`): `H1b`, `G13`, `E8`, `G4`, `H3` | 5 / 5 killed with the message the implementer's table records; restored green |
| Absence search (acceptance 2) with my own sentinels | §6 |
| Restore integrity after every arm | `sha256sum -c .arm/review22/sha_before.txt` over the 11 mutated sources: 0 lines not `OK`; no `ACTIVE` marker left; arm tool copies a backup into `.arm/review22/bak/<arm>/`, restores by `cp`, `cmp` identical, clears `__pycache__` (src, tests, `tests/`) and `.mypy_cache`, re-runs green; each pytest in its own session, killed by process group on timeout |

I did not re-run the Billing integration suite on its own: `quality.sh` ran it in full; every other run is a targeted test under a mutation.

## 2. The three departures from #7 and #8 — rulings

The maintainer's rule: a decision #7 and #8 agree on, with no Python-forced difference, is adopted; only the shared spec's text (or a forced difference) overrides it.

### 2.1 A payment whose credit release has nothing outstanding is refused (`credit.not_outstanding`) — **KEEP; the shared text decides against #7 / #8, and the state is unreachable**

- **What #7 and #8 did:** discarded `release`'s `None` (#7 `payment-register.handler.ts:199` calls `credit.releaseHold(...)` unassigned; #8 `PaymentRegisterService.cs:128`, flagged as N3 in `../order-to-cash-dotnet/progress/review_billing_remittance_intake.md:153` and left "recorded, not actioned"). On that path they commit `payment.received.v1` alone.
- **The shared text:** R47 (`requirements.md:414-418`) requires `payment.received.v1` **followed by** `credit.released.v1` in the same transaction; `saga.md:72-73` (rows 6 – 7) completes the order only on `credit.released.v1`. #7 / #8's path violates R47's text and strands the order at `paid`. #9's own gated designs already bind the refusal: `specs/billing_credit/design.md` §15.3 and `specs/billing_invoicing/design.md` §15.1, "`release`'s `None` must not be discarded".
- **Reachability:** unreachable through any specified flow. An invoice exists only after `consume` of an active hold, which refuses an order with a `release` entry (`buyer_credit.py:392-397`); `release` returns `None` only for no hold or an existing `release` entry (`buyer_credit.py:348-355`); the saga issues `credit.release` only when the stock release won (before despatch, so before any invoice) or for a late `credit.approved.v1` after an accepted cancellation (`saga.md:233-257`); and "Cancellation is impossible from `despatched` onwards" (`domain-model.md:200`). The only route is an out-of-saga `billing.credit.release` call, which `test_n3_a_payment_for_an_order_whose_exposure_is_not_outstanding_is_refused_and_writes_nothing` constructs.
- **The loud failure and its code:** refusing changes nothing (rollback; asserted against the pre-attempt `state_of`). `PRECONDITION_FAILED` is terminal in Orders' set (`nats_saga_commands.py:65-77`), but Orders never calls this subject (`saga.md:50`: caller Gateway). For the Gateway's callers the state is permanent, so terminal is right. The robot treats 409 as `skipped` (`n8n/workflows/2-payment-robot.json`, `payInvoice`). `CONFLICT` is banned (BC27). The same code is the shared spec's choice for the analogous lost race (`saga.md:237`). Accepting without the release would break R47; inventing a zero release would make up a fact. **No SA needed:** R47's WHEN-clause does not exclude a state the spec's own saga cannot produce; neither alternative is more literal. Re-open trigger: any code path that issues `credit.release` for an order at `despatched` or later (feature 41 owns the cancel responder).

### 2.2 A reference reused with another amount or currency is refused, not answered `duplicate` — **KEEP; decided by the shared text**

- `openapi.yaml:673`: "Same `paymentReference` reused for a **different** invoice or a different amount → `409` `PAYMENT_REFERENCE_REUSED`"; `openapi.yaml:672` restricts `duplicate` to "the **same** invoice with the **same** amount". `asyncapi.yaml:3696` (`PaymentRegisterReplyPayload.outcome`): "A mismatched amount or currency is not a duplicate — it is an error reply (R49)." **Currency:** the request's `amount` is a `Money` object (`asyncapi.yaml:3674-3676`, `amount: $ref Money`), so "a different amount" is a different `{amount, currency}`. The leader's reading is confirmed, and the currency half is decided too by `asyncapi.yaml:3696`.
- #7 and #8 compared the invoice only (#8 `PaymentRegisterService.cs:98`; #7 its N11 fix). They deviated from the shared text; #9 follows it.
- **What the R48 duplicate path compares now** (`payment_register.py:73-78`, on the fast path and under the lock): the stored payment's `invoice_id` equals the resolved invoice; whichever of `invoiceId` / `invoiceReference` the caller sent names that invoice (`_identity_matches`); and `payment.amount != command.amount` on `Money`, which is frozen-dataclass equality over **amount and currency**. It does not compare `valueDate` or `source`, so the robot's replay (a fresh `valueDate` each run, `2-payment-robot.json`) is still a `duplicate`. Armed: C3, C3b, C4, C4b, C4c (implementer); RV10 corrupts the duplicate reply's `paidAt` (killed).

### 2.3 R49's refusals answer `INVOICE_NOT_PAYABLE` / `PAYMENT_MISMATCH`, not `PRECONDITION_FAILED` — **KEEP; decided by the shared text, and it costs no behaviour**

- **#7 and #8:** `PRECONDITION_FAILED` with a detail code (#8 `BillingErrorMapper.cs:89-105`; #7 `rpc-error-mapper.ts:108-120`).
- **The shared text:** `RpcError` (`asyncapi.yaml:2840-2870`) says "`code` is stable and machine-readable; `message` is for humans". `details` is "Structured context … **Shape depends on `code`**". R49 (`requirements.md:426-431`) requires "a machine-readable reason". The enum carries `INVOICE_NOT_PAYABLE` and `PAYMENT_MISMATCH`, and no subject in `asyncapi.yaml` but `billing.payment.register` can produce either: payability and payment matching exist nowhere else. `openapi.yaml:675` names the same `PAYMENT_MISMATCH`. Answering `PRECONDITION_FAILED` leaves both enum values with no producer and moves the reason out of the field the contract names as the stable machine-readable one. Both predecessors' Gateways already carry generic rows for the two codes (#8 `RpcErrorClassification.cs:75-76`; #7 `rpc-error-mapping.ts:53-54`), so the specific codes are inside the envelope both predecessors handle. Feature 21's gated design §15.1 had already assigned them to 22. The brief's phrasing (premise FALSE 2) did not create this departure: the gated design and the shared enum did.
- **Saga:** unaffected. Both codes are in `TERMINAL_RPC_ERROR_CODES` (`services/orders/src/otc_orders/infrastructure/messaging/nats_saga_commands.py:65-77`; the guard `test_r49_every_payment_refusal_is_answered_with_its_tabulated_terminal_code` reads the set, it does not retype it), and Orders never sends this subject.
- **Feature 31's "same script as #7's and #8's":** that script is HTTP. #8's `BlackBoxApiTests.cs:372, 405, 460` asserts 422 `PAYMENT_MISMATCH` (amount and currency) and 409 `INVOICE_ALREADY_PAID`. #9 produces the same HTTP surface **only if** feature 25 maps #9's codes to `openapi.yaml:673-675`. A verbatim port of #8's classifier would answer the already-paid refusal with Problem code `INVOICE_NOT_PAYABLE` (its generic row, `RpcErrorClassification.cs:75`), not `INVOICE_ALREADY_PAID`. It would also miss `PAYMENT_REFERENCE_REUSED`, because #8's detail overrides key on upper-case `INVOICE_ALREADY_PAID` / `INVOICE_PAYMENT_*_MISMATCH` (`:63-67`) and #9's `details.code` are dotted (`invoice.already_paid`, `payment.reference_reused`). Hence routing item R1. One case diverges from #7 / #8 by the spec's own text: the same reference with another amount answers 409 here where #7 / #8 answered 200 `duplicate`. Neither predecessor's black-box script exercises it.

## 3. `R<n>` → test mapping (verified by reading the assertions and by arming)

| R | Named test(s) | Armed by |
|---|---|---|
| **R47** (paid + `payment.received.v1` then `credit.released.v1`, one transaction) | `services/billing/tests/integration/test_payment_register.py::test_r47_registers_the_payment_pays_the_invoice_and_emits_the_payment_then_the_release_in_one_transaction` (row, payment row field by field, outbox order by `seq`, both payloads as whole dicts, causation, ledger, available credit 221 864 → 229 979); `test_payment_register_broker.py::test_r47_the_payment_fact_then_the_release_fact_reach_the_broker_in_order_keyed_by_the_order_id` (key, partition, offset order, causation, `valueDate`, `availableCreditAfter`); `unit/test_payment_register_service.py::test_r47_bi8_resolves_unlocked_then_locks_credits_then_re_reads_then_updates` (one shared call log), `::test_id57_the_release_is_caused_by_the_payment_fact_not_by_the_request` | mine: RV01 (swap → broker), RV02, RV03b, RV04, RV05, RV11, RV12, RV14, RV17, RV17b, RV18; implementer re-run: G4, E8 |
| **R48** (idempotent by `paymentReference`) | `test_payment_register.py::test_r48_a_repeated_reference_answers_the_original_outcome_and_writes_nothing` (by id and by reference, against a non-zero baseline), `::test_r48_a_reference_reused_for_another_invoice_is_refused_and_writes_nothing` (same net from another gross), `::test_r48_a_reference_reused_for_another_amount_is_refused_not_answered_duplicate`; `test_payment_register_race.py::test_r48_two_concurrent_registrations_of_one_reference_yield_one_payment_and_one_fact_pair`, `::test_r48_a_reference_stored_by_a_competitor_on_another_credit_line_is_reused_not_internal_error`; `test_invoice_payment_repository.py::test_r48_the_unique_constraint_on_the_payment_reference_is_the_reused_reference_refusal` | mine: RV08, RV09, RV10; implementer re-run: G13 |
| **R49** (three refusals, nothing changed) | `test_payment_register.py::test_r49_a_mismatched_amount_is_rejected_with_nothing_changed` (gross, net − 1, net + 1), `::test_r49_a_mismatched_currency_is_rejected_with_nothing_changed`, `::test_r49_a_second_reference_against_a_paid_invoice_is_rejected_with_nothing_changed`; codes: `tests/architecture/test_billing_rpc_error_retryability.py::test_r49_every_payment_refusal_is_answered_with_its_tabulated_terminal_code`, `unit/test_credit_rpc_errors.py::test_each_row_of_the_mapping_answers_its_code_and_details` | mine: RV13; implementer re-run: H3 |
| **BI8** (acceptance 5) | `test_payment_register_race.py::test_bi8_the_request_waits_for_the_credits_row_without_the_invoice_row_and_re_reads_after_it`; `unit/test_payment_register_service.py::test_bi8_the_decision_uses_the_re_read_after_the_lock_not_the_pre_lock_snapshot` | mine: RV06, RV07, RV07b |

`specs/shared/test-matrix.md` R47 DONE; R48 / R49 "NOT YET GREEN" with the integration halves DONE and the API halves named TODO for feature 31 (the route is feature 25's), as #8 did. Counts 3 / 0 / 2 for the section and 42 / 1 / 20 in total, re-derived row by row.

**Every "nothing changed" is a pre-attempt baseline** (brief Q6). `state_of` (`test_payment_register.py:61-71`) captures table counts for `payments`, `outbox`, `credit_items` and `invoices`, the whole invoice row, and the order's ledger. Every R48 / R49 / N3 assertion compares it to a capture taken before the attempt, and the controls make the baseline non-zero (`credit_items == 3`, `payments == 1` after a first payment).

**The races are held-lock constructions** (brief Q5). `Db.hold` opens a transaction holding `FOR UPDATE` on the credits row (`conftest.py:145-156`), and `wait_for_lock_waiters` polls `pg_stat_activity` for an ungranted lock and is bounded (`conftest.py:176-191`). The BI8 test probes the invoice row with `FOR UPDATE NOWAIT` while the request is parked on the line, then commits a competitor's payment. The cross-line test holds an uncommitted `payments` row so the request parks on the unique index. None relies on repetition or a sleep.

## 4. Fixtures (brief Q7)

The invoice is built through the real host (`make_world`: `billing.credit.hold`, then `billing.invoice.issue`): gross 8465, discount 350, net 8115. The payment equals the net. Another order holds 20 021 on the line, so available credit is 221 864 before and 229 979 after; neither equals the limit (250 000), the gross or the net. Production-site probes:

- **RV05**: `Invoice.mark_paid` compares the payment to the gross (`invoice.py:367`, `_total_amount` → `_amount`). Killed: the net payment answers `PAYMENT_MISMATCH`.
- **RV04**: `BuyerCredit.release` returns the limit as available-after (`buyer_credit.py:377`). Killed: `{'availableCreditAfter': 250000} != {'availableCreditAfter': 229979}`.

## 5. Mutations — verbatim results

Mine (`.arm/review22/mine.py`, `mine2.py`; logs `.arm/review22/logs/`):

| # | Mutation (site) | Family | Test | Result, first failing line |
|---|---|---|---|---|
| RV01 | swap `tx.invoices.mark_paid` / `tx.credits.save` (`payment_register.py`) | delete/order | broker test | FAILED: `R47: the broker delivered ['credit.approved.v1', 'invoice.issued.v1', 'credit.released.v1', 'payment.received.v1'] for the order` |
| RV02 | release `causation_id=fact.correlation_id` (the order id, a sibling of the request id) | sibling | R47 integration | FAILED: `#8 id 57: credit.released.v1's causationId is not payment.received.v1's eventId` |
| RV03 | release reason `ORDER_CANCELLED` | corrupt | broker test | **SURVIVED**: the broker test does not assert `reason` (it asserts order, key, partition, causation, `valueDate`, `availableCreditAfter`) |
| RV03b | same | corrupt | R47 integration | FAILED: `{'reason': 'order_cancelled'} != {'reason': 'invoice_paid'}` |
| RV04 | available-after = the limit (`buyer_credit.py:377`) | corrupt | R47 integration | FAILED: `{'availableCreditAfter': 250000} != {'availableCreditAfter': 229979}` |
| RV05 | domain compares the gross (`invoice.py:367`) | sibling | R47 integration | FAILED: `BC32: expected a payment reply (an outcome), got {'code': 'PAYMENT_MISMATCH', …}` |
| RV06 | `lock_for_order` first takes `SELECT id FROM invoices WHERE order_reference = :o FOR UPDATE` (`credit_repository.py:75`, infrastructure site) | order | BI8 race | FAILED: `BI8: the request holds the invoice row while it waits for the credits row (the lock order is inverted)` |
| RV07 | re-read called but the pre-lock snapshot used (`snapshot = (await tx.invoices.find_by_id(target.id)) and target`; the call log still matches) | defeat row 9 | BI8 race | FAILED: `BI8: the request acted on the invoice it read BEFORE the credits lock; got {'code': 'UNAVAILABLE', …}` |
| RV07b | same | defeat row 9 | unit BI8 decision test | FAILED: `Failed: DID NOT RAISE InvoiceAlreadyPaidError` |
| RV08 | `PAYMENT_REFERENCE_UNIQUE = "uq_invoices_order_reference"` (a sibling constraint) | sibling | cross-line race | FAILED: `R48: the UNIQUE backstop surfaced as {'code': 'INTERNAL_ERROR', …}` |
| RV09 | the payment INSERT's `flush()` removed from the `try` (the violation surfaces later, at the writer's flush) | delete | cross-line race | FAILED: `R48: the UNIQUE backstop surfaced as {'code': 'INTERNAL_ERROR', …}` |
| RV10 | duplicate reply `paid_at=None` (`_duplicate`) | corrupt | R48 sequential | FAILED: `R48: the duplicate did not carry the original paidAt` |
| RV11 | repository UPDATE writes `status="issued"` | corrupt | R47 integration | FAILED: `assert 'issued' == 'paid'` |
| RV12 | release names `invoice.invoice_reference.value` instead of the order (handler → `release` call site) | sibling | R47 integration | FAILED: `BC32: expected a payment reply …, got {'code': 'PRECONDITION_FAILED', …'credit.not_outstanding'…}` |
| RV13 | the two R49 codes swapped in `credit_rpc_errors.py` | sibling | R49 amount integration | FAILED: `R49: amount 8465 answered {'code': 'INVOICE_NOT_PAYABLE', …}` |
| RV14 | handler sends `replace(command, correlation_id=command.request_id)` (`handlers.py:83`, handler → unit call site) | sibling | R47 integration | FAILED: `assert 'f62c902e-…' == '3dd9ff5e-…'` (the facts' `correlation_id`) |
| RV15 / RV15b | payload `invoiceReference` = the order reference (`payloads.py:115`) | corrupt | R47 integration / broker | FAILED, but as `INTERNAL_ERROR`: the generated wire model's `INV-` pattern refuses the value, so the probe proves the model, not the assertion. Hence RV17 / RV18 with valid values |
| RV16 | the outbox writer's per-row `flush()` removed (`writer.py`) | ledger claim | R47 integration | **SURVIVED** — see N2 |
| RV17 / RV17b | payload `valueDate` = `occurred_at` (`payloads.py:119`) | corrupt (valid value) | R47 integration / broker | FAILED: `{'valueDate': '2026-10-10T04:58:21.489Z'} != {'valueDate': '2026-10-09T13:45:10.123Z'}`; broker `assert '2026-10-10T04:58:48.927Z' == '2026-10-09T13:45:10.123Z'` |
| RV18 | payload `amount + 1` (`payloads.py:118`) | corrupt (valid value) | R47 integration | FAILED: `{'amount': 8116} != {'amount': 8115}` |

The implementer's arms, re-run at random (`.arm/review22/random.out`): **H1b** (route → the `invoice.issue` handler) `R47: the payment route answered {'code': 'VALIDATION_FAILED', …}`; **G13** (snapshot currency `'EUR'`) `the payment came back as 8115 EUR`; **E8** (row amount + 1) `assert Money(…) == Money(…)`; **G4** (payment row not inserted) `R47: 0 payments rows for the paid invoice, not one`; **H3** (already-paid → `DOMAIN_ERROR`) `assert <Code.domain_error> is <Code.invoice_not_payable>`. 5 / 5 as recorded in the implementer's §7.3; each restored green.

**Both mutation families hit every fact-emitting branch** (the CLAUDE.md requirement). Deletion and ordering: RV01, plus the implementer's A3 and W1. Payload corruption on the wire with a valid value: RV17, RV18, RV03b, RV04. The guard reads the payload; it does not merely count rows.

## 6. Acceptance 2 — no internal payment timer (absence, re-run independently)

Population: `services/*/src`, `packages/*/src` (`generated/` and `__pycache__` excluded at the source by `--exclude-dir`), `n8n/workflows/*.json`; tests excluded (`grep -v /tests/`, the claim is about runtime code).

```text
$ grep -rnE --include=*.py --exclude-dir=generated --exclude-dir=__pycache__ "payment\.register|PAYMENT_REGISTER|RegisterPaymentCommand\(|payment_register\.register\(|\.mark_paid\(|PaymentReceived\(" services packages | grep -v "/tests/"
services/orders/src/otc_orders/application/saga/step_table.py:104:    order.mark_paid(occurred_at=fact.occurred_at)
services/billing/src/otc_billing/infrastructure/outbox/payloads.py:47:            | PaymentReceived()
services/billing/src/otc_billing/infrastructure/outbox/payloads.py:161:        case PaymentReceived():
services/billing/src/otc_billing/infrastructure/persistence/invoice_repository.py:10:  `billing.payment.register` (BI8, R48), fresh statements at the pinned `READ COMMITTED`; they
services/billing/src/otc_billing/application/payment_register.py:1:"""The remittance-intake transactional unit (`billing.payment.register`; R47 - R49, BI8, #8 id 57).
services/billing/src/otc_billing/application/payment_register.py:125:    fact = invoice.mark_paid(  # 4.
services/billing/src/otc_billing/application/payment_register.py:145:    await tx.invoices.mark_paid(  # 6. outbox row 1: payment.received.v1
services/billing/src/otc_billing/application/messages.py:190:# ------------------------------------------------------------------------ payment.register
services/billing/src/otc_billing/application/messages.py:212:class RegisterPaymentCommand(Command[PaymentRegisterResult]):
services/billing/src/otc_billing/domain/invoice.py:372:        fact = PaymentReceived(
services/billing/src/otc_billing/presentation/credit_responder.py:2:`.release`, `.list`, `billing.invoice.issue` and `.list`, and `billing.payment.register`; `BI31`).
services/billing/src/otc_billing/presentation/credit_responder.py:44:    PAYMENT_REGISTER_SUBJECT,
services/billing/src/otc_billing/presentation/credit_responder.py:130:    PAYMENT_REGISTER_SUBJECT: _payment_register,
services/billing/src/otc_billing/domain/invoice_events.py:58:class PaymentReceived(InvoiceEventBase):
services/billing/src/otc_billing/infrastructure/messaging/subjects.py:8:PAYMENT_REGISTER_SUBJECT = "billing.payment.register"
services/billing/src/otc_billing/application/errors.py:48:    """The invoice a remittance names does not exist (`billing.payment.register`): a contract
services/billing/src/otc_billing/application/ports/invoice_store.py:33:        `billing.payment.register`)."""
services/billing/src/otc_billing/application/ports/invoice_store.py:62:        """The identity resolution of `billing.payment.register`, outside any transaction."""
services/billing/src/otc_billing/presentation/payment_wire.py:1:"""`billing.payment.register` on the wire (`asyncapi.yaml` `PaymentRegisterRequest` / `Reply`).
services/billing/src/otc_billing/presentation/payment_wire.py:33:        raise InvalidPaymentRequestError(f"payment.register request is invalid: {error}") from None
services/billing/src/otc_billing/presentation/payment_wire.py:36:    return RegisterPaymentCommand(
services/billing/src/otc_billing/application/handlers.py:83:        return await payment_register.register(command, self._scope)
services/seed/src/otc_seed/domain/data/sagas.py:11:(`order:<seq>:command:orders.create` / `order:<seq>:command:payment.register`), and every other fact
services/seed/src/otc_seed/domain/data/sagas.py:413:    payment_received_causation_id = deterministic_id(f"order:{sequence}:command:payment.register")

$ grep -rnE --include=*.py --exclude-dir=generated --exclude-dir=__pycache__ "asyncio\.sleep|call_later|call_at|threading\.Timer|\bTimer\(|apscheduler|aiocron|croniter|schedule\.every|\bsched\b|import sched|crontab|setInterval|setTimeout|repeat_every|BackgroundScheduler" services packages | grep -v "/tests/"
services/orders/src/otc_orders/infrastructure/outbox/relay.py:150:                await asyncio.sleep(DEADLOCK_BACKOFF_SECONDS)
services/billing/src/otc_billing/infrastructure/outbox/relay.py:135:                await asyncio.sleep(DEADLOCK_BACKOFF_SECONDS)
services/fulfillment/src/otc_fulfillment/infrastructure/outbox/relay.py:135:                await asyncio.sleep(DEADLOCK_BACKOFF_SECONDS)
services/fulfillment/src/otc_fulfillment/infrastructure/persistence/stock_transactions.py:104:        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
services/orders/src/otc_orders/infrastructure/saga/command_dispatcher.py:72:        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,

$ node types per workflow (json parse of n8n/workflows/*.json)
1-order-generator.json ['n8n-nodes-base.code', 'n8n-nodes-base.scheduleTrigger']
2-payment-robot.json ['n8n-nodes-base.code', 'n8n-nodes-base.scheduleTrigger']
3-stock-replenishment.json ['n8n-nodes-base.code', 'n8n-nodes-base.scheduleTrigger']
4-burst.json ['n8n-nodes-base.code', 'n8n-nodes-base.webhook']
$ grep -lE "billing\.payment|nats" n8n/workflows/*.json
(no output)
```

Classification, one per hit:

- **Orders:** `step_table.py:104` is the Order aggregate's transition when it consumes the fact; a consumer, not a sender.
- **Billing:**
  - `payloads.py:47, :161` are the fact serialiser.
  - `invoice_repository.py:10`, `payment_register.py:1`, `messages.py:190`, `errors.py:48`, `invoice_store.py:33, :62`, `payment_wire.py:1`, `credit_responder.py:2` are docstrings or comments.
  - `payment_register.py:125, :145` are the one transactional unit's two `mark_paid` calls.
  - `messages.py:212` is the class statement.
  - `invoice.py:372` is the fact's construction inside `mark_paid`.
  - `invoice_events.py:58` is the class.
  - `credit_responder.py:44, :130` are the route import and the route entry.
  - `subjects.py:8` is the constant.
  - `payment_wire.py:33, :36` are the NATS request decoder (the only builder of the command).
  - `handlers.py:83` is handler delegation.
- **Seed:** `sagas.py:11, :413` are a docstring and a deterministic id string for historic fixtures; nothing is sent.
- **Pacing:**
  - The three `relay.py` hits are the outbox relays' deadlock back-off.
  - `stock_transactions.py:104` and `command_dispatcher.py:72` are injectable retry pacing for a stock transaction and a saga command.
  - None decides a payment.
- **n8n:** three workflows are schedule-triggered and one is a webhook. The only payer is `2-payment-robot.json`, the external bank, which posts over HTTP to `${OTC_GATEWAY_URL}/invoices/{id}/payments`. No workflow names NATS or Billing's subject.

**Sentinel (must be caught):** I planted `services/orders/src/otc_orders/zz_review_sentinel.py` (`await asyncio.sleep(3600)` plus `# sends billing.payment.register`) and `n8n/workflows/9-review-sentinel.json` (a `scheduleTrigger` plus `nats.request("billing.payment.register")`).

- My greps printed `zz_review_sentinel.py:5` and `:6` and the workflow file.
- The implementer's guard `unit/test_no_internal_payment_timer.py` went **3 failed, 2 passed**, naming the sentinel in each claim.
- After `rm` of both files: `5 passed`, and `ls n8n/workflows` shows the original four.

An auto-payer *inside* Billing, triggered by a consumer rather than a timer, falls outside this guard's subject claim (it skips `services/billing/`). Two other guards close that route: `test_kafka_client_confinement.py`'s consumer sentinel (Billing has no Kafka consumer) and `test_credit_subjects.py`'s exact route table. Acceptance 2 is met.

## 7. Defects and findings

**Blocking: none.**

**N1 — non-blocking, FIX NOW (light).** `services/billing/src/otc_billing/infrastructure/persistence/invoice_repository.py:132`: `if result.rowcount != 1:  # type: ignore[attr-defined]`. It is the only `type: ignore` in Billing's `src` (`grep -rn "type: ignore" services/*/src packages/*/src`: this line and `otc_seed/.../schema_check.py:23`, a different, untyped-call case). `session.execute(update(...))` is typed `Result[Any]`, and `rowcount` lives on `CursorResult`. This is a typing gap of the kind CLAUDE.md's porting questions name. Use a typed form instead, for example `.returning(InvoiceRow.id)` with `scalar_one_or_none() is None`, or a typed `cast(CursorResult[Any], …)`. Behaviour is unchanged and already guarded by B5 / G1. Re-run `test_mark_paid_on_an_invoice_that_is_not_issued_is_a_transient_failure_and_writes_nothing` and arm it once by dropping the `status == 'issued'` guard.

**N2 — non-blocking, FIX NOW (light, text only): a ledger claim over-attributed.**

- **Where:** `payment_register.py:18-19` ("step 6 happens before step 7, **and the outbox writer flushes per row**, so `payment.received.v1` gets the lower `seq`") and the impl record's §10 row "Emission order", which counts the writer's per-row flush as part of the mechanism.
- **The probe:** RV16 removed that flush and **survived** (R47's `seq`-order assertion stayed green).
- **Why:** on this path each `write()` call carries one event, other flushes intervene between the two calls, and SQLAlchemy's unit of work keeps add order. What supplies R47's ordering here is call order plus the `Identity` `seq`. The per-row flush matters only when one `write()` carries several events, which no Billing transaction does yet.
- **The property is supplied and guarded** (A1 / RV01 kill the swap at the outbox and at the broker). Only the attribution is wrong. That is the ported-idiom-ledger class: a claim nobody had probed.
- **Fix:** correct both texts to say which link carries the order on this path.

**N3 — informational, no action.** The broker test does not assert the release `reason` (RV03 survived there). The R47 outbox test asserts the whole `credit.released.v1` payload, including `reason` (RV03b and implementer E10b killed), so the property is guarded once at the right level.

**R1 — routing item for the leader (the half that depends on code not yet built; CLAUDE.md "carried, as an acceptance item on the feature that builds it").** Feature 25 `gateway_rest_auth` should gain this acceptance item:

> carried from billing_remittance_intake (id 22): `POST /invoices/{id}/payments` maps Billing's `RpcError`s to `openapi.yaml:673-675`: `INVOICE_NOT_PAYABLE` (details.code `invoice.already_paid`) → 409 `INVOICE_ALREADY_PAID`; `PAYMENT_MISMATCH` (details.code `invoice.payment_amount_mismatch` / `invoice.payment_currency_mismatch`) → 422 `PAYMENT_MISMATCH`; `PRECONDITION_FAILED` + details.code `payment.reference_reused` → 409 `PAYMENT_REFERENCE_REUSED`; `PRECONDITION_FAILED` + `credit.not_outstanding` → 409 `PRECONDITION_FAILED`. #8's classifier is not ported verbatim: its generic row answers `INVOICE_NOT_PAYABLE` as Problem code `INVOICE_NOT_PAYABLE` (`RpcErrorClassification.cs:75`), and its detail overrides key on upper-case codes (`:63-67`) that #9's dotted `details.code` never match. One test per row, armed by substituting a sibling code.

This is not rooted in `specs/shared/` (`openapi.yaml:673-675` is complete), so no `SA-n`.

**What must change before close:** N1 and N2 as one light batch, which the leader verifies by reading the diff and running the named tests; R1 filed by the leader. None of these gates the verdict.

## 8. Ported-idiom ledger (impl §10) — claims checked, not existence

| Row | Checked how | Holds? |
|---|---|---|
| Lock order credits → invoice; #7 `payment-register.handler.ts:125-145` (`lockForOrder`, then `lockById`), #8 `PaymentRegisterService.cs:83-90` (the same) — read in both checkouts | #9 takes no invoice row lock (feature 21's gated BI8 binding). Probed both ways: RV06 (an infrastructure-level inversion) is caught by the NOWAIT probe; RV07 (stale snapshot behind a matching call log) is caught by the guarded UPDATE → `UNAVAILABLE` ≠ `INVOICE_NOT_PAYABLE`. Every invoice write (issue's INSERT, pay's UPDATE) runs under the same credits-row lock, and the line is immutable on the invoice row | yes |
| Un-hinted in-tx re-read (#8 id 54) | `READ COMMITTED` pinned at `credit_transactions.py:116` and `invoice_reads.py:45, :50`; the concurrent R48 race (C2) proves the loser's fresh re-read sees the winner | yes |
| `mark_paid` returns its event (#8 id 57) | RV02 (a sibling id) killed; implementer A2 / A2b / A2c | yes |
| Emission order = call order + insertion order + per-row flush | RV01 killed at the broker; **RV16 shows the flush is not load-bearing here** | property yes, attribution no → N2 |
| UNIQUE backstop for a competitor the lock does not serialise | RV08 (sibling constraint name) and RV09 (flush outside the `try`) killed by the held-uncommitted-row race | yes |
| Reused reference is not a `duplicate` (#7 N11), extended to amount and currency | §2.2; C3 / C4 / C4b / C4c | yes |
| `release`'s `None` (#8 N3) refused | §2.1; D4 / D4b; RV12 drives the refusal through a sibling identifier | yes |
| Money: `int`, no `/` / `float` / `Decimal` | `grep -nE "float\|Decimal\| / "` over `payment_register.py`, `invoice_snapshot.py`: no hits; AST money guard inside `quality.sh` green | yes |
| JSON / instants (`wire_instant` before the `timestamptz(3)` column) | RV17 / RV17b (payload `valueDate`) killed; implementer H8 / G5 / E5 | yes |
| Event-loop affinity, cancellation | no new engine or pool; the race tests close their connections in `finally` (read) | yes (n/a by construction) |

## 9. `CHECKPOINTS.md`

**C1**
- [x] harness files exist (`init.sh` §1)
- [x] `progress/current.md`, `history.md`
- [x] seven agent definitions
- [x] every agent declares its model (`init.sh`: pinned or documented as unpinned)
- [x] `./init.sh` exit 0

**C2**
- [x] at most one `in_progress` (0)
- [x] statuses valid
- [x] every `done` feature has passing tests (3492 passed)
- [x] `current.md` names the active feature (`init.sh` §4; the body was not audited, which is the leader's)
- [x] no `blocked` feature without a reason (none touched)

**C3**
- [x] domain purity via `lint-imports` (11 kept, 0 broken; `invoice_snapshot.py` imports only `dataclasses`, `datetime`, Billing domain, `otc_shared_kernel`)
- [x] no cross-service DB or package import (independence contract kept; `git status --porcelain services/orders` shows only feature 19's two settings files, nothing of 22's)
- [x] shared runtime only in the three packages
- [x] no domain import of `otc_cqrs`
- [x] `dependencies = []` unchanged (no package touched)
- [x] no `float` / `Decimal` / `/` in money
- [x] Kafka-fact vs NATS-RPC: `billing.payment.register` is RPC (`saga.md:50`), the two facts go through Billing's outbox to Kafka
- [x] no stray debug or context-free TODO (`grep -nE "TODO|FIXME|print\(|breakpoint\(|pdb"` over the new sources: exit 1)

**C4**
- [x] `quality.sh` passes
- [x] application unit tests framework-free (fakes plus a rig; no DB or broker)
- [x] integration through testcontainers (real PostgreSQL, NATS, Kafka), passing with the developer stack down
- [x] coverage ≥ 80 % domain (98 %) and ≥ 60 % overall (97.47 %)
- [x] no Jest, Karma or Jasmine (web on Vitest, 1 / 1)

**C5**
- [x] no suspicious untracked files from this review (`.arm/` is git-ignored, `.gitignore:87`; the sentinels were removed)
- [x] `history.md` entry with the effort record (appended with this verdict)
- [x] `feature_list.json` 22 → `done`
- [ ] human told what was done and how to test it: the leader's, at the phase report
- [x] Claude did not commit

**C6:** n/a (`sdd: false`); R47 – R49 recorded in `test-matrix.md` with named tests [x].

**C7**
- [x] `specs/shared/` byte-identical except `test-matrix.md`'s Status column (`init.sh` §5d plus my keyed row compare)
- [x] no deviation needing an `SA-n` (§2: each departure follows the shared text)
- [x] R ids are #7's, and the realisation satisfies them
- [ ] n8n four workflows fire for real against the Python Gateway: not yet applicable (no Gateway; feature 25 / 33)
- [ ] black-box API script: feature 31
- [x] inherited findings accounted for (§10)
- [x] effort record honest (§10 and the history entry)
- [ ] README three-way section: wrap-up

## 10. Inherited findings and effort

- **#8 id 57** `completion_pair_has_no_causal_edge`: **avoided** (implementer A2 / A2b / A2c / E13, my RV02; live K3 shows `causation_id` = the payment's `event_id` for both orders).
- **#8 feature-22 review N1** (the same, as found in review): **avoided**.
- **#8 feature-22 review N2** (`valueDate` corruptible with the suite green): **avoided** (RV17, RV17b, implementer H8 / G5 / E5).
- **#8 feature-22 review N3** (`release` `None` discarded, the order strands at `paid`): **avoided** by refusal (§2.1).
- **#7 N11** (cross-invoice reuse answered as a success-shaped `duplicate`): **avoided** and extended to amount and currency per `openapi.yaml:673`.
- **#8 id 54** (the un-hinted re-read needs a ledger row): **avoided**.
- **#8 review A1, A2, A3:** **avoided**.
- **#8 N12 / N13:** did not recur (counts from command output; the live run completed both invoiced orders. `ORD-000007` at `confirmed` is feature 19's recorded fixture, not 22's).
- **Recurred, this run's own:** a ledger mechanism claim never armed (N2; the property itself held). This is the class the Phase 8 gate made binding, caught here by a probe of the claim rather than of the behaviour.

**Effort:**
- implementer ≈57 min (3 423 s, the leader's measurement, live walkthrough included);
- premise checks: implementer brief and review brief, ≈43 s for the latter (leader);
- review ≈23 min (brief 06:41:02 → verdict ≈07:04 CEST; 416 s of it `quality.sh`, arms 06:49 → 07:00).

**Total ≈1 h 21 min.** Against #8 ≈1 h 28 min (56 + 32; `../order-to-cash-dotnet/progress/history.md:1376-1386`, approved first pass, 0 blocking): **≈0.92×**. Against #7 ≈1 h 01 min (48 + 13; `../order-to-cash-nestjs/progress/history.md:943-946`, approved first pass, 0 blocking): **≈1.33×, not faster.**
