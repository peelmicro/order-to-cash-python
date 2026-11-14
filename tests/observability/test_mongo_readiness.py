"""Entry 217: a MongoDB container is handed out only once the REAL server answers.

`MongoDbContainer` is declared ready on the first "Waiting for connections" line, logged by the
image's temporary init `mongod` (127.0.0.1 only); the real server logs the second ~5 s later. The
helper `wait_until_mongo_answers` in `health_support.py` closes that window for all three
`MongoDbContainer` sites.
"""

import importlib.util
import itertools
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

SUPPORT_PATH = Path(__file__).resolve().parent / "health_support.py"
USER = "otc_ready"
PASSWORD = "otc_ready_password"


def _support() -> ModuleType:
    spec = importlib.util.spec_from_file_location("health_support", SUPPORT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


support = _support()


@pytest.mark.integration
def test_n217_the_first_authenticated_ping_through_the_mapped_port_succeeds_at_once() -> None:
    container = support.MongoDbContainer(support.MONGO_IMAGE, username=USER, password=PASSWORD)
    with container:
        support.wait_until_mongo_answers(container, USER, PASSWORD)
        uri = (
            f"mongodb://{USER}:{PASSWORD}@{container.get_container_host_ip()}:"
            f"{container.get_exposed_port(27017)}/?authSource=admin"
        )
        client: MongoClient[dict[str, object]] = MongoClient(uri, serverSelectionTimeoutMS=300)
        try:
            assert client.admin.command("ping")["ok"] == 1.0
        finally:
            client.close()


class _Container:
    def get_container_host_ip(self) -> str:
        return "127.0.0.1"

    def get_exposed_port(self, port: int) -> int:
        return port


def test_n217_the_wait_is_paced_and_bounded_when_every_ping_fails_in_microseconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[float] = []

    class _FailsAtOnce:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            attempts.append(time.monotonic())
            self.admin = self

        def command(self, _name: str) -> None:
            raise ConnectionFailure("reset by peer")

        def close(self) -> None:
            return None

    monkeypatch.setattr(support, "MongoClient", _FailsAtOnce)
    budget = 1.2
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="did not answer an authenticated ping"):
        support.wait_until_mongo_answers(_Container(), USER, PASSWORD, budget_seconds=budget)
    elapsed = time.monotonic() - started

    assert budget <= elapsed < budget + 1.0, (
        f"the wait took {elapsed:.2f} s for a {budget} s budget"
    )
    assert len(attempts) <= int(budget / support.POLL_INTERVAL_SECONDS) + 2, (
        f"{len(attempts)} pings in {budget} s: the loop is not paced"
    )
    gaps = [b - a for a, b in itertools.pairwise(attempts)]
    assert gaps
    assert min(gaps) >= support.POLL_INTERVAL_SECONDS * 0.9
