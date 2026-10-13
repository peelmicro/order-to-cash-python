"""The observability modules are COPIES of Orders' (feature 27 `design.md` 10; S1.5).

`infrastructure/observability/logging.py` is canonical in Orders and copied to the other five
services; a copy cannot drift. This module REUSES the instrument of `test_outbox_copy_parity.py`
(`split_docstring`, `expected_body`: the text after the module docstring equals the canonical's
after the service's token map and the repository formatter) and re-runs its premises for this
family on temporary trees, because changing the instrument's population swaps its premises
(CLAUDE.md "Changing an instrument"):

* P1 the docstring is the module's first statement (`ast`), else the copy fails;
* P2 the preamble is every line before the docstring's first line and it must be empty here (no
  allow-list: no copy needs a deviation);
* P3 the docstring statement begins at column 0;
* P4 the tail test slices BYTES, not characters (`end_col_offset` counts UTF-8 bytes).

A second family, `infrastructure/messaging/{fact_retry,dead_letter_publisher}.py` (`OR2`, S4.7), has
a DIFFERENT population: the three services that consume facts, a literal that must equal the
packages `asyncapi.yaml`'s fact `receive` operations name, and a copy found in any other service
fails. The publisher is inside the family on purpose: #8's three publishers were outside every
parity family, and a corrupted `x-first-failed-at` in one copy left that service green (#8 review
round 1, D3/P7).

The population is the literal `SERVICES` (six runtime packages) plus `NOT_RUNTIME` (the seed, a
CLI that writes no log contract); a package under `services/*/src` that is in neither fails by name,
so a seventh service cannot silently skip the family. Each copy's docstring is its own and must name
its canonical's path.
"""

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_SERVICE = "orders"
# service -> package directory name under services/<service>/src
SERVICES = {
    "orders": "otc_orders",
    "gateway": "otc_gateway",
    "fulfillment": "otc_fulfillment",
    "billing": "otc_billing",
    "notifications": "otc_notifications",
    "projector": "otc_projector",
}
NOT_RUNTIME = {"seed"}  # a CLI: it installs no log handler and holds no observability family
OBSERVABILITY_DIR = "infrastructure/observability"
# The modules of the observability family. Later stages append: trace_context, telemetry, metrics.
OBSERVABILITY_MODULES = ["logging.py", "metrics.py", "telemetry.py", "trace_context.py"]
MESSAGING_DIR = "infrastructure/messaging"
MESSAGING_MODULES = ["fact_retry.py", "dead_letter_publisher.py"]
# The fact consumers: a LITERAL, compared with what `asyncapi.yaml` declares (never derived).
FACT_CONSUMERS = ("orders", "projector", "notifications")
# `asyncapi.yaml`'s `Consumer name - <name>.` (the fact `receive` operations) -> the package.
SPEC_CONSUMER_PACKAGE = {
    "orders.saga": "orders",
    "projector": "projector",
    "notifications": "notifications",
}
FACT_CHANNELS = ("ordersFacts", "fulfillmentFacts", "billingFacts")
ASYNCAPI = REPO_ROOT / "specs/shared/asyncapi.yaml"


def _load_instrument() -> ModuleType:
    """`test_outbox_copy_parity.py` loaded by path (the suite runs in importlib mode, so a sibling
    test module is not importable by name)."""
    path = REPO_ROOT / "tests/architecture/test_outbox_copy_parity.py"
    spec = importlib.util.spec_from_file_location("outbox_copy_parity_instrument", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INSTRUMENT = _load_instrument()


class Parts(NamedTuple):
    preamble: str
    docstring: str
    closing_tail: str
    body: str


def split_docstring(text: str) -> Parts | None:
    parts = INSTRUMENT.split_docstring(text)
    return None if parts is None else Parts(*parts)


def expected_body(
    canonical_text: str, filename: str, service: str, canonical: str = CANONICAL_SERVICE
) -> str:
    token_map = {SERVICES[canonical]: SERVICES[service]}
    result: str = INSTRUMENT.expected_body(canonical_text, filename, token_map)
    return result


def module_path(root: Path, service: str, name: str, directory: str = OBSERVABILITY_DIR) -> Path:
    return root / "services" / service / "src" / SERVICES[service] / directory / name


def violations(
    root: Path,
    modules: list[str] | None = None,
    *,
    directory: str = OBSERVABILITY_DIR,
    services: tuple[str, ...] | None = None,
    canonical_service: str = CANONICAL_SERVICE,
) -> list[str]:
    """Every difference between the copies and the canonical under `root` (by default the
    observability family over all six services, canonical in Orders)."""
    found: list[str] = []
    for name in OBSERVABILITY_MODULES if modules is None else modules:
        canonical = module_path(root, canonical_service, name, directory)
        canonical_rel = canonical.relative_to(root).as_posix()
        if not canonical.is_file():
            found.append(f"{name}: the canonical {canonical_rel} is missing")
            continue
        canonical_text = canonical.read_text(encoding="utf-8")
        canonical_parts = split_docstring(canonical_text)
        if canonical_parts is None:
            found.append(f"{name}: the canonical has no module docstring")
            continue
        if canonical_parts.preamble != "" or canonical_parts.closing_tail.strip():
            found.append(f"{name}: the canonical has text outside its docstring's own lines")
        for service in tuple(SERVICES) if services is None else services:
            if service == canonical_service:
                continue
            copy = module_path(root, service, name, directory)
            label = f"{service}/{name}"
            if not copy.is_file():
                found.append(f"{label}: the copy is missing")
                continue
            copy_text = copy.read_text(encoding="utf-8")
            parts = split_docstring(copy_text)
            if parts is None:
                found.append(f"{label}: the copy has no module docstring")
                continue
            if parts.preamble != "":
                found.append(f"{label}: lines before the docstring: {parts.preamble!r}")
            if parts.closing_tail.strip():
                found.append(f"{label}: text follows the docstring's closing quotes")
            if canonical_rel not in parts.docstring:
                found.append(f"{label}: the copy's docstring does not name {canonical_rel}")
            expected = expected_body(canonical_text, copy.as_posix(), service, canonical_service)
            if parts.body.lstrip("\n") != expected:
                found.append(f"{label}: differs from the canonical after the docstring")
    return found


def population(root: Path) -> list[str]:
    """Packages under `services/*/src` that are neither a listed service nor a non-runtime one."""
    listed = {f"{service}:{package}" for service, package in SERVICES.items()}
    on_disk = {
        f"{path.parts[-3]}:{path.name}"
        for path in root.glob("services/*/src/otc_*")
        if path.is_dir() and not path.name.startswith("__")
    }
    unlisted = sorted(on_disk - listed - {f"{name}:otc_{name}" for name in NOT_RUNTIME})
    missing = sorted(listed - on_disk)
    return [f"unlisted service package: {item}" for item in unlisted] + [
        f"listed service package not on disk: {item}" for item in missing
    ]


def directory_census(root: Path) -> list[str]:
    found: list[str] = []
    for service in SERVICES:
        folder = root / "services" / service / "src" / SERVICES[service] / OBSERVABILITY_DIR
        on_disk = sorted(path.name for path in folder.glob("*.py")) if folder.is_dir() else []
        expected = sorted(["__init__.py", *OBSERVABILITY_MODULES])
        if on_disk != expected:
            found.append(f"{service}: observability/ holds {on_disk}, expected exactly {expected}")
    return found


def test_the_observability_modules_are_faithful_copies_of_the_orders_canonical() -> None:
    assert violations(REPO_ROOT) == []


def test_the_population_is_the_six_listed_services_and_no_other_package() -> None:
    assert population(REPO_ROOT) == []
    assert len(SERVICES) == 6


def test_every_observability_directory_holds_exactly_the_family() -> None:
    assert directory_census(REPO_ROOT) == []


def test_every_package_init_is_empty() -> None:
    for service, package in SERVICES.items():
        init = REPO_ROOT / f"services/{service}/src/{package}/{OBSERVABILITY_DIR}/__init__.py"
        assert init.read_text(encoding="utf-8") == "", f"{service}: observability/__init__.py"


def messaging_violations(root: Path) -> list[str]:
    """The `fact_retry` / `dead_letter_publisher` family: the three consumers' copies, and no copy
    in any other service package (a hidden fourth holder is reported by name)."""
    found = violations(root, MESSAGING_MODULES, directory=MESSAGING_DIR, services=FACT_CONSUMERS)
    for service in SERVICES:
        if service in FACT_CONSUMERS:
            continue
        for name in MESSAGING_MODULES:
            stray = module_path(root, service, name, MESSAGING_DIR)
            if stray.exists():
                found.append(f"{service}/{name}: a copy in a service that consumes no fact")
    return found


def spec_consumer_packages(
    spec_text: str, mapping: dict[str, str] = SPEC_CONSUMER_PACKAGE
) -> set[str]:
    """The packages `asyncapi.yaml`'s `receive` operations on the three fact channels name, through
    their `summary: Consumer name - <name>.` (a name the map does not know raises, by name)."""
    operations = yaml.safe_load(spec_text)["operations"]
    packages: set[str] = set()
    for operation in operations.values():
        channel = operation["channel"]["$ref"].rsplit("/", 1)[1]
        if operation["action"] == "receive" and channel in FACT_CHANNELS:
            summary: str = operation["summary"]
            prefix = "Consumer name \u2014 "
            assert summary.startswith(prefix), summary
            name = summary.removeprefix(prefix).rstrip(".")
            assert name in mapping, f"asyncapi.yaml names an unmapped consumer: {name}"
            packages.add(mapping[name])
    return packages


def test_or2_every_fact_consuming_service_holds_the_canonical_retry_and_dead_letter_modules() -> (
    None
):
    assert messaging_violations(REPO_ROOT) == []
    assert len(FACT_CONSUMERS) == 3
    for service in FACT_CONSUMERS:
        for name in MESSAGING_MODULES:
            assert module_path(REPO_ROOT, service, name, MESSAGING_DIR).is_file(), (service, name)


def test_or2_the_population_equals_the_spec_consumers_and_no_other_service_holds_a_copy() -> None:
    assert set(FACT_CONSUMERS) == spec_consumer_packages(ASYNCAPI.read_text(encoding="utf-8"))
    holders = {
        service
        for service in SERVICES
        for name in MESSAGING_MODULES
        if module_path(REPO_ROOT, service, name, MESSAGING_DIR).exists()
    }
    assert holders == set(FACT_CONSUMERS)


# The readiness family (`R60`, S6.1): FIVE modules with FIVE populations, a literal each (a service
# holds a probe only for a dependency it has: design 7.1). A copy in a service the table does not
# name is reported, and so is a missing one. The Gateway's `infrastructure/health_checks.py` is the
# copy of `checks.py` at a different path.
HEALTH_DIR = "infrastructure/health"
GATEWAY_CHECKS = "infrastructure/health_checks.py"
HEALTH_FAMILY: dict[str, tuple[str, tuple[str, ...]]] = {
    "checks.py": ("orders", ("fulfillment", "billing", "notifications", "projector")),
    "postgres_probe.py": ("orders", ("fulfillment", "billing", "notifications")),
    "nats_probe.py": ("orders", ("fulfillment", "billing", "projector", "gateway")),
    "kafka_probe.py": ("orders", ("notifications", "projector")),
    "mongo_probe.py": ("projector", ("gateway",)),
}


def health_violations(root: Path) -> list[str]:
    found: list[str] = []
    for name, (canonical, copies) in HEALTH_FAMILY.items():
        found += violations(
            root, [name], directory=HEALTH_DIR, services=copies, canonical_service=canonical
        )
        holders = {canonical, *copies}
        for service in SERVICES:
            if service not in holders and module_path(root, service, name, HEALTH_DIR).exists():
                found.append(f"{service}/{name}: a copy in a service the table does not name")
    found += gateway_checks_violations(root)
    return found


def gateway_checks_violations(root: Path) -> list[str]:
    """The Gateway's `health_checks.py` equals Orders' `checks.py` after the docstring."""
    canonical = module_path(root, "orders", "checks.py", HEALTH_DIR)
    copy = root / "services/gateway/src" / SERVICES["gateway"] / GATEWAY_CHECKS
    if not copy.is_file():
        return ["gateway/health_checks.py: the copy is missing"]
    parts = split_docstring(copy.read_text(encoding="utf-8"))
    if parts is None:
        return ["gateway/health_checks.py: the copy has no module docstring"]
    found: list[str] = []
    if parts.preamble != "":
        found.append(f"gateway/health_checks.py: lines before the docstring: {parts.preamble!r}")
    if parts.closing_tail.strip():
        found.append("gateway/health_checks.py: text follows the docstring's closing quotes")
    if canonical.relative_to(root).as_posix() not in parts.docstring:
        found.append("gateway/health_checks.py: the copy's docstring does not name its canonical")
    expected = expected_body(canonical.read_text(encoding="utf-8"), copy.as_posix(), "gateway")
    if parts.body.lstrip("\n") != expected:
        found.append("gateway/health_checks.py: differs from the canonical after the docstring")
    return found


def health_census(root: Path) -> list[str]:
    """Every `health/` directory holds exactly the modules the table gives that service."""
    found: list[str] = []
    for service in SERVICES:
        expected = sorted(
            ["__init__.py"]
            + [
                name
                for name, (canonical, copies) in HEALTH_FAMILY.items()
                if service in {canonical, *copies}
            ]
        )
        folder = root / "services" / service / "src" / SERVICES[service] / HEALTH_DIR
        on_disk = sorted(path.name for path in folder.glob("*.py")) if folder.is_dir() else []
        if on_disk != expected:
            found.append(f"{service}: health/ holds {on_disk}, expected exactly {expected}")
    return found


def test_r60_the_health_modules_are_faithful_copies_of_their_canonicals() -> None:
    assert health_violations(REPO_ROOT) == []


def test_r60_every_health_directory_holds_exactly_the_modules_the_table_gives_its_service() -> None:
    assert health_census(REPO_ROOT) == []
    # the literal itself: five modules, and the number of copies (4 + 3 + 4 + 2 + 1)
    assert sorted(HEALTH_FAMILY) == [
        "checks.py",
        "kafka_probe.py",
        "mongo_probe.py",
        "nats_probe.py",
        "postgres_probe.py",
    ]
    assert sum(len(copies) for _, copies in HEALTH_FAMILY.values()) == 14


# ------------------------------------------------------------------------------------- sentinels


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A copy of just the observability family of every service, in its real layout."""
    for service, package in SERVICES.items():
        source = REPO_ROOT / "services" / service / "src" / package / OBSERVABILITY_DIR
        target = tmp_path / "services" / service / "src" / package / OBSERVABILITY_DIR
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def test_sentinel_a_pristine_tree_has_no_violation(tree: Path) -> None:
    assert violations(tree) == []
    assert directory_census(tree) == []


def test_sentinel_one_character_changed_in_one_copy_is_named(tree: Path) -> None:
    copy = module_path(tree, "billing", "logging.py")
    text = copy.read_text(encoding="utf-8")
    assert "ensure_ascii=False" in text
    copy.write_text(text.replace("ensure_ascii=False", "ensure_ascii=True"), encoding="utf-8")
    assert violations(tree) == [
        "billing/logging.py: differs from the canonical after the docstring"
    ]


def test_sentinel_a_comment_added_to_a_copy_is_named(tree: Path) -> None:
    copy = module_path(tree, "projector", "logging.py")
    copy.write_text(copy.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    assert violations(tree) == [
        "projector/logging.py: differs from the canonical after the docstring"
    ]


def test_sentinel_a_deleted_copy_is_named(tree: Path) -> None:
    module_path(tree, "gateway", "logging.py").unlink()
    assert violations(tree) == ["gateway/logging.py: the copy is missing"]
    assert directory_census(tree) != []


def test_sentinel_p2_a_line_before_the_docstring_is_named(tree: Path) -> None:
    copy = module_path(tree, "fulfillment", "logging.py")
    copy.write_text("# ruff: noqa\n" + copy.read_text(encoding="utf-8"), encoding="utf-8")
    [message] = violations(tree)
    assert message.startswith("fulfillment/logging.py: lines before the docstring")


def test_sentinel_p3_p4_code_after_the_closing_quotes_with_non_ascii_earlier_is_named(
    tree: Path,
) -> None:
    copy = module_path(tree, "notifications", "logging.py")
    text = copy.read_text(encoding="utf-8")
    # the docstring's closing line gets a non-ASCII word before the quotes and code after them
    closing = '\n"""\n'
    assert text.count(closing) == 1
    mutated = text.replace(closing, '\nñandú"""; HIDDEN = 1\n')
    copy.write_text(mutated, encoding="utf-8")
    messages = violations(tree)
    assert "notifications/logging.py: text follows the docstring's closing quotes" in messages


def test_sentinel_p1_a_copy_with_no_docstring_is_named(tree: Path) -> None:
    copy = module_path(tree, "gateway", "logging.py")
    text = copy.read_text(encoding="utf-8")
    copy.write_text("import os\n" + text, encoding="utf-8")
    messages = violations(tree)
    assert "gateway/logging.py: the copy has no module docstring" in messages


def test_sentinel_a_docstring_that_does_not_name_its_canonical_is_named(tree: Path) -> None:
    copy = module_path(tree, "billing", "logging.py")
    text = copy.read_text(encoding="utf-8")
    copy.write_text(text.replace("services/orders/src/otc_orders", "elsewhere"), encoding="utf-8")
    [message] = violations(tree)
    assert message.startswith("billing/logging.py: the copy's docstring does not name")


def test_sentinel_a_seventh_service_package_is_named(tree: Path) -> None:
    (tree / "services/reporting/src/otc_reporting").mkdir(parents=True)
    assert population(tree) == ["unlisted service package: reporting:otc_reporting"]


# ------------------------------------------------- the messaging family (OR2): sentinels


@pytest.fixture
def messaging_tree(tmp_path: Path) -> Path:
    """A copy of just the messaging family's modules of the three consumers, in their layout."""
    for service in FACT_CONSUMERS:
        for name in MESSAGING_MODULES:
            source = module_path(REPO_ROOT, service, name, MESSAGING_DIR)
            target = module_path(tmp_path, service, name, MESSAGING_DIR)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    return tmp_path


def test_sentinel_a_pristine_messaging_tree_has_no_violation(messaging_tree: Path) -> None:
    assert messaging_violations(messaging_tree) == []


@pytest.mark.parametrize(
    ("module", "needle", "replacement"),
    [
        ("fact_retry.py", "first_failed_at = failed_at", "first_failed_at = entered"),
        ("dead_letter_publisher.py", '"x-first-failed-at"', '"x-failed-at"'),
    ],
)
def test_sentinel_a_one_character_class_change_in_one_copy_of_each_module_is_named(
    messaging_tree: Path, module: str, needle: str, replacement: str
) -> None:
    copy = module_path(messaging_tree, "projector", module, MESSAGING_DIR)
    text = copy.read_text(encoding="utf-8")
    assert needle in text
    copy.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
    assert messaging_violations(messaging_tree) == [
        f"projector/{module}: differs from the canonical after the docstring"
    ]


def test_sentinel_one_character_in_the_notifications_publisher_is_named(
    messaging_tree: Path,
) -> None:
    copy = module_path(messaging_tree, "notifications", "dead_letter_publisher.py", MESSAGING_DIR)
    text = copy.read_text(encoding="utf-8")
    assert "ERROR_LIMIT = 1000" in text
    copy.write_text(text.replace("ERROR_LIMIT = 1000", "ERROR_LIMIT = 1001"), encoding="utf-8")
    assert messaging_violations(messaging_tree) == [
        "notifications/dead_letter_publisher.py: differs from the canonical after the docstring"
    ]


def test_sentinel_a_deleted_messaging_copy_is_named(messaging_tree: Path) -> None:
    module_path(messaging_tree, "notifications", "fact_retry.py", MESSAGING_DIR).unlink()
    assert messaging_violations(messaging_tree) == [
        "notifications/fact_retry.py: the copy is missing"
    ]


def test_sentinel_a_copy_planted_in_billing_is_named(messaging_tree: Path) -> None:
    planted = module_path(messaging_tree, "billing", "fact_retry.py", MESSAGING_DIR)
    planted.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(module_path(messaging_tree, "orders", "fact_retry.py", MESSAGING_DIR), planted)
    assert messaging_violations(messaging_tree) == [
        "billing/fact_retry.py: a copy in a service that consumes no fact"
    ]


def test_sentinel_a_fourth_declared_consumer_with_no_copy_is_not_the_literal() -> None:
    spec = ASYNCAPI.read_text(encoding="utf-8")
    assert spec_consumer_packages(spec) == set(FACT_CONSUMERS)
    # a fourth consumer the spec could declare: a receive operation naming `fulfillment`
    extended = yaml.safe_load(spec)
    extended["operations"]["fulfillmentConsumesOrdersFacts"] = {
        "action": "receive",
        "channel": {"$ref": "#/channels/ordersFacts"},
        "summary": "Consumer name \u2014 fulfillment.",
    }
    text = yaml.safe_dump(extended)
    with pytest.raises(AssertionError, match="unmapped consumer: fulfillment"):
        spec_consumer_packages(text)
    # and once mapped, the population differs from the literal, so the real test would fail
    mapped = {**SPEC_CONSUMER_PACKAGE, "fulfillment": "fulfillment"}
    assert spec_consumer_packages(text, mapped) == {*FACT_CONSUMERS, "fulfillment"}
    assert spec_consumer_packages(text, mapped) != set(FACT_CONSUMERS)


# ------------------------------------------------------- the health family (R60): sentinels


@pytest.fixture
def health_tree(tmp_path: Path) -> Path:
    """The health directories of every service, and the Gateway's `health_checks.py`."""
    for service, package in SERVICES.items():
        source = REPO_ROOT / "services" / service / "src" / package / HEALTH_DIR
        target = tmp_path / "services" / service / "src" / package / HEALTH_DIR
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    gateway = Path("services/gateway/src") / SERVICES["gateway"] / GATEWAY_CHECKS
    (tmp_path / gateway).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO_ROOT / gateway, tmp_path / gateway)
    return tmp_path


def test_sentinel_a_pristine_health_tree_has_no_violation(health_tree: Path) -> None:
    assert health_violations(health_tree) == []
    assert health_census(health_tree) == []


@pytest.mark.parametrize(
    ("service", "module", "needle", "replacement"),
    [
        ("fulfillment", "checks.py", "CHECK_TIMEOUT_SECONDS = 2.0", "CHECK_TIMEOUT_SECONDS = 2.5"),
        ("billing", "postgres_probe.py", "NullPool", "AsyncAdaptedQueuePool"),
        (
            "projector",
            "nats_probe.py",
            "await self._connection.flush",
            "await self._connection.close",
        ),
        ("notifications", "kafka_probe.py", "describe_cluster()", "list_topics()"),
        ("gateway", "mongo_probe.py", '"ping"', '"hello"'),
    ],
)
def test_sentinel_a_one_token_change_in_one_copy_of_each_module_is_named(
    health_tree: Path, service: str, module: str, needle: str, replacement: str
) -> None:
    copy = module_path(health_tree, service, module, HEALTH_DIR)
    text = copy.read_text(encoding="utf-8")
    assert needle in text
    copy.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
    assert health_violations(health_tree) == [
        f"{service}/{module}: differs from the canonical after the docstring"
    ]


def test_sentinel_the_gateways_health_checks_copy_is_named_when_it_drifts(
    health_tree: Path,
) -> None:
    copy = health_tree / "services/gateway/src" / SERVICES["gateway"] / GATEWAY_CHECKS
    text = copy.read_text(encoding="utf-8")
    assert "asyncio.timeout(self.timeout_seconds)" in text
    copy.write_text(text.replace("asyncio.timeout(self.timeout_seconds)", "asyncio.timeout(None)"))
    assert health_violations(health_tree) == [
        "gateway/health_checks.py: differs from the canonical after the docstring"
    ]
    copy.unlink()
    assert health_violations(health_tree) == ["gateway/health_checks.py: the copy is missing"]


def test_sentinel_a_deleted_health_copy_is_named_and_the_census_differs(
    health_tree: Path,
) -> None:
    module_path(health_tree, "notifications", "postgres_probe.py", HEALTH_DIR).unlink()
    assert health_violations(health_tree) == [
        "notifications/postgres_probe.py: the copy is missing"
    ]
    assert health_census(health_tree) != []


def test_sentinel_a_probe_planted_in_a_service_without_the_dependency_is_named(
    health_tree: Path,
) -> None:
    planted = module_path(health_tree, "fulfillment", "kafka_probe.py", HEALTH_DIR)
    shutil.copyfile(module_path(health_tree, "orders", "kafka_probe.py", HEALTH_DIR), planted)
    assert health_violations(health_tree) == [
        "fulfillment/kafka_probe.py: a copy in a service the table does not name"
    ]
    assert health_census(health_tree) != []
