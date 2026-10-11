# Implementation report — feature 24 `projector_read_model` (phase 12)

> Written incrementally; if this file stops mid-way, the last section is where the run was.

## A. Preconditions and scaffold

### A1 — design §1/§2 checked against the repository as committed (HEAD, working tree as given)

| Item | Result |
|---|---|
| Skeleton's five files | present: `services/projector/pyproject.toml`, `src/otc_projector/presentation/app.py`, `tests/test_projector_health.py`, `src/otc_projector/{domain,application,infrastructure,presentation}/__init__.py`, `domain/value_objects/__init__.py`, `py.typed` (find output at A1 time). No `composition.py`, no `main.py`. |
| import-linter contracts naming `otc_projector` | `pyproject.toml:182` (root_packages), `:197` (`domain-purity`), `:262-263` (`fact-producer-confinement`), `:326-332` (`layers-projector`), `:356` (independence) |
| `test_money_guard.py:56` | `SERVICES = [..., "projector", "seed"]` at line 56 |
| Notifications `composition.py:75-76` | `CONSUMER_STARTUP_SECONDS = 60.0`, `STOP_GRACE_SECONDS = 30.0` |
| Notifications `composition.py:179-216, 241-306` | `unready_reasons` at 179-190 (the `_stopping`/task-done/subscriber-ready reasons), `_await_consumer_ready` and `start_runtime` at 241+ |
| `kafka_fact_subscriber.py:7-13, 120-127, 173` | offset-contract docstring bullets; `consumer_options()` (earliest swap site); `value=record.value if ... else b""` (tombstone) |
| `notification_facts_consumer.py:50-68` | `handle` |
| Orders `kafka_fact_subscriber.py:114-117` | `group_id=ConsumerName.ORDERS_SAGA.value`, `client_id`, `enable_auto_commit=False`, `auto_offset_reset="earliest"` |
| Seed `timeline.py:27-103` | `ORDER_TIMELINE_COLLECTION`... `to_timeline_document` |
| Seed `mongo.py:39-50` | `create_index` (partial filter) and `$setOnInsert` upsert |
| Seed `settings.py:47-54, 98-109` | mongo field set; `mongo_connection_uri` through SQLAlchemy `URL.create` |
| `facts.py:30-78` | `FactEvent` union (30-45), `FACT_MODELS` (47-62), `parse_fact` (71-78) |
| `wire.py:47, 175` | `format_instant`, `to_wire_json` |
| `test_idempotent_consumer_parity.py:50-66, 120-150` | `has_relational_ledger`/`consumer_file`/`copies` (50-66); case 3 (120-134) and case 4 (137-150) |

Absence claims (full output):

```
$ grep -rn "AIOKafkaConsumer" services/projector
(no output; exit 1)
$ grep -n 'name = "motor"' uv.lock
(no output; exit 1)
$ grep -rn '\$literal' ../order-to-cash-nestjs/apps/projector/src ../order-to-cash-dotnet/src/Projector --include=*.ts --include=*.cs
(no output; exit 1)   # zero code hits, zero comment hits
```

No false item.

### A2 — baseline

`./quality.sh` with the developer stack down (only `otcpy-n8n` running, unrelated): **exit 0, 428 s, 3782 passed**, overall coverage 97.56 %, domain coverage 98 % (the 6b step). Every later count is a delta from these figures.

### A3 — leader-owned

Requested of the leader and done before this run: `grep -n -i projector .env.example` shows the block at lines 188-195, `PROJECTOR_KAFKA_CLIENT_ID=otc-projector` and `PROJECTOR_CONSUMER_GROUP=projector`. Not edited by the implementer. H3's settings test passes with or without it (defaults).

## 0. What was built, and the files touched

The `projector` service: a Kafka consumer of all fourteen facts that maintains the `order_timeline` read model in MongoDB, publishes the two `readmodel.*` NATS signals, and serves `/health/live` and `/health/ready` and nothing else.

**Production code, `services/projector/src/otc_projector/` (38 files, 2,287 lines)**

| Layer | Files |
|---|---|
| `domain/` (stdlib and `otc_shared_kernel` only) | `projection_delta.py`, `status_rank.py`, `timeline_order.py` (the reference implementation of `PR10`/`PR31`, the differential oracle) |
| `application/` | `messages.py` (the one command), `handlers.py` (`PR18`/`PR19`), `projection.py` (fourteen `match` arms + `assert_never`), `summaries.py`, `outcome.py`, `scope.py`, `ports/{fact_stream,read_model,update_signal}.py` |
| `infrastructure/` | `settings.py`; `messaging/{consumer_name (byte-identical copy), fact_topics, kafka_fact_subscriber, idempotent_consumer (the variant)}.py`; `persistence/{read_model_document, delta_to_pipeline, timeline_order, mongo_read_model_writer, read_model_indexes, timeline_order_migration}.py`; `signal/nats_update_signal_publisher.py` |
| `presentation/` | `app.py` (the two health routes), `projector_facts_consumer.py` |
| beside the layers | `composition.py` (settings, registration, `Externals`, the boot order, the runtime), `main.py` (the lifespan) |

**Tests, `services/projector/tests/` : 26 unit files (124 test functions), 14 integration files (54), `conftest.py` (the fact builders, one per fact), `integration/conftest.py` (the Docker-held servers, the command listener, the runtime launcher, the NATS barrier), `test_projector_health.py` (4).**

**Edits outside `services/projector/`, all within `tasks.md`'s file list**

| File | Edit |
|---|---|
| `services/projector/pyproject.toml`, `uv.lock` | four existing packages added as dependencies (`uv lock`; 83 packages before and after) |
| `services/orders/tests/unit/test_idempotent_consumer_parity.py` | design 6.5: the declared registry (`PR48`), cases 1/3 selected by mode, case 4 rewritten, sentinels P1 – P6 |
| `tests/architecture/test_registration_behaviour.py`, `test_composition_env_reads.py`, `test_kafka_client_confinement.py`, `test_kafka_client_ids.py` | design 12's edits only (plus a census test and its sentinel in the first) |
| `services/seed/README.md` | the one sentence of O3 |
| `specs/shared/test-matrix.md` | column 5 of `R50` – `R55` and the derived counts (46 / 1 / 16) |
| `specs/projector_read_model/requirements.md` §3, `tasks.md` | Status cells; boxes |
| `feature_list.json` | id 24's `status` line, one line |

Not touched (checked by command, O6): `services/orders/src`, `services/seed/src`, `services/{fulfillment,billing,notifications,gateway}`, `packages/`, `tests/fixtures/`, `.env.example`, root `pyproject.toml`, `docker-compose*.yml`, `infra/`, `progress/current.md`. The working-tree changes that are the leader's and were there when this run started (`SA-6` on `openapi.yaml` and the two generated headers, `README.md`, `CLAUDE.md`, `AGENTS.md`, `progress/history.md`, `.env.example`, id 214 in `feature_list.json`) are untouched.


## 1. Acceptance items 1 – 8 of `feature_list.json` id 24, each mapped to evidence

| # | Item | Evidence (tests are under `services/projector/tests/` unless a path says otherwise) |
|---|---|---|
| 1 | timeline ordered by the recorded causal edge, not by clock | `integration/test_timeline_causal_order.py` › `test_r28_stock_released_precedes_the_order_cancelled_that_names_it_with_adversarial_event_ids`, `test_r24_the_completion_triple_is_stored_in_causal_order_with_adversarial_event_ids` (`eventId`s chosen so the fallback alone inverts, delivered in the inverting order; arm S6 — remove `__depth` from `sortBy` — fails **both**, section 10, J4-*); `test_pr10_the_pipeline_agrees_with_the_reference_rule_on_generated_entry_sets` (250 generated sets, seed 20261011, ties/chains/cycles/self-edges/foreign causes/missing edges, the server against `domain/timeline_order.py`); `test_pr31_a_cycle_a_foreign_cause_and_a_missing_causation_id_all_terminate_with_every_entry_once`; `unit/test_timeline_order_reference.py`; live: ORD-000013's `payment.received` → `credit.released` → `order.completed` tie group stored in that order (section 9, N3) |
| 2 | out-of-order delivery yields the correct final status; replaying a topic reproduces an identical document | `integration/test_out_of_order_facts.py` › `test_r52_appends_the_timeline_entry_without_regressing_the_document_status_or_overwriting_newer_references`, `test_pr12_a_status_less_fact_on_an_absent_order_keeps_the_placeholder_status`; replay THROUGH KAFKA: `integration/test_replay_determinism.py` › `test_pr15_replaying_the_topics_into_a_new_group_reproduces_byte_identical_documents` (two orders, every fact twice, shuffled across the three real topics; group `g1` into database A, `g2` into B, raw BSON equal; `g3` into A again: every outcome `DUPLICATE`, bytes unchanged, zero NATS frames), `test_pr15_shuffled_and_duplicated_application_yields_byte_identical_documents` (all 720 permutations, each followed by a full second pass); live: section 9 (N2, N4) |
| 3 | indexes created at boot and checked against the server's stored specification | `integration/test_read_model_indexes.py` (5 cases: idempotent creation, the server-raised code read from the exception — **86**, `IndexKeySpecsConflict`, measured — in the message, the seed's index then the projector's and the reverse, a differently-named unique index fails the boot, two placeholders coexist); `unit/test_composition.py::test_pr43_start_runtime_runs_its_steps_in_order` (index ensure and verify before the migration, the NATS connect and the consumer); arms H1 |
| 4 | emits the update signal the Gateway turns into SSE, connected inside bootstrap | `integration/test_update_signal.py` (4 cases: exactly one pair per applied fact on a per-order channel, a single-order and a whole-stream subscriber both receive, none for a redelivery, proven with a barrier; the contract's required fields read from `openapi.yaml`; `causationId`; the post-apply status and references); `integration/test_projector_lifespan.py::test_pr45_an_unreachable_nats_fails_the_boot_within_the_bound` (a Docker-held port with nothing behind it, 2 s bound, the failure within 5 s, `NATS_URL` named, no task left behind); live: 106 frames for 53 applied facts (section 9) |
| 5 | SA-2: the operator note reaches the cancellation entry on every compensation branch | `unit/test_projection.py::test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one` (six branches of design 4.2, including `"Cliente pidió anulación"`, `"$status refund"` and `" spaced "`; no `note` key where the fact has none); `integration/test_timeline_projection.py::test_pr46_a_noted_operator_cancellation_stores_the_note_verbatim`; `integration/test_projection_write.py::test_pr47_dollar_prefixed_note_and_last_error_are_stored_verbatim` and `test_pr47_a_dollar_status_note_is_stored_as_text_not_evaluated_as_the_documents_status` (the server evaluated an unwrapped `"$status"` as the document's own status; arm E8 records it) |
| 6 | the projector's version, rank table, `projector:` prefix and `uq_order_reference` equal the shared fixture | `unit/test_read_model_constants.py::test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture` reads the fixture and the projector's OWN constants (nothing re-typed); armed by bumping the projector's `TIMELINE_ORDER_VERSION` to 3 ALONE (fails, the seed's own test stays green), by swapping `completed`/`cancelled`, and by changing the partial filter |
| 7 | backlog 201: the gate decides with evidence | Ruling (b), recorded at the end of `progress/spec_projector_read_model.md`; O3 replaced `services/seed/README.md:21`'s last sentence with the ruling; no projector code depends on it (`PR30` stores `causationId` verbatim). `SA-6` itself is the leader's |
| 8 | the first handlers registered explicitly, validated in the lifespan; the behavioural registration guard | `unit/test_composition.py::test_pr27_zero_handlers_fail_the_boot`, `test_pr27_two_handlers_fail_the_boot` (a `DispatcherValidationError` from `start_runtime` BEFORE any fake connection is opened: the call log is `[]`); `tests/architecture/test_registration_behaviour.py::test_a_service_registers_only_from_its_composition_root_and_its_tables_match[projector]` plus the census `test_the_services_list_is_exactly_the_composition_roots_that_define_a_dispatcher`; armed with F-g + F-j as one fixture (a self-registering handler base drained by a helper loop in the root: "2 registrations share one statement") |


## 2. `tasks.md`, task by task

Every box is ticked in `specs/projector_read_model/tasks.md`; the reworded ones carry the argument on the box and are listed in section 4. "Arm" ids are the labels of section 10 (the arm ledger: mutation, sha256 before and after, verbatim failure, restore by `cmp`, forced cache clean, green re-run).

| Task | Delivered | Evidence |
|---|---|---|
| A1 | preconditions checked | section "A. Preconditions" above |
| A2 | baseline | 428 s, 3782 passed |
| A3 | leader-owned | verified by `grep`, not edited |
| A4 | the four dependencies, no new package | `unit/test_projector_dependencies.py`; `grep -c '^name = ' uv.lock` 83 before, 83 after; `git diff --stat uv.lock` 8 insertions; arms A4-motor, A4-sqlalchemy |
| A5 – A7 | settings, topics, the consumer-name copy | `unit/test_projector_settings_env.py` (27), `test_fact_topics.py`, `test_consumer_name_copy.py`; arms A5-*, A6-sibling-topic, A7-projectors |
| B1 – B4 | the domain | `test_read_model_constants.py` (PR40), `test_timeline_order_reference.py`, `test_domain_is_pure.py`; arms B2-*, B3-*, B4-contracts-import (+ import-linter's own failure naming `pydantic`, B4-lint-imports) |
| C1 – C8 | the application | `test_no_any_in_ports.py`, `test_summaries.py`, `test_projection.py`, `test_projection_exhaustiveness_mypy.py`, `test_project_fact_handler.py`; arms C1 – C8 (C3 also under `mypy` over `src`: `Argument 1 to "assert_never" has incompatible type "OrderSagaFailedEvent"; expected "Never"`) |
| D1 – D4 | the persistence primitives | `test_placeholder.py`, `test_delta_to_pipeline.py`, `test_timeline_order_expression.py`, `test_document_rendering.py`; arms D2-*, D3-*, D4-* |
| E1 – E8 | the variant and the writer | `test_mongo_read_model_writer.py` (9), `integration/test_projection_write.py`, `test_idempotent_consumer_conformance.py` (7), `test_projection_concurrency.py`; arms E2-*, E3, E4-*, E5, E6 (**survives**, section 4 finding 1), E7-*, E8-* |
| F1 – F3 | the Orders parity guard | `services/orders/tests/unit/test_idempotent_consumer_parity.py`: 27 cases; the diff is `.arm/p24/fragments/F1-diff.txt`; arms F2-P1 – P6, F3 |
| G1 – G5 | the update signal | `integration/test_update_signal.py` (4), `unit/test_update_signal_payloads.py` (5); arms G2-S1, G2-S2, G3-*, G4 (+ asymmetry), G5-* |
| H1 – H7 | indexes, migration, composition, lifespan, health | `integration/test_read_model_indexes.py` (5), `test_timeline_order_migration.py` (3), `unit/test_composition.py` (12), `integration/test_projector_lifespan.py` (5), `tests/test_projector_health.py` (4); arms H1-*, H2-*, H3-*, H4-*, H5-*, H6-* (one survives by prediction), H7 |
| I1 – I4 | the consumer | `test_fact_builders.py`, `test_kafka_fact_subscriber_options.py`, `test_projector_facts_consumer.py` (23), `integration/test_offset_contract.py`; arms I1-*, I2, I3-*, I4-* |
| J1 – J7 | end to end | `test_timeline_projection.py` (4), `test_out_of_order_facts.py` (5), `test_placeholder_document.py` (3), `test_timeline_causal_order.py` (6), `test_replay_determinism.py` (2), `test_seeded_oracle_parity.py` (8); arms J1 – J7 (J5-drop-min-cap and J6-no-sortarray **survive**, section 4 findings 2 and 3) |
| K1 – K7 | structural and shared guards | `test_read_model_sole_writer.py`, `test_projector_consumes_only.py`, `test_no_sync_driver.py`, `test_no_process_state.py`, and the four architecture files; arms K1 – K7 |
| K8 | `./quality.sh` | section 8 |
| L1 – L3 | emissions and suppressions armed | section 6 |
| M1 – M3 | the sweep | section 7 |
| N1 – N4 | the live walkthrough | section 9 |
| O1 – O7 | close-out | sections 8 and 11 |


## 3. The ported-idiom ledger (design 10): each guard, and the arm that saw it fail

A row says the guard is the named test and the arm is the section 10 label that was seen to fail under the mutation. "same mechanism" rows have nothing hand-built.

| Row | Guard (test) | Arm |
|---|---|---|
| L1, L4, L8, L15, L16, L17 | the server / dismissed (`—`); L4's command stream is `test_pr6_applies_one_fact_in_exactly_one_update_and_one_find_and_modify_issuing_no_read` | E3 |
| L2 | `test_pr7_concurrent_deliveries_of_one_event_id_from_separate_clients_apply_exactly_once` (8 separate `AsyncMongoClient`s, 6 rounds, exactly one `PROCESSED`) | E4-instance-set (case 3), E4-bare-event-id |
| L3 | `test_mongo_read_model_writer.py` (`test_pr7_*`: once, Phase 1 only, `_id` only) and `test_pr7_concurrent_first_facts_for_an_absent_order_end_in_one_document_holding_both` | E2-retry-twice, E2-retry-phase-2; E6 (**survives**, finding 1) |
| L5 | `test_pr10_the_events_stage_sorts_by_occurred_at_depth_event_id_and_discards_the_depth` | D3-reorder-sortby, D3-remove-unsetfield |
| L6 | `test_pr15_shuffled_and_duplicated_application_yields_byte_identical_documents` | J6-no-sortarray (**survives**, finding 3), J6-clock-updated-at |
| L7 | `test_pr6_every_array_and_rank_operand_is_if_null_guarded` | D2-ifnull-rank, D2-ifnull-events, D2-ifnull-keys (and D2-drop-ifnull-invoice for the reference operand) |
| L9 | `test_pr8_two_placeholders_with_null_order_reference_coexist` (against the real partial index) | H1-nonpartial |
| L10 | `test_pr22_a_plain_unique_index_of_the_same_name_fails_the_boot_naming_the_index_and_the_raised_code` (code read from the exception: measured 86) | H1-hardcode-code-85 |
| L11 | `test_pr39_the_seeds_index_then_the_projectors_and_the_reverse_raise_nothing` (BOTH orders) | H1-nonpartial, B2-partial-filter |
| L12 | `test_pr41_element_names_order_and_bson_types_equal_the_seeds_document` (cases 0 and 5), `test_pr44_*` | E7-omit-cancellation-reason (the sequence check fails, the value checks stay green: recorded), E7-causation-first, J7-* |
| L13 | `test_pr8_the_placeholder_holds_every_key_with_nested_objects_of_null_leaves`, `test_pr9_master_data_names_stay_null_in_a_projected_document` | J3-retailer-none (`retailer lost keys: ['code', 'gln']`) |
| L14 | `test_pr47_every_fact_value_in_the_pipeline_is_literal_wrapped` + `test_pr47_dollar_prefixed_note_and_last_error_are_stored_verbatim` | D2-unwrap-entry, D2-unwrap-updated-at, E8-unwrap-entry (`FailedToParse`, code 9), E8-unwrap-entry-substitution (`'placed'`) |
| L18 | `test_pr14_updated_at_is_the_greatest_occurred_at_not_the_latest_arrival` | J1-updated-at-incoming |
| L19 | `test_the_projector_declares_pymongo_and_no_motor_sqlalchemy_asyncpg_or_alembic`; `grep 'name = "motor"' uv.lock`: none | A4-motor, A4-sqlalchemy |
| L20, L33 | `test_pr41_*`, `test_pr44_*` | E7-*, J7-* |
| L21, L22, L32 | `test_pr41_ids_are_lowercase_hyphenated_strings_instants_are_mmmz_strings_and_integers_keep_their_python_value`, `test_pr41_a_native_uuid_would_be_refused_by_the_driver`, `test_pr41_detail_from_compensation_steps_carries_camel_case_keys_and_mmmz_instants` | D4-uuid-id, D4-isoformat, D4-snake-case-detail |
| L23 | `test_pr41_a_total_past_2_to_the_31_is_int64_and_a_small_one_is_int32`, `test_pr44_*` (types compared) | J7-int64 |
| L24 | `test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references`; `test_pr26_*` | G4-return-document-default (+ G4-asymmetry) |
| L25 | `test_pr6_pr42_the_arguments_the_driver_received_are_upsert_true_and_return_document_after` | E2-drop-upsert |
| L26 | `test_mongo_read_model_writer.py` (`DuplicateKeyError` on `_id` only) | E2-retry-phase-2, E2-retry-twice |
| L27 | `CommandLog` over `pymongo.monitoring.CommandListener` | E3 |
| L28 | separate clients in `test_projection_concurrency.py` | — (the shape of the test) |
| L29, L49 | `test_the_runtime_starts_and_stops_in_two_successive_event_loops`; `unit/test_no_process_state.py` | K7-module-set |
| L30 | `unit/test_no_any_in_ports.py` | C1-any-in-port |
| L31 | `test_a_password_and_user_with_reserved_characters_round_trip_through_the_uri` | A5-drop-quote_plus |
| L34 | `test_pr44_*` (sorted keys equal the seed's `sorted()`) | J7-* |
| L35, L37 | `unit/test_kafka_fact_subscriber_options.py` (both the dict and the factory's kwargs); `test_pr5_a_fact_produced_before_the_group_ever_subscribed_is_projected` | I2-latest-at-the-site, I4-latest |
| L36 | `test_pr38_a_raising_handler_leaves_the_committed_offset_unchanged_read_from_the_broker` (admin client, private topic of three partitions) | I4-commit-before-handler |
| L38 | `tests/architecture/test_kafka_client_ids.py` (five distinct) | K4-client-id |
| L39 | `test_pr15_replaying_the_topics_*` (shuffled across the three real topics) | J6 (replay) |
| L40 | `unit/test_no_sync_driver.py` | K6-sync-client |
| L41 | `test_pr3_a_malformed_envelope_is_logged_and_committed_with_no_dispatch` (six shapes, a tombstone included) | I3-* |
| L42, L43 | `test_pr50_readiness_drops_when_the_consumer_task_dies`, `test_pr50_shutdown_cancels_a_stuck_handler_after_the_grace` (both bounded by `asyncio.timeout`) | H6-drop-done-reason, H6-no-cancel |
| L44 | `test_pr1_one_kafka_consumer_task_over_the_three_fact_topics_and_no_nats_subscription_of_any_kind` | K2-nats-subscribe |
| L45 | `test_pr45_an_unreachable_nats_fails_the_boot_within_the_bound` | H6-no-connect-bound |
| L46 | `test_pr17_two_publishes_carry_distinct_headers_each_with_the_order_id` | G5-shared-headers |
| L47 | `test_r55_*` (single-order and whole-stream subscribers) | G2-S1, G2-S2 |
| L48 | `test_pr19_a_publication_failure_is_logged_and_swallowed` | C8-reraise (S3) |
| L50 | `test_pr17_both_payloads_carry_openapis_required_fields_read_from_the_contract` (a non-ASCII `retailerCode` in the summary arrives raw) | G3-drop-occurred-at |
| L51 | `test_pr2_*` (both directions) and `test_pr2_mypy_rejects_a_projection_match_that_omits_a_fact` | C3-delete-saga-failed-arm (+ `mypy` over `src`), C3-extra-arm |
| L52 | `test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set` | C7-set-literal, C7-triple-quoted, C7-type-checking |
| L53 | `test_pr4_an_unregistered_event_type_is_logged_and_committed_never_silently` (`order.shipped.v1`, `order.placed.v2`); an upper-case type is refused by the envelope pattern in the `PR3` case | I3-bare-return |
| L54, L64 | `tests/architecture/test_money_guard.py` (non-vacuous for the projector) and `test_pr16_money_is_formatted_*` | K5 (c), C2-money-str |
| L55 | `test_pr43_start_runtime_runs_its_steps_in_order` | H4-migration-after-consumer |
| L56 | `test_pr27_zero_handlers_fail_the_boot`, `test_pr27_two_handlers_fail_the_boot` | H5-zero, H5-two |
| L57 | `test_registration_behaviour.py[projector]` | K3-pipeline, K3-census |
| L58 | `test_domain_is_pure.py` and import-linter `domain-purity` | B4-contracts-import, K5 (a) |
| L59 | `test_kafka_client_confinement.py` | K4-consumer-import |
| L60 | `test_read_model_sole_writer.py` | K1-plant-update-one, K1-drop-seed-from-allow-list |
| L61 | `test_pr44_*` against the real seed writer | J7-* |
| L62 | `test_pr40_*` | B2-version-bump |
| L63 | `test_composition_env_reads.py` and `test_each_setting_reaches_the_adapter_it_configures` | K4-environ, H3-* |
| L65 | `test_pr44_*`, `test_pr41_*` | J7-*, D4-isoformat |

Both halves of each row (the "#7 relied on X / #8 supplied Y" file:line citations) are design 10's own and were checked at A1; nothing in them was found wrong. The two rows whose guards turned out unable to fail, L3 and L6, are findings 1 and 3.


## 4. Reworded boxes, and findings with dispositions

### 4.1 Boxes reworded (the argument is also written on the box in `tasks.md`)

| Box | Original wording | What was delivered, and why the wording could not stand |
|---|---|---|
| D3 | "the apply and the migration … neither contains `"$sortArray"` itself" | The apply legitimately holds ONE `$sortArray` of its own (the dedup keys, `PR15`). The test asserts what the claim is about: neither module carries `__depth`, `DEPTH_FIELD`, `$reduce` or a sort by `occurredAt`, the migration contains no `$sortArray` at all, and the apply contains exactly one (the keys) |
| E4 | `test_pr25_case_2_…` | The case is `test_pr25_case_2_the_same_event_and_consumer_again_is_a_duplicate_and_work_does_not_run` (shortened to stay under the line limit); the cases 1 – 5 and `PR26` exist as worded |
| E6 | "Arm: delete the Phase-1 retry (the second case fails — record the escaping error)" | **The arm cannot fail.** On `mongo:8.3.8` an `update_one({_id}, …, upsert=True)` that loses the race is retried by the SERVER: 4,800 racing upserts (32 clients x 150 rounds, probe `.arm/p24/stress_upsert.py`) raised 0 `DuplicateKeyError`. The retry stays (it is `PR7`'s conditional clause and costs nothing); it is guarded by E2's fake-collection arms, which DO fail (E2-retry-twice, E2-retry-phase-2); E6's arm is recorded as a survivor (finding 1) |
| E7 | "`2**31` in a total is Int64 while `9245` is Int32" inside `test_pr41_element_names_order_and_bson_types_equal_the_seeds_document` | Split into its own case, `test_pr41_a_total_past_2_to_the_31_is_int64_and_a_small_one_is_int32`; the sequence case is parametrised over sagas 0 (completed) and 5 (cancelled). `detail` is excluded from the entry sequence exactly as `PR44` excludes it (the seed's `stock.released.v1` entry has no `detail` at all, `PR16` gives one) |
| G3 | "a non-ASCII `note` arrives raw" | Neither signal payload carries a `note` (`OrderStreamUpdate`/`TimelineStreamEntry` have no such field). The raw-UTF-8 property is proven on the one free text the signal does carry: `summary`, which embeds `retailerCode` (`"Café-Zürich"`); the unit test `test_pr17_non_ascii_text_is_written_raw_and_the_json_is_compact` proves it without a broker |
| G4 | "**only** this case may fail while every count-based case stays green" | Every count-based case (R55, PR17, PR33, E3, the concurrency cases, conformance cases 1 – 5) stays green, as worded. Two cases fail: `PR42` (the signal level) and `test_pr26_the_post_apply_callback_runs_once_on_processed_and_never_on_duplicate` (the variant level: it asserts the callback receives the POST-apply document). Recorded verbatim in the arm ledger (G4-asymmetry) |
| G5 | "reuse one module-level headers dict" | The arm shares ONE dict between the two publishes inside the call (a module-level dict would be flagged by K7 before any test ran); the mutation's effect on the claim is the same |
| H5 | "Arms: comment out the registration (zero); register the handler twice (two)" | `test_pr27_zero_handlers_fail_the_boot` / `…two…` substitute the registry class (a `register_command` that drops, or doubles, the registration) to prove the boot fails BEFORE any connection, so the source arms are caught by `test_pr27_the_real_registration_builds_a_dispatcher_with_exactly_one_handler` (and by `test_pr43_start_runtime_runs_its_steps_in_order`) |
| I1 | "`tests/support/facts.py`" | `FactBuilders` lives in `services/projector/tests/conftest.py` and is exposed as the `facts` fixture. `pytest` runs in `--import-mode=importlib` and `mypy` resolves test files by path, so a sibling module is importable by neither without a change to the root `pyproject.toml`, which this feature may not make; Notifications' `conftest.py` is the precedent |
| J2 | "`$gte` … record which case catches it, or that none can" | `test_r52_…` cannot catch it (equal rank implies equal status, so `$gte` writes the same value). The case that catches it is `test_pr12_a_status_less_fact_on_an_absent_order_keeps_the_placeholder_status` (a rank-0 fact against the rank-0 placeholder: `$gte` writes `null` into `status`), added for this |
| J5 | "Arms: drop the `$min` cap …" | The cap never binds (finding 2); the arm is recorded as a survivor. The `$ne` clause arm is caught by the differential test and by the PR31 case |
| J6 | "Arms: drop `processedEventKeys`' `$sortArray`" | The arm survives (finding 3) |
| L3 | "all twelve present" | Present, and more: section 10 lists every arm of the run (133 mutation blocks), the twelve S1 – S8 / L2 rows among them |

### 4.2 Findings

1. **PR7's Phase-1 retry is unreachable on this server (E6's arm survives).** Evidence in 4.1 (E6). Disposition: ACCEPTED, NOT FIXED. The code is kept because `PR7` states it conditionally and it is free; E2's unit arms are the live guard. Re-open if a server version is pinned (compose or conftest) below 4.2, or if an upsert with a non-`_id` filter is ever introduced. Design 5.1's sentence "makes one insert lose with `DuplicateKeyError`" is true only for older servers; I did not edit the design (not in this feature's file list): the leader may amend it.
2. **The `$min` cap in the causal-order expression is dead code (J5's arm survives).** `$reduce` runs exactly `|entries|` rounds and a depth gains at most 1 per round from 0, so it is `<= |entries|` without the cap; the reference rule's cap is equally redundant. A cycle terminates because the `$reduce` is bounded, not because of the `$min`. Disposition: ACCEPTED, NOT FIXED — it mirrors #7 and #8, costs nothing, and the differential test (250 sets, cycles included) proves the order with or without it. Re-open if the `$reduce` bound is ever replaced.
3. **`$sortArray` on `processedEventKeys` is redundant on `mongo:8.3.8` (J6's arm survives).** A probe (`.arm/p24/probe_setunion.py`): `$setUnion` of `["projector:z", "projector:b", "projector:m"]` and `["projector:q", "projector:a"]` returned `['projector:a', 'projector:b', 'projector:m', 'projector:q', 'projector:z']`, value-ordered. The documentation calls the order unspecified, so the sort stays as insurance for `PR15`'s byte determinism and for the seed-equal order. Disposition: ACCEPTED, NOT FIXED. Re-open if a server pin changes: then `test_pr15_shuffled_and_duplicated_application_yields_byte_identical_documents` is the guard that would need a case where the two orders differ.
4. **The live topics hold 24 extra copies, not 16, and `ORD-000007` projects `despatched`.** N1 found 68 records over 44 distinct `eventId`s: eight `eventId`s four times each (24 extra copies). `progress/current.md:21` says 16; I did not reconcile the two (the topics may have been touched since that note). `ORD-000007` is `despatched`, not `confirmed`: its facts include an `order.despatched.v1` (2026-10-08) that precedes its `credit.approved.v1`/`order.confirmed.v1` (2026-10-09), while the Orders write model stayed `confirmed` (it did not apply that despatch). `R52` forbids regressing a rank-5 document, so `despatched` is the correct projection of the facts that exist. Disposition: recorded for the leader's Live-dev-data note; nothing to fix in the projector.
5. **The root conftest's Kafka is ONE broker for the whole pytest session, and every service's tests publish to the real fact topics.** A projector group starts at `earliest`, so a runtime pointed at the real topics replays whatever ANY earlier test of ANY service produced into this test's database; two `order.placed.v1` with one `orderReference` (different order ids) collide on `uq_order_reference` and are redelivered forever (the poison record `requirements.md` §5 carries to feature 27). It surfaced twice: as `test_pr51_…` failing on `ORD-000101` inside the projector's own run, and then — the real proof — as **the first full `./quality.sh` failing three cases** (`test_pr5_…`, `test_pr51_…`, `test_pr15_replaying_…`: 3 failed, 4072 passed, 692 s; the other services' tests had left their facts on the shared topics). A per-test unique `orderReference` (`new_reference`) only fixed the first. **Fix in this phase:** every test that starts the real runtime gets THREE PRIVATE TOPICS (`Topics` in `integration/conftest.py`), pointed at through `Externals.subscriber`; the real topic names are asserted by `unit/test_fact_topics.py`, `unit/test_kafka_fact_subscriber_options.py` and the live walkthrough. Armed (`J-isolation-real-topics`): with a scratch polluter that leaves two `order.placed.v1` with one reference on the REAL topic, the mutated run (real topics again) fails with `E11000 … uq_order_reference dup key: { orderReference: "ORD-424242" }` and the control run (the fix in place) passes. Feature 27's tests that start a consumer from `earliest` need the same isolation.
6. **Sweep survivors (M3):** six on the first run; five closed by new assertions (the optional-field guards of the signal builder, now `test_pr37_each_optional_field_is_guarded_by_its_own_value`; the `topic` and `partition` of the `PR4` log record); one equivalent mutant stands (section 7).
7. **`nats.connect` cancelled by `asyncio.timeout` leaves a half-built client** unless the caller owns the `Client` object: `composition.connect_nats` builds `NatsClient()` itself and closes it on any `BaseException`; `test_pr45_…` asserts no task survives the failed boot. Backlog 214's fix in Orders, Fulfillment and Billing can reuse the shape (not touched).
8. **aiokafka `partitions_for_topic` returns `None` before metadata is loaded** (a live-helper trap, not product code): `.arm/p24/live/n1.py` uses the six known partitions.
9. **`pytest.raises` "DID NOT RAISE" is the message of several arms** (A5, E2, I3): the test names and the parametrised ids carry the claim; the arms whose failure would otherwise be a bare `KeyError` or `ConnectionError` were given explicit messages (`PR19` re-raise, `PR46` note, `PR8` retailer keys).

## 5. The variant's subversion probe (E5) and the Orders parity guard (F1 – F3)

### E5 — the subversion probe


Mutation: drop `"processedEventKeys": {"$ne": key}` from the variant's filter, banner untouched. sha256 prefix before `fc9f5b38c78db010`, after `b952769a4676c4b3`.

**Orders parity guard under the mutation (must stay GREEN: it is text, by design):**
```
...........................                                              [100%]
27 passed in 0.73s
```

**E4 (the conformance file) under the mutation (must FAIL, naming the cases):**
```
E           AssertionError: assert <ConsumptionOutcome.PROCESSED: 'processed'> is <ConsumptionOutcome.DUPLICATE: 'duplicate'>
E            +  where <ConsumptionOutcome.DUPLICATE: 'duplicate'> = ConsumptionOutcome.DUPLICATE
E           AssertionError: case 3: a fresh instance over a new client did not see the recorded key
E           assert <ConsumptionOutcome.PROCESSED: 'processed'> is <ConsumptionOutcome.DUPLICATE: 'duplicate'>
E            +  where <ConsumptionOutcome.DUPLICATE: 'duplicate'> = ConsumptionOutcome.DUPLICATE
E           AssertionError: assert <ConsumptionOutcome.PROCESSED: 'processed'> is <ConsumptionOutcome.DUPLICATE: 'duplicate'>
E            +  where <ConsumptionOutcome.DUPLICATE: 'duplicate'> = ConsumptionOutcome.DUPLICATE
E               AssertionError: assert <ConsumptionOutcome.PROCESSED: 'processed'> is <ConsumptionOutcome.DUPLICATE: 'duplicate'>
E                +  where <ConsumptionOutcome.DUPLICATE: 'duplicate'> = ConsumptionOutcome.DUPLICATE
FAILED services/projector/tests/integration/test_idempotent_consumer_conformance.py::test_pr25_case_2_the_same_event_and_consumer_again_is_a_duplicate_and_work_does_not_run
FAILED services/projector/tests/integration/test_idempotent_consumer_conformance.py::test_pr25_case_3_a_fresh_instance_over_a_new_client_on_the_same_database_still_sees_it
FAILED services/projector/tests/integration/test_idempotent_consumer_conformance.py::test_pr25_case_5_the_same_event_under_a_different_consumer_name_runs
FAILED services/projector/tests/integration/test_idempotent_consumer_conformance.py::test_pr26_the_post_apply_callback_runs_once_on_processed_and_never_on_duplicate
4 failed, 3 passed in 4.14s
restored: cmp identical
```

**Result: the Orders parity guard stays GREEN (27 passed) while E4 FAILS (4 failed, 3 passed), naming cases 2, 3, 5 and `PR26`.** The guard is text by design (the banner, the registry, the files); the behavioural guard is E4. The variant guard is therefore NOT text-only: the leader does not need to be told otherwise.

### F1 — the edit, with `diff`

`cp` of the file to `.arm/p24/bak/F1.parity.orig.py` (sha256 `d2829755954de76c…`) before editing; `diff original edited` is `.arm/p24/fragments/F1-diff.txt` (405 lines: 34 removed, 329 added). **Every removed line is a helper definition, a helper call-site or case 4's old body; no `assert` of cases 1 – 3 is removed** (checked by reading the removed lines below). The real run prints `case 1 compared 2 copies`, `pr48 registry classified 7 packages`, `case 4 examined 1 variant(s)`; 27 cases pass.

```
def copies(root: Path) -> list[Path]:
    """Every service with BOTH a relational `processed_events` ledger AND its own consumer file:
    read from the filesystem, never from a hand-kept list of service names."""
        if has_relational_ledger(p) and consumer_file(p).is_file()
def divergent_copies(root: Path, canonical: Path) -> list[str]:
    for copy in copies(root):
def consumers_without_a_copy(root: Path) -> tuple[list[str], list[str]]:
    """`(examined, missing)`: services with a relational ledger and a Kafka consumer of facts, and
    those of them with no consumer file."""
        if not has_relational_ledger(package):
def variants_without_a_divergence_note(root: Path, canonical_path: str) -> list[str]:
    """A consumer file in a service with NO relational ledger is a variant: never compared, but its
    banner must name the canonical and carry a line beginning `Divergence:`."""
    found = []
        if has_relational_ledger(package) or not file.is_file():
            found.append(f"{package.name}: the banner does not cite {canonical_path}")
        if not any(line.startswith("Divergence:") for line in banner.splitlines()):
            found.append(f"{package.name}: the banner has no line beginning 'Divergence:'")
    return found
    reported = divergent_copies(tmp_path, canonical)
    assert divergent_copies(tmp_path, tmp_path / CANONICAL) == []
# ------------------------------------------------------------ case 4: variants name the canonical
def test_case_4_a_variant_carries_a_divergence_banner_naming_the_canonical() -> None:
    assert variants_without_a_divergence_note(REPO_ROOT, CANONICAL) == []
    # dormant until features 23/24: no service without a relational ledger has a consumer file yet
    variants = [
        consumer_file(p)
        for p in service_roots(REPO_ROOT)
        if not has_relational_ledger(p) and consumer_file(p).is_file()
    print(f"case 4 examined {len(variants)} variant(s)")
        f'"""Variant of {CANONICAL}.\n\nDivergence: a document store shares no transaction."""\n'
    unnamed = f'"""Variant of {CANONICAL}."""\n'
    reported = variants_without_a_divergence_note(tmp_path, CANONICAL)
    assert reported == ["otc_projector: the banner has no line beginning 'Divergence:'"]
```

### F2 — one temporary-tree sentinel per new premise

P1 – P6 and the control tree are cases of the edited file (`test_pr48_p1_…` – `test_pr48_p6_…`, `test_pr48_sentinel_the_control_tree_passes`); each asserts the INTENDED message. Each was armed by weakening the instrument (arms F2-P1 … F2-P6 in section 10): P1 stops reporting a package missing from the registry; P2 a stale entry; P3 looks for a name no module contains; P4 skips a variant with no file again (the OI12 opt-out); P5 stops checking the conformance file's existence; P6 stops comparing the registry with the spec. All six failed with the intended message.

### F3 — on the REAL tree


backup of the real file in `.arm/p24/bak/F3.idempotent_consumer.py`, sha256 prefix `fc9f5b38c78db010`

**(a) rename the projector's `idempotent_consumer.py` (the OI12 opt-out; must now fail by P4, both in the PR48 test and in case 4)**
```
E       AssertionError: assert ['otc_project..._consumer.py'] == []
E         
E         Left contains one more item: 'otc_projector: no consumer file at services/projector/src/otc_projector/infrastructure/messaging/idempotent_consumer.py'
E         Use -v to get more diff
1 failed in 0.08s
E       AssertionError: a registered mode disagrees with the files
E       assert ['projector: ...onsumer file'] == []
E         
E         Left contains one more item: 'projector: registered documented-variant but has no consumer file'
E         Use -v to get more diff
1 failed in 0.09s
restored: cmp identical
```

**(b) remove the `Behavioural conformance:` line from the real banner (must fail by P5)**
```
E       assert ["otc_project...mance:' line"] == []
E         
E         Left contains one more item: "otc_projector: the banner has no 'Behavioural conformance:' line"
E         Use -v to get more diff
1 failed in 0.08s
restored: cmp identical
```
27 passed in 0.80s

The first arm fails by P4 in BOTH places that now own the claim (case 4: `no consumer file at …/idempotent_consumer.py`; the `PR48` test: `registered documented-variant but has no consumer file`); the second fails by P5 (`the banner has no 'Behavioural conformance:' line`).

## 6. Every emission and suppression, armed (L1, L2, L3)

Each row: the mutation, the NAMED test, the first verbatim failure line; the full block (sha256 before and after, restore by `cmp`, forced cache clean, green re-run) is under the arm label in section 10. S5's asymmetry (what else fails) is `G4-asymmetry` there.

| Row | Mutation | Arm | Test | Failure (first `E` line, verbatim) |
|---|---|---|---|---|
| S1 | delete the callback invocation (the variant never calls `after_applied`) | G2-S1-delete-callback | `test_r55_emits_exactly_one_update_signal_per_applied_fact_on_a_per_order_channel_a_single_order_and_a_whole_stream_subscriber_both_receive_and_none_at_all_for_a_suppressed_redelivery` | `E               Failed: two pairs of frames: not observed within 20 s` |
| S2 | invoke the callback unconditionally (also for a redelivery) | G2-S2-unconditional-callback | `test_r55_emits_exactly_one_update_signal_per_applied_fact_on_a_per_order_channel_a_single_order_and_a_whole_stream_subscriber_both_receive_and_none_at_all_for_a_suppressed_redelivery` | `E       AssertionError: order.updated frames: 3` |
| S3 | re-raise in the `PR19` catch | C8-reraise | `test_pr19_a_publication_failure_is_logged_and_swallowed` | `E               Failed: PR19: a publication failure escaped the handler: ConnectionError('nats is gone')` |
| S4 | replace the `PR4` log with a bare `return`; catch the payload error and return | I3-bare-return | `test_pr4_an_unregistered_event_type_is_logged_and_committed_never_silently` | `E       AssertionError: an unregistered type must be logged, never silently dropped` |
| S4b | (the second S4 mutation) | I3-swallow-payload-error | `test_pr4_a_registered_type_with_an_invalid_payload_propagates` | `E       Failed: DID NOT RAISE ValueError` |
| S5 | remove `return_document=ReturnDocument.AFTER` | G4-return-document-default | `test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references` | `E       AssertionError: assert 'placed' == 'confirmed'` |
| S6 | remove `__depth` from `sortBy` | J4-no-depth | `test_r28_stock_released_precedes_the_order_cancelled_that_names_it_with_adversarial_event_ids` | `E       AssertionError: R28: stock.released must precede the order.cancelled that names it` |
| S6b | (the second case of S6) | J4-no-depth-r24 | `test_r24_the_completion_triple_is_stored_in_causal_order_with_adversarial_event_ids` | `E       AssertionError: R24: payment.received, credit.released, order.completed must be stored in causal order` |
| S7 | remove the `$literal` around the entry | E8-unwrap-entry | `test_pr47_dollar_prefixed_note_and_last_error_are_stored_verbatim` | `E       pymongo.errors.OperationFailure: Invalid $set :: caused by :: 'NOW x' contains an invalid character for a variable name: ' ', full error: {'ok': 0.0, 'errmsg': "Invalid $set :: caused by :: 'NOW x' contains an invalid char` |
| S7b | (the substitution half) | E8-unwrap-entry-substitution | `test_pr47_a_dollar_status_note_is_stored_as_text_not_evaluated_as_the_documents_status` | `E       AssertionError: the note was evaluated by the server: stored 'placed'` |
| S8 | `earliest` -> `latest` AT THE ASSIGNMENT SITE | I2-latest-at-the-site | `services/projector/tests/unit/test_kafka_fact_subscriber_options.py` | `E       AssertionError: {'bootstrap_servers': 'localhost:9092', 'group_id': 'projector', 'client_id': 'otc-projector', 'enable_auto_commit': False, ...}` |
| L2a | corrupt the `order.updated` frame's `status` — unit sentinel | L2-status-G5 | `test_pr37_every_field_reaches_both_signal_payloads_verbatim_sentinel_per_field` | `E       AssertionError: assert {'eventId': '...'placed', ...} == {'eventId': '...ncelled', ...}` |
| L2a' | the same — integration (G4) | L2-status-G4 | `test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references` | `E       AssertionError: the signal carries the PRE-apply status 'placed' (return_document default)` |
| L2b | corrupt the `timeline.appended` frame's `causationId` — PR33 | L2-causation-PR33 | `test_pr33_the_timeline_appended_payload_carries_causation_id` | `E       AssertionError: assert '00000321-032...-00000060c9cf' == '99999999-999...-999999999999'` |
| L2b' | the same — unit sentinel (G5) | L2-causation-G5 | `test_pr37_every_field_reaches_both_signal_payloads_verbatim_sentinel_per_field` | `E       AssertionError: assert {'eventId': '...-424242', ...} == {'eventId': '...-424242', ...}` |
| L2c | corrupt the stored entry's `summary` — C2 | L2-summary-C2 | `test_pr16_order_confirmed` | `E       AssertionError: assert 'Order confirmed (ORDRSP!)' == 'Order confirmed (ORDRSP)'` |
| L2c' | the same — J1 | L2-summary-J1 | `test_r50_appends_an_entry_carrying_event_id_event_type_occurred_at_and_a_summary_and_presents_the_timeline_ordered_by_occurred_at_rather_than_by_arrival` | `E           AssertionError: assert 'Order confirmed (ORDRSP!)' == 'Order confirmed (ORDRSP)'` |
| L2d | corrupt the stored `detail.note` — C6 | L2-note-C6 | `test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one` | `E           AssertionError: the operator's note was altered on its way to the entry` |
| L2d' | the same — J1 | L2-note-J1 | `test_pr46_a_noted_operator_cancellation_stores_the_note_verbatim` | `E       AssertionError: assert 'Cliente pidi...ón — $status!' == 'Cliente pidi...ión — $status'` |

All twelve L1/L2 rows the task names are present (S1 – S8 and the four corruption families) and every one failed under its mutation, was restored byte for byte and re-ran green. L3 is this section plus section 10: no emission or suppression of this feature survives its own deletion on a green suite (the survivors of this run are findings 1 – 3 and the equivalent mutant of section 7, none of them an emission).

## 7. The mutation sweep (M1 – M3)

**Instrument** (scratchpad `sweep.py`, not committed; its results are `.arm/p24/sweep/results.jsonl`). For every live attribute reference to a field of a generated payload / envelope model or of a domain / port dataclass in `application/projection.py`, `application/summaries.py`, `infrastructure/persistence/delta_to_pipeline.py`, `infrastructure/signal/nats_update_signal_publisher.py` and `presentation/projector_facts_consumer.py`, the receiver's class is resolved from the function's annotations, the `match` arm's class and comprehension variables (so a site is mutated only where the receiver is KNOWN), and the attribute is replaced by a sibling field of the SAME class and the same type category (the next and, when there are three or more, the previous; a class with no same-type sibling gets the next field of any type). One mutation per run: the unit suite (`-x`), then, for a survivor, the seven integration files that exercise the writer, the signal and the oracle; restore; assert the file's sha256 equals the original.

**Population (read off `sweep.py list`): 155 sites in five files -> 233 mutations**; by type category of the attribute: {'uuid': 6, 'other': 3, 'time': 7, 'object': 27, 'str': 125, 'int': 44, 'list': 9, 'enum': 9, 'bytes': 3}. The population includes `str`, `int`/money and instant-typed sites, as the task demands. Not covered, stated: string keys of dict literals (the camelCase document names are pinned by `test_pr41_*` and `test_pr44_*` instead), and references the resolver could not type.

**Sentinels, before any verdict (M2):**

```
A ('NOT-APPLIED', 'text unchanged')
B ('SURVIVED', 'all unit and integration cases passed')
C ('CAUGHT', 'unit: FAILED services/projector/tests/unit/test_projection.py::test_pr37_every_order_placed_field_reaches_the_header_verbatim_sentinel_per_field | 1 failed, 101 passed, 1 deselected in 1.07s')
```

| Sentinel | Mutation | Expected | Seen |
|---|---|---|---|
| A | text that does not occur anywhere | NOT-APPLIED (by `sha256`, not by a `replace()` return value) | NOT-APPLIED |
| B | the word `earliest` in `kafka_fact_subscriber.py`'s module DOCSTRING | SURVIVES | SURVIVED |
| C | `retailer_code` -> `company_code` in the `order.placed.v1` summary | CAUGHT | CAUGHT (`test_pr37_every_order_placed_field_reaches_the_header_verbatim_sentinel_per_field`) |

**Result of the final run (this session, after the five new assertions below):**

```
TOTAL 233  CAUGHT 232  SURVIVED 1  NOT-APPLIED 0  ERRORED 0
```

Per file: `application/projection.py` {'CAUGHT': 60, 'SURVIVED': 1}; `application/summaries.py` {'CAUGHT': 52}; `infrastructure/persistence/delta_to_pipeline.py` {'CAUGHT': 55}; `infrastructure/signal/nats_update_signal_publisher.py` {'CAUGHT': 56}; `presentation/projector_facts_consumer.py` {'CAUGHT': 9}.

**First run** (`.arm/p24/sweep/results_run1.jsonl`): TOTAL 233, CAUGHT 227, SURVIVED 6, NOT-APPLIED 0, ERRORED 0. Its six survivors, each classified:

| Survivor | Classification |
|---|---|
| `projection.py:122` `OrderConfirmedEvent.payload -> event_id` (`summaries.order_confirmed(event.payload)`) | **equivalent mutant**: `order_confirmed(_payload)` ignores its argument by design (the summary is constant), so no input can distinguish the two; cosmetic, STANDS (the one survivor of the final run) |
| `nats_update_signal_publisher.py:64` `applied.cancellation_reason -> payment_reference` (the `is not None` guard) | identity path (which field a reference guard reads): CLOSED by `unit/test_update_signal_payloads.py::test_pr37_each_optional_field_is_guarded_by_its_own_value` (one optional field present at a time) |
| `…:75` `applied.invoice_reference -> payment_reference` | same, CLOSED |
| `…:80` `applied.payment_reference -> invoice_reference` | same, CLOSED |
| `projector_facts_consumer.py:77` `message.topic -> partition` (the `PR4` log record) | identity path (the record the log names): CLOSED by the extended `test_pr4_an_unregistered_event_type_is_logged_and_committed_never_silently` (`topic`, `partition`, `offset`) |
| `…:78` `message.partition -> offset` | same, CLOSED |

The five closures were re-run alone (all five CAUGHT: `test_update_signal_payloads.py::test_pr37_each_optional_field_is_guarded_by_its_own_value` x3, `test_projector_facts_consumer.py::test_pr4_…[order.shipped.v1]` x2), then the whole sweep was re-run from empty: the figures above.

## 8. `./quality.sh`, twice, with the developer stack down (O1, K8)

Baseline (A2, before this feature): exit 0, 428 s, 3782 passed, overall 97.56 %, domain 98 %.

**A run that does NOT count, recorded because it found something:** the first full run after the feature's own suite was green failed three projector cases (3 failed, 4072 passed, 692 s; `.arm/p24/quality0_failed.log`): the runtime tests replayed other services' facts from the session-wide Kafka topics (finding 4.2.5). Fixed with private topics, armed, and the two runs below made from the fixed tree.

| Run | Exit | Wall time | pytest | Overall coverage (`fail_under` 60) | Domain + shared kernel (gate 80) |
|---|---|---|---|---|---|
| 1 | 0 | 541 s | 4075 passed in 497.32s (0:08:17) | 97.22 % | 98% |
| 2 | 0 | 491 s | 4075 passed in 467.02s (0:07:47) | 97.22 % | 98% |

(`.arm/p24/quality1.log`, `quality2.log`; each ends with `quality.sh: all gates passed`.) `mypy --strict`, `ruff`, `lint-imports` (11 contracts kept, 0 broken), the contracts drift check and the web gates are steps 1 – 7 of the same script.

## 9. Live walkthrough (N1 – N4): the developer stack started and stopped

Procedure: `docker ps` before = `otcpy-n8n` only (`.arm/p24/live/docker_before.txt`); `docker compose -p otcpy -f docker-compose.infra.yml start`; the projector as `uvicorn otc_projector.main:app --port 8105` with a fresh `projector` group (the broker listed only `orders.saga` and `notifications` before); Orders, Fulfillment and Billing as `uvicorn otc_{orders:8101,fulfillment:8102,billing:8103}.main:app` for N3 only; a `nats` subscriber on `readmodel.>` (`frames.py`) running from before the projector's boot to the end. Everything was stopped afterwards (`docker ps` after = `otcpy-n8n` only, now `healthy`; no `uvicorn` left). Helpers (not product code): `.arm/p24/live/*.py`.

### N1 — before the boot

```
== end offsets per topic (sum over partitions) and per partition
otc.orders.facts.v1 records 30 {0: 6, 1: 8, 2: 14, 3: 0, 4: 2, 5: 0}
otc.fulfillment.facts.v1 records 15 {0: 4, 1: 2, 2: 7, 3: 0, 4: 2, 5: 0}
otc.billing.facts.v1 records 23 {0: 10, 1: 1, 2: 11, 3: 0, 4: 1, 5: 0}
== records 68 distinct eventIds 44 eventIds seen more than once 8 extra records from duplicates 24
  dup 1745d7a6-d7b6-44ea-8811-b7f152183805 invoice.issued.v1 x 4
  dup 1eb8ebac-dc01-4a2d-892b-d03f5dcbc643 order.despatched.v1 x 4
  dup 24f4eef0-555e-48cd-8788-8e1612410a23 order.cancelled.v1 x 4
  dup 47a5971e-0309-4b8a-abcf-4eecbcfa49ed order.placed.v1 x 4
  dup 618c52c9-98ab-4d15-bc15-5d10b1e30e7b order.completed.v1 x 4
  dup 8a00a2c3-e5f3-4394-8ae8-b357ee6566fa payment.received.v1 x 4
  dup 8cdeb57a-70b5-446f-9fd5-f33f2f33b8ac order.placed.v1 x 4
  dup b866fd50-af9c-4bf3-a5ca-68c3f0cb8dce order.confirmed.v1 x 4
== seeded eventIds: 50 ; on any topic: 0 []
```

The seeded document in full (ORD-000003, 9 entries, `statusRank` 98, `timelineOrderVersion` 2, 9 sorted `processedEventKeys`) and the index list are in `.arm/p24/live/n1.txt`; the indexes were
```
{'v': 2, 'key': SON([('_id', 1)]), 'name': '_id_'}
  {'v': 2, 'key': SON([('orderReference', 1)]), 'name': 'uq_order_reference', 'unique': True, 'partialFilterExpression': SON([('orderReference', SON([('$type', 'string')]))])}
```
`order_timeline` held **6** documents. **Enumeration that no seeded `eventId` is on any topic:** the 50 `eventId`s of `SAGAS[*].timeline` against the 44 distinct `eventId`s read from the three topics (command `.venv/bin/python .arm/p24/live/n1.py`): `seeded eventIds: 50 ; on any topic: 0 []`. Requirements 2.11's argument holds.

**Not what the brief expected:** the topics hold 68 records over 44 distinct `eventId`s, eight `eventId`s four times each, i.e. 24 extra copies; `progress/current.md:21` says 16 (finding 4.2.4).

### N2 — the boot

`/health/ready` 200 after about 5 s; the group `projector` consumed all 68 records (lag 0, `.arm/p24/live/offsets_after_boot.txt`); zero `ERROR` lines in `projector.log`.

* Document count **6 -> 13** (7 new: `ORD-000007` – `-012` and one placeholder).
* The 6 seeded documents' raw BSON, sha256 per document before (`hashes_before.txt`) and after (`hashes_after.txt`): **all six identical** (the script compares them; identical for each of the six).
* For every document `len(events) == len(processedEventKeys)` and no repeated `eventId`: **0 violations of 13**.

```
document count 13
1741d5aa-cfba-4205-a1c0-82e7a5cb8984 ORD-000001  status=completed       rank= 98 headerComplete=True  events=9 keys=9 repeated=0 ok
cf826257-6521-4471-9292-d5a81919eba6 ORD-000002  status=completed       rank= 98 headerComplete=True  events=9 keys=9 repeated=0 ok
321abe6d-ee7b-465f-86d7-d65d6707d131 ORD-000003  status=completed       rank= 98 headerComplete=True  events=9 keys=9 repeated=0 ok
d69b8a2a-b0c8-47d5-bf66-82720335518c ORD-000004  status=completed       rank= 98 headerComplete=True  events=9 keys=9 repeated=0 ok
6baf7a6d-aeff-46af-a629-8abe050c8699 ORD-000005  status=completed       rank= 98 headerComplete=True  events=9 keys=9 repeated=0 ok
d8324836-41a0-44ab-8128-75b63039eda2 ORD-000006  status=cancelled       rank= 99 headerComplete=True  events=5 keys=5 repeated=0 ok
223c1406-1fd8-45c8-99c5-88a738720414 ORD-000007  status=despatched      rank=  5 headerComplete=True  events=5 keys=5 repeated=0 ok
b7117514-a2a0-49e5-a41f-bab72062b246 ORD-000008  status=completed       rank= 98 headerComplete=True  events=9 keys=9 repeated=0 ok
c8a96a35-b360-4965-a92a-4c379ac81dca ORD-000009  status=cancelled       rank= 99 headerComplete=True  events=5 keys=5 repeated=0 ok
9537652c-3e14-4491-a09a-6eea14bbf3de ORD-000010  status=completed       rank= 98 headerComplete=True  events=9 keys=9 repeated=0 ok
251a81ea-1ab1-4b23-a30c-00a51fc9949b ORD-000011  status=completed       rank= 98 headerComplete=True  events=9 keys=9 repeated=0 ok
22547f28-08c0-491c-ac9e-f4ed2f76c644 ORD-000012  status=cancelled       rank= 99 headerComplete=True  events=5 keys=5 repeated=0 ok
d9d4c3eb-fbc1-4fb9-bf5c-6820bde4fdf2 None        status=credit_approved rank=  3 headerComplete=False events=2 keys=2 repeated=0 ok
violations 0
```

* `ORD-000008`, `-010`, `-011` `completed`; `-009`, `-012` `cancelled`: as expected. **`ORD-000007` is `despatched`, not `confirmed`** (finding 4.2.4).
* The one placeholder (`headerComplete: false`, `orderReference: null`), and why it exists: it is the throwaway Billing-only order (its two facts are a `credit.approved.v1` and a `credit.released.v1`; its `order.placed.v1` is on no topic, so the header can never be filled):

```
223c1406-1fd8-45c8-99c5-88a738720414 ORD-000007 despatched headerComplete True updatedAt 2026-10-09T04:51:45.558Z references {'despatchReference': 'DES-000006', 'invoiceReference': None, 'paymentReference': None}
    2026-10-07T09:48:55.110Z order.placed.v1 | Order ORD-000007 placed for CarrefourEs | cause 1e85ee84
    2026-10-08T04:45:26.424Z stock.reserved.v1 | Stock reserved for 2 line(s) | cause bccaadb5
    2026-10-08T08:31:10.482Z order.despatched.v1 | Despatch DES-000006 created | cause 3d370996
    2026-10-09T04:51:45.558Z credit.approved.v1 | Credit hold of 555.45 EUR approved | cause 37a3ed86
    2026-10-09T04:51:45.558Z order.confirmed.v1 | Order confirmed (ORDRSP) | cause 387d2f9b
d9d4c3eb-fbc1-4fb9-bf5c-6820bde4fdf2 None credit_approved headerComplete False updatedAt 2026-10-09T04:52:59.760Z references {'despatchReference': None, 'invoiceReference': None, 'paymentReference': None}
    2026-10-09T04:52:59.579Z credit.approved.v1 | Credit hold of 10.00 EUR approved | cause f29407a8
    2026-10-09T04:52:59.760Z credit.released.v1 | Credit exposure released — order cancelled | cause e5bbbdcf
```

* 88 frames on `readmodel.>` for the 44 distinct facts (two per applied fact), i.e. the 24 extra copies produced none.

### N3 — expected absence, one order placed end to end

`orders.create` over NATS (CarrefourEs / SPANATURAL, `PRD-0004` x 2) -> `ORD-000013` (2900 EUR); the saga ran by itself to `invoiced`; the payment was registered over `billing.payment.register` -> `completed`:

```
== placing 2026-10-11T12:58:16+02:00
{"orderId":"0c1c3947-b7d3-40e3-a1aa-774da85836f1","orderReference":"ORD-000013","status":"placed","currency":"EUR","initialAmount":2900,"initialDiscount":0,"totalAmount":2900,"orderDate":"2026-10-11T10:58:16.385Z"}
0c1c3947-b7d3-40e3-a1aa-774da85836f1 ORD-000013 invoiced headerComplete True updatedAt 2026-10-11T10:58:17.323Z references {'despatchReference': 'DES-000010', 'invoiceReference': 'INV-000009', 'paymentReference': None}
    2026-10-11T10:58:16.385Z order.placed.v1 | Order ORD-000013 placed for CarrefourEs | cause 0f0fbcb3
    2026-10-11T10:58:16.601Z stock.reserved.v1 | Stock reserved for 1 line(s) | cause 884184db
    2026-10-11T10:58:16.822Z credit.approved.v1 | Credit hold of 29.00 EUR approved | cause 97d652d1
    2026-10-11T10:58:16.822Z order.confirmed.v1 | Order confirmed (ORDRSP) | cause 46946062
    2026-10-11T10:58:17.092Z order.despatched.v1 | Despatch DES-000010 created | cause 8e9f5e8f
    2026-10-11T10:58:17.323Z invoice.issued.v1 | Invoice INV-000009 issued | cause 777809fa
== payment 2026-10-11T12:58:43+02:00 request d3e46ef5-e4f7-4a4c-9288-fd03743c3c4b
{"outcome":"accepted","paymentReference":"LIVE-REF-000013","invoiceReference":"INV-000009","orderReference":"ORD-000013","invoiceStatus":"paid","paidAt":"2026-10-11T10:58:43.531Z"}
0c1c3947-b7d3-40e3-a1aa-774da85836f1 ORD-000013 completed headerComplete True updatedAt 2026-10-11T10:58:43.531Z references {'despatchReference': 'DES-000010', 'invoiceReference': 'INV-000009', 'paymentReference': 'LIVE-REF-000013'}
    2026-10-11T10:58:16.385Z order.placed.v1 | Order ORD-000013 placed for CarrefourEs | cause 0f0fbcb3
    2026-10-11T10:58:16.601Z stock.reserved.v1 | Stock reserved for 1 line(s) | cause 884184db
    2026-10-11T10:58:16.822Z credit.approved.v1 | Credit hold of 29.00 EUR approved | cause 97d652d1
    2026-10-11T10:58:16.822Z order.confirmed.v1 | Order confirmed (ORDRSP) | cause 46946062
    2026-10-11T10:58:17.092Z order.despatched.v1 | Despatch DES-000010 created | cause 8e9f5e8f
    2026-10-11T10:58:17.323Z invoice.issued.v1 | Invoice INV-000009 issued | cause 777809fa
    2026-10-11T10:58:43.531Z payment.received.v1 | Payment LIVE-REF-000013 received | cause d3e46ef5
    2026-10-11T10:58:43.531Z credit.released.v1 | Credit exposure released — invoice paid | cause 2b79cc01
    2026-10-11T10:58:43.531Z order.completed.v1 | Order ORD-000013 completed | cause 57f733d6
```

Counts before and after (`psql` on the three databases; `kafka-get-offsets` on the three topics):

```
otc_orders.outbox=32
otc_orders.saga_commands=21
otc_fulfillment.outbox=24
otc_billing.outbox=38
kafka.otc.orders.facts.v1=30
kafka.otc.fulfillment.facts.v1=15
kafka.otc.billing.facts.v1=23
-- after --
otc_orders.outbox=35
otc_orders.saga_commands=25
otc_fulfillment.outbox=26
otc_billing.outbox=42
kafka.otc.orders.facts.v1=33
kafka.otc.fulfillment.facts.v1=17
kafka.otc.billing.facts.v1=27
```

Orders' outbox +3 (placed, confirmed, completed), Fulfillment's +2 (reserved, despatched), Billing's +4 (approved, invoiced, payment, released) = **9 outbox rows**, **9 new Kafka records** (+3 / +2 / +4), the Orders saga's `saga_commands` +4: every new fact has an outbox row at a producing service and every saga command is Orders'. The projector has no PostgreSQL connection and no producer (K2 proves it structurally), so it caused **no fact, no outbox row and no saga command**. The frames: **18** for `ORD-000013` (9 facts x 2), each with `x-correlation-id` = the order id; 106 in total = 88 + 18.

`nats sub 'readmodel.>'` was a Python subscriber (`frames.py`) rather than the `nats` CLI; the frames are in `.arm/p24/live/frames.log` (first lines: `12:57:17 readmodel.order.updated.22547f28-08c0-491c-ac9e-f4ed2f76c644 x-correlation-id=22547f28-08c0-491c-ac9e-f4ed2f76c…`).

### N4 — a real process restart

The projector was stopped (`SIGTERM`; the log shows `Shutting down`, `Application shutdown complete`), an existing record (`ORD-000013`'s `order.completed.v1`) was re-published byte for byte while it was down (`re-published eventId fe8594d8-4d7e-49fc-90eb-5062f277fe68 to otc.orders.facts.v1 partition 2 offset 17`), and it was started again (a new process).

* Committed offsets read from the broker before and after the restart (`kafka-consumer-groups.sh --describe --group projector`): the only difference is that one partition moved by exactly one record, the re-published one:

```
15c15
< otc.orders.facts.v1 2 17 17 0
---
> otc.orders.facts.v1 2 18 18 0
```

* After: **0** documents with a repeated `eventId` and **0** with `len(events) != len(processedEventKeys)` (`check_after_restart.txt`: `violations 0`); all 14 documents byte-identical to before the restart (sha256 per document, `hashes_before_restart.txt` against `hashes_after_restart.txt`: `diff` empty); frames still 106 = 106 (the duplicate emitted none).

The one side effect on the developer stack, for the leader's Live-dev-data note: the topics now hold `ORD-000013`'s nine facts and one extra copy of its `order.completed.v1`, and the three databases hold `ORD-000013`, `DES-000010`, `INV-000009` and `LIVE-REF-000013`.


## 10. The arm ledger (verbatim)

One block per mutation: the file and its sha256 (first 16 hex digits) before and after the edit, the named test, the exit code of the mutated run, the restore evidence (`cmp` against the backup in the repo-local `.arm/p24/bak/`, sha256 equal, `__pycache__` and `.mypy_cache` cleared), the exit code and last line of the green re-run, then the tail of the failing run verbatim. The arming helper is `.arm/p24/arm.py` (a timeout kills the whole process group). Order: by task.

#### A4-motor

Mutation: add `motor` to the projector's dependencies.

- file `services/projector/pyproject.toml` sha256 before `948dac11d18f80cd` after mutation `2b83e9def608b003`
- test(s): `services/projector/tests/unit/test_projector_dependencies.py::test_the_projector_declares_pymongo_and_no_motor_sqlalchemy_asyncpg_or_alembic`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.01s`

```
F
=================================== FAILURES ===================================
_ test_the_projector_declares_pymongo_and_no_motor_sqlalchemy_asyncpg_or_alembic _
    def test_the_projector_declares_pymongo_and_no_motor_sqlalchemy_asyncpg_or_alembic() -> None:
        names = declared()
>       assert not names & FORBIDDEN, f"forbidden dependency declared: {sorted(names & FORBIDDEN)}"
E       AssertionError: forbidden dependency declared: ['motor']
E       assert not ({'aiokafka', 'fastapi', 'motor', 'nats-py', 'otc-contracts', 'otc-cqrs', ...} & {'alembic', 'asyncpg', 'motor', 'sqlalchemy'})
services/projector/tests/unit/test_projector_dependencies.py:41: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projector_dependencies.py::test_the_projector_declares_pymongo_and_no_motor_sqlalchemy_asyncpg_or_alembic
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.06s
```

#### A4-sqlalchemy

Mutation: add `sqlalchemy` to the projector's dependencies.

- file `services/projector/pyproject.toml` sha256 before `948dac11d18f80cd` after mutation `8abcc01363ad95bc`
- test(s): `services/projector/tests/unit/test_projector_dependencies.py::test_the_projector_declares_pymongo_and_no_motor_sqlalchemy_asyncpg_or_alembic`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.01s`

```
F
=================================== FAILURES ===================================
_ test_the_projector_declares_pymongo_and_no_motor_sqlalchemy_asyncpg_or_alembic _
    def test_the_projector_declares_pymongo_and_no_motor_sqlalchemy_asyncpg_or_alembic() -> None:
        names = declared()
>       assert not names & FORBIDDEN, f"forbidden dependency declared: {sorted(names & FORBIDDEN)}"
E       AssertionError: forbidden dependency declared: ['sqlalchemy']
E       assert not ({'aiokafka', 'fastapi', 'nats-py', 'otc-contracts', 'otc-cqrs', 'otc-shared-kernel', ...} & {'alembic', 'asyncpg', 'motor', 'sqlalchemy'})
services/projector/tests/unit/test_projector_dependencies.py:41: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projector_dependencies.py::test_the_projector_declares_pymongo_and_no_motor_sqlalchemy_asyncpg_or_alembic
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.06s
```

#### A5-client-id-pattern

Mutation: remove the client-id pattern.

- file `services/projector/src/otc_projector/infrastructure/settings.py` sha256 before `dea63383170da913` after mutation `1e262e40e857b948`
- test(s): `services/projector/tests/unit/test_projector_settings_env.py::test_an_empty_or_blank_client_id_or_group_fails_naming_the_variable`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `8 passed in 0.10s`

```
F
=================================== FAILURES ===================================
_ test_an_empty_or_blank_client_id_or_group_fails_naming_the_variable[-PROJECTOR_KAFKA_CLIENT_ID] _
clean_environment = <_pytest.monkeypatch.MonkeyPatch object at 0x72f9a3a1f950>
variable = 'PROJECTOR_KAFKA_CLIENT_ID', value = ''
    @pytest.mark.parametrize("variable", ["PROJECTOR_KAFKA_CLIENT_ID", "PROJECTOR_CONSUMER_GROUP"])
    @pytest.mark.parametrize("value", ["", "   ", "has space", "has/slash"])
    def test_an_empty_or_blank_client_id_or_group_fails_naming_the_variable(
        clean_environment: pytest.MonkeyPatch, variable: str, value: str
    ) -> None:
        clean_environment.setenv(variable, value)
>       with pytest.raises(ValidationError) as raised:
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       Failed: DID NOT RAISE ValidationError
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/tests/unit/test_projector_settings_env.py:95: Failed
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projector_settings_env.py::test_an_empty_or_blank_client_id_or_group_fails_naming_the_variable[-PROJECTOR_KAFKA_CLIENT_ID]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.14s
```

#### A5-drop-quote_plus

Mutation: drop `quote_plus` from the assembled URI.

- file `services/projector/src/otc_projector/infrastructure/settings.py` sha256 before `dea63383170da913` after mutation `0eb0e7682d650d4a`
- test(s): `services/projector/tests/unit/test_projector_settings_env.py::test_a_password_and_user_with_reserved_characters_round_trip_through_the_uri`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.12s`

```
_ test_a_password_and_user_with_reserved_characters_round_trip_through_the_uri _
clean_environment = <_pytest.monkeypatch.MonkeyPatch object at 0x732de5a3d940>
    def test_a_password_and_user_with_reserved_characters_round_trip_through_the_uri(
        clean_environment: pytest.MonkeyPatch,
    ) -> None:
        clean_environment.setenv("MONGO_INITDB_ROOT_USERNAME", "u@s")
        clean_environment.setenv("MONGO_INITDB_ROOT_PASSWORD", "p@ss/w:rd")
        clean_environment.setenv("MONGO_HOST", "mongo.sentinel")
        clean_environment.setenv("MONGO_HOST_PORT", "27999")
>       parsed = parse_uri(MongoSettings().uri)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/tests/unit/test_projector_settings_env.py:82: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/.venv/lib/python3.14/site-packages/pymongo/synchronous/uri_parser.py:108: in parse_uri
    result = _validate_uri(uri, default_port, validate, warn, normalize, srv_max_hosts)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/.venv/lib/python3.14/site-packages/pymongo/uri_parser_shared.py:585: in _validate_uri
    user, passwd = parse_userinfo(userinfo)
                   ^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
userinfo = 'u@s:p'
    def parse_userinfo(userinfo: str) -> tuple[str, str]:
        """Validates the format of user information in a MongoDB URI.
        Reserved characters that are gen-delimiters (":", "/", "?", "#", "[",
        "]", "@") as per RFC 3986 must be escaped.
        Returns a 2-tuple containing the unescaped username followed
        by the unescaped password.
        :param userinfo: A string of the form <username>:<password>
        """
        if "@" in userinfo or userinfo.count(":") > 1 or _unquoted_percent(userinfo):
>           raise InvalidURI(
                "Username and password must be escaped according to "
                "RFC 3986, use urllib.parse.quote_plus"
            )
E           pymongo.errors.InvalidURI: Username and password must be escaped according to RFC 3986, use urllib.parse.quote_plus
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/.venv/lib/python3.14/site-packages/pymongo/uri_parser_shared.py:145: InvalidURI
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projector_settings_env.py::test_a_password_and_user_with_reserved_characters_round_trip_through_the_uri
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.41s
```

#### A5-password-default

Mutation: give the Mongo password a default.

- file `services/projector/src/otc_projector/infrastructure/settings.py` sha256 before `dea63383170da913` after mutation `34c7b184f3da8011`
- test(s): `services/projector/tests/unit/test_projector_settings_env.py::test_no_password_and_no_uri_fails_naming_both_variables`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.10s`

```
F
=================================== FAILURES ===================================
___________ test_no_password_and_no_uri_fails_naming_both_variables ____________
clean_environment = <_pytest.monkeypatch.MonkeyPatch object at 0x759d3a063950>
    def test_no_password_and_no_uri_fails_naming_both_variables(
        clean_environment: pytest.MonkeyPatch,
    ) -> None:
>       with pytest.raises(ValidationError) as raised:
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       Failed: DID NOT RAISE ValidationError
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/tests/unit/test_projector_settings_env.py:68: Failed
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projector_settings_env.py::test_no_password_and_no_uri_fails_naming_both_variables
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.15s
```

#### A6-sibling-topic

Mutation: substitute `otc.orders.facts.v1` with the sibling `otc.orders.facts.v1.dlq`.

- file `services/projector/src/otc_projector/infrastructure/messaging/fact_topics.py` sha256 before `5b55b9dfe697d5de` after mutation `fadda381c3d93d79`
- test(s): `services/projector/tests/unit/test_fact_topics.py::test_the_projector_consumes_exactly_the_three_asyncapi_fact_channel_addresses`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.19s`

```
F
=================================== FAILURES ===================================
_ test_the_projector_consumes_exactly_the_three_asyncapi_fact_channel_addresses _
    def test_the_projector_consumes_exactly_the_three_asyncapi_fact_channel_addresses() -> None:
        channels = document()["channels"]
        expected = tuple(
            channels[c]["address"] for c in ("ordersFacts", "fulfillmentFacts", "billingFacts")
        )
>       assert PROJECTOR_FACT_TOPICS == expected
E       AssertionError: assert ('otc.orders....ing.facts.v1') == ('otc.orders....ing.facts.v1')
E         
E         At index 0 diff: 'otc.orders.facts.v1.dlq' != 'otc.orders.facts.v1'
E         Use -v to get more diff
services/projector/tests/unit/test_fact_topics.py:23: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_fact_topics.py::test_the_projector_consumes_exactly_the_three_asyncapi_fact_channel_addresses
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.23s
```

#### A7-projectors

Mutation: change the projector copy's PROJECTOR value to `projectors` (both tests of the file are run; the first stops the run).

- file `services/projector/src/otc_projector/infrastructure/messaging/consumer_name.py` sha256 before `fb8bc9ad58115380` after mutation `c939de6f048f12f8`
- test(s): `services/projector/tests/unit/test_consumer_name_copy.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `2 passed in 0.02s`

```
F
=================================== FAILURES ===================================
_____ test_the_projectors_consumer_name_is_a_byte_identical_copy_of_orders _____
    def test_the_projectors_consumer_name_is_a_byte_identical_copy_of_orders() -> None:
>       assert COPY.read_bytes() == ORIGINAL.read_bytes()
E       assert b'"""The clos...ifications"\n' == b'"""The clos...ifications"\n'
E         
E         At index 299 diff: b's' != b'"'
E         Use -v to get more diff
services/projector/tests/unit/test_consumer_name_copy.py:13: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_consumer_name_copy.py::test_the_projectors_consumer_name_is_a_byte_identical_copy_of_orders
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.06s
```

#### B2-partial-filter

Mutation: change the projector's partial filter to `{"$exists": True}`.

- file `services/projector/src/otc_projector/infrastructure/persistence/read_model_indexes.py` sha256 before `071e96c7456b66e6` after mutation `bb01ebc1f348065f`
- test(s): `services/projector/tests/unit/test_read_model_constants.py::test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.02s`

```
F
=================================== FAILURES ===================================
_ test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture _
    def test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture() -> None:
        constants = shared()
        assert TIMELINE_ORDER_VERSION == constants["timelineOrderVersion"], (
            "the projector's TIMELINE_ORDER_VERSION differs from the shared fixture's"
        )
        assert dict(STATUS_RANK) == constants["statusRank"], (
            "the projector's status -> rank table differs from the shared fixture's"
        )
        assert ConsumerName.PROJECTOR.value + ":" == constants["processedEventKeyPrefix"], (
            "the projector's dedup-key prefix differs from the shared fixture's"
        )
        assert COLLECTION == constants["collection"], (
            "the projector's collection name differs from the shared fixture's"
        )
        expected_index = constants["orderReferenceIndex"]
        assert ORDER_REFERENCE_INDEX.name == expected_index["name"]
        assert dict(ORDER_REFERENCE_INDEX.key) == expected_index["key"]
        assert ORDER_REFERENCE_INDEX.unique == expected_index["unique"]
>       assert ORDER_REFERENCE_INDEX.partial_filter == expected_index["partialFilterExpression"], (
            "the projector's uq_order_reference partial filter differs from the shared fixture's"
        )
E       AssertionError: the projector's uq_order_reference partial filter differs from the shared fixture's
E       assert {'orderRefere...xists': True}} == {'orderRefere...e': 'string'}}
E         
E         Differing items:
E         {'orderReference': {'$exists': True}} != {'orderReference': {'$type': 'string'}}
E         Use -v to get more diff
services/projector/tests/unit/test_read_model_constants.py:49: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_read_model_constants.py::test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.06s
```

#### B2-swap-ranks

Mutation: swap `completed: 98` and `cancelled: 99` in the projector's table.

- file `services/projector/src/otc_projector/domain/status_rank.py` sha256 before `691f935fe638052c` after mutation `a2ce2e2201b7ffb0`
- test(s): `services/projector/tests/unit/test_read_model_constants.py::test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.02s`

```
F
=================================== FAILURES ===================================
_ test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture _
    def test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture() -> None:
        constants = shared()
        assert TIMELINE_ORDER_VERSION == constants["timelineOrderVersion"], (
            "the projector's TIMELINE_ORDER_VERSION differs from the shared fixture's"
        )
>       assert dict(STATUS_RANK) == constants["statusRank"], (
            "the projector's status -> rank table differs from the shared fixture's"
        )
E       AssertionError: the projector's status -> rank table differs from the shared fixture's
E       assert {'placed': 1,...rmed': 4, ...} == {'placed': 1,...rmed': 4, ...}
E         
E         Omitting 7 identical items, use -vv to show
E         Differing items:
E         {'cancelled': 98} != {'cancelled': 99}
E         {'completed': 99} != {'completed': 98}
E         Use -v to get more diff
services/projector/tests/unit/test_read_model_constants.py:36: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_read_model_constants.py::test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.06s
```

#### B2-version-bump

Mutation: bump the projector's `TIMELINE_ORDER_VERSION` to 3 alone.

- file `services/projector/src/otc_projector/infrastructure/persistence/read_model_document.py` sha256 before `9de057e71dce8149` after mutation `20d9849c7de17494`
- test(s): `services/projector/tests/unit/test_read_model_constants.py::test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.02s`

```
F
=================================== FAILURES ===================================
_ test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture _
    def test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture() -> None:
        constants = shared()
>       assert TIMELINE_ORDER_VERSION == constants["timelineOrderVersion"], (
            "the projector's TIMELINE_ORDER_VERSION differs from the shared fixture's"
        )
E       AssertionError: the projector's TIMELINE_ORDER_VERSION differs from the shared fixture's
E       assert 3 == 2
services/projector/tests/unit/test_read_model_constants.py:33: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_read_model_constants.py::test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.06s
```

#### B3-depth-from-position

Mutation: compute depth from the cause's position in the input instead of the fixpoint.

- file `services/projector/src/otc_projector/domain/timeline_order.py` sha256 before `5d25bc2909be9b30` after mutation `1aa161e7a0073c0b`
- test(s): `services/projector/tests/unit/test_timeline_order_reference.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `10 passed in 0.03s`

```
F
=================================== FAILURES ===================================
_ test_pr10_the_reference_rule_orders_by_occurred_at_then_depth_then_event_id __
    def test_pr10_the_reference_rule_orders_by_occurred_at_then_depth_then_event_id() -> None:
        # A chain of three in one tie group, delivered reversed, with eventIds ordered AGAINST the
        # chain: the fallback alone would give c, b, a.
        root = position("c-root", "command-1")
        middle = position("b-middle", "c-root")
        leaf = position("a-leaf", "b-middle")
>       assert ids(causal_order([leaf, middle, root])) == ["c-root", "b-middle", "a-leaf"]
E       AssertionError: assert ['c-root', 'a...', 'b-middle'] == ['c-root', 'b...le', 'a-leaf']
E         
E         At index 1 diff: 'a-leaf' != 'b-middle'
E         Use -v to get more diff
services/projector/tests/unit/test_timeline_order_reference.py:29: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_timeline_order_reference.py::test_pr10_the_reference_rule_orders_by_occurred_at_then_depth_then_event_id
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.07s
```

#### B3-drop-depth

Mutation: drop the depth key (sort by occurredAt, eventId only).

- file `services/projector/src/otc_projector/domain/timeline_order.py` sha256 before `5d25bc2909be9b30` after mutation `577b6f408bc35182`
- test(s): `services/projector/tests/unit/test_timeline_order_reference.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `10 passed in 0.03s`

```
F
=================================== FAILURES ===================================
_ test_pr10_the_reference_rule_orders_by_occurred_at_then_depth_then_event_id __
    def test_pr10_the_reference_rule_orders_by_occurred_at_then_depth_then_event_id() -> None:
        # A chain of three in one tie group, delivered reversed, with eventIds ordered AGAINST the
        # chain: the fallback alone would give c, b, a.
        root = position("c-root", "command-1")
        middle = position("b-middle", "c-root")
        leaf = position("a-leaf", "b-middle")
>       assert ids(causal_order([leaf, middle, root])) == ["c-root", "b-middle", "a-leaf"]
E       AssertionError: assert ['a-leaf', 'b...le', 'c-root'] == ['c-root', 'b...le', 'a-leaf']
E         
E         At index 0 diff: 'a-leaf' != 'c-root'
E         Use -v to get more diff
services/projector/tests/unit/test_timeline_order_reference.py:29: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_timeline_order_reference.py::test_pr10_the_reference_rule_orders_by_occurred_at_then_depth_then_event_id
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.07s
```

#### B3-self-edge

Mutation: let a self-edge count as a cause.

- file `services/projector/src/otc_projector/domain/timeline_order.py` sha256 before `5d25bc2909be9b30` after mutation `aa5e17b0837d755c`
- test(s): `services/projector/tests/unit/test_timeline_order_reference.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `10 passed in 0.03s`

```
.......F
=================================== FAILURES ===================================
_____________________ test_pr31_a_self_edge_is_not_a_cause _____________________
    def test_pr31_a_self_edge_is_not_a_cause() -> None:
        # If a self-edge counted, `a-self` would reach depth 1 and sort after `b-plain`.
        entries = [position("b-plain", None), position("a-self", "a-self")]
>       assert ids(causal_order(entries)) == ["a-self", "b-plain"]
E       AssertionError: assert ['b-plain', 'a-self'] == ['a-self', 'b-plain']
E         
E         At index 0 diff: 'b-plain' != 'a-self'
E         Use -v to get more diff
services/projector/tests/unit/test_timeline_order_reference.py:80: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_timeline_order_reference.py::test_pr31_a_self_edge_is_not_a_cause
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 7 passed in 0.07s
```

#### B4-contracts-import

Mutation: `from otc_contracts import FACT_MODELS` in a scratch module under `domain/`.

- scratch file created then removed: `services/projector/src/otc_projector/domain/scratch_arm.py`
- test(s): `services/projector/tests/unit/test_domain_is_pure.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.02s`

```
F
=================================== FAILURES ===================================
___ test_the_domain_imports_only_the_standard_library_and_the_shared_kernel ____
    def test_the_domain_imports_only_the_standard_library_and_the_shared_kernel() -> None:
        files = sorted(DOMAIN.rglob("*.py"))
        assert {f.name for f in files} >= {
            "projection_delta.py",
            "status_rank.py",
            "timeline_order.py",
        }, f"the guard must range over the real domain files: {files}"
        for file in files:
            foreign = imported_roots(file) - ALLOWED_ROOTS
>           assert not foreign, f"{file.relative_to(DOMAIN.parents[3])} imports {sorted(foreign)}"
E           AssertionError: projector/src/otc_projector/domain/scratch_arm.py imports ['otc_contracts']
E           assert not {'otc_contracts'}
services/projector/tests/unit/test_domain_is_pure.py:33: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_domain_is_pure.py::test_the_domain_imports_only_the_standard_library_and_the_shared_kernel
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.06s
```

#### C1-any-in-port

Mutation: annotate one port parameter `Any`.

- file `services/projector/src/otc_projector/application/ports/read_model.py` sha256 before `e875afec967647d9` after mutation `5da9f89add587938`
- test(s): `services/projector/tests/unit/test_no_any_in_ports.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.02s`

```
F
=================================== FAILURES ===================================
__________ test_no_typing_any_in_the_domain_or_the_application_ports ___________
    def test_no_typing_any_in_the_domain_or_the_application_ports() -> None:
        files = [f for root in GUARDED for f in sorted(root.rglob("*.py"))]
        names = {f.name for f in files}
        assert {"read_model.py", "update_signal.py", "fact_stream.py", "timeline_order.py"} <= names, (
            f"the guard must range over the real port and domain files: {sorted(names)}"
        )
        offenders = [hit for f in files for hit in any_uses(f)]
>       assert offenders == [], f"typing.Any found: {offenders}"
E       AssertionError: typing.Any found: ['read_model.py:35 import Any', 'read_model.py:35 alias Any', 'read_model.py:37 Name Any']
E       assert ['read_model....:37 Name Any'] == []
E         
E         Left contains 3 more items, first extra item: 'read_model.py:35 import Any'
E         Use -v to get more diff
services/projector/tests/unit/test_no_any_in_ports.py:37: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_no_any_in_ports.py::test_no_typing_any_in_the_domain_or_the_application_ports
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.08s
```

#### C2-credit-rejected-reason

Mutation: corrupt the supplied `credit.rejected.v1` reason in the builder (use `over_limit` regardless).

- file `services/projector/src/otc_projector/application/summaries.py` sha256 before `84a2089b8084511b` after mutation `aa5c69073d65ce29`
- test(s): `services/projector/tests/unit/test_summaries.py::test_pr16_credit_rejected`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
F
=================================== FAILURES ===================================
__________________________ test_pr16_credit_rejected ___________________________
facts = FactBuilders()
    def test_pr16_credit_rejected(facts: Any) -> None:  # :62-67
        result = summaries.credit_rejected(
            payload(facts, "credit.rejected.v1", reason="simulated_cents_rule")
        )
>       assert result.text == "Credit hold of 5 000 JPY rejected (simulated_cents_rule)"
E       AssertionError: assert 'Credit hold ... (over_limit)' == 'Credit hold ...d_cents_rule)'
E         
E         - Credit hold of 5 000 JPY rejected (simulated_cents_rule)
E         ?                                    ^  ^^^ -------------
E         + Credit hold of 5 000 JPY rejected (over_limit)
E         ?                                    ^^^^^^  ^
services/projector/tests/unit/test_summaries.py:84: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_summaries.py::test_pr16_credit_rejected
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### C2-drop-compensation

Mutation: drop ` (compensation)`.

- file `services/projector/src/otc_projector/application/summaries.py` sha256 before `84a2089b8084511b` after mutation `99ae2d761aaa7fc9`
- test(s): `services/projector/tests/unit/test_summaries.py::test_pr16_stock_released_with_the_compensation_suffix_for_a_credit_rejection`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
F
=================================== FAILURES ===================================
_ test_pr16_stock_released_with_the_compensation_suffix_for_a_credit_rejection _
facts = FactBuilders()
    def test_pr16_stock_released_with_the_compensation_suffix_for_a_credit_rejection(
        facts: Any,
    ) -> None:  # :50
        result = summaries.stock_released(payload(facts, "stock.released.v1", reason="credit_rejected"))
>       assert result.text == "13 unit(s) released back to stock (compensation)"
E       AssertionError: assert '13 unit(s) r...back to stock' == '13 unit(s) r...compensation)'
E         
E         - 13 unit(s) released back to stock (compensation)
E         ?                                  ---------------
E         + 13 unit(s) released back to stock
services/projector/tests/unit/test_summaries.py:69: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_summaries.py::test_pr16_stock_released_with_the_compensation_suffix_for_a_credit_rejection
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.08s
```

#### C2-money-str

Mutation: render money with `str(minor_units)`.

- file `services/projector/src/otc_projector/application/summaries.py` sha256 before `84a2089b8084511b` after mutation `96059b4d1fb403cc`
- test(s): `services/projector/tests/unit/test_summaries.py::test_pr16_money_is_formatted_with_the_iso_4217_exponent_by_integer_arithmetic`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `5 passed in 0.04s`

```
F
=================================== FAILURES ===================================
_ test_pr16_money_is_formatted_with_the_iso_4217_exponent_by_integer_arithmetic[9245-EUR-92.45 EUR] _
facts = FactBuilders(), amount = 9245, currency = 'EUR', text = '92.45 EUR'
    @pytest.mark.parametrize(
        ("amount", "currency", "text"),
        [
            (9245, "EUR", "92.45 EUR"),
            (5000, "JPY", "5 000 JPY"),
            (12345, "BHD", "12.345 BHD"),
            (-9245, "EUR", "-92.45 EUR"),
            (2**62, "EUR", "46 116 860 184 273 879.04 EUR"),
        ],
    )
    def test_pr16_money_is_formatted_with_the_iso_4217_exponent_by_integer_arithmetic(
        facts: Any, amount: int, currency: str, text: str
    ) -> None:
        result = summaries.credit_approved(
            payload(facts, "credit.approved.v1", held_amount=amount, currency=currency)
        )
>       assert result.text == f"Credit hold of {text} approved"
E       AssertionError: assert 'Credit hold of 9245 approved' == 'Credit hold ... EUR approved'
E         
E         - Credit hold of 92.45 EUR approved
E         ?                  -  ----
E         + Credit hold of 9245 approved
services/projector/tests/unit/test_summaries.py:185: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_summaries.py::test_pr16_money_is_formatted_with_the_iso_4217_exponent_by_integer_arithmetic[9245-EUR-92.45 EUR]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### C2-placed-detail

Mutation: populate `detail` for `order.placed.v1`.

- file `services/projector/src/otc_projector/application/summaries.py` sha256 before `84a2089b8084511b` after mutation `d55cf92b3e892184`
- test(s): `services/projector/tests/unit/test_summaries.py::test_pr16_detail_is_present_only_for_the_five_named_facts`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
        builders = {
            "order.placed.v1": summaries.order_placed,
            "stock.reserved.v1": summaries.stock_reserved,
            "stock.rejected.v1": summaries.stock_rejected,
            "stock.released.v1": summaries.stock_released,
            "credit.approved.v1": summaries.credit_approved,
            "credit.rejected.v1": summaries.credit_rejected,
            "credit.released.v1": summaries.credit_released,
            "order.confirmed.v1": summaries.order_confirmed,
            "order.despatched.v1": summaries.order_despatched,
            "invoice.issued.v1": summaries.invoice_issued,
            "payment.received.v1": summaries.payment_received,
            "order.completed.v1": summaries.order_completed,
            "order.cancelled.v1": summaries.order_cancelled,
            "order.saga_failed.v1": summaries.order_saga_failed,
        }
        five = {
            "stock.rejected.v1",
            "stock.released.v1",
            "credit.rejected.v1",
            "order.cancelled.v1",
            "order.saga_failed.v1",
        }
        with_detail = {
            event_type
            for event_type, build in builders.items()
            if build(facts.build(event_type).payload).detail is not None
        }
        assert len(builders) == 14
>       assert with_detail == five
E       AssertionError: assert {'credit.reje....released.v1'} == {'credit.reje....released.v1'}
E         
E         Extra items in the left set:
E         'order.placed.v1'
E         Use -v to get more diff
services/projector/tests/unit/test_summaries.py:218: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_summaries.py::test_pr16_detail_is_present_only_for_the_five_named_facts
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### C3-delete-saga-failed-arm

Mutation: delete the `OrderSagaFailedEvent` arm (direction 1).

- file `services/projector/src/otc_projector/application/projection.py` sha256 before `86554167a730d5c6` after mutation `1b1ea09dca648fb3`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr2_projects_every_fact_models_entry_and_fails_in_both_directions_when_the_registry_and_the_match_disagree`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.05s`

```
facts = FactBuilders()
    def test_pr2_projects_every_fact_models_entry_and_fails_in_both_directions_when_the_registry_and_the_match_disagree(  # noqa: E501
        facts: Any,
    ) -> None:
        # direction 1: every registered fact projects a sample without raising, and its entry names it
        for event_type in FACT_MODELS:
            event = facts.build(event_type)
>           assert project(event).entry.event_type == event_type, event_type
                   ^^^^^^^^^^^^^^
services/projector/tests/unit/test_projection.py:42: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
services/projector/src/otc_projector/application/projection.py:154: in project
    assert_never(event)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
arg = OrderSagaFailedEvent(event_id=UUID('00000579-0579-4000-8000-000000a949f7'), event_type='order.saga_failed.v1', aggrega...ts=5, last_error='connection refused', failed_at=datetime.datetime(2026, 3, 12, 12, 22, 32, 345000, tzinfo=TzInfo(0))))
    def assert_never(arg: Never, /) -> Never:
        """Statically assert that a line of code is unreachable.
        Example::
            def int_or_str(arg: int | str) -> None:
                match arg:
                    case int():
                        print("It's an int")
                    case str():
                        print("It's a str")
                    case _:
                        assert_never(arg)
        If a type checker finds that a call to assert_never() is
        reachable, it will emit an error.
        At runtime, this throws an exception when called.
        """
        value = repr(arg)
        if len(value) > _ASSERT_NEVER_REPR_MAX_LENGTH:
            value = value[:_ASSERT_NEVER_REPR_MAX_LENGTH] + '...'
>       raise AssertionError(f"Expected code to be unreachable, but got: {value}")
E       AssertionError: Expected code to be unreachable, but got: OrderSagaFailedEvent(event_id=UUID('00000579-0579-4000-8000-000000a949f7'), event_type='order.saga_f...
../../../../.local/share/uv/python/cpython-3.14.8-linux-x86_64-gnu/lib/python3.14/typing.py:2594: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr2_projects_every_fact_models_entry_and_fails_in_both_directions_when_the_registry_and_the_match_disagree
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.15s
```

#### C3-extra-arm

Mutation: add an arm for a class that is not in `FACT_MODELS` (direction 2).

- file `services/projector/src/otc_projector/application/projection.py` sha256 before `86554167a730d5c6` after mutation `471e9130af29ca6b`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr2_projects_every_fact_models_entry_and_fails_in_both_directions_when_the_registry_and_the_match_disagree`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.05s`

```
F
=================================== FAILURES ===================================
_ test_pr2_projects_every_fact_models_entry_and_fails_in_both_directions_when_the_registry_and_the_match_disagree _
facts = FactBuilders()
    def test_pr2_projects_every_fact_models_entry_and_fails_in_both_directions_when_the_registry_and_the_match_disagree(  # noqa: E501
        facts: Any,
    ) -> None:
        # direction 1: every registered fact projects a sample without raising, and its entry names it
        for event_type in FACT_MODELS:
            event = facts.build(event_type)
            assert project(event).entry.event_type == event_type, event_type
        # direction 2: the classes the match names are exactly the registry's classes
        registered = {model.__name__ for model in FACT_MODELS.values()}
        matched = case_classes(PROJECTION)
>       assert matched == registered, (
            f"match arms without a registry entry: {sorted(matched - registered)}; "
            f"registry entries without an arm: {sorted(registered - matched)}"
        )
E       AssertionError: match arms without a registry entry: ['_Phantom']; registry entries without an arm: []
E       assert {'CreditAppro...edEvent', ...} == {'CreditAppro...edEvent', ...}
E         
E         Extra items in the left set:
E         '_Phantom'
E         Use -v to get more diff
services/projector/tests/unit/test_projection.py:46: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr2_projects_every_fact_models_entry_and_fails_in_both_directions_when_the_registry_and_the_match_disagree
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### C4-released-cancelled

Mutation: give `stock.released.v1` the implied status `cancelled`.

- file `services/projector/src/otc_projector/application/projection.py` sha256 before `dda70680218a055e` after mutation `1cb07d5e913e6c3e`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr12_maps_each_of_the_fourteen_facts_to_the_tables_status_and_rank`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `14 passed in 0.06s`

```
............F
=================================== FAILURES ===================================
_ test_pr12_maps_each_of_the_fourteen_facts_to_the_tables_status_and_rank[stock.released.v1] _
facts = FactBuilders(), event_type = 'stock.released.v1'
    @pytest.mark.parametrize("event_type", sorted(FACT_MODELS))
    def test_pr12_maps_each_of_the_fourteen_facts_to_the_tables_status_and_rank(
        facts: Any, event_type: str
    ) -> None:
        delta = project(facts.build(event_type))
        expected = PR12_STATUS[event_type]
>       assert delta.implied_status == expected, f"{event_type}: implied status"
E       AssertionError: stock.released.v1: implied status
E       assert 'cancelled' == None
E        +  where 'cancelled' = ProjectionDelta(order_id='00000193-0193-4000-8000-00000030b23d', entry=TimelineEntryDelta(event_id='00000191-0191-4000...ne, despatch_reference_if_absent=None, invoice_reference_if_absent=None, payment_reference_if_absent=None, header=None).implied_status
services/projector/tests/unit/test_projection.py:81: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr12_maps_each_of_the_fourteen_facts_to_the_tables_status_and_rank[stock.released.v1]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 12 passed in 0.12s
```

#### C4-swap-placed-reserved

Mutation: swap the `placed` / `stock_reserved` implied statuses.

- file `services/projector/src/otc_projector/application/projection.py` sha256 before `86554167a730d5c6` after mutation `d5f4a7fb32e06909`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr12_maps_each_of_the_fourteen_facts_to_the_tables_status_and_rank`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `14 passed in 0.06s`

```
........F
=================================== FAILURES ===================================
_ test_pr12_maps_each_of_the_fourteen_facts_to_the_tables_status_and_rank[order.placed.v1] _
facts = FactBuilders(), event_type = 'order.placed.v1'
    @pytest.mark.parametrize("event_type", sorted(FACT_MODELS))
    def test_pr12_maps_each_of_the_fourteen_facts_to_the_tables_status_and_rank(
        facts: Any, event_type: str
    ) -> None:
        delta = project(facts.build(event_type))
        expected = PR12_STATUS[event_type]
>       assert delta.implied_status == expected, f"{event_type}: implied status"
E       AssertionError: order.placed.v1: implied status
E       assert 'stock_reserved' == 'placed'
E         
E         - placed
E         + stock_reserved
services/projector/tests/unit/test_projection.py:81: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr12_maps_each_of_the_fourteen_facts_to_the_tables_status_and_rank[order.placed.v1]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 8 passed in 0.10s
```

#### C5-swap-amount-discount

Mutation: swap `initial_amount`/`initial_discount` in the header.

- file `services/projector/src/otc_projector/application/projection.py` sha256 before `86554167a730d5c6` after mutation `bd472d2e2329d37d`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr37_every_order_placed_field_reaches_the_header_verbatim_sentinel_per_field`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
                "description": "d2",
                "quantity": 73,
                "unit_price": 9203,
                "line_discount": 29,
            },
        ]
        event = facts.build(
            "order.placed.v1",
            payload={
                "order_reference": "ORD-777001",
                "order_date": order_date,
                "retailer_code": "RET-SENT",
                "company_code": "CMP-SENT",
                "buyer_gln": "1111111111116",
                "supplier_gln": "2222222222222",
                "currency": "SEK",
                "initial_amount": 4440005,
                "initial_discount": 3330007,
                "total_amount": 1110003,
                "lines": lines,
            },
        )
        delta = project(event)
        header = delta.header
        assert header is not None
        assert header.order_reference == "ORD-777001"
        assert header.order_date == order_date
        assert header.retailer_code == "RET-SENT"
        assert header.company_code == "CMP-SENT"
        assert header.retailer_gln == "1111111111116", "buyerGln -> retailer.gln"
        assert header.company_gln == "2222222222222", "supplierGln -> company.gln"
        assert header.currency == "SEK"
>       assert header.initial_amount == 4440005
E       AssertionError: assert 3330007 == 4440005
E        +  where 3330007 = HeaderDelta(order_reference='ORD-777001', order_date=datetime.datetime(2030, 2, 3, 4, 5, 6, 789000, tzinfo=TzInfo(0)),...unit_price=8101, line_discount=17), ItemDelta(product_code='SENT-P2', quantity=73, unit_price=9203, line_discount=29))).initial_amount
services/projector/tests/unit/test_projection.py:169: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr37_every_order_placed_field_reaches_the_header_verbatim_sentinel_per_field
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.11s
```

#### C5-swap-event-causation

Mutation: swap `causation_id`/`event_id` on the entry.

- file `services/projector/src/otc_projector/application/projection.py` sha256 before `86554167a730d5c6` after mutation `79fb59cb830c982b`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr37_every_envelope_field_reaches_the_entry_verbatim_sentinel_per_field`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
F
=================================== FAILURES ===================================
_ test_pr37_every_envelope_field_reaches_the_entry_verbatim_sentinel_per_field _
facts = FactBuilders()
    def test_pr37_every_envelope_field_reaches_the_entry_verbatim_sentinel_per_field(
        facts: Any,
    ) -> None:
        from datetime import UTC, datetime
        occurred_at = datetime(2031, 5, 6, 7, 8, 9, 321000, tzinfo=UTC)
        event = facts.build("stock.reserved.v1", occurred_at=occurred_at, **ENVELOPE_SENTINELS)
        delta = project(event)
>       assert delta.entry.event_id == "aaaaaaaa-0001-4000-8000-000000000001", "eventId"
E       AssertionError: eventId
E       assert 'aaaaaaaa-000...-000000000004' == 'aaaaaaaa-000...-000000000001'
E         
E         - aaaaaaaa-0001-4000-8000-000000000001
E         ?             ^                      ^
E         + aaaaaaaa-0004-4000-8000-000000000004
E         ?             ^                      ^
services/projector/tests/unit/test_projection.py:109: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr37_every_envelope_field_reaches_the_entry_verbatim_sentinel_per_field
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.11s
```

#### C5-swap-glns

Mutation: swap `buyer_gln`/`supplier_gln` in the header.

- file `services/projector/src/otc_projector/application/projection.py` sha256 before `86554167a730d5c6` after mutation `4a3ea4d4ca6501e5`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr37_every_order_placed_field_reaches_the_header_verbatim_sentinel_per_field`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.05s`

```
                "description": "d2",
                "quantity": 73,
                "unit_price": 9203,
                "line_discount": 29,
            },
        ]
        event = facts.build(
            "order.placed.v1",
            payload={
                "order_reference": "ORD-777001",
                "order_date": order_date,
                "retailer_code": "RET-SENT",
                "company_code": "CMP-SENT",
                "buyer_gln": "1111111111116",
                "supplier_gln": "2222222222222",
                "currency": "SEK",
                "initial_amount": 4440005,
                "initial_discount": 3330007,
                "total_amount": 1110003,
                "lines": lines,
            },
        )
        delta = project(event)
        header = delta.header
        assert header is not None
        assert header.order_reference == "ORD-777001"
        assert header.order_date == order_date
        assert header.retailer_code == "RET-SENT"
        assert header.company_code == "CMP-SENT"
>       assert header.retailer_gln == "1111111111116", "buyerGln -> retailer.gln"
E       AssertionError: buyerGln -> retailer.gln
E       assert '2222222222222' == '1111111111116'
E         
E         - 1111111111116
E         + 2222222222222
services/projector/tests/unit/test_projection.py:166: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr37_every_order_placed_field_reaches_the_header_verbatim_sentinel_per_field
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### C5-swap-retailer-company

Mutation: swap `retailer_code`/`company_code` in the header.

- file `services/projector/src/otc_projector/application/projection.py` sha256 before `86554167a730d5c6` after mutation `ef0ac05f1f9fb27d`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr37_every_order_placed_field_reaches_the_header_verbatim_sentinel_per_field`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
            },
            {
                "product_code": "SENT-P2",
                "description": "d2",
                "quantity": 73,
                "unit_price": 9203,
                "line_discount": 29,
            },
        ]
        event = facts.build(
            "order.placed.v1",
            payload={
                "order_reference": "ORD-777001",
                "order_date": order_date,
                "retailer_code": "RET-SENT",
                "company_code": "CMP-SENT",
                "buyer_gln": "1111111111116",
                "supplier_gln": "2222222222222",
                "currency": "SEK",
                "initial_amount": 4440005,
                "initial_discount": 3330007,
                "total_amount": 1110003,
                "lines": lines,
            },
        )
        delta = project(event)
        header = delta.header
        assert header is not None
        assert header.order_reference == "ORD-777001"
        assert header.order_date == order_date
>       assert header.retailer_code == "RET-SENT"
E       AssertionError: assert 'CMP-SENT' == 'RET-SENT'
E         
E         - RET-SENT
E         + CMP-SENT
services/projector/tests/unit/test_projection.py:164: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr37_every_order_placed_field_reaches_the_header_verbatim_sentinel_per_field
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### C6-delete-note

Mutation: delete the `note` line.

- file `services/projector/src/otc_projector/application/summaries.py` sha256 before `84a2089b8084511b` after mutation `16938fdb4eec8d8d`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `6 passed in 0.05s`

```
F
=================================== FAILURES ===================================
_ test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one[operator_cancelled-step_names0-Cliente pidi\xf3 anulaci\xf3n] _
facts = FactBuilders(), reason = 'operator_cancelled', step_names = []
note = 'Cliente pidió anulación'
    @pytest.mark.parametrize(("reason", "step_names", "note"), BRANCHES)
    def test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one(
        facts: Any, reason: str, step_names: list[str], note: str | None
    ) -> None:
        payload: dict[str, Any] = {
            "cancellation_reason": reason,
            "compensation_steps": steps(step_names),
        }
        if note is not None:
            payload["note"] = note
        detail = project(facts.build("order.cancelled.v1", payload=payload)).entry.detail
        assert detail is not None
        if note is None:
            assert "note" not in detail, f"a note appeared where the fact had none: {detail}"
        else:
>           assert "note" in detail, f"the operator's note {note!r} did not reach detail: {detail}"
E           AssertionError: the operator's note 'Cliente pidió anulación' did not reach detail: {'cancellationReason': 'operator_cancelled', 'compensationSteps': []}
E           assert 'note' in {'cancellationReason': 'operator_cancelled', 'compensationSteps': []}
services/projector/tests/unit/test_projection.py:224: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one[operator_cancelled-step_names0-Cliente pidi\xf3 anulaci\xf3n]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### C6-note-none-when-absent

Mutation: write `detail["note"] = None` when absent.

- file `services/projector/src/otc_projector/application/summaries.py` sha256 before `84a2089b8084511b` after mutation `9fdfd307cea14726`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `6 passed in 0.05s`

```
...F
=================================== FAILURES ===================================
_ test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one[operator_cancelled-step_names3-None] _
facts = FactBuilders(), reason = 'operator_cancelled', step_names = []
note = None
    @pytest.mark.parametrize(("reason", "step_names", "note"), BRANCHES)
    def test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one(
        facts: Any, reason: str, step_names: list[str], note: str | None
    ) -> None:
        payload: dict[str, Any] = {
            "cancellation_reason": reason,
            "compensation_steps": steps(step_names),
        }
        if note is not None:
            payload["note"] = note
        detail = project(facts.build("order.cancelled.v1", payload=payload)).entry.detail
        assert detail is not None
        if note is None:
>           assert "note" not in detail, f"a note appeared where the fact had none: {detail}"
E           AssertionError: a note appeared where the fact had none: {'cancellationReason': 'operator_cancelled', 'compensationSteps': [], 'note': None}
E           assert 'note' not in {'cancellationReason': 'operator_cancelled', 'compensationSteps': [], 'note': None}
services/projector/tests/unit/test_projection.py:222: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one[operator_cancelled-step_names3-None]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 3 passed in 0.10s
```

#### C6-strip-note

Mutation: strip the note.

- file `services/projector/src/otc_projector/application/summaries.py` sha256 before `84a2089b8084511b` after mutation `5d4a4f180fe42ef1`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `6 passed in 0.05s`

```
..F
=================================== FAILURES ===================================
_ test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one[operator_cancelled-step_names2- spaced ] _
facts = FactBuilders(), reason = 'operator_cancelled'
step_names = ['stock_released', 'credit_released'], note = ' spaced '
    @pytest.mark.parametrize(("reason", "step_names", "note"), BRANCHES)
    def test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one(
        facts: Any, reason: str, step_names: list[str], note: str | None
    ) -> None:
        payload: dict[str, Any] = {
            "cancellation_reason": reason,
            "compensation_steps": steps(step_names),
        }
        if note is not None:
            payload["note"] = note
        detail = project(facts.build("order.cancelled.v1", payload=payload)).entry.detail
        assert detail is not None
        if note is None:
            assert "note" not in detail, f"a note appeared where the fact had none: {detail}"
        else:
>           assert detail["note"] == note, "the operator's note was altered on its way to the entry"
E           AssertionError: the operator's note was altered on its way to the entry
E           assert 'spaced' == ' spaced '
E             
E             -  spaced 
E             ? -      -
E             + spaced
services/projector/tests/unit/test_projection.py:224: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one[operator_cancelled-step_names2- spaced ]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 2 passed in 0.10s
```

#### C7-set-literal

Mutation: add `HANDLED = {"order.placed.v1", "stock.reserved.v1"}` to a scratch module under `src`.

- scratch file created then removed: `services/projector/src/otc_projector/scratch_hits.py`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.06s`

```
F
=================================== FAILURES ===================================
_ test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set _
    def test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set() -> (  # noqa: E501
        None
    ):
        hits = event_type_hits(SRC, fourteen_event_types())
        classified = {(file, line) for file, line, _ in CLASSIFIED_HITS}
>       assert hits == classified, (
            f"unclassified eventType literals under services/projector/src: {sorted(hits - classified)}"
            f"; classified but gone: {sorted(classified - hits)}"
        )
E       AssertionError: unclassified eventType literals under services/projector/src: [('scratch_hits.py', 1)]; classified but gone: []
E       assert {('scratch_hits.py', 1)} == set()
E         
E         Extra items in the left set:
E         ('scratch_hits.py', 1)
E         Use -v to get more diff
services/projector/tests/unit/test_projection.py:288: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.11s
```

#### C7-triple-quoted

Mutation (defeat row 6): the literal hidden in a triple-quoted string.

- scratch file created then removed: `services/projector/src/otc_projector/scratch_hits.py`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.06s`

```
F
=================================== FAILURES ===================================
_ test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set _
    def test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set() -> (  # noqa: E501
        None
    ):
        hits = event_type_hits(SRC, fourteen_event_types())
        classified = {(file, line) for file, line, _ in CLASSIFIED_HITS}
>       assert hits == classified, (
            f"unclassified eventType literals under services/projector/src: {sorted(hits - classified)}"
            f"; classified but gone: {sorted(classified - hits)}"
        )
E       AssertionError: unclassified eventType literals under services/projector/src: [('scratch_hits.py', 1)]; classified but gone: []
E       assert {('scratch_hits.py', 1)} == set()
E         
E         Extra items in the left set:
E         ('scratch_hits.py', 1)
E         Use -v to get more diff
services/projector/tests/unit/test_projection.py:288: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.11s
```

#### C7-type-checking

Mutation (defeat row 5): the literal hidden in an `if TYPE_CHECKING:` block.

- scratch file created then removed: `services/projector/src/otc_projector/scratch_hits.py`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.06s`

```
F
=================================== FAILURES ===================================
_ test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set _
    def test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set() -> (  # noqa: E501
        None
    ):
        hits = event_type_hits(SRC, fourteen_event_types())
        classified = {(file, line) for file, line, _ in CLASSIFIED_HITS}
>       assert hits == classified, (
            f"unclassified eventType literals under services/projector/src: {sorted(hits - classified)}"
            f"; classified but gone: {sorted(classified - hits)}"
        )
E       AssertionError: unclassified eventType literals under services/projector/src: [('scratch_hits.py', 4)]; classified but gone: []
E       assert {('scratch_hits.py', 4)} == set()
E         
E         Extra items in the left set:
E         ('scratch_hits.py', 4)
E         Use -v to get more diff
services/projector/tests/unit/test_projection.py:288: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr36_no_event_type_literal_appears_under_the_projector_source_outside_the_classified_set
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.11s
```

#### C8-publish-on-duplicate

Mutation: publish on `DUPLICATE`.

- file `services/projector/src/otc_projector/application/handlers.py` sha256 before `64b21d037ae5f54b` after mutation `7400ab3405d72650`
- test(s): `services/projector/tests/unit/test_project_fact_handler.py::test_pr18_a_duplicate_publishes_nothing`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
F
=================================== FAILURES ===================================
___________________ test_pr18_a_duplicate_publishes_nothing ____________________
facts = FactBuilders()
    async def test_pr18_a_duplicate_publishes_nothing(facts: Any) -> None:
        writer, publisher = FakeWriter(ProjectionOutcome.DUPLICATE), FakePublisher()
        outcome = await handler_for(writer, publisher).handle(
            ProjectFactCommand(event=facts.build("order.confirmed.v1"))
        )
        assert outcome is ProjectionOutcome.DUPLICATE
        assert len(writer.deltas) == 1, "the writer was not asked"
>       assert len(publisher.calls) == 0, "a suppressed redelivery published a signal"
E       AssertionError: a suppressed redelivery published a signal
E       assert 1 == 0
E        +  where 1 = len([(AppliedDocument(order_id='00000323-0323-4000-8000-0000006107ad', order_reference=None, status='placed', cancellation...nfo=TzInfo(0)), summary='Order confirmed (ORDRSP)', causation_id='00000324-0324-4000-8000-00000061269c', detail=None))])
E        +    where [(AppliedDocument(order_id='00000323-0323-4000-8000-0000006107ad', order_reference=None, status='placed', cancellation...nfo=TzInfo(0)), summary='Order confirmed (ORDRSP)', causation_id='00000324-0324-4000-8000-00000061269c', detail=None))] = <services.projector.tests.unit.test_project_fact_handler.FakePublisher object at 0x76e061d0a3c0>.calls
services/projector/tests/unit/test_project_fact_handler.py:96: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_project_fact_handler.py::test_pr18_a_duplicate_publishes_nothing
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.11s
```

#### C8-reraise

Mutation (S3): re-raise in the PR19 catch.

- file `services/projector/src/otc_projector/application/handlers.py` sha256 before `64b21d037ae5f54b` after mutation `5ac39cc11378fc83`
- test(s): `services/projector/tests/unit/test_project_fact_handler.py::test_pr19_a_publication_failure_is_logged_and_swallowed`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.05s`

```
services/projector/src/otc_projector/application/handlers.py:43: in _announce
    await self._scope.signals.publish(applied, delta.entry)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
self = <services.projector.tests.unit.test_project_fact_handler.FakePublisher object at 0x737e98dfe510>
applied = AppliedDocument(order_id='post-apply-order', order_reference='ORD-555555', status='paid', cancellation_reason=None, de...NV-555555', payment_reference='PAY-555555', totals=AppliedTotals(initial_amount=1, initial_discount=2, total_amount=3))
entry = TimelineEntryDelta(event_id='000003e9-03e9-4000-8000-00000078f487', event_type='invoice.issued.v1', occurred_at=dateti...info=TzInfo(0)), summary='Invoice INV-000304 issued', causation_id='000003ec-03ec-4000-8000-000000795154', detail=None)
    async def publish(self, applied: AppliedDocument, entry: TimelineEntryDelta) -> None:
        self.calls.append((applied, entry))
        if self.error is not None:
>           raise self.error
E           ConnectionError: nats is gone
services/projector/tests/unit/test_project_fact_handler.py:64: ConnectionError
During handling of the above exception, another exception occurred:
facts = FactBuilders()
caplog = <_pytest.logging.LogCaptureFixture object at 0x737e98dfdd30>
    async def test_pr19_a_publication_failure_is_logged_and_swallowed(
        facts: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        writer, publisher = FakeWriter(ProjectionOutcome.PROCESSED), FakePublisher()
        publisher.error = ConnectionError("nats is gone")
        event = facts.build("invoice.issued.v1")
        with caplog.at_level(logging.ERROR, logger="otc_projector.application.handlers"):
            try:
                outcome = await handler_for(writer, publisher).handle(ProjectFactCommand(event=event))
            except Exception as error:  # noqa: BLE001 - the claim is that NOTHING escapes
>               pytest.fail(f"PR19: a publication failure escaped the handler: {error!r}")
E               Failed: PR19: a publication failure escaped the handler: ConnectionError('nats is gone')
services/projector/tests/unit/test_project_fact_handler.py:120: Failed
------------------------------ Captured log call -------------------------------
ERROR    otc_projector.application.handlers:handlers.py:47 the update signal could not be published on readmodel.order.updated.000003eb-03eb-4000-8000-000000793265 and readmodel.timeline.appended.000003eb-03eb-4000-8000-000000793265; the fact is applied and committed
Traceback (most recent call last):
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/src/otc_projector/application/handlers.py", line 43, in _announce
    await self._scope.signals.publish(applied, delta.entry)
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/tests/unit/test_project_fact_handler.py", line 64, in publish
    raise self.error
ConnectionError: nats is gone
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_project_fact_handler.py::test_pr19_a_publication_failure_is_logged_and_swallowed
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### C8-signal-from-delta

Mutation: build the signal from the delta instead of the applied document.

- file `services/projector/src/otc_projector/application/handlers.py` sha256 before `64b21d037ae5f54b` after mutation `e8d038a12a09594a`
- test(s): `services/projector/tests/unit/test_project_fact_handler.py::test_pr18_the_signal_is_built_from_the_post_apply_document`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
F
=================================== FAILURES ===================================
__________ test_pr18_the_signal_is_built_from_the_post_apply_document __________
facts = FactBuilders()
    async def test_pr18_the_signal_is_built_from_the_post_apply_document(facts: Any) -> None:
        writer, publisher = FakeWriter(ProjectionOutcome.PROCESSED), FakePublisher()
        await handler_for(writer, publisher).handle(
            ProjectFactCommand(event=facts.build("order.despatched.v1"))
        )
        assert len(publisher.calls) == 1
        applied, entry = publisher.calls[0]
>       assert applied is POST_APPLY, "the publisher did not receive the document the writer returned"
E       AssertionError: the publisher did not receive the document the writer returned
E       assert AppliedDocument(order_id='00000387-0387-4000-8000-0000006d1d09', order_reference='ORD-555555', status='despatched', ca...NV-555555', payment_reference='PAY-555555', totals=AppliedTotals(initial_amount=1, initial_discount=2, total_amount=3)) is AppliedDocument(order_id='post-apply-order', order_reference='ORD-555555', status='paid', cancellation_reason=None, de...NV-555555', payment_reference='PAY-555555', totals=AppliedTotals(initial_amount=1, initial_discount=2, total_amount=3))
services/projector/tests/unit/test_project_fact_handler.py:106: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_project_fact_handler.py::test_pr18_the_signal_is_built_from_the_post_apply_document
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### D2-drop-ifnull-invoice

Mutation: delete the `$ifNull` on `invoiceReference`.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `2c15679d54c7f81e`
- test(s): `services/projector/tests/unit/test_delta_to_pipeline.py::test_pr11_a_reference_fact_fills_only_its_own_reference_if_null`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `3 passed in 0.05s`

```
F
=================================== FAILURES ===================================
_ test_pr11_a_reference_fact_fills_only_its_own_reference_if_null[invoice.issued.v1] _
facts = FactBuilders(), event_type = 'invoice.issued.v1'
    @pytest.mark.parametrize("event_type", sorted(REFERENCE_FACTS))
    def test_pr11_a_reference_fact_fills_only_its_own_reference_if_null(
        facts: Any, event_type: str
    ) -> None:
        fields = stage_fields(delta_to_pipeline(project(facts.build(event_type)), "projector:x"))
        own, value = REFERENCE_FACTS[event_type]
>       assert fields[own] == {"$ifNull": [f"${own}", literal(value)]}
E       AssertionError: assert {'$literal': 'INV-000304'} == {'$ifNull': [...INV-000304'}]}
E         
E         Left contains 1 more item:
E         {'$literal': 'INV-000304'}
E         Right contains 1 more item:
E         {'$ifNull': ['$references.invoiceReference', {'$literal': 'INV-000304'}]}
E         Use -v to get more diff
services/projector/tests/unit/test_delta_to_pipeline.py:201: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_delta_to_pipeline.py::test_pr11_a_reference_fact_fills_only_its_own_reference_if_null[invoice.issued.v1]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### D2-header-ifnull

Mutation: wrap the header's `orderReference` in `$ifNull`.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `b0bd992af406b869`
- test(s): `services/projector/tests/unit/test_delta_to_pipeline.py::test_pr9_order_placed_writes_the_header_unconditionally_and_marks_it_complete`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.05s`

```
F
=================================== FAILURES ===================================
_ test_pr9_order_placed_writes_the_header_unconditionally_and_marks_it_complete _
facts = FactBuilders()
    def test_pr9_order_placed_writes_the_header_unconditionally_and_marks_it_complete(
        facts: Any,
    ) -> None:
        fields = stage_fields(delta_to_pipeline(project(facts.build("order.placed.v1")), "projector:x"))
        assert set(fields) >= HEADER_KEYS
        for key in HEADER_KEYS:
>           assert set(fields[key]) == {"$literal"}, f"{key} is conditional or unwrapped"
E           AssertionError: orderReference is conditional or unwrapped
E           assert {'$ifNull'} == {'$literal'}
E             
E             Extra items in the left set:
E             '$ifNull'
E             Extra items in the right set:
E             '$literal'
E             Use -v to get more diff
services/projector/tests/unit/test_delta_to_pipeline.py:250: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_delta_to_pipeline.py::test_pr9_order_placed_writes_the_header_unconditionally_and_marks_it_complete
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### D2-ifnull-events

L7 arm: remove the `$ifNull` guard of the `events` array operand.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `43f252147e85dc02`
- test(s): `services/projector/tests/unit/test_delta_to_pipeline.py::test_pr6_every_array_and_rank_operand_is_if_null_guarded`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.05s`

```
F
=================================== FAILURES ===================================
___________ test_pr6_every_array_and_rank_operand_is_if_null_guarded ___________
facts = FactBuilders()
    def test_pr6_every_array_and_rank_operand_is_if_null_guarded(facts: Any) -> None:
        fields = stage_fields(
            delta_to_pipeline(project(facts.build("order.confirmed.v1")), "projector:x")
        )
        keys_input = fields["processedEventKeys"]["$sortArray"]["input"]["$setUnion"]
        assert keys_input[0] == {"$ifNull": ["$processedEventKeys", []]}
        events_input = fields["events"]["$let"]["vars"]["all"]["$concatArrays"]
>       assert events_input[0] == {"$ifNull": ["$events", []]}
E       AssertionError: assert '$events' == {'$ifNull': ['$events', []]}
services/projector/tests/unit/test_delta_to_pipeline.py:169: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_delta_to_pipeline.py::test_pr6_every_array_and_rank_operand_is_if_null_guarded
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### D2-ifnull-keys

L7 arm: remove the `$ifNull` guard of the `processedEventKeys` array operand.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `7a6ebce2865135b4`
- test(s): `services/projector/tests/unit/test_delta_to_pipeline.py::test_pr6_every_array_and_rank_operand_is_if_null_guarded`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.05s`

```
F
=================================== FAILURES ===================================
___________ test_pr6_every_array_and_rank_operand_is_if_null_guarded ___________
facts = FactBuilders()
    def test_pr6_every_array_and_rank_operand_is_if_null_guarded(facts: Any) -> None:
        fields = stage_fields(
            delta_to_pipeline(project(facts.build("order.confirmed.v1")), "projector:x")
        )
        keys_input = fields["processedEventKeys"]["$sortArray"]["input"]["$setUnion"]
>       assert keys_input[0] == {"$ifNull": ["$processedEventKeys", []]}
E       AssertionError: assert '$processedEventKeys' == {'$ifNull': ['$processedEventKeys', []]}
services/projector/tests/unit/test_delta_to_pipeline.py:167: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_delta_to_pipeline.py::test_pr6_every_array_and_rank_operand_is_if_null_guarded
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### D2-ifnull-rank

L7 arm: remove the `$ifNull` guard of the rank operand (a missing `statusRank` compares as null, below every number).

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `296e1c5d7b1020ee`
- test(s): `services/projector/tests/unit/test_delta_to_pipeline.py::test_pr6_every_array_and_rank_operand_is_if_null_guarded`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.05s`

```
F
=================================== FAILURES ===================================
___________ test_pr6_every_array_and_rank_operand_is_if_null_guarded ___________
facts = FactBuilders()
    def test_pr6_every_array_and_rank_operand_is_if_null_guarded(facts: Any) -> None:
        fields = stage_fields(
            delta_to_pipeline(project(facts.build("order.confirmed.v1")), "projector:x")
        )
        keys_input = fields["processedEventKeys"]["$sortArray"]["input"]["$setUnion"]
        assert keys_input[0] == {"$ifNull": ["$processedEventKeys", []]}
        events_input = fields["events"]["$let"]["vars"]["all"]["$concatArrays"]
        assert events_input[0] == {"$ifNull": ["$events", []]}
        rank_guard = {"$ifNull": ["$statusRank", 0]}
>       assert fields["statusRank"]["$max"][0] == rank_guard
E       AssertionError: assert '$statusRank' == {'$ifNull': ['$statusRank', 0]}
services/projector/tests/unit/test_delta_to_pipeline.py:171: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_delta_to_pipeline.py::test_pr6_every_array_and_rank_operand_is_if_null_guarded
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### D2-split-stage

Mutation: split the stage in two.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `15ad5c6c5f017108`
- test(s): `services/projector/tests/unit/test_delta_to_pipeline.py::test_pr6_the_pipeline_is_exactly_one_set_stage`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.05s`

```
F
=================================== FAILURES ===================================
________________ test_pr6_the_pipeline_is_exactly_one_set_stage ________________
facts = FactBuilders()
    def test_pr6_the_pipeline_is_exactly_one_set_stage(facts: Any) -> None:
        for event_type in ("order.placed.v1", "stock.released.v1", "order.cancelled.v1"):
            pipeline = delta_to_pipeline(project(facts.build(event_type)), "projector:x")
>           assert len(pipeline) == 1
E           AssertionError: assert 2 == 1
E            +  where 2 = len([{'$set': {'processedEventKeys': {'$sortArray': {'input': {'$setUnion': [...]}, 'sortBy': 1}}, 'events': {'$let': {'va...n', {'$literal': None}]}, 'updatedAt': {'$max': [{'$ifNull': [...]}, {'$literal': '2026-03-02T04:12:24.101Z'}]}, ...}}])
services/projector/tests/unit/test_delta_to_pipeline.py:107: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_delta_to_pipeline.py::test_pr6_the_pipeline_is_exactly_one_set_stage
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### D2-unwrap-entry

Mutation: unwrap the entry (`[entry]` instead of `[L(entry)]`).

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `fbeb2ff32cbf5b83`
- test(s): `services/projector/tests/unit/test_delta_to_pipeline.py::test_pr47_every_fact_value_in_the_pipeline_is_literal_wrapped`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.05s`

```
F
=================================== FAILURES ===================================
________ test_pr47_every_fact_value_in_the_pipeline_is_literal_wrapped _________
    def test_pr47_every_fact_value_in_the_pipeline_is_literal_wrapped() -> None:
        pipeline = delta_to_pipeline(sentinel_delta(), KEY)
>       assert unwrapped_sentinels(pipeline) == [], "a fact value sits outside a $literal"
E       AssertionError: a fact value sits outside a $literal
E       assert ['$SENTINEL_e...TINEL_x', ...] == []
E         
E         Left contains 8 more items, first extra item: '$SENTINEL_event_id'
E         Use -v to get more diff
services/projector/tests/unit/test_delta_to_pipeline.py:113: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_delta_to_pipeline.py::test_pr47_every_fact_value_in_the_pipeline_is_literal_wrapped
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.11s
```

#### D2-unwrap-updated-at

Mutation: unwrap `updatedAt`'s incoming instant.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `3049726e06e6c93f`
- test(s): `services/projector/tests/unit/test_delta_to_pipeline.py::test_pr47_every_fact_value_in_the_pipeline_is_literal_wrapped`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
F
=================================== FAILURES ===================================
________ test_pr47_every_fact_value_in_the_pipeline_is_literal_wrapped _________
    def test_pr47_every_fact_value_in_the_pipeline_is_literal_wrapped() -> None:
        pipeline = delta_to_pipeline(sentinel_delta(), KEY)
>       assert unwrapped_sentinels(pipeline) == [], "a fact value sits outside a $literal"
E       AssertionError: a fact value sits outside a $literal
E       assert ['2031-04-05T06:07:08.901Z'] == []
E         
E         Left contains one more item: '2031-04-05T06:07:08.901Z'
E         Use -v to get more diff
services/projector/tests/unit/test_delta_to_pipeline.py:113: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_delta_to_pipeline.py::test_pr47_every_fact_value_in_the_pipeline_is_literal_wrapped
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### D3-migration-own-copy

Mutation: give the migration its own copy of the ordering.

- file `services/projector/src/otc_projector/infrastructure/persistence/timeline_order_migration.py` sha256 before `a3623a4ceda72b75` after mutation `5ea87d315e5cdf1c`
- test(s): `services/projector/tests/unit/test_timeline_order_expression.py::test_pr10_the_apply_and_the_migration_call_the_same_function`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.02s`

```
F
=================================== FAILURES ===================================
_________ test_pr10_the_apply_and_the_migration_call_the_same_function _________
    def test_pr10_the_apply_and_the_migration_call_the_same_function() -> None:
        """Both modules reference `timeline_order_expression`; neither carries a copy of the ordering.
        The apply legitimately holds ONE `$sortArray` of its own (the dedup keys); what no module but
        `timeline_order.py` may hold is the causal ordering: the depth field, the `$reduce` fixpoint, or
        a sort by `occurredAt`.
        """
        sources = {
            name: (INFRA / "persistence" / f"{name}.py").read_text(encoding="utf-8")
            for name in ("delta_to_pipeline", "timeline_order_migration")
        }
        for name, source in sources.items():
>           assert "timeline_order_expression(" in source, f"{name} does not call the shared expression"
E           AssertionError: timeline_order_migration does not call the shared expression
E           assert 'timeline_order_expression(' in '"""Bring every document to the current timeline-order version before consuming (`PR32`, `PR35`).\n\n* Selected by `{t...onId": without_edge},\n    )\n    return MigrationResult(migrated=migrated, still_without_causation_id=without_edge)\n'
services/projector/tests/unit/test_timeline_order_expression.py:54: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_timeline_order_expression.py::test_pr10_the_apply_and_the_migration_call_the_same_function
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.06s
```

#### D3-remove-unsetfield

Mutation: remove the `$unsetField`.

- file `services/projector/src/otc_projector/infrastructure/persistence/timeline_order.py` sha256 before `9e266433d4437cff` after mutation `63d5299523fca437`
- test(s): `services/projector/tests/unit/test_timeline_order_expression.py::test_pr10_the_events_stage_sorts_by_occurred_at_depth_event_id_and_discards_the_depth`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.02s`

```
F
=================================== FAILURES ===================================
_ test_pr10_the_events_stage_sorts_by_occurred_at_depth_event_id_and_discards_the_depth _
    def test_pr10_the_events_stage_sorts_by_occurred_at_depth_event_id_and_discards_the_depth() -> None:
        expression = timeline_order_expression("$events")
        sort_by = find_key(expression, "$sortArray")
        assert len(sort_by) == 1, "the expression must sort the entries exactly once"
        assert list(sort_by[0]["sortBy"]) == ["occurredAt", "__depth", "eventId"], (
            "dict key order IS the sort order: it must be occurredAt, __depth, eventId"
        )
        assert all(direction == 1 for direction in sort_by[0]["sortBy"].values())
        unsets = find_key(expression, "$unsetField")
>       assert len(unsets) == 1, "the depth must be discarded by exactly one $unsetField"
E       AssertionError: the depth must be discarded by exactly one $unsetField
E       assert 0 == 1
E        +  where 0 = len([])
services/projector/tests/unit/test_timeline_order_expression.py:34: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_timeline_order_expression.py::test_pr10_the_events_stage_sorts_by_occurred_at_depth_event_id_and_discards_the_depth
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.07s
```

#### D3-reorder-sortby

Mutation: reorder `sortBy` to `{occurredAt, eventId, __depth}`.

- file `services/projector/src/otc_projector/infrastructure/persistence/timeline_order.py` sha256 before `9e266433d4437cff` after mutation `baac6bb3f65668b4`
- test(s): `services/projector/tests/unit/test_timeline_order_expression.py::test_pr10_the_events_stage_sorts_by_occurred_at_depth_event_id_and_discards_the_depth`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.02s`

```
F
=================================== FAILURES ===================================
_ test_pr10_the_events_stage_sorts_by_occurred_at_depth_event_id_and_discards_the_depth _
    def test_pr10_the_events_stage_sorts_by_occurred_at_depth_event_id_and_discards_the_depth() -> None:
        expression = timeline_order_expression("$events")
        sort_by = find_key(expression, "$sortArray")
        assert len(sort_by) == 1
>       assert list(sort_by[0]["sortBy"]) == ["occurredAt", "__depth", "eventId"], (
            "dict key order IS the sort order: it must be occurredAt, __depth, eventId"
        )
E       AssertionError: dict key order IS the sort order: it must be occurredAt, __depth, eventId
E       assert ['occurredAt'...d', '__depth'] == ['occurredAt'...h', 'eventId']
E         
E         At index 1 diff: 'eventId' != '__depth'
E         Use -v to get more diff
services/projector/tests/unit/test_timeline_order_expression.py:29: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_timeline_order_expression.py::test_pr10_the_events_stage_sorts_by_occurred_at_depth_event_id_and_discards_the_depth
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.06s
```

#### D4-isoformat

Mutation: render an instant with `isoformat()`.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `a91d9ed0ca191fba`
- test(s): `services/projector/tests/unit/test_document_rendering.py::test_pr41_ids_are_lowercase_hyphenated_strings_instants_are_mmmz_strings_and_integers_keep_their_python_value`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
F
=================================== FAILURES ===================================
_ test_pr41_ids_are_lowercase_hyphenated_strings_instants_are_mmmz_strings_and_integers_keep_their_python_value _
facts = FactBuilders()
    def test_pr41_ids_are_lowercase_hyphenated_strings_instants_are_mmmz_strings_and_integers_keep_their_python_value(  # noqa: E501
        facts: Any,
    ) -> None:
        event = facts.build("order.cancelled.v1")
        delta = project(event)
        pipeline = delta_to_pipeline(delta, "projector:" + delta.entry.event_id)
        entry = entry_of(pipeline)
        for field in ("eventId", "causationId"):
            assert isinstance(entry[field], str), field
            assert UUID_PATTERN.match(entry[field]), f"{field} is not a lowercase hyphenated id"
>       assert INSTANT_PATTERN.match(entry["occurredAt"])
E       AssertionError: assert None
E        +  where None = <built-in method match of re.Pattern object at 0x71ab41527870>('2026-03-02T16:12:36.113000+00:00')
E        +    where <built-in method match of re.Pattern object at 0x71ab41527870> = re.compile('^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$').match
services/projector/tests/unit/test_document_rendering.py:54: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_document_rendering.py::test_pr41_ids_are_lowercase_hyphenated_strings_instants_are_mmmz_strings_and_integers_keep_their_python_value
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.08s
```

#### D4-snake-case-detail

Mutation: build `detail` without aliases (snake_case keys).

- file `services/projector/src/otc_projector/application/summaries.py` sha256 before `84a2089b8084511b` after mutation `c7d81626f673f660`
- test(s): `services/projector/tests/unit/test_document_rendering.py::test_pr41_detail_from_compensation_steps_carries_camel_case_keys_and_mmmz_instants`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
F
=================================== FAILURES ===================================
_ test_pr41_detail_from_compensation_steps_carries_camel_case_keys_and_mmmz_instants _
facts = FactBuilders()
    def test_pr41_detail_from_compensation_steps_carries_camel_case_keys_and_mmmz_instants(
        facts: Any,
    ) -> None:
        steps = [
            {
                "step": "stock_released",
                "event_id": "44444444-4444-4444-8444-444444444444",
                "event_type": "stock.released.v1",
                "occurred_at": "2026-03-11T12:00:00.123Z",
            }
        ]
        event = facts.build("order.cancelled.v1", payload={"compensation_steps": steps})
        delta = project(event)
        assert delta.entry.detail is not None
        step = delta.entry.detail["compensationSteps"][0]  # type: ignore[index]
>       assert set(step) == {"step", "eventId", "eventType", "occurredAt"}, "snake_case leaked"
E       AssertionError: snake_case leaked
E       assert {'event_id', ...d_at', 'step'} == {'eventId', '...edAt', 'step'}
E         
E         Extra items in the left set:
E         'event_type'
E         'event_id'
E         'occurred_at'
E         Extra items in the right set:
E         'eventType'...
E         
E         ...Full output truncated (3 lines hidden), use '-vv' to show
services/projector/tests/unit/test_document_rendering.py:90: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_document_rendering.py::test_pr41_detail_from_compensation_steps_carries_camel_case_keys_and_mmmz_instants
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### D4-uuid-id

Mutation: write a native `UUID` object for `_id`.

- file `services/projector/src/otc_projector/infrastructure/persistence/read_model_document.py` sha256 before `9de057e71dce8149` after mutation `2420efa9a9f6ab45`
- test(s): `services/projector/tests/unit/test_document_rendering.py::test_pr41_ids_are_lowercase_hyphenated_strings_instants_are_mmmz_strings_and_integers_keep_their_python_value`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
F
=================================== FAILURES ===================================
_ test_pr41_ids_are_lowercase_hyphenated_strings_instants_are_mmmz_strings_and_integers_keep_their_python_value _
facts = FactBuilders()
    def test_pr41_ids_are_lowercase_hyphenated_strings_instants_are_mmmz_strings_and_integers_keep_their_python_value(  # noqa: E501
        facts: Any,
    ) -> None:
        event = facts.build("order.cancelled.v1")
        delta = project(event)
        pipeline = delta_to_pipeline(delta, "projector:" + delta.entry.event_id)
        entry = entry_of(pipeline)
        for field in ("eventId", "causationId"):
            assert isinstance(entry[field], str), field
            assert UUID_PATTERN.match(entry[field]), f"{field} is not a lowercase hyphenated id"
        assert INSTANT_PATTERN.match(entry["occurredAt"])
        holder = placeholder(delta.order_id, entry["occurredAt"])
        for field in ("_id", "orderId"):
            value = holder[field]
>           assert isinstance(value, str), field
E           AssertionError: _id
E           assert False
E            +  where False = isinstance(UUID('00000517-0517-4000-8000-0000009d7279'), str)
services/projector/tests/unit/test_document_rendering.py:58: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_document_rendering.py::test_pr41_ids_are_lowercase_hyphenated_strings_instants_are_mmmz_strings_and_integers_keep_their_python_value
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.08s
```

#### E2-drop-upsert

Mutation: drop `upsert=True` from the first operation.

- file `services/projector/src/otc_projector/infrastructure/persistence/mongo_read_model_writer.py` sha256 before `1be883059cbd596d` after mutation `7b391f664ee8d948`
- test(s): `services/projector/tests/unit/test_mongo_read_model_writer.py::test_pr6_pr42_the_arguments_the_driver_received_are_upsert_true_and_return_document_after`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.05s`

```
F
=================================== FAILURES ===================================
_ test_pr6_pr42_the_arguments_the_driver_received_are_upsert_true_and_return_document_after _
facts = FactBuilders()
    async def test_pr6_pr42_the_arguments_the_driver_received_are_upsert_true_and_return_document_after(
        facts: Any,
    ) -> None:
        fake = FakeCollection()
        delta = project(facts.build("order.confirmed.v1"))
        await writer_over(fake).apply(delta, after_applied=Callback())
        _, _, update_options = fake.updates[0]
>       assert update_options == {"upsert": True}, "the first operation must upsert"
E       AssertionError: the first operation must upsert
E       assert {} == {'upsert': True}
E         
E         Right contains 1 more item:
E         {'upsert': True}
E         Use -v to get more diff
services/projector/tests/unit/test_mongo_read_model_writer.py:145: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_mongo_read_model_writer.py::test_pr6_pr42_the_arguments_the_driver_received_are_upsert_true_and_return_document_after
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### E2-retry-phase-2

Mutation: retry Phase 2.

- file `services/projector/src/otc_projector/infrastructure/messaging/idempotent_consumer.py` sha256 before `fc9f5b38c78db010` after mutation `41c742bcfa2c3164`
- test(s): `services/projector/tests/unit/test_mongo_read_model_writer.py::test_pr7_a_duplicate_key_in_the_second_operation_propagates_unretried`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.05s`

```
F
=================================== FAILURES ===================================
____ test_pr7_a_duplicate_key_in_the_second_operation_propagates_unretried _____
facts = FactBuilders()
    async def test_pr7_a_duplicate_key_in_the_second_operation_propagates_unretried(facts: Any) -> None:
        fake = FakeCollection()
        fake.apply_error = ID_CONFLICT
        callback = Callback()
        with pytest.raises(DuplicateKeyError):
            await writer_over(fake).apply(
                project(facts.build("order.placed.v1")), after_applied=callback
            )
        assert len(fake.updates) == 1, "the first operation was repeated"
>       assert len(fake.applies) == 1, "the second operation was retried"
E       AssertionError: the second operation was retried
E       assert 2 == 1
E        +  where 2 = len([({'_id': '00000067-0067-4000-8000-0000000c7229', 'processedEventKeys': {'$ne': 'projector:00000065-0065-4000-8000-000...vents': {'$let': {...}}, 'statusRank': {'$max': [...]}, 'status': {'$cond': [...]}, ...}}], {'return_document': True})])
E        +    where [({'_id': '00000067-0067-4000-8000-0000000c7229', 'processedEventKeys': {'$ne': 'projector:00000065-0065-4000-8000-000...vents': {'$let': {...}}, 'statusRank': {'$max': [...]}, 'status': {'$cond': [...]}, ...}}], {'return_document': True})] = <services.projector.tests.unit.test_mongo_read_model_writer.FakeCollection object at 0x758ada4a2270>.applies
services/projector/tests/unit/test_mongo_read_model_writer.py:134: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_mongo_read_model_writer.py::test_pr7_a_duplicate_key_in_the_second_operation_propagates_unretried
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### E2-retry-twice

Mutation: retry Phase 1 twice.

- file `services/projector/src/otc_projector/infrastructure/persistence/mongo_read_model_writer.py` sha256 before `1be883059cbd596d` after mutation `9246d9a69db8ca46`
- test(s): `services/projector/tests/unit/test_mongo_read_model_writer.py::test_pr7_a_second_id_duplicate_key_propagates_after_exactly_one_retry`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.06s`

```
F
=================================== FAILURES ===================================
____ test_pr7_a_second_id_duplicate_key_propagates_after_exactly_one_retry _____
facts = FactBuilders()
    async def test_pr7_a_second_id_duplicate_key_propagates_after_exactly_one_retry(facts: Any) -> None:
        fake = FakeCollection()
        fake.update_errors = [ID_CONFLICT, ID_CONFLICT]
>       with pytest.raises(DuplicateKeyError):
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       Failed: DID NOT RAISE DuplicateKeyError
services/projector/tests/unit/test_mongo_read_model_writer.py:94: Failed
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_mongo_read_model_writer.py::test_pr7_a_second_id_duplicate_key_propagates_after_exactly_one_retry
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.11s
```

#### E3-find-one-before-phase-2

Mutation: insert a `find_one` before Phase 2.

- file `services/projector/src/otc_projector/infrastructure/persistence/mongo_read_model_writer.py` sha256 before `1be883059cbd596d` after mutation `bb3081b704e9474f`
- test(s): `services/projector/tests/integration/test_projection_write.py::test_pr6_applies_one_fact_in_exactly_one_update_and_one_find_and_modify_issuing_no_read`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 4.34s`

```
F
=================================== FAILURES ===================================
_ test_pr6_applies_one_fact_in_exactly_one_update_and_one_find_and_modify_issuing_no_read _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:35837'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_1b75174ce6a341069202b5be119356e2', uri='mongodb://otc_test:otc_test_password@localhost:35837/?authSource=admin')
facts = FactBuilders()
    async def test_pr6_applies_one_fact_in_exactly_one_update_and_one_find_and_modify_issuing_no_read(
        read_model: Any, facts: Any
    ) -> None:
        event = facts.build("order.placed.v1")
        read_model.log.clear()
        first = await read_model.apply(event)
        first_commands = read_model.log.against(COLLECTION)
        read_model.log.clear()
        redelivery = await read_model.apply(event)
        second_commands = read_model.log.against(COLLECTION)
        assert first.outcome is ProjectionOutcome.PROCESSED
        assert redelivery.outcome is ProjectionOutcome.DUPLICATE
>       assert first_commands == ["update", "findAndModify"], (
            f"the first delivery issued {first_commands}"
        )
E       AssertionError: the first delivery issued ['update', 'find', 'findAndModify']
E       assert ['update', 'f...indAndModify'] == ['update', 'findAndModify']
E         
E         At index 1 diff: 'find' != 'findAndModify'
E         Left contains one more item: 'findAndModify'
E         Use -v to get more diff
services/projector/tests/integration/test_projection_write.py:44: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_projection_write.py::test_pr6_applies_one_fact_in_exactly_one_update_and_one_find_and_modify_issuing_no_read
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.81s
```

#### E4-bare-event-id

Mutation: key on the bare `eventId`.

- file `services/projector/src/otc_projector/infrastructure/messaging/idempotent_consumer.py` sha256 before `fc9f5b38c78db010` after mutation `832537cd209f0f0c`
- test(s): `services/projector/tests/integration/test_idempotent_consumer_conformance.py::test_pr25_case_5_the_same_event_under_a_different_consumer_name_runs`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.75s`

```
F
=================================== FAILURES ===================================
_____ test_pr25_case_5_the_same_event_under_a_different_consumer_name_runs _____
fresh_mongo_database = FreshMongoDatabase(name='otc_test_19e9842ca0c14a12bcf1198c6064c4bf', uri='mongodb://otc_test:otc_test_password@localhost:35875/?authSource=admin')
    async def test_pr25_case_5_the_same_event_under_a_different_consumer_name_runs(
        fresh_mongo_database: Any,
    ) -> None:
        client, consumer = await with_scope(fresh_mongo_database)
        try:
            counter = Counter()
            event = uuid.uuid4()
            assert await run(consumer, event, counter) is ConsumptionOutcome.PROCESSED
            other = await run(consumer, event, counter, ConsumerName.NOTIFICATIONS)
>           assert other is ConsumptionOutcome.PROCESSED, (
                "case 5: the same eventId under another consumer name was treated as a duplicate"
            )
E           AssertionError: case 5: the same eventId under another consumer name was treated as a duplicate
E           assert <ConsumptionOutcome.DUPLICATE: 'duplicate'> is <ConsumptionOutcome.PROCESSED: 'processed'>
E            +  where <ConsumptionOutcome.PROCESSED: 'processed'> = ConsumptionOutcome.PROCESSED
services/projector/tests/integration/test_idempotent_consumer_conformance.py:167: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_idempotent_consumer_conformance.py::test_pr25_case_5_the_same_event_under_a_different_consumer_name_runs
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.88s
```

#### E4-instance-set

Mutation: keep the dedup in an instance `set` instead of the filter.

- file `services/projector/src/otc_projector/infrastructure/messaging/idempotent_consumer.py` sha256 before `fc9f5b38c78db010` after mutation `a6468024af4f42e5`
- test(s): `services/projector/tests/integration/test_idempotent_consumer_conformance.py::test_pr25_case_3_a_fresh_instance_over_a_new_client_on_the_same_database_still_sees_it`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.80s`

```
F
=================================== FAILURES ===================================
_ test_pr25_case_3_a_fresh_instance_over_a_new_client_on_the_same_database_still_sees_it _
fresh_mongo_database = FreshMongoDatabase(name='otc_test_631a3275c95a40628ebc1cb1f5111293', uri='mongodb://otc_test:otc_test_password@localhost:35871/?authSource=admin')
    async def test_pr25_case_3_a_fresh_instance_over_a_new_client_on_the_same_database_still_sees_it(
        fresh_mongo_database: Any,
    ) -> None:
        first_client, first = await with_scope(fresh_mongo_database)
        second_client, second_collection = await collection_for(
            fresh_mongo_database.uri, fresh_mongo_database.name
        )
        try:
            counter = Counter()
            event = uuid.uuid4()
            assert await run(first, event, counter) is ConsumptionOutcome.PROCESSED
            second = IdempotentConsumer(second_collection)
            assert second is not first
            again = await run(second, event, counter)
>           assert again is ConsumptionOutcome.DUPLICATE, (
                "case 3: a fresh instance over a new client did not see the recorded key"
            )
E           AssertionError: case 3: a fresh instance over a new client did not see the recorded key
E           assert <ConsumptionOutcome.PROCESSED: 'processed'> is <ConsumptionOutcome.DUPLICATE: 'duplicate'>
E            +  where <ConsumptionOutcome.DUPLICATE: 'duplicate'> = ConsumptionOutcome.DUPLICATE
services/projector/tests/integration/test_idempotent_consumer_conformance.py:136: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_idempotent_consumer_conformance.py::test_pr25_case_3_a_fresh_instance_over_a_new_client_on_the_same_database_still_sees_it
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.81s
```

#### E5 — the subversion probe

Mutation: drop `"processedEventKeys": {"$ne": key}` from the variant's filter, banner untouched. sha256 prefix before `fc9f5b38c78db010`, after `b952769a4676c4b3`.

**Orders parity guard under the mutation (must stay GREEN: it is text, by design):**
```
...........................                                              [100%]
27 passed in 0.73s
```

**E4 (the conformance file) under the mutation (must FAIL, naming the cases):**
```
E           AssertionError: assert <ConsumptionOutcome.PROCESSED: 'processed'> is <ConsumptionOutcome.DUPLICATE: 'duplicate'>
E            +  where <ConsumptionOutcome.DUPLICATE: 'duplicate'> = ConsumptionOutcome.DUPLICATE
E           AssertionError: case 3: a fresh instance over a new client did not see the recorded key
E           assert <ConsumptionOutcome.PROCESSED: 'processed'> is <ConsumptionOutcome.DUPLICATE: 'duplicate'>
E            +  where <ConsumptionOutcome.DUPLICATE: 'duplicate'> = ConsumptionOutcome.DUPLICATE
E           AssertionError: assert <ConsumptionOutcome.PROCESSED: 'processed'> is <ConsumptionOutcome.DUPLICATE: 'duplicate'>
E            +  where <ConsumptionOutcome.DUPLICATE: 'duplicate'> = ConsumptionOutcome.DUPLICATE
E               AssertionError: assert <ConsumptionOutcome.PROCESSED: 'processed'> is <ConsumptionOutcome.DUPLICATE: 'duplicate'>
E                +  where <ConsumptionOutcome.DUPLICATE: 'duplicate'> = ConsumptionOutcome.DUPLICATE
FAILED services/projector/tests/integration/test_idempotent_consumer_conformance.py::test_pr25_case_2_the_same_event_and_consumer_again_is_a_duplicate_and_work_does_not_run
FAILED services/projector/tests/integration/test_idempotent_consumer_conformance.py::test_pr25_case_3_a_fresh_instance_over_a_new_client_on_the_same_database_still_sees_it
FAILED services/projector/tests/integration/test_idempotent_consumer_conformance.py::test_pr25_case_5_the_same_event_under_a_different_consumer_name_runs
FAILED services/projector/tests/integration/test_idempotent_consumer_conformance.py::test_pr26_the_post_apply_callback_runs_once_on_processed_and_never_on_duplicate
4 failed, 3 passed in 4.14s
restored: cmp identical
```

#### E6-delete-retry

Mutation: delete the Phase-1 retry.

- file `services/projector/src/otc_projector/infrastructure/persistence/mongo_read_model_writer.py` sha256 before `1be883059cbd596d` after mutation `18562e36a234bf53`
- test(s): `services/projector/tests/integration/test_projection_concurrency.py::test_pr7_concurrent_first_facts_for_an_absent_order_end_in_one_document_holding_both`
- mutated run exit code: **0** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.40s`

```
.                                                                        [100%]
1 passed in 3.93s
```

#### E7-causation-first

Mutation: build entries with `causationId` first.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `8cfe0cf99f48b0b1`
- test(s): `services/projector/tests/integration/test_projection_write.py::test_pr41_element_names_order_and_bson_types_equal_the_seeds_document`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `2 passed in 3.95s`

```
F
=================================== FAILURES ===================================
___ test_pr41_element_names_order_and_bson_types_equal_the_seeds_document[0] ___
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:35847'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_9c33f2c88c3944109dbdea515fec20e2', uri='mongodb://otc_test:otc_test_password@localhost:35847/?authSource=admin')
saga_facts = <function facts_of at 0x7ebb6e03a610>, saga_index = 0
    @pytest.mark.parametrize("saga_index", [0, 5])
    async def test_pr41_element_names_order_and_bson_types_equal_the_seeds_document(
        read_model: Any, saga_facts: Any, saga_index: int
    ) -> None:
        saga = SAGAS[saga_index]
        for event in saga_facts(saga):
            await read_model.apply(event)
        projected = elements(await read_model.raw(saga.order_id))
        seeded = elements(await seeded_raw(read_model, saga_index))
        assert list(projected) == list(seeded), "top-level element sequence differs from the seed's"
        for name in ("retailer", "company", "totals", "references"):
            assert list(projected[name]) == list(seeded[name]), f"{name}: element sequence differs"
        assert list(projected["items"][0]) == list(seeded["items"][0]), "item element sequence differs"
        assert len(projected["events"]) == len(seeded["events"])
        for index, (mine, theirs) in enumerate(zip(projected["events"], seeded["events"], strict=True)):
            # `detail` is excluded exactly as PR44 excludes it: the seed's is a hand-written subset (its
            # `stock.released.v1` entry has none at all), the projector's is PR16's builder.
            mine_keys = [key for key in mine if key != "detail"]
            theirs_keys = [key for key in theirs if key != "detail"]
>           assert mine_keys == theirs_keys, f"events[{index}]: element sequence differs"
E           AssertionError: events[0]: element sequence differs
E           assert ['causationId...t', 'summary'] == ['eventId', '...'causationId']
E             
E             At index 0 diff: 'causationId' != 'eventId'
E             Use -v to get more diff
services/projector/tests/integration/test_projection_write.py:98: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_projection_write.py::test_pr41_element_names_order_and_bson_types_equal_the_seeds_document[0]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.97s
```

#### E7-omit-cancellation-reason

Mutation: omit `cancellationReason` from the placeholder (it is then appended at the end of the document by the first pipeline `$set`).

- file `services/projector/src/otc_projector/infrastructure/persistence/read_model_document.py` sha256 before `9de057e71dce8149` after mutation `84c0ff99216d8eec`
- test(s): `services/projector/tests/integration/test_projection_write.py::test_pr41_element_names_order_and_bson_types_equal_the_seeds_document`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `2 passed in 3.92s`

```
F
=================================== FAILURES ===================================
___ test_pr41_element_names_order_and_bson_types_equal_the_seeds_document[0] ___
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:35841'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_b80f77949ced4f28a580f7e583db60bc', uri='mongodb://otc_test:otc_test_password@localhost:35841/?authSource=admin')
saga_facts = <function facts_of at 0x71340d5a2560>, saga_index = 0
    @pytest.mark.parametrize("saga_index", [0, 5])
    async def test_pr41_element_names_order_and_bson_types_equal_the_seeds_document(
        read_model: Any, saga_facts: Any, saga_index: int
    ) -> None:
        saga = SAGAS[saga_index]
        for event in saga_facts(saga):
            await read_model.apply(event)
        projected = elements(await read_model.raw(saga.order_id))
        seeded = elements(await seeded_raw(read_model, saga_index))
>       assert list(projected) == list(seeded), "top-level element sequence differs from the seed's"
E       AssertionError: top-level element sequence differs from the seed's
E       assert ['_id', 'comp... 'items', ...] == ['_id', 'canc...omplete', ...]
E         
E         At index 1 diff: 'company' != 'cancellationReason'
E         Use -v to get more diff
services/projector/tests/integration/test_projection_write.py:88: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_projection_write.py::test_pr41_element_names_order_and_bson_types_equal_the_seeds_document[0]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.94s
```

#### E8-unwrap-entry

Mutation (S7): remove the `$literal` around the entry.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `fbeb2ff32cbf5b83`
- test(s): `services/projector/tests/integration/test_projection_write.py::test_pr47_dollar_prefixed_note_and_last_error_are_stored_verbatim`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.87s`

```
                _error.update({"errorLabels": _labels})
            _raise_write_concern_error(_error)
        if response["ok"]:
            return
        details = response
        errmsg = details["errmsg"]
        code = details.get("code")
        # For allowable errors, only check for error messages when the code is not
        # included.
        if allowable_errors:
            if code is not None:
                if code in allowable_errors:
                    return
            elif errmsg in allowable_errors:
                return
        # Server is "not primary" or "recovering"
        if code is not None:
            if code in _NOT_PRIMARY_CODES:
                raise NotPrimaryError(errmsg, response)
        elif HelloCompat.LEGACY_ERROR in errmsg or "node is recovering" in errmsg:
            raise NotPrimaryError(errmsg, response)
        # Other errors
        # findAndModify with upsert can raise duplicate key error
        if code in (11000, 11001, 12582):
            raise DuplicateKeyError(errmsg, code, response, max_wire_version)
        elif code == 50:
            # Append timeout details to MaxTimeMSExpired responses.
            if pool_opts:
                timeout_details = _get_timeout_details(pool_opts)
                errmsg += format_timeout_details(timeout_details)
            raise ExecutionTimeout(errmsg, code, response, max_wire_version)
        elif code == 43:
            raise CursorNotFound(errmsg, code, response, max_wire_version)
>       raise OperationFailure(errmsg, code, response, max_wire_version)
E       pymongo.errors.OperationFailure: Invalid $set :: caused by :: 'NOW x' contains an invalid character for a variable name: ' ', full error: {'ok': 0.0, 'errmsg': "Invalid $set :: caused by :: 'NOW x' contains an invalid character for a variable name: ' '", 'code': 9, 'codeName': 'FailedToParse'}
.venv/lib/python3.14/site-packages/pymongo/helpers_shared.py:327: OperationFailure
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_projection_write.py::test_pr47_dollar_prefixed_note_and_last_error_are_stored_verbatim
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 4.10s
```

#### E8-unwrap-entry-substitution

Mutation (S7, substitution half): remove the `$literal` around the entry; the note `$status` is applied alone.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `fbeb2ff32cbf5b83`
- test(s): `services/projector/tests/integration/test_projection_write.py::test_pr47_a_dollar_status_note_is_stored_as_text_not_evaluated_as_the_documents_status`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.80s`

```
F
=================================== FAILURES ===================================
_ test_pr47_a_dollar_status_note_is_stored_as_text_not_evaluated_as_the_documents_status _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:35855'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_fb623458f1a24362a656c1c4f4d2d647', uri='mongodb://otc_test:otc_test_password@localhost:35855/?authSource=admin')
facts = FactBuilders()
    async def test_pr47_a_dollar_status_note_is_stored_as_text_not_evaluated_as_the_documents_status(
        read_model: Any, facts: Any
    ) -> None:
        """Alone, so that the unwrapped failure is the SUBSTITUTION and not the poison record."""
        event = facts.build(
            "order.cancelled.v1",
            payload={"cancellation_reason": "operator_cancelled", "note": "$status"},
        )
        await read_model.apply(event)
        (entry,) = (await read_model.document(event.correlation_id))["events"]
>       assert entry["detail"]["note"] == "$status", (
            f"the note was evaluated by the server: stored {entry['detail']['note']!r}"
        )
E       AssertionError: the note was evaluated by the server: stored 'placed'
E       assert 'placed' == '$status'
E         
E         - $status
E         + placed
services/projector/tests/integration/test_projection_write.py:165: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_projection_write.py::test_pr47_a_dollar_status_note_is_stored_as_text_not_evaluated_as_the_documents_status
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.84s
```

#### F2-P1

Mutation (P1): the instrument stops reporting a package missing from the registry.

- file `services/orders/tests/unit/test_idempotent_consumer_parity.py` sha256 before `1025c98ec33727d7` after mutation `4a8f4102c493a2e6`
- test(s): `services/orders/tests/unit/test_idempotent_consumer_parity.py::test_pr48_p1_sentinel_a_package_on_disk_missing_from_the_registry_is_reported`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.06s`

```
F
=================================== FAILURES ===================================
_ test_pr48_p1_sentinel_a_package_on_disk_missing_from_the_registry_is_reported _
tmp_path = PosixPath('/tmp/pytest-of-juanpabloperez/pytest-767/test_pr48_p1_sentinel_a_packag0')
    def test_pr48_p1_sentinel_a_package_on_disk_missing_from_the_registry_is_reported(
        tmp_path: Path,
    ) -> None:
        build_tree(tmp_path, {"ledgerless": {"infrastructure/x.py": "VALUE = 1\n"}})
>       assert registry_problems(tmp_path, IDEMPOTENCY_MODE) == [
            "ledgerless: a service package on disk is missing from IDEMPOTENCY_MODE",
            *[
                f"{name}: registered in IDEMPOTENCY_MODE but there is no such package"
                for name in sorted(IDEMPOTENCY_MODE)
            ],
        ]
E       AssertionError: assert ['billing: re...package', ...] == ['ledgerless:...package', ...]
E         
E         At index 0 diff: 'billing: registered in IDEMPOTENCY_MODE but there is no such package' != 'ledgerless: a service package on disk is missing from IDEMPOTENCY_MODE'
E         Right contains one more item: 'seed: registered in IDEMPOTENCY_MODE but there is no such package'
E         Use -v to get more diff
services/orders/tests/unit/test_idempotent_consumer_parity.py:545: AssertionError
=========================== short test summary info ============================
FAILED services/orders/tests/unit/test_idempotent_consumer_parity.py::test_pr48_p1_sentinel_a_package_on_disk_missing_from_the_registry_is_reported
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.11s
```

#### F2-P2

Mutation (P2): the instrument stops reporting a stale registry entry.

- file `services/orders/tests/unit/test_idempotent_consumer_parity.py` sha256 before `1025c98ec33727d7` after mutation `480b941a3084c2fa`
- test(s): `services/orders/tests/unit/test_idempotent_consumer_parity.py::test_pr48_p2_sentinel_a_registry_entry_with_no_package_is_reported`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.06s`

```
F
=================================== FAILURES ===================================
______ test_pr48_p2_sentinel_a_registry_entry_with_no_package_is_reported ______
tmp_path = PosixPath('/tmp/pytest-of-juanpabloperez/pytest-769/test_pr48_p2_sentinel_a_regist0')
    def test_pr48_p2_sentinel_a_registry_entry_with_no_package_is_reported(tmp_path: Path) -> None:
        build_control_tree(tmp_path)
        modes = {
            "orders": RELATIONAL_COPY,
            "projector": DOCUMENTED_VARIANT,
            "seed": NO_CONSUMER,
            "ghost": NO_CONSUMER,
        }
>       assert registry_problems(tmp_path, modes) == [
            "ghost: registered in IDEMPOTENCY_MODE but there is no such package"
        ]
E       AssertionError: assert [] == ['ghost: regi...such package']
E         
E         Right contains one more item: 'ghost: registered in IDEMPOTENCY_MODE but there is no such package'
E         Use -v to get more diff
services/orders/tests/unit/test_idempotent_consumer_parity.py:562: AssertionError
=========================== short test summary info ============================
FAILED services/orders/tests/unit/test_idempotent_consumer_parity.py::test_pr48_p2_sentinel_a_registry_entry_with_no_package_is_reported
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.11s
```

#### F2-P3

Mutation (P3): the no-consumer scan looks for a name no module contains.

- file `services/orders/tests/unit/test_idempotent_consumer_parity.py` sha256 before `1025c98ec33727d7` after mutation `f675c6cd1cc6c46f`
- test(s): `services/orders/tests/unit/test_idempotent_consumer_parity.py::test_pr48_p3_sentinel_a_no_consumer_that_references_aiokafkaconsumer_is_reported`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.06s`

```
F
=================================== FAILURES ===================================
_ test_pr48_p3_sentinel_a_no_consumer_that_references_aiokafkaconsumer_is_reported _
tmp_path = PosixPath('/tmp/pytest-of-juanpabloperez/pytest-771/test_pr48_p3_sentinel_a_no_con0')
    def test_pr48_p3_sentinel_a_no_consumer_that_references_aiokafkaconsumer_is_reported(
        tmp_path: Path,
    ) -> None:
        build_tree(
            tmp_path, {"seed": {"infrastructure/x.py": "from aiokafka import AIOKafkaConsumer\n"}}
        )
>       assert mode_problems(tmp_path, {"seed": NO_CONSUMER}) == [
            "seed: registered no-consumer but x.py references AIOKafkaConsumer"
        ]
E       AssertionError: assert [] == ['seed: regis...afkaConsumer']
E         
E         Right contains one more item: 'seed: registered no-consumer but x.py references AIOKafkaConsumer'
E         Use -v to get more diff
services/orders/tests/unit/test_idempotent_consumer_parity.py:572: AssertionError
=========================== short test summary info ============================
FAILED services/orders/tests/unit/test_idempotent_consumer_parity.py::test_pr48_p3_sentinel_a_no_consumer_that_references_aiokafkaconsumer_is_reported
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### F2-P4

Mutation (P4): a variant with no consumer file is skipped again (today the OI12 opt-out).

- file `services/orders/tests/unit/test_idempotent_consumer_parity.py` sha256 before `1025c98ec33727d7` after mutation `9907aaf2eff90d5c`
- test(s): `services/orders/tests/unit/test_idempotent_consumer_parity.py::test_pr48_p4_sentinel_a_variant_whose_consumer_file_is_renamed_now_fails`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.06s`

```
F
=================================== FAILURES ===================================
___ test_pr48_p4_sentinel_a_variant_whose_consumer_file_is_renamed_now_fails ___
tmp_path = PosixPath('/tmp/pytest-of-juanpabloperez/pytest-773/test_pr48_p4_sentinel_a_varian0')
    def test_pr48_p4_sentinel_a_variant_whose_consumer_file_is_renamed_now_fails(
        tmp_path: Path,
    ) -> None:
        """The OI12 opt-out: a variant that renames its file used to be examined by no case."""
        build_control_tree(tmp_path)
        modes = {"projector": DOCUMENTED_VARIANT}
        package = tmp_path / "services" / "projector" / "src" / "otc_projector"
        consumer_file(package).rename(consumer_file(package).with_name("renamed.py"))
        examined, problems = variant_problems(tmp_path, CANONICAL, modes)
        assert examined == ["otc_projector"]
>       assert len(problems) == 1
E       assert 0 == 1
E        +  where 0 = len([])
services/orders/tests/unit/test_idempotent_consumer_parity.py:586: AssertionError
=========================== short test summary info ============================
FAILED services/orders/tests/unit/test_idempotent_consumer_parity.py::test_pr48_p4_sentinel_a_variant_whose_consumer_file_is_renamed_now_fails
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### F2-P5

Mutation (P5): the conformance line is not checked for the file's existence.

- file `services/orders/tests/unit/test_idempotent_consumer_parity.py` sha256 before `1025c98ec33727d7` after mutation `1f9d87560fbde8c9`
- test(s): `services/orders/tests/unit/test_idempotent_consumer_parity.py::test_pr48_p5_sentinel_a_conformance_line_naming_a_missing_file_or_absent_is_reported`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.07s`

```
F
=================================== FAILURES ===================================
_ test_pr48_p5_sentinel_a_conformance_line_naming_a_missing_file_or_absent_is_reported _
tmp_path = PosixPath('/tmp/pytest-of-juanpabloperez/pytest-775/test_pr48_p5_sentinel_a_confor0')
    def test_pr48_p5_sentinel_a_conformance_line_naming_a_missing_file_or_absent_is_reported(
        tmp_path: Path,
    ) -> None:
        build_control_tree(tmp_path)
        modes = {"projector": DOCUMENTED_VARIANT}
        package = tmp_path / "services" / "projector" / "src" / "otc_projector"
        file = consumer_file(package)
        original = file.read_text(encoding="utf-8")
        file.write_text(
            original.replace("test_conformance.py", "test_no_such_file.py"), encoding="utf-8"
        )
        _, problems = variant_problems(tmp_path, CANONICAL, modes)
>       assert len(problems) == 1
E       assert 0 == 1
E        +  where 0 = len([])
services/orders/tests/unit/test_idempotent_consumer_parity.py:604: AssertionError
=========================== short test summary info ============================
FAILED services/orders/tests/unit/test_idempotent_consumer_parity.py::test_pr48_p5_sentinel_a_conformance_line_naming_a_missing_file_or_absent_is_reported
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### F2-P6

Mutation (P6): the registry is no longer compared with the spec.

- file `services/orders/tests/unit/test_idempotent_consumer_parity.py` sha256 before `1025c98ec33727d7` after mutation `d275135d2386a59e`
- test(s): `services/orders/tests/unit/test_idempotent_consumer_parity.py::test_pr48_p6_sentinel_a_registry_marking_the_projector_no_consumer_is_reported`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.38s`

```
F
=================================== FAILURES ===================================
_ test_pr48_p6_sentinel_a_registry_marking_the_projector_no_consumer_is_reported _
    def test_pr48_p6_sentinel_a_registry_marking_the_projector_no_consumer_is_reported() -> None:
        modes = {**IDEMPOTENCY_MODE, "projector": NO_CONSUMER}
>       assert spec_problems(SPEC_TEXT, modes) == [
            "projector: the spec names it a consumer but it is registered no-consumer"
        ]
E       AssertionError: assert [] == ['projector: ... no-consumer']
E         
E         Right contains one more item: 'projector: the spec names it a consumer but it is registered no-consumer'
E         Use -v to get more diff
services/orders/tests/unit/test_idempotent_consumer_parity.py:619: AssertionError
=========================== short test summary info ============================
FAILED services/orders/tests/unit/test_idempotent_consumer_parity.py::test_pr48_p6_sentinel_a_registry_marking_the_projector_no_consumer_is_reported
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.25s
```

#### F3 — real-tree arms of the parity guard

backup of the real file in `.arm/p24/bak/F3.idempotent_consumer.py`, sha256 prefix `fc9f5b38c78db010`

**(a) rename the projector's `idempotent_consumer.py` (the OI12 opt-out; must now fail by P4, both in the PR48 test and in case 4)**
```
E       AssertionError: assert ['otc_project..._consumer.py'] == []
E         
E         Left contains one more item: 'otc_projector: no consumer file at services/projector/src/otc_projector/infrastructure/messaging/idempotent_consumer.py'
E         Use -v to get more diff
1 failed in 0.08s
E       AssertionError: a registered mode disagrees with the files
E       assert ['projector: ...onsumer file'] == []
E         
E         Left contains one more item: 'projector: registered documented-variant but has no consumer file'
E         Use -v to get more diff
1 failed in 0.09s
restored: cmp identical
```

**(b) remove the `Behavioural conformance:` line from the real banner (must fail by P5)**
```
E       assert ["otc_project...mance:' line"] == []
E         
E         Left contains one more item: "otc_projector: the banner has no 'Behavioural conformance:' line"
E         Use -v to get more diff
1 failed in 0.08s
restored: cmp identical
```
27 passed in 0.80s

#### G2-S1-delete-callback

Mutation (S1): delete the callback invocation.

- file `services/projector/src/otc_projector/infrastructure/messaging/idempotent_consumer.py` sha256 before `fc9f5b38c78db010` after mutation `32bfe61e04fa7ccb`
- test(s): `services/projector/tests/integration/test_update_signal.py::test_r55_emits_exactly_one_update_signal_per_applied_fact_on_a_per_order_channel_a_single_order_and_a_whole_stream_subscriber_both_receive_and_none_at_all_for_a_suppressed_redelivery`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.92s`

```
F
=================================== FAILURES ===================================
_ test_r55_emits_exactly_one_update_signal_per_applied_fact_on_a_per_order_channel_a_single_order_and_a_whole_stream_subscriber_both_receive_and_none_at_all_for_a_suppressed_redelivery _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:35902'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_f154b4a35ae6499a99107bf837a51205', uri='mongodb://otc_test:otc_test_password@localhost:35902/?authSource=admin')
nats_connection = <nats client v2.16.0>
frames_factory = <function frames_factory.<locals>.make at 0x737979cab740>
facts = FactBuilders()
    async def test_r55_emits_exactly_one_update_signal_per_applied_fact_on_a_per_order_channel_a_single_order_and_a_whole_stream_subscriber_both_receive_and_none_at_all_for_a_suppressed_redelivery(  # noqa: E501
        read_model: Any, nats_connection: Any, frames_factory: Any, facts: Any
    ) -> None:
        order = uuid.UUID("0a0b0c0d-2222-4000-8000-0000000000bb")
        whole = await frames_factory("readmodel.>")
        updated = await frames_factory(f"readmodel.order.updated.{order}")
        appended = await frames_factory(f"readmodel.timeline.appended.{order}")
        handler = handler_for(read_model, nats_connection)
        placed = facts.build("order.placed.v1", correlation_id=order)
        confirmed = facts.build("order.confirmed.v1", correlation_id=order)
        first = await handler.handle(ProjectFactCommand(event=placed))
        second = await handler.handle(ProjectFactCommand(event=confirmed))
        await nats_connection.flush()
>       await until("two pairs of frames", lambda: len(whole.received) >= 4)
services/projector/tests/integration/test_update_signal.py:79: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
claim = 'two pairs of frames'
condition = <function test_r55_emits_exactly_one_update_signal_per_applied_fact_on_a_per_order_channel_a_single_order_and_a_whole_stream_subscriber_both_receive_and_none_at_all_for_a_suppressed_redelivery.<locals>.<lambda> at 0x737979cabcc0>
    async def until(claim: str, condition: Any) -> None:
        """Wait on monotonic evidence, bounded, with a message naming the claim."""
        deadline = asyncio.get_running_loop().time() + BOUND_SECONDS
        while not condition():
            if asyncio.get_running_loop().time() > deadline:
>               pytest.fail(f"{claim}: not observed within {BOUND_SECONDS} s")
E               Failed: two pairs of frames: not observed within 20 s
services/projector/tests/integration/test_update_signal.py:42: Failed
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_update_signal.py::test_r55_emits_exactly_one_update_signal_per_applied_fact_on_a_per_order_channel_a_single_order_and_a_whole_stream_subscriber_both_receive_and_none_at_all_for_a_suppressed_redelivery
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 24.01s
```

#### G2-S2-unconditional-callback

Mutation (S2): invoke the callback unconditionally (also for a suppressed redelivery).

- file `services/projector/src/otc_projector/infrastructure/persistence/mongo_read_model_writer.py` sha256 before `1be883059cbd596d` after mutation `bdfd98dbf4c02f21`
- test(s): `services/projector/tests/integration/test_update_signal.py::test_r55_emits_exactly_one_update_signal_per_applied_fact_on_a_per_order_channel_a_single_order_and_a_whole_stream_subscriber_both_receive_and_none_at_all_for_a_suppressed_redelivery`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 4.49s`

```
F
=================================== FAILURES ===================================
_ test_r55_emits_exactly_one_update_signal_per_applied_fact_on_a_per_order_channel_a_single_order_and_a_whole_stream_subscriber_both_receive_and_none_at_all_for_a_suppressed_redelivery _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:35910'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_b8ddc4832b9d4cc48cfe7cf711dcb759', uri='mongodb://otc_test:otc_test_password@localhost:35910/?authSource=admin')
nats_connection = <nats client v2.16.0>
frames_factory = <function frames_factory.<locals>.make at 0x71e5fa567a00>
facts = FactBuilders()
    async def test_r55_emits_exactly_one_update_signal_per_applied_fact_on_a_per_order_channel_a_single_order_and_a_whole_stream_subscriber_both_receive_and_none_at_all_for_a_suppressed_redelivery(  # noqa: E501
        read_model: Any, nats_connection: Any, frames_factory: Any, facts: Any
    ) -> None:
        order = uuid.UUID("0a0b0c0d-2222-4000-8000-0000000000bb")
        whole = await frames_factory("readmodel.>")
        updated = await frames_factory(f"readmodel.order.updated.{order}")
        appended = await frames_factory(f"readmodel.timeline.appended.{order}")
        handler = handler_for(read_model, nats_connection)
        placed = facts.build("order.placed.v1", correlation_id=order)
        confirmed = facts.build("order.confirmed.v1", correlation_id=order)
        first = await handler.handle(ProjectFactCommand(event=placed))
        second = await handler.handle(ProjectFactCommand(event=confirmed))
        await nats_connection.flush()
        await until("two pairs of frames", lambda: len(whole.received) >= 4)
        redelivery = await handler.handle(ProjectFactCommand(event=placed))
        await barrier(nats_connection, str(order), whole, updated, appended)
        assert (first, second) == (ProjectionOutcome.PROCESSED, ProjectionOutcome.PROCESSED)
        assert redelivery is ProjectionOutcome.DUPLICATE
>       assert len(updated.received) == 2, f"order.updated frames: {len(updated.received)}"
E       AssertionError: order.updated frames: 3
E       assert 3 == 2
E        +  where 3 = len([b'readmodel.order.updated.0a0b0c0d-2222-4000-8000-0000000000bb\n{"eventId":"00000065-0065-4000-8000-0000000c344b","or...":{"despatchReference":null,"invoiceReference":null,"paymentReference":null},"occurredAt":"2026-03-02T04:12:24.101Z"}'])
E        +    where [b'readmodel.order.updated.0a0b0c0d-2222-4000-8000-0000000000bb\n{"eventId":"00000065-0065-4000-8000-0000000c344b","or...":{"despatchReference":null,"invoiceReference":null,"paymentReference":null},"occurredAt":"2026-03-02T04:12:24.101Z"}'] = <services.projector.tests.integration.conftest.Frames object at 0x71e5fa550190>.received
services/projector/tests/integration/test_update_signal.py:86: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_update_signal.py::test_r55_emits_exactly_one_update_signal_per_applied_fact_on_a_per_order_channel_a_single_order_and_a_whole_stream_subscriber_both_receive_and_none_at_all_for_a_suppressed_redelivery
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 4.00s
```

#### G3-drop-occurred-at

Mutation: drop `occurred_at` from the `OrderStreamUpdate` construction.

- file `services/projector/src/otc_projector/infrastructure/signal/nats_update_signal_publisher.py` sha256 before `75b2af1579751596` after mutation `846cdaffc32c7ccb`
- test(s): `services/projector/tests/integration/test_update_signal.py::test_pr17_both_payloads_carry_openapis_required_fields_read_from_the_contract`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 4.84s`

```
            "order.placed.v1", correlation_id=order, payload={"retailer_code": "Café-Zürich"}
        )
        await handler.handle(ProjectFactCommand(event=placed))
>       await until("one pair of frames", lambda: updated.received and appended.received)
services/projector/tests/integration/test_update_signal.py:116: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
claim = 'one pair of frames'
condition = <function test_pr17_both_payloads_carry_openapis_required_fields_read_from_the_contract.<locals>.<lambda> at 0x70d849b6fc10>
    async def until(claim: str, condition: Any) -> None:
        """Wait on monotonic evidence, bounded, with a message naming the claim."""
        deadline = asyncio.get_running_loop().time() + BOUND_SECONDS
        while not condition():
            if asyncio.get_running_loop().time() > deadline:
>               pytest.fail(f"{claim}: not observed within {BOUND_SECONDS} s")
E               Failed: one pair of frames: not observed within 20 s
services/projector/tests/integration/test_update_signal.py:42: Failed
------------------------------ Captured log call -------------------------------
ERROR    otc_projector.application.handlers:handlers.py:47 the update signal could not be published on readmodel.order.updated.0a0b0c0d-3333-4000-8000-0000000000cc and readmodel.timeline.appended.0a0b0c0d-3333-4000-8000-0000000000cc; the fact is applied and committed
Traceback (most recent call last):
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/src/otc_projector/application/handlers.py", line 43, in _announce
    await self._scope.signals.publish(applied, delta.entry)
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/src/otc_projector/infrastructure/signal/nats_update_signal_publisher.py", line 115, in publish
    updated = to_wire_json(order_stream_update(applied, entry)).encode("utf-8")
                           ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/src/otc_projector/infrastructure/signal/nats_update_signal_publisher.py", line 57, in order_stream_update
    return OrderStreamUpdate(
        event_id=UUID(entry.event_id),
    ...<33 lines>...
        ),
    )
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/.venv/lib/python3.14/site-packages/pydantic/main.py", line 263, in __init__
    validated_self = self.__pydantic_validator__.validate_python(data, self_instance=self)
pydantic_core._pydantic_core.ValidationError: 1 validation error for OrderStreamUpdate
occurredAt
  Field required [type=missing, input_value={'event_id': UUID('000000...3, total_amount=124254)}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_update_signal.py::test_pr17_both_payloads_carry_openapis_required_fields_read_from_the_contract
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 24.61s
```

#### G3-sibling-subject

Mutation: publish `timeline.appended` on the sibling subject `readmodel.timeline.appends.<id>`.

- file `services/projector/src/otc_projector/application/ports/update_signal.py` sha256 before `dd213f9b6851fe8d` after mutation `81573a0d36a219d0`
- test(s): `services/projector/tests/integration/test_update_signal.py::test_pr33_the_timeline_appended_payload_carries_causation_id`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.91s`

```
F
=================================== FAILURES ===================================
_________ test_pr33_the_timeline_appended_payload_carries_causation_id _________
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:35926'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_71ce2b0803e241429d8f6b538b09bfc8', uri='mongodb://otc_test:otc_test_password@localhost:35926/?authSource=admin')
nats_connection = <nats client v2.16.0>
frames_factory = <function frames_factory.<locals>.make at 0x730cf036f950>
facts = FactBuilders()
    async def test_pr33_the_timeline_appended_payload_carries_causation_id(
        read_model: Any, nats_connection: Any, frames_factory: Any, facts: Any
    ) -> None:
        order = uuid.UUID("0a0b0c0d-4444-4000-8000-0000000000dd")
        appended = await frames_factory(f"readmodel.timeline.appended.{order}")
        sentinel = uuid.UUID("99999999-9999-4999-8999-999999999999")
        event = facts.build("order.confirmed.v1", correlation_id=order, causation_id=sentinel)
        await handler_for(read_model, nats_connection).handle(ProjectFactCommand(event=event))
>       await until("the timeline.appended frame", lambda: appended.received)
services/projector/tests/integration/test_update_signal.py:138: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
claim = 'the timeline.appended frame'
condition = <function test_pr33_the_timeline_appended_payload_carries_causation_id.<locals>.<lambda> at 0x730cf144f740>
    async def until(claim: str, condition: Any) -> None:
        """Wait on monotonic evidence, bounded, with a message naming the claim."""
        deadline = asyncio.get_running_loop().time() + BOUND_SECONDS
        while not condition():
            if asyncio.get_running_loop().time() > deadline:
>               pytest.fail(f"{claim}: not observed within {BOUND_SECONDS} s")
E               Failed: the timeline.appended frame: not observed within 20 s
services/projector/tests/integration/test_update_signal.py:42: Failed
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_update_signal.py::test_pr33_the_timeline_appended_payload_carries_causation_id
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 24.04s
```

#### G4 asymmetry — S5 mutation against every integration case that exercises the writer

```
FAILED services/projector/tests/integration/test_update_signal.py::test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references
FAILED services/projector/tests/integration/test_idempotent_consumer_conformance.py::test_pr26_the_post_apply_callback_runs_once_on_processed_and_never_on_duplicate
2 failed, 18 passed in 5.34s
restored: cmp identical
```

#### G4-return-document-default

Mutation (S5): remove `return_document=ReturnDocument.AFTER` (the driver's default is BEFORE).

- file `services/projector/src/otc_projector/infrastructure/messaging/idempotent_consumer.py` sha256 before `fc9f5b38c78db010` after mutation `26683a0fd6b4cc36`
- test(s): `services/projector/tests/integration/test_update_signal.py::test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 4.03s`

```
F
=================================== FAILURES ===================================
_ test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:35934'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_0f3e9837dfa14865aba6bde1839b1907', uri='mongodb://otc_test:otc_test_password@localhost:35934/?authSource=admin')
nats_connection = <nats client v2.16.0>
frames_factory = <function frames_factory.<locals>.make at 0x7065603b7950>
facts = FactBuilders()
    async def test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references(
        read_model: Any, nats_connection: Any, frames_factory: Any, facts: Any
    ) -> None:
        order = uuid.UUID("0a0b0c0d-5555-4000-8000-0000000000ee")
        updated = await frames_factory(f"readmodel.order.updated.{order}")
        handler = handler_for(read_model, nats_connection)
        confirmed = facts.build("order.confirmed.v1", correlation_id=order)
        despatched = facts.build(
            "order.despatched.v1",
            correlation_id=order,
            payload={"despatch_reference": "DES-717171"},
        )
        await handler.handle(ProjectFactCommand(event=confirmed))
        await handler.handle(ProjectFactCommand(event=despatched))
        await until("two order.updated frames", lambda: len(updated.received) >= 2)
        first, second = (frame for _, frame in updated.frames())
>       assert first["status"] == "confirmed"
E       AssertionError: assert 'placed' == 'confirmed'
E         
E         - confirmed
E         + placed
services/projector/tests/integration/test_update_signal.py:160: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_update_signal.py::test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 4.54s
```

#### G5-shared-headers

Mutation: reuse one headers dict across the two publishes.

- file `services/projector/src/otc_projector/infrastructure/signal/nats_update_signal_publisher.py` sha256 before `75b2af1579751596` after mutation `4bdf24e3dbe880b6`
- test(s): `services/projector/tests/unit/test_update_signal_payloads.py::test_pr17_two_publishes_carry_distinct_headers_each_with_the_order_id`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.06s`

```
F
=================================== FAILURES ===================================
____ test_pr17_two_publishes_carry_distinct_headers_each_with_the_order_id _____
    async def test_pr17_two_publishes_carry_distinct_headers_each_with_the_order_id() -> None:
        connection = await published()
        first, second = connection.published[0][2], connection.published[1][2]
        assert first == {"x-correlation-id": ORDER_ID}
        assert second == {"x-correlation-id": ORDER_ID}
>       assert first is not second, "the two publishes share one mutable headers mapping"
E       AssertionError: the two publishes share one mutable headers mapping
E       assert {'x-correlation-id': '11111111-aaaa-4aaa-8aaa-111111111111'} is not {'x-correlation-id': '11111111-aaaa-4aaa-8aaa-111111111111'}
services/projector/tests/unit/test_update_signal_payloads.py:122: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_update_signal_payloads.py::test_pr17_two_publishes_carry_distinct_headers_each_with_the_order_id
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### G5-swap-event-causation

Mutation: swap `event_id`/`causation_id` in `timeline.appended`.

- file `services/projector/src/otc_projector/infrastructure/signal/nats_update_signal_publisher.py` sha256 before `75b2af1579751596` after mutation `db57b4885287dd70`
- test(s): `services/projector/tests/unit/test_update_signal_payloads.py::test_pr37_every_field_reaches_both_signal_payloads_verbatim_sentinel_per_field`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.06s`

```
        appended = json.loads(connection.published[1][1])
        assert updated == {
            "eventId": EVENT_ID,
            "orderId": ORDER_ID,
            "orderReference": "ORD-424242",
            "status": "cancelled",
            "cancellationReason": "operator_cancelled",
            "references": {
                "despatchReference": "DES-717171",
                "invoiceReference": "INV-838383",
                "paymentReference": "PAY-949494",
            },
            "totals": {
                "initialAmount": 5550001,
                "initialDiscount": 6660002,
                "totalAmount": 7770003,
            },
            "occurredAt": "2031-07-08T09:10:11.123Z",
        }
>       assert appended == {
            "eventId": EVENT_ID,
            "causationId": CAUSATION_ID,
            "orderId": ORDER_ID,
            "orderReference": "ORD-424242",
            "eventType": "order.cancelled.v1",
            "occurredAt": "2031-07-08T09:10:11.123Z",
            "summary": "Orden anulada por el operador — Zürich",
        }
E       AssertionError: assert {'eventId': '...-424242', ...} == {'eventId': '...-424242', ...}
E         
E         Omitting 5 identical items, use -vv to show
E         Differing items:
E         {'eventId': '33333333-cccc-4ccc-8ccc-333333333333'} != {'eventId': '22222222-bbbb-4bbb-8bbb-222222222222'}
E         {'causationId': '22222222-bbbb-4bbb-8bbb-222222222222'} != {'causationId': '33333333-cccc-4ccc-8ccc-333333333333'}
E         Use -v to get more diff
services/projector/tests/unit/test_update_signal_payloads.py:97: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_update_signal_payloads.py::test_pr37_every_field_reaches_both_signal_payloads_verbatim_sentinel_per_field
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.11s
```

#### H1-delete-pr52

Mutation: delete the PR52 other-index check.

- file `services/projector/src/otc_projector/infrastructure/persistence/read_model_indexes.py` sha256 before `8bb83e0320e7c351` after mutation `c9b9977745c86ff2`
- test(s): `services/projector/tests/integration/test_read_model_indexes.py::test_pr52_a_differently_named_unique_index_on_order_reference_fails_the_boot`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.85s`

```
F
=================================== FAILURES ===================================
_ test_pr52_a_differently_named_unique_index_on_order_reference_fails_the_boot _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:35958'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_5b7f69fbf85b4dd59f93a3a3a75e8254', uri='mongodb://otc_test:otc_test_password@localhost:35958/?authSource=admin')
    async def test_pr52_a_differently_named_unique_index_on_order_reference_fails_the_boot(
        read_model: Any,
    ) -> None:
        collection = read_model.client.get_database(read_model.database).get_collection("rogue_box")
        await collection.create_index([("orderReference", 1)], unique=True, name="uq_rogue_reference")
        await ensure_indexes(collection)  # no conflict: the names differ
>       with pytest.raises(ReadModelIndexError) as refused:
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       Failed: DID NOT RAISE ReadModelIndexError
services/projector/tests/integration/test_read_model_indexes.py:111: Failed
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_read_model_indexes.py::test_pr52_a_differently_named_unique_index_on_order_reference_fails_the_boot
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.86s
```

#### H1-hardcode-code-85

Mutation (#8's A8): hard-code `code 85` in the message.

- file `services/projector/src/otc_projector/infrastructure/persistence/read_model_indexes.py` sha256 before `8bb83e0320e7c351` after mutation `9adb21eda4a5c936`
- test(s): `services/projector/tests/integration/test_read_model_indexes.py::test_pr22_a_plain_unique_index_of_the_same_name_fails_the_boot_naming_the_index_and_the_raised_code`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.80s`

```
F
=================================== FAILURES ===================================
_ test_pr22_a_plain_unique_index_of_the_same_name_fails_the_boot_naming_the_index_and_the_raised_code _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:35954'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_5d95d5b678b8471f9d8e49200017dc03', uri='mongodb://otc_test:otc_test_password@localhost:35954/?authSource=admin')
    async def test_pr22_a_plain_unique_index_of_the_same_name_fails_the_boot_naming_the_index_and_the_raised_code(  # noqa: E501
        read_model: Any,
    ) -> None:
        collection = read_model.client.get_database(read_model.database).get_collection("conflict_box")
        await collection.create_index([("orderReference", 1)], unique=True, name="uq_order_reference")
        # the code the server raises for the projector's creation, read from the exception itself
        with pytest.raises(OperationFailure) as raised:
            await collection.create_index(
                [("orderReference", 1)],
                unique=True,
                name="uq_order_reference",
                partialFilterExpression={"orderReference": {"$type": "string"}},
            )
        server_code = raised.value.code
        print(f"the server raised code {server_code} ({raised.value.details.get('codeName')})")
        assert server_code in (85, 86), f"the server raised an unexpected code {server_code}"
        with pytest.raises(ReadModelIndexError) as refused:
            await ensure_indexes(collection)
        message = str(refused.value)
        assert "uq_order_reference" in message, "the index is not named"
        assert "dropIndex" in message, "the dropIndex one-liner is missing"
>       assert f"code {server_code}" in message, (
            f"the message does not carry the code the server raised ({server_code}): {message}"
        )
E       AssertionError: the message does not carry the code the server raised (86): index uq_order_reference already exists on conflict_box with different options: the server refused the creation with code 85. Drop it and restart: db.getCollection("conflict_box").dropIndex("uq_order_reference")
E       assert 'code 86' in 'index uq_order_reference already exists on conflict_box with different options: the server refused the creation with code 85. Drop it and restart: db.getCollection("conflict_box").dropIndex("uq_order_reference")'
services/projector/tests/integration/test_read_model_indexes.py:72: AssertionError
----------------------------- Captured stdout call -----------------------------
the server raised code 86 (IndexKeySpecsConflict)
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_read_model_indexes.py::test_pr22_a_plain_unique_index_of_the_same_name_fails_the_boot_naming_the_index_and_the_raised_code
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.92s
```

#### H1-nonpartial

Mutation: make `uq_order_reference` non-partial.

- file `services/projector/src/otc_projector/infrastructure/persistence/read_model_indexes.py` sha256 before `8bb83e0320e7c351` after mutation `514e3e812de8e1fa`
- test(s): `services/projector/tests/integration/test_read_model_indexes.py::test_pr8_two_placeholders_with_null_order_reference_coexist`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.80s`

```
.venv/lib/python3.14/site-packages/pymongo/asynchronous/collection.py:1314: in update_one
    await self._update_retryable(
.venv/lib/python3.14/site-packages/pymongo/asynchronous/collection.py:1098: in _update_retryable
    return await self._database.client._retryable_write(
.venv/lib/python3.14/site-packages/pymongo/asynchronous/mongo_client.py:2104: in _retryable_write
    return await self._retry_with_session(retryable, func, s, bulk, operation, operation_id)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.14/site-packages/pymongo/asynchronous/mongo_client.py:1974: in _retry_with_session
    return await self._retry_internal(
.venv/lib/python3.14/site-packages/pymongo/_csot.py:116: in csot_wrapper
    return await func(self, *args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.14/site-packages/pymongo/asynchronous/mongo_client.py:2014: in _retry_internal
    return await _ClientConnectionRetryable(
.venv/lib/python3.14/site-packages/pymongo/asynchronous/mongo_client.py:2901: in run
    res = await self._read() if self._is_read else await self._write()
                                                   ^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.14/site-packages/pymongo/asynchronous/mongo_client.py:3116: in _write
    return await self._func(self._session, conn, self._retryable)  # type: ignore
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv/lib/python3.14/site-packages/pymongo/asynchronous/collection.py:1078: in _update
    return await self._update(
.venv/lib/python3.14/site-packages/pymongo/asynchronous/collection.py:1039: in _update
    _check_write_command_response(result)
.venv/lib/python3.14/site-packages/pymongo/helpers_shared.py:365: in _check_write_command_response
    _raise_last_write_error(write_errors)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
write_errors = [{'index': 0, 'code': 11000, 'errmsg': 'Plan executor error during update :: caused by :: E11000 duplicate key error c...order_timeline index: uq_order_reference dup key: { orderReference: null }', 'keyPattern': {'orderReference': 1}, ...}]
    def _raise_last_write_error(write_errors: list[Any]) -> NoReturn:
        # If the last batch had multiple errors only report
        # the last error to emulate continue_on_error.
        error = write_errors[-1]
        if error.get("code") == 11000:
>           raise DuplicateKeyError(error.get("errmsg"), 11000, error)
E           pymongo.errors.DuplicateKeyError: Plan executor error during update :: caused by :: E11000 duplicate key error collection: otc_test_673cdb956b1540ff831f4c11f79efea6.order_timeline index: uq_order_reference dup key: { orderReference: null }, full error: {'index': 0, 'code': 11000, 'errmsg': 'Plan executor error during update :: caused by :: E11000 duplicate key error collection: otc_test_673cdb956b1540ff831f4c11f79efea6.order_timeline index: uq_order_reference dup key: { orderReference: null }', 'keyPattern': {'orderReference': 1}, 'keyValue': {'orderReference': None}}
.venv/lib/python3.14/site-packages/pymongo/helpers_shared.py:335: DuplicateKeyError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_read_model_indexes.py::test_pr8_two_placeholders_with_null_order_reference_coexist
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 4.01s
```

#### H2-exists-selector

Mutation: select on `{timelineOrderVersion: {$exists: False}}`.

- file `services/projector/src/otc_projector/infrastructure/persistence/timeline_order_migration.py` sha256 before `a3623a4ceda72b75` after mutation `ffd4f027a4156353`
- test(s): `services/projector/tests/integration/test_timeline_order_migration.py::test_pr32_a_document_at_version_one_is_re_sorted_and_stamped`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.78s`

```
F
=================================== FAILURES ===================================
_________ test_pr32_a_document_at_version_one_is_re_sorted_and_stamped _________
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:35964'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_523b2058d4864b05ab1e97be9bc86c01', uri='mongodb://otc_test:otc_test_password@localhost:35964/?authSource=admin')
    async def test_pr32_a_document_at_version_one_is_re_sorted_and_stamped(read_model: Any) -> None:
        # the chain c-root <- b-middle <- a-leaf, stored the way version 1 stored it: by eventId
        stale = document(
            "order-v1",
            1,
            [entry("a-leaf", "b-middle"), entry("b-middle", "c-root"), entry("c-root", "command-1")],
        )
        await read_model.collection.insert_one(stale)
        result = await migrate_timeline_order(read_model.collection)
        after = await read_model.document("order-v1")
>       assert [e["eventId"] for e in after["events"]] == ["c-root", "b-middle", "a-leaf"]
E       AssertionError: assert ['a-leaf', 'b...le', 'c-root'] == ['c-root', 'b...le', 'a-leaf']
E         
E         At index 0 diff: 'a-leaf' != 'c-root'
E         Use -v to get more diff
services/projector/tests/integration/test_timeline_order_migration.py:53: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_timeline_order_migration.py::test_pr32_a_document_at_version_one_is_re_sorted_and_stamped
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.87s
```

#### H2-no-resort

Mutation: stamp the version without re-sorting.

- file `services/projector/src/otc_projector/infrastructure/persistence/timeline_order_migration.py` sha256 before `a3623a4ceda72b75` after mutation `fe5b650195e91b3b`
- test(s): `services/projector/tests/integration/test_timeline_order_migration.py::test_pr32_a_document_at_version_one_is_re_sorted_and_stamped`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.79s`

```
F
=================================== FAILURES ===================================
_________ test_pr32_a_document_at_version_one_is_re_sorted_and_stamped _________
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:35968'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_c9a48060e2e746b1ab02ced69fbcac14', uri='mongodb://otc_test:otc_test_password@localhost:35968/?authSource=admin')
    async def test_pr32_a_document_at_version_one_is_re_sorted_and_stamped(read_model: Any) -> None:
        # the chain c-root <- b-middle <- a-leaf, stored the way version 1 stored it: by eventId
        stale = document(
            "order-v1",
            1,
            [entry("a-leaf", "b-middle"), entry("b-middle", "c-root"), entry("c-root", "command-1")],
        )
        await read_model.collection.insert_one(stale)
        result = await migrate_timeline_order(read_model.collection)
        after = await read_model.document("order-v1")
>       assert [e["eventId"] for e in after["events"]] == ["c-root", "b-middle", "a-leaf"]
E       AssertionError: assert ['a-leaf', 'b...le', 'c-root'] == ['c-root', 'b...le', 'a-leaf']
E         
E         At index 0 diff: 'a-leaf' != 'c-root'
E         Use -v to get more diff
services/projector/tests/integration/test_timeline_order_migration.py:53: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_timeline_order_migration.py::test_pr32_a_document_at_version_one_is_re_sorted_and_stamped
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.83s
```

#### H3-client-id-as-group

Mutation: pass the client id as the group id.

- file `services/projector/src/otc_projector/infrastructure/messaging/kafka_fact_subscriber.py` sha256 before `9cdaa3afcbbca44b` after mutation `a050637822d274b7`
- test(s): `services/projector/tests/unit/test_composition.py::test_each_setting_reaches_the_adapter_it_configures`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.19s`

```
F
=================================== FAILURES ===================================
_____________ test_each_setting_reaches_the_adapter_it_configures ______________
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7d10ad3dd480>
tmp_path = PosixPath('/tmp/pytest-of-juanpabloperez/pytest-783/test_each_setting_reaches_the_0')
    async def test_each_setting_reaches_the_adapter_it_configures(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        settings = settings_from(
            monkeypatch,
            tmp_path,
            MONGO_URI="mongodb://sentinel-user:sentinel-pw@mongo.sentinel:27999/?authSource=sentinel",
            MONGO_DB_READMODEL="readmodel_sentinel",
            KAFKA_BROKERS="kafka.sentinel:19092",
            PROJECTOR_KAFKA_CLIENT_ID="client-sentinel",
            PROJECTOR_CONSUMER_GROUP="group-sentinel",
            NATS_URL="nats://nats.sentinel:4333",
        )
        world = World()
        runtime = await start_runtime(settings, externals=world.externals())
        try:
            assert world.mongo_uri == (
                "mongodb://sentinel-user:sentinel-pw@mongo.sentinel:27999/?authSource=sentinel"
            )
            assert world.database_name == "readmodel_sentinel"
            assert world.collection_name == "order_timeline"
            assert world.nats_url == "nats://nats.sentinel:4333"
            assert world.consumer_kwargs["bootstrap_servers"] == "kafka.sentinel:19092"
            assert world.consumer_kwargs["client_id"] == "client-sentinel"
>           assert world.consumer_kwargs["group_id"] == "group-sentinel"
E           AssertionError: assert 'client-sentinel' == 'group-sentinel'
E             
E             - group-sentinel
E             + client-sentinel
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/tests/unit/test_composition.py:208: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_composition.py::test_each_setting_reaches_the_adapter_it_configures
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.24s
```

#### H3-mongo-uri-to-nats

Mutation: pass `settings.mongo.uri` to the NATS factory.

- file `services/projector/src/otc_projector/composition.py` sha256 before `e57aaf886ddf96ae` after mutation `8054207cf653072c`
- test(s): `services/projector/tests/unit/test_composition.py::test_each_setting_reaches_the_adapter_it_configures`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.19s`

```
F
=================================== FAILURES ===================================
_____________ test_each_setting_reaches_the_adapter_it_configures ______________
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x736a6e52d480>
tmp_path = PosixPath('/tmp/pytest-of-juanpabloperez/pytest-785/test_each_setting_reaches_the_0')
    async def test_each_setting_reaches_the_adapter_it_configures(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        settings = settings_from(
            monkeypatch,
            tmp_path,
            MONGO_URI="mongodb://sentinel-user:sentinel-pw@mongo.sentinel:27999/?authSource=sentinel",
            MONGO_DB_READMODEL="readmodel_sentinel",
            KAFKA_BROKERS="kafka.sentinel:19092",
            PROJECTOR_KAFKA_CLIENT_ID="client-sentinel",
            PROJECTOR_CONSUMER_GROUP="group-sentinel",
            NATS_URL="nats://nats.sentinel:4333",
        )
        world = World()
        runtime = await start_runtime(settings, externals=world.externals())
        try:
            assert world.mongo_uri == (
                "mongodb://sentinel-user:sentinel-pw@mongo.sentinel:27999/?authSource=sentinel"
            )
            assert world.database_name == "readmodel_sentinel"
            assert world.collection_name == "order_timeline"
>           assert world.nats_url == "nats://nats.sentinel:4333"
E           AssertionError: assert 'mongodb://se...urce=sentinel' == 'nats://nats.sentinel:4333'
E             
E             - nats://nats.sentinel:4333
E             + mongodb://sentinel-user:sentinel-pw@mongo.sentinel:27999/?authSource=sentinel
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/tests/unit/test_composition.py:205: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_composition.py::test_each_setting_reaches_the_adapter_it_configures
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.23s
```

#### H4-migration-after-consumer

Mutation: move the migration after the consumer start.

- file `services/projector/src/otc_projector/composition.py` sha256 before `e57aaf886ddf96ae` after mutation `1baf19c39f3c85ff`
- test(s): `services/projector/tests/unit/test_composition.py::test_pr43_start_runtime_runs_its_steps_in_order`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.19s`

```
F
=================================== FAILURES ===================================
_______________ test_pr43_start_runtime_runs_its_steps_in_order ________________
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7c36c6541480>
tmp_path = PosixPath('/tmp/pytest-of-juanpabloperez/pytest-787/test_pr43_start_runtime_runs_i0')
    async def test_pr43_start_runtime_runs_its_steps_in_order(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        world = World()
        runtime = await start_runtime(
            default_settings(monkeypatch, tmp_path), externals=world.externals()
        )
        try:
>           assert world.calls == EXPECTED_ORDER, f"the boot ran {world.calls}"
E           AssertionError: the boot ran ['dispatcher', 'mongo.ping', 'indexes.ensure', 'indexes.verify', 'nats.connect', 'consumer.start', 'migration']
E           assert ['dispatcher'...r.start', ...] == ['dispatcher'...connect', ...]
E             
E             At index 4 diff: 'nats.connect' != 'migration'
E             Use -v to get more diff
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/tests/unit/test_composition.py:221: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_composition.py::test_pr43_start_runtime_runs_its_steps_in_order
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.26s
```

#### H4-skip-mongo-close

Mutation: skip `stack.push_async_callback` for the Mongo client.

- file `services/projector/src/otc_projector/composition.py` sha256 before `e57aaf886ddf96ae` after mutation `7bda520331f82ad0`
- test(s): `services/projector/tests/unit/test_composition.py::test_pr43_a_consumer_that_cannot_start_closes_everything_in_reverse_and_leaves_no_task`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.19s`

```
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7932f6f41480>
tmp_path = PosixPath('/tmp/pytest-of-juanpabloperez/pytest-789/test_pr43_a_consumer_that_cann0')
    async def test_pr43_a_consumer_that_cannot_start_closes_everything_in_reverse_and_leaves_no_task(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        world = World()
        world.subscriber_error = RuntimeError("broker down")
        before = leftover_tasks()
        with pytest.raises(RuntimeError, match="broker down"):
            await start_runtime(default_settings(monkeypatch, tmp_path), externals=world.externals())
        assert leftover_tasks() == before
        closes = [c for c in world.calls if c in ("mongo.close", "nats.drain")]
>       assert closes == ["nats.drain", "mongo.close"], f"closed {closes}"
E       AssertionError: closed ['nats.drain']
E       assert ['nats.drain'] == ['nats.drain', 'mongo.close']
E         
E         Right contains one more item: 'mongo.close'
E         Use -v to get more diff
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/tests/unit/test_composition.py:258: AssertionError
------------------------------ Captured log call -------------------------------
ERROR    otc_projector.composition:composition.py:267 transport task fact-consumer ended with an error
Traceback (most recent call last):
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/src/otc_projector/composition.py", line 355, in start_runtime
    await _await_consumer_ready(
        subscriber, tasks["fact-consumer"], consumer_startup_seconds
    )
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/src/otc_projector/composition.py", line 282, in _await_consumer_ready
    task.result()  # raises the consumer's own error
    ~~~~~~~~~~~^^
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/src/otc_projector/presentation/projector_facts_consumer.py", line 54, in run
    await self._subscriber.run(self.handle, stop)
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/src/otc_projector/infrastructure/messaging/kafka_fact_subscriber.py", line 141, in run
    await consumer.start()
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/tests/unit/test_composition.py", line 118, in start
    raise world.subscriber_error
RuntimeError: broker down
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_composition.py::test_pr43_a_consumer_that_cannot_start_closes_everything_in_reverse_and_leaves_no_task
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.24s
```

#### H5-two

Mutation: register the handler twice.

- file `services/projector/src/otc_projector/composition.py` sha256 before `e57aaf886ddf96ae` after mutation `7e5798ce320ab81a`
- test(s): `services/projector/tests/unit/test_composition.py::test_pr27_the_real_registration_builds_a_dispatcher_with_exactly_one_handler`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.18s`

```
        commands: set[type] = set()
        queries: set[type] = set()
        for message in _messages_under(message_roots):
            is_command = issubclass(message, Command)
            if is_command and issubclass(message, Query):
                problems.append(
                    f"{message.__qualname__} is both a Command and a Query; "
                    "a message is exactly one."
                )
            elif is_command:
                commands.add(message)
            else:
                queries.add(message)
        # Registrations count too, so a handler registered for a type outside the scanned roots is
        # still checked for duplicates (never reported as "missing": absence needs the universe).
        for kind, universe, registered in (
            ("command", commands, self._commands),
            ("query", queries, self._queries),
        ):
            for message_type in sorted(universe | registered.keys(), key=lambda t: t.__qualname__):
                factories = registered.get(message_type, [])
                if not factories and message_type in universe:
                    problems.append(
                        f"No {kind} handler is registered for {message_type.__qualname__}. "
                        "Exactly one is required."
                    )
                elif len(factories) > 1:
                    names = ", ".join(_label(f) for f in factories)
                    problems.append(
                        f"{len(factories)} {kind} handlers are registered for "
                        f"{message_type.__qualname__}: {names}. Exactly one is required."
                    )
        if problems:
>           raise DispatcherValidationError(problems)
E           otc_cqrs.errors.DispatcherValidationError: 2 command handlers are registered for ProjectFactCommand: ProjectFactHandler, ProjectFactHandler. Exactly one is required.
packages/cqrs/src/otc_cqrs/dispatcher.py:146: DispatcherValidationError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_composition.py::test_pr27_the_real_registration_builds_a_dispatcher_with_exactly_one_handler
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.25s
```

#### H5-zero

Mutation: comment out the registration (zero handlers).

- file `services/projector/src/otc_projector/composition.py` sha256 before `e57aaf886ddf96ae` after mutation `dd8ebbe0abf9bc48`
- test(s): `services/projector/tests/unit/test_composition.py::test_pr27_the_real_registration_builds_a_dispatcher_with_exactly_one_handler`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.19s`

```
        commands: set[type] = set()
        queries: set[type] = set()
        for message in _messages_under(message_roots):
            is_command = issubclass(message, Command)
            if is_command and issubclass(message, Query):
                problems.append(
                    f"{message.__qualname__} is both a Command and a Query; "
                    "a message is exactly one."
                )
            elif is_command:
                commands.add(message)
            else:
                queries.add(message)
        # Registrations count too, so a handler registered for a type outside the scanned roots is
        # still checked for duplicates (never reported as "missing": absence needs the universe).
        for kind, universe, registered in (
            ("command", commands, self._commands),
            ("query", queries, self._queries),
        ):
            for message_type in sorted(universe | registered.keys(), key=lambda t: t.__qualname__):
                factories = registered.get(message_type, [])
                if not factories and message_type in universe:
                    problems.append(
                        f"No {kind} handler is registered for {message_type.__qualname__}. "
                        "Exactly one is required."
                    )
                elif len(factories) > 1:
                    names = ", ".join(_label(f) for f in factories)
                    problems.append(
                        f"{len(factories)} {kind} handlers are registered for "
                        f"{message_type.__qualname__}: {names}. Exactly one is required."
                    )
        if problems:
>           raise DispatcherValidationError(problems)
E           otc_cqrs.errors.DispatcherValidationError: No command handler is registered for ProjectFactCommand. Exactly one is required.
packages/cqrs/src/otc_cqrs/dispatcher.py:146: DispatcherValidationError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_composition.py::test_pr27_the_real_registration_builds_a_dispatcher_with_exactly_one_handler
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.24s
```

#### H6-drop-done-reason

Mutation: drop the `t.done()` readiness reason.

- file `services/projector/src/otc_projector/composition.py` sha256 before `e57aaf886ddf96ae` after mutation `32f9fec2cdfd33e5`
- test(s): `services/projector/tests/integration/test_projector_lifespan.py::test_pr50_readiness_drops_when_the_consumer_task_dies`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 8.94s`

```
F
=================================== FAILURES ===================================
____________ test_pr50_readiness_drops_when_the_consumer_task_dies _____________
runtime_env = RuntimeEnv(mongo_uri='mongodb://otc_test:otc_test_password@localhost:36415/?authSource=admin', database='otc_test_3eaf...='otc-test-90dca5d46a-billing-facts'), started=[<otc_projector.composition.ProjectorRuntime object at 0x7a7b93011be0>])
    async def test_pr50_readiness_drops_when_the_consumer_task_dies(runtime_env: Any) -> None:
        runtime = await runtime_env.start("readiness")
        app = create_app()
        app.state.runtime = runtime
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            before = await client.get("/health/ready")
            assert before.status_code == 200, before.text
            task = runtime.tasks["fact-consumer"]
            task.cancel()
            try:
                async with asyncio.timeout(10):
                    await asyncio.gather(task, return_exceptions=True)
            except TimeoutError:
                pytest.fail("PR50: the cancelled consumer task did not end within 10 s")
            after = await client.get("/health/ready")
        assert after.status_code == 503
>       assert "transport task fact-consumer is not running" in after.json()["reasons"]
E       AssertionError: assert 'transport task fact-consumer is not running' in ['the Kafka fact consumer has not joined its group']
services/projector/tests/integration/test_projector_lifespan.py:99: AssertionError
------------------------------ Captured log call -------------------------------
ERROR    aiokafka.consumer.group_coordinator:group_coordinator.py:566 Group Coordinator Request failed: [Error 15] GroupCoordinatorNotAvailableError
WARNING  aiokafka.consumer.group_coordinator:group_coordinator.py:522 Marking the coordinator dead (node 1)for group readiness.
WARNING  aiokafka.consumer.group_coordinator:group_coordinator.py:522 Marking the coordinator dead (node 1)for group readiness.
WARNING  aiokafka.consumer.group_coordinator:group_coordinator.py:522 Marking the coordinator dead (node 1)for group readiness.
ERROR    otc_projector.composition:composition.py:216 transport task fact-consumer was cancelled while the service was running
---------------------------- Captured log teardown -----------------------------
WARNING  otc_projector.composition:composition.py:144 NATS disconnected
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_projector_lifespan.py::test_pr50_readiness_drops_when_the_consumer_task_dies
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 9.03s
```

#### H6-module-level-set

Mutation: move the dedup into a module-level `set` (the filter's `$ne` stays). EXPECTED: this case still PASSES (a runtime rebuilt in one process shares the module); K7's scan is what catches it.

- file `services/projector/src/otc_projector/infrastructure/messaging/idempotent_consumer.py` sha256 before `fc9f5b38c78db010` after mutation `e59d54d7d30a06b5`
- test(s): `services/projector/tests/integration/test_projector_lifespan.py::test_pr51_a_rebuilt_runtime_suppresses_every_applied_fact`
- mutated run exit code: **0** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 9.91s`

```
.                                                                        [100%]
1 passed in 10.18s
```

#### H6-no-cancel

Mutation: drop the `cancel()` after the grace.

- file `services/projector/src/otc_projector/composition.py` sha256 before `e57aaf886ddf96ae` after mutation `31c36788daede6fa`
- test(s): `services/projector/tests/integration/test_projector_lifespan.py::test_pr50_shutdown_cancels_a_stuck_handler_after_the_grace`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 11.30s`

```
        class Stuck:
            def __init__(self, scope: ProjectorScope) -> None:
                self._scope = scope
            async def handle(self, command: ProjectFactCommand, /) -> ProjectionOutcome:
                started.set()
                await release.wait()
                return ProjectionOutcome.PROCESSED
        def wire() -> Wiring:
            registry = HandlerRegistry[ProjectorScope]()
            registry.register_command(ProjectFactCommand, Stuck)
            return registry.build(otc_projector.application), registry.registered_factories()
        runtime = await runtime_env.start(
            "stuck-handler", externals=Externals(wire=wire), stop_grace_seconds=1.0
        )
        await produce([facts.build("order.placed.v1", payload={"order_reference": new_reference()})])
        try:
            async with asyncio.timeout(30):
                await started.wait()
        except TimeoutError:
            pytest.fail("PR50: the stuck handler was never invoked within 30 s")
        task = runtime.tasks["fact-consumer"]
        begun = time.monotonic()
        try:
            async with asyncio.timeout(15):
                await runtime.stop()
        except TimeoutError:
>           pytest.fail(
                "PR50: stop() did not return within 15 s: the stuck handler was never cancelled"
            )
E           Failed: PR50: stop() did not return within 15 s: the stuck handler was never cancelled
services/projector/tests/integration/test_projector_lifespan.py:138: Failed
------------------------------ Captured log call -------------------------------
ERROR    aiokafka.consumer.group_coordinator:group_coordinator.py:566 Group Coordinator Request failed: [Error 15] GroupCoordinatorNotAvailableError
WARNING  aiokafka.consumer.group_coordinator:group_coordinator.py:522 Marking the coordinator dead (node 1)for group stuck-handler.
WARNING  aiokafka.consumer.group_coordinator:group_coordinator.py:522 Marking the coordinator dead (node 1)for group stuck-handler.
WARNING  aiokafka.consumer.group_coordinator:group_coordinator.py:522 Marking the coordinator dead (node 1)for group stuck-handler.
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_projector_lifespan.py::test_pr50_shutdown_cancels_a_stuck_handler_after_the_grace
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 24.06s
```

#### H6-no-connect-bound

Mutation: remove the `asyncio.timeout` around the NATS connect.

- file `services/projector/src/otc_projector/composition.py` sha256 before `e57aaf886ddf96ae` after mutation `755b88e92cbeef2b`
- test(s): `services/projector/tests/integration/test_projector_lifespan.py::test_pr45_an_unreachable_nats_fails_the_boot_within_the_bound`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 10.78s`

```
            host = container.get_container_host_ip()
            before = leftover_tasks()
            started = time.monotonic()
            async def boot() -> None:
                try:
                    async with asyncio.timeout(20):
                        await runtime_env.start_with(
                            "unreachable-nats", nats=f"nats://{host}:{port}", nats_connect_seconds=2.0
                        )
                except TimeoutError:
                    pytest.fail("PR45: the boot did not fail within 20 s against a 2 s bound")
            with pytest.raises(RuntimeError) as refused:
>               await boot()
services/projector/tests/integration/test_projector_lifespan.py:75: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
    async def boot() -> None:
        try:
            async with asyncio.timeout(20):
                await runtime_env.start_with(
                    "unreachable-nats", nats=f"nats://{host}:{port}", nats_connect_seconds=2.0
                )
        except TimeoutError:
>           pytest.fail("PR45: the boot did not fail within 20 s against a 2 s bound")
E           Failed: PR45: the boot did not fail within 20 s against a 2 s bound
services/projector/tests/integration/test_projector_lifespan.py:72: Failed
------------------------------ Captured log call -------------------------------
ERROR    otc_projector.composition:composition.py:141 NATS error: Error('nats: empty response from server when expecting INFO message')
ERROR    otc_projector.composition:composition.py:141 NATS error: Error('nats: empty response from server when expecting INFO message')
ERROR    otc_projector.composition:composition.py:141 NATS error: Error('nats: empty response from server when expecting INFO message')
ERROR    otc_projector.composition:composition.py:141 NATS error: Error('nats: empty response from server when expecting INFO message')
ERROR    otc_projector.composition:composition.py:141 NATS error: Error('nats: empty response from server when expecting INFO message')
ERROR    otc_projector.composition:composition.py:141 NATS error: Error('nats: empty response from server when expecting INFO message')
ERROR    otc_projector.composition:composition.py:141 NATS error: Error('nats: empty response from server when expecting INFO message')
ERROR    otc_projector.composition:composition.py:141 NATS error: Error('nats: empty response from server when expecting INFO message')
ERROR    otc_projector.composition:composition.py:141 NATS error: Error('nats: empty response from server when expecting INFO message')
ERROR    otc_projector.composition:composition.py:141 NATS error: Error('nats: empty response from server when expecting INFO message')
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_projector_lifespan.py::test_pr45_an_unreachable_nats_fails_the_boot_within_the_bound
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 28.81s
```

#### H7-ready-200-when-none

Mutation: return 200 when `app.state.runtime is None`.

- file `services/projector/src/otc_projector/presentation/app.py` sha256 before `a423f4dd58737970` after mutation `037f60d42b2dd67f`
- test(s): `services/projector/tests/test_projector_health.py::test_projector_health_ready_is_503_before_the_lifespan_has_started_a_runtime`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.25s`

```
F
=================================== FAILURES ===================================
_ test_projector_health_ready_is_503_before_the_lifespan_has_started_a_runtime _
    async def test_projector_health_ready_is_503_before_the_lifespan_has_started_a_runtime() -> None:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health/ready")
>       assert response.status_code == 503
E       assert 200 == 503
E        +  where 200 = <Response [200 OK]>.status_code
services/projector/tests/test_projector_health.py:26: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/test_projector_health.py::test_projector_health_ready_is_503_before_the_lifespan_has_started_a_runtime
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.30s
```

#### I1-causation-equals-correlation

Mutation: give the builders causationId = correlationId.

- file `services/projector/tests/conftest.py` sha256 before `a9b7a715ae2d6eff` after mutation `f7c8138369e65c6d`
- test(s): `services/projector/tests/unit/test_fact_builders.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `3 passed in 0.02s`

```
..F
=================================== FAILURES ===================================
_ test_every_envelope_has_four_distinct_ids_and_no_id_repeats_across_envelopes _
facts = FactBuilders()
    def test_every_envelope_has_four_distinct_ids_and_no_id_repeats_across_envelopes(
        facts: Any,
    ) -> None:
        seen: dict[Any, str] = {}
        for event_type in FACT_MODELS:
            event = facts.build(event_type)
            ids = [event.event_id, event.aggregate_id, event.correlation_id, event.causation_id]
>           assert len(set(ids)) == 4, f"{event_type}: an id repeats inside one envelope"
E           AssertionError: order.placed.v1: an id repeats inside one envelope
E           assert 3 == 4
E            +  where 3 = len({UUID('00000065-0065-4000-8000-0000000c344b'), UUID('00000066-0066-4000-8000-0000000c533a'), UUID('00000067-0067-4000-8000-0000000c7229')})
E            +    where {UUID('00000065-0065-4000-8000-0000000c344b'), UUID('00000066-0066-4000-8000-0000000c533a'), UUID('00000067-0067-4000-8000-0000000c7229')} = set([UUID('00000065-0065-4000-8000-0000000c344b'), UUID('00000066-0066-4000-8000-0000000c533a'), UUID('00000067-0067-4000-8000-0000000c7229'), UUID('00000067-0067-4000-8000-0000000c7229')])
services/projector/tests/unit/test_fact_builders.py:32: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_fact_builders.py::test_every_envelope_has_four_distinct_ids_and_no_id_repeats_across_envelopes
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 2 passed in 0.08s
```

#### I1-delete-saga-failed-builder

Mutation: delete the `order.saga_failed.v1` builder.

- file `services/projector/tests/conftest.py` sha256 before `a9b7a715ae2d6eff` after mutation `1310a42d9b2e8e46`
- test(s): `services/projector/tests/unit/test_fact_builders.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `3 passed in 0.03s`

```
F
=================================== FAILURES ===================================
________________ test_the_builder_set_equals_the_fact_registry _________________
facts = FactBuilders()
    def test_the_builder_set_equals_the_fact_registry(facts: Any) -> None:
>       assert set(facts.event_types()) == set(FACT_MODELS)
E       AssertionError: assert {'credit.appr...eted.v1', ...} == {'credit.appr...eted.v1', ...}
E         
E         Extra items in the left set:
E         'order.saga_failed.v2'
E         Extra items in the right set:
E         'order.saga_failed.v1'
E         Use -v to get more diff
services/projector/tests/unit/test_fact_builders.py:14: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_fact_builders.py::test_the_builder_set_equals_the_fact_registry
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.07s
```

#### I2-latest-at-the-site

Mutation (S8): change `earliest` to `latest` AT THE ASSIGNMENT SITE (`"auto_offset_reset": "earliest",`), not the docstring mention; the helper records the file's sha256 before and after the edit.

- file `services/projector/src/otc_projector/infrastructure/messaging/kafka_fact_subscriber.py` sha256 before `9cdaa3afcbbca44b` after mutation `a9a9c6d6a2117662`
- test(s): `services/projector/tests/unit/test_kafka_fact_subscriber_options.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `2 passed in 0.05s`

```
F
=================================== FAILURES ===================================
_ test_pr38_the_options_the_runtime_passes_are_earliest_projector_group_client_id_and_no_auto_commit _
default_settings = KafkaSettings(brokers='localhost:9092', client_id='otc-projector', group_id='projector')
    def test_pr38_the_options_the_runtime_passes_are_earliest_projector_group_client_id_and_no_auto_commit(  # noqa: E501
        default_settings: KafkaSettings,
    ) -> None:
        subscriber = KafkaFactSubscriber(default_settings)
        options = subscriber.consumer_options()
>       assert options == EXPECTED, options
E       AssertionError: {'bootstrap_servers': 'localhost:9092', 'group_id': 'projector', 'client_id': 'otc-projector', 'enable_auto_commit': False, ...}
E       assert {'bootstrap_s...': False, ...} == {'bootstrap_s...': False, ...}
E         
E         Omitting 4 identical items, use -vv to show
E         Differing items:
E         {'auto_offset_reset': 'latest'} != {'auto_offset_reset': 'earliest'}
E         Use -v to get more diff
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/tests/unit/test_kafka_fact_subscriber_options.py:69: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_kafka_fact_subscriber_options.py::test_pr38_the_options_the_runtime_passes_are_earliest_projector_group_client_id_and_no_auto_commit
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### I3-bare-return

Mutation (S4): replace the `PR4` log with a bare `return`.

- file `services/projector/src/otc_projector/presentation/projector_facts_consumer.py` sha256 before `c885e9792fae0d32` after mutation `f85daff6e45d532f`
- test(s): `services/projector/tests/unit/test_projector_facts_consumer.py::test_pr4_an_unregistered_event_type_is_logged_and_committed_never_silently`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `2 passed in 0.04s`

```
F
=================================== FAILURES ===================================
_ test_pr4_an_unregistered_event_type_is_logged_and_committed_never_silently[order.shipped.v1] _
facts = FactBuilders()
caplog = <_pytest.logging.LogCaptureFixture object at 0x7f203e9dfb60>
event_type = 'order.shipped.v1'
    @pytest.mark.parametrize("event_type", ["order.shipped.v1", "order.placed.v2"])
    async def test_pr4_an_unregistered_event_type_is_logged_and_committed_never_silently(
        facts: Any, caplog: pytest.LogCaptureFixture, event_type: str
    ) -> None:
        document = valid_document(facts)
        document["eventType"] = event_type
        dispatcher = RecordingDispatcher()
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await task_over(dispatcher).handle(message(json.dumps(document).encode(), offset=5))
        assert dispatcher.sent == []
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
>       assert len(errors) == 1, "an unregistered type must be logged, never silently dropped"
E       AssertionError: an unregistered type must be logged, never silently dropped
E       assert 0 == 1
E        +  where 0 = len([])
services/projector/tests/unit/test_projector_facts_consumer.py:101: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projector_facts_consumer.py::test_pr4_an_unregistered_event_type_is_logged_and_committed_never_silently[order.shipped.v1]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### I3-swallow-payload-error

Mutation (S4): catch the payload error and return.

- file `services/projector/src/otc_projector/presentation/projector_facts_consumer.py` sha256 before `c885e9792fae0d32` after mutation `f69b3c2de17ac563`
- test(s): `services/projector/tests/unit/test_projector_facts_consumer.py::test_pr4_a_registered_type_with_an_invalid_payload_propagates`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
[the failing assertion lines, from the full output]
E       Failed: DID NOT RAISE ValueError
[...]
services/projector/tests/unit/test_projector_facts_consumer.py:112: Failed
------------------------------ Captured log call -------------------------------
ERROR    otc_projector.presentation.projector_facts_consumer:projector_facts_consumer.py:73 unregistered fact type acknowledged without processing: 11 validation errors for OrderPlacedEvent
payload.orderReference
  Field required [type=missing, input_value={}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
payload.retailerCode
  Field required [type=missing, input_value={}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
payload.companyCode
  Field required [type=missing, input_value={}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
payload.buyerGln
  Field required [type=missing, input_value={}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
payload.supplierGln
  Field required [type=missing, input_value={}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
payload.currency
  Field required [type=missing, input_value={}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
payload.orderDate
  Field required [type=missing, input_value={}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
payload.lines
  Field required [type=missing, input_value={}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
payload.initialAmount
  Field required [type=missing, input_value={}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
payload.initialDiscount
  Field required [type=missing, input_value={}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
payload.totalAmount
  Field required [type=missing, input_value={}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projector_facts_consumer.py::test_pr4_a_registered_type_with_an_invalid_payload_propagates
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.08s
```

#### I4-commit-before-handler

Mutation: commit before the handler.

- file `services/projector/src/otc_projector/infrastructure/messaging/kafka_fact_subscriber.py` sha256 before `9cdaa3afcbbca44b` after mutation `3753e24694528b6f`
- test(s): `services/projector/tests/integration/test_offset_contract.py::test_pr38_a_raising_handler_leaves_the_committed_offset_unchanged_read_from_the_broker`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 6.69s`

```
                "PROJECTOR_KAFKA_CLIENT_ID": f"offset-client-{group}",
                "PROJECTOR_CONSUMER_GROUP": group,
            }
        )
        subscriber = KafkaFactSubscriber(settings, topics=(topic,))
        stop = asyncio.Event()
        task = asyncio.create_task(subscriber.run(handler, stop), name="offset-contract-subscriber")
        try:
            await until("the first (raising) handler call", first_failed)
            # the handler has RAISED: the broker's committed offsets must not have moved
>           assert await committed(bootstrap, group) == {}, (
                "an offset was committed although the handler raised"
            )
E           AssertionError: an offset was committed although the handler raised
E           assert {('offset-con...edbcc', 0): 1} == {}
E             
E             Left contains 1 more item:
E             {('offset-contract-988edbcc', 0): 1}
E             Use -v to get more diff
services/projector/tests/integration/test_offset_contract.py:94: AssertionError
------------------------------ Captured log call -------------------------------
ERROR    aiokafka.cluster:cluster.py:262 Topic offset-contract-988edbcc not found in cluster metadata
ERROR    aiokafka.cluster:cluster.py:262 Topic offset-contract-988edbcc not found in cluster metadata
ERROR    aiokafka.consumer.group_coordinator:group_coordinator.py:566 Group Coordinator Request failed: [Error 15] GroupCoordinatorNotAvailableError
WARNING  aiokafka.consumer.group_coordinator:group_coordinator.py:522 Marking the coordinator dead (node 1)for group offset-group-7fb7abb7.
WARNING  aiokafka.consumer.group_coordinator:group_coordinator.py:522 Marking the coordinator dead (node 1)for group offset-group-7fb7abb7.
WARNING  aiokafka.consumer.group_coordinator:group_coordinator.py:522 Marking the coordinator dead (node 1)for group offset-group-7fb7abb7.
ERROR    otc_projector.messaging.kafka_fact_subscriber:kafka_fact_subscriber.py:177 fact handler failed; the offset is not committed and the record will be delivered again
Traceback (most recent call last):
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/src/otc_projector/infrastructure/messaging/kafka_fact_subscriber.py", line 166, in _consume
    await handler(
    ...<8 lines>...
    )
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/projector/tests/integration/test_offset_contract.py", line 76, in handler
    raise RuntimeError("the handler raises on its first call")
RuntimeError: the handler raises on its first call
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_offset_contract.py::test_pr38_a_raising_handler_leaves_the_committed_offset_unchanged_read_from_the_broker
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 5.75s
```

#### I4-latest

Mutation: switch to `latest` (the second case fails).

- file `services/projector/src/otc_projector/infrastructure/messaging/kafka_fact_subscriber.py` sha256 before `9cdaa3afcbbca44b` after mutation `a9a9c6d6a2117662`
- test(s): `services/projector/tests/integration/test_offset_contract.py::test_pr5_a_fact_produced_before_the_group_ever_subscribed_is_projected`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 9.35s`

```
    ) -> None:
        order = uuid.UUID("0a0b0c0d-7777-4000-8000-0000000000a1")
        reference = new_reference()
        # produced FIRST: the group below has never existed
        await produce(
            [
                facts.build(
                    "order.placed.v1", correlation_id=order, payload={"order_reference": reference}
                )
            ]
        )
        group = f"never-used-{uuid.uuid4().hex[:8]}"
        model = runtime_env.read_model()
        try:
            await runtime_env.start(group)
            deadline = asyncio.get_running_loop().time() + 60
            document: dict[str, Any] | None = None
            while asyncio.get_running_loop().time() < deadline:
                document = await model.collection.find_one({"_id": str(order)})
                if document is not None and document["headerComplete"]:
                    break
                await asyncio.sleep(0.1)
            else:
>               pytest.fail(
                    "PR5: a fact produced before the group subscribed was not projected in 60 s"
                )
E               Failed: PR5: a fact produced before the group subscribed was not projected in 60 s
services/projector/tests/integration/test_offset_contract.py:137: Failed
------------------------------ Captured log call -------------------------------
WARNING  aiokafka.producer.sender:sender.py:870 Got error produce response on topic-partition TopicPartition(topic='otc-test-e693818cbd-orders-facts', partition=2), retrying. Error: <class 'aiokafka.errors.NotLeaderForPartitionError'>
ERROR    aiokafka.consumer.group_coordinator:group_coordinator.py:566 Group Coordinator Request failed: [Error 15] GroupCoordinatorNotAvailableError
WARNING  aiokafka.consumer.group_coordinator:group_coordinator.py:522 Marking the coordinator dead (node 1)for group never-used-facd8ec9.
WARNING  aiokafka.consumer.group_coordinator:group_coordinator.py:522 Marking the coordinator dead (node 1)for group never-used-facd8ec9.
WARNING  aiokafka.consumer.group_coordinator:group_coordinator.py:522 Marking the coordinator dead (node 1)for group never-used-facd8ec9.
---------------------------- Captured log teardown -----------------------------
WARNING  otc_projector.composition:composition.py:144 NATS disconnected
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_offset_contract.py::test_pr5_a_fact_produced_before_the_group_ever_subscribed_is_projected
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 69.66s (0:01:09)
```

#### J-isolation-real-topics

Mutation: point the runtime at the REAL topics again (no subscriber override) after another service's test left two `order.placed.v1` with one `orderReference` on `otc.orders.facts.v1` (the scratch polluter runs first, in the same session). EXPECTED: the control run (the fix in place) passes, the mutated run fails for another test's fact.

- file `services/projector/tests/integration/conftest.py` sha256 before `87de5a5664836d51` after mutation `92f63db0d3f645ef`
- scratch file created then removed: `services/projector/tests/integration/test_aaa_pollution.py`
- test(s): `services/projector/tests/integration/test_aaa_pollution.py services/projector/tests/integration/test_offset_contract.py::test_pr5_a_fact_produced_before_the_group_ever_subscribed_is_projected`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run (the helper had already removed the scratch polluter, so it ran nothing: exit 4): the CONTROL was run by hand with the polluter re-created and the fix in place: see the last block of this entry

```
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/.venv/lib/python3.14/site-packages/pymongo/asynchronous/collection.py", line 598, in _command
    return await conn.command(
           ^^^^^^^^^^^^^^^^^^^
    ...<14 lines>...
    )
    ^
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/.venv/lib/python3.14/site-packages/pymongo/asynchronous/helpers.py", line 51, in inner
    return await func(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/.venv/lib/python3.14/site-packages/pymongo/asynchronous/pool.py", line 396, in command
    return await run_command(
           ^^^^^^^^^^^^^^^^^^
    ...<19 lines>...
    )
    ^
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/.venv/lib/python3.14/site-packages/pymongo/asynchronous/command_runner.py", line 440, in run_command
    docs, _, _ = await _run_command(
                 ^^^^^^^^^^^^^^^^^^^
    ...<18 lines>...
    )
    ^
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/.venv/lib/python3.14/site-packages/pymongo/asynchronous/command_runner.py", line 214, in _run_command
    helpers_shared._check_command_response(
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        response_doc,
        ^^^^^^^^^^^^^
    ...<3 lines>...
        pool_opts=pool_opts,
        ^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/.venv/lib/python3.14/site-packages/pymongo/helpers_shared.py", line 317, in _check_command_response
    raise DuplicateKeyError(errmsg, code, response, max_wire_version)
pymongo.errors.DuplicateKeyError: Plan executor error during findAndModify :: caused by :: E11000 duplicate key error collection: otc_test_8df4f9288d88465d8213a465b9f4efc9.order_timeline index: uq_order_reference dup key: { orderReference: "ORD-424242" }, full error: {'ok': 0.0, 'errmsg': 'Plan executor error during findAndModify :: caused by :: E11000 duplicate key error collection: otc_test_8df4f9288d88465d8213a465b9f4efc9.order_timeline index: uq_order_reference dup key: { orderReference: "ORD-424242" }', 'code': 11000, 'codeName': 'DuplicateKey', 'keyPattern': {'orderReference': 1}, 'keyValue': {'orderReference': 'ORD-424242'}}
---------------------------- Captured log teardown -----------------------------
WARNING  otc_projector.composition:composition.py:144 NATS disconnected
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_offset_contract.py::test_pr5_a_fact_produced_before_the_group_ever_subscribed_is_projected
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 1 passed in 69.71s (0:01:09)
```

Control, run by hand (the polluter in place, the fix in place, the same two tests): `2 passed in 10.22s`

#### J1-append-no-resort

Mutation: append instead of re-sorting.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `e14f1a5864012e08`
- test(s): `services/projector/tests/integration/test_timeline_projection.py::test_r50_appends_an_entry_carrying_event_id_event_type_occurred_at_and_a_summary_and_presents_the_timeline_ordered_by_occurred_at_rather_than_by_arrival`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.80s`

```
F
=================================== FAILURES ===================================
_ test_r50_appends_an_entry_carrying_event_id_event_type_occurred_at_and_a_summary_and_presents_the_timeline_ordered_by_occurred_at_rather_than_by_arrival _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36082'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_3f7c7af71e924d298858fd8051393922', uri='mongodb://otc_test:otc_test_password@localhost:36082/?authSource=admin')
facts = FactBuilders()
    async def test_r50_appends_an_entry_carrying_event_id_event_type_occurred_at_and_a_summary_and_presents_the_timeline_ordered_by_occurred_at_rather_than_by_arrival(  # noqa: E501
        read_model: Any, facts: Any
    ) -> None:
        placed, reserved, approved, confirmed, despatched = chain(facts)
        # arrival: approved, despatched, placed, confirmed, reserved: neither occurredAt order
        # (placed, reserved, approved, confirmed, despatched) nor the causal order (the same)
        arrival = [approved, despatched, placed, confirmed, reserved]
        for event in arrival:
            await read_model.apply(event)
        document = await read_model.document(ORDER)
        entries = document["events"]
>       assert [e["eventId"] for e in entries] == [
            str(e.event_id) for e in (placed, reserved, approved, confirmed, despatched)
        ], "the timeline is not ordered by occurredAt"
E       AssertionError: the timeline is not ordered by occurredAt
E       assert ['000a0003-00...0000262a07a2'] == ['000a0001-00...0000262a1315']
E         
E         At index 0 diff: '000a0003-0000-4000-8000-0000262a0b73' != '000a0001-0000-4000-8000-0000262a03d1'
E         Use -v to get more diff
services/projector/tests/integration/test_timeline_projection.py:61: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_timeline_projection.py::test_r50_appends_an_entry_carrying_event_id_event_type_occurred_at_and_a_summary_and_presents_the_timeline_ordered_by_occurred_at_rather_than_by_arrival
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.87s
```

#### J1-updated-at-incoming

Mutation: replace `updatedAt`'s `$max` with the incoming value.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `6ec2b731e92d6fcd`
- test(s): `services/projector/tests/integration/test_timeline_projection.py::test_pr14_updated_at_is_the_greatest_occurred_at_not_the_latest_arrival`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.79s`

```
F
=================================== FAILURES ===================================
___ test_pr14_updated_at_is_the_greatest_occurred_at_not_the_latest_arrival ____
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36078'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_4268ad794a24479eafbdf7fa1604aabe', uri='mongodb://otc_test:otc_test_password@localhost:36078/?authSource=admin')
facts = FactBuilders()
    async def test_pr14_updated_at_is_the_greatest_occurred_at_not_the_latest_arrival(
        read_model: Any, facts: Any
    ) -> None:
        placed, reserved, approved, *_ = chain(facts)
        await read_model.apply(approved)  # t=3 arrives first
        assert (await read_model.document(ORDER))["updatedAt"] == "2026-05-01T09:00:03.103Z"
        await read_model.apply(placed)  # an OLDER fact arrives last
        await read_model.apply(reserved)
        document = await read_model.document(ORDER)
>       assert document["updatedAt"] == "2026-05-01T09:00:03.103Z", (
            "updatedAt followed the latest arrival instead of the greatest occurredAt"
        )
E       AssertionError: updatedAt followed the latest arrival instead of the greatest occurredAt
E       assert '2026-05-01T09:00:02.102Z' == '2026-05-01T09:00:03.103Z'
E         
E         - 2026-05-01T09:00:03.103Z
E         ?                   ^   ^
E         + 2026-05-01T09:00:02.102Z
E         ?                   ^   ^
services/projector/tests/integration/test_timeline_projection.py:119: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_timeline_projection.py::test_pr14_updated_at_is_the_greatest_occurred_at_not_the_latest_arrival
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 4.80s
```

#### J2-gte

Mutation: replace the strict `$gt` with `$gte`.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `a478ac1469983d22`
- test(s): `services/projector/tests/integration/test_out_of_order_facts.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `5 passed in 4.01s`

```
.F
=================================== FAILURES ===================================
_ test_pr12_a_status_less_fact_on_an_absent_order_keeps_the_placeholder_status _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36088'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_222170743b894b7c926ff3f55102bcce', uri='mongodb://otc_test:otc_test_password@localhost:36088/?authSource=admin')
facts = FactBuilders()
    async def test_pr12_a_status_less_fact_on_an_absent_order_keeps_the_placeholder_status(
        read_model: Any, facts: Any
    ) -> None:
        """A rank-0 fact against a rank-0 placeholder: a `>=` instead of `>` would write `null`."""
        event = facts.build("stock.rejected.v1", correlation_id=ORDER, occurred_at=at(2))
        await read_model.apply(event)
        document = await read_model.document(ORDER)
>       assert document["status"] == "placed", f"the status became {document['status']!r}"
E       AssertionError: the status became None
E       assert None == 'placed'
services/projector/tests/integration/test_out_of_order_facts.py:69: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_out_of_order_facts.py::test_pr12_a_status_less_fact_on_an_absent_order_keeps_the_placeholder_status
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 1 passed in 3.87s
```

#### J2-no-cond

Mutation: drop the status `$cond`.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `4755734069244198`
- test(s): `services/projector/tests/integration/test_out_of_order_facts.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `5 passed in 3.92s`

```
F
=================================== FAILURES ===================================
_ test_r52_appends_the_timeline_entry_without_regressing_the_document_status_or_overwriting_newer_references _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36092'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_9a7541eadec44b08aafaf8221ac6e2a3', uri='mongodb://otc_test:otc_test_password@localhost:36092/?authSource=admin')
facts = FactBuilders()
    async def test_r52_appends_the_timeline_entry_without_regressing_the_document_status_or_overwriting_newer_references(  # noqa: E501
        read_model: Any, facts: Any
    ) -> None:
        despatched = facts.build(
            "order.despatched.v1",
            correlation_id=ORDER,
            occurred_at=at(5),
            payload={"despatch_reference": "DES-717171"},
        )
        placed = facts.build("order.placed.v1", correlation_id=ORDER, occurred_at=at(1))
        await read_model.apply(despatched)  # the document does not exist: a placeholder is created
        after_first = await read_model.document(ORDER)
        assert after_first["status"] == "despatched"
        assert after_first["headerComplete"] is False
        await read_model.apply(placed)  # placed (rank 1) after despatched (rank 5)
        document = await read_model.document(ORDER)
>       assert document["status"] == "despatched", "a late order.placed regressed the status"
E       AssertionError: a late order.placed regressed the status
E       assert 'placed' == 'despatched'
E         
E         - despatched
E         + placed
services/projector/tests/integration/test_out_of_order_facts.py:41: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_out_of_order_facts.py::test_r52_appends_the_timeline_entry_without_regressing_the_document_status_or_overwriting_newer_references
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.84s
```

#### J3-retailer-none

Mutation: write the placeholder's `retailer` as `None` (record that `name`/`gln` vanish).

- file `services/projector/src/otc_projector/infrastructure/persistence/read_model_document.py` sha256 before `9de057e71dce8149` after mutation `1e900e792352dbea`
- test(s): `services/projector/tests/integration/test_placeholder_document.py::test_pr9_master_data_names_stay_null_in_a_projected_document`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.79s`

```
F
=================================== FAILURES ===================================
_________ test_pr9_master_data_names_stay_null_in_a_projected_document _________
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36112'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_ab91539421f44a15b82e14fd934eec66', uri='mongodb://otc_test:otc_test_password@localhost:36112/?authSource=admin')
facts = FactBuilders()
    async def test_pr9_master_data_names_stay_null_in_a_projected_document(
        read_model: Any, facts: Any
    ) -> None:
        await read_model.apply(facts.build("order.placed.v1", correlation_id=ORDER))
        document = await read_model.document(ORDER)
        for name in ("retailer", "company"):
            assert isinstance(document[name], dict), f"{name} must be an object, not {document[name]!r}"
        for name in ("retailer", "company"):
>           assert set(document[name]) == {"code", "name", "gln"}, (
                f"{name} lost keys: {sorted(document[name])}"
            )
E           AssertionError: retailer lost keys: ['code', 'gln']
E           assert {'code', 'gln'} == {'code', 'gln', 'name'}
E             
E             Extra items in the right set:
E             'name'
E             Use -v to get more diff
services/projector/tests/integration/test_placeholder_document.py:48: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_placeholder_document.py::test_pr9_master_data_names_stay_null_in_a_projected_document
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.84s
```

#### J4-no-depth

Mutation (S6): remove `__depth` from `sortBy`. Both cases are named; the run is not stopped at the first failure (see the second run below).

- file `services/projector/src/otc_projector/infrastructure/persistence/timeline_order.py` sha256 before `9e266433d4437cff` after mutation `0e511b5b7f731dc9`
- test(s): `services/projector/tests/integration/test_timeline_causal_order.py::test_r28_stock_released_precedes_the_order_cancelled_that_names_it_with_adversarial_event_ids services/projector/tests/integration/test_timeline_causal_order.py::test_r24_the_completion_triple_is_stored_in_causal_order_with_adversarial_event_ids`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `2 passed in 3.84s`

```
F
=================================== FAILURES ===================================
_ test_r28_stock_released_precedes_the_order_cancelled_that_names_it_with_adversarial_event_ids _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36100'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_f8f3b2cc4ffe477b8e96f044778b30a0', uri='mongodb://otc_test:otc_test_password@localhost:36100/?authSource=admin')
facts = FactBuilders()
    async def test_r28_stock_released_precedes_the_order_cancelled_that_names_it_with_adversarial_event_ids(  # noqa: E501
        read_model: Any, facts: Any
    ) -> None:
        released_id = eid("ffffffff-0000-4000-8000-000000000001")  # the LARGEST id, yet first
        cancelled_id = eid("00000000-0000-4000-8000-000000000002")  # the smallest id, yet last
        released = facts.build(
            "stock.released.v1",
            correlation_id=ORDER,
            event_id=released_id,
            causation_id=eid("11111111-0000-4000-8000-0000000000aa"),
            occurred_at=INSTANT,
        )
        cancelled = facts.build(
            "order.cancelled.v1",
            correlation_id=ORDER,
            event_id=cancelled_id,
            causation_id=released_id,
            occurred_at=INSTANT,
        )
        await read_model.apply(cancelled)  # delivered in the inverting order
        await read_model.apply(released)
        document = await read_model.document(ORDER)
>       assert [e["eventId"] for e in document["events"]] == [str(released_id), str(cancelled_id)], (
            "R28: stock.released must precede the order.cancelled that names it"
        )
E       AssertionError: R28: stock.released must precede the order.cancelled that names it
E       assert ['00000000-00...000000000001'] == ['ffffffff-00...000000000002']
E         
E         At index 0 diff: '00000000-0000-4000-8000-000000000002' != 'ffffffff-0000-4000-8000-000000000001'
E         Use -v to get more diff
services/projector/tests/integration/test_timeline_causal_order.py:52: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_timeline_causal_order.py::test_r28_stock_released_precedes_the_order_cancelled_that_names_it_with_adversarial_event_ids
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.82s
```

#### J4-no-depth-r24

Mutation (S6), second case: remove `__depth` from `sortBy` and run R24's case alone.

- file `services/projector/src/otc_projector/infrastructure/persistence/timeline_order.py` sha256 before `9e266433d4437cff` after mutation `0e511b5b7f731dc9`
- test(s): `services/projector/tests/integration/test_timeline_causal_order.py::test_r24_the_completion_triple_is_stored_in_causal_order_with_adversarial_event_ids`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.88s`

```
        completed_id = eid("aaaaaaaa-0000-4000-8000-000000000003")
        payment = facts.build(
            "payment.received.v1",
            correlation_id=ORDER,
            event_id=payment_id,
            causation_id=eid("11111111-0000-4000-8000-0000000000bb"),
            occurred_at=INSTANT,
        )
        release = facts.build(
            "credit.released.v1",
            correlation_id=ORDER,
            event_id=release_id,
            causation_id=payment_id,
            occurred_at=INSTANT,
        )
        completed = facts.build(
            "order.completed.v1",
            correlation_id=ORDER,
            event_id=completed_id,
            causation_id=release_id,
            occurred_at=INSTANT,
        )
        for event in (completed, release, payment):  # fully reversed
            await read_model.apply(event)
        document = await read_model.document(ORDER)
>       assert [e["eventId"] for e in document["events"]] == [
            str(payment_id),
            str(release_id),
            str(completed_id),
        ], "R24: payment.received, credit.released, order.completed must be stored in causal order"
E       AssertionError: R24: payment.received, credit.released, order.completed must be stored in causal order
E       assert ['aaaaaaaa-00...000000000001'] == ['cccccccc-00...000000000003']
E         
E         At index 0 diff: 'aaaaaaaa-0000-4000-8000-000000000003' != 'cccccccc-0000-4000-8000-000000000001'
E         Use -v to get more diff
services/projector/tests/integration/test_timeline_causal_order.py:87: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_timeline_causal_order.py::test_r24_the_completion_triple_is_stored_in_causal_order_with_adversarial_event_ids
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.80s
```

#### J5-drop-min-cap

Mutation: drop the `$min` cap. EXPECTED TO SURVIVE (see the finding): the `$reduce` runs exactly |entries| rounds and a depth gains at most one per round, so the cap can never bind.

- file `services/projector/src/otc_projector/infrastructure/persistence/timeline_order.py` sha256 before `9e266433d4437cff` after mutation `55bdb0d237af5e71`
- test(s): `services/projector/tests/integration/test_timeline_causal_order.py::test_pr31_a_cycle_a_foreign_cause_and_a_missing_causation_id_all_terminate_with_every_entry_once services/projector/tests/integration/test_timeline_causal_order.py::test_pr10_the_pipeline_agrees_with_the_reference_rule_on_generated_entry_sets`
- mutated run exit code: **0** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `2 passed in 4.34s`

```
..                                                                       [100%]
2 passed in 4.34s
```

#### J5-drop-ne-clause

Mutation: drop the `$ne` self-edge clause (differential test).

- file `services/projector/src/otc_projector/infrastructure/persistence/timeline_order.py` sha256 before `9e266433d4437cff` after mutation `15b0ae605d62645c`
- test(s): `services/projector/tests/integration/test_timeline_causal_order.py::test_pr10_the_pipeline_agrees_with_the_reference_rule_on_generated_entry_sets`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 4.38s`

```
F
=================================== FAILURES ===================================
_ test_pr10_the_pipeline_agrees_with_the_reference_rule_on_generated_entry_sets _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36120'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_cd791418dc294bbd9c3a2a0da120f3c0', uri='mongodb://otc_test:otc_test_password@localhost:36120/?authSource=admin')
    async def test_pr10_the_pipeline_agrees_with_the_reference_rule_on_generated_entry_sets(
        read_model: Any,
    ) -> None:
        print(f"differential seed {SEED}, {SETS} sets")
        disagreements = []
        for index, entries in enumerate(generated_sets(SEED, SETS)):
            expected = [e.event_id for e in causal_order(entries)]
            actual = await server_order(read_model, entries)
            if actual != expected:
                disagreements.append((index, entries, expected, actual))
>       assert disagreements == [], (
            f"seed {SEED}: the server disagrees with the reference rule on set "
            f"{disagreements[0][0]}: entries {disagreements[0][1]}, "
            f"reference {disagreements[0][2]}, server {disagreements[0][3]}"
        )
E       AssertionError: seed 20261011: the server disagrees with the reference rule on set 5: entries [TimelinePosition(event_id='e00253', occurred_at='2026-05-03T09:00:00.001Z', causation_id='foreign-command-id'), TimelinePosition(event_id='e04913', occurred_at='2026-05-03T09:00:00.001Z', causation_id='e08426'), TimelinePosition(event_id='e05092', occurred_at='2026-05-03T09:00:00.000Z', causation_id='e07250'), TimelinePosition(event_id='e07250', occurred_at='2026-05-03T09:00:00.002Z', causation_id='e05092'), TimelinePosition(event_id='e08426', occurred_at='2026-05-03T09:00:00.002Z', causation_id='e05092'), TimelinePosition(event_id='e03183', occurred_at='2026-05-03T09:00:00.001Z', causation_id='e03183')], reference ['e05092', 'e00253', 'e03183', 'e04913', 'e07250', 'e08426'], server ['e05092', 'e00253', 'e04913', 'e03183', 'e07250', 'e08426']
E       assert [(5, [Timelin...01484']), ...] == []
E         
E         Left contains 84 more items, first extra item: (5, [TimelinePosition(event_id='e00253', occurred_at='2026-05-03T09:00:00.001Z', causation_id='foreign-command-id'), T...5092', 'e00253', 'e03183', 'e04913', 'e07250', 'e08426'], ['e05092', 'e00253', 'e04913', 'e03183', 'e07250', 'e08426'])
E         Use -v to get more diff
services/projector/tests/integration/test_timeline_causal_order.py:156: AssertionError
----------------------------- Captured stdout call -----------------------------
differential seed 20261011, 250 sets
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_timeline_causal_order.py::test_pr10_the_pipeline_agrees_with_the_reference_rule_on_generated_entry_sets
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 4.15s
```

#### J5-drop-ne-clause-pr31

Mutation: drop the `$ne` self-edge clause (PR31 case).

- file `services/projector/src/otc_projector/infrastructure/persistence/timeline_order.py` sha256 before `9e266433d4437cff` after mutation `15b0ae605d62645c`
- test(s): `services/projector/tests/integration/test_timeline_causal_order.py::test_pr31_a_cycle_a_foreign_cause_and_a_missing_causation_id_all_terminate_with_every_entry_once`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.80s`

```
            ("order.completed.v1", f, eid("88888888-0000-4000-8000-000000000008")),
        ]
        for event_type, event_id, cause in spec:
            await read_model.apply(
                facts.build(
                    event_type,
                    correlation_id=ORDER,
                    event_id=event_id,
                    causation_id=cause,
                    occurred_at=INSTANT,
                )
            )
        document = await read_model.document(ORDER)
        stored = [e["eventId"] for e in document["events"]]
        assert sorted(stored) == sorted(str(x) for x in (a, b, c, d, f)), "an entry was lost or doubled"
        # a second apply of an unrelated fact (a later instant) leaves the stored order identical
        later = facts.build(
            "credit.released.v1",
            correlation_id=ORDER,
            occurred_at=datetime(2026, 5, 3, 9, 0, 5, tzinfo=UTC),
        )
        await read_model.apply(later)
        again = [e["eventId"] for e in (await read_model.document(ORDER))["events"]]
        assert again[:-1] == stored, "applying an unrelated fact reordered the earlier entries"
        assert again[-1] == str(later.event_id)
        # and the reference rule predicts exactly the stored order
        entries = [
            TimelinePosition(str(event_id), "2026-05-03T09:00:00.123Z", str(cause))
            for _, event_id, cause in spec
        ]
>       assert [e.event_id for e in causal_order(entries)] == stored
E       AssertionError: assert ['30000000-00...000000000002'] == ['30000000-00...000000000004']
E         
E         At index 1 diff: '40000000-0000-4000-8000-000000000004' != '50000000-0000-4000-8000-000000000005'
E         Use -v to get more diff
services/projector/tests/integration/test_timeline_causal_order.py:228: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_timeline_causal_order.py::test_pr31_a_cycle_a_foreign_cause_and_a_missing_causation_id_all_terminate_with_every_entry_once
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 4.91s
```

#### J6-clock-updated-at

Mutation: stamp `updatedAt` from a clock (`$$NOW`).

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `25c17d4cae4dd190`
- test(s): `services/projector/tests/integration/test_replay_determinism.py::test_pr15_shuffled_and_duplicated_application_yields_byte_identical_documents`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 27.50s`

```
F
=================================== FAILURES ===================================
_ test_pr15_shuffled_and_duplicated_application_yields_byte_identical_documents _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36138'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_70dc76f217dd4f3f8b9444ed2eb68e25', uri='mongodb://otc_test:otc_test_password@localhost:36138/?authSource=admin')
facts = FactBuilders()
    async def test_pr15_shuffled_and_duplicated_application_yields_byte_identical_documents(
        read_model: Any, facts: Any
    ) -> None:
        order = uuid.UUID(int=0x15CCCC03)
        events = six_facts(facts, order, 3, "ORD-710001")
        reference: bytes | None = None
        for permutation in itertools.permutations(range(6)):
            await read_model.collection.delete_many({})
            sequence = [events[i] for i in permutation]
            for event in [*sequence, *reversed(sequence)]:  # a full second pass: all duplicates
                await read_model.apply(event)
            stored = await read_model.raw(order)
            if reference is None:
                reference = stored
>           assert stored == reference, f"permutation {permutation} produced different bytes"
E           AssertionError: permutation (0, 1, 2, 3, 5, 4) produced different bytes
E           assert b'\xee\t\x00\....572Z\x00\x00' == b'\xee\t\x00\....536Z\x00\x00'
E             
E             At index 2537 diff: b'7' != b'3'
E             Use -v to get more diff
services/projector/tests/integration/test_replay_determinism.py:232: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_replay_determinism.py::test_pr15_shuffled_and_duplicated_application_yields_byte_identical_documents
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 4.08s
```

#### J6-no-sortarray

Mutation: drop `processedEventKeys`' `$sortArray`.

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `a85df371cde6aeac`
- test(s): `services/projector/tests/integration/test_replay_determinism.py::test_pr15_shuffled_and_duplicated_application_yields_byte_identical_documents`
- mutated run exit code: **0** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 22.95s`

```
.                                                                        [100%]
1 passed in 25.34s
```

#### J7-exclusion-detail

Mutation: remove `events[].detail` from the exclusion.

- file `services/projector/tests/integration/test_seeded_oracle_parity.py` sha256 before `54031e54d291814f` after mutation `4b5b115023a9efc4`
- test(s): `services/projector/tests/integration/test_seeded_oracle_parity.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `8 passed in 4.71s`

```
.....F
=================================== FAILURES ===================================
_ test_pr44_projecting_each_seeded_sagas_facts_reproduces_the_seeds_stored_document_except_the_declared_set[5] _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36152'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_05ef038ab9694138956851053c888e99', uri='mongodb://otc_test:otc_test_password@localhost:36152/?authSource=admin')
saga_facts = <function facts_of at 0x7e0fa3b92820>, saga_index = 5
    @pytest.mark.parametrize("saga_index", range(6))
    async def test_pr44_projecting_each_seeded_sagas_facts_reproduces_the_seeds_stored_document_except_the_declared_set(  # noqa: E501
        read_model: Any, saga_facts: Any, saga_index: int
    ) -> None:
        saga = SAGAS[saga_index]
        for event in saga_facts(saga):
            await read_model.apply(event)
        projected: dict[str, Any] = bson.decode(await read_model.raw(saga.order_id))
        seeded = await seeded_document(
            read_model.uri, f"{read_model.database}_oracle_{uuid.uuid4().hex[:6]}", saga_index
        )
        skipped: set[str] = set()
        differences = compare("", projected, seeded, EXCLUDED, skipped)
>       assert differences == [], f"saga {saga_index} ({saga.order_reference}): {differences[:5]}"
E       AssertionError: saga 5 (ORD-000006): ["events[3]: element sequence ['eventId', 'eventType', 'occurredAt', 'summary', 'detail', 'causationId'] != ['eventId', 'eventType', 'occurredAt', 'summary', 'causationId']", "events[4].detail: element sequence ['cancellationReason', 'compensationSteps'] != ['cancellationReason']"]
E       assert ["events[3]: ...tionReason']"] == []
E         
E         Left contains 2 more items, first extra item: "events[3]: element sequence ['eventId', 'eventType', 'occurredAt', 'summary', 'detail', 'causationId'] != ['eventId', 'eventType', 'occurredAt', 'summary', 'causationId']"
E         Use -v to get more diff
services/projector/tests/integration/test_seeded_oracle_parity.py:116: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_seeded_oracle_parity.py::test_pr44_projecting_each_seeded_sagas_facts_reproduces_the_seeds_stored_document_except_the_declared_set[5]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 5 passed in 4.36s
```

#### J7-int64

Mutation: write `totals` as `bson.Int64` always (ledger L23).

- file `services/projector/src/otc_projector/infrastructure/persistence/delta_to_pipeline.py` sha256 before `851603f7b00e8507` after mutation `fe419eaa4e2efadf`
- test(s): `services/projector/tests/integration/test_seeded_oracle_parity.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `8 passed in 4.66s`

```
F
=================================== FAILURES ===================================
_ test_pr44_projecting_each_seeded_sagas_facts_reproduces_the_seeds_stored_document_except_the_declared_set[0] _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36156'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_7e19047e17ea49b7b5e2dc9e6dd681d7', uri='mongodb://otc_test:otc_test_password@localhost:36156/?authSource=admin')
saga_facts = <function facts_of at 0x70a7f4c52820>, saga_index = 0
    @pytest.mark.parametrize("saga_index", range(6))
    async def test_pr44_projecting_each_seeded_sagas_facts_reproduces_the_seeds_stored_document_except_the_declared_set(  # noqa: E501
        read_model: Any, saga_facts: Any, saga_index: int
    ) -> None:
        saga = SAGAS[saga_index]
        for event in saga_facts(saga):
            await read_model.apply(event)
        projected: dict[str, Any] = bson.decode(await read_model.raw(saga.order_id))
        seeded = await seeded_document(
            read_model.uri, f"{read_model.database}_oracle_{uuid.uuid4().hex[:6]}", saga_index
        )
        skipped: set[str] = set()
        differences = compare("", projected, seeded, EXCLUDED, skipped)
>       assert differences == [], f"saga {saga_index} ({saga.order_reference}): {differences[:5]}"
E       AssertionError: saga 0 (ORD-000001): ['totals.initialAmount: type Int64 != int (16130 / 16130)', 'totals.initialDiscount: type Int64 != int (0 / 0)', 'totals.totalAmount: type Int64 != int (16130 / 16130)']
E       assert ['totals.init...130 / 16130)'] == []
E         
E         Left contains 3 more items, first extra item: 'totals.initialAmount: type Int64 != int (16130 / 16130)'
E         Use -v to get more diff
services/projector/tests/integration/test_seeded_oracle_parity.py:116: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_seeded_oracle_parity.py::test_pr44_projecting_each_seeded_sagas_facts_reproduces_the_seeds_stored_document_except_the_declared_set[0]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.94s
```

#### J7-rank

Mutation: change one rank on the projector side (`completed` 98 -> 97). B2 is run under the same mutation below.

- file `services/projector/src/otc_projector/domain/status_rank.py` sha256 before `6d152af7714876b8` after mutation `ea9dbb36c5bede6a`
- test(s): `services/projector/tests/integration/test_seeded_oracle_parity.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `8 passed in 4.76s`

```
F
=================================== FAILURES ===================================
_ test_pr44_projecting_each_seeded_sagas_facts_reproduces_the_seeds_stored_document_except_the_declared_set[0] _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36148'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_38b5dd13ff914752b356185a487010f9', uri='mongodb://otc_test:otc_test_password@localhost:36148/?authSource=admin')
saga_facts = <function facts_of at 0x7df4ec84e820>, saga_index = 0
    @pytest.mark.parametrize("saga_index", range(6))
    async def test_pr44_projecting_each_seeded_sagas_facts_reproduces_the_seeds_stored_document_except_the_declared_set(  # noqa: E501
        read_model: Any, saga_facts: Any, saga_index: int
    ) -> None:
        saga = SAGAS[saga_index]
        for event in saga_facts(saga):
            await read_model.apply(event)
        projected: dict[str, Any] = bson.decode(await read_model.raw(saga.order_id))
        seeded = await seeded_document(
            read_model.uri, f"{read_model.database}_oracle_{uuid.uuid4().hex[:6]}", saga_index
        )
        skipped: set[str] = set()
        differences = compare("", projected, seeded, EXCLUDED, skipped)
>       assert differences == [], f"saga {saga_index} ({saga.order_reference}): {differences[:5]}"
E       AssertionError: saga 0 (ORD-000001): ['statusRank: value 97 != 98']
E       assert ['statusRank: value 97 != 98'] == []
E         
E         Left contains one more item: 'statusRank: value 97 != 98'
E         Use -v to get more diff
services/projector/tests/integration/test_seeded_oracle_parity.py:116: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_seeded_oracle_parity.py::test_pr44_projecting_each_seeded_sagas_facts_reproduces_the_seeds_stored_document_except_the_declared_set[0]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.91s
```

#### J7-rank-b2

Same mutation, B2 (PR40): fails too.

- file `services/projector/src/otc_projector/domain/status_rank.py` sha256 before `6d152af7714876b8` after mutation `ea9dbb36c5bede6a`
- test(s): `services/projector/tests/unit/test_read_model_constants.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.02s`

```
F
=================================== FAILURES ===================================
_ test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture _
    def test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture() -> None:
        constants = shared()
        assert constants["timelineOrderVersion"] == TIMELINE_ORDER_VERSION, (
            "the projector's TIMELINE_ORDER_VERSION differs from the shared fixture's"
        )
>       assert dict(STATUS_RANK) == constants["statusRank"], (
            "the projector's status -> rank table differs from the shared fixture's"
        )
E       AssertionError: the projector's status -> rank table differs from the shared fixture's
E       assert {'placed': 1,...rmed': 4, ...} == {'placed': 1,...rmed': 4, ...}
E         
E         Omitting 8 identical items, use -vv to show
E         Differing items:
E         {'completed': 97} != {'completed': 98}
E         Use -v to get more diff
services/projector/tests/unit/test_read_model_constants.py:36: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_read_model_constants.py::test_pr40_the_projectors_version_ranks_prefix_and_index_equal_the_shared_fixture
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.06s
```

#### K1-drop-seed-from-allow-list

Mutation: remove `seed` from the allow-list (the real seed then fails, by name).

- file `services/projector/tests/unit/test_read_model_sole_writer.py` sha256 before `78e042133798b6b8` after mutation `632995c7f8ee09a8`
- test(s): `services/projector/tests/unit/test_read_model_sole_writer.py::test_r54_permits_a_read_model_write_only_in_the_projector_and_the_allow_listed_offline_fixture_loader_while_permitting_a_read_anywhere_and_declares_no_write_model_dependency_of_its_own`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.30s`

```
F
=================================== FAILURES ===================================
_ test_r54_permits_a_read_model_write_only_in_the_projector_and_the_allow_listed_offline_fixture_loader_while_permitting_a_read_anywhere_and_declares_no_write_model_dependency_of_its_own _
    def test_r54_permits_a_read_model_write_only_in_the_projector_and_the_allow_listed_offline_fixture_loader_while_permitting_a_read_anywhere_and_declares_no_write_model_dependency_of_its_own() -> (  # noqa: E501
        None
    ):
        found = write_calls(REPO_ROOT)
>       assert unauthorised(found, ALLOWED_WRITERS) == {}, "a service other than the projector writes"
E       AssertionError: a service other than the projector writes
E       assert {'seed': ['se... update_one']} == {}
E         
E         Left contains 1 more item:
E         {'seed': ['services/seed/src/otc_seed/infrastructure/mongo.py:39 create_index',
E                   'services/seed/src/otc_seed/infrastructure/mongo.py:48 update_one']}
E         Use -v to get more diff
services/projector/tests/unit/test_read_model_sole_writer.py:91: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_read_model_sole_writer.py::test_r54_permits_a_read_model_write_only_in_the_projector_and_the_allow_listed_offline_fixture_loader_while_permitting_a_read_anywhere_and_declares_no_write_model_dependency_of_its_own
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.34s
```

#### K1-plant-update-one

Mutation: plant `collection.update_one(...)` in a scratch `services/billing/src/otc_billing/scratch_write.py` (created, run, removed; the guard scans the real tree here).

- scratch file created then removed: `services/billing/src/otc_billing/scratch_write.py`
- test(s): `services/projector/tests/unit/test_read_model_sole_writer.py::test_r54_permits_a_read_model_write_only_in_the_projector_and_the_allow_listed_offline_fixture_loader_while_permitting_a_read_anywhere_and_declares_no_write_model_dependency_of_its_own`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.32s`

```
F
=================================== FAILURES ===================================
_ test_r54_permits_a_read_model_write_only_in_the_projector_and_the_allow_listed_offline_fixture_loader_while_permitting_a_read_anywhere_and_declares_no_write_model_dependency_of_its_own _
    def test_r54_permits_a_read_model_write_only_in_the_projector_and_the_allow_listed_offline_fixture_loader_while_permitting_a_read_anywhere_and_declares_no_write_model_dependency_of_its_own() -> (  # noqa: E501
        None
    ):
        found = write_calls(REPO_ROOT)
>       assert unauthorised(found, ALLOWED_WRITERS) == {}, "a service other than the projector writes"
E       AssertionError: a service other than the projector writes
E       assert {'billing': [... update_one']} == {}
E         
E         Left contains 1 more item:
E         {'billing': ['services/billing/src/otc_billing/scratch_write.py:2 update_one']}
E         Use -v to get more diff
services/projector/tests/unit/test_read_model_sole_writer.py:92: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_read_model_sole_writer.py::test_r54_permits_a_read_model_write_only_in_the_projector_and_the_allow_listed_offline_fixture_loader_while_permitting_a_read_anywhere_and_declares_no_write_model_dependency_of_its_own
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.35s
```

#### K2-nats-subscribe

Mutation: add `await nc.subscribe("readmodel.>")` in a scratch module under `src`.

- scratch file created then removed: `services/projector/src/otc_projector/infrastructure/signal/scratch_sub.py`
- test(s): `services/projector/tests/unit/test_projector_consumes_only.py::test_pr1_one_kafka_consumer_task_over_the_three_fact_topics_and_no_nats_subscription_of_any_kind`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.22s`

```
F
=================================== FAILURES ===================================
_ test_pr1_one_kafka_consumer_task_over_the_three_fact_topics_and_no_nats_subscription_of_any_kind _
    def test_pr1_one_kafka_consumer_task_over_the_three_fact_topics_and_no_nats_subscription_of_any_kind() -> (  # noqa: E501
        None
    ):
        files = python_files(SRC)
        assert len(files) > 25, f"the scan covered {len(files)} files"
        assert consumer_importers(files) == ["infrastructure/messaging/kafka_fact_subscriber.py"]
>       assert nats_subscriptions(files) == [], "the projector subscribes to or requests on NATS"
E       AssertionError: the projector subscribes to or requests on NATS
E       assert ['infrastruct...:2 subscribe'] == []
E         
E         Left contains one more item: 'infrastructure/signal/scratch_sub.py:2 subscribe'
E         Use -v to get more diff
services/projector/tests/unit/test_projector_consumes_only.py:123: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projector_consumes_only.py::test_pr1_one_kafka_consumer_task_over_the_three_fact_topics_and_no_nats_subscription_of_any_kind
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.26s
```

#### K2-orders-route

Mutation: add a `GET /orders` route.

- file `services/projector/src/otc_projector/presentation/app.py` sha256 before `a423f4dd58737970` after mutation `62ae9560c8e7c640`
- test(s): `services/projector/tests/unit/test_projector_consumes_only.py::test_pr21_no_write_model_dependency_no_ledger_table_no_nats_request_and_only_the_two_health_routes`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.23s`

```
F
=================================== FAILURES ===================================
_ test_pr21_no_write_model_dependency_no_ledger_table_no_nats_request_and_only_the_two_health_routes _
    def test_pr21_no_write_model_dependency_no_ledger_table_no_nats_request_and_only_the_two_health_routes() -> (  # noqa: E501
        None
    ):
        files = python_files(SRC)
        assert write_model_imports(files) == []
        names = [
            name
            for name in files
            if any(word in Path(name).stem for word in ("outbox", "relay", "responder", "models"))
        ]
        assert names == [], f"a module named for a write-model concern exists: {names}"
        assert ledger_table_uses(files) == [], "a processed_events ledger table is declared or named"
        routes = {getattr(route, "path", "") for route in create_app().routes}
>       assert routes - DOCS_ROUTES == SERVED, f"the app serves {sorted(routes - DOCS_ROUTES)}"
E       AssertionError: the app serves ['/health/live', '/health/ready', '/orders']
E       assert {'/health/liv...y', '/orders'} == {'/health/liv...health/ready'}
E         
E         Extra items in the left set:
E         '/orders'
E         Use -v to get more diff
services/projector/tests/unit/test_projector_consumes_only.py:142: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projector_consumes_only.py::test_pr21_no_write_model_dependency_no_ledger_table_no_nats_request_and_only_the_two_health_routes
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.30s
```

#### K3-census

Mutation: remove `"projector"` from `SERVICES` (the census must fail).

- file `tests/architecture/test_registration_behaviour.py` sha256 before `fe09217357639754` after mutation `c1f27c434f4a6f09`
- test(s): `tests/architecture/test_registration_behaviour.py::test_the_services_list_is_exactly_the_composition_roots_that_define_a_dispatcher`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.03s`

```
F
=================================== FAILURES ===================================
_ test_the_services_list_is_exactly_the_composition_roots_that_define_a_dispatcher _
    def test_the_services_list_is_exactly_the_composition_roots_that_define_a_dispatcher() -> None:
        """A new service with a dispatcher fails here until it joins `SERVICES` and `TABLES`: the
        behavioural probe cannot examine a service nobody listed."""
>       assert composition_roots_with_a_dispatcher(REPO_ROOT) == set(SERVICES)
E       AssertionError: assert {'billing', '..., 'projector'} == {'billing', '...ns', 'orders'}
E         
E         Extra items in the left set:
E         'projector'
E         Use -v to get more diff
tests/architecture/test_registration_behaviour.py:282: AssertionError
=========================== short test summary info ============================
FAILED tests/architecture/test_registration_behaviour.py::test_the_services_list_is_exactly_the_composition_roots_that_define_a_dispatcher
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.08s
```

#### K3-pipeline

Mutation (acceptance 8): an `__init_subclass__` self-registration on a scratch command, drained by a helper loop in the composition root (F-g + F-j as one fixture). The scratch handler module is created and removed; the composition root is mutated and restored.

- file `services/projector/src/otc_projector/composition.py` sha256 before `e57aaf886ddf96ae` after mutation `9c63803d8ed787fb`
- scratch file created then removed: `services/projector/src/otc_projector/application/scratch_registry.py`
- test(s): `tests/architecture/test_registration_behaviour.py::test_a_service_registers_only_from_its_composition_root_and_its_tables_match[projector]`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.68s`

```
F
=================================== FAILURES ===================================
_ test_a_service_registers_only_from_its_composition_root_and_its_tables_match[projector] _
service = 'projector'
    @pytest.mark.parametrize("service", SERVICES)
    def test_a_service_registers_only_from_its_composition_root_and_its_tables_match(
        service: str,
    ) -> None:
        result = probe(f"otc_{service}")
>       assert violations(result) == []
E       assert ["WIRE: 2 reg...tchCommand']"] == []
E         
E         Left contains one more item: "WIRE: 2 registrations share one statement (composition.py:89): ['otc_projector.application.messages.ProjectFactCommand', 'otc_projector.application.scratch_registry.ScratchCommand']"
E         Use -v to get more diff
tests/architecture/test_registration_behaviour.py:319: AssertionError
=========================== short test summary info ============================
FAILED tests/architecture/test_registration_behaviour.py::test_a_service_registers_only_from_its_composition_root_and_its_tables_match[projector]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.72s
```

#### K4-client-id

Mutation: the projector's default client id set to `otc-notifications`.

- file `services/projector/src/otc_projector/infrastructure/settings.py` sha256 before `cbba2346658d3c97` after mutation `6cbc2f907bccb485`
- test(s): `tests/architecture/test_kafka_client_ids.py`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.09s`

```
F
=================================== FAILURES ===================================
__ test_bc34_the_five_default_client_ids_are_non_empty_and_pairwise_distinct ___
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7c3183e35f30>
tmp_path = PosixPath('/tmp/pytest-of-juanpabloperez/pytest-797/test_bc34_the_five_default_cli0')
    def test_bc34_the_five_default_client_ids_are_non_empty_and_pairwise_distinct(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)  # no `.env` of a developer can supply a value
        for variable in CLIENT_ID_VARIABLES:
            monkeypatch.delenv(variable, raising=False)
        ids = {
            "orders": OrdersKafka().client_id,
            "fulfillment": FulfillmentKafka().client_id,
            "billing": BillingKafka().client_id,
            "notifications": NotificationsKafka().client_id,
            "projector": ProjectorKafka().client_id,
        }
        for service, client_id in ids.items():
            assert client_id.strip(), f"{service}'s default client id is empty or blank"
>       assert len(set(ids.values())) == 5, f"two services share a default client id: {ids}"
E       AssertionError: two services share a default client id: {'orders': 'otc-orders', 'fulfillment': 'otc-fulfillment', 'billing': 'otc-billing', 'notifications': 'otc-notifications', 'projector': 'otc-notifications'}
E       assert 4 == 5
E        +  where 4 = len({'otc-billing', 'otc-fulfillment', 'otc-notifications', 'otc-orders'})
E        +    where {'otc-billing', 'otc-fulfillment', 'otc-notifications', 'otc-orders'} = set(dict_values(['otc-orders', 'otc-fulfillment', 'otc-billing', 'otc-notifications', 'otc-notifications']))
E        +      where dict_values(['otc-orders', 'otc-fulfillment', 'otc-billing', 'otc-notifications', 'otc-notifications']) = <built-in method values of dict object at 0x7c3184789f00>()
E        +        where <built-in method values of dict object at 0x7c3184789f00> = {'orders': 'otc-orders', 'fulfillment': 'otc-fulfillment', 'billing': 'otc-billing', 'notifications': 'otc-notifications', ...}.values
/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/tests/architecture/test_kafka_client_ids.py:50: AssertionError
=========================== short test summary info ============================
FAILED tests/architecture/test_kafka_client_ids.py::test_bc34_the_five_default_client_ids_are_non_empty_and_pairwise_distinct
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.13s
```

#### K4-consumer-import

Mutation: an `AIOKafkaConsumer` import in `presentation/projector_facts_consumer.py`.

- file `services/projector/src/otc_projector/presentation/projector_facts_consumer.py` sha256 before `c885e9792fae0d32` after mutation `8d741a465c1a2d28`
- test(s): `tests/architecture/test_kafka_client_confinement.py::test_the_modules_importing_aiokafka_are_exactly_the_publishers_and_the_subscribers`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.19s`

```
F
=================================== FAILURES ===================================
_ test_the_modules_importing_aiokafka_are_exactly_the_publishers_and_the_subscribers _
    def test_the_modules_importing_aiokafka_are_exactly_the_publishers_and_the_subscribers() -> None:
        found = survey(REPO_ROOT)
>       assert violations(found) == []
E       assert ["the modules...subscriber']"] == []
E         
E         Left contains one more item: "the modules importing aiokafka are ['otc_billing.infrastructure.outbox.kafka_publisher', 'otc_fulfillment.infrastruct...', 'otc_orders.infrastructure.outbox.kafka_publisher', 'otc_projector.infrastructure.messaging.kafka_fact_subscriber']"
E         Use -v to get more diff
tests/architecture/test_kafka_client_confinement.py:114: AssertionError
=========================== short test summary info ============================
FAILED tests/architecture/test_kafka_client_confinement.py::test_the_modules_importing_aiokafka_are_exactly_the_publishers_and_the_subscribers
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.22s
```

#### K4-environ

Mutation: an `os.environ["NATS_URL"]` read in `composition.py`.

- file `services/projector/src/otc_projector/composition.py` sha256 before `e57aaf886ddf96ae` after mutation `e92f51a873e1fe05`
- test(s): `tests/architecture/test_composition_env_reads.py::test_nothing_in_a_service_with_a_root_reads_the_environment_directly`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.23s`

```
F
=================================== FAILURES ===================================
_____ test_nothing_in_a_service_with_a_root_reads_the_environment_directly _____
    def test_nothing_in_a_service_with_a_root_reads_the_environment_directly() -> None:
        offenders = {
            f"{p.relative_to(REPO_ROOT).as_posix()} {hit}"
            for root in ROOTS
            for p in sources(root)
            for hit in environment_reads(p.read_text(encoding="utf-8"))
        }
>       assert not offenders, f"read the environment through a settings class instead: {offenders}"
E       AssertionError: read the environment through a settings class instead: {'services/projector/src/otc_projector/composition.py line 82: os.environ'}
E       assert not {'services/projector/src/otc_projector/composition.py line 82: os.environ'}
tests/architecture/test_composition_env_reads.py:152: AssertionError
=========================== short test summary info ============================
FAILED tests/architecture/test_composition_env_reads.py::test_nothing_in_a_service_with_a_root_reads_the_environment_directly
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.27s
```

#### K5 — the inherited instruments are non-vacuous for this service

One scratch module `services/projector/src/otc_projector/domain/scratch_k5.py` at a time (created, run, removed; nothing else edited). No domain file existed before this feature, so the three guards had nothing to examine; each is shown to fail on a planted violation.

**(a) `import pymongo` in domain (contract domain-purity)**
```
Broken contracts
----------------

Every service domain (nested subpackages included) imports no framework and not 
otc_cqrs
--------------------------------------------------------------------------------
--------

otc_projector.domain is not allowed to import pymongo:

-   otc_projector.domain.scratch_k5 -> pymongo (l.1)


```

**(b) `from otc_projector.infrastructure import settings` in domain (contract layers-projector)**
```
Broken contracts
----------------

Every service domain (nested subpackages included) imports no framework and not 
otc_cqrs
--------------------------------------------------------------------------------
--------

otc_projector.domain is not allowed to import pydantic:

-   otc_projector.domain.scratch_k5 -> otc_projector.infrastructure.settings 
(l.1)
    otc_projector.infrastructure.settings -> pydantic (l.23)


otc_projector.domain is not allowed to import pydantic_settings:
```

**(c) `amount = total / 2` on a money name (tests/architecture/test_money_guard.py)**
```
E       AssertionError: money guard: float / true division / decimal in domain code: {'services/projector/src/otc_projector/domain/scratch_k5.py': ['line 2: true division `/` (int / int is a float)']}
E       assert not {'services/projector/src/otc_projector/domain/scratch_k5.py': ['line 2: true division `/` (int / int is a float)']}
FAILED tests/architecture/test_money_guard.py::test_money_guard_finds_no_violation_in_domain_or_shared_kernel
1 failed, 303 passed in 0.47s
```

(b, second reading) with the same scratch module the `layers-projector` contract reports: `otc_projector: presentation > infrastructure > application > domain BROKEN` and `Contracts: 9 kept, 2 broken.`

#### K6-sync-client

Mutation: add `from pymongo import MongoClient` to a scratch module.

- scratch file created then removed: `services/projector/src/otc_projector/infrastructure/scratch_sync.py`
- test(s): `services/projector/tests/unit/test_no_sync_driver.py::test_no_module_under_src_imports_the_sync_pymongo_client_or_motor`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
F
=================================== FAILURES ===================================
______ test_no_module_under_src_imports_the_sync_pymongo_client_or_motor _______
    def test_no_module_under_src_imports_the_sync_pymongo_client_or_motor() -> None:
        files = sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)
        assert len(files) > 25, f"the scan covered {len(files)} files"
        offenders = {
            str(p.relative_to(SRC)): hits
            for p in files
            if (hits := sync_driver_uses(p.read_text(encoding="utf-8")))
        }
>       assert offenders == {}, f"a synchronous driver is used: {offenders}"
E       AssertionError: a synchronous driver is used: {'infrastructure/scratch_sync.py': ['line 1: from pymongo import MongoClient']}
E       assert {'infrastruct...MongoClient']} == {}
E         
E         Left contains 1 more item:
E         {'infrastructure/scratch_sync.py': ['line 1: from pymongo import MongoClient']}
E         Use -v to get more diff
services/projector/tests/unit/test_no_sync_driver.py:48: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_no_sync_driver.py::test_no_module_under_src_imports_the_sync_pymongo_client_or_motor
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.08s
```

#### K7-module-set

Mutation: the H6 module-level `set` (this test fails where the rebuilt-runtime case did not).

- file `services/projector/src/otc_projector/infrastructure/messaging/idempotent_consumer.py` sha256 before `fc9f5b38c78db010` after mutation `279f3c24b42e1dbe`
- test(s): `services/projector/tests/unit/test_no_process_state.py::test_pr51_no_module_level_mutable_state_and_no_writer_state_beyond_the_collection`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.03s`

```
F
=================================== FAILURES ===================================
_ test_pr51_no_module_level_mutable_state_and_no_writer_state_beyond_the_collection _
    def test_pr51_no_module_level_mutable_state_and_no_writer_state_beyond_the_collection() -> None:
        files = sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)
        assert len(files) > 25, f"the scan covered {len(files)} files"
        found = {
            (str(p.relative_to(SRC)), name)
            for p in files
            for name in module_level_containers(p.read_text(encoding="utf-8"))
        }
>       assert found == set(DECLARED_CONSTANTS), (
            f"module-level mutable containers outside the declared set: "
            f"{sorted(found - set(DECLARED_CONSTANTS))}"
        )
E       AssertionError: module-level mutable containers outside the declared set: [('infrastructure/messaging/idempotent_consumer.py', '_SEEN')]
E       assert {('infrastruc...py', '_SEEN')} == set()
E         
E         Extra items in the left set:
E         ('infrastructure/messaging/idempotent_consumer.py', '_SEEN')
E         Use -v to get more diff
services/projector/tests/unit/test_no_process_state.py:106: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_no_process_state.py::test_pr51_no_module_level_mutable_state_and_no_writer_state_beyond_the_collection
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### L2-causation-G5

L2 corruption: the `timeline.appended` frame's `causationId` carries the event id (caught by G5).

- file `services/projector/src/otc_projector/infrastructure/signal/nats_update_signal_publisher.py` sha256 before `75b2af1579751596` after mutation `ebc7e001f45c0ecd`
- test(s): `services/projector/tests/unit/test_update_signal_payloads.py::test_pr37_every_field_reaches_both_signal_payloads_verbatim_sentinel_per_field`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.07s`

```
        updated = json.loads(connection.published[0][1])
        appended = json.loads(connection.published[1][1])
        assert updated == {
            "eventId": EVENT_ID,
            "orderId": ORDER_ID,
            "orderReference": "ORD-424242",
            "status": "cancelled",
            "cancellationReason": "operator_cancelled",
            "references": {
                "despatchReference": "DES-717171",
                "invoiceReference": "INV-838383",
                "paymentReference": "PAY-949494",
            },
            "totals": {
                "initialAmount": 5550001,
                "initialDiscount": 6660002,
                "totalAmount": 7770003,
            },
            "occurredAt": "2031-07-08T09:10:11.123Z",
        }
>       assert appended == {
            "eventId": EVENT_ID,
            "causationId": CAUSATION_ID,
            "orderId": ORDER_ID,
            "orderReference": "ORD-424242",
            "eventType": "order.cancelled.v1",
            "occurredAt": "2031-07-08T09:10:11.123Z",
            "summary": "Orden anulada por el operador — Zürich",
        }
E       AssertionError: assert {'eventId': '...-424242', ...} == {'eventId': '...-424242', ...}
E         
E         Omitting 6 identical items, use -vv to show
E         Differing items:
E         {'causationId': '22222222-bbbb-4bbb-8bbb-222222222222'} != {'causationId': '33333333-cccc-4ccc-8ccc-333333333333'}
E         Use -v to get more diff
services/projector/tests/unit/test_update_signal_payloads.py:97: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_update_signal_payloads.py::test_pr37_every_field_reaches_both_signal_payloads_verbatim_sentinel_per_field
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.12s
```

#### L2-causation-PR33

L2 corruption: the `timeline.appended` frame's `causationId` carries the event id (caught by PR33).

- file `services/projector/src/otc_projector/infrastructure/signal/nats_update_signal_publisher.py` sha256 before `75b2af1579751596` after mutation `ebc7e001f45c0ecd`
- test(s): `services/projector/tests/integration/test_update_signal.py::test_pr33_the_timeline_appended_payload_carries_causation_id`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 4.00s`

```
F
=================================== FAILURES ===================================
_________ test_pr33_the_timeline_appended_payload_carries_causation_id _________
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36278'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_022352c4dd76408b8e49850ed0be6c68', uri='mongodb://otc_test:otc_test_password@localhost:36278/?authSource=admin')
nats_connection = <nats client v2.16.0>
frames_factory = <function frames_factory.<locals>.make at 0x794ae10c5f30>
facts = FactBuilders()
    async def test_pr33_the_timeline_appended_payload_carries_causation_id(
        read_model: Any, nats_connection: Any, frames_factory: Any, facts: Any
    ) -> None:
        order = uuid.UUID("0a0b0c0d-4444-4000-8000-0000000000dd")
        appended = await frames_factory(f"readmodel.timeline.appended.{order}")
        sentinel = uuid.UUID("99999999-9999-4999-8999-999999999999")
        event = facts.build("order.confirmed.v1", correlation_id=order, causation_id=sentinel)
        await handler_for(read_model, nats_connection).handle(ProjectFactCommand(event=event))
        await until("the timeline.appended frame", lambda: appended.received)
        ((_, entry),) = appended.frames()
>       assert entry["causationId"] == str(sentinel)
E       AssertionError: assert '00000321-032...-00000060c9cf' == '99999999-999...-999999999999'
E         
E         - 99999999-9999-4999-8999-999999999999
E         + 00000321-0321-4000-8000-00000060c9cf
services/projector/tests/integration/test_update_signal.py:140: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_update_signal.py::test_pr33_the_timeline_appended_payload_carries_causation_id
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 4.11s
```

#### L2-note-C6

L2 corruption: the stored `detail.note` (caught by C6).

- file `services/projector/src/otc_projector/application/summaries.py` sha256 before `84a2089b8084511b` after mutation `b1fc490a557114dd`
- test(s): `services/projector/tests/unit/test_projection.py::test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `6 passed in 0.05s`

```
F
=================================== FAILURES ===================================
_ test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one[operator_cancelled-step_names0-Cliente pidi\xf3 anulaci\xf3n] _
facts = FactBuilders(), reason = 'operator_cancelled', step_names = []
note = 'Cliente pidió anulación'
    @pytest.mark.parametrize(("reason", "step_names", "note"), BRANCHES)
    def test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one(
        facts: Any, reason: str, step_names: list[str], note: str | None
    ) -> None:
        payload: dict[str, Any] = {
            "cancellation_reason": reason,
            "compensation_steps": steps(step_names),
        }
        if note is not None:
            payload["note"] = note
        detail = project(facts.build("order.cancelled.v1", payload=payload)).entry.detail
        assert detail is not None
        if note is None:
            assert "note" not in detail, f"a note appeared where the fact had none: {detail}"
        else:
            assert "note" in detail, f"the operator's note {note!r} did not reach detail: {detail}"
>           assert detail["note"] == note, "the operator's note was altered on its way to the entry"
E           AssertionError: the operator's note was altered on its way to the entry
E           assert 'Cliente pidió anulación!' == 'Cliente pidió anulación'
E             
E             - Cliente pidió anulación
E             + Cliente pidió anulación!
E             ?                        +
services/projector/tests/unit/test_projection.py:225: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_projection.py::test_pr46_the_note_reaches_detail_on_every_cancellation_branch_and_is_absent_without_one[operator_cancelled-step_names0-Cliente pidi\xf3 anulaci\xf3n]
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.10s
```

#### L2-note-J1

L2 corruption: the stored `detail.note` (caught by J1).

- file `services/projector/src/otc_projector/application/summaries.py` sha256 before `84a2089b8084511b` after mutation `b1fc490a557114dd`
- test(s): `services/projector/tests/integration/test_timeline_projection.py::test_pr46_a_noted_operator_cancellation_stores_the_note_verbatim`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.83s`

```
F
=================================== FAILURES ===================================
_______ test_pr46_a_noted_operator_cancellation_stores_the_note_verbatim _______
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36290'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_84cc4ccef3544d27ad0d30d4e3997b8e', uri='mongodb://otc_test:otc_test_password@localhost:36290/?authSource=admin')
facts = FactBuilders()
    async def test_pr46_a_noted_operator_cancellation_stores_the_note_verbatim(
        read_model: Any, facts: Any
    ) -> None:
        note = "Cliente pidió anulación — $status"
        event = facts.build(
            "order.cancelled.v1",
            correlation_id=ORDER,
            payload={
                "cancellation_reason": "operator_cancelled",
                "note": note,
                "compensation_steps": [],
            },
        )
        await read_model.apply(event)
        document = await read_model.document(ORDER)
        (entry,) = document["events"]
>       assert entry["detail"]["note"] == note
E       AssertionError: assert 'Cliente pidi...ón — $status!' == 'Cliente pidi...ión — $status'
E         
E         - Cliente pidió anulación — $status
E         + Cliente pidió anulación — $status!
E         ?                                  +
services/projector/tests/integration/test_timeline_projection.py:140: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_timeline_projection.py::test_pr46_a_noted_operator_cancellation_stores_the_note_verbatim
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.87s
```

#### L2-status-G4

L2 corruption: the `order.updated` frame's `status` always `placed` (caught by G4).

- file `services/projector/src/otc_projector/infrastructure/signal/nats_update_signal_publisher.py` sha256 before `75b2af1579751596` after mutation `1da45d2678bb72ef`
- test(s): `services/projector/tests/integration/test_update_signal.py::test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 4.58s`

```
F
=================================== FAILURES ===================================
_ test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references _
read_model = ReadModel(client=AsyncMongoClient(host=['localhost:36269'], document_class=dict, tz_aware=False, connect=True, authsou...c_test_1e612e4266154a3d879a0d2428d236e0', uri='mongodb://otc_test:otc_test_password@localhost:36269/?authSource=admin')
nats_connection = <nats client v2.16.0>
frames_factory = <function frames_factory.<locals>.make at 0x79e13b47de80>
facts = FactBuilders()
    async def test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references(
        read_model: Any, nats_connection: Any, frames_factory: Any, facts: Any
    ) -> None:
        order = uuid.UUID("0a0b0c0d-5555-4000-8000-0000000000ee")
        updated = await frames_factory(f"readmodel.order.updated.{order}")
        handler = handler_for(read_model, nats_connection)
        confirmed = facts.build("order.confirmed.v1", correlation_id=order)
        despatched = facts.build(
            "order.despatched.v1",
            correlation_id=order,
            payload={"despatch_reference": "DES-717171"},
        )
        await handler.handle(ProjectFactCommand(event=confirmed))
        await handler.handle(ProjectFactCommand(event=despatched))
        await until("two order.updated frames", lambda: len(updated.received) >= 2)
        first, second = (frame for _, frame in updated.frames())
>       assert first["status"] == "confirmed", (
            f"the signal carries the PRE-apply status {first['status']!r} (return_document default)"
        )
E       AssertionError: the signal carries the PRE-apply status 'placed' (return_document default)
E       assert 'placed' == 'confirmed'
E         
E         - confirmed
E         + placed
services/projector/tests/integration/test_update_signal.py:160: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_update_signal.py::test_pr42_the_order_updated_signal_carries_the_post_apply_status_and_references
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 4.66s
```

#### L2-status-G5

L2 corruption: the `order.updated` frame's `status` always `placed` (caught by G5).

- file `services/projector/src/otc_projector/infrastructure/signal/nats_update_signal_publisher.py` sha256 before `75b2af1579751596` after mutation `1da45d2678bb72ef`
- test(s): `services/projector/tests/unit/test_update_signal_payloads.py::test_pr37_every_field_reaches_both_signal_payloads_verbatim_sentinel_per_field`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.08s`

```
F
=================================== FAILURES ===================================
_ test_pr37_every_field_reaches_both_signal_payloads_verbatim_sentinel_per_field _
    async def test_pr37_every_field_reaches_both_signal_payloads_verbatim_sentinel_per_field() -> None:
        connection = await published()
        assert [subject for subject, _, _ in connection.published] == [
            f"readmodel.order.updated.{ORDER_ID}",
            f"readmodel.timeline.appended.{ORDER_ID}",
        ]
        updated = json.loads(connection.published[0][1])
        appended = json.loads(connection.published[1][1])
>       assert updated == {
            "eventId": EVENT_ID,
            "orderId": ORDER_ID,
            "orderReference": "ORD-424242",
            "status": "cancelled",
            "cancellationReason": "operator_cancelled",
            "references": {
                "despatchReference": "DES-717171",
                "invoiceReference": "INV-838383",
                "paymentReference": "PAY-949494",
            },
            "totals": {
                "initialAmount": 5550001,
                "initialDiscount": 6660002,
                "totalAmount": 7770003,
            },
            "occurredAt": "2031-07-08T09:10:11.123Z",
        }
E       AssertionError: assert {'eventId': '...'placed', ...} == {'eventId': '...ncelled', ...}
E         
E         Omitting 7 identical items, use -vv to show
E         Differing items:
E         {'status': 'placed'} != {'status': 'cancelled'}
E         Use -v to get more diff
services/projector/tests/unit/test_update_signal_payloads.py:79: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_update_signal_payloads.py::test_pr37_every_field_reaches_both_signal_payloads_verbatim_sentinel_per_field
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.13s
```

#### L2-summary-C2

L2 corruption: the stored entry's `summary` (caught by C2).

- file `services/projector/src/otc_projector/application/summaries.py` sha256 before `84a2089b8084511b` after mutation `d8197b2b6f5153be`
- test(s): `services/projector/tests/unit/test_summaries.py::test_pr16_order_confirmed`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 0.04s`

```
F
=================================== FAILURES ===================================
__________________________ test_pr16_order_confirmed ___________________________
facts = FactBuilders()
    def test_pr16_order_confirmed(facts: Any) -> None:  # :75
>       assert summaries.order_confirmed(payload(facts, "order.confirmed.v1")).text == (
            "Order confirmed (ORDRSP)"
        )
E       AssertionError: assert 'Order confirmed (ORDRSP!)' == 'Order confirmed (ORDRSP)'
E         
E         - Order confirmed (ORDRSP)
E         + Order confirmed (ORDRSP!)
E         ?                        +
services/projector/tests/unit/test_summaries.py:98: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/unit/test_summaries.py::test_pr16_order_confirmed
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 0.09s
```

#### L2-summary-J1

L2 corruption: the stored entry's `summary` (caught by J1).

- file `services/projector/src/otc_projector/application/summaries.py` sha256 before `84a2089b8084511b` after mutation `d8197b2b6f5153be`
- test(s): `services/projector/tests/integration/test_timeline_projection.py::test_r50_appends_an_entry_carrying_event_id_event_type_occurred_at_and_a_summary_and_presents_the_timeline_ordered_by_occurred_at_rather_than_by_arrival`
- mutated run exit code: **1** (expected non-zero)
- restore: `cmp` identical; sha256 matches; `__pycache__` and `.mypy_cache` cleared
- green re-run exit code: **0** — `1 passed in 3.83s`

```
        document = await read_model.document(ORDER)
        entries = document["events"]
        assert [e["eventId"] for e in entries] == [
            str(e.event_id) for e in (placed, reserved, approved, confirmed, despatched)
        ], "the timeline is not ordered by occurredAt"
        expected_summaries = [
            "Order ORD-000101 placed for ACME",
            "Stock reserved for 2 line(s)",
            "Credit hold of 92.45 EUR approved",
            "Order confirmed (ORDRSP)",
            "Despatch DES-000203 created",
        ]
        expected_instants = [
            "2026-05-01T09:00:01.101Z",
            "2026-05-01T09:00:02.102Z",
            "2026-05-01T09:00:03.103Z",
            "2026-05-01T09:00:04.104Z",
            "2026-05-01T09:00:05.105Z",
        ]
        for entry, event, summary, instant in zip(
            entries,
            (placed, reserved, approved, confirmed, despatched),
            expected_summaries,
            expected_instants,
            strict=True,
        ):
            assert entry["eventId"] == str(event.event_id)
            assert entry["eventType"] == event.event_type
            assert entry["occurredAt"] == instant
>           assert entry["summary"] == summary
E           AssertionError: assert 'Order confirmed (ORDRSP!)' == 'Order confirmed (ORDRSP)'
E             
E             - Order confirmed (ORDRSP)
E             + Order confirmed (ORDRSP!)
E             ?                        +
services/projector/tests/integration/test_timeline_projection.py:88: AssertionError
=========================== short test summary info ============================
FAILED services/projector/tests/integration/test_timeline_projection.py::test_r50_appends_an_entry_carrying_event_id_event_type_occurred_at_and_a_summary_and_presents_the_timeline_ordered_by_occurred_at_rather_than_by_arrival
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed in 3.89s
```

#### B4-lint-imports

```
Broken contracts
----------------

Every service domain (nested subpackages included) imports no framework and not 
otc_cqrs
--------------------------------------------------------------------------------
--------

otc_projector.domain is not allowed to import pydantic:

-   otc_projector.domain.scratch_arm -> otc_contracts (l.1)
    otc_contracts -> otc_contracts.envelope (l.3)
    otc_contracts.envelope -> pydantic (l.17)
```

#### F1-diff

```
2a3,13
> THE POPULATION IS DECLARED, NOT DISCOVERED (feature 24, PR48). `IDEMPOTENCY_MODE` classifies EVERY
> service package under `services/` as `relational-copy`, `documented-variant` or `no-consumer`, and
> `test_pr48_...` fails when a package on disk is missing from it, when a registered package does not
> exist, when a mode disagrees with the files, and when the set of consuming packages differs from the
> consumers `asyncapi.yaml`'s fact `receive` operations name. Until feature 24 the cases below
> selected their population by a FILE the subject chooses whether to create (a copy by its
> `processed_events` table and `idempotent_consumer.py`, a variant by that file alone), which is #7's
> OI12 flaw exactly: a consumer that deduplicated nowhere, or named its file differently, was examined
> by no case and every case passed. Cases 1 and 3 select by mode; case 4 examines the registry's
> `documented-variant`s and now FAILS, where it used to skip, when one has no consumer file.
> 
16a28
> from collections.abc import Mapping
19a32
> import yaml
26a40,61
> RELATIONAL_COPY = "relational-copy"
> DOCUMENTED_VARIANT = "documented-variant"
> NO_CONSUMER = "no-consumer"
> # EVERY package under `services/*/src/otc_*`, classified. A new service fails `test_pr48_...` until
> # it is added here, with a mode the files and the spec then have to agree with.
> IDEMPOTENCY_MODE: dict[str, str] = {
>     "orders": RELATIONAL_COPY,
>     "notifications": RELATIONAL_COPY,
>     "projector": DOCUMENTED_VARIANT,
>     "fulfillment": NO_CONSUMER,
>     "billing": NO_CONSUMER,
>     "gateway": NO_CONSUMER,
>     "seed": NO_CONSUMER,
> }
> # `asyncapi.yaml`'s `Consumer name — <name>.` (the fact `receive` operations) -> the package.
> SPEC_CONSUMER_PACKAGE = {
>     "orders.saga": "orders",
>     "projector": "projector",
>     "notifications": "notifications",
> }
> FACT_CHANNELS = ("ordersFacts", "fulfillmentFacts", "billingFacts")
> 
59,61c94,100
< def copies(root: Path) -> list[Path]:
<     """Every service with BOTH a relational `processed_events` ledger AND its own consumer file:
<     read from the filesystem, never from a hand-kept list of service names."""
---
> def short_name(package: Path) -> str:
>     return package.name.removeprefix("otc_")
> 
> 
> def copies(root: Path, modes: Mapping[str, str] = IDEMPOTENCY_MODE) -> list[Path]:
>     """The consumer file of every package REGISTERED as a `relational-copy`: selected by mode, never
>     by the existence of a file (the mode check reports a registered copy whose file is missing)."""
65c104
<         if has_relational_ledger(p) and consumer_file(p).is_file()
---
>         if modes.get(short_name(p)) == RELATIONAL_COPY and consumer_file(p).is_file()
69c108,110
< def divergent_copies(root: Path, canonical: Path) -> list[str]:
---
> def divergent_copies(
>     root: Path, canonical: Path, modes: Mapping[str, str] = IDEMPOTENCY_MODE
> ) -> list[str]:
72c113
<     for copy in copies(root):
---
>     for copy in copies(root, modes):
120,122c161,166
< def consumers_without_a_copy(root: Path) -> tuple[list[str], list[str]]:
<     """`(examined, missing)`: services with a relational ledger and a Kafka consumer of facts, and
<     those of them with no consumer file."""
---
> def consumers_without_a_copy(
>     root: Path, modes: Mapping[str, str] = IDEMPOTENCY_MODE
> ) -> tuple[list[str], list[str]]:
>     """`(examined, missing)`: the write models (a relational ledger, and a mode that is not
>     `documented-variant`, which case 4 examines instead) and, of them, those that consume facts
>     with no consumer file."""
125c169,171
<         if not has_relational_ledger(package):
---
>         if modes.get(short_name(package)) == DOCUMENTED_VARIANT or not has_relational_ledger(
>             package
>         ):
137,140c183,197
< def variants_without_a_divergence_note(root: Path, canonical_path: str) -> list[str]:
<     """A consumer file in a service with NO relational ledger is a variant: never compared, but its
<     banner must name the canonical and carry a line beginning `Divergence:`."""
<     found = []
---
> CONFORMANCE_LINE = "Behavioural conformance:"
> 
> 
> def variant_problems(
>     root: Path, canonical_path: str, modes: Mapping[str, str] = IDEMPOTENCY_MODE
> ) -> tuple[list[str], list[str]]:
>     """`(examined, problems)` over the REGISTRY's `documented-variant`s, never over the files found.
> 
>     A variant is never compared with the canonical, but it must (1) have its consumer file (the
>     opt-out OI12 allowed: a variant that deletes or renames the file is no longer examined, so the
>     file's absence now FAILS), (2) cite the canonical path in its banner, (3) carry a line beginning
>     `Divergence:` and (4) carry a `Behavioural conformance: <repo-relative path>` line naming a
>     file that exists (relative to `root`).
>     """
>     examined, problems = [], []
141a199,201
>         if modes.get(short_name(package)) != DOCUMENTED_VARIANT:
>             continue
>         examined.append(package.name)
143c203,204
<         if has_relational_ledger(package) or not file.is_file():
---
>         if not file.is_file():
>             problems.append(f"{package.name}: no consumer file at {file.relative_to(root)}")
147,150c208,292
<             found.append(f"{package.name}: the banner does not cite {canonical_path}")
<         if not any(line.startswith("Divergence:") for line in banner.splitlines()):
<             found.append(f"{package.name}: the banner has no line beginning 'Divergence:'")
<     return found
---
>             problems.append(f"{package.name}: the banner does not cite {canonical_path}")
>         lines = banner.splitlines()
>         if not any(line.startswith("Divergence:") for line in lines):
>             problems.append(f"{package.name}: the banner has no line beginning 'Divergence:'")
>         conformance = [line for line in lines if line.startswith(CONFORMANCE_LINE)]
>         if not conformance:
>             problems.append(f"{package.name}: the banner has no '{CONFORMANCE_LINE}' line")
>         for line in conformance:
>             named = line.removeprefix(CONFORMANCE_LINE).strip()
>             if not named or not (root / named).is_file():
>                 problems.append(
>                     f"{package.name}: the '{CONFORMANCE_LINE}' line names {named!r}, "
>                     "which is not an existing file"
>                 )
>     return examined, problems
> 
> 
> def spec_consumers(spec_text: str) -> set[str]:
>     """The consumer names `asyncapi.yaml`'s `receive` operations on the three fact channels carry
>     in their `summary: Consumer name — <name>.`, read as text and parsed as YAML."""
>     operations = yaml.safe_load(spec_text)["operations"]
>     names = set()
>     for operation in operations.values():
>         channel = operation["channel"]["$ref"].rsplit("/", 1)[1]
>         if operation["action"] == "receive" and channel in FACT_CHANNELS:
>             summary = operation["summary"]
>             assert summary.startswith("Consumer name \u2014 "), summary
>             names.add(summary.removeprefix("Consumer name \u2014 ").rstrip("."))
>     return names
> 
> 
> def registry_problems(root: Path, modes: Mapping[str, str] = IDEMPOTENCY_MODE) -> list[str]:
>     """P1 / P2: the registry's keys are exactly the packages on disk."""
>     on_disk = {short_name(p) for p in service_roots(root)}
>     problems = [
>         f"{name}: a service package on disk is missing from IDEMPOTENCY_MODE"
>         for name in sorted(on_disk - set(modes))
>     ]
>     problems += [
>         f"{name}: registered in IDEMPOTENCY_MODE but there is no such package"
>         for name in sorted(set(modes) - on_disk)
>     ]
>     return problems
> 
> 
> def mode_problems(root: Path, modes: Mapping[str, str] = IDEMPOTENCY_MODE) -> list[str]:
>     """P3 / P4 (the mode against the files): the half of the registry a subject could lie about."""
>     problems = []
>     for package in service_roots(root):
>         name, mode = short_name(package), modes.get(short_name(package))
>         if mode is None:
>             continue  # reported by `registry_problems`
>         if mode == RELATIONAL_COPY:
>             if not has_relational_ledger(package):
>                 problems.append(f"{name}: registered relational-copy but has no processed_events")
>             if not consumer_file(package).is_file():
>                 problems.append(f"{name}: registered relational-copy but has no consumer file")
>         elif mode == DOCUMENTED_VARIANT:
>             if has_relational_ledger(package):
>                 problems.append(f"{name}: registered documented-variant but has a ledger table")
>         elif mode == NO_CONSUMER:
>             for source in package.rglob("*.py"):
>                 if "AIOKafkaConsumer" in source.read_text(encoding="utf-8"):
>                     problems.append(
>                         f"{name}: registered no-consumer but {source.name} references "
>                         "AIOKafkaConsumer"
>                     )
>         else:
>             problems.append(f"{name}: unknown mode {mode!r}")
>     return problems
> 
> 
> def spec_problems(spec_text: str, modes: Mapping[str, str] = IDEMPOTENCY_MODE) -> list[str]:
>     """P6: the consuming packages are exactly the consumers the spec names."""
>     named = {SPEC_CONSUMER_PACKAGE[name] for name in spec_consumers(spec_text)}
>     registered = {name for name, mode in modes.items() if mode != NO_CONSUMER}
>     problems = [
>         f"{name}: the spec names it a consumer but it is registered no-consumer"
>         for name in sorted(named - registered)
>     ]
>     problems += [
>         f"{name}: registered as a consumer but the spec names no such consumer"
>         for name in sorted(registered - named)
>     ]
>     return problems
166a309
> TWO_COPIES = {"orders": RELATIONAL_COPY, "billing": RELATIONAL_COPY}
204c347
<     reported = divergent_copies(tmp_path, canonical)
---
>     reported = divergent_copies(tmp_path, canonical, TWO_COPIES)
225c368
<     assert divergent_copies(tmp_path, tmp_path / CANONICAL) == []
---
>     assert divergent_copies(tmp_path, tmp_path / CANONICAL, TWO_COPIES) == []
338c481
< # ------------------------------------------------------------ case 4: variants name the canonical
---
> # ----------------------------------------------- PR48: the population is declared, not discovered
339a483
> SPEC_TEXT = (REPO_ROOT / "specs" / "shared" / "asyncapi.yaml").read_text(encoding="utf-8")
341,347c485,625
< def test_case_4_a_variant_carries_a_divergence_banner_naming_the_canonical() -> None:
<     assert variants_without_a_divergence_note(REPO_ROOT, CANONICAL) == []
<     # dormant until features 23/24: no service without a relational ledger has a consumer file yet
<     variants = [
<         consumer_file(p)
<         for p in service_roots(REPO_ROOT)
<         if not has_relational_ledger(p) and consumer_file(p).is_file()
---
> 
> def test_pr48_every_service_package_is_registered_and_its_mode_matches_the_files_and_the_spec() -> (
>     None
> ):
>     on_disk = {short_name(p) for p in service_roots(REPO_ROOT)}
>     assert (
>         on_disk
>         == set(IDEMPOTENCY_MODE)
>         == {
>             "gateway",
>             "orders",
>             "fulfillment",
>             "billing",
>             "notifications",
>             "projector",
>             "seed",
>         }
>     )
>     assert registry_problems(REPO_ROOT) == [], "the registry and the packages on disk disagree"
>     assert mode_problems(REPO_ROOT) == [], "a registered mode disagrees with the files"
>     assert spec_problems(SPEC_TEXT) == [], "the registry disagrees with asyncapi.yaml's consumers"
>     assert spec_consumers(SPEC_TEXT) == set(SPEC_CONSUMER_PACKAGE)
>     print(f"pr48 registry classified {len(IDEMPOTENCY_MODE)} packages")
> 
> 
> def test_pr48_sentinel_the_control_tree_passes(tmp_path: Path) -> None:
>     modes = {"orders": RELATIONAL_COPY, "projector": DOCUMENTED_VARIANT, "seed": NO_CONSUMER}
>     build_control_tree(tmp_path)
>     assert registry_problems(tmp_path, modes) == []
>     assert mode_problems(tmp_path, modes) == []
>     examined, problems = variant_problems(tmp_path, CANONICAL, modes)
>     assert (examined, problems) == (["otc_projector"], [])
> 
> 
> def build_control_tree(root: Path) -> None:
>     conformance = "services/projector/tests/integration/test_conformance.py"
>     (root / conformance).parent.mkdir(parents=True, exist_ok=True)
>     (root / conformance).write_text("", encoding="utf-8")
>     banner = (
>         f'"""Variant of {CANONICAL}.\n\nDivergence: a document store shares no transaction.\n\n'
>         f'{CONFORMANCE_LINE} {conformance}\n"""\n'
>     )
>     build_tree(
>         root,
>         {
>             "orders": {
>                 "infrastructure/persistence/models.py": LEDGER,
>                 "infrastructure/messaging/idempotent_consumer.py": SAMPLE,
>             },
>             "projector": {"infrastructure/messaging/idempotent_consumer.py": banner},
>             "seed": {"domain/x.py": "VALUE = 1\n"},
>         },
>     )
> 
> 
> def test_pr48_p1_sentinel_a_package_on_disk_missing_from_the_registry_is_reported(
>     tmp_path: Path,
> ) -> None:
>     build_tree(tmp_path, {"ledgerless": {"infrastructure/x.py": "VALUE = 1\n"}})
>     assert registry_problems(tmp_path, IDEMPOTENCY_MODE) == [
>         "ledgerless: a service package on disk is missing from IDEMPOTENCY_MODE",
>         *[
>             f"{name}: registered in IDEMPOTENCY_MODE but there is no such package"
>             for name in sorted(IDEMPOTENCY_MODE)
>         ],
>     ]
> 
> 
> def test_pr48_p2_sentinel_a_registry_entry_with_no_package_is_reported(tmp_path: Path) -> None:
>     build_control_tree(tmp_path)
>     modes = {
>         "orders": RELATIONAL_COPY,
>         "projector": DOCUMENTED_VARIANT,
>         "seed": NO_CONSUMER,
>         "ghost": NO_CONSUMER,
>     }
>     assert registry_problems(tmp_path, modes) == [
>         "ghost: registered in IDEMPOTENCY_MODE but there is no such package"
>     ]
> 
> 
> def test_pr48_p3_sentinel_a_no_consumer_that_references_aiokafkaconsumer_is_reported(
>     tmp_path: Path,
> ) -> None:
>     build_tree(
>         tmp_path, {"seed": {"infrastructure/x.py": "from aiokafka import AIOKafkaConsumer\n"}}
>     )
>     assert mode_problems(tmp_path, {"seed": NO_CONSUMER}) == [
>         "seed: registered no-consumer but x.py references AIOKafkaConsumer"
>     ]
> 
> 
> def test_pr48_p4_sentinel_a_variant_whose_consumer_file_is_renamed_now_fails(
>     tmp_path: Path,
> ) -> None:
>     """The OI12 opt-out: a variant that renames its file used to be examined by no case."""
>     build_control_tree(tmp_path)
>     modes = {"projector": DOCUMENTED_VARIANT}
>     package = tmp_path / "services" / "projector" / "src" / "otc_projector"
>     consumer_file(package).rename(consumer_file(package).with_name("renamed.py"))
>     examined, problems = variant_problems(tmp_path, CANONICAL, modes)
>     assert examined == ["otc_projector"]
>     assert len(problems) == 1
>     assert problems[0].startswith("otc_projector: no consumer file at")
> 
> 
> def test_pr48_p5_sentinel_a_conformance_line_naming_a_missing_file_or_absent_is_reported(
>     tmp_path: Path,
> ) -> None:
>     build_control_tree(tmp_path)
>     modes = {"projector": DOCUMENTED_VARIANT}
>     package = tmp_path / "services" / "projector" / "src" / "otc_projector"
>     file = consumer_file(package)
>     original = file.read_text(encoding="utf-8")
> 
>     file.write_text(
>         original.replace("test_conformance.py", "test_no_such_file.py"), encoding="utf-8"
>     )
>     _, problems = variant_problems(tmp_path, CANONICAL, modes)
>     assert len(problems) == 1
>     assert "names 'services/projector/tests/integration/test_no_such_file.py'" in problems[0]
>     assert "which is not an existing file" in problems[0]
> 
>     file.write_text(
>         "\n".join(line for line in original.splitlines() if not line.startswith(CONFORMANCE_LINE))
>         + "\n",
>         encoding="utf-8",
>     )
>     _, problems = variant_problems(tmp_path, CANONICAL, modes)
>     assert problems == [f"otc_projector: the banner has no '{CONFORMANCE_LINE}' line"]
> 
> 
> def test_pr48_p6_sentinel_a_registry_marking_the_projector_no_consumer_is_reported() -> None:
>     modes = {**IDEMPOTENCY_MODE, "projector": NO_CONSUMER}
>     assert spec_problems(SPEC_TEXT, modes) == [
>         "projector: the spec names it a consumer but it is registered no-consumer"
>     ]
>     # and a consumer the spec does not name
>     modes = {**IDEMPOTENCY_MODE, "billing": RELATIONAL_COPY}
>     assert spec_problems(SPEC_TEXT, modes) == [
>         "billing: registered as a consumer but the spec names no such consumer"
349c627,638
<     print(f"case 4 examined {len(variants)} variant(s)")
---
> 
> 
> # ------------------------------------------------------------ case 4: variants name the canonical
> 
> 
> def test_case_4_a_variant_carries_a_divergence_banner_naming_the_canonical_and_an_existing_conformance_file() -> (  # noqa: E501
>     None
> ):
>     examined, problems = variant_problems(REPO_ROOT, CANONICAL)
>     assert problems == []
>     assert examined == ["otc_projector"], examined
>     print(f"case 4 examined {len(examined)} variant(s)")
352a642,644
>     conformance = "services/projector/tests/integration/test_conformance.py"
>     (tmp_path / conformance).parent.mkdir(parents=True, exist_ok=True)
>     (tmp_path / conformance).write_text("", encoding="utf-8")
354c646,647
<         f'"""Variant of {CANONICAL}.\n\nDivergence: a document store shares no transaction."""\n'
---
>         f'"""Variant of {CANONICAL}.\n\nDivergence: a document store shares no transaction.\n'
>         f'{CONFORMANCE_LINE} {conformance}\n"""\n'
356c649
<     unnamed = f'"""Variant of {CANONICAL}."""\n'
---
>     unnamed = f'"""Variant of {CANONICAL}.\n{CONFORMANCE_LINE} {conformance}\n"""\n'
364,365c657,660
<     reported = variants_without_a_divergence_note(tmp_path, CANONICAL)
<     assert reported == ["otc_projector: the banner has no line beginning 'Divergence:'"]
---
>     modes = {"projector": DOCUMENTED_VARIANT, "notifications": DOCUMENTED_VARIANT}
>     examined, problems = variant_problems(tmp_path, CANONICAL, modes)
>     assert examined == ["otc_notifications", "otc_projector"]
>     assert problems == ["otc_projector: the banner has no line beginning 'Divergence:'"]
```

#### K4-lint-imports

```
Broken contracts
----------------

No service's application or presentation layer imports the Kafka client (R14: 
only the relay's adapter publishes)
--------------------------------------------------------------------------------
---------------------------------

otc_projector.presentation is not allowed to import aiokafka:

-   otc_projector.presentation.projector_facts_consumer -> aiokafka (l.30)
```

*133 mutation blocks in this section.*

## 11. How to test it manually, and what is left open

**Manually, against the developer stack** (`docker compose -p otcpy -f docker-compose.infra.yml start`):

1. `uv run uvicorn otc_projector.main:app --port 8105` (a NEW consumer group replays every retained fact from the beginning: idempotent, safe, and it re-materialises every probe fact ever injected into a dev topic). `curl localhost:8105/health/ready` -> `{"status":"ready"}`; `/health/live`; no other route.
2. Watch the signal: any NATS client subscribed to `readmodel.>` (frames carry `x-correlation-id` = the order id).
3. Place an order as in N3 (`orders.create`, then `billing.payment.register` once `invoiced`) and read `otc_read_model.order_timeline` (`db.order_timeline.find({orderReference: "ORD-000013"})`): nine entries, the tie group `payment.received` -> `credit.released` -> `order.completed` in that order, `status: completed`.
4. Stop and start the projector: no document changes, the group's committed offsets resume where they were.

**Automated:** `./quality.sh` (section 8); or the narrowest: `uv run pytest services/projector -q` (Docker needed for the integration files), `uv run pytest tests/architecture services/orders/tests/unit/test_idempotent_consumer_parity.py -q`, `uv run lint-imports`.

**Open, for the leader (none blocks `in_review`):**

* Findings 4.2.1 – 4.2.3 are ACCEPTED with re-open triggers; design 5.1's sentence about the `DuplicateKeyError` race is true only below server 4.2 and may be amended.
* The six `Live dev data` facts of finding 4.2.4 and the N4 side effect belong in `progress/current.md` (not touched).
* Backlog 214 (the unbounded `nats.connect` in Orders, Fulfillment and Billing) is untouched, as briefed; `composition.connect_nats` and `test_pr45_…` are a ready shape for it.
* Feature 27 carries two acceptance items for this (routed by the review, R-1, `feature_list.json` id 27): fact consumers started from `earliest` run on private topics or commit their group to the end first (finding 4.2.5), and `I4-commit-before-handler` and `PR38` are re-run once the retry wrapper lands (#8 id 94).
* `uv.lock` changed only in the `otc-projector` member's dependency lists (8 lines); the commit's `Packages installed:` line reads "none (four existing packages added as dependencies of otc-projector)".
* Nothing was committed or pushed.

---

## Round 2 (after rejection 1: B1, B3, B4 blocking; B2, N3, N4, N5 bundled)

Arm logs: `.arm/p24-r2/*.log`, backups `.arm/p24-r2/*.bak` (git-ignored; sha256 before/after recorded by `.arm/p24-r2/arm.sh`, `cmp` after each restore printed `restored-identical`, `__pycache__` cleared after each).

### B1 — the stored-specification comparison, armed (`PR52`, acceptance 3)

Tests added to `integration/test_read_model_indexes.py`: `test_pr52_the_stored_partial_filter_is_compared_with_the_expected_definition` (the review's `{$type: 2}` alias index: `ensure_indexes` raises nothing, only `verify_indexes` fails, naming the index, `partialFilterExpression` and the one-liner) and `test_pr52_a_stored_non_unique_index_of_the_expected_name_fails_the_verification` (a fake collection serves a non-unique stored spec, since the server refuses to create it). `requirements.md` §3's PR22/PR39/PR52 row now names them.

* `B1-differences-dead` (`if differences:` to `if False and differences:`; sha `854a7bd11699acaf` to `8eb00701d07fb473`): `Failed: DID NOT RAISE ReadModelIndexError`, `2 failed, 6 passed` (the review's survivor: 224 passed).
* `B1-unique-comparison-dead` (the uniqueness branch made `if False:`): `Failed: DID NOT RAISE ReadModelIndexError`, `1 failed, 7 passed`.
* Restored, `cmp` identical; green: `8 passed`.

### B2 — code 85 names the server's index

`read_model_indexes.py`: on code 85 the culprit is parsed from the server's own message (`different name: uq_other`, regex `EXISTING_NAME_IN_CODE_85`), the message says `(expected uq_order_reference)` and the one-liner drops the culprit. Test: `test_pr22_an_identical_index_under_another_name_fails_the_boot_naming_the_server_named_index`. The test caught a bug in my first regex (`\S+` captured the trailing comma: `dropIndex("uq_other,")`); fixed with `[^\s,]+`.

* `B2-expected-name` (`culprit = expected.name` on 85): `AssertionError: the one-liner does not drop the index the server named: index uq_order_reference already exists on renamed_box … dropIndex("uq_order_reference")`. Restored, green.

### B3 — the registration guard bites at n = 1 (`tests/architecture/test_registration_behaviour.py`)

New rule (in `registration_statements`, applied in `violations`): each recorded registration's statement must name its message and handler by plain `Name`/`Attribute` references (the handler may be a `lambda` factory) that are NOT a parameter or a local (any `Store` name: loop variable, unpacked pair, alias) of the enclosing function; a lambda must not close over such a local. The old "share one statement" clause stays (it is the same defect at n >= 2, and `K3-pipeline` still passes through it).

Premises of the new instrument, each armed: (1) the AST statement found for the recorded caller line is the registration (the old cross-check, unchanged); (2) the enclosing function is the innermost `def` (parent map); (3) "bound" means parameters plus every `Store` name in the function, so a loop variable or alias counts; (4) a lambda's own parameters are not locals, a captured local is; (5) all five real roots (orders, fulfillment, billing, notifications, projector) pass: `13 passed` before the new sentinels, the orders root has `lambda scope: ...` factories, which is why lambdas are allowed.

Sentinels added: `test_sentinel_one_control_registration_with_literal_references_passes` (n = 1, literal references, a lambda over its own parameter: passes, so the instrument can say yes), `test_sentinel_a_single_registration_driven_by_a_helper_or_a_loop_is_caught[one_helper|one_loop]` (n = 1, class-attribute self-registration, asserts exactly ONE recorded registration and no "share one statement"), `test_sentinel_a_handler_factory_closing_over_a_loop_variable_is_caught`.

Arms of the rule: `B3-rule-deleted` (`found[node.lineno] = []`): 3 failed; `B3-locals-ignored` (`argument.id in local` to `False`): 2 failed (`AssertionError: []`); `B3-lambda-ignored` (`and n.id in local` to `and False`): 1 failed.

**Arm against the projector's real root, the review's `Q8b` shape** (backups `.arm/p24-r2/{handlers,composition}.bak`, sha `64b21d037ae5f54b` and `e57aaf886ddf96ae`): `ProjectFactHandler(_SelfRegistering, message=ProjectFactCommand)` re-binding a class attribute on the base (no module-level container), drained in `composition.py` by `_one(registry, message, handler)` called from a loop:

```
FAILED tests/architecture/test_registration_behaviour.py::test_a_service_registers_only_from_its_composition_root_and_its_tables_match[projector]
E   Left contains 2 more items, first extra item: 'WIRE: register_command(otc_projector.application.messages.ProjectFactCommand) at composition.py:89 is data-driven: the message `message` is a parameter or a local of `_one`'
```

The loop written inline in `register_handlers` fails the same test (`… is a parameter or a local of register_handlers`). Both restored with `cmp` identical (`e57aaf886ddf96ae`); `K3-pipeline`'s fixture still passes through the "share one statement" clause. This closes acceptance 8: the guard is now armed against this service's real n = 1.

### B4 — `test_r50_…` can tell `occurredAt` from `eventId` order

`integration/test_timeline_projection.py`: `chain()`'s `eventId`s now DESCEND with time (placed `0xA0005` … despatched `0xA0001`, the causes follow), the module docstring and the in-test comment now say what the fixture is (the earlier text claimed the causal order differed; it was the same as `occurredAt`). `specs/shared/test-matrix.md` R50 column 5 wording updated to match ("neither the `occurredAt` order nor the `eventId` order"; column 5 only).

* `R50-arrival-order` (`sortBy` without `occurredAt`, sha `ff45b14be9c3f5e0` to `1b0027570cd87d4d`): `AssertionError: the timeline is not ordered by occurredAt … At index 0 diff: '000a0001-…' != '000a0005-…'`, `1 failed` (the review: `1 passed`). Restored; the module's 4 tests green.

### N3, N4, N5

* N3: the three docstrings (`infrastructure/persistence/timeline_order.py`, `domain/timeline_order.py`, `infrastructure/persistence/mongo_read_model_writer.py`) now state the measured premises (the cap never binds, termination comes from the bounded `$reduce`; the `DuplicateKeyError` retry is unreachable on `mongo:8.3.8`). `design.md` was the leader's half. Re-enumerated on the retired wording: `grep -rn -i 'cycle terminate\|so a cycle\|cap makes\|one insert lose\|makes one insert' services/projector/src services/projector/tests specs/projector_read_model` returns 4 hits after the edit, each now a conditional or measured statement (the writer docstring, `design.md:210`, `design.md:279`, and `requirements.md:60`, which states the correct requirement).
* N4: `test_pr41_ids_…` now asserts both `$max` operands of `updatedAt` are `.mmmZ` instants. Arm `N4-isoformat` (`occurred_at = delta.entry.occurred_at.isoformat()`): `AssertionError: updatedAt operand '2026-03-02T16:12:36.113000+00:00' is not a .mmmZ instant` (the review: both named guards stayed green). Restored, green.
* N5: the stale comment in `test_projector_lifespan.py` now says the topics are private to the test.
* §11's "Feature 27 must …" sentence now cites the two acceptance items the leader appended to feature 27.

### Verification

* After all fixes, with the developer stack down (`docker ps`: `otcpy-n8n` only): `tests/architecture` + `services/projector` + the Orders parity guard + the seed constants test: `886 passed in 92.49s`.
* `ruff format --check`, `ruff check`: clean (one E501 in my own docstring fixed).
* `./quality.sh` once, developer stack down (`docker ps`: `otcpy-n8n` only): exit 0, 482 s, `4082 passed in 450.12s` (round 1: 4075, +7 new cases), `Contracts: 11 kept, 0 broken`, coverage 97.26% overall (`Required test coverage of 60.0% reached`), Vitest 1 passed, `quality.sh: all gates passed`. Log: `.arm/p24-r2/quality.log`.
* `feature_list.json` id 24: `pending`-in-HEAD / `in_progress` in the tree to `in_review` (that one line; `git diff` read: the only other hunks are the leader's feature 27 items).
* Surprise: my first `register_*` rule rejected the Orders root, whose handlers are `lambda scope: Saga(...)` factories; lambdas are now allowed unless they close over a function local. My first code-85 regex captured a trailing comma, caught by the new test.

---

## Round 3 (after rejection 2; scope B5, B6, N9)

Files: `tests/architecture/test_registration_behaviour.py`, `services/projector/tests/integration/test_timeline_projection.py`, `specs/projector_read_model/tasks.md` (K3, J1 notes), `specs/shared/test-matrix.md` (R50 column 5 only: its sentence "the `eventIds` descending with time" would have become false), `feature_list.json` (id 24 status line only). No production code. Arms in `.arm/p24-r3/` (backups with sha256, `cmp` on restore, process-group watchdog).

### B5 — the statement must NAME what it registers

Change: the probe now also records the registered handler's class name (`handler`, only when the second argument is a class; a factory lambda has none). `registration_statements` returns, per statement, its problems plus the terminal identifier of the message argument and the identifiers the handler argument names (its terminal identifier, or every name in a factory lambda's body). `violations` adds two clauses per recorded registration: the recorded message class name must equal the statement's message identifier (`does not name its message`), and, when a handler class was recorded, its name must be among the handler identifiers (`does not name its handler`). All 36 `register_*` statements in the five roots satisfy both (the parametrised real-root case is green). Header (`:4-6` untouched list of what a syntax guard loses; `:14-26`) rewritten. Stated limit: for a lambda handler (Orders' five events) only the message is checked against the recorded class, since the probe records no handler class there.

New sentinels: `one_holder` (S5 shape, class-attribute holder) and `one_globals` (S6 shape, module globals), both n = 1, one direct statement, no helper/loop/local: `test_sentinel_f_j_alone_at_n_equals_one_is_caught_by_the_statement_naming_rule[one_holder|one_globals]` assert both new messages and no "data-driven" / "share one statement"; `test_sentinel_a_handler_argument_that_does_not_carry_the_registered_class_name_is_caught` (`one_alias`: message right, handler imported under an alias) isolates the handler clause.

Arms (guard sha `16c125637c7bb2d8`, restored `cmp` identical each time):

* `S5-class-attr-holder` on the projector's REAL `handlers.py`+`composition.py`: `test_a_service_registers_only_from_its_composition_root_and_its_tables_match[projector]` FAILED, `… ProjectFactCommand) at composition.py:90 does not name its message: the statement says \`message\``.
* `S6-module-global-unpack` on the real root: FAILED, `… at composition.py:92 does not name its message: the statement says \`_MESSAGE\``.
* `M-name-dead` (message clause `if False and …`): `2 failed` — the two F-j-alone sentinels, `AssertionError: ["WIRE: … does not name its handler \`HandleA\`: the statement says ['handler']"]` (the message assertion lost).
* `M-handler-dead` (handler clause dead): `3 failed` — both F-j-alone sentinels plus the alias sentinel, `assert any("does not name its handler …")` over `[… does not name its message …]` / `[]`.

### B6 — premise (2), and the premise list as it now stands

Sentinel `test_sentinel_a_helper_def_nested_in_the_root_is_caught_by_the_innermost_function` (`one_nested`: helper `def _one(message, handler)` nested in `build_dispatcher`, loop variables `m, h` so only the innermost `def` knows `message` is a parameter). Arm `B3r-outermost` (`enclosing_function` returns the outermost `def`): `1 failed, 20 passed` — that sentinel, `assert any("is data-driven: the message \`message\` is a parameter or a local of \`_one\`" …)` over the new naming messages. Also `S8-nested-helper` on the real root fails the projector case (`… is data-driven: the message \`message\` is a parameter or a local of \`_one\``).

Premises of the guard as it stands, with the arm that saw each fail:

1. the statement at the caller line is the registration (old cross-check): `S2`/`S3`/`S4` (review round 2, P3), fixture `getattr`; not re-armed in round 3, the path is unchanged.
2. the enclosing function is the INNERMOST `def`: `B3r-outermost` (round 3, above) — now armed.
3. "bound" = parameters + every `Store` name: `B3r-params-only` (review round 2, P3), `2 failed`; unchanged path.
4. a lambda's own parameters are not locals: `one_control`/`one_lambda` + `B3-lambda-ignored` (round 2).
5. the five real roots pass: the parametrised real-root case (green in round 3).
6. (new) the recorded message class name is the terminal identifier of the message argument: `S5`, `S6` on the real root, `M-name-dead`.
7. (new) the recorded handler class name is among the identifiers the handler argument names: `M-handler-dead` on the sentinels. Armed only on fixtures, not on a real-root shape (no real-root shape isolates the handler clause; `S5`/`S6` fail the message clause first). UNARMED against the real root; stated.
8. (new) a factory lambda's handler class is not checked (not recorded): a documented gap, no arm.

### N9 — R50's fixture

`eventId`s scrambled (placed `0xA0003`, reserved `0xA0005`, approved `0xA0001`, confirmed `0xA0004`, despatched `0xA0002`, causes follow the chain); arrival changed to despatched, approved, reserved, placed, confirmed (the first scramble made arrival equal the `eventId` ascending order, so arrival moved: three distinct orders, none the reverse of another). Docstring and in-test comment say so. Case name unchanged; the matrix sentence about the `eventIds` fixed (false otherwise). Arms on `timeline_order.py:92` (sha `ff45b14be9c3f5e0`): `R50r-arrival-order` (`sortBy` without `occurredAt`): FAILED, `the timeline is not ordered by occurredAt … At index 0 diff: '000a0001-…' != '000a0003-…'`; `R50r-eventid-desc` (`eventId: -1`): FAILED, `… At index 0 diff: '000a0005-…' != '000a0003-…'` (round 2: this one survived).

### Verification

`ruff format --check` / `ruff check` on `tests/architecture` and `services/projector`: clean; mypy on the guard file clean. `tests/architecture` + `services/projector` + Orders parity guard + seed constants: `890 passed in 90.22s` (886 + 4 new cases), developer stack down (`docker ps`: `otcpy-n8n` only). `./quality.sh`: see the line below.

`./quality.sh` once, developer stack down: exit 0, 511 s, `4086 passed in 475.17s` (round 2: 4082, +4 new cases), `Contracts: 11 kept, 0 broken`, coverage 97.26% (`.arm/p24-r3/quality.log`). Feature 24 status set to `in_review` (that line only).
