# Brief — implementer, light change at the Phase 8 wrap-up: Kafka test-container group rebalance delay

**Why:** `./quality.sh` takes ≈440 s with the stack down, against the maintainer's ~125 s threshold. The cause was measured in feature 16's review round 2 (`progress/review_order_saga_orchestrator.md`, "Duration"). The root `conftest.py` Kafka container (`conftest.py` ~:283–300) does not set `KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS`, so every `orders.saga` group join waits the broker default of 3 s. The reviewer's probe with `0` took 22 saga cases from 98.7 s to 32.3 s.

**Task:**
1. Add `.with_env("KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS", "0")` to the root `conftest.py` Kafka container, with a one-line reason beside it.
2. Check `services/orders/tests/integration/test_fixture_matches_deployed_server.py`, and any other test that compares the fixture's broker settings with `docker-compose.infra.yml`. If one fails, classify the new variable there as test-only, with its reason, in that test's own allow-list. Do **not** change `docker-compose.infra.yml`.
3. Re-run the SO9 / SO1 arms under the new broker setting: R3.9a, R3.9b, R3.9c, R3.9d, R3.10, R3.10c and R3.12. Their mutations and expected failures are in `progress/review_order_saga_orchestrator.md` lines 47–54. Each must still fail with its named assertion and not hang. Use `.arm/` for backups and sha256, kill the whole process group on timeout, restore with `cmp`, and re-run green.
4. Run `./quality.sh` once with the developer stack down. Report exit code, duration and pass count (expected 2387, unchanged).

**Bounds:** root `conftest.py`, the classification line in the parity test if needed, and a new file `progress/impl_kafka_rebalance_delay.md`. Nothing else. No `feature_list.json` edit (no feature owns this; the leader records it in feature 16's history addendum). No git writes. Return only "result in `progress/impl_kafka_rebalance_delay.md`" plus at most 4 lines.
