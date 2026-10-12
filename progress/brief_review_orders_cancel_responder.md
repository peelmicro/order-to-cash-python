# Brief — reviewer, feature 41 `orders_cancel_responder` (phase 13, full group — saga, round 1)

**Task:** approve or reject feature 41 (`in_review`), with backlog 213's acceptance item 2 (no #9 test or document cites `saga.md` §2 as `credit.release`'s source). Inputs: `progress/impl_orders_cancel_responder.md` (200 lines), its brief `progress/brief_impl_orders_cancel_responder.md` (the Must-hold list is your checklist, with `feature_list.json` id 41's **six** acceptance items), the premise check `progress/premise_impl_orders_cancel_responder.md`, and the working tree (features 25 and 40 are `done` and uncommitted in the same tree; review feature 41's change: `services/orders/**` including `alembic/versions/0002_saga_commands_operator_note.py`, the Gateway test it retired, and the architecture literals the record names). CLAUDE.md on disk is binding — grep before quoting.

## Already settled by the leader

- **Real Fulfillment answers a lost `stock.release` with `PRECONDITION_FAILED`** (record §2 q5, §10): inherited parity, not a finding — #8 `src/Fulfillment/Domain/StockItem.cs:123-130` and #7 `apps/fulfillment/src/domain/stock-item.ts:146` throw the same terminal-reservation error (`domain-model.md` F4). Check only that Orders treats it as the terminal end of a lost race (no retry, no park, no `order.saga_failed.v1`, no `credit.release`).
- **The envelope carry** (record §10 first bullet) is filed as feature 27's acceptance item 12.
- **The migration `0002`** is the implementer's answer to question 2; it is in scope to review (additive? reversible? does it collide with feature 27's planned columns? is the live `otc_orders` at `0002` registered?).

## Prove or refute, with a scratch test (not committed) — the leader goes to the gate on it

**The stranded reservation** (record §10 second bullet): `saga.md` §4.3 cancels a `placed` order at once ("nothing acquired"), but once the saga has processed `order.placed.v1` a `stock.reserve` row exists (pending, sent, or parked against a down Fulfillment) while the order is still `placed`. If the operator cancels then, the `stock.reserve` is still dispatched, Fulfillment reserves, and `stock.reserved.v1` reaches a `cancelled` order and is ignored (R25) — so the reservation is never released. Construct it against the real code (testcontainers; a held or parked `stock.reserve` is enough), in `.arm/r41/`, and record: is it reachable, what is left in Fulfillment's stock at the end, and what #7 and #8 do in the same window (cite their code: does either's cancel at `placed` withdraw the pending `stock.reserve` row, or release on a late `stock.reserved.v1`?). Do not fix it; do not count it against feature 41 unless feature 41's own code made it reachable when the predecessors' did not.

## Where to push hardest

1. **SA-4's order on the wire** (acceptance 3) observed at real or stand-in responders over real NATS; transpose the two; credit-only; despatch-wins.
2. **The `stock.release` reason on both paths** (#8 D1) asserted on the observed request; transpose the arms.
3. **The accepted-operator-cancel query** (acceptance 5, #8 id 91): `find_accepted_operator_cancel` keys on `command = 'stock.release'` and `payload->>'reason' = 'order_cancelled'` with no status filter. Substitute each sibling identifier yourself (`stock.reserve` / `despatch.create` / `credit.release`, `credit_rejected`, another order id, the `operator_note` column for `payload`) and confirm a decoy row makes the `false` cases fail for the right reason. Is "no status filter" right — e.g. a `rejected` operator release (despatch won) still marks the cancellation accepted, so a later `credit.approved.v1` releases a hold the shipping order still needs? Trace that case against `saga.md` §4.3 *The despatch wins* ("No `credit.release` is issued — the hold still backs an order that is shipping").
4. **The race, both outcomes** (acceptance 5, #8 id 62): constructed with a held lock; remove the cancel's `FOR UPDATE` and confirm a test fails.
5. **The late `credit.approved.v1`** (acceptance 3): no transition, no `order.confirmed.v1`, no `despatch.create`; inverted preconditions; a late approval for a `credit_rejected` cancel stays out.
6. **The note** (acceptance 4): every starting status, every hand-over (Gateway → responder → `saga_commands.operator_note` → completing fact → `order.cancelled.v1` → timeline); never on a wire payload that does not declare it.
7. **Acceptance 6** (the retired Gateway 503 test and its replacement in `services/orders/tests/integration/saga/test_cancel_through_gateway.py`): does the replacement drive the real Gateway over real NATS against a subject nobody serves, and does deleting the Gateway's no-responder mapping fail it?
8. **Key sets from the schema** (#8 D2) for `OrdersCancel*` and `CreditRelease*`, both ways.
9. **The surviving arm the implementer fixed** (the `credit.release` dispatch event hidden by the sweeper): is the new test the right guard, and are there sibling dispatch events where the sweeper hides the same deletion?
10. **Backlog 213 item 2:** `grep -rn "saga.md" services/orders progress/impl_orders_cancel_responder.md | grep -n "§2\|section 2"` and classify each hit.

## Process

Arm on copies in `.arm/r41/` (backup + `sha256`, `cmp` restore, clear caches; a timeout kills the process group). Read-only: no source or test edit outside `.arm/`, no index-writing git command. The developer stack is stopped; you may use it for a live check (start, then stop what you started; it holds the implementer's altered live data — read §9 of the record). Run `./quality.sh` once at the end (developer stack down): exit code, pytest time and pass count (implementer: 4 675 passed in 543.68 s).

## Output

`progress/review_orders_cancel_responder.md`: verdict; blocking findings (surviving mutation + remedy); non-blocking with a disposition; your arming table; the stranded-reservation result (reachable or not, the residue, #7's and #8's behaviour with citations); #8 D1, D2, ids 62, 63, 71, 91 avoided / recurred. APPROVED → feature 41 `done`; REJECTED → `in_progress` (that line only). Return only "result in `progress/review_orders_cancel_responder.md`" plus the verdict and at most 4 lines.
