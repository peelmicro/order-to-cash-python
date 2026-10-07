# Requirements — `orders_aggregate` (feature 13)

> **This is a pointer document, not new specification.** Assessment #9 inherits `specs/shared/` verbatim (copied from #8, with `SA-1` to `SA-5` applied). The requirements this feature realises, **R5 – R10**, were written in #7 and are binding here with the same ids. Nothing in this file amends, reinterprets or extends them; where the Python realisation needs a decision the shared spec does not take, that decision lives in [`design.md`](./design.md) as a design decision, never as a requirement.
>
> Quoting convention: every requirement below is reproduced verbatim from `specs/shared/requirements.md` §1 (lines 89–115). The only alteration is line-unwrapping (CLAUDE.md, *Markdown* row). No word, emphasis or id differs.

---

## 1. The requirements this feature realises

Six requirements, all provable by pure domain unit tests (`specs/shared/requirements.md` §1: *"All of these are provable by pure domain tests — no store, no broker, no framework"*).

### R5 — no empty orders (invariant O1)

> **R5.** IF an order is created with no lines, or its last remaining line is removed, THEN THE SYSTEM SHALL raise a domain error and SHALL NOT persist the order (invariant **O1**).

**Realised here as:** `Order.place` refuses an empty line sequence and `Order.remove_line` refuses to remove the last line, both raising `OrderMustHaveAtLeastOneLineError` (`order.must_have_at_least_one_line`). "SHALL NOT persist" holds structurally: an `Order` with no lines cannot be constructed, so no repository is ever handed one. `Order.rehydrate` applies the same check on every load (`design.md` §8). Same reading as #7 (`apps/orders/src/domain/order.ts:128-130, 336-338`) and #8 (`src/Orders/Domain/Order.cs:109-112, 318-321`).

### R6 — totals are derived and never negative (invariant O3)

> **R6.** WHEN any line of an order is added, removed or modified, THE SYSTEM SHALL recompute the order's initial amount as the sum over lines of `unitPrice × quantity`, its initial discount as the sum of line discounts plus any order-level discount, and its total amount as `initialAmount − initialDiscount`; and IF the resulting total amount is negative, THEN THE SYSTEM SHALL raise a domain error and leave the order unchanged (invariant **O3**).

**Realised here as:** the three totals are read-only properties recomputed by one pure function over a *candidate* line tuple, committed only if the candidate total is not negative (candidate-then-commit, `design.md` §5). The order-level discount term is `Money.zero(currency)`, exactly as in #7 (`order-totals.ts:25`) and #8 (`Order.cs:534`); refusing a non-zero `orderDiscount` on the wire is feature 15's (`design.md` §5.4).

### R7 — lines are frozen from `confirmed` onwards (invariant O4)

> **R7.** IF a line addition, removal or modification is attempted while the order status is `confirmed`, `despatched`, `invoiced`, `paid`, `completed` or `cancelled`, THEN THE SYSTEM SHALL raise a domain error and SHALL leave every field of the order unchanged (invariant **O4**).

**Realised here as:** `_ensure_lines_mutable()`, the first statement of every line mutator, refuses unless the status is in the literal allow-list `{placed, stock_reserved, credit_approved}` (#7's form, `order.ts:104`), raising `OrderLinesAreFrozenError` (`order.lines_are_frozen`) before any structural check, so removing the last line of a `confirmed` order raises the frozen error and not the empty-order error (`design.md` §6.2).

### R8 — only the edges of Table T-1

> **R8.** THE SYSTEM SHALL permit an order status change only along an edge listed in Table T-1 of `domain-model.md` §3.3, SHALL treat `completed` and `cancelled` as terminal, and SHALL allow `cancelled` to be reached from `placed`, `stock_reserved`, `credit_approved` and `confirmed` only.

**Realised here as:** the eleven status-to-status edges of Table T-1 (rows 2–12; row 1 is creation) are encoded once, as a `frozenset` of `NamedTuple` edges, and the aggregate exposes no method that lets a caller name a target status (`design.md` §4). Terminality needs no code: `completed` and `cancelled` never appear as a source.

### R9 — an illegal transition raises, changes nothing, appends nothing

> **R9.** IF an order status change is attempted along a `(from, to)` pair absent from Table T-1, THEN THE SYSTEM SHALL raise a domain error, SHALL leave the status and every other field unchanged, and SHALL append no domain event to the aggregate.

**Realised here as:** the private `_transition_to` is the only mutator of the status after construction, and it consults the edge set before it assigns anything, stamps anything or raises any event. The named test drives all 72 attemptable pairs (9 sources × 8 targets) and asserts the three legs separately on each of the 61 illegal ones (`design.md` §4.4).

### R10 — cancellation carries an immutable reason from the closed set (invariant O6)

> **R10.** WHEN an order transitions to `cancelled`, THE SYSTEM SHALL require a cancellation reason drawn from `{stock_rejected, credit_rejected, operator_cancelled}`, SHALL record it immutably on the order, and SHALL emit `order.cancelled.v1` carrying it; and IF no reason is supplied, THEN THE SYSTEM SHALL raise a domain error and SHALL NOT change the status (invariant **O6**).

**Realised here as:** a closed `CancellationReason` enum, a read-only `cancellation_reason` assigned inside `_transition_to`'s accepted branch (#7 `order.ts:421-424, 450`; #8 `Order.cs:436-439`, after #8's advisory A2), and an `OrderCancelled` event that reads the reason **from the aggregate's state**, so an assignment moved out of the accepted branch makes the event wrong and the test fail. "IF no reason is supplied" is reachable in Python at the method itself (a `None` passes at run time whatever the annotation says), so `cancel` refuses `None` (`order.cancellation_reason_required`) and a non-member (`order.cancellation_reason_unknown`) before touching anything, as #7 does (`order.ts:402-407`); the wire-token parse at the boundary raises the same two codes, as #8's does (`CancellationReason.cs:44-58`). The reason↔status pairing of Table T-1's *Trigger* column is enforced on the aggregate (#7's OA4, `order.ts:414-419`; #8 `Order.cs:459-465`). The optional operator `note` of `SA-2` (`asyncapi.yaml` `OrderCancelledPayload.note`) is carried on the event (`design.md` §7.3).

---

## 2. Requirements this feature depends on but does not close

| Id | Owner | Standing for this feature |
|---|---|---|
| **R1** | `shared_kernel` (feature 7) | Domain half `DONE`, API half ratified-scoped to feature 31. Every amount on this aggregate is the kernel's `Money`; this feature adds no monetary representation. |
| **R2** | `shared_kernel` (feature 7) | `DONE`. Invariant **O2** is enforced on this aggregate by an explicit per-line, per-field currency check, but the rule is R2's; no new id (`requirements.md` §9 maps M2 → R2). |
| **R3**, **R4** | `shared_kernel` (feature 7) | `DONE`. `Quantity` and `GLN` used as-is. |
| **R11**, **R12**, **R13** | `outbox_and_idempotency` (feature 14) | This feature *produces* the domain events and fixes their `event_id`, `aggregate_id`, `correlation_id`, `causation_id` and `occurred_at` when the aggregate raises them (`domain-model.md` §7.1). It writes no outbox row and serialises nothing. |
| **R19** – **R29** | `order_saga_orchestrator` (feature 16) | The status built here is the saga state (`domain-model.md` §3.1). This feature makes each T-1 transition expressible and every other one refused, and nothing more. `order.saga_failed.v1` (R29) is not built here, as in #7 and #8 (`design.md` §13). |

---

## 3. New requirements: none

**This feature introduces no new `R<n>`** and no local `OA<n>`. R5 – R10 cover it, and the Python realisation satisfies each in the same sense #7's and #8's do; that is what reusing the ids asserts, and `design.md` §2 (the ported-idiom ledger) is where each "same sense" is checked rather than assumed.

**No spec amendment is proposed.** `SA-6` is not used by this feature. (`feature_list.json` id 201 mentions a tentative "likely an SA-6" for the phase-12 causation question; that number stays free for whichever amendment is raised first.) Every question below was checked against `specs/shared/` and against #7's and #8's code before being written down, and none is a defect of the shared spec:

| # | Question | Answer, and where it comes from | Realised in |
|---|---|---|---|
| 1 | O8 says a successful transition appends exactly one event, but T-1 names a fact on only seven rows and the catalogue is closed at fourteen. | T-1 governs: the five silent edges emit nothing. #7 `order-transitions.ts:36,42,54,60,66` (`emits: null`) and `order.ts:452`; #8 `Order.cs:159-194` (`buildEvent: null`). | `design.md` §7.4 |
| 2 | `orders` has no `order_discount` column, yet R6 adds "any order-level discount". | The term is `Money.zero(currency)`; a non-zero wire value is refused by the place-order handler. #7 `order-totals.ts:25`, `place-order.handler.ts:67-68`; #8 `Order.cs:534`. | `design.md` §5.4 |
| 3 | `order_items` has no ordering column, yet §3.1 says lines are an "ordered list". | Line order is observable only on `order.placed.v1`, built from the in-memory aggregate. #7 leaves the load unordered (`order.repository.ts:217-228`); #8 sorts by line id in `Rehydrate` (`Order.cs:394`). #9 sorts by line id. | `design.md` §8.4 |
| 4 | `orders` has no version column. | No concurrency token on the aggregate; feature 16 owns the lock. Same in #7 and #8 (#8 `design.md` §8.6). | `design.md` §9 |
| 5 | Should a load re-check O3 (a non-negative total)? | Yes. #7's `reconstitute` derives totals through `computeOrderTotals`, which throws on a negative total (`order.ts:216` → `order-totals.ts:36-38`); #8's `Rehydrate` derives them without that check (`Order.cs:395`, `RecomputeTotals` at `:523-539` has none). #9 follows #7: the acceptance item says *"rehydrate validates its invariants on every load"*, and O3 is one. Observable only on a corrupt row. | `design.md` §8.2 |

---

## 4. Invariant coverage

| Invariant | Requirement | Enforced by | Load path (`rehydrate`) |
|---|---|---|---|
| **O1** at least one line | R5 | `place`, `remove_line` | refused, own test |
| **O2** single currency | R2 | `_require_line_currency`, on place, add, change | refused per field, own tests |
| **O3** totals derived, `total ≥ 0` | R6 | `compute_totals` + candidate-then-commit | totals derived (no parameter exists), negative refused, own tests |
| **O4** lines frozen from `confirmed` | R7 | `_ensure_lines_mutable` | n/a (no mutation on load) |
| **O5** only legal transitions | R8, R9 | `LEGAL_EDGES` + `_transition_to` | bypassed by design (restores a produced state), own test |
| **O6** reason iff cancelled, immutable | R10 | `cancel`, `_transition_to` | both halves of the biconditional refused separately, plus member type |
| **O7** terminal states | R8 | absence of outbound edges | n/a |
| **O8** events accompany state | R9, R11 | `_transition_to` raises only after acceptance, on the seven fact rows | `rehydrate` raises nothing, own test |

---

## 5. Traceability

Rows R5 – R10 of `specs/shared/test-matrix.md` §1 belong to this feature and are `TODO`. This spec pass flips no Status cell; the implementer flips a row (column 5 only) when the named test exists and has been observed green.

Matrix paths map onto #9 as `orders/domain/<name>.spec` → `services/orders/tests/unit/domain/test_<name with underscores>.py`. The intended names are fixed here so the reviewer can check the mapping mechanically:

| Id | #9 file | #9 case names |
|---|---|---|
| **R5** | `services/orders/tests/unit/domain/test_order.py` | `test_r5_order_refuses_to_create_an_order_with_no_lines_and_to_remove_the_last_remaining_line` |
| **R6** | `services/orders/tests/unit/domain/test_order_totals.py` | `test_r6_order_recomputes_initial_amount_initial_discount_and_total_amount_after_each_mutation`, `test_r6_order_rejects_a_mutation_whose_resulting_total_amount_would_be_negative_and_leaves_the_order_unchanged` |
| **R7** | `services/orders/tests/unit/domain/test_order.py` | `test_r7_order_refuses_to_add_remove_or_modify_a_line_once_the_order_is_confirmed_and_leaves_every_field_unchanged` |
| **R8** | `services/orders/tests/unit/domain/test_order_state_machine.py` | `test_r8_order_walks_every_legal_edge_of_table_t1`, `test_r8_order_reaches_cancelled_only_from_placed_stock_reserved_credit_approved_and_confirmed`, `test_r8_order_treats_completed_and_cancelled_as_terminal` |
| **R9** | `services/orders/tests/unit/domain/test_order_state_machine.py` | `test_r9_order_raises_on_every_from_to_pair_absent_from_table_t1_without_mutating_state_or_appending_an_event` |
| **R10** | `services/orders/tests/unit/domain/test_order_cancellation.py` | `test_r10_order_requires_a_reason_from_the_closed_set_records_it_immutably_and_carries_it_on_order_cancelled_v1`, `test_r10_order_raises_when_no_cancellation_reason_is_supplied_and_does_not_change_the_status`, `test_r10_order_refuses_a_cancellation_reason_table_t1_does_not_pair_with_the_current_status` |

The naming shape `test_r<n>_<subject>_<what it proves>` is the one `shared_kernel` set for R1 – R4 (`packages/shared_kernel/tests/test_money.py`). Tests that guard a design decision rather than a shared requirement carry no `r<n>` prefix and are listed in [`tasks.md`](./tasks.md).

---

## 6. Points for the human gate

One decision closed at the gate and one flagged for visibility. Everything else was closed on evidence from #7's and #8's checkouts (§3 above and the ledger in `design.md` §2).

**OP-1 (closed at the gate, 2026-10-06: the kernel, as in #7 and #8): where the money-text formatter lives.** `OrderTotalMustNotBeNegativeError`'s message reaches a human (feature 15's responder → the Gateway's problem `detail`), and #7's backlog id 102 is the defect of rendering it as raw minor units. Both previous builds render it with a shared money-text formatter: #7 `packages/shared-kernel/src/domain/money-text.ts` (used at `apps/orders/src/domain/order-errors.ts:65`, guarded by `domain-error-money-text.spec.ts`), #8 `src/SharedKernel/MoneyText.cs` (used at `src/Orders/Domain/Errors/OrderTotalMustNotBeNegativeError.cs:21`). #9 has one copy today, in the seed's domain (`services/seed/src/otc_seed/domain/money_text.py:11-19`), which service independence forbids Orders to import; `progress/impl_shared_kernel.md:44` recorded that #8's `MoneyText` was not ported to the kernel in feature 7 because it "belongs to the presentation boundary / phase 16". The maintainer ruled at the gate that #9's earlier note does not reopen a placement #7 and #8 agree on.

**Decided:** move `format_money` into the kernel as `otc_shared_kernel/money_text.py` (a pure function over the SA-5 exponent table, which CLAUDE.md names as the kind of thing the kernel may hold), port the seed's vectors to a kernel test, and make the seed import it from the kernel, deleting the seed's copy. One copy, the placement both previous builds chose, and Billing's errors (feature 18 onwards) reuse it. `tasks.md` §1 (tasks 1.4–1.7) implements it.

**Decision flagged for visibility (not open): a naive or non-UTC `datetime` is a domain error, `order.instant_not_utc`.** #7's `Date` and #8's `DateTimeOffset` cannot be naive, so neither build had to decide this; a Python `datetime` without `tzinfo` type-checks under `mypy --strict` and would be silently interpreted as local time by any later conversion. Every instant parameter of the aggregate refuses it (`design.md` §2 row L13, §7.5). It is the one error code with no #7/#8 counterpart, and it is listed in the error table (`design.md` §10) so the population test counts it.
