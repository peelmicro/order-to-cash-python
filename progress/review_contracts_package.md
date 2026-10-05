# Review: contracts_package (id 8, phase 5), full process (wire contract), `sdd: false`

**Verdict: REJECTED** (round 1). 2 major, 2 minor, 3 nits. The generator, the drift check, the golden parity tests and the payload comparer are solid: every drift probe, every writer-side payload corruption and every sibling substitution I planted was killed. Both majors are the same defect class: **the one serializer configuration is not the only way a generated model reaches bytes**, and the guards exercise only the paths the implementer chose (`from_wire_json` in, `to_wire_json` out of a freshly validated model).

Reviewer: `reviewer` agent (Opus), 2026-10-05, 06:44 to 06:54. I enforced the "JSON wire shape", "Money", "ported-idiom ledger", arming-protocol, mutation-family and defeat-list rules as grepped from `CLAUDE.md` on disk (lines 62, 83, 92 and the Testing conventions section), not from the injected copy.

## What I ran (and what I did not)

- `uv run pytest packages/contracts`: 159 passed. The whole backend `uv run pytest`: 549 passed (it runs in 23 s and needs no containers, so I ran it once after every restore).
- `scripts/generate_contracts.py --check`: exit 0, "3 generated files match a fresh generation". `ruff format --check`: 126 files, clean. The extra file over the implementer's 125 is the report markdown, which ruff 0.16 includes. `ruff check`: clean. `mypy`: 94 files, clean. `lint-imports`: 10 kept, 0 broken. `uv lock --check`: consistent.
- `./init.sh`: exit 0. 5d reports the shared spec byte-identical to #8 and #7. I also ran `cmp` on `asyncapi.yaml` and `openapi.yaml` against #8, #7 and `git show HEAD:` before the probes and again after the last one.
- **Not re-run:** `./quality.sh` end to end (sections 6b and 7, the web gates). This feature touches no web code and no domain code, and the verdict is a rejection. Sections 1 to 6 were run separately, as listed above.
- 30 independent arming runs, listed below. I did not reuse the implementer's harness. Backups are in `scratchpad/rv/bak/`. Every restore was a `cp`, then a `cmp`, then `__pycache__` cleared, then a green re-run.

## Defects

### D1 (MAJOR): the writer trusts the model. Assignment, `model_copy(update=)` and `model_construct` put `true`, `89.34` and `"8934"` into money fields on the wire. The ledger's integer-strictness guard only drives the parse path.

- **Where:** `packages/contracts/src/otc_contracts/wire.py:47-56` (the `ConfigDict` sets `strict=True` but neither `frozen` nor `validate_assignment`) and `wire.py:83-91` (`to_wire_json` serialises whatever the instance holds and never validates).
- **Reproduction** (each run in this session against the committed code):
  - Construction is correct: `Money(amount=True | 8934.0 | "8934" | 8934.5, currency="EUR")` is refused with `int_type` in all 4 cases.
  - `m = Money(amount=8934, currency="EUR"); m.amount = True; to_wire_json(m)` gives `{"amount":true,"currency":"EUR"}` with **no warning at all**.
  - `m.amount = 8934.0` gives `{"amount":8934.0,...}`. `m.amount = "8934"` gives `{"amount":"8934",...}`. Pydantic emits only a `UserWarning`, which is not an error outside pytest.
  - `Money(amount=8934, currency="EUR").model_copy(update={"amount": 89.34})` gives `{"amount":89.34,"currency":"EUR"}`. That is a major-unit float on the wire.
  - `Money.model_construct(amount=True, currency="EUR")` gives `{"amount":true,...}`.
  - The same path carries a non-UUID string: a `model_copy(update={"aggregate_id": "not-a-uuid"})` is written verbatim. It also carries an unformatted instant string assigned to `occurred_at`, and any integer past the int64 bound.
- **Why it matters:** M1 and the `CLAUDE.md` money row say never `float`, and overflow is guarded at the write boundary. `to_wire_json` is the write boundary, and it guards nothing. The type checker does not close the gap. mypy accepts `bool` for `int`, and `model_copy(update=...)` takes a `dict[str, Any]` (the "Any leaking" question that `CLAUDE.md` tells every port to ask). The ledger row "Integer strictness: #8 `long` … in #9 `strict=True`" claims a property that #8 supplied through the type system and immutable records, for every path. #9 supplies it only at validation time. The row's named guards (`test_a_money_or_quantity_integer_field_refuses_a_string_float_or_bool`, `test_money_beyond_the_int64_…`) run only `from_wire_json`. `CLAUDE.md` asks: "does the named guard execute the code the row is about?" It does not.
- **Required change:** make the writer refuse an invalid instance, and make instances immutable.
  - Add `frozen=True` to `WireModel` (`CLAUDE.md`: value objects are frozen).
  - Make `to_wire_json` re-validate before writing. I measured that `type(model).model_validate(model.model_dump(mode="python"))` passes on a parsed golden and refuses both the `bool` and the bad UUID above: `int_type` and `is_instance_of`. The implementer may choose another mechanism if it refuses all three bypasses.
  - Guards: one test per bypass (assignment refused; `model_copy(update=…)` with `True`, `89.34` and `"8934"` refused at write; `model_construct` refused at write), each armed by deleting the new check.
  - Correct the ledger row so it names the write-side guard.

### D2 (MAJOR): `format_instant` is not the only path to the wire. `model_dump_json()`, `model_dump(mode="json")` and FastAPI's response serialisation of the generated models all write `.442000Z`, so the package ships two serializer configurations that disagree.

- **Where:** `wire.py:59-66` (the wrap serializer handles `None` only) and `wire.py:17` (the docstring that acknowledges it). Reported as defeat row 12 in `progress/impl_contracts_package.md:156`, and left "out of bounds".
- **Reproduction:**
  - For the `order_placed_v1.json` golden, `parse_fact(golden).model_dump_json()` writes `occurredAt":"2026-08-30T16:20:20.442000Z`, and `model_dump(mode="json")["occurredAt"]` is `2026-08-30T16:20:20.442000Z`.
  - FastAPI 0.142.2 (installed) with `response_model=openapi.StreamPing` returns `{"at":"2026-08-30T16:20:20.442000Z"}` from a `TestClient` call. The openapi models are generated precisely to be the REST bodies. On the path FastAPI will use, they violate the `.mmmZ` rule.
- **Why it matters:** `CLAUDE.md:83` asks for "`occurredAt` as `YYYY-MM-DDTHH:MM:SS.mmmZ` from an explicit formatter, one serializer configuration". Acceptance item 2 repeats it. #8's closing note for this feature says: "Check your serialiser's default instant format before writing a single payload type … it silently breaks every envelope assertion if missed." #8 applied its one configuration, instant converter included, to REST as well (`../order-to-cash-dotnet/src/Gateway/GatewayHost.cs:86-96`). In #9 the idiomatic Pydantic and FastAPI path is the wrong one, and nothing fails when a later feature takes it. The inherited #8 finding has **recurred** on every path except `to_wire_json`.
- **Required change, within this feature's bounds (`wire.py`):** make the model's own JSON-mode serialisation write `.mmmZ`.
  - I prototyped it in the scratchpad, not in the repo. A `@model_serializer(mode="wrap")` that takes `info: SerializationInfo` and, when `info.mode_is_json()`, replaces each `datetime`-valued field with `format_instant(value)`. With that change `model_dump_json()`, `model_dump(mode="json")` and a FastAPI `response_model` response all wrote `2026-08-30T16:20:20.442Z` for a `442999` µs input.
  - With that in place, `to_wire_json` and `model_dump_json` agree. Add one test asserting that agreement on all 12 goldens, and one FastAPI-free assertion on `model_dump(mode="json")`. Arm both by removing the json-mode branch.
- **Alternative disposition (leader's call, not my recommendation):** accept with evidence and file a numbered backlog entry attached to the gateway feature that first returns a generated model. The entry must name a guard that fails on `.442000Z` in a REST body. A sentence in this review does not discharge it.

### D3 (MINOR): the alias-agreement guard covers named schemas only. An acronym inside an inline object schema reaches the wire mis-cased with 159 tests green.

- **Where:** `packages/contracts/tests/test_spec_alignment.py:73-79` (`object_schema_names`) and `:126-146`. Its population is the top-level `components.schemas` entries. It misses the inline object schemas (`…/lines/items` in 5 asyncapi RPC payloads; `ReplenishStockRequest.lines.items`, `Invoice.lines.items`, `ValidationProblem…errors.items` and `StockUnavailableProblem…shortages.items` in openapi; `HealthResponse.checks`). I enumerated them with a YAML walk: 22 inline sites in asyncapi, 14 of which are the Event `allOf` parts the guard does resolve, and 7 in openapi.
- **Reproduction:**
  - I added `warehouseGLN: {type: string}` to `StockCheckRequestPayload.lines.items` in `asyncapi.yaml`, then ran the generator.
  - The generated `Line1.warehouse_gln` has the alias `warehouseGln`. `pytest packages/contracts` gave **159 passed**. Restored with `cp` and `cmp`; drift check green.
  - The same plant on a named schema (`buyerGLN`, `schema` → `schema_`) **is** caught: `…StockReleasedPayload: ['buyerGln', 'address2Line', 'schema_', …] != ['buyerGLN', 'address2Line', 'schema', …]`.
- **Why it matters:** `progress/impl_contracts_package.md:39` claims the test "proves every spec property name equals the generated field's alias, for both specs". The claim is about a population; the test checks a sample of it. Today all 132 spec property names do have an exact generated alias: I cross-checked the set both ways, and nothing is missing either way. So this is a latent gap, triggered by a future SA that adds an acronym or a keyword inside an inline object.
- **Required change:** extend the guard to every property site. The cheapest version is a two-way set check. Collect every property name at any depth of both specs, minus the three excluded header schemas, and compare it with every alias of every generated `WireModel`. Pin the population size (132) as non-vacuity. Arm it with the `warehouseGLN` mutant above.

### D4 (MINOR): the two no-golden facts' round trips use Python `==`, the comparison this feature proved blind to `int` → `float` → `bool`

- **Where:** `packages/contracts/tests/test_facts_without_a_golden.py:41,50,59`, `assert json.loads(written) == json.loads(...)`.
- **Why it matters:** `stock.rejected.v1` (`Shortage.requested`/`available`) and `order.saga_failed.v1` (`attempts`) have no golden. These three assertions are their only round-trip check, and `{"available": 2.0} == {"available": 2}` is `True`. The writer-wide mutants I ran (D1's float and bool forms) are caught by the golden tests. A defect specific to these two payloads would not be. `test_python_equality_alone_cannot_see_the_differences_the_comparer_sees` documents exactly this.
- **Required change:** use `strict_json_differences`, moved to a shared test helper or a `conftest.py`, in all three places.

### D5 (NIT): `scripts/` is outside mypy's `files`

`pyproject.toml` `[tool.mypy] files = ["packages", "services", "tests"]`, so the gate does not type-check `scripts/generate_contracts.py`. It passes `mypy --strict` when run by hand (`Success: no issues found in 1 source file`). Add `"scripts"`. The leader may edit root tool sections.

### D6 (NIT): the header calls a 64-bit prefix "the SHA-256"

`generate_contracts.py:263` writes `_sha256(...)[:16]`. The module docstring (`:20-21`) and `quality.sh` section 5 say "carries the SHA-256 of each spec". The S2 and S3 probes show the prefix works. Make the wording accurate, or write the full digest.

### D7 (NIT, advisory): the nullable lookup is keyed by the defining module's last component and the class name (`wire.py:62`)

A subclass of a generated model declared anywhere else, for example `class GatewayInvoice(openapi.Invoice)`, silently loses its explicit `null`s. The key-sensitivity mutant (M10) shows how tight the key is. Advisory only: either refuse subclassing outside `generated/` (`__init_subclass__`), or look the key up along the MRO. No change required for this round.

### Not defects, recorded

- **Unknown inbound keys are ignored** (`extra` defaults to `ignore`). An `"extra":1` envelope key parses and disappears on re-serialisation. This is consistent with the spec: `asyncapi.yaml:44-48` says additive optional fields are non-breaking, "which is why payload schemas do not close `additionalProperties`". A future relay feature must not re-serialise to forward.
- **Lax inbound instant forms** (`2026-08-30 16:20:20Z`, no fraction, a `+02:00` offset, 7 fractional digits) parse and are normalised to `.mmmZ`. An integer epoch is refused. Recorded by the implementer; I agree.

## Leader rulings, reviewed

1. **None as `null` only for the 9 spec-nullable fields: endorsed.** The spec's own words decide it: `asyncapi.yaml:3032-3036` gives `InvoiceView.paidAt` as `oneOf: [Instant, {type: 'null'}]` and says it is "null while `issued` (invariant B9)". #7 writes the explicit null (`list-invoices.query.ts:38`, `paidAt: item.paidAt ?? null`, verified). #8's `WhenWritingNull` (`JsonWire.cs:40`, verified) also conforms, since every one of the 9 is optional. No Kafka fact carries one, so no golden can arbitrate. `test_the_nullable_table_is_exactly_what_the_spec_declares_nullable` computes the table from the spec independently. The generator's `_is_nullable` is broader (`type: [..,'null']`, `nullable`, `anyOf`), so any widening of the spec fails that test rather than passing silently. Count: 1 asyncapi field plus 8 openapi fields = 9.
2. **`pyyaml==6.0.3` and `types-pyyaml==6.0.12.20260906` in the root dev group: endorsed.** It is root configuration, not a member's dependencies (`CLAUDE.md`, leader section). The stubs are needed because `test_spec_alignment.py` imports `yaml` under `mypy --strict`. `uv lock --check` is consistent, and `otc-contracts` still declares only `pydantic==2.13.5`, which `test_the_package_declares_exactly_one_runtime_dependency_pinned` guards.

## Answers to the brief's questions

| Question | Answer | Evidence |
|---|---|---|
| Does the drift check detect drift? | **Yes**, for every probe | D1–D7 and S1–S3 below. Hand edits to all three generated modules, a deleted module, a generator-version pin change, two flag changes, a property added to the spec, and no-op edits to each spec are all detected and name the file. |
| Is the envelope byte-exact claim tested on bytes the serializer produced? | **Yes** | `test_envelope_is_byte_exact_against_the_golden` compares `to_wire_json(parse_fact(golden))` up to `,"payload":` with the golden's bytes. M3 (UUIDs upper-cased by the writer) killed it: `At index 19 diff: b'B' != b'b'`. |
| Is the payload comparer type-strict at every depth? | **Yes** | My direct probes: `[{"a":{"q":6}}]` vs `6.0` gives `$.l[0].a.q: int 6 vs float 6.0`; `{"b":1}` vs `true` inside an array of objects gives `$.l[1].b: int 1 vs bool True`; `0` vs `false` and `"8934"` vs `8934` are flagged too; key order inside a nested object is ignored. End to end on writer bytes: M1 and M2 were killed. |
| Is `occurredAt` from the formatter the only path to the wire? | **No** (D2) | Non-UTC aware input is converted to UTC; naive input is refused by `format_instant` and by `AwareDatetime` on parse; sub-millisecond precision is truncated (M9 killed). But `model_dump_json`, `model_dump(mode="json")` and FastAPI write `.442000Z`. |
| Is there exactly one alias mechanism? | **Yes, but the agreement guard is sampled** (D3) | No `Field(alias=…)` is generated (`--no-alias`, AST guard). Acronym, digit and keyword names disagree with `to_camel` (`buyerGLN`→`buyerGln`, `schema`→`schema_`; `address2Line` survives). That is caught on named schemas and missed on inline objects. |
| Integer strictness on parse? On construction? | **Parse: yes. Construction: yes. Assignment, copy and construct: no** (D1) | M8 (a per-call `strict=False`) was killed. |
| Does the completeness test read the spec at test time? | **Yes** | S1: a property added to `asyncapi.yaml` with no regeneration failed two alignment tests. |
| Does the registry map each `eventType` correctly, and is a sibling caught? | **Yes** | M6 (`order.completed` swapped with `order.confirmed`) and M7 (`stock.rejected.v1` → `StockReleasedEvent`, a fact with no golden) were both killed by the `Literal`. |
| `ensure_ascii` against a real golden? | **Yes** | `grep -l "[^ -~]"` finds exactly one golden, `order_cancelled_v1.json` (`"summary":"stock released — reason: credit_rejected"`). `test_the_non_ascii_golden_is_written_raw_not_escaped` reads it. |
| Goldens identical to #8's? | **Yes** | `cmp` passes on all 12 against `../order-to-cash-dotnet/tests/Contracts.UnitTests/GoldenEnvelopes/` (12 files there, 12 here). |

## Independent arming table (this session; every row restored with `cp`, checked with `cmp`, caches cleared, and green afterwards)

| # | Claim | Mutant | Instrument | Verbatim failure (first line) | Result |
|---|---|---|---|---|---|
| D1 | drift: a hand edit of `asyncapi.py` | `max_length=30` → `31` (16 sites) | `--check` | `DRIFT: …/generated/asyncapi.py differs from a fresh generation` (exit 1) | killed |
| D2 | drift: a hand edit of `openapi.py` | first `: str` → `: str \| None = None` | `--check` | `DRIFT: …/generated/openapi.py differs …` | killed |
| D3 | drift: a hand edit of `nullable.py` | `asyncapi.InvoiceView` entry dropped | `--check` | `DRIFT: …/generated/nullable.py differs …` | killed |
| D4 | drift: a deleted file | `rm generated/openapi.py` | `--check` | `DRIFT: …/generated/openapi.py differs …` | killed |
| D5 | generator version | `GENERATOR_VERSION` → `0.84.0` | `--check` | `datamodel-code-generator 0.83.0 installed, 0.84.0 pinned` (exit 1) | killed |
| D6 | generator flags | `--use-annotated` removed | `--check` | `DRIFT: …asyncapi.py …` + `DRIFT: …openapi.py …` | killed |
| D7 | generator flags | `--no-alias` removed | `--check` | `DRIFT: …asyncapi.py …` + `DRIFT: …openapi.py …` | killed |
| S1 | spec edit, no regeneration | `reviewerProbe: string` added to `StockReleasedPayload` | `--check`; `test_spec_alignment.py` | `DRIFT: …asyncapi.py` + `nullable.py`; `asyncapi.StockReleasedPayload: [...] != ['reviewerProbe', …]` (2 failed) | killed |
| S2 | no-op spec edit (asyncapi) | trailing `# reviewer probe` comment | `--check` | `DRIFT: …asyncapi.py …` + `nullable.py` | killed |
| S3 | no-op spec edit (openapi) | trailing comment | `--check` | `DRIFT: …openapi.py …` + `nullable.py` | killed |
| A1 | alias agreement, named schema | `buyerGLN`, `address2Line`, `schema` added and regenerated | alignment test | `… ['buyerGln', 'address2Line', 'schema_', …] != ['buyerGLN', 'address2Line', 'schema', …]` | killed |
| A2 | alias agreement, inline object | `warehouseGLN` in `StockCheckRequestPayload.lines.items`, regenerated | `pytest packages/contracts` | `159 passed` | **SURVIVED (D3)** |
| M1 | payload type on writer bytes | the writer turns every `int` into a `float` | `test_payload_is_semantically_equal_to_the_golden` | `'$.payload.availableCreditAfter: int 491066 vs float 491066.0'` | killed |
| M2 | payload type on writer bytes | the writer turns `0` into `false` | same | `'$.payload.discount: int 0 vs bool False'` | killed |
| M3 | envelope bytes from the serializer | UUID writer `.upper()` | `test_envelope_is_byte_exact_against_the_golden` | `At index 19 diff: b'B' != b'b'` | killed |
| M4 | payload field deleted on the wire | the writer drops `reason` | payload test | `'$.payload.reason: missing from the actual document'` | killed |
| M5 | None: a not-required field emitted as null | omission rule replaced by `if True` | `pytest packages/contracts` | `assert 'retailerCode' not in '{"eventId":…"retailerCode":null,…'` | killed |
| M6 | registry sibling | `order.confirmed` swapped with `order.completed` | `pytest packages/contracts` | `ValidationError: 2 validation errors for OrderConfirmedEvent … Input should be 'order.confirmed.v1'` | killed |
| M7 | registry sibling, no-golden fact | `stock.rejected.v1` → `StockReleasedEvent` | `pytest packages/contracts` | `ValidationError: 3 validation errors for StockReleasedEvent` | killed |
| M8 | strict parse | `from_wire_json(..., strict=False)` per call | `pytest packages/contracts` | `Failed: DID NOT RAISE ValidationError` | killed |
| M9 | UTC conversion | `utc = value` (no `astimezone`) | `pytest packages/contracts` | `assert '2026-08-30T18:20:20.442Z' == '2026-08-30T16:20:20.442Z'` | killed |
| M10 | nullable key (sibling identifier) | key = class name only | `pytest packages/contracts` | `assert '"paidAt":null' in '{"invoiceId":…'` | killed |
| P1 | construction strictness | `Money(amount=True/8934.0/"8934"/8934.5)` | direct | `int_type` ×4 | holds |
| P2 | write-side strictness | `m.amount = True` / `8934.0` / `"8934"` | direct | `{"amount":true…}`, `{"amount":8934.0…}`, `{"amount":"8934"…}` | **SURVIVED (D1)** |
| P3 | write-side strictness | `model_copy(update={"amount": 89.34})` | direct | `{"amount":89.34,"currency":"EUR"}` | **SURVIVED (D1)** |
| P4 | write-side strictness | `model_construct(amount=True)` | direct | `{"amount":true,"currency":"EUR"}` | **SURVIVED (D1)** |
| P5 | one instant path | `model_dump_json()` on a golden | direct | `occurredAt":"2026-08-30T16:20:20.442000Z` | **SURVIVED (D2)** |
| P6 | one instant path | `model_dump(mode="json")` | direct | `2026-08-30T16:20:20.442000Z` | **SURVIVED (D2)** |
| P7 | one instant path | FastAPI `response_model=openapi.StreamPing` | `TestClient` | `{"at":"2026-08-30T16:20:20.442000Z"}` | **SURVIVED (D2)** |
| P8 | comparer, nested depth | int vs float / bool inside an array of objects | direct | flagged with path, see the answers table | holds |

Restore evidence: after the last arm, `cmp` against the backups passed for `generated/{asyncapi,openapi,nullable}.py`, `scripts/generate_contracts.py`, `specs/shared/{asyncapi,openapi}.yaml` and `otc_contracts/{wire,facts}.py`. Both YAML files are also `cmp`-identical to #8 and #7, and `init.sh` 5d is OK. Then `--check` green, and 549 passed.

## Defeat-list rows that apply

1. **Delete the behaviour:** D4 (a deleted file), M4 (a deleted payload field), M5 (the omission deleted). All killed.
2. **Corrupt a supplied field:** M1 and M2 (types on writer bytes), M3 (envelope bytes). All killed. On the model side the corruption survives, because the writer does not validate: P2–P4 (D1).
3. **Substitute a sibling identifier:** M6 and M7 (registry), M10 (nullable key). All killed.
4. **Shadow in a comment or string:** the drift check compares full text, so a comment-only edit fails (the implementer's A1 and my S2/S3 header probes). The alias AST scan correctly ignores comments.
5. **Dead region:** the implementer's A18b (`if TYPE_CHECKING:` import) is accepted. Not re-run.
6. **Raw or triple-quoted string:** not applicable. The guards are AST-based or compare bytes.
7. **Drop an optional element:** D3 (the nullable entry), D6 (a generator flag). Killed.
8. **Literal compared to a literal:** none found among the guards. `test_python_equality_alone_…` is an evidence test, not a guard.
9. **Closer half satisfied, premise stale:** S2 and S3 (a spec edited with output unchanged still fails, via the header digest). Killed.
10. **Build output or caches in the population:** the generated-file population is a literal set of 3 plus `__init__.py`. Caches were cleared at every arm.
11. **A form the instrument doesn't recognise:** A2, an inline object schema outside the alignment test's population. **Survived (D3).**
12. **A path the population never drives:** P2–P4 (assignment, copy, construct) and P5–P7 (Pydantic and FastAPI JSON). **Survived (D1, D2).**

## Ledger check (claims, not existence)

| Row | Verdict |
|---|---|
| Generator | Holds. #7's citation `generate-asyncapi.mts:36-46` was verified. "#8 hand-wrote" was verified at #8 `history.md:317`. |
| Drift check | Holds. #7's `check.mts:27-56` was verified. All 10 drift probes were killed. |
| camelCase alias | Mechanism holds. The guard is sampled (D3). #8's `JsonWire.cs:38` was verified. |
| Compact / raw non-ASCII | Hold for `to_wire_json`. #8's `JsonWire.cs:41-42` was verified. |
| Timestamp | **Overstated (D2).** It is supplied for `to_wire_json` only. #8's `InstantJsonConverter.cs:25,45` was verified, and #8 also applied it to REST (`GatewayHost.cs:86-96`). |
| None handling | Holds. The ruling is endorsed. |
| Integer strictness | **Overstated (D1).** #8 supplied it with `long` on immutable records, on every path. #9 supplies it at validation only, and the named guards drive only the parse path. |
| Payload equivalence | Holds (M1, M2, P8). It is not applied in `test_facts_without_a_golden.py` (D4). |

## Inherited findings, as I assess them

- #7 single-line `{}` root-interface regex bug: **avoided**. The script parses YAML and JSON. Its only text filtering, two generator header lines, is behind the drift check.
- #7 `title` beats the key: **avoided**. Titles are stripped, and class name = schema key is proven for named schemas.
- #8 "check the serialiser's default instant format": **avoided on `to_wire_json`, recurred on `model_dump_json`, `model_dump(mode="json")` and FastAPI (D2)**.
- #8 13 vs 14 facts: **avoided**. 14 are read from the spec, with a non-vacuity check.
- #8 a spec-side probe, not a code-side one: **avoided**. S1 confirmed it independently.
- #8 A1 (token-wise byte-exactness): **avoided**. It compares serializer bytes (M3).
- #8 A2 (an `R<n>` cited with no validation): **avoided**. `grep -rnE "\bR[0-9]{1,2}\b" packages/contracts scripts/generate_contracts.py` returns no hits (exit 1), and `test-matrix.md`'s diff touches only R1–R4 and the summary (shared_kernel's).
- #8 A4 (no dependency guard on Contracts): **avoided**.
- `stock.rejected.v1` has no golden: **recurred, disclosed** (inherent; `order.saga_failed.v1` too). Their shape tests are weakened by D4.

## R<n> → test mapping

No `R<n>` is claimed (`sdd: false`). R11 stays with `outbox_and_idempotency`, as in #8, and is untouched. The five acceptance items map as follows:

1. Generated with a drift check: `test_generation_drift.py` (6 tests) and `quality.sh` section 5. Verified by D1–D7 and S1–S3.
2. One serializer configuration: `test_wire_serializer.py`. **Not met** on the D1 and D2 paths.
3. Envelope byte-exact: `test_envelope_is_byte_exact_against_the_golden` (12). Verified by M3.
4. Payload semantically equal: `test_payload_is_semantically_equal_to_the_golden` (12). Verified by M1, M2, M4 and P8.
5. Round trip: `test_round_trip_every_golden_parses_into_its_model_and_reserialises_equal` (12) plus the 132 relabellings. Verified by M6 and M7.

## CHECKPOINTS.md walk

**C1 (harness):** `[x]` files exist · `[x]` progress files exist · `[x]` agents present (unchanged by this feature) · `[x]` models declared (unchanged) · `[x]` `./init.sh` exit 0.

**C2 (state):** `[x]` no feature `in_progress` before this verdict; after it, exactly one (feature 8) · `[x]` valid statuses (init.sh) · `[x]` done features have passing tests (549 passed) · `[x]` `current.md` describes this session · `[x]` none blocked.

**C3 (architecture):** `[x]` no framework in `domain`/`shared_kernel` (`lint-imports`: 10 kept); the domain allowlist still forbids `otc_contracts` · `[x]` no cross-service access or imports · `[x]` shared runtime only in the three allowed packages · `[x]` no `domain` imports `otc_cqrs` · `[x]` kernel and cqrs `dependencies = []` · `[ ]` **no float on the money wire: D1** (the domain is clean; the wire writer is not) · `[x]` Kafka/NATS: no interaction is implemented here · `[x]` no debug logging or context-free TODO.

**C4 (verification):** `[x]` sections 1–6 green as run (I did not re-run section 7 web, see above) · `[x]` domain tests pure (contracts tests are not domain tests and use no framework beyond Pydantic) · `[x]` no integration tests in scope · `[x]` coverage gate exercised by the implementer's run; not re-measured by me · `[x]` no Jest, Karma or Jasmine.

**C5 (clean close):** `[x]` no stray files (my probes used the scratchpad; every restore was checked with `cmp`) · `[ ]` history entry: none, by rule, on a rejection · `[x]` `feature_list.json` set to `in_progress` · `[ ]` human told what was done: the leader's step · `[x]` no commit.

**C6:** not applicable (`sdd: false`).

**C7:** `[x]` `specs/shared/` byte-identical to #8 and #7 (5d plus my own `cmp`) · `[x]` no deviation needing an SA (nothing here is rooted in `specs/shared/`; D1–D4 are this package's) · `[x]` no `R<n>` claimed · `[ ]` inherited findings: #8's instant-format note recurred off the main path (D2), which must be recorded when the feature closes · other boxes not applicable yet.

## What must change before re-review

1. **D1:** `frozen=True` on `WireModel`, and write-side validation in `to_wire_json`. Add tests for assignment, `model_copy(update=)` (`True`, `89.34`, `"8934"`) and `model_construct`, each armed by removing the check. Correct the integer-strictness ledger row.
2. **D2:** JSON-mode instant formatting inside `WireModel`'s own serializer. Add a test that `model_dump_json()` equals `to_wire_json()` on all 12 goldens, and a `model_dump(mode="json")` assertion. Arm both. Correct the timestamp ledger row. (Or the leader takes the alternative disposition and files the backlog entry against the gateway feature.)
3. **D3:** an alias-agreement guard over every property site of both specs, with a population pin (132), armed with the `warehouseGLN` inline mutant.
4. **D4:** `strict_json_differences` in `test_facts_without_a_golden.py:41,50,59`.
5. D5 and D6 (nits): leader's discretion. D7 is advisory only.

On re-review I will re-run P2–P7, A2 and the D4 file's round trips against the new code, plus a fresh sample of D1–M10 to confirm that no arm went stale.

## Round 2 (2026-10-05)

**Verdict: APPROVED.** All four round-1 defects (D1–D4) are fixed, and each of my round-1 mutants is now killed by a named test. D5, D6 and D7 are fixed too. Probing the new instruments found 2 minor residuals and 2 nits, all in premises the fix round introduced. Each is **ACCEPTED, NOT FIXED** with evidence, a re-open trigger and a proposed backlog entry, below. None is on a path the system uses today. Reviewer: `reviewer` agent (Opus), round 2 from 07:07 to 07:13 by my `date`.

### What I ran

- `./quality.sh` **end to end, once, after every arm had been restored**: exit 0, `quality.sh: all gates passed`. Per section:

| Section | Result |
|---|---|
| ruff format | `129 files already formatted` |
| ruff check | `All checks passed!` |
| mypy | `Success: no issues found in 97 source files` (section title now includes `scripts`) |
| import-linter | `Contracts: 10 kept, 0 broken.` |
| 5. drift check | `3 generated files match a fresh generation` |
| 6. pytest + coverage | `579 passed in 15.21s`, no warnings line; overall `TOTAL 809 7 72 1 99%` |
| 6b. domain coverage | `TOTAL 267 0 54 0 100%` |
| 7. web | Vitest `1 passed`; both builds `✓ built` |

- `pytest packages/contracts`: 189 passed. `./init.sh`: exit 0.
- `asyncapi.yaml` and `openapi.yaml` were `cmp`-identical to #8, #7 and `git show HEAD:` after my last arm.
- 15 arming runs and 18 direct probes, with my own harness (backups in `scratchpad/rv2/bak/`). Every restore was `cp`, then `cmp`, then `__pycache__` cleared. After the last arm, all 9 touched files were `cmp`-identical to the backups and the drift check was green.
- **The leader's warning filter is armed:** a scratch test importing `fastapi.testclient`, run under the repository's `pyproject.toml`, failed collection with `E   starlette.exceptions.StarletteDeprecationWarning: Using \`httpx\` with \`starlette.testclient\` is deprecated` (1 error). The FastAPI test now uses `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))`, and the run shows no warnings line.

### Round-1 mutants, re-run against the fixed code

| Round-1 id | Probe | Now | Killed by (named test) and verbatim failure when the fix is reverted |
|---|---|---|---|
| P2 (D1) | `m.amount = True` | refused, `frozen_instance` | `test_assignment_to_a_wire_model_is_refused`. With `frozen=True` removed: `Failed: DID NOT RAISE ValidationError` |
| P3 (D1) | `model_copy(update={"amount": 89.34})` → `to_wire_json` | refused, `1 validation error for Money` | `test_a_copy_updated_past_validation_is_refused_at_write_naming_the_field` (5 cases) and `…bad_uuid_or_an_unformatted_instant…`. With the re-validation removed: `Failed: DID NOT RAISE ValidationError` ×8 |
| P4 (D1) | `model_construct(amount=True)` → `to_wire_json` | refused | `test_a_constructed_model_that_skipped_validation_is_refused_at_write` (3). Same revert: killed |
| P5/P6 (D2) | `model_dump_json()` and `model_dump(mode="json")` on a golden | `2026-08-30T16:20:20.442Z` | `test_model_dump_json_equals_to_wire_json_on_every_golden` (12). With the JSON-mode branch disabled (`if False:`): `+ :20:20.979000Z","payload":…`. Formatter corrupted to `isoformat()`: `test_model_dump_mode_json_writes_the_wire_instant` gives `'2026-08-30T1....442999+00:00' == '2026-08-30T16:20:20.442Z'` |
| P7 (D2) | FastAPI `response_model` | `.442Z` | `test_a_fastapi_response_model_writes_the_wire_instant`. With the branch disabled: `'{"at":"2026-...:20.442999Z"}' == '{"at":"2026-...:20:20.442Z"}'` |
| A2 (D3) | inline `warehouseGLN` in `StockCheckRequestPayload.lines.items`, regenerated | 1 failed, 188 passed | `test_every_property_name_at_every_depth_is_exactly_a_generated_wire_name[asyncapi]`: `assert ['warehouseGLN'] == []`. A second plant, inline `schema` (→ `schema_`), was also killed: `assert ['schema'] == []` |
| D4 | the writer turns `available`/`attempts` from `int` into `float` **after** validation (so the re-validation cannot catch it first) | 3 failed | `test_stock_rejected_parses_round_trips…`, `test_stock_rejected_without_the_optional_retailer_code…`, `test_order_saga_failed_parses_round_trips…`: `'$.payload.shortages[0].available: int 2 vs float 2.0'`, `'$.payload.attempts: int 3 vs float 3.0'`. The same mutant against `test_golden_envelopes.py`: `72 passed`. That survivor is expected (no golden has these fields), and it is why D4 mattered |
| D7 | MRO lookup reduced to the class itself | killed | `test_a_subclass_declared_elsewhere_keeps_the_explicit_nulls`: `assert '{}' == '{"despatchRe...erence":null}'` |

### Population reconciliation (D3)

The implementer's pins are 105 for asyncapi and 91 for openapi. My round-1 132 is their union. I recomputed it with my own walk (headers excluded): asyncapi **105**, openapi **91**, intersection **64**, union **132** = 105 + 91 − 64. The counts reconcile. The per-module pin is the stronger form, because the comparison is per module.

Premise of the set instrument: it compares names, not property sites. It could miss a mis-cased alias only if the spec declared the mis-cased spelling somewhere else and the generator emitted the spec's spelling as an alias somewhere. `to_camel` never emits two consecutive capitals, so the acronym case cannot escape. The `schema` → `schema_` keyword case was armed above.

### Probes of the new instruments' premises

| Probe | Result |
|---|---|
| Q1: `model_dump_json()` on `model_copy(update={"amount": 89.34})` | **wrote** `{"amount":89.34,"currency":"EUR"}` |
| Q2: `json.dumps(model.model_dump(mode="json"))`, same instance | **wrote** `{"amount": 89.34, …}` |
| Q3: `pydantic_core.to_json(instance)` | **wrote** `{"amount":89.34,…}`. On a golden, the instant is `.442Z` (the serializer is shared) |
| Q4: `ev.payload.lines.append(OrderLine.model_construct(quantity=True, unit_price=89.34, …))` | `to_wire_json` **refused** (`2 validation errors for OrderPlacedEvent`); `model_dump_json` **wrote** `'unitPrice': 89.34` |
| Q5: `__dict__` write into a nested frozen model | `to_wire_json` **refused** |
| FastAPI `response_model=Money` returning `model_copy(update={"amount": 89.34})` | **200** `{"amount":89.34,"currency":"EUR"}` (FastAPI does not re-validate instances) |
| Q6: generic `Envelope(payload={"amount": 89.34, "at": <442999 µs>})` | `to_wire_json` writes `"at":"…442Z"`; `model_dump_json` writes `"at":"…442999Z"`. **The two disagree.** `89.34` is written by both (the spec types `payload` only as `object`). A `True` assigned into the dict after construction is written as `true` |
| List-held instant: `occurredAt: {type: array, items: Instant}` added to `InvoiceView`, regenerated (an existing name, so the population pin is unchanged) | `to_wire_json` gives `['…442Z']`; `model_dump_json` gives `['…442999Z']`; **`189 passed`**. Restored and `cmp`-checked |
| The same with a new name (`releasedAtHistory` on a fact payload) | caught only incidentally, by the population pin and by the optional-fields literal, never by an instant assertion |
| `RootModel[datetime]`, `list[AwareDatetime]` or `dict[…, AwareDatetime]` in the generated code | **none**: `grep` over `generated/*.py` for those forms returns no hits. The `Any` dicts are `Envelope.payload` (`asyncapi.py:121`), `RpcError.details` (`:441`) and openapi `detail` (`openapi.py:179`) |
| Dead `RootModel`s | `asyncapi.Quantity.model_validate("6").root` is `6` (lax; it is not a `WireModel`). Unreferenced. `DespatchReference` inside `OrderReferences` refuses `7` |

### Round-2 findings, each with its disposition

- **R2-1 (MINOR) The write-side re-validation lives only in `to_wire_json`.**
  - **Evidence:** Q1–Q4 and the FastAPI row. A `model_copy(update=…)`, a `model_construct`, or an in-place append to a list field puts `89.34` or `true` on the wire through `model_dump_json`, `pydantic_core.to_json` or a FastAPI `response_model`. These are the paths that D2's fix now presents as agreeing with `to_wire_json` (`wire.py:65-68` docstring). That is changing an instrument and swapping its premises: D1's fix assumed `to_wire_json` is the only writer, and D2's fix made it not the only one.
  - **Why it is not blocking:** every bypass needs an API that is explicitly validation-skipping. Assignment, the casual path, is refused. The canonical fact writer validates. No service code exists yet.
  - **Disposition:** ACCEPTED, NOT FIXED. Re-open trigger: the first `model_copy(update=` or `model_construct(` on a `WireModel` in `services/`, or the first publisher or REST route that serialises a `WireModel` other than through `to_wire_json`.
  - **Suggested fix for the entry:** validate inside `WireModel._serialize` when `info.mode_is_json()`. `type(self).model_validate(self.model_dump(mode="python"))` does not recurse, because python mode skips the branch. Alternatively, a repo-wide guard that forbids those calls in `services/`.
- **R2-2 (MINOR) The JSON-mode instant formatter only sees `datetime` values held directly in a field.**
  - **Evidence:** a list-held instant survives the whole suite (189 passed). A `datetime` inside an `Any` dict (`Envelope.payload`, `RpcError.details`, `Problem.detail`) is written `.442999Z` by `model_dump_json` and `.442Z` by `to_wire_json` (Q6). No generated field holds a list or dict of instants today.
  - **Why it matters:** the likeliest real trigger is an outbox relay that wraps a typed payload's python-mode dump in the generic `Envelope` and serialises it with `model_dump_json`. That is exactly the next feature.
  - **Disposition:** ACCEPTED, NOT FIXED. Re-open trigger: a spec change (SA) that introduces an array or map of `Instant`, or any code constructing the generic `Envelope` with a non-JSON-native payload.
  - **Suggested fix:** in JSON mode, derive the output from the python-mode dump through the same conversion as `_default`, so that `model_dump_json() == to_wire_json()` holds by construction. Arm it with the `InvoiceView.occurredAt` list plant above and a generic `Envelope` whose dict payload holds a `datetime`.
- **R2-3 (NIT) `wire.py`'s module docstring contradicts the code.** Lines 10-11 say "which is why the writer starts from a python-mode dump", and line 17 says "`model_dump_json` is deliberately not the writer: it would emit microsecond instants". Both are untrue since D2. Line 14 still says integers are strict "when parsing" only. Fold the correction into the same backlog entry (the leader may not edit `packages/`).
- **R2-4 (NIT) The dead `RootModel`s `asyncapi.Quantity` and `asyncapi.ProductCode` are exported and lax.** `"6"` becomes `6`. They are unreferenced, and they are not `WireModel`s. Same entry: drop them at generation, or document them as non-wire.

**Proposed backlog entry (for the leader to file; I do not write `feature_list.json` beyond the status line).** Next id 203, `wire_model_every_path_residuals`, attached to feature 14 `outbox_and_idempotency`, the first feature that publishes and the likeliest to build a generic `Envelope`. Acceptance:

1. `model_dump_json`, `model_dump(mode="json")` and a FastAPI `response_model` refuse a `model_copy(update=…)` or `model_construct` instance holding `True`, `89.34` or `"8934"` in an integer field. Arm it by removing the check.
2. `model_dump_json() == to_wire_json()` for a list-held instant (the `InvoiceView` plant, made in a test-local subclass or a generated fixture) and for a generic `Envelope` with a `datetime` in its dict payload. Arm it by reverting.
3. `wire.py`'s module docstring matches the code. The dead `RootModel`s are removed or documented.

Re-open triggers as given in R2-1 and R2-2.

### Ledger rows, re-checked

- **Integer strictness:** now supplied on parse (`strict=True`), on assignment (`frozen=True`) and at `to_wire_json` (re-validation). Each named guard executes its path: P2–P4, killed when reverted. R2-1 is the stated residual.
- **Timestamp:** supplied on `to_wire_json`, `model_dump_json`, `model_dump(mode="json")`, `pydantic_core.to_json` and FastAPI, for direct fields. R2-2 is the stated residual. The implementer's report corrects its own round-1 "avoided" to **recurred** (`impl_contracts_package.md`, "Corrections" section). I agree.
- **camelCase alias:** the guard now covers the full population (D3). The other rows are unchanged from round 1.

### CHECKPOINTS, round 2 (the boxes that were open in round 1)

- C3 `[x]` no float on the money wire through `to_wire_json`, on any of the round-1 bypasses (R2-1 accepted for the non-canonical writers).
- C4 `[x]` `./quality.sh` end to end, exit 0, sections 1–7 including 6b and web.
- C5 `[x]` history entry appended (below) with its effort record · `[x]` `feature_list.json` id 8 → `done` · `[ ]` the human told what was done: the leader's step · `[x]` no commit.
- C7 `[x]` inherited findings accounted for in the history entry, including the recurrence.
