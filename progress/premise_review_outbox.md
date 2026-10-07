# Premise check: brief_review_outbox_and_idempotency.md
VERIFIED A1 note at design.md §6.4 (line 428) says ConsumerName in per-service consumer_name.py, one relative import, whole-file scan
VERIFIED tasks.md widened root conftest bound (line 15: Postgres -c timezone=UTC -c log_timezone=UTC)
VERIFIED G1 and G2 DECIDED 2026-10-06 as recommended (design.md 543, 545)
VERIFIED impl report has §11, §13, arming table (§6), census (§7), skip-vs-block (§5.4), "Amendment A1" section (line 587)
VERIFIED impl 8.1 reports exit 0, 153 s, 1644 passed, 98.44 %, stack down (before A1; A1 section lists no quality.sh rerun)
VERIFIED §11 has items 4, 5, 9, 10 (lines 517-531)
VERIFIED #8 history entry spans lines 730-772 (heading 730, next entry 773); #8 ~3.4h; #7 ~2.4h (nestjs history line 773)
VERIFIED #8/#7 paths exist (dotnet Outbox dir, specs dirs, nestjs specs dir)
VERIFIED stack stopped except otcpy-n8n (docker ps; ss shows no 9092/5432)
VERIFIED feature 14 status in_review (feature_list.json)
VERIFIED Phase 7 103.24 s / 1290 passed; feature 43 run 2 m 22 s = 142 s with stack up (history.md:778; premise_review_orders_aggregate.md:9)
VERIFIED 1644 = 1506 + 138 (history.md:778 headline 1506; per-file counts sum to 1644 over 123 files)
UNVERIFIABLE "A1: 5 passed" for test_idempotent_consumer.py: needs testcontainers (suite run), not run
NOTED: current `pytest --collect-only` now collects 1648 (4 more than 1644, consistent with A1's new parity sentinels, post-report); the 1644 figure is pre-A1.
