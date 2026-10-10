# Brief — implementer, feature 19 `billing_credit`, round 2 (fix round)

**Task:** fix the three blocking defects and the three non-blocking items of `progress/review_billing_credit.md` (round 1, REJECTED), exactly as its **§8 "What must change"** instructs, items 1 – 5. Item 6 is the leader's and is done (backlog entry 213, filed in `feature_list.json`). Feature 19 is `in_progress` (set by the reviewer). Read the review's §4 (D1 – D3 and N1 – N3) and §8 in full before starting; §4 holds the mutations that survived, and each one is the arm your fix must turn red.

## Bounds

- **Test files only:** `services/billing/tests/**` and `tests/architecture/test_outbox_copy_parity.py`. **No production file changes** (the review found every production path correct). If a fix seems to need a production change, stop and report it instead of making it.
- Also yours: `progress/impl_billing_credit.md` (append a "Round 2" section, and correct §9 as the review's §8 item 5 says) and feature 19's status line in `feature_list.json` (set `in_review` when done; that line only — entry 213, further down the file, is the leader's and must not change).
- `specs/billing_credit/tasks.md` still outranks this brief; the review's §8 is the scope of this round.
- No git command that writes the index or working tree. The developer stack stays stopped (only `otcpy-n8n` runs); do not start it.

## Process

- Arming protocol (grep `CLAUDE.md` on disk): backups in `.arm/bc19r2/` with `sha256`; one named test per arm; the failure message must name the claim; restore by `cp` + `cmp`, never `git checkout`; clear `__pycache__` / `.mypy_cache`; a timeout kills the whole process group.
- **Run each arm the review names verbatim** (U8, U9, U10, `Q1-code-on-docstring-line-plus-file-noqa`, R9a, `D6-mine-mapper-aware-local`, the four census forms of §4 D3, the `['notifications']` arm). A prescribed mutation is evidence only once it has been run. Record each red message verbatim and the green after restore.
- **D1's fixtures must not satisfy the relation by accident:** the second order's exposure makes available-after differ from both the limit and the pre-release value; say which three values each fixture produces.
- **D2 and D3 change an instrument:** list the new instrument's premises in its docstring and arm the ones that matter (CLAUDE.md, "Changing an instrument"). Keep the sentinels parametrised over both copy services.
- Re-run `./quality.sh` with the stack down at the end (exit code, duration, pass count against round 1's 3 111).

## Output

`progress/impl_billing_credit.md` § Round 2. Set feature 19 to `in_review`. Return only "result in `progress/impl_billing_credit.md` § Round 2" plus at most 5 lines: the `quality.sh` result, the arms run and seen red, and any item not done.
