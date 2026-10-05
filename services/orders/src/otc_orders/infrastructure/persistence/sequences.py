"""The counter SQL for `order_number_sequences`.

The allocator proper is Phase 8 (`orders_acceptance`).

Seeding is `INSERT ... ON CONFLICT DO NOTHING`: ONE statement whose atomicity is the engine's, so
sixteen first-ever callers cannot race a check against an insert (#8 id 45 shipped
`IF NOT EXISTS ... INSERT`, two statements, and lost the race). Allocation then reads the row
`FOR UPDATE` and advances it in the caller's transaction, so a rolled-back order burns no number
(a PostgreSQL SEQUENCE is not transactional and is rejected for that reason).
"""

SEED_ORDER_SEQUENCE = (
    "INSERT INTO order_number_sequences (id, next_value) VALUES (1, 1) ON CONFLICT (id) DO NOTHING"
)
LOCK_ORDER_SEQUENCE = "SELECT next_value FROM order_number_sequences WHERE id = 1 FOR UPDATE"
ADVANCE_ORDER_SEQUENCE = (
    "UPDATE order_number_sequences SET next_value = next_value + 1 WHERE id = 1"
)
