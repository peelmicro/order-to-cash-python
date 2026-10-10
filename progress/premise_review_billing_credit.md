# Premise check — brief_review_billing_credit.md

FALSE       "`test_outbox_copy_parity.py` +238/−… lines" (brief line 11) — `git diff --numstat tests/architecture/test_outbox_copy_parity.py`: `180 58`. Insertions are 180; 238 is insertions + deletions (180+58).
VERIFIED    67 of 67 `tasks.md` boxes ticked — `grep -c '^- \[x\]'` = 67, `grep -c '^- \[ \]'` = 0
VERIFIED    51 task lines carry `[ARM]` — the stated grep prints 51
VERIFIED    feature 19 `in_review`, diff changes that one line — `git diff feature_list.json`: 1 insertion, 1 deletion, `"pending"` -> `"in_review"`
VERIFIED    only `otcpy-n8n` runs — `docker ps --format '{{.Names}}'`: `otcpy-n8n`
VERIFIED    outside `services/billing/` git status lists Orders'/Fulfillment's settings.py and their two settings tests, the five named architecture tests, two new ones (`test_billing_rpc_error_retryability.py`, `test_kafka_client_ids.py`, both `??`) — `git status --short | grep -v services/billing` (also modified: .env.example, feature_list.json, progress/current.md, test-matrix.md, uv.lock; untracked specs/billing_credit/ and progress files)
VERIFIED    Orders/Fulfillment `client_id` gains `pattern=r"^[A-Za-z0-9._-]+$"` and nothing else — `git diff` of both settings.py: only a reformat to multi-line plus the `pattern=` line
VERIFIED    all those files are on `tasks.md`'s file list — `grep -c` per name in tasks.md: 2 each (1 each for the two settings tests, named in a glob-style entry at line 15)
VERIFIED    design.md §8.5, §10.2, §16.1, §17 exist — `grep -n '^#'`: 359 `### 8.5 The error mapping`, 397 `### 10.2 The parity guard`, 529 `### 16.1 Open for the gate`, 537 `## 17.`
VERIFIED    impl report §5, §6, §8 exist — `grep -n '^#'`: `## 5. Deviations` (45), `## 6. Arming` (61), `## 8. Live boot` (325); also K5 at 535, H8 at 234, J1 at 292
VERIFIED    `progress/spec_billing_credit.md` § Gate ruling — line 73 `## Gate ruling (maintainer, 2026-10-08)`; design §16.1 G1 is the zero-amount hold
VERIFIED    tasks H8, J1, K5 exist and are ticked — tasks.md:100 `- [x] H8 **[ARM]** BC32's population ... (#8 id 55)`, :111 `- [x] J1 **[ARM]**`, :119 `- [x] K5`
VERIFIED    BC11, BC12, BC24, BC32, BC34, BC35, BC37, BC38 in requirements.md — `grep -c` counts 4, 3, 3, 3, 4, 3, 3, 5
VERIFIED    L8, L11, L12, L14, L25 rows in design.md — lines 131, 134, 135, 137, 148 (`| L8 | B8 | The Σ is computed from committed state, after the lock |`, etc.)
VERIFIED    #8 history line 1215 is the feature 19 entry, ≈5 h 39 min, REJECTED round 1, "4 blocking defects, all guards" — sed: 1215 heading `billing_credit (id 19, phase 10) — 2026-09-05`; "Total ≈5 h 39 min from the first spec file to the final verdict"; "REJECTED, 4 blocking defects, all guards" (the entry says "REJECTED on round 1, approved on round 2")
VERIFIED    #7 history line 882 is the feature 19 entry — `sed -n 882p`: `## billing_credit (id 19, phase 10) — 2026-08-22`
VERIFIED    impl report: `./quality.sh` exit 0, 3111 passed = +327 over 2784 — impl:39 "exit **0**, 609 s ... **3111 passed = +327 over the baseline of 2784**"; 3111-2784 = 327
VERIFIED    A2 331 s, second run 354 s, third 609 s attributed to machine load — impl:31 "331 s, **2784 passed**"; impl:39 "second run ... 354 s: the third was slower because the machine was loaded"; log mtimes `.arm/bc19/quality1.log` 06:44:31, `quality2.log` 06:50:40, `quality3.log` 07:24:44 (consistent with ~354 s and ~609 s runs)
VERIFIED    "141 distinct arms, 0 survivors" as reported by the impl — impl:63 "**141 arms, every one seen red under its name**"; the arming table has 142 distinct first-column ids (one row header/extra), not re-counted by the leader and not claimed verified in the brief
VERIFIED    J1's 26 call-site arms each killed by an existing test — `grep -c '^| J1-'` = 26; impl:321 `J1-26-... killed by test_the_list_filters_and_pages_at_sql_level`
VERIFIED    deviation 1 = import order in two outbox copies, `# ruff: noqa: I001` — impl:47; `services/billing/.../outbox/{writer,wire}.py` line 1 `# ruff: noqa: I001 - the copy keeps the canonical's import order` (line 1, before the docstring, as the brief says)
VERIFIED    deviation 4 = `release` checks a negative exposure before "nothing outstanding" — impl:50
VERIFIED    deviation 9 = first `B5` "check only per order" arm survived, re-run removing all three cross-order checks — impl:55
VERIFIED    deviation 13 = `R40` `DONE` on its domain test alone — impl:59
VERIFIED    responder bound `pool_size = bound + 1` — `services/billing/src/otc_billing/composition.py:270` `pool_size=bound + 1,`
VERIFIED    K1–K5 live walkthrough ran and altered dev databases, K5 holds the register — impl:325-535; impl:541 "`credit_items` + 4 rows ... `outbox` 21 -> 26"
VERIFIED    spec_author ≈26 min, brief 17:49 → design.md 18:15 on 2026-10-08 — `stat`: brief_spec 17:49:34, design.md 18:15:26 (1552 s by mtime; brief says 1 563 s, ≈ same, probably the agent's own timer)
VERIFIED    implementer second run ≈86 min (5 180 s) ending 07:26 on 2026-10-09 — `stat`: impl_billing_credit.md mtime 07:26:24 (birth/ctime shows 06:00 for the file's latest creation); 5180 s = 86.3 min
VERIFIED    first implementer run began ≈18:37 — `stat`: brief_impl 18:36:14, premise_impl 18:36:40; `.arm/a2_quality.log` 18:42:57
UNVERIFIABLE first implementer run stopped ≈19:02 when the Claude Code session ended, ≈25 min — no file mtime marks the stop; the gap 19:02 → ~06:00 has no artefact
UNVERIFIABLE "three premise checks of ≈1 min each" — two premise files exist (premise_billing_credit_spec.md 17:49:28, premise_impl_billing_credit.md 18:36:40); the third is this one; durations are not recorded in any file
UNVERIFIABLE `quality.sh` exit 0 / 3 111 passed — the brief marks it "reported, not verified"; only a `quality.sh` run settles it
UNVERIFIABLE leader read the Orders/Fulfillment diffs — a statement about the leader's action (the diffs themselves were verified above)
UNVERIFIABLE maintainer reference ~360 s for quality.sh — maintainer's statement, no file

Counts: VERIFIED 28, FALSE 1, UNVERIFIABLE 5
Verdict: DO NOT ACT as written (1 FALSE; minor: a diff-stat figure, the numbers 180/58 should be read for 238).
