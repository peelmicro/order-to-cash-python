# Requirements — `outbox_and_idempotency` (feature 14, phase 8, `sdd: true`)

> **This is a pointer document.** `specs/shared/` was copied verbatim from #8 (with `SA-1` – `SA-5` applied) and is **read-only**. The shared requirements this feature realises, **R11 – R18**, are cited here by id and are **not restated**: `specs/shared/requirements.md` §2 (lines 128 – 165) is their single authority, together with the envelope of `specs/shared/domain-model.md` §7.1, the three idempotency layers of `specs/shared/saga.md` §6 and the `Envelope` / `FactHeaders` schemas of `specs/shared/asyncapi.yaml`. Nothing below amends, rewords or reinterprets them. The value of this feature's spec is in [`design.md`](./design.md).
>
> **Local ids.** This file reuses #8's local ids **`OI1` – `OI16`** with their numbering unchanged (`OI1` – `OI12` are #7's, `OI13` – `OI16` are #8's; `../order-to-cash-dotnet/specs/outbox_and_idempotency/requirements.md` lines 57 – 103, `../order-to-cash-nestjs/specs/outbox_and_idempotency/requirements.md` lines 34 – 56), so the three feature specs compare line by line. Reusing one is a claim that #9 owes the same obligation; where the Python/PostgreSQL realisation is differently shaped, a *#9 note* says how. **`OI17` – `OI20` are new in #9**, each tied to an acceptance item of `feature_list.json` id 14 that #7 and #8 did not carry. No new `R<n>` is written.

## 1. Shared requirements realised

| Shared id | One-line reminder (authority: `specs/shared/requirements.md`) | Realised in #9 by | `design.md` |
|---|---|---|---|
| **R11** | Complete envelope; no field absent, null or empty; `eventType` matches `<aggregate>.<fact>.v<n>` | A pure guard `validate_domain_event_envelope` in `otc_shared_kernel` (§1.1), called by the outbox writer before any row is built; the generic `Envelope[P]` in `otc_contracts` re-validates at the writer and the relay | §4.4 – §4.6, §5.4 |
| **R12** | `correlationId` = order id; `causationId` = the causing event or command | The aggregate mints both (feature 13, `specs/orders_aggregate/design.md` §7.3); the writer copies the five identity fields into columns verbatim and the relay rebuilds the envelope from those columns alone | §4.4, §5.4 |
| **R13** | Aggregate state and outbox records in one transaction of one write model, or neither | `SqlAlchemyUnitOfWork.begin()`: one `AsyncSession`, one transaction pinned to `READ COMMITTED`; the repository writes aggregate rows and one outbox row per event inside it | §4.1 – §4.3 |
| **R14** | Only the relay publishes; stamped only after the broker acknowledges; unstamped records republished on a later poll | `OutboxRelay.run_once()`: claim, publish, stamp, commit; every failure path rolls back. "No command handler, aggregate or domain service publishes directly" is an import-linter contract (`OI16`) | §5.1 – §5.6, §9 |
| **R15** | `correlationId` is the partition key | `KafkaFactPublisher` keys every record by `str(correlation_id)` as UTF-8, with aiokafka's idempotent producer (`OI7`) | §5.5 |
| **R16** | Consumer retry with backoff, then `<topic>.dlq`, then acknowledge | **Not realised here: deferred to feature 27** (§1.2). The row stays `TODO` | §7 |
| **R17** | (`eventId`, consumer) recorded in the same transaction as every effect | `IdempotentConsumer.run_once(event_id, consumer, work)` inserts the dedup row first, inside the same unit-of-work transaction as `work` | §6.1, §6.2 |
| **R18** | A redelivery is acknowledged with no mutation, no fact, no command | The duplicate branch: `INSERT … ON CONFLICT (event_id, consumer) DO NOTHING RETURNING` returns no row, the transaction rolls back and `work` is never invoked | §6.1 |

**Reusing an id is a claim.** Each row asserts that the Python realisation satisfies the requirement #7's and #8's do. Two rows differ in mechanism, not in obligation: `R13`'s transaction boundary is an async context manager over one `AsyncSession` (neither #7's branded handle nor #8's DI scope), and `R18`'s duplicate is detected by `ON CONFLICT DO NOTHING` rather than by catching a duplicate-key error (PostgreSQL aborts the whole transaction on any error; `design.md` §6.1 argues it).

### 1.1 `R11` has no owner in #9 yet, and this feature closes it

`specs/shared/test-matrix.md`'s `R11` row is `TODO` in this repository (line 106) and names a **domain unit** test, `shared-kernel/domain/event-envelope.spec`. #9's feature 7 (`shared_kernel`) shipped no envelope guard: `packages/shared_kernel/src/otc_shared_kernel/entity.py:32-33` types events as `object` because *"the fact envelope (R11) lives in `contracts`"*. That sentence stays true: the envelope **model** is `otc_contracts`' (`OI20`); what the kernel gains is a pure guard over six scalar values, importing nothing from `contracts`. #8 was in exactly this position and closed it in its feature 14 (#8 `requirements.md` §1.1; `src/SharedKernel/DomainEventEnvelope.cs`); #7's kernel had shipped it earlier (`assertValidDomainEventEnvelope`, #7 `requirements.md` line 60, *"R11 is already DONE"*). #7 and #8 agree on the home (the kernel) and the level (domain unit), so #9 adopts both: a pure function in `otc_shared_kernel`, live because the outbox writer calls it. No shared text changes.

### 1.2 The `R16` deferral — adopted, both predecessors decided it identically

`R16` is consumer-side retry and dead-lettering. #7 deferred it to feature 27 at its own gate (#7 `requirements.md` line 22, *"The `R16` deferral — ratified, not overlooked"*; #7 `progress/history.md` line 775, *"`R16` deliberately left `TODO` for feature 27, a deferral ratified at the gate"*), and #8 did the same (#8 `requirements.md` §1.2). #9's feature 27 carries the matching acceptance bullet (*"failed processing lands on `<topic>.dlq` after N attempts with SA-3 header semantics"*), and this feature builds no fact-stream consumer for a retry wrapper to wrap: the matrix row names `orders/integration/saga-dead-letter.spec`, a saga file. Python forces no difference. **Decided, not an open point:** feature 14 is complete when `R11`, `R12`, `R13`, `R14`, `R15`, `R17`, `R18` are green; `R16` stays `TODO` for feature 27, whose seam is `design.md` §7.

## 2. Local requirements

### 2.1 Reused from #7 and #8 (`OI1` – `OI16`)

Texts are #8's, verbatim (`../order-to-cash-dotnet/specs/outbox_and_idempotency/requirements.md` lines 57 – 103), line-unwrapped only.

**OI1.** THE SYSTEM SHALL persist, for every outbox record, every field of the `R11` envelope — `eventId`, `eventType`, `aggregateId`, `correlationId`, `causationId`, `occurredAt` and `payload` — such that the relay reconstructs the published envelope from the stored record alone, inferring, defaulting or regenerating no field at publication time; and IF any envelope field is absent from a record about to be written, THEN THE SYSTEM SHALL refuse the write rather than store an incomplete envelope.

> *#9 note.* The columns exist since feature 9 (`services/orders/src/otc_orders/infrastructure/persistence/models.py:156-173`, `causation_id` included). This feature adds the refusal at the writer and a row-to-envelope mapper that receives only the stored row: no clock, no `uuid4`, no default.

**OI2.** THE SYSTEM SHALL order the relay's publication of unpublished records by a **strictly increasing, tie-free sequence assigned at insertion**, so that two records written by one transaction — which necessarily share a `correlationId` and may share an identical `occurredAt` — are always published in the order the aggregate appended them, and so that the publication order of any two records of one write model is the same on every poll and on every relay instance.

> *#9 note.* `outbox.seq` is `bigint GENERATED ALWAYS AS IDENTITY` (`models.py:172`). #8 found its ORM assigned identity values out of `Add` order (#8 `progress/history.md` line 744); #9 does not trust the SQLAlchemy unit of work's batching either and inserts one outbox row per awaited flush, in raise order (`design.md` §4.4, ledger row L4).

**OI3.** THE SYSTEM SHALL select the records to publish by the **absence of a publication stamp** and never by a stored high-water mark of the ordering sequence, so that a record whose transaction committed after a higher-sequence record had already been published is still found and published on a later poll.

**OI4.** WHILE two or more relay instances poll one write model concurrently, THE SYSTEM SHALL grant each unpublished record to at most one instance per poll cycle, so that no record is published twice as a result of concurrent claims and no record is skipped because another instance holds it.

**OI5.** IF a relay instance terminates, loses its database connection or fails after claiming records and before stamping them published, THEN THE SYSTEM SHALL make those records claimable again without operator action, without a lease-expiry wait and without a compensating sweep, and SHALL publish them on a later poll — accepting the resulting duplicate publication as the at-least-once contract of `R14`.

**OI6.** WHILE a poll cycle of one relay instance is in progress, THE SYSTEM SHALL NOT begin a further poll cycle in that instance, so that the configured poll interval can never cause overlapping cycles to compete for the same records.

**OI7.** THE SYSTEM SHALL configure the fact-stream producer so that a retry performed inside the producer client can neither reorder the records of one partition nor create a broker-side duplicate of a record the broker already accepted.

**OI8.** IF the broker rejects or fails to acknowledge a claimed batch, THEN THE SYSTEM SHALL leave every record of that batch unpublished, SHALL log the failure with the `correlationId` and `eventId` of the affected records, SHALL retry the same records on the next poll, and SHALL NOT skip them, drop them, reorder them or publish a later record ahead of them.

**OI9.** WHEN a unit of work that persisted an aggregate and its outbox records is rolled back, THE SYSTEM SHALL leave no outbox record and no aggregate change behind, and a retry of the same operation SHALL produce exactly one outbox record per emitted fact — never zero, which is what a retry driven from an aggregate instance whose events were already cleared would produce.

> *#9 note.* #7 recorded this rule as *demonstrated, not guarded* (its review D9); #9 guards it with a retry driven from the **same** in-memory instance after a rollback (`design.md` §4.3).

**OI10.** IF the same (`eventId`, consumer) pair is delivered concurrently to two consumer instances of one write model, THEN THE SYSTEM SHALL apply the handler's effects exactly once — one delivery committing its effects together with its dedup record, the other observing the dedup record and reporting a duplicate without applying any effect.

**OI11.** THE SYSTEM SHALL keep the `outbox` and `processed_events` definitions — every column, type, nullability, key and index — identical in every write model that carries them, and SHALL prove that identity mechanically rather than by inspection.

> *#9 note — inherited satisfied.* `tests/database_parity/test_reliability_table_parity.py` › `test_outbox_and_processed_events_are_identical_across_the_four_databases` (feature 11) already compares the live catalogues of the four migrated databases. This feature changes no schema, so the obligation is that the test stays green.

**OI12.** THE SYSTEM SHALL keep every per-service copy of the idempotent-consumer pattern in textual agreement with one designated canonical copy, normalising only the per-copy banner and the single namespace declaration in which a copy declares where it lives, and SHALL prove that agreement mechanically rather than by inspection; and IF a write model that consumes facts carries no copy of the pattern, or a copy diverges from the canonical outside those two regions, or the canonical acquires a service-specific name or reference another service could not adopt verbatim, THEN THE SYSTEM SHALL fail the check. WHERE a component's dedup ledger is not a relational `processed_events` table and the pattern therefore cannot be copied verbatim, THE SYSTEM SHALL require that component's variant to name the canonical copy and state its divergence in prose, and SHALL exclude it from the textual comparison.

> *#9 note — the same obligation, one region fewer.* #7 predicted #9 *"one module"* would make this unnecessary (#7 `progress/history.md` line 788); it does not, for #8's reason: CLAUDE.md admits three shared runtime packages (`shared_kernel` and `cqrs` with `dependencies = []`, `contracts` for wire models), and this pattern talks to SQLAlchemy. Python has no namespace declaration, so #9 normalises **only the banner** (#7's original rule); the "namespace line" clause is vacuous here and is satisfied trivially.

**OI13.** THE SYSTEM SHALL claim unpublished outbox records under an **explicit update lock that skips records another transaction already holds**, taken at row granularity and at an isolation level under which such a skipping read is legal, so that concurrent relay instances take disjoint batches; and THE SYSTEM SHALL make the claim's behaviour independent of the write model's row-versioning configuration, so that a database created with statement-level row versioning enabled neither weakens the claim into a versioned read that sees stale rows nor causes the claim to fail.

> *#9 note — the obligation, mapped onto PostgreSQL.* `FOR UPDATE SKIP LOCKED` is native, as in #7. PostgreSQL is always multi-version; its analogue of *"row-versioning configuration"* is the isolation level a connection inherits (`default_transaction_isolation`, or an engine's `isolation_level`). Under `REPEATABLE READ` a locking read of a row concurrently stamped and committed raises `40001` instead of re-evaluating it, so the claim pins `READ COMMITTED` per transaction and is proven independent of an engine whose default is `REPEATABLE READ` (`design.md` §5.2).

**OI14.** IF the broker has not acknowledged a claimed batch within the configured publication timeout, THEN THE SYSTEM SHALL abandon the wait, SHALL **roll the claim transaction back** rather than commit it, SHALL leave every record of that batch unstamped, and SHALL retry the same records on the next poll; and THE SYSTEM SHALL hold no claim transaction open for longer than that timeout plus the time the claim and the stamp themselves take.

**OI15.** THE SYSTEM SHALL publish, for a stored outbox record, an envelope whose seven fields appear in the order `asyncapi.yaml` declares them and whose six scalar fields reproduce byte for byte the bytes assessment #7 published for the same record, and SHALL republish the stored payload text **unchanged**, so that what a consumer receives is what the producing transaction committed; and THE SYSTEM SHALL produce, for the same business inputs, a payload **semantically equal** to #7's — same keys, same values, same types, same casing — with key order asserted nowhere.

> *#9 note.* PostgreSQL `json` (not `jsonb`) stores the text as written (`persistence/types.py:1-12`). The relay parses the stored text and re-writes it through the one serializer; for text the writer produced, and for #7's golden bytes, that is a fixed point, and the byte-exact case proves it rather than assumes it (`design.md` §5.4).

**OI16.** THE SYSTEM SHALL confine the fact-stream producer client to the outbox relay's adapter, such that no type in a domain, application or presentation namespace of any service can reference it, and SHALL prove that confinement with a check that fails the build rather than with a convention.

> *#9 note.* The check is an import-linter `forbidden` contract over every service's `application` and `presentation` (the existing `domain-purity` contract already forbids `aiokafka` in every `domain`); the `FactPublisher` protocol lives in `infrastructure.outbox`, so the existing layers contract already keeps `application` from reaching it (`design.md` §9).

### 2.2 New in #9 (`OI17` – `OI20`)

Each exists because an acceptance item of `feature_list.json` id 14 asks for a property #7 and #8 did not specify.

**OI17.** IF a relay poll cycle's transaction is chosen as a deadlock victim, THEN THE SYSTEM SHALL retry the whole cycle within the same `run_once` call, up to a fixed bound, without the deadlock error escaping `run_once` while the bound is not exhausted, and SHALL leave unstamped every record whose cycle did not commit.

> *Why.* Acceptance item 3 (*"a deadlock victim … handled inside run_once (#8 id 87)"*). #8 shipped the defect (a deadlock victim escaped `RunOnceAsync`; #8 `feature_list.json` id 87) and fixed it with a relay-scoped retry of SQL Server error 1205 (#8 `src/Orders/Infrastructure/Outbox/DeadlockRetryExecutionStrategy.cs:91-104`). #9 retries SQLSTATE `40P01` only.

**OI18.** IF a claimed outbox record cannot be reconstructed into a valid envelope, THEN THE SYSTEM SHALL publish and stamp every record of the claim that precedes it in sequence order, SHALL leave that record and every later record of the claim unpublished and unstamped, SHALL log it with its `eventId`, `correlationId`, sequence and the reason, and SHALL complete the poll cycle without raising; and THE SYSTEM SHALL NOT skip, park, delete or reorder it.

> *Why.* Acceptance item 3 (*"a poison payload … handled inside run_once (#8 id 111)"*). #8 left 111 an open question, dispositioned ACCEPTED, NOT FIXED: neither #7 nor #8 has a poison-row breaker, and in both a reconstruction failure escapes the relay's cycle (#7 `outbox-relay.ts:145-146`, #8 `OutboxRelay.cs:124`, both outside the publish `try`). The behaviour chosen here, and the alternative rejected, are **gate point G1** (`design.md` §12).

**OI19.** THE SYSTEM SHALL truncate every instant to whole milliseconds before persisting it or writing it into an envelope or payload, so that the stored value, the envelope's `occurredAt` and every payload instant derived from the same instant are equal.

> *Why.* Acceptance item 5 (backlog 205). PostgreSQL `timestamptz(3)` **rounds** (`.123987` is stored as `.124`, asserted by `services/orders/tests/integration/test_orders_json_and_timestamps.py` › `test_instants_come_back_aware_utc_and_rounded_to_the_millisecond`) while `otc_contracts.wire.format_instant` **truncates** (`.123`). #7's `Date` holds milliseconds and could not disagree; #8 did not face it in this form.

**OI20.** THE SYSTEM SHALL provide a generic envelope typed by its payload model such that every JSON serialisation path of it produces the bytes of the one wire serializer, writes no instant with sub-millisecond digits, and refuses an instance whose payload skipped validation.

> *Why.* Acceptance item 6 (backlog 203 item 2): *"a generic Envelope[P] … model_dump_json() == to_wire_json(), no microsecond instant, a model_copy(update={...: 89.34}) of the payload refused by model_dump_json and by to_wire_json"*.

## 3. Local traceability

Shared `R11` – `R15`, `R17`, `R18` are traced in [`specs/shared/test-matrix.md`](../shared/test-matrix.md) §2; the implementer writes **column 5 only**, citing the literal test function names below (not a name pattern: #8 review D7), and updates the derived counts including the **Total** row (#7 review D6). `R16` stays `TODO`. The local ids are traced here; every row starts `TODO`.

| Id | Level | Test file › case | Status |
|---|---|---|---|
| **R11** (shared row) | domain unit | `packages/shared_kernel/tests/test_event_envelope.py` › `test_r11_event_envelope_refuses_an_envelope_with_an_absent_null_or_empty_field_and_an_event_type_that_does_not_match_the_pattern`, `test_r11_event_envelope_accepts_a_complete_envelope_and_every_event_type_of_the_catalogue` | DONE |
| **R12** (shared row) | integration | `services/orders/tests/integration/test_outbox_envelope.py` › `test_r12_stamps_every_fact_of_one_order_with_the_order_id_as_correlation_id_and_the_causing_event_id_as_causation_id` | DONE |
| **R13** (shared row) | integration | `services/orders/tests/integration/test_outbox_atomicity.py` › `test_r13_persists_neither_the_aggregate_nor_the_outbox_record_and_publishes_nothing_when_the_transaction_fails`, `test_r13_rolls_back_an_outbox_row_already_written_when_a_later_save_in_the_same_transaction_fails` | DONE |
| **R14** (shared row) | integration | `services/orders/tests/integration/test_outbox_relay.py` › `test_r14_stamps_a_record_only_after_the_broker_acknowledgement_and_republishes_an_unstamped_record_on_the_next_poll` | DONE |
| **R15** (shared row) | integration | `services/orders/tests/integration/test_fact_partitioning.py` › `test_r15_delivers_all_facts_produced_by_one_context_about_one_order_to_consumers_in_emission_order` | DONE |
| **R17** (shared row) | integration | `services/orders/tests/integration/test_idempotent_consumer.py` › `test_r17_records_the_event_id_and_consumer_name_in_the_same_transaction_as_the_state_change_and_the_outbox_records`, `test_r17_leaves_no_dedup_row_when_a_failure_inside_work_rolls_back_the_whole_transaction` | DONE |
| **R18** (shared row) | integration | same file › `test_r18_acknowledges_a_redelivered_fact_without_mutating_state_emitting_a_fact_or_issuing_a_command` | DONE |
| **OI1** | integration | `services/orders/tests/integration/test_outbox_envelope.py` › `test_oi1_relay_reconstructs_the_complete_envelope_from_the_stored_record_alone`, `test_oi1_writer_refuses_an_event_with_an_incomplete_envelope_before_any_row_is_written`, `test_oi1_writer_refuses_an_event_type_outside_the_fact_catalogue`, `test_oi1_every_column_and_envelope_field_comes_from_its_own_event_field` | DONE |
| **OI2** | integration | `services/orders/tests/integration/test_outbox_relay.py` › `test_oi2_publishes_records_written_by_one_transaction_in_append_order_although_they_share_occurred_at`, `test_oi2_orders_the_claim_by_seq_never_by_occurred_at_when_they_disagree` | DONE |
| **OI3** | integration | `services/orders/tests/integration/test_outbox_relay.py` › `test_oi3_publishes_a_lower_sequence_record_that_committed_after_a_higher_one_was_published` | DONE |
| **OI4** | integration | `services/orders/tests/integration/test_outbox_relay_concurrency.py` › `test_oi4_two_concurrent_relays_take_disjoint_batches_and_publish_every_record_exactly_once` | DONE |
| **OI5** | integration | `services/orders/tests/integration/test_outbox_relay_concurrency.py` › `test_oi5_records_claimed_by_a_relay_whose_connection_died_are_claimed_on_the_next_poll_without_a_wait` | DONE |
| **OI6** | unit | `services/orders/tests/unit/test_outbox_relay_task.py` › `test_oi6_never_starts_a_second_cycle_while_one_is_in_progress`, `test_oi6_stop_waits_for_the_in_flight_cycle`, `test_relay_task_survives_a_failed_cycle_and_runs_the_next`, `test_relay_task_propagates_cancellation`, `test_relay_task_propagates_a_cancellation_that_arrives_during_the_inter_cycle_sleep`, `test_relay_task_waits_the_poll_interval_between_cycles_and_stop_cuts_the_wait_short` | DONE |
| **OI7** | unit | `services/orders/tests/unit/test_kafka_fact_publisher.py` › `test_oi7_producer_is_idempotent_so_an_internal_retry_can_neither_reorder_nor_duplicate` | DONE |
| **OI8** | integration | `services/orders/tests/integration/test_outbox_relay.py` › `test_oi8_leaves_every_record_of_a_rejected_batch_unstamped_logs_each_and_republishes_the_same_records_in_order`; adapter ordering-on-failure: `services/orders/tests/unit/test_kafka_fact_publisher.py` › `test_a_send_that_raises_stops_the_batch_and_names_that_fact_and_every_later_one` | DONE |
| **OI9** | integration | `services/orders/tests/integration/test_outbox_atomicity.py` › `test_oi9_a_retry_from_the_same_instance_after_a_rollback_writes_exactly_one_outbox_row_per_event` | DONE |
| **OI10** | integration | `services/orders/tests/integration/test_idempotent_consumer.py` › `test_oi10_applies_the_effects_once_when_the_same_event_is_delivered_concurrently` | DONE |
| **OI11** | integration | `tests/database_parity/test_reliability_table_parity.py` › `test_outbox_and_processed_events_are_identical_across_the_four_databases` — inherited satisfied (feature 11); re-run green | DONE |
| **OI12** | unit | `services/orders/tests/unit/test_idempotent_consumer_parity.py` › `test_case_1_every_write_models_copy_is_byte_identical_to_the_canonical_after_the_banner`, `test_case_2_the_canonical_is_adoptable_verbatim_naming_no_service`, `test_case_3_every_write_model_that_consumes_facts_carries_a_copy`, `test_case_4_a_variant_carries_a_divergence_banner_naming_the_canonical` | DONE |
| **OI13** | integration | `services/orders/tests/integration/test_outbox_relay_concurrency.py` › `test_oi13_a_claim_skips_rows_another_relay_holds_and_returns_without_waiting`, `test_oi13_the_claim_runs_at_read_committed_under_an_engine_defaulting_to_repeatable_read` | DONE |
| **OI14** | integration | `services/orders/tests/integration/test_outbox_relay.py` › `test_oi14_abandons_a_publish_that_exceeds_the_timeout_rolls_the_claim_back_and_republishes_on_the_next_poll` | DONE |
| **OI15** | integration | `services/orders/tests/integration/test_outbox_wire_parity.py` › `test_oi15_relay_publishes_bytes_identical_to_the_golden_envelope`, `test_oi15_writer_stores_a_payload_semantically_equal_to_the_golden_for_the_same_business_inputs`, `test_r11_published_envelope_carries_the_seven_fields_in_declared_order_with_none_absent_null_or_empty` | DONE |
| **OI16** | architecture | `pyproject.toml` contract `fact-producer-confinement` (run by `lint-imports` in `quality.sh`), armed | DONE |
| **OI17** | integration + unit | `services/orders/tests/integration/test_outbox_relay_deadlock.py` › `test_oi17_run_once_survives_a_constructed_deadlock_victim_and_retries_the_cycle`, `test_oi17_without_the_retry_the_constructed_deadlock_escapes_run_once_as_40p01`; `services/orders/tests/unit/test_deadlock_classifier.py` › `test_the_classifier_retries_only_a_deadlock_victim`, `test_run_once_retries_a_deadlock_victim_up_to_the_bound_then_lets_it_escape` | DONE |
| **OI18** | integration | `services/orders/tests/integration/test_outbox_relay.py` › `test_oi18_a_poison_row_blocks_at_itself_after_the_clean_prefix_is_published`, `test_oi18_a_poison_row_at_the_head_publishes_nothing_and_raises_nothing_on_every_poll` | DONE |
| **OI19** | integration | `services/orders/tests/integration/test_outbox_envelope.py` › `test_oi19_a_sub_millisecond_instant_is_stored_enveloped_and_written_in_the_payload_as_the_same_millisecond`, `test_oi19_every_instant_column_the_repository_writes_is_stored_truncated_never_rounded` | DONE |
| **OI20** | unit | `packages/contracts/tests/test_envelope_generic.py` › `test_oi20_model_dump_json_equals_to_wire_json`, `test_oi20_no_path_writes_an_instant_with_more_than_three_fractional_digits`, `test_oi20_a_payload_copied_past_validation_is_refused_by_model_dump_json_and_by_to_wire_json`, `test_the_generic_envelope_has_the_generated_envelopes_fields_aliases_order_and_pattern`, `test_wire_instant_truncates_and_agrees_with_format_instant` | DONE |

**Case names are the contract** (matrix rule 4): a renamed test edits its row in the same change.

## 4. Acceptance (from `feature_list.json` id 14)

| Acceptance item | Requirements |
|---|---|
| 1. aggregate row and outbox row written in one transaction | R13, OI1, OI9 |
| 2. relay claims with `FOR UPDATE SKIP LOCKED`, publishes keyed by `correlationId`, stamps `published_at`; skip-versus-block measured with the guard armed the other way | R11, R12, R14, R15, OI2 – OI8, OI13 – OI16 |
| 3. relay loop self-scheduled; a deadlock victim and a poison payload handled inside `run_once` (#8 ids 87, 111) | OI6, OI17, OI18 |
| 4. redelivery deduplicated via `processed_events` keyed on (`event_id`, consumer) | R17, R18, OI10, OI12 |
| 5. backlog 205: instants truncated to whole milliseconds before persist or envelope | OI19 |
| 6. backlog 203 item 2: a generic `Envelope[P]` | OI20 |

## 5. Promotion candidates — restated, not promoted; no spec amendment

#7 recorded `OI1`, `OI2`, `OI4` + `OI5` and `OI10` as promotion candidates for `specs/shared/`; #8 restated them without promoting (#8 `requirements.md` §5). #9 meeting the same four gaps a third time is further corroboration and nothing more: **this feature proposes no `SA-n` and edits nothing in `specs/shared/` except column 5 of the matrix and its derived counts.** Nothing in the implementation of R11 – R18 found the shared text wrong or incomplete; the questions it did raise (poison rows, deadlock victims, instant precision) are realisation questions answered locally by `OI17` – `OI19`.

## 6. What this feature changes outside its own directory

| Path | Change | Why |
|---|---|---|
| `packages/shared_kernel/src/otc_shared_kernel/event_envelope.py` (new), `__init__.py` | The pure `R11` guard and its error | §1.1 |
| `packages/contracts/src/otc_contracts/envelope.py` (new), `wire.py`, `__init__.py` | The generic `Envelope[P]`; `wire_instant` (the one millisecond truncation) | `OI19`, `OI20` |
| `services/orders/src/otc_orders/application/**`, `infrastructure/**` | Ports, unit of work, repository, outbox, relay, idempotent consumer, settings | `design.md` §1 |
| `services/orders/pyproject.toml`, `uv.lock` | `aiokafka` | `design.md` §10 |
| `pyproject.toml` | One import-linter contract (`OI16`); a pytest `filterwarnings` line only if aiokafka is measured to emit its own `DeprecationWarning` | `design.md` §9, §10 |
| `conftest.py` (root) | A session-scoped Kafka container fixture | `design.md` §11.3 |
| `tests/architecture/test_money_guard.py`, `test_write_path_population.py`, `test_cqrs_registration_explicit.py`, `packages/shared_kernel/tests/test_kernel_surface.py` | Census entries for the new code, each classified | `design.md` §9.2 |
| `.env.example` | The `OUTBOX_*` and `KAFKA_BROKERS` / `KAFKA_CLIENT_ID` variables (#7's names) | `design.md` §10 |
| `specs/shared/test-matrix.md` | Column 5 of R11 – R15, R17, R18 and the derived counts | §3 |

`services/orders/src/otc_orders/domain/**` does **not** change: the writer reads the events feature 13 already emits (`specs/orders_aggregate/design.md` §7.6), and the `R11` guard takes keyword arguments rather than requiring the events to implement a new interface.
