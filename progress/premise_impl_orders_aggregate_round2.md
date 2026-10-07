# Premise check: brief_impl_orders_aggregate_round2.md
VERIFIED D1-D3 in review section 6 (lines 225-227), each "Fix (reject)"
VERIFIED mutations P1-P4, R1-R4, PL1, PL2 in review section 4.1 (lines 104-113)
VERIFIED required changes in review section 7 (items 1-3 map to 4.17, 5.12, 3.22)
VERIFIED tasks.md 3.22 (line 64), 4.17 (84), 5.12 (101) exist as "- [ ]" with the arms the brief names (PL1/PL2; P1-P4 + OrderConfirmed.order_reference + OrderCancelled retailer_code<->company_code; R1-R4)
VERIFIED pyproject.toml line 63 extend-exclude = ["specs"] directly under [tool.ruff] (before [tool.ruff.lint])
UNVERIFIABLE "armed by the leader": needs a ruff format run (not run, read-only)
VERIFIED tasks 3.12 (line 54) and 4.16 (line 83) carry "Amended after review round 1, F5" wording
VERIFIED feature 15 acceptance has the F7 item (last entry, "carried from orders_aggregate review round 1 (F7...")
VERIFIED feature 13 status = in_progress (brief sets in_review, mandated by tasks 6.8)
NO CONFLICT: file bounds (tests/unit/domain/**, conftest, impl report) cover the files named by 3.22/4.17/5.12 (test_order.py, test_order_events.py, test_order_rehydration.py all exist there); "no production edit" matches review section 7 header; feature_list line-only edit matches 6.8.
