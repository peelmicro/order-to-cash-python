# Brief — reviewer, feature 15 `orders_acceptance` (phase 8, `sdd: false`, full group, round 1)

**Task:** adversarially review feature 15 against its eight acceptance items (`feature_list.json` id 15), the implementer brief `progress/brief_impl_orders_acceptance.md`, and the implementer's record `progress/impl_orders_acceptance.md`. Feature 15 is `in_review`. Write `progress/review_orders_acceptance.md`. On APPROVED: set 15 to `done` (that line only) and append the effort entry to `progress/history.md` (against #8's baseline at `../order-to-cash-dotnet/progress/history.md` lines 773–820 and #7's quoted there; name each inherited #8 finding — D1–D6, A3, A5, A10, A11, ids 46, 47, 50, 56 — and #7's N2/N3 as avoided or recurred; classification: full group). On REJECTED: set 15 to `in_progress` and list, in a section headed "What must change", each item as an instruction with the test or arm that will prove it. This is round 1; CLAUDE.md allows one more without asking the maintainer.

## What the leader established this session (with commands) — not claims for you to trust, only to locate

- The implementer reports `./quality.sh` exit 0, 193 s, 1867 passed (1652 + 215), developer stack down; nats-py 2.16.0 added. Re-run what you need; the developer stack is stopped and must stay stopped (integration suites must pass with it down). Never run two test runs at once against the same containers.
- #8 placed its host outside `Presentation`: `../order-to-cash-dotnet/src/Orders/OrdersHost.cs` and `Program.cs` at the project root (commit `4c6ed34`).

## Questions to rule on (each one a finding with a disposition, or a ruling with evidence)

1. **Deviation 1 (impl §11.1):** the lifespan lives in `otc_orders/main.py`, not `presentation/app.py` as CLAUDE.md's architecture conventions say, because the import-linter fact-producer-confinement contract (R14) forbids presentation reaching aiokafka through the composition root. Is the deviation sound, is it the shape #8 had, and does anything (import-linter contracts, the cqrs registration guard's composition-root rule, CLAUDE.md wording) now lie? A CLAUDE.md wording change is the leader's to make; name it.
2. **The unported guard (impl §6, §11.9):** #8's `RpcSubjectsTests` (subject constants equal `asyncapi.yaml` channel addresses) was not ported. Findings are fixed in the phase that detects them (CLAUDE.md); rule accordingly.
3. **Impl §11.7:** the boot-time probe builds `PlaceOrderCommandHandler` by hand, so a handler added by features 16 and 41 must be added to it. Is that a guard with a hole (a later handler missing from the probe stays green)?
4. **Impl §11.4:** the one-relay-per-process enforcement detects `WEB_CONCURRENCY>1`, a multiprocessing worker and a second runtime in one process, not a gunicorn fork model or two replicas. Does that meet acceptance item 8 ("enforced at startup or by the composition root, proven by a test, armed")?
5. **#8's defect class for this feature** was "the behaviour is correct and nothing would notice it being reverted" (seven times across three rounds). Mutate the code the implementer fixed last (impl §11.10: `A11a`, `7c`), the call sites (validator, mapper, registration, relay start, responder start, readiness wiring), the no-responders/timeout split, each required-field check, each money field of the reply, and each env read reachable from the composition root. Report each mutation with its verbatim result. Restore by `cp` + `cmp`, never `git checkout`/`restore`/`stash`.
6. Counts: per-file test counts sum to 215; the arming table's rows were actually run (re-run a sample of your choosing, and say which).

## Bounds

Read-only except `progress/review_orders_acceptance.md`, feature 15's status line, and (on approval) `progress/history.md`. Mutations go through a `cp` backup and are restored `cmp`-identical, caches cleared. No git command that writes the index or working tree. Return only "result in `progress/review_orders_acceptance.md`" plus the verdict and at most 5 lines.
