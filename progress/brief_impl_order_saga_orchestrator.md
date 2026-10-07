# Brief — implementer, feature 16 `order_saga_orchestrator` (phase 8, `sdd: true`, full group)

**Task:** implement feature 16 from its approved spec, `specs/order_saga_orchestrator/{requirements,design,tasks}.md`, task by task in `tasks.md` order. The maintainer approved the spec on 2026-10-06 with gate points G1, G2 and G3 decided as recommended (`design.md` §17.1, first paragraph). Feature 16 is `in_progress` (set by the leader). **`tasks.md` outranks this brief**: if anything here conflicts with a task, stop and report the conflict.

## What changed since the spec was written

- **Amendment A2' (leader, 2026-10-07, `design.md` §1 and §2, `tasks.md` file list):** feature 15 put the lifespan in `otc_orders/main.py`, not `presentation/app.py`. The import-linter contract `fact-producer-confinement` forbids presentation from reaching aiokafka through the composition root. The owned tasks are created in `composition.start_runtime`. Task 0.1 checks A1–A7 against feature 15 as it stands; read A2 as amended.
- **Feature 15 is closed** (`progress/review_orders_acceptance.md`, rounds 1–2, and the leader's round-3 closure in `progress/history.md`). Its boot path stops and awaits every task it created on any failure, cancellation included (D-1, R2-D1, R2-D2, R2-D4). Its D-6 guard derives the boot probe from every registered handler of all three kinds through `HandlerRegistry`'s public read accessor. Your registrations go through that path. The ten fact commands and five events must pass it, and so must any new task you add to `start_runtime` (§12.1's three tasks join the same stop-and-await and readiness rules).
- **Baseline:** read it fresh as task 0.2 says. Do not take it from this brief.

## Process

- Follow `tasks.md`'s header exactly: the arming protocol, the defeat-list rows, the files you may and must not touch. Keep arming backups in your scratchpad or another persistent directory, **never bare `/tmp`**, and record a `sha256sum` before each mutation. A session break in this phase lost a reviewer's `/tmp` backups.
- #8 needed four review rounds for this feature (`../order-to-cash-dotnet/progress/history.md` lines 821–871). Each round was a fix that nothing noticed being reverted. For every fix and every guard, ask "what fails if I revert this?" before you call it done.
- Integration suites must pass with the developer stack down. It is stopped and stays stopped. Never run two test runs against the same containers at once.
- Do not edit `feature_list.json` beyond feature 16's status line, CLAUDE.md, `progress/current.md`, or `specs/` beyond what `tasks.md` names.

## Output

`progress/impl_order_saga_orchestrator.md`, structured as `tasks.md` 14.x requires: per-task evidence, the arming table with verbatim failures, the defeat-list rows, the ledger halves verified, #8's findings marked avoided or recurred, and the figures with commands. Set feature 16 to `in_review` (that line only). No git writes. Return only "result in `progress/impl_order_saga_orchestrator.md`" plus at most 5 lines.
