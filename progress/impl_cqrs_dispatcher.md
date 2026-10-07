# Implementation report: feature 43 `cqrs_dispatcher` (phase 8, `sdd: false`, full group)

Status set to `in_review` (feature_list.json line 247 only).

## What was built

`packages/cqrs/src/otc_cqrs/` (zero dependencies, `py.typed` added):

- `messages.py`: `Command[R]` and `Query[R]` markers (PEP 695 generics). They are the closed universe the validation checks against. Events carry no marker.
- `handlers.py`: `CommandHandler[C, R]`, `QueryHandler[Q, R]`, `EventHandler[E]` as `typing.Protocol` (`async def handle(self, message, /)`).
- `dispatcher.py`: `HandlerRegistry[S]` (mutable: `register_command|query|event(message_type, factory)`; `build(*message_modules)` validates and returns) and `Dispatcher[S]` (immutable; `send`, `ask`, `publish`, each taking the caller's scope `S`).
- `errors.py`: `DispatcherValidationError` (all problems collected, `.problems` tuple), `HandlerNotFoundError`.
- `__init__.py`: re-exports.

Registration is by explicit call with a handler *factory* `Callable[[S], Handler]`. Per-dispatch resources come from the scope the caller passes on every call; the dispatcher holds no scope, session or handler instance.

Not done on purpose (brief): no service `composition.py`; the per-service half of acceptance item 2 is carried on features 15/17/19/23/24/25.

## Files touched

- new: `packages/cqrs/src/otc_cqrs/{messages,handlers,dispatcher,errors}.py`, `packages/cqrs/src/otc_cqrs/py.typed`, `packages/cqrs/tests/test_cqrs_dispatcher.py`, `packages/cqrs/tests/test_cqrs_mypy_strict.py`, `tests/architecture/test_cqrs_registration_explicit.py`
- edited: `packages/cqrs/src/otc_cqrs/__init__.py`, `feature_list.json` (feature 43 status only)
- no `R<n>` exists (`sdd: false`), so no `test-matrix.md` row was added, as in #8.

## Answers to the five questions

1. **Zero handlers needs a known universe.** `build(*message_modules)` scans the given modules for classes DEFINED there (`member.__module__ == module.__name__`) that subclass `Command` or `Query`. This is #8's marker-interface answer, and it holds in Python for the same reason: an unwritten handler leaves no artifact, so absence is only decidable against declared messages. The universe is the modules the composition root names (Python has no assembly scan; a module list is the equivalent, and it is passed by the composition root, not hardcoded in the package). Duplicates are also detected for registrations outside the scanned modules (never reported as "missing"). Events: zero handlers is NOT an error (#8 `IEventHandler` remarks / history.md lines 676-729 summary, matching #7's EventBus); arm 4 proves it. A type that is both Command and Query is a malformed declaration (#8 D6 analogue).
2. **Scope (#8 D1).** `S` is the caller's scope; factories take it per call. Proved from outside by `test_two_scopes_yield_two_distinct_scoped_dependencies` (ONE dispatcher, two scopes, two distinct session ids, each equal to its own scope's) and `test_a_scope_is_not_retained_by_the_dispatcher_between_calls` (weakref dies after the call). Armed with a real capture mutation (arms 5, 6).
3. **Typing (#8 D8).** The result type survives: `reveal_type` is `int` for `send` and `ask` (test asserts two `int` and no `Any`). `mypy --strict` subprocess rejects 7 wrong uses (result assigned to str via `send` and via `ask`, query sent as a command, command asked as a query, handler for the wrong command, non-message object, wrong scope type), with 3 controls that pass. KNOWN GAP, stated not hidden: `register_command(Place, factory)` checks the handler against the command class (arm: wrong-command handler is rejected) but cannot tie the handler's return type `R` to the `R` in `Command[R]` (a PEP 695 bound cannot reference another type parameter). A handler returning `str` for a `Command[int]` is not rejected at registration. Callers still see `int` from `send`. mypy also reports `func-returns-value` when a `Command[None]` result is used, which is correct.
4. **Async.** Handler exceptions propagate as the same object (`is boom`); a handler raising `CancelledError` propagates it; cancelling the awaiting task ends `cancelled()`; `all_tasks()` is 1 inside a command handler and an event handler, so the dispatcher creates no task. No `except` exists in `otc_cqrs`. `publish` runs handlers sequentially by runtime type then bases (`type(event).__mro__[:-1]`, derived first), so a base-typed variable still reaches derived handlers (#8 D3 equivalent, natural in Python); the first failure stops the rest, as in #8's loop.
5. **No import-time decorators (#8 D7).** The rule is about HOW handlers register, so the guard reads registration mechanisms, not presence of a name: (A) otc_cqrs source has no module-level statement beyond docstring, imports, defs, classes, type aliases and `__all__` (so no import-time registry or side effect), and no otc_cqrs function is applied as a decorator; (B) no file in `packages/*/src/**` or `services/*/src/**` decorates with a name that came from otc_cqrs (all import forms: from, from-as, import, import-as, inside `if False:`); (C) `.register_command|query|event(` is called only from a file named `composition.py`. Populations are globbed (#8 D10), and sentinels prove each detector can fail, including text in a comment and a triple-quoted string that must NOT hit. Behavioural half: `test_importing_a_module_with_handlers_registers_nothing`.

## Ported-idiom ledger

| Idiom | #7 relied on | #8 supplied | #9 supplies | Guard |
|---|---|---|---|---|
| Handler registry keyed by message type | `@nestjs/cqrs` `CqrsModule.forRoot()` (`../order-to-cash-nestjs/apps/billing/src/app.module.ts:88`; `@QueryHandler` import `apps/billing/src/application/queries/invoice.query-handlers.ts:5`) | `Dispatcher` over `IServiceProvider` (`../order-to-cash-dotnet/src/Cqrs/Dispatcher.cs`) | `HandlerRegistry` dict keyed by `type`, explicit `register_*` | `test_dispatch_is_keyed_by_message_type_not_by_registration_order` |
| Per-message scope | NestJS DI request scope (framework) | `AddScoped<IDispatcher, Dispatcher>()` (`DispatcherServiceCollectionExtensions.cs:86`), after D1 | scope is a call argument; handler factories take it; no captured state | arms 5, 6 on `ask` only in round 1; round 2 extends it to send, ask and publish (six arms below) |
| Startup validation of zero/duplicate | none owed: `@nestjs/cqrs` does not validate (history.md, "guarantees `@nestjs/cqrs` does not offer") | `DispatcherRegistrationValidator.cs` + marker interfaces `ICommand`, `IQuery` | `HandlerRegistry.build` + `Command`/`Query` markers + module scan | arms 0-3, 18, 19 |
| Event zero listeners is fine | `EventBus` publish with no subscriber (#7 behaviour recorded in #8's `IEventHandler.cs` remarks) | `IEventHandler<in TEvent>` unconstrained | no marker, `publish` no-op | arm 4 |
| Publish by runtime type | RxJS event bus dispatches by event class | `GetType()` + `MakeGenericType` + `MethodInfo.Invoke` (`Dispatcher.cs` publish, with D8: lost CA2016 check) | `type(event).__mro__`; plain awaited call, nothing reflective, so nothing is lost | arm 14 |
| Cancellation token forwarding | n/a (no tokens in NestJS) | `CancellationToken` parameter on every call (four tests) | none owed: asyncio cancellation travels by `CancelledError`, nothing to forward; swallowing it is the risk | arms 11, 12 |
| Result type through dispatch | `@nestjs/cqrs` generics `ICommand`/`IQuery` types | generic `Task<TResult>` | `Command[R]` -> `send -> R` | arm 7, 8 |
| No MediatR / package guard (D7) | n/a | project-file guard, D10 hardcoded list | `dependencies = []` guard already exists (`tests/architecture/test_dependency_freedom.py`); registration guard globbed | arms 16-17, B/C below |

Python questions asked: integer division (none used), JSON (none), event-loop affinity (the registry/dispatcher own no loop or pool; the scope does), cancellation (above), `Any` leaking (arm 7).

## Arming table (arm script: scratchpad `arm.py`; each row: backup, mutate real file, run the ONE named test, record, restore from backup)

| # | Mutation of the real target | Named test | Verbatim failure |
|---|---|---|---|
| 0 | zero-handler branch disabled | `test_a_command_with_zero_handlers_fails_startup_naming_the_command` | `Failed: DID NOT RAISE DispatcherValidationError` |
| 1 | same, query | `test_a_query_with_zero_handlers_fails_startup` | `DID NOT RAISE DispatcherValidationError` |
| 2 | duplicate threshold 1 -> 99 | `test_a_command_with_two_handlers_fails_startup_naming_both` | `DID NOT RAISE DispatcherValidationError` |
| 3 | duplicate only for commands | `test_a_query_with_two_handlers_fails_startup` | `DID NOT RAISE DispatcherValidationError` |
| 4 | publish raises on zero handlers | `test_publish_with_zero_handlers_is_a_no_op` | `HandlerNotFoundError: no event handler` |
| 5 | `ask` captures first scope (D1) | `test_two_scopes_yield_two_distinct_scoped_dependencies` | `assert UUID('09b1648b...') == UUID('02945bed...')` |
| 6 | `ask` keeps a strong reference to the scope | `test_a_scope_is_not_retained_by_the_dispatcher_between_calls` | `the dispatcher is holding on to a caller's scope` |
| 7 | `send` returns `Any` | `test_the_result_type_survives_dispatch_as_int_not_any` | `Revealed type is "Any"` |
| 8 | `send` takes `object` | `test_mypy_strict_rejects_wrong_dispatcher_use` | ``mypy --strict accepted `await d.send(object(), s)` (a non-message object)`` |
| 9 | `ValueError` swallowed | `test_a_handler_exception_propagates_unchanged` | `DID NOT RAISE ValueError` |
| 10 | `ValueError` replaced by `RuntimeError` | same | `RuntimeError: wrapped` (chained from `ValueError: boom`) |
| 11 | `CancelledError` swallowed in `send` | `test_cancellation_of_the_caller_is_not_swallowed` | `DID NOT RAISE CancelledError` |
| 12 | same | `test_a_handler_raising_cancelled_error_propagates_it` | `DID NOT RAISE CancelledError` |
| 13 | `create_task` per `send` | `test_dispatch_creates_no_task_of_its_own` | `assert [2, 1] == [1, 1]` |
| 14 | publish ignores base types | `test_publish_resolves_by_runtime_type_not_the_declared_type` | `assert ['fact'] == ['fact', OrderPlaced...]` |
| 15 | publish continues after a failure | `test_publish_first_handler_exception_propagates_and_stops_the_rest` | `DID NOT RAISE RuntimeError` |
| 16 | module-level `_REGISTRY` in dispatcher.py | `test_otc_cqrs_has_no_module_level_state_that_could_register_at_import` | `{'packages/cqrs/src/otc_cqrs/dispatcher.py': ['line 30: AnnAssign']}` |
| 17 | `command_handler` decorator defined and applied in otc_cqrs | `test_otc_cqrs_exports_no_function_applied_as_a_decorator` | `assert not ['@command_handler(int) on _Hh']` |
| 18 | validation scans no modules | `test_every_defect_is_reported_at_once` | `assert 1 == 4` |
| 19 | drop the `__module__` filter (re-export counted) | `test_a_message_re_exported_...` | first run: SURVIVED (fixture registered PlaceOrder, satisfying the relation by accident). Fixture changed (PlaceOrder left unhandled); re-armed: `ValueError: too many values to unpack (expected 1, got 2)` |
| B | real temp file `services/orders/src/otc_orders/application/zz_arm.py` with `@c` from `otc_cqrs import Command as c` | `test_no_source_file_decorates_with_a_name_from_otc_cqrs` | `{'services/orders/src/otc_orders/application/zz_arm.py': ['line 4: @c on Handler']}` |
| C | same file calling `r.register_command(...)` | `test_register_calls_appear_only_in_a_composition_root` | `registration belongs in composition.py only: {...zz_arm.py: ['line 2: .register_command(...)']}`; control: same call in `composition.py` passes (10 passed) |

Arm 5 and 6 first failed with `AttributeError ... no __dict__` (a slots error, wrong reason); the mutation was corrected to add the slot, and the table shows the corrected failures. Temp files removed; backups restored from copies; `*.armbak` search returned nothing; `__pycache__` under `packages/cqrs` cleared before the final run. After the arms, the full suite re-ran green.

## Defeat list rows (on the guards of question 5 and the validation)

Applied: 1 (arms 0-4, 9-13), 2 (arm 10, 16), 3 (sibling: arm 3 queries-only, arm 19), 4 (comment text in sentinel `text_that_only_looks_like_a_decorator_is_not_a_hit`), 5 (`if False:` sentinel, both for decorator and top-level state), 6 (triple-quoted string sentinel), 7 (aliased import `from-as`/`import-as` forms), 8 (n/a to this guard family), 9 (arm 19 was exactly this: a satisfied relation by accident), 10 (glob excludes `__pycache__`, population-not-empty test), 11 (every import form; `Command[R]` subscription is a Subscript, not matched as a decorator), 12 (arm B/C drive the real population). Row 12 limit: a decorator applied through `getattr`/indirection is not recognised by (B); (A)+(C) and the behavioural test cover the registry never registering at import.

## Figures

- New tests: `packages/cqrs/tests/test_cqrs_dispatcher.py` 26, `packages/cqrs/tests/test_cqrs_mypy_strict.py` 11, `tests/architecture/test_cqrs_registration_explicit.py` 10 = 47 (`uv run pytest <file> --collect-only -q | grep -c '::'`).
- `./quality.sh`: exit 0, 2m04.8s, 1484 passed (pytest), coverage 98.58% total (`Required test coverage of 60.0% reached`), web 1 test passed. The `otcpy` stack was UP (12 containers via `docker ps --filter name=otcpy`); I neither started nor stopped it.
- ruff format/check clean, `mypy` 248 source files clean.

## Surprises and reports for the leader

- Rule-bearing sweep (D9): `grep -n "import-time\|decorator" CLAUDE.md AGENTS.md .claude/agents/*.md` hit only CLAUDE.md line 78 (the existing rule, unchanged by this feature). Nothing was amended. Suggestion, not done (I may not edit those files): CLAUDE.md could record the convention this feature establishes, that commands and queries subclass `otc_cqrs.Command[R]` / `Query[R]` and the composition root passes its message modules to `HandlerRegistry.build(...)`. Features 15/17/19/23/24/25 will need that.
- Pytest runs with `--import-mode=importlib`, so sibling test helper modules are not importable by name; fixtures live in the single test module, which scans itself via `sys.modules[__name__]`.
- First arm run showed guard 19 surviving; this is the #8 D7 shape (a fixture satisfying the relation). Fixed and re-armed.
- `HandlerRegistry.build` reports qualnames, so locally-defined test classes appear with `<locals>` prefixes; tests assert `endswith`.

## Review round 1 rework (F1-F4)

Everything above is round 1. Where it conflicts with this section (the module-scan description in Q1, the registration-guard description in Q5, ledger rows "Startup validation" and "Result type", arms 7/8/16-19/B/C), this section supersedes it.

### F1: handler result type tied to `R` (#8 D8)

Mechanism (the reviewer's, re-probed here with a real `mypy --strict` run before adopting): `Command[R]` and `Query[R]` carry a phantom `_result_witness(cls, instance: Self, result: R, /) -> R` classmethod; `CommandType[C, R]` / `QueryType[Q, R]` are Protocols requiring it; `register_command[C, R](command_type: CommandType[C, R], factory: Callable[[S], CommandHandler[C, R]])` (same for query). Probe result: matching handler and the `Command[None]` handler accepted; `-> str` handler rejected (`expected "Callable[[Scope], CommandHandler[Place, int]]"`); `register_command(int, ...)` rejected (`expected "CommandType[...]"`).
`cast` calls remaining in `dispatcher.py` and why each is sound: `send`/`ask` cast the factory result to `CommandHandler[Command[R], R]` / `QueryHandler[Query[R], R]`; the factory was admitted by `register_*` only as `CommandHandler[C, R]` for the class `C` that is the dict key, and `C`'s result type is the `R` of the `Command[R]` being dispatched (the witness proves it). `register_*` casts the class protocol back to `type` for the dict key (only a class satisfies the protocol). `publish` casts to `EventHandler[object]` because a handler is registered under a class the event is an instance of.
Tests (`test_cqrs_mypy_strict.py`): rejected "a command handler returning the wrong result type", "a query handler returning the wrong result type", "a command class registered that is not a Command"; accepted controls "a no-result command with a None handler", "a query with a matching handler".
Arms (real file, ONE named test): reverting `register_command`/`register_query` to a free `R` (`type[C]`) -> `mypy --strict accepted \`r.register_command(Place, lambda scope: WrongResultHandler())\` (a command handler returning the wrong result type)` and the query twin (`... accepted \`r.register_query(Count, ...)\``). Pinning the witness protocol to `int` -> control `a no-result command with a None handler` fails: `expected "CommandType[Ping, None]"`. (My first free-R arm reverted to the round-1 `C: Command[object]` bound and failed for another reason, `Value of type variable "C" ... cannot be "Place"`; the test's expected-text check named it; the arm was corrected to a bare free `R`.)
Ledger row "Result type through dispatch" rewritten: #7 relied on `@nestjs/cqrs` generics; #8 supplied both sides (`ICommandHandler.cs:30-31`, `where TCommand : ICommand<TResult>`, plus `Task<TResult>`); #9 supplies the call side by `Command[R]` -> `send -> R` and the handler side by the witness protocol; guards: the three REJECTED shapes above and the reveal_type test, armed.

### F2: a universe that closes itself (#8 D10)

`build(*message_roots)` now takes modules or packages: a package is walked with `pkgutil.walk_packages` and every submodule imported (an import error is a loud boot failure, not a skip); classes are collected recursively through nested classes; a message is counted wherever it is VISIBLE (defined or imported, aliased or not), deduplicated by identity, so a message imported from a module nobody scanned is still demanded a handler (the round-1 `__module__ ==` filter is gone); classes with unbound type parameters (`__parameters__` non-empty, e.g. `class Base[T](Command[T])`) are skipped, their concrete subclasses counted. Ledger row "Startup validation" now reads: #7 none owed; #8 `Assembly.GetTypes()` over every type of the assemblies; #9 package walk + nested + visibility.
One test and one armed mutation per route (all failures verbatim from the arm run):
- nested class: `test_a_nested_message_class_is_found`; arm no nested walk -> `DID NOT RAISE DispatcherValidationError`.
- new submodule (a real package written under `tmp_path`, put on `sys.path`): `test_a_new_submodule_of_a_scanned_package_is_found`; arm no submodule walk -> `DID NOT RAISE DispatcherValidationError`.
- aliased import from an unscanned module: `test_a_message_imported_from_an_unscanned_module_is_still_demanded_a_handler`; arm `__module__` filter restored -> `DID NOT RAISE DispatcherValidationError`.
- generic base: `test_an_abstract_generic_base_is_not_a_message_but_its_concrete_subclass_is`; arm no generic skip -> `ValueError: too many values to unpack (expected 1, got 2)` (the base was demanded a handler too).
- also `test_a_message_visible_under_two_names_is_reported_once` (identity dedupe; not separately armed).
The round-1 re-export test (asserting a re-exported message is NOT counted) was replaced, since that behaviour is exactly the escape F2 names.

### F3: change of kind, allow-list from a census

Replaced rules B and C of round 1 (recognition of shapes) with:
- Rule B: every decorator in `services/*/src/**/*.py` (globbed) must be in `ALLOWED_DECORATORS`. Census command (also in the test file's docstring) run this session: result `{'model_validator': 5, 'property': 31, 'asynccontextmanager': 6, 'app.get': 6, 'dataclass': 31, 'classmethod': 2, 'staticmethod': 2}` = exactly the leader's seven. `test_the_decorator_allow_list_is_exactly_the_census_of_the_real_population` fails on an unused entry or a used-but-unlisted one.
- Rule C: `register_command|query|event` (attribute, name or string literal) is referenced only in the exact path `services/<svc>/src/otc_<svc>/composition.py` (`is_composition_root`), and there only as the callee of a statement-level call with a Name/dotted-Name first argument and no loop, comprehension, generator or lambda above it inside its function. Outside it, any reference fails.
- Kept: rule A (otc_cqrs has no module-level state and no function applied as a decorator) and the behavioural `test_importing_a_module_with_handlers_registers_nothing`. Round 1's rule B (decorator imported from otc_cqrs) is subsumed by the allow-list and removed.
Sentinels (functions on source text): B1 `test_sentinel_b1_...`, C1 (loop and comprehension), C2 alias, C3 `functools.partial`, C4 `getattr` with the string, the non-root `composition.py` sibling (plus `otc_billing` under orders and `composition.py.bak`), a plain-registration clean control, a non-class first argument, and text in comment/triple-quoted string not a hit.
Arms against the real target (real temp files inside the globbed population, each removed after; `ls` confirms none remain and the empty `application/handlers` dir I created was removed):
| Arm | Real file / mutation | Named test | Verbatim failure |
|---|---|---|---|
| B1 | `services/orders/src/otc_orders/application/zz_arm_handlers.py` with `@handles(PlaceOrder)` collecting into `HANDLERS` | `test_every_decorator_under_services_is_in_the_census_allow_list` | `['services/orders/src/otc_orders/application/zz_arm_handlers.py line 7: @handles']` |
| C1 | `services/orders/src/otc_orders/composition.py` draining `HANDLERS` in a `for` | `test_register_references_exist_only_in_the_exact_composition_root_as_direct_calls` | `composition.py line 4: register_* under a loop, comprehension or lambda` |
| C2 | same file, `reg = r.register_command; reg(A, f)` | same | `line 2: register_* used other than as a direct call (alias/partial/str)` |
| C3 | same file, `functools.partial(r.register_command, A)(f)` | same | `line 3: register_* used other than as a direct call (alias/partial/str)` |
| C4 | same file, `getattr(r, "register_command")(A, f)` | same | `line 2: register_* used other than as a direct call (alias/partial/str)` |
| sibling | `.../application/handlers/composition.py` with a plain call | same | `application/handlers/composition.py line 2: a reference to a register_* name` |
| C2 outside | `.../application/zz_alias.py` alias | same | `zz_alias.py line 2: a reference to a register_* name` |
| control | root `composition.py` with two plain `register_*` lambda-factory calls | same | `1 passed` (must pass) |
| census, remove | `"staticmethod"` removed from `ALLOWED_DECORATORS` | `test_every_decorator_under_services_is_in_the_census_allow_list` | `['services/orders/src/otc_orders/domain/order.py line 581: @staticmethod', ...]` |
| census, add | unused `"unused_zz"` added | `test_the_decorator_allow_list_is_exactly_the_census_of_the_real_population` | `unused allow-list entries: ['unused_zz']; used but unlisted: []` |
| exemption loosened | `parts[4].startswith("composition")` | `test_sentinel_a_file_named_composition_py_at_a_non_root_path_is_not_exempt` | `assert not True where True = is_composition_root('services/orders/src/otc_orders/composition.py.bak')` |
Every mutated file was restored from its backup and `filecmp.cmp` was asserted by the arm script.
Defeat-list rows now: 3 (sibling path) covered; 4/5/6 (comment, `if False:`, string) covered by AST; 11 (different form: alias/partial/getattr) covered inside and outside the root; 12 (served through a path the population never drives): open, see below.
**Left open under the stopping rule:** a handler registered by a mechanism that uses neither a decorator nor a `register_*` name (e.g. a service-local dict mutated by a function called at import) is not recognised by B or C. That sentence was FALSE (review round 2, section 3); see 'Review round 2 light pass' for the true residual. Also: a new legitimate decorator fails until a human adds it to the allow-list (by design). The leader dispositions.

### F4: reflow

Rewrote `dispatcher.py`, `messages.py` docstrings/comments, `test_cqrs_mypy_strict.py` and `test_cqrs_dispatcher.py` headers and `test_cqrs_registration_explicit.py` docstring and comments as continuous prose within 100 columns (my round-1 reflow script had cut sentences after a word). `ruff format --check` and `ruff check` clean.

### Figures (this round)

- Tests: `test_cqrs_dispatcher.py` 30, `test_cqrs_mypy_strict.py` 16, `test_cqrs_registration_explicit.py` 17 = 63 (round 1: 47). Headline 1500 = 1484 - 47 + 63.
- `./quality.sh`: exit 0, 2m09.8s, `1500 passed`, coverage 98.59%, web 1 passed. The `otcpy` stack was UP (12 containers); not touched.
- `uv run mypy`: no issues, 248 files; `ruff check .` clean; `uv run lint-imports`: 10 kept, 0 broken.
- Feature 43 set to `in_review` (feature_list.json line 247 only).
- Rule-file sweep: no convention wording changed this round. The suggestion for CLAUDE.md now has a settled mechanism: messages subclass `otc_cqrs.Command[R]`/`Query[R]`, the composition root passes its message package(s) (e.g. `otc_orders.application`) to `HandlerRegistry.build(...)`, and registers by plain statement-level `register_*(MessageClass, factory)` calls; a new decorator needs an allow-list entry.


## Review round 2 light pass (RC1, RC2, F-d; test and text only, no production edit)

### RC1: D1 guard on every dispatch path

`test_two_scopes_yield_two_distinct_scoped_dependencies` and `test_a_scope_is_not_retained_by_the_dispatcher_between_calls` are parametrised over `send`, `ask`, `publish`. One dispatcher with local message classes (so `build(FIXTURES)` is unaffected) whose handlers append their own scope's session id to a list the test reads. Ledger row "Per-message scope" now: #7 NestJS DI request scope; #8 `AddScoped<IDispatcher, Dispatcher>()` (`DispatcherServiceCollectionExtensions.cs:86`) after D1; #9 scope is a call argument on all three paths; guards: the six parametrised cases, armed.
Arms: the reviewer's mutation `factory(globals().setdefault("_CAPTURED", scope))` on that path's `factory(scope)` in the real `dispatcher.py`, ONE test each (backup, mutate, run, restore, `filecmp` asserted by the script, caches cleared, green after):
| Path | Test | Verbatim failure |
|---|---|---|
| send | two_scopes | `AssertionError: assert [UUID('72325f...bd3a7723ae2')] == [UUID('72325f...b4d2cfa24b1')]` |
| send | not_retained | `the dispatcher is holding on to a caller's scope (send)` |
| ask | two_scopes | `AssertionError: assert [UUID('81502b...ff1f578abf5')] == [UUID('81502b...47d19616096')]` |
| ask | not_retained | `the dispatcher is holding on to a caller's scope (ask)` |
| publish | two_scopes | `AssertionError: assert [UUID('31cbdd...8a695ad6253')] == [UUID('31cbdd...8be38db03d2')]` |
| publish | not_retained | `the dispatcher is holding on to a caller's scope (publish)` |

### RC2: the true residual (replaces the false open-row sentence above and the comment in the guard file)

Not closed by rules B and C: F-a/F-b (computed `getattr(r, "register_" + kind)`), F-g (a `register_*` call inside a helper `def` that the root's loop calls), F-i (a decorator applied by call, `handles(X)(cls)`), F-j (import-time self-registration via `__init_subclass__`). F-j plus F-g is a complete import-time pipeline that registers INTO `otc_cqrs`. Carried as a behavioural guard on features 15/17/19/23/24/25 (the leader added the item). F-c (reaching `HandlerRegistry._commands` directly) is closed by ruff SLF001 (leader, pyproject.toml; tests exempt). F-d is closed by the next item. Also still open by design: F-e/F-f (allow-list matches text, not origin: defeat row 3).

### F-d: `Dispatcher(` constructed only inside `HandlerRegistry.build`

`test_dispatcher_is_constructed_only_inside_handler_registry_build`: AST over the globs `services/*/src/**/*.py` and `packages/*/src/**/*.py`; a call whose callee is the name `Dispatcher`, an attribute `.Dispatcher`, or either subscripted; the whole population must equal exactly `[("packages/cqrs/src/otc_cqrs/dispatcher.py", "HandlerRegistry", "build")]`. Sentinel `test_sentinel_every_construction_form_of_dispatcher_is_detected` (bare, `otc_cqrs.Dispatcher`, dotted module path, subscripted, inside a def; a type annotation is not a hit). Defeat rows it loses (stated, not chased): 3/11 an aliased import (`Dispatcher as D`), `type(d)(...)`, and `getattr`/`importlib` access.
Arms (named test `test_dispatcher_is_constructed_only_inside_handler_registry_build`):
- real temp file `services/orders/src/otc_orders/application/zz_dispatch.py` (`D = Dispatcher({}, {}, {})`): `Left contains one more item: ('services/orders/src/otc_orders/application/zz_dispatch.py', None, None)`; file removed, `ls` shows only `__init__.py`.
- second site in a cp-backup of `packages/cqrs/src/otc_cqrs/errors.py` (`_sneak` returning `Dispatcher({}, {}, {})`): `Left contains one more item: ('packages/cqrs/src/otc_cqrs/errors.py', None, '_sneak')`; restored from backup, `cmp` clean, caches cleared, green.

### Figures

Per-file counts: `test_cqrs_dispatcher.py` 34, `test_cqrs_mypy_strict.py` 16, `test_cqrs_registration_explicit.py` 19 = 69 (round 1 rework: 63; +4 parametrised scope cases, +2 F-d). Headline after this pass would be 1500 + 6 = 1506 (leader runs `./quality.sh`). Run here: cqrs + architecture tests `pytest packages/cqrs tests/architecture` pass, `mypy` 248 files clean, `ruff check` and `ruff format --check` clean, `lint-imports` 10 kept, 0 broken. No production file, feature_list.json, specs, pyproject.toml or rule file touched.
