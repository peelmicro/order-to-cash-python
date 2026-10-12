# Premise check — brief_impl_orders_catalog_responder.md
VERIFIED asyncapi.yaml:545 `address: catalog.reference.list` (channel catalogReferenceList at 544); request payload at 3713, reply payload at 3731 (sed/grep)
VERIFIED channel summary: "Reference data for the place-order form. Caller — gateway. Responder — orders." (line 548; brief quotes the tail)
VERIFIED openapi.yaml /catalog/products 777, /catalog/retailers 802, /catalog/companies 827, ending ~851 (grep -n)
VERIFIED CatalogReferenceListRequestPayload has `kinds` (products|retailers|companies|currencies) and `includeDisabled` (boolean, default false), asyncapi.yaml:3716-3728
VERIFIED Orders tables have a disabled notion: `disabled_at` at persistence/models.py:79, 93, 107; reference_catalog.py adapter has no enabled/disabled filter today
VERIFIED ports/reference_catalog.py has ReferenceCatalog with find_retailer, find_company, currency_exists, find_products (exactly four)
VERIFIED persistence/reference_catalog.py defines SqlAlchemyReferenceCatalog (line 17); composition.py:354 builds it
VERIFIED place_order.py uses it (via scope.catalog: ReferenceCatalog, application/scope.py:30; calls at place_order.py:112,115,118,120)
VERIFIED presentation/orders_create_responder.py:45 class OrdersCreateResponder; messaging/{subjects,rpc_reply}.py exist; subscribes with queue=ORDERS_QUEUE_GROUP (line 63)
VERIFIED services/orders/tests/unit/test_rpc_subjects.py exists and reads asyncapi.yaml (ASYNCAPI, line 18); it has no 'catalog' reference yet (brief does not claim one)
VERIFIED tests/architecture/test_registration_behaviour.py and test_cqrs_registration_explicit.py exist
VERIFIED #8 14d9a66 "catalog and cancel responders" (40+41 in one commit; adds ListCatalogReferenceQuery, EfCoreOrderReferenceCatalog, RpcSubjects.cs); 461e987 "unify orders.*/catalog.* payload records into src/Contracts/Rpc"
VERIFIED #8 history.md:1684 heading orders_catalog_responder; next heading (cancel) at 1707, so 1684-1706 is the record
VERIFIED #8 progress/impl_orders_catalog_responder.md and review_orders_catalog_responder.md exist
VERIFIED #7 32da6e9 "catalog and cancel NATS responders"; #7 history.md:1067 heading "orders_catalog_responder (id 40, phase 13)"
VERIFIED #7 catalog-reference-list.controller.spec.ts, application/ports/catalog-reference-list.port.ts exist; app.module.ts:127-136 `useExisting: ORDER_REFERENCE_DATA`
VERIFIED docs/lessons.md:123 describes #7's gateway_rest_auth first rejection ("both sides of the seam were tested only against the wire each preferred")
VERIFIED feature 40 has two acceptance items (feature_list.json:446-449)
FALSE   "Feature 40 is `in_progress`" (line 3) — feature_list.json:445 (working tree and HEAD) says "status": "pending"
VERIFIED brief forbids nothing acceptance mandates: acceptance 2 needs list reads on the port/adapter, both inside allowed paths (application/ports, infrastructure/persistence/reference_catalog.py); no domain/models edit needed (disabled_at columns exist)
UNVERIFIABLE-pending Gateway claims (feature 25 "approved", /catalog/* routes, client in services/gateway/**, progress/impl_gateway_rest_auth.md contents) — being built
Verdict: DO NOT ACT until fixed (1 FALSE, 18 VERIFIED, 1 UNVERIFIABLE-pending)
