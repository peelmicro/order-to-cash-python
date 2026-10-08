# Brief — implementer, feature 17 `fulfillment_stock` (phase 9, `sdd: true`, full group)

**Task:** implement feature 17 from its approved spec, `specs/fulfillment_stock/{requirements,design,tasks}.md`, task by task in `tasks.md` order (A1 → L6). The maintainer approved the spec on 2026-10-08 with gate points G1, G2 and G3 decided **as recommended** (`design.md` §16.1, the "Gate record" paragraph). Feature 17 is `in_progress` (set by the leader). **`tasks.md` outranks this brief**: if anything here conflicts with a task, stop and report the conflict.

## What changed since the spec was written

- Nothing under `services/`, `packages/` or `tests/` (premise-checked: `progress/premise_impl_fulfillment_stock.md`); only the spec, progress files and `feature_list.json`'s status line are uncommitted.
- **Task L4's "id 101 attachment for feature 29" is already satisfied**: `feature_list.json` feature 29's acceptance item "inherited criteria: #8 ids 98, 100, 101, 102, 103, 106" carries it. Record that line in the report; do not edit feature 29.
- **Baseline:** read it fresh as task A2 says. Do not take it from this brief.

## Process

- Follow `tasks.md`'s header exactly: the arming protocol, the defeat-list rows, the files you may and must not touch. Grep `CLAUDE.md` on disk for the arming protocol before the first arm: backups go **into the repo-local, git-ignored `.arm/`** with a `sha256` recorded (never `/tmp` or a scratchpad); restore from the backup with `cmp`, never `git checkout`; a timeout kills the whole process group, never only the `uv` parent; clear `__pycache__` / `.mypy_cache` after a restore.
- #8 needed three review rounds for this feature, with two blocking defects of one shape (`../order-to-cash-dotnet/progress/history.md` from line 999); #7 was rejected once because an unplanned fifth mutation survived (`../order-to-cash-nestjs/progress/history.md` line 842). For every fix and every guard, ask **"what fails if I revert this?"** before you tick it.
- Before declaring done, list every branch of each hand-built loop or adapter (the responder task: cancel, bound, per-request fault, reply-send raises, shutdown drain; `StockTransactions.run`: 40P01 re-run, re-run exhausted, non-deadlock error; the relay copy: send raises, stop-on-failure) and name the test that drives each (tasks D3 and F5 ask for this for the first two; for the relay copy, name the Orders test that drives each branch of the canonical, which C3's parity guard makes binding on the copy).
- Every multi-claim test gets one mutation per claim; every negative assertion gets a control row.
- Integration suites must pass with the developer stack down. It is stopped (only `otcpy-n8n` runs) and stays stopped until section K. Never run two test runs against the same containers at once. Run section K only after every container-backed suite has passed; start the stack with `docker compose -p otcpy -f docker-compose.infra.yml start`, and when K5 is done, stop everything you started so that only `otcpy-n8n` runs again (record `docker ps` before and after).
- Do not edit `feature_list.json` beyond feature 17's status line, nor `CLAUDE.md`, `progress/current.md`, or `specs/` beyond what `tasks.md` names. No git command that writes the index or working tree.

## Output

`progress/impl_fulfillment_stock.md`, structured as task L4 requires. Set feature 17 to `in_review` (that line only, task L6). Return only "result in `progress/impl_fulfillment_stock.md`" plus at most 5 lines: the `quality.sh` exit code and pass count against A2's baseline, the number of `[ARM]` rows armed and seen red, any task left unticked, and any deviation from the design.
