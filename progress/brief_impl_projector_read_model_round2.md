# Brief — implementer, feature 24 `projector_read_model`, round 2 (after rejection 1)

**Task:** close the findings of `progress/review_projector_read_model.md` exactly as its "What must change before re-review" section (items 1 – 5) states them: **B1, B3, B4** (blocking) and **B2, N3 (the three docstrings only), N4, N5** (bundled). Read the "Defects" section and the Q4, Q8 and traceability probes that prove each one. Append a "Round 2" section to `progress/impl_projector_read_model.md` as you go (each finding: the change, the arm with its verbatim failure, the green re-run), update `tasks.md` boxes and `requirements.md` §3 where a finding names them, and set feature 24's status line from `in_progress` to `in_review` when done (that one line only; read `git diff feature_list.json` after). Return a summary of at most 10 lines. Read `CLAUDE.md` on disk first.

## Already done by the leader (do not redo)

- N3's `design.md` half (the `DuplicateKeyError` sentence of §5.1 and the `$min` sentence of §5.3 now state the measured premises).
- Route R-1: two acceptance items appended to feature 27 in `feature_list.json`. Your record's §11 sentence "Feature 27 must …" can now cite them instead.

## Bounds

`tasks.md`'s file lists stand. **B3 changes a shared guard** (`tests/architecture/test_registration_behaviour.py`): the stricter rule must still pass for orders, fulfillment, billing and notifications, and you arm it against the projector's real root with the review's `Q8b` shape (one handler, class-attribute self-registration drained by a helper) while keeping `K3-pipeline`. List the new instrument's premises and arm them (CLAUDE.md: changing an instrument swaps its premises). After all fixes run `tests/architecture` in full, the projector suite, the Orders parity guard and the seed constants test; then `./quality.sh` once with the developer stack down, and record exit code, duration and pass count. Arming protocol as before (`.arm/p24-r2/`, sha256, `cmp` on restore, process-group kill on timeout). Bound every wait with `asyncio.timeout(...)`. No git command that writes the index or working tree. Backlog 214's three `composition.py` files stay untouched.
