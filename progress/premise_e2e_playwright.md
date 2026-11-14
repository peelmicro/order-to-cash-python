# Premise check: brief_impl_e2e_playwright.md (2026-11-14)

VERIFIED #8 history.md:3109 reads "Id 32 e2e_playwright (phase 19, full process)" (sed -n 3109p)
VERIFIED #7 history.md:1201 is the e2e_playwright entry, "approved on the second review, after one rejection"
VERIFIED #8 package.json:19 is the test:e2e script (sed -n 19p)
VERIFIED #8 line counts 48/128/116 (e2e files) and 267 (dev-stack.sh) (wc -l)
VERIFIED #8 playwright.config.ts exists; line 20 reads E2E_BASE_URL ?? WEB_PORT (default 3010)
VERIFIED #7 e2e/ holds the same three files (ls)
VERIFIED place.page.ts:132,145,152,159 are the four [for]="fieldId(line, ...)" labels (product, quantity, unit-price, line-discount)
VERIFIED vite.config.ts:36 and :51 are include patterns; tsconfig.spec.json:12 is "include"
VERIFIED .gitignore:43 playwright-report/, :45 test-results/
VERIFIED test-matrix.md:83 holds "The one row not yet green is R28 (its e2e half, feature 32)"; :128 is R28 with "integration half DONE ... e2e half TODO"; totals line 81 reads 63 / 62 / 0 / 1
VERIFIED #7 useOrderDetail.ts:112 is refetchInterval (the fix site); #8 use-order-detail.ts:59-71 is the refetchInterval/observedNonTerminal logic
VERIFIED #7 review_e2e_playwright.md has D1, D2, D7 (D7 a narrow residual of the D2 fix)
VERIFIED README uvicorn commands at lines 145-178 (ports 8101-8105), Gateway/GATEWAY_PORT at ~204 (range 111-209 is loose: 111 is a quality.sh note, "Running the services" starts at 140)
VERIFIED .env.example:25 POSTGRES_HOST_PORT=5432, :97 REDPANDA_CONSOLE_HOST_PORT=8080
VERIFIED init.sh section 5d: SPEC_FILES excludes test-matrix.md ("EXEMPT by design") at init.sh ~320-322
VERIFIED .arm/web29r3/s2r1/live/ exists (bare2.mjs, *.out)
VERIFIED progress/review_web_app.md:543 "## Stage 2 re-review (fix round 1)"
VERIFIED scripts/seed_parity.py exists (it is an #8-vs-#9 parity dump tool; a `seed` service also exists under services/ per README:91)
VERIFIED apps/web/package.json:73 "packageManager": "pnpm@12.8.1"
VERIFIED scripts/dev-stack.sh absent in #9 (ls: No such file)
VERIFIED ~/.cache/ms-playwright holds chromium-1234, chromium-1243 (+headless shells, ffmpeg-1011); no 1248
VERIFIED npm view: 1.64.1 2026-10-14T11:58Z, 1.65.0 2026-11-05T18:30Z, 1.65.1 2026-11-13T21:12Z
VERIFIED Playwright v1.64.1 browsers.json chromium revision 1248 (raw.githubusercontent.com)
VERIFIED feature 32: status in_progress, 4 acceptance items; item 4 is the carried feature-29 keystroke check
VERIFIED feature 36: 6 items, last is "carried from e2e_playwright (id 32, acceptance item 3...)"
VERIFIED Phase 18: progress/history.md:1580 and current.md:63 give 5 288 pytest / 1 625.85 s; web 35 files / 687 tests
VERIFIED #8 feature_list.json has id 106
VERIFIED docker ps: no otcpy-* containers; kb-poc-postgres-1 127.0.0.1:5432, kb-poc-proxy-1 0.0.0.0:8080; ss -ltn shows 5432 and 8080 listening
UNVERIFIABLE "#8's condition C2 / C1 / N1 / N2 / id 106 content", "llama-server held ~7 of 16 cores": historical or live-load claims, not settled by one command (id 106 existence only confirmed)
UNVERIFIABLE "Vitest still collects 35/687 with e2e added": needs a suite run

Counts: 27 VERIFIED, 0 FALSE, 2 UNVERIFIABLE. Verdict: SAFE TO ACT.
