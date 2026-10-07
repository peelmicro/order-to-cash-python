# Kafka test-container rebalance delay (light change, Phase 8 wrap-up)

## What changed
- `conftest.py`, root Kafka container: added `.with_env("KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS", "0")` after `KAFKA_AUTO_CREATE_TOPICS_ENABLE`, with a one-line test-only reason beside it. Nothing else touched (no compose, no feature_list.json, no git writes).

## Parity test (task 2)
`services/orders/tests/integration/test_fixture_matches_deployed_server.py` compares only PostgreSQL session settings (`timezone`, isolation, `lock_timeout`, ...) against `docker-compose.infra.yml`. It reads no Kafka setting, so no allow-list edit was needed. `grep -rln "GROUP_INITIAL\|docker-compose.infra" --include=*.py` found only the root conftest, that test and `services/orders/tests/integration/conftest.py`. The compose file has no `REBALANCE` line.

## Arms under the new broker setting (task 3)
Script `.arm/arms_rb0.py` (uses `.arm/arm.py`: backup and sha256 in `.arm/bak/rb0-*`, process group killed on timeout, `cmp` restore, caches cleared, green re-run). Logs in `.arm/logs/rb0-*.log`. Every arm failed (exit 1, none hung), every restore was `cmp identical` and sha256-equal, every restored run was green.

| Arm | Test | Mutated run | Failure (verbatim) | Restored |
|---|---|---|---|---|
| R3.9a | SO9 #1 | 12.8 s | `AssertionError: the offset moved while the handler ran` (:159) | green 19.6 s |
| R3.9b | SO9 #1 | 17.1 s | `AssertionError: the offset moved while the handler ran` (:159) | green 20.8 s |
| R3.9c | SO9 #1 | 19.0 s | `AssertionError: a failed handler must not advance the offset` (:165) | green 19.7 s |
| R3.9d | SO9 #1 | 19.0 s | `AssertionError: a failed handler must not advance the offset` (:165) | green 19.7 s |
| R3.10 | SO9 #2 | 72.4 s | `AssertionError: only 1 attempts in 60 s` (:227) | green 27.1 s |
| R3.10c | SO9 #2 | 18.9 s | `AssertionError: the committed offset 1 passed the failed record at 0: samples=[0, 1, 1, ...]` (:231) | green 27.4 s |
| R3.12 | SO1 | 31.7 s | `AssertionError: timed out after 20s waiting for: the credit.hold row exists: the fact published first was consumed` | green 11.6 s |

Mutations I used (the review file gives the names and expected failures, not the edits): 9a commit before the handler await; 9b `enable_auto_commit=True` and the explicit commit removed; 9c the failure-branch `seek` replaced by `commit(offset+1)`; 9d the `await pace(...)` replaced by `pass`; 10 the `seek` replaced by `pass`; 10c `commit(offset+1)` inserted before the `seek`; 12 `auto_offset_reset="latest"`. All match the recorded failure messages and assertions.

## quality.sh, developer stack down (task 4)
Only `otcpy-n8n` was running (no Kafka, Postgres or NATS). Exit 0, "all gates passed", **2387 passed** (unchanged), pytest 255.76 s, whole script about 286 s (log created 15:43:13, finished 15:47:59), against about 440 s before. Coverage 98.70% overall, domain 98%. Log: `.arm/rb0_quality.log`.

## Surprises
- `setsid ./quality.sh` returns at once when the shell is not a group leader, so my first exit/duration files read 0; I waited for the log's final line instead and took the duration from file timestamps. The 286 s is therefore a timestamp estimate, not a timed wall clock.
