# Brief — implementer, feature 24 `projector_read_model`, round 3 (after rejection 2; maintainer-approved, scoped)

**Task:** close exactly **B5, B6 and N9** of `progress/review_projector_read_model.md` "Round 2 — what must change before re-review" (items 1 – 3), and nothing else. Read that section and the Round 2 defects table first; the reviewer's probe shapes are in `.arm/p24-review2/` (`shapes.py` holds `S5`, `S6`, `S8`; `B3r-outermost.py`). Append a "Round 3" section to `progress/impl_projector_read_model.md` as you go (each finding: the change, every arm with its verbatim failure, the green re-run), update the `tasks.md` K3 / J1 notes where they state what the guard or fixture now does, and set feature 24's status line from `in_progress` to `in_review` when done (that line only; read `git diff feature_list.json` after). Return a summary of at most 8 lines. Read `CLAUDE.md` on disk first.

## Scope (binding)

- **B5** — `tests/architecture/test_registration_behaviour.py`: each recorded registration's statement must NAME what it registers — the recorded message class's name is the terminal identifier of the statement's message argument, and the handler class's name is the terminal identifier of the handler argument or appears inside the factory `lambda`'s body (or an equivalent rule that fails `S5` and `S6` and passes the five real roots). The leader checked this is satisfiable: all 36 `register_*` statements in the five roots name both directly (`grep -n -A2 '\.register_\(command\|query\|event\)(' services/*/src/otc_*/composition.py`; counts 16 / 6 / 6 / 7 / 1). Arm it on the projector's real root with `S5` and `S6`; add an n = 1 F-j-alone sentinel; rewrite the header's F-j sentence (`:4-6`, `:14-18`) to what is then true.
- **B6** — same file: a sentinel with a registration helper `def` nested inside the root's function (`S8`), and premise (2) armed with `B3r-outermost`. List every premise of the guard as it now stands and state for each the arm that saw it fail; if one stays unarmed, say so — never "each armed" over an unarmed one.
- **N9** — `services/projector/tests/integration/test_timeline_projection.py`: scramble the R50 fixture's `eventId`s (neither ascending nor descending against `occurredAt`), fix the docstring, re-run `R50r-arrival-order` and `R50r-eventid-desc`; update `specs/shared/test-matrix.md` column 5 of R50 only if the case's name changes.

No other file. No production code. Backlog 214's three `composition.py` files stay untouched.

## Verification

`tests/architecture` in full, the projector suite, the Orders parity guard and the seed constants test; then `./quality.sh` once with the developer stack down (exit code, duration, pass count). Arming protocol as before (`.arm/p24-r3/`, sha256, `cmp` on restore, process-group kill on timeout). No git command that writes the index or working tree.
