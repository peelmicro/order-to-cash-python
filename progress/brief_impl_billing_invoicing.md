# Brief — implementer, feature 21 `billing_invoicing` (phase 10, `sdd: true`, full group)

**Task:** implement feature 21 from its approved spec, `specs/billing_invoicing/{requirements,design,tasks}.md`, task by task in `tasks.md` order (A1 → L-close-out; 65 tasks). The maintainer approved the spec on 2026-10-09 with its one gate point, **G1, decided as recommended**: an out-of-range list request (a page past `2⁶³ − 1`, an `issuedBeforeMinutes` cutoff before year 1) answers success with no items and the true `page.total`, on **all three** list subjects — `billing.invoice.list`, `billing.credit.list` and `fulfillment.stock.list` — so `BI37` stands (`progress/spec_billing_invoicing.md` § Gate ruling; `design.md` §16.1). Feature 21 is `in_progress` (set by the leader). **`tasks.md` outranks this brief**: if anything here conflicts with a task, stop and report the conflict.

## What changed since the spec was written

- Feature 20's light follow-up has **landed**: `services/billing/tests/integration/conftest.py:377`'s `billing_host` docstring and `services/billing/tests/integration/test_credit_simulator.py` are final (the spec author's note "F1 must wait until the other agent's conftest edit has landed" is satisfied).
- The leader corrected one clause of `specs/billing_credit/design.md` §8.1 (the responder is `CreditResponder`; 21 extends its route table without a rename), as the spec author recommended.
- Features 19 and 20 are `done` and **uncommitted** in the same tree; this feature extends some of their files. Do not reformat or reorganise their code beyond what `tasks.md` names: the wrap-up splits the commits by file.
- **Baseline:** read it fresh as task A2 says. Do not take it from this brief.

## Process

- Follow `tasks.md`'s header exactly: the arming protocol, the files you may and must not touch (including the arm-and-restore exception for `services/orders/` in C6), the forbidden constructs. Grep `CLAUDE.md` on disk for the arming protocol before the first arm: backups go **into the repo-local, git-ignored `.arm/`** (use `.arm/bc21/`) with a `sha256` recorded; restore from the backup with `cmp`, never `git checkout`; a timeout kills the whole process group, never only the `uv` parent; clear `__pycache__` / `.mypy_cache` after a restore.
- **Run every prescribed mutation exactly as written** and record its verbatim failure (#8 feature 19's D1). #8 was rejected once on this feature because its tests could not see two things the code did right (`../order-to-cash-dotnet/progress/history.md` line 1305; `../order-to-cash-dotnet/progress/review_billing_invoicing.md`) — one was the discount: zeroing it left 273 tests green.
- **This phase's own rejections, to avoid repeating:**
  - Feature 19 round 1 D1: **a fixture satisfied the relation by accident** (every release fixture released the line's only exposure, so available-after equalled the limit). For every total, gross, net, discount and available-credit assertion, state in the report the plausible wrong values and show the fixture's expected value differs from each.
  - Feature 19 D2 / D3 / R2-1: **changing an instrument swaps its premises.** Any guard you extend (registration, write-path population, retryability) lists its new premises and arms them.
  - Feature 20 N1: a guard's failure must name its claim and fail fast — no failure that arrives only as a timeout or a connection error.
- Feature 17's rejection (three mutations that survived the whole suite) is why task J1 exists; do it as a search result first, then one mutation per call site.
- Assert values read back through the adapter, never values the test recomputes. Assert a reply's discriminating field before touching any collection in it. Construct races with a held lock (`wait_for_lock_waiters`), never by repetition.
- Ruff formats Python blocks inside Markdown: code quoted in `progress/impl_billing_invoicing.md` is quoted formatted.
- **Runs:** integration suites must pass with the developer stack down. It is stopped (only `otcpy-n8n` runs) and stays stopped until section K. Never run two test runs against the same containers at once; wait on a PID, never on `pgrep -f`. Run section K only after every container-backed suite has passed; start the stack with `docker compose -p otcpy -f docker-compose.infra.yml start`, read K5's register in `progress/impl_billing_credit.md` § Live boot first, and when the walkthrough is done stop everything you started so that only `otcpy-n8n` runs again (record `docker ps` before and after).
- Do not edit `feature_list.json` beyond feature 21's status line, nor `CLAUDE.md`, `progress/current.md`, or `specs/` beyond what `tasks.md` names. No git command that writes the index or working tree.

## Output

`progress/impl_billing_invoicing.md`, structured as the close-out task requires. Set feature 21 to `in_review` (that line only). Return only "result in `progress/impl_billing_invoicing.md`" plus at most 5 lines: the `quality.sh` exit code and pass count against A2's baseline, the number of `[ARM]` rows armed and seen red, any task left unticked, and any deviation from the design.
