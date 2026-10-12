# Review: feature 26 `gateway_sse_push` (phase 13, full group, round 1) and backlog 215 item 1

Reviewer: Claude (Opus 5.5), 2026-10-12. Inputs: `progress/brief_review_gateway_sse_push.md`, `progress/impl_gateway_sse_push.md`, `progress/brief_impl_gateway_sse_push.md`, `progress/premise_impl_gateway_sse_push.md`, the working tree (feature 26's half of `services/gateway/**`, `tests/architecture/test_composition_env_reads.py`, `specs/shared/test-matrix.md` R55 column 5).

## Verdict: REJECTED

The stream itself is sound: the teardown, the heartbeat (strong form), reconnect, the filter, headers, auth and the subscriber lifecycle all hold under my own arms (table below), `quality.sh` is green, and the backpressure path that §15 left untested holds under a probe. The rejection is for three things that are cheap to fix and that this review must not wave through:

1. **Ledger row 11 claims "cannot be armed", and that is false.** The property it covers (no frame lost between the replay snapshot and the subscription) is hand-built and has no guard. This is #8's R2-1 recurring in kind.
2. **The route test named for the overflow → disconnect → resume property does not test that property.** It stays green under a gap-introducing mutation, and it contains a vacuous assertion.
3. **Backlog 215 item 1's completeness argument fails in two places**, and one classification leaves out the #7/#8 fact the leader's `SA-n` proposal needs.

`feature_list.json` id 26 is set back to `in_progress`. Backlog 215 stays `pending` (its item 2 is the leader's).

## Blocking findings

### B1. Ledger row 11 (subscribe before the snapshot): "none, and it cannot be armed" is false; the property is unguarded

- **Where:** `progress/impl_gateway_sse_push.md` §4 row 11 and §15. The code is `services/gateway/src/otc_gateway/presentation/event_stream.py:70` (subscribe), `:100` (snapshot) and `:105` (the `stream.ready` write, an `await`).
- **Mutation R11:** the subscription is created unregistered at `:70` and added to the hub only after the `stream.ready` write at `:105`. That is "snapshot, then `await`, then subscribe", the order #8's `StreamEndpoints.cs:67-77` comment names as the one that loses a frame. Every test in the 8 Gateway SSE / population files stays green: `73 passed in 7.55s` (`.arm/r26/batch3b.out`, arm `R11a`).
- **The guard can be written in 20 lines.** An ASGI-level test whose `send` hook publishes a frame while `stream.ready` is being written fails under R11 in 10 s: `Failed: stream.ready and the frame published while it was written: 1 of 2 frames within 10.0 s` (arm `R11b`). The same probe passes on the restored code. It was a temporary file (`.arm/r26/test_zz_r26_probe.py`), copied in for the run and then removed: `ls services/gateway/tests/unit | grep -c zz` gives `0`.
- **Why it matters:** under that mutation the lost frame is neither replayed nor delivered live. The client's next `Last-Event-ID` then steps over it, which is exactly the at-least-once breach §3 rejected drop-oldest for. The property is hand-built, so CLAUDE.md requires a named, armed guard.
- **Remedy:**
  - Commit a guard in `test_gateway_sse_route.py`: publish during the `stream.ready` write and assert the frame arrives.
  - Add a resume variant, with `Last-Event-ID` set and a frame published inside the window. It must arrive at least once; a duplicate is allowed.
  - Arm both with R11.
  - Correct row 12 of the record and §11's R2-1 line ("avoided" → recurred in kind, then fixed).

### B2. `test_r55_a_client_that_falls_behind_is_disconnected_and_resumes_without_a_gap` does not test "without a gap"

- **Where:** `services/gateway/tests/unit/test_gateway_sse_route.py:340-376`.
  - The slow client receives **zero** content frames: the queue is cleared on overflow (`hub.py:127-129`).
  - The test then resumes from `published[0].cursor`, a frame that client never received, and asserts `published[1:]`.
  - The first `resumed` stream is dead code, kept alive only by the vacuous `assert resumed is not None`.
  - The hub test's `seen_by_slow = frames[0]` (`test_gateway_sse_hub.py:139`) states the same falsehood.
- **Mutation O1** (drop the oldest queued frame, deliver the newer ones, then end, which loses frames): the route test **passes** (`1 passed`, arm `O1a`). Only the hub unit test catches it, at `test_gateway_sse_hub.py:136` (`assert StreamFrame(...) is None`, arm `O1b`).
- **What is proved, and what is not:** the property is held at unit level, so the code is not wrong. But the brief's question, whether overflow → disconnect → resume is proved end to end, is answered *no*, and the test's name claims it is.
- **Remedy:**
  - Rewrite the test. The slow client reads k ≥ 1 content frames; a burst overflows its queue; the response ends.
  - Reconnect with the id of the **last frame the client actually received**, and assert received + replayed == published exactly: no gap, no duplicate.
  - Delete the dead stream and the vacuous assertion, and fix the hub test's comment.
  - Arm with O1 (it must now fail the route test) and with D2.

### B3. Backlog 215 item 1: the population is not complete, and the "why it is complete" argument fails in two places

- **(a) The handler door is keyed by (file, exception class), not by (raise site, operation).** `HANDLER_RAISES` / `HANDLER_OPERATIONS` (`test_gateway_status_population.py:137-166`) let a new raise of an already-listed class in an already-listed file go unseen, even when it sits in another operation's handler.
  - Plant ST1: `if query.order_filter.page > 1000: raise GatewayNotFoundError(...)` in `ListOrdersHandler.handle` (`application/order_queries.py:22`). That makes the undeclared pair `(GET /orders, 404)` reachable.
  - Result: the population file stays green, `5 passed` (arm `ST1`).
  - A new raise of an unlisted class *is* caught (arm `ST2`, `{'stock_handlers.py': {'LookupError'}}`). A changed `RpcError` row is caught and named pair by pair (arm `ST3`, `('GET', '/catalog/products', 410)` …).
- **(b) The "no runtime" door skips the stream** (`operations - {STREAM}`, line ~322). Probe `.arm/r26/cold_stream.py`: `GET /orders/stream` with a bearer and no runtime answers `status 503 ... "code":"UPSTREAM_UN…`. So `(GET /orders/stream, 503)` is a reachable, undeclared pair in the record's own "reachable only without a lifespan" class, and it is missing. The totals become 100 observed / 34 Gateway-originated / 4 lifespan-only.
- **(c) The `502 UPSTREAM_PROTOCOL_ERROR` classification as #9-only is right, but it leaves out what #7 and #8 answer for the same input.** Both map a malformed responder reply to `RpcTransportError` with code `UNAVAILABLE`, which is a **503** (declared on most of these operations):
  - #7: `order-to-cash-nestjs/apps/gateway/src/infrastructure/messaging/nats-rpc-client.adapter.ts:84-85` and `application/ports/rpc-client.port.ts:49-50`.
  - #8: `order-to-cash-dotnet/src/Gateway/Infrastructure/Messaging/NatsRpcClient.cs:82-84` and `Application/Ports/IRpcClient.cs:48-52`.

  So this is a cross-build status divergence, not only an undeclared code. The leader's `SA-n` proposal has to choose between "declare 502 in all three" and "map to 503 for parity". My `grep -rIn "UPSTREAM_PROTOCOL_ERROR\|502\|BadGateway\|Status502"` over both Gateways returned no hits, which confirms the implementer's absence claim.
- **Remedy:**
  - Derive the handler door per raise site. Options: execute it; or have an AST pass map each `raise` to its enclosing handler class → message → route; or key the literal by (file, handler, exception).
  - Arm the new door with ST1.
  - Drive the stream through the cold door (bounded, through `asgi_stream`).
  - Add (c)'s citations to §9 and update the counts.

## Non-blocking findings (each with a disposition)

| # | Finding | Evidence | Disposition |
|---|---|---|---|
| N1 | **Shutdown with open streams.** It takes ~5.2 s, and uvicorn logs at ERROR: `Cancel N running task(s), timeout graceful shutdown exceeded`, then one `Exception in ASGI application … CancelledError: Task cancelled, timeout graceful shutdown exceeded` traceback per open stream. **Not a breach of CLAUDE.md's task rules**: each connection's tasks are cancelled and awaited in `__call__`'s `finally` (`event_stream.py:76-81`), cancellation is never caught, and the subscriber is stopped before the NATS drain (E4). It is a bounded, documented stop. | My integration run (`.arm/r26/integ_baseline.log:459-576`, captured stderr of `test_r55_stopping_the_server_with_streams_open…`): the ERROR lines appear in tests and fail nothing. Mechanism: `uvicorn/server.py:299-307` cancels after the graceful bound; `h11_impl`/`httptools_impl.run_asgi:424-427` logs every `BaseException` at ERROR. | **ACCEPTED, NOT FIXED** for feature 26. Re-open trigger: feature 27 `observability_reliability`, the feature that builds the log contract (structlog JSON, uvicorn's loggers). The leader should attach an acceptance item to 27: "an SSE stream open at shutdown produces no ERROR line: the Gateway ends its streams on the exit signal, or the log contract classifies uvicorn's cancellation line". That is the half that depends on code not yet built. |
| N2 | The end-to-end test checks `eventId`, `orderId`, schema validity and the last `status`, but not the payload bytes. A relay corruption of `occurredAt` passes it. | Arm `P2e`: `1 passed in 8.13s`. The same corruption **is** caught by `test_r55_a_signal_published_on_nats…` (exact bytes, arm `P2i`). A `status` corruption fails the end-to-end test (arm `P3e`: `'paid' == 'completed'`), and so does dropping one fact's timeline frame (arm `P4e`: `17 frames within 90.0 s for 9 facts`). For `timeline.appended`, the only exact-bytes check on the relay path is the unit fixture `'{"t":1}'`. | Fix in the same round (cheap): the end-to-end test also subscribes to `readmodel.>` and asserts each frame's `data` equals the bytes the Projector published, for both event types. |
| N3 | `SseSettings` allows queue capacity == buffer capacity. At equality, or with frames arriving during the reconnect, an overflowed client's cursor can be evicted, which gives `resumed: false`. That is legal under the contract (the client re-fetches), but §3's "the resume is complete" holds only while queue + reconnect-window frames < buffer. | `hub.py:127-129`, `settings.py:196`; defaults 256/500 leave a margin of 243 | Accept; correct the wording in §3 of the record. |
| N4 | The backpressure path (§15a) has no committed test. My probe, against a real uvicorn: a client with `SO_RCVBUF` 4096 stops reading while 4 000 × 4 KB frames are published. Result: worst `publish` 0.028 ms, the subscription `overflowed=True` with 0 queued, held while connected, released 0.01 s after the socket closes. While the pump is blocked in `send`, an overflowed stream does not end until the client leaves. That is harmless, because the client is not reading. | `.arm/r26/test_zz_r26_backpressure.py` (temporary, removed after the run) | Property holds. Recommended, not required: commit the probe as a test. |
| N5 | Ledger row 12: "only the echoed cursor differs" is inaccurate for #9's own code. `event_stream.py:101` mints a cursor for `""` whether or not `or None` is there, so an empty header is unobservable. | Code reading | No guard owed; correct the wording. |
| N6 | `domain/sse/cursor.py:11` cites `tests/unit/test_gateway_sse_cursor.py`, which does not exist (the tests are in `test_gateway_sse_domain.py`). | `ls services/gateway/tests/unit \| grep -i cursor` → nothing | Fix the reference. |

## Arming table (reviewer's own; harness `.arm/r26/arm.py`: backup + `sha256`, mutate, run the named test with the process group killed on timeout, restore by `cp`, `cmp`, clear `.pyc`)

| Arm | File | Mutation | Test | Result (verbatim) | Time | sha256 (16) | cmp |
|---|---|---|---|---|---|---|---|
| T1 | event_stream.py | delete `self._hub.unsubscribe(subscription)` | teardown › `…closes_its_tcp_connection…` (real uvicorn, TCP close) | `Failed: a closed TCP connection: 1 subscription(s) still on the publisher's hub 2.0 s after the client left` | 2.3 s | 2992380c49eed1f6 | identical |
| T2 | event_stream.py | wait on `{pump}` only (disconnect not watched) | same | same message | 4.3 s | 2992380c49eed1f6 | identical |
| T4 | event_stream.py | cancel only the watcher (the disconnect is not propagated into the pump) | same | same message | 4.3 s | 2992380c49eed1f6 | identical |
| T3 | routes_stream.py | subscribe on a fresh `StreamHub`, not the publisher's | same | `AssertionError: the open stream is not subscribed on the publisher's hub` | 0.2 s | 0dd34fcb57362673 | identical |
| H1 | event_stream.py | delete the ping write | heartbeat › strong form | `Failed: a frame while the relay's 0.5 s idle window runs: the server closed the connection` (the relay closed it at 0.5 s; the client's own bound is 2.0 s) | 0.7 s | 2992380c49eed1f6 | identical |
| H2 | event_stream.py | `ping` with a minted `id:` | `…ping_carries_no_id…` | `AssertionError: a frame other than content carries an id: line` | 0.3 s | 2992380c49eed1f6 | identical |
| H3 | event_stream.py | `stream.ready` with `id:` | `…stream_ready_is_the_first_frame…` | `AssertionError: stream.ready carries no id: its cursor must never become a resume point` | 0.1 s | 2992380c49eed1f6 | identical |
| C1 | replay_buffer.py | `entries[position:]` | `…reconnect_resumes_strictly_after…` | `AssertionError: the reconnect did not replay exactly the frames after Last-Event-ID (10, 11, 12)` | <1 s | a3c4b84571e187fa | identical |
| C2 | replay_buffer.py | `entries[position + 2 :]` (skips one) | same | `Failed: ready and the three missed frames: 3 of 4 frames within 10.0 s` | 10.1 s | a3c4b84571e187fa | identical |
| C3 | replay_buffer.py | unknown/evicted cursor → `resumed=True` + whole buffer | `…an_evicted_last_event_id_is_resumed_false` | `assert True is False` (`test_gateway_sse_route.py:337`) | 0.1 s | a3c4b84571e187fa | identical |
| F1 | event_stream.py | `_matches` → `True` | `…order_id_restricts_the_live_stream…` | `AssertionError: ?orderId= did not restrict the live stream to the one order` | <1 s | 2992380c49eed1f6 | identical |
| O1a | hub.py | on overflow drop the oldest, keep the newer frames, then end (**loses frames**) | route › `…falls_behind…resumes_without_a_gap` | **SURVIVED: `1 passed`** (B2) | 0.04 s | 891fb200b82783f4 | identical |
| O1b | hub.py | same | `test_gateway_sse_hub.py` | `AssertionError: assert StreamFrame(cursor='1755511234567-2', …) is None` (line 136) | 0.1 s | 891fb200b82783f4 | identical |
| O2 | event_stream.py | overflow does not end the response | route › `…falls_behind…` | `Failed: an overflowed stream: the response did not end within 10.0 s` | 10.2 s | 2992380c49eed1f6 | identical |
| P1 | event_stream.py | live `data` with `occurredAt` corrupted (`2…` → `1…`) | `…live_frames_carry…exact_data` | `assert [(…)] == [(…)]  At index 0 diff: (… "occurredAt":"1026-08-18T10:15:02.100Z"}')` | 0.1 s | 2992380c49eed1f6 | identical |
| P2u | stream_signal_subscriber.py | relay corrupts `occurredAt` | `test_gateway_sse_signal_subscriber.py` | survived, `19 passed` (fixtures carry no `occurredAt`; see P2i) | 0.3 s | 85909227a0e6fb16 | identical |
| P2i | stream_signal_subscriber.py | same | integration › `…signal_published_on_nats…` (real NATS) | `AssertionError: the data line is not the Projector's exact bytes` | 4.6 s | 85909227a0e6fb16 | identical |
| P2e | stream_signal_subscriber.py | same | integration › end-to-end through the real Projector | **survived, `1 passed in 8.13s`** (N2) | 8.1 s | 85909227a0e6fb16 | identical |
| P3e | stream_signal_subscriber.py | relay rewrites `"status":"completed"` → `"paid"` | end-to-end | `AssertionError: the last signal is the final document  assert 'paid' == 'completed'` | 9.6 s | 85909227a0e6fb16 | identical |
| P4e | stream_signal_subscriber.py | relay drops the `stock.reserved` timeline frame | end-to-end | `Failed: R55: 17 frames within 90.0 s for 9 facts (…)` | 98 s (the test's own 90 s bound) | 85909227a0e6fb16 | identical |
| S1 | stream_signal_subscriber.py | `ORDER_UPDATED_SUBJECT` → the timeline subject (sibling) | subscriber unit file | `Failed: each subject feeds its own event type: 1 of 2 signals reached the hub` | 5.2 s | 85909227a0e6fb16 | identical |
| E3i | composition.py | drop `HealthCheck("streamSignals", …)` | integration › `…dead_subscriber_task_takes_readiness_down` | `KeyError: 'streamSignals'` | 4.6 s | 36c06c805c725912 | identical |
| R11a | event_stream.py | subscribe after the snapshot, across the `stream.ready` write | 8 files (route, teardown, heartbeat, hub, domain, subscriber, population, auth sweep) | **SURVIVED: `73 passed in 7.55s`** (B1) | 7.6 s | 2992380c49eed1f6 | identical |
| R11b | event_stream.py | same | reviewer probe (temporary) | `Failed: stream.ready and the frame published while it was written: 1 of 2 frames within 10.0 s` | 10.1 s | 2992380c49eed1f6 | identical |
| ST1 | order_queries.py | new `raise GatewayNotFoundError` in `ListOrdersHandler` (reachable `GET /orders 404`) | `test_gateway_status_population.py` | **SURVIVED: `5 passed`** (B3a) | 1.1 s | 21cc2a46a4aa3cd0 | identical |
| ST2 | stock_handlers.py | new `raise LookupError(...)` site | same | `AssertionError: a raise site under application/ is not in HANDLER_RAISES …  {'stock_handlers.py': {'LookupError'}}` | <1 s | 5d2ecfcfd279b079 | identical |
| ST3 | rpc_error_classification.py | `CONFLICT` → 410 | `…status_population_against_openapi` | `Extra items in the left set: ('GET', '/catalog/products', 410) ('POST', '/orders/{id}/cancel', 410) …` | <1 s | 2353e4ec9de3f0af | identical |

Logs: `.arm/r26/batch1.out`, `batch2.out`, `batch3b.out` (`batch3.out` is a discarded first R11 run whose mutation used the wrong queue capacity and failed for that reason; it is superseded), and per-arm `.arm/r26/<arm>.log`. After every arm `git status` showed no tracked file changed under `services/gateway`, and both temporary probe files are gone (`grep -c zz` → 0).

Defeat-list rows exercised by these arms:
- Row 1 (delete): T1, H1, F1, O2, E3i.
- Row 2 (corrupt a supplied field): P1, P2i/P2e, P3e, C2.
- Row 3 (sibling): T3, S1.
- Row 9 (premise stale): T3, which fails on the `subscriber_count == 1` premise.
- Row 12 (a path the population never drives): R11 and ST1, both surviving, and the backpressure probe (N4).

## Inherited findings: avoided or recurred

| Finding | Verdict | Evidence |
|---|---|---|
| **#8 D1** (teardown hand-built, unguarded) | **Avoided.** | Armed three ways through a **real TCP close** under a real uvicorn: T1 (delete the unsubscribe), T2/T4 (disconnect not watched / not propagated into the pump), T3 (another hub). Each fails at the 2.0 s bound, with a 30 s ping, so no ping can be what notices. |
| **#8 R2-1** (a ledger row whose stated evidence cannot fire) | **Recurred in kind** (B1). | Row 11 states "cannot be armed"; R11a/R11b show both that the property is unguarded and that a guard can be written. Row 10 (subscriber stop before drain) is genuinely observable (E4). |
| **Strong-form heartbeat** | **Met.** | H1: the relay closes the connection at its 0.5 s idle window (the client's per-frame bound is 2.0 s), and the message names the server-side close. The control test proves the relay closes a quiet stream. §14's earlier wrong-reason failure does not recur. |
| **#7's false-equivalence finding** | **Avoided.** | `grep -rn -i "equivalent\|the same as\|identical to\|stand-in\|as the dev\|like the real"` over the Gateway tests, `__main__.py` and `event_stream.py` finds 6 hits. None is an unproven equivalence: the relay "stand-in" is backed by its control test; the end-to-end test's "the body of its lifespan" is true (`otc_projector/main.py:26` calls `start_runtime`, as `otc_gateway/main.py:24` does); the rest are about previous builds' tests or explicitly disclaim substitution. |
| `ping` / `stream.ready` carry no `id` | **Guarded.** | H2, H3 |
| Reconnect (middle cursor, evicted, ids that differ from wrong orders) | **Guarded.** | C1, C2 (string order `-10` < `-9`), C3; `?orderId=` with A1 B1 A2 B2 A3 (F1) |

## `R<n>` → test mapping verified

Feature 26 proves **R55's subscriber leg** only. R55 stays NOT YET GREEN (the web half is feature 29), and the matrix row says so.

- Every one of the 7 test names cited in R55's column 5 exists. Each was checked with `grep -rl "def <name>"`, one hit apiece.
- The summary counts: 46 → 48 DONE comes from R54 and R63 (feature 25's), not from R55. Feature 26 changed only R55's cell.

Acceptance 1 → `test_r55_a_reconnect_resumes_strictly_after…` (C1, C2), `…unknown…` and `…evicted…` (C3); the overflow-and-resume half is B2.
Acceptance 2 → `test_r55_the_connection_outlives_an_idle_timeout_because_of_the_heartbeat` (H1) + control.
Acceptance 3 → `test_r55_a_client_that_closes_its_tcp_connection_releases_the_subscription` (T1 – T4) and the ASGI variant.

## `CHECKPOINTS.md` (boxes applicable to this review)

- [x] C1: the harness files and agents exist (not re-run beyond what `quality.sh` covers).
- [x] C2: one feature `in_progress` after this edit (26); the statuses are valid.
- [x] C3 domain purity: `lint-imports` 13 kept, 0 broken (`quality.sh`). `domain/sse/*` imports only `collections`/`dataclasses`.
- [x] C3: no cross-service imports (independence contract kept); no new shared runtime code; no money arithmetic touched. The one `/` is `ping_interval_ms / 1000` (seconds, not money).
- [x] C3: Kafka-fact / NATS-RPC classification. The update signal is NATS core publish/subscribe, which is the Projector design's §7 hand-over, not RPC; no Kafka in the Gateway.
- [x] C4: `./quality.sh` exit 0, developer stack down (`docker ps` = `otcpy-n8n` only): ruff format/check clean, `mypy --strict` no issues in 838 files, **4757 passed in 647.55 s**, total coverage 97.61 %, domain 98 %, wall clock 11 m 13 s. The pass count matches the implementer's 4 757; the time is +42 s on their 605 s.
- [x] C4: the integration tests use the testcontainers servers (the SSE integration file ran green with the developer stack down: `5 passed in 11.53s`).
- [x] C4: no Jest/Karma/Jasmine introduced.
- [ ] C4: "tests are real" fails on B2 (a test that does not test its name, with a vacuous assertion).
- [x] C6: n/a (`sdd: false`); the ledger is in the impl record as CLAUDE.md requires for `sdd: false`.
- [x] C7: `specs/shared/` byte-identical to #7 and #8 except `test-matrix.md` (`cmp` over `asyncapi.yaml`, `domain-model.md`, `n8n-workflows.md`, `openapi.yaml`, `requirements.md`, `saga.md`: all `same8 same7`).
- [ ] C7: every inherited finding accounted for. R2-1 is recorded as avoided but recurred (B1).

Settings: `GATEWAY_SSE_BUFFER_CAPACITY`, `GATEWAY_SSE_PING_INTERVAL_MS` and `GATEWAY_SSE_CLIENT_QUEUE_CAPACITY` are each a `validation_alias` in `infrastructure/settings.py:185-190` and present in `.env.example:257,258,261`. The `test_composition_env_reads.py` change is the one `"SseSettings"` entry.

## Backlog 215 item 1: verdict

**Not met yet** (B3).
- Most of it holds: the four-door derivation by execution is the right instrument; the RPC-row door (ST3) and the unlisted-class door (ST2) fire and name what moved.
- Two parts do not: the handler door misses a new raise site of a listed class in another operation's handler (ST1), and the cold door skips the stream (`GET /orders/stream 503`).
- The 502 row is correctly #9-only, but #7 and #8 answer **503** for the same malformed reply (citations in B3c). That belongs in the record, because it turns the leader's `SA-n` question into "declare 502, or restore parity with 503".
- The `SA-n` proposal (item 2) stays the leader's. Nothing here is narrated as "the next feature".

## What must change before re-review

1. **B1:**
   - Commit and arm (R11) a guard that a frame published between the snapshot and the first live read is delivered, both fresh and resumed.
   - Correct ledger row 11, §11's R2-1 line, and §15.
2. **B2:**
   - Rewrite `test_r55_a_client_that_falls_behind…` so the client receives k ≥ 1 frames, overflows, and resumes from its own last received id: received + replayed == published.
   - Remove the dead `resumed` stream and `assert resumed is not None`, and fix `test_gateway_sse_hub.py:139`'s comment.
   - Arm with O1 (it must fail the route test) and D2.
3. **B3:**
   - Make the handler door per raise site and arm it with ST1.
   - Drive the stream through the cold door.
   - Add the #7/#8 503 citations to §9 and update the counts.
4. **In the same round (cheap):**
   - N2: the end-to-end test compares frame bytes with the Projector's published bytes.
   - N3, N5: wording.
   - N6: the dangling test reference.
5. **Leader:** attach N1's acceptance item to feature 27.

Process note: I did not re-run the full suite beyond the one `quality.sh` the brief asks for. I ran the 66 SSE/population unit tests and the 5 SSE integration tests on the unmodified tree, plus the 27 arms and 3 probes above.

---

# Round 2 (re-review of B1, B2, B3, N2, N3, N5, N6 only)

Reviewer: Claude (Opus 5.5), 2026-10-12. Scope fixed by round 1's "What must change before re-review"; nothing else re-walked. Inputs: this file (round 1), `progress/impl_gateway_sse_push.md` "Round 2", `progress/brief_impl_gateway_sse_push_round2.md`, the working tree. Item 5 (N1 → feature 27) is the leader's and is not re-checked here.

## Verdict: APPROVED

All three blockers are closed and my own round-1 mutations now fail the named tests fast, on every path the round asked for. One small literal inaccuracy (R2-N1) gets a light disposition below; it does not block.

**What I ran instead of the full suite:** I did not re-run `quality.sh`; the implementer's run is `.arm/n26r2/quality.log` (exit 0, 4 760 passed in 571.65 s). What I ran: a baseline of the 4 touched unit files (`45 passed in 2.21s`); 13 arms (below); after every restore, a green run of the 7 SSE/population unit files plus the SSE integration file (`74 passed in 19.27s`, developer stack down, `docker ps` = `otcpy-n8n` only); `ruff check` / `ruff format --check services/gateway` clean; `mypy --strict` over the 4 touched test files, no issues.

## Arming table (reviewer's own; harness `.arm/r26r2/arm.py`, the round-1 harness repointed: backup + `sha256`, mutate, ONE named test, process group killed on timeout, restore by `cp`, `cmp`, `.pyc` cleared; logs `.arm/r26r2/batch1.out`, `batch2.out`, per-arm `.log`)

| Arm | File | Mutation | Test | Result (verbatim) | Time | sha256 (16) | cmp |
|---|---|---|---|---|---|---|---|
| R11 | event_stream.py | **my round-1 R11, unchanged:** subscription created unregistered, added to the hub after the `stream.ready` write | `…delivered_on_a_fresh_connection[start]` | `Failed: stream.ready and the frame published in the start write: 1 of 2 frames within 3 s` | 3.1 s | 2992380c49eed1f6 | identical |
| R11 | same | same | `…fresh_connection[ready]` | `Failed: stream.ready and the frame published in the ready write: 1 of 2 frames within 3 s` | 3.1 s | 2992380c49eed1f6 | identical |
| R11 | same | same | `…delivered_on_a_resumed_connection` | `Failed: ready, the two replayed frames and the frame published mid-write: 3 of 4 frames within 3 s` | 3.1 s | 2992380c49eed1f6 | identical |
| R11d | same | **new ordering, not in the implementer's set:** registered only after the replayed frames are written (just before the live loop) | resumed | `Failed: ready, the two replayed frames and the frame published mid-write: 3 of 4 frames within 3 s` | 3.1 s | 2992380c49eed1f6 | identical |
| O1 | hub.py | **my round-1 O1:** on overflow drop the oldest, keep the newer, then end | route `…falls_behind…without_a_gap` | `AssertionError: received + replayed is not exactly what was published: a gap or a duplicate` (`At index 2 diff: '5-5' != '5-4'`) | 1.6 s | 0e7f46dbc48abd9c | identical |
| D2 | hub.py | #8's policy: drop the oldest, never mark overflowed, never end | same | `Failed: an overflowed stream: the response did not end within 10.0 s` | 10.1 s | 0e7f46dbc48abd9c | identical |
| C1′ | replay_buffer.py | replay includes the cursor (`entries[position:]`, a duplicate) | same (B2) | `AssertionError: received + replayed is not exactly what was published…` (`At index 2 diff: '5-3' != '5-4'`) | 2.0 s | a3c4b84571e187fa | identical |
| C2′ | replay_buffer.py | replay skips one (`entries[position + 2 :]`, a gap) | same (B2) | `Failed: ready and the unseen frames: 8 of 9 frames within 10.0 s` | 10.1 s | a3c4b84571e187fa | identical |
| ST1 | order_queries.py | **my round-1 ST1:** `if query.order_filter.page > 1000: raise GatewayNotFoundError(...)` in `ListOrdersHandler.handle` | `test_gateway_status_population.py` | `AssertionError: a raise SITE under application/ is not in HANDLER_RAISE_SITES … ('order_queries.py', 'ListOrdersHandler.handle', 'GatewayNotFoundError')` (round 1: survived) | 1.6 s | 21cc2a46a4aa3cd0 | identical |
| ST9 | catalog_handlers.py | **planted by me (another file, another class, a listed exception class):** import `GatewayNotFoundError`, `raise` it in `ListRetailersHandler.handle` when the reply is empty | same | `… Extra items in the left set: ('catalog_handlers.py', 'ListRetailersHandler.handle', 'GatewayNotFoundError')` | 1.6 s | 5103c5a0eb6c8356 | identical |
| ST10 | the test's literal | drop `("GET", "/orders/stream", 503)` from `GATEWAY_ORIGINATED` | `…status_population_against_openapi` | `Extra items in the left set: ('GET', '/orders/stream', 503)` (`:510`) | 2.4 s | 141421b09cc627ad | identical |
| P2e | stream_signal_subscriber.py | **my round-1 P2e:** relay corrupts `occurredAt` | integration end-to-end (N2) | `AssertionError: order.updated: the frames' data lines are not the Projector's published bytes` (round 1: survived) | 10.0 s | 85909227a0e6fb16 | identical |
| P5e | same | **new:** relay corrupts `summary` on `timeline.appended` frames only | same | `AssertionError: timeline.appended: the frames' data lines are not the Projector's published bytes` | 10.1 s | 85909227a0e6fb16 | identical |

Mutation families: delete (D2, ST10), corrupt a supplied field (O1, C1′, C2′, P2e, P5e — the payload family on the wire, both event types), order/premise (R11 at three windows, R11d), a path the population never drove (ST1, ST9, the cold stream). `hub.py`'s sha differs from the implementer's O1/D2 backups (891fb200…) because N3 rewrote its docstring after those arms: `diff` of their backup against the current file is the docstring only, and my O1/D2 ran on the current file.

## B1 — closed

- Three guards exist and pass: `test_r55_a_frame_published_between_the_snapshot_and_the_first_live_read_is_delivered_on_a_fresh_connection[start]` / `[ready]` and `…_on_a_resumed_connection` (`services/gateway/tests/unit/test_gateway_sse_route.py:398-435`). The `on_send` hook (`services/gateway/tests/conftest.py:110-112`) publishes from inside the app's own write, so the frame lands in the exact window, and a hook that never fires fails by `IndexError` on `published[0]`, not silently.
- My R11 fails all three in 3.1 s (round 1: survived 73 tests; my probe took 10 s). R11d, an ordering the implementer did not build, fails the resumed test. Fresh and resumed both covered.
- Ledger row 11, §11's R2-1 line ("RECURRED in kind in round 1, fixed in round 2") and §15 are corrected (`progress/impl_gateway_sse_push.md:70`, `:223`, `:273`).

## B2 — closed

- The rewritten test (`test_gateway_sse_route.py:341-376`): the slow client reads k = 2 frames through `slow.frames` (frames the app actually sent); `leftovers` (`conftest.py:149-159`) adds only chunks the app sent before the response ended, read from the stream's own queue and never from the hub. `received = got + leftovers`, the cursor is `received[-1].id` (its own last received id), and `received ids + replayed ids == published cursors` exactly. On the real code `received` is the 2 read frames and the replay is the other 8 (C2′'s "8 of 9" counts ready + 8).
- My O1 now fails **the route test** (round 1: passed), and so do a duplicate (C1′) and a gap (C2′) in the resume itself; D2 fails on the "is disconnected" half.
- The dead `resumed` stream and `assert resumed is not None` are gone (`grep -n "resumed is not None" services/gateway/tests/unit/test_gateway_sse_route.py` → no output). The hub test no longer claims the slow client saw frame 0.

## B3 — closed (backlog 215 item 1: **met**)

- **(a) Per-raise-site door.** `HANDLER_RAISE_SITES` is keyed by (file, enclosing class.function, exception class), compared both ways with an AST walk (`test_gateway_status_population.py:412-446`), and a `raise` that is not `raise Name(...)` fails outright. My ST1 now fails naming the site; my ST9 (catalog file, retailers handler) fails naming it too.
- **(b) The cold stream.** `GET /orders/stream 503 <- ['no runtime']` is in my `-s` run (`.arm/r26r2/status_population.out:53`), driven through `asgi_stream` with a bounded `response_started`, and pinned by the source check at `:510` and the literal (ST10).
- **(c) Citations.** All four hold on disk: #8 `NatsRpcClient.cs:82-85` (`catch (JsonException) { throw new RpcTransportError(...) }`) and `IRpcClient.cs:47-53` (`Code => "UNAVAILABLE"`); #7 `nats-rpc-client.adapter.ts:84-85` and `rpc-client.port.ts:48-50` (`code = 'UNAVAILABLE'`).
- **§9 counts against the test's own output and literals** (python over `.arm/r26r2/status_population.out` and `ast.literal_eval` of the literals): observed 100; `UNDECLARED` 59; `GATEWAY_ORIGINATED` 34 (literal 34); `PASS_THROUGH` 25 (literal 25); declared 100 − 59 = 41; Gateway-originated `502` = 10; Gateway-originated `503` = 6, of which 4 lifespan-only (`/auth/me`, `/docs`, `POST /auth/login`, `/orders/stream`) and 2 deployable (`GET /orders`, `GET /orders/{id}`, read model unavailable); 34 − 4 = 30. Everything reconciles.
- **ST8's stated limit — acceptable as stated.** The population is pairs, and a pair is (operation, `classify(instance)`). A second raise of the same class in an already-listed function has the same operations by construction, and the same status as long as `classify` decides on the class alone. I checked that premise in `presentation/problems.py:93-145`: the only status that depends on instance fields is `RpcRemoteError`'s (by `code`), and no `RpcRemoteError` is raised under `application/` (`grep -n "raise " services/gateway/src/otc_gateway/application/*.py services/gateway/src/otc_gateway/application/*/*.py` → 10 hits, none `RpcRemoteError`; a first one would be a new site and fail). So it is a limit of the key, not a gap. It would become a gap only if `classify` began reading fields of a listed class.

## Non-blocking (round 2)

| # | Finding | Evidence | Disposition |
|---|---|---|---|
| R2-N1 | **`HANDLER_RAISE_SITES` over-attributes one site.** `("order_views.py", "order_summary", "IncompleteOrderHeaderError")` maps to `[GET /orders, GET /orders/{id}]`. But `order_summary` is called only from `ListOrdersHandler` (`order_queries.py:25`). `GetOrderHandler` uses `order_detail` (`:44`), which neither calls `order_summary` nor raises. No pair is wrong: `(GET /orders/{id}, 500)` is independently observed from `read model: unexpected` (`status_population.out:57`). Only the source label is false. It also shows the general limit of option 3, which I offered in round 1: the site → operations map is a hand literal, so a *new caller* of a listed helper from another operation's handler adds a pair with no new raise site. | `grep -rn "order_summary\|order_detail\|_order_reference_of" services/gateway/src/` → callers at `order_queries.py:25` (summary, list), `:44` (detail, get), `payment_handlers.py:42` (the private helper, payments only) | **Fix, light** (test-only, one entry): drop `("GET", "/orders/{id}")` from that entry, before the commit (`test_maintainer` or the implementer; the leader reads the diff and runs the file). **Helper-reuse limit: ACCEPTED, NOT FIXED.** Re-open trigger: a helper listed in `HANDLER_RAISE_SITES` (`order_summary`, `RegisterPaymentHandler._order_reference_of`) gains a caller in another handler. Today's callers are enumerated above. |
| R2-N2 | `specs/shared/test-matrix.md` R55 column 5 does not name the new B1 guard (`grep -c "snapshot_and_the_first_live_read" specs/shared/test-matrix.md` → `0`). R55 is still mapped, and the round's bounds kept the implementer out of `specs/`. | grep above | Leader, at wrap-up: add the B1 test to R55's gateway subscriber half. Not a traceability failure. |

N3, N5 and N6 are done as asked: the `hub.py` docstring and §3 reworded (N3); ledger row 12 now says an empty header is unobservable (N5, and I confirmed both branches mint and answer `resumed: false`); `domain/sse/cursor.py:11` cites `tests/unit/test_gateway_sse_domain.py`, which exists (N6). N2: the end-to-end test compares sorted frame `data` bytes with the bytes a second NATS client recorded on `readmodel.>`, for both event types, after asserting the Projector published `len(facts)` of each (P2e, P5e).

## `R<n>` → test mapping (round-2 delta only)

- R55, subscriber leg, no frame lost between the snapshot and the first live read: `…delivered_on_a_fresh_connection[start]`, `[ready]`, `…delivered_on_a_resumed_connection` (armed R11 ×3, R11d).
- R55, overflow → disconnect → resume with no gap and no duplicate: `test_r55_a_client_that_falls_behind_is_disconnected_and_resumes_without_a_gap` (armed O1, D2, C1′, C2′).
- R55, end to end, payload bytes: `test_r55_a_projected_fact_reaches_an_sse_client_as_frames_through_the_real_projector` (armed P2e, P5e).
- Backlog 215 item 1: `test_the_handler_raise_sites_are_exactly_the_ones_classified_here` (ST1, ST9), `test_the_status_population_against_openapi` (ST10).

## `CHECKPOINTS.md` (boxes this round touches)

- [x] C4: the tests are real; each round-2 claim fails under a mutation that names it (13 arms, 0 survivors).
- [x] C4: no mocked broker on the N2 path (testcontainers NATS, Kafka and Mongo; the developer stack was down).
- [x] C4: the arming protocol was followed: `.arm/r26r2/`, sha256, `cmp` identical ×13, caches cleared, green re-run.
- [x] C7: inherited #8 R2-1 is recorded as "recurred in kind, fixed" (`impl` §11). That is honest.
- [x] C2: `feature_list.json` id 26 → `done` (that line only); backlog 215 left `pending` (item 2, the `SA-n` proposal, is the leader's).
- [ ] C5 / effort record: **the leader's.** Phase 13's history entries are written by the leader from harness durations (features 25, 40, 41), so I have not written one. Feature 26 is not closeable until its `progress/history.md` entry with the effort record (sessions, wall-clock, both review rounds) is appended.

## Routing

- **Backlog 215 item 2** (the `SA-n` proposal: declare the 30 deployable Gateway-originated pairs, and choose "declare 502 in all three builds" or "map a malformed reply to 503 for parity"): **the leader's**. The evidence for it is now complete in `impl` §9.
- **R2-N1:** a light fix before the commit, as above.
- No other finding is rooted in `specs/shared/`.

Process: read-only apart from this section and the one `feature_list.json` line. No git command was run that writes the index or the working tree. The probe files are removed (`ls services/gateway/tests/unit | grep -c zz` → `0`).
