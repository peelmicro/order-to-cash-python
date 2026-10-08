# Premise check — brief_impl_fulfillment_stock_round2.md

Verdict: DO NOT ACT as written (0 FALSE, 1 CONFLICT, rest VERIFIED). Commands run from repo root.

VERIFIED review §6 has D1-D7 (grep '^\*\*D' lines 125-137) and §7 items 1-8 (lines 141-150) with arms R1, M1 (x2), M9, I5, D5a named (D5a at review line 35 and §7 item 8).
VERIFIED §7 ends "Not required: the code itself." (line 152).
VERIFIED feature 18 acceptance already carries the D4 item (feature_list.json id 18, third acceptance entry "carried from fulfillment_stock ...").
VERIFIED feature 17 status is in_progress (python json read: "17 fulfillment_stock in_progress").
VERIFIED .arm/review17/ holds a_r1.py and log.md; log.md line 311 "Q6-G8-Fj-plus-Fg" (real F-j fixture, RED by WIRE).
VERIFIED impl report §2 (lines 20-37) lists corrected line numbers; §8.1 is an empty heading (line 161); G8 description at impl line 94 of tasks / "feature 43's carried F-g + F-j fixture"; §7 ids 49 (line 134) and 79 (line 138) exist.
VERIFIED test files exist: services/fulfillment/tests/integration/test_stock_repository.py, test_stock_release_idempotency.py; services/fulfillment/tests/unit/test_stock_reservation_service.py; integration/conftest.py. (They sit under integration/ and unit/ subfolders; the brief gives bare names.)
VERIFIED D5 stale citations are present in the spec (design.md lines 26, 31, 40, 103, 104, 353, 395; requirements.md 39, 63; 91 cites nats_saga_commands, see output).
VERIFIED stock_repository.py:101-102 are the two reads R1 swaps; :104-105 the ConcurrentReservationChangeError branch; stock_reservation.py:115 and :170 carry scope.ids.new.
VERIFIED brief bounds on specs/shared (test-matrix col 5 R30-R35 only) agree with tasks.md lines 18 and 21.
NOTE .arm/fix17/ does not exist yet (brief says "use"; creation is the implementer's).

CONFLICT Brief Bounds "Nothing under services/*/src/" vs review §7 items 1, 2, 3, 4, 6, 8: every arm (R1 on stock_repository.py, M1 on stock_reservation.py:115/:170, M9 on :104, I5, Q6/G8 which edits application/handlers.py and composition.py) must mutate src temporarily. Meant as "no permanent change", but not stated; an implementer could read it as forbidding the mandated arms.
