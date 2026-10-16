Problem documents captured from a RUNNING #9 Gateway (`uv run python -m otc_gateway`, 2026-10-15) with curl, bodies only, byte for byte:

- `login-401.json`: `POST /auth/login` with a wrong password.
- `orders-no-token-401.json`: `GET /orders` with no Authorization header.
- `order-bad-id-400.json`: `GET /orders/not-a-uuid` with a valid token (carries `errors[]`).

Tests feed these through the BFF and the login page so that the shape under test is the real one, not one this repository invented (#7's generic-error defect hid behind hand-written shapes).
