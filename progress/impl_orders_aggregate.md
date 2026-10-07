# Implementation report — `orders_aggregate` (feature 13)

Status set to `in_review`. Full group (money domain). One implementer, no git writes, no commit.

## 1. What was built

- **OP-1 (the kernel):** `otc_shared_kernel/money_text.py` (`format_money`, moved unchanged from the seed), exported from `__init__`; the seed's copy deleted and its two importers (`sagas.py`, `test_money_text.py`) now import from the kernel; the fourteen vectors ported to `packages/shared_kernel/tests/test_money_text.py` (the seed's copy of the vectors stays, as `tasks.md` 1.7 changes only its import line).
- **Domain (`services/orders/src/otc_orders/domain/`):** `errors.py` (twelve errors), `instants.py` (`require_utc`), `value_objects/{order_status,cancellation_reason,compensation_step}.py`, `state_machine.py` (`Edge`, `LEGAL_EDGES`, `is_legal`), `order_line.py`, `totals.py`, `snapshot.py`, `events.py`, `order.py` (`Order` with `place`, `rehydrate`, eight transitions + `cancel`, `add_line`/`remove_line`/`change_line`, `_transition_to`, `_commit_lines`). `domain/__init__.py` and `value_objects/__init__.py` untouched.
- **Instruments:** `ALLOWED_ROOTS` gained `"enum"` (docstring census updated: 46 files, `enum` in the root list); `EXPECTED["orders"]` gained `"domain/totals.py": Counter({("call", "add"): 3})`, count read from the scan; `test_kernel_surface.py` `MODULE_NAMES` gained `money_text` and `format_money`.
- **Tests:** 121 pure domain tests in `services/orders/tests/unit/domain/` (11 files + `conftest.py`), 6 contract-parity tests, 14 kernel `format_money` cases.
- `specs/shared/test-matrix.md`: Status cell (column 5) of R5 – R10 flipped to `DONE`, the two coverage-count lines updated (feature 1: 9 / 1 / 0; total 9 / 1 / 53; 9+1+53 = 63). Nothing else in `specs/shared/`.
- `specs/orders_aggregate/tasks.md`: all 73 boxes ticked. `feature_list.json`: feature 13 `in_review` (that line only).

## 2. Files touched

New: `packages/shared_kernel/src/otc_shared_kernel/money_text.py`, `packages/shared_kernel/tests/test_money_text.py`; `services/orders/src/otc_orders/domain/{errors,events,instants,order,order_line,snapshot,state_machine,totals}.py`, `domain/value_objects/{order_status,cancellation_reason,compensation_step}.py`; `services/orders/tests/unit/domain/{conftest,test_domain_tests_are_pure,test_order,test_order_cancellation,test_order_errors,test_order_events,test_order_instants,test_order_rehydration,test_order_state_machine,test_order_structure,test_order_totals,test_order_vocabulary}.py`; `services/orders/tests/unit/test_order_domain_contract_parity.py`.
Edited: `packages/shared_kernel/src/otc_shared_kernel/__init__.py`, `packages/shared_kernel/tests/test_kernel_surface.py`, `services/seed/src/otc_seed/domain/data/sagas.py`, `services/seed/tests/unit/test_money_text.py`, `tests/architecture/test_money_guard.py`, `tests/architecture/test_write_path_population.py`, `specs/shared/test-matrix.md` (column 5 + counts), `specs/orders_aggregate/tasks.md` (ticks), `feature_list.json` (feature 13 status). Deleted: `services/seed/src/otc_seed/domain/money_text.py`.
Temporarily touched and restored byte-identically (arming): `packages/shared_kernel/src/otc_shared_kernel/entity.py` (arm 4.15, `cmp` identical). A throwaway `application/_probe.py` was created and deleted (arm 3.14b; `git status` shows nothing under `application/`).

## 3. Requirement to test (R5 – R10)

| R | Test (file) |
|---|---|
| R5 | `test_r5_order_refuses_to_create_an_order_with_no_lines_and_to_remove_the_last_remaining_line` (`test_order.py`) |
| R6 | `test_r6_order_recomputes_initial_amount_initial_discount_and_total_amount_after_each_mutation`, `test_r6_order_rejects_a_mutation_whose_resulting_total_amount_would_be_negative_and_leaves_the_order_unchanged` (add and change), `test_r6_place_refuses_a_negative_total`, `test_r6_a_total_of_exactly_zero_is_allowed` (`test_order_totals.py`) |
| R7 | `test_r7_order_refuses_to_add_remove_or_modify_a_line_once_the_order_is_confirmed_and_leaves_every_field_unchanged` (six statuses, one-line order), `test_r7_lines_are_mutable_exactly_in_placed_stock_reserved_and_credit_approved` (`test_order.py`) |
| R8 | `test_r8_order_walks_every_legal_edge_of_table_t1`, `test_r8_order_reaches_cancelled_only_from_placed_stock_reserved_credit_approved_and_confirmed`, `test_r8_order_treats_completed_and_cancelled_as_terminal` (`test_order_state_machine.py`); T-1 itself: `test_legal_edges_are_exactly_the_eleven_status_to_status_edges_of_table_t1`, `test_table_t1_parsed_from_the_specification_equals_the_transcription` |
| R9 | `test_r9_order_raises_on_every_from_to_pair_absent_from_table_t1_without_mutating_state_or_appending_an_event` (72 / 11 / 61 as literals) |
| R10 | `test_r10_order_requires_a_reason_from_the_closed_set_records_it_immutably_and_carries_it_on_order_cancelled_v1`, `test_r10_order_raises_when_no_cancellation_reason_is_supplied_and_does_not_change_the_status`, `test_r10_order_refuses_a_cancellation_reason_table_t1_does_not_pair_with_the_current_status`, plus SA-2 `test_sa2_*` (two) and the parse tests |

O8 (`test_o8_*`), R12's aggregate half (`test_r12_order_stamps_*`) and the other design guards are named in `tasks.md` and exist under those names.

## 4. Ported-idiom ledger: the guard that executes each row (design.md section 2)

| Row | Guard that ran | Differs from `design.md` section 2? |
|---|---|---|
| L1, L2, L3 | `test_order_vocabulary.py` token tests, `test_the_vocabularies_are_enums_not_str_subclasses`, `test_parse_is_exact_...`; parity file (both directions); arms 2.2a-e, 2.3, 4.10 | no |
| L4, L5 | `test_private_state_has_exactly_the_literal_writers`, `test_no_domain_module_refers_to_setattr_or_dunder_setattr`, `test_public_state_has_no_setter_and_nothing_outside_the_class_reaches_private_state`; arms 3.13a-d, 3.14a, 3.14b | no |
| L6 | the two T-1 tests; arms 2.5a-c, 4.3, 4.4 | no |
| L7 | `match` + `assert_never` exists in one place, `_sources_for(reason)` (reason pairing), checked by `mypy --strict`; the other tables are `frozenset` literals compared with spec literals (R7 lists, T-1) | **Narrower**: only one `match` exists, because only the reason pairing dispatches over a closed set. The status freeze is the allow-list `LINES_MUTABLE_IN`, guarded by 3.18/3.19 |
| L8 | `test_lines_are_a_tuple_...`, `test_events_are_frozen_and_hold_tuples_...`, `test_no_domain_dataclass_has_a_list_field_...`; arms 3.12, 4.13a/b | **The arm differs**, see section 6 item 3 |
| L9 | `test_an_overflowing_total_is_refused_and_leaves_the_order_unchanged`; arm 3.11 | no |
| L10 | existing AST money guard over every new domain file (green) | no |
| L11 | `test_every_write_path_in_the_service_is_a_classified_literal[orders]`; arm 1.3 | no |
| L12 | `test_r10_order_raises_when_no_cancellation_reason_is_supplied_...`; arms 4.7, 4.7b | no |
| L13 | `test_every_instant_parameter_refuses_...` (+ the literal 13-parameter population test), `test_rehydrate_refuses_a_naive_or_non_utc_instant`; arms 3.15, 5.9a-c | no |
| L14 | none owed | no |
| L15 | `test_rehydrate_orders_lines_by_ascending_line_id` (ids chosen so decimal-string order differs from integer order); arms 5.11, 5.11b | no |
| L16 | `test_rehydrate_derives_the_three_totals_...` (literal field set); arm 5.3 | no |
| L17 | one test per check (5.4 - 5.10c), table in section 5 | no |
| L18 | `test_events_are_frozen_...`; arm 4.13b | no |
| L19 | `test_order_event_is_the_union_of_exactly_the_four_event_classes`; arm 4.13c | no |
| L20 | none owed (no `async def`, no third-party import; the allow-list is structural) | no |
| L21 | `test_place_generates_a_fresh_order_id_and_fresh_line_ids_inside_the_domain`; arm 3.5 | no |

## 5. Arming (CLAUDE.md protocol: `cp` backup, one mutation, the named tests, verbatim failure, restore from backup, `cmp`, clear `__pycache__` and `.mypy_cache`, re-run green)

All 87 table rows below were produced by one script that records the outcome of each step (`armed result` is pytest's own summary line; `restore cmp` is `filecmp` against the backup; every re-run was after clearing caches). Arms with a mutated second file (4.13a) restore both. Not one arm survived.

### 5.1 Arms run by hand (before the script)

| Task | Mutation | Test | Verbatim result | Restore |
|---|---|---|---|---|
| 1.2 (a) | `"enum"` in `ALLOWED_ROOTS`, no domain file importing it yet | `test_the_import_allowlist_is_the_census_derived_from_the_real_population` | `AssertionError: allow-list not in the census: unused=['enum'] missing=[]` | edit kept (this is the intended final state) |
| 1.2 (b) | domain imports `enum`, `"enum"` removed from `ALLOWED_ROOTS` | same | `AssertionError: allow-list not in the census: unused=[] missing=['enum']` | `cp` backup, `cmp` ok |
| 1.3 | one more `a.add(b)` in `totals.py` | `test_every_write_path_in_the_service_is_a_classified_literal[orders]` | message contains `'domain/totals.py': Counter({('call', 'add'): 4})` against the expected 3 | `cp` backup, `cmp` ok |
| 1.5 | new kernel module `money_text.py` before `MODULE_NAMES` was edited | `test_the_kernel_module_population_is_the_literal_list` | `AssertionError: a kernel module was added or removed: +['money_text'] -[]` | the edit is the fix |
| 1.6 | exponent forced to a constant 2 in `format_money` | `test_format_money_is_exponent_scaled_and_grouped` | 3 failed, 11 passed: the JPY, KWD and CLF cases | `cp` backup, `cmp` ok |
| 3.14b | throwaway `application/_probe.py` with `return order._status` | `test_public_state_has_no_setter_and_nothing_outside_the_class_reaches_private_state` | `AssertionError: private aggregate state reached from outside `self`: {'application/_probe.py': [2]}` | file deleted, test green |
| 6.3 | `from otc_contracts.facts import FACT_MODELS` in `events.py` | `lint-imports` (stated, not assumed) | `Contracts: 9 kept, 1 broken.` ... `otc_orders.domain is not allowed to import pydantic: otc_orders.domain.events -> otc_contracts.facts (l.14) -> otc_contracts.wire -> pydantic`. **It names pydantic, not `otc_contracts`**: the AST guard (arm 6.3a below) is the one that names the wire package | `cp` backup, `cmp` ok, `Contracts: 10 kept, 0 broken.` |

### 5.2 Arms run by the script

| Arm | Task | Mutation | Test(s) run | Armed result | Verbatim failure (first claim-naming line) | Restore `cmp` | Re-run |
|---|---|---|---|---|---|---|---|
| 2.2a | 2.2 | STOCK_RESERVED value changed to 'stockreserved' | `test_order_status_tokens_are_exactly_the_nine_of_the_specification`<br>`test_domain_tokens_equal_the_generated_contract_enums_both_ways` | 3 failed, 3 passed in 0.22s | `AssertionError: assert {'cancelled',...nvoiced', ...} == {'cancelled',...nvoiced', ...}` | identical | exit 0: 6 passed in 0.21s |
| 2.2b | 2.2 | tenth member ON_HOLD = 'on_hold' added to OrderStatus | `test_order_status_tokens_are_exactly_the_nine_of_the_specification`<br>`test_domain_tokens_equal_the_generated_contract_enums_both_ways` | 3 failed, 3 passed in 0.23s | `AssertionError: OrderStatus has tokens the contract lacks: {'on_hold'}` | identical | exit 0: 6 passed in 0.26s |
| 2.2c | 2.2 | OrderStatus made a StrEnum | `test_the_vocabularies_are_enums_not_str_subclasses` | 1 failed, 2 passed in 0.03s | `AssertionError: assert not True` | identical | exit 0: 3 passed in 0.02s |
| 2.2d | 2.2 (reason, step) | CancellationReason value 'credit_rejected' -> 'credit_reject'; CompensationStepKind 'credit_released' -> 'credit_release' | `test_cancellation_reason_tokens_are_exactly_the_three_of_the_specification`<br>`test_domain_tokens_equal_the_generated_contract_enums_both_ways` | 3 failed, 3 passed in 0.24s | `AssertionError: assert {'credit_reje...ock_rejected'} == {'credit_reje...ock_rejected'}` | identical | exit 0: 6 passed in 0.21s |
| 2.2e | 2.2 (step) | CompensationStepKind CREDIT_RELEASED value changed | `test_compensation_step_kinds_are_exactly_the_two_of_the_specification`<br>`test_domain_tokens_equal_the_generated_contract_enums_both_ways` | 2 failed, 4 passed in 0.31s | `AssertionError: assert {'credit_rele...ock_released'} == {'credit_rele...ock_released'}` | identical | exit 0: 6 passed in 0.29s |
| 2.3 | 2.3 | parse_order_status looks up token.strip().lower() | `test_parse_is_exact_and_refuses_everything_outside_the_closed_set` | 3 failed, 4 passed in 0.03s | `Failed: DID NOT RAISE InvalidOrderSnapshotError` | identical | exit 0: 7 passed in 0.03s |
| 2.5a | 2.5 | delete Edge(CONFIRMED, CANCELLED) | `test_legal_edges_are_exactly_the_eleven_status_to_status_edges_of_table_t1`<br>`test_table_t1_parsed_from_the_specification_equals_the_transcription` | 1 failed, 1 passed in 0.03s | `AssertionError: assert 10 == 11` | identical | exit 0: 2 passed in 0.03s |
| 2.5b | 2.5 | add Edge(PLACED, CONFIRMED) | `test_legal_edges_are_exactly_the_eleven_status_to_status_edges_of_table_t1`<br>`test_every_pair_is_decided_by_is_legal_exactly_as_table_t1_says` | 2 failed in 0.04s | `AssertionError: assert 12 == 11` | identical | exit 0: 2 passed in 0.03s |
| 2.5c | 2.5 | substitute Edge(STOCK_RESERVED, CREDIT_APPROVED) -> Edge(STOCK_RESERVED, CONFIRMED) | `test_legal_edges_are_exactly_the_eleven_status_to_status_edges_of_table_t1` | 1 failed in 0.04s | `AssertionError: LEGAL_EDGES differs from Table T-1: missing=[('stock_reserved', 'credit_approved')] extra=[('stock_reserved', 'confirmed')]` | identical | exit 0: 1 passed in 0.04s |
| 3.5 | 3.5 | place reuses one module-level UniqueId for the order | `test_place_generates_a_fresh_order_id_and_fresh_line_ids_inside_the_domain` | 1 failed in 0.04s | `AssertionError: assert 7 == (6 + 2)` | identical | exit 0: 1 passed in 0.04s |
| 3.8 | 3.8 | delete the empty-candidate check in remove_line | `test_r5_order_refuses_to_create_an_order_with_no_lines_and_to_remove_the_last_remaining_line` | 1 failed in 0.04s | `Failed: DID NOT RAISE OrderMustHaveAtLeastOneLineError` | identical | exit 0: 1 passed in 0.03s |
| 3.8b | 3.8 | delete the empty-lines check in place | `test_r5_order_refuses_to_create_an_order_with_no_lines_and_to_remove_the_last_remaining_line` | 1 failed in 0.04s | `Failed: DID NOT RAISE OrderMustHaveAtLeastOneLineError` | identical | exit 0: 1 passed in 0.04s |
| 3.9 | 3.9 | add public def transition(self, target: OrderStatus) | `test_no_public_method_takes_an_order_status_and_none_targets_placed` | 1 failed in 0.03s | `AssertionError: a public method lets a caller name a target status: ['transition(target)']` | identical | exit 0: 1 passed in 0.03s |
| 3.10 | 3.10 | render the negative total with str(candidate_total) | `test_the_negative_total_message_renders_money_text_never_minor_units` | 1 failed in 0.03s | `AssertionError: assert 'The resultin...ve: -100 EUR.' == 'The resultin...e: -1.00 EUR.'` | identical | exit 0: 1 passed in 0.03s |
| 3.11 | 3.11 | add_line commits _lines before computing totals | `test_an_overflowing_total_is_refused_and_leaves_the_order_unchanged` | 1 failed in 0.04s | `AssertionError: assert (<OrderStatus...y='EUR'), ...) == (<OrderStatus...y='EUR'), ...)` | identical | exit 0: 1 passed in 0.03s |
| 3.12 | 3.12 | place stores a list (not a tuple) of lines | `test_lines_are_a_tuple_and_mutating_the_input_after_place_changes_nothing` | 1 failed in 0.04s | `assert False` | identical | exit 0: 1 passed in 0.06s |
| 3.13a | 3.13 | self._status = OrderStatus.PAID added to mark_invoiced | `test_private_state_has_exactly_the_literal_writers` | 1 failed in 0.04s | `AssertionError: private state is written by functions the design does not allow: _status: found ['__init__', '_transition_to', 'mark_invoiced'], allowed ['__init__', '_transition_to']` | identical | exit 0: 1 passed in 0.04s |
| 3.13b | 3.13 | reason assignment moved out of _transition_to into cancel | `test_private_state_has_exactly_the_literal_writers` | 1 failed in 0.04s | `AssertionError: private state is written by functions the design does not allow: _cancellation_reason: found ['__init__', 'cancel'], allowed ['__init__', '_transition_to']` | identical | exit 0: 1 passed in 0.04s |
| 3.13c | 3.13 (defeat row 11) | setattr(self, '_status', x) added to mark_paid | `test_private_state_has_exactly_the_literal_writers`<br>`test_no_domain_module_refers_to_setattr_or_dunder_setattr` | 1 failed, 1 passed in 0.05s | `AssertionError: setattr/__setattr__ in the domain (a write the AST cannot name): {'domain/order.py': [405]}` | identical | exit 0: 2 passed in 0.06s |
| 3.13d | 3.13 (defeat row 5) | a write to _lines hidden inside `if False:` in mark_paid | `test_private_state_has_exactly_the_literal_writers` | 1 failed in 0.04s | `AssertionError: private state is written by functions the design does not allow: _lines: found ['__init__', '_commit_lines', 'mark_paid'], allowed ['__init__', '_commit_lines']` | identical | exit 0: 1 passed in 0.04s |
| 3.14a | 3.14 | __slots__ removed from Order | `test_public_state_has_no_setter_and_nothing_outside_the_class_reaches_private_state` | 1 failed in 0.03s | `Failed: DID NOT RAISE AttributeError` | identical | exit 0: 1 passed in 0.05s |
| 3.15 | 3.15 | require_utc call deleted from complete | `test_every_instant_parameter_refuses_a_naive_or_non_utc_datetime` | 2 failed in 0.03s | `Failed: DID NOT RAISE InstantNotUtcError` | identical | exit 0: 2 passed in 0.03s |
| 3.16 | 3.16 | unlisted OrderStatusUnknownError added to errors.py | `test_the_orders_domain_error_population_is_the_literal_table` | 1 failed in 0.02s | `AssertionError: domain errors differ from design.md section 10: undeclared=[('OrderStatusUnknownError', 'order.status_unknown')] missing=[]` | identical | exit 0: 1 passed in 0.02s |
| 3.17a | 3.17 | line_discounts dropped from the initial_discount formula | `test_r6_order_recomputes_initial_amount_initial_discount_and_total_amount_after_each_mutation` | 1 failed in 0.04s | `assert (8465, 0, 8465) == (8465, 350, 8115)` | identical | exit 0: 1 passed in 0.03s |
| 3.17b | 3.17 | add_line assigns _lines before the sign check | `test_r6_order_rejects_a_mutation_whose_resulting_total_amount_would_be_negative_and_leaves_the_order_unchanged` | 1 failed, 1 passed in 0.03s | `AssertionError: assert (<OrderStatus...y='EUR'), ...) == (<OrderStatus...y='EUR'), ...)` | identical | exit 0: 2 passed in 0.04s |
| 3.17c | 3.17 | change_line assigns _lines before the sign check | `test_r6_order_rejects_a_mutation_whose_resulting_total_amount_would_be_negative_and_leaves_the_order_unchanged` | 1 failed, 1 passed in 0.03s | `AssertionError: assert (<OrderStatus...y='EUR'), ...) == (<OrderStatus...y='EUR'), ...)` | identical | exit 0: 2 passed in 0.04s |
| 3.17d | 3.17 | delete the sign check in place | `test_r6_place_refuses_a_negative_total` | 1 failed in 0.03s | `Failed: DID NOT RAISE OrderTotalMustNotBeNegativeError` | identical | exit 0: 1 passed in 0.03s |
| 3.18a | 3.18 | freeze check moved after the empty-candidate check in remove_line | `test_r7_order_refuses_to_add_remove_or_modify_a_line_once_the_order_is_confirmed_and_leaves_every_field_unchanged` | 6 failed in 0.06s | `otc_orders.domain.errors.OrderMustHaveAtLeastOneLineError: An order must have at least one line.` | identical | exit 0: 6 passed in 0.04s |
| 3.18b | 3.18 | CONFIRMED added to LINES_MUTABLE_IN | `test_r7_order_refuses_to_add_remove_or_modify_a_line_once_the_order_is_confirmed_and_leaves_every_field_unchanged` | 1 failed, 5 passed in 0.05s | `Failed: DID NOT RAISE OrderLinesAreFrozenError` | identical | exit 0: 6 passed in 0.05s |
| 3.19 | 3.19 | CREDIT_APPROVED removed from LINES_MUTABLE_IN | `test_r7_lines_are_mutable_exactly_in_placed_stock_reserved_and_credit_approved` | 1 failed in 0.04s | `otc_orders.domain.errors.OrderLinesAreFrozenError: The lines of an order in status 'credit_approved' can no longer be added, removed or changed.` | identical | exit 0: 1 passed in 0.03s |
| 3.20 | 3.20 | the line_discount currency comparison deleted from _require_line_currency | `test_o2_order_refuses_a_line_whose_price_or_discount_is_not_in_the_orders_currency` | 3 failed, 3 passed in 0.05s | `otc_shared_kernel.errors.CurrencyMismatchError: cannot combine or compare amounts in different currencies: 'EUR' and 'GBP'` | identical | exit 0: 6 passed in 0.04s |
| 3.20b | 3.20 | the unit_price currency comparison deleted from _require_line_currency | `test_o2_order_refuses_a_line_whose_price_or_discount_is_not_in_the_orders_currency` | 3 failed, 3 passed in 0.07s | `otc_shared_kernel.errors.CurrencyMismatchError: cannot combine or compare amounts in different currencies: 'EUR' and 'GBP'` | identical | exit 0: 6 passed in 0.05s |
| 3.21 | 3.21 (unmarked, armed anyway) | _find_line call deleted from remove_line | `test_remove_line_and_change_line_raise_line_not_found_for_an_unknown_line_id` | 1 failed in 0.04s | `Failed: DID NOT RAISE OrderLineNotFoundError` | identical | exit 0: 1 passed in 0.04s |
| 4.2 | 4.2 | mark_paid targets COMPLETED | `test_r8_order_walks_every_legal_edge_of_table_t1` | 1 failed in 0.03s | `otc_orders.domain.errors.IllegalOrderTransitionError: An order cannot move from 'invoiced' to 'completed': that edge is not in Table T-1.` | identical | exit 0: 1 passed in 0.04s |
| 4.3 | 4.3 | Edge(DESPATCHED, CANCELLED) added | `test_r8_order_reaches_cancelled_only_from_placed_stock_reserved_credit_approved_and_confirmed` | 1 failed in 0.04s | `otc_orders.domain.errors.CancellationReasonNotApplicableError: The cancellation reason 'operator_cancelled' does not apply to an order in status 'despatched'.` | identical | exit 0: 1 passed in 0.04s |
| 4.4 | 4.4 | Edge(COMPLETED, CANCELLED) added | `test_r8_order_treats_completed_and_cancelled_as_terminal` | 1 failed in 0.04s | `otc_orders.domain.errors.CancellationReasonNotApplicableError: The cancellation reason 'operator_cancelled' does not apply to an order in status 'completed'.` | identical | exit 0: 1 passed in 0.04s |
| 4.5a | 4.5 | self._status = target moved above the legality check | `test_r9_order_raises_on_every_from_to_pair_absent_from_table_t1_without_mutating_state_or_appending_an_event` | 1 failed in 0.04s | `otc_orders.domain.errors.IllegalOrderTransitionError: An order cannot move from 'stock_reserved' to 'stock_reserved': that edge is not in Table T-1.` | identical | exit 0: 1 passed in 0.05s |
| 4.5b | 4.5 | event raise moved above the legality check in _transition_to (confirm's path) | `test_r9_order_raises_on_every_from_to_pair_absent_from_table_t1_without_mutating_state_or_appending_an_event` | 1 failed in 0.05s | `AssertionError: placed -> confirmed changed the order` | identical | exit 0: 1 passed in 0.04s |
| 4.5c | 4.5 | updated_at stamped above the legality check | `test_r9_order_raises_on_every_from_to_pair_absent_from_table_t1_without_mutating_state_or_appending_an_event` | 1 failed in 0.04s | `AssertionError: placed -> credit_approved changed the order` | identical | exit 0: 1 passed in 0.05s |
| 4.6a | 4.6 | reason assignment moved from _transition_to to the line after the call in cancel (#8 A2) | `test_r10_order_requires_a_reason_from_the_closed_set_records_it_immutably_and_carries_it_on_order_cancelled_v1` | 6 failed in 0.04s | `otc_orders.domain.errors.InvalidOrderSnapshotError: The stored order cannot be restored: the cancellation reason was not recorded.` | identical | exit 0: 6 passed in 0.05s |
| 4.6b | 4.6 | event builder substitutes CREDIT_REJECTED for the recorded reason | `test_r10_order_requires_a_reason_from_the_closed_set_records_it_immutably_and_carries_it_on_order_cancelled_v1` | 5 failed, 1 passed in 0.05s | `AssertionError: assert <CancellationReason.CREDIT_REJECTED: 'credit_rejected'> is <CancellationReason.STOCK_REJECTED: 'stock_rejected'>` | identical | exit 0: 6 passed in 0.05s |
| 4.7 | 4.7 | the `reason is None` check deleted from cancel | `test_r10_order_raises_when_no_cancellation_reason_is_supplied_and_does_not_change_the_status` | 1 failed in 0.03s | `otc_orders.domain.errors.UnknownCancellationReasonError: None is not a cancellation reason: expected one of 'stock_rejected', 'credit_rejected', 'operator_cancelled'.` | identical | exit 0: 1 passed in 0.03s |
| 4.7b | 4.7 | the `type(reason) is not CancellationReason` check deleted from cancel | `test_r10_order_raises_when_no_cancellation_reason_is_supplied_and_does_not_change_the_status` | 1 failed in 0.04s | `AssertionError: Expected code to be unreachable, but got: 'operator_cancelled'` | identical | exit 0: 1 passed in 0.04s |
| 4.8a | 4.8 | credit_rejected pairing check deleted (allowed from all four sources) | `test_r10_order_refuses_a_cancellation_reason_table_t1_does_not_pair_with_the_current_status` | 3 failed, 3 passed in 0.04s | `Failed: DID NOT RAISE CancellationReasonNotApplicableError` | identical | exit 0: 6 passed in 0.04s |
| 4.8b | 4.8 | PLACED substituted for STOCK_RESERVED in the credit_rejected pairing | `test_r10_order_requires_a_reason_from_the_closed_set_records_it_immutably_and_carries_it_on_order_cancelled_v1`<br>`test_r10_order_refuses_a_cancellation_reason_table_t1_does_not_pair_with_the_current_status` | 2 failed, 10 passed in 0.05s | `otc_orders.domain.errors.CancellationReasonNotApplicableError: The cancellation reason 'credit_rejected' does not apply to an order in status 'stock_reserved'.` | identical | exit 0: 12 passed in 0.05s |
| 4.8c | 4.8 | stock_rejected pairing check deleted (allowed from all four sources) | `test_r10_order_refuses_a_cancellation_reason_table_t1_does_not_pair_with_the_current_status` | 3 failed, 3 passed in 0.04s | `Failed: DID NOT RAISE CancellationReasonNotApplicableError` | identical | exit 0: 6 passed in 0.05s |
| 4.9 | 4.9 | the note argument dropped from the OrderCancelled builder | `test_sa2_cancel_with_no_note_raises_order_cancelled_with_note_absent`<br>`test_sa2_cancel_with_a_note_raises_order_cancelled_carrying_the_exact_note_text` | 1 failed, 1 passed in 0.04s | `AssertionError: assert None == 'Cliente solicitó la anulación — pedido duplicado ✓'` | identical | exit 0: 2 passed in 0.03s |
| 4.10 | 4.10 | parse_cancellation_reason raises UnknownCancellationReasonError for the missing branch too | `test_r10_parse_cancellation_reason_raises_when_the_token_is_missing` | 3 failed in 0.04s | `otc_orders.domain.errors.UnknownCancellationReasonError: None is not a cancellation reason: expected one of 'stock_rejected', 'credit_rejected', 'operator_cancelled'.` | identical | exit 0: 3 passed in 0.03s |
| 4.11a | 4.11 | the event builder deleted from complete | `test_o8_order_appends_exactly_one_domain_event_for_each_fact_bearing_edge_of_table_t1` | 1 failed in 0.05s | `AssertionError: assert 2 == (2 + 1)` | identical | exit 0: 1 passed in 0.05s |
| 4.11b | 4.11 | place raises its event twice | `test_o8_order_appends_exactly_one_domain_event_for_each_fact_bearing_edge_of_table_t1` | 1 failed in 0.05s | `AssertionError: assert ['order.place...er.placed.v1'] == ['order.placed.v1']` | identical | exit 0: 1 passed in 0.05s |
| 4.11c | 4.11 | the event builder deleted from confirm | `test_o8_order_appends_exactly_one_domain_event_for_each_fact_bearing_edge_of_table_t1` | 1 failed in 0.05s | `AssertionError: assert 1 == (1 + 1)` | identical | exit 0: 1 passed in 0.05s |
| 4.11d | 4.11 | the event builder deleted from cancel | `test_o8_order_appends_exactly_one_domain_event_for_each_fact_bearing_edge_of_table_t1` | 1 failed in 0.05s | `AssertionError: <OrderStatus.PLACED: 'placed'>` | identical | exit 0: 1 passed in 0.05s |
| 4.12a | 4.12 | direct _raise_event added to mark_invoiced (row 6; #8 armed rows 2 and 5) | `test_o8_order_appends_no_domain_event_on_the_five_silent_edges_of_table_t1` | 1 failed in 0.05s | `assert (<object obje...7f13f93a470>,) == ()` | identical | exit 0: 1 passed in 0.05s |
| 4.12b | 4.12 | direct _raise_event added to mark_paid (row 7) | `test_o8_order_appends_no_domain_event_on_the_five_silent_edges_of_table_t1` | 1 failed in 0.05s | `assert (<object obje...dafb4c5a470>,) == ()` | identical | exit 0: 1 passed in 0.05s |
| 4.13a | 4.13 | OrderCancelled.compensation_steps typed list and the caller's list passed through | `test_events_are_frozen_and_hold_tuples_and_steps_are_copied`<br>`test_no_domain_dataclass_has_a_list_field_and_the_population_is_the_literal_set` | 2 failed in 0.05s | `AssertionError: assert False` | identical | exit 0: 2 passed in 0.05s |
| 4.13b | 4.13 | every event class declared frozen=False | `test_events_are_frozen_and_hold_tuples_and_steps_are_copied` | 1 failed in 0.05s | `Failed: DID NOT RAISE FrozenInstanceError` | identical | exit 0: 1 passed in 0.05s |
| 4.13c | 4.13 | a fifth member added to the OrderEvent union | `test_order_event_is_the_union_of_exactly_the_four_event_classes` | 1 failed in 0.05s | `AssertionError: assert {<class 'otc_...rPlacedLine'>} == {<class 'otc_...erCompleted'>}` | identical | exit 0: 1 passed in 0.05s |
| 4.14 | 4.14 | confirm sets correlation_id=causation_id | `test_r12_order_stamps_every_domain_event_with_a_fresh_event_id_the_order_id_as_correlation_id_and_the_supplied_causation_id` | 1 failed in 0.05s | `AssertionError: assert UniqueId(valu...fd982f0fd39')) == UniqueId(valu...ef61caacde7'))` | identical | exit 0: 1 passed in 0.06s |
| 4.14b | 4.14 | complete reuses the order id as event_id | `test_r12_order_stamps_every_domain_event_with_a_fresh_event_id_the_order_id_as_correlation_id_and_the_supplied_causation_id` | 1 failed in 0.05s | `AssertionError: an id was reused where a fresh one was owed` | identical | exit 0: 1 passed in 0.05s |
| 4.15 | 4.15 (unmarked, armed anyway) | kernel AggregateRoot.pull_domain_events no longer clears the list | `test_pull_domain_events_empties_the_pending_list_and_leaves_every_other_field_untouched` | 1 failed in 0.05s | `AssertionError: assert (OrderPlaced(... notes=None),) == ()` | identical | exit 0: 1 passed in 0.05s |
| 4.16 | 4.16 | OrderCompleted.EVENT_TYPE changed to 'order.complete.v1' | `test_order_event_types_are_all_declared_in_the_shared_fact_catalogue` | 1 failed in 0.24s | `AssertionError: assert {'order.cance...er.placed.v1'} <= {'credit.appr...eted.v1', ...}` | identical | exit 0: 1 passed in 0.29s |
| 5.2 | 5.2 | rehydrate raises an event | `test_rehydrate_restores_a_terminal_order_without_walking_the_state_machine_and_without_raising_any_event` | 1 failed in 0.03s | `assert (<object obje...a8bf396fd30>,) == ()` | identical | exit 0: 1 passed in 0.03s |
| 5.3 | 5.3 | a total_amount field added to OrderSnapshot | `test_rehydrate_derives_the_three_totals_from_the_lines_and_the_snapshot_has_no_totals_field` | 1 failed in 0.04s | `AssertionError: assert {'buyer_gln',...y', 'id', ...} == {'buyer_gln',...y', 'id', ...}` | identical | exit 0: 1 passed in 0.04s |
| 5.4 | 5.4 / 6.2 check 1 | load check 1 deleted | `test_rehydrate_refuses_a_status_that_is_not_an_order_status_member` | 1 failed in 0.03s | `Failed: DID NOT RAISE InvalidOrderSnapshotError` | identical | exit 0: 1 passed in 0.04s |
| 5.5 | 5.5 / 6.2 check 2 | load check 2 deleted | `test_rehydrate_refuses_a_cancellation_reason_that_is_not_a_member` | 1 failed in 0.04s | `Failed: DID NOT RAISE InvalidOrderSnapshotError` | identical | exit 0: 1 passed in 0.04s |
| 5.6 | 5.6 / 6.2 check 3 | load check 3 deleted | `test_rehydrate_refuses_cancelled_without_a_reason` | 1 failed in 0.03s | `Failed: DID NOT RAISE InvalidOrderSnapshotError` | identical | exit 0: 1 passed in 0.04s |
| 5.7 | 5.7 / 6.2 check 4 | load check 4 deleted | `test_rehydrate_refuses_a_reason_on_an_order_that_is_not_cancelled` | 1 failed in 0.03s | `Failed: DID NOT RAISE InvalidOrderSnapshotError` | identical | exit 0: 1 passed in 0.03s |
| 5.8 | 5.8 / 6.2 check 5 | load check 5 deleted | `test_rehydrate_refuses_an_empty_lines_collection` | 1 failed in 0.03s | `Failed: DID NOT RAISE OrderMustHaveAtLeastOneLineError` | identical | exit 0: 1 passed in 0.03s |
| 5.10a | 5.10a / 6.2 check 6 | load check 6 deleted (unit_price currency) | `test_rehydrate_refuses_a_line_whose_unit_price_is_not_in_the_orders_currency` | 1 failed in 0.04s | `AssertionError: assert 'money.cross_currency' == 'order.line_currency_mismatch'` | identical | exit 0: 1 passed in 0.04s |
| 5.10b | 5.10b / 6.2 check 7 | load check 7 deleted (line_discount currency) | `test_rehydrate_refuses_a_line_whose_line_discount_is_not_in_the_orders_currency` | 1 failed in 0.03s | `AssertionError: assert 'money.cross_currency' == 'order.line_currency_mismatch'` | identical | exit 0: 1 passed in 0.03s |
| 5.9 | 5.9 / 6.2 check 8 | load check 8 deleted for updated_at only | `test_rehydrate_refuses_a_naive_or_non_utc_instant` | 2 failed, 4 passed in 0.06s | `Failed: DID NOT RAISE InstantNotUtcError` | identical | exit 0: 6 passed in 0.05s |
| 5.9b | 5.9 / 6.2 check 8 | load check 8 deleted for order_date only | `test_rehydrate_refuses_a_naive_or_non_utc_instant` | 2 failed, 4 passed in 0.04s | `Failed: DID NOT RAISE InstantNotUtcError` | identical | exit 0: 6 passed in 0.04s |
| 5.9c | 5.9 / 6.2 check 8 | load check 8 deleted for created_at only | `test_rehydrate_refuses_a_naive_or_non_utc_instant` | 2 failed, 4 passed in 0.04s | `Failed: DID NOT RAISE InstantNotUtcError` | identical | exit 0: 6 passed in 0.04s |
| 5.10c | 5.10c / 6.2 check 9 | load check 9 deleted | `test_rehydrate_refuses_lines_whose_derived_total_is_negative` | 1 failed in 0.03s | `Failed: DID NOT RAISE OrderTotalMustNotBeNegativeError` | identical | exit 0: 1 passed in 0.03s |
| 5.11 | 5.11 | the sort deleted from rehydrate (constant key) | `test_rehydrate_orders_lines_by_ascending_line_id` | 1 failed in 0.05s | `AssertionError: assert [UniqueId(val...c5dea00000'))] == [UniqueId(val...8bbd400000'))]` | identical | exit 0: 1 passed in 0.03s |
| 5.11b | 5.11 | the sort keyed on the decimal string of the id | `test_rehydrate_orders_lines_by_ascending_line_id` | 1 failed in 0.03s | `AssertionError: assert [UniqueId(val...987b900000'))] == [UniqueId(val...8bbd400000'))]` | identical | exit 0: 1 passed in 0.03s |
| 6.2-1 | 6.2 | load check 1 deleted; whole domain suite | `domain`<br>`test_order_domain_contract_parity.py` | 1 failed, 126 passed in 0.70s | `Failed: DID NOT RAISE InvalidOrderSnapshotError` | identical | exit 0: 127 passed in 0.66s |
| 6.2-2 | 6.2 | load check 2 deleted; whole domain suite | `domain`<br>`test_order_domain_contract_parity.py` | 1 failed, 126 passed in 0.60s | `Failed: DID NOT RAISE InvalidOrderSnapshotError` | identical | exit 0: 127 passed in 0.68s |
| 6.2-3 | 6.2 | load check 3 deleted; whole domain suite | `domain`<br>`test_order_domain_contract_parity.py` | 1 failed, 126 passed in 0.66s | `Failed: DID NOT RAISE InvalidOrderSnapshotError` | identical | exit 0: 127 passed in 0.64s |
| 6.2-4 | 6.2 | load check 4 deleted; whole domain suite | `domain`<br>`test_order_domain_contract_parity.py` | 1 failed, 126 passed in 0.65s | `Failed: DID NOT RAISE InvalidOrderSnapshotError` | identical | exit 0: 127 passed in 0.76s |
| 6.2-5 | 6.2 | load check 5 deleted; whole domain suite | `domain`<br>`test_order_domain_contract_parity.py` | 1 failed, 126 passed in 0.58s | `Failed: DID NOT RAISE OrderMustHaveAtLeastOneLineError` | identical | exit 0: 127 passed in 0.63s |
| 6.2-6 | 6.2 | load check 6 deleted; whole domain suite | `domain`<br>`test_order_domain_contract_parity.py` | 1 failed, 126 passed in 0.75s | `AssertionError: assert 'money.cross_currency' == 'order.line_currency_mismatch'` | identical | exit 0: 127 passed in 0.71s |
| 6.2-7 | 6.2 | load check 7 deleted; whole domain suite | `domain`<br>`test_order_domain_contract_parity.py` | 1 failed, 126 passed in 0.62s | `AssertionError: assert 'money.cross_currency' == 'order.line_currency_mismatch'` | identical | exit 0: 127 passed in 0.62s |
| 6.2-8 | 6.2 | load check 8 deleted (all three instants); whole domain suite | `domain`<br>`test_order_domain_contract_parity.py` | 6 failed, 121 passed in 0.59s | `Failed: DID NOT RAISE InstantNotUtcError` | identical | exit 0: 127 passed in 0.66s |
| 6.2-9 | 6.2 | load check 9 deleted; whole domain suite | `domain`<br>`test_order_domain_contract_parity.py` | 1 failed, 126 passed in 0.63s | `Failed: DID NOT RAISE OrderTotalMustNotBeNegativeError` | identical | exit 0: 127 passed in 0.62s |
| 6.4 | 6.4 | import otc_contracts added to a domain test file | `test_domain_unit_tests_import_only_pytest_the_standard_library_the_kernel_and_the_orders_domain` | 1 failed in 0.04s | `AssertionError: domain unit tests may not import: {'test_order_errors.py': ['otc_contracts']}` | identical | exit 0: 1 passed in 0.05s |
| 6.3a | 6.3 | from otc_contracts.facts import FACT_MODELS added to events.py | `test_domain_and_shared_kernel_import_only_the_allowlist`<br>`test_money_guard_finds_no_violation_in_domain_or_shared_kernel` | 2 failed in 0.15s | `AssertionError: domain import allowlist: non-stdlib/non-kernel import in domain: {'services/orders/src/otc_orders/domain/events.py': ['line 14: from-import of `otc_contracts.facts` is outside the domain import allowlist']}` | identical | exit 0: 2 passed in 0.15s |

### 5.3 Task 6.2: each load check deleted alone, the whole suite run

| Check (design.md 8.2) | Deleted alone | Tests that fail (whole domain suite + parity file, 127 tests) | Result |
|---|---|---|---|
| 1 status is an OrderStatus | yes | `test_rehydrate_refuses_a_status_that_is_not_an_order_status_member` (1) | each killed by its own named test, and by no other |
| 2 reason is a CancellationReason | yes | `test_rehydrate_refuses_a_cancellation_reason_that_is_not_a_member` (1) | each killed by its own named test, and by no other |
| 3 O6: cancelled needs a reason | yes | `test_rehydrate_refuses_cancelled_without_a_reason` (1) | each killed by its own named test, and by no other |
| 4 O6: reason only when cancelled | yes | `test_rehydrate_refuses_a_reason_on_an_order_that_is_not_cancelled` (1) | each killed by its own named test, and by no other |
| 5 O1: at least one line | yes | `test_rehydrate_refuses_an_empty_lines_collection` (1) | each killed by its own named test, and by no other |
| 6 O2: unit_price currency | yes | `test_rehydrate_refuses_a_line_whose_unit_price_is_not_in_the_orders_currency` (1) | each killed by its own named test, and by no other |
| 7 O2: line_discount currency | yes | `test_rehydrate_refuses_a_line_whose_line_discount_is_not_in_the_orders_currency` (1) | each killed by its own named test, and by no other |
| 8 instants UTC (order_date, created_at, updated_at together) | yes | `test_rehydrate_refuses_a_naive_or_non_utc_instant[naive-created_at]`, `test_rehydrate_refuses_a_naive_or_non_utc_instant[naive-order_date]`, `test_rehydrate_refuses_a_naive_or_non_utc_instant[naive-updated_at]`, `test_rehydrate_refuses_a_naive_or_non_utc_instant[plus-one-hour-created_at]`, `test_rehydrate_refuses_a_naive_or_non_utc_instant[plus-one-hour-order_date]`, `test_rehydrate_refuses_a_naive_or_non_utc_instant[plus-one-hour-updated_at]` (6) | each killed by its own named test, and by no other |
| 9 O3: derived total not negative | yes | `test_rehydrate_refuses_lines_whose_derived_total_is_negative` (1) | each killed by its own named test, and by no other |

Every check is killed by its own named test and by no other; none is caught only by another check's test (#8's defect shape does not recur). Check 8 deletes the three instants together, which is why six cases (3 fields x 2 spellings) fail; deleting one instant alone is armed by 5.9, 5.9b and 5.9c (two cases each).

### 5.4 Defeat list (CLAUDE.md), by guard

| Row | Applies to | Where it is exercised |
|---|---|---|
| 1 delete the behaviour | every `[ARM]` task | arms 3.8, 4.11a/c/d, 5.4 - 5.10c |
| 2 corrupt a supplied field | event fields: wrong reason, wrong causation, wrong correlation | 4.6b, 4.14, 4.14b |
| 3 substitute a sibling identifier | the T-1 edge, the pairing, the token | 2.5c, 4.8b (`PLACED` for `STOCK_RESERVED`), 2.2a |
| 4 shadow the pattern in a comment or string | the writer scan (3.13) | sentinels `the name in a comment`, `the name in a string` must NOT count (`test_the_writer_scan_does_not_mistake_text_for_a_write`) |
| 5 hide in a dead region | the writer scan | sentinels `if False` and `if TYPE_CHECKING` must be seen; real-file arm 3.13d (`if False:` write in `mark_paid`) |
| 6 hide in a raw or triple-quoted string | the writer scan | sentinel `the name in a docstring` must NOT count. The inverse (a write hidden in a triple-quoted string) is not a write in Python, so nothing to detect |
| 7 drop an optional element | the SA-2 note | arm 4.9 |
| 8 compare a literal to a literal | T-1 and the token sets | each compares the code against a spec-transcribed literal; the T-1 literal is itself compared with the table parsed from `domain-model.md` (`test_table_t1_parsed_from_the_specification_equals_the_transcription`; not armed by editing the spec, see section 6 item 8) |
| 9 satisfy the closer half, leave the premise stale | the guard-order test (R7) | the test uses a one-line order; arm 3.18a fails with `order.must_have_at_least_one_line` |
| 10 build output joins the population | the writer/outside-access scans | they read `*.py` only (`__pycache__` holds `.pyc`); caches were cleared before every arm run |
| 11 a form the instrument does not recognise | the writer scan | `setattr(self, "_status", x)` and `object.__setattr__` sentinels; real-file arm 3.13c (`setattr` in `mark_paid`); the structural test is paired with a ban on any `setattr`/`__setattr__` reference in the domain |
| 12 a path the population never drives | a second status writer in a method no test calls | arm 3.13a (`self._status = ...` in `mark_invoiced`); the silent-edge guard was armed on rows 6 and 7 (`mark_invoiced`, `mark_paid`), neither of the two edges #8 used (#8 implementer: `MarkStockReserved`; #8 reviewer: `MarkDespatched`) |

## 6. Divergences from the spec, and things that surprised me

1. **Errors take string tokens, not enum members**: `IllegalOrderTransitionError(source: str, target: str)`, `OrderNotCancellableError(status: str)`, `OrderLinesAreFrozenError(status: str)`, `CancellationReasonNotApplicableError(reason: str, status: str)`. `errors.py` must not import `value_objects` because `parse_order_status` / `parse_cancellation_reason` (in `value_objects`) raise from `errors.py`; the aggregate passes `.value`. Codes and the twelve-class table are exactly `design.md` section 10.
2. **`Order.place` and `Order.__init__` signatures** were not spelled out in the design: `place(*, order_reference, order_date, retailer_code, buyer_gln, company_code, supplier_gln, currency, lines, notes, occurred_at, causation_id)` (as #8's `Place`, keyword-only); `__init__` is keyword-only with `order_id`.
3. **Task 3.12's arm, as worded, cannot bite**: "store the caller's list without `tuple(...)`". `place` builds new `OrderLine` objects from the caller's inputs, so the caller's list is never stored on the order; replacing `requested = tuple(lines)` with `requested = lines` changes nothing observable. I armed the equivalent mutation (the aggregate's own `lines` held as a `list`, arm 3.12) and the `cancel` path's real aliasing (arm 4.13a: caller's `list` kept as `compensation_steps`). The test still asserts the caller-mutation property; the spec wording of the arm should say `placed_lines = order_lines`.
4. **Task 4.16's wording is false as written**: "exactly the four `order.*` facts other than `order.saga_failed.v1`". `FACT_MODELS` also holds `order.despatched.v1` (Fulfillment's fact). The test excludes both `order.saga_failed.v1` and `order.despatched.v1` and says why. No spec change proposed; the task text is imprecise.
5. **A `# pragma: no cover` branch** in `cancel`'s event builder (`if recorded is None: raise InvalidOrderSnapshotError`) exists only to narrow `CancellationReason | None` for `mypy --strict` without `cast`/`assert`. It is reachable under arm 4.6a (reason assignment moved out of `_transition_to`): the builder then raises instead of emitting an event carrying `None`; the R10 test fails either way. The design said the event "would carry `None`"; here a type-narrowing branch turns that into an error.
6. **`CompensationStep` is keyword-only** (design.md says "frozen dataclass"; keyword-only matches the events and avoids a positional mix-up).
7. **Extra tests beyond `tasks.md`** (all pass; none weakens a task): `test_r6_a_total_of_exactly_zero_is_allowed` (boundary), `test_r10_the_pairing_lists_are_exhaustive_over_reason_and_cancellable_source` (6 + 6 = 12), `test_every_pair_is_decided_by_is_legal_exactly_as_table_t1_says`, `test_the_events_carry_the_aggregate_state_not_the_request`, `test_a_utc_instant_in_any_spelling_of_utc_is_accepted`, `test_place_keeps_the_order_reference_and_the_business_codes_it_was_given`, `test_parse_accepts_each_real_token_and_returns_its_member`, the writer-scan sentinel tests, and the purity-scan sentinel test.
8. **Not armed: the spec-parse half of T-1** (`test_table_t1_parsed_from_the_specification_equals_the_transcription`) was not armed by editing `specs/shared/domain-model.md`, because editing `specs/shared/` is outside my bounds even temporarily. What was run: arm 2.5a - c against the transcription half. The parse half's non-vacuity is the literal counts (12 / 11 / 7 / 5) asserted on its own output, which fails if the parser finds no rows. The reviewer can arm it by changing one cell of the table.
9. **The seed's `test_money_text.py` keeps its fourteen vectors** as well as the kernel's copy (task 1.7 asks only for the import-line change). The two copies are now a duplication a later pass may remove.
10. **Surprise**: `specs/orders_aggregate/design.md` was modified on disk by someone other than me while I was working (the harness reported a changed file after a `ruff format` run). I did not edit it. Worth the leader checking it is the intended content.
11. **`quality.sh` was green on the first full run**; the only gate adjustments were an E501 in the money-guard docstring and the new classified entry in the write-path census, both caught by their own gates before the full run.

## 7. Verification (commands and figures copied from their output)

- `./quality.sh`: **exit 0, 131 seconds** (`/tmp/quality.rc`: `exit=0 seconds=131`), `1433 passed in 93.08s`, total coverage 98.41% (gate 60%), domain coverage step (`--include='*/domain/*,packages/shared_kernel/*'`, gate 80%) TOTAL 98%, web gates green. The `otcpy` stack was **up** (`docker ps`: grafana, prometheus, kafka-exporter, kafka-console, n8n, otel-collector, postgres, mongodb, jaeger, kafka, mailpit, nats), neither started nor stopped by me; the integration suites use their own Docker-held containers.
- `./init.sh`: exit 0, before and after.
- `uv run pytest` over the directories I touched (each run separately, then combined):

| Command | Result |
|---|---|
| `uv run pytest services/orders/tests/unit/domain -q` | 121 passed |
| `uv run pytest services/orders/tests/unit/test_order_domain_contract_parity.py -q` | 6 passed |
| `uv run pytest packages/shared_kernel -q` | 316 passed |
| `uv run pytest services/seed/tests/unit -q` | 148 passed |
| `uv run pytest tests/architecture -q` | 399 passed |
| the five paths together | **990 passed** (121 + 6 + 316 + 148 + 399 = 990) |

Per-file figures of `services/orders/tests/unit/domain` (each `uv run pytest <file> -q`): `test_domain_tests_are_pure.py` 2, `test_order.py` 18, `test_order_cancellation.py` 24, `test_order_errors.py` 1, `test_order_events.py` 8, `test_order_instants.py` 4, `test_order_rehydration.py` 17, `test_order_state_machine.py` 7, `test_order_structure.py` 19, `test_order_totals.py` 7, `test_order_vocabulary.py` 14: 2 + 18 + 24 + 1 + 8 + 4 + 17 + 7 + 19 + 7 + 14 = 121.
- `uv run ruff format --check`, `ruff check`, `mypy` (241 source files, strict), `lint-imports` (10 kept, 0 broken): green inside `quality.sh`.

## 8. Acceptance walk (`feature_list.json` id 13)

| Criterion | Evidence |
|---|---|
| every legal transition allowed, every illegal one raises a DomainError | R8 walk (11 edges from `place`), R9 (72 / 11 / 61), arms 4.2 - 4.5 |
| no empty orders, no line mutation after confirmed | R5, R7 (six statuses x three mutators, one-line order), arms 3.8, 3.18, 3.19 |
| totals always consistent with lines | R6 (hand-computed literals after place, add, change, remove), candidate-then-commit arms 3.11, 3.17b/c; derived on load (5.3) |
| cancelled requires a reason, set inside the accepted transition | R10 (three tests), arms 3.13b and 4.6a, 4.7, 4.8 |
| rehydrate validates its invariants on every load | nine checks, nine tests, table 5.3 |
| pure domain unit tests, zero framework imports | `test_domain_unit_tests_import_only_...` (arm 6.4), AST money guard + `lint-imports` (arm 6.3) |

## 9. #8's six findings (defect, A1 - A5): avoided or recurred

| #8 id | Shape | Verdict | Evidence |
|---|---|---|---|
| defect | two load checks survived their own deletion | **avoided** | table 5.3: nine deletions, each caught by its own test |
| A1 | report figures not summing to the headline | **avoided** | section 7: 990 = 121 + 6 + 316 + 148 + 399, and 121 per file |
| A2 | cancellation reason assigned outside the accepted branch | **avoided** | assignment is inside `_transition_to`'s accepted branch; the event reads it from state; arms 3.13b and 4.6a |
| A3 | a corrupt snapshot raised a business code | **avoided** | `InvalidOrderSnapshotError` (`order.snapshot_invalid`), distinct from `order.cancellation_reason_not_applicable` (asserted in `test_rehydrate_refuses_cancelled_without_a_reason`) |
| A4 | eleven error classes against a table of ten | **avoided** | `test_the_orders_domain_error_population_is_the_literal_table` walks the package; arm 3.16 |
| A5 | brief vs `tasks.md` conflict handled ad hoc | **avoided** | the leader's pre-run check had already fixed the one conflict (6.6); I met none during the run |

## Review round 1 rework (D1-D3, tasks 3.22, 4.17, 5.12)

Test-only; no production edit, no conftest change (the fixture values were already pairwise distinct: GLNs, retailer vs company code, order_date -60 vs occurred_at 0, price vs discount, initial 8465 vs total 8115). Tasks 3.22, 4.17 and 5.12 are ticked (`grep -c "^- \[ \]" specs/orders_aggregate/tasks.md` = 0).

### Tests added

| Test | Task | Proves |
|---|---|---|
| `test_order.py::test_place_keeps_both_glns_the_order_date_and_the_two_creation_instants_it_was_given` | 3.22 | `place` keeps `buyer_gln`, `supplier_gln`, `order_date`, `created_at`, `updated_at` (D3) |
| `test_order_events.py::test_every_payload_field_of_each_of_the_four_events_is_the_value_the_aggregate_was_given` | 4.17 | every payload field of `OrderPlaced` (incl. both lines' five fields), `OrderConfirmed`, `OrderCompleted`, `OrderCancelled` (D1) |
| `test_order_rehydration.py::test_rehydrate_restores_every_field_of_the_snapshot_with_a_non_none_note` | 5.12 | `rehydrate` restores every field, `notes` non-None, per-line fields (D2) |

### Arming (cp backup of `order.py`, one anchor, ONE named test, restore, `cmp` identical, caches cleared)

| Arm | Mutation | Failure (verbatim, abridged) |
|---|---|---|
| P1 | `OrderPlaced` buyer/supplier GLN swapped | `assert GLN(value='5412345000006') == GLN(value='4012345000009')` |
| P2 | `OrderCompleted.total_amount=_initial_amount` | `At index 4 diff: Money(amount=8465...) != Money(amount=8115...)` |
| P3 | `OrderPlaced.order_date=occurred_at` | `datetime(...9, 0) == datetime(...8, 0)` on `.order_date` |
| P4 | `OrderPlacedLine` unit_price / line_discount swapped | `At index 0 diff: (... Money(amount=250...), Money(amount=1999...)) != (...)` |
| CONF | `OrderConfirmed.order_reference` corrupted | `At index 0 diff: OrderNumber(value='ORD-999999') != OrderNumber(value='ORD-000009')` |
| CANC | `OrderCancelled` retailer_code / company_code swapped | `At index 1 diff: 'CMP-01' != 'RET-01'` |
| R1 | `rehydrate` `notes=None` | `assert None == 'leave at dock 4'` |
| R2 | `rehydrate` retailer/company swapped | `assert 'CMP-01' == 'RET-01'` |
| R3 | `rehydrate` `created_at=snapshot.updated_at` | `...created_at` 9:05 `==` 9:00 |
| R4 | `rehydrate` `supplier_gln=snapshot.buyer_gln` | `GLN('4012345000009') == GLN('5412345000006')` |
| PL1 | `place` order's GLNs swapped | `GLN('5412345000006') == GLN('4012345000009')` |
| PL2 | `place` order's `order_date=occurred_at` | `.order_date` 9:07 `==` 8:00 |

All 12 killed; every restore printed `identical` and the final run is green. Defeat rows applied: 1 (existing), 2 (P2, P3, PL2, CONF, R1), 3 (P1, P4, R2-R4, PL1, CANC), 7 (R1).

### Counts

Per file (each run alone): purity 2, cancellation 24, errors 1, events 9, instants 4, order 19, rehydration 18, state machine 7, structure 19, totals 7, vocabulary 14 = **124** domain. Parity 6, kernel `test_money_text` 14 (unchanged). Headline 1433 + 3 = **1436**, matching quality.sh.

### quality.sh

One run: exit 0, 139 s wall (pytest 100.32 s), **1436 passed**, `all gates passed`. The `otcpy` stack was UP (12 containers), so the time is not comparable with the stack-stopped threshold; not started or stopped by me. `feature_list.json` line 231 set to `in_review` (feature 13 only).

## F8 follow-up (test-only)

Added `test_r6_add_line_and_change_line_keep_every_non_money_field_supplied` in `services/orders/tests/unit/domain/test_order.py` (pairwise-distinct `SKU-ALPHA` / `Bravo widget` / quantity 3 then 4; asserts product_code, description, quantity, and for change_line the kept product_code and description plus the new price and discount). No production edit.

| Arm | Mutation of `order.py` | Verbatim failure |
|---|---|---|
| U1 | `add_line` builds with `description=None` | `AssertionError: assert None == 'Bravo widget'` (`.description`) |
| U2 | `add_line` builds with `product_code=str(description)` | `AssertionError: assert 'Bravo widget' == 'SKU-ALPHA'` (product_code) |
| U3 | `change_line` replacement `description=None` | `AssertionError: assert None == 'Bravo widget'` (`.description`) |

Restored from backup, `cmp` identical, `__pycache__` cleared, test green. `uv run pytest services/orders/tests/unit -q`: 156 passed (run from `services/orders` as `tests/unit`).
