# Brief — implementer, feature 19 `billing_credit` (phase 10, `sdd: true`, full group)

**Task:** implement feature 19 from its approved spec, `specs/billing_credit/{requirements,design,tasks}.md`, task by task in `tasks.md` order (A1 → L4). The maintainer approved the spec on 2026-10-08 with the one gate point, **G1, decided as recommended**: a zero-amount `credit.hold` is approved and `release` / `consume` read "outstanding" by `BC11` / `BC12`, so `BC38` stands (`progress/spec_billing_credit.md` § Gate ruling; `design.md` §16.1). Feature 19 is `in_progress` (set by the leader). **`tasks.md` outranks this brief**: if anything here conflicts with a task, stop and report the conflict.

## What changed since the spec was written

- Nothing under `services/`, `packages/` or `tests/`; only `specs/billing_credit/`, progress files, `progress/current.md` and feature 19's status line in `feature_list.json` are uncommitted (premise check: `progress/premise_impl_billing_credit.md`).
- **Baseline:** read it fresh as task A2 says. Do not take it from this brief.

## Process

- Follow `tasks.md`'s header exactly: the arming protocol, the files you may and must not touch, the forbidden constructs. Grep `CLAUDE.md` on disk for the arming protocol before the first arm: backups go **into the repo-local, git-ignored `.arm/`** with a `sha256` recorded (never `/tmp` or a scratchpad); restore from the backup with `cmp`, never `git checkout`; a timeout kills the whole process group, never only the `uv` parent; clear `__pycache__` / `.mypy_cache` after a restore.
- **#8 was rejected once on this feature, with four blocking defects, all guards** (`../order-to-cash-dotnet/progress/history.md` line 1215). The sharpest: a mutation that `tasks.md` prescribed was never actually run, and the guard turned out decorative. **Run every prescribed mutation exactly as written**, and record its verbatim failure.
- **Feature 17's rejection in this repository** was three mutations that survived the whole suite: a lock method's read order, the id port at the application → domain seam, and one refusal branch. Task J1 exists for this; do it as a search result first, then one mutation per call site.
- For every fix and every guard, ask **"what fails if I revert this?"** before you tick it. Assert values read back through the adapter, never values the test recomputes. A guard's failure message must name its claim (no unpack-before-assert, no bare `TimeoutError`); assert a reply's discriminating field before touching any collection in it.
- Construct races with a held lock (`wait_for_lock_waiters`), never by repetition.
- Ruff formats Python blocks inside Markdown: any code quoted in `progress/impl_billing_credit.md` is quoted formatted.
- **Runs:** integration suites must pass with the developer stack down. It is stopped (only `otcpy-n8n` runs) and stays stopped until section K. Never run two test runs against the same containers at once; wait on a PID, never on `pgrep -f`. Run section K only after every container-backed suite has passed; start the stack with `docker compose -p otcpy -f docker-compose.infra.yml start`, and when K5 is done stop everything you started so that only `otcpy-n8n` runs again (record `docker ps` before and after).
- Do not edit `feature_list.json` beyond feature 19's status line, nor `CLAUDE.md`, `progress/current.md`, or `specs/` beyond what `tasks.md` names. No git command that writes the index or working tree.

## Output

`progress/impl_billing_credit.md`, structured as task L4 requires. Set feature 19 to `in_review` (that line only). Return only "result in `progress/impl_billing_credit.md`" plus at most 5 lines: the `quality.sh` exit code and pass count against A2's baseline, the number of `[ARM]` rows armed and seen red, any task left unticked, and any deviation from the design.
