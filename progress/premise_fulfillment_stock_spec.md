# Premise check — brief_spec_fulfillment_stock.md

FALSE       "no domain, no application" in Fulfillment (brief line 13) — `find services/fulfillment/src -type f`: `domain/__init__.py`, `domain/value_objects/__init__.py` (85 B sentinel docstring), `application/__init__.py` exist; all are docstring-only placeholders (no code). Partially true only: packages exist, with no code.
VERIFIED    paths in the brief exist (Fulfillment persistence files, settings.py, presentation/app.py, Orders composition/main/responder, the three architecture tests, parity, lifespan, acceptance tests, messaging adapters, outbox spec/review, packages/cqrs, shared spec files) — `ls -d` printed all
VERIFIED    #7 apps/fulfillment/ and #8 src/Fulfillment/ exist — `ls`: Application Domain FulfillmentHost.cs ...; src drizzle package.json ...
VERIFIED    #8 spec line counts 125/581/109 and #7 98/511/79 — `wc -l` output identical
VERIFIED    history anchors #8 999 (17), 1062 (id 46), 1126 (18), 1167 (Phase 9 closing); #7 842 (17), 863 (18) — `sed -n` printed the matching headings
VERIFIED    #8 17: three review rounds, two blocking defects; #7 17: one rejection, unplanned fifth mutation survived — history text "REJECTED, REJECTED, APPROVED. 2 blocking defects"; "1 unplanned fifth mutation survived"
VERIFIED    #8 backlog ids 49, 50, 51, 54, 79, 95, 101 exist with stated subjects — python json over feature_list.json (titles: release event id; responder shutdown fault isolation; RPC payload schema parity; ledger row for un-hinted re-read; SA-4 operator cancel release order; cold NATS connection; stock page repeats code)
VERIFIED    feature 17 has six acceptance items, 18 has two — json len 6 / 2; item 6 is "carried from cqrs_dispatcher (id 43 ...)" naming F-a,F-b,F-g,F-i,F-j and the F-g + F-j fixture; 18 sdd false
VERIFIED    207 done, attached_to names 17 — status "done", attached_to "fulfillment_stock (id 17), the first writer of stock.units..."
VERIFIED    test-matrix §4 fulfillment_stock → R30–R36, R61; R36 is despatch — test-matrix.md:75,131,141
VERIFIED    saga.md ~230 states one lock — saga.md:222-240 "decide stock.release and despatch.create for one order under one lock"
VERIFIED    tables stock, reservations, despatches, despatch_items, despatch_number_sequences, outbox, processed_events; no composition.py — grep __tablename__ models.py lines 60-138; find shows no composition.py
VERIFIED    parity guard case 1 at line 170, case 3 at line 274 — sed printed the "case 1"/"case 3" banner comments at those lines
VERIFIED    TERMINAL_RPC_ERROR_CODES at nats_saga_commands.py:65 with nine codes — block starts ~line 65 (sed 60-80); nine members listed
VERIFIED    reach test section from test_orders_host_lifespan.py:571 — line 571 is the "every environment read reaches the thing it configures (id 56)" banner
VERIFIED    id 56 recurred three times in Phase 8 (15 D-2, 15 R2-D5, 16 D1) — progress/history.md:859 "for the third time this phase after feature 15's D-2 and R2-D5"
VERIFIED    orders_create_responder.py drains in-flight on shutdown and isolates a faulted request — read: run() `finally` -> `_drain` = asyncio.gather(*in_flight, return_exceptions=True) (lines 104-108); _log_fault done-callback (130-132); cancellation re-raised (83-88). One scope per request: `self._scope_factory()` per _serve (line 118); this file does not itself close the scope (closing is not visible here)
VERIFIED    `stand_in_stock_check` fixture exists — services/orders/tests/integration/conftest.py:552 (the brief says it lives in test_orders_create_acceptance.py; that file only USES it, lines 60, 111)  [wording nit: location differs; fixture exists]
UNVERIFIABLE ORD-000007 parked stock.reserve row in dev DB — dev stack stopped, not started; progress/current.md:21 asserts it
UNVERIFIABLE "Check whether the schema already carries every column 17 needs" — task for the spec author, not a claim

Counts: VERIFIED 17, FALSE 1, UNVERIFIABLE 2
Verdict: DO NOT ACT as written (1 FALSE; minor).
