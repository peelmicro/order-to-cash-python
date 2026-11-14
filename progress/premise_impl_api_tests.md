# Premise check — progress/brief_impl_api_tests.md

VERIFIED   feature 31 has seven acceptance items — `python3 ... len(acceptance)` printed 7 (status `pending`)
VERIFIED   `tests/saga_e2e/conftest.py` is 352 lines — `wc -l` = 352
VERIFIED   ASGITransport at conftest.py:311 — grep: `311: transport=httpx.ASGITransport(app=gateway)`
VERIFIED   `test_gateway_sse_signals.py` lines 6-12 and 201 mention uvicorn — grep -n -i uvicorn: lines 6, 12, 201 (real uvicorn socket)
VERIFIED   #8 history:3079 is id 31 api_tests entry; :3081 says "in-process, over real Kestrel, with HttpClient as the only client"
VERIFIED   #8 id 105 entry directly after — history.md has `## Id 105 ...causal_order_check_is_vacuous_without_causation_id` within the following ~20 lines
VERIFIED   #7 history:1168 is the api_tests entry header; 1176 is the "Acceptance criteria" line, the real-process evidence (`spawnRealService`, `node dist/main.js`) is on 1177 (off by one, content correct)
VERIFIED   #8 impl_api_tests.md section lines :56 (Scenario 1), :71 (Scenario 2), :83 (Scenario 3), :94 (Scenario 4), :102 (R49) — sed/grep -n of headings
VERIFIED   every named #7/#8 file exists — `ls` of the 5 #8 test files, 3 #8 progress records (impl/review api_tests, causal_order impl, two money impl records), 3 #7 files: all present
VERIFIED   #9 route files, problems.py, test_payment_register.py, test_stock_replenish.py exist — ls (routes_*.py, problems.py, wire.py all present under presentation/)
VERIFIED   matrix rows R1, R24, R48, R49, R61 each name feature 31 `api_tests` as API-half closer — grep of each row shows "feature 31 `api_tests`"
VERIFIED   matrix line 83 is the scoped-rows paragraph — sed -n 83p begins "**Scoped rows, and what closing them would take.**"
VERIFIED   Phase 17 counts 57 green / 1 scoped / 5 not yet green — matrix line 81 Total `| 63 | 57 | 1 | 5 |`
VERIFIED   quality.sh Phase 17: 23 min 10 s; pytest 5 231 passed in 843.28 s — progress/current.md:35
VERIFIED   "#8 added no package" in api_tests — `git show --stat c376b26` (#8 api test commit) touches no csproj/props/lock; only the gateway commit says "adding no package"
VERIFIED   #8 F1 wording — review_api_tests.md:157: R49 Status cell said "the third is the identical code path as the first"; review calls it false
VERIFIED   #8 shared-collection regression, 5 timeouts — history:3095-ish "shared collection caused 5 timeouts, fixed by splitting the collection"; impl_api_tests.md:311 "5 spurious failures ... TimeoutException"
VERIFIED   #8 reviewer reversed projector tiebreak — review_api_tests.md:41 "reverse the tiebreak ... [DepthField] = 1 -> -1", output fully reversed (:50)
VERIFIED   #8 baseline ≈1 h 30 min implementer, approved on first review — history: "09:33:16Z -> 11:03:39Z (about 1 h 30 min" and "approved on the first review"
VERIFIED   #7 baseline 8 sessions, approved on third review — history:1168/1170 "8 sessions ... 2 REJECTED, 1 APPROVED"
FALSE      "#7's two rejections were projector ordering defects (the R28 tie, then D4's causal-depth tiebreak)" — history:1183: the FIRST rejection was "not for finding [the R28 tie] but for closing R28 DONE with the requirement's own assertion deleted"; only the second was the projector statusRank tiebreak defect
VERIFIED   ports 5432 and 8080 held by kb-poc-* — docker ps: kb-poc-postgres-1 127.0.0.1:5432, kb-poc-proxy-1 0.0.0.0:8080; ss -ltn shows LISTEN on 5432 and 8080; only otcpy-n8n (5678) among otcpy-*

Counts: VERIFIED 21, FALSE 1, UNVERIFIABLE 0
Verdict: DO NOT ACT (one FALSE)
