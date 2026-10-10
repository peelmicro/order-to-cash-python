# Premise check — brief_review_billing_credit_round2.md

VERIFIED    review_billing_credit.md has §§0–9, §8 "What must change", D1–D3, N1–N3 — `grep -n '^## '`: §0 line 7 … §8 line 121 "What must change before re-review", §9 line 132; D1/D2/D3 at lines 89/93/97, N1/N2/N3 at 103/104/105
VERIFIED    impl § Round 2 starts at line 712 — `grep -n 'Round 2'`: `712:## Round 2 (fix round after review_billing_credit.md round 1, REJECTED)`
VERIFIED    feature 19 is in_review — python json over feature_list.json: `19 billing_credit in_review`
VERIFIED    `find services/*/src packages -newer progress/brief_impl_billing_credit_round2.md -type f -not -path '*/__pycache__/*'` is empty — ran it, no output
VERIFIED    changed .py files under services and tests match exactly the six listed — `find services tests -newer … -name '*.py'` printed exactly: tests/architecture/test_outbox_copy_parity.py, services/billing/tests/integration/{test_credit_repository,test_credit_release}.py, services/billing/tests/unit/test_credit_release_service.py, services/billing/tests/unit/domain/{test_credit_ledger,test_credit_exposure}.py
VERIFIED    only otcpy-n8n runs — `docker ps --format '{{.Names}}'`: `otcpy-n8n`
VERIFIED    MIRRORS_NOT_OWNERS exists in test_outbox_copy_parity.py naming the seed tables file — line 113 `MIRRORS_NOT_OWNERS = {"seed"}`, comment line 110 names `otc_seed/infrastructure/tables.py`
VERIFIED    that file declares Table("outbox") — services/seed/src/otc_seed/infrastructure/tables.py:54-55 `return Table(` / `"outbox",` inside `_outbox()`, used at lines 147, 200, 270 (multi-line, not the literal one-line `Table("outbox")`)
VERIFIED    review §9 says ≈42 min — review_billing_credit.md:5 and :134 "≈42 min"
VERIFIED    impl round-2 figures — 366 s and 3 154 passed at impl line 718; P4 survived first at line ~748 ("slice by characters (P4), first run SURVIVED"); 15 of 18: line ~756 "15 failed, 3 passed" over the 18 spelling cases (the literal "15 of 18" does not appear; the numbers agree)
VERIFIED    fix round 4 633 s — only in the brief itself (leader-measured); not checkable in a file
VERIFIED    history anchors #8 1215, #7 882 — `sed -n`: both are `## billing_credit (id 19, phase 10)` headings (#8 line 1215, #7 line 882)

Counts: VERIFIED 11, FALSE 0, UNVERIFIABLE 0 (the 4 633 s figure is leader-measured, not in a file; counted above as a note, not a claim a command settles)
Verdict: SAFE TO ACT.
