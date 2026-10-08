# Premise check: brief_review_fulfillment_despatch.md
VERIFIED 18 in_review with three acceptance items - python json of feature_list.json: id 18 status in_review, 3 acceptance bullets
VERIFIED shared anchors - requirements.md:279 is R36; domain-model.md:311-313 are F6,F7,F8; asyncapi.yaml:397-399 despatchCreate / address fulfillment.despatch.create; order.despatched.v1 at :1423; RpcHeaders :2816; RpcError :2840
VERIFIED feature 17 design sections 15, 6.3, 6.5, 8, 10 exist - grep of specs/fulfillment_stock/design.md headings
VERIFIED #8 history 1126 ~1 h 46 min, 1 impl pass + fix, 2 review rounds, rejected on test asserting opposite of name - sed 1126-1140 of dotnet history
VERIFIED #8 1167 Phase 9 closing assessment - sed 1167
VERIFIED #7 863 fulfillment_despatch, ~1 h 03 min, approved first pass, fault-injection proof - sed 863-880 of nestjs history
VERIFIED only otcpy-n8n runs - docker ps --format '{{.Names}}' => otcpy-n8n
VERIFIED nothing under services/orders/src, packages/, specs/fulfillment_stock beyond feature 17 since the brief - git status --porcelain shows only specs/fulfillment_stock/ untracked (feature 17); find services/orders packages specs/fulfillment_stock -newer progress/brief_impl_fulfillment_despatch.md => empty. (services/orders/tests/integration/conftest.py modified 05:33, before the brief 09:33: pre-existing.)
VERIFIED files changed since brief outside services/fulfillment - find -newer: feature_list.json, specs/shared/test-matrix.md, 3 named tests/architecture files, impl report (also progress/current.md and the brief itself, unlisted, benign)
VERIFIED impl report cites - section 11 live check (ORD-000007, DES-000006, reservations consumed, Orders "saga fact ignored", still stock_reserved), section 8 F8 layers (I3a_v2 UNAVAILABLE, I3b_v2 PRECONDITION_FAILED, I4_v2 40001), section 2 deviations (items 1,3,8,9), P2 and X9 equivalent (line 193), T3 identity control green (line 127), 87 arms/76 red/7 superseded
VERIFIED 2784 passed, +94 over 2690 - impl report line 3 states 2784 (reported, quality.sh not rerun; arithmetic 2784-2690=94 holds if baseline is 2690, see line 3)
VERIFIED named test files exist - services/fulfillment/tests/unit/test_stock_responder.py, integration/test_fulfillment_host_lifespan.py, tests/architecture/{test_registration_behaviour,test_write_path_population,test_fulfillment_rpc_error_retryability}.py
UNVERIFIABLE implementer ~74 min (4 434 s), premise check ~1.5 min - no artifact
UNVERIFIABLE quality.sh exit 0 / arm counts as run results - would need a suite run (reported-by-design)
UNVERIFIABLE F8 later saga despatch.create for ORD-000007 returns created:false and stalls at confirmed - question put to the reviewer, settled only by running
CONFLICT none with CLAUDE.md
Verdict: SAFE TO ACT (0 FALSE, 0 CONFLICT)
