# otc-seed: the deterministic, idempotent seed job

`python -m otc_seed` writes the same dataset #7 and #8 seed into the four stores of the development stack: the `otc_orders`, `otc_fulfillment` and `otc_billing` PostgreSQL databases and the MongoDB `order_timeline` read model. It is a one-shot CLI, not a service.

```
docker compose -f docker-compose.infra.yml up -d postgres mongodb      # the stack
uv run alembic -c services/orders/alembic.ini upgrade head             # the databases must be at head
uv run alembic -c services/fulfillment/alembic.ini upgrade head
uv run alembic -c services/billing/alembic.ini upgrade head
uv run python -m otc_seed                                              # reads ./.env
```

Configuration is `pydantic-settings` only (`.env` in the working directory, or the environment): `POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_HOST_PORT`, `POSTGRES_DB_ORDERS|FULFILLMENT|BILLING`, `MONGO_HOST`, `MONGO_HOST_PORT`, `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD`, `MONGO_DB_READMODEL`; a full `ORDERS_DATABASE_URL` / `FULFILLMENT_DATABASE_URL` / `BILLING_DATABASE_URL` / `MONGO_URI` wins over its parts. There is no password default. Exit codes: 0 seeded, 1 a store refused (not migrated to head, unreachable), 2 no credential.

What it writes: 3 currencies, 12 products, 7 retailers, 22 companies, 154 credit lines, 215 stock rows, and six sagas (five completed orders and one cancelled order, `ORD-000001..006`) with their reservations, despatches, invoices, payments, credit ledger entries, 50 already-published outbox rows and 6 `order_timeline` documents. Every id is `deterministic_id(namespace)`, a SHA-256 of `otc-seed:<namespace>` laid out as a UUID, and every instant is a fixed past UTC instant, so two runs produce the same rows. A second run inserts nothing (and rewrites nothing: a row or document that already exists is left as it is, because stock units, order status and a projector-advanced timeline are live state).

The seed must run before the first live order: it owns `ORD-000001..006`, `DES-000001..005` and `INV-000001..005`, and the number allocators of the services must start above them (the seed writes no counter row; #8's allocator seeds its counter from `MAX(order_reference)`).

## Seeded causal chain versus live causal chain (backlog 201)

The seeded `causationId` chain is #7's and #8's, unchanged (that is what dataset parity means), and it is **one link shorter than a live saga's**. The seed has no commands, so the two root facts (`order.placed.v1`, `payment.received.v1`) cite a synthetic deterministic command id and every other fact cites the `eventId` of the fact that triggered it: every entry of a seeded timeline has a "caused by" link. In a live saga a fact produced by an RPC responder (Fulfillment's `stock.reserved.v1`, Billing's `credit.approved.v1`, ...) cites the triggering COMMAND's id, which is never a timeline entry, so a live timeline links only the facts Orders itself emits. Whether that changes is the phase 12 decision of backlog 201; until then neither claim in the UI or README may describe the seeded behaviour as the live one.

## Tests

Unit tests are pure (`services/seed/tests/unit`); integration tests (`services/seed/tests/integration`, `pytest.mark.integration`) run against Docker-held `postgres:18.6` (the three services' Alembic-migrated templates, never a schema the seed created) and `mongo:8.3.8`. The oracle fixtures in `services/seed/tests/fixtures/` are #7's own TypeScript output (`toTimelineDocument` over #7's `SAGAS`, and the dataset behind it), checked in before any writer existed.
