# Premise check — brief_review_billing_credit_simulator.md

VERIFIED    `find … -newer progress/brief_impl_billing_credit_simulator.md` population equals the brief's list — find printed 12 files: .env.example; test-matrix.md; tests/architecture/test_composition_env_reads.py; billing integration/{conftest.py,test_credit_simulator.py}; unit/{test_billing_settings_env.py,test_credit_simulator.py,test_credit_simulator_settings.py}; src composition.py, infrastructure/settings.py, infrastructure/credit/{always_approve.py,simulator.py}; none extra, none missing
VERIFIED    feature 20 is in_review — feature_list.json: `20 in_review billing_credit_simulator`
VERIFIED    test-matrix.md:158-159 read `billing/infrastructure/credit-simulator.spec` — sed 158,159p; also true at HEAD (`git show HEAD:… | grep -o`), so N6 was resolved before this feature (the file's diff touches only the Status column and counts)
VERIFIED    impl report line 91 says N6 "not touched" — sed -n 91p
VERIFIED    impl report lines 63 and 102 describe A13 (clamp) failing by NoServersError after ~131 s — sed -n 63p (table row), 102p
VERIFIED    #8 history line 1261 is feature 20; ≈1 h 04 min and approved first pass — heading "approved first pass"; line 1272 row "Total, first artefact → verdict | ≈1 h 04 min"
VERIFIED    #7 history 903 is feature 20 — "## billing_credit_simulator (id 20, phase 10) — 2026-08-22"
VERIFIED    requirements.md 365–366 is the trilogy obligation, 373–393 span R42–R44 — sed: "> **Trilogy obligation.** … R42 and R43 identically"; 373 starts R42, R44 ends at 392 (`CREDIT_FAILURE_RATE = 0`.), 393 blank
VERIFIED    BC15 exists — specs/billing_credit/requirements.md:78 (and :184 test row); cited in composition.py:288
VERIFIED    decorator census rejects `@field_validator` — tests/architecture/test_cqrs_registration_explicit.py:230 `test_every_decorator_under_services_is_in_the_census_allow_list`; ALLOWED_DECORATORS (line 37) lists model_validator but not field_validator; impl report line 8 and 101 say the same
VERIFIED    impl report states 3160 → 3234 (+74) — impl report line 96 "3160 passed … 3234 passed (+74)"
VERIFIED    only otcpy-n8n runs — `docker ps --format '{{.Names}}'` printed `otcpy-n8n`
UNVERIFIABLE quality.sh exit 0 / 3234 passed, 20 arms red then restored, #7/#8 bind the simulator by default — the brief itself marks these "reported, not verified"; only a quality.sh run settles the first

Counts: VERIFIED 12, FALSE 0, UNVERIFIABLE 1
Verdict: SAFE TO ACT (0 FALSE).
