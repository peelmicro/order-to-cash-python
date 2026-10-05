# Premise check — brief_contracts_package.md

VERIFIED   asyncapi.yaml is AsyncAPI 3.0.0 with 99 components.schemas — yaml load: `3.0.0 99`
VERIFIED   openapi.yaml is 3.1.0 with 57 schemas — `3.1.0 57`
VERIFIED   Envelope at ~2156 — `grep -n '^    Envelope:'` -> 2156
VERIFIED   14 *Event schemas, each with a *Payload — 14 Event names, none lacks a matching Payload
VERIFIED   RpcError, RpcHeaders, FactHeaders, DeadLetterHeaders exist — all four in schema keys (plus Envelope)
VERIFIED   Envelope key order eventId,eventType,aggregateId,correlationId,causationId,occurredAt,payload — properties list from yaml
VERIFIED   12 golden file names exactly as listed — ls of #8 GoldenEnvelopes (12 files, names match)
VERIFIED   every golden has that key order — 12/12 identical list
VERIFIED   no golden for stock_rejected / order_saga_failed — absent from ls
VERIFIED   #8 paths src/Contracts/{Wire/JsonWire.cs,Wire/InstantJsonConverter.cs,Envelopes,Facts/FactCatalog.cs,Rpc} and tests/Contracts.UnitTests/{GoldenEnvelopeParityTests,JsonEquivalence,FactCatalogCompletenessTests,JsonWireOptionsTests}.cs — all present in ls
VERIFIED   #8 history.md lines 305-345 — section header at 305, closing `---` at 346
VERIFIED   #8 hand-wrote types — history line "#7 generated its contract types; #8 hand-wrote them"
VERIFIED   #7 generator/check scripts packages/contracts/scripts/{generate,check}.mts + lib/ + specs — all present
VERIFIED   #7 hit two surprises (single-line {} root-interface regex bug; title-beats-key naming) — #7 history.md:458 section, lines ~462-463
VERIFIED   datamodel-code-generator==0.83.0 in dev group — pyproject.toml:49 inside `dev = [`
VERIFIED   otc-contracts has no pydantic dependency — packages/contracts/pyproject.toml `dependencies = []`
VERIFIED   packages/contracts is a placeholder — only src/otc_contracts/__init__.py, no tests dir
VERIFIED   quality.sh section 5 is the SLOT — quality.sh:27-32 `section "5. contracts drift check"` with SLOT text
VERIFIED   tests/architecture domain allowlist — test_money_guard.py:92-181 (allowlist test); otc_contracts is only a root_package in pyproject.toml:159
VERIFIED   CLAUDE.md has "JSON wire shape" and "Payload columns" bullets — CLAUDE.md:83-84
VERIFIED   feature 8 acceptance is five items — feature_list.json:160-166
VERIFIED   scripts/generate_contracts.py does not exist yet — `ls scripts` shows only git-hooks
UNVERIFIABLE  "the plan's location" tests/fixtures/golden_envelopes/ — Plan is external private doc; not grepped in repo
UNVERIFIABLE  goldens are "real #7 wire bytes" — provenance; only #8 history asserts it
FUTURE     "Feature 8 will be in_progress when you start" — feature_list.json id 8 status is currently "pending" (line 159)

Counts: VERIFIED 21, FALSE 0, UNVERIFIABLE 2, FUTURE 1
Verdict: SAFE TO ACT
