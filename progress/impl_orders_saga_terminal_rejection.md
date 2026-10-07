# Implementation record, feature 42 `orders_saga_terminal_rejection_classification`

Classification: full group (saga, persistence). `sdd: false`. Status set to `in_review` (that line only in `feature_list.json`). No git writes; no migration; no `specs/shared/` change; `specs/shared/test-matrix.md` untouched (no `R<n>` covers this split, as #7 and #8 found).

## What was built

* `application/ports/saga_commands.py`: new `SagaCommandBusinessRejectionError(SagaCommandError)` carrying `code`, deliberately NOT a `SagaCommandTransportError` subclass. `SagaCommandRpcError` now means a transient code only.
* `infrastructure/messaging/nats_saga_commands.py`: `TERMINAL_RPC_ERROR_CODES: frozenset[Code]` (the nine); `_decode` raises the rejection error for a terminal code and `SagaCommandRpcError` otherwise. A code outside the twelve still fails `from_wire_json(RpcError, ...)` with a `ValueError` and becomes a plain `SagaCommandTransportError` (retryable), unchanged.
* `application/ports/saga_command_store.py` and `infrastructure/saga/command_ledger.py`: `reject(row_id, *, total_attempts, last_error)` (status `rejected`, attempts, truncated last_error, `next_attempt_at = NULL`, range-checked, only on a `CLAIMABLE` row). `park`'s predicate changed from `status != 'sent'` to `status IN CLAIMABLE`.
* `infrastructure/saga/command_dispatcher.py`: `except SagaCommandBusinessRejectionError` before `except SagaCommandError`; on the first attempt it calls `ledger.reject(total_attempts=row.attempts + attempt)`, logs ERROR with `code`, returns new `DispatchOutcome.REJECTED`. Never `park`, never `mark_sent`, no pause.
* `infrastructure/saga/sweeper.py`: `SweepResult.rejected` (default 0 so existing positional constructions stay valid).
* Docs: `specs/order_saga_orchestrator/design.md` §9.2, §9.5, §9.6 heading, §9.9 seam row; `requirements.md` §5 and the SO4 note, each marked "Feature 42's amendment".
* `tests/architecture/test_write_path_population.py`: ledger census `update` 4 -> 5, comment classified (the new `reject` writes `attempts`, `ensure_in_range`).

## Files touched

Source: the six under `services/orders/src/otc_orders/` named above (`ports/saga_commands.py`, `ports/saga_command_store.py`, `messaging/nats_saga_commands.py`, `saga/command_dispatcher.py`, `saga/command_ledger.py`, `saga/sweeper.py`).
Tests: `services/orders/tests/unit/saga/{test_nats_saga_commands,test_command_dispatcher,test_sweeper}.py` (edited), `services/orders/tests/integration/saga/{test_saga_command_rejected_ledger,test_saga_command_terminal_rejection}.py` (new), `tests/architecture/test_write_path_population.py` (census).
Docs: the two spec files. Tooling: `.arm/arm42.py` (counting arm driver; no timeout hit in any run, `timeout_hit=False` throughout), `.arm/f42.out` (arm output).

## Answers to the brief's questions

1. **The set.** `asyncapi.yaml` (`RpcError.code`, around line 2847) describes only `TIMEOUT` ("produced by the caller"); no per-code description forces anything, so #7's and #8's set is adopted member for member: terminal = VALIDATION_FAILED, NOT_FOUND, CONFLICT, PRECONDITION_FAILED, ORDER_NOT_CANCELLABLE, STOCK_UNAVAILABLE, INVOICE_NOT_PAYABLE, PAYMENT_MISMATCH, DOMAIN_ERROR; transient = INTERNAL_ERROR, UNAVAILABLE, TIMEOUT (#7 `nats-saga-commands.adapter.ts:79`, #8 `NatsSagaCommandsAdapter.cs:179`). Unknown code: retryable plain transport error, test `test_so15_an_rpc_error_with_a_code_outside_the_twelve_fails_open_to_transport` (now also asserts no `code` attribute). Per-code arming (A1, A3, A4 below): removing one code fails exactly its parametrised case plus the set-partition test that names all twelve; adding one transient code fails its transient case plus the partition test. `CONFLICT` additionally fails the six `every_command_method` cases because that test uses CONFLICT as its stimulus (it names it).
2. **Short-circuit.** `test_feature_42_a_terminal_rejection_is_rejected_on_the_first_attempt_never_retried_parked_or_sent` asserts outcome `REJECTED`, one call, no sleeps, one `ledger.rejected` entry, empty `parked` and `sent`: the kind of resolution, not only a count. Arm D1 (reject -> park) fails it.
3. **Predicates** (all in `command_ledger.py`): `try_claim` `IN CLAIMABLE` excludes rejected; `claim_due` names `pending` and `parked`, excludes rejected; `mark_sent` `IN CLAIMABLE`, excludes rejected; `park` was `!= 'sent'` and WOULD re-park a rejected row, now `IN CLAIMABLE`; `reject` `IN CLAIMABLE` (never moves a sent row, never re-rejects). One integration test per predicate, each with a control row that must change/return (`..._while_it_claims_a_pending_sibling`, `..._returns_a_due_pending_control`, `..._marks_a_claimed_control`, `..._parks_a_claimed_control`); each has its own mutation that leaves the others green (L1-L5, L8: exactly one failing test each).
4. **Feature 15/16 splits.** Stock-availability (feature 15) files untouched. Re-run: `test_nats_saga_commands.py` (no-responders vs timeout, SO15), `test_command_dispatcher.py` (SO4 retry/park, SO6), `test_saga_command_retry.py`, `test_nats_saga_commands_reply_decode.py`, full ledger file: all green (13 integration passed in the targeted run; the full quality run is green). Arm D6 (every error rejected) fails the SO4 test and 6 more, proving those tests execute the new clause.
5. **Deferred surfacing.** Confirmed not carried: no `order.saga_failed.v1` and no dead letter on a terminal rejection; only the ERROR log and the `rejected` row. I built nothing and did not edit `feature_list.json`; the leader files the item (the amendment text in design.md §9.5 says so). My search of feature 27 is the leader's; I did not re-run it.
6. **Doc.** Updated, see above.

## Acceptance items one by one

1. Terminal `RpcError` classified terminal, not retried: `test_feature_42_a_terminal_code_is_a_business_rejection_not_a_transport_error[<code>]` x9 and `test_feature_42_a_terminal_rejection_is_rejected_on_the_first_attempt_...`; e2e `test_feature_42_a_terminal_rpc_error_resolves_the_row_to_rejected_on_the_first_attempt_and_the_sweeper_never_re_issues_it` (one request at the real NATS responder).
2. Transient failures still retried: `test_feature_42_a_transient_code_is_a_retryable_rpc_error_carrying_its_code[<code>]` x3, `test_feature_42_a_transient_rpc_error_is_still_retried_and_parked_not_rejected`, e2e `test_feature_42_a_transient_rpc_error_is_still_retried_in_line_and_parked` (3 requests, parked, attempts 3), plus the unchanged SO4/SO15 tests.
3. Row reaches a resolved end state: `test_reject_resolves_a_claimed_row_to_rejected_clearing_the_lease_...` and the e2e (status `rejected`, attempts 1, `last_error` names the code, `next_attempt_at` NULL).
4. Every status predicate: the six tests in `test_saga_command_rejected_ledger.py` (try_claim, claim_due, mark_sent, park, reject x2), armed (table below). `park`'s `status <> 'sent'` is arm L1.

## Ported-idiom ledger (one line per idiom)

| Idiom | #7 relied on | #8 supplied | #9 supplies |
|---|---|---|---|
| Terminal-code set | exhaustive `switch` with a `never` default, `nats-saga-commands.adapter.ts:79` | `IsTerminalRpcErrorCode` switch, default false, `NatsSagaCommandsAdapter.cs:179` | `TERMINAL_RPC_ERROR_CODES` frozenset over the generated `Code` enum; partition test over the enum (so a thirteenth code added to the spec fails the test rather than falling silently to one side); armed A1-A4 |
| Unknown code | the `never` default throws, retried at run time by the generic catch in `saga-command-dispatcher.ts` (per #8 history note 4) | falls false (transient) | pydantic `ValueError` in `_decode` -> plain `SagaCommandTransportError`: retryable by construction, no extra code; test asserts no `code` |
| Reject-before-retry catch | generic catch, `saga-command-dispatcher.ts:172-193` | catch before the filter, `SagaCommandDispatcher.cs:109-119` | `except SagaCommandBusinessRejectionError` placed before `except SagaCommandError`; the type is NOT a transport-error subclass (a subclass order inversion cannot swallow it); armed D2, D6 |
| `rejected` write | `markRejected`, `drizzle-saga-command-store.ts:159-171`, predicate `notAlreadySent()` | `RejectAsync`, `EfCoreSagaCommandStore.cs:241-256`: NO status predicate at all, attempts computed as `current.Attempts + attemptsMade` after a read | `reject` conditional `IN CLAIMABLE` in one statement; the caller passes the accumulated total like `park`; armed L5 |
| Other ledger predicates | `notAlreadySent()` (`!= sent`) also on park: a rejected row WOULD be re-parked | `park` `!= "sent"` at `EfCoreSagaCommandStore.cs:217` (same hole; unreachable there only because nothing re-dispatches a rejected row) | all write predicates `IN CLAIMABLE`; a test per predicate, armed. Also #8's predicate-free `MarkSentAsync` (`EfCoreSagaCommandStore.cs:177`) |
| Integer arithmetic | JS numbers | C# int | `row.attempts + attempt` is `int + int`; no `/`; range-checked by `ensure_in_range` (the ORM-enabled `update` bypasses the attribute guard) |

Python questions: integer division none; JSON none new; event-loop affinity unchanged; cancellation: the new clause awaits `ledger.reject` and never catches `CancelledError`; typing: `Code` enum members, `frozenset[Code]`, mypy strict clean.

## Ported-guard table (#8's tests for this mechanism, by content)

| #8 assertion | Status |
|---|---|
| per-code theory over the nine + three (probe 1) | ported (parametrised both ways), armed per code |
| dispatcher: terminal rejects on first attempt, `Reject` not `Park` (probe 2) | ported, asserts kind and count |
| sweeper exclusion with a boundary-exact due row (probe 3) | ported with a control row and a planted due `next_attempt_at`; one mutation per claim |
| unknown code stays transient | ported |
| transient `RpcError` still retried | ported (unit + e2e) |
| #8 added no predicate tests for `park`/`mark_sent` | added here (#8 note 1 and A1) |

## #8's probes and notes: avoided or recurred

* Probe 1 (per-code arming): avoided (done at one-code grain). Probe 2 (kind of resolution): avoided. Probe 3 / note 2 (vacuous negative assertion over a one-row table): avoided (control rows; L4 and L8 each fail only that test). Note 1 (a mutation dying at an earlier assertion arms nothing about a later one): avoided for the ledger tests, one claim per test. One residual of the same family, recorded honestly: arm E2 (sweeper's parked branch includes `rejected`) SURVIVES the e2e test, because `reject` clears `next_attempt_at` to NULL and `NULL <= now` is false, so the e2e "sweeper never re-issues it" assertion is independently protected by the cleared lease, not by status. The status claim is guarded by L4/L8 (planted due `next_attempt_at`), not by the e2e. Note 3 (stale binary): n/a, Python re-reads source; `.pyc` and `.mypy_cache` cleared on every arm. Note 4 (runtime not apparent intent): avoided. Note 5 / A1 (stale doc): RECURRED PARTIALLY in round 1 (the design.md §9.6 listing, the "All four statements" count and the `sent` bullet still described `park` as `<> 'sent'` and omitted `reject`); closed in round 2 below.
* Recurred: note 5 partially (round 1; fixed in round 2). One inherited defect avoided that #7 and #8 both carry: the `park`/`reject` predicate hole (above).

## Arming table (driver `.arm/arm42.py`; each row: backup + sha256 in `.arm/bak/f42/<id>/`, whole test file run without `-x`, restored from backup, `cmp` identical and sha256 equal in every run, restored run green; verbatim output in `.arm/f42.out`)

| Id | Mutation | Failing tests (verbatim leaf) |
|---|---|---|
| A1 | drop `Code.precondition_failed` from the set | `test_feature_42_a_terminal_code_is_a_business_rejection_not_a_transport_error[PRECONDITION_FAILED]` (`assert <class ...SagaCommandRpcError'> is SagaCommandBusinessRejectionError`) and `..._partition_the_generated_code_enum` |
| A3 | drop each of the other eight terminal codes in turn | each fails its own `[CODE]` case plus the partition test (CONFLICT also the six `every_command_method` cases) |
| A2, A4 | add UNAVAILABLE / INTERNAL_ERROR / TIMEOUT to the set | the matching `test_feature_42_a_transient_code_is_a_retryable_rpc_error_carrying_its_code[CODE]` plus the partition test |
| D1 | `ledger.reject` -> `ledger.park` | `test_feature_42_a_terminal_rejection_is_rejected_on_the_first_attempt_...`, `..._counts_the_attempts_made_and_stops` |
| D2 | rejection clause never matches | same two |
| D3 | `total_attempts = attempt` | `test_feature_42_a_rejection_after_transient_failures_counts_the_attempts_made_and_stops` only |
| D4 | return `SENT` | the same two as D1 |
| D5 | `continue` instead of returning on rejection | the same two |
| D6 | catch every `SagaCommandError` as a rejection | 7 failures, including `test_so4_retries_a_timed_out_command_...` and `test_feature_42_a_transient_rpc_error_is_still_retried_and_parked_not_rejected` (`AttributeError: 'SagaCommandTimeoutError' object has no attribute 'code'`) |
| S1 | sweeper `rejected=0` | `test_feature_42_a_rejected_dispatch_is_counted_as_rejected_only` |
| L1 | park predicate back to `!= 'sent'` | `test_park_never_re_parks_a_rejected_row_while_it_parks_a_claimed_control`: `AssertionError: park: a rejected row is not re-parked` (only this test) |
| L2 | mark_sent predicate `!= 'parked'` | `test_mark_sent_never_moves_a_rejected_row_...`: `mark_sent: a rejected row stays rejected` (only this) |
| L3 | try_claim includes `rejected` | `test_try_claim_never_claims_a_rejected_row_...`: `try_claim: status, not the NULL next_attempt_at, keeps a rejected row out` (only this) |
| L4 | claim_due parked branch includes `rejected` | `test_claim_due_never_returns_a_rejected_row_...`: `claim_due: exactly the pending control, never the rejected row` (only this) |
| L8 | claim_due pending branch includes `rejected` | same test as L4 (only this) |
| L5 | `reject` has no status predicate | `test_reject_never_moves_a_sent_row_...`: `assert ('rejected', 7, 'late') == ('sent', 0, None)` (only this) |
| L6 | `reject` writes `parked` | 6 failures (the helper asserts `rejected`) |
| L7 | `reject` keeps the lease | `test_reject_resolves_a_claimed_row_...` (`the lease is cleared: a resolved row is never due`) and the park test |
| E1 | classifier forced off, real NATS e2e | `test_feature_42_a_terminal_rpc_error_resolves_...`: `timed out after 20s waiting for: the stock.reserve row is resolved to rejected` |
| E2 | sweeper parked branch includes `rejected`, e2e | SURVIVED (see above; L4 is the guard) |

Defeat list rows applied: 1 delete the behaviour (D2, A3-all, E1), 2 corrupt a supplied field (D3, L6, L7), 3 substitute a sibling identifier (A2/A4 sibling codes; L2 `'parked'` for `'sent'`; the sibling pending row as control), 8 literal-to-literal (the e2e uses `STOCK_UNAVAILABLE`/`INTERNAL_ERROR` while the set literal lives in the adapter, and the partition test compares against a literal tuple in the test, not the adapter's own), 9 closer half satisfied, premise stale (E2 found exactly this and is recorded), 11 form the instrument does not recognise (behaviour tests, no syntax guard added), 12 failure through a path the population does not drive (every one of the six commands is driven by `every_command_method`). Rows 4, 5, 6, 7, 10 do not apply (no syntax/text guard was added; caches cleared on each arm).

## Figures

* Baseline before any edit: `uv run pytest --collect-only -q -p no:cacheprovider | tail -1` -> 2356 tests collected.
* After: same command -> 2387 collected (+31). Per file: `test_nats_saga_commands.py` +18 (19 new, 1 replaced), `test_command_dispatcher.py` +3, `test_sweeper.py` +1, `test_saga_command_rejected_ledger.py` +7, `test_saga_command_terminal_rejection.py` +2; 18+3+1+7+2 = 31.
* `./quality.sh`, developer stack down (`docker ps` showed only `otcpy-n8n`; `ss -ltn` showed none of 9092, 4222, 5432, 27017 listening): exit code 0 (`.arm/f42_quality.exit`), 442 s wall (`.arm/f42_q.end` minus `.start`), `2387 passed in 409.07s`, total coverage 98.70%, final line "quality.sh: all gates passed". Log: `.arm/f42_quality.log`.
* `./init.sh` after the final edit (status set to `in_review`): exit 0.

## Surprises

* #8's `RejectAsync` has no status predicate and #7/#8's `park`/`markRejected` use `!= sent`: the acceptance item 4 hole exists in both predecessors, unreachable only because nothing re-dispatches a rejected row. Closed here.
* Arm E2 surviving the e2e (above): the end-to-end negative is protected by the cleared lease, so a status-only claim needs the planted-row integration tests, which have it. Correction (review D3): only the parked-branch status term rests on planted state; the pending branch and `try_claim` are guarded through reachable state (reviewer arm R3 fails the e2e).

## Round 2 (documentation only)

Closed review items 1-3. No executable statement changed.

* Item 1, `design.md` §9.6: heading note kept; "All five statements" (marked as feature 42's amendment); `park`'s SQL now `status IN ('pending', 'parked')`; a `reject` statement added; the `mark_sent`/`park`/`reject` bullet now says none moves a `sent` or `rejected` row. The only remaining `<> 'sent'` is the historical mention in the §9.5 amendment block ("`park` was `status <> 'sent'`"), classified as history.
* Item 2: `rejected` added at `design.md` §9.5 (no-op claim list) and `infrastructure/saga/command_dispatcher.py` docstring; `ALREADY_OWED` comment in `application/ports/saga_command_store.py` now "pending, parked, sent or rejected"; `infrastructure/saga/command_ledger.py` docstring line 1 adds `reject`.
* Item 3: note 5 corrected to partially recurred; Q1 wording corrected; ledger row "Other ledger predicates" adds `MarkSentAsync` (`EfCoreSagaCommandStore.cs:177`). Additional guards from the review: R4 (a `!= 'sent'` predicate on `reject` fails the two-claim test with `assert ('rejected', 9, 'second') == ('rejected', 1, 'first')`) and R10 (`ensure_in_range` deleted from `reject` fails `...outside_int32_raises_the_range_guards_domain_error`). No re-arming: no executable line changed.

### Checks (the first run flagged E501 on the new ALREADY_OWED comment; the comment moved to its own line, still comment-only)
```
$ grep -n "<> 'sent'\|!= 'sent'\|All four" specs/order_saga_orchestrator/design.md
524:> **Feature 42's amendment (§9.5).** `rejected` is a terminal row status. `reject` sets `status = 'rejected'`, `att
578: WHERE id = :id AND status IN ('pending', 'parked')   -- feature 42's amendment: was `status <> 'sent'`
588:- `mark_sent`, `park` and `reject` are conditional (feature 42's amendment: `reject` added, and `park` changed from 
(524: historical mention in the 9.5 amendment block; 578 and 588: feature 42 amendment markers naming the old predicate)
$ ruff format --check services/orders
181 files already formatted
$ ruff check services/orders
All checks passed!
$ pytest services/orders/tests/unit/saga
............................                                             [100%]
388 passed in 2.63s
```
