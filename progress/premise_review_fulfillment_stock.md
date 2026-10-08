# Premise check — brief_review_fulfillment_stock.md
FALSE  ".arm/impl17/ (42 entries)" — `ls .arm/impl17 | wc -l` = 74 top-level (433 files by `find -type f`; `bak/` alone holds 122).
VERIFIED #8 history.md:999 = fulfillment_stock entry: "3 review passes — REJECTED, REJECTED, APPROVED", "≈4 h 13 min".
VERIFIED #8 history.md:1167 = Phase 9 closing assessment heading; the table row (line 1171) says ≈4 h 13 min, 3 review passes + 2 fixes, 2 rejections.
VERIFIED #7 history.md:842 = fulfillment_stock entry; "REJECTED on pass 1 ... APPROVED on pass 2" (one rejection).
VERIFIED 82/82 ticked — `grep -c '^- \[x\]' tasks.md` = 82, unticked = 0.
VERIFIED feature 17 in_review — feature_list.json id 17 status in_review.
VERIFIED only otcpy-n8n runs — `docker ps --format '{{.Names}}'` = otcpy-n8n.
VERIFIED A2 268 s / J4 309 s (also 315 s final) — impl report lines 3, 42, 44.
VERIFIED ~125 s threshold — progress/current.md:45 and history.md:695/799.
VERIFIED files exist: tests/architecture/test_fulfillment_rpc_error_retryability.py; services/orders/.../nats_saga_commands.py (TERMINAL_RPC_ERROR_CODES at :65).
VERIFIED impl report sections: §2 = stale citations (line 22), §8 = H10 equivalent mutant, §10 live boot K1-K5 with ORD-000007/000008, §11 dev 1 (formatter), 2 (snapshot product_code), 6 (NatsServerShape; KafkaServerShape precedent), 9 (H10 equivalent mutant), §15.1 C6 unarmed argued via C3 parity + Orders test.
VERIFIED design sections exist: §6.2 (l.220), §6.3 (244), §6.5 (265), §8.5 (351), §10.2 (389), §13.3 (463), §16.1 "Gate record" (l.500, within §16.1 block; G1-G3 as recommended).
VERIFIED KafkaServerShape in HEAD:services/orders/tests/integration/conftest.py (line 279).
VERIFIED deviation 1 "design §10.2 named the token map alone" — impl §11.1 says so (design text not re-read).
UNVERIFIABLE-by-design: quality.sh exit 0, 2686 vs 2387 (+299), 51/52 ARM rows over 119 runs, lint-imports 11 contracts.
CONFLICT (minor): brief says deviation 6 "breaks task A4's 'nothing else in that file changes'"; that phrase is in tasks.md header line 15, not A4 (line 30, which says "unchanged", run Orders suite, same pass count). The substance (conflict with tasks.md) holds.
No CLAUDE.md conflict found (reviewer-sets-done for full group is consistent; no model forbidden).
NOTE: tasks.md has 55 lines containing "[ARM]" vs the "52 rows" reported (reported-not-verified; may include header prose).
Verdict: DO NOT ACT until fixed — 1 FALSE, 1 CONFLICT(minor), 1 UNVERIFIABLE group, rest VERIFIED.
