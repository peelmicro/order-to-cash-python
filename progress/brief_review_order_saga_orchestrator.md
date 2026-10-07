# Brief — reviewer, feature 16 `order_saga_orchestrator` (phase 8, `sdd: true`, full group, round 1)

**Task:** adversarially review feature 16 against its approved spec `specs/order_saga_orchestrator/{requirements,design,tasks}.md` (gate outcome G1–G3 in `design.md` §17.1; leader amendment A2' in §1), the shared spec (`specs/shared/saga.md` step table, R19–R29, `asyncapi.yaml`), CHECKPOINTS.md, and the implementer's record `progress/impl_order_saga_orchestrator.md`. Feature 16 is `in_review`. Write `progress/review_order_saga_orchestrator.md`. On APPROVED: set 16 to `done` (that line only) and append the effort entry to `progress/history.md` against #8 (`../order-to-cash-dotnet/progress/history.md` lines 821–871: 4 rounds, ≈8.7 h) and #7 (≈1 h 45 min + 35 min review, quoted there), naming every inherited #8 finding the spec maps (`design.md` §18) as avoided or recurred; classification: full group. On REJECTED: set 16 to `in_progress` and write "What must change", each item an instruction with the test and arm that will prove it. Round 1; one more round is allowed without asking the maintainer.

## What the leader established this session (with commands) — locate, do not trust

- The run was interrupted by a laptop reboot (≈09:12) that wiped `/tmp`; the implementer restored the one in-flight mutation (arm 3.9a, `kafka_fact_subscriber.py`) by an inverse edit verified against its transcript (no sha256 survived). Arming backups since then are in the repo-local, git-ignored `.arm/`.
- Reported: `./quality.sh` exit 0, 2350 passed (1883 + 467), stack down; 123 arm runs re-run after the last code change, all failed under mutation. 101/101 tasks ticked (leader counted). 14.2 done against the live stack, which the leader then stopped (no dev port listening; only `otcpy-n8n` up). The developer stack must stay stopped; never run two test runs at once against the same containers.
- The leader killed two orphaned pytest processes: the mutated runs of arms 3.9a/3.9b, which **hung** instead of failing (the implementer's account: the held handler blocked shutdown after the first assertion failed; its arm tool's timeout killed only the `uv` parent). It reports the test fixed, the tool not.

## Questions to rule on

1. **The SO9 offset contract** (aiokafka `seek` after a failed record; committed offset read from the broker; a genuine redelivery, #8 id 94) is the one silent-loss behaviour (`design.md` §5.3). Do the 3.9/3.10/3.12 tests fail — not hang — under each of their mutations now? Re-run them yourself with an outer timeout that kills the whole process group.
2. **Line order.** The record says order lines reload with no `ORDER BY` and one flake showed (arm 7.5's restored run); feature 13's design L15 says `rehydrate` sorts lines by id. Which is true, what flaked, and is any test or request payload order-dependent? A flake is a finding.
3. **Forced edits to feature 15's tests** (record "Edited" list, `test_orders_host_lifespan.py` assertions changed): did any edit weaken a feature 15 guard? Re-run feature 15's P1, P3, P4, P5, P8 arms (`progress/history.md` orders_acceptance entry gives each edit and failure) — they go stale when `composition.py` changes.
4. **G1 as built:** one task per command, max 256, overflow dropped to the durable row — is no-head-of-line-blocking proven at integration level (#8 ids 80/89) and the max armed (#8 id 90)? Trace context carried (L7)?
5. **Feature 42 boundary** (`requirements.md` §5): confirm 42 item 2 is delivered and item 1 half-delivered exactly as stated, so the leader can scope 42.
6. **#8's defect class** for this feature (4 rounds, each a fix nothing noticed reverted): mutate the code changed last, the call sites (consumer → dispatcher, enqueue inside the fact transaction, fast-path signal, sweeper claim, reply decode, compensation branches), and the step table rows. Report each mutation with its verbatim result. Restore by `cp` into `.arm/` + `cmp`, never `git checkout`/`restore`/`stash`.

## Bounds

Read-only except `progress/review_order_saga_orchestrator.md`, feature 16's status line and (on approval) `progress/history.md`. Backups in `.arm/` with a recorded sha256, never `/tmp`. No git command that writes the index or working tree. Return only "result in `progress/review_order_saga_orchestrator.md`" plus the verdict and at most 5 lines.
