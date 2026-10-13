# Premise check: brief_spec_observability_reliability.md

VERIFIED 13 acceptance items for id 27: python3 json count -> 13
VERIFIED #8 line counts: specs 91/515/108, spec_ 105, impl_ 3381, review_ 2053: wc -l
VERIFIED #7 line counts: specs 75/221/91, spec_ 45, impl_ 1034, review_ 79: wc -l
VERIFIED 36 files use stdlib logging: grep -rl 'import logging|from logging' services/*/src packages/*/src -> 36
VERIFIED no file imports structlog or opentelemetry: same grep -> 0
VERIFIED order_mapper.py:57 `request_id=None,`
VERIFIED __main__.py:19 GRACEFUL_SHUTDOWN_SECONDS = 5; :28 timeout_graceful_shutdown=...
VERIFIED review_gateway_sse_push.md:66 is finding N1 (shutdown with open streams)
VERIFIED impl_projector_read_model.md:153 is the PR38 test row; :4326 is `#### I4-commit-before-handler`
VERIFIED review_projector_read_model.md:190 `### Q11`; :297 `R-1 -> feature 27`
VERIFIED impl_orders_cancel_responder.md:178 is "## 10. Findings and carries" (section 10)
VERIFIED OrdersCancelAcceptanceTests.cs:549 StockReserved_OperatorCancelCompensationParks_PublishesADlqCopy...
VERIFIED impl_orders_saga_terminal_rejection.md:27 deferred surfacing, only ERROR log and rejected row
VERIFIED orchestrator design.md:602 is "### 9.8 Seams for feature 27"; :728 feature-27 row; :760 id 94 row; :762 id 71 row; L23 is the envelope log-and-acknowledge row (line 118)
VERIFIED design.md section 11 "Trace context and headers (SO14)" at :616
VERIFIED test-matrix.md:183 is "## 8. observability_reliability - R56-R60, R62"; R63 in 8.1 (:196), owned by gateway feature 25 (done)
VERIFIED requirements.md R56 at :479, R60 :500, R62 :524; R16 :154, R29 :227
VERIFIED asyncapi.yaml dead-letter record at :1553-1582; header definitions :2223-2251 (x-first-failed-at :2247)
VERIFIED README.md:35 is the SA-3 registry row
VERIFIED #8 history.md:2122 "four review rounds, three rejected, ~3.1x #7"
VERIFIED #7 history.md:1055 heading; its effort line says "approved first time"
VERIFIED #7 operator-cancel-envelope.ts and #8 OperatorCancelRequestedEnvelope.cs exist: ls
VERIFIED orchestrator tasks.md 3.9, 3.10, 3.12 are the SO9/SO1 arms
VERIFIED FactMessage.headers "kept for feature 27's traceparent" at application/ports/fact_stream.py:20 in orders, notifications, projector
VERIFIED wire.py:8 and nats_saga_commands.py:22 carry the traceparent placeholders
VERIFIED no x-first-failed-at / .dlq publisher in services/*/src, packages/*/src (one comment in send_failure_classifier.py:11)
VERIFIED send_failure_classifier.py exists in notifications infrastructure/notification
VERIFIED collector image otcpy-otel-collector:0.159.0 (docker-compose.infra.yml:320); jaeger 2.20.0 (:344)
VERIFIED prometheus.yml byte-identical to #8 (and #7): cmp
VERIFIED five series: dashboard exprs: request_latency_ms_bucket by (le, exported_job, endpoint); fact_processing_latency_ms_bucket by (le, exported_job, consumer); saga_completion_ms_bucket by (le, outcome); max by (exported_job)(otc_outbox_lag_ms); otc_dlq_depth
VERIFIED #8 ids 71 (operator note; envelope bytes), 74 (DLQ tests by content), 75 (x-first-failed-at), 94 (SO9 arm), 104 (DLQ producer localhost): #8 feature_list.json
VERIFIED otc_orders at migration 0002 saga_commands.operator_note: services/orders/alembic/versions/0002_saga_commands_operator_note.py
VERIFIED asyncio / projector design hand-over for id 94 exists (projector design.md:604 row 94)
FALSE   §9.8 names the columns `triggering_event_envelope`, `triggering_event_topic`, `dead_lettered_at`: design.md:605 says "two nullable columns plus a `dead_lettered_at` marker"; only dead_lettered_at is named, the other two names appear nowhere in specs/order_saga_orchestrator (grep). They exist in #8's spec files, not here
FALSE   migration `0003` "per orchestrator §9.8": grep '0003' specs/order_saga_orchestrator -> no hit; §9.8 says only "feature 27's migration"

Verdict: DO NOT ACT (2 FALSE, 0 UNVERIFIABLE)
