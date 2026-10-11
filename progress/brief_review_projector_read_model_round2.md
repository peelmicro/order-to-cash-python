# Brief — reviewer, feature 24 `projector_read_model`, round 2 (full group)

**Task:** re-review feature 24 after rejection 1. Round 1's verdict and findings are in `progress/review_projector_read_model.md` (Defects; "What must change before re-review" items 1 – 5). The implementer's round 2 is the "Round 2" section of `progress/impl_projector_read_model.md`; its brief is `progress/brief_impl_projector_read_model_round2.md`. Feature 24 is `in_review`. Read `CLAUDE.md` on disk first.

## Verified by the leader this session

- `specs/shared/test-matrix.md` vs `HEAD`: the only changed cells are column 5 of R50 – R55 and the Done/TODO count cells of the §7 summary row and the Total row (parsed cell by cell).
- `feature_list.json`: 24 `in_review`; 214 `pending`; feature 27 gained two acceptance items (route R-1, the leader's).
- The leader edited `specs/projector_read_model/design.md` §5.1 and §5.3 (N3's design half).

## What to check (by command or mutation, not by reading the record)

1. **B1:** delete or neuter the stored-specification comparison in `read_model_indexes.py` your own way (not only the implementer's `if False and`): does a named `PR52` case fail on a real server, with a message naming the index?
2. **B3:** the new rule in `tests/architecture/test_registration_behaviour.py`. Re-run your round-1 `Q8b` probe against the projector's real root; then try at least one shape the implementer did not list (e.g. a registration inside a `for` over a module-level tuple, a `functools.partial`, a dict-dispatch helper, `getattr`-based call). Does the rule still pass all five real services? Were the new instrument's premises listed and armed?
3. **B4:** re-run `R50-arrival-order`; check the fixture now separates `occurredAt` order, `eventId` order and arrival order, and that the docstring states what the fixture does.
4. **B2, N3 (docstrings + the two design sentences), N4, N5:** one check each.
5. **Regression:** confirm `quality.sh`'s recorded run (`482 s`, `4082 passed`) from its log under `.arm/p24-r2/` or wherever the record points, and run `tests/architecture` plus the projector suite yourself. You need not re-run the whole round-1 probe set; re-run any round-1 arm whose path the round-2 changes touched.

## Rules and output

As round 1 (`progress/brief_review_projector_read_model.md` "Rules"; backups under `.arm/p24-review2/`). Append a "Round 2" section to `progress/review_projector_read_model.md` with the verdict (APPROVED / REJECTED), each finding with its proof and disposition. On approval set feature 24's status line to `done`; on rejection to `in_progress`; that line only. Return only "result in `progress/review_projector_read_model.md`" plus the verdict and the count of blocking findings.
