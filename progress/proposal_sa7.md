# Proposal `SA-7` — `saga.md` §2 gains the `credit.release` row (backlog 213)

**Status:** proposed by the leader, Phase 13 (2026-10-12), for the maintainer's gate. Not applied.

## The gap

`specs/shared/saga.md` §2 ("The command vocabulary", lines 38 – 50) lists seven commands — `stock.check`, `stock.reserve`, `stock.release`, `despatch.create`, `credit.hold`, `invoice.issue`, `payment.register` — and no `credit.release`. Yet the same file issues it: §4.3 (lines 235, 241, 255) and the §5 step table (lines 303 – 304, 306), and `specs/shared/asyncapi.yaml`'s `creditRelease` channel (line 439) says *"Caller — orders.saga. Responder — billing."* Found by #9's feature 19 review (`progress/review_billing_credit.md` §7); #8 narrated it with "owner feature 41" and never filed it; #9's `specs/billing_credit/requirements.md` §1.2 item 1 narrated it again. Feature 41 is the first to issue `credit.release` from the orchestrator (SA-4's release ordering), so the gap closes here or is ruled intentional.

## Why an amendment rather than a ruling that the omission is intentional

§2's own preamble makes the table the command vocabulary (*"These are requests, not domain events"*); every other orchestrator-issued command is in it, including the compensation `stock.release`. Nothing in the three repositories argues the omission was deliberate: the subject, both payload schemas and the caller are already in `asyncapi.yaml`, and all three Billing builds implement the responder. A ruling of "intentional" would leave a table that a reader takes as complete and is not — the defect class `SA-5` and `SA-6` corrected.

## The change (one table row, `saga.md` §2, inserted after `credit.hold`)

```markdown
| `credit.release` | Orchestrator | Billing | `(orderReference, release)` | released / not-held (`released: false`) |
```

- **Caller / Responder:** from `asyncapi.yaml` `creditRelease` (*"Caller — orders.saga. Responder — billing."*).
- **Idempotency key:** `(orderReference, release)` — the shape of `stock.release`'s key, and what Billing implements: a release is owed only while the order has an outstanding exposure, and a repeat appends nothing and emits nothing (`asyncapi.yaml` `CreditReleaseReplyPayload.released`: *"`false` — idempotent repeat or nothing was ever held (BC11, B5); not an error, no ledger entry, no fact"*; #9 `specs/billing_credit/requirements.md` BC11, BC25).
- **Response:** from `CreditReleaseReplyPayload` (`released: true` with the amount, or `released: false`), worded like `stock.release`'s "released / already-released".
- **Placement:** after `credit.hold`, keeping each responder's rows together as the table already does for Fulfillment.

Prose only otherwise: no schema, subject, payload, requirement, or test-matrix change. `saga.md` is in `init.sh`'s byte-identity check, so the row lands in #7, #8 and #9 in one session, committed on its own in each, with an `SA-7` row in each README registry and an entry in each `progress/history.md`.

## After the gate

- Approved → the leader applies the row byte-identically to the three repositories (one `spec(SA-7): …` commit each at the wrap-up), and backlog 213 closes with feature 41.
- Ruled intentional → the ruling is recorded in every README registry; until either, no #9 test or document cites `saga.md` §2 as `credit.release`'s source (213 acceptance 2) — feature 41's brief says so.
