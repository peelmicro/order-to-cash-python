# Implementation record - feature 23 `notifications_service` (phase 11, `sdd: false`, full group)

Status: `in_review`. Everything below was produced by commands in this session; raw outputs are in `.arm/n23/` (git-ignored).

## 0. Quality runs

| Run | Result |
|---|---|
| Baseline `./quality.sh`, developer stack down (only `otcpy-n8n`) | exit 0, 410 s wall, `3492 passed in 382.40s`, coverage 97.47% (`.arm/n23/baseline.log`) |
| Final `./quality.sh`, same conditions | exit 0, 433 s wall, `3781 passed in 411.77s`, coverage 97.56% (`.arm/n23/final.log`) |
| Delta | +289 tests, +23 s wall, +0.09 points |

`./init.sh` exits 0 at the end. Feature 23 set to `in_review` (line 412 of `feature_list.json` only). There is no `tasks.md` (`sdd: false`).

## 1. What was built

Application (`services/notifications/src/otc_notifications/`): `application/{messages,handlers,dispatch,notified_facts,scope}.py`, `application/ports/{notification_sender,delivery_ledger,fact_stream,clock}.py`, `application/templates/{format,order_placed,order_confirmed,order_despatched,invoice_issued,payment_received,order_completed,order_cancelled}.py`. Infrastructure: `messaging/{idempotent_consumer,consumer_name}.py` (copies of Orders', byte-identical), `messaging/{kafka_fact_subscriber,fact_topics}.py`, `notification/{console_sender,smtp_sender,mime,degrading_sender,send_failure_classifier}.py`, `persistence/delivery_ledger.py`, `clock.py`, `settings.py` (+`KafkaSettings`, `SmtpSettings`). Presentation: `notification_facts_consumer.py`, `app.py` (readiness). Root: `composition.py`, `main.py`.

Design: Kafka fact consumer task -> `NOTIFIED_FACTS` (the dictionary whose keys ARE the filter and the routing) -> seven explicitly registered commands/handlers via `otc_cqrs` -> `dispatch` (record-first, send outside any transaction, forget-on-throw) -> `NotificationSender` port (console; SMTP/aiosmtplib inside the degrading decorator). One task class (`fact-consumer`), started by the lifespan and awaited (cancelled after a 30 s grace) on shutdown; readiness goes 503 when the task is done or the consumer has not joined its group; `start_runtime` returns only once the consumer is positioned. No outbox, no responder, no fact emitted.

Other files touched: `services/notifications/pyproject.toml`, `uv.lock`; tests `services/notifications/tests/**`; `scripts/notification-template-sweep.py` (new); `specs/shared/test-matrix.md` (R17, R18 column 5 only); instruments (section 9). No edit to `services/orders/src`, `packages/**`, `models.py`, `alembic/**`.

## 2. The five questions, answered from the predecessors

1. Recipient/templates. Both: `<retailerCode lower>@retailer.order-to-cash.example`; `payment.received.v1` has no `retailerCode`, so `orderReference` (#7 `infrastructure/templates/notification-format.ts:39`; #8 `Application/Templates/NotificationFormat.cs:46`). Subject `[order-to-cash] <summary> (correlationId: <id>)`; text+HTML bodies; HTML escaped (#7 `notification-format.ts:65`, #8 `NotificationFormat.cs:62`); money through the shared exponent table (#9: `otc_shared_kernel.format_money`, integer `divmod`, SA-5); instants: #7 interpolates the payload's JSON string, which already IS the wire form (#7 `order-placed.template.ts:15`, `` `Order date: ${payload.orderDate}` ``), so #9's `format_instant` text (`YYYY-MM-DDTHH:MM:SS.mmmZ`) matches #7 and departs only from #8's `{payload.OrderDate:O}` (#8 `OrderPlacedTemplate.cs:24`); email text is not a parity claim.
2. Topics. All three fact topics; the filter is by `eventType` only (#8 `NotificationFactsConsumer.cs` `_routes` dictionary; #7 `notification-facts.controller.ts`). #9: `NOTIFIED_FACTS` keys. A topic carrying non-notified facts is shown to produce no email and no ledger row (`test_the_filter_is_by_event_type_not_by_topic`, `test_r17_a_fact_the_filter_refuses_leaves_no_ledger_row`).
3. Permanent vs transient. #7 `degrading-notification-sender.ts:64-79` + `send-failure-classifier.ts` (5yz permanent, EAUTH permanent, default transient); #8 `DegradingNotificationSender.cs:67`, `SendFailureClassifier.cs:72` (5yz `SmtpCommandException`, `ServiceNotAuthenticatedException`). Permanent: one loud error line (`event=notification.send.degraded`), the same message through the console fallback, normal return (fact acknowledged, ledger row kept). Transient: the original exception re-raised, `forget`, offset uncommitted, paced redelivery (dead-letter is feature 27). #9 classifier on aiosmtplib: `SMTPResponseException.code` 5yz permanent (this covers 530 auth required), `SMTPRecipientsRefused` permanent only if every refusal is 5yz, everything else transient. A non-notified fact: acknowledged, NOT recorded.
4. SMTP settings. #7 `smtp.config.ts:61-64` refuses a partial credential pair; #8 `NotificationsOptions.cs:17,54` explicit `NotificationSenderKind` defaulting to Console. #9: the SMTP and Kafka names are #7's (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` in #7 `smtp.config.ts:54-89`; `NOTIFICATIONS_KAFKA_CLIENT_ID`, `NOTIFICATIONS_CONSUMER_GROUP` in #7 `.env.example:136-137`; #8 used `NOTIFICATIONS_SMTP_*`, `.env.example:139-141`); only `NOTIFICATIONS_SENDER` (console default; #8's explicit `NotificationSenderKind`, `NotificationsOptions.cs:59`) and `SMTP_START_TLS` are #9's own: `NOTIFICATIONS_SENDER` (console default), `SMTP_HOST/PORT/FROM_EMAIL/START_TLS`, `SMTP_USER/PASSWORD` (a partial pair fails the boot, regardless of sender), port constrained 1..65535.
5. Typing and Mailpit. aiosmtplib 5.1.3 ships `py.typed`: `mypy --strict` passes with no new override. `testcontainers.community.mailpit` EXISTS but imports `cryptography` (not installed in this workspace) and generates a 4096-bit RSA certificate per container; the fixture uses the generic `DockerContainer` with the compose-pinned `axllent/mailpit:v1.27.5`, Docker-held ports, `MP_ENABLE_CHAOS=true`.

Ledger/send order (brief question on case 1 vs case 4): both predecessors record first with a no-op `work`, send outside the transaction, and delete the row on a send failure (#7 `application/notification-dispatch.service.ts:12-19,95-108` and `processed-events-compensation.ts`; #8 `Application/NotificationDispatchService.cs:22-28,60`). A crash between the commit and the send loses one email, never duplicates one. Hence #9's copy is BYTE-IDENTICAL (parity case 1, no variant); the compensating delete is in another file. The brief's premise that #8 had a "banner-only variant" finding was false (premise check); the variant route was not taken, so no variant guard was needed.

## 3. Ported-idiom ledger

| Idiom | #7 relied on | #8 supplied | #9 supplies | Armed guard |
|---|---|---|---|---|
| Record-first / forget-on-throw | no-op `work` + `deleteProcessedEvent` (`notification-dispatch.service.ts:95-108`) | `RecordAsync`/`DeleteRecordAsync` (`NotificationDispatchService.cs:60`) | `application/dispatch.py` + `SqlAlchemyDeliveryLedger` over the byte-identical canonical consumer | D01-D06, L01-L03, I01, I04 |
| Durable ledger (not a heap Set) | a Set in round 1 (three emails for one eventId, `history.md:964-975`; the spec fixture still shows the Set, `notification-dispatch.service.spec.ts:23-24`), then durable (`processed-events-compensation.ts`, wired `app.module.ts:32,143`) | `Notifications/Infrastructure/Messaging/ProcessedEventLedger.cs:42` (unique-violation codes `:44-45`) | PostgreSQL unique `(event_id, consumer)`, `ON CONFLICT DO NOTHING` | I05 (a memory Set deciding duplicates fails the restart test) |
| Starting offset | `fromBeginning: false` (`main.ts:24-53`) | `AutoOffsetReset.Latest` (`Notifications/.../KafkaFactStreamSubscriber.cs:77,117`) | `latest`; aiokafka resolves it lazily at the first fetch, so the subscriber resolves every assigned partition's position BEFORE `ready` (hand-built property) | V01, V04, V05, B05 |
| Offset after the handler, seek back on failure | kafkajs re-delivers when the handler throws; a normal return commits (`notification-facts.controller.ts:174-175`) | re-entry after 2 s (`NotificationFactsConsumer.cs:86-99`, `Task.Delay(TimeSpan.FromSeconds(2))` at `:97`) | Orders' aiokafka subscriber ported (aiokafka's position is already past a returned record) | V03, V06 |
| Recipient / subject | `notification-format.ts:39` | `NotificationFormat.cs:46` (the `RecipientFor` line) | `templates/format.py` | M01, M05, M06, sweep |
| Money text | shared-kernel `formatMoney` (`notification-format.ts:17`) | `MoneyText.Format` (`SharedKernel/MoneyText.cs:34`) | `format_money` (integer `divmod`) | M03, goldens in EUR, JPY, KWD, USD |
| HTML escaping | `escapeHtml` (`notification-format.ts:65`) | `EscapeHtml` (`NotificationFormat.cs:62`) | `str.translate` map | M02 |
| Degrade on permanent failure | `degrading-notification-sender.ts` | `DegradingNotificationSender.cs` | `degrading_sender.py` bound only around SMTP | G01-G05, I02, I03 |
| Classification | nodemailer `responseCode` (`send-failure-classifier.ts:58-64`) | MailKit `StatusCode` (`SendFailureClassifier.cs:72`) | `SMTPResponseException.code` | C01-C03 |
| Partial credential pair refused | `smtp.config.ts:61` | explicit sender kind | `SmtpSettings` validator | T02 |
| Envelope copy | hand copy in the controller (`notification-facts.controller.ts:78-102`, `candidate as Envelope`) | `ToEnvelope` hand copy (id 58; `NotificationFactsConsumer.cs:180`) | none: the whole envelope is parsed by the generated model | P03 |
| Instants in email text (DEPARTURE from #8, not from #7) | interpolates the payload's wire string (`order-placed.template.ts:15`) | `{payload.OrderDate:O}` (`OrderPlacedTemplate.cs:24`) | `format_instant`: `YYYY-MM-DDTHH:MM:SS.mmmZ`, equal to #7's text | sweep of the 7 instant sites, goldens (section 6) |
| Environment names (DEPARTURE from #8; #7's names kept) | `SMTP_*` (`smtp.config.ts:54-89`), `NOTIFICATIONS_KAFKA_CLIENT_ID` / `NOTIFICATIONS_CONSUMER_GROUP` (`.env.example:136-137`) | `NOTIFICATIONS_SMTP_*` (`.env.example:139-141`); explicit `NotificationSenderKind` (`NotificationsOptions.cs:59`) | #7's names; `NOTIFICATIONS_SENDER` and `SMTP_START_TLS` are #9's own; `specs/shared/` is silent | `test_each_setting_reaches_the_adapter_it_configures`, `test_notifications_settings_env.py` |
| Consumes only | `notifications-consumes-only.spec.ts:59-60` | none for Notifications (Projector only: `tests/Projector.UnitTests/ProjectorConsumesOnlyTests.cs:12-15`, the only hit) | `test_notifications_consumes_only.py` (AST) | N01, N02 |

## 4. #8 backlog classification (23 ids; the regex over `../order-to-cash-dotnet/feature_list.json` also returns 69, verified)

| Id | Subject | Disposition |
|---|---|---|
| 58 | envelope copy unguarded | applies to 23: AVOIDED by construction, guarded (P03, `test_the_subject_carries_the_envelopes_correlation_id_not_another_envelope_id`) |
| 59 | date-typed payload sites survive | applies: guarded (7 instant sites in the 109; goldens + sweep) |
| 60 | envelope fixture collisions | applies: guarded (`test_fact_fixtures_do_not_collide.py`, Q01, Q02) |
| 73 | degrade on permanent failure | applies: built and armed |
| 23 | the feature itself | this feature |
| 14 | outbox and idempotency | consumed (canonical copy, parity cases 1 and 3 made live) |
| 68 | composition root wiring unguarded | applies: AVOIDED (`test_each_setting_reaches_the_adapter_it_configures`, B-arms) |
| 76 | application depends on infrastructure | applies: AVOIDED (`layers-notifications` KEPT) |
| 82 | arming messages that name nothing | applies: recorded verbatim; weakest is B03 (probe traceback names `DispatcherValidationError`) |
| 85 | container fixtures race host ports | applies: AVOIDED (Docker-held ports) |
| 56 (CLAUDE.md) | composition env reads | applies: AVOIDED (`test_composition_env_reads.py` extended, N06, N07, `test_notifications_settings_env.py`) |
| 74, 75, 104 | dead-letter test selection, first-failed-at, DLQ producer default | owned by feature 27 `observability_reliability` |
| 94 | SO9 arm no longer kills once a retry wrapper exists | lands on feature 27 (re-run V03/V06 after the wrapper) |
| 1, 2, 4, 9, 11 | bootstrap, harness, compose (Mailpit pin used), Orders/Billing DBs, Notifications DB | not applicable (done earlier) |
| 52, 67 | decode-boundary ledger; design-time DbContext factory env reads | not applicable (no hand decode; alembic untouched by bound) |
| 69, 81 | Gateway pacing / trace timeout | not applicable (Gateway) |

## 5. The fourteen facts (`domain-model.md` 7.2), expected set a literal and read from the spec

Notified (7): order.placed.v1, order.confirmed.v1, order.despatched.v1, invoice.issued.v1, payment.received.v1, order.completed.v1, order.cancelled.v1. Not notified (7): stock.reserved.v1, stock.rejected.v1, stock.released.v1, credit.approved.v1, credit.rejected.v1, credit.released.v1, order.saga_failed.v1. Tests: `test_notified_facts.py` (literal, and equality with the `notificationsConsume*` operations of `asyncapi.yaml`), `test_notification_facts_consumer.py` (all 14 driven through the real consumer/dispatcher). Arms F01-F07 (delete each of the seven) and S01-S07 (add each non-notified sibling) all fail.

## 6. Template sites: enumeration, sweep, population test

Instrument: `scripts/notification-template-sweep.py` (committed; #8's ruling after counts 14/89/95: a re-runnable instrument is required). Command and full output:

```
$ uv run python scripts/notification-template-sweep.py --enumerate
  1  application/templates/invoice_issued.py:17 payload.total_amount                   InvoiceIssuedPayload.total_amount  [int]
  2  application/templates/invoice_issued.py:17 payload.currency                       InvoiceIssuedPayload.currency  [string]
  3  application/templates/invoice_issued.py:18 payload.invoice_date                   InvoiceIssuedPayload.invoice_date  [instant]
  4  application/templates/invoice_issued.py:20 payload.invoice_reference              InvoiceIssuedPayload.invoice_reference  [string]
  5  application/templates/invoice_issued.py:20 event.correlation_id                   InvoiceIssuedEvent.correlation_id  [id]
  6  application/templates/invoice_issued.py:24 payload.invoice_reference              InvoiceIssuedPayload.invoice_reference  [string]
  7  application/templates/invoice_issued.py:24 payload.order_reference                InvoiceIssuedPayload.order_reference  [string]
  8  application/templates/invoice_issued.py:25 payload.retailer_code                  InvoiceIssuedPayload.retailer_code  [string]
  9  application/templates/invoice_issued.py:26 payload.company_code                   InvoiceIssuedPayload.company_code  [string]
 10  application/templates/invoice_issued.py:29 event.correlation_id                   InvoiceIssuedEvent.correlation_id  [id]
 11  application/templates/invoice_issued.py:34 payload.invoice_reference              InvoiceIssuedPayload.invoice_reference  [string]
 12  application/templates/invoice_issued.py:34 payload.order_reference                InvoiceIssuedPayload.order_reference  [string]
 13  application/templates/invoice_issued.py:36 payload.retailer_code                  InvoiceIssuedPayload.retailer_code  [string]
 14  application/templates/invoice_issued.py:37 payload.company_code                   InvoiceIssuedPayload.company_code  [string]
 15  application/templates/invoice_issued.py:41 event.correlation_id                   InvoiceIssuedEvent.correlation_id  [id]
 16  application/templates/invoice_issued.py:44 payload.retailer_code                  InvoiceIssuedPayload.retailer_code  [string]
 17  application/templates/order_cancelled.py:17 step.step                              CompensationStep.step  [enum]
 18  application/templates/order_cancelled.py:17 payload.compensation_steps             OrderCancelledPayload.compensation_steps  [collection]
 19  application/templates/order_cancelled.py:18 payload.compensation_steps             OrderCancelledPayload.compensation_steps  [collection]
 20  application/templates/order_cancelled.py:21 payload.cancelled_at                   OrderCancelledPayload.cancelled_at  [instant]
 21  application/templates/order_cancelled.py:23 payload.order_reference                OrderCancelledPayload.order_reference  [string]
 22  application/templates/order_cancelled.py:23 event.correlation_id                   OrderCancelledEvent.correlation_id  [id]
 23  application/templates/order_cancelled.py:27 payload.order_reference                OrderCancelledPayload.order_reference  [string]
 24  application/templates/order_cancelled.py:28 payload.cancellation_reason            OrderCancelledPayload.cancellation_reason  [enum]
 25  application/templates/order_cancelled.py:29 payload.retailer_code                  OrderCancelledPayload.retailer_code  [string]
 26  application/templates/order_cancelled.py:30 payload.company_code                   OrderCancelledPayload.company_code  [string]
 27  application/templates/order_cancelled.py:33 event.correlation_id                   OrderCancelledEvent.correlation_id  [id]
 28  application/templates/order_cancelled.py:38 payload.order_reference                OrderCancelledPayload.order_reference  [string]
 29  application/templates/order_cancelled.py:40 payload.cancellation_reason            OrderCancelledPayload.cancellation_reason  [enum]
 30  application/templates/order_cancelled.py:41 payload.retailer_code                  OrderCancelledPayload.retailer_code  [string]
 31  application/templates/order_cancelled.py:42 payload.company_code                   OrderCancelledPayload.company_code  [string]
 32  application/templates/order_cancelled.py:46 event.correlation_id                   OrderCancelledEvent.correlation_id  [id]
 33  application/templates/order_cancelled.py:49 payload.retailer_code                  OrderCancelledPayload.retailer_code  [string]
 34  application/templates/order_completed.py:17 payload.total_amount                   OrderCompletedPayload.total_amount  [int]
 35  application/templates/order_completed.py:17 payload.currency                       OrderCompletedPayload.currency  [string]
 36  application/templates/order_completed.py:18 payload.completed_at                   OrderCompletedPayload.completed_at  [instant]
 37  application/templates/order_completed.py:20 payload.order_reference                OrderCompletedPayload.order_reference  [string]
 38  application/templates/order_completed.py:20 event.correlation_id                   OrderCompletedEvent.correlation_id  [id]
 39  application/templates/order_completed.py:24 payload.order_reference                OrderCompletedPayload.order_reference  [string]
 40  application/templates/order_completed.py:25 payload.retailer_code                  OrderCompletedPayload.retailer_code  [string]
 41  application/templates/order_completed.py:26 payload.company_code                   OrderCompletedPayload.company_code  [string]
 42  application/templates/order_completed.py:29 event.correlation_id                   OrderCompletedEvent.correlation_id  [id]
 43  application/templates/order_completed.py:34 payload.order_reference                OrderCompletedPayload.order_reference  [string]
 44  application/templates/order_completed.py:36 payload.retailer_code                  OrderCompletedPayload.retailer_code  [string]
 45  application/templates/order_completed.py:37 payload.company_code                   OrderCompletedPayload.company_code  [string]
 46  application/templates/order_completed.py:41 event.correlation_id                   OrderCompletedEvent.correlation_id  [id]
 47  application/templates/order_completed.py:44 payload.retailer_code                  OrderCompletedPayload.retailer_code  [string]
 48  application/templates/order_confirmed.py:17 payload.total_amount                   OrderConfirmedPayload.total_amount  [int]
 49  application/templates/order_confirmed.py:17 payload.currency                       OrderConfirmedPayload.currency  [string]
 50  application/templates/order_confirmed.py:18 payload.confirmed_at                   OrderConfirmedPayload.confirmed_at  [instant]
 51  application/templates/order_confirmed.py:20 payload.order_reference                OrderConfirmedPayload.order_reference  [string]
 52  application/templates/order_confirmed.py:20 event.correlation_id                   OrderConfirmedEvent.correlation_id  [id]
 53  application/templates/order_confirmed.py:24 payload.order_reference                OrderConfirmedPayload.order_reference  [string]
 54  application/templates/order_confirmed.py:25 payload.retailer_code                  OrderConfirmedPayload.retailer_code  [string]
 55  application/templates/order_confirmed.py:26 payload.company_code                   OrderConfirmedPayload.company_code  [string]
 56  application/templates/order_confirmed.py:29 event.correlation_id                   OrderConfirmedEvent.correlation_id  [id]
 57  application/templates/order_confirmed.py:34 payload.order_reference                OrderConfirmedPayload.order_reference  [string]
 58  application/templates/order_confirmed.py:36 payload.retailer_code                  OrderConfirmedPayload.retailer_code  [string]
 59  application/templates/order_confirmed.py:37 payload.company_code                   OrderConfirmedPayload.company_code  [string]
 60  application/templates/order_confirmed.py:41 event.correlation_id                   OrderConfirmedEvent.correlation_id  [id]
 61  application/templates/order_confirmed.py:44 payload.retailer_code                  OrderConfirmedPayload.retailer_code  [string]
 62  application/templates/order_despatched.py:16 line.product_code                      DespatchLine.product_code  [string]
 63  application/templates/order_despatched.py:16 line.units                             DespatchLine.units  [int]
 64  application/templates/order_despatched.py:16 payload.lines                          OrderDespatchedPayload.lines  [collection]
 65  application/templates/order_despatched.py:17 payload.despatch_date                  OrderDespatchedPayload.despatch_date  [instant]
 66  application/templates/order_despatched.py:19 payload.order_reference                OrderDespatchedPayload.order_reference  [string]
 67  application/templates/order_despatched.py:19 payload.despatch_reference             OrderDespatchedPayload.despatch_reference  [string]
 68  application/templates/order_despatched.py:20 event.correlation_id                   OrderDespatchedEvent.correlation_id  [id]
 69  application/templates/order_despatched.py:24 payload.order_reference                OrderDespatchedPayload.order_reference  [string]
 70  application/templates/order_despatched.py:25 payload.despatch_reference             OrderDespatchedPayload.despatch_reference  [string]
 71  application/templates/order_despatched.py:27 payload.retailer_code                  OrderDespatchedPayload.retailer_code  [string]
 72  application/templates/order_despatched.py:28 payload.company_code                   OrderDespatchedPayload.company_code  [string]
 73  application/templates/order_despatched.py:30 event.correlation_id                   OrderDespatchedEvent.correlation_id  [id]
 74  application/templates/order_despatched.py:35 payload.order_reference                OrderDespatchedPayload.order_reference  [string]
 75  application/templates/order_despatched.py:37 payload.despatch_reference             OrderDespatchedPayload.despatch_reference  [string]
 76  application/templates/order_despatched.py:39 payload.retailer_code                  OrderDespatchedPayload.retailer_code  [string]
 77  application/templates/order_despatched.py:40 payload.company_code                   OrderDespatchedPayload.company_code  [string]
 78  application/templates/order_despatched.py:43 event.correlation_id                   OrderDespatchedEvent.correlation_id  [id]
 79  application/templates/order_despatched.py:46 payload.retailer_code                  OrderDespatchedPayload.retailer_code  [string]
 80  application/templates/order_placed.py:17   payload.total_amount                   OrderPlacedPayload.total_amount  [int]
 81  application/templates/order_placed.py:17   payload.currency                       OrderPlacedPayload.currency  [string]
 82  application/templates/order_placed.py:18   payload.order_date                     OrderPlacedPayload.order_date  [instant]
 83  application/templates/order_placed.py:20   payload.order_reference                OrderPlacedPayload.order_reference  [string]
 84  application/templates/order_placed.py:20   event.correlation_id                   OrderPlacedEvent.correlation_id  [id]
 85  application/templates/order_placed.py:24   payload.order_reference                OrderPlacedPayload.order_reference  [string]
 86  application/templates/order_placed.py:25   payload.retailer_code                  OrderPlacedPayload.retailer_code  [string]
 87  application/templates/order_placed.py:26   payload.company_code                   OrderPlacedPayload.company_code  [string]
 88  application/templates/order_placed.py:29   event.correlation_id                   OrderPlacedEvent.correlation_id  [id]
 89  application/templates/order_placed.py:34   payload.order_reference                OrderPlacedPayload.order_reference  [string]
 90  application/templates/order_placed.py:36   payload.retailer_code                  OrderPlacedPayload.retailer_code  [string]
 91  application/templates/order_placed.py:37   payload.company_code                   OrderPlacedPayload.company_code  [string]
 92  application/templates/order_placed.py:41   event.correlation_id                   OrderPlacedEvent.correlation_id  [id]
 93  application/templates/order_placed.py:44   payload.retailer_code                  OrderPlacedPayload.retailer_code  [string]
 94  application/templates/payment_received.py:23 payload.amount                         PaymentReceivedPayload.amount  [int]
 95  application/templates/payment_received.py:23 payload.currency                       PaymentReceivedPayload.currency  [string]
 96  application/templates/payment_received.py:24 payload.value_date                     PaymentReceivedPayload.value_date  [instant]
 97  application/templates/payment_received.py:26 payload.invoice_reference              PaymentReceivedPayload.invoice_reference  [string]
 98  application/templates/payment_received.py:26 event.correlation_id                   PaymentReceivedEvent.correlation_id  [id]
 99  application/templates/payment_received.py:30 payload.payment_reference              PaymentReceivedPayload.payment_reference  [string]
100  application/templates/payment_received.py:30 payload.invoice_reference              PaymentReceivedPayload.invoice_reference  [string]
101  application/templates/payment_received.py:30 payload.order_reference                PaymentReceivedPayload.order_reference  [string]
102  application/templates/payment_received.py:33 payload.source                         PaymentReceivedPayload.source  [enum]
103  application/templates/payment_received.py:34 event.correlation_id                   PaymentReceivedEvent.correlation_id  [id]
104  application/templates/payment_received.py:39 payload.payment_reference              PaymentReceivedPayload.payment_reference  [string]
105  application/templates/payment_received.py:39 payload.invoice_reference              PaymentReceivedPayload.invoice_reference  [string]
106  application/templates/payment_received.py:39 payload.order_reference                PaymentReceivedPayload.order_reference  [string]
107  application/templates/payment_received.py:43 payload.source                         PaymentReceivedPayload.source  [enum]
108  application/templates/payment_received.py:45 event.correlation_id                   PaymentReceivedEvent.correlation_id  [id]
109  application/templates/payment_received.py:48 payload.order_reference                PaymentReceivedPayload.order_reference  [string]

109 sites in 7 templates
per kind: collection=3, enum=5, id=21, instant=7, int=6, string=67
per file: invoice_issued.py=16, order_cancelled.py=17, order_completed.py=14, order_confirmed.py=14, order_despatched.py=18, order_placed.py=14, payment_received.py=16
```

Sentinels (`--sentinels`):
```
ok   baseline: the unmutated copy passes the template tests
ok   NOT-APPLIED: wrong-target: 'payload.does_not_exist' not at application/templates/invoice_issued.py:17
ok   SURVIVED: comment-only
ok   CAUGHT: known-kill -> services/notifications/tests/unit/templates/test_template_rendering.py::test_order_placed_subject_names_the_order_and_the_correlation_id
```
`--all`: 109 sites, 198 mutations (constant + sibling swap), 198 caught, 0 survived. With `test_template_payload_sites.py` excluded (`--also-ignore`): 198 of 198 still caught, so the exact-text goldens alone kill every site mutation. Population test `test_template_payload_sites.py`: 114 leaves (envelope + payload, list elements one by one), 55 rendered, 59 declared unrendered, each rendered leaf must reach BOTH bodies. Fixture collisions: `test_fact_fixtures_do_not_collide.py` (equality and containment, 7 facts x 2 variants).

## 7. Test -> requirement / acceptance map

- Acceptance 1: `integration/test_notification_mailpit_inbox.py::test_a_real_email_for_the_notified_fact_lands_in_the_mailpit_inbox` (x7, read through the Mailpit HTTP API).
- Acceptance 2: `unit/test_degrading_sender.py`, `unit/test_notification_sender_binding.py`, `integration/test_notification_send_failure_real_smtp.py` (real 550 and 451).
- Acceptance 3 / R17 / R18: `integration/test_notification_idempotency.py` (x7 redelivery against a baseline, restart), `integration/test_delivery_ledger.py`, `unit/test_notification_dispatch.py`. Matrix rows R17 and R18 extended.
- Acceptance 4: sections 5-6; `templates/test_template_rendering.py` (recipient, subject, text, HTML, wrong values).
- Acceptance 5: `integration/test_notifications_host_lifespan.py` (zero handlers, two handlers, unregistered command, unbuilt handler, unbound port, boot unwinding, task awaited, readiness) and `tests/architecture/test_registration_behaviour.py[notifications]` (F-a, F-b, F-g, F-i, F-j shapes; B04 arms F-g+F-j as one pipeline in the real root).

## 8. Defeat list (twelve rows) against my guards

Applies: 1 delete (D, G, F, B arms), 2 corrupt (D05, G05, P03), 3 sibling identifier (V02, T01, T04, L01, B02, M06, E03, S01-S07), 4 shadow in a comment/string (consumes-only and confinement sentinels), 5 dead region (confinement `TYPE_CHECKING` sentinel pre-existing; N07 env reads any region), 7 drop an optional element (Q04 one body only), 8 literal vs literal (goldens are written out from the fixture, never built from the template), 9 premise stale (N08-N13 re-arm the edited instruments), 10 caches (restored files had their `__pycache__` removed), 11 unrecognised form (population test is behavioural, the sweep AST), 12 failure through a path the population never drives (I-arms drive Kafka, SMTP, PostgreSQL). Row 6 (raw strings) is covered by the AST-based censuses, not separately armed.

## 9. Instruments edited (premises armed in the same round)

`test_idempotent_consumer_parity.py` (case 1 population literal `{otc_orders, otc_notifications}`; case 3 literal; N03, N04, N05, N08), `test_kafka_client_confinement.py` (N02, N09 + 2 sentinels), `test_kafka_client_ids.py` (now 4 ids; T01, T04), `test_composition_env_reads.py` (N06, N07, N10), `test_registration_behaviour.py` (SERVICES/TABLES; B03, B04, N11), `test_write_path_population.py` (Notifications entries; N12, N13). `test_kafka_client_ids.py` did not cover consumers before: it covers Notifications' now. #7 and #8 both give the Notifications consumer client id `otc-notifications` (#7 `kafka.config.ts`, #8 `KafkaFactStreamSubscriber.cs:116`).

## 10. Arming table (80 arms, protocol of CLAUDE.md)

Backups in `.arm/n23/bak/<id>/`, each restored by `cp` and checked equal (the `cmp` column), bytecode of the edited module removed, every pytest run under a timeout in its own process group; harness `.arm/n23/arm.py`, raw `.arm/n23/arm_results.md`. 80 of 80 failed as expected, 0 green. (Q04 was first NOT-CAUGHT: the population test used the union of both bodies; strengthened to require both bodies and re-armed.) I05 was first caught only by an incidental precondition and was rewritten to keep the row and decide duplicates in memory.

| Arm | Mutation | Named test(s) | Failure (verbatim, first E line) | Verdict | sha256 before | cmp |
|---|---|---|---|---|---|---|
| F01 | filter: delete the entry order.placed.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_each_notified_fact_is_sent_once_through_the_port_with_its_event_id_as_message_id` | `AssertionError: missing ['order.placed.v1'], extra []` | FAILED-AS-EXPECTED 1.3s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| F02 | filter: delete the entry order.confirmed.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_each_notified_fact_is_sent_once_through_the_port_with_its_event_id_as_message_id` | `AssertionError: missing ['order.confirmed.v1'], extra []` | FAILED-AS-EXPECTED 1.4s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| F03 | filter: delete the entry order.despatched.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_each_notified_fact_is_sent_once_through_the_port_with_its_event_id_as_message_id` | `AssertionError: missing ['order.despatched.v1'], extra []` | FAILED-AS-EXPECTED 1.4s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| F04 | filter: delete the entry invoice.issued.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_each_notified_fact_is_sent_once_through_the_port_with_its_event_id_as_message_id` | `AssertionError: missing ['invoice.issued.v1'], extra []` | FAILED-AS-EXPECTED 1.3s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| F05 | filter: delete the entry payment.received.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_each_notified_fact_is_sent_once_through_the_port_with_its_event_id_as_message_id` | `AssertionError: missing ['payment.received.v1'], extra []` | FAILED-AS-EXPECTED 1.4s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| F06 | filter: delete the entry order.completed.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_each_notified_fact_is_sent_once_through_the_port_with_its_event_id_as_message_id` | `AssertionError: missing ['order.completed.v1'], extra []` | FAILED-AS-EXPECTED 1.4s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| F07 | filter: delete the entry order.cancelled.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_each_notified_fact_is_sent_once_through_the_port_with_its_event_id_as_message_id` | `AssertionError: missing ['order.cancelled.v1'], extra []` | FAILED-AS-EXPECTED 1.3s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| S01 | filter: add the non-notified sibling stock.reserved.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_a_non_notified_fact_is_not_routed, test_a_well_formed_non_notified_fact_produces_no_email_and_no_ledger_row` | `AssertionError: missing [], extra ['stock.reserved.v1']` | FAILED-AS-EXPECTED 1.4s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| S02 | filter: add the non-notified sibling stock.rejected.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_a_non_notified_fact_is_not_routed, test_a_well_formed_non_notified_fact_produces_no_email_and_no_ledger_row` | `AssertionError: missing [], extra ['stock.rejected.v1']` | FAILED-AS-EXPECTED 1.4s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| S03 | filter: add the non-notified sibling stock.released.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_a_non_notified_fact_is_not_routed, test_a_well_formed_non_notified_fact_produces_no_email_and_no_ledger_row` | `AssertionError: missing [], extra ['stock.released.v1']` | FAILED-AS-EXPECTED 1.4s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| S04 | filter: add the non-notified sibling credit.approved.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_a_non_notified_fact_is_not_routed, test_a_well_formed_non_notified_fact_produces_no_email_and_no_ledger_row` | `AssertionError: missing [], extra ['credit.approved.v1']` | FAILED-AS-EXPECTED 1.3s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| S05 | filter: add the non-notified sibling credit.rejected.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_a_non_notified_fact_is_not_routed, test_a_well_formed_non_notified_fact_produces_no_email_and_no_ledger_row` | `AssertionError: missing [], extra ['credit.rejected.v1']` | FAILED-AS-EXPECTED 1.4s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| S06 | filter: add the non-notified sibling credit.released.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_a_non_notified_fact_is_not_routed, test_a_well_formed_non_notified_fact_produces_no_email_and_no_ledger_row` | `AssertionError: missing [], extra ['credit.released.v1']` | FAILED-AS-EXPECTED 1.4s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| S07 | filter: add the non-notified sibling order.saga_failed.v1 | `test_the_filter_is_exactly_the_seven_notified_types, test_a_non_notified_fact_is_not_routed, test_a_well_formed_non_notified_fact_produces_no_email_and_no_ledger_row` | `AssertionError: missing [], extra ['order.saga_failed.v1']` | FAILED-AS-EXPECTED 1.3s | `5f122a260ecb0e1e1a7783f304abda192bccbc7be3989216798fa1d6951245e6` | True |
| D01 | R18: delete the duplicate short-circuit | `test_r18_a_duplicate_is_acknowledged_without_a_build_a_send_or_a_second_row` | `AssertionError: a duplicate must not even render the message` | FAILED-AS-EXPECTED 1.1s | `5400d3019b0e48686efb2eaa2a213e0f912c73f8a7b5b23044b7a2e29be16860` | True |
| D02 | compensation: delete the forget on a failed send | `test_a_failed_send_forgets_the_row_and_propagates_the_original_error` | `AssertionError: the row is gone: the redelivery is a fresh attempt` | FAILED-AS-EXPECTED 1.1s | `5400d3019b0e48686efb2eaa2a213e0f912c73f8a7b5b23044b7a2e29be16860` | True |
| D03 | R17: send first, record after | `test_r17_the_ledger_row_is_recorded_before_the_message_is_sent` | `AssertionError: record-first: a crash after the send can never be re-sent` | FAILED-AS-EXPECTED 1.1s | `5400d3019b0e48686efb2eaa2a213e0f912c73f8a7b5b23044b7a2e29be16860` | True |
| D04 | a failing compensation masks the original send error | `test_a_failing_compensation_never_masks_the_send_error_and_is_logged_with_the_ids` | `TimeoutError: smtp timeout` | FAILED-AS-EXPECTED 1.1s | `5400d3019b0e48686efb2eaa2a213e0f912c73f8a7b5b23044b7a2e29be16860` | True |
| D05 | corrupt the Message-Id (drop the suffix) | `test_the_message_id_is_the_event_id_at_order_to_cash_set_centrally` | `AssertionError: assert '0000abcd-000...-00000000abcd' == '0000abcd-000...order-to-cash'` | FAILED-AS-EXPECTED 1.1s | `5400d3019b0e48686efb2eaa2a213e0f912c73f8a7b5b23044b7a2e29be16860` | True |
| D06 | cancellation: compensate only Exception, not BaseException | `test_a_cancelled_send_forgets_the_row_and_cancellation_propagates` | `AssertionError: a send that never completed must not leave the fact consumed` | FAILED-AS-EXPECTED 1.1s | `5400d3019b0e48686efb2eaa2a213e0f912c73f8a7b5b23044b7a2e29be16860` | True |
| G01 | degrade: delete the degrade (always re-raise) | `test_a_permanent_failure_renders_through_the_fallback_and_returns_normally` | `aiosmtplib.errors.SMTPSenderRefused: (550, 'mailbox unavailable', 'no-reply@x.example')` | FAILED-AS-EXPECTED 1.2s | `57e1f497b69991c45a49dd0f43eed5f8203f12841efac34fa46d3218cbdf47de` | True |
| G02 | degrade: invert the classification | `test_a_permanent_failure_renders_through_the_fallback_and_returns_normally, test_a_transient_failure_is_re_raised_unchanged_and_the_fallback_is_untouched` | `aiosmtplib.errors.SMTPSenderRefused: (550, 'mailbox unavailable', 'no-reply@x.example')` | FAILED-AS-EXPECTED 1.2s | `57e1f497b69991c45a49dd0f43eed5f8203f12841efac34fa46d3218cbdf47de` | True |
| G03 | degrade: degrade on EVERY failure (delete the transient re-raise) | `test_a_transient_failure_is_re_raised_unchanged_and_the_fallback_is_untouched` | `Failed: DID NOT RAISE SMTPSenderRefused` | FAILED-AS-EXPECTED 1.1s | `57e1f497b69991c45a49dd0f43eed5f8203f12841efac34fa46d3218cbdf47de` | True |
| G04 | degrade: the fallback is never called | `test_a_permanent_failure_renders_through_the_fallback_and_returns_normally` | `AssertionError: the SAME message through the same port` | FAILED-AS-EXPECTED 1.1s | `57e1f497b69991c45a49dd0f43eed5f8203f12841efac34fa46d3218cbdf47de` | True |
| G05 | degrade: corrupt the stable event field | `test_a_permanent_failure_renders_through_the_fallback_and_returns_normally` | `AssertionError: assert 'notification.send.degrade' == 'notification.send.degraded'` | FAILED-AS-EXPECTED 1.1s | `57e1f497b69991c45a49dd0f43eed5f8203f12841efac34fa46d3218cbdf47de` | True |
| C01 | classifier: 4yz counted as permanent | `test_a_4yz_reply_or_anything_outside_5yz_is_transient` | `AssertionError: assert <SendFailure.PERMANENT: 'permanent'> is <SendFailure.TRANSIENT: 'transient'>` | FAILED-AS-EXPECTED 1.1s | `d538ea0bccf5f30f2a74883a72cd62133d1a3223e1bfa94e0b6a660a32923e8a` | True |
| C02 | classifier: 5yz counted as transient (upper bound) | `test_a_5yz_reply_is_permanent` | `AssertionError: assert <SendFailure.TRANSIENT: 'transient'> is <SendFailure.PERMANENT: 'permanent'>` | FAILED-AS-EXPECTED 1.1s | `d538ea0bccf5f30f2a74883a72cd62133d1a3223e1bfa94e0b6a660a32923e8a` | True |
| C03 | classifier: any (not all) recipient refusals | `test_recipients_refused_is_permanent_only_when_every_refusal_is_5yz` | `AssertionError: assert <SendFailure.PERMANENT: 'permanent'> is <SendFailure.TRANSIENT: 'transient'>` | FAILED-AS-EXPECTED 1.2s | `d538ea0bccf5f30f2a74883a72cd62133d1a3223e1bfa94e0b6a660a32923e8a` | True |
| B01 | binding: the bare SMTP adapter, no degrading decorator | `test_smtp_binds_the_degrading_decorator_around_the_smtp_adapter_with_the_console_fallback` | `AssertionError: assert <class 'otc_notifications.infrastructure.notification.smtp_sender.SmtpNotificationSender'> is DegradingNotificationSender` | FAILED-AS-EXPECTED 1.3s | `1e7185a632bbbd76226cd36e92db32a61647789b16cf775bea73276d6c28a4d9` | True |
| B02 | binding: swap the two sibling senders inside the decorator | `test_smtp_binds_the_degrading_decorator_around_the_smtp_adapter_with_the_console_fallback` | `AssertionError: the real adapter is what is wrapped` | FAILED-AS-EXPECTED 1.3s | `1e7185a632bbbd76226cd36e92db32a61647789b16cf775bea73276d6c28a4d9` | True |
| B03 | registration: delete one register_command statement | `test_a_service_registers_only_from_its_composition_root_and_its_tables_match, test_the_lifespan_starts_the_fact_consumer_and_awaits_it_on_shutdown` | `AssertionError: the probe could not run otc_notifications:` | FAILED-AS-EXPECTED 13.9s | `1e7185a632bbbd76226cd36e92db32a61647789b16cf775bea73276d6c28a4d9` | True |
| B04 | registration: F-g + F-j shape (helper loop over a list) in the real root | `test_a_service_registers_only_from_its_composition_root_and_its_tables_match` | `assert ["WIRE: 2 reg...medCommand']"] == []` | FAILED-AS-EXPECTED 4.4s | `1e7185a632bbbd76226cd36e92db32a61647789b16cf775bea73276d6c28a4d9` | True |
| L01 | ledger: record under a sibling consumer name (projector) | `test_the_ledger_consumer_name_is_notifications_and_is_the_default_group, test_r17_the_first_record_is_recorded_and_the_row_is_durable_across_a_new_engine` | `AssertionError: assert <ConsumerName.PROJECTOR: 'projector'> is <ConsumerName.NOTIFICATIONS: 'notifications'>` | FAILED-AS-EXPECTED 4.4s | `abde49706e101a0d5cfa7b668fb1456808893aac8ba2ebb14190e901f2a1f07f` | True |
| L02 | ledger: forget deletes under the wrong consumer (deletes nothing) | `test_forget_removes_exactly_the_pair_and_the_event_can_be_recorded_again` | `AssertionError: only the forgotten pair is gone` | FAILED-AS-EXPECTED 4.2s | `abde49706e101a0d5cfa7b668fb1456808893aac8ba2ebb14190e901f2a1f07f` | True |
| L03 | ledger: record always reports RECORDED (duplicate never seen) | `test_r18_a_duplicate_writes_nothing_and_changes_no_row` | `AssertionError: assert <LedgerOutcome.RECORDED: 'recorded'> is <LedgerOutcome.DUPLICATE: 'duplicate'>` | FAILED-AS-EXPECTED 4.2s | `abde49706e101a0d5cfa7b668fb1456808893aac8ba2ebb14190e901f2a1f07f` | True |
| V01 | subscriber: earliest instead of latest | `test_the_consumer_reads_from_latest_commits_manually_and_uses_the_notifications_group_and_client_identity` | `AssertionError: assert {'bootstrap_s...': False, ...} == {'bootstrap_s...': False, ...}` | FAILED-AS-EXPECTED 1.2s | `de50784f4b3e0a459815afc3bceffbd9396bf1b212b5fe1e1458c0fa046bd1ed` | True |
| V02 | subscriber: group id from the sibling client id | `test_the_group_and_client_identity_come_from_the_settings_not_from_literals` | `AssertionError: assert ('other.test:...ent-sentinel') == ('other.test:...oup-sentinel')` | FAILED-AS-EXPECTED 1.2s | `de50784f4b3e0a459815afc3bceffbd9396bf1b212b5fe1e1458c0fa046bd1ed` | True |
| V03 | subscriber: no seek back on a failed record | `test_a_failed_record_is_sought_back_to_its_own_offset` | `AssertionError: assert [] == [(('otc.order...s.v1', 3), 7)]` | FAILED-AS-EXPECTED 1.1s | `de50784f4b3e0a459815afc3bceffbd9396bf1b212b5fe1e1458c0fa046bd1ed` | True |
| V04 | subscriber: ready before the positions are resolved | `test_the_subscriber_is_ready_only_after_every_assigned_partition_has_a_position` | `AssertionError: every assigned partition` | FAILED-AS-EXPECTED 1.2s | `de50784f4b3e0a459815afc3bceffbd9396bf1b212b5fe1e1458c0fa046bd1ed` | True |
| V05 | subscriber: ready never set | `test_ready_is_set_while_consuming_and_cleared_when_the_loop_ends` | `assert [False] == [True]` | FAILED-AS-EXPECTED 1.4s | `de50784f4b3e0a459815afc3bceffbd9396bf1b212b5fe1e1458c0fa046bd1ed` | True |
| V06 | subscriber: commit the offset itself, not one past it | `test_a_successful_record_is_committed_one_past_its_offset_after_the_handler_returned` | `AssertionError: assert [{('otc.order...s.v1', 3): 4}] == [{('otc.order...s.v1', 3): 5}]` | FAILED-AS-EXPECTED 1.3s | `de50784f4b3e0a459815afc3bceffbd9396bf1b212b5fe1e1458c0fa046bd1ed` | True |
| T01 | settings: client id read from the sibling shared variable | `test_the_population_of_environment_variables_is_exactly_the_literal, tests/architecture/test_kafka_client_ids.py` | `AssertionError: declared but untested: ['KAFKA_CLIENT_ID']; tested but not declared: ['NOTIFICATIONS_KAFKA_CLIENT_ID']` | FAILED-AS-EXPECTED 1.8s | `2a5e34dd914d75d154723e8d8b565371f0461dd5adb71d892cab0ade2a36e12e` | True |
| T02 | settings: drop the partial-credential refusal | `test_a_partial_credential_pair_is_refused_naming_both_variables` | `Failed: DID NOT RAISE ValidationError` | FAILED-AS-EXPECTED 1.4s | `2a5e34dd914d75d154723e8d8b565371f0461dd5adb71d892cab0ade2a36e12e` | True |
| T03 | settings: the default sender is smtp | `test_the_documented_defaults` | `AssertionError: the safe default: no I/O` | FAILED-AS-EXPECTED 1.3s | `2a5e34dd914d75d154723e8d8b565371f0461dd5adb71d892cab0ade2a36e12e` | True |
| T04 | settings: default client id is Orders' (a sibling identifier) | `tests/architecture/test_kafka_client_ids.py` | `AssertionError: two services share a default client id: {'orders': 'otc-orders', 'fulfillment': 'otc-fulfillment', 'billing': 'otc-billing', 'notifications': 'otc-orders'` | FAILED-AS-EXPECTED 1.0s | `2a5e34dd914d75d154723e8d8b565371f0461dd5adb71d892cab0ade2a36e12e` | True |
| P01 | consumer: a malformed envelope raises instead of being acknowledged | `test_a_malformed_envelope_is_acknowledged_and_logged_not_retried` | `pydantic_core._pydantic_core.ValidationError: 1 validation error for Envelope[dict[str, Any]]` | FAILED-AS-EXPECTED 1.4s | `c1fb0d290d0d13c8eef666c0cbcf3dac1182d5058fde16d8f6f616a824dc3925` | True |
| P02 | consumer: the filter return is deleted | `test_a_well_formed_non_notified_fact_produces_no_email_and_no_ledger_row` | `AttributeError: 'NoneType' object has no attribute 'event_model'` | FAILED-AS-EXPECTED 1.4s | `c1fb0d290d0d13c8eef666c0cbcf3dac1182d5058fde16d8f6f616a824dc3925` | True |
| P03 | consumer: the envelope's correlation id replaced by the aggregate id in the typed parse | `test_the_subject_carries_the_envelopes_correlation_id_not_another_envelope_id` | `AssertionError: assert '(correlationId: 00000067-0067-4000-8000-0000000c7229)' in '[order-to-cash] Order ORD-000101 placed (correlationId: 00000066-0066-4000-8000-0000000` | FAILED-AS-EXPECTED 1.4s | `c1fb0d290d0d13c8eef666c0cbcf3dac1182d5058fde16d8f6f616a824dc3925` | True |
| M01 | format: recipient not lowercased | `test_order_placed_recipient_is_the_retailer_code_lowercased` | `AssertionError: not companyCode (globex), not the order reference` | FAILED-AS-EXPECTED 1.1s | `77bade41478ed1cf7b6203ba342935a8c623ccad4d802fc45cc6d943f9cf3f20` | True |
| M02 | format: no HTML escaping | `test_payment_received_escapes_an_externally_supplied_reference` | `assert '<script>' not in '<p>Payment ...008547c1</p>'` | FAILED-AS-EXPECTED 1.2s | `77bade41478ed1cf7b6203ba342935a8c623ccad4d802fc45cc6d943f9cf3f20` | True |
| M03 | format: money as the raw integer | `test_order_placed_text_body_is_exactly_the_documented_lines` | `AssertionError: assert 'Order ORD-00...-0000000c7229' == 'Order ORD-00...-0000000c7229'` | FAILED-AS-EXPECTED 1.2s | `77bade41478ed1cf7b6203ba342935a8c623ccad4d802fc45cc6d943f9cf3f20` | True |
| M04 | format: instant as isoformat | `test_order_placed_text_body_is_exactly_the_documented_lines` | `AssertionError: assert 'Order ORD-00...-0000000c7229' == 'Order ORD-00...-0000000c7229'` | FAILED-AS-EXPECTED 1.1s | `77bade41478ed1cf7b6203ba342935a8c623ccad4d802fc45cc6d943f9cf3f20` | True |
| M05 | format: correlation id left out of the subject | `test_order_confirmed_subject_names_the_order_and_the_correlation_id` | `AssertionError: assert '[order-to-ca...102 confirmed' == '[order-to-ca...0000006107ad)'` | FAILED-AS-EXPECTED 1.2s | `77bade41478ed1cf7b6203ba342935a8c623ccad4d802fc45cc6d943f9cf3f20` | True |
| M06 | template: payment recipient from the invoice reference (sibling) | `test_payment_received_recipient_is_the_order_reference_lowercased` | `AssertionError: not the invoice or payment reference` | FAILED-AS-EXPECTED 1.2s | `9d2e6ddc3eec5c99a9dd91761c4ca0da13c1de6c966b48db481ea1c2648ceb78` | True |
| E01 | mime: drop the HTML alternative | `test_the_mime_message_carries_both_bodies_and_the_headers` | `AssertionError: assert 'text/plain' == 'multipart/alternative'` | FAILED-AS-EXPECTED 1.2s | `8907b1dc4d572b922519128fe5d7fe81d549c9578a6827ab778e28cf66479a71` | True |
| E02 | mime: drop the Message-ID header | `test_the_mime_message_carries_both_bodies_and_the_headers` | `AssertionError: assert None == '<0000abcd-0000-4000-8000-00000000abcd@order-to-cash>'` | FAILED-AS-EXPECTED 1.2s | `8907b1dc4d572b922519128fe5d7fe81d549c9578a6827ab778e28cf66479a71` | True |
| E03 | smtp sender: recipient list from the sender address (sibling) | `test_the_sender_hands_the_transport_the_message_the_envelope_and_the_settings` | `AssertionError: assert {'sender': 'f...t': 2525, ...} == {'sender': 'f...t': 2525, ...}` | FAILED-AS-EXPECTED 1.2s | `10335c50ecd6ae27a66c28574b1a05a773fa2225492679f02df393c1177bee6c` | True |
| N01 | consumes-only: a NATS import appears | `test_no_module_of_the_service_imports_nats_an_outbox_or_a_kafka_producer` | `AssertionError: assert ['main.py: imports nats'] == []` | FAILED-AS-EXPECTED 1.3s | `7416d501327a4329bf553222f8d4a3cc9085a0d93e3ea7d3cd84b8a2dfe4ac1b` | True |
| N02 | confinement: a producer name appears in Notifications' subscriber | `test_the_modules_importing_aiokafka_are_exactly_the_publishers_and_the_subscribers` | `assert ["the subscri...kaProducer']"] == []` | FAILED-AS-EXPECTED 1.3s | `de50784f4b3e0a459815afc3bceffbd9396bf1b212b5fe1e1458c0fa046bd1ed` | True |
| N03 | parity: the literal of case 3 reverted to Orders alone | `test_case_3_every_write_model_that_consumes_facts_carries_a_copy` | `AssertionError: assert {'otc_notific... 'otc_orders'} == {'otc_orders'}` | FAILED-AS-EXPECTED 1.0s | `d2829755954de76ce299397fbde6614d5019bac9e6890fb1b55769a6070b0612` | True |
| N04 | parity: the Notifications copy of the canonical differs in one statement | `test_case_1_every_write_models_copy_is_byte_identical_to_the_canonical_after_the_banner` | `AssertionError: assert ['services/no...e the banner'] == []` | FAILED-AS-EXPECTED 1.0s | `088382845224d9b4a3d2dd184cd2699452f9b8fa70ae81f4b1ca2c518151d9f9` | True |
| N05 | parity: the Notifications copy is deleted | `test_case_1_every_write_models_copy_is_byte_identical_to_the_canonical_after_the_banner, test_case_3_every_write_model_that_consumes_facts_carries_a_copy` | `AssertionError: [PosixPath('/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/orders/src/otc_orders/infrastructure/messaging/idempotent_consume` | FAILED-AS-EXPECTED 1.0s | `088382845224d9b4a3d2dd184cd2699452f9b8fa70ae81f4b1ca2c518151d9f9` | True |
| N06 | env reads: a settings class the root forgets to build | `test_every_settings_class_of_the_service_is_the_literal_and_is_built_by_load_settings` | `AssertionError: load_settings never builds ['SmtpSettings']` | FAILED-AS-EXPECTED 1.1s | `1e7185a632bbbd76226cd36e92db32a61647789b16cf775bea73276d6c28a4d9` | True |
| N07 | env reads: an os.environ read appears | `test_nothing_in_a_service_with_a_root_reads_the_environment_directly` | `AssertionError: read the environment through a settings class instead: {'services/notifications/src/otc_notifications/infrastructure/clock.py line 6: os.environ'}` | FAILED-AS-EXPECTED 1.2s | `7b241c93bc7cd4d3f2cb0e7663b1d7094e9df5c6c593020b0a334418f5c7861d` | True |
| I01 | integration: duplicate short-circuit deleted (second emails reach the inbox) | `test_r18_a_byte_identical_redelivery_leaves_the_inbox_and_the_ledger_unchanged[order.placed.v1], test_r18_a_redelivery_after_a_runtime_restart_within_one_process_sends_nothing_more` | `AssertionError: assert ['00000065-00...rder-to-cash'] == ['00000000-00...rder-to-cash']` | FAILED-AS-EXPECTED 14.1s | `5400d3019b0e48686efb2eaa2a213e0f912c73f8a7b5b23044b7a2e29be16860` | True |
| I02 | integration: degrade deleted | `test_a_permanent_550_degrades_to_the_console_and_the_fact_is_acknowledged` | `AssertionError: no log record containing 'notification.send.degraded' within 30 s` | FAILED-AS-EXPECTED 40.8s | `57e1f497b69991c45a49dd0f43eed5f8203f12841efac34fa46d3218cbdf47de` | True |
| I03 | integration: classification inverted | `test_a_permanent_550_degrades_to_the_console_and_the_fact_is_acknowledged, test_a_transient_451_is_retried_and_the_email_is_sent_exactly_once_after_recovery` | `AssertionError: no log record containing 'notification.send.degraded' within 30 s` | FAILED-AS-EXPECTED 71.3s | `57e1f497b69991c45a49dd0f43eed5f8203f12841efac34fa46d3218cbdf47de` | True |
| I04 | integration: forget deleted on a failed send | `test_a_transient_451_is_retried_and_the_email_is_sent_exactly_once_after_recovery` | `AssertionError: and the ledger row was forgotten: the retry is fresh` | FAILED-AS-EXPECTED 11.0s | `5400d3019b0e48686efb2eaa2a213e0f912c73f8a7b5b23044b7a2e29be16860` | True |
| I05 | integration: the duplicate decision is an in-memory set (the row is still written, as #7 did with a Set) | `test_r18_a_redelivery_after_a_runtime_restart_within_one_process_sends_nothing_more` | `AssertionError: assert ['00000000-00...rder-to-cash'] == ['00000000-00...rder-to-cash']` | FAILED-AS-EXPECTED 11.7s | `abde49706e101a0d5cfa7b668fb1456808893aac8ba2ebb14190e901f2a1f07f` | True |
| Q01 | fixture collision: aggregateId equals correlationId | `test_no_two_leaves_of_a_notified_fixture_are_equal_and_no_text_contains_another` | `assert ["EQUAL .aggr...000000c7229'"] == []` | FAILED-AS-EXPECTED 1.1s | `1dd1e786817fb0b155ad988f9231123fbe3722eec9fc7c942f2e8ecf46721af4` | True |
| Q02 | fixture collision: a step's eventType contains the step name (#8's prefix survivor) | `test_no_two_leaves_of_a_notified_fixture_are_equal_and_no_text_contains_another` | `assert ["CONTAINS .p...released.v1'"] == []` | FAILED-AS-EXPECTED 1.1s | `1dd1e786817fb0b155ad988f9231123fbe3722eec9fc7c942f2e8ecf46721af4` | True |
| Q03 | sweep population: a new payload read appears in a template | `test_the_population_is_the_recorded_count_per_template_and_per_kind` | `AssertionError: assert {'invoice_iss....py': 15, ...} == {'invoice_iss....py': 14, ...}` | FAILED-AS-EXPECTED 1.1s | `c2a73e9ff058c664fbbf4db6f4661d33ee7d532d5cf3015dcd73e6d5994c5bfa` | True |
| Q05 | payload sites: an envelope id starts being rendered | `test_every_rendered_site_is_read_and_every_unrendered_field_is_not[order.completed.v1]` | `AssertionError: rendered but declared unrendered (or the reverse): unexpectedly unchanged []; unexpectedly changed ['aggregate_id']` | FAILED-AS-EXPECTED 1.1s | `6d5e411b47afd77fb1700fbcced44699b25eaf1d144b31c25ebb0e5c61e01f68` | True |
| Q04 | payload sites: a rendered field silently stops being rendered (Company line dropped) | `test_every_rendered_site_is_read_and_every_unrendered_field_is_not[order.confirmed.v1]` | `AssertionError: reaches only one of the text and HTML bodies: ['payload.company_code']` | FAILED-AS-EXPECTED 1.0s | `c2a73e9ff058c664fbbf4db6f4661d33ee7d532d5cf3015dcd73e6d5994c5bfa` | True |
| N08 | instrument: parity case 1's population literal loses Notifications | `test_case_1_every_write_models_copy_is_byte_identical_to_the_canonical_after_the_banner` | `AssertionError: [PosixPath('/home/juanpabloperez/Work/Projects/Assessments/order-to-cash-python/services/notifications/src/otc_notific...ects/Assessments/order-to-cash-py` | FAILED-AS-EXPECTED 0.9s | `d2829755954de76ce299397fbde6614d5019bac9e6890fb1b55769a6070b0612` | True |
| N09 | instrument: the confinement census loses Notifications' subscriber | `test_the_modules_importing_aiokafka_are_exactly_the_publishers_and_the_subscribers` | `assert ["the modules..._publisher']"] == []` | FAILED-AS-EXPECTED 1.0s | `10aa478f33c7212bd968d9838f77f5a99d7b9222f9964c7332c131e20afdb851` | True |
| N10 | instrument: the env-read roots literal loses notifications | `test_the_composition_roots_are_exactly_the_literal` | `AssertionError: assert ['billing', '...ders', 'seed'] == ['billing', '...ders', 'seed']` | FAILED-AS-EXPECTED 0.9s | `fbaa6bf16b435af86605c1842c61388e74a604b35acb1375147985c514658357` | True |
| N11 | instrument: the registration TABLES literal loses one notify command | `test_a_service_registers_only_from_its_composition_root_and_its_tables_match` | `AssertionError: assert ['otc_notific...Command', ...] == ['otc_notific...eivedCommand']` | FAILED-AS-EXPECTED 4.2s | `5bcb8fe5ade61de2551653979b89d790c55ce9177c7cc9072e1599c3d172c759` | True |
| N12 | instrument: the write-path census loses the ledger's DELETE entry | `test_every_write_path_in_the_service_is_a_classified_literal` | `AssertionError: services/notifications/src has an unclassified write path (or lost a classified one, or gained a second occurrence of one): add it to EXPECTED with its cl` | FAILED-AS-EXPECTED 1.1s | `a364aabe4053989d9db8be5f246d02f0de4cc280ed8b44a2e82e2abb8fc8cae0` | True |
| N13 | instrument: a new unclassified writer appears in Notifications | `test_every_write_path_in_the_service_is_a_classified_literal` | `AssertionError: services/notifications/src has an unclassified write path (or lost a classified one, or gained a second occurrence of one): add it to EXPECTED with its cl` | FAILED-AS-EXPECTED 1.1s | `7b241c93bc7cd4d3f2cb0e7663b1d7094e9df5c6c593020b0a334418f5c7861d` | True |

## 11. Live record (stack started and stopped; `.arm/n23/live/`)

`docker ps` before: `otcpy-n8n` only. Started `docker compose -p otcpy -f docker-compose.infra.yml start`; hosts `uvicorn otc_{fulfillment:8102,billing:8103,orders:8101}.main:app` and `NOTIFICATIONS_SENDER=smtp uvicorn otc_notifications.main:app --port 8104` (all `/health/ready` 200). Fresh orders over NATS `orders.create` (CarrefourEs / SPANATURAL): ORD-000011 (13333 EUR) driven to `completed` (payment over `billing.payment.register`, INV-000008, reference LIVE-REF-000011) and ORD-000012 (4599, the `.99` rule) to `cancelled`. ORD-000007 untouched.

```
== K3 inbox, total 8
----------------------------------------------------------------------------------------------------
To     : carrefoures@retailer.order-to-cash.example
From   : no-reply@order-to-cash.example
Subject: [order-to-cash] Order ORD-000011 placed (correlationId: 251a81ea-1ab1-4b23-a30c-00a51fc9949b)
Msg-ID : 8cdeb57a-70b5-446f-9fd5-f33f2f33b8ac@order-to-cash
Order ORD-000011 has been placed.
Retailer: CarrefourEs
Company: SPANATURAL
Total: 133.33 EUR
Order date: 2026-10-10T17:27:59.477Z
Correlation id: 251a81ea-1ab1-4b23-a30c-00a51fc9949b
----------------------------------------------------------------------------------------------------
To     : carrefoures@retailer.order-to-cash.example
From   : no-reply@order-to-cash.example
Subject: [order-to-cash] Order ORD-000012 placed (correlationId: 22547f28-08c0-491c-ac9e-f4ed2f76c644)
Msg-ID : 47a5971e-0309-4b8a-abcf-4eecbcfa49ed@order-to-cash
Order ORD-000012 has been placed.
Retailer: CarrefourEs
Company: SPANATURAL
Total: 45.99 EUR
Order date: 2026-10-10T17:27:59.658Z
Correlation id: 22547f28-08c0-491c-ac9e-f4ed2f76c644
----------------------------------------------------------------------------------------------------
To     : carrefoures@retailer.order-to-cash.example
From   : no-reply@order-to-cash.example
Subject: [order-to-cash] Order ORD-000011 confirmed (correlationId: 251a81ea-1ab1-4b23-a30c-00a51fc9949b)
Msg-ID : b866fd50-af9c-4bf3-a5ca-68c3f0cb8dce@order-to-cash
Order ORD-000011 has been confirmed — stock reserved and credit approved.
Retailer: CarrefourEs
Company: SPANATURAL
Total: 133.33 EUR
Confirmed at: 2026-10-10T17:27:59.980Z
Correlation id: 251a81ea-1ab1-4b23-a30c-00a51fc9949b
----------------------------------------------------------------------------------------------------
To     : carrefoures@retailer.order-to-cash.example
From   : no-reply@order-to-cash.example
Subject: [order-to-cash] Order ORD-000011 despatched (DES-000009) (correlationId: 251a81ea-1ab1-4b23-a30c-00a51fc9949b)
Msg-ID : 1eb8ebac-dc01-4a2d-892b-d03f5dcbc643@order-to-cash
Order ORD-000011 has been despatched.
Despatch reference: DES-000009
Despatch date: 2026-10-10T17:28:00.232Z
Retailer: CarrefourEs
Company: SPANATURAL
Lines: PRD-0001 x2, PRD-0002 x1
Correlation id: 251a81ea-1ab1-4b23-a30c-00a51fc9949b
----------------------------------------------------------------------------------------------------
To     : carrefoures@retailer.order-to-cash.example
From   : no-reply@order-to-cash.example
Subject: [order-to-cash] Invoice INV-000008 issued (correlationId: 251a81ea-1ab1-4b23-a30c-00a51fc9949b)
Msg-ID : 1745d7a6-d7b6-44ea-8811-b7f152183805@order-to-cash
Invoice INV-000008 has been issued for order ORD-000011.
Retailer: CarrefourEs
Company: SPANATURAL
Total: 133.33 EUR
Invoice date: 2026-10-10T17:28:00.492Z
Correlation id: 251a81ea-1ab1-4b23-a30c-00a51fc9949b
----------------------------------------------------------------------------------------------------
To     : carrefoures@retailer.order-to-cash.example
From   : no-reply@order-to-cash.example
Subject: [order-to-cash] Order ORD-000012 cancelled (correlationId: 22547f28-08c0-491c-ac9e-f4ed2f76c644)
Msg-ID : 24f4eef0-555e-48cd-8788-8e1612410a23@order-to-cash
Order ORD-000012 has been cancelled.
Reason: credit_rejected
Retailer: CarrefourEs
Company: SPANATURAL
Cancelled at: 2026-10-10T17:28:00.496Z
Compensation steps: stock_released
Correlation id: 22547f28-08c0-491c-ac9e-f4ed2f76c644
----------------------------------------------------------------------------------------------------
To     : ord-000011@retailer.order-to-cash.example
From   : no-reply@order-to-cash.example
Subject: [order-to-cash] Payment received for invoice INV-000008 (correlationId: 251a81ea-1ab1-4b23-a30c-00a51fc9949b)
Msg-ID : 8a00a2c3-e5f3-4394-8ae8-b357ee6566fa@order-to-cash
Payment LIVE-REF-000011 has been received for invoice INV-000008 (order ORD-000011).
Amount: 133.33 EUR
Value date: 2026-10-10T17:29:10.000Z
Source: operator
Correlation id: 251a81ea-1ab1-4b23-a30c-00a51fc9949b
----------------------------------------------------------------------------------------------------
To     : carrefoures@retailer.order-to-cash.example
From   : no-reply@order-to-cash.example
Subject: [order-to-cash] Order ORD-000011 completed (correlationId: 251a81ea-1ab1-4b23-a30c-00a51fc9949b)
Msg-ID : 618c52c9-98ab-4d15-bc15-5d10b1e30e7b@order-to-cash
Order ORD-000011 is complete — despatched, invoiced and paid.
Retailer: CarrefourEs
Company: SPANATURAL
Total: 133.33 EUR
Completed at: 2026-10-10T17:28:09.935Z
Correlation id: 251a81ea-1ab1-4b23-a30c-00a51fc9949b

               event_id               |   consumer    |        processed_at        
--------------------------------------+---------------+----------------------------
 8cdeb57a-70b5-446f-9fd5-f33f2f33b8ac | notifications | 2026-10-10 17:27:59.745+00
 47a5971e-0309-4b8a-abcf-4eecbcfa49ed | notifications | 2026-10-10 17:27:59.939+00
 b866fd50-af9c-4bf3-a5ca-68c3f0cb8dce | notifications | 2026-10-10 17:28:00.468+00
 1eb8ebac-dc01-4a2d-892b-d03f5dcbc643 | notifications | 2026-10-10 17:28:00.491+00
 1745d7a6-d7b6-44ea-8811-b7f152183805 | notifications | 2026-10-10 17:28:00.722+00
 24f4eef0-555e-48cd-8788-8e1612410a23 | notifications | 2026-10-10 17:28:00.982+00
 8a00a2c3-e5f3-4394-8ae8-b357ee6566fa | notifications | 2026-10-10 17:28:10.13+00
 618c52c9-98ab-4d15-bc15-5d10b1e30e7b | notifications | 2026-10-10 17:28:10.385+00
(8 rows)


```

Redelivery, byte-identical (same key, value, headers), then the group lag read:
```
before: inbox=8 ledger=8
read 8 notified facts of the two orders
republished invoice.issued.v1 1745d7a6-d7b6-44ea-8811-b7f152183805 1b08a8af22da
republished payment.received.v1 8a00a2c3-e5f3-4394-8ae8-b357ee6566fa 00ef0f9df6ef
republished order.placed.v1 8cdeb57a-70b5-446f-9fd5-f33f2f33b8ac 9292ba2bf2c4
republished order.confirmed.v1 b866fd50-af9c-4bf3-a5ca-68c3f0cb8dce 8d57e76dbd4d
republished order.completed.v1 618c52c9-98ab-4d15-bc15-5d10b1e30e7b 09c4874757ba
republished order.placed.v1 47a5971e-0309-4b8a-abcf-4eecbcfa49ed 246955679e81
republished order.cancelled.v1 24f4eef0-555e-48cd-8788-8e1612410a23 3cb2381a67b1
republished order.despatched.v1 1eb8ebac-dc01-4a2d-892b-d03f5dcbc643 33d6d046b26d
group lag per partition after the redelivery (0 everywhere = every record consumed): {'otc.orders.facts.v1[2]': 0, 'otc.orders.facts.v1[1]': 0, 'otc.fulfillment.facts.v1[2]': 0, 'otc.fulfillment.facts.v1[1]': 0, 'otc.billing.facts.v1[2]': 0, 'otc.billing.facts.v1[1]': 0}
after: inbox=8 ledger=8

```
After stopping and restarting the Notifications host and republishing again:
```
restart: before inbox=8 ledger=8
read 16 notified facts of the two orders
group lag per partition after the redelivery (0 everywhere = every record consumed): {'otc.orders.facts.v1[2]': 0, 'otc.orders.facts.v1[1]': 0, 'otc.fulfillment.facts.v1[2]': 0, 'otc.fulfillment.facts.v1[1]': 0, 'otc.billing.facts.v1[2]': 0, 'otc.billing.facts.v1[1]': 0}
restart: after inbox=8 ledger=8

```
Stopped by SIGTERM (each log ends `Application shutdown complete`, 0 `Traceback`, ports 8101-8104 free); containers stopped; `docker ps` after: `otcpy-n8n` only.

Register of altered live fixtures (add to the earlier registers): orders ORD-000011 `completed`, ORD-000012 `cancelled`; INV-000008 `paid`, payment LIVE-REF-000011; DES-000009; stock PRD-0001 (2), PRD-0002 (1) consumed and PRD-0003 reserve+release for SPANATURAL; the `CarrefourEs`/`SPANATURAL` credit line moved by the hold, consume and release; `otc_notifications.processed_events` 8 rows; the developer Mailpit inbox holds the 8 messages (not cleared); the three Kafka fact topics hold 16 extra duplicate records of those orders' notified facts; consumer group `notifications` has committed offsets (lag 0). 

## 12. Inherited findings: avoided or recurred

#8 58 avoided; 59 avoided; 60 avoided; 73 avoided (built); 56 avoided; 68 avoided; 76 avoided; 85 avoided; 82 partly recurred (B03's message is a probe traceback, not a one-line claim); #8's "parity guard against a population of one" avoided (case 1 now asserts the two-member population literal); #7's in-memory ledger avoided (I05); #7's stale "latest" ordering avoided by design. Recurred: none beyond B03. #8 94 and 74/75/104 are deferred to feature 27 by ownership.

## 13. What I could not do, and what surprised me

- Dead-letter and retry are feature 27's: a notified fact with a poisoned payload, or a transient send failure, holds its partition and is retried paced 1 s doubling to 30 s until then (same as Orders).
- `.env.example` and compose carry no `NOTIFICATIONS_*` / `SMTP_*` variables (root config is outside my bounds); the defaults make the host run (console sender). Suggest the leader document `NOTIFICATIONS_SENDER`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_EMAIL`, `NOTIFICATIONS_KAFKA_CLIENT_ID`, `NOTIFICATIONS_CONSUMER_GROUP`.
- CLAUDE.md asks for structlog JSON with `correlationId` in contextvars; like the other services this one logs through stdlib `logging`; feature 27 owns observability.
- Surprise: a boot whose consumer never finishes `start()` hung the cleanup forever (the stop event is not seen inside `start()`); fixed with a grace period then cancellation, and a test. The Mailpit module of testcontainers needs `cryptography` (see Q5). Mailpit's `Text` carries CRLF.
- Classification: full group (Kafka consumer, durable ledger); an Opus reviewer follows.

## 14. Packages installed

`Packages installed:` uv: `aiosmtplib==5.1.3` (new to the lock); `aiokafka>=0.14.0` declared for `otc-notifications` (already locked at 0.14.0 for other services). npm: none. No dependency added to `packages/shared_kernel` or `packages/cqrs`.

## 15. Review findings fixed (N1, N2, N3, X1; light; `feature_list.json` untouched)

Backups in `.arm/n23-fix/` (`composition.py` sha256 `01dc26134b50a554b6b79b77bded2ce3e6295f34a02cf08f7347ba742e51be88`, `degrading_sender.py` sha256 `57e1f497b69991c45a49dd0f43eed5f8203f12841efac34fa46d3218cbdf47de`); each restored by `cp`, confirmed with `cmp`, `__pycache__` cleared.

- **N1.** `composition.py`: `NotificationsRuntime.__init__` takes `stop_grace_seconds` (default `STOP_GRACE_SECONDS`), `stop()` passes it to `_stop_tasks`, `start_runtime` passes its own value. `test_a_consumer_that_never_joins_its_group_...` now bounds its wait with `asyncio.timeout(15)` and fails with "the stuck consumer task was not cancelled after the grace period". New `test_stop_cancels_a_send_that_never_returns_after_the_grace_and_forgets_its_row` (sender that never returns; `runtime.stop()` returns after 0.3 s; `task.cancelled()`; `ledger_rows() == []`). The test factory (`conftest.py`) gained a `stop_grace_seconds` keyword on its sender path.
- **N2.** Test renamed to `test_r18_a_redelivery_after_a_runtime_restart_within_one_process_sends_nothing_more`; docstring names `test_delivery_ledger.py::test_forget_removes_exactly_the_pair_and_the_event_can_be_recorded_again` (R19b) as the process-wide-cache guard and section 11's PIDs 2689861 and 2703138 as the real-process evidence; module docstring says "runtime restart". Command `grep -rn "after_a_process_restart" . --include=*.md --include=*.py | grep -v ".venv|.arm/|progress/review_|progress/brief_"` prints nothing after the edit; the references fixed were `specs/shared/test-matrix.md` (R18, column 5), rows I01 and I05 of section 10 of this record. (The review and brief keep the old name as history.)
- **N3.** Section 3: the seven rows now carry #7 and #8 file:line (each read from the checkouts this session); two departure rows added (instants; environment names). Section 2: item 1 (instants match #7's wire-form string, depart from #8's `:O`) and item 4 (names are #7's; only `NOTIFICATIONS_SENDER`, `SMTP_START_TLS` are #9's own) corrected. Citations read: `notification-facts.controller.ts:174-175`, `main.ts:24-53`, `NotificationFactsConsumer.cs:86-99,180`, `ProcessedEventLedger.cs:42-45`, `KafkaFactStreamSubscriber.cs:77,117`, `MoneyText.cs:34`, `NotificationFormat.cs:46,62`, `SendFailureClassifier.cs:72`, `ProjectorConsumesOnlyTests.cs:12-15`. Note: #7 `.env.example` has no SMTP block (only the Kafka pair at 136-137), so the SMTP names are cited from `smtp.config.ts:54-89`.
- **X1.** The real-SMTP test asserts `len(delivered) == 1` with "the refused fact is not retried: the inbox holds N messages, not 1" before destructuring.

| Arm | Mutation | Test | Verbatim failure | Result |
|---|---|---|---|---|
| F01 | R20: `task.cancel()` -> `pass` | `test_a_consumer_that_never_joins_its_group_times_out_the_boot_and_leaves_no_task` | `Failed: the stuck consumer task was not cancelled after the grace period: the failed boot is still waiting for it` | FAILED-AS-EXPECTED, 25.2 s (was a 180 s hang) |
| F02 | same | `test_stop_cancels_a_send_that_never_returns_after_the_grace_and_forgets_its_row` | `Failed: runtime.stop() did not return: the task was not cancelled after the grace period` | FAILED-AS-EXPECTED, 26.0 s |
| F03 | R13i: degrading sender re-raises after the fallback | `test_notification_send_failure_real_smtp.py` (the 550 test) | `AssertionError: the refused fact is not retried: the inbox holds 2 messages, not 1` | FAILED-AS-EXPECTED, 14.1 s |

Final: `pytest services/notifications/tests tests/architecture` 861 passed in 73.2 s; ruff check, ruff format --check and mypy on `services/notifications` clean. `./quality.sh` was not re-run in full.
