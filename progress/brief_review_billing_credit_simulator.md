# Brief — reviewer, feature 20 `billing_credit_simulator` (phase 10, `sdd: false`, full group, round 1)

**Task:** adversarially review feature 20 against its acceptance items (`feature_list.json` id 20), `specs/shared/requirements.md` **R42 – R44** (lines 373 – 393, and the trilogy obligation at 365 – 366), the seam `specs/billing_credit/design.md` §15.1, the implementer brief `progress/brief_impl_billing_credit_simulator.md`, `CHECKPOINTS.md`, and the record `progress/impl_billing_credit_simulator.md`. Feature 20 is `in_review`. Write `progress/review_billing_credit_simulator.md`.

- **On APPROVED:** set 20 to `done` (that line only) and append the effort entry to `progress/history.md` against #8 (`../order-to-cash-dotnet/progress/history.md` line 1261: ≈1 h 04 min first artefact → verdict, approved first pass) and #7 (`../order-to-cash-nestjs/progress/history.md` line 903). Classification: **full group** (the leader's reason: R44 is a wire / saga-compensation claim). Durations the leader measured from agent runs: implementer ≈31 min (1 878 s), one premise check ≈35 s; add your own. Name each inherited #7 / #8 finding **avoided** or **recurred**.
- **On REJECTED:** set 20 to `in_progress` and write "What must change", each item naming the test and the arm that will prove it. Round 1; one more round is allowed without asking the maintainer.

## What the leader established (with commands) — locate, do not trust

- Files newer than the implementer brief (`find services packages tests specs/shared .env.example -newer progress/brief_impl_billing_credit_simulator.md`), exactly: `.env.example`; `services/billing/src/otc_billing/{composition.py,infrastructure/settings.py,infrastructure/credit/always_approve.py,infrastructure/credit/simulator.py}`; `services/billing/tests/integration/{conftest.py,test_credit_simulator.py}`; `services/billing/tests/unit/{test_billing_settings_env.py,test_credit_simulator.py,test_credit_simulator_settings.py}`; `specs/shared/test-matrix.md`; `tests/architecture/test_composition_env_reads.py`. All are inside the brief's bounds (the brief allowed `services/billing/tests/**` and the `infrastructure/credit/` directory). Feature 19's files are uncommitted in the same tree; review only feature 20's changes (feature 19 is `done`).
- **#7's N6 is already resolved in #9**, contrary to the impl report's line 91: `specs/shared/test-matrix.md:158-159` already reads `billing/infrastructure/credit-simulator.spec` for R42 and R43 (the leader's `grep`). Correct the record; no SA is owed.
- Feature 20 is `in_review`; only `otcpy-n8n` runs. **Do not start the developer stack.**
- Reported, not verified: `quality.sh` exit 0, 3 160 → 3 234 passed (+74); 20 arms red then restored; the simulator is the default binding, as the implementer says #7 and #8 bind it.

## Questions to rule on

1. **A13 (impl report line 63, 102): a guard whose failure does not name its claim.** "Clamp instead of refuse" fails `test_r43_a_bad_rate_refuses_to_boot_naming_the_value_before_connecting` only by `nats.errors.NoServersError` after ≈131 s of retries. CLAUDE.md: a guard's failure must name its claim (feature 18's N1/N2). Rule whether this blocks, and if so what the test must assert before any connection is attempted.
2. **The ordering (acceptance 1):** swap the `.99` check and the draw; make the `.99` branch consume a draw; confirm each fails a named test deterministically (rate `1`, source returning `0`).
3. **`CREDIT_FAILURE_RATE` parsing — the Python-forced row.** The implementer chose a numeral-shape regex plus a finite check via `BeforeValidator` (the decorator census rejects `@field_validator`). Attack it: `"nan"`, `"inf"`, `"1_0"`, non-ASCII digits (`"٠.٥"`), `" 0.5 "`, `"0.5\n"`, `"1e-1"`, `"-0"`, `"1.0000000000000001"`, `""`, absent. Which does R43 require refused, and is each refusal's message naming the value? Is the ledger row's "#7 relied on X; #8 supplied Y" half cited with file and line?
4. **R43's composition read (#8 A1):** delete the settings read in `composition.py`, and bind always-approve by default instead of the simulator; does a named test fail for each? Re-run `tests/architecture/test_composition_env_reads.py` with the literal entry removed.
5. **R44:** are the simulated and genuine rejection payloads compared to each other, read back from the outbox `payload` column and from the RPC reply (never a hand-typed key list, #7 N1)? Corrupt the cents branch's reason; transpose a payload field.
6. **The measured-rate theory** (#8's only guard against a rate applied at half strength): arm `rate * 0.5` and an off-by-one at the boundary (`<` versus `<=`).
7. **Unplanned mutations:** at least three of your own at the call sites (composition → simulator constructor arguments, settings → composition, simulator → port result).
8. **Feature 19's untouched seam:** confirm no `domain/`, `application/` or `presentation/` file changed in this feature (`BC15`).

## Bounds

Read-only except `progress/review_billing_credit_simulator.md`, feature 20's status line and, on approval, `progress/history.md`. Arming backups in `.arm/review20/` with `sha256`; restore by `cp` + `cmp`, never `git checkout` / `restore` / `stash`; clear `__pycache__` and `.mypy_cache`; timeouts kill the whole process group. Run `./quality.sh` once with the stack down. Return only "result in `progress/review_billing_credit_simulator.md`" plus the verdict and at most 5 lines.
