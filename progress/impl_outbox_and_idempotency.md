# Implementation report — `outbox_and_idempotency` (feature 14, phase 8, full group)

Status: `in_review`. Spec: `specs/outbox_and_idempotency/` (approved 2026-10-06, G1 and G2 as recommended). No git write was run. `progress/current.md` was not touched by this session (its mtime is the leader's, 12:09; `git diff progress/current.md` is the leader's edit).

## 1. What was built

The transactional outbox, its polling relay, the Kafka publisher adapter and the canonical idempotent consumer, for the Orders write model, with the tests that prove R11–R15, R17, R18 and OI1–OI20. R16 stays `TODO` for feature 27 (decided, `requirements.md` §1.2).

* **Kernel / contracts.** `otc_shared_kernel.event_envelope` (the pure R11 guard, `re.fullmatch`); `otc_contracts.envelope.Envelope[P]` (PEP 695 syntax works on a pydantic 2.13 model: no `Generic[P]` fallback was needed) and `otc_contracts.wire_instant` (truncate, never round).
* **Orders `application/ports`**: `Clock`, `OrderRepository`, `OrdersTransaction`, `UnitOfWork`.
* **Orders `infrastructure`**: `SystemClock`; `OutboxRelaySettings` / `KafkaSettings`; `SqlAlchemyUnitOfWork` (one `AsyncSession`, `READ COMMITTED` pinned before the first statement, events cleared after the commit, no retry), `SqlAlchemyOrderRepository` + `order_mapper` (rehydrate only), `outbox/` (`payloads`, `writer`, `wire`, `publisher`, `topic`, `kafka_publisher`, `relay`, `relay_task`, `errors`), `messaging/idempotent_consumer.py` (canonical).
* **Guards**: import-linter contract `fact-producer-confinement`; census updates in `test_money_guard.py` (`"re"`), `test_write_path_population.py` (`EXPECTED["orders"]`), `test_kernel_surface.py`.
* **Fixtures**: a session-scoped real Kafka (`apache/kafka:4.3.1`, Docker-assigned port, topic `otc.orders.facts.v1` with 6 partitions) in the root `conftest.py`, and the orders integration fixtures (`sessions`, `reference_data`, `uow`, `place_order`, `kafka_publisher`, `read_topic`, `make_relay`, `row_planter`).
* **Requirement status** written: matrix column 5 of R11–R15, R17, R18 (+ derived counts: feature 2 = 7 green / 0 scoped / 1 not yet green; Total 16 / 1 / 46 = 63) and `requirements.md` §3 (every local row `DONE`, literal function names, each verified by `grep -n "def <name>"`: `check_names.txt` output below).

## 2. Files touched

New (src): `packages/shared_kernel/src/otc_shared_kernel/event_envelope.py`; `packages/contracts/src/otc_contracts/envelope.py`; `services/orders/src/otc_orders/application/ports/{__init__,clock,order_repository,unit_of_work}.py`; `services/orders/src/otc_orders/infrastructure/clock.py`; `.../infrastructure/messaging/{__init__,idempotent_consumer}.py`; `.../infrastructure/outbox/{__init__,errors,kafka_publisher,payloads,publisher,relay,relay_task,topic,wire,writer}.py`; `.../infrastructure/persistence/{order_mapper,order_repository,unit_of_work}.py`.
Changed (src): `packages/shared_kernel/src/otc_shared_kernel/__init__.py`, `packages/contracts/src/otc_contracts/{__init__,wire}.py` (`wire_instant` only), `services/orders/src/otc_orders/infrastructure/settings.py` (two classes).
New (tests): `packages/shared_kernel/tests/test_event_envelope.py`; `packages/contracts/tests/test_envelope_generic.py`; `services/orders/tests/unit/{test_outbox_settings,test_outbox_payloads,test_outbox_relay_task,test_kafka_fact_publisher,test_deadlock_classifier,test_idempotent_consumer_parity,test_system_clock}.py`; `services/orders/tests/integration/{test_kafka_fixture,test_fixture_matches_deployed_server,test_order_repository,test_outbox_atomicity,test_outbox_envelope,test_outbox_relay,test_outbox_relay_concurrency,test_outbox_relay_deadlock,test_fact_partitioning,test_outbox_wire_parity,test_idempotent_consumer}.py`; `services/seed/tests/integration/test_seeded_outbox_has_nothing_to_publish.py`.
Changed (tests / config): `conftest.py` (root: the Kafka fixture, and one line on the Postgres fixture, see §11 divergence 2), `services/orders/tests/integration/conftest.py` (new fixtures only), `packages/shared_kernel/tests/test_kernel_surface.py`, `tests/architecture/test_money_guard.py`, `tests/architecture/test_write_path_population.py`, `pyproject.toml` (the one import-linter contract; no `filterwarnings` line), `services/orders/pyproject.toml`, `uv.lock`, `.env.example`, `specs/shared/test-matrix.md` (column 5 of the seven rows and the derived counts only), `specs/outbox_and_idempotency/{requirements,tasks}.md` (status cells and ticks), `feature_list.json` (feature 14's `status` line only).
`test_cqrs_registration_explicit.py`: the census command was run, the allow-list was **not** edited (§8).
Not touched: `domain/**`, `presentation/**`, `alembic/**`, `packages/cqrs/**`, `composition.py`, `specs/orders_aggregate/` (proved below by `find ... -newer` over those trees: nothing).


## 3. Requirements and the tests that prove them

Shared ids (matrix column 5 `DONE`; `R16` stays `TODO` for feature 27):

| Id | Test file › function(s) |
|---|---|
| R11 | `test_event_envelope.py` › `test_r11_event_envelope_refuses_an_envelope_with_an_absent_null_or_empty_field_and_an_event_type_that_does_not_match_the_pattern`, `test_r11_event_envelope_accepts_a_complete_envelope_and_every_event_type_of_the_catalogue`; `test_outbox_wire_parity.py` › `test_r11_published_envelope_carries_the_seven_fields_in_declared_order_with_none_absent_null_or_empty` |
| R12 | `test_outbox_envelope.py` › `test_r12_stamps_every_fact_of_one_order_with_the_order_id_as_correlation_id_and_the_causing_event_id_as_causation_id` |
| R13 | `test_outbox_atomicity.py` › `test_r13_persists_neither_the_aggregate_nor_the_outbox_record_and_publishes_nothing_when_the_transaction_fails`, `test_r13_rolls_back_an_outbox_row_already_written_when_a_later_save_in_the_same_transaction_fails` |
| R14 | `test_outbox_relay.py` › `test_r14_stamps_a_record_only_after_the_broker_acknowledgement_and_republishes_an_unstamped_record_on_the_next_poll` |
| R15 | `test_fact_partitioning.py` › `test_r15_delivers_all_facts_produced_by_one_context_about_one_order_to_consumers_in_emission_order` |
| R17 | `test_idempotent_consumer.py` › `test_r17_records_the_event_id_and_consumer_name_in_the_same_transaction_as_the_state_change_and_the_outbox_records`, `test_r17_leaves_no_dedup_row_when_a_failure_inside_work_rolls_back_the_whole_transaction` |
| R18 | `test_idempotent_consumer.py` › `test_r18_acknowledges_a_redelivered_fact_without_mutating_state_emitting_a_fact_or_issuing_a_command` |

Local ids (`requirements.md` §3, every row `DONE`):

| Id | Test file › function(s) |
|---|---|
| OI1 | `test_outbox_envelope.py` › `test_oi1_relay_reconstructs_the_complete_envelope_from_the_stored_record_alone`, `test_oi1_writer_refuses_an_event_with_an_incomplete_envelope_before_any_row_is_written`, `test_oi1_writer_refuses_an_event_type_outside_the_fact_catalogue`, `test_oi1_every_column_and_envelope_field_comes_from_its_own_event_field` |
| OI2 | `test_outbox_relay.py` › `test_oi2_publishes_records_written_by_one_transaction_in_append_order_although_they_share_occurred_at`, `test_oi2_orders_the_claim_by_seq_never_by_occurred_at_when_they_disagree` |
| OI3 | `test_outbox_relay.py` › `test_oi3_publishes_a_lower_sequence_record_that_committed_after_a_higher_one_was_published` |
| OI4 | `test_outbox_relay_concurrency.py` › `test_oi4_two_concurrent_relays_take_disjoint_batches_and_publish_every_record_exactly_once` |
| OI5 | `test_outbox_relay_concurrency.py` › `test_oi5_records_claimed_by_a_relay_whose_connection_died_are_claimed_on_the_next_poll_without_a_wait` |
| OI6 | `test_outbox_relay_task.py` › `test_oi6_never_starts_a_second_cycle_while_one_is_in_progress`, `test_oi6_stop_waits_for_the_in_flight_cycle`, `test_relay_task_survives_a_failed_cycle_and_runs_the_next`, `test_relay_task_propagates_cancellation` |
| OI7 | `test_kafka_fact_publisher.py` › `test_oi7_producer_is_idempotent_so_an_internal_retry_can_neither_reorder_nor_duplicate` |
| OI8 | `test_outbox_relay.py` › `test_oi8_leaves_every_record_of_a_rejected_batch_unstamped_logs_each_and_republishes_the_same_records_in_order` |
| OI9 | `test_outbox_atomicity.py` › `test_oi9_a_retry_from_the_same_instance_after_a_rollback_writes_exactly_one_outbox_row_per_event` |
| OI10 | `test_idempotent_consumer.py` › `test_oi10_applies_the_effects_once_when_the_same_event_is_delivered_concurrently` |
| OI11 | `test_reliability_table_parity.py` › `test_outbox_and_processed_events_are_identical_across_the_four_databases` |
| OI12 | `test_idempotent_consumer_parity.py` › `test_case_1_every_write_models_copy_is_byte_identical_to_the_canonical_after_the_banner`, `test_case_2_the_canonical_is_adoptable_verbatim_naming_no_service`, `test_case_3_every_write_model_that_consumes_facts_carries_a_copy`, `test_case_4_a_variant_carries_a_divergence_banner_naming_the_canonical` |
| OI13 | `test_outbox_relay_concurrency.py` › `test_oi13_a_claim_skips_rows_another_relay_holds_and_returns_without_waiting`, `test_oi13_the_claim_runs_at_read_committed_under_an_engine_defaulting_to_repeatable_read` |
| OI14 | `test_outbox_relay.py` › `test_oi14_abandons_a_publish_that_exceeds_the_timeout_rolls_the_claim_back_and_republishes_on_the_next_poll` |
| OI15 | `test_outbox_wire_parity.py` › `test_oi15_relay_publishes_bytes_identical_to_the_golden_envelope`, `test_oi15_writer_stores_a_payload_semantically_equal_to_the_golden_for_the_same_business_inputs`, `test_r11_published_envelope_carries_the_seven_fields_in_declared_order_with_none_absent_null_or_empty` |
| OI17 | `test_outbox_relay_deadlock.py` › `test_oi17_run_once_survives_a_constructed_deadlock_victim_and_retries_the_cycle`, `test_oi17_without_the_retry_the_constructed_deadlock_escapes_run_once_as_40p01`; `test_deadlock_classifier.py` › `test_the_classifier_retries_only_a_deadlock_victim`, `test_run_once_retries_a_deadlock_victim_up_to_the_bound_then_lets_it_escape` |
| OI18 | `test_outbox_relay.py` › `test_oi18_a_poison_row_blocks_at_itself_after_the_clean_prefix_is_published`, `test_oi18_a_poison_row_at_the_head_publishes_nothing_and_raises_nothing_on_every_poll` |
| OI19 | `test_outbox_envelope.py` › `test_oi19_a_sub_millisecond_instant_is_stored_enveloped_and_written_in_the_payload_as_the_same_millisecond`, `test_oi19_every_instant_column_the_repository_writes_is_stored_truncated_never_rounded` |
| OI20 | `test_envelope_generic.py` › `test_oi20_model_dump_json_equals_to_wire_json`, `test_oi20_no_path_writes_an_instant_with_more_than_three_fractional_digits`, `test_oi20_a_payload_copied_past_validation_is_refused_by_model_dump_json_and_by_to_wire_json`, `test_the_generic_envelope_has_the_generated_envelopes_fields_aliases_order_and_pattern`, `test_wire_instant_truncates_and_agrees_with_format_instant` |
| OI16 | `pyproject.toml` contract `fact-producer-confinement`, run by `lint-imports` in `quality.sh` (arms: §6, rows 7.2a–7.2d) |

Supporting tests that prove no `R<n>` alone: `test_kafka_fixture.py` (2.2), `test_fixture_matches_deployed_server.py` (2.3), `test_outbox_settings.py` (3.4), `test_system_clock.py` (3.2), `test_order_repository.py` (3.8), `test_outbox_payloads.py` (3.9), `test_seeded_outbox_has_nothing_to_publish.py` (4.20).

`grep -n "def <name>"` over every name written into the matrix and `requirements.md` §3 (`check`: 52 names, each defined exactly once; the last line is the sentinel, a deliberately misspelled name, reported missing before the cells were written):

```
grep -n 'def test_r11_event_envelope_refuses_an_envelope_with_an_absent_null_or_empty_field_and_an_event_type_that_does_not_match_the_pattern' packages/shared_kernel/tests/test_event_envelope.py: 1 definition(s)
grep -n 'def test_r11_event_envelope_accepts_a_complete_envelope_and_every_event_type_of_the_catalogue' packages/shared_kernel/tests/test_event_envelope.py: 1 definition(s)
grep -n 'def test_r11_published_envelope_carries_the_seven_fields_in_declared_order_with_none_absent_null_or_empty' services/orders/tests/integration/test_outbox_wire_parity.py: 1 definition(s)
grep -n 'def test_r12_stamps_every_fact_of_one_order_with_the_order_id_as_correlation_id_and_the_causing_event_id_as_causation_id' services/orders/tests/integration/test_outbox_envelope.py: 1 definition(s)
grep -n 'def test_r13_persists_neither_the_aggregate_nor_the_outbox_record_and_publishes_nothing_when_the_transaction_fails' services/orders/tests/integration/test_outbox_atomicity.py: 1 definition(s)
grep -n 'def test_r13_rolls_back_an_outbox_row_already_written_when_a_later_save_in_the_same_transaction_fails' services/orders/tests/integration/test_outbox_atomicity.py: 1 definition(s)
grep -n 'def test_r14_stamps_a_record_only_after_the_broker_acknowledgement_and_republishes_an_unstamped_record_on_the_next_poll' services/orders/tests/integration/test_outbox_relay.py: 1 definition(s)
grep -n 'def test_r15_delivers_all_facts_produced_by_one_context_about_one_order_to_consumers_in_emission_order' services/orders/tests/integration/test_fact_partitioning.py: 1 definition(s)
grep -n 'def test_r17_records_the_event_id_and_consumer_name_in_the_same_transaction_as_the_state_change_and_the_outbox_records' services/orders/tests/integration/test_idempotent_consumer.py: 1 definition(s)
grep -n 'def test_r17_leaves_no_dedup_row_when_a_failure_inside_work_rolls_back_the_whole_transaction' services/orders/tests/integration/test_idempotent_consumer.py: 1 definition(s)
grep -n 'def test_r18_acknowledges_a_redelivered_fact_without_mutating_state_emitting_a_fact_or_issuing_a_command' services/orders/tests/integration/test_idempotent_consumer.py: 1 definition(s)
grep -n 'def test_oi1_relay_reconstructs_the_complete_envelope_from_the_stored_record_alone' services/orders/tests/integration/test_outbox_envelope.py: 1 definition(s)
grep -n 'def test_oi1_writer_refuses_an_event_with_an_incomplete_envelope_before_any_row_is_written' services/orders/tests/integration/test_outbox_envelope.py: 1 definition(s)
grep -n 'def test_oi1_writer_refuses_an_event_type_outside_the_fact_catalogue' services/orders/tests/integration/test_outbox_envelope.py: 1 definition(s)
grep -n 'def test_oi1_every_column_and_envelope_field_comes_from_its_own_event_field' services/orders/tests/integration/test_outbox_envelope.py: 1 definition(s)
grep -n 'def test_oi2_publishes_records_written_by_one_transaction_in_append_order_although_they_share_occurred_at' services/orders/tests/integration/test_outbox_relay.py: 1 definition(s)
grep -n 'def test_oi2_orders_the_claim_by_seq_never_by_occurred_at_when_they_disagree' services/orders/tests/integration/test_outbox_relay.py: 1 definition(s)
grep -n 'def test_oi3_publishes_a_lower_sequence_record_that_committed_after_a_higher_one_was_published' services/orders/tests/integration/test_outbox_relay.py: 1 definition(s)
grep -n 'def test_oi4_two_concurrent_relays_take_disjoint_batches_and_publish_every_record_exactly_once' services/orders/tests/integration/test_outbox_relay_concurrency.py: 1 definition(s)
grep -n 'def test_oi5_records_claimed_by_a_relay_whose_connection_died_are_claimed_on_the_next_poll_without_a_wait' services/orders/tests/integration/test_outbox_relay_concurrency.py: 1 definition(s)
grep -n 'def test_oi6_never_starts_a_second_cycle_while_one_is_in_progress' services/orders/tests/unit/test_outbox_relay_task.py: 1 definition(s)
grep -n 'def test_oi6_stop_waits_for_the_in_flight_cycle' services/orders/tests/unit/test_outbox_relay_task.py: 1 definition(s)
grep -n 'def test_relay_task_survives_a_failed_cycle_and_runs_the_next' services/orders/tests/unit/test_outbox_relay_task.py: 1 definition(s)
grep -n 'def test_relay_task_propagates_cancellation' services/orders/tests/unit/test_outbox_relay_task.py: 1 definition(s)
grep -n 'def test_oi7_producer_is_idempotent_so_an_internal_retry_can_neither_reorder_nor_duplicate' services/orders/tests/unit/test_kafka_fact_publisher.py: 1 definition(s)
grep -n 'def test_oi8_leaves_every_record_of_a_rejected_batch_unstamped_logs_each_and_republishes_the_same_records_in_order' services/orders/tests/integration/test_outbox_relay.py: 1 definition(s)
grep -n 'def test_oi9_a_retry_from_the_same_instance_after_a_rollback_writes_exactly_one_outbox_row_per_event' services/orders/tests/integration/test_outbox_atomicity.py: 1 definition(s)
grep -n 'def test_oi10_applies_the_effects_once_when_the_same_event_is_delivered_concurrently' services/orders/tests/integration/test_idempotent_consumer.py: 1 definition(s)
grep -n 'def test_outbox_and_processed_events_are_identical_across_the_four_databases' tests/database_parity/test_reliability_table_parity.py: 1 definition(s)
grep -n 'def test_case_1_every_write_models_copy_is_byte_identical_to_the_canonical_after_the_banner' services/orders/tests/unit/test_idempotent_consumer_parity.py: 1 definition(s)
grep -n 'def test_case_2_the_canonical_is_adoptable_verbatim_naming_no_service' services/orders/tests/unit/test_idempotent_consumer_parity.py: 1 definition(s)
grep -n 'def test_case_3_every_write_model_that_consumes_facts_carries_a_copy' services/orders/tests/unit/test_idempotent_consumer_parity.py: 1 definition(s)
grep -n 'def test_case_4_a_variant_carries_a_divergence_banner_naming_the_canonical' services/orders/tests/unit/test_idempotent_consumer_parity.py: 1 definition(s)
grep -n 'def test_oi13_a_claim_skips_rows_another_relay_holds_and_returns_without_waiting' services/orders/tests/integration/test_outbox_relay_concurrency.py: 1 definition(s)
grep -n 'def test_oi13_the_claim_runs_at_read_committed_under_an_engine_defaulting_to_repeatable_read' services/orders/tests/integration/test_outbox_relay_concurrency.py: 1 definition(s)
grep -n 'def test_oi14_abandons_a_publish_that_exceeds_the_timeout_rolls_the_claim_back_and_republishes_on_the_next_poll' services/orders/tests/integration/test_outbox_relay.py: 1 definition(s)
grep -n 'def test_oi15_relay_publishes_bytes_identical_to_the_golden_envelope' services/orders/tests/integration/test_outbox_wire_parity.py: 1 definition(s)
grep -n 'def test_oi15_writer_stores_a_payload_semantically_equal_to_the_golden_for_the_same_business_inputs' services/orders/tests/integration/test_outbox_wire_parity.py: 1 definition(s)
grep -n 'def test_r11_published_envelope_carries_the_seven_fields_in_declared_order_with_none_absent_null_or_empty' services/orders/tests/integration/test_outbox_wire_parity.py: 1 definition(s)
grep -n 'def test_oi17_run_once_survives_a_constructed_deadlock_victim_and_retries_the_cycle' services/orders/tests/integration/test_outbox_relay_deadlock.py: 1 definition(s)
grep -n 'def test_oi17_without_the_retry_the_constructed_deadlock_escapes_run_once_as_40p01' services/orders/tests/integration/test_outbox_relay_deadlock.py: 1 definition(s)
grep -n 'def test_the_classifier_retries_only_a_deadlock_victim' services/orders/tests/unit/test_deadlock_classifier.py: 1 definition(s)
grep -n 'def test_run_once_retries_a_deadlock_victim_up_to_the_bound_then_lets_it_escape' services/orders/tests/unit/test_deadlock_classifier.py: 1 definition(s)
grep -n 'def test_oi18_a_poison_row_blocks_at_itself_after_the_clean_prefix_is_published' services/orders/tests/integration/test_outbox_relay.py: 1 definition(s)
grep -n 'def test_oi18_a_poison_row_at_the_head_publishes_nothing_and_raises_nothing_on_every_poll' services/orders/tests/integration/test_outbox_relay.py: 1 definition(s)
grep -n 'def test_oi19_a_sub_millisecond_instant_is_stored_enveloped_and_written_in_the_payload_as_the_same_millisecond' services/orders/tests/integration/test_outbox_envelope.py: 1 definition(s)
grep -n 'def test_oi19_every_instant_column_the_repository_writes_is_stored_truncated_never_rounded' services/orders/tests/integration/test_outbox_envelope.py: 1 definition(s)
grep -n 'def test_oi20_model_dump_json_equals_to_wire_json' packages/contracts/tests/test_envelope_generic.py: 1 definition(s)
grep -n 'def test_oi20_no_path_writes_an_instant_with_more_than_three_fractional_digits' packages/contracts/tests/test_envelope_generic.py: 1 definition(s)
grep -n 'def test_oi20_a_payload_copied_past_validation_is_refused_by_model_dump_json_and_by_to_wire_json' packages/contracts/tests/test_envelope_generic.py: 1 definition(s)
grep -n 'def test_the_generic_envelope_has_the_generated_envelopes_fields_aliases_order_and_pattern' packages/contracts/tests/test_envelope_generic.py: 1 definition(s)
grep -n 'def test_wire_instant_truncates_and_agrees_with_format_instant' packages/contracts/tests/test_envelope_generic.py: 1 definition(s)
grep -n 'def test_r11_event_envelope_refuses_an_envelope_with_an_absent_null_or_empty_field_and_an_event_type_that_does_not_match_the_patternx' packages/shared_kernel/tests/test_event_envelope.py: 0 definition(s)
sentinel caught: MISSING OR DUPLICATE: test_r11_event_envelope_refuses_an_envelope_with_an_absent_null_or_empty_field_and_an_event_type_that_does_not_match_the_patternx in packages/shared_kernel/tests/test_event_envelope.py
```


## 4. The ported-idiom ledger: rows confirmed or corrected from what actually ran

(`design.md` §2, L1–L27. "Guard" below is the task that actually proves the row; where it differs from the design's column it says so.)

| # | Result | What ran |
|---|---|---|
| L1 | confirmed | one `AsyncSession` and one transaction per `begin()`; guards 3.10 (both cases), 6.2; arm 3.10a (commit on exception) |
| L2 | confirmed; guard is **4.18**, not 4.11 as the design column says | `session.connection(execution_options={"isolation_level": "READ COMMITTED"})` before the first statement, in the relay and in the unit of work; both pinned and armed (4.18a, 4.18b: without the pin the listener records `repeatable read`). PostgreSQL direction probed; the InnoDB direction is cited, not probed |
| L3 | confirmed, **measured** | skip-versus-block §5.4 |
| L4 | confirmed, **measured** | one `add_all` + single flush preserved raise order on this stack (§5.3); one flush per row is kept anyway; arm 4.8c (writer inserts reversed) |
| L5 | confirmed | arm 4.7 (stamp and commit before the publish) |
| L6 | confirmed, observed not inferred | `after_commit` absent and `after_rollback` present on a timed-out cycle; arm 4.11b records `['commit']` |
| L7 | confirmed | arm 4.11a (no `asyncio.timeout`: the test's own 5 s bound fires) |
| L8 | confirmed | `grep -rn "except BaseException\|except:" services/orders/src` returns nothing (exit 1); it first matched a docstring sentence in `relay.py`, reworded; arm 5.4 |
| L9 | confirmed; citation in §5.1 | arms 4.4a |
| L10 | confirmed | `str(correlation_id).encode("utf-8")`; the test computes the default partitioner's partition (`aiokafka.partitioner.DefaultPartitioner`) and compares it with the broker's; arms 4.13a, 4.13b |
| L11 | confirmed, with a surprise | the row mapper reads the row alone (arm 3.13c). asyncpg hands back its own `UUID` subclass (`asyncpg.pgproto.pgproto.UUID`); `UniqueId` (`type(...) is uuid.UUID`) refused it on the first load (measured), so `order_mapper._unique_id` rebuilds a plain `uuid.UUID`. pydantic's `UUID` field accepted the subclass |
| L12 | confirmed | the existing `RawJson` / `payload::text`; the byte-exact case 4.14 |
| L13 | confirmed | `grep` in §10: exactly one `json.loads` in code (`outbox/wire.py:32`), no `json.dumps` and no `model_dump_json` in `infrastructure` code (the `persistence/types.py` hits are its pre-existing docstring) |
| L14 | confirmed and extended | `wire_instant` is applied in the mapper, the writer's payload mapper, the relay's stamp (`SystemClock`) and every repository column; guards 3.14, `test_oi19_every_instant_column_the_repository_writes_is_stored_truncated_never_rounded`, `test_every_instant_of_every_payload_and_envelope_is_truncated_to_the_millisecond`; arms 3.14a, 3.14c, 3.14d1–d7, 3.9e1–e6, 3.2 |
| L15 | confirmed | no `SELECT` in the dedup path (grep §10); arm 6.5 (read-then-write) fails with `UniqueViolationError`, 6.6 sibling constant |
| L16 | confirmed | arm 3.11 (`pull_domain_events()` inside `save`) |
| L17 | confirmed; reproduced before the fix | §5.5; the constructed cycle made the relay the victim in every run (the two deadlock tests passed in every run of this session, including both `quality.sh` runs); arms 4.19a, 4.19b |
| L18 | confirmed | `OutboxRelayTask.run`; arm 5.2a |
| L19 | confirmed | arm 5.3 |
| L20 | confirmed | arm 5.2b |
| L21 | confirmed | three poison kinds (not an object, `eventType` outside the pattern, a number `json.loads` turns into `inf`); arms 4.12a–d |
| L22 | confirmed | arms 7.2a–d; a mention in a comment or string does not trip the contract (7.2c, recorded, not armed) |
| L23 | confirmed | arm 4.4b (producer built in `__init__`) |
| L24 | confirmed | §10: `Any` appears only as `dict[str, Any]` in `outbox/wire.py`; `kafka_publisher.py` has no `Any` (the missing stubs make `AIOKafkaProducer` `Any` through the one allowed override and it is assigned to a `Protocol`-typed variable); sentinel 7.1 |
| L25 | **corrected** | the design says `PytestUnraisableExceptionWarning` would catch an unretrieved future exception. asyncio reports it through the loop's exception handler (a log record), not as an unraisable warning, so that guard cannot fail. The armed guard is `test_a_batch_with_two_failed_records_names_every_failed_event_id_and_retrieves_every_exception`: both failed ids are named and every future's `_log_traceback` is `False`; arm 4.10c |
| L26 | confirmed | arm 1.4a; the trailing-newline case fails under `re.match("^...$")` |
| L27 | confirmed, with a correction | `enum.Enum`, explicit values. But `design.md` §6.1 puts `ConsumerName` in the canonical file and §6.4 case 2 forbids `orders` / `projector` / `notifications` in it: §11 divergence 1 |


## 5. Measurements and citations

### 5.1 aiokafka (L9, task 4.3): version and source
`aiokafka==0.14.0` (transitive `async-timeout==5.0.1`; `packaging` and `typing-extensions` were already present). `python -W error::DeprecationWarning -c "import aiokafka; from aiokafka import AIOKafkaProducer"` is clean, and so is constructing and stopping one producer inside `asyncio.run` under the same flag: **no `filterwarnings` line was added**. The installed source (`.venv/lib/python3.14/site-packages/aiokafka/`): `producer/sender.py:141` `drain_by_nodes(ignore_nodes=self._in_flight, muted_partitions=...)`, `:148` `self._in_flight.add(node_id)`, `:149-150` every partition of an in-flight batch is muted, `:290` removed when the request completes: one produce request per node at a time and no two batches of one partition in flight, so there is no `max_in_flight` option to set. `producer/producer.py:265-272`: idempotence requires `acks` of `"all"` or `-1`.

### 5.2 The claim SQL as emitted (task 4.5; `before_cursor_execute` capture, batch size 7)
```
SELECT outbox.id, outbox.event_id, outbox.event_type, outbox.aggregate_id, outbox.correlation_id, outbox.causation_id, CAST(outbox.payload AS TEXT) AS payload, outbox.occurred_at, outbox.published_at, outbox.created_at, outbox.seq, outbox.trace_parent FROM outbox WHERE outbox.published_at IS NULL ORDER BY outbox.seq LIMIT $1::INTEGER FOR UPDATE SKIP LOCKED   | (7,)
UPDATE outbox SET published_at=$1::TIMESTAMP WITH TIME ZONE WHERE outbox.id IN ($2::UUID)
```

### 5.3 Batched flush (task 4.8, design L4), measured, not asserted
Forty `Outbox` rows with random primary keys added by one `session.add_all(rows)` and one `await session.flush()`: SQLAlchemy emitted one `executemany` `INSERT INTO outbox (...)` and `ORDER BY seq` returned the rows in add order, on four runs. So this stack preserves the order in a batched flush; the writer still flushes once per row and does not rely on it.

### 5.4 Skip versus block (task 4.17), measured
Relay A holds a claim of 5 of 20 rows, relay B (own engine, both production `OutboxRelay`) runs under `asyncio.timeout(3)`:
```
OI13 measured: relay B returned in 0.033s while relay A held its claim
1 passed in 2.98s
OI13 measured: relay B returned in 0.035s while relay A held its claim
1 passed in 3.04s
OI13 measured: relay B returned in 0.037s while relay A held its claim
1 passed in 3.08s
```
B returns a non-empty batch (5), disjoint from A's, in 0.033-0.038 s. The same test armed the other way, diagnoses verbatim:
* `skip_locked=False`: `Failed: relay B BLOCKED on rows relay A holds: the claim does not skip locked rows` (the 3 s bound fired, `asyncio.exceptions.CancelledError / TimeoutError`)
* no `with_for_update`: `AssertionError: B DUPLICATED A's rows: {UUID('29852792-...'), ...}`

### 5.5 The deadlock (task 4.19, #8 id 87): before and after
Constructed cycle (`test_outbox_relay_deadlock.py` docstring): A claims r1, r2; C takes `LOCK TABLE outbox IN SHARE MODE`; A is released and its stamp blocks (`pg_locks` shows the ungranted request); C asks `SELECT ... FOR UPDATE` on r1. The relay was the victim in every run of this session. **Before** (the retry bounded at one attempt, kept as the permanent test `test_oi17_without_the_retry_the_constructed_deadlock_escapes_run_once_as_40p01`), verbatim:
```
OI17 reproduced, escaping run_once: (sqlalchemy.dialects.postgresql.asyncpg.Error) deadlock detected
[SQL: UPDATE outbox SET published_at=$1::TIMESTAMP WITH TIME ZONE WHERE outbox.id IN ($2::UUID, $3::UUID)]
[parameters: (datetime.datetime(2026, 10, 6, 12, 40, 51, 300000, tzinfo=datetime.timezone.utc), UUID('1cb1fbc0-e499-4434-aad4-b47ce1f8b0a8'), UUID('623b6dae-e25d-4cf4-b3ae-02617f26cd42'))]
(Background on this error at: https://sqlalche.me/e/21/dbapi)
..
2 passed in 5.27s
```
**After**: `run_once` returns `RelayResult(claimed=1, published=1)`, exactly one WARNING (`attempt == 1`), the retried cycle takes r2 only (its claim skips r1, now C's), r2 is stamped, r1 is not and the next poll publishes it; C's statement succeeded (A, not C, was the victim). Arms 4.19a/4.19b fail with `relay A's run_once ended instead of retrying the deadlock victim: DBAPIError('(sqlalchemy.dialects.postgresql.asyncpg.Error) deadlock detected')`.

### 5.6 Stack down (task 2.1; #8 id 104)
```
$ docker ps --format "{{.Names}}"
otcpy-n8n
$ ss -ltn | grep -E ":(5432|9092|4222|27017|29092) "
(nothing listening)
```
`./quality.sh` (below) and the orders integration suite alone (`uv run pytest services/orders/tests/integration`: 82 passed in 33.7 s, run before the final test additions) ran in that state. The fixture's bootstrap pointed at `localhost:9092` fails with `KafkaConnectionError: Unable to bootstrap from [('localhost', 9092, ...)]` (arm 2.1).


## 6. The arming table

Protocol for every row (`arm.py`): `cp` the file to a backup, apply the one mutation (it must match exactly once, else the row aborts), run the named test(s), record the failure, restore from the backup, `cmp`, delete `__pycache__`, re-run green. The row text below is the first lines of the real failure, verbatim (cut at ~200 characters by the recorder). Rows are in the order they were run, not task order. A row marked `PASSED (GUARD DID NOT FIRE)` is a finding, not an arm; each is closed in §7 or §11.

| Arm | Mutation | Test | Failure |
|---|---|---|---|
| 1.3a | event_envelope.py imports `sys` instead of `re` (census sees `re` unused) | test_the_import_allowlist_is_the_census_derived_from_the_real_population | `AssertionError: allow-list not in the census: unused=['re'] missing=['sys']` |
| 1.3b | `"re"` removed from ALLOWED_ROOTS | same | `AssertionError: allow-list not in the census: unused=[] missing=['re']` |
| 1.3c | `MODULE_NAMES["event_envelope"]` removed | test_the_kernel_module_population_is_the_literal_list | `AssertionError: a kernel module was added or removed: +['event_envelope'] -[]` |
| 1.4a | `re.fullmatch(EVENT_TYPE_PATTERN, x)` -> `re.match("^"+EVENT_TYPE_PATTERN+"$", x)` | test_r11_event_envelope_refuses_...[event_type-trailing_newline] | `Failed: DID NOT RAISE IncompleteDomainEventEnvelopeError` (1 failed, 23 passed) |
| 1.4b | delete `_require_id("causation_id", ...)` | same, 3 cases | FAILED ...[causation_id-none], [causation_id-plain_uuid], [causation_id-nil_unique_id] (3 failed, 22 passed) |
| 1.4c | EVENT_TYPE_PATTERN `[a-z_]+` -> `[a-z]+` | test_the_event_type_pattern_is_the_asyncapi_envelope_pattern (+ catalogue case for order.saga_failed.v1) | `AssertionError: assert '^[a-z]+\\.[a-z_]+\\.v[0-9]+$' == '^[a-z]+\\.[a-z]+\\.v[0-9]+$'` |
| 1.7a | `_serialize`: `if False and key in data and _holds_datetime(value)` (revert the datetime replacement) | test_oi20_model_dump_json_equals_to_wire_json; test_oi20_no_path_writes_an_instant_with_more_than_three_fractional_digits | `AssertionError: model_dump_json wrote a long fraction: {...}` (2 failed, 3 passed) |
| 1.7b | `_serialize`: `type(self).model_validate(python_dump)` -> `pass` | test_oi20_a_payload_copied_past_validation_is_refused_by_model_dump_json_and_by_to_wire_json | `Failed: DID NOT RAISE PydanticSerializationError` (1 failed, 4 passed) |
| 1.7c | Envelope: `aggregate_id` and `correlation_id` swapped | test_the_generic_envelope_has_the_generated_envelopes_fields_aliases_order_and_pattern | `AssertionError: assert ['event_id', ...rred_at', ...] == ['event_id', ...rred_at', ...]` |
| 1.7d | wire_instant rounds (`(us + 500)//1000*1000`) | test_wire_instant_truncates_and_agrees_with_format_instant | `AssertionError: (997, datetime.datetime(2026, 10, 6, 9, 30, 5, 1000, tzinfo=datetime.timezone.utc))` |
| 2.2 | topic created with 1 partition (`KAFKA_TOPIC_PARTITIONS = 1`) | test_the_kafka_fixture_topic_has_six_partitions | `AssertionError: otc.orders.facts.v1 has 1 partitions on the broker: [{'error_code': 0, 'partition': 0, ...}]` / `assert 1 == 6` |
| 2.1 | fixture yields bootstrap `localhost:9092` (stack down, nothing listening, verified by `ss -ltn`) | test_the_kafka_fixture_topic_has_six_partitions | `aiokafka.errors.KafkaConnectionError: KafkaConnectionError: Unable to bootstrap from [('localhost', 9092, <AddressFamily.AF_UNSPEC: 0>)]` |
| 2.3a | `ALTER DATABASE ... SET default_transaction_isolation = 'repeatable read'` then reconnect | test_the_fixture_server_has_the_setting_the_deployed_server_has[default_transaction_isolation] | `AssertionError: the fixture server's default_transaction_isolation is 'repeatable read'; the deployed server's is 'read committed'` |
| 2.3b | root conftest Postgres `with_command(["postgres","-c","timezone=UTC",...])` removed (this was the REAL finding: unarmed fixture read `Etc/UTC`) | same [timezone] | `AssertionError: the fixture server's timezone is 'Etc/UTC'; the deployed server's is 'UTC'` |
| 3.4a | `populate_by_name=True` on KafkaSettings | test_bare_enabled_batch_size_brokers_and_client_id_change_nothing | `AssertionError: assert ('elsewhere:1...someone-else') == ('localhost:9... 'otc-orders')` |
| 3.4b | alias `KAFKA_SECURITY` added to KafkaSettings, not cleared by the fixture | test_the_fixture_clears_every_alias_the_settings_classes_declare | `AssertionError: assert {'KAFKA_BROKE...EOUT_MS', ...} == {'KAFKA_BROKE...ELAY_ENABLED'}` |
| 3.4c | `populate_by_name=True` on OutboxRelaySettings | test_bare_enabled_batch_size_brokers_and_client_id_change_nothing | FAILED (1 failed, 3 passed) |
| 3.8a | mapper reads line discount from the price column | test_a_placed_order_round_trips_through_save_and_get_by_id | FAILED (armed): `AssertionError: assert {UniqueId(val..., 1999, 1999)} == {UniqueId(val...2, 1234, 100)} / ` 1 failed in 2.50s |
| 3.8b | get_by_reference queries by id | test_a_cancelled_order_round_trips_through_get_by_reference_with_notes_reason_and_line_dis | FAILED (armed): `ValueError: invalid UUID 'ORD-000007': length must be between 32..36 characters, got 10 / asyncpg.exceptions.DataError: invalid input for query argument $1: 'ORD-000007' (invalid UUID 'ORD-000007': length must be between 32..36 characters, got 10)` 1 failed in 4.10s |
| 3.8c | update path skips deleting a removed line | test_save_of_a_loaded_order_inserts_updates_and_deletes_its_changed_lines | FAILED (armed): `AssertionError: A removed, C added / assert {UniqueId(val...cbbcc60f28'))} == {UniqueId(val...3210c67af7'))}` 1 failed in 3.66s |
| 3.10a | unit of work commits on exception | test_r13_persists_neither_the_aggregate_nor_the_outbox_record_and_publishes_nothing_when_t | FAILED (armed): `assert (1, 2, 1) == (0, 0, 0) / ` 1 failed in 2.55s |
| 3.10a2 | (same mutation) the SECOND case | test_r13_rolls_back_an_outbox_row_already_written_when_a_later_save_in_the_same_transactio | FAILED (armed): `sqlalchemy.exc.PendingRollbackError: This Session's transaction has been rolled back due to a previous exception during flush. To begin a new transaction with this Session, first issue Session.rollbac / [SQL: INSERT INTO orders (id, order_reference, request_id, order_date, company_id, retailer_id, currency_id, initial_amount, initial_discount, total_amount, status, cancellation_reason, notes, created` 1 failed in 3.76s |
| 3.10b | delete the writer call from save | test_r13_persists_neither_the_aggregate_nor_the_outbox_record_and_publishes_nothing_when_t | FAILED (armed): `assert (1, 2, 0) == (1, 2, 2) / ` 1 failed in 2.56s |
| 3.11 | drain with pull_domain_events() inside save (pre-commit clear) | test_oi9_a_retry_from_the_same_instance_after_a_rollback_writes_exactly_one_outbox_row_per | FAILED (armed): `AssertionError: a rolled-back unit of work must not clear the events / assert [] == [UUID('ca4782...5258d17a45b')]` 1 failed in 2.74s |
| 3.12a | writer copies event_id into causation_id | test_r12_stamps_every_fact_of_one_order_with_the_order_id_as_correlation_id_and_the_causin | FAILED (armed): `AssertionError: assert UUID('c004667f-58a9-46fc-a688-7b9328c3746a') == UUID('a014db29-46bd-4238-adc4-aa2766c418e7') / +  where UUID('c004667f-58a9-46fc-a688-7b9328c3746a') = <otc_orders.infrastructure.persistence.models.Outbox object at 0x7180c6133110>.causation_id` 1 failed in 2.60s |
| 3.12b | writer reads correlation_id from aggregate_id's sibling (causation_id) | test_r12_stamps_every_fact_of_one_order_with_the_order_id_as_correlation_id_and_the_causin | FAILED (armed): `AssertionError: assert UUID('270958a7-bee5-4402-9b44-91e5f2408322') == UUID('380279c4-757f-4d16-999a-48065cc03bbb') / +  where UUID('270958a7-bee5-4402-9b44-91e5f2408322') = <otc_orders.infrastructure.persistence.models.Outbox object at 0x7da2dfe13c50>.correlation_id` 1 failed in 2.55s |
| 3.13a | delete the validate_domain_event_envelope call | test_oi1_writer_refuses_an_event_with_an_incomplete_envelope_before_any_row_is_written | FAILED (armed): `AttributeError: 'NoneType' object has no attribute 'value'` 1 failed in 2.43s |
| 3.13b | delete the catalogue check (key lookup + payload type) | test_oi1_writer_refuses_an_event_type_outside_the_fact_catalogue | FAILED (armed): `AttributeError: 'NoneType' object has no attribute 'model_fields'` 1 failed in 2.43s |
| 3.13b2 | delete the payload-type check | test_oi1_writer_refuses_a_payload_that_is_not_the_catalogues_payload_for_the_type | FAILED (armed): `Failed: DID NOT RAISE UndeclaredFactError` 1 failed in 2.60s |
| 3.13c | row mapper defaults causation_id to a fresh uuid4() | test_oi1_relay_reconstructs_the_complete_envelope_from_the_stored_record_alone | FAILED (armed): `AssertionError: assert '3bbe9a27-1fb...-4fbb1a5eb747' == '134fda09-88c...-d3e3302a681d' / ` 1 failed in 2.50s |
| 3.14a | remove wire_instant from the envelope instant (payloads.build_fact) | test_oi19_a_sub_millisecond_instant_is_stored_enveloped_and_written_in_the_payload_as_the_ | FAILED (armed): `assert datetime.datetime(2026, 10, 5, 12, 0, 5, 124000, tzinfo=datetime.timezone.utc) == datetime.datetime(2026, 10, 5, 12, 0, 5, 123000, tzinfo=datetime.timezone.utc)` 1 failed in 3.77s |
| 3.14c | remove wire_instant from the row mapper's insert path (updated_at=) | test_oi19_a_sub_millisecond_instant_is_stored_enveloped_and_written_in_the_payload_as_the_ | FAILED (armed): `assert datetime.datetime(2026, 10, 5, 12, 0, 5, 124000, tzinfo=datetime.timezone.utc) == datetime.datetime(2026, 10, 5, 12, 0, 5, 123000, tzinfo=datetime.timezone.utc)` 1 failed in 3.86s |
| 5.2a | create_task(run_once()) per tick without awaiting it | test_oi6_never_starts_a_second_cycle_while_one_is_in_progress | FAILED (armed): `AssertionError: a second cycle started while the first was still running / assert 10 == 1` 1 failed in 0.46s |
| 5.2b | cancel the in-flight cycle on stop | test_oi6_stop_waits_for_the_in_flight_cycle | FAILED (armed): `AssertionError: stop() must wait for the in-flight cycle / assert not True` 1 failed in 0.47s |
| 5.3 | remove the except Exception (replaced by an unrelated class) | test_relay_task_survives_a_failed_cycle_and_runs_the_next | FAILED (armed): `asyncio.exceptions.CancelledError / TimeoutError` 1 failed in 2.43s |
| 5.4 | except BaseException in the loop | test_relay_task_propagates_cancellation | FAILED (armed): `AssertionError: the cancellation was swallowed: the loop is still running / assert <Task cancelling name='Task-2' coro=<OutboxRelayTask.run() running at /home/juanpabloperez/Work/Projects/Assessments/o...rvices/orders/src/otc_orders/infrastructure/outbox/relay_task.py:39> wai` 1 failed in 2.42s |
| 5.5 | ignore enabled | test_a_disabled_relay_task_returns_without_calling_run_once | FAILED (armed): `asyncio.exceptions.CancelledError / TimeoutError` 1 failed in 2.58s |
| 4.7 | stamp (and commit) before the publish | test_r14_stamps_a_record_only_after_the_broker_acknowledgement_and_republishes_an_unstampe | FAILED (armed): `AssertionError: stamped without an ack / assert True is False` 1 failed in 8.67s |
| 4.8a | claim ordered by occurred_at | test_oi2_orders_the_claim_by_seq_never_by_occurred_at_when_they_disagree | FAILED (armed): `AssertionError: ordered by something but seq / assert [UUID('698b2e...b7497c'), ...] == [UUID('531d4d...5e8f5b'), ...]` 1 failed in 3.97s |
| 4.8a2 | claim ordered by occurred_at (the append-order case) | test_oi2_publishes_records_written_by_one_transaction_in_append_order_although_they_share_ | PASSED (GUARD DID NOT FIRE): `(no E line)` 1 passed in 3.76s |
| 4.8b | claim ordered by id (a random uuid) | test_oi2_orders_the_claim_by_seq_never_by_occurred_at_when_they_disagree | FAILED (armed): `AssertionError: ordered by something but seq / assert [UUID('bf8213...119de3'), ...] == [UUID('2f3a58...2e355f'), ...]` 1 failed in 4.13s |
| 4.8c | the writer inserts the events reversed | test_oi2_publishes_records_written_by_one_transaction_in_append_order_although_they_share_ | FAILED (armed): `AssertionError: run 0: published out of append order / assert [UUID('d1927b...b86d8a07669')] == [UUID('c1236d...a2e64e96a11')]` 1 failed in 3.73s |
| 4.9 | high-water-mark predicate (seq > max published seq) | test_oi3_publishes_a_lower_sequence_record_that_committed_after_a_higher_one_was_published | FAILED (armed): `AssertionError: the lower seq was skipped / assert [UUID('01e6ce...218062768c4')] == [UUID('01e6ce...69ffba5071b')]` 1 failed in 3.57s |
| 4.10a | stamp the records that did succeed (first row of a failed batch) | test_oi8_leaves_every_record_of_a_rejected_batch_unstamped_logs_each_and_republishes_the_s | FAILED (armed): `assert (2, 1) == (2, 0) / ` 1 failed in 3.92s |
| 4.10b | delete the per-row log (debug instead of error) | test_oi8_leaves_every_record_of_a_rejected_batch_unstamped_logs_each_and_republishes_the_s | FAILED (armed): `AssertionError: one ERROR record per claimed row / assert 0 == 2` 1 failed in 3.80s |
| 4.11a | remove asyncio.timeout | test_oi14_abandons_a_publish_that_exceeds_the_timeout_rolls_the_claim_back_and_republishes | FAILED (armed): `asyncio.exceptions.CancelledError / TimeoutError` 1 failed in 8.91s |
| 4.11b | return normally from the failure branch so begin() commits | test_oi14_abandons_a_publish_that_exceeds_the_timeout_rolls_the_claim_back_and_republishes | FAILED (armed): `AssertionError: the claim transaction committed: ['commit'] / assert 'commit' not in ['commit']` 1 failed in 4.25s |
| 4.10c | gather without return_exceptions | test_a_batch_with_two_failed_records_names_every_failed_event_id_and_retrieves_every_excep | FAILED (armed): `RuntimeError: second failed` 1 failed in 0.18s |
| 4.4a | enable_idempotence False | test_oi7_producer_is_idempotent_so_an_internal_retry_can_neither_reorder_nor_duplicate | FAILED (armed): `assert False is True` 1 failed in 0.19s |
| 4.4b | producer constructed in __init__ | test_constructing_the_publisher_outside_a_running_loop_builds_no_kafka_client | FAILED (armed): `assert [<services.or...70b50e5a5400>] == [] / ` 1 failed in 0.18s |
| 4.2 | substitute sibling topic otc.fulfillment.facts.v1 | test_the_orders_facts_topic_is_the_asyncapi_orders_facts_address | FAILED (armed): `AssertionError: the constant is 'otc.fulfillment.facts.v1', the spec's ordersFacts address is 'otc.orders.facts.v1' / assert 'otc.orders.facts.v1' == 'otc.fulfillment.facts.v1'` 1 failed in 0.37s |
| 4.6a | classifier compares against 40001 | services/orders/tests/unit/test_deadlock_classifier.py | FAILED (armed): `AssertionError: assert ('40P01' == '40001' / ` 1 failed in 0.43s |
| 4.6b | retry on any DBAPIError | services/orders/tests/unit/test_deadlock_classifier.py | FAILED (armed): `IndexError: pop from empty list` 1 failed, 5 passed in 0.47s |
| 4.12a | remove the per-row catch (exception escapes run_once) | test_oi18_a_poison_row_blocks_at_itself_after_the_clean_prefix_is_published | FAILED (armed): `pydantic_core._pydantic_core.ValidationError: 1 validation error for Envelope[dict[str, Any]] / event_type` 1 failed in 3.74s |
| 4.12b | skip the poison row and keep converting | test_oi18_a_poison_row_blocks_at_itself_after_the_clean_prefix_is_published | FAILED (armed): `assert (3, 2) == (3, 1) / ` 1 failed in 3.81s |
| 4.12c | build the whole batch before publishing (the prefix is dropped) | test_oi18_a_poison_row_blocks_at_itself_after_the_clean_prefix_is_published | FAILED (armed): `assert (3, 0) == (3, 1) / ` 1 failed in 3.78s |
| 4.12d | head poison: skip it, keep converting | test_oi18_a_poison_row_at_the_head_publishes_nothing_and_raises_nothing_on_every_poll | FAILED (armed): `assert (2, 1) == (2, 0) / ` 1 failed in 3.77s |
| 4.13a | key by event_id | services/orders/tests/integration/test_fact_partitioning.py | FAILED (armed): `AssertionError: one partition per order / assert {4, 5} == {3}` 1 failed in 8.67s |
| 4.13b | key by a constant (broker-read precondition) | services/orders/tests/integration/test_fact_partitioning.py | FAILED (armed): `AssertionError: precondition (read from the broker): the two orders landed on ONE partition, so 'one partition per order' proves nothing: {UniqueId(value=UUID('0b84a297-8e44-4ee9-a2e5-e3a8a1d366b4')): / assert {0} != {0}` 1 failed in 8.80s |
| 4.14a | write the envelope with json.dumps defaults | test_oi15_relay_publishes_bytes_identical_to_the_golden_envelope[order_placed_v1.json] | FAILED (armed): `AssertionError: order_placed_v1.json: the consumed bytes differ from the golden file / assert b'{"eventId":...iscount": 0}}' == b'{"eventId":...Discount":0}}'` 1 failed in 7.52s |
| 4.14b | write occurredAt with datetime.isoformat() | test_oi15_relay_publishes_bytes_identical_to_the_golden_envelope[order_placed_v1.json] | FAILED (armed): `AssertionError: order_placed_v1.json: the consumed bytes differ from the golden file / assert b'{"eventId":...Discount":0}}' == b'{"eventId":...Discount":0}}'` 1 failed in 7.53s |
| 4.14c | drop ensure_ascii=False (non-ASCII golden) | test_oi15_relay_publishes_bytes_identical_to_the_golden_envelope[order_cancelled_v1.json] | FAILED (armed): `AssertionError: order_cancelled_v1.json: the consumed bytes differ from the golden file / assert b'{"eventId":...t_rejected"}}' == b'{"eventId":...t_rejected"}}'` 1 failed in 7.45s |
| 4.14d | add a traceparent header | test_oi15_relay_publishes_bytes_identical_to_the_golden_envelope[order_placed_v1.json] | FAILED (armed): `AssertionError: exactly x-event-type and content-type / assert [('x-event-ty...69203331-01')] == [('x-event-ty...cation/json')]` 1 failed in 8.66s |
| 4.14e | drop the SA-2 note from the cancelled payload | test_sa2_published_cancelled_envelope_carries_the_note_with_the_exact_supplied_text | FAILED (armed): `KeyError: 'note'` 1 failed in 8.56s |
| 4.14f | SA-2: a note appears when none was supplied | test_sa2_published_cancelled_envelope_omits_the_note_key_when_none_was_supplied | FAILED (armed): `AssertionError: an absent note is an absent key, never an explicit null / assert 'note' not in {'orderReference': 'ORD-000042', 'retailerCode': 'RET-01', 'companyCode': 'CMP-01', 'cancellationReason': 'stock_rejected', ...}` 1 failed in 7.53s |
| 4.14g | R11: swap eventId and aggregateId in the published envelope | test_r11_published_envelope_carries_the_seven_fields_in_declared_order_with_none_absent_nu | FAILED (armed): `AssertionError: every fact reached the broker / assert set() == {UUID('6cdbce...14c98d90c10')}` 1 failed in 8.71s |
| 4.15 | remove with_for_update (OI4) | test_oi4_two_concurrent_relays_take_disjoint_batches_and_publish_every_record_exactly_once | FAILED (armed): `AssertionError: a record went to both relays / assert {UUID('01ce94...c68b84'), ...} == set()` 1 failed in 2.86s |
| 4.16 | stamp and COMMIT the claimed rows before publishing | test_oi5_records_claimed_by_a_relay_whose_connection_died_are_claimed_on_the_next_poll_wit | FAILED (armed): `AssertionError: the dead relay's claim must be claimable again at once / assert 0 == 3` 1 failed in 3.81s |
| 4.17a | skip_locked=False (B must BLOCK) | test_oi13_a_claim_skips_rows_another_relay_holds_and_returns_without_waiting | FAILED (armed): `asyncio.exceptions.CancelledError / TimeoutError` 1 failed in 6.48s |
| 4.17b | no with_for_update (B must DUPLICATE A's rows) | test_oi13_a_claim_skips_rows_another_relay_holds_and_returns_without_waiting | FAILED (armed): `AssertionError: B DUPLICATED A's rows: {UUID('29852792-dd22-4eff-b2c9-3296bf4539fc'), UUID('13a0be72-81e9-4e3b-b56f-e32296bbb544'), UUID('338db2c6-9716-4485-9bab-e666c9eb7c61'), UUID('4abb608f-127f-4c / assert False` 1 failed in 3.02s |
| 4.18a | remove the isolation pin from the relay | test_oi13_the_claim_runs_at_read_committed_under_an_engine_defaulting_to_repeatable_read | FAILED (armed): `AssertionError: the relay's transaction ran at ['repeatable read'] / assert ['repeatable read'] == ['read committed']` 1 failed in 2.51s |
| 4.18b | remove the isolation pin from the unit of work | test_the_unit_of_work_runs_at_read_committed_under_an_engine_defaulting_to_repeatable_read | FAILED (armed): `AssertionError: the unit of work's transaction ran at ['repeatable read'] / assert ['repeatable read'] == ['read committed']` 1 failed in 2.50s |
| 4.19a | remove the retry (a deadlock victim always escapes) | test_oi17_run_once_survives_a_constructed_deadlock_victim_and_retries_the_cycle | FAILED (armed): `AssertionError: relay A's run_once ended instead of retrying the deadlock victim: DBAPIError('(sqlalchemy.dialects.postgresql.asyncpg.Error) deadlock detected')` 1 failed in 3.53s |
| 4.19b | retry on 40001 instead of 40P01 | test_oi17_run_once_survives_a_constructed_deadlock_victim_and_retries_the_cycle | FAILED (armed): `AssertionError: relay A's run_once ended instead of retrying the deadlock victim: DBAPIError('(sqlalchemy.dialects.postgresql.asyncpg.Error) deadlock detected')` 1 failed in 3.56s |
| 4.20 | insert one unpublished outbox row into the seeded database before the relay runs | test_a_relay_over_the_seeded_orders_database_claims_nothing_and_publishes_nothing | FAILED (armed): `AssertionError: the relay claimed 1 seeded rows / assert 1 == 0` 1 failed in 7.77s |
| 6.4 | on a duplicate, call work anyway | test_r18_acknowledges_a_redelivered_fact_without_mutating_state_emitting_a_fact_or_issuing | FAILED (armed): `AssertionError: work was invoked once in total / assert [0, 1] == [0]` 1 failed in 4.06s |
| 6.2 | the dedup insert commits in its OWN transaction ahead of work (#7's M4) | test_r17_records_the_event_id_and_consumer_name_in_the_same_transaction_as_the_state_chang | FAILED (armed): `AssertionError: no dedup row / assert [(UUID('5c49f...orders.saga')] == [(UUID('5c49f...orders.saga')]` 1 failed in 4.02s |
| 6.3 | the dedup insert commits in its OWN transaction ahead of work | test_r17_leaves_no_dedup_row_when_a_failure_inside_work_rolls_back_the_whole_transaction | FAILED (armed): `AssertionError: the dedup row rolled back with the work / assert [(UUID('d900e...orders.saga')] == []` 1 failed in 3.86s |
| 6.5 | SELECT then INSERT (read-then-write) instead of INSERT ... ON CONFLICT DO NOTHING | test_oi10_applies_the_effects_once_when_the_same_event_is_delivered_concurrently | FAILED (armed): `asyncpg.exceptions.UniqueViolationError: duplicate key value violates unique constraint "uq_processed_events_event_id_consumer" / DETAIL:  Key (event_id, consumer)=(e486ae4f-e931-461a-8d39-83a78c117fdd, orders.saga) already exists.` 1 failed in 4.31s |
| 6.6 | write the constant 'orders.saga' instead of consumer.value | test_dedup_is_per_event_id_and_consumer_pair_not_per_event_id | FAILED (armed): `AssertionError: assert (<Consumption... 'duplicate'>) == (<Consumption... 'processed'>) / ` 1 failed in 3.75s |
| 6.8a | write otc_orders into the canonical body | test_case_2_the_canonical_is_adoptable_verbatim_naming_no_service | FAILED (armed): `assert ["names 'orde...e vocabulary"] == [] / ` 1 failed in 0.07s |
| 6.8a2 | write BillingDb into the canonical body | test_case_2_the_canonical_is_adoptable_verbatim_naming_no_service | FAILED (armed): `assert ["names 'bill...e vocabulary"] == [] / ` 1 failed in 0.08s |
| 6.8b | compare banners instead of bodies (a one-character difference goes unreported) | test_case_1_sentinel_a_copy_that_differs_by_one_character_is_reported | FAILED (armed): `AssertionError: assert 2 == 1 / +  where 2 = len(['services/billing/src/otc_billing/infrastructure/messaging/idempotent_consumer.py diverges from the canonical outside.../orders/src/otc_orders/infrastructure/messaging/idempotent_con` 1 failed in 0.08s |
| 6.8b2 | compare banners instead of bodies (the real-population case) | test_case_1_every_write_models_copy_is_byte_identical_to_the_canonical_after_the_banner | FAILED (armed): `AssertionError: assert ['services/or...e the banner'] == [] / ` 1 failed in 0.08s |
| 6.8c | ignore the Kafka consumer reference | test_case_3_sentinel_a_consumer_of_facts_without_a_copy_is_reported | FAILED (armed): `AssertionError: assert ['otc_fulfillment'] == ['otc_billing'] / ` 1 failed in 0.10s |
| 6.8d | variant check drops the Divergence line requirement | test_case_4_sentinel_a_variant_without_a_divergence_line_is_reported | FAILED (armed): `assert [] == ["otc_project...Divergence:'"] / ` 1 failed in 0.08s |
| 7.2a | `import aiokafka` in new module `otc_orders/application/zz_arm.py` | lint-imports `fact-producer-confinement` | `otc_orders.application is not allowed to import aiokafka: - otc_orders.application.zz_arm -> aiokafka (l.1)`; `Contracts: 10 kept, 1 broken.` |
| 7.2b | `from otc_orders.infrastructure.outbox.publisher import FactPublisher` in application | lint-imports `layers-orders` | `otc_orders: presentation > infrastructure > application > domain BROKEN`; `otc_orders.application.zz_arm -> otc_orders.infrastructure.outbox.publisher` |
| 7.2c | `aiokafka` only in a comment, a string and a triple-quoted string | lint-imports | NOT a failure (recorded, not armed): `Contracts: 11 kept, 0 broken.` (import-linter reads the import graph, not text) |
| 7.2d | `import aiokafka` in `otc_billing/presentation/zz_arm.py` (a sibling service) | lint-imports | the same contract names it (all seven services listed) |
| 7.3 | one more session.add( in the writer | test_every_write_path_in_the_service_is_a_classified_literal[orders] | FAILED (armed): `AssertionError: services/orders/src has an unclassified write path (or lost a classified one, or gained a second occurrence of one): add it to EXPECTED with its classification. Found: {'domain/totals. / assert {'domain/tota...d'): 2}), ...} == {'domain/tota...d'): 1}), ...}` 1 failed in 0.10s |
| 7.1 | temporary `def leak() -> typing.Any` + `def uses_leak() -> int: return leak()` in relay.py | `uv run mypy` (strict, warn_return_any) | see report: the grep for `Any` lists the sentinel line; mypy reports `Returning Any from function declared to return "int"  [no-any-return]` |
| 3.14d1 | wire_instant removed: orders.order_date (insert) | test_oi19_every_instant_column_the_repository_writes_is_stored_truncated_never_rounded | FAILED (armed): `assert (datetime.dat...timezone.utc)) == (datetime.dat...timezone.utc)) / ` 1 failed in 2.54s |
| 3.14d2 | wire_instant removed: orders.created_at (insert) | test_oi19_every_instant_column_the_repository_writes_is_stored_truncated_never_rounded | FAILED (armed): `assert (datetime.dat...timezone.utc)) == (datetime.dat...timezone.utc)) / ` 1 failed in 2.79s |
| 3.14d3 | wire_instant removed: orders.updated_at (insert) | test_oi19_every_instant_column_the_repository_writes_is_stored_truncated_never_rounded | FAILED (armed): `assert (datetime.dat...timezone.utc)) == (datetime.dat...timezone.utc)) / ` 1 failed in 2.61s |
| 3.14d4 | wire_instant removed: orders.order_date (update, same instance saved twice) | test_oi19_every_instant_column_the_repository_writes_is_stored_truncated_never_rounded | FAILED (armed): `assert (datetime.dat...timezone.utc)) == (datetime.dat...timezone.utc)) / ` 1 failed in 2.55s |
| 3.14d5 | wire_instant removed: orders.updated_at (update) | test_oi19_every_instant_column_the_repository_writes_is_stored_truncated_never_rounded | FAILED (armed): `assert (datetime.dat...timezone.utc)) == (datetime.dat...timezone.utc)) / ` 1 failed in 2.56s |
| 3.14d6 | wire_instant removed: order_items created_at/updated_at (insert) | test_oi19_every_instant_column_the_repository_writes_is_stored_truncated_never_rounded | FAILED (armed): `assert {datetime.dat...timezone.utc)} == {datetime.dat...timezone.utc)} / ` 1 failed in 2.69s |
| 3.14d7 | wire_instant removed: order_items.updated_at (update) | test_oi19_every_instant_column_the_repository_writes_is_stored_truncated_never_rounded | FAILED (armed): `AssertionError: the changed line / assert datetime.datetime(2026, 10, 5, 12, 0, 4, 123000, tzinfo=datetime.timezone.utc) in {datetime.datetime(2026, 10, 5, 12, 0, 4, 124000, tzinfo=datetime.timezone.utc)}` 1 failed in 2.69s |
| 3.9e1 | wire_instant removed: placed.order_date | test_every_instant_of_every_payload_and_envelope_is_truncated_to_the_millisecond | FAILED (armed): `assert 123987 == 123000 / +  where 123987 = datetime.datetime(2026, 10, 6, 9, 30, 5, 123987, tzinfo=datetime.timezone.utc).microsecond` 1 failed in 0.20s |
| 3.9e2 | wire_instant removed: confirmed_at | test_every_instant_of_every_payload_and_envelope_is_truncated_to_the_millisecond | FAILED (armed): `assert 123987 == 123000 / +  where 123987 = datetime.datetime(2026, 10, 6, 9, 30, 5, 123987, tzinfo=datetime.timezone.utc).microsecond` 1 failed in 0.25s |
| 3.9e3 | wire_instant removed: completed_at | test_every_instant_of_every_payload_and_envelope_is_truncated_to_the_millisecond | FAILED (armed): `assert 123987 == 123000 / +  where 123987 = datetime.datetime(2026, 10, 6, 9, 30, 5, 123987, tzinfo=datetime.timezone.utc).microsecond` 1 failed in 0.25s |
| 3.9e4 | wire_instant removed: cancelled_at | test_every_instant_of_every_payload_and_envelope_is_truncated_to_the_millisecond | FAILED (armed): `assert 123987 == 123000 / +  where 123987 = datetime.datetime(2026, 10, 6, 9, 30, 5, 123987, tzinfo=datetime.timezone.utc).microsecond` 1 failed in 0.25s |
| 3.9e6 | wire_instant removed: envelope occurredAt | test_every_instant_of_every_payload_and_envelope_is_truncated_to_the_millisecond | FAILED (armed): `AssertionError: assert 123987 == 123000 / +  where 123987 = datetime.datetime(2026, 10, 6, 9, 30, 5, 123987, tzinfo=datetime.timezone.utc).microsecond` 1 failed in 0.24s |
| 3.9e5 | wire_instant removed: compensation step occurred_at | test_every_instant_of_every_payload_and_envelope_is_truncated_to_the_millisecond | FAILED (armed): `assert [123987] == [123000] / ` 1 failed in 0.21s |
| 3.2 | SystemClock returns datetime.now(UTC) unwrapped | services/orders/tests/unit/test_system_clock.py | FAILED (armed): `AssertionError: whole milliseconds / assert False` 1 failed in 0.19s |
| 3.9a | swap initial_amount and total_amount in the placed payload | services/orders/tests/unit/test_outbox_payloads.py | FAILED (armed): `AssertionError: assert 8115 == 8465 / +  where 8115 = OrderPlacedPayload(order_reference='ORD-000123', retailer_code='RET-77', company_code='CMP-88', buyer_gln='40123450000...=2, unit_price=1234, line_discount=100)], initial_amount=8115, ` 1 failed in 0.24s |
| 3.9b | drop note from the cancelled payload | services/orders/tests/unit/test_outbox_payloads.py | FAILED (armed): `AssertionError: assert None == 'operator said so' / +  where None = OrderCancelledPayload(order_reference='ORD-000126', retailer_code='RET-80', company_code='CMP-91', cancellation_reason... occurred_at=datetime.datetime(2026, 10, 6, 9, 30, 5, 123000, t` 1 failed, 4 passed in 0.24s |
| 3.9c | map buyer_gln from supplier_gln | services/orders/tests/unit/test_outbox_payloads.py | FAILED (armed): `AssertionError: assert '5412345000006' == '4012345000009' / ` 1 failed in 0.24s |

Instruments arms that were not mutations: 7.1 (sentinel `def leak() -> typing.Any` in `relay.py`, with `def uses_leak() -> int: return leak()`): `grep -n Any` over `outbox/*.py` and `messaging/*.py` listed `relay.py:210: def leak() -> "typing.Any":` next to the two `wire.py` hits, and `uv run mypy` failed `relay.py:215: error: Returning Any from function declared to return "int"  [no-any-return]`; removed, `.mypy_cache` cleared, mypy green (290 files).


## 7. The constructor-call census, and the corruption sweep (feature 13's lesson)

Census: every constructor call in the new `src` that maps values into a fact, an envelope, a row or an aggregate (keyword or positional), found by walking the AST of the named functions (`sweep.py`; a call whose arguments are all one expression is not a mapping):

| File | Call sites (arguments) |
|---|---|
| `outbox/payloads.py` | `OrderLine` (5), `CompensationStep` (5), `OrderPlacedPayload` (12), `OrderConfirmedPayload` (6), `OrderCompletedPayload` (6), `OrderCancelledPayload` (7), `envelope_type` (7), `BuiltFact` x4 (3 each) |
| `outbox/writer.py` | `validate_domain_event_envelope` (6), `Outbox` (11), `UndeclaredFactError` x2 (2) |
| `outbox/wire.py` | `Envelope[dict[str, Any]]` (7), `PublishableFact` (4) |
| `persistence/order_mapper.py` | `OrderRow` (15), `OrderItemRow` (9), `OrderLineSnapshot` (6), `OrderSnapshot` (15), the `row.<attr>` assignments of `apply_to_order_row` (8) and `apply_to_order_item_row` (5), `Money(amount, currency)` x2 |
| `persistence/order_repository.py` | `ResolvedIds` (3), `OrderReferences` (5), `ReferenceDataMissingError` x2 (2) |
| `persistence/unit_of_work.py` | `SqlAlchemyOrderRepository` (2), `SqlAlchemyOrdersTransaction` (2) |
| `outbox/relay.py` | `PoisonedRow` (4), `RelayResult` x2 (3), `_Claimed` (3), `_Prefix` x2 (3), the `extra={...}` log dicts x3 (4-5 keys) |
| `messaging/idempotent_consumer.py` | the `.values(...)` of the dedup row (5) |
| `outbox/kafka_publisher.py` | `producer_options()` dict (4), `producer.send(...)` (3), `FactPublicationError` x2 (2) |

Method: for each argument, substitute the expression of the next sibling whose source text differs, run the file's tests, restore from backup and `cmp` (`sweep.py`, every mutant `restored=true`). Rounds, each over the tests as they stood:

| Round | Mutants | Killed | Survivors | What the survivors were, and the fix |
|---|---:|---:|---:|---|
| 1 | 183 | 166 | 17 | writer `Outbox.id <- event_id` and `aggregate_id <- correlation_id` (the aggregate mints them equal, so no real order tells them apart); the same swap in `wire.py`; the three totals columns and `created_at <- updated_at` of the `orders` row (written, never read back into the aggregate; every fixture had `created_at == updated_at`); `PoisonedRow.correlation_id` / `reason`, the aborted branch's `poisoned`, two log `extra` keys (never asserted); `producer.send(value/key/headers)` (not asserted at unit level). Fixed with `test_oi1_every_column_and_envelope_field_comes_from_its_own_event_field` (a hand-built event with five distinct ids), raw reads of the totals columns, `test_a_confirmed_order_saved_for_the_first_time_keeps_created_at_and_updated_at_apart`, assertions on the poisoned row and the log fields, and `test_publish_sends_every_fact_to_the_orders_topic_with_its_own_key_value_and_headers_in_order` |
| 2 | 214 (positional constructors added) | 205 | 9 | error-path constructors: `UndeclaredFactError(event_type, reason)`, `ReferenceDataMissingError(table, code)`, `FactPublicationError(ids, reason)` with swapped arguments. Fixed with assertions on `.event_type`, `.table`, `.code`, `.reason` and two new tests (an unknown reference code, a row that vanished between load and save) and `test_publishing_before_start_fails_naming_every_event_id_and_the_reason` |
| 3 | 44 (writer, repository, kafka publisher re-run after the fixes) | 44 | 0 | |
| 4 | 142 (payloads, mapper, writer re-run after the last test edits) | 142 | 0 | |

Final state: 214 distinct mutants over nine files, all killed by the final tests (files re-run in rounds 3 and 4 as their tests changed; the wire, unit-of-work, relay and consumer sweeps last ran in round 2 and no test they run was weakened afterwards: tests only gained assertions). Two further families the swap does not reach were armed by removal instead: every `wire_instant` call of the mapper (arms 3.14d1-d7) and of the payload mapper (3.9e1-e6) — two of those first PASSED (the insert-path `updated_at` and the update-path `order_date`, whose value an update never changed in the fixture) and were closed by reading the insert path before any update and by saving one aggregate twice in a transaction.

Another honest note from round 1: killed does not always mean killed for the right reason. A swap of two differently typed fields dies in pydantic or asyncpg with a type error, which is a kill but not an assertion about the field. The same-typed neighbours (the ones that matter: `buyer_gln <- supplier_gln`, `initial_amount <- total_amount`, ...) die on the distinct-value assertion, as the arms in §6 show.

Defeat list (CLAUDE.md), the rows that apply: **1** delete the behaviour (every arm above); **2** corrupt a supplied field (the sweep); **3** substitute a valid sibling identifier (the topic `otc.fulfillment.facts.v1` 4.2, `consumer.value` vs the `"orders.saga"` literal 6.6, `40001` for `40P01` 4.6/4.19, `correlation_id` vs `event_id` as the key 4.13a, the sibling service in 7.2d, an unlisted settings alias 3.4b); **4/6** shadow in a comment, string or triple-quoted string (7.2c: import-linter reads the import graph, so a mention in text does not trip the contract; recorded as a non-failure); **5** dead region (`if False:` was the mutation form in 3.13b2/4.19a, and the census instruments read dead regions by construction); **7** drop an optional element (the SA-2 note, 4.14e/f; the line `description` `None`); **9** satisfy the closer half and leave the premise stale (the R15 precondition was first computed from the ids only and could not see a publisher that ignored the key: it is now read from the broker too, arm 4.13b); **11** a form the instrument does not recognise (`insert as pg_insert` is an aliased import: the write-path census classifies it as an import hit plus a resolved `insert` call); **12** a path the population never drives (all the round-2 survivors were error-path constructors no test reached). Rows 8 (literal against literal: the topic and the event-type pattern are compared with values READ from `asyncapi.yaml`, 1.4 and 4.2) and 10 (build output in the population: `__pycache__` deleted after every arm; `find -size 0` run) hold without a separate arm.


## 8. Architecture guards (tasks 7.1-7.5)

* **7.1** `uv run ruff format --check` and `ruff check` clean; `uv run mypy` strict clean over 290 source files; no new `[[tool.mypy.overrides]]`, no `# type: ignore` in new `src` (`grep -rn "type: ignore" services/orders/src` empty). `grep -n "Any"` over `outbox/*.py` and `messaging/*.py`: `wire.py:17` (`from typing import Any`) and `wire.py:25` (`Envelope[dict[str, Any]]`: the relay's pass-through of the stored payload text; both allowed); nothing in `kafka_publisher.py`.
* **7.2** the contract `fact-producer-confinement` (all seven services, `application` and `presentation`); `lint-imports`: `Contracts: 11 kept, 0 broken`. Arms 7.2a-d in §6.
* **7.3** `EXPECTED["orders"]` gained four classified entries (`idempotent_consumer.py`, `relay.py`, `writer.py`, `order_repository.py`), counts read from `scan_service("orders")`, each hit classified in the file: guarded (`session.add` x1 in the writer, x3 in the repository), no guarded column (the dedup `insert`/`execute`, the stamp `update`/`execute`, `session.delete`), not a write (`set.add` x3, `set.update`, two `SELECT` executes). Arm 7.3.
* **7.4** census command run: `{'model_validator': 5, 'property': 39, 'dataclass': 39, 'asynccontextmanager': 7, 'app.get': 6, 'classmethod': 2, 'staticmethod': 2}`: no decorator outside the allow-list; `ALLOWED_DECORATORS` was not edited, so there was nothing to arm.
* **7.5** `tests/database_parity/test_reliability_table_parity.py` (OI11) is green inside `quality.sh` (8 cases).
* `test_money_guard.py`: `"re"` added to `ALLOWED_ROOTS` and to the census sentence (47 files, was 46); `test_kernel_surface.py`: `event_envelope` and three new `__init__` names. Arms 1.3a-c (three messages above).

## 9. Closing checks

* **8.1 `./quality.sh`**: exit **0**, **153 s** elapsed, **1644 passed** in 122.4 s of pytest (a first run on the previous tree: 1642 passed, 148 s, exit 0; the two tests added since are `test_system_clock` and the payload-truncation test), overall coverage **98.44 %** (gate 60 %), domain + kernel **98 %** (gate 80 %), web gates green. Run with the developer stack down: `docker ps` shows only `otcpy-n8n` (§5.6).
* **Per-file counts** (`uv run pytest --collect-only -q`, 123 files, summing to the headline **1644** at the time; after A1 and review round 1 the real total is 1651, see the rework section): `count path` below.
* **8.2 `./init.sh`**: exit 0 (96 uncommitted changes warned, expected mid-session).
* **8.3** matrix and `requirements.md` §3: see §3; derived counts feature 2 = 8 rows / 7 green / 0 scoped / 1 not yet green, Total 63 / 16 / 1 / 46.

```
     10 packages/contracts/tests/test_contracts_dependencies.py
      5 packages/contracts/tests/test_envelope_generic.py
      4 packages/contracts/tests/test_facts_without_a_golden.py
      6 packages/contracts/tests/test_generation_drift.py
     72 packages/contracts/tests/test_golden_envelopes.py
     16 packages/contracts/tests/test_spec_alignment.py
     54 packages/contracts/tests/test_wire_serializer.py
     51 packages/contracts/tests/test_write_side_and_json_paths.py
     34 packages/cqrs/tests/test_cqrs_dispatcher.py
     16 packages/cqrs/tests/test_cqrs_mypy_strict.py
     71 packages/shared_kernel/tests/test_business_reference.py
     15 packages/shared_kernel/tests/test_currency_exponent.py
     10 packages/shared_kernel/tests/test_entity.py
     12 packages/shared_kernel/tests/test_errors.py
     25 packages/shared_kernel/tests/test_event_envelope.py
     41 packages/shared_kernel/tests/test_gln.py
     31 packages/shared_kernel/tests/test_kernel_surface.py
     67 packages/shared_kernel/tests/test_money.py
     14 packages/shared_kernel/tests/test_money_text.py
      8 packages/shared_kernel/tests/test_mypy_rejects_float.py
     26 packages/shared_kernel/tests/test_quantity.py
     23 packages/shared_kernel/tests/test_unique_id.py
      5 services/billing/tests/integration/test_billing_counter_seed.py
      2 services/billing/tests/integration/test_billing_foreign_keys_and_indexes.py
      3 services/billing/tests/integration/test_billing_json_and_timestamps.py
      2 services/billing/tests/integration/test_billing_migration_lifecycle.py
      1 services/billing/tests/integration/test_billing_models_match_migration.py
      7 services/billing/tests/integration/test_billing_quantity_range.py
     10 services/billing/tests/integration/test_billing_round_trip.py
      3 services/billing/tests/integration/test_billing_schema_types.py
      1 services/billing/tests/test_billing_health.py
      6 services/billing/tests/unit/test_billing_database_settings.py
     23 services/billing/tests/unit/test_billing_range_guards.py
      5 services/fulfillment/tests/integration/test_fulfillment_counter_seed.py
      2 services/fulfillment/tests/integration/test_fulfillment_foreign_keys_and_indexes.py
      2 services/fulfillment/tests/integration/test_fulfillment_json_and_timestamps.py
      2 services/fulfillment/tests/integration/test_fulfillment_migration_lifecycle.py
      1 services/fulfillment/tests/integration/test_fulfillment_models_match_migration.py
      6 services/fulfillment/tests/integration/test_fulfillment_quantity_range.py
      9 services/fulfillment/tests/integration/test_fulfillment_round_trip.py
      3 services/fulfillment/tests/integration/test_fulfillment_schema_types.py
      1 services/fulfillment/tests/test_fulfillment_health.py
      6 services/fulfillment/tests/unit/test_fulfillment_database_settings.py
     21 services/fulfillment/tests/unit/test_fulfillment_range_guards.py
      1 services/gateway/tests/test_gateway_health.py
      3 services/notifications/tests/integration/test_notifications_migration_lifecycle.py
      1 services/notifications/tests/integration/test_notifications_models_match_migration.py
      3 services/notifications/tests/integration/test_notifications_schema.py
      1 services/notifications/tests/test_notifications_health.py
      6 services/notifications/tests/unit/test_notifications_database_settings.py
      1 services/orders/tests/integration/test_fact_partitioning.py
      4 services/orders/tests/integration/test_fixture_matches_deployed_server.py
      5 services/orders/tests/integration/test_idempotent_consumer.py
      1 services/orders/tests/integration/test_kafka_fixture.py
      7 services/orders/tests/integration/test_order_repository.py
      5 services/orders/tests/integration/test_orders_counter_seed.py
      2 services/orders/tests/integration/test_orders_foreign_keys_and_indexes.py
      3 services/orders/tests/integration/test_orders_json_and_timestamps.py
      2 services/orders/tests/integration/test_orders_migration_lifecycle.py
      1 services/orders/tests/integration/test_orders_models_match_migration.py
      6 services/orders/tests/integration/test_orders_quantity_range.py
      2 services/orders/tests/integration/test_orders_request_id.py
      3 services/orders/tests/integration/test_orders_schema_types.py
      3 services/orders/tests/integration/test_outbox_atomicity.py
     12 services/orders/tests/integration/test_outbox_envelope.py
      5 services/orders/tests/integration/test_outbox_relay_concurrency.py
      2 services/orders/tests/integration/test_outbox_relay_deadlock.py
     10 services/orders/tests/integration/test_outbox_relay.py
      8 services/orders/tests/integration/test_outbox_wire_parity.py
      1 services/orders/tests/test_orders_health.py
      2 services/orders/tests/unit/domain/test_domain_tests_are_pure.py
     24 services/orders/tests/unit/domain/test_order_cancellation.py
      1 services/orders/tests/unit/domain/test_order_errors.py
      9 services/orders/tests/unit/domain/test_order_events.py
      4 services/orders/tests/unit/domain/test_order_instants.py
     20 services/orders/tests/unit/domain/test_order.py
     18 services/orders/tests/unit/domain/test_order_rehydration.py
      7 services/orders/tests/unit/domain/test_order_state_machine.py
     19 services/orders/tests/unit/domain/test_order_structure.py
      7 services/orders/tests/unit/domain/test_order_totals.py
     14 services/orders/tests/unit/domain/test_order_vocabulary.py
      6 services/orders/tests/unit/test_deadlock_classifier.py
     18 services/orders/tests/unit/test_idempotent_consumer_parity.py
      7 services/orders/tests/unit/test_kafka_fact_publisher.py
      6 services/orders/tests/unit/test_order_domain_contract_parity.py
      6 services/orders/tests/unit/test_orders_database_settings.py
     19 services/orders/tests/unit/test_orders_range_guards.py
      9 services/orders/tests/unit/test_outbox_payloads.py
      7 services/orders/tests/unit/test_outbox_relay_task.py
      4 services/orders/tests/unit/test_outbox_settings.py
      1 services/orders/tests/unit/test_system_clock.py
      1 services/projector/tests/test_projector_health.py
      3 services/seed/tests/integration/test_seed_cli.py
      5 services/seed/tests/integration/test_seed_databases.py
      2 services/seed/tests/integration/test_seeded_outbox_has_nothing_to_publish.py
      5 services/seed/tests/integration/test_seed_mongo.py
      2 services/seed/tests/integration/test_seed_parity_nine_half.py
     14 services/seed/tests/integration/test_seed_tables_match_migration.py
      1 services/seed/tests/integration/test_seed_write_path_behaviour.py
     11 services/seed/tests/unit/test_dataset_counts.py
      3 services/seed/tests/unit/test_dataset_parity.py
     33 services/seed/tests/unit/test_deterministic_parity.py
     15 services/seed/tests/unit/test_money_text.py
      7 services/seed/tests/unit/test_payloads_against_contracts.py
      9 services/seed/tests/unit/test_range_check.py
      6 services/seed/tests/unit/test_read_model_constants.py
     11 services/seed/tests/unit/test_run_seed_and_wiring.py
      5 services/seed/tests/unit/test_seed_instants.py
     19 services/seed/tests/unit/test_seed_parity_tooling.py
      9 services/seed/tests/unit/test_seed_settings.py
      9 services/seed/tests/unit/test_timeline_value_guard.py
     11 services/seed/tests/unit/test_write_path_population.py
     19 tests/architecture/test_cqrs_registration_explicit.py
      2 tests/architecture/test_dependency_freedom.py
      4 tests/architecture/test_import_contract_coverage.py
    304 tests/architecture/test_money_guard.py
      2 tests/architecture/test_mypy_policy.py
     12 tests/architecture/test_range_guard_parity.py
      2 tests/architecture/test_warning_policy.py
     73 tests/architecture/test_write_path_population.py
      8 tests/database_parity/test_reliability_table_parity.py
      3 tests/database_templates/test_template_isolation.py
      3 tests/seed_counters/test_seeded_counters_start_above_references.py
```


## 10. Population checks (task 8.4), one classification per line

1. `git status --porcelain --untracked-files=all` (127 paths at the end; the full list is in the leader's `git status`): every path this session created or changed is in the file list of `tasks.md` §preamble (new `src` under `application/ports`, `infrastructure/{clock,settings,messaging,outbox,persistence}`; the tests under the two `tests/` trees and the seed; kernel / contracts files; root `conftest.py`, `.env.example`, `pyproject.toml`, `services/orders/pyproject.toml`, `uv.lock`; the three architecture tests; the matrix, `requirements.md`, `tasks.md`; `feature_list.json`). The other 62 paths are not this feature's and predate this session: features 13 and 43 (`domain/**`, `packages/cqrs/**`, `services/orders/tests/unit/domain/**`, `specs/orders_aggregate/`, `money_text`, `services/seed` edits) and the leader's `progress/*` briefs, premises and reports. `progress/current.md` is the leader's (12:09, after the brief).
2. `git status --porcelain services/orders/alembic` prints nothing (no migration). The domain tree is untracked (feature 13) so git cannot show a delta there; instead `find services/orders/src/otc_orders/domain services/orders/src/otc_orders/presentation services/orders/alembic packages/cqrs -type f -newer progress/brief_impl_outbox_and_idempotency.md` printed nothing: no file under those trees was written after this brief.
3. `find services packages tests -name '*.py' -size 0`: **nothing** (every `__init__.py` this feature added carries a docstring). Sentinel: an empty `outbox/relay_copy.py` was listed by that command; removed and re-run empty.
4. `grep -rn "Order(" services/orders/src`: `persistence/models.py:112 class Order(Base)` (the ORM class) and `domain/order.py:80 class Order(AggregateRoot)` (the aggregate); no call and no `cls(`. The mapper reaches an `Order` only through `Order.rehydrate` (imports the ORM class as `OrderRow`).
5. `grep -rn "\.begin()\|40P01" services/orders/src`: `unit_of_work.py:53 session.begin()` (no retry, G2); `relay.py:155 session.begin()` (the cycle: retried on `40P01` by `run_once`, `relay.py:46` the constant); the other `relay.py` hits (lines 10, 21, 22) are docstring text. The third transaction site of `design.md` §8, `IdempotentConsumer.run_once`, opens its transaction through `self._begin()` (the unit of work's `begin`), which the pattern does not match: it inherits the unit of work's no-retry rule, so a victim there propagates and redelivery re-runs the step.
6. `grep -rn "Decimal\|float\|json\.dumps\|model_dump_json\|json\.loads" services/orders/src/otc_orders/infrastructure`: `json.loads` exactly once in code, `outbox/wire.py:32`; `json.dumps` and `model_dump_json` only inside the pre-existing `persistence/types.py` docstring; no `Decimal` (one docstring sentence in `payloads.py` says there is none); `float`: `settings.py:72-78` (the millisecond conversion, allowed), and `relay.py:129` (`publish_timeout: float`) and `relay_task.py:29` (`poll_interval: float`), which are the same seconds the settings produce, handed to `asyncio` (timing, not money; §11 divergence 5). Sentinel: a temporary `SENTINEL = json.dumps({})` line in `relay.py` appeared in this search (`relay.py:208`); removed, `cmp` identical.
7. `grep -in "select" idempotent_consumer.py`: one hit, line 12, inside the banner (`There is no \`SELECT\` anywhere in the dedup path`).


## 11. Divergences from the spec, each with its reason

1. **`ConsumerName` against `design.md` §6.4 case 2.** §6.1 defines `ConsumerName` (`ORDERS_SAGA = "orders.saga"`, `PROJECTOR`, `NOTIFICATIONS`) in the canonical file, and case 2 forbids the substrings `orders`, `projector`, `notifications` anywhere outside the banner. The spec cannot be satisfied as written. I kept §6.1 (the closed vocabulary of `specs/shared/requirements.md`, adoptable verbatim by every service, so not a service-specific reference: OI12's own purpose) and made case 2 scan the file **without the `ConsumerName` class body**, with sentinels that a service name outside the enum still fails (`test_case_2_sentinel_the_consumer_vocabulary_is_exempt_only_inside_the_enum`, `...a_service_name_or_a_foreign_import_in_the_body_is_reported`). The leader should decide whether this becomes a design amendment (the alternative is moving the enum out of the canonical file, which §6.1's layout and the copy-verbatim rule both argue against).
2. **One line outside the stated bound.** `tasks.md` bounds the root `conftest.py` to "the Kafka container fixture only". Task 2.3's own test found that the session's Postgres reports `timezone = Etc/UTC` while the deployed server (`docker-compose.infra.yml:78`) reports `UTC`. The fixture is the thing to fix, so I added the deployed command (`postgres -c timezone=UTC -c log_timezone=UTC`) to the Postgres container in the same file, with the reason beside it; armed (arm 2.3b). No other Postgres fixture line changed.
3. **`SqlAlchemyUnitOfWork(sessions=..., outbox=...)`**, not `(sessions, clock, writer)`: the clock reaches the `OutboxWriter`, which is the only user. Same behaviour.
4. **Task 4.13's "key by a constant: the precondition fails, naming it".** The precondition as specified (two orders on different partitions) is computed from the order ids and cannot see what the publisher does with the key, so a constant key failed at "one partition per order", not at the precondition. I added a second precondition read from the broker (`landed[first] != landed[second]`), which fails naming itself under the constant key (arm 4.13b); the id-based loop stays as the selection of the pair.
5. **`float` seconds in `OutboxRelay.__init__` and `OutboxRelayTask.__init__`**, outside the settings class the grep expectation allowed: the settings produce `float` seconds, the relay takes what `asyncio.timeout` and `wait_for` take. Timing, not money.
6. **Tests beyond the task list, all from §7's survivors or from a claim the task made loosely:** `test_oi1_writer_refuses_...incomplete_envelope...` is parametrised over five fields (the task named `causation_id`); `test_oi1_every_column_and_envelope_field...`; `test_oi19_every_instant_column...`; `test_every_instant_of_every_payload...`; the two repository reference-error tests; `test_a_confirmed_order_saved_for_the_first_time...`; `test_publish_sends_every_fact...`; `test_publishing_before_start...`; `test_a_batch_with_two_failed_records...`; the permanent `test_oi17_without_the_retry_...`. `test_kafka_fixture.py` is a new file for task 2.2.
7. **`OutboxRelay` captures `(event_id, correlation_id, seq)` before the transaction ends** (`_Claimed`): an ORM row is expired by the rollback, and the OI8 log lines are written after it. Not in the design; required by the rollback-first shape.
8. **`session.commit()` inside `session.begin()` is refused by SQLAlchemy** (`InvalidRequestError: Can't operate on closed transaction inside context manager`), so the #7 "M4" arm (commit the dedup insert in its own transaction ahead of `work`) is built as a genuinely second transaction (arms 6.2 / 6.3), not as an inline commit; my first draft of that mutant failed for the wrong reason and was replaced.
9. **Arm 4.8a2.** `order_by(Outbox.occurred_at)` does NOT fail the first OI2 case (`test_oi2_publishes_records_written_by_one_transaction_in_append_order...`): its three rows tie on `occurred_at`, so PostgreSQL returns them in heap order, which equals `seq`. The second OI2 case (rows whose `occurred_at` runs against `seq`) is the one that discriminates (arm 4.8a, 4.8b). Both cases stay; the first proves the append-order claim end to end, the second the ordering key.
10. **Arm 3.10a2.** The second R13 case fails under "commit on exception" with `PendingRollbackError`, not with a state assertion: the failed flush leaves the session unusable for the commit, so the test's `pytest.raises(IntegrityError)` sees a different exception. The first case is the one that shows the state (`assert (1, 2, 1) == (0, 0, 0)`). #8's reviewer's remark (the second case catches what the first may not) did not recur here: both fail.
11. **`design.md` L25's guard** (see §4): replaced by an armed, deterministic one.
12. **Rows R5–R10 and feature 1's counts in `test-matrix.md`** were already changed in the working tree before this session (feature 13's work). I added only my seven rows and recomputed the Total from the file as it stood (9 → 16 green).

## 12. Surprises

* asyncpg returns `asyncpg.pgproto.pgproto.UUID`, a `uuid.UUID` subclass, which `UniqueId.__post_init__` refuses (`type(...) is uuid.UUID`).
* aiokafka 0.14.0 on Python 3.14: `AIOKafkaConsumer.stop()` raises `CancelledError` when called before the loop has yielded once after `start()` (its `NoGroupCoordinator` task is cancelled before its first step); one loop tick in the test helper avoids it. `partitions_for_topic` returns nothing for a consumer that has not subscribed, so the helper reads partition ids from the admin client's metadata.
* The Postgres test container's `timezone` is `Etc/UTC`, not the deployed `UTC` (§11.2).
* `Envelope[P]` with PEP 695 syntax works on pydantic 2.13 as is. `model_dump_json()` of an unvalidated payload raises `pydantic_core.PydanticSerializationError`; `to_wire_json` raises `ValidationError`: both name the field.
* Kafka (KRaft, `apache/kafka:4.3.1`) is ready in about 4 s through the generic container; a session fixture is cheap.
* The constructed deadlock made the relay the victim in every run (it waited first, so its `deadlock_timeout` expired first).
* Five of the first sweep's seventeen survivors were not about a missing assertion but about a fixture that could not tell two fields apart (`aggregate_id == correlation_id`, `created_at == updated_at`); the fix was a different fixture, not a different assertion.

## 13. Inherited findings (`design.md` §13)

| Finding | Result |
|---|---|
| #8 id 87 (deadlock victim escaped) | **avoided**: reproduced, then retried inside `run_once`, armed both ways (§5.5) |
| #8 id 111 (poison row) | **avoided** (decided at G1): published clean prefix, blocked at the row, three kinds, armed (4.12a-d) |
| #8 D1 (stray empty file) | **avoided**: §10 line 3 and its sentinel |
| #8 D2, D3 (R18 negatives) | **avoided**: three discriminating effects, the order row re-read, positive control (arm 6.4) |
| #8 D4 (vacuous parity cases at n = 1) | **avoided**: temporary-tree sentinels for cases 1, 3, 4 (arms 6.8b-d) |
| #8 D5 (`current.md` out of lockstep) | **avoided**: not touched |
| #8 D6 (package installed, named nowhere) | **avoided**: §14 |
| #8 D7 (name pattern in a matrix cell) | **avoided**: literal names, each grepped |
| #8 D8 (fixture changes without assertions) | **avoided**, and it paid: the assertion found `Etc/UTC` |
| #8 history 1, 2, 3 (skip/block, `seq`, inline claim) | **avoided**: §5.4, §5.3, both relays production |
| #8 id 104 (a developer Kafka hid a dependency) | **avoided**: stack down for the run, bootstrap-at-9092 arm fails |
| #7 D1 (orphan migration snapshot) | not applicable: `alembic/` untouched |
| #7 D2 (dead publish timeout) | **avoided**: arm 4.11a |
| #7 D3 (unused Kafka test package) | **avoided**: no test package added |
| #7 D4 (manual step used local time) | **avoided**: §15 uses `now()` on a `timestamptz` |
| #7 D5 (`findByReference` untested) | **avoided**: arm 3.8b |
| #7 D6 (stale matrix Total) | **avoided** |
| #7 D7 (failure committed an empty transaction) | **avoided**: arm 4.11b |
| #7 D8 (`seq` typed nullable) | already avoided by feature 9 |
| #7 D9 (OI9 demonstrated, not guarded) | **avoided**: same-instance retry, arm 3.11 |
| #7 D10 (R17 case survived the mutation) | **avoided**: arms 6.2 and 6.3 both fail |

Recurred: none of the inherited findings. New findings of this feature are in §11 and §12.

## 14. Packages installed

`aiokafka==0.14.0` (`services/orders/pyproject.toml`, `uv.lock`), with its transitive `async-timeout==5.0.1`. No test package (the Kafka container is `testcontainers`' generic `DockerContainer`; `testcontainers.community.kafka.KafkaContainer` cannot drive `apache/kafka`: its start script runs `/etc/confluent/docker/configure` and `/launch`, testcontainers 4.15.0 `community/kafka/__init__.py:163-184`, task 2.4). npm: none.

## 15. Manual verification for the human

1. `docker compose -p otcpy -f docker-compose.infra.yml up -d` (Postgres, Kafka, Redpanda Console).
2. Point a Python shell at the developer database (`ORDERS_DATABASE_URL`, `KAFKA_BROKERS=localhost:9092`), build `OutboxRelay(sessions=..., publisher=<a started KafkaFactPublisher>, clock=SystemClock(), batch_size=100, publish_timeout=5)` and call `await relay.run_once()` (the lifespan wiring is feature 15's, so no service starts it yet).
3. Insert one unpublished row by hand with `occurred_at = now()` (a `timestamptz`; never `localtimestamp` and never a `timestamp` cast), e.g. `INSERT INTO outbox (id, event_id, event_type, aggregate_id, correlation_id, causation_id, payload, occurred_at, published_at, created_at, trace_parent) VALUES (gen_random_uuid(), gen_random_uuid(), 'order.placed.v1', gen_random_uuid(), <same as aggregate>, gen_random_uuid(), '<a valid payload>'::json, now(), NULL, now(), NULL);`.
4. Watch it appear in Redpanda Console on `otc.orders.facts.v1`, keyed by the order id, with headers `x-event-type` and `content-type: application/json` and **no** `traceparent`, and `published_at` stamped.

## 16. What I could not do, and why

* The relay is not started by any service: no `composition.py` or lifespan exists yet (feature 15's acceptance item, already on its list). The relay task is proven by driving it directly.
* No consumer shell, no `R16` (retry, backoff, `.dlq`), no metrics, no `traceparent`: other features.
* `./quality.sh` ran twice (once before the last test additions, once after): the final figures are the second run's.

## Amendment A1 (ConsumerName moved out of the canonical)

Resolves section 11 item 1. Files: new `services/orders/src/otc_orders/infrastructure/messaging/consumer_name.py` (unchanged enum); canonical `idempotent_consumer.py` now has exactly `from .consumer_name import ConsumerName` and no enum; importer updated: `services/orders/tests/integration/test_idempotent_consumer.py` (no re-export kept, nothing else imports it); `services/orders/tests/unit/test_idempotent_consumer_parity.py` case 2 rewritten (no excluded region, whole body scanned, exactly one allowed relative import, docstring updated, new sentinels: enum back, other/second relative import, missing import); `specs/outbox_and_idempotency/tasks.md` 6.1 marked "(amended A1)".

Arms (backup, mutate, run `test_case_2_the_canonical_is_adoptable_verbatim_naming_no_service`, restore, `cmp` clean, `__pycache__` cleared):
- (a) `ConsumerName` class appended to canonical: `Left contains one more item: "names 'orders' outside the banner"`
- (b) `from .other import X` appended: `AssertionError: assert ['relative im...me), found 2'] == []` / `'relative import .other is not allowed'`
- (c) comment `# projector` after banner: `Left contains one more item: "names 'projector' outside the banner"`

Counts: parity file 17 passed; cases 1/3/4 (7 tests) pass; `services/orders/tests/unit` 205 passed; mypy clean (292 files); ruff clean; lint-imports 11 kept, 0 broken. Integration test edit not run (needs containers, not started).

## Review round 1 rework (F1-F4, test-side only; no `services/*/src` or `packages/*/src` file changed)

Total now **1651** (`uv run pytest --collect-only -q`): 1648 after A1, plus 2 relay-task tests and 1 parity sentinel. Per-file: `test_outbox_relay_task.py` 5 -> 7, `test_idempotent_consumer_parity.py` 17 -> 18 (the 13 in the §9 list predates A1's four sentinels; the review reconciled 17), `test_deadlock_classifier.py` unchanged (an existing case gained assertions). `requirements.md` §3 OI6 row gained both new names; OI17's row already lists F3's case.

| Finding | Test | Requirement | Arm (backup, one mutation, one named test, restore, `cmp`, caches cleared) | Failure, verbatim |
|---|---|---|---|---|
| F1 | `test_relay_task_propagates_a_cancellation_that_arrives_during_the_inter_cycle_sleep` | OI6, L8 | `suppress(TimeoutError, asyncio.CancelledError)` at `relay_task.py:42` | `AssertionError: the cancellation was swallowed during the sleep: the loop polls on` |
| F2a | `test_relay_task_waits_the_poll_interval_between_cycles_and_stop_cuts_the_wait_short` | OI6, L18 | `wait_for(...)` replaced by `asyncio.sleep(0)` | `AssertionError: a second cycle ran inside the poll interval: no pacing` (`assert 36502 == 1`) |
| F2b | same | OI6, L18 | `asyncio.sleep(self._poll_interval)` (not interruptible) | `AssertionError: stop did not end the wait: the sleep is not interruptible` |
| F3a | `test_run_once_retries_a_deadlock_victim_up_to_the_bound_then_lets_it_escape` | OI17, L17 | `await asyncio.sleep(DEADLOCK_BACKOFF_SECONDS)` at `relay.py:150` replaced by `pass` | `assert [] == [0.2, 0.2]` |
| F3b | same | OI17, L17 | `DEADLOCK_BACKOFF_SECONDS = 0` | `assert [0, 0] == [0.2, 0.2]` |
| F4 | `test_case_2_sentinel_a_dynamic_import_in_the_body_is_reported` | OI12 | the new `import_module`/`__import__` reference check disabled (`if False:`); the `importlib` import check stays | `AssertionError: ["imports 'importlib': a dynamic import hides its module"]` (the `import_module` reference assertion fails) |

All six restored (`cmp` silent), `__pycache__` and `.mypy_cache` cleared, and the real canonical still passes case 2. F3 asserts the literals `[0.2, 0.2]` (exhausted case) and `[0.2]` (survivor), not the constant. F4 follows the money guard's precedent (`__import__` / `import_module` references, plus any `importlib` import).

## Review round 2 light pass

Test-only, no `src` change. Added `test_a_send_that_raises_stops_the_batch_and_names_that_fact_and_every_later_one` (OI8 at the adapter) to `services/orders/tests/unit/test_kafka_fact_publisher.py`, with a `RaisingSendProducer` fake (send 2 raises `RuntimeError("buffer full")`). Four assertions: `FactPublicationError` raised; `event_ids == (UUID(int=2), UUID(int=3))`; sent keys `[key-1, key-2]`; "send failed" in the message. Paperwork: `requirements.md` §3 OI8 row, `design.md` file table row.

Line numbers: arm (a) `break` is at kafka_publisher.py:79 as the review said; arm (b) `facts[index:]` is at :77, not :78.

* Arm (a), `break` -> `continue`: `AssertionError: fact 3 was never sent` / `assert [b'key-1', b'key-2', b'key-3'] == [b'key-1', b'key-2']` / `Left contains one more item: b'key-3'`; 1 failed.
* Arm (b), `facts[index:]` -> `facts[index + 1 :]`: `AssertionError: fact 2 and every later` / `assert (UUID('000000...0000000003'),) == (UUID('000000...00000000003'))` / `At index 0 diff: ...0003 != ...0002`; 1 failed.
* Both restored from backup, `cmp` identical, caches cleared, test green again.

Counts: `test_kafka_fact_publisher.py` 7 -> 8; total 1651 -> 1652 (`uv run pytest --collect-only -q`). `services/orders/tests/unit`: 209 passed; mypy clean; ruff check and format clean.
