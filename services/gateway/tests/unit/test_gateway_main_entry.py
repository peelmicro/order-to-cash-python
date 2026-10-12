"""`python -m otc_gateway` bounds the graceful shutdown (feature 26): an open `GET /orders/stream`
never ends by itself, and uvicorn waits for every open response before it runs the lifespan's
shutdown, so without `timeout_graceful_shutdown` a stop signal hangs behind the first browser tab.
The port itself is held by `tests/integration/test_gateway_listens_on_gateway_port.py`."""

from typing import Any

import pytest
import uvicorn

from otc_gateway import __main__ as entry


def test_r55_the_entry_point_hands_uvicorn_a_graceful_shutdown_bound(
    required_environment: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(app: str, **kwargs: Any) -> None:
        seen.update(kwargs, app=app)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    required_environment.setenv("GATEWAY_PORT", "38123")

    entry.main()

    assert seen["port"] == 38123
    assert "timeout_graceful_shutdown" in seen, "uvicorn.run was given no graceful-shutdown bound"
    assert seen["timeout_graceful_shutdown"] == entry.GRACEFUL_SHUTDOWN_SECONDS
    assert isinstance(seen["timeout_graceful_shutdown"], int)
    assert 0 < seen["timeout_graceful_shutdown"] <= 30
