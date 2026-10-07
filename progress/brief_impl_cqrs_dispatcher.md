# Brief — implementer, feature 43 `cqrs_dispatcher` (phase 8, `sdd: false`, full group)

**Task:** build the hand-rolled in-process dispatcher in `packages/cqrs/src/otc_cqrs/` (today it holds only `__init__.py` with a docstring) with its tests, working from feature 43's acceptance list in `feature_list.json` and CLAUDE.md's *Architecture conventions* ("The hand-rolled dispatcher is binding in all six services: `CommandHandler` / `QueryHandler` / `EventHandler` protocols, a registry keyed by message type, explicit registration in the composition root (no import-time decorators). Startup validation fails on a missing or duplicate handler."). Feature 43 is `in_progress` (set by the leader).

## Scope split (decided by the leader, with evidence)

#8 built its dispatcher alone (`../order-to-cash-dotnet` commit `ece0f2e`, `src/Cqrs/`) and registered it in each host with that host's first handlers (commits `4c6ed34` orders acceptance, `5a84e81` fulfillment, `17ce0d1` billing). #9 does the same: **this feature builds `otc_cqrs` and proves it against test handlers**; no service `composition.py` exists yet (`find services -name composition.py` returns only the seed's), so acceptance item 2's per-service half has been carried by the leader as an acceptance item on features 15, 17, 19, 23, 24 and 25. Do not create service composition roots here.

## Inputs

- #8's effort entry and its four defects, which are this feature's acceptance criteria: `../order-to-cash-dotnet/progress/history.md` lines 676–729 (D1 scope capture, D7 a guard reading the wrong source, D8 a fix that dropped a compile-time check, D9 a stale rule left in an agent file; advisory D10 a hardcoded file list; and "Notes for #9").
- #8's code: `../order-to-cash-dotnet/src/Cqrs/` and its tests `../order-to-cash-dotnet/tests/Cqrs.UnitTests/`. #7 used `@nestjs/cqrs` (no hand-written counterpart; find its usage under `../order-to-cash-nestjs/apps/*/src` for the ledger's "#7 relied on X" half).
- Existing guards already covering this package: `tests/architecture/test_dependency_freedom.py` (`dependencies = []` for `cqrs`), and import-linter contracts in `pyproject.toml` forbidding `otc_cqrs` in every service domain and in `otc_shared_kernel` (`tests/architecture/test_import_contract_coverage.py`). The `mypy --strict` subprocess pattern is in `packages/shared_kernel/tests/test_mypy_rejects_float.py`.

## Questions you must answer in the code and the report (research; nothing here is pre-decided)

1. **Zero handlers is only decidable against a known universe of message types.** How does `validate()` know which commands/queries must have a handler? (#8's answer was marker interfaces; say whether a Python equivalent holds and why.) Events with zero handlers: is that an error? Check #8 and #7 and follow them unless Python forces otherwise.
2. **Scope/lifetime (#8 D1).** An `AsyncSession` belongs to one inbound message (CLAUDE.md). How does a handler get per-dispatch resources without the dispatcher capturing one? Prove it from outside: two dispatches in two independent scopes yield two distinct scoped dependencies.
3. **Typing (#8 D8, CLAUDE.md "typing gaps").** Does the result type survive `dispatch` under `mypy --strict` with no `Any` leaking? Prove it with a `mypy --strict` subprocess test that a wrong use is rejected, with a control that passes.
4. **Async semantics.** Handler exceptions propagate unchanged; `CancelledError` is never swallowed; no task is created that is not awaited.
5. **"No import-time decorators" (#8 D7: match the guard's source to the rule's wording).** What guard proves registration is explicit, and does it read the thing the rule is about? Glob, never a hardcoded file list (#8 D10).

## Process

- Every guard armed (CLAUDE.md protocol: cp backup, mutation, the ONE named test, verbatim failure naming the claim, restore, `cmp`, clear caches, re-run green). Never `git checkout`/`restore`/`stash`. Run the defeat list against your guards and state which rows apply. Arm against the real target, not the reporting path (#8 note).
- The ported-idiom ledger goes in `progress/impl_cqrs_dispatcher.md` (`sdd: false`): one row per idiom, "#7 relied on X; #8 supplied it with Y; in #9 it is supplied by Z", the first two halves cited with file and line, a named armed guard where #9 hand-builds the property.
- If you change a convention, sweep every rule-bearing file (CLAUDE.md, AGENTS.md, `.claude/agents/*.md`) for the old wording and report each hit (#8 D9). You may not edit those files; report instead.
- Files you may touch: `packages/cqrs/**`, `tests/architecture/**` (new guards only, or a classified addition to an existing population), `progress/impl_cqrs_dispatcher.md`, and feature 43's status line. Nothing in `services/`, `specs/`, root `pyproject.toml`, or other packages; if one is needed, stop and report.
- Before finishing: `./quality.sh` once (exit code, duration, pass count, and whether the `otcpy` stack was up — do not start or stop it), and the per-file counts of the new tests summing to the headline.

## Output

`progress/impl_cqrs_dispatcher.md` (what was built, files, ledger, the answers to questions 1–5 with evidence, arming table, defeat-list rows, figures with commands). Set feature 43 to `in_review` (that line only). No git writes. Return only "result in `progress/impl_cqrs_dispatcher.md`" plus at most 5 lines.
