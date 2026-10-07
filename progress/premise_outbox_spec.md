# Premise check: brief_spec_outbox_and_idempotency.md

VERIFIED feature 14 exists, sdd true, status pending, six acceptance items, items 5 (205) and 6 (203 item 2) as quoted (python read of feature_list.json)
VERIFIED 205 (instant_millisecond_agreement) and 203 (item 2, generic Envelope half, carried to feature 14) mean what the brief says (feature_list.json)
VERIFIED #8 spec line counts 163 req / 636 design / 105 tasks; #7 105 / 515 / 93 (wc -l)
VERIFIED #8 history.md: outbox entry at line 730, next entry at 773, "Notes for #9" at 763 (grep -n)
VERIFIED #8 cites R11-R18 (history line 730 "R11 - R18"; #8 requirements.md cites R11..R18); #8 reuses OI ids (OI1..OI10+)
VERIFIED shared requirements.md section 2 outbox_and_idempotency is R11-R18 (line 54 table; R11-R18 at 128-165): envelope, correlationId, single txn, relay-only publish, partition key, DLQ, processed pair, redelivery no-op
VERIFIED #8 backlog 87 = deadlock victim escapes RunOnceAsync (feature_list.json)
FALSE (partial) #8 backlog 111 as stated "retried unboundedly ... no poison-row breaker": 111 was an open question, DISPOSED "ACCEPTED, NOT FIXED"; neither repo has a breaker, #8 is not lacking what #7 supplies, unbounded retry was never demonstrated. Feature 14's acceptance still requires poison handling inside run_once, so this is #9's choice, not an inherited fix.
VERIFIED models.py has Outbox (line 156) and ProcessedEvent (176) with payload RawJson() whose DDL type is "JSON" (types.py:24), not jsonb; processed_events unique (event_id, consumer); outbox.seq Identity
VERIFIED packages/contracts has to_wire_json (wire.py:161)
VERIFIED services/orders/src/otc_orders/domain/events.py exists; packages/cqrs/src/otc_cqrs exists (dispatcher, handlers, errors, messages)
VERIFIED guards exist: tests/architecture/test_write_path_population.py, test_range_guard_parity.py, test_cqrs_registration_explicit.py (ls)
UNVERIFIABLE "#7's D1-D10" listed in its history: brief hedges with "if"; not searched exhaustively
UNVERIFIABLE "Plan adds ..." claims (external document, not in repo)

Verdict: DO NOT ACT strictly (1 FALSE partial, 2 UNVERIFIABLE); the FALSE is a characterisation of 111, harmless to scope.
NOTED: a non-generic Envelope(WireModel) with payload dict[str, Any] already exists at packages/contracts/src/otc_contracts/generated/asyncapi.py:114.
