# Brief — implementer, feature 43 `cqrs_dispatcher`, review round 1 rework

**Task:** close F1–F4 of `progress/review_cqrs_dispatcher.md` (§Defects and §"What must change before re-review", items 1–5). F5 (`progress/current.md`) is done by the leader: `./init.sh` now ends "environment and state are coherent". Feature 43 is `in_progress`. This is the last round the leader may run without asking the maintainer, so close each finding completely and state plainly anything left open.

## F1 — handler result type tied to `Command[R]` / `Query[R]` (#8 D8)

As review F1 requires: a REJECTED `mypy --strict` shape "a handler returning the wrong result type" for a command **and** for a query in `test_cqrs_mypy_strict.py`, the `Command[None]` control still accepted, armed by reverting to the free `R`; ledger row rewritten. The reviewer proved one mechanism with a real mypy run (phantom `_result_witness` classmethod + a private protocol on the first argument of `register_*`); any mechanism that makes the probe fail under `mypy --strict` is acceptable. If the `cast(...)` calls in `dispatcher.py` remain, say why each is now sound.

## F2 — a zero-handler universe that closes itself (#8 D10 shape)

As review F2 requires: `build` must not depend on a hand-listed module set that can silently miss a message type — submodules walked, nested classes found, classes with unbound type parameters skipped. One test per escape route (nested class, new submodule, aliased import from an unscanned module, generic base), each armed.

## F3 — change of kind for the registration guard (leader decision)

The Phase 7 gate rule (`progress/current.md`, Notes, item (3): "When a syntax guard loses twice, propose a change of kind (allow-list from a census, or a behaviour test) and a stopping rule"; CLAUDE.md's defeat list row 11 says the same: "when a syntax guard keeps losing, test the behaviour, or inspect what actually runs"). Round 1's guard recognised specific decorator and call shapes and lost to a service-local decorator drained by a loop and to alias/`partial`/`getattr` forms. Replace the recognition with an **allow-list from a census**:

1. **Decorator allow-list.** Every decorator in `services/*/src/**/*.py` (globbed; not a file list) must be in a literal allow-list. The leader's census (AST over that glob, this session) found exactly seven, written as `ast.unparse` of the decorator (call stripped to its callee): `app.get`, `asynccontextmanager`, `classmethod`, `dataclass`, `model_validator`, `property`, `staticmethod`. Reproduce the census in your report with the command. Any other decorator fails, naming file and line, until a human adds it with a reason. This catches a service-local `@handles(X)` however it is drained. Add a population test that every allow-list entry is still used (the census test pattern of `tests/architecture/test_money_guard.py`), so the list cannot rot.
2. **Registration only in the exact composition root.** The exemption is by exact path `services/<svc>/src/otc_<svc>/composition.py`; there, `register_*` appears only as statement-level calls whose first argument is a class reference (no loop, comprehension or indirection). Outside it, any reference to an attribute or string named `register_command`/`register_query`/`register_event` fails.
3. **Arm against the real target:** a real temp file in `services/*/src` (decorator file plus a composition loop), and the census population test (remove an entry still in use; add an unused one). The review names sentinels "B1, C1–C4" without defining them; they are the shapes of its answer to question 4 (`progress/review_cqrs_dispatcher.md`, §Answers, item 4). Write one sentinel for each:
   - **B1** a service-local decorator: `def handles(t): ... HANDLERS.append((t, cls))`, applied as `@handles(PlaceOrder)` in a handler module.
   - **C1** that list drained by a `for` loop calling `registry.register_command(...)` inside `composition.py`.
   - **C2** a bound-method alias: `reg = r.register_command; reg(A, f)`.
   - **C3** `functools.partial(r.register_command, A)(f)`.
   - **C4** `getattr(r, "register_command")(A, f)`.
   - Plus the basename sibling: a file named `composition.py` at a non-root path, e.g. `services/orders/src/otc_orders/application/handlers/composition.py`, must not be exempt.

**Stopping rule:** this round makes one change of kind. Any defeat-list row the new guard still loses is stated in the report as open, with the reason. Do not chase it with more patterns; the leader dispositions it.

## F4

Reflow the broken docstrings and comments the review lists (≤100 columns; prose, not hard-wrapped mid-phrase).

## Bounds and output

- Files: `packages/cqrs/**`, `tests/architecture/test_cqrs_registration_explicit.py` (and a new architecture test file if you split the census guard), `progress/impl_cqrs_dispatcher.md`, feature 43's status line. Nothing in `services/` beyond temp files you create and remove for arming (confirm removal with `ls`), `specs/`, root `pyproject.toml` or rule files.
- Arming protocol as before (cp backup, mutation, ONE named test, verbatim failure naming the claim, restore, `cmp`, clear caches, re-run green). Never `git checkout`/`restore`/`stash`.
- Run: the cqrs tests, the architecture tests, `mypy`, `ruff`, `lint-imports`, and `./quality.sh` once (exit, duration, pass count, whether the `otcpy` stack was up; do not start or stop it). Per-file counts must sum to the headline.
- Append a "Review round 1 rework" section to `progress/impl_cqrs_dispatcher.md`; set feature 43 to `in_review`. Return only "result in `progress/impl_cqrs_dispatcher.md`" plus at most 5 lines, including any row left open under the stopping rule.
