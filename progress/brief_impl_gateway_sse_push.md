# Brief — implementer, feature 26 `gateway_sse_push` (phase 13, `sdd: false`, full group) + backlog 215's enumeration

**Task:** implement feature 26 from its acceptance items (`feature_list.json` id 26, **three** items), then do backlog **215**'s acceptance item 1 (an enumeration; the `SA-n` proposal of item 2 is the leader's). Feature 26 is set `in_progress` by the leader at dispatch. There is no spec phase (`sdd: false`): the specification of record is the three items, `specs/shared/openapi.yaml` `/orders/stream` (lines 383 – 514: frame format, the four event types, the `ping`-carries-no-`id` rule and why, reconnection with `Last-Event-ID`, `resumed: false` on a buffer miss, at-least-once, `?orderId=`, `x-sse-events`) and its schemas `OrderStreamUpdate`, `TimelineStreamEntry`, `StreamReady`, `StreamPing`; R55's **subscriber** leg (`specs/shared/test-matrix.md` line 181); and the Projector's hand-over, `specs/projector_read_model/design.md` §7 (lines 365 ff.: NATS core publish on `readmodel.order.updated.<orderId>` / `readmodel.timeline.appended.<orderId>` (core NATS: no persistence, so a subscriber that is not connected misses the signal), payloads the generated `OrderStreamUpdate` / `TimelineStreamEntry` serialised by `to_wire_json`). Classification: **full group** (a wire contract and a long-lived per-connection resource), so an Opus reviewer follows. The **ported-idiom ledger lives in your impl record**.

## Inputs (found on disk by the leader this session)

- **The Gateway** (feature 25, `done`): `services/gateway/src/otc_gateway/**` — composition root, lifespan in `main.py`, settings in `infrastructure/settings.py`, the NATS connection owned by the lifespan, bearer auth, the Problem middleware, the route census guards (the anonymous-route sweep derives the protected set from the served routes — `/orders/stream` is protected; the B1 body-media guard). Read `progress/impl_gateway_rest_auth.md` §1, §10 and §12 (FastAPI 0.142.2's lazy `_IncludedRouter`) first.
- **The Projector's publisher** (feature 24): `services/projector/src/otc_projector/infrastructure/**` (the `NatsUpdateSignalPublisher`) and its R55 tests `services/projector/tests/integration/test_update_signal.py` — the payloads you receive. You may not edit `services/projector/**`; an end-to-end test may **run** the real Projector host (Kafka fact in → Projector → NATS → Gateway → SSE client), as #8 did in-process.
- **#8 (baseline):** commit `27643ba` (25 + 26 in one commit; tell 26's half from it); source `../order-to-cash-dotnet/src/Gateway/{Domain/Sse/{CursorGenerator,ReplayBuffer,ReplayResult}.cs,Application/Stream/{StreamFrame,StreamHub}.cs,Infrastructure/Messaging/{NatsStreamSignalSubscriber,GatewaySseOptions}.cs,Presentation/Endpoints/StreamEndpoints.cs}`; settings `GATEWAY_SSE_BUFFER_CAPACITY=500`, `GATEWAY_SSE_PING_INTERVAL_MS=15000` (`../order-to-cash-dotnet/.env.example:253-254`); record `../order-to-cash-dotnet/progress/history.md` lines 1765 – 1793; `progress/{impl,review}_gateway_sse_push.md` there.
- **#7:** commit `f4524cf` (*"every fact into one stream, and the heartbeat that quietly defeated it"*) in `../order-to-cash-nestjs`; source `apps/gateway/src/**` (find `stream.controller.ts` and its replay buffer); record `../order-to-cash-nestjs/progress/history.md` line 1037 (the rejection text at line 1041).
- **#8 backlog population.** Enumerate every #8 entry whose subject is the stream, SSE, the replay buffer, the heartbeat or the update signal's subscriber with a command over `../order-to-cash-dotnet/feature_list.json` (regex in the record, full hit list), classified: applies to 26 / owned by a later #9 feature (name it — e.g. 29 `web_app` for R55's web half) / not applicable.

## What #8's and #7's records say to carry (read the lines; this is not the finding)

Each named **avoided** or **recurred** in your record:

- **#8 D1 — the teardown, hand-built and unguarded:** #7's teardown was Express's engine-supplied `res.on('close')`; #8 hand-built it and deleting its `Unsubscribe` left every test green — every disconnected `EventSource` would have leaked a buffer the publisher iterates on every fact. In #9 the property is hand-built again (Starlette / FastAPI streaming, client disconnect, `asyncio` cancellation): acceptance 3's guard must be armed **three ways**, as #8's round 2 was — delete the unsubscribe; do not propagate the request's disconnect / cancellation into the read-and-ping loop; subscribe on a different hub instance than the one the publisher uses — and it must fire within a bounded time (a guard that only notices when a later ping hits a dead socket is too slow).
- **#8 R2-1 — a ledger row whose stated evidence cannot fire:** for every row (especially "a framework supplies X, no guard owed"), state what would turn red if the row were false, and show it.
- **#7's rejection — a false equivalence claim in a harness comment** (a spawned process claimed equivalent to the real dev command). Any harness claim of equivalence is a claim to prove or drop.
- **The strong-form heartbeat** (acceptance 2): prove the connection would **die without** the ping — an idle timeout below the ping interval at a real socket (#8 used a raw `TcpClient` with a read timeout), so deleting the ping fails the test; not merely "a ping frame arrives".
- **`ping` and `stream.ready` carry no `id`** (`openapi.yaml`'s reason: a heartbeat id would become the client's resume point and every reconnect would answer `resumed: false`). Guard it.
- **Reconnect without duplicates** (acceptance 1): resume strictly after the `Last-Event-ID` cursor; an unknown or evicted cursor → `stream.ready` with `resumed: false`; a fixture where the cursor sits in the middle of the buffer, and whose ids differ from every plausible wrong order (Phase 12's R50 lesson, and feature 40's: differ from *every* plausible wrong order, including the one a sibling field would give).
- **Cursor monotonicity under concurrency:** #8 needed an `Interlocked` guard; in #9 decide whether cursor minting can interleave (one event loop, but awaits between read and increment?) and guard the answer.
- **`?orderId=`** filters to one order — a fixture with two orders whose frames interleave; the wrong-order frame must not appear.

## Must hold (each a guard; each armed)

- The three acceptance items, as above, each armed (teardown three ways; heartbeat strong form; reconnect resume / miss).
- Every frame's `data` validates against its schema (generated models, key sets both ways — never retyped); `event` names exactly the four types; `Cache-Control: no-cache`, `text/event-stream`; `401` without a token (the stream is protected — show the route census still derives it).
- The NATS subscription is owned by the lifespan (started, awaited on shutdown, cancellation propagated, a dead subscriber takes readiness down) — CLAUDE.md's task rules; the per-connection queues are bounded and a slow client cannot block the fan-out (decide the overflow policy with #8's and #7's citations).
- R55's subscriber leg: one end-to-end test from a projected fact to an SSE frame through the real Projector and the real Gateway.
- New settings (buffer capacity, ping interval, …): read through pydantic-settings in the composition root; list them in the record with defaults and sources — the leader writes `.env.example`.

## Backlog 215, acceptance item 1 (after feature 26's work is green)

Write a section "Backlog 215 — the status enumeration" in your record: every `(operation, HTTP status)` pair the Gateway can answer — **derived from its code and tests by a command** (e.g. its route table × its Problem mapping and handlers; say how the population is derived and why it is complete; a sentinel that must be found) — set against every pair `openapi.yaml` declares (read from the YAML by a command), with the full output, and each undeclared pair classified (inherited from #7 / #8 with a citation, or #9-only). Features 25, 40 and 41's routes are all in the tree when you run it (41 may still be in review — say which state you enumerated). Do not edit `openapi.yaml`; the proposal is the leader's.

## Process

- Arming protocol (grep `CLAUDE.md` on disk): backups in `.arm/n26/` with `sha256`; one named test per arm; the failure message names the claim and arrives fast; restore by `cp` + `cmp`; clear caches; a timeout kills the whole process group. Defeat list: state which rows apply.
- Every wait in a test is bounded (`asyncio.timeout`) and every retry loop paced, the pacing proven by a change of kind (#8 id 63).
- Baseline `./quality.sh` first (developer stack down), a second at the end (delta, time per test). Wait on the real PID; read the verdict from the log.
- `specs/shared/test-matrix.md` column 5 only for rows this feature proves (R55's subscriber leg), and the derived counts.
- Write `progress/impl_gateway_sse_push.md` early and keep it updated.

## Live walkthrough

Read the live-data registers (`progress/current.md`). Start the stack and the Orders, Fulfillment, Billing, Projector and Gateway hosts; open `curl -N` on `/orders/stream` (with a token) and on `/orders/stream?orderId=…`; place an order and record the frames through to `completed`; kill and reopen with `Last-Event-ID` and record the resume; leave it idle past one ping interval. Stop everything you started so only `otcpy-n8n` runs (`docker ps` before and after).

## Bounds

May touch: `services/gateway/**`; `tests/architecture/**` only where a literal must include the stream (report each); `specs/shared/test-matrix.md` (as above); `progress/impl_gateway_sse_push.md`; feature 26's status line in `feature_list.json`. **No edit under `services/{orders,fulfillment,billing,notifications,projector,seed}/**`, `packages/**`, `specs/shared/` beyond column 5, `.env.example` or compose.** If feature 41's implementer or reviewer is still working in `services/orders/**`, do not run two test runs against the same containers (testcontainers are per run; the developer stack is shared — use it only for the walkthrough, after confirming with `docker ps` that nothing else uses it). No new package without a reason (#8 added none; `sse-starlette` or similar needs one). No git command that writes the index or working tree.

## Output

`progress/impl_gateway_sse_push.md`: what was built; the ledger (file and line on both halves, armed guard, what turns red if the row were false); the guard-port table (#8's and #7's stream tests by content: ported / deliberately not / n/a); the #8 backlog classification; the arming table (mutation, test, verbatim message, `sha256`, `cmp`); defeat-list rows; the new settings; the live record; the backlog-215 enumeration; each inherited finding avoided / recurred; the two `quality.sh` runs; `Packages installed:`. Set feature 26 to `in_review` (that line only). Return only "result in `progress/impl_gateway_sse_push.md`" plus at most 5 lines.

## Premise check

`progress/premise_impl_gateway_sse_push.md`: 21 verified, 0 false; two wording notes applied above (#7's rejection text is at line 1041; design §7 says NATS core publish, not "at-most-once").
