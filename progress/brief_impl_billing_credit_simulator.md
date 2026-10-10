# Brief — implementer, feature 20 `billing_credit_simulator` (phase 10, `sdd: false`, full group)

**Task:** implement feature 20 from its acceptance items (`feature_list.json` id 20, three items) and the shared requirements **R42, R43, R44** (`specs/shared/requirements.md` lines 373 – 393; the trilogy obligation at lines 365 – 366: #8 and #9 reproduce R42 and R43 **identically** — same predicate, same default, same rejection reasons). Feature 20 is `in_progress`. There is no spec phase (`sdd: false`): **the design is the seam feature 19 cut for you**, `specs/billing_credit/design.md` §15.1 — read it first, and treat its footprint as your file bound (below). Classification: **full group** (R44 is a wire / saga-compensation claim), so an Opus reviewer follows.

## Inputs (found on disk by the leader this session; premise check: `progress/premise_impl_billing_credit_simulator.md`)

- **The seam:** the port `services/billing/src/otc_billing/application/ports/credit_decision.py` (`CreditDecisionPort.decide`, line 47, is a plain `def` — `design.md` ported-idiom ledger row L24; `Approve` / `Refuse`), the current adapter `services/billing/src/otc_billing/infrastructure/credit/always_approve.py`, `composition.py`'s binding, `infrastructure/settings.py`, the adapter reason type (`domain/reasons.py`, which cannot name `over_limit`), and the integration fixture guard for amounts ending in 99 (`services/billing/tests/integration/conftest.py` from line 381, `CENTS_RULE_SUFFIX`, `allow_cents_rule`).
- **#8:** `../order-to-cash-dotnet/src/Billing/Infrastructure/CreditDecisions/SimulatorCreditDecision.cs`, `../order-to-cash-dotnet/src/Billing/Infrastructure/BillingOptions.cs`, `../order-to-cash-dotnet/src/Billing/BillingProgramConfiguration.cs`; tests `../order-to-cash-dotnet/tests/Billing.UnitTests/{SimulatorCreditDecisionTests,BillingProgramConfigurationTests}.cs`, `../order-to-cash-dotnet/tests/Billing.IntegrationTests/CreditSimulatorTests.cs`. Record: `../order-to-cash-dotnet/progress/history.md` line 1261 (approved first pass; findings N1, **A1** — the composition root's env read was deletable with the suite green — and **N2**), `../order-to-cash-dotnet/progress/review_billing_credit_simulator.md`.
- **#7:** `../order-to-cash-nestjs/apps/billing/src/infrastructure/credit/simulator-credit-decision.ts` and its `.spec.ts`, `../order-to-cash-nestjs/apps/billing/src/credit-rejection-parity.integration.spec.ts`, `../order-to-cash-nestjs/apps/billing/src/app.module.ts`; record `../order-to-cash-nestjs/progress/history.md` line 903 and `../order-to-cash-nestjs/progress/review_billing_credit_simulator.md` (six findings, N1 – N6).

## Questions to answer with a command (record each answer in the report, with the command)

1. Which adapter do #7 and #8 bind **by default** (simulator or always-approve), and how is it selected? Adopt their choice if they agree (maintainer ruling: a decision #7 and #8 agree on, with no Python-forced difference, is adopted and cited).
2. **Python-forced parsing differences for `CREDIT_FAILURE_RATE`.** #8's ledger row: `"NaN"` / `"Infinity"` parse in both .NET and JS and had to be refused by hand. What do Python's `float()` and pydantic-settings' float parsing accept that a "number in `[0, 1]`" should not — try at least `"nan"`, `"inf"`, `"1e-1"`, `" 0.5 "`, `"0x1"`, `"1_0"`, `"0.5\n"`, `""`, `"true"` — and which of them must the boot refuse? Write the ported-idiom ledger rows (*"#7 relied on X; #8 supplied it with Y; in #9 it is supplied by Z"*, each half with file and line) in `progress/impl_billing_credit_simulator.md`, one row per idiom, each with its armed guard.
3. What does an absent or empty `CREDIT_FAILURE_RATE` mean in #7 and #8 (R43: default `0`)?

## Must hold (each is a guard; each guard is armed)

- **The ordering (Plan item, acceptance 1):** `total % 100 == 99` is evaluated **before** the failure-rate draw, and the draw is **not consumed** for a `.99` amount. Prove it with the other branch fixed to its certain-to-fire configuration (rate `1`, a random source returning `0`) so that swapping the two checks fails deterministically; arm by swapping them.
- **Seedable / injected randomness:** the random source is injected (a plain callable, since `decide` is synchronous); no probabilistic test anywhere. #8 committed a measured many-draw theory, the only guard that caught a rate applied at half strength: commit the equivalent with an injected deterministic source, and arm it with `rate * 0.5`.
- **R43 boot failure names the offending value**, through the real settings → composition path, and **the composition root's read is guarded** (#8's A1; #9's reach tests: `tests/architecture/test_composition_env_reads.py`, `services/billing/tests/unit/test_billing_settings_env.py`, `services/billing/tests/integration/test_billing_host_lifespan.py`). Arm: delete the read.
- **R44:** a simulated and a genuine over-limit rejection produce the same fact type and the same payload key set, compared **to each other** (never to a hand-typed list — #7's N1 tautology), and the over-limit rejection stays reachable with the simulator bound and rate `0`. Read both payloads back from the outbox `payload` column and from the RPC reply. Arm: corrupt the reason of the cents branch (#8's wire-level kill).
- **Inherited:** #8 N2 / #7 N2 — the `% 100 == 99` fixture guard already exists (feature 19); confirm it now protects against the simulator being bound, and name the test that fails if a fixture amount ends in 99 without `allow_cents_rule`.
- **No change** to `domain/`, `application/` or `presentation/` (design §15.1, `BC15`). If you find one is needed, stop and report.

## Process

- Arming protocol (grep `CLAUDE.md` on disk): backups in `.arm/bc20/` with `sha256`; one named test per arm; the failure message names the claim; restore by `cp` + `cmp`, never `git checkout`; clear `__pycache__` / `.mypy_cache`; timeouts kill the whole process group. **Mutate every call site of the new adapter and of the settings read**, not only the adapter (feature 17's lesson), and name the test that kills each.
- Integration suites run with the developer stack down (only `otcpy-n8n` runs). **No live walkthrough is required for this feature;** do not start the stack.
- Baseline first: `./quality.sh` with the stack down (exit code, duration, pass count); end with a second run and report the delta.
- Update `specs/shared/test-matrix.md` §5 column 5 for **R42 – R44** only (names verbatim) and its derived counts; nothing else in `specs/shared/`.

## Bounds

May touch: `services/billing/src/otc_billing/infrastructure/credit/` (new `simulator.py`), `services/billing/src/otc_billing/infrastructure/settings.py`, `services/billing/src/otc_billing/composition.py`, the Billing tests (`services/billing/tests/**`), `tests/architecture/test_composition_env_reads.py` (its literal only), `.env.example` (`CREDIT_FAILURE_RATE` with a comment), `specs/shared/test-matrix.md` (as above), `progress/impl_billing_credit_simulator.md`, and feature 20's status line in `feature_list.json`. Nothing else. No git command that writes the index or working tree.

## Output

`progress/impl_billing_credit_simulator.md`: what was built, the three answers, the ledger rows, the arming table (mutation, test, verbatim message, `sha256`, `cmp`), the call-site search output with one classification per hit, each inherited #7 / #8 finding named **avoided** or **recurred**, and the `Packages installed:` line. Set feature 20 to `in_review` (that line only). Return only "result in `progress/impl_billing_credit_simulator.md`" plus at most 5 lines.
