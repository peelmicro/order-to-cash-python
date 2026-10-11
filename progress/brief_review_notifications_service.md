# Brief — reviewer, feature 23 `notifications_service` (phase 11, `sdd: false`, full group)

**Task:** adversarial review of feature 23 against its five acceptance items (`feature_list.json` id 23), `specs/shared/domain-model.md` §6 and §7.3, R17 / R18, `CHECKPOINTS.md`, and the implementer's brief `progress/brief_impl_notifications_service.md` (its Must hold section is the guard list). The implementation record is `progress/impl_notifications_service.md` (sections 0 – 14); arming artefacts are under `.arm/n23/`. Feature 23 is `in_review`. Classification: **full group**, round 1. The implementer stalled for ~9 h mid-run and resumed on a leader message; check that the record's late sections describe the code as it is now, not as it was planned.

## Verified by the leader this session (do not re-derive; do re-check anything your verdict rests on)

- `git diff feature_list.json` changes only line 412 (`pending` → `in_review`).
- `.arm/n23/final.log` ends `quality.sh: all gates passed` / `EXIT 0 DURATION 433s`; the record claims `3781 passed` (baseline `3492`). Only `otcpy-n8n` is running.

## Questions the review must answer (each with a command or a mutation, not by reading the record)

1. **Ledger / send order.** The record says the canonical `idempotent_consumer.py` is adopted byte-identically with a no-op `work`, the send happens outside the transaction, and a separate forget-on-throw deletes the row (record §2). Does a transient failure leave no row, does a permanent failure keep the row, does a crash between commit and send lose at most one email and never duplicate one — and does a test fail when the forget is deleted, or when it runs on the permanent path?
2. **Parity guard case 3** now has a two-service literal: does it still fail when Notifications' copy is removed or diverges by one character, and was the instrument's change of premises armed (Phase 10 D2/D3)?
3. **The filter itself** (#8's guards never crossed it): delete one of the seven from `NOTIFIED_FACTS`, add a valid sibling (`stock.reserved.v1`, `credit.released.v1`): each fails a named test, fast.
4. **Template sites** (#8 ids 58, 59, 60): reproduce `scripts/notification-template-sweep.py`'s enumeration independently (109 sites claimed); run at least one mutation by hand that the tool does not generate (e.g. a nested or list-held field, a transposition of two envelope ids, recipient fallback for `payment.received.v1`); check the sentinels fail to detect; check no fixture collision lets a transposition pass.
5. **Departures from #7 / #8:** the record renders instants in the wire form where #7 and #8 render the raw form (§2 item 1), and names its own env variables and settings (§2 item 4). For each, decide whether `specs/shared/` decides it or it is a free choice, and whether it is a departure that needs recording in the ported-idiom ledger.
6. **Lifespan:** the consumer task is awaited on shutdown, cancellation propagates, a dead task takes readiness to 503; the 30 s grace + cancel (record §13) — does a test fail when it is removed?
7. **Acceptance 5** (feature 43 carry-over): every row, including the F-g + F-j fixture, armed against this service's composition root.
8. **Live record (§11):** do its outputs under `.arm/n23/live/` show seven Mailpit messages for seven facts with the asserted fields, and an unchanged inbox and ledger after the byte-identical redelivery and after a host restart?
9. **Avoided / recurred** for every inherited #7 / #8 finding the record lists (§4, §12), and the #8 backlog classification (23 ids incl. 69).

## Rules

Read-only: never edit source, tests or `feature_list.json` except feature 23's status line (`done` on approval; `in_progress` on rejection). Mutations follow CLAUDE.md's arming protocol: backups in `.arm/n23-review/` with `sha256`, restore by `cp` + `cmp`, clear `__pycache__` / `.mypy_cache`, never `git checkout`; never two test runs against the same containers at once; a timeout kills the process group. Grep `CLAUDE.md` on disk before enforcing a rule. Every finding gets a disposition (fix / accept with evidence and a re-open trigger / SA-n proposal) and names its unit. No git command that writes the index or working tree.

## Output

`progress/review_notifications_service.md`: verdict (APPROVED / REJECTED), blocking and non-blocking findings with the mutation or command that proves each, the answers to questions 1 – 9. Return only "result in `progress/review_notifications_service.md`" plus the verdict and the count of blocking findings.
