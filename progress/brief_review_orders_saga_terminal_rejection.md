# Brief — reviewer, feature 42 `orders_saga_terminal_rejection_classification` (phase 8, `sdd: false`, full group, round 1)

**Task:** adversarially review feature 42 against its four acceptance items (`feature_list.json` id 42), the brief `progress/brief_impl_orders_saga_terminal_rejection.md`, the seam in `specs/order_saga_orchestrator/requirements.md` §5 and `design.md` §9.2/§9.5–§9.7 (now carrying feature 42's amendment), and the record `progress/impl_orders_saga_terminal_rejection.md`. Feature 42 is `in_review`. Write `progress/review_orders_saga_terminal_rejection.md`. On APPROVED: set 42 to `done` (that line only) and append the effort entry to `progress/history.md` against #8 (`../order-to-cash-dotnet/progress/history.md` lines 872–913: 1 pass, approved first time, ≈1.1 h, ~2× #7) and #7 (quoted there), naming #8's three probes and five notes as avoided or recurred; classification: full group. On REJECTED: set 42 to `in_progress` and write "What must change" (each item an instruction with the test and arm). One more round is allowed without asking the maintainer.

## Reported by the implementer (locate, do not trust)

- `./quality.sh` exit 0, 442 s, 2387 passed (2356 + 31), stack down. Arm driver `.arm/arm42.py`, backups `.arm/bak/f42/`, output `.arm/f42.out`.
- Arm E2 survived the end-to-end test (the "sweeper never re-issues it" claim is held by the cleared lease, not by status); the status claim rests on planted-row ledger tests (arms L4, L8).
- The leader filed the deferred `order.saga_failed.v1` / dead-letter surfacing of a rejected row on feature 27 (diff read). Not this feature's to build.

## Questions to rule on

1. **E2 and the planted rows.** Is "a rejected row is never re-issued" guarded by a test that fails when the *status* exclusion alone is removed through a reachable path, or only through planted state? Feature 16's round-2 review accepted a planted-state guard for `sent` with a stated reason; apply the same test of reasonableness here and say whether it holds for `rejected`.
2. **#8's probes, re-run at your grain:** remove one code from the terminal set (exactly its tests fail); swap reject → park in the dispatcher; widen each claim predicate to admit `rejected` with a control row present. #8's notes 1 and 2 (a mutation dying at an earlier assertion; a negative assertion over one row) are the shapes to hunt.
3. **The unknown code** (outside the twelve) stays on the transport path and is retried — the runtime behaviour #7 and #8 shipped. Proven by a test?
4. **No regression of features 15 and 16:** the no-responders / timeout split, SO4 / SO15 retry and park, the SO9 offset arms where the touched files intersect; feature 15's P-arms only if `composition.py` changed.
5. The implementer reports #7's `markRejected` and #8's `park` / `RejectAsync` carry status-predicate holes. Verify with file and line; that is evidence for the trilogy record, not work for #7 or #8 (CLAUDE.md: they are touched only for a spec amendment or at the maintainer's request).

## Bounds

Read-only except `progress/review_orders_saga_terminal_rejection.md`, feature 42's status line and (on approval) `progress/history.md`. Backups in `.arm/` with a recorded sha256, never `/tmp`; any timeout you use kills the whole process group. Developer stack stays stopped; never two test runs at once. No git command that writes the index or working tree. Return only "result in `progress/review_orders_saga_terminal_rejection.md`" plus the verdict and at most 5 lines.
