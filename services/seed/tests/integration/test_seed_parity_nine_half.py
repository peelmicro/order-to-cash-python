"""The #9 half of `scripts/seed_parity.py`, end to end against the seeded test containers.

R-map (feature_list.json id 12, acceptance 5): the dump of #9's PostgreSQL and MongoDB writes the 19
files, with the literal row counts, normalised (instants, uuid case, integers), canonical JSON.
(The same command against the developer stack is recorded in progress/impl_seed_job.md.)
"""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from otc_seed.application import run_seed
from otc_seed.composition import SeedRuntime
from otc_seed.infrastructure.settings import SeedSettings

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "seed_parity.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("seed_parity_it", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_parity_it"] = module
    spec.loader.exec_module(module)
    return module


def _every_file_is_sorted(directory: Path) -> bool:
    files = list(directory.glob("*.jsonl"))
    return len(files) == 20 and all(
        (lines := p.read_text(encoding="utf-8").splitlines()) == sorted(lines) for p in files
    )


async def test_the_nine_half_dumps_the_literal_subset_normalised(
    runtime: SeedRuntime, settings: SeedSettings, tmp_path: Path, number7_timeline: list[Any]
) -> None:
    parity = _load()
    await run_seed(runtime.targets)
    files = await parity.collect_nine(settings)
    counts = parity.write_files(tmp_path, files)

    assert len(counts) == 20  # 18 tables + the stock live section + the timeline collection
    assert counts["fulfillment.stock.jsonl"] == 215
    assert counts["billing.credits.jsonl"] == 154
    assert counts["mongo.order_timeline.jsonl"] == 6
    assert sum(c for n, c in counts.items() if n.endswith(".outbox.jsonl")) == 50

    first_order = next(
        json.loads(line)
        for line in (tmp_path / "orders.orders.jsonl").read_text(encoding="utf-8").splitlines()
        if '"ORD-000001"' in line
    )
    assert first_order["order_date"] == "2026-06-01T09:00:00.000Z"
    assert first_order["id"] == "1741d5aa-cfba-4205-a1c0-82e7a5cb8984"
    assert first_order["total_amount"] == 16130
    assert "seq" not in (tmp_path / "orders.outbox.jsonl").read_text(encoding="utf-8")
    raw = (tmp_path / "orders.retailers.jsonl").read_text(encoding="utf-8")
    assert "Aldi España" in raw  # written as UTF-8, raw
    lines = (tmp_path / "mongo.order_timeline.jsonl").read_text(encoding="utf-8").splitlines()
    assert sorted(json.loads(line)["orderReference"] for line in lines) == [
        d["orderReference"] for d in number7_timeline
    ]
    # a file is sorted, so row order is not a claim
    assert _every_file_is_sorted(tmp_path)


async def test_the_nine_half_fails_on_an_unseeded_stack_instead_of_writing_empty_files(
    settings: SeedSettings, tmp_path: Path
) -> None:
    parity = _load()
    with pytest.raises(SystemExit, match="literal keys missing"):
        await parity.collect_nine(settings)
