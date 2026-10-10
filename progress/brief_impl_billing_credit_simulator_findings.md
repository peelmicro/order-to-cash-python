# Brief — implementer, feature 20 `billing_credit_simulator`, review findings N1 – N3 (LIGHT)

**Task:** close N1, N2, N3 and the record corrections RC1, RC2 of `progress/review_billing_credit_simulator.md` (lines 115 – 135; Q1 for N1's fix and arm). Classification **light** (CLAUDE.md, Cost discipline: test-only plus record): no separate reviewer; the leader reads the diff and re-runs the affected tests. Feature 20 is `done`; do **not** change `feature_list.json`.

## What to do

1. **N1:** in `services/billing/tests/integration/test_credit_simulator.py` (lines 136 – 152), make the lifespan refusal test fail **within seconds, naming R43 and the offending value**, when the boot does not refuse: e.g. monkeypatch the composition root's NATS connect with a `pytest.fail("R43: … booted with CREDIT_FAILURE_RATE=…")`, as Q1 describes. **Arm:** the clamp mutation (review R16 / impl A13: `_parse_failure_rate` clamps instead of refusing) must now fail that test quickly with a message naming R43; record the verbatim message and duration, restore with `cp` + `cmp`, re-run green. Backups in `.arm/bc20f/` with `sha256`; timeouts kill the whole process group.
2. **N3:** reword the `billing_host` docstring at `services/billing/tests/integration/conftest.py:377` to "the default (simulator, rate 0) adapter", as the review says.
3. **N2 (record):** in `progress/impl_billing_credit_simulator.md`'s ported-idiom ledger (lines 23 – 33), write in the file-and-line citations the review gives for each row, and add the two missing rows: (a) *accepted spellings* — #7 and #8 disagree (#7 refuses `1e-1`, `+0.5`, `1.`, `-0`; #8 accepts them); state which set #9 adopts and why; (b) *integer modulo sign* — Python's `-1 % 100 == 99` versus `-1` in C# and JS, unreachable because `presentation/credit_wire.py:59-60` refuses a negative amount (BC33), guarded by `unit/test_credit_requests.py:79`. Verify each citation with a `sed -n` before writing it.
4. **RC1 / RC2 (record):** correct line 91 (#7 N6 was **avoided by inheritance**: `specs/shared/test-matrix.md:158-159` already read `billing/infrastructure/credit-simulator.spec` at HEAD) and replace the A13 row (line 63) with N1's new arm.

## Bounds

Edit only `services/billing/tests/integration/test_credit_simulator.py`, `services/billing/tests/integration/conftest.py` (the docstring only) and `progress/impl_billing_credit_simulator.md` (append a "Review findings" section and the in-place corrections above). No production file. Do not start the developer stack (the integration test uses testcontainers). No git command that writes the index or working tree. Run the changed test file plus `ruff check`, `ruff format --check` and `mypy` on the two test files.

## Output

Return only "result in `progress/impl_billing_credit_simulator.md` § Review findings" plus at most 4 lines: the N1 arm's message and duration, and the test file's result.
