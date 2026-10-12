# Premise check: brief for backlog 216

VERIFIED backlog 216 has three acceptance items - feature_list.json id 216 `acceptance` list length 3 (SA-8 gate; scratch scenario as failing-first test; mutation families + decoy + redelivery).
VERIFIED `.arm/r41/test_r41_stranded_reservation.py` and `.arm/r41/stranded.out` exist - ls -la (3771 B, 1842 B).
VERIFIED quoted output - stranded.out ends `command rows: [('stock.reserve', 'sent')]`, `stock.release requests: []`, `outbox: ['order.cancelled.v1']`, `1 passed in 12.48s`.
VERIFIED review N1 describes it - progress/review_orders_cancel_responder.md:28.
VERIFIED fact_handler.py lines - handle 68, LATE_APPROVAL_EVENT_TYPE branch 84, _is_late_approval 128, _enqueue 140, _ignore 164 (cat -n).
VERIFIED step_table.py exists and map_release_reason has `case Reason1.order_cancelled` (lines 60, 68).
VERIFIED impl_orders_cancel_responder.md section 2 item 6 = "The late credit.approved.v1"; arms F1-F8 in section 6 (also F1b, F1c exist; harmless).
VERIFIED ledger unique on (order, command) - alembic 0001:209 `uq_saga_commands_order_id_command` on ("order_id","command"); models.py:189.
VERIFIED #8 CancelOrderCommandHandler.cs:157-169 - `default:` branch for `placed`: cancels with compensationSteps [] , no stock release.
VERIFIED #8 SagaStepTable.cs:181-186 - stock.reserved.v1 Advance from Placed (file is at src/Orders/Application/Sagas/, brief gives no dir for it).
VERIFIED #7 cancel-order.handler.ts:118-131 - `placed` falls to cancel with [] steps.
VERIFIED #7 saga-steps.ts:173-178 - 'stock.reserved.v1' advance, precondition 'placed' (range starts at the tail of the previous entry, content correct).
VERIFIED R26/F3 meaning - saga.md:166 F3 all-or-nothing, stock.rejected means nothing reserved; R26 no release command (test-matrix.md:126).
VERIFIED "saga ignores stock.released.v1 at cancelled (R25)" - step_table `stock.released.v1` variants are stock_reserved/credit_approved/confirmed only, so cancelled -> step None -> precondition_unmet.
VERIFIED dispatcher never loads the order - command_dispatcher.py:20.
VERIFIED brief forbids nothing the acceptance mandates - bounds allow saga/**, tests/**, test-matrix col 5, feature_list line; acceptance 2/3 need only those. Specs/shared amendment (acceptance 1) is the leader's, outside the implementer.
FALSE-ish (state only) "216 is set in_progress by the leader at dispatch" - feature_list.json currently `"status": "pending"`; a pending action, not a defect.
UNVERIFIABLE-pending SA-8 applied text (saga.md section 4.3 new paragraph, section 5 and 6 rows) and progress/sa7_sa8_sa9_application.md - being applied.

Verdict: SAFE TO ACT - 0 FALSE (1 status note), 1 UNVERIFIABLE-pending.
