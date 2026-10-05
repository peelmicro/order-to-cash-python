"""The use case and the composition root's boot validation.

R-map (feature_list.json id 12): every target is verified BEFORE any target writes (a database that
is not migrated stops the run with nothing written anywhere); a missing or unknown target raises at
build time (CLAUDE.md: "a missing binding raises in the lifespan, never as an AttributeError on the
first message"); a run reports what it ADDED.
"""

from collections.abc import Mapping

import pytest

from otc_seed.application import SeedDataset, SeedReport, SeedTarget, default_dataset, run_seed
from otc_seed.composition import EXPECTED_TARGETS, build_runtime, validate_wiring
from otc_seed.infrastructure.settings import SeedSettings


class _FakeTarget:
    def __init__(self, name: str, log: list[str], *, fail_verify: bool = False) -> None:
        self.name = name
        self._log = log
        self._fail_verify = fail_verify

    async def verify(self) -> None:
        self._log.append(f"verify:{self.name}")
        if self._fail_verify:
            raise RuntimeError(f"{self.name} is not migrated")

    async def seed(self, dataset: SeedDataset) -> Mapping[str, int]:
        self._log.append(f"seed:{self.name}")
        return {"rows": len(dataset.sagas)}


async def test_every_target_is_verified_before_any_target_writes() -> None:
    log: list[str] = []
    targets: list[SeedTarget] = [_FakeTarget("a", log), _FakeTarget("b", log)]
    report = await run_seed(targets)
    assert log == ["verify:a", "verify:b", "seed:a", "seed:b"]
    assert report == SeedReport({"a": {"rows": 6}, "b": {"rows": 6}})
    assert report.total_added == 12


async def test_a_target_that_fails_verification_stops_the_run_before_any_write() -> None:
    log: list[str] = []
    targets: list[SeedTarget] = [
        _FakeTarget("a", log),
        _FakeTarget("b", log, fail_verify=True),
    ]
    with pytest.raises(RuntimeError, match="b is not migrated"):
        await run_seed(targets)
    assert log == ["verify:a", "verify:b"]  # not one `seed:` line


async def test_two_targets_with_one_name_are_refused() -> None:
    log: list[str] = []
    with pytest.raises(ValueError, match="share a name"):
        await run_seed([_FakeTarget("a", log), _FakeTarget("a", log)])
    assert log == []


async def test_the_default_dataset_is_used_when_none_is_given() -> None:
    log: list[str] = []
    seen: list[SeedDataset] = []

    class _Capture(_FakeTarget):
        async def seed(self, dataset: SeedDataset) -> Mapping[str, int]:
            seen.append(dataset)
            return {}

    await run_seed([_Capture("a", log)])
    assert seen == [default_dataset()]


def test_wiring_accepts_exactly_the_four_expected_targets() -> None:
    log: list[str] = []
    validate_wiring([_FakeTarget(name, log) for name in EXPECTED_TARGETS])
    assert EXPECTED_TARGETS == ("orders", "fulfillment", "billing", "mongo")


@pytest.mark.parametrize("missing", EXPECTED_TARGETS)
def test_wiring_refuses_a_missing_target_naming_it(missing: str) -> None:
    log: list[str] = []
    targets = [_FakeTarget(n, log) for n in EXPECTED_TARGETS if n != missing]
    with pytest.raises(RuntimeError, match="seed wiring") as raised:
        validate_wiring(targets)
    assert missing not in str(raised.value).split("got")[1]


def test_wiring_refuses_a_duplicate_and_an_unknown_target() -> None:
    log: list[str] = []
    with pytest.raises(RuntimeError, match="seed wiring"):
        validate_wiring([_FakeTarget(n, log) for n in (*EXPECTED_TARGETS, "orders")])
    with pytest.raises(RuntimeError, match="seed wiring"):
        validate_wiring([_FakeTarget(n, log) for n in (*EXPECTED_TARGETS[:3], "kafka")])


async def test_the_composition_root_builds_exactly_the_four_targets_in_write_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """The real `build_runtime` (engines and the Mongo client are lazy, so no server is needed):
    a target dropped from, or added to, the root fails here and not on the first write."""
    monkeypatch.chdir(str(tmp_path))
    for name, value in {
        "ORDERS_DATABASE_URL": "postgresql+asyncpg://u:p@127.0.0.1:1/o",
        "FULFILLMENT_DATABASE_URL": "postgresql+asyncpg://u:p@127.0.0.1:1/f",
        "BILLING_DATABASE_URL": "postgresql+asyncpg://u:p@127.0.0.1:1/b",
        "MONGO_URI": "mongodb://u:p@127.0.0.1:1/?authSource=admin",
    }.items():
        monkeypatch.setenv(name, value)
    runtime = build_runtime(SeedSettings(_env_file=None))  # type: ignore[call-arg]
    try:
        assert tuple(t.name for t in runtime.targets) == EXPECTED_TARGETS
    finally:
        await runtime.aclose()
