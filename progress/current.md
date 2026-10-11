# Current session

**Feature:** none active — next phase 13 (Gateway / BFF): `orders_catalog_responder` (id 40), `orders_cancel_responder` (id 41) with backlog 213, `gateway_rest_auth` (id 25), `gateway_sse_push` (id 26)
**Status:** Phase 12 closed and committed at the full wrap-up (2026-10-11); Phase 13 not started
**Session started:** —

## Goal

## Decisions taken this session

## Blockers

## Notes

**Resume point:** Phase 12 is done: feature 24 `projector_read_model`, backlog 214 and `SA-6` are committed (`git log`; SA-6 also in #7 and #8). Phase 13 starts in a **fresh session** (CLAUDE.md, one session per phase) from this file. The `otcpy` developer stack is **stopped** except `otcpy-n8n`; restart it with `docker compose -p otcpy -f docker-compose.infra.yml start` when a live check needs it.

**Live dev data, read before any live walkthrough:** the registers of altered live fixtures are in `progress/impl_billing_credit.md` §8 (K5), `progress/impl_billing_invoicing.md` (K section), `progress/impl_billing_remittance_intake.md` §9 (K5), `progress/impl_notifications_service.md` §11 and `progress/impl_projector_read_model.md` §9. `ORD-000008`, `ORD-000010`, `ORD-000011` and `ORD-000013` are `completed`; `ORD-000009` and `ORD-000012` are `cancelled`; `ORD-000007` is stalled at `confirmed` in Orders but **projects `despatched`** (a hand-sent Phase 9 `despatch.create` put its `order.despatched.v1` on the topic; correct per R52; do not use it); throwaway `ORD-000090` exists only in Billing's ledger. The three fact topics hold **24 extra copies of 8 events** (Phase 11's redelivery; counted by the Phase 12 walkthrough). The `projector` and `notifications` consumer groups have committed offsets; the read model holds the seeded documents plus every live order.

**Brief for phase 13 — Gateway / BFF (Plan step 18).** Five pending entries carry `"phase": 13` (count: `python3 -c "import json;print([(f['id'],f['name']) for f in json.load(open('feature_list.json'))['features'] if f.get('phase')==13 and f['status']!='done'])"`): **40** `orders_catalog_responder` (`sdd: false`, 2 items), **41** `orders_cancel_responder` (`sdd: false`, 5 items; SA-4 release ordering, SA-2 note end to end), **213** `saga_command_table_lacks_credit_release` (attached to 41: an `SA-7` proposal for `saga.md` §2's missing `credit.release` row, or a recorded ruling), **25** `gateway_rest_auth` (`sdd: false`, 8 items — count them before quoting; items 5 – 8 are carried: feature 43's registration guard, the payment `x-correlation-id` = order id, the payment `RpcError` → HTTP mapping of `openapi.yaml:673-675`, and Phase 12's lambda-handler residual of the registration guard), **26** `gateway_sse_push` (`sdd: false`, 3 items). None is `sdd: true`, so no spec gate — but 41 and 25 are **full group** (saga, wire contract, security): implementer → Opus reviewer, premise-checked briefs.

- **Order:** #7 and #8 both ran 40 → 41 → 25 → 26 (#8 `../order-to-cash-dotnet/progress/history.md` lines 1684, 1707, 1734, 1765; #7 `../order-to-cash-nestjs/progress/history.md` lines 1067, 1075, 1013, 1037 — #7 ran 25 and 26 first). Decide the order from the dependencies (25 serves 40's and 41's routes; 26 subscribes to the Projector's signal), not from either predecessor.
- **What #9 already has:** `services/gateway/` is a skeleton (empty layers, `tests/test_gateway_health.py`). The Projector's hand-over to the Gateway is `specs/projector_read_model/design.md` §7 (feature 25: read `order_timeline` excluding `statusRank`, `processedEventKeys`, `timelineOrderVersion` (`PR33`); placeholders appear in the list; no document → `202 ProjectionPending`; feature 26: subscribe `readmodel.order.updated.*` / `readmodel.timeline.appended.*`, at-most-once, payloads the generated `OrderStreamUpdate` / `TimelineStreamEntry`). R54's and R55's Gateway halves close in 25 / 26 (their rows stay `TODO` until then, ratified at the Phase 12 gate).
- **Process lessons from Phase 12, for every brief:**
  - **A guard whose population is n = 1 at the service under test must be armed at n = 1.** The registration guard passed every shape at n = 2 and lost twice at the Projector's one registration. Feature 25 joins that guard: arm it against the Gateway's real root at its real n, and decide the lambda-handler residual it now carries.
  - **A fixture's order must differ from every plausible wrong order, not only from the right one** (R50: ids in time order, then in exact reverse order, each passed a wrong sort).
  - **An exit code from a detached process says nothing** (`setsid` returned 0 in 0 s while `quality.sh` ran on): wait on the real PID; read the verdict from the log.
  - **Stall watches:** a background `while` loop survives `pkill -f` on its own text; stop it with `TaskStop`, or don't start one.
  - **After a second rejection, propose a scoped round with a stopping rule written first** — the maintainer approved exactly that shape in Phase 12.
  - Phase 11's lessons still apply (bounded waits with `asyncio.timeout`, name the restart, ledger file:line on both halves, new settings into `.env.example` by the leader, counts from a command).
- **`quality.sh` reference:** ~360 s (maintainer, Phase 9 gate); **491.63 s inside pytest, ≈500 s wall at the Phase 12 wrap-up** (4 089 passed), for the maintainer to re-baseline or not.
- **Carried into later features (read them when those features open):** feature **27** owns Notifications' dead-letter and retry (#8 ids 74, 75, 94, 104), the Projector's two items from Phase 12 (fact consumers starting from `earliest` on private topics or committed to the end; re-run the Projector's `I4-commit-before-handler` and `PR38` arms after the retry wrapper), and the Orders saga items; feature **29** owns the "caused by" UI claim per the G1 ruling (backlog 201 acceptance 2).
- **Accepted, with a re-open trigger:** feature 18's N3, feature 20's O1, feature 19's N3 (unchanged); Phase 12's: the unreachable `DuplicateKeyError` retry, the never-binding `$min` cap, the redundant `$sortArray` (record `progress/impl_projector_read_model.md` §4.2), the review's N1, N2, N6, N7, N8 (`progress/review_projector_read_model.md`).
- **Commits:** one per feature; an `SA-7` (if 213 takes the amendment) on its own, in all three repositories.

---

## Template (reset to this on session close)

```markdown
# Current session

**Feature:** `<name>` (id <n>, phase <n>)
**Status:** <status>
**Session started:** <date>

## Goal

## Decisions taken this session

## Blockers

## Notes
```
