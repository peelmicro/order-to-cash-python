# Brief — implementer, feature 17 `fulfillment_stock`, fix round (round 2 of review)

**Premise-checked:** `progress/premise_impl_fulfillment_stock_round2.md` (0 false; its one conflict, the `src` bound against the arms, is corrected below).

**Task:** close the round-1 rejection in `progress/review_fulfillment_stock.md` §6 (defects D1–D7) by doing §7 items 1–6 and 8, exactly as written there. Item 7 (D4, feature 18's acceptance item) **is already done by the leader**: do not touch it. Feature 17 is `in_progress` (set by the reviewer). The reviewer found no production-code defect: **§7 says the code itself needs no change.** If a fix appears to need a permanent source change under `services/fulfillment/src/`, stop and report instead.

## Inputs

- `progress/review_fulfillment_stock.md` §6 (D1–D7) and §7 (items 1–8): the instructions, the suggested test names, and the arms (`R1`, `M1` ×2, `M9`, `I5`, `D5a`). The reviewer's arm scripts and backups are in `.arm/review17/` (`a_r1.py`, `log.md` with the `Q6` real-F-j fixture); read them, do not overwrite them.
- Your own round-1 record `progress/impl_fulfillment_stock.md` (its §2 holds the corrected line numbers D5 asks you to carry into the spec text; re-verify each against the file before writing it).
- `specs/fulfillment_stock/{design,requirements,tasks}.md`.

## Bounds

- **Code:** permanent edits to test files only: `services/fulfillment/tests/integration/{test_stock_repository.py,test_stock_release_idempotency.py,conftest.py}` (the conftest only if D6's message needs it) and `services/fulfillment/tests/unit/test_stock_reservation_service.py`. **No permanent change** under `services/*/src/`, `packages/`, other services or `tests/architecture/`. Arms **do** edit `src` temporarily (`stock_repository.py` for R1 and M9, `stock_reservation.py:115` and `:170` for M1, the I5 site, and `application/handlers.py` / `composition.py` if you re-arm G8 with the real F-j pipeline); each is restored by `cp` + `cmp` from its `.arm/fix17/` backup before the next step.
- **Text:** `specs/fulfillment_stock/design.md` and `requirements.md` — line citations listed in D5 and ledger row L1 / §17's id 49 and id 79 lines (substance unchanged, item 1 and D5); `progress/impl_fulfillment_stock.md` — append a **"Round 2"** section (what changed, each new arm with backup path, `sha256`, verbatim red failure and green re-run; the `quality.sh` result) and fix §8.1, G8's description and §7's id 49 / id 79 dispositions in place (D7). Nothing in `specs/shared/` except, if a new test name proves a matrix row, `test-matrix.md` column 5 for R30–R35.
- `feature_list.json`: feature 17's status line only — set `in_review` when done.
- Arming protocol from `CLAUDE.md` on disk: backup into `.arm/` (use `.arm/fix17/`) with `sha256`, ONE named test per arm, timeouts kill the whole process group, restore by `cp` + `cmp`, clear `__pycache__` / `.mypy_cache`, re-run green. The failure must name the claim (that is D6's point).
- For each new test, ask "what fails if I revert this?": the arm is the revert of the production line the test guards, and a test that stays green under it is not done.
- Developer stack stays stopped (only `otcpy-n8n`). Never two test runs against the same containers at once. No git command that writes the index or working tree.

## Output

Set 17 to `in_review`. Return only "result in `progress/impl_fulfillment_stock.md` § Round 2" plus at most 5 lines: `quality.sh` exit, count and duration; each of the new arms red/green; anything from §7 not done and why.
