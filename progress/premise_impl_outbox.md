# Premise check: brief_impl_outbox_and_idempotency.md

VERIFIED   G1/G2 decided at the gate, design.md section 12.1 (lines 540, 542 say "DECIDED at the human gate, 2026-10-06").
VERIFIED   Feature 14 is in_progress (feature_list.json: id 14 outbox_and_idempotency in_progress).
VERIFIED   tasks.md preamble lists may-touch (services/orders/pyproject.toml aiokafka, uv.lock, pyproject.toml fact-producer-confinement, test_money_guard.py, test_write_path_population.py) and must-not-touch.
VERIFIED   domain/** and packages/cqrs/** are on the must-not-touch list; features 13 and 43 are done (feature_list.json).
VERIFIED   tasks.md has the skip-versus-block measurement (task 4.17, OI13).
VERIFIED   otcpy stack is up: docker ps shows otcpy-postgres 5432->5432 and otcpy-kafka 9092->9092, Up 7 hours.
VERIFIED   CLAUDE.md line 109 says integration suites must pass with developer infrastructure down, citing #8 id 104 and Kafka on 9092.
VERIFIED   "feature 13's review lesson: ten single-field corruptions survived": review_orders_aggregate.md line 49.
CONFLICT   Brief line 15: "The developer stack otcpy is up; do not start or stop it." Task 2.1 mandates running the orders integration suite once with the developer stack DOWN (docker ps shows no otcpy-kafka) and recording it, and its arm requires the Kafka-backed tests to fail with it down. The brief forbids what 2.1 mandates; tasks.md outranks the brief.
