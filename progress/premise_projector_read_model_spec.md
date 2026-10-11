# Premise check — brief_spec_projector_read_model.md

Repo root /home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python; #8 = ../order-to-cash-dotnet; #7 = ../order-to-cash-nestjs.

FALSE
- Lesson 8: `grep -rn "caller frame\|F-g\|F-j" services/*/tests` returns NOTHING (exit 1, no output). The guard lives at repo level: `tests/architecture/test_registration_behaviour.py` (F-g/F-j at lines 5, 16, 21, 332; `SERVICES` list at line 37 includes billing, notifications; `test_a_service_registers_only_from_its_composition_root_and_its_tables_match` parametrised at 268; sentinels 423-449) and `tests/architecture/test_cqrs_registration_explicit.py` (F-g/F-i/F-j at 353-354). Command that finds it: `grep -rIn "caller frame\|F-g\|F-j" tests/architecture`. Also in progress/impl_notifications_service.md:260 (B04) and impl_billing_invoicing.md:606 (H2). Consequence: acceptance 8 is satisfied by adding "projector" to SERVICES (and its table at ~line 98) in tests/architecture/, which is outside services/projector — the brief's tasks.md file list must allow that edit.

VERIFIED
- feature 24 has eight acceptance items: python3 count printed 8; items 5-8 are SA-2, the constants pin (212 projector half; text mentions TIMELINE_ORDER_VERSION etc.), backlog 201 gate decision, feature 43 registration guard. NOTE numbering: item 6 text is the constants-pin item, which is backlog 212's projector half (id 212 note/attached_to confirms); items 1-4 are the four unnumbered base items.
- test-matrix.md:172 = `## 7. projector_read_model — R50 – R55`; R54 (line 180) and R55 (181) carry "projector half" cells (two-half rows).
- test-matrix.md:124 = R24 row citing "amendment A1, projector_read_model PR10/PR30–PR33".
- README.md:34 = `SA-2 | #8, Phase 13 | asyncapi.yaml — OrderCancelledPayload ... optional note added`.
- R50 shared text (requirements.md:439-443): "present the timeline ordered by `occurredAt` rather than by arrival order".
- Line counts #8 spec: requirements 246, design 741, tasks 168; #8 gate record 100 lines; review 974. #7 spec: requirements 261, design 543, tasks 126; gate record 47; review 478. (wc -l)
- #8 gate record: 40 open points; row 1 = GATE (eager NATS connect, type (c)); row 2 = RATIFY (R54/R55); row 3 = NATS core publish; row 4 = seed allow-list; row 5 = partial index; row 9 = IdempotentConsumerParityTests case 4, and VariantBannerTests named in the same row.
- #7 gate record: 21 open points; "4 flagged ... rows 1, 2, 3 and 4" = index partiality (1), NATS core publish (2), R54/R55 split (3), seed allow-list (4); row 7 = OI12 case 4.
- #8 history.md:1546 = projector_read_model heading, "REJECTED three times, then approved", every rejection on records.
- #7 history.md:988 = projector_read_model (id 24) heading; its body states rejection once on bookkeeping (gate record row 37 of #8 says "two blocking defects... bookkeeping only"; not independently re-read beyond heading). Line 974 = OI12 finding text "the existence of a file the implementer chooses whether to create".
- test_idempotent_consumer_parity.py:50 = `def has_relational_ledger(package: Path) -> bool:` (also used at 65 and 125).
- .env.example lines 50-54: comment header + MONGO_HOST_PORT, MONGO_INITDB_ROOT_USERNAME, MONGO_INITDB_ROOT_PASSWORD, MONGO_DB_READMODEL=otc_read_model.
- services/projector skeleton: files are pyproject.toml, tests/test_projector_health.py, presentation/app.py, empty __init__ layers (domain/value_objects too), py.typed; no composition.py, no main.py; dependencies fastapi, uvicorn, otc-shared-kernel, otc-contracts, otc-cqrs (no Mongo/Kafka/NATS).
- services/seed/tests/unit/test_read_model_constants.py exists.
- tests/fixtures/read_model_constants.json: timelineOrderVersion 2, statusRank table, processedEventKeyPrefix "projector:", partial uq_order_reference index.
- Backlog 201 (note, acceptance a/b) and 212 (seed half done, projector half is item of feature 24) exist as described; feature 43 acceptance carries the per-service registration half "on features 15, 17, 19, 23, 24 and 25".

UNVERIFIABLE
- Contents of #7's history line 988 beyond the heading (not required beyond "rejected once, bookkeeping only": confirmed by #8 gate row 37 quoting it). Not checked: "Phase 11's search returned 23 ids", the 16 duplicate records on the live topics, and the code/behaviour claims in the Questions section (they are tasks, not premises).

Verdict: DO NOT ACT as written on lesson 8 only (1 FALSE); everything else VERIFIED.
