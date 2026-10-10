# Implementation report: feature 20 `billing_credit_simulator` (phase 10, `sdd: false`, full group)

Status set to `in_review`. No git command run. No change under `domain/`, `application/` or `presentation/` (BC15, design 15.1).

## Built

- `infrastructure/credit/simulator.py` (new): `SimulatorCreditDecision(failure_rate, random_source=None)`. `amount.amount % 100 == 99` is evaluated first and returns `simulated_cents_rule` without consuming a draw; then `random_source() < failure_rate` (strict) returns `simulated_failure_rate`; else `Approve`. The source is a plain callable (default: a private `random.Random().random`; `decide` is a plain `def`, L24). Constructor refuses a rate that is not finite or outside [0, 1].
- `infrastructure/settings.py`: `CreditSimulatorSettings.failure_rate`, alias `CREDIT_FAILURE_RATE`, default `0.0`, parsed by `_parse_failure_rate` through `Annotated[..., BeforeValidator]` (not a decorator: the decorator census guard `test_every_decorator_under_services_is_in_the_census_allow_list` failed on my first `@field_validator`, which is how I found out).
- `composition.py`: `BillingSettings.credit_simulator`, built in `load_settings`; default binding `credit_decision or SimulatorCreditDecision(settings.credit_simulator.failure_rate)`.
- `always_approve.py`: docstring only (it said "until feature 20"); kept because `test_credit_repository.py:201` builds its scope with it.
- `.env.example`: `CREDIT_FAILURE_RATE=0` with a comment. `tests/architecture/test_composition_env_reads.py`: the literal gained `CreditSimulatorSettings`. Integration `conftest.py`: `host_environment` sets `CREDIT_FAILURE_RATE=0` (every variable the root reads is set there). `specs/shared/test-matrix.md` section 5 column 5 for R42-R44 and the derived counts (billing_credit 8/0/0, total green 39, not yet green 23; `grep -c "| DONE"` = 39).

## Files touched

New: `services/billing/src/otc_billing/infrastructure/credit/simulator.py`, `services/billing/tests/unit/test_credit_simulator.py`, `services/billing/tests/unit/test_credit_simulator_settings.py`, `services/billing/tests/integration/test_credit_simulator.py`. Edited: the files listed above plus `services/billing/tests/unit/test_billing_settings_env.py` (ENV literal, class literal, default), `feature_list.json` (line 371 only).

## The three answers

1. **Default adapter.** Both bind the simulator by default and always: #7 `apps/billing/src/app.module.ts:142` (`useFactory: () => new SimulatorCreditDecision(loadCreditSimulatorConfig())`, header lines 5-16), #8 `src/Billing/BillingProgramConfiguration.cs:36` (`options.CreditFailureRate = CreditSimulatorOptionsLoader.Load(...)`). The always-approve adapter stays in the tree in both. Adopted (commands: `grep -n "Simulator\|AlwaysApprove" ../order-to-cash-nestjs/apps/billing/src/app.module.ts ../order-to-cash-dotnet/src/Billing/BillingProgramConfiguration.cs`). `start_runtime(credit_decision=...)` still lets a test bind another port.
2. **Python parsing.** Measured with `python3 -c "float(s)"`: `nan` -> nan, `inf` -> inf, `-inf`, `infinity` -> inf, `1e-1` -> 0.1, `" 0.5 "` -> 0.5, `"0.5\n"` -> 0.5, `"1_0"` -> **10.0**, `"+0.5"`, `"1e0"` accepted, Arabic-Indic `"٠.٥"` -> 0.5; `"0x1"`, `""`, `"true"` raise. A pydantic `float` field (measured with `BaseModel`) also accepts `nan`, `inf`, `1_0`, `" 0.5 "`, `"0.5\n"`, `1e-1`. The boot must refuse: `nan`, `inf`, `-inf`, `infinity` (non-finite, as #8), `1_0` (digit-group underscore: reads 10 and would be refused only by the range, but `0_5` would read 0.5, and a rate is not a Python literal), non-ASCII digits, `0x1`, `true`, whitespace-only, anything outside [0, 1]. It accepts what #8 accepts (`1e0`, `+0.5`, surrounding whitespace, `.5`, `1.`, `1e-1`): a numeral shape regex (`re.ASCII`, `fullmatch` after `strip()`), then `float`, then finite and range.
3. **Absent or empty.** Both mean `0` (#7 `simulator-credit-decision.ts` `raw === undefined || raw === ''`; #8 `CreditSimulatorOptionsLoader.Load` `IsNullOrEmpty`). Whitespace-only is refused in both and here. #9: absent via the field default, empty via `_parse_failure_rate` (`raw == ""`).

## Ported-idiom ledger (rows also owed to `design.md`'s ledger; `sdd: false`, so they live here)

| Idiom | #7 relied on | #8 supplied it with | #9 supplies it with | Armed guard |
|---|---|---|---|---|
| Numeral shape | a hand-written plain-decimal regex before `Number()` (`../order-to-cash-nestjs/apps/billing/src/infrastructure/credit/simulator-credit-decision.ts` `:54` `NUMERAL_SHAPE`, trimmed `:61`, tested `:62`), because `Number('0x1')` is 1 and `Number('  ')` is 0 | `double.TryParse(trimmed, NumberStyles.Float, InvariantCulture)` (`../order-to-cash-dotnet/src/Billing/Infrastructure/CreditDecisions/SimulatorCreditDecision.cs` `:125`) has no such coercion | a hand-written ASCII regex (`settings.py:147` `_RATE_NUMERAL`), because `float()` accepts `1_0`, `nan`, `inf` and non-ASCII digits | A11 (regex deleted): `test_r43_anything_but_a_finite_number_in_the_closed_interval_fails_naming_variable_and_value[٠.٥]` |
| Non-finite | `Number.isFinite` (`simulator-credit-decision.ts:66`) | `double.IsFinite` (`SimulatorCreditDecision.cs:126`) | `math.isfinite` plus the range test in `_parse_failure_rate` (`settings.py:165`), again in the adapter constructor (`simulator.py:43`) | A10 (check deleted): same test, `[1.5]` fails "was accepted" |
| Named value in the failure | `JSON.stringify(raw)` in the message (the throw after the check, `simulator-credit-decision.ts:66-`) | `got "{raw}"` in the message (`SimulatorCreditDecision.cs:130`) | `{raw!r}` in the validator's own message (`settings.py:156`) | A12: the test reads `error.errors()[i]["msg"]`, NOT `str(error)`: pydantic's `str` echoes `input_value=` and named the value even with it deleted (the first version of the test passed under A12; fixed) |
| Rate boundary | `random() < failureRate` (`simulator-credit-decision.ts:91`; cents predicate `:82`) | `_random() < _failureRate` (`SimulatorCreditDecision.cs:70`; cents predicate `:60`) | `self._random() < self._failure_rate` (`simulator.py:56`); `int % int` for the cents rule (`simulator.py:53`), no `/` | A3 (`<=`): `test_r43_the_comparison_is_strict_a_draw_equal_to_the_rate_approves` |
| Injected randomness | `random = Math.random` constructor default (`simulator-credit-decision.ts:76`) | `Func<double>? random` defaulting to `Random.Shared.NextDouble` (`SimulatorCreditDecision.cs:49`) | `Callable[[], float] | None`, default `random.Random().random` (`simulator.py:48-49`; private instance, S311 suppressed with a reason) | every unit test injects `Draws` or `random.Random(20261009).random` |
| Env read in the root | `process.env` in the factory (`app.module.ts:142`) | A1: Program.cs read deletable with the suite green (`BillingProgramConfiguration.cs:36`) | pydantic-settings class built in `load_settings`; reach asserted by value | A6, A6w, A8, A8s, A9 below |
| Absent / empty | `raw === undefined || raw === ''` is `0` (`simulator-credit-decision.ts:58`) | `string.IsNullOrEmpty(raw)` is `0` (`SimulatorCreditDecision.cs:119`) | `raw == ""` (`settings.py:154`) plus the field default `0.0` (`settings.py:182-184`) | A14, A15 |
| Accepted spellings | #7 refuses `1e-1`, `+0.5`, `1.`, `-0` (`NUMERAL_SHAPE = /^(?:\d+\|\d*\.\d+)$/`, `simulator-credit-decision.ts:54`: no sign, exponent or trailing point) | #8 accepts all four (`NumberStyles.Float`, `SimulatorCreditDecision.cs:125`) | #9 adopts #8's set (`settings.py:147` allows sign, exponent and trailing point). #7 and #8 disagree, so this is a choice, not an inheritance: R43 says "a number in [0, 1]", the trilogy obligation is the predicate, the default and the failure reasons, not the spellings, and refusing a spelling that is unambiguously a number in range would be stricter than the requirement | `test_r43_a_number_in_the_closed_interval_is_accepted` (11 forms, incl. `1e0`, `+0.5`, `1.`) |
| Integer modulo sign | `%` keeps the dividend's sign in JS (`-1 % 100 === -1`, `simulator-credit-decision.ts:82`) | the same in C# (`SimulatorCreditDecision.cs:60`) | Python's `-1 % 100 == 99`, so a negative amount reaching `decide` would be refused as `simulated_cents_rule` here and approved in #7 and #8. Unreachable: `presentation/credit_wire.py:59-60` refuses a negative amount (BC33) before the port is called | `unit/test_credit_requests.py:79` (`BC33: a negative amount`) |
| Synchronous decide | `decide` sync | `ValueTask` | plain `def` | `test_the_simulator_is_synchronous_and_does_no_io` (and mypy against the port in `test_always_approve.py`) |

Engine claim probed: Python's `float()` was probed both ways above (accepts and rejects lists); `re.ASCII` pinned by the `٠.٥` row.

## Tests and the `R<n>` each proves

- R42: `test_credit_simulator.py::test_r42_an_amount_ending_in_99_is_refused_with_the_cents_rule_whatever_the_available_credit` (6 availables x 5 amounts, incl. int64 max), `test_r42_an_amount_not_ending_in_99_is_approved_at_rate_zero`, `test_r42_the_cents_rule_precedes_the_draw_and_the_draw_is_not_consumed` (rate 1, source 0, draw count 0, with a control that draws once); wire: `test_r42_a_total_ending_in_99_is_refused_with_the_cents_rule_over_the_wire` (reply, ledger empty, outbox payload exact, control row), `test_r43_a_rate_of_one_in_the_environment_refuses_a_plain_hold_and_the_ordering_holds` (the ordering at the wire).
- R43: unit `test_r43_the_configured_rate_is_measured_over_two_hundred_thousand_seeded_draws`, `..._a_rate_of_one_refuses_every_amount_...`, `..._the_comparison_is_strict_...`, `..._the_constructor_refuses_a_rate_outside_...`, `..._the_default_random_source_never_disagrees_with_rates_zero_and_one`; settings `test_credit_simulator_settings.py` (absent -> 0, empty -> 0, 11 accepted forms, 20 refused forms each asserting variable and value in the validator's message); `test_billing_settings_env.py` (variable reads exactly its field); lifespan `test_r43_the_failure_rate_defaults_to_zero_...`, `test_r43_the_rate_the_environment_carries_reaches_the_simulator_the_root_builds`, `test_r43_a_bad_rate_refuses_to_boot_naming_the_value_before_connecting` (7 values, dead DB/NATS addresses, through `create_app()`'s lifespan).
- R44: `test_r44_a_simulated_and_a_genuine_rejection_share_fact_type_and_payload_keys`: one host at rate 0, one `.99` hold and one over-limit hold; outbox `payload` key sets and RPC reply key sets compared to each other, differing keys of the payload are exactly `{orderReference, requestedAmount, reason}`.
- Inherited fixture guard: `test_cents_rule_fixture_guard.py::test_the_request_helper_refuses_an_amount_ending_in_99_unless_allowed` (existing, fails if a fixture amount ending in 99 is not flagged) and new `test_the_fixture_guard_still_refuses_a_99_amount_with_the_simulator_bound` (through the `rpc` fixture with the simulator bound).

## Arming table (script `.arm/bc20/arm.py`; backups `.arm/bc20/bak/`; output `.arm/bc20/arms.out`, `arms2.out`; every run `cmp_restored=True`; each test is the ONE named test; subprocess in its own session, killed by group on timeout)

| Mutation | Test | Verbatim failure | sha256 (backup, first 16) |
|---|---|---|---|
| A1 swap the two checks | `test_r42_the_cents_rule_precedes_the_draw_and_the_draw_is_not_consumed` | `AssertionError: R42: the draw won over the cents rule` | 340828fb97c535b5 |
| A2 rate x 0.5 | `test_r43_the_configured_rate_is_measured_over_two_hundred_thousand_seeded_draws[0.1]` | `R43: rate 0.1 refused 0.0498 of 200000 seeded draws` | 340828fb97c535b5 |
| A3 `<` to `<=` | `test_r43_the_comparison_is_strict_a_draw_equal_to_the_rate_approves` | `assert Refuse(reason=...SIMULATED_FAILURE_RATE) == Approve()` | 340828fb97c535b5 |
| A4 cents branch emits the failure-rate reason | unit `test_r42_an_amount_ending_in_99_is_refused_...[0]` | `R42: 99 (available 0) was not refused as simulated_cents_rule` | 340828fb97c535b5 |
| A4w same, wire | `test_r44_a_simulated_and_a_genuine_rejection_share_fact_type_and_payload_keys` | `assert 'simulated_failure_rate' == 'simulated_cents_rule'` | 340828fb97c535b5 |
| A5 cents branch deleted | `test_r42_a_total_ending_in_99_is_refused_with_the_cents_rule_over_the_wire` | `assert 'approved' == 'rejected'` | 340828fb97c535b5 |
| A6 composition read deleted (constant 0.0) | `test_r43_the_rate_the_environment_carries_reaches_the_simulator_the_root_builds` | `CREDIT_FAILURE_RATE must reach the simulator the root builds, once` | ab7faead69d25888 |
| A6w same | `test_r43_a_rate_of_one_in_the_environment_refuses_a_plain_hold_and_the_ordering_holds` | `assert ((None or None)) is not None` (no refusal at rate 1) | ab7faead69d25888 |
| A7 root binds always-approve | `test_r42_a_total_ending_in_99_is_refused_with_the_cents_rule_over_the_wire` | `assert 'approved' == 'rejected'` | ab7faead69d25888 |
| A8 bundle built by `model_construct()` | `tests/architecture/test_composition_env_reads.py::test_every_settings_class_of_the_service_is_the_literal_and_is_built_by_load_settings` | `load_settings never builds ['CreditSimulatorSettings']` | ab7faead69d25888 |
| A8s same | `test_billing_settings_env.py::test_each_variable_is_read_into_its_own_field_and_no_other[CREDIT_FAILURE_RATE]` | `assert 0.0 == 0.37` | ab7faead69d25888 |
| A9 sibling alias `CREDIT_FAIL_RATE` | `test_r43_a_number_in_the_closed_interval_is_accepted[1-1.0]` | `assert 0.0 == 1.0` | 108926ded96c76e4 |
| A10 finite/range check deleted | `test_r43_anything_but_..._fails_naming_variable_and_value[1.5]` | `R43: CREDIT_FAILURE_RATE='1.5' was accepted: the service would boot with it` | 108926ded96c76e4 |
| A11 numeral regex deleted | same test, `[٠.٥]` | `R43: CREDIT_FAILURE_RATE='٠.٥' was accepted: ...` | 108926ded96c76e4 |
| A12 message drops the value | same test, `[1.5]` | `the failure does not report the offending value '1.5'` | 108926ded96c76e4 |
| A13 clamp instead of refuse (`return min(1.0, max(0.0, rate))` for the range check) | `test_r43_a_bad_rate_refuses_to_boot_naming_the_value_before_connecting[1.5]` (the NATS connect is monkeypatched to `pytest.fail`) | `Failed: R43: the boot reached NATS with CREDIT_FAILURE_RATE='1.5': not refused` in 8.5 s (was 131 s of NATS retries); re-armed after the `import nats` edit, same message | 108926ded96c76e4 |
| A14 empty string not mapped to 0 | `test_r43_an_empty_rate_means_zero_as_absent_does` | `ValidationError: 1 validation error for CreditSimulatorSettings` | 108926ded96c76e4 |
| A15 default 0.5 | `test_r43_an_absent_rate_defaults_to_zero` | `assert 0.5 == 0` | 108926ded96c76e4 |
| A16 fixture guard no-op | `test_the_request_helper_refuses_an_amount_ending_in_99_unless_allowed` | `DID NOT RAISE AssertionError` | f5c1a4d5104309a4 |
| A16i same | `test_the_fixture_guard_still_refuses_a_99_amount_with_the_simulator_bound` | `DID NOT RAISE AssertionError` | f5c1a4d5104309a4 |

Defeat-list rows applied: 1 (A5, A7, A14), 2 (A4, A15), 3 (A9 sibling alias, A6 vs the rate-1 wire test), 7 (A11 drops the optional regex), 9 (A12: the closer half passed while the premise was stale; found and fixed), 11 (the decorator census forced the `BeforeValidator` form). Rows 4-6, 8, 10, 12 do not apply: no syntax guard was written; the one literal-vs-literal risk (fixtures contain no suffix by accident) is checked by the distinct values.

## Call-site search (`grep -rn "SimulatorCreditDecision\b" services tests --include=*.py`, excluding the unit test file)

| Hit | Classification | Killed by |
|---|---|---|
| `simulator.py:38` class definition | the adapter | A1-A5 |
| `composition.py:50` import | import | A7 (swapped import) |
| `composition.py:292` the binding | the one call site | A5, A6, A6w, A7 |
| `test_credit_simulator.py:19,123,128` | the recording subclass monkeypatched into `composition` | reach test (A6) |

Settings read sites (`grep -rn "failure_rate\|CREDIT_FAILURE_RATE" services/*/src tests`): `composition.py:293` (the one read of the field), `settings.py` (definition), `simulator.py` (constructor, comparison), `domain/reasons.py` (the reason token, not the setting). `CREDIT_FAILURE_RATE` outside source: `.env.example`, the test files, `feature_list.json`. All classified; the composition read is killed by A6/A6w, the field by A8s, the alias by A9, the class construction by A8.

## Inherited findings

- #8 A1 (env read deletable with the suite green): **avoided**, A6/A6w/A8/A8s/A9.
- #8 N1 (report count wrong): **avoided**, the counts below come from the log (`grep passed .arm/bc20/final.log`).
- #8 N2 / #7 N2 (fixture guard): **avoided**, guard exists since feature 19 and is now also tested through `rpc` with the simulator bound.
- #7 N1 (R44 compared to a hand-typed key list): **avoided**, key sets compared to each other.
- #7 N3 (`Number()` coercion): **avoided**, row 1 of the ledger, Python's own variants measured.
- #7 N5 (always-approve retained for a consumer that does not exist): **avoided**, it has one (`test_credit_repository.py:201`) and its docstring says so.
- #7 N4 (rule not written down): not applicable to this feature (CLAUDE.md carries it).
- #7 N6 (test-matrix sketch column names the wrong layer): **avoided by inheritance** (review RC1): `specs/shared/test-matrix.md:158-159` already read `billing/infrastructure/credit-simulator.spec` at HEAD. No SA owed.
- Recurred: none, except the A12 shape (a message assertion satisfied by pydantic echoing the input), caught by arming before submission.

## Quality

Baseline `./quality.sh` (stack down, only `otcpy-n8n` running): exit 0, 394 s, **3160 passed**, coverage 97.42%. Final: exit 0, 407 s, **3234 passed** (+74), coverage 97.42%, ruff, mypy, import-linter, web all green. `./init.sh` exit 0.

## Could not do / surprises

- No live walkthrough (not required, stack not started).
- The first `@field_validator` failed the decorator census, which is outside my file bounds; I used `BeforeValidator` instead.
- A13 (clamp) fails by a slow NATS connection error rather than a named assertion; the claim is still caught but the message does not name it.
- The test matrix column 4 of R42-R44 still cites #7-style sketch names (shared, read-only).

Packages installed: none

## Review findings (round 1: N1, N2, N3, RC1, RC2)

- **N1 closed.** `integration/test_credit_simulator.py`: the lifespan refusal test takes `monkeypatch` and replaces `nats.connect` with a coroutine that calls `pytest.fail(f"R43: the boot reached NATS with CREDIT_FAILURE_RATE={raw!r}: not refused")`; the dead addresses stay as a second line. Arm (backup `.arm/bc20f/settings.py`, sha256 `108926ded96c76e4a2360f98249775dda0e8ce576e41a4c054bbbef6a877fd99`, process group killed on timeout): the clamp mutation fails the test with `Failed: R43: the boot reached NATS with CREDIT_FAILURE_RATE='1.5': not refused`, `1 failed in 8.50s` (10.3 s wall). Restored with `cp`, `cmp` identical, sha256 re-checked, caches cleared, green again. First attempt patched `composition.nats`, which mypy refused (the module does not re-export `nats`); the final form imports `nats` and was re-armed with the same result (8.49 s).
- **N2 closed.** Ledger rows carry file-and-line citations, each verified with `sed -n` against the checkouts and #9, and two rows were added (accepted spellings, integer modulo sign). Absent / empty is a separate row.
- **N3 closed.** `integration/conftest.py` `billing_host` docstring now reads "the default (simulator, rate 0) adapter".
- **RC1, RC2 closed** in place (the #7 N6 line, the A13 row).
- Checks: `test_credit_simulator.py` 13 passed (11 s); with `test_credit_simulator_settings.py`, 46 passed; ruff check, ruff format --check and mypy clean on the two test files. No production file touched; `feature_list.json` untouched.
