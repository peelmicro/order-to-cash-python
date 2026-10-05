# Current session

**Feature:** none — Phase 6 closed, awaiting Phase 7
**Status:** idle
**Session started:** —

## Goal

## Decisions taken this session

## Blockers

## Notes

**Brief for phase 7 — Seed job (step 12).** One feature, id 12 `seed_job` (`sdd: false`). Process: **full** — it writes all four databases plus MongoDB and its whole value is parity, so implementer → reviewer (Opus), `premise_checker` over the brief.

- **Acceptance** (`feature_list.json` id 12, 5 items): `deterministic_id(ns)` = SHA-256 of `"otc-seed:" + ns` reshaped to a UUID, **reproducing #7's skipped hex index 12** (commented so nobody "fixes" it); `make_gln` / `make_ean13` with real check digits; the same 3 currencies, 12 products, 7 retailers, 22 companies, 215 stock rows, 154 credit lines (plan Phase 7) — counts are claims to re-derive from #8's seed, not to copy; the sample completed and cancelled orders with their `order_timeline` documents, `headerComplete`, `statusRank` and `processedEventKeys` **values** tested; idempotent second run; no `uuid4()`/`now()` in seeded values.
- **Parity against #8's live databases** needs the maintainer's authorisation at the gate (only one trilogy stack runs at a time: `otcnet` up means `otcpy` down). Isolate the seeded subset first, **dump rows to files and diff them** — never a server-side aggregate and a hash (#8 Phase 7: `STRING_AGG` truncated, `GROUP_CONCAT` cut at 1 024 bytes, a non-UTF-8 client printed `Aldi Espa?a`). #8's seed: `../order-to-cash-dotnet/src/Seed/`; its Phase 7 reports `progress/impl_seed_job.md` / `review_seed_job.md` (#8 was REJECTED once, D1 — read it first); #7's `deterministic.ts`.
- **What Phase 6 hands over:** four Alembic histories (`services/{orders,fulfillment,billing,notifications}/alembic`), models under each `infrastructure/persistence/`, the range guard on every integer column (ORM unit of work only — a Core/ORM-enabled `insert()` bypasses it, backlog 204(a); the seed is the first bulk writer, so it must classify its write path against 204(a)'s list or call `ensure_in_range`), the root `conftest.py` (one Docker-held `postgres:18.6` per session, template databases per service, fresh database per test), the four-database parity test in `tests/database_parity/`. MongoDB has no fixture yet — the seed is its first writer: `testcontainers.community.mongodb`, ports held by Docker, loop scope written beside the fixture (PyMongo async).
- **Money in the seed:** `int` minor units into `bigint`; #8 id 44 deleted every narrowing cast in its seed — there is nothing to narrow in Python, but `/` on a money path is still forbidden (AST guard covers `domain` and `shared_kernel` only — ask whether the seed's money code is in its population).
- **Open backlog touching this phase:** none attached to `seed_job`. 205 (instant ms rounding vs truncation) is attached to feature 14, but seeded instants are written by the seed first — ask whether seeded `occurred_at` values have sub-ms parts (#8's seed uses fixed instants).
- **Gate time — threshold CROSSED at the Phase 6 wrap-up:** the leader's wrap-up run (stack stopped, `/usr/bin/time`) took **99.8 s** whole-script, pytest 68.2 s (the maintainer's run at 14:46: pytest 62.1 s; review_db_billing A1: 84.6 s) — load moves it by several seconds, but it is past the ~90 s threshold. The maintainer chose to commit first; Phase 7 owns the fix before adding its MongoDB container. A MongoDB container joins in this phase, so cut first and then measure; the lever named in review_db_billing A1 is the three counter-seed sentinels' round count (prove any reduction by a change of kind, not of probability).
- **Baselines** (`../order-to-cash-dotnet/progress/history.md`, `seed_job` entry, lines ~511–513): #7 1 session, "~0.5h — implementation ~22 min, review ~1h" (the figure and its parts disagree as #8 recorded them — quote both, do not reconcile); #8 ~1.9h, REJECTED once (D1), approved on the second round.
- **Commit:** `seed_job`.

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
