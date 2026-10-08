# Premise check — brief_review_fulfillment_stock_round2.md

VERIFIED round-1 review has verdict REJECTED — review_fulfillment_stock.md:3 "Verdict: REJECTED"
VERIFIED round-1 review §6 holds D1-D7 — grep of lines 125-137 shows D1..D7; §7 (line 139) holds items 1-8 (line 150 item 8 quality.sh)
VERIFIED impl report has a Round 2 section — impl_fulfillment_stock.md:720 "## Round 2"
VERIFIED feature 17 is in_review — feature_list.json id 17 status "in_review"
VERIFIED feature 18 acceptance carries the SA-4 despatch item — id 18 third item cites D4, design §6.3/§15, stock_keys_of_order + lock_order_items, both race outcomes, FS25 despatch half (#8 id 79), READ COMMITTED (#8 id 54): covers all four parts of review D4
VERIFIED every .arm/fix17/bak/*__services__* cmp-identical to live path — 6 backups (D5a, I5, M9, R1 -> stock_repository.py; M1a, M1b -> stock_reservation.py), all 6 printed SAME; the dir holds only those 6
VERIFIED five files modified after round-2 impl brief (08:59:26) — mtimes 09:00:10 / 09:03:03 / 09:03:21 / 09:02:53 / 09:02:30; find -newer also lists feature_list.json, current.md, impl report (the brief's "plus" list omits current.md, minor)
VERIFIED round-1 brief's first bullet specifies the effort entry — brief_review_fulfillment_stock.md:5 (history.md entry vs #8 line 999 / #7 line 842)
VERIFIED "reported" claims appear in impl Round 2 — R1, M9, M1a, M1b red/green rows; I5 text "the release never waited on the held stock row"; D5a re-run; "Exit 0, 2690 passed"
VERIFIED D3 host-level UNAVAILABLE not done, test-matrix.md unchanged, with the stated reasoning — impl:754
VERIFIED src lines :115 and :170 both hold new_id=scope.ids.new — sed of stock_reservation.py
VERIFIED only otcpy-n8n runs — docker ps --format {{.Names}} -> otcpy-n8n
VERIFIED durations arithmetic: 5463 s = 91 min; 574 s = 9.6 min (~10)
UNVERIFIABLE leader-measured run times (27 min, 1h57, premise checks 3.5 min) — agent timings are not on disk
UNVERIFIABLE quality.sh 2690 passed / arms red-green as true results — only a suite run settles it (reviewer re-runs them)
CONFLICT none with CLAUDE.md (reviewer sets done; second rejection escalates to maintainer; ledger in design.md for sdd:true)

Totals: VERIFIED 12, FALSE 0, UNVERIFIABLE 2, CONFLICT 0. SAFE TO ACT.
