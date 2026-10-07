# Brief — implementer, feature 13 `orders_aggregate`, review round 1 rework (test-only)

**Task:** close defects D1–D3 of `progress/review_orders_aggregate.md` (§6, with the mutations in §4.1 and the required changes in §7) by doing the three new tasks the leader added to the approved `specs/orders_aggregate/tasks.md`: **3.22** (`place` keeps every field; arms PL1, PL2), **4.17** (every event payload field; arms P1–P4 plus `OrderConfirmed.order_reference` and the `OrderCancelled` `retailer_code` ↔ `company_code` swap), **5.12** (`rehydrate` restores every field, `notes` non-`None`; arms R1–R4). Tick each box when done.

## Bounds

- Test-only. Expected files: `services/orders/tests/unit/domain/**` (including its `conftest.py` if a fixture needs distinct or non-`None` values), plus `progress/impl_orders_aggregate.md`. No production edit is expected; if a test reveals a real production defect, stop and report it rather than fixing it.
- Fixtures must not satisfy the relation by accident: pairwise-distinct values for every field asserted (CLAUDE.md).
- Arming protocol as before (cp backup, mutation, ONE named test, verbatim failure naming the field, restore, `cmp`, clear `__pycache__`/`.mypy_cache`, re-run green). Never `git checkout`/`restore`/`stash`.
- Leader changes already made this round, do not redo: `pyproject.toml` `[tool.ruff] extend-exclude = ["specs"]` (F4, armed by the leader); the wording of tasks 3.12 and 4.16 (F5); feature 15's new acceptance item (F7).

## Output

- Append to `progress/impl_orders_aggregate.md` a "Review round 1 rework" section: the tests added, one arming row per mutation, updated per-file counts that sum to the headline, and one `./quality.sh` run (exit code, duration, pass count, and whether the `otcpy` stack was up — do not start or stop it).
- Set feature 13 to `in_review` (only that line of `feature_list.json`).
- Return only "result in `progress/impl_orders_aggregate.md`" plus at most 4 lines.
