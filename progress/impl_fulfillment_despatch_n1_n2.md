# Mechanical test edits N1, N2 from review_fulfillment_despatch.md

## N1: test_despatch_create.py, line 121

**File:** `services/fulfillment/tests/integration/test_despatch_create.py`

**Lines before:**
```python
    outbox = await db.outbox()
    [fact] = facts_of(outbox, "order.despatched.v1")
```

**Lines after:**
```python
    outbox = await db.outbox()
    facts = facts_of(outbox, "order.despatched.v1")
    assert len(facts) == 1, "exactly one order.despatched.v1 in the outbox"
    [fact] = facts
```

**Why:** Make the assertion of cardinality explicit; the unpacking `[fact] = facts` will still fail if the count is wrong, but now the error message is clear and names the claim being tested.

---

## N2: test_despatch_store.py, test_f8_the_fast_path_answers_a_repeat_from_a_plain_read

**File:** `services/fulfillment/tests/integration/test_despatch_store.py`

**Lines before (391-394):**
```python
    try:
        again = await asyncio.wait_for(despatch_creation.create(command(), scope), timeout=5)
    finally:
        await hold.rollback()
```

**Lines after (391-401):**
```python
try:
    again = await asyncio.wait_for(despatch_creation.create(command(), scope), timeout=5)
except TimeoutError:
    pytest.fail(
        "the repeat waited on the held stock row: "
        "F8's fast path did not answer before the transaction"
    )
finally:
    await hold.rollback()
```

**Why:** Catch `TimeoutError` from `wait_for` and convert it to a named test failure. If F8's fast path works correctly, it should answer immediately even when a stock row is held; if it waits, the timeout fires and `pytest.fail` replaces it with a descriptive message naming the exact violation.

**Note:** `pytest` was already imported in the file at line 21.

## Leader arming (2026-10-08)

The leader then ran `ruff format` on `test_despatch_store.py`: the edit had split a call that fits on one line, and `ruff format --check` refused it. Both arms used `.arm/leader18/arm.sh`, with the backup and `sha256` in `.arm/leader18/sha256.txt`. Each arm ran one named test in its own process group under a 300 s watchdog, was restored by `cp -p` and checked with `cmp`, and was re-run green after `__pycache__` was cleared.

| Arm | Mutation | Red (verbatim) | Green after restore |
|---|---|---|---|
| R21 | `despatch_repository.py:106` outbox write → `pass` | `AssertionError: exactly one order.despatched.v1 in the outbox` (`test_despatch_create.py:122`) | 1 passed |
| R16 | `despatch_creation.py:104-106` fast path removed | `Failed: the repeat waited on the held stock row: F8's fast path did not answer before the transaction` (`test_despatch_store.py:394`) | 1 passed |

Both files in full: 14 passed. Ruff check, ruff format and mypy are clean on the two files.
