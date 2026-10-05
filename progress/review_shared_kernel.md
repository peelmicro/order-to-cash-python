# Review: shared_kernel (id 7, phase 5), full process (money domain), `sdd: false`

**Verdict: REJECTED** (round 1). One major defect (a member-kind gap in R1's absence guard: the inherited #8 `shared_kernel` D1 class, recurring in a new form), five minor, two nits. The domain code itself is correct: every behavioural mutant I planted against it was killed. Every defect is in a guard, a test that compares a literal to a literal, or a record.

Reviewer: `reviewer` agent, 2026-10-05. Rules enforced were grepped from `CLAUDE.md` on disk (arming protocol, mutation families, defeat list, money row, ledger, "a finding rooted in `specs/shared/` becomes an `SA-n` proposal or a backlog entry").

## What I ran (and what I did not)

- `packages/shared_kernel` + `tests/architecture` pytest: 340 passed.
- **The full `./quality.sh`, once, after all arming was restored** (the C4 claim is about the whole gate): exit 0; ruff format 110 files formatted, ruff check clean, mypy `Success: no issues found in 81 source files`, import-linter `Contracts: 10 kept, 0 broken`, pytest `347 passed`, overall coverage 98.04%, 6b `TOTAL 267 0 54 0 100%`, Vitest 1 passed, web build green. `uv.lock` was `cmp`-identical to a backup taken before my runs.
- `./init.sh`: exit 0; 5d says the shared spec is byte-identical to #8 and #7 across 6 files, with `test-matrix.md` exempt. I checked the exempt file separately: comparing it with `git show HEAD:` shows lines 1–68 (rules) unchanged, and columns 1–4 of R1–R4 identical. The only changes are the four Status cells and two summary rows.
- 64 independent arming runs plus 2 arms of the 6b gate (below). I did not reuse the implementer's table or harness: `scratchpad/rv/arm.py`, raw results in `scratchpad/rv/arming.jsonl`.

## Defects

### D1 (MAJOR): R1's "no decimal representation" guard inspects public names and a deny-list of dunders. `__format__`, `__repr__` and private members are not inspected (#8 D1, recurred)

- **Where:** `packages/shared_kernel/tests/test_money.py:97-114`. `test_r1_money_defines_exactly_the_expected_public_members` filters `not name.startswith("_")`. `test_r1_money_offers_no_division_conversion_or_rounding_dunder` forbids `operator`-module dunders plus the 16-name `CONVERSION_DUNDERS` literal (`:77-94`), which is a word list.
- **Reproduction (each planted in `money.py` after `__str__`; the whole of `test_money.py` run, then the AST guard):**
  - `def __format__(self, spec: str) -> str: return f"{self.amount // 100}.{self.amount % 100:02d} {self.currency}"`: **66 passed**, AST guard **passed**. `f"{price}"` would then print `1242.50 EUR`.
  - The same body as `__repr__`: **66 passed**.
  - `@property def _major(self) -> str` with the same body: **66 passed**.
- **Why it matters:** M1 says "a decimal, floating-point or fixed-point *major-unit* representation is never used". The R1 Status cell cites these tests as proof of "*offers no decimal representation*". #8's history for this feature (`../order-to-cash-dotnet/progress/history.md:296`) told #9: "for every ported rule: which member kinds does it inspect (… operators? dunder methods?), and arm one of each". The implementer's report marks #8 D1 **avoided**. For dunders outside the deny-list and for private members, it **recurred**.
- **Required change:** turn the member check into an **allowlist of every name in `vars(Money)`**: public, private and dunder, as a literal. Spell out the dataclass-generated dunders, so any added member of any kind fails. Arm it with `__format__`, `__repr__`, a private property, and a post-class-body assignment (`Money.__truediv__ = …`, which the current test does catch: run 6).

### D2 (MINOR): no guard covers a major-unit representation offered by the kernel *module* rather than the class, or one typed as `fractions.Fraction`

- **Reproduction:** add `from fractions import Fraction` and a module-level `def to_major_units(money: "Money") -> Fraction: return Fraction(money.amount, 100)` to `money.py`. `test_money.py` gives **66 passed**, the AST guard **passed** and the import allowlist **passed**, since `fractions` is stdlib (runs 15, 16). The same applies to `if TYPE_CHECKING: def to_major(self) -> Fraction: ...` inside the class, a type-level surface mypy would offer callers (runs 12–14). The `"float"` spelling of that last probe *is* caught, by the AST guard (run 4).
- **Required change (cheap):** add `fractions` to the AST guard's banned-import family next to `decimal` (M1's "fixed-point" leg), with MUST_DETECT sentinels. Assert each kernel module's public top-level names against a literal set, so a module-level conversion function fails.
- **Alternative disposition:** if the leader prefers, accept it with evidence and a re-open trigger ("any `fractions` import or new module-level public name in `otc_shared_kernel`"). It is minor because the leak needs a deliberate new function, not a typo.

### D3 (MINOR): the AST money guard does not recognise `/` spelled as its dunder (feature 6's instrument, relied on by this feature's "no division" ledger row)

- **Where:** `tests/architecture/test_money_guard.py:61-64` matches only `truediv` as a name or attribute.
- **Reproduction:** a private helper returning `self.amount.__truediv__(100)` (run 20) or `int.__truediv__(self.amount, 100)` (run 21): the guard **passes**. So does `self.amount * 10**-2`, a float with no `/` and no `float` name (run 17).
- **Required change:** extend the attribute and name check to `__truediv__`, `__rtruediv__` and `__itruediv__` (the guard already claims "`operator.truediv` is `/` by another name"; these are the same family), with sentinels.
- **Accepted residual:** the `**`-negative and `math.*` forms are a syntax-guard limit (defeat row 11). Write the backstop down: `type(amount) is int` at construction, which run 28 arms.
- **Nit in the same file:** a quoted annotation is parsed as a separate sub-AST, so its violation is reported as `line 1` (run 4 output: `'line 1: \`float\` used as call, annotation or value'`) instead of the real line. Carry the parent node's `lineno`.
- **Ownership:** the brief bounded `tests/architecture/` to exemptions. Fixing it in this round is my recommendation. Otherwise it becomes a backlog entry attached to feature 13 `orders_aggregate`, the next feature to put money arithmetic in a service domain.

### D4 (MINOR): `test_the_four_error_codes_are_distinct_and_stable` compares a literal to a literal (defeat row 8)

- **Where:** `packages/shared_kernel/tests/test_business_reference.py:107-113` compares the test file's own `KINDS` codes with a second literal. It never reads `ERROR_CODE`.
- **Reproduction:** set `OrderNumber.ERROR_CODE = "despatch_reference.invalid"` (a sibling substitution). The test **passes** (run 64). The production codes *are* guarded by another test (`test_reference_refuses_malformed_text[CR]` killed the CR substitution, run 63), so this is a vacuous test, not an unguarded property.
- **Required change:** assert `[k.ERROR_CODE for k in (OrderNumber, DespatchReference, InvoiceReference, CreditLineReference)]` against the literal list, plus `len(set(...)) == 4`. Re-arm with run 64's mutant.

### D5 (MINOR, leader's action): the R1 ratification is cited to a record that does not exist, and the coverage summary lacks its "which rows are scoped" paragraph

- **The dangling record:** the R1 cell (`specs/shared/test-matrix.md:89`) says the ratification is "recorded in `progress/history.md` › `shared_kernel`". `grep -n shared_kernel progress/history.md` finds only the `monorepo_scaffold` entry's lines 229–233. No `shared_kernel` entry exists, so the ratification currently points at nothing. Rule 3(b) wants a record, not a sentence. The leader is a legitimate non-author ratifier; the record just has to exist.
- **The missing paragraph:** `test-matrix.md:67` (a shared rule) says "the paragraph under the table says which rows hold which". #9 has no such paragraph under the coverage table (`:82` is the `---` directly after it). #8 carried one ("**Scoped rows, and what closing them would take.**").
- **Required change:** when the feature closes, the history entry must carry the R1 ratification sentence. Add a per-assessment paragraph under the table naming R1 as ratified scoped, its unproven leg, and its closer (feature 31 `api_tests`; its acceptance now names R1's API half, which I verified in `feature_list.json`). The counts 3 / 1 / 59 and 3 / 1 / 6 reconcile with the Status column: R1 is SCOPED, R2–R4 are DONE, R5–R63 are TODO.

### D6 (NIT): `quality.sh:40-41` describes an arm that was not done

The comment says 6b was "Armed … (threshold raised above the measured value: the step fails, names the figure)". The implementer's own report (`progress/impl_shared_kernel.md`, 6b row) says that is impossible at 100% and that the gate was armed by lowering the measurement. Fix the comment to describe the arm actually performed. My arm is below.

### D7 (NIT): the `errors.py:3-4` docstring is false

It says the codes are "the same strings #8 used, plus `money.invalid_amount`". #8's UniqueId code is `unique_id.empty` (`../order-to-cash-dotnet/src/SharedKernel/Errors/InvalidUniqueIdError.cs:11`); #9's is `unique_id.invalid`. `despatch_reference.invalid`, `invoice_reference.invalid` and `credit_line_reference.invalid` are also new. No code appears in `specs/shared/` (`grep -rn "unique_id\|cross_currency\|gln.invalid\|order_number.invalid" specs/shared` returns nothing), so nothing on the wire is affected. Correct the sentence.

### D8 (MINOR, route, do not fix here): `Quantity` is unbounded, and a test pins a value no column can hold

- **Where:** `test_quantity.py:22` asserts `Quantity(2**63)` is accepted. #8's `Quantity` is `int` (int32, `../order-to-cash-dotnet/src/SharedKernel/Quantity.cs:23,35`) over an `int` column (Orders migration snapshot, `HasColumnName("quantity")` on `Property<int>`). `Money` was bounded "because the write model's column is bigint". `Quantity` has no bound at all.
- **Assessment:** this is consistent with CLAUDE.md's "overflow guarded at the write boundary", but the kernel's own reasoning is inconsistent across the two types.
- **Disposition proposal:** accept here, and file a backlog entry attached to **feature 9 `db_orders`**: "the `quantity` column's range is enforced at the write boundary, and a test writes `2**31` (or the chosen column's max + 1) and sees a domain refusal, not a driver error". Alternatively, bound `Quantity` now to the column the leader picks; then the test at `:22` changes.

## Answers to the open questions

**Q1. Is `UniqueId.parse` accepting any non-nil UUID correct?** Yes.
- **What #7 and #8 generate:** v4 only. #7 uses `randomUUID()` (`../order-to-cash-nestjs/packages/shared-kernel/src/domain/unique-id.ts:27`); #8 uses `Guid.NewGuid()` (`../order-to-cash-dotnet/src/SharedKernel/UniqueId.cs:18`).
- **What their seeds use:** deterministic ids from #7's `deterministic.ts`, ported byte-for-byte by #8 (`../order-to-cash-dotnet/src/Seed/Domain/Deterministic/DeterministicId.cs:38-41`). They force the v4 version nibble and the 8–b variant, so they are v4-*shaped*.
- **The wire:** all 36 distinct UUIDs in #8's 12 golden envelopes have version nibble 4, and so do all 6 in `specs/shared/` (counted with `grep -rhoE <uuid> … | awk substr($0,15,1) | uniq -c`).
- **Where non-v4 ids appear:** only as #8 **unit-test fixtures** (`11111111-1111-1111-1111-111111111111`, `aaaaaaaa-…`, `22222222-…-222222222226`; e.g. `../order-to-cash-dotnet/tests/Projector.UnitTests/FactProjectionTests.cs:97-98,117-119`). #8's `UniqueId.From` admits them (it refuses only `Guid.Empty`, `UniqueId.cs:23`); #7's v4-only `from` (`unique-id.ts:6-7,32`) would refuse them.
- **Conclusion:** `domain-model.md` §2.5 says "UUID", not v4. No production value is non-v4, so both choices pass production data. #9's tolerant parse with v4 generation (armed: run 53) matches #8 and lets fixtures port unchanged. Correct.

**Q2. Does anything carry a reference form #9 refuses?**
- **Shared spec and goldens: nothing.** Every reference in `specs/shared/` and in #8's golden envelopes is canonical (`ORD-000011/18/41/42`, `DES-000010/31`, `INV-000010/16/27`, `CR-000004/39/66/87`). #8's seed writes `ORD-000001`, `DES-000001`, `INV-000001` and `CR-000001/7/8`.
- **But the wire contract is looser than #9's domain:** `openapi.yaml:1123-1141` and `asyncapi.yaml:1957-1976` use the pattern `^ORD-[0-9]{6,}$`, which admits `ORD-000000` and `ORD-0000001`.
- **And #7 sends one of those forms:** #7's saga integration test **SO8** publishes `stock.reserved.v1` with `orderReference: 'ORD-000000'` for an unknown order and expects it to be recorded as ignored `unknown_order` (`../order-to-cash-nestjs/apps/orders/src/saga-preconditions.integration.spec.ts:183-190`). If #9's Orders consumer parses the inbound `orderReference` through `OrderNumber.parse` before the correlation lookup, that contract-valid payload raises `order_number.invalid` instead of taking the `unknown_order` path.
- **Assessment:** not a `specs/shared/` defect. A pattern that is a superset of the domain's canonical form is legitimate on the wire; the domain choice is #9's and is disclosed.
- **Disposition:** accept for the kernel, and **file a backlog entry attached to feature 16 `order_saga_orchestrator`**: "SO8 ported verbatim, with `orderReference: ORD-000000`. An inbound fact's `orderReference` is never parsed through `BusinessReference.parse` ahead of the correlation lookup, or a refusal is classified as `unknown_order`, not as a poison message."

**Q3. Is `Money` bounded to int64 at construction consistent with "overflow guarded at the write boundary"?** Yes. It is the same per-operation semantics as both predecessors, not a second guard that changes behaviour.
- **#8:** `long` plus `checked(...)` on every add, subtract and multiply (`Money.cs:49,56,60`). An intermediate result past `long` throws, but it threw `OverflowException`, not a `DomainError`.
- **#7:** `Number.isSafeInteger` at construction (`money.ts:55`), so every intermediate `Money` was bounded at ±2⁵³.
- **#9:** every intermediate `Money` is bounded, and the error is the `DomainError` `money.invalid_amount`. Probe: `Money(2**63-1).add(Money(1)).subtract(Money(1))` is refused at the intermediate, exactly as #8's `checked` would be.
- **The only behavioural difference:** #9 raises a domain error where #8 raised a runtime exception, so the Gateway's problem mapping will see a 4xx-class domain code rather than a 500. Raw `int` intermediates inside an aggregate are unbounded in Python and are checked when they become a `Money`; that is more permissive than #8, never less.
- **What stays owed:** the write-boundary guard is still owed for any `bigint` column not written from a `Money`; see D8 for quantity.

**Q4. Does every Status-column citation exist literally?** Yes. All 19 back-ticked test names in the R1–R4 cells (`grep -oE '`test_[a-z0-9_]+`' | wc -l` gives 19) resolve to a `def <name>(` in the cited file: 19/19 OK. The sentinel works: a fabricated name `…dunderX` returned 0 matches. The cited paths are 5, all real.

## Independent arming table

Protocol: `cp` a backup, plant the mutant, clear `__pycache__` and `.mypy_cache`, run the ONE named test with `python -B -m pytest -x`, restore from the backup, compare with `filecmp.cmp(shallow=False)`, clear the caches, re-run. **All 64 runs: cmp identical, green re-run exit 0.** A "survived" mutant on an absence probe is a finding (D1–D4).

| # | Mutant | Test run | Result (verbatim, abbreviated) |
|---|---|---|---|
| 1 | `@property major_units` returning `amount / 100` | `test_r1_money_defines_exactly_the_expected_public_members` | KILLED: `Money gained or lost a public member: +{'major_units'}` |
| 2 | same | AST guard | KILLED: `line 117: true division \`/\`` |
| 3 | private `@property _major` → `"1242.50"` via `//`,`%` | all `test_money.py` | **SURVIVED** 66 passed (D1) |
| 4 | `if TYPE_CHECKING: def to_major(self) -> "float"` | AST guard | KILLED: `line 1: \`float\` used as …` (wrong line: D3 nit) |
| 11 | same, with the import present | all `test_money.py` | survived (the AST guard is the catcher, run 4) |
| 6 | `Money.__truediv__ = lambda …` after the class body | `test_r1_money_offers_no_division_…` | KILLED: `forbidden numeric protocol members: ['__truediv__']` |
| 7/8 | `__format__` → major-unit decimal string | all `test_money.py` / AST guard | **SURVIVED** 66 passed / passed (D1) |
| 9 | `__repr__` → major-unit decimal string | all `test_money.py` | **SURVIVED** 66 passed (D1) |
| 12–14 | `to_major -> Fraction` under `TYPE_CHECKING` | money tests / AST guard / import allowlist | **SURVIVED** ×3 (D2) |
| 15/16 | module-level `to_major_units -> Fraction` | money tests / AST guard | **SURVIVED** ×2 (D2) |
| 17 | private helper `self.amount * 10**-2` | AST guard | **SURVIVED** (D3, accepted residual) |
| 20/21 | `self.amount.__truediv__(100)` / `int.__truediv__(…)` | AST guard | **SURVIVED** ×2 (D3) |
| 19 | public class attribute `RATE = 100` | members test | KILLED: `+{'RATE'}` |
| 22/23 | M2 check deleted in `add` / `subtract` | `test_r2_money_raises_…` | KILLED: `DID NOT RAISE CurrencyMismatchError` |
| 24 | `__ge__` bypasses `compare` | `test_r2_each_ordering_operator_raises_across_currencies` | KILLED: `DID NOT RAISE CurrencyMismatchError` |
| 25 | **corrupt field:** error operands swapped | `test_r2_money_raises_…` | KILLED: `('GBP', 'EUR') == ('EUR', 'GBP')` |
| 26 | **corrupt field:** `multiply` currency hard-coded `"EUR"` | `test_m3_add_subtract_multiply_are_closed_…` | KILLED: `'EUR' == 'JPY'` |
| 27 | **corrupt field:** `subtract` operands swapped | same | KILLED: `Money(...) == Money(...)` |
| 28 | `isinstance` replaces `type is int` (admits `True`) | `test_r1_money_refuses_an_amount_that_is_not_a_plain_int` | KILLED: `DID NOT RAISE InvalidMoneyAmountError` |
| 29 | int64 bound deleted | `test_r1_money_refuses_an_amount_beyond_the_bigint_column` | KILLED: `DID NOT RAISE InvalidMoneyAmountError` |
| 30 | `__mul__` admits a bare `int` | `test_m3_multiplication_admits_a_quantity_and_nothing_else` | KILLED: `DID NOT RAISE TypeError` |
| 31 | currency `isalpha()` | `test_r1_money_refuses_a_malformed_currency_code` | KILLED: `DID NOT RAISE InvalidCurrencyCodeError` |
| 32 | M4 `is_negative` uses `<=` | `test_m4_negative_money_…` | KILLED: `assert not True … Money(amount=0 …).is_negative` |
| 33–35 | Quantity: `isinstance` (bool) / `< 0` (zero) / integral float admitted | `test_r3_quantity_refuses_…` | KILLED ×3: `DID NOT RAISE QuantityMustBePositiveError` |
| 36 | GLN weights swapped 3↔1 | `test_r4_gln_accepts_a_real_valid_gln` | KILLED: `'4006381333931' is not a valid GLN: check digit must be 7` |
| 37 | same | `test_r4_gln_refuses_wrong_length_…_bad_check_digit` | survived (expected: its bad inputs stay bad under any weighting; the accept side is the catcher) |
| 38 | same | `test_r4_every_single_digit_mutation_…` | KILLED: `DID NOT RAISE InvalidGlnError` |
| 39 | same | `test_r4_gln_check_digit_agrees_with_the_oracle_…` | KILLED: `000000000013 … assert 4 == 0` |
| 40 | `isascii()` dropped | `test_r4_gln_refuses_unicode_digits_…` | KILLED: `DID NOT RAISE InvalidGlnError` |
| 41 | all weights 1 | `test_r4_gln_accepts_a_real_valid_gln` | KILLED: `check digit must be 7` |
| 42–44 | JSON: BHD dropped / XYZ added / KWD 3→2 | parity test | KILLED: `BHD: in Python, missing from the JSON` / `XYZ: in the JSON, missing from Python` / `KWD: Python says 3, the JSON says 2` |
| 45–47 | Python: XYZ added / CLF dropped / OMR 3→0 | parity test (the parity test itself, not the 26-count test) | KILLED: `XYZ: in Python, missing from the JSON` / `CLF: in the JSON, missing from Python` / `OMR: Python says 0, the JSON says 3` |
| 48 | `exponent_of` ignores the table | `test_the_sa5_exponents` | KILLED: `assert 2 == 0 … exponent_of('JPY')` |
| 49 | truncation `sequence % 1_000_000` | `test_reference_grows_beyond_six_digits_…` | KILLED: `'ORD-000000' is not a valid ORD- business reference` |
| 50 | **sibling:** INV prefix → DES | `test_reference_is_the_prefix_plus_…` | KILLED: `'DES-000001' == 'INV-000001'` |
| 51/64 | **sibling:** CR code → INV's; ORD code → DES's | `test_the_four_error_codes_are_distinct_and_stable` | **SURVIVED** ×2 (D4) |
| 63 | **sibling:** CR code → INV's | `test_reference_refuses_malformed_text` | KILLED: `'invoice_reference.invalid' == 'credit_line_…'` |
| 52 | sequence 0 admitted | `test_reference_refuses_malformed_text` | KILLED: `DID NOT RAISE InvalidBusinessReferenceError` |
| 53/54 | `uuid1()` / nil admitted | UniqueId tests | KILLED: `all(...)` False / `DID NOT RAISE InvalidUniqueIdError` |
| 55–57 | Entity type compare deleted / pull doesn't clear / clear no-op | entity tests | KILLED: `Thing(...) != OtherThing(...)` / `('a','b') == ()` / `('a',) == ()` |
| 58 | mypy test snippet `/` → `//` | `test_mypy_strict_rejects_…` | KILLED: ``mypy --strict accepted `Money(10 // 3, "EUR")` … Success`` |
| 59 | source `amount: int \| float` | same | KILLED: ``mypy --strict accepted `Money(100.0, "EUR")` `` |
| 60–62 | kernel `dependencies = ["pydantic"]` / key deleted / `optional-dependencies` added | `test_package_declares_dependencies_as_an_empty_list` | KILLED: `assert ['pydantic'] == []` / `assert None == []` / `must not declare optional-dependencies` |

Invalid harness runs (disclosed, not counted as evidence):
- Run 5 was killed by a `NameError` (the `TYPE_CHECKING` import was missing); run 11 is the valid version.
- Run 10 was a Fraction mutant without the import, which survived trivially; run 15 is the valid version.
- Run 18 was killed by a `NameError`; it is moot, because the public-name allowlist catches any public method (runs 1 and 19).

**Gate 6b** (the exact `quality.sh:44-45` line, run under `set -euo pipefail` after `pytest --cov` over `packages/shared_kernel`, `tests/architecture` and `services`): I planted 101 uncovered statements, once in a **service domain** (`otc_orders/domain/value_objects/__init__.py`) and once in the **kernel** (`quantity.py`). Both gave `Coverage failure: total of 76 is less than fail-under=80`, exit 2. Both restores were `cmp` identical, and the green re-run gave exit 0 with `TOTAL 267 0 54 0 100%`. Both include globs are therefore armed. The population is 23 files: 9 kernel modules and 14 service-domain `__init__`s.

**Runtime type probes (no mutation):** `True`, `False`, `Fraction(1)`, `Fraction(5, 2)`, an `int` subclass, a numpy-like object with `__index__`/`__int__`, `Decimal(5)` and `5.0` are each refused by both `Money` and `Quantity`. `format(Money(124250, "EUR"))` currently gives `124250 EUR`, which is correct today; D1 is about the guard, not the present code.

## Defeat-list rows that apply

1. **Delete the behaviour** applies to every behavioural row. All killed.
2. **Corrupt a supplied field:** runs 25–27 and 42–47. All killed.
3. **Substitute a sibling identifier:** runs 50 and 63 killed; runs 51 and 64 **survived** in the literal-vs-literal test (D4).
4. **Shadow in comment or string:** feature 6's MUST_NOT_DETECT sentinels are unchanged and green. The four `float`/`Decimal`/`/` hits in kernel source (`grep -rnE "\bfloat\b|Decimal|/ " packages/shared_kernel/src`) are all docstrings: `errors.py:5`, `money.py:3`, `money.py:9`, `quantity.py:12`.
5. **Dead region:** `TYPE_CHECKING` with `"float"` is caught by the AST guard (run 4). With `Fraction` it is not caught (D2).
6. **Raw or triple-quoted string:** feature 6's sentinels cover it. Not applicable to the behaviour tests.
7. **Drop an optional element:** JSON entry drops (runs 42, 46).
8. **Literal to literal:** D4.
9. **Closer half satisfied, premise stale:** R1's ratification cites a record that does not exist yet (D5).
10. **Build output or caches:** caches cleared on every arm. `-B` was used. The 6b population was listed, not inferred.
11. **A form the instrument doesn't recognise:** D1 (dunder kinds), D2 (`Fraction`), D3 (`__truediv__` and `**`).
12. **A path the population never drives:** the member population skips private names and module scope (D1, D2).

## Ledger check (claims, not existence)

The ledger is in `progress/impl_shared_kernel.md`, as `sdd: false` requires. I spot-checked its citations: #7 `money.ts:4,88,109,149,159`, `unique-id.ts:6-7,27`; #8 `Money.cs:28,60,87`, `GLN.cs:65`, `OrderNumber.cs:52`, `Entity.cs:31`, `UniqueId.cs:18,23`. All say what the ledger claims. The exponent table, independently re-parsed, is equal across #7's `.ts`, #8's `.cs`, #8's JSON, #9's Python and #9's JSON: 26 entries each, all equal (`True`).

The row most likely to be assumed was "**no division / no float surface**, guarded by member population + `operator`-derived set + AST guard". It is only partly supplied: D1, D2 and D3.

## The R<n> → test mapping I verified

| Row | Tests | Verification |
|---|---|---|
| R1 (domain half; SCOPED, ratification pending its record) | `test_money.py` › the six `test_r1_*`; `test_mypy_rejects_float.py` › `test_mypy_strict_rejects_a_float_or_a_bare_int_in_money_arithmetic` | Exercised and armed (runs 1, 2, 6, 19, 28, 29, 58, 59). The absence half is incomplete (D1, D2). The API half is owed by feature 31, and its acceptance names it (verified). |
| R2 | `test_r2_money_raises_…`, `test_r2_each_ordering_operator_raises_…`, `test_r2_equality_…`, `test_r2_a_mismatch_at_either_operand_position_…` | Armed: runs 22–25 |
| R3 | `test_r3_quantity_refuses_…`, `test_r3_quantity_accepts_…`, `test_r3_quantity_has_no_float_accepting_entry_point` | Armed: runs 33–35 |
| R4 | `test_r4_gln_accepts_a_real_valid_gln`, `…_refuses_wrong_length_…`, `…_refuses_unicode_digits_…`, `test_r4_every_single_digit_mutation_…`, `test_r4_the_real_vectors_discriminate_the_weights` | Armed: runs 36, 38–41. The real vectors are independently valid under the left-to-right oracle. `0000000000000` is not relied on. |

## CHECKPOINTS.md walk

**C1, harness complete:**
- [x] The harness files exist.
- [x] `progress/current.md` and `progress/history.md` exist.
- [x] All seven agents are present.
- [x] `./init.sh` exits 0.
- [ ] Models declared in every agent definition: not re-walked this round. It is not this feature's subject; feature 2 owns it.

**C2, state coherent:**
- [x] At most one feature is `in_progress`. Before my edit, none was; feature 7 was `in_review`.
- [x] Every status is valid.
- [x] Every `done` feature has passing tests: 6 `monorepo_scaffold` is green in `quality.sh`.
- [x] `current.md` is not stale. init.sh section 4 passed.
- [x] No `blocked` feature lacks a reason.

**C3, architecture:**
- [x] `lint-imports` gives 10 kept, 0 broken (run, not eyeballed).
- [x] No cross-service imports (independence contract kept).
- [x] Shared runtime code stays within the three packages.
- [x] No `domain` package imports `otc_cqrs`.
- [x] `shared_kernel` declares `dependencies = []` (armed: runs 60–62).
- [ ] No float, Decimal or `/` in domain money arithmetic: **true of the code, but the guard proving it has the D1–D3 gaps**. I leave this box open until the guards close.
- [x] Kafka-fact versus NATS-RPC: not applicable, no interaction exists yet.
- [x] No stray debug output or context-free TODOs in the kernel.

**C4, verification real:**
- [x] `./quality.sh` exit 0, run by me.
- [x] Domain tests are pure: the import enumeration of `packages/shared_kernel/tests/*.py` shows only stdlib, `pytest` and `otc_shared_kernel`. `mypy` runs as a subprocess tool, not as an import.
- [x] Integration tests: not applicable, there are none.
- [x] Coverage: domain 100% and gated (armed), overall 98.04%.
- [x] No Jest, Karma or Jasmine.

**C5, session closed cleanly:**
- [x] No suspicious untracked files. My harness lives only in the scratchpad.
- [ ] History entry with effort record: not written, because the feature was rejected.
- [x] `feature_list.json` reflects the truth after my edit.
- [ ] The human has been told how to test: the leader does this at close.
- [x] Claude did not commit.

**C6:** not applicable (`sdd: false`).

**C7, second-reuse fidelity:**
- [x] `specs/shared/` is byte-identical to #8 and #7 (init.sh 5d), except the Status column and summary of `test-matrix.md`, which I checked.
- [x] There are no un-amended deviations. Q2 is a #9 design choice, not a spec change.
- [x] The R ids are #7's, and the Python tests satisfy the same requirement for R2–R4.
- [ ] Every inherited #8 finding accounted for: the implementer marks #8 D1 **avoided**. It **recurred** in a new form (D1 above); the effort entry must say so.
- [ ] Effort records: written only on approval.

## What must change before re-review

1. **D1:** an allowlist over every name in `vars(Money)` (public, private and dunder), armed with `__format__`, `__repr__`, a private property and a post-body assignment.
2. **D2:** ban `fractions` alongside `decimal` in the AST guard, and add a module-namespace allowlist for the kernel's public top-level names, with sentinels. The alternative is the leader's accept-with-trigger.
3. **D3:** add `__truediv__`, `__rtruediv__` and `__itruediv__` to the AST guard's truediv family, with sentinels, and report string-annotation violations at the real line. The alternative is a backlog entry attached to feature 13.
4. **D4:** make the error-code test read `ERROR_CODE` from production and assert distinctness, then re-arm it with run 64's mutant.
5. **D6, D7:** correct the `quality.sh:40-41` comment and the `errors.py:3-4` docstring.
6. **Leader:** D5 (a "scoped rows" paragraph under the coverage table, and the R1 ratification sentence in the closing history entry). File the two routed entries: D8 → feature 9 `db_orders`, and Q2/SO8 → feature 16 `order_saga_orchestrator`. Neither is rooted in `specs/shared/`, so no `SA-n` is proposed.
7. **The re-review will:** re-run runs 3, 7, 9, 12–17, 20, 21 and 64 (each must now be killed by a named test), re-arm one behavioural row per changed test file, and run `./quality.sh` once.

---

## Round 2 (2026-10-05)

**Verdict: APPROVED.** Every round-1 survivor is now killed by a named test, and every behavioural re-arm is killed. The round-1 must-change items 1–6 are all done.

Probing the new instruments' premises found **three new findings: 2 minor, 1 nit**. All are dispositioned **ACCEPTED, NOT FIXED**, each with a re-open trigger, and proposed as **one backlog entry attached to feature 13 `orders_aggregate`** for the leader to file. I did not write it into `feature_list.json`.
- None of them lets a major-unit surface onto `Money` itself; that is now held by three independent layers.
- Each needs either a new kernel *subpackage*, which is a visible structural change, or a deliberately unusual binding form.

### What I ran

- **Integrity of the sources first.** `money.py`, `business_reference.py`, `currency_exponent.py`, `entity.py`, `gln.py`, `quantity.py` and `unique_id.py` are each `cmp`-identical to my round-1 `rv/*.bak` backups. This independently confirms the leader's check after the implementer's hand-repaired harness crash.
- **Round-1 survivors, re-run with my own harness** (`rv/probes6.py`; raw results in `rv/arming.jsonl`, round 1 kept as `rv/arming_round1.jsonl`), each against the named test claimed as its killer.
- **Premise probes of the new instruments** (`rv/probes7.py`, plus a manual subpackage and service-domain run).
- **`./quality.sh` once, at the end:** exit 0. ruff: 112 files formatted, checks pass. mypy: `no issues found in 82 source files`. import-linter: `Contracts: 10 kept, 0 broken`. pytest: `390 passed`, overall coverage 98.04%. 6b: `TOTAL 267 0 54 0 100%`. Vitest: 1 passed. Build green.
- **`./init.sh`:** exit 0.
- **Matrix citations:** 20 back-ticked test names in R1–R4, 20 resolve, 0 missing. This includes the renamed allowlist test and the new text-form test.

### Round-1 survivors, re-run (every row: `cmp` identical, green re-run exit 0)

| R1 run | Mutant | Killer (verbatim) |
|---|---|---|
| 3 | private `_major` property | `test_r1_money_defines_exactly_the_allowlisted_members_of_every_kind`: `Money gained or lost a member: +['_major']`; also `test_money_class_body_binds_exactly_the_allowlisted_names_even_under_type_checking`: `+['_major']` |
| 7 | `__format__` → `1242.50 EUR` | allowlist: `+['__format__']`; `test_r1_every_text_form_of_money_shows_minor_units_never_a_major_unit_decimal`: `assert '124250' in '1242.50 EUR'` |
| 9 | `__repr__` → `1242.50 EUR` (class body) | text-form test: `assert '1242.50 EUR' == "Money(amount...rrency='EUR')"`; class-body test: `+['__repr__']` |
| 12–14 | `if TYPE_CHECKING: def to_major(self) -> Fraction` | class-body test: `+['to_major']`; AST guard: `line 14: \`from fractions import ...\``; module allowlist `[money]`: `+['Fraction', 'TYPE_CHECKING']` |
| 15/16 | module-level `to_major_units -> Fraction` | module allowlist: `+['Fraction', 'to_major_units']`; AST guard: `line 14: \`from fractions import ...\`` |
| 15c (new) | module-level `to_major_text -> str` (no Fraction) | module allowlist: `+['to_major_text']` |
| 17 | `self.amount * 10**-2` | AST guard: ``line 116: `**` with a negative or non-literal exponent`` |
| 20 / 21 | `self.amount.__truediv__(100)` / `int.__truediv__(…)` | AST guard: ``line 116: `truediv` family (`/` by another name)`` (×2) |
| 64 | `OrderNumber.ERROR_CODE` → despatch code | `test_the_four_error_codes_are_distinct_and_stable`: `At index 0 diff: 'despatch_reference.invalid' != 'order_number.invalid'` |

The reported line numbers are now real (14 is the planted import, 116 the planted body), so round 1's D3 nit is closed.

**Behavioural re-arm, one per changed test file:**
- `test_money.py`: M2 check deleted in `add`, killed (`DID NOT RAISE CurrencyMismatchError`).
- `test_quantity.py`: `< 0` admits zero, killed (`DID NOT RAISE QuantityMustBePositiveError`).
- `test_business_reference.py`: truncation `% 1_000_000`, killed (`'ORD-000000' is not a valid ORD- business reference`).
- `test_money_guard.py`: `/` in a property, killed (``line 117: true division `/` ``).
- `test_kernel_surface.py`: armed by runs 3, 12, 14, 15 and 15c above.

### Premise probes of the new instruments

Changing an instrument swaps its premises. These are the new premises and how each probe came out.

| Instrument / premise | Probe | Result |
|---|---|---|
| `vars(Money)` allowlist assumes a new member adds a *name* | post-body `Money.__repr__ = <major-unit lambda>` (name already exists) | Allowlist blind as expected. **Killed** by the text-form test (`'1242.50 EUR' == "Money(amount=124250, …)"`). |
| same | post-body `Money.__str__ = …` | **Killed** by the text-form test (`'1242.50 EUR' == '124250 EUR'`). |
| Text-form test checks only the empty format spec | post-body `setattr(Money, "__format__", …)` returning major units only for `spec == "major"` | Text-form test blind as expected. **Killed** by the `vars` allowlist (`+['__format__']`). The two layers cover each other. |
| Module allowlist assumes names are bound by `def`/`class`/`Assign(Name)`/`AnnAssign`/import | `(to_major_text,) = (lambda m: …,)` in `money.py` | **SURVIVED**: 291 kernel tests pass, and the AST guard file (82) passes. → **R2-2** |
| same | `(to_major_text := lambda m: …)` (walrus) | **SURVIVED**, 291 passed → R2-2 |
| same | `globals()["to_major_text"] = …` | **SURVIVED**, 291 passed → R2-2 |
| same | `for to_major_text in (lambda m: …,): pass` | **SURVIVED**, 291 passed → R2-2 |
| Module population assumes every kernel module is a top-level `*.py` (`KERNEL_DIR.glob("*.py")`) | new subpackage `otc_shared_kernel/text/__init__.py` with `def to_major_text(money) -> str` (ints only) | **SURVIVED**: `packages/shared_kernel/tests` + `tests/architecture` gave 383 passed. → **R2-1** |
| `**`/`pow` rule assumes the operation is spelled `**` or bare `pow(` | `(1).__pow__(-2)` inside the existing `is_zero` body (no new name) | **SURVIVED**: 291 kernel tests pass, the AST guard passes → **R2-3** |
| same, in a service domain (the module allowlist does not apply there) | `math.pow(10, 2)`, `operator.pow(10, -2)`, `(10).__pow__(-2)`, `math.sqrt(4)` in `otc_orders/domain/value_objects/__init__.py` | **SURVIVED** ×4 → R2-3. Each restore was confirmed byte-identical, and the green re-run gave 383 passed. |

### Round-2 findings, each with its disposition

- **R2-1 (MINOR), ACCEPTED, NOT FIXED: the kernel-surface population is not recursive.**
  - **Where:** `packages/shared_kernel/tests/test_kernel_surface.py`, in `test_the_kernel_module_population_is_the_literal_list` (`KERNEL_DIR.glob("*.py")`) and the parametrised module test.
  - **The gap:** a kernel subpackage is invisible to the module allowlist. The AST money guard *does* recurse (`rglob`), so `float`, `/`, `decimal` and `fractions` in a subpackage are still caught. Only an int-only major-unit text formatter escapes.
  - **Why it matters soon:** #8 put `MoneyText` in its SharedKernel (`../order-to-cash-dotnet/src/SharedKernel/MoneyText.cs`), used by domain errors such as `src/Orders/Domain/Errors/OrderTotalMustNotBeNegativeError.cs`. #9 is likely to add its equivalent in feature 13.
  - **Fix (one line):** use `rglob`, keyed by dotted module path.
  - **Re-open trigger:** the first directory created under `packages/shared_kernel/src/otc_shared_kernel/`, or the first human-money-text function added to the kernel.
- **R2-2 (MINOR), ACCEPTED, NOT FIXED: the module allowlist does not see every binding form.**
  - **The gap:** its AST binder misses tuple-unpacking targets, walrus, `for` targets and `globals()[…] =`. All four bind a real runtime attribute of `otc_shared_kernel.money`.
  - **Fix:** complement the AST scan, which is needed for `TYPE_CHECKING` regions, with a runtime `vars(module)` comparison against the same literal. The runtime check sees every form that executes.
  - **Accepted because** each form is a deliberate obfuscation, not a natural way to write a function. `Money`'s own surface, which R1 is about, is held by the `vars` allowlist, the class-body AST scan and the text-form behaviour test.
  - **Re-open trigger:** the same entry as R2-1.
- **R2-3 (NIT), ACCEPTED RESIDUAL: the pow family spelled as an attribute escapes the AST guard.**
  - **The gap:** `math.pow`, `operator.pow` and `__pow__`, together with `math.sqrt` and similar functions, are float-returning forms the AST guard does not recognise. This is the syntax-guard limit (defeat row 11) that round 1 already accepted for `math.*`.
  - **The backstop:** `type(amount) is int` at `Money` construction (round-1 run 28, armed), so no float can become a `Money`.
  - **Cheap improvement worth taking with the R2-1 fix:** treat `pow` and `__pow__` as an attribute (`operator.pow`, `x.__pow__`) like the truediv family.
  - **Re-open trigger:** a service domain computing a ratio or rate with `math.*`.

**Proposed backlog entry**, for the leader to file (id ≥ 201, attached to **feature 13 `orders_aggregate`**, the next feature to add domain money code and the likely home of `MoneyText`): "kernel surface guard: population recurses into subpackages; module allowlist also compared at runtime against `vars(module)`; AST money guard treats `pow`/`__pow__` as an attribute like the truediv family. Each is armed with the corresponding mutant from `progress/review_shared_kernel.md` Round 2 (subpackage `text/__init__.py`, tuple-unpacked formatter, `operator.pow(10, -2)`)." Nothing here is rooted in `specs/shared/`, so no `SA-n` is proposed.

### Leader actions, checked

- **D5:** the "Scoped rows, and what closing them would take" paragraph now sits under the coverage table and names R1 as ratified scoped, with its unproven leg and its closer (feature 31). The R1 cell and the paragraph both cite `progress/history.md` › `shared_kernel`. That entry is written with this approval (below), so the citation is now true.
- **D8:** routed into feature 9 `db_orders` acceptance ("every quantity column's range is enforced at the write boundary … 2**31 …"). Verified in `git diff feature_list.json`.
- **Q2/SO8:** routed into feature 16 `order_saga_orchestrator` acceptance ("#7's SO8 ported verbatim with orderReference ORD-000000 …"). Verified.
- **D6:** the `quality.sh:37-45` comment now describes the lowering arm. **D7:** the `errors.py` docstring names `unique_id.empty` with its #8 citation. Both are fixed.
- The implementer's report appends a correction: #8 D1 **recurred** in round 1 and is now avoided in fact. That is the honest classification, and the history entry carries it.

### CHECKPOINTS, round 2 (only the boxes that were open in round 1)

- [x] **C3:** no float, Decimal or `/` in domain money arithmetic. True of the code, and its guards now cover dunders, private members, the class body under `TYPE_CHECKING`, module scope (with the R2-2 residual), `fractions`, the truediv family and `**`/`pow`. The residuals R2-1 to R2-3 are dispositioned.
- [x] **C5:** the history entry, with its effort record, is written below.
- [x] **C7:** every inherited #8 finding is accounted for in the history entry, including D1's recurrence.
- [ ] **C5:** "the human has been told how to test". The leader does this at wrap-up.
- [ ] **C1:** agent model declarations. Not this feature's subject (feature 2).

### Closure actions taken by the reviewer

- Feature 7 `status` set to `done`, editing that one line, then I read `git diff feature_list.json`.
- I appended `progress/history.md` › `shared_kernel` with the effort record and the R1 ratification sentence. My role does not let me approve without that record, and the R1 cell already cites it. **The leader should amend this entry, not add a second one.**
