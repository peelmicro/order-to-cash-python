# Brief — reviewer, feature 14 `outbox_and_idempotency` (phase 8, full group: persistence, wire contract)

**Task:** approve or reject feature 14. Write `progress/review_outbox_and_idempotency.md`. On approval set feature 14 to `done` and append its effort entry to `progress/history.md` (against #7's ~2.4 h and #8's ~3.4 h, `../order-to-cash-dotnet/progress/history.md` 730–772; name every inherited #8/#7 finding avoided or recurred); on rejection set it to `in_progress`. Edit only that status line of `feature_list.json`. Read-only otherwise; no git command that writes the index or working tree. Return the verdict plus at most 8 lines.

## Inputs

- Spec (approved 2026-10-06, G1 and G2 decided as recommended): `specs/outbox_and_idempotency/{requirements,design,tasks}.md`, including the leader's **amendment A1** at `design.md` §6.4 (`ConsumerName` in a per-service `consumer_name.py`, #8's shape) and the widened root-`conftest.py` bound in `tasks.md`.
- Implementation report: `progress/impl_outbox_and_idempotency.md` (§11 divergences, §13 inherited findings, arming table, constructor-call census, skip-versus-block numbers, "Amendment A1" section). Briefs: `progress/brief_impl_outbox_and_idempotency.md`.
- #8's spec and code for the same feature: `../order-to-cash-dotnet/specs/outbox_and_idempotency/`, `../order-to-cash-dotnet/src/Orders/Infrastructure/Outbox/`; #7's: `../order-to-cash-nestjs/specs/outbox_and_idempotency/`.

## What the leader established with a command this session

- The developer stack `otcpy` is stopped (only `otcpy-n8n` on 5678; `ss -ltn` shows no 9092/5432). Do not start it. Testcontainers suites run without it.
- After A1, `uv run pytest services/orders/tests/integration/test_idempotent_consumer.py` → 5 passed (testcontainers, dev ports free).
- The implementer reported `./quality.sh` exit 0, **153 s**, 1644 passed, 98.44 % coverage, stack down — before A1. Phase 7's threshold is ~125 s (stack stopped; 103.24 s, 1 290 passed); feature 43's run was 142 s with the stack up.

## Questions (research, do not assume)

1. Re-arm, do not re-read: the SKIP LOCKED claim (two relays never publish the same row) and the skip-versus-block measurement with the guard armed the other way; the deadlock-victim retry inside `run_once` (#8 87); the poison-row behaviour of G1 (clean prefix published, then stop; no skip; loud); the `(event_id, consumer)` dedupe; millisecond agreement (205); the generic `Envelope[P]` refusal of an unvalidated payload (203 item 2). At least one arm per item that the implementer did not run the same way.
2. Ordering: can any fact of one order be published ahead of an earlier one (R15/OI8) through retry, poison or a second relay?
3. Field mapping: the implementer reports 214 single-field constructor mutants killed. Probe a mapping site the census might have missed (enumerate the sites yourself and compare).
4. Python-specific: event-loop affinity of the engine and the aiokafka producer, task cancellation of the relay loop (cancelled cleanly, never swallowed), exception propagation out of `run_once`, `Any` leaking from aiokafka past the typed adapter, the JSON serializer (compact, raw non-ASCII, `occurredAt` formatter), `json` not `jsonb`.
5. A1: is the full-file scan sound and does the one allowed relative import admit nothing else? Is any other spec-vs-code divergence in §11 a silent weakening (report §11 items 4, 5, 9, 10 especially)?
6. The 153 s: what in this feature costs it (time the new integration modules), and is any fixture scoped wider or narrower than its comment says? Report a number and a cause; do not fix.
7. Counts: 1644 = 1506 + 138 — reconcile per-file against your own run of the new test files; R11–R15, R17, R18 rows in `specs/shared/test-matrix.md` column 5 only, names existing.

Run the defeat list on what you probe and state which rows apply. Disposition every finding (fix → reject; accept with evidence and a re-open trigger; or re-open only if X); findings are fixed in this phase. This is round 1; a rejection must make each required change unambiguous.
