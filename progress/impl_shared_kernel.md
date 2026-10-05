# impl: shared_kernel (id 7, phase 5), full process (money domain), `sdd: false`

Result: kernel built, `./quality.sh` exit 0 (347 passed, was 75; overall coverage 98.04%; domain/kernel coverage 267 statements, 54 branches, 100%; mypy clean on 81 files; import-linter 10 kept, 0 broken; Vitest 1 passed; web build green), `./init.sh` exit 0. I did not touch `feature_list.json` (status stays `in_progress` for the leader's transition to `in_review`). No `tasks.md` exists (`sdd: false`).

## Files

Source, `packages/shared_kernel/src/otc_shared_kernel/`: `errors.py` (DomainError + 7 named errors), `money.py`, `quantity.py`, `gln.py`, `business_reference.py` (OrderNumber, DespatchReference, InvoiceReference, CreditLineReference), `unique_id.py`, `entity.py` (Entity, AggregateRoot), `currency_exponent.py`, `__init__.py` (exports).

Tests, `packages/shared_kernel/tests/`: `test_money.py`, `test_quantity.py`, `test_gln.py`, `test_business_reference.py`, `test_unique_id.py`, `test_entity.py`, `test_errors.py`, `test_currency_exponent.py` (includes the Python/JSON parity), `test_mypy_rejects_float.py` (subprocess `mypy --strict`).

Other: `apps/web/src/lib/currency-exponents.json` (new; 26 entries; #8 kept the same path), `quality.sh` section 6b (real gate), `specs/shared/test-matrix.md` Status cells of R1-R4 only (`git diff` is 4 lines). `tests/architecture/` untouched: no exemption was needed (no `float` name anywhere in the kernel source).

## Decisions and the answers to the brief's questions

- **(a) "known, seeded currency code" at construction.** Format check only in both: #7 `../order-to-cash-nestjs/packages/shared-kernel/src/domain/money.ts:4` (`/^[A-Z]{3}$/`, after `toUpperCase()` at `:159`, so #7 normalises lower case) and #8 `../order-to-cash-dotnet/src/SharedKernel/Money.cs:28,66-80` (length 3, `A`-`Z`, no normalisation). Neither consults a list; whether a code is seeded is the Orders catalogue's concern. #9: strict #8 shape (three ASCII capitals, `"eur"` refused, no normalisation: a value object that silently rewrites its input hides a bad caller).
- **(b) `==` across currencies.** #7 `equals` returns false (`money.ts:109`); #8 record-struct equality is false and only `CompareTo`/relational operators throw (`Money.cs:87`, remarks at `:11-22`). #9 chooses the same split: `==`/`!=` is the dataclass value equality (false, never raises), `<`, `<=`, `>`, `>=` and `compare` raise `CurrencyMismatchError`. Reason: M2 names "comparison" as the refused operation, and a hash/dict key or `in` check must not blow up; ordering needs a rate the model does not have.
- **(c) multiply by a bare `int`.** Not admitted by either (#7 `multiply(quantity: Quantity)` `money.ts:88`; #8 `Multiply(Quantity)` `Money.cs:60`). #9: `__mul__` returns `NotImplemented` for anything but `Quantity` (so `Money * 3`, `Money * True`, `Money * 2.5` raise `TypeError`), there is no `__rmul__`, `multiply(3)` raises `AttributeError`, and mypy rejects `.multiply(3)` (test below).
- **Python traps.** `type(x) is int` (not `isinstance`) in `Money`, `Quantity`: refuses `bool`, integral floats (`100.0`), `IntEnum`, `Decimal`, `str`. Amount is also bounded to signed 64-bit (`money.py` `MIN/MAX_MINOR_UNITS`), because the write model's column is `bigint` and Python ints do not overflow (#8 used `checked`, #7 `isSafeInteger`); an out-of-range result of add/subtract/multiply raises `InvalidMoneyAmountError` (code `money.invalid_amount`, the one code #8 does not have).
- **Quantity float entry point.** Not needed: the runtime type check refuses `2.0`/`2.5`/`nan`. #8's `From(double)` existed only because C# cannot express "fractional" in a constructor; `Quantity` has exactly one public member, `value` (asserted by `test_r3_quantity_has_no_float_accepting_entry_point`). Hence no exemption in the AST guard to key (#8 D7 moot).
- **GLN.** Validator is `value.isascii() and value.isdigit()` plus length 13 and `type is str`; `isdigit()` alone accepts Arabic-Indic, fullwidth and superscript digits (the test feeds all three). Check-digit algorithm as `domain-model.md` 2.4.
- **Business references.** One generic shape, four prefixes (recommended by the leader; #7 built all four `business-reference.ts:73-133`, #8 only `OrderNumber`, `OrderNumber.cs`; the spec places all four in the kernel). Divergence from both, disclosed: a reference is canonical (strictly positive sequence, zero-padded to six, no extra leading zero), so `ORD-0000001` and `ORD-000000` are refused where #8's regex `^ORD-\d{6,}$` (`OrderNumber.cs:52`) accepted them; reason: `parse(str(x)) == x` and a single spelling per sequence. Sequence capped at int64 (the allocating counter row is a bigint). Error codes: `order_number.invalid` (#8's), plus `despatch_reference.invalid`, `invoice_reference.invalid`, `credit_line_reference.invalid`.
- **UniqueId.** Version 4 in both (#7 `unique-id.ts:27` `randomUUID()`; #8 `UniqueId.cs:18` `Guid.NewGuid()`); `uuid.uuid4()`. Parsing: any non-nil UUID in canonical hyphenated spelling (#8 refuses only the empty Guid, `UniqueId.cs:23`; #7 insists on v4 in parse, `unique-id.ts:6`). I followed #8 because an `eventId` or seed key arrives from outside; recommend the leader confirm if a stricter v4-only parse is wanted.
- **Entity / AggregateRoot.** Equality = same concrete type and same id (#8 `Entity.cs:31`; #7 compared id only, `entity.ts`, no type). Events are typed `object` (the fact envelope belongs to `contracts`, and #7's `DomainEventEnvelope` placement was `event-envelope.ts`, R11, not this feature). API: `domain_events` (tuple copy), `_raise_event`, `pull_domain_events()` (read + clear, #7 `pullDomainEvents`), `clear_domain_events()` (#8 `ClearDomainEvents`).
- **Exponent table.** Compared entry by entry by script (this session): #7 `currency-exponent.ts:36-65` parsed = 26 entries, #8 `CurrencyExponent.cs:76` parsed = 26, #8's `apps/web/src/lib/currency-exponents.json` = 26, and `d7 == d8 == json8` printed `True`. #9's table is identical to all three (26 entries: 16 zero-digit, 7 three-digit, CLF/UYW four-digit, UYI zero; default 2). JSON location `apps/web/src/lib/currency-exponents.json`. Parity test `test_the_json_export_for_the_web_equals_the_python_table_in_both_directions` uses a duplicate-key-detecting loader and a type check (`"0"` and `False` are divergences).

## Ported-idiom ledger

| Idiom | #7 relied on | #8 supplied | #9 supplies, guarded by |
|---|---|---|---|
| int minor units, no float | `Number.isInteger`/`isSafeInteger` (`money.ts:51-57`) | `long MinorUnits`, no double member (`Money.cs:26`), reflection rules after D1 | `type(...) is int` in `__post_init__`; `test_r1_money_refuses_an_amount_that_is_not_a_plain_int`, `test_r1_money_defines_exactly_the_expected_public_members`, `test_r1_money_offers_no_division_conversion_or_rounding_dunder`, `test_r1_money_has_no_float_decimal_or_complex_in_any_signature`, AST guard `test_money_guard_finds_no_violation_in_domain_or_shared_kernel` |
| no division | no `divide` method (`money.ts` has none) | no operator `/` | no `__truediv__`/`__floordiv__`/`__mod__`/etc.; guard derives the forbidden set from the `operator` module (not a word list) |
| overflow | safe-integer bound | `checked(...)` (`Money.cs:44,53,60`) | int64 bound in `__post_init__`; `test_m3_arithmetic_beyond_the_bigint_column_is_refused_not_wrapped` |
| M2 | `assertSameCurrency` (`money.ts:149`) | `EnsureSameCurrency` (`Money.cs:87`) | `_require_same_currency` in add/subtract/compare, each ordering operator via compare; `test_r2_*` |
| equality across currencies | `equals` false | record-struct equality | dataclass `eq`; `test_r2_equality_across_currencies_is_false_not_an_error` |
| value-object immutability | `private readonly` fields | `readonly record struct` | `@dataclass(frozen=True, slots=True)`; `test_r1_money_is_immutable_hashable_and_slotted`, GLN/Quantity/reference immutability tests |
| GLN mod-10 + sweep | `computeCheckDigit` + exhaustive mutation sweep (`gln.spec.ts`) | `ComputeCheckDigit` (`GLN.cs`), five vectors, no sweep | same algorithm; independent left-to-right oracle in the test; `test_r4_every_single_digit_mutation_of_a_valid_gln_is_rejected` (13 x 9 = 117 mutants per vector, 7 vectors) |
| ASCII digits only | `/^\d{13}$/` (JS `\d` is ASCII) | `char.IsAsciiDigit` (`GLN.cs:65`) | `isascii() and isdigit()`; `test_r4_gln_refuses_unicode_digits_whitespace_and_signs` |
| references grow past 6 digits | `padStart` then refuses length != 6 (`business-reference.ts:55-58`: #7 truncates by refusing) | `ToString("000000")` grows (`OrderNumber.cs`) | `f"{n:06d}"`; `test_reference_grows_beyond_six_digits_rather_than_truncating` |
| UniqueId | v4 string | `Guid` | `uuid.UUID` wrapper; `test_new_generates_a_distinct_version_4_uuid_inside_the_domain` |
| entity identity | id only (`entity.ts`) | `GetType()` + id | type + id; `test_entities_of_different_types_with_the_same_id_are_not_equal` |
| exponent table | literal Record after its Intl defect | literal dictionary + JSON parity test | `MappingProxyType` literal + JSON parity both directions, `test_parity_*` instrument tests |
| `dependencies = []` | package.json | csproj has no PackageReference | feature 6's `test_package_declares_dependencies_as_an_empty_list[shared_kernel]` (armed below) |

Not ported: #8's `Quantity.From(double)` (deliberately: see above); #8's `MoneyText` and `DomainEventEnvelope` (not feature 7's acceptance; R11 stays TODO and `MoneyText` belongs to the presentation boundary / phase 16).

## R to test mapping (all rows also written in `specs/shared/test-matrix.md`)

- R1 (domain half; SCOPED, unratified): `test_money.py` > `test_r1_money_represents_1242_50_eur_as_124250_minor_units_no_decimal_representation`, `test_r1_money_defines_exactly_the_expected_public_members`, `test_r1_money_offers_no_division_conversion_or_rounding_dunder`, `test_r1_money_has_no_float_decimal_or_complex_in_any_signature`, `test_r1_money_refuses_an_amount_that_is_not_a_plain_int`, `test_r1_money_refuses_an_amount_beyond_the_bigint_column`; `test_mypy_rejects_float.py` > `test_mypy_strict_rejects_a_float_or_a_bare_int_in_money_arithmetic`. API half (payload, read model, every response) cannot be proven yet; I named feature 31 `api_tests` as closer and wrote in the cell that ratification is NONE YET. Action for the leader: ratify (or not) per matrix rule 3(b), and add R1's API half to feature 31's acceptance (#8 lesson: its gateway feature shipped without naming R1). I did not edit `feature_list.json`.
- R2: `test_r2_money_raises_a_domain_error_when_eur_and_gbp_are_added_subtracted_or_compared`, `test_r2_each_ordering_operator_raises_across_currencies` (4 operators), `test_r2_equality_across_currencies_is_false_not_an_error`, `test_r2_a_mismatch_at_either_operand_position_is_refused`.
- R3: `test_quantity.py` > `test_r3_quantity_refuses_zero_negative_fractional_bool_and_non_int_and_creates_nothing` (19 inputs), `test_r3_quantity_accepts_a_strictly_positive_int`, `test_r3_quantity_has_no_float_accepting_entry_point`.
- R4: `test_gln.py` > `test_r4_gln_accepts_a_real_valid_gln` (6 real vectors + all-zero), `test_r4_gln_refuses_wrong_length_non_digits_and_a_bad_check_digit`, `test_r4_gln_refuses_unicode_digits_whitespace_and_signs`, `test_r4_every_single_digit_mutation_of_a_valid_gln_is_rejected`, `test_r4_the_real_vectors_discriminate_the_weights`, `test_r4_gln_check_digit_agrees_with_the_oracle_over_a_wide_sweep`.
- Matrix summary counts (0/0/63) and the coverage-summary prose were NOT edited (brief: Status cells only); the leader should reconcile them (3 green, 1 scoped).

GLN vectors: `4006381333931` (EAN-13/GS1 worked example), `4890123456787`, `9520012345605`, `1234567890128` (hand-worked in the test comment: sum 92, check 8), `9501101530003`, `0614141000036`, `7350053850019`; `0000000000000` is tested as valid but declared worthless as evidence (the swap test shows it is valid under swapped weights). An earlier vector, `5012345678900`, survived the swapped-weights oracle (check digit 0 under both), so `test_r4_the_real_vectors_discriminate_the_weights` caught my own bad vector and I replaced it.

## Arming table

Harness: `arm.py` in the session scratchpad: copy to backup, plant the mutant, clear `__pycache__` and `.mypy_cache`, run the ONE named test file with `.venv/bin/python -B -m pytest -x`, restore from the backup, `filecmp.cmp(shallow=False)`, clear caches, re-run green. Logs: scratchpad `arming1-4.log`. Every row: mutant run exit 1 unless noted, `cmp` identical, green re-run exit 0. (`.venv/bin/python` directly, not `uv run`, so a mutated `pyproject.toml` could not trigger a re-lock; `uv.lock` untouched.)

| Claim | Mutant | Catching test (verbatim failure, abbreviated) |
|---|---|---|
| M2 add | removed the currency check in `add` | `test_r2_money_raises_a_domain_error_...`: `Failed: DID NOT RAISE CurrencyMismatchError` |
| M2 subtract | same in `subtract` | same test, same message |
| M2 compare | same in `compare` | same test, same message |
| M2 `<` / `<=` / `>` / `>=` (4 mutants, one operator each bypassing `compare`) | `return self.amount < other.amount` etc. | `test_r2_each_ordering_operator_raises_across_currencies[lt]` / `[le]` / `[gt]` / `[ge]`: `DID NOT RAISE CurrencyMismatchError` (each only its own parameter) |
| M2 `==` is false | `__eq__` that raises on mismatch | `test_r2_equality_across_currencies_is_false_not_an_error`: `CurrencyMismatchError: ... 'EUR' and 'GBP'` |
| M3 no `__truediv__` | added | `test_r1_money_offers_no_division_conversion_or_rounding_dunder`: `Money defines forbidden numeric protocol members: ['__truediv__']` |
| M3 no `__float__` | added (`-> int`, so the AST guard cannot be the catcher) | same test: `['__float__']`; with `-> float` the AST guard catches it instead (row below) |
| M3 `__rtruediv__`, `__floordiv__`, `__round__` | added each | same test: `['__rtruediv__']`, `['__floordiv__']`, `['__round__']` |
| M3 no extra public member | `major_units()` added | `test_r1_money_defines_exactly_the_expected_public_members`: `Money gained or lost a public member: +{'major_units'}` |
| M3 multiply admits Quantity only | `__mul__` accepts `int` | `test_m3_multiplication_admits_a_quantity_and_nothing_else[3_0]`: `DID NOT RAISE TypeError` |
| M1 bool | `isinstance` instead of `type is` | `test_r1_money_refuses_an_amount_that_is_not_a_plain_int[bool-True]`: `DID NOT RAISE InvalidMoneyAmountError` |
| M1 integral float | type check deleted | same test `[float-100.0]` |
| M1 bigint | upper bound x4 | `test_r1_money_refuses_an_amount_beyond_the_bigint_column[9223372036854775808]` |
| currency format | `isalpha()` instead of A-Z | `test_r1_money_refuses_a_malformed_currency_code[str-'eur']` |
| M4 sign | `is_negative` uses `<=` | `test_m4_negative_money_is_representable_...`: `assert not True ... Money(amount=0, ...).is_negative` |
| M4 negatives representable | constructor refuses negatives | `test_r1_money_holds_the_whole_int64_range[-9223372036854775808]`: `InvalidMoneyAmountError` |
| R3 zero | `<= 0` -> `< 0` | `test_r3_quantity_refuses_...[int-0]`: `DID NOT RAISE QuantityMustBePositiveError` |
| R3 negative | `<= 0` -> `== 0` | `...[int--1]` |
| R3 bool | `isinstance` | `...[bool-True]` |
| R3 float | type check deleted | `...[bool-True]` (first parameter reached under `-x`; the float cases are in the same parametrization) |
| R3 no float entry point | `from_number` classmethod added | `test_r3_quantity_has_no_float_accepting_entry_point`: `assert {'from_number', 'value'} == {'value'}` |
| R4 weights swapped (3 and 1 exchanged) | weights `1 if distance%2==0 else 3` | `test_r4_gln_accepts_a_real_valid_gln[4006381333931]`: `InvalidGlnError: ... check digit must be 7`; also the mutation sweep, the wide sweep and the discrimination test depend on it; the all-zero vector alone would not have caught it |
| R4 Unicode digits | `isdigit()` without `isascii()` | `test_r4_gln_refuses_unicode_digits_whitespace_and_signs[...Arabic-Indic...]`: `DID NOT RAISE InvalidGlnError` |
| R4 check digit skipped | `if False:` | `test_r4_gln_refuses_wrong_length_non_digits_and_a_bad_check_digit`: `DID NOT RAISE` |
| R4 length not checked | length condition deleted | same test: `IndexError: string index out of range` (a mutant that leaks a non-domain error is also a finding) |
| R4 `(10 - s%10)%10` | outer `%10` dropped | `test_r4_gln_accepts_a_real_valid_gln[0000000000000]`: `check digit must be 10` |
| OrderNumber truncation | `sequence % 1_000_000` | `test_reference_grows_beyond_six_digits_rather_than_truncating[ORD]`: `'ORD-000000' is not a valid ORD- business reference` |
| canonical spelling | check deleted (twice, once keeping only a leading-zero rule) | `test_reference_refuses_malformed_text[ORD]`: `DID NOT RAISE InvalidBusinessReferenceError` |
| prefix enforced | `startswith` check deleted | same test |
| sibling prefix (substitute a valid sibling) | DES prefix set to `ORD` | `test_reference_is_the_prefix_plus_a_zero_padded_sequence`: `assert 'ORD-000001' == 'DES-000001'` |
| UniqueId v4 | `uuid1()` | `test_new_generates_a_distinct_version_4_uuid_inside_the_domain`: `assert False where False = all(...)` |
| UniqueId nil | nil check deleted | `test_parse_refuses_anything_but_a_canonical_non_nil_uuid_string['00000000-...']` |
| UniqueId canonical | canonical-spelling check deleted | `test_parse_refuses_a_36_character_string_that_uuid_would_still_read` |
| Entity type | type comparison deleted | `test_entities_of_different_types_with_the_same_id_are_not_equal`: `assert Thing(...) != OtherThing(...)` |
| Entity id | id comparison deleted | `test_entities_with_different_ids_are_not_equal` |
| AggregateRoot pull clears | `clear()` removed from pull | `test_pull_domain_events_reads_and_clears`: `assert ('a', 'b') == ()` |
| AggregateRoot clear | `pass` body | `test_clear_domain_events_discards_without_returning`: `assert ('a',) == ()` |
| per-instance event list | all instances share one list | `test_the_returned_events_are_a_copy_...`: `assert ('a','b','a','b') == ('a','b')` |
| table to JSON, 5 shapes | JSON: BHD dropped; XYZ added; JPY 0 to 2; duplicate `JPY`; `"JPY": "0"` | `test_the_json_export_for_the_web_equals_...`: `assert ['BHD: in Python, missing from the JSON'] == []`, `['XYZ: in the JSON, missing from Python']`, `['JPY: Python says 0, the JSON says 2']`, `duplicate keys in the JSON export: ['JPY']`, `['JPY: ... the JSON says '0'']` |
| table to JSON, Python side | Python: BHD dropped; JPY 0 to 2; XYZ added; EUR 2 added | `test_the_sa5_exponents` (`exponent_of('BHD') == 3` fails), same for JPY, and `test_the_table_is_the_literal_twenty_six_entries...`: `assert 27 == 26` (both the XYZ and the redundant-EUR mutants). Note: an added Python-only entry is caught by the 26 count and, equally, by the parity test (not run first under `-x`) |
| mypy rejects `/` | `Money.amount: float` | `test_mypy_strict_rejects_a_float_or_a_bare_int_in_money_arithmetic[Money from a float literal]`: `mypy --strict accepted ... Success: no issues found in 1 source file` |
| same, Quantity | `Quantity.value: int \| float` | `[Quantity from true division]`: `mypy --strict accepted Quantity(7 / 2)` |
| mypy test snippet armed with `//` | test snippet `Money(10 / 3` changed to `Money(10 // 3` | `mypy --strict accepted `Money(10 // 3, "EUR")` (Money from true division): Success: no issues found in 1 source file` |
| AST money guard: float | `def __float__(self) -> float` in `money.py` | `test_money_guard_finds_no_violation_in_domain_or_shared_kernel`: `line 112: \`float\` used as call, annotation or value` |
| AST guard: `/` | `self.amount / 1` | `line 55: true division \`/\`` |
| AST guard: decimal | `from decimal import Decimal` | `line 14: \`from decimal import ...\`` |
| import allowlist, kernel | `import pydantic` in `money.py` | `test_domain_and_shared_kernel_import_only_the_allowlist`: `line 14: import \`pydantic\` is outside the domain import allowlist` |
| import-linter | same mutant | `lint-imports`: `otc_shared_kernel imports no framework and not otc_cqrs BROKEN ... otc_shared_kernel.money -> pydantic (l.14)`; restored, 10 kept 0 broken |
| `dependencies = []` | `dependencies = ["pydantic"]` in the kernel's pyproject | feature 6's `test_package_declares_dependencies_as_an_empty_list[shared_kernel]`: `AssertionError: packages/shared_kernel must declare dependencies = []` |
| 6b gate | only `test_quantity.py` run, then the exact 6b command | `Coverage failure: total of 49 is less than fail-under=80`, exit 2. A threshold "raised above the measured value" is impossible because the measured value is 100% and `coverage` rejects `--fail-under` above 100, so I lowered the measurement instead (same command, fewer tests); the gate is wired as `--fail-under="${DOMAIN_COVERAGE_MIN:-80}"` |

Surviving mutants found and handled (the arming earned its keep):
1. `len(digits) < _MIN_DIGITS` in `business_reference.py` survived: it was dead, subsumed by the canonical-spelling check (`"00001"` fails `digits != f"{n:06d}"`). Source simplified (redundant clause removed, comment names the subsumption), canonical check re-armed (rows above).
2. `Entity.__hash__` using `hash(self._id)` instead of `hash((type(self), self._id))` survives: an equivalent mutant (equal objects still hash alike; equal hashes for unequal objects are legal). Accepted, not tested; stated here rather than hidden.
3. My first `UniqueId v1` arm replaced the text in a docstring (not the call) and "survived": a defeat-list row 4 slip in the harness, redone on the `return` line (killed).
4. A first GLN vector survived swapped weights (above).

## Defeat-list walk (against my own guards)

1 delete the behaviour: applies to every row above (each check deleted once). 2 corrupt a supplied field: JSON exponent changed/added/dropped, prefix changed, vector digit sweep (117 mutants). 3 substitute a sibling identifier: DES prefix set to ORD (killed); JSON `XYZ` vs python table; applies to currencies EUR/GBP in R2. 4 shadow the pattern in a comment or string: applies to the AST/allowlist guards (feature 6's `MUST_NOT_DETECT` sentinels; my own harness slipped once, docstring `uuid4`); the money guard walks real kernel files. 5 dead region (`if False:` / `TYPE_CHECKING`): the AST guard walks those (feature 6 sentinels); `if False:` used as my GLN check mutant. 6 raw or triple-quoted string: covered by feature 6's sentinels; not applicable to my behaviour tests. 7 drop an optional element: the JSON `UYI` and `BHD` entries, the `-` sign and whitespace variants. 8 compare a literal to a literal: the mypy test asserts the checker's real output for a real snippet, with `//` controls that must pass; the parity test compares two independently loaded tables, with a non-empty assertion; the oracle is a second formulation rather than the code under test. 9 satisfy the closer half and leave the premise stale: applies to the exponent parity (the JSON loader rejects duplicates and non-int), R1 split with its unproven leg named. 10 build output or caches join the population: caches cleared on every restore; `.import_linter_cache` cleared after the lint arm; `guarded_files` reads `src/**/*.py`, `__pycache__` holds no `.py`. 11 a form the instrument does not recognise: the "no division" guard tests behaviour (`price / 3` raises `TypeError`, `float(price)`, `round(price)`, `3 * price`) AND the member population derived from `operator`, rather than one pattern. 12 served through a path the population never drives: ordering operators tested one by one, both operand orders, via `compare` and the operators; `Money.__mul__` reached by operator and by `multiply`.

## What I could not do, and why

- Could not ratify R1's scoped row (I am the author; rule 3(b)); it is left unratified and blocks the gate until the leader or maintainer records a ratification.
- Could not arm 6b by raising the threshold above 100%; armed by lowering the measured value instead (disclosed above).
- `Entity.__hash__` type component is not guarded (equivalent mutant).
- The web side of the JSON export (Vitest import, `resolveJsonModule`) is phase 16; only the committed file and the Python-side parity exist.
- `test_mypy_rejects_float.py` costs about 6 seconds (8 cold `mypy` subprocesses with a per-test cache directory); acceptable, noted.

## #8's shared_kernel findings

- **Reopen: guards never scanned the kernel** (domain purity and no-decimal rules selected namespaces that excluded `SharedKernel`): **avoided**. `guarded_files` includes `packages/shared_kernel/src` and this session's arms planted `float`, `/`, `Decimal` and `pydantic` in `otc_shared_kernel/money.py`: the AST guard and allowlist failed naming the file and line, and import-linter reported `otc_shared_kernel.money -> pydantic (l.14)`.
- **D1: float/double surface** (only `decimal` guarded): **avoided**. The surface is guarded by member population (a literal public set; every `operator` dunder not on the allowed list; the conversion dunders), by type hints of every method and property (`float`, `Decimal`, `complex` in any hint), and by behaviour; the AST guard bans `float`, `/` and `decimal`. Arms: `major_units`, `__float__ -> int`, `__truediv__`, `__round__`, `__floordiv__`, `__rtruediv__` each killed, plus `float` annotation by the AST guard.
- **D5: sibling references not built** (a decision #8 deferred): **avoided**: all four built with one generic shape, divergence from #8's looser regex disclosed.
- **D6: stale build after restore**: **avoided**: every restore was `cp` from backup plus `filecmp.cmp(shallow=False)`, `__pycache__` and `.mypy_cache` cleared, `-B` on every arm run, then a green re-run (all `cmp True` above). Python has no compile step; the harness is the protocol.
- **D7: exemption keyed too loosely**: **avoided by not needing one**: there is no float-accepting entry point and no exemption in `tests/architecture/`.
- **The `0000000000000` GLN**: **avoided**: it is tested but declared worthless as evidence; six real vectors, an independent left-to-right oracle, the exhaustive single-digit sweep (with `gcd(3, 10) = 1` stated), and a test that the vectors discriminate swapped weights (which also caught one of my own vectors).

## Surprises

- `str.isdigit()` accepts `"¹"` (superscript one) and `"١"`; `isascii()` first is mandatory (both tests feed them).
- Ruff `UP037` wanted quotes removed from `-> "Money"` inside the class (Python 3.14 deferred annotations); the codebase therefore writes unquoted forward references.
- `ruff format` rewrote my `"ÉUR"` escapes to literal characters, tripping `RUF001`; fixed with a targeted `noqa` beside the parameter list.
- A mutant that deletes the GLN length check leaks `IndexError`, not a `DomainError`: the test catches it only as a failure to raise `InvalidGlnError`.
- Section 6b's old `|| true` masked everything; it is now plain `coverage report ... --fail-under`, relying on `set -euo pipefail`.

## Fix round 1 (review `progress/review_shared_kernel.md`, REJECTED round 1)

**Correction to "#8's shared_kernel findings" above (appended, the original line is left as written):** the line "D1: float/double surface ... **avoided**" was wrong. #8 D1 **recurred** in a new form: my member test inspected public names plus a word list of dunders, so `__format__`, `__repr__` and private members were not inspected (reviewer runs 3, 7, 9: 66 passed). It is now **avoided in fact**, by the allowlists and behaviour test below, and the arms in the table were made with the reviewer's exact mutants.

Changes: D1 `test_money.py` (literal allowlist `MONEY_MEMBERS` over every name in `vars(Money)`, renamed test `test_r1_money_defines_exactly_the_allowlisted_members_of_every_kind`; new behaviour test `test_r1_every_text_form_of_money_shows_minor_units_never_a_major_unit_decimal`, needed because `__repr__`/`__format__` are names the dataclass already owns, so a name allowlist cannot see a replaced body), `test_quantity.py` (same allowlist, `QUANTITY_MEMBERS`). D2 new `test_kernel_surface.py` (AST allowlist of top-level names of every kernel module, class-body names of `Money` including `if TYPE_CHECKING:` regions, and the kernel module population) and `fractions` banned next to `decimal` in `tests/architecture/test_money_guard.py` (both import forms and dynamic). D3 same guard: `__truediv__`/`__rtruediv__`/`__itruediv__` as name, attribute, `def` or `getattr` string; `**`, `**=` and `pow(...)` flagged unless the exponent is a non-negative int literal (rule chosen: a negative, float or non-literal exponent can yield a float, so it is refused; `2 ** 63` stays legal; the backstop for the residual `math.*` forms is `type(amount) is int` at construction, armed earlier as "M1 integral float"); a quoted annotation now reports its real line (`test_a_violation_inside_a_quoted_annotation_is_reported_at_its_real_line`); 20 new must-detect and 4 must-not-detect sentinels. D4 `test_the_four_error_codes_are_distinct_and_stable` reads `ERROR_CODE` from the production classes and asserts distinctness. D6 `quality.sh` comment and D7 `errors.py` docstring corrected (`unique_id.empty`, `InvalidUniqueIdError.cs:11`). Matrix R1 cell: renamed test cited, the new text-form test added (Status column only; all cited names verified to exist literally, 0 missing).

Harness incident, disclosed: my first fix-round arm run crashed (a harness bug: a list passed as a selection) after planting the module-level `to_major_units` mutant and before restoring it, so the second run started from a mutated `money.py` and its first rows were meaningless (its green re-runs failed, which exposed it). I removed the planted block by hand, confirmed `ruff format --check`, the allowlist tests (exact name sets) and the whole suite green, fixed the harness to restore in a `finally`, and re-ran every arm below from a clean file; the table is from that clean re-run. There is no pre-mutation backup of `money.py` to `cmp` against for that one hand repair; the exact-name allowlists and the 390-test run are the evidence it equals the reviewed file.

Arming (clean re-run; mutant planted in `money.py` unless noted; every row `cmp` identical, green re-run exit 0; the catcher is the first test file that fails, with its verbatim message):

| Review run | Mutant | Killed by |
|---|---|---|
| 3 | private `@property _major` (`//`, `%`) | `test_money.py::test_r1_money_defines_exactly_the_allowlisted_members_of_every_kind`: `Money gained or lost a member: +['_major']`; also `test_kernel_surface.py::test_money_class_body_binds_exactly_the_allowlisted_names_even_under_type_checking`: `+['_major']` |
| 7/8 | `__format__` -> "1242.50 EUR" | same allowlist test: `+['__format__']`; class-body test: `+['__format__']` |
| 9 | `__repr__` -> "1242.50 EUR" | `test_r1_every_text_form_of_money_shows_minor_units_never_a_major_unit_decimal`: `assert '1242.50 EUR' == "Money(amount...currency='EUR')"`; class-body test: `+['__repr__']` (the `vars` allowlist cannot see this one: `__repr__` is already a generated name, hence the behaviour test) |
| 12-14 | `if TYPE_CHECKING: def to_major(self) -> Fraction` in the class | `test_money_class_body_binds_...`: `Money's class body changed: +['Fraction', 'to_major']`; AST guard `test_money_guard_finds_no_violation_in_domain_or_shared_kernel`: `line 113: from fractions import ...`. (`test_money.py` alone survives: the block never executes.) |
| 15/16 | module-level `def to_major_units(...) -> Fraction` | `test_kernel_surface.py::test_every_kernel_module_binds_exactly_the_allowlisted_top_level_names[money]`: `money.py top-level names changed: +['Fraction', 'to_major_units']`; AST guard: `line 34: from fractions import ...` |
| 17 | `self.amount * 10**-2` | AST guard: ``line 113: `**` with a negative or non-literal exponent`` |
| 20 | `self.amount.__truediv__(100)` | AST guard: ``line 113: `truediv` family (`/` by another name)`` |
| 21 | `int.__truediv__(self.amount, 100)` | AST guard: same message |
| 64 | `OrderNumber.ERROR_CODE` set to the despatch code | `test_business_reference.py::test_the_four_error_codes_are_distinct_and_stable`: `assert ['despatch_re...ence.invalid'] == ['order_numbe...ence.invalid']` |
| (6, re-armed) | `Money.__truediv__ = ...` after the class body | allowlist test: `+['__truediv__']` |
| (new) | `Quantity.__float__` | `test_quantity.py::test_r3_quantity_has_no_float_accepting_entry_point`: name sets differ |

Guard sentinels are in `test_money_guard.py` (`MUST_DETECT` now includes: `import fractions`, `from fractions import Fraction`, star form, dynamic `import_module`/`__import__("fractions")`, `__truediv__` call, `int.__truediv__`, `__rtruediv__` and `__itruediv__` access, `def __truediv__`, `def __rtruediv__`, `getattr(..., "__truediv__")`, `10 ** -2`, `10 ** n`, `4 ** 0.5`, `x **= -1`, `pow(10, -2)`, `pow(10, n)`, `TYPE_CHECKING` fractions; `MUST_NOT_DETECT` adds non-negative literal exponents, the truediv name inside a docstring or a longer string, and `fractions` only inside a string).

Gate: `./quality.sh` exit 0 once at the end: ruff clean, mypy `no issues found in 82 source files`, `Contracts: 10 kept, 0 broken`, **390 passed**, overall coverage 98.04%, 6b `TOTAL 267 0 54 0 100%`, Vitest 1 passed, build green; `./init.sh` exit 0. Not touched, per the dispositions: D5, D8, Q2, `test_quantity.py:22`, `feature_list.json`.
