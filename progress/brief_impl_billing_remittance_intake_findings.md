# Brief — implementer, feature 22 `billing_remittance_intake`, review findings N1 – N2 (LIGHT)

**Task:** close N1 and N2 of `progress/review_billing_remittance_intake.md` §7, exactly as written there. Classification **light**, chosen by the leader and recorded: N2 is text only; N1 changes the typed form of one persistence statement with **no behaviour change**, guarded by an existing test plus one arm. No separate reviewer; the leader reads the diff and re-runs the affected tests. Feature 22 is `done`; do **not** change `feature_list.json` (the leader filed R1 on feature 25).

## What to do

1. **N1:** remove the `# type: ignore[attr-defined]` on `rowcount` at `services/billing/src/otc_billing/infrastructure/persistence/invoice_repository.py:132` with a typed form — the review suggests `.returning(<the id column>)` with `scalar_one_or_none() is None`, or a typed `cast(CursorResult[Any], …)`; prefer the one that keeps the statement's behaviour byte-for-byte (same `WHERE`, same refusal when no row matches). Then re-run `test_mark_paid_on_an_invoice_that_is_not_issued_is_a_transient_failure_and_writes_nothing` and **arm it once** by dropping the `status == 'issued'` guard: it must fail naming the claim; restore by `cp` + `cmp`. Backups in `.arm/bc22f/` with `sha256`; clear `__pycache__` / `.mypy_cache`; timeouts kill the whole process group. Confirm `grep -rn "type: ignore" services/billing/src` is empty afterwards. Note: `tests/architecture/test_write_path_population.py` classifies this `update(` — if the change to `.returning(...)` alters what that guard sees, re-run it and report; do not edit the guard without saying so.
2. **N2:** correct `services/billing/src/otc_billing/application/payment_register.py:18-19` and the "Emission order" row of `progress/impl_billing_remittance_intake.md` §10 to say what carries R47's ordering on this path (call order plus the `Identity` `seq`; the writer's per-row flush matters only when one `write()` carries several events, which no Billing transaction does yet — review RV16).

## Bounds

Edit only `invoice_repository.py` (that statement), `payment_register.py` (the docstring lines), and `progress/impl_billing_remittance_intake.md` (the §10 row plus an appended "Review findings" section). No other file. Do not start the developer stack. No git command that writes the index or working tree. Run `services/billing/tests/integration/test_invoice_payment_repository.py`, `services/billing/tests/integration/test_payment_register.py`, `tests/architecture/test_write_path_population.py`, plus `ruff check`, `ruff format --check` and `mypy` on the two source files.

## Output

Return only "result in `progress/impl_billing_remittance_intake.md` § Review findings" plus at most 4 lines: the N1 form chosen, the arm's message, and the test results.
