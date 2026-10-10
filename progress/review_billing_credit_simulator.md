# Review: feature 20 `billing_credit_simulator` (phase 10, `sdd: false`, full group), round 1

**Verdict: APPROVED** (0 blocking defects; 2 non-blocking items with disposition FIX NOW, light, one test-only and one record-only; 1 stale-docstring nit in the same batch; 2 record corrections; 2 observations accepted with evidence).

Reviewer: Opus, 2026-10-09, ≈10:41 → ≈11:00 local (≈19 min). Inputs: `progress/brief_review_billing_credit_simulator.md` (premise check `progress/premise_review_billing_credit_simulator.md`: 12 VERIFIED, 0 FALSE), `progress/impl_billing_credit_simulator.md`, `progress/brief_impl_billing_credit_simulator.md`, `feature_list.json` id 20 (three acceptance items), `specs/shared/requirements.md` R42–R44 (373–392) and the trilogy obligation (365–366), `specs/billing_credit/design.md` §15.1, `CHECKPOINTS.md`, and the #7 and #8 checkouts. The developer stack stayed down (`docker ps`: `otcpy-n8n` only). No git command that writes the index or working tree was run.

## 0. What I ran (and what I did not)

- **`./quality.sh` once, stack down:** exit 0, **382 s**, `3234 passed in 356.11s`, coverage **97.42 %** overall, domain gate 99 %, import-linter **11 kept, 0 broken**, ruff / format / mypy / contracts drift / web green (log `.arm/review20/quality.log`). This reconciles with the impl report's 3 160 → 3 234 (+74).
- **`./init.sh`:** exit 0; section 5d: `shared spec byte-identical to ../order-to-cash-dotnet across 6 file(s)` and the same for `../order-to-cash-nestjs` (test-matrix exempt).
- **17 arms of my own** (script `.arm/review20/arm.py`, backups `.arm/review20/bak/`, output `arms_unit.out`, `arms_int1.out`, `arms_int2.out`, `arms_r17.out`): each one mutation, ONE named test, run in its own session (process group killed on timeout), restored by `cp`, `cmp=True` every time, `__pycache__` and `.mypy_cache` cleared. Final `sha256sum -c .arm/review20/pre.sha256`: all five armed source / test files OK; `conftest.py` restored to `f5c1a4d5…`.
- **After all restores:** the six files the feature owns or touches (`test_credit_simulator.py` unit and integration, `test_credit_simulator_settings.py`, `test_billing_settings_env.py`, `test_cents_rule_fixture_guard.py`, `tests/architecture/test_composition_env_reads.py`): **110 passed in 15.44 s**.
- **Not re-run:** the implementer's 20 arms one by one (I re-ran the ones the brief's questions are about under my own names, R1–R17). The full suite once, through `quality.sh`, as the brief requires.

## 1. Rulings on the brief's questions

### Q1. A13: the lifespan test fails on the clamp mutation without naming its claim — **non-blocking, FIX NOW (light, test-only)**

Reproduced as **R16**: `_parse_failure_rate` clamping instead of refusing, then `test_r43_a_bad_rate_refuses_to_boot_naming_the_value_before_connecting[1.5]` → `FAILED … 1 failed in 130.09s (0:02:10)`, and the visible error is a chain of `ConnectionRefusedError: [Errno 111] Connect call failed ('127.0.0.1', 1)`. The boot went past the settings and spent 130 s on NATS retries against the dead address. The test still fails, so the claim is guarded, but the failure points at NATS, not at R43, which is CLAUDE.md arming step 2 (*"its message must name the claim"*). This is the same shape as feature 18's N2 (a bare `TimeoutError`), which was ruled non-blocking with FIX NOW.

Why not blocking: the same mutation is killed **immediately and by name** at the unit level. My **R13** is the same clamp, and it fails `test_credit_simulator_settings.py::…fails_naming_variable_and_value[1.5]` with `Failed: R43: CREDIT_FAILURE_RATE='1.5' was accepted: the service would boot with it` in 0.68 s. R43's refusal is therefore never unguarded.

**What the test must assert before any connection is attempted:** the test file is `services/billing/tests/integration/test_credit_simulator.py:136-152`. Monkeypatch the composition root's connect (`composition.nats.connect`, or `otc_billing.main.start_runtime`) with a function that raises `pytest.fail(f"R43: the boot reached NATS with CREDIT_FAILURE_RATE={raw!r}: the settings did not refuse it")`. `pytest.fail` raises `Failed`, which `pytest.raises(ValidationError)` does not swallow. Keep the dead addresses as a second line of defence. **Arm that proves it:** R16 / the implementer's A13 (the clamp in `settings.py`) must fail **within seconds**, with that message.

### Q2. The ordering (acceptance 1): holds, deterministically

- **R1, the two `if` blocks swapped** → `test_r42_the_cents_rule_precedes_the_draw_and_the_draw_is_not_consumed`: `AssertionError: R42: the draw won over the cents rule` (`SIMULATED_FAILURE_RATE != SIMULATED_CENTS_RULE`), 0.09 s.
- **R2, the `.99` branch consumes a draw** (`self._random()` before its return) → the same test: `AssertionError: R42: the failure-rate draw was consumed for a .99 amount` / `assert 1 == 0`.

Both run at rate `1.0` with `Draws(0.0)` (`unit/test_credit_simulator.py:74-75`), and the test's control half (lines 80-81) proves that the source does fire for a plain amount. At the wire, `test_r43_a_rate_of_one_in_the_environment_refuses_a_plain_hold_and_the_ordering_holds` repeats the ordering through the real lifespan.

### Q3. `CREDIT_FAILURE_RATE` parsing: correct; the ledger citations are not (N2)

I probed the real `CreditSimulatorSettings` (script `.arm/review20/probe_parse.py`, run from a directory with no `.env`). For every refusal I checked that the validator's own `msg` contains `repr(value)`:

| Input | Result | Value named | R43 requires |
|---|---|---|---|
| `nan`, `inf`, `1e400` | REFUSED | yes | refuse (not a finite number in [0, 1]) |
| `1_0` | REFUSED | yes | refuse (`float()` reads 10.0) |
| `٠.٥` (Arabic-Indic), `０.５` (full-width) | REFUSED | yes | refuse (`re.ASCII`; `float()` reads 0.5) |
| `.`, `e1`, `1e` | REFUSED | yes | refuse |
| `" 0.5 "`, `"0.5\n"`, `"\t1\t"`, `"\xa00.5"` (NBSP) | ACCEPTED 0.5 / 1.0 | n/a | accept. #8's `Trim()` + `NumberStyles.Float` and #7's `trim()` strip the same (Unicode whitespace in all three) |
| `1e-1`, `+.5e+0`, `0.`, `-0` | ACCEPTED 0.1 / 0.5 / 0.0 / −0.0 | n/a | numbers in [0, 1]: accept (#8 accepts all four; #7 refuses them, see below) |
| `1.0000000000000001` | ACCEPTED 1.0 | n/a | see observation O1 |
| `1e-400` | ACCEPTED 0.0 (underflow) | n/a | a number in [0, 1]: accept |
| `""` / absent | 0.0 / 0.0 | n/a | R43 default 0, as in #7 (`:58`) and #8 (`:119`) |

`−0.0` behaves as 0, because `random() < -0.0` is never true.

The parsing is right. **The ledger's "#7 relied on X / #8 supplied Y" halves are not cited with lines** (see N2): row 1 cites "line ~46" (the regex is at **`simulator-credit-decision.ts:54`**) and #8 "comment in its header". Row 1 also does not record that **#7 and #8 disagree** on the accepted set. #7's `NUMERAL_SHAPE = /^(?:\d+|\d*\.\d+)$/` (`:54`) has no sign, no exponent and no trailing point, so it refuses `1e-1`, `+0.5`, `1.` and `-0`, all of which #8's `double.TryParse(trimmed, NumberStyles.Float, InvariantCulture)` (`SimulatorCreditDecision.cs:125`) accepts. #9 follows #8, which is defensible (R43 says "a number"; the trilogy obligation is about the predicate, the default and the reasons, not about spellings), but it is a choice and must be written as one.

### Q4. R43's composition read (#8 A1): guarded both ways

- **R3, the read deleted** (`SimulatorCreditDecision(0.0)`) → `test_r43_the_rate_the_environment_carries_reaches_the_simulator_the_root_builds`: `CREDIT_FAILURE_RATE must reach the simulator the root builds, once` / `[0.0] == [0.37]`.
- **R4, the root binds `AlwaysApproveCreditDecision()` by default** → `test_r42_a_total_ending_in_99_is_refused_with_the_cents_rule_over_the_wire`: `assert 'approved' == 'rejected'` (line 51). A `.99` hold approved *is* R42's claim failing. Acceptable without a custom message.
- **R5, `"CreditSimulatorSettings"` removed from `EXPECTED_SETTINGS`** → `tests/architecture/test_composition_env_reads.py::test_every_settings_class_of_the_service_is_the_literal_and_is_built_by_load_settings`: `Extra items in the left set: 'CreditSimulatorSettings'`.
- **R14, sibling alias** (`CREDIT_FAILURE_RATE` → `BILLING_CREDIT_FAILURE_RATE`) → `test_billing_settings_env.py::test_the_population_of_environment_variables_is_exactly_the_literal`: `declared but untested: ['BILLING_CREDIT_FAILURE_RATE']; tested but not declared: ['CREDIT_FAILURE_RATE']`.

The default binding (simulator, always) matches #7 (`app.module.ts:142`) and #8 (`BillingProgramConfiguration.cs:36`), as the impl report says. #7's review ruled that an env toggle would be a regression.

### Q5. R44: compared to each other, read back from the outbox column and the reply

`test_r44_…` (`integration/test_credit_simulator.py:155-191`) reads both `credit.rejected.v1` rows from the outbox (`db.outbox_rows_for`, the `payload` column) and both RPC replies. It compares their key sets **to each other** (lines 181, 184; no hand-typed key list, so #7 N1 is avoided) and pins the differing set to `{orderReference, requestedAmount, reason}`. It also proves over-limit reachable at rate `0` with the simulator bound (line 176).

- **R6, the cents branch's reason corrupted** → `test_r44_…`: `assert 'simulated_failure_rate' == 'simulated_cents_rule'`.
- **R7, payload transposition** (`requested_amount` ↔ `available_credit` in `outbox/payloads.py:61-62`, the one builder both paths share) → `test_r42_a_total_ending_in_99_is_refused_with_the_cents_rule_over_the_wire`: `a field of the simulated credit.rejected.v1 payload is wrong` / `{'availableCredit': 4299} != {'availableCredit': 100000}`, `{'requestedAmount': 100000} != {'requestedAmount': 4299}`. Fixture values are distinct (4 299 vs 100 000), so the transposition cannot satisfy the equality by accident.
- *The compensation-path half of R44* is structural on the Orders side. The saga keys on the event type (`step_table.py:148` `"credit.rejected.v1"`, `fact_commands.py:97`), not on Billing's reason, and the contract's reason enum carries all three values (`asyncapi.py:183-185`). Orders is outside this feature's bounds. #8's R44 row has the same scope.

### Q6. The measured-rate theory

- **R8, `rate * 0.5`** → `test_r43_the_configured_rate_is_measured_over_two_hundred_thousand_seeded_draws[0.1]`: `R43: rate 0.1 refused 0.0498 of 200000 seeded draws`. Deterministic: `random.Random(20261009)`.
- **R9, `<` → `<=`** → `test_r43_the_comparison_is_strict_a_draw_equal_to_the_rate_approves`: `assert Refuse(…SIMULATED_FAILURE_RATE) == Approve()` (line 91). The proportion test cannot see this one and the boundary test does, as #7's history predicted.

### Q7. Unplanned mutations at the call sites (mine)

- **R10, composition → constructor argument** (`failure_rate / 100`, a percent misreading) → the reach test: `[0.0037] == [0.37]`.
- **R11, settings → parse** (drop `re.ASCII` only, keeping the regex) → `…fails_naming_variable_and_value[٠.٥]`: `Failed: R43: CREDIT_FAILURE_RATE='٠.٥' was accepted: the service would boot with it`.
- **R12, simulator → port result** (the rate branch returns the cents reason) → `test_r43_a_rate_of_one_in_the_environment_refuses_a_plain_hold_and_the_ordering_holds`: `assert 'simulated_cents_rule' == 'simulated_failure_rate'`.
- **R15, the predicate reads the wrong operand** (`available_credit.amount % 100`) → `test_r42_an_amount_ending_in_99_is_refused_…[0]`: `R42: 99 (available 0) was not refused as simulated_cents_rule`.
- **R17, inherited fixture guard made a no-op** (`conftest.py` `refuse_cents_rule` returns at once) → `test_cents_rule_fixture_guard.py::test_the_request_helper_refuses_an_amount_ending_in_99_unless_allowed`: `Failed: DID NOT RAISE AssertionError`.

### Q8. Feature 19's seam (BC15) is untouched

`find services packages tests specs .env.example apps/web/src scripts quality.sh pyproject.toml -newer progress/brief_impl_billing_credit_simulator.md -type f` (excluding `__pycache__` / `.mypy_cache` / `node_modules` / `.pytest_cache`) printed exactly 12 files. None is under `domain/`, `application/` or `presentation/`:

```
.env.example
tests/architecture/test_composition_env_reads.py
specs/shared/test-matrix.md
services/billing/tests/integration/test_credit_simulator.py
services/billing/tests/integration/conftest.py
services/billing/tests/unit/test_billing_settings_env.py
services/billing/tests/unit/test_credit_simulator.py
services/billing/tests/unit/test_credit_simulator_settings.py
services/billing/src/otc_billing/composition.py
services/billing/src/otc_billing/infrastructure/settings.py
services/billing/src/otc_billing/infrastructure/credit/always_approve.py
services/billing/src/otc_billing/infrastructure/credit/simulator.py
```

Classification: three are source in `infrastructure/` or the composition root, five are tests (one in `tests/architecture`, its literal only), and one each is env template and shared-matrix Status. All are inside the implementer brief's bounds. `uv.lock` and `services/billing/pyproject.toml` are older than the brief (feature 19), so no package was added.

## 2. R<n> → test mapping (verified: each test exists once, `grep -rln "def <name>\b" services/billing/tests` = 1, and each R is killed by at least one arm above)

| R | Tests | Killed by (this review) |
|---|---|---|
| **R42** | unit `test_r42_an_amount_ending_in_99_is_refused_with_the_cents_rule_whatever_the_available_credit` (6 availables × 5 amounts, int64 max), `test_r42_an_amount_not_ending_in_99_is_approved_at_rate_zero`, `test_r42_the_cents_rule_precedes_the_draw_and_the_draw_is_not_consumed`; integration `test_r42_a_total_ending_in_99_is_refused_with_the_cents_rule_over_the_wire` (reply, empty ledger, exact outbox payload, control row), `test_r43_a_rate_of_one_in_the_environment_refuses_a_plain_hold_and_the_ordering_holds`; fixture guard `test_the_request_helper_refuses_an_amount_ending_in_99_unless_allowed`, `test_the_fixture_guard_still_refuses_a_99_amount_with_the_simulator_bound` | R1, R2, R4, R7, R15, R17 |
| **R43** | unit `test_r43_the_configured_rate_is_measured_over_two_hundred_thousand_seeded_draws`, `test_r43_a_rate_of_one_refuses_every_amount_that_does_not_end_in_99`, `test_r43_the_comparison_is_strict_a_draw_equal_to_the_rate_approves`, `test_r43_the_constructor_refuses_a_rate_outside_the_closed_unit_interval`, `test_r43_the_default_random_source_never_disagrees_with_rates_zero_and_one`; settings `test_r43_an_absent_rate_defaults_to_zero`, `test_r43_an_empty_rate_means_zero_as_absent_does`, `test_r43_a_number_in_the_closed_interval_is_accepted` (11), `test_r43_anything_but_a_finite_number_in_the_closed_interval_fails_naming_variable_and_value` (20); `test_billing_settings_env.py::test_each_variable_is_read_into_its_own_field_and_no_other`; lifespan `test_r43_the_failure_rate_defaults_to_zero_so_a_fitting_plain_hold_is_approved`, `test_r43_the_rate_the_environment_carries_reaches_the_simulator_the_root_builds`, `test_r43_a_bad_rate_refuses_to_boot_naming_the_value_before_connecting` (7) | R3, R5, R8, R9, R10, R11, R12, R13, R14, R16 |
| **R44** | `test_r44_a_simulated_and_a_genuine_rejection_share_fact_type_and_payload_keys` | R6 (and R7 through the shared builder) |

`specs/shared/test-matrix.md` §5 R42–R44 Status names these tests verbatim. Derived counts: `grep -c "| DONE"` = **39**; row count 63 = 39 + 1 + 23; §5 reads `8 | 8 | 0 | 0`. Column 4 (the stack-agnostic sketch) is untouched.

## 3. Findings

**N1 (non-blocking; disposition FIX NOW, light, test-only, route to `test_maintainer`): the lifespan refusal test fails the clamp mutation on a 130 s NATS timeout, not on R43.** `services/billing/tests/integration/test_credit_simulator.py:136-152`. Q1 above gives the fix and the arm (R16 / A13 must fail within seconds, naming R43 and the value). This is a recurrence of #9's own arming-message class (feature 16 N1, feature 18 N1/N2), not of an #8 id.

**N2 (non-blocking; disposition FIX NOW, record-only, the leader may edit `progress/`): the ported-idiom ledger in `progress/impl_billing_credit_simulator.md` (lines 23-33) cites files but not lines, gives one line wrongly, and omits two rows.** CLAUDE.md, *Porting*: *"the '#7 relied on X' and '#8 supplied Y' halves are read from the checkouts, with a file and line"*. I verified the substance of every row. The lines to write in:

- *Numeral shape*: #7 `apps/billing/src/infrastructure/credit/simulator-credit-decision.ts:54` (`NUMERAL_SHAPE`; not "~46"), trimmed at `:61`, tested at `:62`; #8 `src/Billing/Infrastructure/CreditDecisions/SimulatorCreditDecision.cs:125` (`double.TryParse(trimmed, NumberStyles.Float, CultureInfo.InvariantCulture, …)`); #9 `infrastructure/settings.py:147`.
- *Non-finite*: #7 `:66`; #8 `:126`; #9 `settings.py:165` and `simulator.py:43`.
- *Named value*: #7 `:66-` (the throw after the check); #8 `:130`; #9 `settings.py:156`.
- *Rate boundary*: #7 `:91`; #8 `:70`; #9 `simulator.py:56`. *Cents predicate*: #7 `:82`; #8 `:60`; #9 `simulator.py:53`.
- *Injected randomness*: #7 `:76`; #8 `:49`; #9 `simulator.py:48-49`.
- *Absent / empty*: #7 `:58`; #8 `:119`; #9 `settings.py:154` plus the field default at `:182-184`.

Missing row (a): *accepted spellings*. #7 and #8 disagree (#7 refuses `1e-1`, `+0.5`, `1.`, `-0`; #8 accepts them); #9 adopts #8's set, and the row should say why. Missing row (b): *integer modulo sign*, the Python question CLAUDE.md requires of every port. Python's `-1 % 100 == 99`, whereas C# and JS give `-1`. So a negative amount reaching `decide` would be refused as `simulated_cents_rule` in #9 and approved in #7 and #8. This is unreachable because `presentation/credit_wire.py:59-60` refuses a negative amount (BC33), and `unit/test_credit_requests.py:79` guards that. The row must cite that guard.

**N3 (nit, same light batch): stale fixture docstring.** `services/billing/tests/integration/conftest.py:377`, `billing_host`: *"…the default (approving) adapter"*. Since this feature, the default is the simulator at rate 0, which refuses every `.99` amount. Reword to "the default (simulator, rate 0) adapter".

**RC1 (record correction): #7 N6 was already resolved before this feature.** Impl report line 91 says "not touched … Reported, not fixed". In fact `git show HEAD:specs/shared/test-matrix.md` already reads `billing/infrastructure/credit-simulator.spec` for R42 and R43 (2 hits). #8 back-ported the fix, and the matrix was copied from #8. So N6 is **avoided by inheritance**: no SA is owed and nothing is routed.

**RC2 (record correction): A13's arming row** (impl report line 63) records `nats.errors.NoServersError` as the failure. My re-run shows the visible chain is `ConnectionRefusedError … ('127.0.0.1', 1)` ending in that failure after 130.09 s, so the substance is the same. N1 replaces the row once fixed.

**O1 (observation, ACCEPTED WITH EVIDENCE, not a defect): `1.0000000000000001` is accepted as `1.0`.** Mathematically it lies outside [0, 1], but binary64 rounds it to 1.0 before any range check, and all three builds behave identically (#7: `Number('1.0000000000000001') === 1` after passing `:54`; #8: `TryParse` → 1.0). R43 is evaluated on the parsed value in every stack; a decimal-exact parse would make #9 the odd one out against the trilogy obligation. Not rooted in a `specs/shared/` defect, so nothing is routed. *Re-open trigger:* any trilogy build adopting a decimal-exact parse.

**O2 (observation): several wire assertions carry no custom message** (`integration/test_credit_simulator.py:51, 107, 175`). Under R4, R6 and R12 they fail with `assert 'approved' == 'rejected'`-style text. In each case the compared values are the R-claim itself (a `.99` hold approved; a reason swapped), and the test name names R42 / R43 / R44, so I rule them sufficient. Not owed.

## 4. Ported-idiom ledger: claims checked, not existence

| Row | Supplied in #9? | Probe |
|---|---|---|
| Numeral shape | yes, `re.ASCII` + `fullmatch` after `strip()` | R11 (drop `re.ASCII` only) RED; my probe refuses `٠.٥` and `０.５` |
| Non-finite | yes, twice (settings and constructor) | probe: `nan`, `inf`, `1e400` refused; constructor test parametrises `nan`, ±`inf` |
| Named value | yes, the validator's own `msg` | probe: `value-named=True` on all 11 refusals; the test reads `errors()[i]["msg"]`, not `str(error)` (implementer's A12 shows why) |
| Rate boundary | yes, strict `<` | R9 RED |
| Injected randomness | yes, a plain callable | R2 (the draw count is observable) RED |
| Env read in the root | yes | R3, R5, R10, R14 RED |
| Synchronous decide | yes, plain `def`; `test_the_simulator_is_synchronous_and_does_no_io` | read |
| *(missing)* accepted spellings / `%` sign | **not written** | N2 |

## 5. CHECKPOINTS walk

**C1**

- [x] harness files exist
- [x] `progress/current.md` and `history.md` exist
- [x] seven agent definitions
- [x] every agent declares a model (`premise_checker` sonnet, `suite_runner` and `test_maintainer` haiku, `implementer` sonnet; `leader`, `reviewer` and `spec_author` state deliberate inheritance)
- [x] `./init.sh` exit 0

**C2**

- [x] 0 `in_progress` (34 done, 21 pending, 1 in_review before this verdict)
- [x] every status valid
- [x] `done` features have passing tests (3 234 passed)
- [x] `current.md` describes this session. Its *Goal* line still describes feature 19's spec step: the leader's file, a nit.
- [x] no `blocked` feature

**C3**

- [x] `lint-imports` 11 kept, 0 broken (from `quality.sh`)
- [x] no cross-service DB access or imports (independence contract kept)
- [x] no new shared runtime code
- [x] no `domain` → `otc_cqrs`
- [x] `dependencies = []` unchanged (no `pyproject.toml` of `shared_kernel` / `cqrs` touched)
- [x] no float, Decimal or `/` in money: `amount.amount % 100` is int; the `float` is the rate, a probability, in `infrastructure`; the AST money guard is green
- [x] interactions classified: NATS `billing.credit.hold` RPC in, Kafka `credit.rejected.v1` fact out via the outbox
- [x] no debug prints or bare TODOs in the two new source files (`grep` empty)

**C4**

- [x] `quality.sh` passes (382 s)
- [x] domain tests pure: the simulator's tests import no framework and live in `unit/`, not `unit/domain/`
- [x] integration tests on testcontainers, stack down
- [x] coverage 97.42 % / 99 % domain
- [x] no Jest, Karma or Jasmine

**C5**

- [x] no suspicious untracked files (`.arm/` is git-ignored, `.gitignore:87`)
- [x] history entry with effort record (appended with this verdict)
- [x] `feature_list.json` 20 → `done`
- [ ] the human told what was done and how to test it: the leader's, at wrap-up
- [x] Claude did not commit

**C6:** `sdd: false`; no spec directory owed.

- [x] R42–R44 are each mapped to named tests in `test-matrix.md`

**C7**

- [x] `specs/shared/` byte-identical to #8 and #7 (init.sh 5d, real `cmp`)
- [x] no deviation needing an SA (O1 is trilogy-identical)
- [x] R42–R44 are #7's ids, and the Python behaviour satisfies them, armed
- n/a: n8n and the API script (not this feature)
- [x] every inherited #7 / #8 finding accounted for (§6)
- [x] the effort record, including the comparison against #7, where #9 is slower

## 6. Inherited findings

- **#8 A1** (the env read deletable with the suite green): **avoided**. R3 and R10 are RED in the reach test; R5 and R14 are RED in the literal and population guards.
- **#8 N1** (the report's count wrong): **avoided**. 3 234 reconciles with my `quality.sh` run.
- **#8 N2 / #7 N2** (the fixture guard as a one-off search): **avoided**. A durable guard exists since feature 19, now also tested through `rpc` with the simulator bound; R17 RED.
- **#7 N1** (R44 compared to a hand-typed key list): **avoided**, lines 181 and 184 compare the two payloads to each other.
- **#7 N3** (`Number()` coercion): **avoided**. My probe shows Python's own coercions (`1_0`, `nan`, non-ASCII digits) refused.
- **#7 N5** (always-approve retained for a consumer that does not exist): **avoided**. It has real consumers, `integration/test_credit_repository.py:201` and `unit/test_always_approve.py:17`.
- **#7 N6**: **avoided by inheritance** (RC1).
- **#7 N4**: not applicable.
- **Recurred:** #9's own arming-message class (N1). Nothing from #8's backlog recurred.

## 7. What must change

Nothing for the verdict. Before feature 20's commit (FIX NOW, light, one batch; the leader runs the arm):

1. **N1**: `integration/test_credit_simulator.py:136-152`. Monkeypatch the root's NATS connect to `pytest.fail("R43: the boot reached NATS with CREDIT_FAILURE_RATE=…")`. Arm R16 / A13 (the clamp in `settings.py:165-167`) must fail within seconds with that message.
2. **N3**: reword `conftest.py:377`.
3. **N2 + RC1 + RC2**: amend `progress/impl_billing_credit_simulator.md`'s ledger with the lines above and the two missing rows, and correct line 91 (N6 avoided by inheritance) and the A13 row.
