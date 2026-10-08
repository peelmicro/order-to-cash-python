# Premise check — brief_impl_fulfillment_stock.md

VERIFIED  Gate-record paragraph in design.md 16.1 — `grep -n "Gate record"` -> line 500 (under "### 16.1 Open for the gate", line 498), G1/G2/G3 "as recommended".
VERIFIED  Feature 17 is in_progress — feature_list.json parse: `17 in_progress`; git diff shows only `pending -> in_progress`.
VERIFIED  Feature 29 acceptance carries #8 id 101 — "inherited criteria: #8 ids 98, 100, 101, 102, 103, 106; ..." (status pending).
VERIFIED  tasks.md runs A1 -> L6 — first task `A1` (line 27), last `L6` (line 143).
VERIFIED  L4 mentions the id 101 attachment — "the hand-over to feature 18 (15) and the id 101 attachment for feature 29".
VERIFIED  D3 and F5 ask for branch enumeration — D3 line 57 "Enumerate in the impl report every branch of run()", F5 line 79 "every branch of start, run, _serve and _drain".
VERIFIED  CLAUDE.md arming protocol: .arm/, sha256, cmp, process-group timeout, cache clearing — CLAUDE.md lines 118-120 (`__pycache__`, `.mypy_cache`).
VERIFIED  .arm/ is git-ignored — `git check-ignore -v .arm/x` -> `.gitignore:87:/.arm/`.
VERIFIED  #8 history anchor :999, three review rounds, two blocking defects of one shape — line 999 is `## fulfillment_stock`, "three review rounds, two blocking defects of one shape".
VERIFIED  #7 history anchor :842, rejected once, unplanned fifth mutation survived — line 842 heading; line 845 "REJECTED on pass 1 ... 1 unplanned fifth mutation survived".
VERIFIED  Compose file real — docker-compose.infra.yml exists; `docker compose -p otcpy -f docker-compose.infra.yml config --services` lists 12 services (postgres, kafka, nats, ...). Containers exist, stopped.
VERIFIED  Only otcpy-n8n running — `docker ps` -> `otcpy-n8n` only (up 58 s, health starting); all other otcpy containers Exited.
VERIFIED  Nothing in services/, packages/, tests/ changed — `git status --porcelain -- services packages tests apps | wc -l` -> 0.
VERIFIED  Brief's "do not edit" bounds consistent with tasks.md — tasks may-touch list includes specs/shared/test-matrix.md (L3), requirements.md 3 status cells, feature 17 status line; must-not-touch includes progress/current.md; brief bounds are the same or tighter.
UNVERIFIABLE  "git status at the gate showed only the spec, the two progress files and the feature_list status line" — historic snapshot; the current status additionally has `M progress/current.md` and a third untracked progress file (premise_fulfillment_stock_spec.md). No services/packages/tests change either way.
NOTE (not a conflict)  Brief line 15 attributes the relay-copy branches (send raises, stop-on-failure) to "tasks D3 and F5"; D3/F5 cover StockTransactions.run and the responder only. The relay branches fall under C-section; brief demands more than tasks, forbids nothing.

CONFLICTS with tasks.md: none found (brief forbids nothing tasks.md mandates).

Counts: VERIFIED 14, FALSE 0, UNVERIFIABLE 1, CONFLICT 0.
Verdict: SAFE TO ACT
