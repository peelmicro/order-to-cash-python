# Current session

**Feature:** none — Phase 7 closed, awaiting Phase 8
**Status:** idle
**Session started:** —

## Goal

## Decisions taken this session

## Blockers

## Notes

**Brief for phase 8 — Orders service + saga orchestrator (step 13).** Six features, in `feature_list.json` order: **13 `orders_aggregate` (sdd)**, 43 `cqrs_dispatcher`, **14 `outbox_and_idempotency` (sdd)**, 15 `orders_acceptance`, **16 `order_saga_orchestrator` (sdd)**, 42 `orders_saga_terminal_rejection_classification`. #8's most expensive phase (≈19 h 54 min on the comparable subset against #7's ≈11 h 18 min, plan) and the one with the most inherited findings. One session per phase may not hold all six: close a feature cleanly (state, history entry) before the session ends.

- **First action:** feature 13 is `pending` + `sdd: true` → one `spec_author` writes `specs/orders_aggregate/{requirements,design,tasks}.md` → **stop at the human gate**. The same for 14 and 16 when their turn comes. Per CLAUDE.md, go to each gate with a recommendation and evidence (check what #8 and #7 did first), never a menu; and never forbid in a brief what the approved `tasks.md` mandates.
- **Process:** full for all six (saga, money domain, persistence, wire contract). `premise_checker` over every brief; Opus reviewer. At most one rejection round without asking.
- **New rules from the Phase 7 gate (2026-10-05):** (1) **findings are fixed in the phase that detects them** — no backlog entry for a fix whose code exists; only the half needing unbuilt code is carried, as an acceptance item on the feature that builds it (CLAUDE.md). (2) `quality.sh` threshold **~125 s** (stack stopped); wrap-up run 103.24 s, 1 290 passed. (3) When a syntax guard loses twice, propose a change of kind (allow-list from a census, or a behaviour test) and a stopping rule before the next round — the Phase 7 sweep lost three rounds before doing so.
- **Carried into Phase 8 features (read their last acceptance items):** feature 14 has 205 (instant truncation through the outbox path) and 203's generic-Envelope half (`model_dump_json` and `to_wire_json` both refuse an unvalidated payload; list-held instants). Feature 15 inherits 211's counters (`services/*/…/persistence/sequences.py`: the no-scan `MAX` seed is already there — the allocator only needs the lock-and-advance in the caller's transaction) and 204(d)(e) are already done (orders settings: no password default, no `populate_by_name`).
- **Guards Phase 8 will meet:** `tests/architecture/test_write_path_population.py` fails on any new unclassified write path in `services/*/src` — classify each new writer in its `EXPECTED` counter; the range guard (207) refuses a non-Integer SQL expression, so write `Model.col + 1` with an Integer type; the money guard is an import allow-list (`collections, dataclasses, datetime, hashlib, types, typing, uuid` + first-party) and forbids the names `pow`, `float`, `round` in any domain — a new stdlib import in a domain is a deliberate allow-list edit whose census test fails until something uses it.
- **#8's baselines:** `../order-to-cash-dotnet/progress/history.md` — orders_aggregate :629, cqrs_dispatcher :676, outbox_and_idempotency :730, orders_acceptance :773, order_saga_orchestrator :821, terminal_rejection_classification :872 (each quotes #7's figure). Every inherited #8 finding gets **avoided / recurred** in the effort entry.
- **Plan items to honour** (Plan Phase 8): `rehydrate` validates invariants on every load; every dispatcher guard armed before review; relay `FOR UPDATE SKIP LOCKED` with skip-versus-block **measured**, self-scheduled `asyncio.sleep`, deadlock victim and poison payload inside `run_once` (#8 ids 87, 111); `processed_events` keyed `(event_id, consumer)`; `success | RpcError` decoded explicitly; sweeper must not re-claim a row it holds; fast path without head-of-line blocking and with trace context; nine of twelve error codes terminal; a live `order.placed.v1` compared with the golden envelope.
- **Commits:** one per feature; each spec commit before its implementation commit.

---

## Template (reset to this on session close)

```markdown
# Current session

**Feature:** `<name>` (id <n>, phase <n>)
**Status:** <status>
**Session started:** <date>

## Goal

## Decisions taken this session

## Blockers

## Notes
```
