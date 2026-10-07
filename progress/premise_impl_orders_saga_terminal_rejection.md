# Premise check, brief_impl_orders_saga_terminal_rejection.md

VERIFIED feature 42 has four acceptance items; the fourth names park's `status <> 'sent'` at command_ledger.py:157 (python json load; line 157 is `.where(SagaCommand.id == row_id, SagaCommand.status != "sent")`)
VERIFIED paths exist: nats_saga_commands.py, saga/command_dispatcher.py, saga/command_ledger.py, application/ports/saga_commands.py, tests/{unit,integration}/saga/ (ls)
VERIFIED SagaCommandRpcError carries code (ports/saga_commands.py:48, `self.code = code`; adapter raises it at nats_saga_commands.py:150)
VERIFIED Code enum at generated/asyncapi.py:423, twelve members (sed)
VERIFIED saga_commands.status varchar(10) at models.py:199 (String(10)); no CHECK found in the column
VERIFIED design.md sections 9.2 (l.448), 9.5 (509), 9.6 (545), 9.7 (580), 12.4 (625; names feature 42's rejected, 8 chars)
VERIFIED requirements.md section 5 has corrected wording (plain SagaCommandTransportError with no code, "corrected by the leader from review round 1 Q5")
VERIFIED #8 history 872-913 content: heading at 872, section ends before id 45 heading at 914; approved first time, 3 probes, "Notes for #9", ~2x #7 clock
VERIFIED #8 IsTerminalRpcErrorCode at NatsSagaCommandsAdapter.cs:179
VERIFIED #7 isTerminalRpcErrorCode at nats-saga-commands.adapter.ts:79 (sed shows function there)
VERIFIED #7 history line 1091 is the feature 42 heading
VERIFIED #7 and #8 terminal sets agree member for member: VALIDATION_FAILED NOT_FOUND CONFLICT PRECONDITION_FAILED ORDER_NOT_CANCELLABLE STOCK_UNAVAILABLE INVOICE_NOT_PAYABLE PAYMENT_MISMATCH DOMAIN_ERROR (nine); transient TIMEOUT UNAVAILABLE INTERNAL_ERROR. #8 unknown code falls false; #7 default throws (as #8 history says)
VERIFIED no acceptance item of feature 27 names a terminal rejection or saga_failed (json dump; 27's items are trace, logs, DLQ, readiness, requestId, metrics, reload, SO9 re-run). Items for 15 and 41 mention rejection/terminal but are not feature 27
VERIFIED repo-local .arm/ exists with arm.py
VERIFIED feature 42 status is "pending" now; brief says in_progress (expected, leader sets it)
VERIFIED no conflict: nothing the brief forbids (no migration, no specs/shared, no feature_list edits beyond status, no new package) is required by the four acceptance items; ledger, sweeper, tests are all in the allowed paths
NOTED: design.md 9.2 still says "retryable until feature 42" (the pre-42 wording the brief says to amend)
