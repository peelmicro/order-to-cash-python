# Current session

**Feature:** none — Phase 5 closed, awaiting Phase 6
**Status:** idle
**Session started:** —

## Goal

## Decisions taken this session

## Blockers

## Notes

**Brief for phase 6 — SQLAlchemy models and Alembic migrations (steps 9–11).** Three features, ids 9 → 10 → 11, in that order; one `in_progress` at a time. Process: **full** (persistence) — implementer, then reviewer on Opus; `premise_checker` over each brief before dispatch.

- **`db_orders` (id 9):** async Alembic template (no sync driver), PostgreSQL types per the plan (`uuid`, `timestamptz(3)`, `bigint` money, identity `outbox.seq`, **`json` not `jsonb`** payloads — CLAUDE.md), `orders.request_id` unique accepting many NULLs, foreign keys as a closed set read from `pg_constraint`, `order_number_sequences` seeded with `ON CONFLICT DO NOTHING` under a concurrent-first-caller test, and — routed from `review_shared_kernel.md` D8 — every quantity column's range enforced at the write boundary (the kernel's `Quantity` is unbounded by design). Inherits #8 ids 44 and 45.
- **`db_fulfillment` (id 10)** and **`db_billing` (id 11):** read their `acceptance`; `db_billing` owns the outbox/`processed_events` parity across all four databases, read from `information_schema`/`pg_indexes`, never from SQLAlchemy metadata.
- **Test-harness conventions first used here** (CLAUDE.md Testing): testcontainers from `testcontainers.community.*`; container ports held by Docker, never picked free (#8 id 85); each async fixture's loop scope written beside it and the engine disposed in that scope (the pytest default is `function`, `pyproject.toml`); **integration suites must pass with the developer stack down** (#8 id 104) — `docker compose -p otcpy down` before the run that proves it; never two runs against the same containers.
- **Warnings policy:** `error::DeprecationWarning` plus `error::starlette.exceptions.StarletteDeprecationWarning` (Starlette's deprecations are UserWarnings — found in phase 5). A new library that warns through its own non-`DeprecationWarning` class needs the same treatment, measured, with the reason beside the filter.
- **Phase 5 residuals that are NOT phase 6 work:** id 202 (kernel surface guard, attached to `orders_aggregate`), id 203 (every JSON path of a wire model, attached to `outbox_and_idempotency`), feature 16's SO8 criterion, feature 31's R1 API half.
- **Baselines** (`progress/history.md` of each sibling): #7 ~1.5h / ~1.25h / ~0.75h; #8 ~2.3h (one rejection on fidelity) / ~0.55h / ~0.75h.
- **Commits:** `db_orders`, `db_fulfillment`, `db_billing`, one each.
- **Phase 5 pattern to carry:** every defect in phase 5 (six review defects and one leader finding across three features) was in a *guard* or a *serialisation path*, never in the domain code — and two of them were the same class: a check whose population was narrower than the rule (a deny-list that missed `bson`; a member check that missed dunders; a single serializer that was not the only path to bytes). For persistence, ask of every guard: which tables, which columns, which databases does it actually read?

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
