"""The counter SQL for `despatch_number_sequences` (`DES-######`).

The allocator proper is Phase 9 (fulfillment's despatch feature).

Seeding is `INSERT ... SELECT ... WHERE NOT EXISTS (counter row) ... ON CONFLICT DO NOTHING`: ONE
statement whose atomicity is the engine's, so sixteen first-ever callers cannot race a check against
an insert (#8 id 45 shipped `IF NOT EXISTS ... INSERT`, two statements, and lost the race;
`ON CONFLICT` still arbitrates the callers that all passed the `WHERE NOT EXISTS`).

A database that already holds references starts the counter above them (backlog 211: the seed
job writes `DES-` rows but no counter row, so `VALUES (1, 1)` would re-issue `DES-000001`).
The start is the numeric MAX of the reference suffix plus one: `substring(... FROM 5)` drops the
4-character `DES-` prefix and the CAST makes it a number, because a text MAX ranks `999999`
above `1000000` (the format is `DES-######` but never stops at six digits). The MAX lives in the
select-list subquery, which PostgreSQL evaluates only for a row that survives the one-time
`WHERE NOT EXISTS` filter: with the counter row present the scan of `despatches` is
"never executed". #8 id 47 shipped the MAX on every allocation and had to fix its cost.
(Measured on postgres:18.6: an aggregate `SELECT MAX(...) FROM despatches WHERE NOT EXISTS (...)`
also skips the scan, but it still emits a row and attempts a conflicting insert.) The test file
pins the skip with `EXPLAIN (ANALYZE)`.

Allocation then reads the row `FOR UPDATE` and advances it in the caller's transaction, so a
rolled-back despatch burns no number (a PostgreSQL SEQUENCE is not transactional and is rejected for
that reason).

`ADVANCE_DESPATCH_SEQUENCE` is raw SQL: it bypasses the ORM range guard on `next_value` (the
residual named in `range_guards.py`); the engine refuses an overflow with a driver error.
"""

SEED_DESPATCH_SEQUENCE = (
    "INSERT INTO despatch_number_sequences (id, next_value) "
    "SELECT 1, COALESCE((SELECT MAX(CAST(substring(despatch_reference FROM 5) AS bigint)) "
    "FROM despatches), 0) + 1 "
    "WHERE NOT EXISTS (SELECT 1 FROM despatch_number_sequences WHERE id = 1) "
    "ON CONFLICT (id) DO NOTHING"
)
LOCK_DESPATCH_SEQUENCE = "SELECT next_value FROM despatch_number_sequences WHERE id = 1 FOR UPDATE"
ADVANCE_DESPATCH_SEQUENCE = (
    "UPDATE despatch_number_sequences SET next_value = next_value + 1 WHERE id = 1"
)
