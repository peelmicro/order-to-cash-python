"""The counter SQL for `despatch_number_sequences` (`DES-######`).

The allocator proper is Phase 9 (fulfillment's despatch feature).

Seeding is `INSERT ... ON CONFLICT DO NOTHING`: ONE statement whose atomicity is the engine's, so
sixteen first-ever callers cannot race a check against an insert (#8 id 45 shipped
`IF NOT EXISTS ... INSERT`, two statements, and lost the race). Allocation then reads the row
`FOR UPDATE` and advances it in the caller's transaction, so a rolled-back despatch burns no number
(a PostgreSQL SEQUENCE is not transactional and is rejected for that reason).

`ADVANCE_DESPATCH_SEQUENCE` is raw SQL: it bypasses the ORM range guard on `next_value` (the
residual named in `range_guards.py`); the engine refuses an overflow with a driver error.
"""

SEED_DESPATCH_SEQUENCE = (
    "INSERT INTO despatch_number_sequences (id, next_value) VALUES (1, 1) "
    "ON CONFLICT (id) DO NOTHING"
)
LOCK_DESPATCH_SEQUENCE = "SELECT next_value FROM despatch_number_sequences WHERE id = 1 FOR UPDATE"
ADVANCE_DESPATCH_SEQUENCE = (
    "UPDATE despatch_number_sequences SET next_value = next_value + 1 WHERE id = 1"
)
