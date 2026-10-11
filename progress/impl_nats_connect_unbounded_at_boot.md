# Implementation: nats_connect_unbounded_at_boot (backlog 214, light)

Orders, Fulfillment and Billing `composition.py` each gained `NATS_CONNECT_SECONDS = 10.0` and a keyword `nats_connect_seconds` on `start_runtime`; the boot's `nats.connect(settings.nats.url)` now runs under `asyncio.timeout`, re-raised as `RuntimeError("NATS_URL <url> did not accept a connection within <n> s")`. Runtime reconnect settings are the client defaults, untouched. The module-level `nats.connect` call is kept (existing host-lifespan tests monkeypatch it); a cancelled connect leaves no task (asserted), so the projector's caller-owned `Client` shape was not needed.

Tests (one per service, integration, Docker-held nats port with the entrypoint replaced by `sleep`, wait under `asyncio.timeout(20)`, asserts elapsed < 5 s, error names `NATS_URL`, the URL and the bound, no leftover task):
- `services/orders/tests/integration/test_orders_nats_connect_bound.py`
- `services/fulfillment/tests/integration/test_fulfillment_nats_connect_bound.py`
- `services/billing/tests/integration/test_billing_nats_connect_bound.py`

Arms (`.arm/n214/`, sha256 recorded, `cp`/`cmp` restore, caches cleared): `asyncio.timeout(nats_connect_seconds)` -> `asyncio.timeout(None)` in each service. Each failed at ~20 s with `Failed: 214: the <service> boot did not fail within 20 s against a 2 s bound` (fulfillment's message later shortened to "within 20 s of a 2 s bound" for line length; re-run green, arm not repeated on the reworded string). Restored and green.

Green: orders+fulfillment+billing+tests/architecture 2698 passed; ruff check/format clean; mypy --strict no issues (726 files). `quality.sh` not run (leader).
Surprise: a closed Docker-held port makes the unbounded call run the full 20 s test wait, so the arm costs ~20 s each.
