# Premise check — brief_impl_gateway_sse_push.md

VERIFIED   feature 26 has three acceptance items — feature_list.json id 26: "client reconnect resumes without duplicates" / "connection outlives an idle timeout (heartbeat, strong form)" / "client disconnect releases the subscription"
VERIFIED   openapi.yaml /orders/stream spans 383–514 — `/orders/stream:` at 383, `/stock:` at 515
VERIFIED   content: ping carries no id (and why), four event types, stream.ready, resumed:false on buffer miss, at-least-once (eventId dedupe), orderId query param, x-sse-events, Cache-Control const no-cache — read lines 383–514
VERIFIED   schemas OrderStreamUpdate, TimelineStreamEntry, StreamReady, StreamPing exist — openapi.yaml lines 1590, 1616, 1638, 1659
VERIFIED   test-matrix.md line 181 is R55 (projector half DONE; Gateway push channel feature 26 listed as unproven leg)
VERIFIED   projector design §7 at 365: subjects readmodel.order.updated.<orderId> / readmodel.timeline.appended.<orderId>, payloads OrderStreamUpdate / TimelineStreamEntry via to_wire_json — design.md:365-382; "at-most-once" is not worded in §7.1 but "NATS's delivery semantics ... accepts" and NATS core publish (accepted gloss)
VERIFIED   NatsUpdateSignalPublisher exists — services/projector/src/otc_projector/infrastructure/signal/nats_update_signal_publisher.py:111; test_update_signal.py exists in services/projector/tests/integration/
VERIFIED   gateway main.py (lifespan -> start_runtime), infrastructure/settings.py exist; NATS opened in composition.py start_runtime under AsyncExitStack (lifespan-owned)
VERIFIED   impl_gateway_rest_auth.md has §1 (What was built), §10 (Guards entered), §12 (Surprises; FastAPI 0.142.2 lazy _IncludedRouter at line 287)
VERIFIED   route census/B1 body-media guard exist — services/gateway/tests/unit/test_gateway_body_media_types.py; feature 25 status done
VERIFIED   #8 commit 27643ba contains 25 + 26 ("feat(gateway): the sixth service — REST, JWT, rate limiting and SSE"; both impl_/review_ gateway_* files)
VERIFIED   all eight #8 files exist at the stated paths (Domain/Sse/{CursorGenerator,ReplayBuffer,ReplayResult}.cs, Application/Stream/{StreamFrame,StreamHub}.cs, Infrastructure/Messaging/{NatsStreamSignalSubscriber,GatewaySseOptions}.cs, Presentation/Endpoints/StreamEndpoints.cs) — ls
VERIFIED   #8 .env.example:253-254 — GATEWAY_SSE_BUFFER_CAPACITY=500, GATEWAY_SSE_PING_INTERVAL_MS=15000
VERIFIED   #8 history 1765–1793 — starts "## gateway_sse_push (id 26...)" at 1765, ends "---" at 1793; contains D1 teardown unsubscribe, three-way arming in round 2, R2-1, strong-form raw TcpClient heartbeat, Interlocked cursor guard
VERIFIED   #8 progress/{impl,review}_gateway_sse_push.md exist
VERIFIED   #7 commit f4524cf subject "feat(gateway): every fact into one stream, and the heartbeat that quietly defeated it"
VERIFIED   #7 history line 1037 is the feature 26 section header; the rejection for a header comment falsely claiming equivalence to `pnpm dev:projector` is on line 1041 of that section (brief's "line 1037" = section start, not the sentence)
VERIFIED   #7 stream controller — apps/gateway/src/presentation/stream.controller.ts (replay buffer: apps/gateway/src/domain/sse/replay-buffer.ts; hub: application/stream-hub.ts)
VERIFIED   #8 id 63 is a retry-pacing finding (readiness waits retry with no delay)
VERIFIED   backlog 215 item 1 matches the brief's final section (population of (operation,status) pairs derived from code/tests vs openapi, full output, each undeclared pair classified; item 2 SA-n is the leader's); attached_to feature 26
VERIFIED   the brief forbids nothing feature 26's acceptance or 215 item 1 mandates (bounds: no openapi.yaml/.env.example edit; 215 item 1 requires only an enumeration in the record)
UNVERIFIABLE "Phase 12's R50 lesson, and feature 40's" fixture lesson — not checked (outside the listed claims)

Verdict: SAFE TO ACT (0 FALSE, 21 VERIFIED, 1 UNVERIFIABLE)
