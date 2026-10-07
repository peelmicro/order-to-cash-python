# Mechanical test edits (N1, N2) — feature 16 closing round 2 findings

## N1: Parked back-off assertion message
**File:** `services/orders/tests/integration/saga/test_saga_command_ledger.py:311-315`

Changed unpacking to list assertion with wrapped message:
- Line 312: `[due] = await ledger.claim_due(10)` → `due = await ledger.claim_due(10)`
- Lines 313-315: `assert [row.id for row in due] == [claimed.id], (` + message wrapped to next line

**Why:** The unpacking fails with `ValueError: not enough values to unpack` before the assertion message is shown. The test body now allows the assertion to name the claim's boundary condition on failure. Message wrapped for line length.

**Arm:** b3 (`<=` → `<` in `claim_due` parked branch) now fails with the named message instead of `ValueError`.

## N2: SAGA_SENTINELS population sentinel
**File:** `services/orders/tests/integration/test_orders_host_lifespan.py:748-769` (new)

Added test `test_saga_sentinels_cover_all_saga_environment_variables()` that parses the unit test file with `ast` module to extract `ENV` literal, finds all SAGA_* keys, and asserts they match `SAGA_SENTINELS`. Docstring fits 100-char limit.

**Why:** The reach test's sentinel dictionary must be tied to the unit population test's environment variables. A 12th `SAGA_*` variable added in a later feature would fail this test and prevent silent omission from SAGA_SENTINELS.

**Arm:** Adding a 12th `SAGA_*` entry to the unit `ENV` only makes this test fail naming the missing variable.

**Correction (ruff SIM102):** Replaced nested if/walk pattern with list comprehension over `tree.body` to extract ENV keys.
