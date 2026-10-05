"""Seed test fixtures: the two oracle files, loaded once.

* `order_timeline_from_number7.json`: the six `order_timeline` documents, produced by executing #7's
  own `toTimelineDocument` (`apps/seed/src/writers/mongo.writer.ts`) over #7's own `SAGAS` (tsx,
  from `order-to-cash-nestjs/apps/seed`). Byte-identical (as parsed JSON) to the fixture #8 checked
  in (`tests/Seed.IntegrationTests/OracleFixtures/order_timeline_from_number7.json`), which a second
  agent had derived independently in #8's review. Checked in BEFORE any writer existed.
* `seed_dataset_from_number7.json`: every master-data table and every saga (rows, outbox payloads,
  timeline entries) as #7's TypeScript computes them, plus the id/GLN/EAN vectors. Same derivation,
  same provenance: `JSON.stringify` of #7's exported constants.

Neither file was written by this port: they are the expected values, not a snapshot of its output.
"""

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def number7_timeline() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(
        (FIXTURES / "order_timeline_from_number7.json").read_text(encoding="utf-8")
    )
    return data


@pytest.fixture(scope="session")
def number7_dataset() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (FIXTURES / "seed_dataset_from_number7.json").read_text(encoding="utf-8")
    )
    return data


def _leaves(value: Any, path: str = "") -> dict[str, tuple[type, Any]]:
    """Flatten a document to `path -> (exact type, value)`: a list element is addressed by its
    INDEX, so order is part of the comparison, and the exact type is part of the leaf, so `True` is
    not `1`, `1` is not `1.0` and `null` is not `""`."""
    if isinstance(value, dict):
        out: dict[str, tuple[type, Any]] = {path + "{}": (dict, sorted(value))}
        for key, child in value.items():
            out.update(_leaves(child, f"{path}.{key}"))
        return out
    if isinstance(value, list):
        out = {path + "[]": (list, len(value))}
        for index, child in enumerate(value):
            out.update(_leaves(child, f"{path}[{index}]"))
        return out
    return {path: (type(value), value)}


@pytest.fixture(scope="session")
def assert_timeline_matches_oracle() -> Any:
    """`check(documents, oracle)`: assert every seeded `order_timeline` document equals #7's, field
    by field (the D1 class of #8's review: a value test, not a presence test). The population is the
    oracle's six documents matched by `orderReference`; every leaf of every document is compared,
    with its path in the failure message (`ORD-000003 .events[4].causationId`)."""

    def check(documents: list[dict[str, Any]], oracle: list[dict[str, Any]]) -> None:
        by_reference = {d["orderReference"]: d for d in documents}
        assert sorted(by_reference) == sorted(o["orderReference"] for o in oracle), (
            "the seeded documents are not the oracle's six orders"
        )
        assert len(documents) == len(oracle)
        for expected in oracle:
            actual = by_reference[expected["orderReference"]]
            want, have = _leaves(expected), _leaves(actual)
            for path in sorted(set(want) | set(have)):
                assert have.get(path) == want.get(path), (
                    f"{expected['orderReference']} {path}: seeded {have.get(path)!r}, "
                    f"#7 produced {want.get(path)!r}"
                )

    return check
