# Brief — implementer, feature 40 `orders_catalog_responder` (phase 13, `sdd: false`, full group)

**Task:** implement feature 40 from its acceptance items (`feature_list.json` id 40, **two** items). Feature 40 is set `in_progress` by the leader at dispatch. There is no spec phase (`sdd: false`): the specification of record is the two items, `specs/shared/asyncapi.yaml`'s `catalogReferenceList` channel (line 545, address `catalog.reference.list`, *"Caller — gateway. Responder — orders."*) with `CatalogReferenceListRequestPayload` (line 3713) and `CatalogReferenceListReplyPayload` (line 3731), and `specs/shared/openapi.yaml`'s `/catalog/products`, `/catalog/retailers`, `/catalog/companies` (lines 777 – 851). Classification: **full group** (a new RPC responder is a wire contract), so an Opus reviewer follows. Because `sdd: false`, the **ported-idiom ledger lives in your impl record**.

## Inputs (found on disk by the leader this session)

- **The Gateway exists** (feature 25, approved before this dispatch): its `/catalog/*` routes and its `catalog.reference.list` client are in `services/gateway/src/otc_gateway/**`; read `progress/impl_gateway_rest_auth.md` for what the Gateway sends and how it maps errors. Acceptance 1 is proven **through that real Gateway** against your real responder (testcontainers), not against a stub on either side — the seam `docs/lessons.md` line 123 describes (#7's first gateway rejection: client and responder each green against the wire it preferred). If the Gateway's client and the contract disagree, stop and report; do not edit `services/gateway/`.
- **The lookup order acceptance already calls** (acceptance 2): the port `services/orders/src/otc_orders/application/ports/reference_catalog.py` (`ReferenceCatalog`: `find_retailer`, `find_company`, `currency_exists`, `find_products`) and its one adapter `services/orders/src/otc_orders/infrastructure/persistence/reference_catalog.py` (`SqlAlchemyReferenceCatalog`), used by `application/commands/place_order.py`. "Exposed as a query": a `otc_cqrs.Query[R]` with its handler registered **explicitly in `services/orders/src/otc_orders/composition.py`** (CLAUDE.md's dispatcher rule; the registration guards `tests/architecture/test_registration_behaviour.py` and `test_cqrs_registration_explicit.py` will see a new Orders registration — run them).
- **The existing responder:** `services/orders/src/otc_orders/presentation/orders_create_responder.py` (`OrdersCreateResponder`) and `infrastructure/messaging/{subjects,rpc_reply}.py`; the subject guard `services/orders/tests/unit/test_rpc_subjects.py` asserts subjects against `asyncapi.yaml`. Decide — with #7's and #8's citations — whether `catalog.reference.list` is a second subscription on the same responder task or a task of its own (CLAUDE.md: "One asyncio task class per transport … started and awaited on shutdown by the lifespan"), and whether it subscribes with a NATS queue group (#8's review left "subscribed without a queue group" as an item; what does #9's `orders.create` do?).
- **#8 (baseline, rejected once):** commit `14d9a66` in `../order-to-cash-dotnet` (40 + 41 in one commit — tell 40's half from it), later `461e987` (Orders/catalog RPC payload records unified); record `../order-to-cash-dotnet/progress/history.md` lines 1684 – 1706; `progress/impl_orders_catalog_responder.md` and `progress/review_orders_catalog_responder.md` there.
- **#7 (approved first time):** commit `32da6e9` in `../order-to-cash-nestjs`; record `../order-to-cash-nestjs/progress/history.md` line 1067; its controller spec `apps/orders/src/presentation/catalog-reference-list.controller.spec.ts`, its port `catalog-reference-list.port.ts` and the `useExisting` wiring in `app.module.ts` (find the lines).

## What #8's record says to carry (read the lines; this summary is not the finding)

Each is named **avoided** or **recurred** in your record:

- **D1:** the `includeDisabled` request flag was unguarded end to end, and the shared fixture seeded no disabled row, so the flag's effect was never observed. #7 guarded it in its first pass. Every request field of `CatalogReferenceListRequestPayload` reaches the query and changes the result in a test whose fixture makes the change visible (a disabled row of each kind, if the schema has the notion — read the schema and the Orders tables).
- **D2:** a ledger row whose "#7 relied on X" half was invented. Each history half is read out of #7's and #8's checkouts with a file and line; the "same instance place-order uses" claim is a two-party claim — probe it.
- **A4:** a guard named in the ledger is a guard owed an arm.
- **A5:** the "ordered by code" claim was guarded for products only; deleting the ordering from the other lists stayed green. Every list the reply carries has its ordering guarded, with a fixture whose insertion order differs from code order **and** from its reverse (Phase 12's R50 lesson: a fixture's order must differ from every plausible wrong order).
- Enumerate #8's tests for this mechanism by content and classify each assertion: ported / deliberately not ported (reason) / not applicable.

## Must hold (each guard armed)

- The reply validates against `CatalogReferenceListReplyPayload` (read through `otc_contracts`' generated model and the one serializer — camelCase, compact, `ensure_ascii` off), money as integer minor units with the currency code, never a float.
- Malformed request → the `RpcError` the contract and #9's other responders use (cite `orders.create`'s behaviour); the responder never leaves a request unanswered on a path it can reach.
- The list query issues reads only (no write, no lock) and owns its `AsyncSession` per request.
- `GET /catalog/products|retailers|companies` through the real Gateway return the seeded rows (acceptance 1), each field asserted, with fixture values pairwise distinct across fields.

## Process

- Arming protocol (grep `CLAUDE.md` on disk): backups in `.arm/n40/` with `sha256`; one named test per arm; failure message names the claim and arrives fast; restore by `cp` + `cmp`; clear caches; a timeout kills the whole process group. Defeat list rows stated.
- Baseline `./quality.sh` first with the developer stack down (exit code, pytest time and pass count), a second at the end, the delta and the time per test. Wait on the real PID; read the verdict from the log.
- `specs/shared/test-matrix.md` column 5 only for rows this feature proves, and the derived counts.
- Write `progress/impl_orders_catalog_responder.md` early and keep it updated.

## Live walkthrough

Read the live-data registers (`progress/current.md` "Live dev data"). Start the stack and the Orders and Gateway hosts; `curl` the three catalog routes through the Gateway with a token; record the bodies (counts and first rows). Stop everything you started so only `otcpy-n8n` runs (`docker ps` before and after).

## Bounds

May touch: `services/orders/src/otc_orders/{application,presentation,infrastructure/messaging,infrastructure/persistence/reference_catalog.py,composition.py,main.py}` and `services/orders/tests/**`; `tests/architecture/**` only where a guard's literal must include the new registration (report each); `specs/shared/test-matrix.md` (as above); `progress/impl_orders_catalog_responder.md`; feature 40's status line in `feature_list.json`. **No edit to `services/orders/src/otc_orders/domain/**`, `alembic/**`, `persistence/models.py`, `services/gateway/**`, other services or `packages/**`** — stop and report if one is needed. No new package without a reason. No git command that writes the index or working tree.

## Output

`progress/impl_orders_catalog_responder.md`: what was built; the task/queue-group decision with citations; the ledger (file and line on both halves, armed guard, what turns red if the row were false); the guard-port table; the arming table (mutation, test, verbatim message, `sha256`, `cmp`); defeat-list rows; the live record; each inherited finding avoided / recurred; the two `quality.sh` runs; `Packages installed:`. Set feature 40 to `in_review` (that line only). Return only "result in `progress/impl_orders_catalog_responder.md`" plus at most 5 lines.

## Premise check

`progress/premise_impl_orders_catalog_responder.md`: one false claim (feature 40's status at the time of writing; the leader sets `in_progress` at dispatch), corrected above. Verified there: the request carries `kinds` and `includeDisabled` (`asyncapi.yaml:3716-3728`), the Orders reference tables carry `disabled_at` (`persistence/models.py:79, 93, 107`), and today's adapter has no enabled/disabled filter — so `includeDisabled` is new behaviour on the read path, and D1 above is directly in scope.
