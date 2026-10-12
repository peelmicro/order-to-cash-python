# Proposal `SA-8` — a stock reservation that arrives after an operator cancellation is released (backlog 216)

**Status:** proposed by the leader, Phase 13 (2026-10-12), for the maintainer's gate. Not applied.

## The defect

`specs/shared/saga.md` §4.3's generalisation table says an operator cancel at `placed` has acquired **nothing** and releases nothing (*"Operator cancels while `placed` | (nothing) | (nothing) | cancel `operator_cancelled`"*). That is false once the orchestrator has processed `order.placed.v1`: step 1 (§3.1, line 67) has issued `stock.reserve` while the order stays `placed` (*"the fact, not the command response, moves it"*). If the operator cancels in that window:

1. the cancel moves the order to `cancelled` (`operator_cancelled`) at once, with no compensation;
2. the `stock.reserve` already owed is still dispatched — the dispatcher sends commands without reading the order;
3. Fulfillment reserves and emits `stock.reserved.v1`;
4. that fact reaches a `cancelled` order, whose precondition `placed` is unmet, so it is ignored (R25; §6's redelivery row for `stock.reserved.v1`);
5. no `stock.release` is ever requested, Fulfillment has no expiry, and the units stay reserved for good.

The window is wide, not a microsecond race: a `stock.reserve` parked against an unavailable Fulfillment keeps it open for as long as the outage lasts.

**Evidence.** Disclosed by #9's feature 41 implementer (`progress/impl_orders_cancel_responder.md` §10); **reproduced** by its reviewer against the real Orders host over real NATS, Kafka and PostgreSQL (`progress/review_orders_cancel_responder.md` N1; `.arm/r41/stranded.out`: `stock.reserve` dispatched again after the cancel, `stock.reserved.v1` recorded `precondition_unmet`, end state `command rows: [('stock.reserve', 'sent')]`, `stock.release requests: []`, `1 passed in 12.48s`). **#7 and #8 behave the same** (leader-verified): #8 `src/Orders/Application/Commands/CancelOrderCommandHandler.cs:157-169` cancels at `placed` with `compensationSteps: []` and leaves the owed `stock.reserve` alone, and `SagaStepTable.cs:181-186` gives `stock.reserved.v1` one variant, precondition `Placed`; #7 `apps/orders/src/application/cancel-order.handler.ts:118-131` and `saga-steps.ts:173-178` the same.

## Why the fix is a release on arrival, not withdrawing the command

Withdrawing the owed `stock.reserve` at cancel time closes only the `pending` half: a `sent` request may already be at Fulfillment (step 4 of the reproduction). The only point that sees every case is the arrival of the reservation's fact — exactly how `SA-4` handled the same shape for credit (*"A credit approval that arrives after the cancellation"*, §4.3). This proposal is that paragraph's stock counterpart.

## The change (three edits to `saga.md`, prose only)

**1. §4.3, a new paragraph after *"A credit approval that arrives after the cancellation"*:**

```markdown
**A stock reservation that arrives after the cancellation.** An operator
cancellation of a `placed` order acquires nothing *yet*, but once
`order.placed.v1` has been processed a `stock.reserve` is already owed and may
already be at Fulfillment, so the reservation can still be made. A
`stock.reserved.v1` for an order already `cancelled` with reason
`operator_cancelled` issues `stock.release` (reason `order_cancelled`) and
**nothing else**: no transition, no `credit.hold`. The reservation was
acquired, so it is unwound. That release is not one of the cancellation's
recorded compensation steps; it reaches the timeline as its own
`stock.released.v1`.
```

**2. §5, the `stock.reserved.v1` row's Orchestrator cell:**

`✅ → `stock_reserved`, issue `credit.hold`` → `✅ → `stock_reserved`, issue `credit.hold`; for an order already cancelled by its operator, issue `stock.release` only (§4.3)`

(the same form `SA-4` gave the `credit.approved.v1` row).

**3. §6, the `stock.reserved.v1` redelivery row:** add to *What happens*: `At `cancelled` with `operator_cancelled`: §4.3 — `stock.release` (re-)issued; the command is idempotent on `(orderReference, release)` and the responder no-ops (**F5**, R34) without a second `stock.released.v1``.

## What is deliberately not changed

- **R25 and the R-numbers.** `SA-4`'s late-credit rule changed `saga.md`, `openapi.yaml` and `asyncapi.yaml` only (README registry row `SA-4`), not `requirements.md`; this follows that precedent. R25 already lists its preconditions by reference to the step rows, and §4.3's late-arrival rules are stated where the saga's preconditions are.
- **No schema, subject or payload**: `stock.release` with `reason: order_cancelled` already exists (`asyncapi.yaml` `StockReleaseRequestPayload`; #9's `map_release_reason`).
- **`stock_rejected` / `credit_rejected` cancellations** are untouched: a `stock.rejected.v1` means nothing was reserved (R26, F3), and a `credit_rejected` order passed `stock_reserved`, so its reservation's fact already arrived.

## Recommendation

**Approve `SA-8`**: the spec half byte-identically in #7, #8 and #9 (one `spec(SA-8): …` commit each at the wrap-up, a registry row in each README, an entry in each `progress/history.md`); the **code half in #9 in this phase** as backlog 216 (implementer → Opus reviewer: the reproduction committed as a test that fails first, both mutation families, the `stock_rejected` / `credit_rejected` decoys, redelivery idempotency). For **#7 and #8 the code half is your call**: they are complete, so my recommendation is the spec only, with their registry rows stating that their code predates `SA-8` (as #7's did for `SA-4` until #8's backlog 79 aligned it) — say so if you want either aligned now.
