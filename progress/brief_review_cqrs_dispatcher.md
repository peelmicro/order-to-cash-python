# Brief — reviewer, feature 43 `cqrs_dispatcher` (phase 8, `sdd: false`, full group)

**Task:** approve or reject feature 43. Write `progress/review_cqrs_dispatcher.md`; on approval set feature 43 to `done` and append its effort entry to `progress/history.md` (against #8's baseline; #7 has none — say so, as #8 did); on rejection set it to `in_progress`. Edit only that status line of `feature_list.json`. Read-only otherwise; no git command that writes the index or working tree. Return the verdict plus at most 8 lines.

## Inputs

- Acceptance: feature 43 in `feature_list.json`. Item 2 records a scope split decided by the leader: this feature proves explicit, decorator-free registration against test handlers; the per-service half is carried as acceptance items on features 15, 17, 19, 23, 24, 25 (check they are there).
- Implementer brief and report: `progress/brief_impl_cqrs_dispatcher.md`, `progress/impl_cqrs_dispatcher.md` (ledger, answers to the brief's questions 1–5, arming table).
- Change set (leader's `git status` plus mtimes, this session): `packages/cqrs/src/otc_cqrs/{__init__,dispatcher,errors,handlers,messages}.py`, `py.typed`, `packages/cqrs/tests/`, `tests/architecture/test_cqrs_registration_explicit.py`, feature 43's status line. The diffs in `pyproject.toml`, `test_money_guard.py` and `test_write_path_population.py` predate this feature (feature 13 and its review round; mtimes 09:07–09:38, the brief is 09:54).
- #8's record, whose defects are this feature's acceptance criteria: `../order-to-cash-dotnet/progress/history.md` 676–729 (D1 root-scope capture; D7 a guard reading the wrong source; D8 a fix that dropped a compile-time check; D9 a stale rule in an agent file; D10 a hardcoded file list). #8's code `../order-to-cash-dotnet/src/Cqrs/`, tests `../order-to-cash-dotnet/tests/Cqrs.UnitTests/`.

## Questions (research, do not assume)

1. **The typing gap the implementer disclosed:** registration cannot tie a handler's return type to its command's `R`, and `dispatcher.py:145,154,165` `cast(...)` the factory's result. Is this #8's D8 shape (a compile-time guarantee dropped)? Can a handler that returns the wrong type reach a caller typed as `R` with the suite and `mypy --strict` green? If so: is there a cheap fix (typed registration API, a runtime check) or is it a disposition with evidence? Probe it with a real `mypy --strict` run, not by reading.
2. **D1 from outside:** build a throwaway consumer: two dispatches in two independent scopes with a scoped dependency → two instances; and no module-level or dispatcher-held session.
3. **Zero-handler validation:** how is the universe of message types decided (the report says composition roots pass their message modules to `build`)? Can a command type escape the universe (defined in a module not passed, nested, imported under an alias, generic subclass) and so escape the zero check? Arm it.
4. **D7/D10:** does `test_cqrs_registration_explicit.py` read what "no import-time decorators" is about, by glob over the real population, and fail on a real decorator-style registration in a service file? Arm it against the real target (a temp file in the population), plus at least one defeat-list row the implementer did not run.
5. **Async semantics:** exception propagation unchanged, `CancelledError` not swallowed, no un-awaited task; event fan-out — what happens when the second of two event handlers raises?
6. **D9:** the implementer suggests CLAUDE.md record that messages subclass `Command[R]`/`Query[R]` and composition roots pass message modules to `build`. Is a rule-file change warranted, and does any rule-bearing file (CLAUDE.md, AGENTS.md, `.claude/agents/*.md`) now carry wording this design contradicts? Report the hits; do not edit.
7. Counts: 47 new tests (26 + 11 + 10) and `quality.sh` 1484 passed (stack up; the leader reconciles 1484 = 1436 + 1 F8 test + 47). Reconcile per-file figures against a run of your own.

Run the defeat list on the guards you probe and state which rows apply. Disposition every finding (fix → reject; accept with evidence and a re-open trigger; or re-open only if X); findings are fixed in this phase.
