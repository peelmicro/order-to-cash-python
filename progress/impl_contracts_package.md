# Implementation: `contracts_package` (id 8, phase 5), full process (wire contract), `sdd: false`

Status set by the leader (`in_progress`); I did not touch `feature_list.json`. No `tasks.md` exists (`sdd: false`); the contract is the five-item `acceptance` array, `specs/shared/asyncapi.yaml`, `specs/shared/openapi.yaml` and `CLAUDE.md`. No git command that writes was run.

## Files

New:
- `scripts/generate_contracts.py` (generator + `--check` + `--out`)
- `packages/contracts/src/otc_contracts/wire.py` (the one serializer configuration)
- `packages/contracts/src/otc_contracts/facts.py` (registry `eventType` -> model, `parse_fact`)
- `packages/contracts/src/otc_contracts/generated/{asyncapi,openapi,nullable}.py` (GENERATED, committed; `__init__.py` is hand-written)
- `packages/contracts/tests/test_{golden_envelopes,wire_serializer,spec_alignment,generation_drift,facts_without_a_golden,contracts_dependencies}.py` (159 tests)
- `tests/fixtures/golden_envelopes/*.json` (12 files, `cmp`-identical to `../order-to-cash-dotnet/tests/Contracts.UnitTests/GoldenEnvelopes/`)

Edited:
- `packages/contracts/src/otc_contracts/__init__.py` (exports)
- `packages/contracts/pyproject.toml` (`dependencies = ["pydantic==2.13.5"]`)
- `quality.sh` section 5 (SLOT replaced by `uv run python scripts/generate_contracts.py --check`; header line 4 reworded)
- `uv.lock`
- **Bound deviation, flagged for the leader:** root `pyproject.toml` dev group gained `pyyaml==6.0.3` and `types-pyyaml==6.0.12.20260906`. The generator and the spec-reading tests import `yaml`; `mypy --strict` has no global `ignore_missing_imports`, so the stubs are required, and a member's dependency group is not installed by `uv sync` at this root. `pyyaml` was already installed transitively via `datamodel-code-generator`; it is now explicit and pinned. Revert-able if you prefer another home.

## Commands and versions

- Regenerate: `uv run python scripts/generate_contracts.py`. Check: `uv run python scripts/generate_contracts.py --check` (also `--out DIR`, used by the test that proves the check can fail).
- `datamodel-code-generator==0.83.0` (the script refuses any other installed version). Options (constants `CODEGEN_ARGS`): `--input-file-type jsonschema --output-model-type pydantic_v2.BaseModel --base-class otc_contracts.wire.WireModel --target-python-version 3.14 --snake-case-field --no-alias --use-annotated --field-constraints --use-standard-collections --use-union-operator --collapse-root-models --skip-root-model --disable-timestamp --formatters builtin`.
- Formatting after generation: the script pipes each file through `python -m ruff check --fix --select I,F401,UP` and `ruff format` **with the repository's `pyproject.toml` via stdin** (`--stdin-filename` under `packages/contracts/...`), so output is identical wherever generated and passes the repo's 100-column config with no excludes.
- Pydantic 2.13.5, ruff 0.16.10, mypy 2.4.0.

What the extraction does (all in `load_spec`, nothing hand-edited): `components.schemas` -> JSON-Schema document with `#/components/schemas/X` rewritten to `#/$defs/X`; **dropped** `description`/`examples`/`title`/`$comment` at schema level (they live in the spec; they would push generated lines past 100 columns, so ruff E501 would need an exclude; property *names* `description`/`title` are protected, `OrderLine.description` survives); `format: int64`/`int32` on integers becomes explicit `minimum`/`maximum` (the spec declares the width, Pydantic `int` is unbounded); `format: uri|password` dropped (would become `AnyUrl`/`SecretStr`, which have no wire writer); any other unknown format is refused. `allOf: [{$ref: Base}, {properties}]` is **flattened** (the generator otherwise emits `class XEvent(Envelope)` redeclaring `payload` with a narrower type, which `mypy --strict` rejects: 14 errors observed). Flattening keeps Envelope property order and replaces `eventType` by the `const` and `payload` by the `$ref`; the script asserts every `*Event` schema was merged. **Excluded schemas** (literal set): `FactHeaders`, `DeadLetterHeaders`, `RpcHeaders` (transport header keys like `content-type`, `x-original-topic`; cannot be camelCase; no body is parsed into them; `test_the_excluded_header_schemas_are_transport_headers_with_non_camel_case_keys`).

Generated: `asyncapi.py` 102 classes (`grep -c "^class"` on the committed file; includes enums and the dead root models below), `openapi.py` 54 classes. Not collapsed by the generator: 2 dead `RootModel`s in asyncapi (`Quantity`, `ProductCode`, unreferenced) and 3 in openapi (`DespatchReference`, `InvoiceReference`, `PaymentReference`, referenced by `OrderReferences`' nullable fields); inert, left as generated.

## Answers to the brief's questions (each measured in this session)

1. **Does `model_dump_json` write compact separators and raw non-ASCII by default (Pydantic 2.13.5)?** Yes to both: `{"t":"é—日本","d":"2026-08-30T16:20:20.442123Z"}`. Pinned by `test_pydantic_default_json_is_already_compact_and_raw_but_the_writer_does_not_rely_on_it`. The writer still states `separators=(",", ":")` and `ensure_ascii=False` explicitly (arms A4, A5).
2. **What does Pydantic write for a datetime?** Microseconds (`.442000Z`), proven by `test_pydantic_default_datetime_output_is_not_the_wire_format`. So the writer is `json.dumps(model.model_dump(mode="python"), default=...)` with `format_instant` as the explicit formatter. `model_dump_json` is therefore NOT the wire writer and must not be used by services for facts (a repo-wide guard on that is for the first feature that publishes; I did not add it, `tests/architecture` is out of bounds).
3. **Aware non-UTC datetime:** converted to UTC (`18:20:20.442+02:00` -> `16:20:20.442Z`). **Naive datetime:** `format_instant` raises `ValueError` ("timezone-aware"); parsing a naive string fails because the generated type is `AwareDatetime`. **Sub-millisecond:** parse accepts it, write **truncates** (`.442999` -> `.442`, `.999999` -> `.999`), the same as `.fff` in #8 and `toISOString()` in #7. Tests: `test_instant_is_written_as_yyyy_mm_ddthh_mm_ss_mmmz` (7 cases), `test_a_naive_datetime_has_no_instant_and_is_refused`, `test_a_naive_instant_is_refused_when_parsing`, `test_the_serializer_writes_instants_inside_a_model_as_mmmz`. Lax forms Pydantic's datetime parser accepts (no fractional part, space separator) are accepted on input and normalised on output; recorded, not forbidden.
4. **Integer strictness (CLAUDE.md money row, M1):** `ConfigDict(strict=True)` on `WireModel`, so `"8934"`, `8934.0`, `true`, `false`, `8934.5`, `1e3` and `null` are refused for every integer field (`MinorUnits`, `Quantity`, `UnitCount`, `attempts`, ...). Lax mode measured: `"6"` -> `6`. `int64` bounds enforced from the spec's `format: int64` (`2**63` refused, `2**63-1` accepted). `Quantity >= 1` enforced. Consequence of strict mode, deliberate: Python code constructs models with real `UUID`/`datetime`/enum objects, never strings; wire text goes through `from_wire_json` (JSON mode). Tests: `test_a_money_or_quantity_integer_field_refuses_a_string_float_or_bool` (21 cases), `test_money_beyond_the_int64_the_spec_declares_is_refused`, `test_the_int64_bounds_themselves_are_accepted`, `test_a_quantity_below_one_is_refused`, `test_strict_mode_is_a_model_config_decision_not_a_per_call_flag`.
5. **Alias mechanism:** exactly one, `alias_generator=to_camel` in `WireModel` (`wire.py`). The generator runs `--no-alias`, so there is no `Field(alias=...)`: proven by AST scan (`test_no_generated_field_carries_its_own_alias`, 3 modules) and by `test_the_alias_generator_is_declared_exactly_once_in_the_package`. Parsing is by alias only (`by_alias=True, by_name=False`); `validate_by_name=True` is set in config only so mypy-visible snake_case construction works. `test_every_object_schema_has_a_model_whose_fields_are_the_spec_properties_in_order` proves every spec property name equals the generated field's alias, for both specs.
6. **Envelope order:** `asyncapi.yaml` `Envelope.properties` order is `eventId, eventType, aggregateId, correlationId, causationId, occurredAt, payload` (read from the YAML at test time, then pinned as a literal in `test_the_envelope_field_order_is_the_order_the_spec_declares`); every golden has the same seven keys in the same order (`test_a_golden_envelope_has_the_envelope_keys_in_spec_order`, 12). All 14 generated Event models list their fields in that order. Both recorded and equal.

## Per-field None table (decided against `asyncapi.yaml`; enumerated by the test `test_the_not_required_fields_of_the_fourteen_payloads_are_these_and_none_is_nullable`)

Rule (one rule, `WireModel._omit_absent_none`, driven by the generated `nullable.py`): a `None` is written as `null` only for a field the spec declares nullable (`oneOf` with `type: 'null'`); every other `None` is **absent**.

| Schema | Not-required field | Nullable in spec? | Decision |
|---|---|---|---|
| `OrderPlacedPayload` | `notes` | no | absent when None |
| `StockReservedPayload`, `StockRejectedPayload`, `StockReleasedPayload` | `retailerCode` | no | absent when None |
| `CreditRejectedPayload`, `CreditReleasedPayload` | `creditCode` | no | absent when None |
| `OrderCancelledPayload` | `note` | no | absent when None |
| `OrderLine` (inside `OrderPlacedPayload`) | `description` | no | absent when None |
| `PartyRef` | `name` | no | absent when None |
| `CompensationStep` (inside `OrderCancelledPayload`) | `eventId`, `summary` | no | absent when None |
| the other 6 fact payloads | none | n/a | every field required |
| `asyncapi.InvoiceView` (RPC view) | `paidAt` | **yes** | explicit `null` ("null while issued", B9) |
| `openapi`: `Invoice.paidAt`, `OrderDetail.cancellationReason`, `OrderStreamUpdate.cancellationReason`, `OrderSummary.cancellationReason`, `OrderReferences.{despatchReference,invoiceReference,paymentReference}`, `StreamReady.orderId` | all are nullable in the spec | **yes** | explicit `null` |

The other optional fields of the RPC/REST schemas (enumerated in the session with a YAML walk; e.g. `PageRequest.page`, `RpcError.details`) follow the same rule: absent when None. Evidence the table equals the spec: `test_the_nullable_table_is_exactly_what_the_spec_declares_nullable` (independent computation in the test, 7 classes non-vacuity assertion).

**Difference from #8, for the leader:** #8's `JsonWire` uses `WhenWritingNull` globally (`../order-to-cash-dotnet/src/Contracts/Wire/JsonWire.cs:40`), so a nullable field is *omitted* there; #9 writes `"paidAt":null`, which is what the spec's own words ("null while `issued`") say. No golden covers a nullable field (none of the 12 facts has one), so cross-stack byte parity for these RPC/REST fields is unproven either way. If the maintainer wants #8's behaviour, the single change is an empty `NULLABLE_FIELDS`.

## Test inventory and what each proves (acceptance items)

No `R<n>` is claimed; `specs/shared/test-matrix.md` untouched (R11 stays with `outbox_and_idempotency`, as in #8).

- Item 1 (generated, drift check in quality.sh): `test_generation_drift.py` (6): `test_the_committed_generated_files_equal_a_fresh_generation`, `test_generation_is_deterministic`, `test_every_generated_file_is_marked_as_generated_and_names_its_source`, `test_the_drift_check_flags_an_edited_file_and_a_missing_file_by_name` (sentinels), `test_the_check_command_names_the_drifted_file_and_exits_non_zero` (real CLI), plus `test_a_fresh_generation_writes_exactly_the_three_committed_files`; and `quality.sh` section 5. `test_spec_alignment.py` (12): completeness of the 14 events (`test_every_event_schema_has_a_model_and_a_registry_entry`, non-vacuity `test_the_spec_declares_fourteen_event_schemas_so_the_sweep_is_not_vacuous`), literal pinning, payload type names, enums, required-ness and property order for every object schema of both specs, the two facts with no golden listed explicitly (`test_the_facts_with_no_golden_are_exactly_the_two_listed`).
- Item 2 (one serializer configuration): `test_wire_serializer.py` (24 test functions).
- Item 3 (envelope byte-exact, field set and order): `test_envelope_is_byte_exact_against_the_golden` (12: literal bytes before `"payload"`), `test_a_golden_envelope_has_the_envelope_keys_in_spec_order` (12), `test_the_envelope_field_order_is_the_order_the_spec_declares`.
- Item 4 (payload semantically equal, key order not asserted): `test_payload_is_semantically_equal_to_the_golden` (12), with the strict comparer `strict_json_differences` proven by `test_the_payload_comparer_sees_a_difference` (16 sentinel pairs: int vs float, int vs bool, str vs int, null vs 0/missing, nested, extra/missing key, array order/length) and `test_the_payload_comparer_ignores_object_key_order_at_every_depth`; `test_python_equality_alone_cannot_see_the_differences_the_comparer_sees` records why `json.loads(a) == json.loads(b)` is not used.
- Item 5 (round trip): `test_round_trip_every_golden_parses_into_its_model_and_reserialises_equal` (12, also asserts the model class by registry and a parse/write fixed point), `test_every_golden_relabelled_with_a_sibling_event_type_is_refused` (12 x 11 = 132 relabellings), `test_a_credit_approved_envelope_is_refused_by_the_credit_rejected_model`.
- Goldens: `test_the_twelve_golden_envelope_files_are_exactly_these` (literal set of 12), `test_the_golden_bytes_are_pinned` (SHA-256 per file), `test_a_golden_parses_to_the_values_the_file_literally_holds` (non-circular literals), `test_the_non_ascii_golden_is_written_raw_not_escaped` (only `order_cancelled_v1.json` has non-ASCII: an em dash in `summary`; found with `grep -l "[^ -~]"`).
- No-golden facts: `test_facts_without_a_golden.py` (4) with hand-written spec-derived envelopes for `stock.rejected.v1` and `order.saga_failed.v1` (shape tests, NOT parity evidence).
- Dependencies (#8 advisory A4): `test_contracts_dependencies.py` (3 + 7 per-module cases): allow-list of imported roots (stdlib + `pydantic` + `otc_contracts`), declared dependency list is exactly `["pydantic==2.13.5"]`. `tests/architecture` still forbids `domain` / `shared_kernel` from importing `otc_contracts` (unchanged, still green).

## Ported-idiom ledger

| Idiom | #7 relied on | #8 supplied | In #9 |
|---|---|---|---|
| Generator | `openapi-typescript` + `json-schema-to-typescript` over extracted `components.schemas` (`../order-to-cash-nestjs/packages/contracts/scripts/lib/generate-asyncapi.mts:37-45`) | hand-written types, no generator (`../order-to-cash-dotnet/progress/history.md:317`) | `datamodel-code-generator==0.83.0` via `scripts/generate_contracts.py`; guarded by `test_the_committed_generated_files_equal_a_fresh_generation`, `test_generation_is_deterministic` |
| Drift check | `check.mts` regenerates to a temp dir and `diff -u` (`check.mts:27,54`) | two spec-parsing completeness tests, no drift gate (`history.md:317`) | `--check` in `quality.sh` section 5 plus `test_spec_alignment.py`; header carries each spec's SHA-256; guarded by `test_the_drift_check_flags_an_edited_file_and_a_missing_file_by_name` and the CLI test |
| camelCase alias | the spec's own camelCase names are the TS property names | `PropertyNamingPolicy = CamelCase` (`JsonWire.cs:38`) | one `alias_generator=to_camel` on `WireModel`; generator `--no-alias`; guarded by `test_no_generated_field_carries_its_own_alias`, `test_the_alias_generator_is_declared_exactly_once_in_the_package`, `test_the_wire_is_camel_case_and_python_names_are_snake_case` |
| Compact JSON | `JSON.stringify` (compact by language) | `WriteIndented = false` (`JsonWire.cs:41`) | `separators=(",", ":")` stated explicitly; guarded by `test_output_is_compact_with_no_space_after_separators` |
| Raw non-ASCII | `JSON.stringify` writes raw | `UnsafeRelaxedJsonEscaping` (`JsonWire.cs:42`) | `ensure_ascii=False`; guarded by `test_non_ascii_text_is_written_raw_not_as_u_escapes`, `test_the_non_ascii_golden_is_written_raw_not_escaped` |
| Timestamp | `toISOString()` (always `.mmmZ`) | `InstantJsonConverter`, `yyyy-MM-dd'T'HH:mm:ss.fff'Z'` (`InstantJsonConverter.cs:25,45`) | explicit `format_instant` (truncating); Pydantic default writes `.442000Z`; guarded by `test_instant_is_written_as_yyyy_mm_ddthh_mm_ss_mmmz`, `test_envelope_is_byte_exact_against_the_golden` |
| None handling | TS optional (`?:`), `JSON.stringify` drops `undefined` | `WhenWritingNull` global (`JsonWire.cs:40`) | per-field via generated `nullable.py`; guarded by `test_a_not_required_field_that_is_none_is_absent_not_null`, `test_a_nullable_field_that_is_none_is_written_as_an_explicit_null`, `test_the_nullable_table_is_exactly_what_the_spec_declares_nullable` |
| Integer strictness | TS `number` (no integer type; `Number.isSafeInteger` in the kernel) | `long` (System.Text.Json refuses `"8934"` by default) | `strict=True` plus spec-derived int64 bounds; guarded by `test_a_money_or_quantity_integer_field_refuses_a_string_float_or_bool`, `test_money_beyond_the_int64_the_spec_declares_is_refused` |
| Payload equivalence | n/a (no golden oracle) | recursive `JsonElement` comparison, order-immaterial (`JsonEquivalence.cs`) | `strict_json_differences` with `type(...)` checks (Python `1 == 1.0 == True`); guarded by `test_the_payload_comparer_sees_a_difference` |

"None owed" rows: none. Python questions asked: integer division (none in this package, `grep -n " / " ` over `wire.py`/`facts.py`/`generate_contracts.py` finds only `//` in `format_instant`; there is a `/` in the script's `Path` joins only), JSON serialisation (separators, `ensure_ascii`, timestamp: all explicit), event-loop affinity (nothing async here), typing gaps (generator output passes `mypy --strict`; `document.get(...)` in `parse_fact` is `Any` and narrowed by `isinstance` before use; one `cast` to the `FactEvent` union).

## Arming (CLAUDE.md protocol; harness `scratchpad/arm/arm.py`, 39 arms, final run after the last code edit)

Protocol per arm: `cp` backup of every touched file, plant, clear `__pycache__`, run the ONE named test, record failure, restore by `cp`, `filecmp` byte compare, clear caches, re-run green. Spec arms edit `specs/shared/asyncapi.yaml` itself (restored byte-identical; afterwards `./init.sh` 5d reports it byte-identical to #8 and #7). All 39: restored file identical, re-run exit 0. Verbatim failures are truncated to the first assertion line.

| Arm (claim; mutant) | Result and verbatim failure | Restored + cmp identical | Re-run |
|---|---|---|---|
| A1 drift: hand-edit generated file | killed: `DRIFT: packages/contracts/src/otc_contracts/generated/asyncapi.py differs from a fresh generation` | yes | exit 0 |
| A1b drift (pytest): same edit | killed: `E           AssertionError: asyncapi.py drifted from the generator / E           assert '# GENERATED ...None = None\n' == '# GENERATED ...None = None\n'` | yes | exit 0 |
| A2 drift: property added to asyncapi.yaml, no regeneration (check) | killed: `DRIFT: packages/contracts/src/otc_contracts/generated/asyncapi.py differs from a fresh generation / DRIFT: packages/contracts/src/otc_contracts/generated/nullable.py differs from a fresh generation` | yes | exit 0 |
| A2b spec edit: same, spec-alignment test | killed: `E       assert ["asyncapi.Or...extraProbe']"] == [] / E` | yes | exit 0 |
| A3 formatter: isoformat instead of explicit .mmmZ | killed: `E       AssertionError: assert '2026-08-30T1....442000+00:00' == '2026-08-30T16:20:20.442Z' / E` | yes | exit 0 |
| A3b formatter: Pydantic default datetime output (python-mode dump replaced by json-mode) | killed: `E       assert b'{"eventId":...0:20.979000Z"' == b'{"eventId":...6:20:20.979Z"' / E` | yes | exit 0 |
| A4 compact: default json separators | killed: `E       assert '{"amount": 1...ency": "EUR"}' == '{"amount":12...rency":"EUR"}' / E` | yes | exit 0 |
| A4b compact: default separators vs goldens | killed: `E       AssertionError: the payload is the last envelope field / E       assert False` | yes | exit 0 |
| A5 raw non-ASCII: ensure_ascii=True | killed: `E       assert 'Líquido — 日本 ñ' in '{"productCode":"PRD-0008","description":"L\\u00edquido \\u2014 \\u65e5\\u672c \\u00f1","quantity":1,"unitPrice":1,"lineDiscount":0}' / packages/contracts/tests/test_wire_serializer.py:115: Asser` | yes | exit 0 |
| A5b raw non-ASCII: ensure_ascii=True vs the real golden | killed: `E       assert '—' in '{"eventId":"6f69651a-46aa-4895-a70b-55a4804f405b","eventType":"order.cancelled.v1","aggregateId":"28211434-b1a5-41ab-...ck.released.v1","occurredAt":"2026-08-30T17:03:45.767Z","summary":"stock released \\u20` | yes | exit 0 |
| A6 envelope order: swap eventId/aggregateId in OrderPlacedEvent | killed: `E       assert b'{"aggregate...6:20:20.442Z"' == b'{"eventId":...6:20:20.442Z"' / E` | yes | exit 0 |
| A6b envelope order vs the spec | killed: `E           AssertionError: OrderPlacedEvent / E           assert ['aggregateId...urredAt', ...] == ['eventId', '...urredAt', ...]` | yes | exit 0 |
| A7 comparer: type check removed (== only) | killed: `E       AssertionError: 8934 vs 8934.0 was not flagged / E       assert []` | yes | exit 0 |
| A7b comparer lax + lax parse + golden 8934.0 (int->float regression invisible to ==) | SURVIVED (expected): `............                                                             [100%] / 12 passed in 0.23s` | yes | exit 0 |
| A7c comparer strict + lax parse + golden 8934.0 | killed: `E       AssertionError: assert ['$.payload.t... vs int 8934'] == [] / E` | yes | exit 0 |
| A7d comparer strict + lax parse + golden lineDiscount true | killed: `E       AssertionError: assert ['$.payload.l...rue vs int 1'] == [] / E` | yes | exit 0 |
| A8 corrupt golden payload value 8934->8935 (valid sibling value) | killed: `E       AssertionError: golden bytes changed (copied from #8, must be immutable): ['order_placed_v1.json'] / E       assert ['order_placed_v1.json'] == []` | yes | exit 0 |
| A8b same corruption vs literal-value test | killed: `E       AssertionError: assert 8935 == 8934 / E        +  where 8935 = OrderPlacedPayload(order_reference='ORD-000011', retailer_code='LeroyMerlinEs', company_code='PORTOTOOLS', buyer_gln='...quantity=6, unit_price=1489, line_disc` | yes | exit 0 |
| A8c same corruption vs round trip (expected survivor) | SURVIVED (expected): `............                                                             [100%] / 12 passed in 0.25s` | yes | exit 0 |
| A9 sibling eventType: registry credit.approved -> CreditRejectedEvent | killed: `E       pydantic_core._pydantic_core.ValidationError: 4 validation errors for CreditRejectedEvent / E       eventType` | yes | exit 0 |
| A9b sibling eventType vs completeness | killed: `E       AssertionError: assert ['credit.appr...pprovedEvent'] == [] / E` | yes | exit 0 |
| A9c sibling literal: CreditRejectedEvent literal -> credit.approved.v1 | killed: `E           AssertionError: CreditRejectedEvent: typing.Literal['credit.approved.v1'] / E           assert ('credit.approved.v1',) == ('credit.rejected.v1',)` | yes | exit 0 |
| A9d registry entry deleted | killed: `E       AssertionError: assert ['order.saga_...aFailedEvent'] == [] / E` | yes | exit 0 |
| A10 None: not-required field emitted as null | killed: `E       assert 'description' not in '{"productCo...Discount":0}' / E` | yes | exit 0 |
| A10b None: nullable field dropped when None | killed: `E       assert '"paidAt":null' in '{"invoiceId":"11111111-1111-4111-8111-111111111111","invoiceReference":"INV-000027","invoiceDate":"2026-01-01T00:00:0...0011","retailerCode":"R","companyCode":"C","currency":"EUR","amount":1,"dis` | yes | exit 0 |
| A10c None: nullable table corrupted (paidAt removed) | killed: `E       AssertionError: assert {'asyncapi.In...erence'], ...} == {'asyncapi.In...erence'], ...} / E` | yes | exit 0 |
| A10d None: sibling class key (asyncapi.InvoiceView -> asyncapi.InvoiceLine) | killed: `E       AssertionError: assert {'asyncapi.In...erence'], ...} == {'asyncapi.In...Reason'], ...} / E` | yes | exit 0 |
| A11 integer strictness: strict=False (str) | killed: `>       with pytest.raises(ValidationError): / E       Failed: DID NOT RAISE ValidationError` | yes | exit 0 |
| A11b int64 bound removed from generator (edit generated file) | killed: `>       with pytest.raises(ValidationError): / E       Failed: DID NOT RAISE ValidationError` | yes | exit 0 |
| A12 alias: per-field alias added | killed: `E       AssertionError: assert ['asyncapi.py:17 alias='] == [] / E` | yes | exit 0 |
| A13 alias generator removed | killed: `E       assert '{"product_co..._discount":3}' == '{"productCod...eDiscount":3}' / E` | yes | exit 0 |
| A13b parse accepts snake_case (by_name=True) | killed: `>       with pytest.raises(ValidationError): / E       Failed: DID NOT RAISE ValidationError` | yes | exit 0 |
| A14 Decimal accepted by default hook | killed: `>       with pytest.raises(TypeError, match="Decimal has no wire representation"): / E       Failed: DID NOT RAISE TypeError` | yes | exit 0 |
| A15 naive datetime accepted by format_instant | killed: `>       with pytest.raises(ValueError, match="timezone-aware"): / E       Failed: DID NOT RAISE ValueError` | yes | exit 0 |
| A16 ms rounding instead of truncation | killed: `E       AssertionError: assert '2026-08-30T16:20:20.443Z' == '2026-08-30T16:20:20.442Z' / E` | yes | exit 0 |
| A18 dependency: import bson (a package no deny-list named) in wire.py | killed: `E       AssertionError: wire.py imports ['bson'] / E       assert {'bson'} == set()` | yes | exit 0 |
| A18b dependency: import inside `if TYPE_CHECKING:` (dead region) | killed: `E       AssertionError: wire.py imports ['httpx'] / E       assert {'httpx'} == set()` | yes | exit 0 |
| A18c dependency: second runtime dependency declared | killed: `E       AssertionError: assert ['pydantic==2...ttpx==0.28.1'] == ['pydantic==2.13.5'] / E` | yes | exit 0 |
| A17 excluded headers added to generation (EXCLUDED emptied) | killed: `DRIFT: packages/contracts/src/otc_contracts/generated/asyncapi.py differs from a fresh generation` | yes | exit 0 |
Two survivors, both expected and informative:
- **A7b** (a lax comparer with a lax parse and `8934.0` in a golden): `test_payload_is_semantically_equal_to_the_golden` passes. That is the point of the sentinel test: with `==` the int-to-float regression is invisible end to end, so the comparer's own strictness is guarded by A7 (the `test_the_payload_comparer_sees_a_difference` pairs) and the parse strictness by A11; A7c/A7d show the strict comparer does see `float 8934.0 vs int 8934` and `bool True vs int 1` once the parse is lax.
- **A8c** (golden `8934` -> `8935`): `test_round_trip_...` passes because the model re-serialises what it parsed. The corruption is caught by `test_the_golden_bytes_are_pinned` (A8) and `test_a_golden_parses_to_the_values_the_file_literally_holds` (A8b). Without those two the round trip alone could not see a corrupted oracle.

Arms not run, stated: a mutant of `_flatten_compositions` (the flatten step) is covered only indirectly (A1/A2 drift; A17); `datamodel-code-generator` version mismatch refusal is not armed.

## Defeat-list walk (which rows apply, which instrument)

1. Delete the behaviour: A3, A4, A5, A10, A10b, A13, A14, A15, A9d.
2. Corrupt a supplied field: A8 (golden value), A10c (nullable table entry), A6 (envelope field order).
3. Substitute a valid sibling identifier: A9 (registry credit.approved -> CreditRejectedEvent), A9c (literal), A10d (nullable key `InvoiceView` -> `InvoiceLine`), and the 132-relabelling test.
4. Shadow in a comment or string: the alias guard is an AST scan of `ast.keyword` nodes, so `alias=` in a comment or a string is not counted; the dependency guard scans `ast.Import`/`ImportFrom`, so a `"import bson"` string is inert. Not separately armed with a planted comment.
5. Hide in a dead region: A18b (import under `if TYPE_CHECKING:` is still seen by `ast.walk`).
6. Raw or triple-quoted string: n/a (AST-based; a string cannot be an import or a keyword).
7. Drop an optional element: A10c, A11b (int64 bound removed), A12.
8. Compare a literal to a literal: avoided on purpose. The pinned digests compare a literal to the file bytes; the nullable-table literal test is paired with a spec-derived test; `test_a_golden_parses_to_the_values_the_file_literally_holds` reads values off the file, not off the serializer.
9. Satisfy the closer half and leave the premise stale: A2 (spec edited, generated code stale; the SHA-256 header makes even a no-op spec edit fail the drift check).
10. Build output or caches joining the population: `PACKAGE_ROOT.rglob("*.py")` and the generated-directory globs do not include `__pycache__` (only `*.py` sources); caches cleared between arm steps.
11. A form the instrument does not recognise: `importlib.import_module("bson")` would not be seen by the AST dependency guard (residual, written here); a datetime formatted through `strftime` elsewhere would not be seen either, but the byte-exact golden tests execute the real writer.
12. Serve the failure through a path the population never drives: `model_dump_json` is a second path to bytes that bypasses `format_instant`; it is documented and demonstrated (`test_pydantic_default_datetime_output_is_not_the_wire_format`) but not forbidden by a repo-wide guard (out of bounds).

## Gate results

- `./quality.sh` end to end: **exit 0**. ruff format `125 files already formatted`; ruff check `All checks passed!`; mypy `Success: no issues found in 94 source files`; import-linter `Contracts: 10 kept, 0 broken`; section 5 `contracts drift check: 3 generated files match a fresh generation`; pytest `549 passed`, overall coverage `99%` (`TOTAL 794 7 64 1`), `wire.py` 100% in the contracts-only run; 6b domain `TOTAL 267 0 54 0 100%`; Vitest 1 passed; web build green. (Counted this session: `pytest --ignore=packages/contracts` = 390 passed (shared_kernel 291, tests/architecture 92, other 7), contracts = 159, total 549. The shared_kernel review quoted 347 before its fixes; I did not reconcile the 43-test growth in that earlier count, it is not from this feature.)
- `./init.sh`: **exit 0** (5d: shared spec byte-identical to #8 and #7 across 6 files).
- Goldens: `cmp` identical for all 12 against `../order-to-cash-dotnet/tests/Contracts.UnitTests/GoldenEnvelopes/`.

## Inherited findings

#7 (`contracts_package`, history.md:458-): root-interface single-line `{}` regex bug: **avoided** (no text parsing of generated code; the script works on parsed YAML/JSON, and the generator emits Python classes). `title` beats the key for naming: **avoided** (titles stripped at extraction, and `--use-title-as-name` is not passed; `test_every_object_schema_has_a_model_...` proves class name = schema key for every object schema of both specs).
#8 (`history.md:305-345` and its review): default instant format would break every envelope assertion: **avoided** (`format_instant`, A3/A3b). Thirteen facts vs fourteen: **avoided** (count read from the spec, 14, asserted non-vacuous). Spec-side probe rather than code-side: **avoided** (A2/A2b edit `asyncapi.yaml` itself). A4 nothing guards `Contracts`' dependencies: **avoided** (`test_contracts_dependencies.py`). A1 envelope byte-exactness asserted token-wise: **avoided** (literal byte comparison before `"payload"`). A2 an `R<n>` cited in a doc comment with no validation: **avoided** (no R cited, none flipped). `stock.rejected.v1` has no golden: **recurred, disclosed** (unchanged; plus `order.saga_failed.v1`, which #8 also lacked; both listed in a test). Payload key order unasserted: **as ruled**.

## What I could not do, and surprises

- OpenAPI REST DTOs are generated (54 classes) but no test parses a real REST body: there is no oracle for them yet (feature 25 and siblings).
- No byte-parity evidence for nullable fields (no golden has one) and for `stock.rejected.v1` / `order.saga_failed.v1`.
- Surprises: (1) `--type-mappings`/`--type-overrides` do not apply under `--collapse-root-models`, so a global `Instant` type could not be injected; this is why instants are formatted in the writer, not per field. (2) `--collapse-root-models` leaves 5 dead root models. (3) strict mode makes Python-side construction require real `UUID`/`datetime`/enum objects; wire text must go through `from_wire_json`. (4) the `allOf` composition could not be generated as inheritance under `mypy --strict`; flattening is a documented transform. (5) `ruff` needs the repo config passed explicitly when formatting from stdin, otherwise default 88 columns would have been written into committed files.
- Not done on purpose: no `model_dump_json` ban (out of bounds), no test-matrix edit, no `feature_list.json` edit.

## Arming table detail (final run)



---

# Fix round 1 (after `progress/review_contracts_package.md`, REJECTED)

Same bounds as the brief; `feature_list.json` untouched. Edited: `packages/contracts/src/otc_contracts/wire.py`, tests under `packages/contracts/tests/`, `scripts/generate_contracts.py` (header wording), `quality.sh` (comments), root `pyproject.toml` `[tool.mypy] files` (+ `"scripts"`), regenerated `generated/*.py` (header line only).

## What changed, per defect

- **D1 (write side).** `WireModel` is `frozen=True` (assignment raises `frozen_instance`). `to_wire_json` re-validates (`type(model).model_validate(model.model_dump(mode="python"))`) before writing, so `model_copy(update=...)` and `model_construct` results holding a bool, float, string, out-of-int64 integer, bad UUID or unformatted instant are refused with the field named (`amount`, `aggregateId`, `occurredAt`). Tests (`test_write_side_and_json_paths.py`): `test_assignment_to_a_wire_model_is_refused`, `test_a_copy_updated_past_validation_is_refused_at_write_naming_the_field` (True, 89.34, 8934.0, "8934", 2**63), `test_a_copy_with_a_bad_uuid_or_an_unformatted_instant_is_refused_at_write`, `test_a_constructed_model_that_skipped_validation_is_refused_at_write` (True, 89.34, "8934"), `test_a_valid_instance_still_writes`.
- **D2 (one instant format on every JSON path).** `WireModel`'s wrap serializer now takes `SerializationInfo`; in JSON mode it replaces every datetime field with `format_instant(value)` (nested models apply their own). Python mode is unchanged (datetimes stay objects for the writer). Tests: `test_model_dump_json_equals_to_wire_json_on_every_golden` (12), `test_model_dump_mode_json_writes_the_wire_instant` (envelope field and a nested payload field, 442999 microseconds in), `test_an_openapi_model_writes_the_wire_instant_through_model_dump_json`, `test_a_fastapi_response_model_writes_the_wire_instant` (in-test `FastAPI` app, `response_model` on `openapi.StreamPing` and on the `OrderPlacedEvent` golden). FastAPI is a test-only import: `otc-contracts` still declares only `pydantic==2.13.5` (`test_the_package_declares_exactly_one_runtime_dependency_pinned`) and the source import allow-list test is green; `tests/architecture` (domain allowlist) 92 passed. FastAPI/`TestClient` were already installed through the gateway member and root dev group; no dependency was added. One warning appears in the run (`StarletteDeprecationWarning` about `httpx` in `starlette.testclient`), not a `DeprecationWarning` subclass under the repo filter; recorded, not filtered.
- **What `to_wire_json` still adds beyond the model's own serialisation** (now also in its docstring): (1) write-time re-validation (the model's own `model_dump_json` does not validate), (2) separators, `ensure_ascii=False`, `allow_nan=False` stated rather than inherited from a library default, (3) `TypeError` for a value with no wire form (a `Decimal` in an untyped payload). Instants, None handling and field order are now the model's own, and the two agree byte for byte on all 12 goldens.
- **D3.** `test_every_property_name_at_every_depth_is_exactly_a_generated_wire_name` (asyncapi, openapi): walks every `properties` mapping at any depth of each spec (headers excluded), compares the set both ways with every alias of every generated `WireModel` in that module, and pins the population last (`PROPERTY_NAME_POPULATION`: 105 asyncapi, 91 openapi, measured; the reviewer's 132 is a different count, I did not reconcile it). Set differences are asserted before the pin so a failure names the claim.
- **D4.** `strict_json_differences` moved to `packages/contracts/tests/strict_json.py` (loaded by path because pytest runs in importlib mode) and is used in all three round trips of `test_facts_without_a_golden.py`.
- **D5.** `scripts` added to `[tool.mypy] files`; `mypy --strict` over 97 files passes including `scripts/generate_contracts.py`; `quality.sh` section 3 title updated.
- **D6.** Headers now read `sha256-prefix16=` and the docstring and `quality.sh` say "first 16 hex digits (a 64-bit prefix) of the spec's SHA-256".
- **D7 fixed** (small): `_nullable_for` walks the MRO, so a subclass declared outside `generated/` keeps the explicit nulls: `test_a_subclass_declared_elsewhere_keeps_the_explicit_nulls`.

## Arming, fix round (harness `scratchpad/arm/arm2.py`; protocol as before: backup, plant, run the ONE named test, restore by `cp`, `cmp`, clear caches, green re-run)

| Arm (mutant) | Result and verbatim failure | Restored + cmp identical | Re-run |
|---|---|---|---|
| F1 D1 assignment: frozen=True removed (reviewer P2) | killed: `>       with pytest.raises(ValidationError, match="frozen_instance"): / E       Failed: DID NOT RAISE ValidationError` | yes | exit 0 |
| F2 D1 model_copy(update): write-side re-validation removed (reviewer P3) | killed: `>       with pytest.raises(ValidationError, match="amount"): / E       Failed: DID NOT RAISE ValidationError` | yes | exit 0 |
| F2b D1 uuid/instant copy: re-validation removed | killed: `>       with pytest.raises(ValidationError, match="aggregateId"): / E       Failed: DID NOT RAISE ValidationError` | yes | exit 0 |
| F3 D1 model_construct: re-validation removed (reviewer P4) | killed: `>       with pytest.raises(ValidationError, match="amount"): / E       Failed: DID NOT RAISE ValidationError` | yes | exit 0 |
| F3b D1 valid instance still writes: validation made to always fail | killed: `(3) a value with no wire form (a `Decimal` in an untyped payload) raises `TypeError`. / >       raise ValueError('x')` | yes | exit 0 |
| F4 D2 model_dump_json: json-mode datetime branch removed (reviewer P5) | killed: `E       assert '{"eventId":"...ter":491066}}' == '{"eventId":"...ter":491066}}' / E` | yes | exit 0 |
| F5 D2 model_dump(mode=json): branch removed (reviewer P6) | killed: `E       AssertionError: assert '2026-08-30T16:20:20.442999Z' == '2026-08-30T16:20:20.442Z' / E` | yes | exit 0 |
| F5b D2 openapi model: branch removed | killed: `E       assert '{"at":"2026-...:20.442999Z"}' == '{"at":"2026-...:20:20.442Z"}' / E` | yes | exit 0 |
| F6 D2 FastAPI response_model: branch removed (reviewer P7) | killed: `E       assert '{"at":"2026-...:20.442999Z"}' == '{"at":"2026-...:20:20.442Z"}' / E` | yes | exit 0 |
| F6b D2 sibling key: replace by field name instead of alias | killed: `E       assert '{"eventId":"...:20:20.979Z"}' == '{"eventId":"...ter":491066}}' / E` | yes | exit 0 |
| F7 D7 MRO lookup removed (own class only) | killed: `E       assert '{}' == '{"despatchRe...erence":null}' / E` | yes | exit 0 |
| F9 D4 no-golden stock.rejected: writer turns available 2 into 2.0 | killed: `E       AssertionError: assert ['$.payload.s...vs float 2.0'] == [] / E` | yes | exit 0 |
| F9b D4 no-golden saga_failed: writer turns attempts 3 into 3.0 | killed: `E       AssertionError: assert ['$.payload.a...vs float 3.0'] == [] / E` | yes | exit 0 |
| F9c D4 OLD assertion (Python ==) vs the same mutant (expected survivor) | SURVIVED (expected): `.                                                                        [100%] / 1 passed in 0.53s` | yes | exit 0 |
| F8 D3 inline `warehouseGLN` in `StockCheckRequestPayload.lines.items`, regenerated (reviewer A2) | killed: `AssertionError: spec names with no generated alias of that spelling / assert ['warehouseGLN'] == []` | yes (spec, 3 generated files) | exit 0 |

Survivor F9c is the point of D4: with the old `json.loads(...) == json.loads(...)` assertion the same writer mutant (`attempts` 3 to 3.0) passes; with `strict_json_differences` (F9b) it is killed.

## Corrections to earlier lines of this file (appended, not rewritten)

- **Ledger, Timestamp row:** the claim that the explicit formatter supplies the idiom was true for `to_wire_json` only. Until this round `model_dump_json`, `model_dump(mode="json")` and FastAPI `response_model` wrote `.442000Z`. Now supplied by `WireModel`'s JSON-mode serializer, guarded by `test_model_dump_json_equals_to_wire_json_on_every_golden`, `test_model_dump_mode_json_writes_the_wire_instant`, `test_a_fastapi_response_model_writes_the_wire_instant`, plus the earlier `test_instant_is_written_as_yyyy_mm_ddthh_mm_ss_mmmz` and `test_envelope_is_byte_exact_against_the_golden`.
- **Ledger, Integer strictness row:** supplied at validation only, and the named guards drove only the parse path. Now: parse side as before; **write side** `frozen=True` plus write-time re-validation, guarded by `test_assignment_to_a_wire_model_is_refused`, `test_a_copy_updated_past_validation_is_refused_at_write_naming_the_field`, `test_a_constructed_model_that_skipped_validation_is_refused_at_write`.
- **Inherited findings, #8 "check the serialiser's default instant format":** I wrote **avoided**; it **recurred on every path except `to_wire_json`** and is avoided on all paths only as of this round. In the Defeat list, row 12 was reported as "documented, out of bounds"; it was in bounds and is closed by D2.
- **Line 39 claim** ("proves every spec property name equals the generated field's alias, for both specs"): was a sample (named schemas); now the population (every property site at every depth) by the D3 test.

## Gate

`./quality.sh` end to end, once, after all edits: **exit 0**. ruff format `129 files already formatted`; ruff check `All checks passed!`; mypy `Success: no issues found in 97 source files`; import-linter `Contracts: 10 kept, 0 broken`; drift check `3 generated files match a fresh generation`; pytest `579 passed, 1 warning` (contracts 189), overall coverage 99% (`TOTAL 809 7 72 1`); 6b domain `TOTAL 267 0 54 0 100%`; Vitest 1 passed; web build green. `./init.sh` exit 0.

## Fix round 1, addendum: FastAPI test moved off `starlette.testclient`

The leader added `error::starlette.exceptions.StarletteDeprecationWarning` to the pytest `filterwarnings`; `fastapi.testclient` emits it on import. `test_a_fastapi_response_model_writes_the_wire_instant` in `packages/contracts/tests/test_write_side_and_json_paths.py` is now async and uses `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")`; the assertions are unchanged (same `.mmmZ` claim on `openapi.StreamPing` and on the `OrderPlacedEvent` golden). The earlier "one warning" note is resolved (no warning in the run).

Re-arm, D2 FastAPI row (json-mode instant formatter reverted, `if info.mode_is_json():` -> `if False:`), re-run after the rewrite: killed, `assert '{"at":"2026-...:20.442999Z"}' == '{"at":"2026-...:20:20.442Z"}'`; restored from backup, `cmp` identical: yes; re-run green exit 0.

Result: `./quality.sh` end to end **exit 0**: ruff check clean, mypy `Success: no issues found in 97 source files`, `579 passed` (no warnings line), coverage 99% (`TOTAL 809 7 72 1`), domain `TOTAL 267 0 54 0 100%`, web green.
