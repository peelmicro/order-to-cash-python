# Premise check — brief_impl_billing_credit_round2.md

VERIFIED    review §4 and §8 exist — `grep -n '^#'`: line 87 "## 4. Defects", line 121 "## 8. What must change before re-review"
VERIFIED    §4 holds D1–D3 and N1–N3 — lines 89, 93, 97 (D1–D3) and the "Non-blocking" block 101+ with N1, N2, N3
VERIFIED    §8 lists items 1–6, item 6 the leader's entry 213 — sed 121-131: items 1 (D1), 2 (D2), 3 (D3), 4 (N1–N3), 5 (impl report), 6 "Leader (not the implementer): file backlog entry 213 per §7"
VERIFIED    entry 213 exists in feature_list.json attached to feature 41 — `grep -n '"id": 213'` line 848; attached_to "orders_cancel_responder (id 41)"; id 41 at line 451, status pending
FALSE       "entry 213 above it" (feature 19's status line) — 213 is at feature_list.json:848, feature 19 at :351, so 213 is BELOW feature 19 (wording only; both entries exist)
VERIFIED    feature 19 is `in_progress`, set by the reviewer — feature_list.json:351-356 `"status": "in_progress"`; git diff shows pending -> in_progress; review C2/C5 say "19 -> in_progress"
VERIFIED    arm U8, U9, U10 appear in the review — §4 D1 and §8 item 1 (grep -c 4 each)
VERIFIED    arm Q1-code-on-docstring-line-plus-file-noqa — review §4 D2 and §8 item 2
VERIFIED    arm R9a — review §4 N1 and §8 item 4
VERIFIED    arm D6-mine-mapper-aware-local — review §8 item 4 (once; not in §4, which names the N2 arm only by description)
VERIFIED    the four census forms of §4 D3 — D3 lists annotated, constant, Core Table, another module; §8 item 3 repeats them
VERIFIED    the ['notifications'] arm — review §8 item 3 "existing ['notifications'] arm stays red"
VERIFIED    the review says no production file needs to change — §8 "no production file should change"; §4 D1 "the production code is right"
VERIFIED    round 1's pass count 3 111 — review line 9 "3111 passed in 326.63 s"; impl_billing_credit.md:39 "3111 passed"
VERIFIED    only otcpy-n8n runs — `docker ps --format '{{.Names}}'` printed only `otcpy-n8n`
VERIFIED    test paths in scope exist as targets — tests/architecture/test_outbox_copy_parity.py is modified in `git status`; services/billing tests are in the working tree

Counts: VERIFIED 14, FALSE 1, UNVERIFIABLE 0
Verdict: SAFE TO ACT in substance (1 FALSE, wording only: "above it" should be "below it"; no effect on the implementer's work).
