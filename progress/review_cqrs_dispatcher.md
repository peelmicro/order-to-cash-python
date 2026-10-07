# Review: feature 43 `cqrs_dispatcher` (phase 8, `sdd: false`, full group)

**Verdict: REJECTED** (round 1). Three blocking findings, each a recurrence of a named #8 defect class (D8, D10, D7), each with a cheap fix and each probed by a command. Status set back to `in_progress` (feature_list.json line 247 only).

## What I ran (and what I did not)

- The feature's 47 tests: `uv run pytest packages/cqrs/tests/test_cqrs_dispatcher.py packages/cqrs/tests/test_cqrs_mypy_strict.py tests/architecture/test_cqrs_registration_explicit.py -q` -> `47 passed in 13.60s`.
- Per-file collect: 26, 11, 10 (= 47). Whole workspace `uv run pytest --collect-only -q` -> `1484 tests collected`. The 1484 figure is reconciled as a **collection count**; I did **not** re-run `./quality.sh` (its integration tests need the otcpy stack, which I was told not to touch), so the pass count of 1484 rests on the implementer's run. 1484 - 47 = 1437; the 1436 + 1 (F8) split of that was not checked against HEAD.
- `uv run lint-imports` -> `Contracts: 10 kept, 0 broken.`; `uv run mypy` -> `Success: no issues found in 248 source files`; `ruff check` / `ruff format --check` on the change -> clean.
- `./init.sh` -> **exit 1**: `progress/current.md names none of the active feature(s) [cqrs_dispatcher=in_review]: "**Feature:** orders_aggregate (id 13, phase 8)"` (leader file, F6).
- My own mutation probes: in memory (a pytest plugin that re-executes `otc_cqrs/dispatcher.py`'s source with one substitution; the file on disk was never written, sha256 `b7424ec5...ab13eee` unchanged after). Table below.
- Throwaway consumers for Q1, Q2, Q3, Q5 in the session scratchpad. An attempt to arm the registration guard with real temp files under `services/orders/src/otc_orders/` was **denied by the permission classifier**; I exercised the guard's own detector functions on the same sources instead (detection path proven, population path not — the implementer must arm the population path, see F3).

## Answers to the brief's questions

1. **Typing gap = #8 D8, and reachable.** Probe: `Place(Command[int])`, `WrongHandler.handle(...) -> str`, `r.register_command(Place, lambda scope: WrongHandler())`, `x: int = await d.send(Place(1), Scope())`. `mypy --strict` -> `Success: no issues found in 1 source file` (exit 0); runtime -> `str 'not an int'`, then `TypeError: can only concatenate str (not "int") to str` on `x + 1`. #8 had this guarantee at compile time: `../order-to-cash-dotnet/src/Cqrs/ICommandHandler.cs:30-31` `public interface ICommandHandler<in TCommand, TResult> where TCommand : ICommand<TResult>`. A cheap typed fix exists — proven by a real `mypy --strict` run (F1).
2. **D1 from outside: holds.** One dispatcher, two concurrent `asyncio.gather`ed requests each with its own scope/session, for `send`, `ask` and `publish`: `distinct sessions: True each its own: True scopes released: True` (x3). `Dispatcher` has `__slots__ = ('_commands','_events','_queries')`, no `__dict__`; its tables hold only factory functions/tuples; the only non-callable module attribute of `otc_cqrs.dispatcher` is the `_Factory` type alias.
3. **The universe leaks (F2).** Probe module `pkg/commands.py` scanned by `build(m)`: a nested `Outer.Nested(Command[int])` and an aliased import `from pkg.other import Elsewhere as Aliased` (module not passed) both pass `build` with no handler and then fail at the first dispatch: `Outer.Nested -> runtime HandlerNotFoundError (escaped startup validation)`, `Elsewhere -> runtime HandlerNotFoundError`. An abstract generic base `class GenericBase[T](Command[T])` is wrongly demanded a handler: `No command handler is registered for GenericBase`.
4. **D7/D10: the guard is globbed (good) but reads the wrong source for the realistic shape (F3).** Detector run on a service-local decorator (`def handles(t): ... HANDLERS.append((t, cls))`, applied as `@handles(PlaceOrder)`, drained by a loop in `composition.py`): `(B) hits = [] (C) hits = []` on the handler file and the registry file; the loop's `register_command` is allowed because the file is named `composition.py`. Defeat rows I ran that the implementer did not: row 11 (`reg = r.register_command; reg(A, f)` -> `(C) = []`; `partial(r.register_command, A)(f)` -> `(C) = []`), row 3 (sibling identifier: the exemption is by basename, so `services/orders/src/otc_orders/application/handlers/composition.py` is exempt -> `True`), row 12 (import-time registration served through a decorator whose name never came from `otc_cqrs`). `getattr(r, 'register_command')` -> `(C) = []` (the implementer disclosed this one).
5. **Async semantics: hold.** No `except`, `create_task`, `ensure_future`, `TaskGroup` or `gather` in `otc_cqrs` (`grep -n "except\|create_task\|ensure_future\|TaskGroup\|gather" packages/cqrs/src/otc_cqrs/*.py` -> 2 hits, both docstrings: `dispatcher.py:160` "exception", `errors.py:1` "exceptions"). Second of three event handlers raising `KeyError`: the same object propagates (`is boom` True), `['first ran']` — the first handler's effects stand, the third never runs, 1 task. Matches #8's loop; consumers (features 15+) must run `publish` inside the scope's transaction so the first handler's writes roll back — worth one line in the consumer features' design, not a defect here.
6. **D9: no contradicting wording.** `grep -n -i "import-time\|decorator\|registry\|composition root\|CommandHandler\|QueryHandler\|EventHandler\|otc_cqrs\|packages/cqrs\|dispatcher" CLAUDE.md AGENTS.md .claude/agents/*.md CHECKPOINTS.md` -> 11 hits: `implementer.md:67` (no deps in cqrs: consistent), `AGENTS.md:28` (PROCESS.md row, "registry" = artifact registry: n/a), `AGENTS.md:33` (consistent), `CHECKPOINTS.md:25,26,27` (consistent), `reviewer.md:52` (consistent), `CLAUDE.md:9` (SA registry: n/a), `CLAUDE.md:76,78,79,83` (consistent with this design). A rule-file change is warranted **after** F2 settles the universe mechanism (recording "messages subclass `Command[R]`/`Query[R]`; the composition root passes X to `build`" now would record a mechanism F2 changes). Leader's call at the gate; not a defect.
7. **Counts:** 26 + 11 + 10 = 47 reconciled by my own collect and run; 1484 reconciled as a collection count only (see above).

## Mutation probes (mine; two families plus sibling substitution)

| # | Family | Mutation (in memory) | Named test | Result |
|---|---|---|---|---|
| M1 | delete | zero-handler branch -> `if False:` | `test_a_command_with_zero_handlers_fails_startup_naming_the_command` | killed: `DID NOT RAISE DispatcherValidationError` |
| M2 | corrupt field | missing-handler message names `__module__` instead of the type | same | killed: `... registered for packages.cqrs.tests.test_cqrs_dispatcher. ...' != '... for Ping. ...'` |
| M3 | corrupt field | duplicate message drops handler names | `test_a_command_with_two_handlers_fails_startup_naming_both` | killed: `assert '<lambda>' in '2 command handlers are registered for Ping: handlers. ...'` |
| M4 | sibling | `ask` falls back to the command table first | `test_ask_routes_a_query_to_its_handler` | survived — **equivalent mutant**: tables are disjoint by construction (a type in both is rejected at build; `register_command` of a Query is rejected by mypy and, at runtime, leaves the query unhandled in the scanned universe) |
| M4b | sibling | `ask` reads the command table only | same | killed: `HandlerNotFoundError: No query handler registered for CountOrders` |
| M5 | corrupt supplied field | `ask` builds the handler from a fresh scope, not the caller's | `test_two_scopes_yield_two_distinct_scoped_dependencies` | killed: `assert UUID('65c0…') == UUID('541b…')` |
| M6 | delete | publish skips the runtime type's own handlers | `test_publish_runs_every_handler_in_registration_order` | killed: `assert [] == ['first', 'second']` |
| M7 | corrupt field | publish hands handlers a different event instance | `test_publish_resolves_by_runtime_type_not_the_declared_type` | killed: `[... quantity=0)] == [... quantity=7)]` |

The behaviour tests that exist are real. The defects are in what is **not** guarded (F1-F3).

## Acceptance -> test mapping (`sdd: false`, no `R<n>`)

| Acceptance item | Test(s) verified | Status |
|---|---|---|
| 1 protocols + dispatcher keyed by type, in packages/cqrs | `test_send_routes_a_command_to_its_handler_and_returns_the_result`, `test_ask_routes_a_query_to_its_handler`, `test_dispatch_is_keyed_by_message_type_not_by_registration_order`, `test_publish_*` | met, but the typed half of the handler protocol is weaker than #8's (F1) |
| 2 explicit registration, no import-time decorators (this feature's half) | `test_importing_a_module_with_handlers_registers_nothing`, `test_otc_cqrs_has_no_module_level_state_that_could_register_at_import`, `test_otc_cqrs_exports_no_function_applied_as_a_decorator`, `test_no_source_file_decorates_with_a_name_from_otc_cqrs`, `test_register_calls_appear_only_in_a_composition_root` | **not met as claimed**: the services-wide guard misses a service-local decorator (F3). Carried half present on 15, 17, 19, 23, 24, 25 (each acceptance list has the "carried from cqrs_dispatcher (id 43 ...)" item) |
| 3 fail fast on zero / two handlers, a test per case | `test_a_command_with_zero_handlers_fails_startup_naming_the_command`, `test_a_command_with_two_handlers_fails_startup_naming_both`, `test_a_query_with_zero_handlers_fails_startup`, `test_a_query_with_two_handlers_fails_startup` | met for scanned top-level classes; **zero detection leaks** for nested classes and unscanned modules (F2) |
| 4 every guard armed before review | implementer arms 0-19, B, C (re-arm not needed for M1-M7 above) | **not met**: the result-type guard does not execute the handler side (F1); the registration guard was armed only with an `otc_cqrs`-named decorator (F3) |

## Ported-idiom ledger (checked claims, not existence)

| Row | Verdict |
|---|---|
| Registry keyed by type | holds (M4b, M6) |
| Per-message scope (D1) | holds, probed from outside (Q2) and by M5 |
| Startup validation zero/duplicate | **overstated**: "module scan" is not #8's assembly scan — `Assembly.GetTypes()` covers every type in the project, nested included; a hand-passed module list is the D10 whitelist shape (F2) |
| Event zero listeners fine | holds (arm 4) |
| Publish by runtime type | holds (M6, M7) |
| Cancellation | holds (no `except` in the package; tests 11/12) |
| **Result type through dispatch** | **wrong**: cites arms 7, 8 (caller side only). #8 also guaranteed the handler side (`ICommandHandler.cs:31`); #9 drops it. D8 recurrence (F1) |
| No MediatR / package guard | holds (`dependencies = []`, `test_dependency_freedom.py`) |

Citations spot-checked: `../order-to-cash-nestjs/apps/billing/src/app.module.ts:88` = `imports: [CqrsModule.forRoot()],`; `.../invoice.query-handlers.ts:5` = `import { QueryHandler, ... } from '@nestjs/cqrs';`; `../order-to-cash-dotnet/src/Cqrs/DispatcherServiceCollectionExtensions.cs:86` = `services.AddScoped<IDispatcher, Dispatcher>();`. All correct.

## Defects

### F1 (blocking, #8 D8 recurred) — handler result type not tied to the command's `R`
`packages/cqrs/src/otc_cqrs/dispatcher.py:55-63` (`register_command[C: Command[object], R]`, `register_query[Q: Query[object], R]`: `R` is free) and `:145,154` (`cast(...)` hides it). A handler returning the wrong type reaches a caller typed `R` with the suite and `mypy --strict` green (Q1 probe). #8 enforced it at compile time. **Cheap fix exists, proven** with a real `mypy --strict` run on a scratch model: give `Command[R]` (and `Query[R]`) a phantom `@classmethod def _result_witness(cls, instance: Self, result: R, /) -> R` and type the first registration argument as a private protocol `class _CommandType[C, R](Protocol): def _result_witness(self, instance: C, result: R, /) -> R: ...`, with `register_command[C, R](self, command_type: _CommandType[C, R], factory: Callable[[S], CommandHandler[C, R]])`. Result on the four shapes: matching handler accepted; `-> str` handler rejected (`expected "Callable[[Scope], CommandHandler[Place, int]]"`); wrong-command handler rejected; `register_command(int, ...)` rejected; `reveal_type(send(Place))` = `int`. Not mandated — any mechanism that makes the probe fail under `mypy --strict` is acceptable.
**Required:** a REJECTED shape "a handler returning the wrong result type" (command **and** query) in `test_cqrs_mypy_strict.py`, armed by reverting to the free `R`; the `Command[None]` control still accepted; the ledger row rewritten.

### F2 (blocking, #8 D10 shape) — the zero-handler universe is a hand-listed module set
`dispatcher.py:36-44` (`vars(module)` top level only) and `:70` (`build(*message_modules)`). A nested command class and a command in a module the composition root forgot to pass both pass `build` and fail on first dispatch (Q3 probe). Passing a package scans only its `__init__`. This is the property acceptance item 3 exists for, and #8's assembly scan supplied it for every type in the project. **Required:** a universe that closes itself — e.g. `build` takes package(s) and walks every submodule (`pkgutil.walk_packages` + import) and nested classes, or enumerates `Command`/`Query` subclasses transitively filtered to the given package prefix — so that adding a new message module or nesting a class cannot escape. Skip classes that still carry unbound type parameters (`GenericBase[T]`, false positive in Q3). Tests for each escape route (nested, new submodule, aliased import from an unscanned module, generic base), each armed.

### F3 (blocking, #8 D7 shape) — the registration guard misses the realistic import-time decorator
`tests/architecture/test_cqrs_registration_explicit.py:68-88` (rule B only recognises decorators whose root name was imported from `otc_cqrs`) and `:111-118,162-168` (rule C only recognises `<x>.register_*(` call syntax and exempts any file whose basename is `composition.py`). A service-local `@handles(PlaceOrder)` collecting into a module-level list and drained by a loop in `composition.py` passes all three rules (Q4). That is import-time decorator registration, which CLAUDE.md:78 forbids, and features 15/17/19/23/24/25 will rely on this guard for the half carried to them. **Required:** the guard detects that shape — e.g. `register_*` in the composition root only as statement-level calls whose first argument is a class reference (no loop/comprehension, no indirection), any `.register_*` attribute reference (not only a call) outside the composition root, and the exemption by exact path `services/<svc>/src/otc_<svc>/composition.py`; sentinels for B1, C1-C4 above; and an arm **with a real temp file in the population** (decorator file + composition loop), which my session could not perform.

### F4 (minor, fix in the same round) — prose broken mid-sentence in docstrings and comments
`dispatcher.py:3-17, 73-76, 93-96, 160-161`, `messages.py:3-9`, `errors.py` is fine, `test_cqrs_mypy_strict.py:3-8`, `test_cqrs_registration_explicit.py:3-13, 171-172`: lines are cut after a word and continue on the next line ("in-process fast / path from", "a handler / that was / never written"). Looks like a failed rewrap. Reflow to <=100 columns.

### F5 (leader, not implementer) — `init.sh` exit 1
`progress/current.md` still names `orders_aggregate` (id 13) while 43 is the active feature. C2 box 4 fails until the leader updates it.

### Not defects
- Q5 fan-out semantics (first handler's effects stand when the second raises) match #8; the transaction boundary is the consumer's (features 15+).
- No root cause in `specs/shared/`: nothing to route as `SA-n`.

## CHECKPOINTS walked

C1
- [x] harness files exist; [x] progress files exist; [x] agent roster; [x] models declared (not re-verified this round; unchanged files) ; [ ] `./init.sh` exits 0 (F5)

C2
- [x] at most one `in_progress` (0 before my edit, 1 after: feature 43); [x] statuses valid; [x] `done` features have tests (not touched by this feature); [ ] `progress/current.md` describes the active session (F5); [x] no `blocked` feature

C3
- [x] `lint-imports` 10 kept, 0 broken; [x] no cross-service access (no service code touched); [x] shared runtime only in the three packages; [x] no `domain` imports `otc_cqrs` (import-linter contracts at pyproject.toml:187-238); [x] `packages/cqrs` `dependencies = []`; [x] money: n/a (no money code); [x] Kafka/NATS: n/a (in-process); [x] no debug logging / bare TODOs in `otc_cqrs`

C4
- [ ] `./quality.sh` — not re-run by me (stack constraint); implementer reports exit 0, 1484 passed; I reconciled 1484 collected, 47 passed, mypy/ruff/lint-imports green
- [x] pure tests: `otc_cqrs` tests import no framework (pytest only, no container); [x] integration: n/a; [x] coverage: not re-measured (implementer: 98.58%); [x] no Jest/Karma/Jasmine introduced

C5
- [x] no suspicious untracked files from this feature (no `zz_*` / `*.armbak` left: `ls ... | grep -c zz_` -> 0); [ ] history entry: n/a on rejection; [x] feature_list.json reflects state (43 -> `in_progress`); [ ] human told what/how to test: leader's; [x] no commit

C6 — n/a (`sdd: false`)

C7
- [x] inherited #8 findings accounted for in this review: D1 **avoided**; D8 **recurred** (F1); D10 **recurred in shape** (F2); D7 **recurred in shape** (F3); D9 **avoided** (no contradicting rule wording); D3 equivalent avoided (runtime-type publish, M6/M7). Other C7 boxes not applicable to this feature.

## What must change before re-review

1. F1: typed registration ties handler result to `Command[R]`/`Query[R]`; new REJECTED mypy shapes (command and query), armed; ledger row corrected.
2. F2: a self-closing universe (submodules + nested classes), generic bases skipped; one test per escape route, armed.
3. F3: the registration guard catches a service-local decorator drained by a loop, alias/partial/getattr indirection where feasible (state any row left open, with the reason), and the exemption is by exact path; armed with a real temp file in `services/*/src`.
4. F4: reflow the broken docstrings/comments.
5. Re-run the three files, `mypy`, `ruff`, `lint-imports`, and `./quality.sh`; report per-file counts and the new total.
6. (Leader) F5: update `progress/current.md`.

---

# Round 2 (re-review after the F1-F4 rework)

**Verdict: REJECTED** (round 2). F1, F2, F4 and the round-1 F3 shapes are closed and I verified each. One new blocking gap, a **test** gap, not a code defect: the #8 D1 guard (per-call scope) runs only on `ask`. A D1 capture on `send` (the write path) or on `publish` passes all 63 tests. A second, text-only item: the open-row claim in the guard file is false. Both fixes are small and test/comment-only. This is the second rejection, so per CLAUDE.md the leader takes it to the maintainer. My recommendation: one light implementer pass for RC1 and RC2 below, then the leader verifies the two arms and closes, with no third full review.

Feature 43 is set to `in_progress` (feature_list.json line 247 only).

## What I ran

- The feature's tests: `63 passed in 13.96s`. Per-file collect: `test_cqrs_dispatcher.py 30`, `test_cqrs_mypy_strict.py 16`, `test_cqrs_registration_explicit.py 17` = 63. Whole workspace: `1500 tests collected` (= 1484 - 47 + 63). I did **not** re-run `./quality.sh`. The otcpy stack is off-limits to me, so the 1500 *passed* count rests on the implementer's run. 1500 is reconciled as a collection count only.
- `uv run mypy` -> `Success: no issues found in 248 source files`. `lint-imports` -> `10 kept, 0 broken`. `ruff check` -> `All checks passed!`. `ruff format --check` -> `310 files already formatted`. `./init.sh` -> exit 0 (F5 closed by the leader).
- Mutation probes ran in memory: the same pytest plugin re-executes `dispatcher.py`'s source with one substitution. The file on disk is unchanged (`sha256sum -c` -> `OK` after every batch).
- I did not retry temp files under `services/`: the permission classifier denied that outcome in round 1, and the denial covers retries. Every guard probe below therefore runs the guard module's own functions. The population-path arms use the **real** globbed population with the allow-list or the population list changed in memory.

## (1) My round-1 probes, re-run: each now fails as it must

- **Q1 command:** registering a `-> str` handler for `Place(Command[int])` gets `mypy --strict` exit 1: `Argument 2 to "register_command" of "HandlerRegistry" has incompatible type "Callable[[Scope], WrongHandler]"; expected "Callable[[Scope], CommandHandler[Place, int]]"`.
- **Q1 query:** registering a `-> str` handler for `Count(Query[int])` gets exit 1: `... "register_query" ... expected "Callable[[Scope], QueryHandler[Count, int]]"`.
- **Q3 escape routes:** I built a package with `Outer.Middle.Nested` (two levels deep), a sub-package module `app/sub/deep.py` that `app/__init__` never imports, `from other_unscanned import Elsewhere as Aliased`, and `class GenericBase[T](Command[T])` plus `Concrete(GenericBase[int])`. `build(app)` with only `Handled` registered gives `build FAILED`, naming exactly `Concrete`, `Elsewhere`, `Outer.Middle.Nested` and `DeepQuery`. `GenericBase` is no longer demanded a handler.
- **Q4 shapes, run through `classify` on the reworked guard:** B1 (local `@handles`) -> `line 5: @handles`. C1 (loop in the root) -> `register_* under a loop, comprehension or lambda`. C2 (alias), C3 (`partial`) and C4 (`getattr` with the literal) outside the root -> `a reference to a register_* name`. Basename sibling `application/handlers/composition.py` -> `a reference to a register_* name`. **All detected.**
- My in-memory mutants against the new code:
  - N1: submodule walk deleted. `test_a_new_submodule_of_a_scanned_package_is_found` -> `DID NOT RAISE DispatcherValidationError`.
  - N2: nested recursion deleted. `test_a_nested_message_class_is_found` -> `DID NOT RAISE`.
  - N4: the round-1 `__module__` filter restored. `test_a_message_imported_from_an_unscanned_module_is_still_demanded_a_handler` -> `DID NOT RAISE`.
  - All killed.

## (2) Census guard arms (detector functions plus the real population, changed in memory, not a temp file)

- Census reproduced independently over 105 files: `{'app.get': 6, 'asynccontextmanager': 6, 'classmethod': 2, 'dataclass': 31, 'model_validator': 5, 'property': 31, 'staticmethod': 2}`. That is the leader's seven, with the implementer's counts.
- Baseline: both population tests PASSED.
- Arm, used entry removed (`dataclass`):
  - `test_every_decorator_under_services_is_in_the_census_allow_list` FAILED: `['services/orders/src/otc_orders/domain/events.py line 17: @dataclass', ...`
  - `test_the_decorator_allow_list_is_exactly_the_census_of_the_real_population` FAILED: `unused allow-list entries: []; used but unlisted: ['dataclass']`.
- Arm, unused entry added (`functools.cache`): the exactly-the-census test FAILED with `unused allow-list entries: ['functools.cache']; used but unlisted: []`.
- Arm, population gains a scratch `@handles` file appended to the real glob result: the allow-list test FAILED with `['services/orders/src/otc_orders/application/zz_handlers.py line 4: @handles']`.
- The implementer's real-temp-file arms (B1, C1-C4, sibling, control) are recorded in `impl_cqrs_dispatcher.md`. I did not re-run them on disk, for the reason above.

## (3) The open row under the stopping rule: the claim is broken

The claim is that a mechanism using neither a decorator nor a `register_*` name "cannot reach HandlerRegistry without a register_* reference, which the guard confines to the composition root". It is false in three ways. Each line below is `classify(...)` output on the reworked guard:

| # | Shape | Path | Guard |
|---|---|---|---|
| F-a | `getattr(r, 'register_' + kind)(A, f)` | `application/x.py` | MISSED: reaches `register_command` with no `register_*` literal, outside the root |
| F-b | `getattr(r, f'register_{kind}')(A, f)` | root | MISSED |
| F-c | `REGISTRY._commands.setdefault(PlaceOrder, []).append(...)` at import | `application/x.py` | MISSED: reaches the registry's table directly. ruff's `SLF` family is not selected (`pyproject.toml:66`) |
| F-g | `def one(r, t, f): r.register_command(t, f)` with `for t, f in H: one(r, t, f)` in the root | root | MISSED: the loop check stops at the enclosing `def`, and the first-argument check accepts any `Name`, including a parameter |
| F-j | `class Base: def __init_subclass__(cls, msg, **kw): HANDLERS[msg] = cls` with `class PlaceOrderHandler(Base, msg=PlaceOrder)` | `application/x.py` | MISSED: import-time self-registration, no decorator, no register name |
| F-i | `handles(PlaceOrder)(PlaceOrderHandler)` (decorator applied by call, no `@`) | `application/x.py` | MISSED |
| F-e | `from ...reg import handles as dataclass`, then `@dataclass(PlaceOrder)` | `application/x.py` | MISSED: the allow-list matches text, not origin (defeat row 3) |
| F-f | a local `app = Registrar()`, then `@app.get(PlaceOrder)` | `application/x.py` | MISSED (row 3) |
| F-d | `Dispatcher(TABLE, {}, {})` built directly | `application/x.py` | MISSED: skips `build`, so skips startup validation entirely. Parity note: #8's `Dispatcher` is also `public sealed` (`../order-to-cash-dotnet/src/Cqrs/Dispatcher.cs:33`), so this is not a dropped #8 property |

F-j plus F-g together is a complete import-time registration pipeline: handlers self-register at import, and the root drains them through a helper. It ends in `HandlerRegistry.register_command` and passes the guard. So the residual is **not** "a parallel private registry"; it registers into `otc_cqrs`.

Census of the fresh idioms over the same 105 files: `__init_subclass__` 0, `metaclass=` 0, `Dispatcher` name 0, non-literal `getattr`/`setattr` 3 (existing code, unrelated). None of these shapes is present today.

**Disposition (not a reason to reject):** the stopping rule was the leader's, and the realistic shapes that round 1 found are closed. These rows are ACCEPTED, NOT FIXED in feature 43. The right guard for them is the change of kind CLAUDE.md row 11 names, **testing the behaviour**, and that needs composition roots, which do not exist yet (features 15/17/19/23/24/25 build them). So it is legitimately carried. **Leader action (I may not edit acceptance text):** extend the carried item on 15, 17, 19, 23, 24 and 25 with:

> "behavioural registration guard: importing every module of the service (walked) creates no `HandlerRegistry`/`Dispatcher` and calls no `register_*`; wiring the composition root records each `register_*` call's caller frame, and each registration comes from a distinct statement in `composition.py`; the built dispatcher's tables equal the recorded registrations (catches F-a/F-c/F-g/F-i/F-j); `Dispatcher(` is constructed only by `HandlerRegistry.build` (F-d); armed with F-g+F-j as one fixture."

Re-open trigger: any shape in the table appears under `services/*/src` before that guard lands, or feature 15 starts without the amended item.

## (4) Fresh unrequested probe: the D1 guard covers one path of three (BLOCKING)

The ledger row "Per-message scope" names arms 5 and 6 as its guard. Both tests, `test_two_scopes_yield_two_distinct_scoped_dependencies` and `test_a_scope_is_not_retained_by_the_dispatcher_between_calls` (`packages/cqrs/tests/test_cqrs_dispatcher.py:138-156`), dispatch **only through `ask`**. I applied #8's D1 exactly (capture the first scope and reuse it) to each path and ran all 63 tests of the feature:

| Path | Mutation | Result |
|---|---|---|
| `send` (`dispatcher.py:167`) | `factory(scope)` -> `factory(globals().setdefault("_CAPTURED", scope))` | **63 passed**: survives |
| `publish` (`dispatcher.py:189`) | same, `_CAPTURED_E` | **63 passed**: survives |
| `ask` (`dispatcher.py:177`) | same, `_CAPTURED_Q` | `FAILED ...::test_two_scopes_yield_two_distinct_scoped_dependencies`: killed |

`factory(None)` on `send` and on `publish` also survives (`30 passed`, dispatcher file). The **code** is correct today: my round-1 throwaway consumer proved two scopes give two sessions on all three paths. What fails is the guard. The command path, where handlers write through the session, is exactly where a captive session does damage (#8 D1: "one captive DbContext shared by every request"). This is the ledger check CLAUDE.md requires ("does the named guard execute the code the row is about?"), and it fails for two of the three paths. I missed it in round 1 too, because my M5 targeted `ask` only.

## Ledger, re-checked

| Row | Verdict |
|---|---|
| Result type through dispatch | holds now: handler side tied by the witness protocol (Q1 command and query), call side by `reveal_type` |
| Startup validation zero/duplicate | holds now: package walk, nested classes, visibility, generic skip (Q3; N1, N2, N4 killed). Residual: it is complete only for the roots the composition root passes, the same as #8's `AddDispatcher(assemblies)` |
| Per-message scope | **guard incomplete**: executes `ask` only (section 4) |
| others | unchanged from round 1, hold |

## Required changes (exact)

- **RC1 (blocking, test-only).**
  - Parametrise `test_two_scopes_yield_two_distinct_scoped_dependencies` and `test_a_scope_is_not_retained_by_the_dispatcher_between_calls` over the three paths `send`, `ask` and `publish`. For `send` and `publish`, the handler reports its own scope's session id, for example by appending to a list the test reads.
  - Arm each case with the capture mutation in the table above, applied to that path's `factory(scope)`. Each of the 3 × 2 cases must fail on its own path's mutation and pass on the restored file.
  - Record the six failures verbatim in `impl_cqrs_dispatcher.md` and update the ledger row "Per-message scope" to name the parametrised guard.
- **RC2 (blocking, text-only).** Replace the open-row comment at `tests/architecture/test_cqrs_registration_explicit.py:351-356`, and the matching sentence in `impl_cqrs_dispatcher.md` ("It cannot reach the `HandlerRegistry` without a `register_*` reference ..."), with the true residual: rows F-a to F-j of section 3, and that the behavioural guard is carried to features 15/17/19/23/24/25. A false premise in a guard file is defeat-list row 9, and features 15+ will read it.
- **Leader:** amend the carried items as quoted in section 3, and take this second rejection to the maintainer.

Nothing in this round traces back to `specs/shared/`, so there is no SA to propose.

## CHECKPOINTS (deltas from round 1)

- C1 `./init.sh` exits 0: [x] (was [ ]).
- C2 `progress/current.md` describes the active session: [x] (init.sh coherent).
- C3: [x] unchanged (lint-imports 10/0; `packages/cqrs` `dependencies = []`; no `domain` imports `otc_cqrs`).
- C4 `./quality.sh`: [ ] not re-run by me (stack constraint); implementer reports exit 0, 1500 passed, 98.59%. I reconciled 1500 collected and 63 passed.
- C5: [x] no stray files (no scratch file was written into the repository). History entry: n/a on rejection.
- C7 inherited #8 findings, as of round 2:
  - D1 code avoided, **guard partial** (RC1).
  - D7 decorator shape closed; residual rows accepted and carried.
  - D8 avoided after round 1 (recurred in round 1, fixed).
  - D9 avoided.
  - D10 avoided after round 1 (recurred in round 1 as the module whitelist, fixed).
