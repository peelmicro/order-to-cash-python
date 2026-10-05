# Review: Phase 7 backlog sweep (backlog 202, 203, 204, 207, 210; carries of 201, 205)

Reviewer, 2026-10-05, 19:58–20:14 CEST. FULL process (money guard, wire contract, persistence, security). Inputs: the brief (scratchpad `brief_backlog_sweep.md`), `progress/premise_backlog_sweep.md`, `progress/impl_backlog_sweep.md`, the working tree. Contract: each entry's `acceptance` array in `feature_list.json` plus the review section its note cites.

## Verdict: REJECTED

**3 blocking defects** (B1 money guard, B2 write-path population, B3 `to_wire_json`). 207 and 210 are clean, and so are 204(b)–(e). 203 is clean apart from B3. No statuses changed in `feature_list.json`: this is a rejection, and the brief says to change none.

**Reviewer incident: I left a stray file in the working tree. It must be deleted before anything else.** During one arm I appended to a path I believed existed: `packages/shared_kernel/src/otc_shared_kernel/currency.py`. It did not exist, so the command created it. The file holds only my plant (a blank line, then `vars()["to_major_text"] = len`). My `rm` was refused by the permission classifier, and I did not work around the refusal. The leader or the maintainer must delete that one file. Until then, `test_the_kernel_module_population_is_the_literal_list` fails with `+['currency']`, which incidentally shows 202 R2-1's population test working. The two `quality.sh` runs below were taken **before** the file existed. Every other mutation I made was restored from a `cp` backup and confirmed with `cmp`, and `__pycache__` was cleared.

## What I ran (instead of re-running everything twice)

- I armed one mutation per entry that the implementer had not published, plus extra probes. Details are under each entry below.
- I ran `quality.sh` twice with the 12 `otcpy` containers stopped, as the brief asked. After that I ran `pytest --durations=30` and `--durations=0`, bucketing the time by area. These runs were sequential, never two at once.
- I ran the sweep's own 13 test files: 305 passed in 0.95 s.
- I checked the ledger citations in the #7 and #8 checkouts.
- I did not re-run `init.sh`, because the stray file above would make it meaningless. The implementer reports exit 0.

## CHECKPOINTS.md (applicable boxes)

- C2 [x] Every status is valid, and none is changed by this review. [x] `progress/current.md` was not touched by the sweep.
- C3 [x] `lint-imports` is green (quality.sh step 4, both runs). [x] No service imports another, and `specs/shared/` is untouched (`git status --porcelain specs/` gives 0 lines). [ ] The money guard has a hole for `**` spelled as a from-imported `pow` (B1).
- C4 [x] `./quality.sh` exit 0, 1032 passed, coverage 98 % overall and 98 % domain (both runs). [x] The integration suites pass with the developer stack down. [x] No Jest, Karma or Jasmine.
- C5 [ ] A suspicious untracked file exists: my stray `currency.py` (see the incident above). [ ] `feature_list.json` is not yet true for 202–210, because they are rejected. [x] No commit was made.
- C6 n/a: every entry is `sdd: false`.
- C7 [x] The 204(d) ledger row's "#7 relied on" and "#8 supplied" halves are cited correctly. `order-to-cash-nestjs/apps/orders/src/infrastructure/persistence/db-config.ts:20` reads `password: env.MYSQL_PASSWORD ?? ''`. `order-to-cash-dotnet/src/Orders/Infrastructure/Persistence/OrdersDbContextFactory.cs:33-37` reads `?? throw new InvalidOperationException`. Both halves were read on disk.

## Acceptance item → test mapping (verified)

| Item | Test(s) | Seen to fail |
|---|---|---|
| 202.1 recursion | `test_kernel_surface.py::test_the_kernel_module_population_is_the_literal_list` (`rglob`) | implementer: planted `text/__init__.py`. Mine, by accident: a top-level `currency.py` gives `+['currency']` |
| 202.2 runtime `vars()` | `::test_every_kernel_module_holds_at_runtime_only_the_allowlisted_names` | implementer: 4 forms. **Mine, unpublished:** `vars()["to_major_text"] = len` appended to `gln.py` gives `gln holds names at runtime that the allowlist lacks: ['to_major_text']`. Restored, `cmp` OK, green |
| 202.3 pow family | `test_money_guard.py` `POW_NAMES` sentinels | implementer: `operator.pow(10, -2)` in the kernel and in a domain. **Mine: a from-import form is NOT seen** (B1) |
| 203.1 every JSON path refuses | `test_r2_1_*` (14 cases, including FastAPI `response_model`) | **Mine:** with `model_validate` replaced by `pass`, the FastAPI test alone fails with `assert 200 == 500`, so it is armed by the fix and not by FastAPI's own validation. I also confirmed that `pydantic_core.to_json`, `TypeAdapter(...).dump_json`, `TypeAdapter(list[Money])` and `jsonable_encoder` all refuse (probe). **But `to_wire_json` does not** for a model held in `Envelope.payload` (B3) |
| 203.2 list- and dict-held instants (buildable half) | `test_r2_2_a_list_held_instant_*`, `test_r2_2_a_dict_held_instant_in_an_envelope_payload_*` | **Mine, unpublished:** only the dict branch of `_holds_datetime` disabled (list branch kept) makes the dict test fail with `...442999Z` written against `...442Z` expected. Probes: tuple-held, `dict[str, datetime]`, a WireModel inside the payload and a list of WireModels inside the payload all write `.mmmZ` |
| 203.3 docstring and RootModels | `test_r2_3_*`, `test_r2_4_*` | implementer |
| 204(a) population | `tests/architecture/test_write_path_population.py` | **Mine: 3 unclassified writers PASS** (B2) |
| 204(b) docstring | text check | `grep`: both cited test names exist in all three `tests/integration/test_*_quantity_range.py`. `Core` appears only as the quoted `"Core only"`. `md5sum` at HEAD is identical for all three copies (`8349af19…`) |
| 204(c) pass-through | `test_a_sql_expression_assigned_to_a_guarded_attribute_passes_through` (×3) | unchanged claim. The `SagaCommand.attempts + 1` line is untouched |
| 204(d) no default | `test_orders_database_settings.py::test_boot_fails_when_no_credential_is_supplied`, `::test_a_bare_password_variable_is_not_a_credential` | implementer: default restored |
| 204(e) no bare names | `::test_bare_user_host_port_and_password_never_reach_the_url` | **Mine, sibling substitution:** `validate_by_name=True` in place of `populate_by_name` fails 2 tests with `someone-else:…@elsewhere:1` |
| 207.1–3 | `test_a_non_integer_typed_expression_is_refused_not_rounded_by_the_engine` and `test_an_integer_typed_expression_still_passes_through` (×3), plus `test_range_guard_parity` | **Mine, unpublished:** `Integer \| Numeric` admitted in billing's copy fails `[numeric literal]`, and parity restored green. Shape probe on `Stock.units`: `/ 2` (Numeric), `+ Decimal('0.6')`, `func.round(x * 0.5)`, `func.greatest(...)` (NullType) and `case(..., 0.5)` (Double) are refused. `// 2` and `coalesce(x, 0)` (Integer) pass. `cast(x * 0.5, Integer)` passes, which is the docstring's named residual |
| 210.1–2 | the closure test in orders, fulfillment and seed (billing and notifications already had it) | **Mine:** a new field declared with `alias=` (not `validation_alias=`) in orders fails the closure test with `Extra items: 'POSTGRES_POOL_SIZE'` |

Point 4 of the brief (the three retyped tests): confirmed, **not weakened**. The untyped `literal_column(...)` that used to stand for "any ClauseElement" moved into the new refusal test (`untyped literal_column (NullType)` id, all three services). The typed form stayed in the pass-through test, and the `Model.col + 1` line is untouched in all three. The claim narrowed exactly as 207 requires.

## Blocking defects

### B1. 202.3: `math.pow` imported by name escapes the money guard

`tests/architecture/test_money_guard.py:93-102` and `:124` (`_is_unsafe_pow_call`). The new rules see `pow` only as an `Attribute` (`math.pow`) or as a dunder `Name`. A bare `pow(...)` is judged as `builtins.pow` by its exponent. Probe (`violations(...)`):

```
'from math import pow\nx = pow(10, 2)\n'            -> []   # math.pow: returns 100.0, a float
'from math import pow as p\nx = p(10, 2)\n'         -> []
'from operator import pow as p\nx = p(10, -2)\n'    -> []   # 0.01
'from operator import truediv as t\nx = t(6, 3)\n'  -> []   # pre-existing, same class
```

The acceptance item names `math.pow` explicitly. The implementer's own sentinel `"math.pow": "import math\nx = math.pow(10, 2)"` treats a positive-exponent `math.pow` as a violation, and the from-import spelling of the same call passes. This is defeat row 11 (a form the instrument does not recognise). **Fix:** flag an `ast.ImportFrom` alias whose `name` is in `POW_NAMES | TRUEDIV_NAMES`, from any module. Add `MUST_DETECT` sentinels for `from math import pow`, `from math import pow as p`, `from operator import pow as p` and `from operator import truediv as t`. Arm the fix by deleting the new branch.

### B2. 204(a): the population test does not fail on a new writer. This refutes the leader's reliance on it for features 15–17

`tests/architecture/test_write_path_population.py:72-91` (`hits` returns a **set** of `(kind, detail)`), `:53-56` (`DML_TEXT`), and `:94-124` (`EXPECTED` compared by set equality). The expected set is a literal and the sentinels exist for the forms listed, but two faults defeat the claim "a new unclassified writer fails it".

1. **Occurrences collapse.** The detail is the first four words of the statement, or the bare call name. A second writer in an already-classified file with the same call name or the same four words leaves the set unchanged. From feature 15 onward, a repository file classified with `("call", "execute")` or `("call", "add")` makes every later `execute`/`add` in that file invisible.
2. **Forms not seen.** Probe of `hits(...)`: `"UPDATE {} SET ...".format(t)`, `"UPDATE %s SET ..." % t`, `"UPDATE " + t + " SET ..."`, `UPDATE <t> AS s SET`, `UPDATE ONLY <t> SET`, `from sqlalchemy import insert as ins; ins(T)` and `b"UPDATE t SET a = 1"` all return `[]`.

**Arm (mine, verbatim).** I appended `SET_ORDER_SEQUENCE = "UPDATE order_number_sequences SET next_value = :value WHERE id = 1"` to `services/orders/.../persistence/sequences.py`. That is a caller-supplied value written into the counter column, exactly the write `ensure_in_range` exists for. I also created `persistence/planted_writer.py` with `"UPDATE {} SET next_value = :value".format(table)` and `"UPDATE order_number_sequences AS s SET next_value = :value"`. Result: `test_every_write_path_in_the_service_is_a_classified_literal` gave `4 passed`. All three new writers passed silently. I restored with `cp` (`cmp` OK), deleted the planted file and cleared `__pycache__`; the re-run was 30 passed.

Point 2 of the brief: the expected set **is** a literal and the listed forms **have** sentinels. But a NEW unclassified writer in `services/*/src` does **not** reliably fail it. It fails only when the writer lands in a new file **and** uses a recognised form. Coverage is also 4 of 7 services (`SERVICES` omits gateway, projector and seed). Seed has its own population test, and projector writes MongoDB, which has no guarded integer column, so that omission is acceptable if stated.

The leader should therefore either keep the "classify new writers" item on features 15–17, or get the guard fixed. **Fix:**
- Count occurrences (for example a `Counter` of `(kind, detail)` per file with the counts in `EXPECTED`), so any added occurrence fails.
- Make the SQL detail the whole normalised statement, not four words.
- Recognise `UPDATE` followed by a placeholder (`{}`, `%s`, a `+`-concatenated `BinOp` of string constants, joined before scanning), `ONLY` and `AS alias`.
- Recognise an aliased import of a DML constructor (an `ImportFrom` of `insert|update|delete|text` from `sqlalchemy*` under any `asname`) and `bytes` constants.
- Add a `MUST_SEE` sentinel per new form and an arm per fault: my three plants above must each fail by name.

### B3. 203: `to_wire_json` writes an unvalidated WireModel held in `Envelope.payload`

`packages/contracts/src/otc_contracts/wire.py:173-185`. `to_wire_json` re-validates only the top-level model. The existing `Envelope.payload` is `dict[str, Any]`, so a `WireModel` inside it is not re-validated, and `json.dumps` writes its python dump. Probe: `to_wire_json(Envelope(..., payload={"money": Money.model_construct(amount=89.34, currency="EUR")}))` ends `"payload":{"money":{"amount":89.34,"currency":"EUR"}}}`. `model_dump_json()` of the same envelope **refuses** it (`PydanticSerializationError … amount`). After this sweep, the documented canonical writer is therefore the one JSON path that writes an unvalidated value, and the module docstring now states the opposite ("no JSON path writes it").

The fix is buildable now, so the rule "fixed in the phase that detects it" applies. For example, `to_wire_json` can also run `model.model_dump(mode="json")` (or validate every nested `WireModel` it meets) before `json.dumps`. Add a test for exactly this probe and arm it.

The carry to feature 14 must also be corrected, which is the leader's edit. Feature 14's 203 item says "refused by model_dump_json" and must say **"refused by model_dump_json and by to_wire_json"**: the outbox will publish through `to_wire_json`.

## Advisory (non-blocking; the leader disposes)

- **A1 (207).** `row.col = sqlalchemy.null()` on a nullable guarded column is now refused with the guard's error. `null()` is a `ClauseElement` typed `NullType` (probe: `null() … REFUSED QuantityOutOfRangeError`). That is a misleading code for an explicit SQL NULL. Plain `None` still passes. Either document it in the docstring, or treat a `Null` element like `None`.
- **A2 (210).** The closure test sees aliases only. A new settings field with **no** alias is read from its bare name, and the test does not notice. Asserting that every field declares a `validation_alias` would close it.
- **A3 (204(a)).** `SERVICES` is a literal of 4. State in the docstring why gateway, projector and seed are out, or derive the population from `services/*/src` and subtract a literal exclusion set with reasons.

## Carries (brief point 5)

- **203 item 2 → feature 14:** present. The text needs the B3 amendment ("and by to_wire_json"). The original item's dict-payload half is done now (`test_r2_2_a_dict_held_instant_in_an_envelope_payload_*`). Only the generic `Envelope[P]` half is carried, which is correct.
- **201 → features 24 and 29:** item 1 matches the original. "SA-6" became "SA-n", which is acceptable because SA numbers are allocated at the gate. Item 2 matches. Item 3 is done: `services/seed/README.md:19-21` ("Seeded causal chain versus live causal chain (backlog 201)") and the docstring at `services/seed/src/otc_seed/domain/data/sagas.py:8-15`. Nothing in 201 is unowned, **so 201's carries are complete**.
- **205 → feature 14:** its single acceptance item is carried verbatim, plus the title's truncation rule. **Complete.**
- Statuses were not changed, because the verdict is REJECTED. 201 and 205 can be set `done` when this sweep is approved.

## quality.sh wall clock (brief point 6)

Stack stopped (`docker stop` of the 12), `/usr/bin/time -p ./quality.sh`, sequential runs:

| Run | real | user | sys | pytest |
|---|---|---|---|---|
| 1 | **126.05 s** | 88.86 | 10.52 | 1032 passed in 97.05 s |
| 2 | **114.94 s** | 80.14 | 9.43 | 1032 passed in 91.58 s |

Both runs exceed the 110 s finding line. **The sweep is not the cause.** Its 13 test files (305 tests, including the ones that were already there) run in 0.95 s.

`--durations=0` (pytest 86.2 s; sum of phases 83.9 s), by area:

| Time | Area |
|---|---|
| 22.7 s | `services/seed/tests/integration` |
| 15.6 s | `tests/database_parity` |
| 8.6 s | billing integration |
| 8.0 s | fulfillment integration |
| 7.6 s | orders integration |
| 6.5 s | `tests/seed_counters` (3.7 s first-test setup) |
| 6.2 s | `test_mypy_rejects_float` (one mypy subprocess per case) |
| 4.2 s | `test_generation_drift` |
| ~1 s | all the unit and architecture tests together |

Phase 7's seed and counter integration (about 29 s) is the growth over the Phase 6 baseline. The rest is outside pytest: mypy, the web build, and box load (load average 5–6 from other desktop processes during run 1).

**Recommendation:** do not fix this inside the sweep. At the wrap-up, ask the maintainer to either:
- re-baseline the threshold to about 125 s, citing these numbers; or
- give the seed's read-only integration tests one seeded template database per session, cloned per test with `CREATE DATABASE … TEMPLATE`. That is the same move that saved 11 % in `review_db_billing.md`, and it would remove most of the 22.7 s.

Restarted: 12 of 12 `otcpy` containers healthy.

## What must change before re-review

1. B1: from-import `pow`/`truediv` aliases are flagged, with sentinels and an arm.
2. B2: the population test fails on an added occurrence and on the listed forms; my three plants each fail by name; sentinels and arms.
3. B3: `to_wire_json` refuses an unvalidated WireModel held in a `dict[str, Any]` payload, tested and armed. The leader amends feature 14's 203 carry to name `to_wire_json`.
4. Leader: delete `packages/shared_kernel/src/otc_shared_kernel/currency.py` (the reviewer's stray plant) before any run.
5. Re-review scope: B1–B3 only, plus a re-run of the touched tests and `quality.sh` once.

---

# Review — round 2

Reviewer, 2026-10-05. Scope: B1, B2, B3 from round 1, plus whether each premise of the new 204(a) instrument is armed. Input: the "Round 2" section of `progress/impl_backlog_sweep.md`.

Leader facts taken as given, not re-run:
- my stray `currency.py` has been deleted, and `test_kernel_surface.py` passes (27 tests);
- feature 14's 203 carry now names `to_wire_json` (I confirmed the string with `grep -o "refused by model_dump_json and by to_wire_json" feature_list.json`, which found 1 match);
- the threshold is re-baselined to about 125 s, and the implementer measured 109.83 s. I did not re-run `quality.sh`.

Mutation hygiene: I only appended to existing files (`services/orders/src/otc_orders/domain/__init__.py`, `.../persistence/sequences.py`, `.../persistence/types.py`, `wire.py`, `test_write_path_population.py`) or worked on copies in the session scratchpad. Each one was backed up with `cp`, restored, checked with `cmp`, and `__pycache__` was cleared. At the end, `git status --short` is identical to the snapshot I took before round 2 (69 lines, `diff` empty). No file I created is in the tree.

## Verdict: REJECTED

**2 blocking defects** (R2-B1, R2-B2). B3 is closed. No statuses changed.

This is the second rejection. Under CLAUDE.md's cost rule, the leader must now ask the maintainer whether to continue, accept with a disposition, or defer. Both remaining items are a few lines each. I give the exact list below so that one more round can close them.

## B3: CLOSED

- `to_wire_json` now also runs `model.model_dump(mode="json")` (`wire.py:176-185`).
- **Round-1 probe re-run:** the envelope whose `payload` holds `Money.model_construct(amount=89.34)` is now refused by `to_wire_json` (`PydanticSerializationError … Money`).
- **New shapes (probe), all refused:** the bad model held in a tuple; nested in a dict inside a list inside a dict; and `model_copy(update={"amount": True})` of a valid model.
- **My unpublished arm (sibling substitution):** I changed `model_dump(mode="json")` to `model_dump(mode="python")`. Then `test_r2_1_to_wire_json_refuses_an_unvalidated_model_held_in_an_envelope_payload` failed 3 of 3 cases with `DID NOT RAISE PydanticSerializationError`. Restored, `cmp` OK. The contracts suite, money guard and kernel surface then gave 343 passed.

## R2-B1 (202.3): the round-1 forms are closed, but `ipow`, `itruediv` and `getattr(x, "pow")` still escape

**Round-1 plant, re-run on disk.** I appended `from math import pow as _p`, `from operator import truediv as _t` and `_X = _p(10, 2)` to the orders domain `__init__.py`. `test_money_guard_finds_no_violation_in_domain_or_shared_kernel` failed with `line 3: \`from math import pow\` …` and `line 4: \`from operator import truediv\` …`. Restored, `cmp` OK, 104 passed.

**New forms (unpublished), appended to the same real domain file:**

```
import operator
_X = operator.ipow(10, -2)          # 0.01
_Y = operator.itruediv(6, 4)        # 1.5
_Z = getattr(operator, "pow")(10, -2)
```

Result: `104 passed`. All three escape. As probes: `from operator import ipow` and `from operator import itruediv` also give `[]`, while `getattr(operator, "truediv")` **is** caught (`` `truediv` as a string``).

**Ruling on the residual the implementer names (`getattr(math, "pow")`): fix now, under the fix-in-phase rule. Do not accept it.** Reasons:
- The acceptance item says "like the truediv family". That family refuses the exact string `"truediv"` (`test_money_guard.py`, the `node.value in TRUEDIV_NAMES` branch), and the pow family refuses only the dunder strings. That inconsistency is the defect.
- The fix has no false-positive cost today. I ran `grep -rnE "[\"'](pow|ipow|itruediv)[\"']"` over every `services/*/src/otc_*/domain` and `packages/shared_kernel/src`, and it produced no output.

**Required:**
1. Add `ipow` (and `__ipow__`, already present) to `POW_NAMES`, and `itruediv` to `TRUEDIV_NAMES`.
2. Flag an exact string constant equal to any name in `POW_NAMES` (not only `POW_DUNDERS`).
3. Add `MUST_DETECT` sentinels for `operator.ipow`, `from operator import ipow`, `operator.itruediv`, `from operator import itruediv` and `getattr(math, "pow")`.
4. Arm each new branch.

**Accepted residual** (name it in the guard's docstring): a computed name (`getattr(m, "p" + "ow")`, `importlib.import_module("math").__dict__[...]`). No syntax guard can see it, and the same residual exists for truediv.

## R2-B2 (204(a)): round-1 defect closed; two unseen forms remain, and one premise is not armed

**Round-1 plants, re-run on disk.** None of these created a new file: the two "new file" plants went into the existing, unclassified `persistence/types.py`. Each made `test_every_write_path_in_the_service_is_a_classified_literal[orders]` fail, with the message `services/orders/src has an unclassified write path (or lost a classified one, or gained a second occurrence of one) … Found: {...}`:
- P1: `SET_ORDER_SEQUENCE = "UPDATE order_number_sequences SET next_value = :value WHERE id = 1"` appended to `sequences.py` (same key as a classified writer). **Fails.**
- P2: `"UPDATE {} SET next_value = :value".format(table)` appended to `types.py`. **Fails.**
- P3: `"UPDATE order_number_sequences AS s SET next_value = :value"` appended to `types.py`. **Fails.**
- New form N3: `INSERT … ON CONFLICT (id) DO UPDATE SET next_value = :v` appended to `sequences.py`. **Fails** (good).

The core fault is fixed: the test now counts occurrences, and the detail is the whole statement. Counting also exposed that `models.py` holds two `text(...)` calls, which the set had hidden.

**New forms (unpublished), appended to `types.py` and run on disk:**
- N1: `RESET_C = "UPDATE /* hot */ order_number_sequences SET next_value = :value"` gives `1 passed`. **Escapes.** A SQL comment between the verb and the table defeats `_TABLE`.
- N2: `from sqlalchemy.sql.dml import Update as _U` followed by `_STMT = _U` gives `1 passed`. **Escapes.** SQLAlchemy's DML classes `Insert`, `Update` and `Delete` (capitalised, constructable, importable under an alias) are not in `CALL_NAMES`, and the import is not a hit. Probe: `Update(T).values(a=1)` gives `{}`.

**Premises (the report's 1 to 7):**
- Premise 7 (scanned set = `services/*/src` minus the literal `EXCLUDED`): **armed by me.** Adding `"notifications": "MUTATION"` to `EXCLUDED` failed `test_the_scanned_population_is_every_service_minus_the_literal_exclusions`.
- Premises 1, 2, 3, 4 and 5: the implementer's arms are plausible, and my P1–P3 and N3 plants confirm 1, 2 and 4 on the real population.
- **Premise 6 ("operands consumed by a longer string are not scanned twice") is NOT armed.** I replaced `consumed.update(` with `set().update(` (nothing consumed). The whole file still passed (59). On a scratchpad copy, each of the 6 `MUST_COUNT` sentinels gives the same count with and without the mutation: their operands never match DML on their own. A form whose left operand is already a full statement does show the difference: `"UPDATE t SET a = 1" + " WHERE id = :v"` counts 1 on the real code and 2 on the mutated copy. The failure direction is safe (an over-count fails loudly), but "all armed" is not true for this premise.

**Required:**
1. Strip SQL comments (`/* … */` and `-- …` to end of line) from the text before `DML_TEXT` is applied, and add N1 as a `MUST_SEE` sentinel.
2. Treat `Insert`, `Update` and `Delete` (and their imports under any alias, from `sqlalchemy*`) as DML constructors, and add N2 as `MUST_SEE`, both as an import with `as` and as a call.
3. Add the `MUST_COUNT` case `'Q = "UPDATE t SET a = 1" + " WHERE id = :v"\n'` → 1, and arm premise 6 by removing the consumption.

**Accepted residuals** (name them in the docstring):
- a statement whose verb sits in a separate *name* (`_V = "UPDATE "`, `Q = _V + _R`; probe `{}`);
- `getattr(sa, "update")`;
- a quoted table name containing a space.

All three are computed or unidiomatic forms that a syntax scan cannot close, and the live-database guard is the behavioural half.

## Round 2 mapping changes

| Item | Test | Seen to fail (round 2, mine) |
|---|---|---|
| 202.3 | `test_money_guard_finds_no_violation_in_domain_or_shared_kernel` | from-import forms: yes. `ipow`, `itruediv`, `getattr "pow"`: **no** (R2-B1) |
| 203.1 (`to_wire_json`) | `test_r2_1_to_wire_json_refuses_an_unvalidated_model_held_in_an_envelope_payload` | yes (sibling mode) |
| 204(a) | `test_every_write_path_in_the_service_is_a_classified_literal`, `test_the_scanned_population_is_every_service_minus_the_literal_exclusions` | P1, P2, P3, N3 and EXCLUDED: yes. N1, N2: **no**. Premise 6: **unarmed** (R2-B2) |

## What must change before round 3 (if the maintainer continues)

- The R2-B1 required list, items 1 to 4.
- The R2-B2 required list, items 1 to 3.
- The named residuals written into both docstrings.
- Re-run `tests/architecture` once. No other scope.

---

# Review — round 3

Reviewer, 2026-10-05. Scope: R2-B1 and R2-B2 only. Input: the "Round 3" section of `progress/impl_backlog_sweep.md`. I did not re-run `quality.sh`; the implementer reports 107.23 s against the re-baselined threshold of about 125 s.

**Claim "only the two test files changed": verified.**
- `find services packages tests scripts conftest.py pyproject.toml -newer progress/review_backlog_sweep.md -type f` lists `tests/architecture/test_write_path_population.py` and `tests/architecture/test_money_guard.py`.
- It also lists `packages/shared_kernel/src/otc_shared_kernel/__init__.py` and `services/orders/src/otc_orders/domain/__init__.py`. Those two only have a new mtime from the implementer's arm-and-restore: `git diff --stat` and `git status --short` on both are empty, so their content equals HEAD.

**Hygiene.**
- I only appended to existing files (the orders domain `__init__.py`, `persistence/types.py`, `test_money_guard.py`) or worked on scratchpad copies. Each was backed up with `cp`, restored, checked with `cmp`, and `__pycache__` was cleared.
- After restoring, the full files are green again: money guard 195 passed, write-path population 70 passed.
- The final `git status --short` matches my round-3 snapshot (see the end of this section).

## Verdict: REJECTED

**2 blocking items, one per guard, each a few words of code.** No statuses changed.

The round-2 survivors are all closed, and the premises of the new instruments are armed. What remains is one omission per guard: a form a reasonable author would write, which a syntax scan can close and which no docstring names.

## Round-2 survivors, re-planted on disk: all fail by name

| Plant (appended) | Test | Result |
|---|---|---|
| `import operator` / `operator.ipow(10, -2)` / `operator.itruediv(6, 4)` / `getattr(operator, "pow")(10, -2)` → orders domain `__init__.py` | `test_money_guard_finds_no_violation_in_domain_or_shared_kernel` | **fails**: ``line 3: `import operator` (banned numeric module…)``, ``line 5: `.ipow` …``, ``line 6: `truediv` family …``, ``line 7: `getattr` …`` |
| `import math` / `getattr(math, "pow")(10, 2)` → same file | same | **fails**: ``import math``, `` `getattr` ``, `` `pow` as a string`` |
| N1 `"UPDATE /* hot */ order_number_sequences SET next_value = :value"` → `persistence/types.py` | `test_every_write_path_in_the_service_is_a_classified_literal[orders]` | **fails**, `unclassified write path … Found: {...}` |
| N2 `from sqlalchemy.sql.dml import Update as _U` / `_STMT = _U` → same file | same | **fails** (`('import', 'Update as _U')`) |
| Premise 6 tail form `"UPDATE t SET a = 1" + " WHERE id = :v"` (probe) | `hits` | counts 1 |

## Premises of the new instruments: armed (my unpublished single-element arms)

- **Ban list.** I removed only `"cmath"` from `BANNED_NUMERIC_MODULES`. Seven sentinels failed by name: `money guard failed to detect: from-import of cmath`, `import as of cmath`, `dunder import of cmath`, `dotted __import__ of cmath`, `from submodule of cmath`, `from-import as of cmath` and `from-import star of cmath`. Restored, `cmp` OK, 195 passed.
- **Reflection set.** I removed only `"__getattribute__"`. Two failed: `__getattribute__ call` and `def __getattribute__`. Restored, `cmp` OK.
- **The implementer's other premises:** the population walk (the existing non-vacuity tests), the false-positive list (`MUST_NOT_DETECT`), comment stripping, and `Insert`/`Update`/`Delete`. My survivor plants exercise each on the real population, and premise 6 now has a sentinel that can fail. Accepted.

## R3-B1 (money guard): the ban list was never enumerated, and `statistics` is a float source a domain author would reach for

The new instrument rests on a negative claim: "without the module there is no `/` or `**` to reach". CLAUDE.md treats a negative claim as a search result, but the six-module list is a literal nobody derived. My new form, appended to the orders domain `__init__.py`:

```
import statistics
_M = statistics.mean([1, 2])     # 1.5 (and 3, an int, for [2, 4]: the float appears only on some data)
```

`test_money_guard_finds_no_violation_in_domain_or_shared_kernel` gave **1 passed**, so it escapes. An average (of unit prices, or of days to pay) is a form a reasonable domain author writes. Because the result is an int on some inputs, `Money`'s refusal at construction catches it only on some data. `from statistics import fmean` escapes too (probe). Today's population has no hit (`grep -rnE "\bstatistics\b"` over every domain and the kernel produced no output), so the ban breaks nothing.

The builtin `pow` taken **as a value** also escapes. I appended `from functools import reduce`, `_power = pow`, `_X = _power(10, -2)` and `_Y = reduce(pow, [10, -2])`: **1 passed**. Both give `0.01`. The probes `map(pow, [10], [-2])` and `functools.partial(pow, 10)` also give `[]`. The guard judges a bare `pow` only in the call position (`_is_unsafe_pow_call`), yet it refuses `getattr` "as an alias `g = getattr`". The docstring's residual criterion is "a name the AST cannot evaluate", and `pow` as a value is plainly visible to the AST, so the residual list is incomplete on its own terms.

**Required:**
1. Add `statistics` to `BANNED_NUMERIC_MODULES`. Also run a search for any other stdlib module whose public functions return `float` from int input, write the command and its classified output in the report, and either ban each hit or name it as a residual with a reason. Add sentinels for `import statistics` and `from statistics import fmean`, and arm by removing the entry.
2. Flag `Name("pow")` anywhere except as the `func` of a `Call` (that call keeps its exponent rule). Add sentinels `_p = pow`, `reduce(pow, …)`, `map(pow, …)` and `partial(pow, 10)`, and arm.

## R3-B2 (write-path population): asyncpg's `copy_to_table`, the sibling of a listed name, escapes

`CALL_NAMES` lists asyncpg's `copy_records_to_table`. My new form, the sibling identifier `copy_to_table` (defeat row 3), was appended to `persistence/types.py`:

```
async def _load(conn: object) -> None:
    await conn.copy_to_table("order_number_sequences", source="counters.csv")
```

`test_every_write_path_in_the_service_is_a_classified_literal[orders]` gave **1 passed**, so it escapes. `asyncpg.Connection` has exactly two write-side COPY methods, `copy_records_to_table` and `copy_to_table` (`dir(asyncpg.Connection)` filtered on `copy`: `copy_from_query`, `copy_from_table`, `copy_records_to_table`, `copy_to_table`, plus private helpers). The services use asyncpg, and a bulk load from a file is a form an infrastructure author writes. Today's population has no hit (`grep -rn copy_to_table services/*/src`: no output).

A second form also escapes: `from sqlalchemy import update`, then `{"u": update}`, an unaliased DML constructor used as a value. This one is unidiomatic, and naming it as a residual is acceptable. The aliased form (`update as update`) already fails.

**Required:**
1. Add `copy_to_table` to `CALL_NAMES`, with a `MUST_SEE` sentinel and an arm.
2. Either flag an unaliased name imported from `sqlalchemy*` whose name is a DML constructor when it is used outside the call position, or add it to the docstring's residuals.

## Docstring residuals: are they honest?

- **Money guard.** `vars()`, `__dict__`, `globals()`, `__builtins__` and a non-literal `import_module`: honest, all computed. **Incomplete:** `statistics` and the other float-returning modules (R3-B1.1), and `pow` as a value (R3-B1.2).
- **Write path.** A verb held in a separate name, `getattr(sa, "update")`, and a quoted table with a space: honest, all computed or unidiomatic. **Incomplete:** `copy_to_table` (R3-B2.1) and the unaliased constructor as a value (R3-B2.2).

## What remains (complete list)

- R3-B1.1: `statistics` banned, plus a recorded search of float-returning stdlib modules; sentinels and an arm.
- R3-B1.2: `pow` as a value flagged; sentinels and an arm.
- R3-B2.1: `copy_to_table` in `CALL_NAMES`; sentinel and arm.
- R3-B2.2: an unaliased DML constructor used as a value, either flagged or named as a residual.

Everything else in 202, 203, 204, 207 and 210 is verified (rounds 1 to 3), and the 201 and 205 carries are complete. Re-check scope after the fix: `tests/architecture` only, plus my four plants above re-run on disk.

---

# Review — round 4 (final, bound by the maintainer's stopping rule)

Reviewer, 2026-10-05. Scope, fixed by the stopping rule:
1. The money guard's import allow-list equals a census re-derived by command, and the listed arms fail by name.
2. The write path has `copy_to_table` present and armed, and the `{"u": update}` residual is named.

Under the stopping rule, any further form is a named residual, not a blocking finding. Input: the "Round 4" section of `progress/impl_backlog_sweep.md`. I did not re-run `quality.sh`; the implementer reports 117 s against about 125 s.

**Claim "only the two test files changed": verified.**
- `find … -newer progress/review_backlog_sweep.md -type f` lists the two test files, plus four source files that the implementer appended to and restored during arming.
- Three of those four have empty `git diff --stat` and `git status --short`, so they equal HEAD: the orders domain `__init__.py`, the kernel `__init__.py`, and `persistence/types.py`.
- The fourth, `services/seed/src/otc_seed/domain/__init__.py`, differs from HEAD only by the Phase 7 seed docstring. It was already `M` in the session's starting status, and it carries no planted `import otc_orders`.

**Hygiene.** I only appended to existing files (the orders domain `__init__.py`, `persistence/types.py`, `test_money_guard.py`). Each was backed up with `cp`, restored, checked with `cmp`, and `__pycache__` was cleared. After restoring, the full files are green again: money guard 304 passed, write-path population 73 passed. The final `git status --short` matches my round-4 snapshot.

## Verdict: APPROVED

**0 blocking.** Every listed item is met, and the allow-list is the census.

## Item 1: money guard

**Census, re-derived by me** (scratchpad `census_mine.py`, an AST walk over `services/*/src/otc_*/domain/**` and `packages/shared_kernel/src/**`, excluding `__pycache__`):

```
files 35
roots {'collections': 2, 'dataclasses': 12, 'datetime': 2, 'hashlib': 1, 'otc_seed': 23, 'otc_shared_kernel': 19, 'types': 1, 'typing': 4, 'uuid': 1}
relative 0
names {'sum': 5, 'divmod': 1, 'abs': 1}
```

This equals `ALLOWED_ROOTS` (`test_money_guard.py:90-93`) exactly: the 7 stdlib roots plus `otc_shared_kernel`, and `otc_seed` as the importing service's own package, passed per file. **The allow-list is the census.** The name census agrees with the implementer's: `pow`, `float` and `round` are used 0 times, `sum` 5, `divmod` 1, `abs` 1.

**Arms I re-ran:**
- **Listed forms, planted in the real orders domain `__init__.py`:** `import statistics`, `from importlib import import_module`, `_R = round(7 // 2)`, `_S = import_module("statistics")` and `_M = statistics.mean([1, 2])`. `test_money_guard_finds_no_violation_in_domain_or_shared_kernel` **failed, naming each line**:
  - ``line 3: `import statistics` is outside the import allow-list``;
  - ``line 4: `from importlib import ...` is outside the import allow-list``;
  - ``line 6: `round` used as call, annotation or value``;
  - ``line 7: dynamic import machinery (imports are an allow-list)``.
  
  Restored, `cmp` OK.
- **Allow-list element removed** (`dataclasses`, a different element from the implementer's `uuid`): 3 tests failed, `test_money_guard_finds_no_violation_in_domain_or_shared_kernel` (the real population, 12 `dataclasses` imports), `test_money_guard_ignores_text_that_is_not_code[allowed roots, every form]` and `test_the_import_allowlist_is_the_census_literal`. Restored, `cmp` OK, 304 passed.
- **Not re-run by me, per the instruction to re-run only one or two:** `_p = pow`, `reduce(pow, …)` and `float(x)`. The implementer reports each failing by name in both the orders domain and the kernel. The rule that produces them (`BANNED_BUILTINS = {"float", "pow", "round"}` refused as a Name anywhere) is the same branch my `round` arm drove.

**Reflection ban kept:** `BANNED_REFLECTION = {"getattr", "__getattribute__"}` (`:99`), armed in round 3. **Residuals and the backstop are named** in the docstring: `Money`'s `type(...) is int` construction check in `money.py`, plus `mypy --strict`.

## Item 2: write path

- **`copy_to_table`:** present in `CALL_NAMES` (`test_write_path_population.py:83`). My round-3 plant, appended again to the real `persistence/types.py` (`await conn.copy_to_table("order_number_sequences", source="counters.csv")`), now **fails** `test_every_write_path_in_the_service_is_a_classified_literal[orders]` naming `('call', 'copy_to_table')`. Restored, `cmp` OK, 73 passed.
- **`{"u": update}` residual:** named in the module docstring (`:39`): "a DML constructor stored in a dict and called through it".

## Named residuals (non-blocking under the stopping rule), each with whether the backstop catches it

1. **`test_the_import_allowlist_is_the_census_literal` compares a literal to a literal** (defeat row 8). It does not re-derive the census in the test, so widening `ALLOWED_ROOTS` and the test literal together would pass. Backstop: none mechanical. The widening needs two deliberate edits in one file, and the census command is recorded in the report and here. If it is wanted later, re-derive the census inside the test.
2. **Float-returning APIs of allowed modules**, for example `datetime.timestamp()` (same class as the named `timedelta.total_seconds()`). The backstop catches it where the value reaches `Money`, through the runtime `type(...) is int` check and `mypy --strict` (float is not assignable to `int`). It is not caught in an intermediate computation that is never typed.
3. **Stale nit:** the old "Accepted residuals" paragraph at the end of the docstring still says a non-literal `importlib.import_module(name)` is "flagged as unverifiable". Since round 4, `import_module` is refused as a name anywhere, so that sentence is now weaker than the code. It is harmless.

## Statuses

`feature_list.json`: ids 201, 202, 203, 204, 205, 207 and 210 were changed from `pending` to `done`. Only the status lines were edited, as a line-scoped edit; the JSON parses. `diff` against my pre-edit copy shows exactly 7 changed lines (662, 677, 692, 707, 724, 752, 795), and each was confirmed to belong to its id. `git diff feature_list.json` also shows the leader's earlier pre-existing transitions, which I did not touch.

## Owed by the leader (not written by me; the brief limited me to status lines)

The `progress/history.md` effort entry for this sweep. Classification: FULL. It took 4 review rounds: round 1 found 3 blocking defects, round 2 found 2, round 3 found 2, and round 4 found 0. Rounds 3 and 4 were maintainer-approved after the second and third rejections. Record also:
- each entry as avoided or recurred against its #8 id, where one exists (204(d) is #8 review_db_orders D6, recurred in #9 F5 and now closed);
- the `quality.sh` re-baseline from about 105 s to about 125 s (rounds 1 and 2 measured 126.05 s, 114.94 s and 109.83 s; round 3 107.23 s; round 4 117 s).
