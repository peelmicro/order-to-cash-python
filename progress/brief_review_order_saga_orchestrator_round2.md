# Brief — reviewer, feature 16 `order_saga_orchestrator`, round 2 (the last round without asking the maintainer)

**Task:** verify the round-2 rework against your round-1 "What must change before re-review" (items 1–6) using the "Round 2" section of `progress/impl_order_saga_orchestrator.md`. Append a "Round 2" section to `progress/review_order_saga_orchestrator.md`. Re-run, do not re-read: every arm of items 1–3 and your own round-1 survivors (RS hard-codings one at a time, RL-b, RL-c, and the `try_claim` / `claim_due` halves). Then probe the new tests themselves, because #8 lost rounds 2–4 of this feature to repairs nothing guarded (`../order-to-cash-dotnet/progress/history.md` lines 821–871).

## Specific checks

1. **Planted state (impl Round 2):** removing `status` from `claim_due`'s parked branch first survived because the API cannot reach that state (`mark_sent` nulls `next_attempt_at`); the implementer then planted the state by hand. Rule on it: is that a guard of a reachable property, a guard of an invariant worth keeping (e.g. against a future write path), or defeat-list row 12 in reverse, a test of a path production never drives? Accept, rewrite or drop, with the reason.
2. **`src/` untouched** (reported). Confirm it with a search for any `services/orders/src` file whose mtime falls after round 1's review, and check that the round-1 `src` state is what is under test.
3. **Duration:** `./quality.sh` reported **441 s** (stack down), against 193 s at feature 15's close and the ~125 s Phase 7 threshold. Time the pytest part, or read `--durations`, and say what took the time (new saga integration modules, Kafka rebalance delay, machine load). The threshold is the maintainer's at wrap-up; the cause is yours to establish.
4. The arm tool now kills the process group (reported, kill path not exercised). If you use it, prove the kill once with a deliberately hanging run; otherwise use your own killable group.

## Outcome

On APPROVED: set 16 to `done` (that line only) and append the effort entry to `progress/history.md` exactly as the round-1 brief (`progress/brief_review_order_saga_orchestrator.md`) specifies, both rounds included, plus the session incidents in the record (the reboot restore of arm 3.9a; the orphaned arm processes). On REJECTED: set 16 to `in_progress` and write "What must change"; the leader then asks the maintainer. Bounds as in round 1 (backups in `.arm/`, never `/tmp`; developer stack stopped). Return only "result in `progress/review_order_saga_orchestrator.md` (Round 2)" plus the verdict and at most 5 lines.
