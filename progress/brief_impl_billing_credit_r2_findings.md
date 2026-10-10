# Brief — implementer, feature 19 `billing_credit`, review round 2 findings R2-1 – R2-3 (LIGHT, test-only)

**Task:** fix R2-1, R2-2 (option **a**) and R2-3 exactly as `progress/review_billing_credit.md` § R2.6 (line 238 onwards) instructs. Classification **light** (CLAUDE.md, Cost discipline: test-only fix): no separate reviewer; the leader reads the diff and re-runs the tests. Feature 19 is `done`; do **not** change `feature_list.json`.

## Bounds

- Edit only `tests/architecture/test_outbox_copy_parity.py` (the instrument, its docstring's premises list and its sentinels). No production file, no other test file.
- Append a section "Review round 2 findings (R2-1 – R2-3)" to `progress/impl_billing_credit.md`.
- No git command that writes the index or working tree. The developer stack stays stopped.

## What to do

1. **R2-1:** the canonical operand's preamble must be `""` and its closing-line tail blank, failing with a message naming `orders` and the module. Add a sentinel parametrised over a preamble and a tail on the canonical.
2. **R2-2 (a):** widen the import cross-check's population to the scan's (`infrastructure/**/*.py` minus `__init__.py`), and update P6 in the docstring to match.
3. **R2-3:** one sentinel, parametrised over both copy services: a comment-only tail (`"""  # ruff: noqa`) fails naming the file.
4. **Arms, each run exactly as § R2.6 describes:** D2i and D2h (on Orders' `infrastructure/outbox/relay.py`), D3g (`Table("out" + "box", MetaData())` in a new `otc_notifications/infrastructure/messaging/tables.py`, deleted afterwards), IM1 (the tail check made to ignore comments). Each must go RED with a message naming its claim, then green after restore. Protocol: backups in `.arm/bc19r2f/` with `sha256`; restore by `cp` + `cmp` (a created file is deleted and its absence confirmed); clear `__pycache__` and `.mypy_cache`; timeouts kill the whole process group.
5. Run `uv run pytest tests/architecture/test_outbox_copy_parity.py -q`, `uv run ruff check` + `ruff format --check` on that file, and `uv run mypy` on it. A full `./quality.sh` is not needed for this light change; the leader decides.

## Output

Return only "result in `progress/impl_billing_credit.md` § Review round 2 findings" plus at most 4 lines: the test count of the file before and after, and each arm's RED / green.
