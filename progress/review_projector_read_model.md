# Review — feature 24 `projector_read_model` (phase 12, `sdd: true`, full group), round 1

> Written incrementally. Reviewer: `reviewer` (Opus). Inputs: `progress/brief_review_projector_read_model.md`, `specs/projector_read_model/{requirements,design,tasks}.md`, the gate ruling at the end of `progress/spec_projector_read_model.md`, `feature_list.json` id 24, `progress/impl_projector_read_model.md`, `CHECKPOINTS.md`, `CLAUDE.md` (read on disk). Mutation backups: `.arm/p24-review/` (git-ignored, checked with `git check-ignore`).

**Verdict:** REJECTED — 3 blocking findings (B1 index comparison unarmed, B3 registration guard vacuous at n = 1, B4 R50 evidence blind to eventId order). Details at the end.

## Probe log (written as each probe ran)

### Q1 — causal ordering (acceptance 1, PR10, PR30 – PR35)

**Own fixture** (scratch file `services/projector/tests/integration/test_zz_review_probe_q1.py`, deleted after the review; run through the real `MongoReadModelWriter` on the root conftest's Docker-held `mongo:8.3.8`): nine facts for one order — a tie group at `T0+5ms` holding a chain of three `X(eeee…) → Y(bbbb…) → Z(aaaa…)` (ids chosen so the `eventId` fallback alone inverts the chain) plus a fallback pair `P(cccc…)`, `Q(dddd…)` with foreign causes; `W` at `T0+1ms` whose `causationId` names `Z` in the LATER group; `V` at `T0+7ms` whose cause `U` is at `T0+9ms`; arrival `[Z, U, Q, Y, A, V, P, W, X]` (neither `occurredAt`, causal nor `eventId` order). Expected by hand from `openapi.yaml` `TimelineEntry` + `PR10`: `[A, W, P, Q, X, Y, Z, V, U]` (occurredAt wins across groups; inside the tie group depth 0 `{P, Q, X}` by `eventId`, then `Y`, then `Z`). Plus 18 arrival permutations of the tie group on fresh orders: all equal.

```
$ uv run pytest services/projector/tests/integration/test_zz_review_probe_q1.py -q
1 passed in 4.34s
```

**Mutation `Q1-no-depth`** (remove `__depth` from `sortBy` in `infrastructure/persistence/timeline_order.py`, sha `9e266433d4437cff → 0e511b5b7f731dc9`): my probe fails (`At index 2 diff: 'aaaaaaaa…' != 'cccccccc…'`), and so do the implementer's `test_r28_…` (`R28: stock.released must precede the order.cancelled that names it`), `test_r24_…`, `test_pr10_…differential` (77 sets disagree) and `test_pr31_…`. Restored, `cmp` identical.

**Mutation `Q1-cross-group-edge`** (drop the same-tie-group clause `{"$eq": ["$$p.occurredAt", "$$e.occurredAt"]}`): `test_pr10_the_pipeline_agrees_with_the_reference_rule_on_generated_entry_sets` fails (85 sets disagree, seed and set printed); my fixture and R24/R28 stay green (their edges are all in-group). Restored, `cmp` identical.

**Answer:** yes — the stored order equals the shared rule on a fixture where arrival, clock and edge all differ, and ignoring the edge fails four named tests. *Observation (non-blocking, no SA):* `openapi.yaml`'s wording is pairwise ("where no such recorded edge exists between two tied entries … `eventId` ascending"), which is non-transitive in my fixture (`Y < P` by fallback, `P < X` by fallback, `X < Y` by edge); `PR10`'s depth rule — #7's A1 and #8's realisation, unchanged — is the total order that honours every edge. No live tie group mixes a chain with an unrelated entry (design §5.4's three shapes are pure chains), so the two readings never disagree on live data. Disposition: accepted, re-open if feature 41 or any producer creates a tie group with an edge plus an unrelated tied entry.

### Q2 — out-of-order delivery and replay (acceptance 2, R52, PR38)

**Replay through Kafka.** `integration/test_replay_determinism.py::test_pr15_replaying_the_topics_into_a_new_group_reproduces_byte_identical_documents` produces through a real `AIOKafkaProducer` to three private topics, then boots the real `start_runtime` twice (groups `replay-g1` → database A, `replay-g2` → database B) and compares `RawBSONDocument.raw`; then `replay-g3` into A (all `DUPLICATE`, bytes unchanged, zero frames after a NATS barrier). Not an in-process call. My concern was that two groups reading one log see one arrival order, so the case could be blind to arrival-dependence; probed:

**Mutation `Q2-updatedAt-last-arrival`** (`updatedAt` ← the incoming `occurredAt` instead of `$max`, `delta_to_pipeline.py` sha `851603f7b00e8507 → dd1532e7f4242150`), the two `PR15` cases only:

```
E   AssertionError: order 00000000-0000-0000-0000-000015aaaa01: a replay into a new group produced different bytes
E   AssertionError: permutation (0, 1, 2, 3, 5, 4) produced different bytes
FAILED …test_pr15_replaying_the_topics_into_a_new_group_reproduces_byte_identical_documents
```

Both fail (the cross-topic interleaving of g1 and g2 differs in practice; the 720-permutation case is the deterministic guard). Restored, `cmp` identical.

**Restart performed, per test:** `test_pr15_replaying_…` = new consumer group (design §11.2 b), into an empty database and into the same one; `test_pr51_a_rebuilt_runtime_suppresses_every_applied_fact` and `test_the_runtime_starts_and_stops_in_two_successive_event_loops` = in-process rebuild (a); `test_pr15_shuffled_…` = none (writer only); process restart (c) = live walkthrough N4 only (record §9, offsets read with `kafka-consumer-groups.sh`). Each test's docstring names its model; one stale comment: `test_projector_lifespan.py:162` still says "the topics are session-wide" although the test now runs on private topics (cosmetic, see N-findings).

**Status never regresses, a reference never overwritten — own server probe** (`test_zz_review_probe_q2.py`, scratch, deleted): all 36 ordered pairs of the nine status facts with `rank(first) > rank(second)` applied later-rank-first, each followed by the five status-less facts: status and rank stay the first's in all 36; a second `order.despatched.v1` / `invoice.issued.v1` / `payment.received.v1` (different `eventId`, different reference, earlier `occurredAt`) leaves the first reference; a second `order.cancelled.v1` leaves the first `cancellationReason`. `2 passed in 4.67s`.

**Answer:** yes on all three counts, with the restart model of each test named above.

### Q3 — idempotency and the parity guard (PR23 – PR26, PR48, F1 – F3)

**Population.** `services/orders/tests/unit/test_idempotent_consumer_parity.py::test_pr48_…` asserts `on_disk == set(IDEMPOTENCY_MODE) == {gateway, orders, fulfillment, billing, notifications, projector, seed}` (a literal), then `registry_problems`, `mode_problems`, `spec_problems` (the non-`no-consumer` set against `asyncapi.yaml`'s `Consumer name — …` summaries on the three fact channels, parsed as YAML) and `spec_consumers == set(SPEC_CONSUMER_PACKAGE)`. Cases 1 and 3 select by mode, case 4 by the registry's `documented-variant`s and asserts `examined == ["otc_projector"]`. The population is fixed by literals cross-checked with disk and spec, not by a file the subject creates. Confirmed.

| Mutation (mine, `.arm/p24-review/`) | Result |
|---|---|
| `Q3a` remove `"projector": DOCUMENTED_VARIANT` from `IDEMPOTENCY_MODE` (sha `ba1132c527d17bb7 → 0d43b7eb850e78e4`) | 3 failed: `test_pr48_every_service_package_…` (`Extra items in the left set: 'projector'`), `test_pr48_p6_sentinel_…`, `test_case_4_…` (`assert [] == ['otc_projector']`). Restored, `cmp` identical |
| `Q3b` delete `services/projector/tests/integration/test_idempotent_consumer_conformance.py` (sha `18b707abf2f1c241`) | 1 failed: `test_case_4_…` — `"otc_projector: the 'Behavioural conformance:' line names '…/test_idempotent_consumer_conformance.py', which is not an existing file"`. Restored, `cmp` identical |
| `Q3c` (= E5) drop `"processedEventKeys": {"$ne": key}` from the variant's filter (sha `fc9f5b38c78db010 → b952769a4676c4b3`), parity guard **plus the whole projector suite** | parity guard: green (text, by design). Projector: **11 failed, 299 passed in 58.79s** — conformance cases 2, 3, 5 and `PR26`; `test_pr7_concurrent_deliveries_…`; `test_pr6_applies_one_fact_…`; `test_pr51_a_rebuilt_runtime_…`; `test_pr15_replaying_…`; `test_r51_…`; `test_r55_…`; `unit/test_mongo_read_model_writer.py::test_pr6_pr42_the_arguments_…`. Restored, `cmp` identical |

**Stays green that should not?** Under `Q3c`, `test_pr15_shuffled_and_duplicated_application_yields_byte_identical_documents` stays green: every permutation is followed by a full duplicate pass, so every run doubles every entry identically and the bytes still agree. It asserts determinism, not dedup, and R51 / conformance own dedup — correct classification, not a defect. **One limitation, non-blocking (N1 below):** the guard requires the conformance file to *exist*, not to contain the cases; an emptied file passes (`build_control_tree` itself uses an empty one). This is #7's rule verbatim (`../order-to-cash-nestjs/apps/orders/src/infrastructure/messaging/idempotent-consumer.parity.spec.ts:519-529`, existence only) and exactly what `PR48` asks.

**Answer:** population is declared; the three mutations fail the guard (a, b) or the behavioural suite (c, 11 named cases); the only green case under `Q3c` is correctly not a dedup guard.

### Q4 — indexes (acceptance 3, PR22, PR52)

Created at boot and before the consumer: `composition.start_runtime` steps 3 (`ensure_indexes` then `verify_indexes`), order proven by `unit/test_composition.py::test_pr43_start_runtime_runs_its_steps_in_order`.

**Sibling substitutions** (scratch `test_zz_review_probe_q4.py`, real `mongo:8.3.8`, `ensure_indexes` then `verify_indexes`; plus one case through the real `start_runtime`): all eight fail with `ReadModelIndexError`.

```
[same-name-plain-unique]        … uq_order_reference already exists … refused the creation with code 86 … dropIndex("uq_order_reference")
[same-name-other-partial]       ({$exists: true})  … code 86 … dropIndex("uq_order_reference")
[same-name-not-unique]          … code 86
[status-index-other-direction]  … ix_status_updatedAt … code 86 … dropIndex("ix_status_updatedAt")
[status-index-unique]           … ix_status_updatedAt … code 86
[other-name-compound-unique]    index uq_combo … is a unique index covering orderReference besides uq_order_reference … dropIndex("uq_combo")
[other-name-identical-spec]     index uq_order_reference already exists on box_other_name_identical_spec with different options: the server refused the creation with code 85. Drop it and restart: db.getCollection("box_other_name_identical_spec").dropIndex("uq_order_reference")
[boot]                          index uq_rogue on order_timeline is a unique index covering orderReference besides uq_order_reference … dropIndex("uq_rogue")
8 passed in 9.55s
```

**Defect B2 (the `other-name-identical-spec` row):** an index identical in key, uniqueness and partial filter but named `uq_other` makes the server refuse with code 85 (`IndexOptionsConflict`, "Index already exists with a different name: uq_other"); `read_model_indexes.py:73-80` reports `index uq_order_reference already exists … with different options` and prints `dropIndex("uq_order_reference")` — an index that does not exist on that collection. The boot fails (correct), but the message names the wrong index and its one-liner cannot work. `PR22` requires the message to name the index and give the `dropIndex` one-liner; on code 85 the culprit is the server-named index. See defects.

**The stored-specification comparison itself has no failing test (defect B1).** `verify_indexes`'s per-index branch (`read_model_indexes.py:96-111`: key, uniqueness, partial filter of `uq_order_reference` / `ix_status_updatedAt`) — the half of `PR52` that IS acceptance 3's "checked against the server's stored specification" — is reachable: an index created as `partialFilterExpression: {orderReference: {$type: 2}}` (the numeric alias #8's seed wrote, ledger L11) is accepted by the server's create as equivalent, and only `verify_indexes` catches it:

```
ensure raised nothing
[verify] index uq_order_reference on box_alias differs from the expected definition (partialFilterExpression SON([('orderReference', SON([('$type', 2)]))]) != {'orderReference': {'$type': 'string'}}). Drop it and restart: …dropIndex("uq_order_reference")
```

**Mutation `Q4-verify-differences-dead`** (`if differences:` → `if False and differences:`, sha `8bb83e0320e7c351 → 691d51936d5998ed`), run over `integration/test_read_model_indexes.py`, the whole projector `unit/` tree and `integration/test_projector_lifespan.py`:

```
mutated run exit 0
224 passed in 22.05s
```

It survives. The arms of task H1 (`H1-nonpartial`, `H1-hardcode-code-85`, `H1-delete-pr52`) attack creation and the *other-index* scan; none attacks the comparison. `requirements.md` §3 maps `PR52` only to `test_pr52_a_differently_named_unique_index_on_order_reference_fails_the_boot`, which exercises the second clause. Restored, `cmp` identical.

**Answer:** created at boot, yes; a sibling of every kind I tried fails the boot naming an index; but the comparison against the stored specification — the clause acceptance 3 is about — is never seen to fail (B1), and one sibling's message names the wrong index (B2).

### Q5 — the update signal (acceptance 4, R55 projector half, PR17 – PR19, PR42, PR45)

Mutations (mine), each run over `integration/test_update_signal.py`, `unit/test_update_signal_payloads.py`, `unit/test_project_fact_handler.py`; every one restored with `cmp` identical (`nats_update_signal_publisher.py` sha `75b2af1579751596`):

| Mutation | Family | First failure |
|---|---|---|
| `Q5-double-publish` — publish `order.updated` twice per fact | count | `test_r55_…`: `AssertionError: order.updated frames: 4` (plus `PR17`'s unpack and `PR42`) |
| `Q5-wire-order-reference` — `TimelineStreamEntry.order_reference = None` | corrupt a payload field on the wire | `unit/test_update_signal_payloads.py::test_pr37_every_field_reaches_both_signal_payloads_verbatim_sentinel_per_field`: `Right contains 1 more item: {'orderReference': 'ORD-424242'}` |
| `Q5-wire-summary` — `summary = entry.event_type` | corrupt a payload field on the wire | `test_pr17_…`: `assert b'Z\xc3\xbcrich' in …"summary":"order.placed.v1"…`; and the unit `test_pr37_…` |
| `Q3c` (above) — drop the `$ne` dedup filter, so a redelivery re-applies | suppression deleted | `test_r55_…` failed (the redelivery emitted) |

**Connected inside bootstrap, within a bound.** `composition.start_runtime` step 5 wraps `connect_nats` in `asyncio.timeout(nats_connect_seconds)` before the consumer task exists; `unit/test_composition.py::test_pr43_…` asserts the literal call log `[…, "migration", "nats.connect", "consumer.start"]` and, parametrised over `["indexes.ensure", "indexes.verify", "migration", "nats.connect"]`, that a failing step leaves `consumer.start` absent. **Mutation `Q5-no-connect-bound`** (`asyncio.timeout(nats_connect_seconds)` → `asyncio.timeout(None)`, `composition.py` sha `e57aaf886ddf96ae → 9ac288138c41c65e`): `test_pr45_an_unreachable_nats_fails_the_boot_within_the_bound` fails with `Failed: PR45: the boot did not fail within 20 s against a 2 s bound`; restored (`cmp` identical), green re-run `1 passed in 10.71s`.

**Answer:** one pair per applied fact, none for a redelivery, both deletion and wire corruption caught; NATS connects in `start_runtime` before the consumer, bounded, and an unreachable NATS fails the boot fast.

### Q6 — SA-2 note (acceptance 5, PR46, PR47)

The three operator branches of `saga.md:216-218` (`[]`, `[stock_released]`, `[stock_released, credit_released]`) are the ones that can carry a note (`asyncapi.yaml:2629`: `stock_rejected` / `credit_rejected` never do). Own server probe (`test_zz_review_probe_q6.py`, scratch, deleted): five notes `["$$ROOT", "$status", "$literal", "$$NOW x", "Cliente pidió anulación — ok"]` × three branches through the real writer: each `events[0].detail.note` equals the supplied text, steps intact, status `cancelled` — `1 passed in 3.88s`.

| Mutation (mine) | Result |
|---|---|
| `Q6-unwrap-entry` (`[literal(entry_document(…))]` → `[entry_document(…)]`, `delta_to_pipeline.py` sha `851603f7b00e8507 → fbeb2ff32cbf5b83`) | my probe fails: the note `"$$ROOT"` was stored as **the whole document** (`'note': {'_id': '9fb5f97c-…', 'cancellationReason': None, 'company': {…}, …}`) — a third shape of the latent #7/#8 defect, beside the implementer's `'placed'` substitution and `FailedToParse`. Restored, `cmp` identical |
| `Q6-note-only-without-steps` (`if payload.note is not None and not payload.compensation_steps:`, `summaries.py` sha `84a2089b8084511b → caa2213778896d55`) | 3 failed: `test_pr46_…[operator_cancelled-step_names1-$status refund]`, `[…step_names2- spaced ]`, and my probe. Restored, `cmp` identical. (`integration/test_timeline_projection.py::test_pr46_a_noted_operator_cancellation_stores_the_note_verbatim` uses the no-step branch, so it stays green; the per-branch claim is the unit case's, as `requirements.md` §3 maps it) |

**Answer:** yes on every branch, and `$`-prefixed text is stored verbatim.

### Q7 — the constants pin (acceptance 6, PR40)

Each mutation run over the whole projector `unit/` tree plus `services/seed/tests/unit/test_read_model_constants.py` (the seed's own pin, which must stay green: the mutation is the projector's ALONE). `tests/fixtures/read_model_constants.json` untouched (`git status` shows it unmodified).

| Mutation (mine) | Result |
|---|---|
| `Q7-version-3` `TIMELINE_ORDER_VERSION: Final = 2 → 3` (`read_model_document.py` sha `9de057e71dce8149 → 20d9849c7de17494`) | `1 failed, 219 passed`: `test_pr40_…` — `the projector's TIMELINE_ORDER_VERSION differs from the shared fixture's`; seed's pin green |
| `Q7-swap-ranks` `placed 1 ↔ stock_reserved 2` (`status_rank.py` sha `6d152af7714876b8 → 8150d5a71ddad270`) | `1 failed, 219 passed`: `test_pr40_…` — `the projector's status -> rank table differs from the shared fixture's` |
| `Q7-prefix-name` `ConsumerName.PROJECTOR = "projectors"` (`consumer_name.py` sha `fb8bc9ad58115380 → c939de6f048f12f8`) | `6 failed`: `test_pr40_…` (`the projector's dedup-key prefix differs from the shared fixture's`), the byte-copy test, the group-default tests, the writer's argument test |
| `Q7-prefix-separator` the variant's key `f"{consumer.value}:{event_id}"` → `"/"` (`idempotent_consumer.py` sha `fc9f5b38c78db010 → 08fc4f6ad6442bcb`), plus `integration/test_seeded_oracle_parity.py` and the conformance file | `12 failed, 223 passed` — **but not `test_pr40_…`**: caught by `unit/test_mongo_read_model_writer.py::test_pr6_pr42_…`, `test_pr44_…[0]`–`[5]` (against the seed's stored keys, the seed being pinned to the fixture), the exclusion-set case and four conformance cases |

All restored, `cmp` identical. **Answer:** version, rank table and the consumer-name half of the prefix each fail the named fixture-reading test. The separator half of the prefix is recomposed inside `test_pr40_…` (`ConsumerName.PROJECTOR.value + ":"`) rather than read from the key the variant builds, so `PR40` alone would not catch a separator drift; twelve other tests do, including `PR44` against the fixture-pinned seed. Non-blocking (N2 below).

### Q8 — the registration guard (acceptance 8, PR27, PR49)

`tests/architecture/test_registration_behaviour.py` gains `"projector"` in `SERVICES`, `TABLES["projector"] = {commands: [ProjectFactCommand], queries: [], events: []}`, and a census (`test_the_services_list_is_exactly_the_composition_roots_that_define_a_dispatcher`) with its sentinel. The implementer's arm `K3-pipeline` (record §10) planted a **scratch second command** self-registering through `__init_subclass__` and drained by a loop in the root: it failed with `WIRE: 2 registrations share one statement (composition.py:89)`. That proves the instrument at n = 2. The projector's real population is **n = 1**.

**My arm `Q8` — F-g + F-j at the projector's real n = 1, against its real composition root.** `ProjectFactHandler` self-registers via `__init_subclass__(…, message=ProjectFactCommand)` into a module-level `HANDLERS` dict; `register_handlers` drains it through a helper `def _one(registry, message, handler): registry.register_command(message, handler)` (exactly the guard's own `F_G_AND_F_J` fixture shape). `handlers.py` sha `64b21d037ae5f54b → 97d79cb828612346`, `composition.py` `e57aaf886ddf96ae → 66d8df3f96a8e40a`:

```
FAILED services/projector/tests/unit/test_no_process_state.py::test_pr51_no_module_level_mutable_state_and_no_writer_state_beyond_the_collection
  module-level mutable containers outside the declared set: [('application/handlers.py', 'HANDLERS')]
1 failed, 54 passed in 6.28s     (test_registration_behaviour.py[projector] PASSED)
```

Only K7's module-level-container scan caught it, incidentally. **Arm `Q8b`** — the same pipeline with the registry held as a class attribute (`_SelfRegistering.handlers`, re-bound in `__init_subclass__`, no module-level container), `handlers.py` → `fb041861ce9ada6d`, `composition.py` → `d3e1eb1fbdd964a8`, run over **all of `tests/architecture` and the projector's `unit/` tree**:

```
780 passed in 39.86s
```

Both restored, `cmp` identical (`64b21d037ae5f54b`, `e57aaf886ddf96ae`), caches cleared. **Defect B3:** for a service with exactly one registration the guard's "each registration comes from a distinct statement" clause is vacuous, and the `register_*` call inside a helper is accepted as a "direct `.register_*(...)` statement" (`registration_statements` matches any `Expr` call named `register_*` in the file, so the helper's line qualifies — the F-g weakness `progress/review_cqrs_dispatcher.md:164` recorded: "the first-argument check accepts any `Name`, including a parameter"). Acceptance 8 asks for the guard "armed with F-g + F-j … against this service's composition root"; at this service's population it does not bite (defeat row 12: the arm used a population the service never has).

PR27's zero/two cases: `unit/test_composition.py::test_pr27_zero_handlers_fail_the_boot` / `…two…` — green, with the call log `[]`; the source arms are carried by `test_pr27_the_real_registration_builds_a_dispatcher_with_exactly_one_handler` (record §4.1 H5). Not re-armed by me (the record's H5 arms are verbatim in §10).

### Q9 — the three accepted survivors (record §4.2 findings 1 – 3)

| # | Claim | My check | Verdict on the disposition |
|---|---|---|---|
| 1 | Phase-1 `DuplicateKeyError` retry unreachable on `mongo:8.3.8` | Not re-measured (the probe `.arm/p24/stress_upsert.py`, 4,800 racing upserts, 0 errors, is consistent with the server's documented retry of an `_id`-equality upsert since 4.2). The retry's own logic is guarded at unit level by E2 (`test_mongo_read_model_writer.py`, arms `E2-retry-twice`, `E2-retry-phase-2` verbatim in §10) | **Unreachable, not a missing test.** Re-open trigger present (a server pin below 4.2, or an upsert with a non-`_id` filter). Accepted |
| 2 | `$min` cap never binds | Argument checked against `infrastructure/persistence/timeline_order.py`: the `$reduce` runs `$size: $$all` rounds, each depth is `prev(cause) + 1` from `0`, so after round k every depth ≤ k ≤ `|all|` = the cap. A cycle's members climb in lockstep and tie on depth, then fall back to `eventId`; termination comes from the bounded `$reduce`. Same for `domain/timeline_order.py`'s `min(count, …)` | **Equivalent mutant.** Re-open trigger present (the `$reduce` bound replaced). Accepted |
| 3 | `$sortArray` on `processedEventKeys` redundant on this server | **Mutation `Q9-drop-key-sort`** (remove the `$sortArray` wrapper, `delta_to_pipeline.py` sha `851603f7b00e8507 → a85df371cde6aeac`) over the projector `unit/` tree: fails — `KeyError: '$sortArray'` (×2, `test_delta_to_pipeline.py`) and `AssertionError: only the dedup keys are sorted … assert 0 == 1` (`test_timeline_order_expression.py`). Restored, `cmp` identical | **Guarded structurally after all**; the record's "survivor" is true only of the integration arm J6. Accepted; the record could say so |

**But the retired claims survive in the source and the design (non-blocking N3).** Enumerated on the retired wording (`grep -rn -i 'cycle terminate\|so a cycle\|cap makes\|capped at\|lose with\|one insert lose'` over `services/projector/src`, `services/projector/tests`, `specs/projector_read_model`): `infrastructure/persistence/timeline_order.py:10-11` ("capped at `|entries|` so a cycle terminates"), `domain/timeline_order.py:12-13` ("capped at `|entries|` (a cycle terminates deterministically)"), `infrastructure/persistence/mongo_read_model_writer.py:6` ("makes one insert lose with `DuplicateKeyError`"), `design.md:210` (same), `design.md:279` ("The `$min` cap makes a cycle terminate deterministically"). The record retires findings 1 and 2 but leaves each premise stated as fact in three source docstrings (defeat row 9). The other hits (`kafka_fact_subscriber.py:89` backoff cap, `requirements.md:50, 60`) are unrelated or correct.

### Q10 — `ORD-000007` (record §4.2 finding 4)

Developer stack: `docker compose -p otcpy -f docker-compose.infra.yml start kafka postgres` (only those two; `docker ps` before = `otcpy-n8n` only), then `stop kafka postgres` (after = `otcpy-n8n` only). Commands and output:

```
$ docker exec otcpy-kafka kafka-console-consumer.sh --topic <each fact topic> --from-beginning … | grep 223c1406-1fd8-45c8-99c5-88a738720414
otc.orders.facts.v1      Partition:2 Offset:0 2026-10-07T09:48:55.110Z order.placed.v1     fdc241b6 cause 1e85ee84
otc.orders.facts.v1      Partition:2 Offset:1 2026-10-09T04:51:45.558Z order.confirmed.v1  cf82f292 cause 387d2f9b
otc.fulfillment.facts.v1 Partition:2 Offset:0 2026-10-08T04:45:26.424Z stock.reserved.v1   614766a7 cause bccaadb5
otc.fulfillment.facts.v1 Partition:2 Offset:1 2026-10-08T08:31:10.482Z order.despatched.v1 d765ec54 cause 3d370996 DES-000006
otc.billing.facts.v1     Partition:2 Offset:0 2026-10-09T04:51:45.558Z credit.approved.v1  387d2f9b cause 37a3ed86

$ psql otc_orders: select order_reference,status from orders where order_reference='ORD-000007'  ->  ORD-000007 | confirmed
$ psql otc_orders: processed_events where event_id like 'd765ec54%'  ->  d765ec54-… | orders.saga | 2026-10-08 08:31:10.566+00
$ psql otc_fulfillment: despatches where order_reference='ORD-000007'  ->  DES-000006 | 2026-10-08 08:31:10.503+00
```

**What is true of the topic:** five facts; an `order.despatched.v1` (`DES-000006`) sits at `08:31` on 2026-10-08, a day **before** `credit.approved.v1` → `order.confirmed.v1` (one tie group at `04:51:45.558`, `order.confirmed`'s cause = `credit.approved`'s `eventId`). Its cause `3d370996` is not a saga command: it is the request id of feature 17's Phase 9 live check, a raw `fulfillment.despatch.create` sent by hand (`progress/impl_fulfillment_despatch.md:156-170`). Orders consumed it and ignored it at `stock_reserved` (the `processed_events` row above), and its later `despatch.create` was answered `created: false` with no fact (`progress/history.md:935`), so Orders stalls at `confirmed`.

**Is the projection correct per R52?** Yes: the set of facts proves rank 5 was reached; R52 forbids regressing it; `despatched` with `despatchReference: DES-000006` is the projection of what is on the topic. The write model and the topic disagree because a probe injected a fact outside the saga, not because of any product path.

**Owner and classification:** feature 17's live-data side effect, already registered (`progress/history.md:935`: "`ORD-000007` will stall at `confirmed` … Avoid it or recreate `otc_fulfillment` from the seed") and noted by the leader in `progress/current.md:22`. Not a feature-24 defect, no `specs/shared/` root cause. Disposition: **accept**, live-data note only; re-open if a write-model / read-model status disagreement appears for an order no manual probe touched.

### Q11 — test isolation on the session-wide Kafka (record §4.2 finding 5)

Population — every test module that starts a fact consumer or produces to a fact topic (`grep -rln 'KafkaFactSubscriber\|start_runtime\|AIOKafkaConsumer' services/*/tests tests`, then `send_and_wait\|.send(` × `facts.v1\|FACT_TOPICS\|topic_of`):

| Suite | Consumer start | Exposure today |
|---|---|---|
| Orders saga (`services/orders/tests/integration/saga/conftest.py:778-790`) | default `history="skip"`: deletes the `orders.saga` group and commits it at the END of every partition before the lifespan; `"keep"` resumes its own offsets | **one test** reads history: `test_saga_consumption.py:65-77` (`test_so1_first_boot_…`) deletes the group and boots with `"keep"`, i.e. from `earliest`. Every earlier test's facts reach a fresh database and are recorded `unknown_order` (the harness docstring, `:8-11`) — designed, benign. All other suites publish only well-formed facts (`services/notifications/tests/integration/*.py`, 13 `publisher.publish(` sites, each `facts.wire(…)`/`facts.wire_from(…)`), so no poison reaches it. (Its docstring still names a `history="replay"` mode no test uses — Orders' file, not this feature's.) |
| Notifications (`services/notifications/tests/integration/conftest.py:281`) | a UNIQUE group per host and `auto_offset_reset="latest"` (`kafka_fact_subscriber.py:126`) | none: it never reads history |
| Fulfillment, Billing | no fact consumer (relay producers only) | none |
| Projector | private topics per test (`Topics`, `integration/conftest.py`), armed `J-isolation-real-topics` | closed |

**Answer:** not a defect today: the projector was the first suite that started a group from `earliest` with a uniqueness constraint (`uq_order_reference`) able to turn another suite's fact into a poison record, and it is isolated. The exposure returns with feature 27 (retry / DLQ wrappers around consumers that start from `earliest`, and its DLQ tests). The record's §11 discharges this, and the re-run of `I4-commit-before-handler` after the wrapper (#8 id 94, design hand-over §7), with the sentence "Feature 27 must …" — **routed instead (R-1 below):** two acceptance items for the leader to append to feature 27.

### Q12 — the ported-idiom ledger, spot-checked by mutation (design §10, record §3)

Ten rows, each attacked at the code the row is about, each run against the row's named guard (restored with `cp`, `cmp` identical, caches cleared, after every one):

| Row | Python question | Mutation (mine) | Named guard executed the code? | Result |
|---|---|---|---|---|
| L29 / L49 | loop affinity | `@functools.cache` on `composition._mongo_client` (one client shared across `asyncio.run`s) | `test_the_runtime_starts_and_stops_in_two_successive_event_loops` | fails: `RuntimeError: Cannot use AsyncMongoClient in different event loop` |
| L43 | cancellation | the subscriber's handler guard `except Exception:` → `except BaseException:` (swallows the cancel) | `test_pr50_shutdown_cancels_a_stuck_handler_after_the_grace` | fails: `the stuck consumer task was not cancelled after the grace` |
| L36 | commit after the handler | `consumer.commit({tp: offset + 1})` before `await handler(...)` | `test_pr38_a_raising_handler_leaves_the_committed_offset_unchanged_read_from_the_broker` | fails: `an offset was committed although the handler raised` (read from the broker) |
| L45 | bounded connect | (Q5) `asyncio.timeout(None)` | `test_pr45_…` | fails: `the boot did not fail within 20 s against a 2 s bound` |
| L46 | headers not shared | one `shared` dict for both publishes | `test_pr17_two_publishes_carry_distinct_headers_each_with_the_order_id` | fails |
| L21 | identifier encoding | `order_id=event.correlation_id` (native `UUID`) | `test_pr41_ids_are_lowercase_hyphenated_…` | fails (plus `test_pr37_…`, `test_pr19_…`) |
| L23 | integer width | `totals.initialDiscount` as `bson.Int64` always | `test_pr41_a_total_past_2_to_the_31_is_int64_and_a_small_one_is_int32`, `test_pr44_…` | fails: 8 cases |
| L14 | `$`-text evaluated | (Q6) unwrap the entry | `test_pr47_…` and my probe | fails (`$$ROOT` stored as the whole document) |
| **L22** | **timestamp format** | `occurred_at = delta.entry.occurred_at.isoformat()` in `delta_to_pipeline` (the `updatedAt` `$max` operands) | named guards: "`PR41` regex case; `PR14`" | **both stay green**: the unit `test_pr41_ids_…` checks the entry's `occurredAt` and the placeholder's `updatedAt`, never the pipeline's `updatedAt` operands; `test_pr14_updated_at_…` passes because `"…Z"` sorts above `"…000+00:00"`. Caught only by `test_pr44_…` ×7 and `test_pr15_shuffled_…` over the whole suite (`8 failed, 285 passed`) — rows L65 / L6's guards. Non-blocking N4 |
| L30 | `Any` leakage | read, not mutated: `grep -rn '\bAny\b'` over `application`, `domain`, `presentation` → only `presentation/projector_facts_consumer.py:30, 58` (`Envelope[dict[str, Any]]`, validation only, the result discarded) | `test_no_any_in_ports.py` ranges over `domain/` and `application/ports/` | holds for its population; the row's "documents are `Mapping[str, Any]` inside `infrastructure` only" is true of documents; the presentation hit is the wire envelope. Cosmetic |

**Answer:** nine of ten rows' named guards execute and bite on the row's own code; L22's named guards do not bite on the `updatedAt` instant (another row's guard does).

### Q13 — avoided / recurred

**#8's backlog (design §13, 27 hits; the ids that apply to this feature):**

| #8 id | Subject | This feature | Evidence (mine where marked) |
|---|---|---|---|
| 52 | ledger written at port time | **avoided** (65 rows, both halves cited) — with one row whose named guard does not bite (L22, N4) | Q12 |
| 57 | completion pair without a causal edge | **avoided / consumed** | `test_r24_…` failed under my `Q1-no-depth` |
| 58 | hand-written envelope copy unguarded | **avoided** | Q5 wire corruptions caught by `test_pr37_…` (mine) |
| 60 | envelope fixture collisions | **avoided** for the four ids (`unit/test_fact_builders.py`) — **but the sibling class recurred** in R50's own fixture (eventId order = occurredAt order, B4) | R50 arm (mine) |
| 65 | totals / party-code transposition | **avoided** | record arms C5-* (verbatim §10); sweep 232/233 (artefact recounted: `results.jsonl` `CAUGHT 232, SURVIVED 1`) |
| 66, 71 | note reaches the timeline, every branch | **avoided** (projector half) | Q6 (mine) |
| 68 | composition wiring unguarded | **avoided** | `test_each_setting_reaches_the_adapter_it_configures` (record H3 arms) |
| 85 | fixtures self-assign host ports | **avoided** | `grep -rn 'socket\|free_port\|bind('` over the projector tests: no hit; PR45 uses a Docker-held port |
| 100 | timeline money as minor units | **avoided** | `format_money`, C2-money-str |
| 105 | causal check vacuous without `causationId` | **avoided** (projector half) | `test_pr33_…` (L2-causation-PR33); Q1 |
| 94 | an offset arm stops killing once a retry wrapper exists | **carried** — but as a sentence, not an item (R-1) | record §11 |
| 78 | doc-comment `cref`s | n/a (sentinel B of the sweep is the Python analogue) | — |
| 8, 12, 24, 27, 29, 30, 31, 41, 69, 74, 75, 102, 103, 104 | owned elsewhere | not this feature's | design §13 |

**#7's and #8's review classes (gate record §6 note 5):**

| Class | This feature |
|---|---|
| engine claim probed one way (#8 D1/D4) | **avoided** — `test_pr39_…` runs both creation orders |
| tests that cannot fail (#8 D2) | **recurred** — B1 (PR52's comparison: deleting it leaves 224 tests green), B3 (registration guard at n = 1: 780 green), B4 (R50's ordering at eventId), N4 (L22's named guards) |
| a retired claim surviving elsewhere (#8 D5) | **recurred** — N3 (five sites still state the retired `$min`-cap and `DuplicateKeyError` premises) |
| a message naming a literal code (#8 A2/A8) | **avoided** for the code (`H1-hardcode-code-85` arm) — a sibling defect B2 (the message names the expected index, not the server-named one, on code 85) |
| a name promising an unexercised half (#8 A3, #7 N6) | **avoided** for J2 / G4; **recurred** in traceability: `requirements.md` §3 maps `PR52` to one case that exercises its second clause only (B1) |
| a box ticked over an undelivered clause (#8 A4, #7 N1) | **recurred** — J1's box ticked over the binding fixture rule its R50 case breaks (B4); acceptance 8 "armed against this service's composition root" ticked on an n = 2 arm (B3) |
| an exclusion list as control flow (#8 A5) | **avoided** — `test_pr44_over_the_six_sagas_the_comparison_skipped_exactly_the_declared_paths` |
| a replay that skips Kafka (#8 A6) | **avoided** — Q2 |
| transcribed sweep output (#8 A12) | **avoided** — recounted from `.arm/p24/sweep/results.jsonl` (233 / 232 / 1) and `results_run1.jsonl` (233 / 227 / 6) |
| the seam never walked in one run (#7 N4) | **avoided** — record N3 (one order end to end, 18 frames) |

### Traceability probe — the shared rows' own evidence, armed

| Row | Named test (matrix column 5) | My mutation | Result |
|---|---|---|---|
| R50 | `test_timeline_projection.py::test_r50_…ordered_by_occurred_at_rather_than_by_arrival` | **`R50-arrival-order`**: `sortBy` without `occurredAt` (`{__depth, eventId}`), `timeline_order.py` sha `9e266433d4437cff → 71c350b617e5f742` | **`1 passed in 3.78s` — survives** (B4). Over the whole projector suite the same mutation fails 10 other cases (`test_pr10_…` differential, `test_pr31_…`, `test_pr44_…` ×7, the unit stage test), so the behaviour is guarded; the row's own evidence is not |
| R51 | `test_r51_…` | `Q3c` drop `$ne` | fails |
| R52 | `test_r52_…` | **`R52-no-status-guard`**: `$cond` test `$gt [rank, current]` → `$gte [rank, 0]` | fails: `a late order.placed regressed the status` |
| R53 | `test_r53_…` | **`R53-no-upsert`**: Phase 1 `upsert=False` (`mongo_read_model_writer.py` sha `1be883059cbd596d → 281b87c1fbda0a11`) | fails: `no document for 0a0b0c0d-aaaa-…` |
| R54 (projector half) | `test_r54_…`, `test_pr20_…` | not re-armed (record arms K1-*, verbatim) | — |
| R55 (projector half) | `test_r55_…` | `Q5-double-publish`, `Q3c` | fails |

All restored with `cmp` identical. **Why R50 survives:** its fixture (`test_timeline_projection.py:28-47`) gives the five facts `eventId`s `0xA0001 … 0xA0005` in the same order as their `occurredAt` (and their causal chain), so an implementation that sorts by `eventId` produces the expected order. The module docstring (`:3-4`) says "arrival order, `occurredAt` order and causal order all differ from each other" — false (the in-test comment at `:55` says "the causal order (the same)"), and `tasks.md`'s binding fixture rule ("`eventId`s chosen so the `eventId` fallback alone would invert the expected order", header and design §11.1 rule 3) is broken by the very case the shared matrix cites for R50.

---

## Defects

### Blocking

| Id | File, line | Defect | Why it matters | Proof |
|---|---|---|---|---|
| **B1** | `services/projector/src/otc_projector/infrastructure/persistence/read_model_indexes.py:96-111`; `specs/projector_read_model/requirements.md:202` (§3 row PR22/PR39/PR52) | The stored-specification comparison (key, uniqueness, partial filter of the two expected indexes) has **no test that fails when it is deleted**. Reachable: a `{$type: 2}` alias index is accepted by the create and caught only here. | It is acceptance 3's own clause ("checked against the server's stored specification") and `PR52`'s first half; §3 marks PR52 DONE on a case that exercises only the second half. A guard not seen to fail is not done (`CLAUDE.md`, arming protocol) | `Q4-verify-differences-dead`: `224 passed`; the alias probe output in Q4 |
| **B3** | `tests/architecture/test_registration_behaviour.py` (`registration_statements`, `violations`) for `projector` | At the projector's real population (one registration) the F-g + F-j pipeline passes: the "distinct statement" clause is vacuous at n = 1 and a `register_*` inside a helper counts as a direct statement. The arm `K3-pipeline` added a second scratch command (n = 2). | Acceptance 8 asks for the behavioural guard armed with F-g + F-j against **this** service's root; at this service's n it does not bite (defeat row 12). The next n = 1 service (the Gateway may be one) inherits the blind spot | `Q8b`: `780 passed` over `tests/architecture` + projector `unit/` |
| **B4** | `services/projector/tests/integration/test_timeline_projection.py:3-4, 28-47` | R50's matrix evidence cannot tell `occurredAt` order from `eventId` order; the docstring states the opposite of the fixture | The shared matrix closes R50 on this case; `tasks.md`'s binding fixture rule is broken by it; J1's box is ticked over it (#7 N1 / #8 A4 class) | `R50-arrival-order`: `1 passed` |

### Non-blocking (each with a disposition)

| Id | File, line | Finding | Disposition |
|---|---|---|---|
| **B2** | `read_model_indexes.py:73-80` | On code 85 ("Index already exists with a different name: uq_other") the message names `uq_order_reference` and prints `dropIndex("uq_order_reference")`, an index that does not exist there | **fix** in this round (same file as B1): name the index the server named (its `errmsg` / `details`), and add a case for it — the `other-name-identical-spec` row of Q4 |
| N1 | `services/orders/tests/unit/test_idempotent_consumer_parity.py` (`variant_problems`) | the conformance file must exist, not contain the cases; an empty file passes | **accept** — `PR48`'s text and #7's rule verbatim (`idempotent-consumer.parity.spec.ts:519-529`); behaviour is guarded by the file's own cases (Q3c: 11 fail). Re-open if any variant's conformance file is edited or a second variant appears |
| N2 | `services/projector/tests/unit/test_read_model_constants.py:39` | the prefix assertion recomposes `ConsumerName.PROJECTOR.value + ":"`; a separator drift in `idempotent_consumer.py` escapes `PR40` | **accept** — 12 other cases catch it, `PR44` against the fixture-pinned seed among them (Q7). Re-open if the key construction moves out of `run_once` |
| N3 | `infrastructure/persistence/timeline_order.py:10-11`, `domain/timeline_order.py:12-13`, `infrastructure/persistence/mongo_read_model_writer.py:6`, `specs/projector_read_model/design.md:210, 279` | the retired premises (the `$min` cap "makes a cycle terminate"; "one insert loses with `DuplicateKeyError`") still stated as fact | **fix** (text): the three docstrings by the implementer; `design.md` lines by the leader (the record §4.2 already asks for 210) |
| N4 | design §10 row L22; `unit/test_document_rendering.py` | L22's named guards (`PR41` regex case, `PR14`) do not bite on the pipeline's `updatedAt` instants (`isoformat()` there survives both) | **fix**: extend `test_pr41_ids_…` to the `updatedAt` `$max` operands (a two-line assertion), or name `PR44`/`PR15` as L22's guard in the record's §3 |
| N5 | `services/projector/tests/integration/test_projector_lifespan.py:162` | comment "the topics are session-wide" is stale (private topics now) | **fix** (comment) |
| N6 | `specs/shared/openapi.yaml:1484-1491` | the pairwise fallback wording is non-transitive when a tie group mixes a chain and an unrelated entry; `PR10`'s depth rule (#7 A1, #8) resolves it | **accept** — no live tie group has that shape (design §5.4). Re-open (as an `SA-n` proposal) if feature 41 or any producer creates one |
| N7 | update-signal transport | NATS core publish is neither Kafka-fact nor NATS-RPC in `saga.md:29-34`'s matrix | **accept** — #7 gate row 2, #8 gate row 3, #9 design §7.1 approved at this spec's gate; inherited, identical in all three (user rule: inherited decisions are not gate questions). C3 box marked with this exception |

### Routed (the leader files; I do not write `feature_list.json` beyond id 24's status)

- **R-1 → feature 27 `observability_reliability`, two acceptance items** (not a `specs/shared/` gap; the record's §11 says only "Feature 27 must …"): (a) *"every test that starts a fact consumer from `earliest` (the projector's retry/DLQ tests included) runs on private topics or commits its group to the end first, so a fact another suite left on the session-wide topics cannot poison it (feature 24 review Q11; `services/projector/tests/integration/conftest.py` `Topics`)"*; (b) *"after the retry / DLQ wrapper lands around `ProjectorFactsConsumerTask`, re-run the projector's `I4-commit-before-handler` and `PR38` arms (#8 id 94; `specs/projector_read_model` hand-over §7)"* — the projector's twin of 27's existing feature-16 SO9 item.
- **No `SA-n` is owed by this feature.** SA-6's text (`openapi.yaml:1500-1505`, byte-identical in all three: `cmp` in C7 below) agrees with what the projector does: `causationId` stored verbatim (`PR30`), a responder fact's command id never naming an entry.

---

## `CHECKPOINTS.md`

**C1** — [x] the five harness files exist; [x] `progress/current.md`, `history.md` exist; [x] `.claude/agents/` holds the seven; [x] each declares a model (`implementer`/`premise_checker` sonnet, `suite_runner`/`test_maintainer` haiku, `leader`/`reviewer`/`spec_author` "inherits the session model"); [x] `./init.sh` exit 0 (`.arm/p24-review/init.log`).

**C2** — [x] no feature `in_progress` before this verdict (statuses: 38 done, 18 pending, 1 in_review); [x] every status valid; [x] `done` features untouched by this review; [x] `progress/current.md` is the leader's phase-12 file (not this feature's to edit); [x] no `blocked` feature.

**C3** — [x] `lint-imports`: `Contracts: 11 kept, 0 broken` (run by me); [x] no cross-service DB access or import (independence contract kept; the projector has no SQL dependency, `test_projector_dependencies.py`); [x] no shared runtime code beyond the three packages; [x] no `domain` imports `otc_cqrs` (contract kept); [x] `shared_kernel`/`cqrs` untouched (`git diff --stat packages` shows only SA-6's two generated header lines); [x] no `float`/`Decimal`/`/` in the projector's domain (`grep` over `domain/`: no hit); [x] every interaction classified — Kafka facts in, NATS core publish out, with the N7 exception approved at the gate; [x] no debug leftovers (`grep 'print(\|breakpoint\|TODO\|FIXME'` over `services/projector/src`: no hit).

**C4** — [x] `./quality.sh` — **not re-run in full by me** (the claim is the implementer's two runs: `.arm/p24/quality{1,2}.log` end `quality.sh: all gates passed`, `4075 passed`, `Contracts: 11 kept`). I ran instead, on the restored tree with the developer stack down: `ruff format --check` exit 0, `ruff check` "All checks passed!", `mypy` "Success: no issues found in 723 source files", `lint-imports` 11/0, and `pytest services/projector tests/architecture services/orders/tests/unit/test_idempotent_consumer_parity.py services/seed/tests/unit/test_read_model_constants.py` → `879 passed in 87.92s`; [x] domain tests pure (`test_timeline_order_reference.py` imports only the domain); [x] integration tests on testcontainers (root conftest, `mongo:8.3.8`, `apache/kafka:4.3.1`, `nats:2.14.5-alpine`), green with the developer stack down; [x] coverage 97.22 % overall / 98 % domain (the logs); [x] no Jest/Karma/Jasmine.

**C5** — [x] no suspicious untracked files (`.arm/` is git-ignored; my scratch probes were removed from `services/projector/tests/integration/`, copies kept in `.arm/p24-review/`); [ ] `progress/history.md` entry with effort record — **not applicable on a rejection**; [x] `feature_list.json` id 24 set back to `in_progress` (one line); [x] how to test manually: record §11; [x] nothing committed by me. (Note for the leader's wrap-up: `specs/projector_read_model/` is still untracked; its spec commit must precede the implementation commit, C6.)

**C6** — [x] `specs/projector_read_model/{requirements,design,tasks}.md` exist; [x] EARS with ids; [ ] every task genuinely done — **J1 is ticked over a fixture that breaks the task header's binding rule (B4), H1's box over an unarmed comparison (B1), K3 / acceptance 8 over an n = 2 arm (B3)**; [ ] every `R<n>` covered by a concrete named test that exercises it — R50's named case does not distinguish its own claim from `eventId` order (B4); [—] spec commit before implementation commit: pending wrap-up (both uncommitted).

**C7** — [x] `specs/shared/` byte-identical to #7 and #8 except `test-matrix.md` (`cmp`: `asyncapi.yaml`, `domain-model.md`, `n8n-workflows.md`, `openapi.yaml`, `requirements.md`, `saga.md` same in both; `test-matrix.md` differs, expected); [x] `test-matrix.md`'s diff is column 5 of R50 – R55 plus the derived counts only (parsed: R50 – R55 change column 5 alone; summary `6 | 4 | 0 | 2`, total `46 | 1 | 16`, consistent: 42 + 4, 20 − 4); [x] SA-6 applied in all three (`openapi.yaml` `cmp` same) — the leader's, outside this feature; [x] reused `R<n>` ids are claims about behaviour — R50 – R53's behaviour confirmed by my probes (Q1, Q2) even though R50's cited case is weak (B4); [—] n8n / API script: not this feature's; [x] inherited #8 findings accounted for (Q13); [—] effort record: on approval only; [—] README benchmark: wrap-up.

---

## `R<n>` → test mapping verified

| Requirement | Test | Verified how |
|---|---|---|
| R50 | `test_timeline_projection.py::test_r50_…` | exists, green; **survives the eventId-order mutation (B4)**; the behaviour itself is proven by my Q1 fixture and by `test_pr10_…` / `test_pr44_…` |
| R51 | `test_timeline_projection.py::test_r51_…` | fails under `Q3c` (mine) |
| R52 | `test_out_of_order_facts.py::test_r52_…` | fails under `R52-no-status-guard` (mine); behaviour confirmed by my 36-pair probe |
| R53 | `test_placeholder_document.py::test_r53_…` | fails under `R53-no-upsert` (mine) |
| R54 projector half | `unit/test_read_model_sole_writer.py::test_r54_…`, `test_pr20_…`, `unit/test_projector_consumes_only.py::test_pr21_…` | green; record arms K1-* (not re-armed) |
| R55 projector half | `integration/test_update_signal.py::test_r55_…` (+ `test_pr17_…`, `test_pr33_…`, `test_pr42_…`, unit `test_pr37_…`, `test_pr18_…`, `test_pr19_…`) | fails under `Q5-double-publish`, `Q3c`; wire corruption caught (mine) |
| PR1 – PR52 | `requirements.md` §3 | every named function exists (enumerated: each `def test_…` found once; the three non-matches are a Billing precedent, a file name and the `test_pr16_*` pattern); PR52 half-covered (B1) |

---

## What must change before re-review

1. **B1** — add a case that drives `verify_indexes`'s per-index comparison to fail on a real server (the `{$type: 2}` alias index of Q4b is a ready, reachable fixture; a differing stored key or uniqueness through a fake collection is acceptable as a second case), asserting the message names the index; arm it with `if differences:` → `if False and differences:` and record the failure; update `requirements.md` §3's PR52 row to name it.
2. **B3** — make the registration guard bite at n = 1: e.g. require each recorded registration's statement to be the direct call inside the root's registration function with message/handler arguments that are not that function's parameters or loop variables, or an equivalent rule the implementer prefers; arm it against the projector's real root with this review's `Q8b` shape (class-attribute self-registration drained by a helper, one handler, no module-level container), and keep `K3-pipeline`.
3. **B4** — give `test_r50_…` `eventId`s that invert the `occurredAt` order (and fix its docstring); arm it with `R50-arrival-order` (`sortBy` without `occurredAt`) and record the failure.
4. **B2, N3, N4, N5** in the same round (small, same files).
5. Re-run the affected arms and the projector suite; no full `quality.sh` re-run is owed by this review unless a shared guard changes (B3 does: run `tests/architecture` in full).

---

**Verdict: REJECTED** — 3 blocking findings (B1, B3, B4); 1 non-blocking fix bundled (B2) and N1 – N7 with dispositions; routed R-1 (two acceptance items for feature 27). `feature_list.json` id 24 → `in_progress`.

---

# Round 2 — re-review after rejection 1

> Written incrementally. Reviewer: `reviewer` (Opus). Inputs: `progress/brief_review_projector_read_model_round2.md`, the "Round 2" section of `progress/impl_projector_read_model.md` (lines 6398 – 6454), `progress/brief_impl_projector_read_model_round2.md`, round 1 above, `CLAUDE.md` (read on disk). Backups: `.arm/p24-review2/` (git-ignored: `git check-ignore -v` → `.gitignore:87:/.arm/`). Developer stack down throughout (`docker ps` → `otcpy-n8n` only).

## Probe log (round 2)

### P0 — the recorded `quality.sh` run

`.arm/p24-r2/quality.done` = `exit 0 dur 482s`; `.arm/p24-r2/quality.log`: line 44 `Contracts: 11 kept, 0 broken.`, line 598 `Required test coverage of 60.0% reached. Total coverage: 97.26%`, line 599 `4082 passed in 450.12s (0:07:30)`, line 666 `quality.sh: all gates passed`. `find services packages tests specs apps/web/src -newer .arm/p24-r2/quality.log -type f` (excluding `__pycache__`, `node_modules`) → no output: no source changed after the recorded run. Claim confirmed from the artefact; not re-run in full by me (see P5 for what I ran).

### P1 — B1, the stored-specification comparison (`read_model_indexes.py:98-121`)

My own mutations, not the implementer's `if False and` (script `.arm/p24-review2/arm.sh`: `cp` backup + sha256, mutation, `setsid` run with a 300 s watchdog that kills the process group, restore, `cmp`, `__pycache__`/`.mypy_cache` cleared), each over `integration/test_read_model_indexes.py` + the projector `unit/` tree + `integration/test_projector_lifespan.py` (the population that let round 1's survivor live: 224 passed then). File sha before/after restore `854a7bd11699acaf`.

| Mutation (mine) | Family | Result |
|---|---|---|
| `B1r-partial-presence`: the partial-filter comparison weakened to "both present or both absent" (`(found… is None) != (expected… is None)`) | delete the behaviour (plausible weakening) | **`1 failed, 226 passed`**: `test_pr52_the_stored_partial_filter_is_compared_with_the_expected_definition` — `Failed: DID NOT RAISE ReadModelIndexError` (real `mongo:8.3.8`, the `{$type: 2}` alias index) |
| `B1r-unique-default`: `found.get("unique", False)` → `found.get("unique", True)` in the comparison | corrupt a field | fails broadly (every boot: `index ix_status_updatedAt … (unique False != False)`), including `test_pr52_a_stored_non_unique_…` and `test_pr52_a_differently_named_…` |
| `B1r-message-unnamed`: the differences branch still raises but drops the index name and the one-liner | corrupt the message | **`2 failed`**: both new PR52 cases — `AssertionError: the index is not named` / `assert 'uq_order_reference' in 'an index on fake_box differs …'` |
| `B1r-key-dead`: the key comparison `if tuple(found["key"].items()) != expected.key:` → `if False:` | delete the behaviour | **`227 passed` — survives** (see below) |

All four restored, `cmp` identical. **The key branch is unreachable on a real server after `ensure_indexes`**, measured (scratch `test_zz_review2_probe_key.py`, copy in `.arm/p24-review2/`, removed from the tree): an index of the expected name with key `{orderReference: -1}`, `{status: 1, updatedAt: 1}` or `{updatedAt: -1, status: 1}` is refused by the create with code 86 before `verify_indexes` runs (`ensure: index … refused the creation with code 86`, `3 passed`). `start_runtime` always runs `ensure_indexes` before `verify_indexes` (round 1 Q4, `test_pr43_…` call log). Round 1's item 1 accepted "a differing stored key **or** uniqueness through a fake collection" as the second case; uniqueness was chosen. **N8 (non-blocking): accept** — the key branch is a defensive duplicate of the server's 86; re-open if `verify_indexes` is ever called without a preceding `ensure_indexes` (e.g. a read-only health check) or the expected key set changes.

`requirements.md:202` (§3 row PR22/PR39/PR52) now names the two comparison cases and which clause each covers; `tasks.md:89` H1 carries the round-2 note. **B1: closed** — the comparison's partial-filter and uniqueness clauses each fail a named PR52 case, on a real server for the reachable one, with a message assertion that names the index.

### P2 — B2, code 85 names the server's index

One check, my own mutation `B2r-greedy-regex` (`[^\s,]+` → `\S+`, i.e. the implementer's own first bug re-introduced): `1 failed, 7 passed` — `test_pr22_an_identical_index_under_another_name_fails_the_boot_naming_the_server_named_index`: `the one-liner does not drop the index the server named: … dropIndex("uq_other,")`. Restored, `cmp` identical. **B2: closed.**

### P3 — B3, the new rule in `tests/architecture/test_registration_behaviour.py` (`registration_statements`, `violations`)

Guard sha `dd988fb84b614ff5` throughout (restored after every arm). Shapes applied to the projector's **real** `application/handlers.py` (`64b21d037ae5f54b`) and `composition.py` (`e57aaf886ddf96ae`) by `.arm/p24-review2/shapes.py` through `.arm/p24-review2/arm2.sh` (two-file backup + sha256, process-group watchdog, restore, `cmp`, caches cleared). Each restored `cmp` identical.

| Shape on the real root (mine unless noted) | Listed by the implementer? | Result |
|---|---|---|
| `Q8b` (round 1): class-attribute `handlers` dict filled by `__init_subclass__`, drained by a helper `_one(registry, message, handler)` from a loop | yes (record's arm) | caught by the record's run: `… is data-driven: the message \`message\` is a parameter or a local of \`_one\`` (log in record; my `S8` below is the nested variant) |
| `S1` `for pair in _REGISTRATIONS:` (module-level tuple) `registry.register_command(pair[0], pair[1])` | no | **caught**: `… is data-driven: the message is not a plain reference (pair[0])` |
| `S2` `functools.partial(registry.register_command, ProjectFactCommand)(ProjectFactHandler)` | no | **caught** (old clause): `… reached from composition.py:90, which is not a direct \`.register_*(...)\` statement` |
| `S3` dict dispatch `{"command": registry.register_command}["command"](…)` | no | **caught** (old clause), same message |
| `S4` `getattr(registry, "register_" + "command")(…)` | no (F-a fixture exists) | **caught** (old clause), same message |
| `S7` `registry.register_command(*next(iter(SelfRegistering.handlers.items())))` | no | **caught**: `… fewer than two positional arguments` |
| `S8` the helper NESTED inside `register_handlers` (`def _one(message, handler): registry.register_command(message, handler)`), loop over the class-attribute dict | no | **caught**: `… a parameter or a local of \`_one\`` |
| **`S5` F-j alone, class-attribute holder:** `class SelfRegistering` whose `__init_subclass__(cls, *, message)` sets `SelfRegistering.message = message; SelfRegistering.handler = cls`; `class ProjectFactHandler(SelfRegistering, message=ProjectFactCommand)`; the root's ONE statement is `registry.register_command(SelfRegistering.message, SelfRegistering.handler)` | no | **passes**: `17 passed in 5.41s` on the guard file; over **all of `tests/architecture` + the projector `unit/` tree: `784 passed in 41.70s`** |
| **`S6` F-j alone, module globals:** the class-attribute dict as in `Q8b`, then at module level in `composition.py` `_MESSAGE, _HANDLER = next(iter(SelfRegistering.handlers.items()))`; the one statement `registry.register_command(_MESSAGE, _HANDLER)` | no | **passes**: `17 passed`; `tests/architecture` + projector `unit/`: **`784 passed in 41.53s`** |

**Premises of the new instrument (record line 6420 lists five, "each armed"):**

| Premise | Armed by | My arm | Result |
|---|---|---|---|
| (1) the statement at the caller line is the registration | the old cross-check | `S2`/`S3`/`S4` above | holds |
| (2) the enclosing function is the INNERMOST `def` | **none** — no fixture has a nested `def` | `B3r-outermost` (`enclosing_function` returns the outermost `def`), guard sha `dd988fb84b614ff5 → a5a99dba29765d90` | **`17 passed` — survives**; and with the guard so mutated, `S8` (nested helper on the real root) **passes** (`17 passed in 5.42s`): the premise matters and no sentinel holds it. The record's "each armed" is false for (2) |
| (3) "bound" = parameters + every `Store` name | `B3-locals-ignored` (record) | `B3r-params-only` (drop the `Store` names): `2 failed` — `[one_loop]`, `…closing_over_a_loop_variable…`, `AssertionError: []` | holds |
| (4) a lambda's own parameters are not locals | `one_control`, `one_lambda` + `B3-lambda-ignored` | — (record logs `.arm/p24-r2/B3-*.log` read: 3 / 2 / 1 failed as claimed) | holds |
| (5) the five real roots pass | the parametrised case | P5 below | holds |

**Finding B5 (blocking) — the F-j half of acceptance 8 still passes at this service's n = 1.** The module header (lines 4-6, 14-18) says the guard defeats F-j ("`__init_subclass__` self-registration, drained by the root") and that a statement must "name its message and handler"; acceptance 8 asks for the guard armed with F-g **+ F-j** against this service's root. The new rule bans *parameters and locals*, so it catches F-j only when it is drained through a helper or a loop (F-g). F-j drained by one statement whose arguments are an attribute of the self-registering base (`S5`) or module globals unpacked at import (`S6`) passes the guard and every other test in `tests/architecture` and the projector's `unit/` tree (784 passed each). The pairing message → handler is then decided at import time in `application/`, which is the convention the guard enforces (`CLAUDE.md`: "explicit registration in the composition root (no import-time decorators)"). The holder shape also works at any n (one holder class per registration), so it is not confined to the projector. **I own part of this:** round 1's item 2 suggested the parameters-or-locals rule as an example; it is the implementer's faithful realisation of my suggestion, and my round-1 arms (`Q8`, `Q8b`) combined F-j with F-g, so neither isolated F-j. It is still the shape acceptance 8 names, and the behavioural fix is available from data the probe already records: the recorded subject's class name (`ProjectFactCommand`) must be the terminal identifier of the statement's message argument (S5: `message`, S6: `_MESSAGE` → both fail), and likewise the handler's class name must appear in the handler argument (a `Name`/`Attribute` terminal identifier, or inside the factory `lambda`'s body).

**Finding B6 (blocking, same file, same round) — premise (2) is listed as armed and is not.** `B3r-outermost` survives the whole guard file, and under it the nested-helper F-g shape `S8` passes on the real root. A sentinel with a helper `def` nested in the root's function is owed (`CLAUDE.md`: "Changing an instrument swaps its premises. List the new instrument's assumptions and arm them in the same round").

### P4 — B4 (R50's evidence), N3, N4, N5

**B4.** `integration/test_timeline_projection.py`: `chain()` now gives `eventId`s `0xA0005 … 0xA0001` DESCENDING with `occurredAt` (placed greatest), arrival `[approved, despatched, placed, confirmed, reserved]`; the module docstring (`:3-8`) now says what the fixture is ("the `eventId` fallback alone would INVERT the `occurredAt` order … The causal chain follows the `occurredAt` order"), and the in-test comment (`:59-60`) states arrival is neither order. `occurredAt` order `[p, r, a, c, d]`, `eventId` order `[d, c, a, r, p]`, arrival `[a, d, p, c, r]` — three distinct orders, and the causal order equals `occurredAt` order, as the docstring says.

| Mutation (`timeline_order.py:92`, sha `ff45b14be9c3f5e0`) | Run | Result |
|---|---|---|
| `R50r-arrival-order` (round 1's `R50-arrival-order`, re-run): `sortBy: {__depth: 1, eventId: 1}` | the R50 case only | **`1 failed`**: `AssertionError: the timeline is not ordered by occurredAt … At index 0 diff: '000a0001-…' != '000a0005-…'` (round 1: `1 passed`) |
| `R50r-eventid-desc` (sibling direction): `sortBy: {__depth: 1, eventId: -1}` | the R50 case only | **`1 passed` — survives** |
| same | `services/projector/tests` (283 collected) | `11 failed, 272 passed in 49.61s`: `test_r52_…`, `test_pr44_…` ×7, `test_pr10_…` differential, `test_pr31_…`, unit `test_pr10_the_events_stage_sorts_…` |

All restored, `cmp` identical. **B4: closed** — the round-1 ask (an `eventId` order that inverts `occurredAt`, a true docstring, the arm re-run) is met. **N9 (non-blocking):** a perfectly *inverted* `eventId` order is still a fixed relation: `eventId` descending reproduces the expected order exactly, so the R50 case alone does not tell `occurredAt` from reversed `eventId` (the "fixtures must not satisfy the relation by accident" rule applied to a sibling sort direction). The behaviour is guarded (eleven other cases fail), and the double mutation (drop `occurredAt` *and* flip the direction) is less plausible than either alone. Disposition: **fix in the next round** since the feature goes back anyway — `eventId`s in an order that is neither ascending nor descending against `occurredAt` (e.g. placed `0xA0003`, reserved `0xA0005`, approved `0xA0001`, confirmed `0xA0004`, despatched `0xA0002`), docstring adjusted, both `R50r-*` arms re-run. If the leader judges it not worth a round on its own, **accept** with re-open trigger: any change to `test_r50_…`'s fixture or to `sortBy`.

**N3** — `grep -rn -i 'cycle terminate\|so a cycle\|cap makes\|capped at\|lose with\|one insert lose\|makes one insert\|DuplicateKeyError' services/projector/src specs/projector_read_model`, full output classified:
- `mongo_read_model_writer.py:6` "could make one insert lose …" followed by `:8-9` "Measured: … the retry is unreachable there" — conditional + measured, correct;
- `mongo_read_model_writer.py:14, 27, 42, 108` — the Phase-2 non-retry sentence, the import, `is_id_conflict`, the `except` — code, correct;
- `timeline_order.py:10-13` "capped at `|entries|`. The cap never binds … termination comes from the bounded `$reduce`" — correct;
- `domain/timeline_order.py:12-14` "(the cap never binds: the bounded rounds terminate a cycle …)" — correct;
- `kafka_fact_subscriber.py:89` backoff cap — unrelated;
- `requirements.md:50` (`PR7`'s conditional clause), `:60` (`PR31`, the requirement "a cycle terminates") — correct requirements;
- `design.md:60` (tree comment "DuplicateKeyError retried once"), `:210`, `:279`, `:446` (L3), `:474` (L26) — `:210` and `:279` now carry the measured premise (the leader's edit); `:60`, `:446`, `:474` describe the mechanism that exists, not its reachability — correct;
- `tasks.md:65, 69` — E2/E6 with the reworded survivor note — correct.
**N3: closed.**

**N4** — own corruption `N4r-seconds-operand` (the second `$max` operand of `updatedAt` written `…:36Z`, no milliseconds; `delta_to_pipeline.py:123`, sha `851603f7b00e8507`): `1 failed, 2 passed` — `test_pr41_ids_…`: `AssertionError: updatedAt operand '2026-03-02T16:12:36Z' is not a .mmmZ instant`. Restored, `cmp` identical. **N4: closed.**

**N5** — `test_projector_lifespan.py:162` now reads "the topics are private to this test (Topics fixture)". **N5: closed.**

**Shared matrix** (re-checked, the leader's claim): parsing `specs/shared/test-matrix.md` against `git show HEAD:` row by row, R50 – R55 change cell 5 only, every other `R5x` row unchanged, cell counts equal; R50's cell 5 now reads "five facts delivered in an order that is neither the `occurredAt` order nor the `eventId` order, the `eventIds` descending with time" — true of the fixture (see N9 for its limit).

### P5 — regression (round-2 paths) and conventions

- `quality.sh`: not re-run in full (P0: the recorded run is confirmed from its artefact and no source is newer than its log).
- Run by me, restored tree, developer stack down: `uv run pytest tests/architecture services/projector services/orders/tests/unit/test_idempotent_consumer_parity.py services/seed/tests/unit/test_read_model_constants.py` → **`886 passed in 89.05s`**, exit 0 (log `.arm/p24-review2/regression.log`; equals the record's 886). In it, `test_a_service_registers_only_from_its_composition_root_and_its_tables_match[orders|fulfillment|billing|notifications|projector]` all PASSED (premise 5 of the new rule).
- `lint-imports`: `Contracts: 11 kept, 0 broken.`; `ruff check services/projector tests/architecture`: `All checks passed!`; `ruff format --check`: `97 files already formatted`.
- Round-1 arms whose paths round 2 touched, re-run: `R50-arrival-order` (P4, now fails), `Q4-verify-differences-dead` (superseded by `B1r-*`, P1), `Q8b` (its F-g half now fails per the record; its F-j half isolated as `S5`/`S6`, P3), L22 (`N4r-…`, P4). Not touched by round 2, not re-run: Q1 – Q3, Q5 – Q7, Q9 – Q12.
- Tree after my probes: source shas `handlers.py 64b21d037ae5f54b`, `composition.py e57aaf886ddf96ae`, `read_model_indexes.py 854a7bd11699acaf`, `timeline_order.py ff45b14be9c3f5e0`, `delta_to_pipeline.py 851603f7b00e8507`, guard `dd988fb84b614ff5` (all equal to their pre-probe values); no scratch file left under `services/` or `tests/` (`git status --short --untracked-files=all services tests packages | grep -i 'zz\|review'` → no output).

---

## Round 2 — defects

### Blocking

| Id | File, line | Defect | Why it matters | Proof |
|---|---|---|---|---|
| **B5** | `tests/architecture/test_registration_behaviour.py:208-289` (`registration_statements`: any `Name`/`Attribute` that is not a parameter or local is accepted) | F-j (`__init_subclass__` self-registration) drained by ONE statement whose arguments are an attribute of the self-registering base (`registry.register_command(SelfRegistering.message, SelfRegistering.handler)`) or module globals unpacked at import (`_MESSAGE, _HANDLER = next(iter(SelfRegistering.handlers.items()))`) passes the guard on the projector's real root, and every test in `tests/architecture` + projector `unit/` | The guard's header (`:4-6`, `:14-18`) and feature 43's carried row (`progress/review_cqrs_dispatcher.md:177`, "catches … F-g/F-i/F-j") claim F-j is caught and that the statement "names its message and handler"; at this service's n = 1 the F-j half is caught only when combined with F-g. The pairing is then decided at import time in `application/`, the convention the guard exists for (`CLAUDE.md`: explicit registration, no import-time decorators). The holder shape works at any n. Partly mine: round 1's example rule was this one, and my round-1 arms never isolated F-j | `S5`, `S6`: `17 passed` (guard file), `784 passed` (`tests/architecture` + projector `unit/`) |
| **B6** | same file, `enclosing_function` (`:224-229`); record line 6420 ("Premises … each armed: … (2) the enclosing function is the innermost `def`") | Premise (2) has no sentinel: making `enclosing_function` return the OUTERMOST `def` leaves the whole guard file green, and under that mutation a helper nested in the root's function (`S8`) passes on the real root | `CLAUDE.md`: changing an instrument swaps its premises — list them and arm them in the same round. The record says each is armed; one is not (a countable claim unseen to fail) | `B3r-outermost`: `17 passed`; combined with `S8`: `17 passed in 5.42s` |

### Non-blocking (each with a disposition)

| Id | File, line | Finding | Disposition |
|---|---|---|---|
| N8 | `read_model_indexes.py:107-108` (the key comparison) | `B1r-key-dead` survives (`227 passed`): no case drives a stored key difference | **accept** — measured unreachable on a real server after `ensure_indexes`: three same-name different-key siblings are refused by the create with code 86 (P1); round 1 accepted key **or** uniqueness through a fake. Re-open if `verify_indexes` is called without a preceding `ensure_indexes`, or the expected keys change |
| N9 | `integration/test_timeline_projection.py:32-53` | the `eventId`s are a perfect inversion of `occurredAt` order, so `sortBy {__depth, eventId: -1}` (no `occurredAt`) passes the R50 case (11 other cases fail) | **fix** in the next round (the feature goes back for B5/B6 anyway): a scrambled `eventId` order, neither ascending nor descending; re-run `R50r-arrival-order` and `R50r-eventid-desc`. Accept instead only if the leader rules otherwise, re-open trigger: any change to the R50 fixture or `sortBy` |

Round-1 findings: **B1, B2, B3 (the stated mechanism: helper/loop at n = 1), B4, N3, N4, N5 closed** (P1 – P4); N1, N2, N6, N7 dispositions unchanged; R-1 filed by the leader (feature 27's two items, per the brief).

### Routed

- None new. No `specs/shared/` root cause in round 2: B5/B6 are in a repository guard, N9 in a projector test.

---

## Round 2 — `CHECKPOINTS.md`

**C1** — [x] unchanged since round 1 (harness files, agents, models); `./init.sh` not re-run (`git status --short init.sh .claude CHECKPOINTS.md` → no output: no harness file changed).

**C2** — [x] before this verdict: 38 `done`, 18 `pending`, 1 `in_review` (24), none `in_progress`; [x] every status valid; [x] no `done` feature touched; [x] no `blocked` feature.

**C3** — [x] `lint-imports` 11 kept / 0 broken (mine); [x] no cross-service access or import; [x] no shared runtime code beyond the three packages; [x] no `float`/`Decimal`/`/` added in the projector's domain (round 2 changed no domain code beyond a docstring: `domain/timeline_order.py`); [x] interactions unchanged (N7 as in round 1); [x] no debug leftovers in the round-2 diff.

**C4** — [x] `quality.sh` green per its artefact (P0), not re-run in full; [x] 886 targeted tests green (P5); [x] domain tests pure; [x] integration tests on testcontainers with the developer stack down; [x] coverage 97.26 % overall (log line 598); [x] no Jest/Karma/Jasmine.

**C5** — [x] no stray untracked files from this review; [ ] history entry — not applicable on a rejection; [x] feature 24 → `in_progress` (one line); [x] nothing committed.

**C6** — [x] spec files exist; [ ] every task genuinely done — **K3 / acceptance 8: the round-2 note says the guard bites at n = 1, true for F-g, false for F-j alone (B5), and one premise is unarmed (B6)**; [x] H1 (B1 closed), J1 (B4 closed; N9 is a residual of the fixture rule, not a broken rule); [x] every `R<n>` has a concrete named test that exercises it (R50 now fails under the eventId-order arm).

**C7** — [x] `specs/shared/` diff = column 5 of R50 – R55 + derived counts (re-parsed, P4); [x] inherited #8 findings: no change from round 1's Q13 except the D2 class ("tests that cannot fail"): B1, B4, N4 closed; **recurred once more in B6** (a premise stated as armed, unarmed); the #8 D10 class ("a guard that keeps losing to the next shape") **recurred** in B5.

---

## Round 2 — `R<n>` → test mapping verified

| Requirement | Test | Verified how (round 2) |
|---|---|---|
| R50 | `test_timeline_projection.py::test_r50_…` | fails under `R50r-arrival-order` (mine); N9 limit noted |
| R51 – R55 | as round 1 | unchanged by round 2; green in P5's 886 |
| PR22 / PR52 | `test_pr52_the_stored_partial_filter_…`, `test_pr52_a_stored_non_unique_…`, `test_pr22_an_identical_index_under_another_name_…` (+ round 1's) | fail under `B1r-partial-presence`, `B1r-unique-default`, `B1r-message-unnamed`, `B2r-greedy-regex` (mine); key clause N8 |
| PR27 / PR49 (acceptance 8) | `test_registration_behaviour.py::…[projector]` + the four new sentinels | F-g at n = 1 caught (S1, S7, S8; the record's `Q8b`); **F-j alone not caught (B5)**; premise (2) unarmed (B6) |
| PR41 (L22) | `unit/test_document_rendering.py::test_pr41_ids_…` | fails under `N4r-seconds-operand` (mine) |

---

## Round 2 — what must change before re-review

1. **B5** — make the guard check that each registration statement NAMES what it registers, from data the probe already records: the recorded message's class name must be the terminal identifier of the statement's message argument, and the handler's class name must be the terminal identifier of the handler argument or appear inside the factory `lambda`'s body (all five real roots already satisfy this: `grep -n -A2 '\.register_\(command\|query\|event\)(' services/*/src/otc_*/composition.py`). Arm it on the projector's real root with `S5` and `S6` (shapes in `.arm/p24-review2/shapes.py`) and add an n = 1 F-j-alone sentinel; update the header's F-j sentence to what is then true. An equivalent rule is fine if it fails `S5` and `S6` and passes the five roots.
2. **B6** — add a sentinel with a registration helper `def` nested inside the root's function (the `S8` shape) and arm premise (2) with `B3r-outermost` (`.arm/p24-review2/B3r-outermost.py`); correct the record's "each armed" if any premise stays unarmed.
3. **N9** — scramble the R50 fixture's `eventId`s (neither ascending nor descending against `occurredAt`), adjust the docstring, re-run `R50r-arrival-order` and `R50r-eventid-desc`.
4. Re-run `tests/architecture` in full (shared guard), the projector suite and the parity/seed pins; `quality.sh` only if anything outside `tests/architecture` and `services/projector/tests` changes.

---

**Round 2 verdict: REJECTED** — 2 blocking findings (B5, B6, both in the registration guard; acceptance 8 / task K3), 1 non-blocking fix bundled (N9), 1 accepted (N8). Round-1 B1 – B4, N3 – N5 closed. `feature_list.json` id 24 → `in_progress`. Note for the leader: this is the second rejection, so `CLAUDE.md`'s "at most one rejection round without asking" applies; B5 is partly an artefact of the example rule this review gave in round 1 (said above), and the remaining work is confined to one test file plus one fixture.

---

# Round 3 (scope: B5, B6, N9) — 2026-10-11

**Verdict: APPROVED** — 0 blocking findings. B5, B6, N9 closed; no regression. Arms in `.arm/p24-review3/` (sha256 recorded by the script, `cmp` restore each time, `__pycache__`/`.mypy_cache` cleared, process-group watchdog). Guard sha `16c125637c7bb2d8` restored identical after every arm; `timeline_order.py` `ff45b14be9c3f5e0` restored.

## Checks (each run)

1. **B5.** `arm2.sh S5-class-attr-holder` on the projector's real root, `test_registration_behaviour.py -k projector`: FAILED, `… composition.py:90 does not name its message: the statement says \`message\``. `S6-module-global-unpack`: FAILED, `… composition.py:92 does not name its message: the statement says \`_MESSAGE\``. Five real roots: the parametrised real-root cases pass in the full `tests/architecture` run (574 passed). My own arm `N-always` (`if statement["message"] != message or True:`): `test_a_service_registers_only_from_its_composition_root_and_its_tables_match[projector]` FAILED, `does not name its message: the statement says \`ProjectFactCommand\``. The n = 1 sentinels (`one_holder`, `one_globals`, `one_alias`) are in the green full run (21 cases in the file). Handler-clause arm `M-handler-dead` not re-run by me (implementer's record only; I read the clause at lines 372-378 and the alias sentinel asserts it).
   **Classification of the stated gap** (a lambda handler's class is not recorded, so only its message is checked): the lambda body is a literal in the statement, closing over a local is already flagged, and the message key is checked; the residual shape is a lambda whose body calls a module-level factory that returns another handler, with the right message. Not a regression of B5 as specified (the spec of B5 asked for exactly this rule, "or appear inside the factory lambda's body"). ACCEPTED, NOT FIXED; re-open trigger: any service registers a lambda-handler whose body calls a non-class factory function; carry to feature 25 `gateway_rest_auth` as a one-line check (record the factory's return type name in the probe).
2. **B6.** `arm.sh B3r-outermost` (enclosing_function returns the outermost `def`): `1 failed, 20 passed` — `test_sentinel_a_helper_def_nested_in_the_root_is_caught_by_the_innermost_function` (`assert any("is data-driven: …`" fails). `S8-nested-helper` on the real root: FAILED, `composition.py:91 is data-driven: the message \`message\` is a parameter or a local of \`_one\``. Premise list in the impl record: premise 2 now armed (confirmed above); premise 1/3 say "not re-armed in round 3, path unchanged" (honest, and I armed them in round 2); premise 7 says "UNARMED against the real root" (stated, not claimed armed); premise 8 a documented gap. No "each armed" overclaim remains.
3. **N9.** Fixture (`test_timeline_projection.py:35-65`): by `occurredAt` the eventIds are A3, A5, A1, A4, A2 (neither ascending nor descending); arrival is despatched, approved, reserved, placed, confirmed, which is neither the time order nor eventId ascending nor descending. `R50r-arrival-order` (sortBy without occurredAt): `test_r50_…` FAILED, `the timeline is not ordered by occurredAt`. `R50r-eventid-desc` (`DEPTH_FIELD: 1, "eventId": -1`): `test_r50_…` FAILED, same message (round 2: survived).
4. **Regression.** `uv run pytest tests/architecture`: 574 passed; `uv run pytest services/projector`: 283 passed (developer stack down: `docker ps` showed only `otcpy-n8n`); `lint-imports`: 11 kept, 0 broken. Record's `quality.sh` log read (`.arm/p24-r3/quality.log`, `quality.done`): `exit 0 dur 511s`, `4086 passed in 475.17s`, "all gates passed", coverage 97 %; not re-run (nothing outside `tests/architecture` and `services/projector/tests` changed in round 3; scope-bounded claim).

## CHECKPOINTS (round 3, scoped)

C3 [x] no production code changed in round 3; imports 11/0. C4 [x] targeted suites green, log artefact checked. C5 [x] no stray files from this review (only `.arm/`); [x] history entry written by this review (below). C6 [x] K3 / acceptance 8 now true at n = 1 for F-g and F-j; J1 closed. C7 [x] `specs/shared/test-matrix.md` round-3 edit is R50 column 5 only (leader-verified; not re-parsed by me).

## Accepted, not fixed

- Lambda-handler residual (above), for carrying to feature 25 `gateway_rest_auth` (the leader files it). Proof: reading `registration_statements`/`violations` (handler recorded only when the second argument is a class). Per the stopping rule I did not build a bypass shape beyond this reading.

`feature_list.json` id 24 → `done` (that line only).
