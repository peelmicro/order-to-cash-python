# Brief — implementer, feature 13 `orders_aggregate` (phase 8)

**Task:** implement `specs/orders_aggregate/` (approved at the human gate on 2026-10-06) by working through `specs/orders_aggregate/tasks.md` in order, ticking each box as it is done. The spec is the authority: where this brief and the approved `tasks.md` disagree, the spec wins — stop and report the conflict rather than picking a side silently.

## Inputs

- `specs/orders_aggregate/requirements.md` (R5–R10 pointer; §6: OP-1 is closed — `format_money` moves to the kernel, tasks 1.4–1.7).
- `specs/orders_aggregate/design.md` (ledger §2, error table §10, test design §11, arming §12).
- `specs/orders_aggregate/tasks.md` — its preamble lists the files this feature may touch. That list is the bound; nothing outside it.
- Feature 13 in `feature_list.json` is `in_progress` (set by the leader).

## Process (full group: money domain)

- Every `[ARM]` task: run the CLAUDE.md arming protocol (cp backup, introduce the mutation, run the ONE named test, record the failure verbatim, restore from the backup, confirm with `cmp`, clear `__pycache__`/`.mypy_cache`, re-run green). Never `git checkout`/`restore`/`stash`. Record each arm (mutation, test, verbatim failure line, restore `cmp` result) in a table in the report.
- Run the defeat list (CLAUDE.md) against your own guards and state which rows apply to which guard.
- Before finishing: `./quality.sh` — record its exit code, duration and pass count, and whether the `otcpy` stack was up (`docker ps`; it is up as this brief is written — do not start or stop it, the leader owns that); and `uv run pytest` over the orders, shared_kernel and seed test directories you touched — counts copied from the command output, per-file figures summing to the headline (this is #8's advisory A1).
- Ported-idiom ledger: for any row whose guard ended up different from `design.md` §2, say so in the report.

## Output

- `progress/impl_orders_aggregate.md`: what was built, every file touched, the arming table, the defeat-list rows, the test/quality figures with the commands that produced them, and every place you diverged from the spec and why.
- Set feature 13's status to `in_review` (edit only that line; you are the only writer of `feature_list.json` while you run).
- Do not edit `specs/` except ticking `tasks.md` boxes and what `tasks.md` itself mandates there (task 6.6: the Status cells of rows R5–R10 and the coverage counts in `specs/shared/test-matrix.md`, nothing else in `specs/shared/`). No git command that writes the index or working tree; no commit.
- Return only: "result in `progress/impl_orders_aggregate.md`" plus at most 5 lines (test count, quality.sh exit/time, any conflict or divergence).
