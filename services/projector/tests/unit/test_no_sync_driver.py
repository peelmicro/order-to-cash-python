"""K6 (ledger L19, L40): no synchronous MongoDB driver, no Motor, anywhere under `src`.

aiokafka heartbeats from a coroutine on the SAME event loop, so a blocking call in a handler stalls
the group (ledger L40); `pymongo.MongoClient` (and `pymongo.synchronous`) is blocking I/O, and Motor
is deprecated in favour of PyMongo's own async API and absent from `uv.lock`. The async client is
`pymongo.AsyncMongoClient`, a different name, and is the only one allowed.
"""

import ast
from pathlib import Path

import pytest

import otc_projector

SRC = Path(otc_projector.__file__).resolve().parent


def sync_driver_uses(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root == "motor" or alias.name.startswith("pymongo.synchronous"):
                    found.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root == "motor" or node.module.startswith("pymongo.synchronous"):
                found.append(f"line {node.lineno}: from {node.module} import ...")
            if root == "pymongo" and any(
                a.name in {"MongoClient", "synchronous"} for a in node.names
            ):
                found.append(f"line {node.lineno}: from {node.module} import MongoClient")
        elif isinstance(node, ast.Attribute) and node.attr in {"MongoClient", "synchronous"}:
            found.append(f"line {node.lineno}: .{node.attr}")
    return found


def test_no_module_under_src_imports_the_sync_pymongo_client_or_motor() -> None:
    files = sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)
    assert len(files) > 25, f"the scan covered {len(files)} files"
    offenders = {
        str(p.relative_to(SRC)): hits
        for p in files
        if (hits := sync_driver_uses(p.read_text(encoding="utf-8")))
    }
    assert offenders == {}, f"a synchronous driver is used: {offenders}"


@pytest.mark.parametrize(
    "source",
    [
        "from pymongo import MongoClient\n",
        "from pymongo import AsyncMongoClient, MongoClient\n",
        "import pymongo\nc = pymongo.MongoClient()\n",
        "from pymongo.synchronous.mongo_client import MongoClient\n",
        "import pymongo.synchronous\n",
        "import motor.motor_asyncio\n",
        "from motor import motor_asyncio\n",
        "if False:\n    from pymongo import MongoClient\n",
    ],
)
def test_sentinel_every_form_of_a_sync_driver_import_is_seen(source: str) -> None:
    assert sync_driver_uses(source), source


def test_sentinel_the_async_client_is_not_a_sync_driver() -> None:
    assert sync_driver_uses("from pymongo import AsyncMongoClient\nx = AsyncMongoClient\n") == []
