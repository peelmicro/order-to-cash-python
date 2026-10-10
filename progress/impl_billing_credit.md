# Implementation report: feature 19 `billing_credit`

Status: `in_review`. `./quality.sh` exit 0 with the developer stack down; every `tasks.md` box is ticked; no commit, no git command that writes the index or the working tree.

## 1. What was built

The first Billing runtime: the `BuyerCredit` aggregate with its append-only ledger, the credit-decision port (feature 20's seam) and its always-approve adapter, the three NATS responders (`billing.credit.hold`, `.release`, `.list`), Billing's copies of the outbox family under the extended parity guard, the first Billing composition root, lifespan and readiness, and `BC34`'s client-id pattern in all three services.

- **Domain** (`services/billing/src/otc_billing/domain/`): `errors.py` (nine errors, amounts through `format_money`), `credit_entry_type.py`, `ledger_entry.py` (frozen; refuses a negative amount, accepts zero: G1 as recommended), `snapshot.py`, `reasons.py`, `events.py`, `exposure.py` (`summarise`, int64 check on every accumulated value), `buyer_credit.py` (`evaluate_hold`, `approve`, `refuse`, `release`, `consume`, `rehydrate`; `new_id` required at all six id sites).
- **Application**: `ports/{clock (copy),ids,credit_store,credit_decision}.py` (`decide` is a plain `def`), `messages.py`, `errors.py`, `scope.py`, `handlers.py`, `credit_hold.py`, `credit_release.py`.
- **Infrastructure**: `credit/always_approve.py`, `ids.py`, `clock.py` (copy), `messaging/subjects.py`, `outbox/{errors,publisher,kafka_publisher,relay,relay_task,wire,writer}.py` (copies) + `topic.py` + `payloads.py`, `settings.py` (five classes), `persistence/{credit_mapper,credit_repository,credit_reads,credit_transactions}.py`. No migration; `models.py`, `range_guards.py`, `types.py`, `sequences.py` and `alembic/` are untouched.
- **Presentation / host**: `presentation/{app,credit_headers,credit_wire,credit_rpc_errors,credit_responder}.py`, `composition.py`, `main.py`.
- **Other services** (BC34 only): the `pattern=r"^[A-Za-z0-9._-]+$"` on `client_id` in `services/orders/src/otc_orders/infrastructure/settings.py` and `services/fulfillment/src/otc_fulfillment/infrastructure/settings.py`, and the empty/blank cases in their settings tests.
- **Guards** edited: `tests/architecture/test_{composition_env_reads,registration_behaviour,write_path_population,kafka_client_confinement,outbox_copy_parity}.py`; new: `test_billing_rpc_error_retryability.py`, `test_kafka_client_ids.py`.
- **Spec bookkeeping**: `specs/shared/test-matrix.md` column 5 of `R37` - `R41` and the derived counts (feature 5: 5 green / 3 not yet green; total 36 / 1 scoped / 26), `specs/billing_credit/requirements.md` section 3.2 (all 34 rows `DONE`), `specs/billing_credit/tasks.md` (ticks), `.env.example` (two variables), `uv.lock` (workspace metadata), feature 19's status line.

Packages installed: none (the two workspace dependencies `aiokafka` and `nats-py>=2.16.0` were already locked for Orders and Fulfillment; `uv lock` added only the two dependency entries to `otc-billing`).

## 2. A. Preconditions

### A1: `design.md` against the repository (all true)

- `credits` and `credit_items` columns, the unique pair, `ix_credit_items_credit_id_order_reference`, `outbox`, `processed_events`: `services/billing/src/otc_billing/infrastructure/persistence/models.py:62-87, :140-167`.
- Fulfillment `composition.py`: settings bundle `:78-98`, `register_handlers` `:104`, single-relay guard `:137-178`, `FulfillmentRuntime` `:184`, `start_runtime` `:258-350` (pool `bound + 1`, `max_overflow=0` at `:273-277`).
- `stock_responder.py`: `StockResponder` `:131`, `_drain` `:203`, `_log_fault` `:235`; `stock_headers.py` (`required_correlation`), `stock_transactions.py` (`TRANSIENT_SQLSTATES`, pinned `READ COMMITTED`), `scope.py` (`MissingBindingError`); `stock_store.py:114-122` is `class StockTransaction(Protocol)`.
- Orders `nats_saga_commands.py:65-75` is `TERMINAL_RPC_ERROR_CODES` (nine codes); `:143` is the per-call `headers` dict with `x-correlation-id` / `x-request-id`; `relay.py:46-48` is `DEADLOCK_DETECTED` / `DEADLOCK_ATTEMPTS` / `DEADLOCK_BACKOFF_SECONDS`.
- Measured with `uv run python -I` and `KAFKA_CLIENT_ID=` / `FULFILLMENT_KAFKA_CLIENT_ID=`: both `KafkaSettings(_env_file=None).client_id` are `''`; aiokafka `producer.py:284-287` substitutes a default only `if client_id is None`.

### A2: baseline

`./quality.sh`, stack down (only `otcpy-n8n`): exit 0, 331 s, **2784 passed**, overall coverage 97.98 %, domain 99 %, web 1 test. Log `.arm/a2_quality.log`.

### A3: packages

`diff .arm/uv.lock.before uv.lock`: `+ { name = "aiokafka" }`, `+ { name = "nats-py" }` (dependency entries of `otc-billing`) and the two `requires-dist` specifiers; no package version added.

## 3. L1 / quality numbers

Final `./quality.sh` (stack down): exit **0**, 609 s (the A2 run took 331 s; the second run of this feature took 354 s: the third was slower because the machine was loaded, not because of a test), **3111 passed = +327 over the baseline of 2784**, overall coverage 97.42 % (gate 60), domain coverage 99 % (gate 80), web 1 test. `./init.sh` exit 0. Logs `.arm/bc19/quality{1,2,3}.log` (the first run failed on one classification, `presentation/credit_responder.py`'s `in_flight.add(task)`, which `test_write_path_population.py` rightly reported; classified, then green).

## 4. Requirement to test (full names in `specs/shared/test-matrix.md` column 5 and `requirements.md` 3.2)

`R37`: `test_r37_keeps_active_holds_plus_open_exposure_within_the_credit_limit_and_raises_on_any_update_or_deletion_of_a_ledger_entry`. `R38`: `test_r38_appends_a_hold_entry_and_emits_exactly_one_credit_approved_v1_...` (domain), `test_r38_an_approved_hold_appends_one_hold_row_and_emits_one_credit_approved_v1` (host). `R39`: `test_r39_appends_no_ledger_entry_and_emits_credit_rejected_v1_...`, `test_r39_an_over_limit_hold_replies_rejected_...`. `R40`: `test_r40_appends_a_consume_entry_at_invoice_issue_...` (delivered, not driven: feature 21 calls it). `R41`: `test_r41_releases_with_reason_invoice_paid_on_payment_and_with_reason_order_cancelled_...`, `test_bc25_one_release_entry_...` (the `invoice_paid` caller is feature 22). Local ids `BC1` - `BC39` map one-to-one to the tests of `requirements.md` section 3.2 (checked mechanically: every cited file and function exists).

## 5. Deviations from the design, and surprises

1. **Import order in two outbox copies.** `otc_billing` sorts before `otc_contracts`, so the canonical's import order (which the parity guard keeps) is an `I001` error in Billing's `outbox/wire.py` and `outbox/writer.py`. Each carries `# ruff: noqa: I001 - ...` on the line BEFORE the docstring (outside the compared region). No `pyproject.toml` change.
2. Billing's nine copies were first generated from Fulfillment's copies and failed the parity guard (the formatter reflows `FULFILLMENT_FACTS_TOPIC` lines that `BILLING_FACTS_TOPIC` does not need): they were regenerated from Orders' canonicals through the guard's own `expected_body`. Lesson: derive a copy from the canonical, never from a sibling copy.
3. `approve` on an `AlreadyHeld` / `CurrencyMismatch` evaluation raises `CreditRefusalMismatchError` (the nine-error list has no better code; only a caller that bypasses `evaluate_hold` can reach it).
4. `release` checks a negative exposure BEFORE the "nothing outstanding" test. With the structural reading, `CreditReleaseUnderflowError` would otherwise be unreachable (a negative exposure needs a `release` entry, which already means "nothing outstanding"); a ledger that releases more than it held now fails loudly.
5. `summarise` takes `LedgerLine(order_reference, type, amount)` values, because the list view reads four columns, not entries.
6. The unknown-token scalar returns a count only, so the error message describes the count instead of naming the token.
7. `BuyerCreditSnapshot` carries `credit_limit` / `committed_exposure` as `int` plus `currency` (the task D5 asserts `type(...) is int`); `rehydrate` builds the `Money`.
8. `app.py` no longer exports a module-level `app`; `main.py` does (Fulfillment's shape). Nothing referenced the old name.
9. The first `B5` "check only per order" arm SURVIVED: the cross-order `active_holds` check masked the removed `committed` check. The arm was re-run removing all three cross-order checks and failed as intended (this is the reading of "check only inside the per-order accumulation").
10. `H2`'s "credit_code from another line" arm fails with a BC32-named `INTERNAL_ERROR` assertion, not at the field comparison: the generated model's `^CR-` pattern refuses any sibling value at the writer, so the payload model is itself a guard of that field.
11. F3's reply-key-set arms live in `unit/test_credit_wire.py` (they need the reply builders); `test_outbox_payloads.py` carries the three payload mappings and the "approved payload transposed" arm.
12. G4's "NATS URL hard-coded" arm fails with `NoServersError` (the hard-coded default address has no server) rather than at the recorded-URL assertion.
13. Shared-kernel / test-matrix rule: `R40`'s row is `DONE` on its domain test alone (the matrix names a domain unit test); the integration half does not exist because no caller exists before feature 21.

## 6. Arming

Tool `.arm/bc19/arm.py` (backup into the repo-local `.arm/bc19/bak/<arm>/` with sha256, exactly ONE literal mutation, one named test, process group killed on timeout, restore from the backup, `cmp`, caches cleared, re-run green). Logs `.arm/bc19/logs/<arm>.log`. **141 arms, every one seen red under its named mutation and green after restore; 0 survivors; 0 runs with a `cmp` difference** (`grep -l DIFFERENT logs/*.log` empty; every log says `sha256 equals before: True`). After the last edit to any guarded file, the whole set was re-run in one pass (`.arm/bc19/run_all.sh`, 144 arm invocations, all `FAILED (armed)`).

The tasks' prescribed counts: B6 six per-site arms (each fails at its own assertion line of `test_credit_ids.py`: the `B6-site*` rows below give the six line numbers), F6 eleven arms (nine files + census + docstring), G2 three arms, I1 three arms, E5 two arms, H2, H3 and H5 two each (H4 one), C2 pytest + mypy for both prescribed mutations (the `assert_never` error and the `Protocol` assignment error are in the `C2-*-mypy` rows).

| arm | run | location | message | sha256 (12) | restored cmp | control | re-run |
|---|---|---|---|---|---|---|---|
| B2-drop-negative-check | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_ledger_entry.py:61 | Failed: R37: a ledger entry accepted the negative amount -1 EUR | 63550412dac8 | True |  | 1 passed in 0.02s |
| B2-parse-strip-lower | mutated run: exit=1 (1.1s) | services/billing/tests/unit/domain/test_credit_ledger_entry.py:41 | Failed: BC37: the closed set accepted 'Hold' as CreditEntryType.HOLD | ae425e773b86 | True |  | 1 passed in 0.02s |
| B4-group-by-upper | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_exposure.py:96 | AssertionError: two references differing only by letter case were merged | 4f753f30db54 | True |  | 1 passed in 0.03s |
| B4-open-exposure-naive | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_exposure.py:57 | AssertionError: the cancelled-before-invoice shape went negative | 4f753f30db54 | True |  | 5 passed in 0.03s |
| B5-check-only-per-order | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_exposure.py:129 | Failed: BC30: summarise returned a total outside int64 instead of raising: committed_exposure=9223372036854775810 | 4f753f30db54 | True | control under the mutation: exit=0 (0.9s) [1 passed in 0.02s | 1 passed in 0.03s |
| B5-delete-range-check-1 | mutated run: exit=1 (1.1s) | services/billing/tests/unit/domain/test_credit_exposure.py:119 | Failed: BC30: summarise returned a total outside int64 instead of raising: committed_exposure=9223372036854775810 | 4f753f30db54 | True |  | 1 passed in 0.03s |
| B5-delete-range-check-2 | mutated run: exit=1 (1.1s) | services/billing/tests/unit/domain/test_credit_exposure.py:129 | Failed: BC30: summarise returned a total outside int64 instead of raising: committed_exposure=9223372036854775810 | 4f753f30db54 | True |  | 1 passed in 0.03s |
| B6-site1-hold-entry | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_ids.py:35 | AssertionError: site 1: the hold entry id is not the supplied one | 64a2cd512cb9 | True |  | 1 passed in 0.02s |
| B6-site2-approved-event | mutated run: exit=1 (1.1s) | services/billing/tests/unit/domain/test_credit_ids.py:36 | AssertionError: site 2: the approved fact's event id is not the supplied one | 64a2cd512cb9 | True |  | 1 passed in 0.02s |
| B6-site3-rejected-event | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_ids.py:50 | AssertionError: site 3: the rejected fact's event id is not the supplied one | 64a2cd512cb9 | True |  | 1 passed in 0.02s |
| B6-site4-release-entry | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_ids.py:66 | AssertionError: site 4: the release entry id is not the supplied one | 64a2cd512cb9 | True |  | 1 passed in 0.04s |
| B6-site5-released-event | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_ids.py:69 | AssertionError: site 5: the released fact's event id is not the supplied one | 64a2cd512cb9 | True |  | 1 passed in 0.03s |
| B6-site6-consume-entry | mutated run: exit=1 (1.1s) | services/billing/tests/unit/domain/test_credit_ids.py:76 | AssertionError: site 6: the consume entry id is not the supplied one | 64a2cd512cb9 | True |  | 1 passed in 0.02s |
| B7-rehydrate-no-limit-check | mutated run: exit=1 (1.1s) | services/billing/tests/unit/domain/test_buyer_credit.py:150 | Failed: rehydrate accepted a snapshot over its limit | 64a2cd512cb9 | True |  | 1 passed in 0.03s |
| B7-release-rewrites-hold | mutated run: exit=1 (1.1s) | services/billing/tests/unit/domain/test_buyer_credit.py:56 | AssertionError: a loaded entry was rewritten | 64a2cd512cb9 | True |  | 1 passed in 0.03s |
| B8-approved-retailer-from-company | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_hold.py:96 | AssertionError: R38: a field of the credit.approved.v1 fact is not the supplied/derived value | 64a2cd512cb9 | True |  | 1 passed in 0.04s |
| B8-available-after-pre-hold | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_hold.py:155 | AssertionError: the fact carries the pre-hold value | 64a2cd512cb9 | True |  | 1 passed in 0.04s |
| B8-currency-before-already-held | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_hold.py:235 | AssertionError: BC26: already_held must rank above currency_mismatch | 64a2cd512cb9 | True |  | 1 passed in 0.04s |
| B8-refuse-hardcoded-over-limit | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_hold.py:136 | AssertionError: R39/BC14: a field of the port-refusal credit.rejected.v1 fact is wrong | 64a2cd512cb9 | True |  | 1 passed in 0.04s |
| B8-rejected-retailer-from-company | mutated run: exit=1 (1.1s) | services/billing/tests/unit/domain/test_credit_hold.py:119 | AssertionError: R39: a field of the over-limit credit.rejected.v1 fact is wrong | 64a2cd512cb9 | True |  | 1 passed in 0.04s |
| B8-requested-plus-one | mutated run: exit=1 (1.1s) | services/billing/tests/unit/domain/test_credit_hold.py:119 | AssertionError: R39: a field of the over-limit credit.rejected.v1 fact is wrong | 64a2cd512cb9 | True |  | 1 passed in 0.04s |
| B9-consume-keyed-on-positive-active-hold | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_ledger.py:199 | otc_billing.domain.errors.NoActiveHoldError: Order ORD-000101 has no active hold: it was never held, or its hold was already consumed or released. | 64a2cd512cb9 | True | control under the mutation: exit=0 (0.9s) [2 passed in 0.02s | 1 passed in 0.04s |
| B9-consume-reduces-committed | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_ledger.py:46 | AssertionError: R40: a consume entry moved the available credit | 64a2cd512cb9 | True |  | 1 passed in 0.04s |
| B9-release-double-counts | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_ledger.py:142 | AssertionError: BC11: the release was not counted once | 64a2cd512cb9 | True |  | 1 passed in 0.05s |
| B9-release-emits-on-no-op | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_ledger.py:149 | AssertionError: the no-op release emitted a fact | 64a2cd512cb9 | True |  | 1 passed in 0.04s |
| B9-release-keyed-on-positive-exposure | mutated run: exit=1 (1.0s) | services/billing/tests/unit/domain/test_credit_ledger.py:214 | AssertionError: BC38: a zero hold was not released (nothing outstanding) | 64a2cd512cb9 | True | control under the mutation: exit=0 (0.9s) [3 passed in 0.02s | 1 passed in 0.04s |
| C2-add-over-limit-member-mypy | mutated run: exit=1 (7.8s) |  |  | 35a1a4f4e612 | True |  | Success: no issues found in 104 source files |
| C2-add-over-limit-member-pytest | mutated run: exit=1 (1.0s) | services/billing/tests/unit/test_credit_decision_port.py:30 | AssertionError: BC14: the adapter's reason type has members ['over_limit', 'simulated_cents_rule', 'simulated_failure_rate'] | 35a1a4f4e612 | True |  | 1 passed in 0.03s |
| C2-async-decide-mypy | mutated run: exit=1 (7.5s) | services/billing/tests/unit/test_always_approve.py:17 |  | 196290a583cf | True |  | Success: no issues found in 104 source files |
| C2-async-decide-pytest | mutated run: exit=1 (1.0s) | services/billing/tests/unit/test_always_approve.py:29 | AssertionError: BC15: the default adapter did not approve 0 | 196290a583cf | True |  | 1 passed in 0.03s |
| C3-delete-refuse-on-port-branch | mutated run: exit=1 (1.0s) | services/billing/tests/unit/test_credit_hold_service.py:235 | AssertionError: BC14: expected exactly one fact on the saved aggregate, got () | 65ffb022f2ed | True |  | 1 passed in 0.08s |
| C3-delete-save-on-refusal | mutated run: exit=1 (1.0s) | services/billing/tests/unit/test_credit_hold_service.py:232 | AssertionError: BC14: the refusal branch did not save the aggregate | 65ffb022f2ed | True |  | 1 passed in 0.08s |
| C3-port-before-over-limit-check | mutated run: exit=1 (1.0s) | services/billing/tests/unit/test_credit_hold_service.py:197 | AssertionError: BC13: the port was consulted 1 time(s) for an over-limit hold | 65ffb022f2ed | True |  | 1 passed in 0.08s |
| C3-refuse-wrong-reason | mutated run: exit=1 (1.1s) | services/billing/tests/unit/test_credit_hold_service.py:227 | AssertionError: BC14: the reply carries a reason other than the port's | 65ffb022f2ed | True |  | 1 passed in 0.08s |
| C3-uniqueid-new-instead-of-scope-ids | mutated run: exit=1 (1.0s) | services/billing/tests/unit/test_credit_hold_service.py:289 | AssertionError: BC36: the hold entry id | 65ffb022f2ed | True |  | 1 passed in 0.08s |
| C4-corrupt-released-amount | mutated run: exit=1 (1.0s) | services/billing/tests/unit/test_credit_release_service.py:154 | AssertionError: a field of the credit.released.v1 fact is wrong | 64a2cd512cb9 | True |  | 1 passed in 0.06s |
| C4-delete-fact-emission | mutated run: exit=1 (1.0s) | services/billing/tests/unit/test_credit_release_service.py:153 | AssertionError: expected exactly one credit.released.v1, got 0 | 64a2cd512cb9 | True |  | 1 passed in 0.07s |
| C4-emit-on-no-op | mutated run: exit=1 (1.1s) | services/billing/tests/unit/test_credit_release_service.py:191 | AssertionError: released: the no-op release recorded a fact | 64a2cd512cb9 | True |  | 1 passed in 0.06s |
| C4-uniqueid-new-instead-of-scope-ids | mutated run: exit=1 (1.0s) | services/billing/tests/unit/test_credit_release_service.py:208 | AssertionError: BC36: the release entry id | 9afffa0b5090 | True |  | 1 passed in 0.06s |
| D2-clear-events-before-commit | mutated run: exit=1 (1.4s) | services/billing/tests/unit/test_credit_transactions.py:163 | AssertionError: OI9: events were cleared before the commit returned | c64e23489a8d | True |  | 1 passed in 0.32s |
| D2-drop-40P01 | mutated run: exit=1 (1.4s) | services/billing/tests/unit/test_credit_transactions.py:117 | sqlalchemy.exc.DBAPIError: (services.billing.tests.unit.test_credit_transactions.DriverError) driver error 40P01 | c64e23489a8d | True |  | 7 passed in 0.33s |
| D2-map-every-dbapi-error | mutated run: exit=1 (1.4s) | services/billing/tests/unit/test_credit_transactions.py:99 | sqlalchemy.exc.DBAPIError: (services.billing.tests.unit.test_credit_transactions.DriverError) driver error 23505 | c64e23489a8d | True |  | 1 passed in 0.32s |
| D2-updated-at-second-clock-read | mutated run: exit=1 (1.1s) | services/billing/tests/unit/test_credit_mapper.py:38 | AssertionError: updated_at must be the same instant as created_at | ff9af715d74a | True |  | 1 passed in 0.10s |
| D3-commit-inside-save | mutated run: exit=1 (4.5s) | services/billing/tests/integration/test_credit_repository.py:131 | AssertionError: the hold row survived the rollback | 49f9b1ca52e0 | True |  | 1 passed in 3.73s |
| D4-delete-isolation-pin | mutated run: exit=1 (4.3s) | services/billing/tests/integration/test_credit_repository.py:163 | AssertionError: BC35: the transaction ran at 'repeatable read', not read committed | c64e23489a8d | True |  | 1 passed in 2.44s |
| D5-drop-22003-mapping | mutated run: exit=1 (4.9s) | services/billing/tests/integration/test_credit_repository.py:247 | asyncpg.exceptions.NumericValueOutOfRangeError: bigint out of range | 49f9b1ca52e0 | True |  | 1 passed in 2.59s |
| D5-drop-cast | mutated run: exit=1 (4.4s) | services/billing/tests/integration/test_credit_repository.py:188 | otc_billing.domain.errors.InvalidBuyerCreditSnapshotError: The stored credit line cannot be restored: committed exposure Decimal('7000') is not an int. | 49f9b1ca52e0 | True |  | 1 passed in 2.56s |
| D5-ignore-unknown-count | mutated run: exit=1 (4.5s) | services/billing/tests/integration/test_credit_repository.py:234 | Failed: BC37: a line with an unknown type token answered HoldOutcomeKind.APPROVED | 49f9b1ca52e0 | True |  | 1 passed in 2.53s |
| D6-mapper-drops-tzinfo | mutated run: exit=1 (4.5s) | services/billing/tests/integration/test_credit_repository.py:278 | AssertionError: BC24: wrote 2026-10-08 09:30:15.123000+00:00, read back 2026-10-08 09:30:15.123000 | ff9af715d74a | True |  | 1 passed in 3.60s |
| D6-mapper-to-madrid-then-drop-tzinfo | mutated run: exit=1 (4.2s) | services/billing/tests/integration/test_credit_repository.py:278 | AssertionError: BC24: wrote 2026-10-08 09:30:15.123000+00:00, read back 2026-10-08 11:30:15.123000 | ff9af715d74a | True |  | 1 passed in 2.53s |
| D6-repo-updates-earlier-row | mutated run: exit=1 (4.4s) | services/billing/tests/integration/test_credit_repository.py:289 | assert datetime.datetime(2026, 10, 9, 5, 57, 13, 734000, tzinfo=datetime.timezone.utc) == datetime.datetime(2026, 10, 9, 4, 57, 13, 741000, tzinfo=datetime.timezone.utc) | 49f9b1ca52e0 | True |  | 1 passed in 3.71s |
| D8-second-session-add | mutated run: exit=1 (1.2s) | tests/architecture/test_write_path_population.py:427 | AssertionError: services/billing/src has an unclassified write path (or lost a classified one, or gained a second occurrence of one): add it to EXPECTED with its classification. Found: {'infrastructur | 49f9b1ca52e0 | True |  | 4 passed in 0.21s |
| E2-hold-subject-sibling | mutated run: exit=1 (1.5s) | services/billing/tests/unit/test_credit_subjects.py:42 | AssertionError: channel creditHold: the subject Billing answers is not the spec's address | 0a5174fb7a71 | True |  | 1 passed in 0.74s |
| E3-drop-length-check | mutated run: exit=1 (1.3s) | services/billing/tests/unit/test_credit_requests.py:159 | Failed: BC33: a 21-character orderReference on credit.hold was accepted: HoldCreditCommand(order_reference='ORD-11111111111111111', retailer_code='RETAIL-77', company_code='SUPPLY-CO', amount=Money(am | 111b3482dd1a | True |  | 1 passed in 0.24s |
| E3-drop-sign-check | mutated run: exit=1 (1.4s) | services/billing/tests/unit/test_credit_requests.py:177 | Failed: BC33: a negative hold amount was accepted: HoldCreditCommand(order_reference='ORD-000101', retailer_code='RETAIL-77', company_code='SUPPLY-CO', amount=Money(amount=-1, currency='EUR'), correla | 111b3482dd1a | True |  | 1 passed in 0.30s |
| E4-already-held-reports-current-exposure | mutated run: exit=1 (1.5s) | services/billing/tests/unit/test_credit_wire.py:88 | assert (1000, 300) == (300, 1000) | 111b3482dd1a | True |  | 1 passed in 0.31s |
| E5-fresh-id-for-malformed-request-id | mutated run: exit=1 (1.5s) | services/billing/tests/unit/test_credit_responder.py:222 | AssertionError: billing.credit.hold: request malformed | ce757af97b98 | True |  | 8 passed in 0.36s |
| E5-tolerate-missing-request-id | mutated run: exit=1 (2.1s) | services/billing/tests/unit/test_credit_responder.py:222 | AssertionError: billing.credit.hold: request malformed | ce757af97b98 | True |  | 8 passed in 0.39s |
| E6-overflow-to-unavailable | mutated run: exit=1 (1.5s) | services/billing/tests/unit/test_credit_rpc_errors.py:106 | AssertionError: ledger overflow | 0e1236767d95 | True |  | 13 passed in 0.31s |
| E6-raw-amount-in-message | mutated run: exit=1 (1.5s) | services/billing/tests/unit/test_credit_rpc_errors.py:138 | AssertionError: assert '92.45 EUR' in 'A hold of 9245 exceeds the available credit of 1.00 EUR.' | 03608fd9b6cd | True |  | 1 passed in 0.31s |
| E6-store-unavailable-to-conflict | mutated run: exit=1 (1.4s) | tests/architecture/test_billing_rpc_error_retryability.py:88 | AssertionError: StoreUnavailableError(the credit store is temporarily unavailable (40001)) is answered CONFLICT, which Orders' saga adapter treats as a terminal rejection | 0e1236767d95 | True |  | 1 passed in 0.39s |
| E6-unlisted-domain-error | mutated run: exit=1 (1.5s) | tests/architecture/test_billing_rpc_error_retryability.py:99 | AssertionError: a DomainError subclass was added or removed: ['CreditCurrencyMismatchError', 'CreditLedgerOverflowError', 'CreditLimitExceededError', 'CreditLineNotFoundError', 'CreditRefusalMismatchE | 03608fd9b6cd | True |  | 1 passed in 0.37s |
| E7-gather-without-return-exceptions | mutated run: exit=1 (1.4s) | services/billing/tests/unit/test_credit_responder.py:351 | AssertionError: one request finishing (badly) must not end the drain early | 5225b5a8b1fb | True |  | 1 passed in 0.36s |
| E7-skip-drain | mutated run: exit=1 (1.4s) | services/billing/tests/unit/test_credit_responder.py:348 | AssertionError: the drain must wait for the requests still running | 5225b5a8b1fb | True |  | 1 passed in 0.36s |
| E7-swallow-cancelled-error | mutated run: exit=1 (1.3s) | services/billing/tests/unit/test_credit_responder.py:378 | Failed: BC22: cancelling `run` did not re-raise the cancellation (it was swallowed) | 5225b5a8b1fb | True |  | 1 passed in 0.26s |
| E8-delete-flush | mutated run: exit=1 (1.2s) | services/billing/tests/unit/test_credit_responder.py:393 | AssertionError: assert ('subscribe',...'otc-billing') == ('flush',) | 5225b5a8b1fb | True |  | 1 passed in 0.28s |
| E8-one-scope-per-responder | mutated run: exit=1 (1.4s) | services/billing/tests/unit/test_credit_responder.py:304 | AssertionError: BC21: two concurrent requests observe the same scope | 5225b5a8b1fb | True |  | 1 passed in 0.25s |
| E8-scope-before-bound | mutated run: exit=1 (1.4s) | services/billing/tests/unit/test_credit_responder.py:319 | AssertionError: BC21: 2 scopes exist while one request holds the only slot: a waiting request opened its unit of work before it was admitted | 5225b5a8b1fb | True |  | 1 passed in 0.31s |
| F2-topic-sibling | mutated run: exit=1 (1.2s) | services/billing/tests/unit/test_fact_topic.py:24 | AssertionError: channel billingFacts: the topic the outbox publishes to is not the spec's | 965813b1ed03 | True |  | 1 passed in 0.20s |
| F3-approved-reply-with-a-reason | mutated run: exit=1 (1.2s) | services/billing/tests/unit/test_credit_wire.py:43 | AssertionError: an approved reply has no `reason` key | 111b3482dd1a | True |  | 1 passed in 0.18s |
| F3-rejected-reply-with-held-amount | mutated run: exit=1 (1.3s) | services/billing/tests/unit/test_credit_wire.py:68 | AssertionError: a rejected reply has no `heldAmount` key | 111b3482dd1a | True |  | 1 passed in 0.17s |
| F3-released-false-with-amount | mutated run: exit=1 (1.3s) | services/billing/tests/unit/test_credit_wire.py:144 | AssertionError: released: false has no `releasedAmount` key | 111b3482dd1a | True |  | 1 passed in 0.21s |
| F3-transpose-held-and-available-after | mutated run: exit=1 (1.2s) | services/billing/tests/unit/test_outbox_payloads.py:117 | AssertionError: held_amount and available_credit_after must not be transposed | a24063feac0b | True |  | 1 passed in 0.18s |
| F4-consumer-import-in-billing-publisher | mutated run: exit=1 (1.3s) | tests/architecture/test_kafka_client_confinement.py:101 | assert ["the publish...kaConsumer']"] == [] | 7a627fb88e5b | True |  | 1 passed in 0.20s |
| F5-key-by-aggregate-id | mutated run: exit=1 (12.7s) | python/services/billing/tests/integration/test_billing_outbox_relay.py:141 | AssertionError: BC16: keyed by b'177ec39e-0a6d-4738-a804-c0eed0e1e037', not by the correlationId (the order id) | bc12b7db4a7f | True |  | 1 passed in 10.44s |
| F6-application-ports-clock.py | mutated run: exit=1 (1.9s) | tests/architecture/test_outbox_copy_parity.py:201 | AssertionError: billing's outbox copies differ from Orders': ["application/ports/clock.py: differs from the canonical after the docstring: ['@@ -5 +5 @@\\n', '-class Clock(Protocol):', '+class _Clock( | 3b9744e6dbbc | True |  | 1 passed in 0.35s |
| F6-census-service-with-outbox-and-no-copies | mutated run: exit=1 (1.0s) | tests/architecture/test_outbox_copy_parity.py:216 | AssertionError: ["services owning an `outbox` table without the relay family: ['notifications'] (listed: ['billing', 'fulfillment', 'orders'])"] | ae1896c6c92d | True |  | 1 passed in 0.04s |
| F6-docstring-names-no-canonical | mutated run: exit=1 (1.3s) | tests/architecture/test_outbox_copy_parity.py:201 | AssertionError: billing's outbox copies differ from Orders': ["infrastructure/clock.py: the copy's docstring does not name its canonical services/orders/src/otc_orders/infrastructure/clock.py"] | a68ecdc4b98e | True |  | 1 passed in 0.36s |
| F6-infrastructure-clock.py | mutated run: exit=1 (1.3s) | tests/architecture/test_outbox_copy_parity.py:201 | AssertionError: billing's outbox copies differ from Orders': ["infrastructure/clock.py: differs from the canonical after the docstring: ['@@ -6 +6 @@\\n', '-class SystemClock:', '+class _SystemClock:' | a68ecdc4b98e | True |  | 1 passed in 0.34s |
| F6-infrastructure-outbox-errors.py | mutated run: exit=1 (1.3s) | tests/architecture/test_outbox_copy_parity.py:201 | AssertionError: billing's outbox copies differ from Orders': ["infrastructure/outbox/errors.py: differs from the canonical after the docstring: ['@@ -1 +1 @@\\n', '-class UnmappedDomainEventError(Exce | 5660c8694764 | True |  | 1 passed in 0.35s |
| F6-infrastructure-outbox-kafka_publisher.py | mutated run: exit=1 (1.3s) | tests/architecture/test_outbox_copy_parity.py:201 | AssertionError: billing's outbox copies differ from Orders': ["infrastructure/outbox/kafka_publisher.py: differs from the canonical after the docstring: ['@@ -14 +14 @@\\n', '-class _Producer(Protocol | 7a627fb88e5b | True |  | 1 passed in 0.35s |
| F6-infrastructure-outbox-publisher.py | mutated run: exit=1 (1.4s) | tests/architecture/test_outbox_copy_parity.py:201 | AssertionError: billing's outbox copies differ from Orders': ["infrastructure/outbox/publisher.py: differs from the canonical after the docstring: ['@@ -8 +8 @@\\n', '-class PublishableFact:', '+class | 1e603ae4b9e8 | True |  | 1 passed in 0.35s |
| F6-infrastructure-outbox-relay.py | mutated run: exit=1 (1.3s) | tests/architecture/test_outbox_copy_parity.py:201 | AssertionError: billing's outbox copies differ from Orders': ["infrastructure/outbox/relay.py: differs from the canonical after the docstring: ['@@ -28 +28 @@\\n', '-class PoisonedRow:', '+class _Pois | d6ff44caeb64 | True |  | 1 passed in 0.37s |
| F6-infrastructure-outbox-relay_task.py | mutated run: exit=1 (1.3s) | tests/architecture/test_outbox_copy_parity.py:201 | AssertionError: billing's outbox copies differ from Orders': ["infrastructure/outbox/relay_task.py: differs from the canonical after the docstring: ['@@ -11 +11 @@\\n', '-class RunsOutboxOnce(Protocol | bd695bf85203 | True |  | 1 passed in 0.36s |
| F6-infrastructure-outbox-wire.py | mutated run: exit=1 (1.3s) | tests/architecture/test_outbox_copy_parity.py:201 | AssertionError: billing's outbox copies differ from Orders': ["infrastructure/outbox/wire.py: differs from the canonical after the docstring: ['@@ -9 +9 @@\\n', '-def to_publishable_fact(row: Outbox)  | bc12b7db4a7f | True |  | 1 passed in 0.36s |
| F6-infrastructure-outbox-writer.py | mutated run: exit=1 (1.4s) | tests/architecture/test_outbox_copy_parity.py:201 | AssertionError: billing's outbox copies differ from Orders': ["infrastructure/outbox/writer.py: differs from the canonical after the docstring: ['@@ -14 +14 @@\\n', '-class OutboxWriter:', '+class _Ou | eda047ea6b76 | True |  | 1 passed in 0.34s |
| G2-remove-pattern-billing | mutated run: exit=1 (1.5s) | python/services/billing/tests/unit/test_billing_settings_env.py:220 | Failed: BC34: BILLING_KAFKA_CLIENT_ID='' was accepted: the service would boot with it | ab8223fecfd4 | True | control under the mutation: exit=0 (2.0s) [8 passed in 0.92s | 5 passed in 0.55s |
| G2-remove-pattern-fulfillment | mutated run: exit=1 (1.5s) | python/services/fulfillment/tests/unit/test_fulfillment_settings_env.py:221 | Failed: BC34: FULFILLMENT_KAFKA_CLIENT_ID='' was accepted (it would boot) | 0780effc2eca | True | control under the mutation: exit=0 (1.6s) [9 passed in 0.56s | 4 passed in 0.41s |
| G2-remove-pattern-orders | mutated run: exit=1 (1.5s) | python/services/orders/tests/unit/test_orders_settings_env.py:198 | Failed: BC34: KAFKA_CLIENT_ID='' was accepted: the service would boot with it | 4af21a2b9a58 | True | control under the mutation: exit=0 (1.6s) [9 passed in 0.54s | 4 passed in 0.45s |
| G3-billing-default-is-orders | mutated run: exit=1 (1.1s) | python/tests/architecture/test_kafka_client_ids.py:39 | AssertionError: two services share a default client id: {'orders': 'otc-orders', 'fulfillment': 'otc-fulfillment', 'billing': 'otc-orders'} | ab8223fecfd4 | True |  | 1 passed in 0.10s |
| G4-delete-a-settings-class-from-load-settings | mutated run: exit=1 (1.0s) | tests/architecture/test_composition_env_reads.py:153 | AssertionError: load_settings never builds ['ResponderSettings'] | 2ea0fb267040 | True |  | 1 passed in 0.16s |
| G4-hardcode-pool-size | mutated run: exit=1 (10.6s) | python/services/billing/tests/integration/test_billing_host_lifespan.py:373 | AssertionError: the engine's pool is sized from the bound + 1 | 2ea0fb267040 | True |  | 1 passed in 8.72s |
| G4-nats-url-hardcoded | mutated run: exit=1 (132.0s) | python/services/billing/tests/integration/test_billing_host_lifespan.py:364 | nats.errors.NoServersError: nats: no servers available for connection | 2ea0fb267040 | True |  | 1 passed in 8.56s |
| G4-orders-client-id-to-publisher | mutated run: exit=1 (10.6s) | python/services/billing/tests/integration/test_billing_host_lifespan.py:376 | AssertionError: BILLING_KAFKA_CLIENT_ID must reach it | 2ea0fb267040 | True |  | 1 passed in 9.78s |
| G5-remove-release-registration | mutated run: exit=1 (1.7s) | services/billing/tests/integration/test_billing_host_lifespan.py:451 | otc_cqrs.errors.DispatcherValidationError: No command handler is registered for ReleaseCreditCommand. Exactly one is required. | 2ea0fb267040 | True |  | 1 passed in 0.08s |
| G6-f-g-plus-f-j-pipeline-in-billing | mutated run: exit=1 (1.8s) | tests/architecture/test_registration_behaviour.py:247 | assert ["WIRE: 2 reg...ditCommand']"] == [] | e164da730645 | True |  | 1 passed in 1.04s |
| H1-delete-cents-rule-refusal | mutated run: exit=1 (2.1s) | services/billing/tests/unit/test_cents_rule_fixture_guard.py:43 | Failed: DID NOT RAISE AssertionError | c888a6e01bb3 | True |  | 1 passed in 0.58s |
| H2-causation-from-correlation-header | mutated run: exit=1 (10.5s) | python/services/billing/tests/integration/test_credit_hold.py:100 | AssertionError: causationId is not x-request-id | 65ffb022f2ed | True |  | 1 passed in 8.64s |
| H2-credit-code-from-another-line | mutated run: exit=1 (12.1s) | python/services/billing/tests/integration/test_credit_hold.py:63 | AssertionError: BC32: expected a hold reply (an `outcome`), got {'code': 'INTERNAL_ERROR', 'message': 'The request could not be processed.', 'correlationId': '35c138f6-a2ed-4854-b55f-73a299b33690', 'o | 64a2cd512cb9 | True |  | 1 passed in 7.65s |
| H3-corrupt-company-code-on-rejected-fact | mutated run: exit=1 (10.8s) | python/services/billing/tests/integration/test_credit_hold.py:126 | AssertionError: a field of the over-limit credit.rejected.v1 payload is wrong | 64a2cd512cb9 | True |  | 1 passed in 8.78s |
| H3-no-outbox-row-on-refusal | mutated run: exit=1 (10.6s) | python/services/billing/tests/integration/test_credit_hold.py:208 | AssertionError: expected exactly one fact for this correlation id, got 0 | 49f9b1ca52e0 | True |  | 1 passed in 8.69s |
| H4-already-held-only-when-net-exposure-positive | mutated run: exit=1 (10.5s) | python/services/billing/tests/integration/test_credit_hold.py:273 | AssertionError: a released hold must not re-approve (BC7) | 64a2cd512cb9 | True |  | 1 passed in 8.75s |
| H5-corrupt-retailer-code-on-released-fact | mutated run: exit=1 (11.8s) | python/services/billing/tests/integration/test_credit_release.py:50 | AssertionError: a field of the credit.released.v1 payload is wrong | 64a2cd512cb9 | True |  | 1 passed in 8.80s |
| H5-released-true-on-the-repeat | mutated run: exit=1 (10.5s) | python/services/billing/tests/integration/test_credit_release.py:65 | AssertionError: assert True is False | 9afffa0b5090 | True |  | 1 passed in 8.75s |
| H6-available-credit-from-active-holds-only | mutated run: exit=1 (10.8s) | python/services/billing/tests/integration/test_credit_list.py:72 | AssertionError: BC6: CR-000422 does not reconcile: available credit 100000 | fa1f5dd8b231 | True |  | 1 passed in 8.96s |
| H7-error-wrapped-in-response-key | mutated run: exit=1 (10.4s) | python/services/billing/tests/integration/test_credit_wire.py:83 | AssertionError: BC2: billing.credit.hold did not answer an RpcError: {'response': {'code': 'VALIDATION_FAILED', 'message': "credit.hold request is invalid: 4 validation errors for CreditHoldRequestPay | 5225b5a8b1fb | True |  | 1 passed in 8.47s |
| H7-reply-wrapped-in-response-key | mutated run: exit=1 (10.5s) | python/services/billing/tests/integration/test_credit_wire.py:53 | AssertionError: BC2: not a hold reply: {'response': {'outcome': 'approved', 'orderReference': 'ORD-000101', 'creditCode': 'CR-000321', 'currency': 'EUR', 'heldAmount': 4210, 'availableCredit': 95790}} | 5225b5a8b1fb | True |  | 1 passed in 9.69s |
| H8-list-answers-an-rpc-error-assertion-moved-after-the-collection | mutated run: exit=1 (12.6s) | python/services/billing/tests/integration/test_credit_list.py:62 | KeyError: 'items' | 5225b5a8b1fb | True |  | 1 passed in 11.40s |
| H8-list-answers-an-rpc-error-discriminating-field-first | mutated run: exit=1 (12.2s) | python/services/billing/tests/integration/test_credit_list.py:62 | AssertionError: BC32: expected a list reply (a `page`), got {'code': 'UNAVAILABLE', 'message': 'the credit store is temporarily unavailable (injected: answer the list with an RpcError)', 'occurredAt': | 5225b5a8b1fb | True |  | 1 passed in 10.23s |
| I1-drop-with-for-update | mutated run: exit=1 (10.8s) | python/services/billing/tests/integration/test_credit_hold_race.py:57 | AssertionError: BC9: two holds for 6 000 against 10 000 of credit answered ['approved', 'approved'] | 49f9b1ca52e0 | True |  | 1 passed in 9.97s |
| I1-repeatable-read | mutated run: exit=1 (9.6s) | python/services/billing/tests/integration/test_credit_hold_race.py:57 | AssertionError: BC9: two holds for 6 000 against 10 000 of credit answered ['approved', 'approved'] | c64e23489a8d | True |  | 1 passed in 8.78s |
| I1-scalar-before-lock | mutated run: exit=1 (9.6s) | python/services/billing/tests/integration/test_credit_hold_race.py:57 | AssertionError: BC9: two holds for 6 000 against 10 000 of credit answered ['approved', 'approved'] | 49f9b1ca52e0 | True |  | 1 passed in 8.71s |
| I2-read-order-entries-before-lock | mutated run: exit=1 (10.7s) | python/services/billing/tests/integration/test_credit_hold_race.py:93 | AssertionError: B4: two holds for ONE order answered ['approved', 'approved'] | 49f9b1ca52e0 | True |  | 1 passed in 8.81s |
| I3-serve-inline-in-the-loop | mutated run: exit=1 (21.0s) | python/services/billing/tests/integration/test_credit_responder_concurrency.py:50 | asyncio.exceptions.CancelledError | 5225b5a8b1fb | True |  | 1 passed in 8.78s |
| I4-drop-with-for-update-from-lock-for-order | mutated run: exit=1 (27.0s) | python/services/billing/tests/integration/test_credit_responder_concurrency.py:86 | AssertionError: expected 1 backend(s) waiting on a lock (query LIKE '%FROM credits%FOR UPDATE%'), saw 0 after 15.0 s: the request never waited on the line lock | 49f9b1ca52e0 | True |  | 1 passed in 10.00s |
| J1-01-credit_reads-summarise-deleted | mutated run: exit=1 (12.9s) | python/services/billing/tests/integration/test_credit_list.py:71 | AssertionError: CR-000411 | fa1f5dd8b231 | True |  | 1 passed in 10.25s |
| J1-02-aggregate-summary-property | mutated run: exit=1 (1.5s) | services/billing/tests/unit/domain/test_buyer_credit.py:44 | assert (0 + 0) == 700 | 64a2cd512cb9 | True |  | 5 passed in 0.05s |
| J1-03-order-exposure-other-order | mutated run: exit=1 (1.6s) | services/billing/tests/unit/domain/test_buyer_credit.py:55 | assert None is not None | 64a2cd512cb9 | True |  | 36 passed in 0.19s |
| J1-04-approve-skips-evaluate-hold | mutated run: exit=1 (1.4s) | services/billing/tests/unit/domain/test_buyer_credit.py:72 | Failed: DID NOT RAISE CreditLimitExceededError | 64a2cd512cb9 | True |  | 36 passed in 0.18s |
| J1-05-hold-lock-for-order-args-swapped | mutated run: exit=1 (12.3s) | python/services/billing/tests/integration/test_credit_hold.py:63 | AssertionError: BC32: expected a hold reply (an `outcome`), got {'code': 'NOT_FOUND', 'message': "No credit line exists for retailer 'RETAIL-77' and company 'SUPPLY-CO'.", 'details': {'retailerCode':  | 65ffb022f2ed | True |  | 1 passed in 10.03s |
| J1-06-hold-lock-for-order-order-reference-swapped | mutated run: exit=1 (1.3s) | services/billing/tests/unit/test_credit_hold_service.py:282 | AssertionError: assert [('RETAIL-77'... 'RETAIL-77')] == [('RETAIL-77'...'ORD-000101')] | 65ffb022f2ed | True |  | 8 passed in 0.15s |
| J1-07-hold-evaluate-hold-deleted | mutated run: exit=1 (1.6s) | services/billing/tests/unit/test_credit_hold_service.py:179 | otc_billing.domain.errors.CreditRefusalMismatchError: A hold of 2.50 EUR cannot be refused as 'approved': the available credit is 10.00 EUR. | 65ffb022f2ed | True |  | 8 passed in 0.13s |
| J1-08-hold-decide-deleted | mutated run: exit=1 (1.7s) | services/billing/tests/unit/test_credit_hold_service.py:204 | AssertionError: BC13: the port must be consulted once for a fitting hold | 65ffb022f2ed | True |  | 8 passed in 0.13s |
| J1-09-hold-approve-deleted | mutated run: exit=1 (1.8s) | services/billing/tests/unit/test_credit_hold_service.py:275 | assert (250, 700, None) == (250, 450, None) | 65ffb022f2ed | True |  | 8 passed in 0.12s |
| J1-10-hold-approve-id-port-bypassed | mutated run: exit=1 (1.2s) | services/billing/tests/unit/test_credit_hold_service.py:289 | AssertionError: BC36: the hold entry id | 65ffb022f2ed | True |  | 8 passed in 0.10s |
| J1-11-hold-save-after-approve-deleted | mutated run: exit=1 (1.2s) | services/billing/tests/unit/test_credit_hold_service.py:277 | assert 0 == 1 | 65ffb022f2ed | True |  | 8 passed in 0.11s |
| J1-12-hold-refuse-id-port-bypassed | mutated run: exit=1 (1.2s) | services/billing/tests/unit/test_credit_hold_service.py:236 | AssertionError: BC14: a field of the port-refusal fact is wrong | 65ffb022f2ed | True |  | 8 passed in 0.11s |
| J1-13-hold-clock-now-replaced | mutated run: exit=1 (1.2s) | services/billing/tests/unit/test_credit_hold_service.py:236 | AssertionError: BC14: a field of the port-refusal fact is wrong | 65ffb022f2ed | True |  | 8 passed in 0.10s |
| J1-14-hold-causation-from-correlation | mutated run: exit=1 (1.2s) | services/billing/tests/unit/test_credit_hold_service.py:236 | AssertionError: BC14: a field of the port-refusal fact is wrong | 65ffb022f2ed | True |  | 8 passed in 0.11s |
| J1-15-release-lock-for-order-args-swapped | mutated run: exit=1 (11.9s) | python/services/billing/tests/integration/test_credit_release.py:36 | AssertionError: BC32: expected a release reply (`released`), got {'code': 'NOT_FOUND', 'message': "No credit line exists for retailer 'RETAIL-77' and company 'SUPPLY-CO'.", 'details': {'retailerCode': | 9afffa0b5090 | True |  | 1 passed in 10.00s |
| J1-16-release-reason-sibling | mutated run: exit=1 (1.3s) | services/billing/tests/unit/test_credit_release_service.py:154 | AssertionError: a field of the credit.released.v1 fact is wrong | 9afffa0b5090 | True |  | 4 passed in 0.10s |
| J1-17-release-correlation-from-request-id | mutated run: exit=1 (1.2s) | services/billing/tests/unit/test_credit_release_service.py:154 | AssertionError: a field of the credit.released.v1 fact is wrong | 9afffa0b5090 | True |  | 4 passed in 0.09s |
| J1-18-release-save-deleted | mutated run: exit=1 (1.2s) | services/billing/tests/unit/test_credit_release_service.py:148 | AssertionError: the release must save the aggregate exactly once | 9afffa0b5090 | True |  | 4 passed in 0.08s |
| J1-19-release-clock-now-replaced | mutated run: exit=1 (1.2s) | services/billing/tests/unit/test_credit_release_service.py:154 | AssertionError: a field of the credit.released.v1 fact is wrong | 9afffa0b5090 | True |  | 4 passed in 0.08s |
| J1-20-release-causation-from-correlation | mutated run: exit=1 (1.1s) | services/billing/tests/unit/test_credit_release_service.py:154 | AssertionError: a field of the credit.released.v1 fact is wrong | 9afffa0b5090 | True |  | 4 passed in 0.08s |
| J1-21-hold-responder-required-correlation-bypassed | mutated run: exit=1 (2.0s) | services/billing/tests/unit/test_credit_responder.py:222 | AssertionError: billing.credit.hold: correlation malformed | 5225b5a8b1fb | True |  | 26 passed in 0.80s |
| J1-22-release-responder-required-correlation-bypassed | mutated run: exit=1 (2.0s) | services/billing/tests/unit/test_credit_responder.py:222 | AssertionError: billing.credit.release: correlation malformed | 5225b5a8b1fb | True |  | 26 passed in 0.82s |
| J1-23-handler-hold-calls-release | mutated run: exit=1 (12.0s) | python/services/billing/tests/integration/test_credit_hold.py:64 | AssertionError: assert 'rejected' == 'approved' | e164da730645 | True |  | 1 passed in 9.90s |
| J1-24-handler-release-delegation-replaced | mutated run: exit=1 (12.1s) | python/services/billing/tests/integration/test_credit_release.py:37 | AssertionError: assert False is True | e164da730645 | True |  | 1 passed in 10.36s |
| J1-25-handler-list-page-size-hardcoded | mutated run: exit=1 (13.1s) | python/services/billing/tests/integration/test_credit_list.py:94 | assert (2, 25, 4) == (2, 3, 4) | e164da730645 | True |  | 1 passed in 10.33s |
| J1-26-handler-list-filter-dropped | mutated run: exit=1 (12.6s) | python/services/billing/tests/integration/test_credit_list.py:84 | AssertionError: assert 4 == 1 | e164da730645 | True |  | 1 passed in 10.48s |


## 7. Search outputs

### D7 (countable claims)

```text
$ grep -n "with_for_update" services/billing/src/otc_billing/infrastructure/persistence/credit_reads.py
(exit: no output above means zero hits)

$ grep -rn "async def decide" services/billing/src
(no output above: zero hits)

$ grep -rnE "update\(|delete\(|on_conflict" services/billing/src/otc_billing
services/billing/src/otc_billing/infrastructure/outbox/relay.py:150:                            .with_for_update(skip_locked=True)
services/billing/src/otc_billing/infrastructure/outbox/relay.py:162:                            update(Outbox)
services/billing/src/otc_billing/infrastructure/persistence/range_guards.py:14:2's bulk insert), `update(Model)` (with `.where().values()` or bulk-by-primary-key), and
services/billing/src/otc_billing/infrastructure/persistence/credit_repository.py:6:1. the line row, ORM `select(Credit)...with_for_update()` (plain `FOR UPDATE`, not `key share`: it
services/billing/src/otc_billing/infrastructure/persistence/credit_repository.py:19:No `update(`, `delete(`, `on_conflict_*` or textual DML exists in this service: every row written is
services/billing/src/otc_billing/infrastructure/persistence/credit_repository.py:76:            .with_for_update()
```

Classification of each hit: `credit_repository.py:6` and `:19`: docstring prose naming `with_for_update()` / `update(`; `credit_repository.py:76`: the ORM `select(Credit)...with_for_update()` line lock (a read that locks, not a write); `range_guards.py:14`: docstring prose; `outbox/relay.py:150`: `with_for_update(skip_locked=True)` of the copied relay's claim (a read); `outbox/relay.py:162`: `update(Outbox)` stamping `published_at` (the parity-guarded copy; no guarded column). None writes a ledger or credit row. `credit_reads.py` has zero locks; no `async def decide` exists. The write-path population (`tests/architecture/test_write_path_population.py`, `EXPECTED["billing"]`, counts read from `scan_service("billing")`) classifies: `relay.py` execute 1 + update 1 (the copy's stamp), `writer.py` add 1 (guarded unit of work), `credit_reads.py` execute 1 (SELECT), `credit_repository.py` text 1 + execute 1 (the SELECT scalar) + add 1 (the guarded ledger row), `credit_responder.py` add 1 (`set.add`), `sequences.py` unchanged. Arm `D8-second-session-add` adds a second `session.add`: the count fails by name.

### H8 (BC32: every reply decode in Billing's tests, rooted at the decode)

```text
$ grep -rnE "from_wire_json|json\.loads|\.data\b" services/billing/tests
services/billing/tests/integration/test_credit_wire.py:4:bare `RpcError`. The reply is decoded with `json.loads` first (NO `response`, `isDisposed` or `id`
services/billing/tests/integration/test_credit_wire.py:16:from otc_contracts import from_wire_json
services/billing/tests/integration/test_credit_wire.py:32:    return bytes(reply.data)
services/billing/tests/integration/test_credit_wire.py:52:    hold = json.loads(await raw(client, "billing.credit.hold", hold_body, headers()))
services/billing/tests/integration/test_credit_wire.py:56:        from_wire_json(asyncapi.CreditHoldReplyPayload, json.dumps(hold).encode()).held_amount
services/billing/tests/integration/test_credit_wire.py:60:    released = json.loads(await raw(client, "billing.credit.release", release_body, headers()))
services/billing/tests/integration/test_credit_wire.py:64:        from_wire_json(asyncapi.CreditReleaseReplyPayload, json.dumps(released).encode()).released
services/billing/tests/integration/test_credit_wire.py:68:    listed = json.loads(await raw(client, "billing.credit.list", b"{}", None))
services/billing/tests/integration/test_credit_wire.py:71:    decoded = from_wire_json(asyncapi.CreditListReplyPayload, json.dumps(listed).encode())
services/billing/tests/integration/test_credit_wire.py:82:        error = json.loads(await raw(client, subject, body, hdrs))
services/billing/tests/integration/test_credit_wire.py:85:        decoded = from_wire_json(asyncapi.RpcError, json.dumps(error).encode())
services/billing/tests/integration/test_billing_outbox_relay.py:82:                    if json.loads(r.value)["correlationId"] == correlation_id
services/billing/tests/integration/test_billing_outbox_relay.py:144:    envelope = json.loads(record.value)
services/billing/tests/integration/conftest.py:30:from otc_contracts import from_wire_json
services/billing/tests/integration/conftest.py:239:        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]
services/billing/tests/integration/conftest.py:393:    parsed = json.loads(body) if isinstance(body, bytes) else body
services/billing/tests/integration/conftest.py:421:        parsed: dict[str, Any] = json.loads(reply.data)
services/billing/tests/integration/conftest.py:434:        return from_wire_json(asyncapi.RpcError, json.dumps(reply).encode())
services/billing/tests/integration/conftest.py:439:        return from_wire_json(asyncapi.CreditHoldReplyPayload, json.dumps(reply).encode())
services/billing/tests/integration/conftest.py:444:        return from_wire_json(asyncapi.CreditReleaseReplyPayload, json.dumps(reply).encode())
services/billing/tests/integration/conftest.py:450:        return from_wire_json(asyncapi.CreditListReplyPayload, json.dumps(reply).encode())
services/billing/tests/integration/test_billing_json_and_timestamps.py:22:from otc_contracts import from_wire_json, to_wire_json
services/billing/tests/integration/test_billing_json_and_timestamps.py:36:    raw = json.loads(GOLDEN.read_text(encoding="utf-8"))["payload"]
services/billing/tests/integration/test_billing_json_and_timestamps.py:38:    model = from_wire_json(InvoiceIssuedPayload, json.dumps(raw, ensure_ascii=False))
services/billing/tests/integration/test_billing_json_and_timestamps.py:59:    keys = list(json.loads(payload))
services/billing/tests/unit/test_credit_responder.py:27:from otc_contracts import from_wire_json
services/billing/tests/unit/test_credit_responder.py:53:        self.data = data
services/billing/tests/unit/test_credit_responder.py:199:    return from_wire_json(RpcError, reply)
services/billing/tests/unit/test_credit_responder.py:247:    assert "code" not in json.loads(reply)
services/billing/tests/unit/test_credit_wire.py:19:from otc_contracts import from_wire_json
services/billing/tests/unit/test_credit_wire.py:24:    parsed: dict[str, Any] = json.loads(credit_wire.encode(model))
services/billing/tests/unit/test_credit_wire.py:170:    decoded = from_wire_json(asyncapi.CreditListReplyPayload, payload)
services/billing/tests/unit/test_outbox_payloads.py:82:    parsed: dict[str, Any] = json.loads(to_wire_json(payload))  # type: ignore[arg-type]
services/billing/tests/unit/test_credit_requests.py:22:from otc_contracts import from_wire_json
services/billing/tests/unit/test_credit_requests.py:170:    assert from_wire_json(CreditHoldRequestPayload, enc(hold(orderReference=twenty_one)))
services/billing/tests/unit/test_credit_requests.py:176:    assert from_wire_json(CreditHoldRequestPayload, negative)
services/billing/tests/unit/test_credit_requests.py:203:        self.data = data
services/billing/tests/unit/test_credit_requests.py:235:    error = from_wire_json(RpcError, reply)
```

One classification per hit (discriminating field asserted first, line cited):

- `unit/test_credit_wire.py:19, 24, 170`: encodes a locally built model and reads the bytes back (not a received reply); each test asserts its own `outcome` / `released` / `page` before using any other key.
- `integration/conftest.py:30, 434, 439, 444, 450` (`Decode`): each decoder asserts its discriminating field BEFORE `from_wire_json` or any collection: `code` (`:433`), `outcome` (`:438`), `released` (`:443`), `page` and `page.total` (`:448-449`).
- `integration/conftest.py:239, 393`: outbox rows read from SQL and a request body in the cents-rule guard (not replies). `:421`: the `rpc` helper returns the parsed dict untouched (no key access); every test reads it through `Decode`.
- `integration/test_credit_wire.py:4, 16, 32, 52-85`: each `json.loads` is followed by a `"outcome" in` / `"released" in` / `"page" in` / `"code" in` assertion carrying the reply in its message (`:53, :61, :69, :83`) before the generated model is built.
- `integration/test_billing_json_and_timestamps.py:22, 36, 38, 59`: phase 6's golden file and a stored payload (not replies).
- `integration/test_billing_outbox_relay.py:82, 144`: Kafka record values (facts), selected by envelope `correlationId`, key asserted separately.
- `unit/test_credit_responder.py:27, 53, 199, 247`: `FakeMessage.data` (request side); `error_of` builds `RpcError` (its required `code` is the discriminating field and each caller asserts `.code` first); `:247` asserts the ABSENCE of `code`.
- `unit/test_credit_requests.py:22, 170, 176, 203, 235`: request models, `FakeMessage.data`, and `from_wire_json(RpcError, reply)` followed at once by `error.code`.
- `unit/test_outbox_payloads.py:82`: serialisation of a locally built payload.

Arms (both seen red): the list route answers an `RpcError` and the test fails on `BC32: expected a list reply (a \`page\`), got {...}` (the field is named); with the assertion moved after the collection access the same reply fails on `KeyError: 'items'` (the shape BC32 forbids).

### J1 (feature 17's rejection class: every call site of a hand-built seam)

Enumeration (`grep -rnE "lock_for_order|\.save\(|evaluate_hold|\.approve\(|\.refuse\(|\.release\(|\.consume\(|\.decide\(|to_rejection_reason|required_correlation|summarise\(|scope\.ids\.new|scope\.clock\.now" services/billing/src`), minus docstrings and imports, gave these call sites: `credit_reads.py:70` summarise; `buyer_credit.py:227, 230` summarise; `buyer_credit.py:257` evaluate_hold (inside approve); `credit_hold.py:46` lock_for_order, `:56` evaluate_hold, `:74` decide, `:86` approve, `:87` save, `:98` to_rejection_reason, `:99` refuse, `:100` save, `:116` clock.now, `:117` ids.new; `credit_release.py:28` lock_for_order, `:33` release, `:49` save, `:64` clock.now, `:65` ids.new; `credit_responder.py:62, 73` required_correlation; `handlers.py` three delegations. `consume` has zero call sites in `src` (feature 21 calls it; domain-tested). The mutation per site and its killer:

- `J1-01-credit_reads-summarise-deleted`: killed by `test_bc6_every_listed_line_reconciles_to_its_credit_limit`
- `J1-02-aggregate-summary-property`: killed by `test_r37_keeps_active_holds_plus_open_exposure_within_the_credit_limit_and_raises_on_any_update_or_deletion_of_a_ledger_entry`
- `J1-03-order-exposure-other-order`: killed by `test_a_negative_exposure_in_a_loaded_ledger_is_refused_by_a_release`, `test_bc11_releases_the_outstanding_exposure_once_and_reports_a_no_op_on_a_second_release`, `test_bc12_consume_leaves_available_credit_unchanged_emits_no_fact_and_refuses_an_order_with_no_active_hold`
- `J1-04-approve-skips-evaluate-hold`: killed by `test_approve_refuses_an_over_limit_amount_by_its_own_evaluation`, `test_every_refused_call_leaves_the_snapshot_and_the_events_unchanged`, `test_r37_keeps_active_holds_plus_open_exposure_within_the_credit_limit_and_raises_on_any_update_or_deletion_of_a_ledger_entry`
- `J1-05-hold-lock-for-order-args-swapped`: killed by `test_r38_an_approved_hold_appends_one_hold_row_and_emits_one_credit_approved_v1`
- `J1-06-hold-lock-for-order-order-reference-swapped`: killed by `test_an_approved_hold_saves_once_and_replies_with_the_amounts`
- `J1-07-hold-evaluate-hold-deleted`: killed by `test_a_missing_line_and_a_currency_mismatch_are_contract_violations_that_save_nothing`, `test_bc13_the_port_is_consulted_only_for_a_fitting_hold_and_never_for_an_over_limit_one`, `test_bc36_the_hold_hands_the_scope_id_port_to_the_domain`
- `J1-08-hold-decide-deleted`: killed by `test_bc13_the_port_is_consulted_only_for_a_fitting_hold_and_never_for_an_over_limit_one`, `test_bc14_a_port_refusal_records_exactly_one_credit_rejected_fact_on_the_saved_aggregate`, `test_bc14_the_port_refusal_reason_is_the_ports_not_a_sibling`
- `J1-09-hold-approve-deleted`: killed by `test_an_approved_hold_saves_once_and_replies_with_the_amounts`, `test_bc36_the_hold_hands_the_scope_id_port_to_the_domain`
- `J1-10-hold-approve-id-port-bypassed`: killed by `test_bc36_the_hold_hands_the_scope_id_port_to_the_domain`
- `J1-11-hold-save-after-approve-deleted`: killed by `test_an_approved_hold_saves_once_and_replies_with_the_amounts`, `test_bc36_the_hold_hands_the_scope_id_port_to_the_domain`, `test_the_reply_comes_only_after_run_returns_and_a_rollback_yields_no_reply`
- `J1-12-hold-refuse-id-port-bypassed`: killed by `test_bc14_a_port_refusal_records_exactly_one_credit_rejected_fact_on_the_saved_aggregate`, `test_bc36_the_hold_hands_the_scope_id_port_to_the_domain`
- `J1-13-hold-clock-now-replaced`: killed by `test_bc14_a_port_refusal_records_exactly_one_credit_rejected_fact_on_the_saved_aggregate`
- `J1-14-hold-causation-from-correlation`: killed by `test_bc14_a_port_refusal_records_exactly_one_credit_rejected_fact_on_the_saved_aggregate`
- `J1-15-release-lock-for-order-args-swapped`: killed by `test_bc25_one_release_entry_and_one_released_fact_then_released_false_writing_nothing_on_a_repeat`
- `J1-16-release-reason-sibling`: killed by `test_a_release_with_outstanding_exposure_records_exactly_one_release_entry_and_one_released_fact`
- `J1-17-release-correlation-from-request-id`: killed by `test_a_release_with_outstanding_exposure_records_exactly_one_release_entry_and_one_released_fact`
- `J1-18-release-save-deleted`: killed by `test_a_release_with_outstanding_exposure_records_exactly_one_release_entry_and_one_released_fact`, `test_bc36_the_release_hands_the_scope_id_port_to_the_domain`
- `J1-19-release-clock-now-replaced`: killed by `test_a_release_with_outstanding_exposure_records_exactly_one_release_entry_and_one_released_fact`
- `J1-20-release-causation-from-correlation`: killed by `test_a_release_with_outstanding_exposure_records_exactly_one_release_entry_and_one_released_fact`
- `J1-21-hold-responder-required-correlation-bypassed`: killed by `test_bc1_hold_and_release_refuse_the_remaining_header_faults`, `test_bc1_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_is_missing_or_malformed`, `test_bc1_the_command_carries_the_correlation_and_request_ids_from_the_headers`
- `J1-22-release-responder-required-correlation-bypassed`: killed by `test_bc1_hold_and_release_refuse_the_remaining_header_faults`, `test_bc1_replies_validation_failed_and_dispatches_nothing_when_a_correlation_or_request_header_is_missing_or_malformed`
- `J1-23-handler-hold-calls-release`: killed by `test_r38_an_approved_hold_appends_one_hold_row_and_emits_one_credit_approved_v1`
- `J1-24-handler-release-delegation-replaced`: killed by `test_bc25_one_release_entry_and_one_released_fact_then_released_false_writing_nothing_on_a_repeat`
- `J1-25-handler-list-page-size-hardcoded`: killed by `test_the_list_filters_and_pages_at_sql_level`
- `J1-26-handler-list-filter-dropped`: killed by `test_the_list_filters_and_pages_at_sql_level`

The already-armed sites are cited in the main table: `credit_hold.py:98` (`C3-refuse-wrong-reason`), `:99` (`C3-delete-refuse-on-port-branch`), `:100` (`C3-delete-save-on-refusal`), `:117` (`C3-uniqueid-new-instead-of-scope-ids`), `credit_release.py:65` (`C4-uniqueid-new-instead-of-scope-ids`), the repository's three reads (`I1-*`, `I2-*`, `I4-*`). **No site lacked a killing test, so no test was added by this sweep.** Feature 17's three survivors are covered: a lock method's read order (I1 scalar-before-lock, I2 entries-before-lock), the id port at the application to domain seam (C3, C4, J1-10, J1-12), a refusal branch (C3 delete-`refuse`, H3 no-outbox-row).

## 8. Live boot (BC20; tasks K1 - K5)

Stack: `docker ps` before: `otcpy-n8n Up 50 seconds (health: starting)`; started `postgres nats kafka` with `docker compose -p otcpy -f docker-compose.infra.yml start postgres nats kafka` (healthy). Hosts: `uvicorn otc_fulfillment.main:app --port 8102`, `otc_billing.main:app --port 8103`, `otc_orders.main:app --port 8101` (`/health/ready` 200 on all three). Raw outputs: `.arm/bc19/live/`.

### K1 pre-state

```text
== K1 pre-state, 2026-10-09T06:51:22+02:00
                  id                  | order_reference |     status     |  retailer   |  company  | total_amount | cur 
--------------------------------------+-----------------+----------------+-------------+-----------+--------------+-----
 223c1406-1fd8-45c8-99c5-88a738720414 | ORD-000007      | stock_reserved | CarrefourEs | IBERFOODS |        55545 | EUR
 b7117514-a2a0-49e5-a41f-bab72062b246 | ORD-000008      | stock_reserved | CarrefourEs | IBERFOODS |        99996 | EUR
(2 rows)

 order_reference |    command    | status | attempts |      next_attempt_at       |                  id                  |                                     last_error                                      
-----------------+---------------+--------+----------+----------------------------+--------------------------------------+-------------------------------------------------------------------------------------
 ORD-000007      | credit.hold   | parked |       12 | 2026-10-08 14:32:44.25+00  | 37a3ed86-d3c1-459d-bc9b-e1e36d28860b | billing.credit.hold: no responder is subscribed to billing.credit.hold.
 ORD-000007      | stock.reserve | sent   |        6 |                            | bccaadb5-0354-4f91-b2bd-482a8ef26edb | fulfillment.stock.reserve: no responder is subscribed to fulfillment.stock.reserve.
 ORD-000008      | credit.hold   | parked |       12 | 2026-10-08 14:32:44.248+00 | 5f3bceaa-2c9e-4320-8b65-71c2870dc731 | billing.credit.hold: no responder is subscribed to billing.credit.hold.
 ORD-000008      | stock.reserve | sent   |        0 |                            | 70e5aa5f-c4e9-4857-a52c-c6de0ae82c58 | 
(4 rows)

 saga_commands_total | parked 
---------------------+--------
                   4 |      2
(1 row)

   code    | retailer_code | company_code | credit_limit | currency_code 
-----------+---------------+--------------+--------------+---------------
 CR-000001 | CarrefourEs   | IBERFOODS    |       500000 | EUR
(1 row)

 credits_rows 
--------------
          154
(1 row)

   code    | order_reference |  type   | amount 
-----------+-----------------+---------+--------
 CR-000001 | ORD-000001      | consume |  16130
 CR-000001 | ORD-000001      | hold    |  16130
 CR-000001 | ORD-000001      | release |  16130
(3 rows)

 credit_items_total | holds 
--------------------+-------
                 15 |     5
(1 row)

 outbox_rows 
-------------
          21
(1 row)

 order_reference | product_code | units |  status  
-----------------+--------------+-------+----------
 ORD-000007      | PRD-0001     |     2 | consumed
 ORD-000007      | PRD-0002     |     3 | consumed
 ORD-000008      | PRD-0001     |     4 | reserved
(3 rows)

 despatch_reference | order_reference 
--------------------+-----------------
 DES-000001         | ORD-000001
 DES-000002         | ORD-000002
 DES-000003         | ORD-000003
 DES-000004         | ORD-000004
 DES-000005         | ORD-000005
 DES-000006         | ORD-000007
(6 rows)
```

The state is the one `design.md` section 14 describes (both `credit.hold` rows `parked`, attempts 12; `CR-000001` ledger nets to zero; `ORD-000007` already despatched in Fulfillment).

### K2 the unattended boot (hosts started 06:51:2x; first holds at 04:51:45Z)

Within one sweeper interval of starting Orders (the last host), with no operator action: both orders gained exactly one `hold` row and one `credit.approved.v1`, stamped published; `ORD-000008` reached `despatched` (`despatch.create` answered, `DES-000007`) and `invoice.issue` parked; `ORD-000007` stopped at `confirmed` (expected, `design.md` 14). Each fact's `correlation_id` equals `otc_orders.orders.id` and its `causation_id` equals that order's `credit.hold` `saga_commands.id` (both read from the two databases below).

```text
== K2 evidence 2026-10-09T06:52:13+02:00
 order_reference | type | amount |        credit_date         |   code    
-----------------+------+--------+----------------------------+-----------
 ORD-000007      | hold |  55545 | 2026-10-09 04:51:45.558+00 | CR-000001
 ORD-000008      | hold |  99996 | 2026-10-09 04:51:45.554+00 | CR-000001
(2 rows)

     event_type     |            correlation_id            |             causation_id             |             aggregate_id             | published |        occurred_at         |                                                                                      payload                                                                                      
--------------------+--------------------------------------+--------------------------------------+--------------------------------------+-----------+----------------------------+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 credit.approved.v1 | b7117514-a2a0-49e5-a41f-bab72062b246 | 5f3bceaa-2c9e-4320-8b65-71c2870dc731 | 5c62308c-31fd-47ab-aa6f-a27cc545a36e | t         | 2026-10-09 04:51:45.554+00 | {"orderReference":"ORD-000008","retailerCode":"CarrefourEs","companyCode":"IBERFOODS","creditCode":"CR-000001","currency":"EUR","heldAmount":99996,"availableCreditAfter":400004}
 credit.approved.v1 | 223c1406-1fd8-45c8-99c5-88a738720414 | 37a3ed86-d3c1-459d-bc9b-e1e36d28860b | 5c62308c-31fd-47ab-aa6f-a27cc545a36e | t         | 2026-10-09 04:51:45.558+00 | {"orderReference":"ORD-000007","retailerCode":"CarrefourEs","companyCode":"IBERFOODS","creditCode":"CR-000001","currency":"EUR","heldAmount":55545,"availableCreditAfter":344459}
(2 rows)

 outbox_total | unpublished 
--------------+-------------
           23 |           0
(1 row)

                  id                  | order_reference 
--------------------------------------+-----------------
 223c1406-1fd8-45c8-99c5-88a738720414 | ORD-000007
 b7117514-a2a0-49e5-a41f-bab72062b246 | ORD-000008
(2 rows)

 order_reference |           hold_command_id            
-----------------+--------------------------------------
 ORD-000007      | 37a3ed86-d3c1-459d-bc9b-e1e36d28860b
 ORD-000008      | 5f3bceaa-2c9e-4320-8b65-71c2870dc731
(2 rows)

 order_reference |     command     | status | attempts 
-----------------+-----------------+--------+----------
 ORD-000007      | credit.hold     | sent   |       12
 ORD-000007      | despatch.create | sent   |        0
 ORD-000007      | stock.reserve   | sent   |        6
 ORD-000008      | credit.hold     | sent   |       12
 ORD-000008      | despatch.create | sent   |        0
 ORD-000008      | invoice.issue   | parked |        3
 ORD-000008      | stock.reserve   | sent   |        0
(7 rows)

-- billing log
INFO:     Started server process [267286]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8103 (Press CTRL+C to quit)
INFO:     127.0.0.1:59386 - "GET /health/ready HTTP/1.1" 200 OK
```

`billing.credit.list` through raw NATS equals the hand computation:

```text
== billing.credit.list (CarrefourEs / IBERFOODS) 2026-10-09T06:52:21+02:00
{"items":[{"creditCode":"CR-000001","retailerCode":"CarrefourEs","companyCode":"IBERFOODS","currency":"EUR","creditLimit":500000,"activeHolds":155541,"openExposure":0,"availableCredit":344459}],"page":{"page":1,"pageSize":25,"total":1}}
hand: 500000 - 99996 - 55545 = 344459
```

Billing logs no request lines (structured logging is feature 27); the evidence is the databases.

### K3 a genuine over-limit order, no simulator bound

```text
== K3 2026-10-09T06:52:27+02:00: 15 x 24999 = 374985 > remaining 344459; total % 100 = 85
{"orderId":"c8a96a35-b360-4965-a92a-4c379ac81dca","orderReference":"ORD-000009","status":"placed","currency":"EUR","initialAmount":374985,"initialDiscount":0,"totalAmount":374985,"orderDate":"2026-10-09T04:52:27.333Z"}
 order_reference |  status   | cancellation_reason | total_amount 
-----------------+-----------+---------------------+--------------
 ORD-000009      | cancelled | credit_rejected     |       374985
(1 row)

    command    | status | attempts 
---------------+--------+----------
 credit.hold   | sent   |        0
 stock.release | sent   |        0
 stock.reserve | sent   |        0
(3 rows)

 credit_items_rows_for_it 
--------------------------
                        0
(1 row)

     event_type     |                                                                                                 payload                                                                                                  
--------------------+----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 credit.rejected.v1 | {"orderReference":"ORD-000009","retailerCode":"CarrefourEs","companyCode":"IBERFOODS","creditCode":"CR-000001","currency":"EUR","requestedAmount":374985,"availableCredit":344459,"reason":"over_limit"}
(1 row)

 order_reference | product_code | units |  status  
-----------------+--------------+-------+----------
 ORD-000009      | PRD-0001     |    15 | released
(1 row)

    event_type     | pub 
-------------------+-----
 stock.reserved.v1 | t
 stock.released.v1 | t
(2 rows)
```

### K4 release over raw NATS (throwaway `ORD-000090`, never `ORD-000007` / `ORD-000008`)

```text
== K4 2026-10-09T06:52:59+02:00 throwaway ORD-000090, correlation d9d4c3eb-fbc1-4fb9-bf5c-6820bde4fdf2
-- hold
{"outcome":"approved","orderReference":"ORD-000090","creditCode":"CR-000001","currency":"EUR","heldAmount":1000,"availableCredit":343459}
-- release #1
{"released":true,"orderReference":"ORD-000090","creditCode":"CR-000001","currency":"EUR","releasedAmount":1000,"availableCreditAfter":344459}
  type   | amount 
---------+--------
 hold    |   1000
 release |   1000
(2 rows)

     event_type     | caused_by_release_request | pub |                                                                                                     payload                                                                                                     
--------------------+---------------------------+-----+-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
 credit.approved.v1 | f                         | t   | {"orderReference":"ORD-000090","retailerCode":"CarrefourEs","companyCode":"IBERFOODS","creditCode":"CR-000001","currency":"EUR","heldAmount":1000,"availableCreditAfter":343459}
 credit.released.v1 | t                         | t   | {"orderReference":"ORD-000090","retailerCode":"CarrefourEs","companyCode":"IBERFOODS","creditCode":"CR-000001","currency":"EUR","releasedAmount":1000,"availableCreditAfter":344459,"reason":"order_cancelled"}
(2 rows)

-- release #2 (repeat)
{"released":false,"orderReference":"ORD-000090","creditCode":"CR-000001","currency":"EUR","availableCreditAfter":344459}
 ledger_rows 
-------------
           2
(1 row)

 facts 
-------
     2
(1 row)
```

### K5 teardown and the register of known-altered live fixtures

Hosts stopped with `kill -TERM` of the three server PIDs (`.arm/bc19/live/server.pids`; each logged `Application shutdown complete`); `pgrep -af "uvicorn otc_"` empty, ports 8101 - 8103 free; `docker compose -p otcpy -f docker-compose.infra.yml stop kafka nats postgres`; `docker ps` after: `otcpy-n8n Up 3 minutes (healthy)`.

Fixtures this walkthrough CHANGED in the developer databases (recreate them to repeat the walkthrough):

- `otc_billing`: `credit_items` + 4 rows (`ORD-000007` hold 55 545, `ORD-000008` hold 99 996, `ORD-000090` hold 1 000 and release 1 000); `outbox` 21 -> 26 rows (all published); line `CR-000001` now has 155 541 of active holds (available credit 344 459).
- `otc_orders`: `ORD-000007` `stock_reserved` -> `confirmed` (it stops there by design); `ORD-000008` -> `despatched` with `invoice.issue` `parked`; new order `ORD-000009` `cancelled` / `credit_rejected` (15 x `PRD-0001`, 374 985 EUR); `saga_commands` 4 -> 10 rows.
- `otc_fulfillment`: `DES-000007` for `ORD-000008`; `ORD-000008`'s reservation `consumed`; `ORD-000009`'s 15-unit reservation `released`; stock `IBERFOODS` `PRD-0001` 494 / 0, `PRD-0002` 492 / 0.
- `order_number_sequences` advanced for `ORD-000009`; the Kafka topics carry the new facts; `otcpy-n8n` untouched.

State after:

```text
== K5 final fixture state 2026-10-09T06:53:15+02:00
 order_reference |   status   | cancellation_reason 
-----------------+------------+---------------------
 ORD-000007      | confirmed  | 
 ORD-000008      | despatched | 
 ORD-000009      | cancelled  | credit_rejected
(3 rows)

 saga_commands_total 
---------------------
                  10
(1 row)

 credit_items_total | holds | outbox_total 
--------------------+-------+--------------
                 19 |     8 |           26
(1 row)

 order_reference |  type   | amount 
-----------------+---------+--------
 ORD-000007      | hold    |  55545
 ORD-000008      | hold    |  99996
 ORD-000090      | hold    |   1000
 ORD-000090      | release |   1000
(4 rows)

 despatch_reference | order_reference 
--------------------+-----------------
 DES-000006         | ORD-000007
 DES-000007         | ORD-000008
(2 rows)

 product_code | units | reserved_units 
--------------+-------+----------------
 PRD-0001     |   494 |              0
 PRD-0002     |   492 |              0
(2 rows)

 unpublished 
-------------
           0
(1 row)
```

## 9. Inherited findings (`design.md` section 17), avoided or recurred

One recurred in round 1 and is fixed in round 2: **#7 W3 / N5 and #8 D3 (a fact field whose corruption survives the suite)** recurred as review D1 (U8, U9, U10: the release path's `availableCreditAfter`, fact and both replies, could be the credit limit with the suite green); see § Round 2. The review's reading of #9 feature 17's class (surviving call-site mutations) as recurred is also accepted. The other rows below were avoided.

| Finding | Disposition | Guard |
|---|---|---|
| #8 id 49 (the id port at every site) | avoided | B6 six per-site arms; C3 / C4 application seams; J1-10, J1-12 |
| #8 id 50 (shutdown rethrew) | avoided | `_drain` with `return_exceptions=True`; E7 three arms |
| #8 id 51 (retyped key lists) | avoided by construction | generated models; reply key sets in `test_credit_wire.py` (F3 arms) |
| #8 id 53 / 55, A6 (reply-shape assertions that only throw) | avoided | `Decode`, H8 enumeration and both arms |
| #8 id 54 (un-hinted in-transaction re-read) | avoided | D4 (isolation read back), I1 three arms including `REPEATABLE READ` |
| #8 id 56 / 67 / 68 (composition-root env reads, wiring) | avoided | G1 - G5: env-reads guard, per-variable settings test, the reach test (pool, client id, NATS URL, database URL, poll interval), registration case by case |
| #8 id 63 (unpaced readiness loops) | avoided | the host is reachable when `start()` returns (`flush()` armed in E8) |
| #8 id 76 / 83 (layering) | avoided | `layers-billing` import-linter contract; `application` imports no `otc_contracts` |
| #8 id 85 (container ports) | avoided | root `conftest.py` fixtures (Docker-held ports); the suites pass with the stack down |
| #8 id 87 / 111 (relay classification, poison row) | avoided | the parity guard keeps the copy identical (F6, 11 arms) |
| #8 id 102 (problem money text) | avoided | `BC39`, E6 raw-amount arm |
| #8 id 57 (completion pair has no causal edge) | assigned to feature 22 | `release` takes the caller's `CreditContext` |
| #7 D1 (port refusal emitted no fact) | avoided | C3 delete-`refuse` arm; H3 with a refusing port bound |
| #7 W3 / N5, #8 D3 (payload corruption, identity fields) | **RECURRED in round 1 (review D1), fixed in round 2** for the release path's `availableCreditAfter`; avoided elsewhere | B8, C3, C4, H2, H3, H5 corruption arms; round 2: U8, U9, U10 now red |
| #7 N1 (`already_held` vs currency precedence) | avoided | `BC26`, B8 arm |
| #8 D1 (prescribed mutation never run) | avoided | every prescribed mutation was run; D6 reads through the mapper |
| #8 D4 (malformed `x-request-id`) | avoided | E5 eight cases, two arms |
| #8 A1 (empty client id) | avoided | `BC34` in three services, G2 three arms, G3 |
| #9 feature 17 (three surviving mutations) | **recurred in round 1 as U8/U9/U10** (result fields built after a `release(` call, not covered by J1's call-site enumeration), fixed in round 2 | task J1 above (26 call-site arms); round 2: the three arms |

## 10. Not done, and why

Nothing in `tasks.md` is unticked. The structured-log, trace and deadline features (27) are out of scope by the spec; Billing logs no per-request line.

## 11. `git status --porcelain` against the file list of `tasks.md` (L3)

```text
 M .env.example
 M feature_list.json
 M progress/current.md
 M services/billing/pyproject.toml
 M services/billing/src/otc_billing/infrastructure/settings.py
 M services/billing/src/otc_billing/presentation/app.py
 M services/billing/tests/integration/conftest.py
 M services/fulfillment/src/otc_fulfillment/infrastructure/settings.py
 M services/fulfillment/tests/unit/test_fulfillment_settings_env.py
 M services/orders/src/otc_orders/infrastructure/settings.py
 M services/orders/tests/unit/test_orders_settings_env.py
 M specs/shared/test-matrix.md
 M tests/architecture/test_composition_env_reads.py
 M tests/architecture/test_kafka_client_confinement.py
 M tests/architecture/test_outbox_copy_parity.py
 M tests/architecture/test_registration_behaviour.py
 M tests/architecture/test_write_path_population.py
 M uv.lock
?? progress/brief_impl_billing_credit.md
?? progress/brief_spec_billing_credit.md
?? progress/impl_billing_credit.md
?? progress/premise_billing_credit_spec.md
?? progress/premise_impl_billing_credit.md
?? progress/spec_billing_credit.md
?? services/billing/src/otc_billing/application/credit_hold.py
?? services/billing/src/otc_billing/application/credit_release.py
?? services/billing/src/otc_billing/application/errors.py
?? services/billing/src/otc_billing/application/handlers.py
?? services/billing/src/otc_billing/application/messages.py
?? services/billing/src/otc_billing/application/ports/
?? services/billing/src/otc_billing/application/scope.py
?? services/billing/src/otc_billing/composition.py
?? services/billing/src/otc_billing/domain/buyer_credit.py
?? services/billing/src/otc_billing/domain/credit_entry_type.py
?? services/billing/src/otc_billing/domain/errors.py
?? services/billing/src/otc_billing/domain/events.py
?? services/billing/src/otc_billing/domain/exposure.py
?? services/billing/src/otc_billing/domain/ledger_entry.py
?? services/billing/src/otc_billing/domain/reasons.py
?? services/billing/src/otc_billing/domain/snapshot.py
?? services/billing/src/otc_billing/infrastructure/clock.py
?? services/billing/src/otc_billing/infrastructure/credit/
?? services/billing/src/otc_billing/infrastructure/ids.py
?? services/billing/src/otc_billing/infrastructure/messaging/
?? services/billing/src/otc_billing/infrastructure/outbox/
?? services/billing/src/otc_billing/infrastructure/persistence/credit_mapper.py
?? services/billing/src/otc_billing/infrastructure/persistence/credit_reads.py
?? services/billing/src/otc_billing/infrastructure/persistence/credit_repository.py
?? services/billing/src/otc_billing/infrastructure/persistence/credit_transactions.py
?? services/billing/src/otc_billing/main.py
?? services/billing/src/otc_billing/presentation/credit_headers.py
?? services/billing/src/otc_billing/presentation/credit_responder.py
?? services/billing/src/otc_billing/presentation/credit_rpc_errors.py
?? services/billing/src/otc_billing/presentation/credit_wire.py
?? services/billing/tests/integration/test_billing_host_lifespan.py
?? services/billing/tests/integration/test_billing_outbox_relay.py
?? services/billing/tests/integration/test_credit_hold.py
?? services/billing/tests/integration/test_credit_hold_race.py
?? services/billing/tests/integration/test_credit_list.py
?? services/billing/tests/integration/test_credit_release.py
?? services/billing/tests/integration/test_credit_repository.py
?? services/billing/tests/integration/test_credit_responder_concurrency.py
?? services/billing/tests/integration/test_credit_wire.py
?? services/billing/tests/unit/domain/
?? services/billing/tests/unit/test_always_approve.py
?? services/billing/tests/unit/test_billing_settings_env.py
?? services/billing/tests/unit/test_cents_rule_fixture_guard.py
?? services/billing/tests/unit/test_credit_decision_port.py
?? services/billing/tests/unit/test_credit_hold_service.py
?? services/billing/tests/unit/test_credit_mapper.py
?? services/billing/tests/unit/test_credit_release_service.py
?? services/billing/tests/unit/test_credit_requests.py
?? services/billing/tests/unit/test_credit_responder.py
?? services/billing/tests/unit/test_credit_rpc_errors.py
?? services/billing/tests/unit/test_credit_subjects.py
?? services/billing/tests/unit/test_credit_transactions.py
?? services/billing/tests/unit/test_credit_wire.py
?? services/billing/tests/unit/test_fact_topic.py
?? services/billing/tests/unit/test_outbox_payloads.py
?? specs/billing_credit/
?? tests/architecture/test_billing_rpc_error_retryability.py
?? tests/architecture/test_kafka_client_ids.py
```

Walk: every path under `services/billing/**` is on the "may touch" list (the new files are exactly those of `design.md` section 2, section 10 - 13; `presentation/app.py` and `integration/conftest.py` are the two modified ones; `services/billing/pyproject.toml` and `uv.lock` are task A3); `services/orders/src/otc_orders/infrastructure/settings.py` and `services/fulfillment/src/otc_fulfillment/infrastructure/settings.py` changed in the `client_id` field only, and the two settings tests in the empty/blank cases only; the five edited and two new files under `tests/architecture/` are the named ones; `.env.example` is the two variables; `specs/shared/test-matrix.md` is column 5 of `R37` - `R41` plus the two count lines; `specs/billing_credit/` holds the spec (untracked since the gate) with `requirements.md` section 3.2 and `tasks.md` ticks edited; `feature_list.json` changed on feature 19's status line only (`git diff` shows `pending` -> `in_review` against HEAD; the leader's intermediate `in_progress` was never committed). `progress/current.md` and the `progress/brief_*`, `premise_*`, `spec_*` files were the leader's and are untouched by me. Nothing outside the list changed; `models.py`, `range_guards.py`, `types.py`, `sequences.py`, `alembic/`, `packages/`, the root `pyproject.toml` and `services/orders/tests/unit/test_idempotent_consumer_parity.py` are unchanged.

## Round 2 (fix round after `review_billing_credit.md` round 1, REJECTED)

Test files only (`services/billing/tests/**`, `tests/architecture/test_outbox_copy_parity.py`); no production file changed (`git diff` of `services/billing/src` is round 1's). Arm tooling, backups with sha256 and verbatim logs: `.arm/bc19r2/` (`arm.py`, `arm_multi.py`, `logs/<arm>.log`, `bak/`). Every armed file restored by `cp`, `cmp` equal and sha256 equal (printed per arm), `__pycache__` cleared after each. The developer stack stayed down (`docker ps`: `otcpy-n8n` only, before and after).

### Result

`./quality.sh` exit 0, 366 s, **3 154 passed** (round 1: 3 111; +43 = 42 new parity sentinel cases + 1 new `summarise` case), ruff format/check clean, mypy --strict 551 files clean, import-linter 11 kept 0 broken, coverage 97.42 % overall / 99 % domain. `./init.sh` exit 0.

### D1: release fixtures with a second order's exposure

The aggregate loads only its own order's entries and takes the line's committed exposure as a scalar, so "another order's hold" is the scalar's extra part in the unit tests and a planted `credit_items` row in the integration tests.

| Fixture | limit | other order | before the release | after (hand value) | not equal to |
|---|---|---|---|---|---|
| `test_credit_ledger.py::test_r41_…` (both reasons) and `::test_bc11_…` | 1 000 | 400 (committed 650 = 250 + 400) | 350 | **600** | limit 1 000, before 350 |
| `test_credit_release_service.py` released case | 1 000 | 400 | 350 | **600** (fact and reply) | 1 000, 350 |
| `test_credit_release_service.py` no-op cases (never held; already released) | 1 000 | 400 (committed 400) | 600 | **600** | 1 000 |
| `integration/test_credit_release.py::test_bc25_…` | 100 000 | `ORD-000202` hold 30 000 (planted) | 65 790 | **70 000** (reply, outbox payload, repeat) | 100 000, 65 790 |
| `…::test_a_release_of_an_order_that_was_never_held_is_released_false` | 100 000 | 30 000 planted | 70 000 | **70 000** | 100 000 |

BC11's domain test also asserts the fact's `available_credit_after == 600`. R41's test name is unchanged, so `test-matrix.md` is unchanged.

Arms (the review's U10, U9, U8 verbatim; logs `U10-fact-available-is-limit.log`, `U9-released-true-reply-available-is-limit.log`, `U8-noop-reply-available-is-limit.log`):

| Arm | Mutation | Red in | Message (verbatim) | Green after restore |
|---|---|---|---|---|
| U10 | `buyer_credit.py:377` `available_credit_after=self._credit_limit.amount` | `test_r41_…` and `test_bc25_…` (2 failed) | `AssertionError: a field of the credit.released.v1 payload is wrong … {'availableCreditAfter': 100000} != {'availableCreditAfter': 70000}` | 2 passed |
| U9 | `credit_release.py:56` `credit.credit_limit.amount` | service released case and `test_bc25_…` (2 failed) | `assert (4210, 100000) == (4210, 70000)` (integration); `assert (250, 1000) == (250, 600)` (service) | 2 passed |
| U8 | `credit_release.py:47` `credit.credit_limit.amount` | service no-op case and the never-held integration case (2 failed) | `assert 1000 == 600 … ReleaseResult(released=False, …available_credit_after=1000)`; `assert 100000 == 70000 … CreditReleaseReplyPayload(released=False, …)` | 2 passed |

### D2: the parity guard compares the whole file outside the docstring span

`split_docstring` now returns `Parts(preamble, docstring, closing_tail, body)`. The preamble must equal `PREAMBLE_ALLOWED[(service, rel)]` (an exact literal, empty by default; only Billing's `wire.py` and `writer.py` hold the one `# ruff: noqa: I001 - …` line); the closing line may carry nothing after the quotes (`end_col_offset`, sliced as UTF-8 bytes); the docstring must still name the canonical. The instrument's docstring was corrected and lists premises P1 – P4.

Sentinels, parametrised over both services: code after the closing quotes (relay, wire); the same after non-ASCII text on the line (P4); three non-listed lines before the docstring (`# ruff: noqa: E402`, `# type: ignore`, `# ruff: noqa: I001`); a second line in an allow-listed file; the listed directive in an unlisted file; the listed directive missing (wire, writer: defeat row 7); the pristine tree (already existing) still passes.

Arms: `Q1-code-on-docstring-line-plus-file-noqa` (the review's, on the real Billing `relay.py`): RED, message `billing's outbox copies differ from Orders': ["infrastructure/outbox/relay.py: the lines before the docstring are '# ruff: noqa: E402 - the copy keeps the canonical layout\\n', the allow-list holds ''", 'infrastructure/outbox/relay.py: text follows the docstring\'s closing quotes: \'; HIDDEN = __import__("logging").disable()  # noqa: E702  # fmt: skip\'']`; green after restore (88 passed). Instrument arms (mutating the parity test, restored and green): drop the preamble check, 12 failed; preamble `not in` instead of `!=`, 10 failed (`…allow_listed_directive_in_a_file_that_is_not_listed_fails[fulfillment]`, `…second_line…[billing]`); drop the tail check, 6 failed; slice by characters (P4), first run SURVIVED (my sentinel's tail `; X = 1` was longer than the byte/char shift), then the sentinel was changed to three non-ASCII characters with the two-character tail `;0` and the arm is RED (2 failed: `…non_ascii_text_on_the_line[billing]`, `[fulfillment]`). Lesson recorded: a shift detector needs a tail shorter than the shift.

### D3: the census recognises what a module declares

`declares_outbox_table` is an AST scan (not a text match) of every `.py` under `services/*/src/otc_*/infrastructure/**` for an `Assign` / `AnnAssign` to `__tablename__` or a `Table(...)` call whose first argument is `"outbox"` or a same-module string constant. Premises P5 – P7 are in the docstring. A second, independent instrument is a behaviour test: `test_the_scan_agrees_with_what_the_persistence_modules_declare_once_imported` imports every real `persistence` module and reads the `MetaData` tables; its owners must equal the scan's.

**A surprise the wider instrument found:** `services/seed/src/otc_seed/infrastructure/tables.py` declares a Core `Table("outbox", …)` (a hand-written mirror checked against the migrated databases by `schema_check`). The seed does not own the table, so `MIRRORS_NOT_OWNERS = {"seed"}` (reason beside it) excludes it at the source, and the real-tree test asserts the scan still sees the seed (the exclusion cannot go stale). The round-1 text match missed it only because the seed has no `persistence/models.py`.

Sentinels: six spellings (literal, annotated, constant, annotated constant, `Table(...)`, `sa.Table(...)`) x three modules (`models.py`, `outbox_models.py`, `sub/tables.py`) = 18 cases, each fails the census naming `['notifications']`; five mentions that declare nothing (docstring, comment, triple-quoted string, `outbox_archive`, an unrelated constant) are not owners (defeat rows 4, 6); the pristine three-service tree passes; the literal `["billing", "fulfillment", "orders"]` population assertion stays.

Arms: the four forms of §4 D3 by reverting the census to the old text match (`I-census-back-to-text-match`): 15 failed, 3 passed (the three literal-form cases still pass, as they must), e.g. `…every_spelling…[sub/tables.py-core table, qualified-…]` red. `F6-fourth-service-outbox-table` (the review's `['notifications']` arm: Notifications' `__tablename__ = "outbox"`): RED, `["services owning an `outbox` table without the relay family: ['notifications'] (listed: ['billing', 'fulfillment', 'orders'])"]` in both the census test and the behaviour cross-check. `I-drop-mirror-exclusion` (a sibling service added to the exclusion): RED in the cross-check.

### N1 – N3

- **N1:** `test_credit_exposure.py::test_bc30_raises_ledger_overflow_when_the_hold_total_exceeds_int64_though_the_exposure_does_not`: holds `2**62 + 1` twice and a release of 3 (exposure lands on `INT64_MAX`, so only the hold-total check can raise), asserting the message names `hold ledger total of order ORD-000101`. Arm R9a (`exposure.py` hold accumulation unchecked): RED, `Failed: BC30: summarise returned a total outside int64 instead of raising: committed_exposure=9223372036854775807`; 12 passed after restore.
- **N2:** `test_credit_repository.py::test_bc24_…` now carries `BC24: read back …, offset …, not UTC` on the `utcoffset()` assertion. Arm `D6-mine-mapper-aware-local` (`entry_date=row.credit_date.astimezone()`): RED, `AssertionError: BC24: read back 2026-10-08 11:30:15.123000+02:00, offset 2:00:00, not UTC`.
- **N3:** accepted, not changed: fixing the sentence-as-token message needs a production change (the repository or the error's constructor), which the round's bounds forbid; the message is cosmetic and the error code and type are guarded. Re-open trigger: any change to `credit_repository.py:63-66`.

### §9 and §6

§9 corrected above (the "None recurred" line, the #7 W3 / N5 / #8 D3 row, and the feature 17 row now say recurred in round 1, fixed in round 2). The round-2 arms above are the additions to § 6 (F6 and D1 rows); the 141 round-1 arms were not re-run wholesale, only the ones whose path round 2 changed (F6 parity, D6).

### Not done

Nothing in the review's §8 items 1 – 5 is undone. Item 6 (backlog entry 213) is the leader's. Feature 19 is `in_review` (that one line of `feature_list.json`).

## Review round 2 findings (R2-1 – R2-3)

Light, test-only; the only file touched is `tests/architecture/test_outbox_copy_parity.py` (88 tests before, 94 after).

- **R2-1:** `violations()` now requires each canonical's `preamble == ""` and a blank `closing_tail`, failing with `<rel>: the canonical (orders) has lines before its docstring ...` / `... text after its docstring's closing quotes ...`. Sentinel `test_sentinel_r2_1_the_canonical_with_a_preamble_or_a_tail_fails_naming_orders_and_the_module` (service x {preamble, tail}). Docstring updated.
- **R2-2 (a):** `test_the_scan_agrees_with_what_the_infrastructure_modules_declare_once_imported` (renamed) imports `infrastructure/**/*.py` minus `__init__.py`, the scan's own population; P6 updated. Consequence: the import now reaches the seed's Core mirror, so the assertion is `declared - MIRRORS_NOT_OWNERS == owners` plus `declared & MIRRORS_NOT_OWNERS == MIRRORS_NOT_OWNERS` (the exclusion stays live).
- **R2-3:** `test_sentinel_r2_3_a_comment_only_tail_on_the_closing_line_fails_naming_the_file` (both copy services). The directive text is built with an f-string so ruff does not read the test's own source as a directive.
- **Arms** (backups in `.arm/bc19r2f/`, sha256 recorded, restored by `cp` + `cmp`, caches cleared): D2h RED (`the canonical (orders) has lines before its docstring`); D2i RED (both the preamble and the `closing quotes` messages, naming `infrastructure/outbox/relay.py`); D3g RED (`declared` held `notifications`, `owners` did not; new `messaging/` dir deleted, absence confirmed); IM1 (tail check ignoring `#`) RED, 2 failed (the R2-3 sentinel, both services). All restored; 94 passed. `ruff check`, `ruff format --check`, `mypy` clean on the file.
