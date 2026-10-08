# Premise check — brief_impl_fulfillment_despatch.md

VERIFIED   feature 18 in_progress, sdd false, phase 9, THREE acceptance items — feature_list.json id 18 printed: status "in_progress", 3 acceptance entries (consumed; outbox; carried SA-4 item citing §6.3/§15, #8 id 79, id 54)
VERIFIED   R36 at requirements.md:279; F6/F7/F8 at domain-model.md:311-313; asyncapi despatchCreate from :397 (address fulfillment.despatch.create at 398); order.despatched.v1 on otc.fulfillment.facts.v1 (OrderDespatched :1422, channel :125/145); RpcErrorReply present
VERIFIED   design.md sections §3 (L1-L26 ledger rows), §6.3, §6.5, §8, §8.5, §10, §15 exist and say what the brief says (§6.3 two methods; §6.5 READ COMMITTED + 40P01 re-run; §8.5 error table; §10.1 payloads.py assert_never; §15 boundary)
VERIFIED   stock_keys_of_order (stock_reads.py:97, ports/stock_store.py:107), lock_order_items (stock_repository.py:98), StockTransactions.run (stock_transactions.py:85), wait_for_lock_waiters (tests/integration/conftest.py:275), payloads.py assert_never (:127)
VERIFIED   models.py: Despatch.order_reference unique (:94), despatch_reference unique, DespatchItem (:99), DespatchNumberSequence (:111)
VERIFIED   sequences.py docstring "The allocator proper is Phase 9"
VERIFIED   Orders allocator exists; test_order_number_allocator.py has exactly six tests matching the brief's list (grep ^async def test_: lines 57,74,91,105,123,153)
VERIFIED   TERMINAL_RPC_ERROR_CODES at nats_saga_commands.py:65 (nine codes)
VERIFIED   #8 history: 1126 = fulfillment_despatch, rejected round 1 on a test asserting the opposite of its name; 1158 = "Notes for #9"; 1167 = Phase 9 closing assessment; #8 feature_list ids 54 (un-hinted re-read ledger row), 49 (deterministic id), 79 (SA-4 one-lock) exist
VERIFIED   #7 history 863 = fulfillment_despatch, approved first pass; fault-injection (throw after despatches.save, zero outbox rows, outbox-outside-tx control) at line 870
VERIFIED   code paths: #7 order-to-cash-nestjs/apps/fulfillment; #8 order-to-cash-dotnet/src/Fulfillment (DespatchCreationService.cs exists). Siblings are at ../ relative to the repo (Assessments/), as the brief writes
VERIFIED   test-matrix.md R36 row: 5 data columns, col 5 = Status, currently TODO (col 4 holds #7-style test names); feature 17's review R1 (lock-read order swap) exists in progress/review_fulfillment_stock.md:93; design.md:520 records the despatch half carried to 18
VERIFIED   CLAUDE.md: sdd:false ledger lives in progress/impl_<feature>.md — matches the brief; arming protocol (.arm/, git-ignored: git check-ignore .arm prints .arm) matches
FALSE      "the settings->adapter reach test and the registration guard still pass with the new handler (they are parameterised over the service)" — partially false: tests/architecture/test_registration_behaviour.py:74-83 holds a LITERAL TABLES["fulfillment"] listing exactly 3 commands (Reserve/Release/Replenish) and 2 queries; it is parametrised over service but asserts the table equals the literal (line 237-239), so registering a despatch command FAILS it until that literal is edited. Likewise test_composition_env_reads.py:38 EXPECTED_SETTINGS["fulfillment"] is a literal set (fails only if a new settings class is added). The settings->adapter reach test is not in tests/architecture: it is services/fulfillment/tests/unit/test_fulfillment_settings_env.py. Brief's bounds allow tests/architecture edits only "where a census needs a new module classified" — the TABLES edit is not obviously covered
CONFLICT   none with CLAUDE.md found (ledger location, arming, bounds on services/orders and packages all agree)
UNVERIFIABLE ORD-000007/8 hold reserved reservations in otc_fulfillment — stack down; not started
UNVERIFIABLE "no migration expected" / no column missing — would need an implementation to settle (despatch tables present per models.py)
NOTED: design.md §15 and §8.1 say "two acceptance items"/"five subjects"; the brief's "sixth subject" and "three items" are consistent with the current state (feature_list has 3 items).

Counts: VERIFIED 13, FALSE 1, UNVERIFIABLE 2, CONFLICT 0. Verdict: DO NOT ACT (until the registration-guard claim is corrected).
