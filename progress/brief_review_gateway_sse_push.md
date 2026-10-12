# Brief — reviewer, feature 26 `gateway_sse_push` (phase 13, full group, round 1) + backlog 215 item 1

**Task:** approve or reject feature 26 (`in_review`) and check backlog 215's acceptance item 1 (the status enumeration). Inputs: `progress/impl_gateway_sse_push.md` (277 lines; §3 decisions, §9 the enumeration, §14 – §15 surprises and gaps first), its brief `progress/brief_impl_gateway_sse_push.md` (Must-hold = your checklist, with `feature_list.json` id 26's three acceptance items and id 215's item 1), the premise check `progress/premise_impl_gateway_sse_push.md`, and the working tree (features 25, 40, 41 are `done` and uncommitted in the same tree; review feature 26's change: `services/gateway/**` since feature 25, `tests/architecture/test_composition_env_reads.py`'s one line, `specs/shared/test-matrix.md` R55's column 5). CLAUDE.md on disk is binding.

## Already decided by the leader

- **Overflow policy — disconnect and resume, not #8's drop-oldest** (record §3): accepted. `openapi.yaml` `/orders/stream` allows a frame to repeat after a reconnect, never to go missing; drop-oldest lets `Last-Event-ID` step over an undelivered frame. Review that the implementation delivers that property, not whether to have it.
- **`.env.example`** gained the three `GATEWAY_SSE_*` settings (leader edit); check each is a `validation_alias` in `infrastructure/settings.py`.
- **The `test_composition_env_reads.py` line** (`SseSettings`) is inside the brief's bounds.

## Where to push hardest

1. **Teardown, three ways** (#8 D1): delete the unsubscribe; do not propagate the disconnect / cancellation into the read-and-ping loop; subscribe on a different hub instance — each must fail within a bounded time. Is the guard reached through a **real** client disconnect, not a unit-level `stop()`?
2. **The two gaps the implementer names** (§15): (a) the backpressure path — a client that stops reading while the pump is blocked in `send` — is driven by no test; is the overflow → disconnect → resume property itself (§3) proved end to end somewhere, and does deleting the overflow branch, or making `publish` wait, fail a test? (b) ledger rows 11 (subscribe before the snapshot) and 12 (an empty `Last-Event-ID`) have no guard — is "no guard owed" justified, and could subscribe-after-snapshot lose a frame between snapshot and subscription? Decide whether either gap is blocking.
3. **Heartbeat, strong form** (acceptance 2): deleting the ping must fail because the relay's idle timeout closes the connection — not because of the client's own read timeout (record §14 says an earlier draft failed for the wrong reason; re-arm it). `ping` and `stream.ready` carry no `id`.
4. **Reconnect** (acceptance 1): cursor in the middle of the buffer, evicted cursor → `resumed: false`, fixture ids that differ from every plausible wrong order (Phase 12 R50; feature 40's sibling-column lesson); `?orderId=` with interleaved orders.
5. **The frame writer** (raw ASGI, not `StreamingResponse`): the `text/event-stream` header without `charset`; a multi-line payload refused (E2); `Cache-Control: no-cache`; `401` without a token, and the route census still derives `/orders/stream` as protected.
6. **The NATS subscriber task**: owned by the lifespan, awaited on shutdown, a dead task takes `/health/ready` down (`streamSignals`). **Shutdown with an open stream takes 5.2 s** (`GRACEFUL_SHUTDOWN_SECONDS = 5`, uvicorn waits for open responses): acceptable, or a defect against CLAUDE.md's task rules? Is the cancelled stream's `Exception in ASGI application` log noise an ERROR line in tests?
7. **R55's subscriber leg end to end** through the real Projector and the real Gateway; corrupt one field in the Projector-to-frame path and confirm the end-to-end test fails.
8. **Backlog 215 item 1** (§9 and `services/gateway/tests/unit/test_gateway_status_population.py`): is the population derived (four doors) and complete — plant a new status source (a new `raise` mapped to an undeclared status; a new `RpcError` code row) and confirm the test fails naming the pair; is each classification right (spot-check the #9-only `502 UPSTREAM_PROTOCOL_ERROR` claim against #7 / #8 with your own `grep`, and what #7 and #8 answer for a malformed responder reply)?

## Process

Arm on copies in `.arm/r26/` (backup + `sha256`, `cmp` restore, clear caches; a timeout kills the process group — note §14: a request to `/orders/stream` through `httpx.ASGITransport` hangs, bound every one). Read-only: no source or test edit, no index-writing git command. Run `./quality.sh` once at the end (developer stack down): exit code, pytest time and pass count (implementer: 4 757 passed).

## Output

`progress/review_gateway_sse_push.md`: verdict; blocking findings (surviving mutation + remedy); non-blocking with a disposition; your arming table; #8 D1, R2-1, the strong-form heartbeat, #7's false-equivalence finding avoided / recurred; a short verdict on backlog 215 item 1. APPROVED → feature 26 `done`; REJECTED → `in_progress` (that line only; leave 215 `pending` either way — its item 2 is the leader's). Return only "result in `progress/review_gateway_sse_push.md`" plus the verdict and at most 4 lines.
