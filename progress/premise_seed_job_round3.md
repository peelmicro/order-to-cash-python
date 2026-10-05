# Premise check, seed_job round 3

VERIFIED #8 compose is docker-compose.infra.yml, `name: otcnet` at line 29; .env line 22 COMPOSE_PROJECT_NAME=otcnet
VERIFIED mssql container otcnet-mssql, port `${MSSQL_HOST_PORT:-1433}:1433` (lines 65, 85); mongodb otcnet-mongodb, `${MONGO_HOST_PORT:-27017}:27017` (132, 139)
VERIFIED volumes mssql_data / mongodb_data mounted (87, 141); `docker volume ls` shows otcnet_mssql_data and otcnet_mongodb_data
VERIFIED no otcnet-* container exists (`docker ps -a` names: none start with otcnet; `otc-sonarqube` is a different name)
VERIFIED otcpy stack 12 running containers (`docker ps | grep -c otcpy` = 12), otcpy-mongodb on 0.0.0.0:27017
VERIFIED mssql (lines 63-129) and mongodb (130-153) have no depends_on (first depends_on is line 217, kafka-init); `up -d mssql mongodb` starts only those two (plus network otcnet-net creation)
VERIFIED sequences.py orders 12-14 SEED_ORDER_SEQUENCE text exact
FALSE (minor) fulfillment and billing SEED_* are at sequences.py:15-17 (3 lines, split string), not 15-16; same shape and ON CONFLICT clause otherwise (billing line 15 SEED_INVOICE_SEQUENCE, fulfillment line 15 SEED_DESPATCH_SEQUENCE)
VERIFIED three counter tables order/despatch/invoice_number_sequences appear in models.py and alembic 0001 of the three services only
VERIFIED #8 impl_order_number_allocator_scan_cost.md exists (id 47; evaluates MAX only when the sequence row does not exist; plan before/after in contract) and impl_order_number_allocator_seed_race.md exists (id 45)
VERIFIED #7 order-number-allocator.ts:56-70 is the numeric MAX (D6 comment, `cast(... as unsigned)`, startAt line 70); path apps/orders/src/infrastructure/persistence/order-number-allocator.ts
VERIFIED tests/fixtures/ holds only golden_envelopes/ (`ls tests/fixtures`)
VERIFIED feature_list id 24 last acceptance item names tests/fixtures/read_model_constants.json; ids 211, 212 attached to seed_job phase 7 as described; id 12 is in_review
VERIFIED CLAUDE.md line 51 "Findings are fixed in the phase that detects them" is on disk
VERIFIED prefixes ORD-/DES-/INV- are 4 characters (business_reference.py docstring; #7 comment "fixed 4-character ORD-")
VERIFIED seed oracle counts: sagas 6, credits 154, stock 215, order_timeline fixture 6 documents (services/seed/tests/fixtures)
VERIFIED services/seed/tests/fixtures/ holds order_timeline_from_number7.json and seed_dataset_from_number7.json (#7 oracle)
VERIFIED timeline.py line 10 says "sync by inspection and by tests/unit/test_timeline_value_guard.py" (comment to update exists)
VERIFIED progress/evidence/ does not exist yet (brief says new directory)
VERIFIED seed_parity.py dump8 does NOT read #8's .env: needs MSSQL_APP_PASSWORD (no default) and EIGHT_MONGO_URI supplied as env vars (lines 531, 551); defaults: user otc_app, container otcnet-mssql, db names otc_orders/otc_fulfillment/otc_billing, MONGO_DB_READMODEL otc_read_model. #8 .env holds MSSQL_APP_PASSWORD (line 42) and MONGO_INITDB_ROOT_USERNAME/PASSWORD (57-58), so the caller must export them.
UNVERIFIABLE whether #8's databases hold the seeded subset (needs containers started; brief step 3 handles it)
UNVERIFIABLE "maintainer ran otc_seed, second run totalAdded 0" (no command settles a past session action)

Verdict: 1 FALSE (minor line range), 2 UNVERIFIABLE.
