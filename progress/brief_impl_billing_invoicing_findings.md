# Brief — implementer, feature 21 `billing_invoicing`, review findings N1 – N5 (LIGHT)

**Task:** close N1 – N5 of `progress/review_billing_invoicing.md` §6 (lines 147 – 151), exactly as written there. Classification **light** (CLAUDE.md, Cost discipline: docs, comments and one test assertion): no separate reviewer; the leader reads the diff and re-runs the affected tests. Feature 21 is `done`; do **not** change `feature_list.json` (the leader already filed R1 on feature 22).

## What to do

1. **N1 (spec text):** in `specs/billing_invoicing/design.md` §6.2 ("Why the line is locked first") and §13.3, and `specs/billing_invoicing/tasks.md` F6's parenthetical, state the outcomes the code actually produces, as the review observed them: F6 → `PRECONDITION_FAILED` (consume precedes the insert); I1 → `PRECONDITION_FAILED`, `INTERNAL_ERROR` (23505) or `UNAVAILABLE` (40001 on the counter row the winner updated); every outcome safe. Remove the claim that `REPEATABLE READ` cannot raise 40001 here. Cite the review's F6-repro row and the impl report's I1 rows as the evidence.
2. **N2 (spec text):** `design.md` §5.2, ledger row L41, §16.2 and `requirements.md` BI23's #9 note: replace "`@final`" with the runtime refusal (`__init_subclass__` raises `TypeError`, armed by B2d), and record the ruling: **the maintainer is told; the census allow-list is not extended** (review §4.7: mypy accepts a subclass but class creation raises; exhaustiveness does not depend on `final`).
3. **N3 (test):** in `tests/architecture/test_billing_rpc_error_retryability.py`, assert that every `DOMAIN_ERRORS` input's mapped code is in Orders' `TERMINAL_RPC_ERROR_CODES` (imported, never retyped), failing with a message naming the error class. **Arm:** Q6f (`case DomainError()` → `Code.internal_error` in Billing's `credit_rpc_errors.py` / the invoice mapper, wherever the review's Q6f applied it) must fail in the architecture file, naming the class. Backups in `.arm/bc21f/` with `sha256`; restore by `cp` + `cmp`; clear `__pycache__` / `.mypy_cache`; timeouts kill the whole process group.
4. **N4 (test comments):** (a) `services/billing/tests/integration/test_invoice_issue.py:389`; (b) `services/billing/tests/integration/test_invoice_issue_race.py`'s header — reword as the review says.
5. **N5 (docstring):** `services/billing/src/otc_billing/infrastructure/persistence/credit_repository.py:19-21` — add the outbox relay's `update(Outbox)` stamp (`outbox/relay.py:162`) to the exceptions it names. Docstring only.

## Bounds

Edit only the files named above, plus a "Review findings" section appended to `progress/impl_billing_invoicing.md`. No production behaviour change. Do not start the developer stack. No git command that writes the index or working tree. Run the retryability test file, plus `ruff check`, `ruff format --check` and `mypy` on every Python file you touched.

## Output

Return only "result in `progress/impl_billing_invoicing.md` § Review findings" plus at most 4 lines: the N3 arm's message, and the test results.
