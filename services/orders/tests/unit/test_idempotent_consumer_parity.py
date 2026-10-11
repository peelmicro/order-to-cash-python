"""OI12: every per-service copy of the idempotent consumer agrees with the canonical.

THE POPULATION IS DECLARED, NOT DISCOVERED (feature 24, PR48). `IDEMPOTENCY_MODE` classifies EVERY
service package under `services/` as `relational-copy`, `documented-variant` or `no-consumer`, and
`test_pr48_...` fails when a package on disk is missing from it, when a registered package does not
exist, when a mode disagrees with the files, and when the set of consuming packages differs from the
consumers `asyncapi.yaml`'s fact `receive` operations name. Until feature 24 the cases below
selected their population by a FILE the subject chooses whether to create (a copy by its
`processed_events` table and `idempotent_consumer.py`, a variant by that file alone), which is #7's
OI12 flaw exactly: a consumer that deduplicated nowhere, or named its file differently, was examined
by no case and every case passed. Cases 1 and 3 select by mode; case 4 examines the registry's
`documented-variant`s and now FAILS, where it used to skip, when one has no consumer file.

`design.md` 6.4's four cases, over the REAL population plus a temporary-tree sentinel for every case
that would otherwise be vacuous at n = 1 (#8 D4: three of its four cases passed with one service).
Pure text: files are read as text, no service is imported, no container. Python has no namespace
declaration, so the normalised region is the BANNER only (the module docstring and any comment
lines before it), #7's original single-region rule.

Case 2 scans the WHOLE canonical after the banner (no excluded region): `ConsumerName` lives in
`consumer_name.py` (amendment A1, #8's shape), so the canonical names no service. Its imports are
the standard library, `sqlalchemy`, and exactly one relative import,
`from .consumer_name import ConsumerName`.
"""

import ast
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
CANONICAL = "services/orders/src/otc_orders/infrastructure/messaging/idempotent_consumer.py"
SERVICE_TOKENS = ("orders", "fulfillment", "billing", "notifications", "projector", "otc_")
ALLOWED_IMPORT_ROOTS = frozenset(sys.stdlib_module_names) | {"sqlalchemy"}
PROCESSED_EVENTS_TABLE = '__tablename__ = "processed_events"'

RELATIONAL_COPY = "relational-copy"
DOCUMENTED_VARIANT = "documented-variant"
NO_CONSUMER = "no-consumer"
# EVERY package under `services/*/src/otc_*`, classified. A new service fails `test_pr48_...` until
# it is added here, with a mode the files and the spec then have to agree with.
IDEMPOTENCY_MODE: dict[str, str] = {
    "orders": RELATIONAL_COPY,
    "notifications": RELATIONAL_COPY,
    "projector": DOCUMENTED_VARIANT,
    "fulfillment": NO_CONSUMER,
    "billing": NO_CONSUMER,
    "gateway": NO_CONSUMER,
    "seed": NO_CONSUMER,
}
# `asyncapi.yaml`'s `Consumer name — <name>.` (the fact `receive` operations) -> the package.
SPEC_CONSUMER_PACKAGE = {
    "orders.saga": "orders",
    "projector": "projector",
    "notifications": "notifications",
}
FACT_CHANNELS = ("ordersFacts", "fulfillmentFacts", "billingFacts")


# ----------------------------------------------------------------------------------- instruments


def split_banner(text: str) -> tuple[str, str]:
    """`(banner, body)`: the module docstring plus any comment lines before it, then the rest."""
    tree = ast.parse(text)
    first = tree.body[0] if tree.body else None
    if not (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return "", text
    lines = text.splitlines(keepends=True)
    assert first.end_lineno is not None
    return "".join(lines[: first.end_lineno]), "".join(lines[first.end_lineno :])


def service_roots(root: Path) -> list[Path]:
    return sorted(p for p in (root / "services").glob("*/src/otc_*") if p.is_dir())


def has_relational_ledger(package: Path) -> bool:
    models = package / "infrastructure" / "persistence" / "models.py"
    return models.is_file() and PROCESSED_EVENTS_TABLE in models.read_text(encoding="utf-8")


def consumer_file(package: Path) -> Path:
    return package / "infrastructure" / "messaging" / "idempotent_consumer.py"


def short_name(package: Path) -> str:
    return package.name.removeprefix("otc_")


def copies(root: Path, modes: Mapping[str, str] = IDEMPOTENCY_MODE) -> list[Path]:
    """The consumer file of every package REGISTERED as a `relational-copy`: selected by mode, never
    by the existence of a file (the mode check reports a registered copy whose file is missing)."""
    return [
        consumer_file(p)
        for p in service_roots(root)
        if modes.get(short_name(p)) == RELATIONAL_COPY and consumer_file(p).is_file()
    ]


def divergent_copies(
    root: Path, canonical: Path, modes: Mapping[str, str] = IDEMPOTENCY_MODE
) -> list[str]:
    reference = split_banner(canonical.read_text(encoding="utf-8"))[1]
    found = []
    for copy in copies(root, modes):
        if split_banner(copy.read_text(encoding="utf-8"))[1] != reference:
            found.append(f"{copy.relative_to(root)} diverges from the canonical outside the banner")
    return found


DYNAMIC_IMPORTS = frozenset({"__import__", "import_module"})  # as tests/architecture's money guard
ALLOWED_RELATIVE_IMPORT = ("consumer_name", ("ConsumerName",))


def adoptability_problems(text: str) -> list[str]:
    """Why the canonical could not be adopted verbatim by another service (empty = adoptable)."""
    body = split_banner(text)[1]
    problems = []
    scanned = body.lower()
    for token in SERVICE_TOKENS:
        if token in scanned:
            problems.append(f"names {token!r} outside the banner")
    relative = 0
    for node in ast.walk(ast.parse(body)):
        if isinstance(node, ast.Name | ast.Attribute):
            referenced = node.id if isinstance(node, ast.Name) else node.attr
            if referenced in DYNAMIC_IMPORTS:
                problems.append(f"references {referenced!r}: a dynamic import hides its module")
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
            if any(alias.name.split(".")[0] == "importlib" for alias in node.names):
                problems.append("imports 'importlib': a dynamic import hides its module")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module]
            if node.module.split(".")[0] == "importlib":
                problems.append("imports 'importlib': a dynamic import hides its module")
        elif isinstance(node, ast.ImportFrom):
            relative += 1
            shape = (node.module, tuple(alias.name for alias in node.names))
            if node.level != 1 or shape != ALLOWED_RELATIVE_IMPORT:
                problems.append(f"relative import {'.' * node.level}{node.module} is not allowed")
        problems.extend(
            f"imports {module!r}, which is neither the standard library nor sqlalchemy"
            for module in modules
            if module.split(".")[0] not in ALLOWED_IMPORT_ROOTS
        )
    if relative != 1:
        problems.append(f"expected exactly one relative import (consumer_name), found {relative}")
    return problems


def consumers_without_a_copy(
    root: Path, modes: Mapping[str, str] = IDEMPOTENCY_MODE
) -> tuple[list[str], list[str]]:
    """`(examined, missing)`: the write models (a relational ledger, and a mode that is not
    `documented-variant`, which case 4 examines instead) and, of them, those that consume facts
    with no consumer file."""
    examined, missing = [], []
    for package in service_roots(root):
        if modes.get(short_name(package)) == DOCUMENTED_VARIANT or not has_relational_ledger(
            package
        ):
            continue
        examined.append(package.name)
        consumes = any(
            "AIOKafkaConsumer" in source.read_text(encoding="utf-8")
            for source in package.rglob("*.py")
        )
        if consumes and not consumer_file(package).is_file():
            missing.append(package.name)
    return examined, missing


CONFORMANCE_LINE = "Behavioural conformance:"


def variant_problems(
    root: Path, canonical_path: str, modes: Mapping[str, str] = IDEMPOTENCY_MODE
) -> tuple[list[str], list[str]]:
    """`(examined, problems)` over the REGISTRY's `documented-variant`s, never over the files found.

    A variant is never compared with the canonical, but it must (1) have its consumer file (the
    opt-out OI12 allowed: a variant that deletes or renames the file is no longer examined, so the
    file's absence now FAILS), (2) cite the canonical path in its banner, (3) carry a line beginning
    `Divergence:` and (4) carry a `Behavioural conformance: <repo-relative path>` line naming a
    file that exists (relative to `root`).
    """
    examined, problems = [], []
    for package in service_roots(root):
        if modes.get(short_name(package)) != DOCUMENTED_VARIANT:
            continue
        examined.append(package.name)
        file = consumer_file(package)
        if not file.is_file():
            problems.append(f"{package.name}: no consumer file at {file.relative_to(root)}")
            continue
        banner = split_banner(file.read_text(encoding="utf-8"))[0]
        if canonical_path not in banner:
            problems.append(f"{package.name}: the banner does not cite {canonical_path}")
        lines = banner.splitlines()
        if not any(line.startswith("Divergence:") for line in lines):
            problems.append(f"{package.name}: the banner has no line beginning 'Divergence:'")
        conformance = [line for line in lines if line.startswith(CONFORMANCE_LINE)]
        if not conformance:
            problems.append(f"{package.name}: the banner has no '{CONFORMANCE_LINE}' line")
        for line in conformance:
            named = line.removeprefix(CONFORMANCE_LINE).strip()
            if not named or not (root / named).is_file():
                problems.append(
                    f"{package.name}: the '{CONFORMANCE_LINE}' line names {named!r}, "
                    "which is not an existing file"
                )
    return examined, problems


def spec_consumers(spec_text: str) -> set[str]:
    """The consumer names `asyncapi.yaml`'s `receive` operations on the three fact channels carry
    in their `summary: Consumer name — <name>.`, read as text and parsed as YAML."""
    operations = yaml.safe_load(spec_text)["operations"]
    names = set()
    for operation in operations.values():
        channel = operation["channel"]["$ref"].rsplit("/", 1)[1]
        if operation["action"] == "receive" and channel in FACT_CHANNELS:
            summary = operation["summary"]
            assert summary.startswith("Consumer name \u2014 "), summary
            names.add(summary.removeprefix("Consumer name \u2014 ").rstrip("."))
    return names


def registry_problems(root: Path, modes: Mapping[str, str] = IDEMPOTENCY_MODE) -> list[str]:
    """P1 / P2: the registry's keys are exactly the packages on disk."""
    on_disk = {short_name(p) for p in service_roots(root)}
    problems = [
        f"{name}: a service package on disk is missing from IDEMPOTENCY_MODE"
        for name in sorted(on_disk - set(modes))
    ]
    problems += [
        f"{name}: registered in IDEMPOTENCY_MODE but there is no such package"
        for name in sorted(set(modes) - on_disk)
    ]
    return problems


def mode_problems(root: Path, modes: Mapping[str, str] = IDEMPOTENCY_MODE) -> list[str]:
    """P3 / P4 (the mode against the files): the half of the registry a subject could lie about."""
    problems = []
    for package in service_roots(root):
        name, mode = short_name(package), modes.get(short_name(package))
        if mode is None:
            continue  # reported by `registry_problems`
        if mode == RELATIONAL_COPY:
            if not has_relational_ledger(package):
                problems.append(f"{name}: registered relational-copy but has no processed_events")
            if not consumer_file(package).is_file():
                problems.append(f"{name}: registered relational-copy but has no consumer file")
        elif mode == DOCUMENTED_VARIANT:
            if has_relational_ledger(package):
                problems.append(f"{name}: registered documented-variant but has a ledger table")
            if not consumer_file(package).is_file():
                problems.append(f"{name}: registered documented-variant but has no consumer file")
        elif mode == NO_CONSUMER:
            for source in package.rglob("*.py"):
                if "AIOKafkaConsumer" in source.read_text(encoding="utf-8"):
                    problems.append(
                        f"{name}: registered no-consumer but {source.name} references "
                        "AIOKafkaConsumer"
                    )
        else:
            problems.append(f"{name}: unknown mode {mode!r}")
    return problems


def spec_problems(spec_text: str, modes: Mapping[str, str] = IDEMPOTENCY_MODE) -> list[str]:
    """P6: the consuming packages are exactly the consumers the spec names."""
    named = {SPEC_CONSUMER_PACKAGE[name] for name in spec_consumers(spec_text)}
    registered = {name for name, mode in modes.items() if mode != NO_CONSUMER}
    problems = [
        f"{name}: the spec names it a consumer but it is registered no-consumer"
        for name in sorted(named - registered)
    ]
    problems += [
        f"{name}: registered as a consumer but the spec names no such consumer"
        for name in sorted(registered - named)
    ]
    return problems


# -------------------------------------------------------------------------- a temporary tree


def build_tree(root: Path, services: dict[str, dict[str, str]]) -> None:
    """`services`: name -> {relative path below `src/otc_<name>`: content}."""
    for name, files in services.items():
        package = root / "services" / name / "src" / f"otc_{name}"
        for relative, content in files.items():
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")


LEDGER = f"class ProcessedEvent:\n    {PROCESSED_EVENTS_TABLE}\n"
TWO_COPIES = {"orders": RELATIONAL_COPY, "billing": RELATIONAL_COPY}
SAMPLE = '"""Banner."""\n\nimport enum\n\nVALUE = 1\n'


# --------------------------------------------------------------- case 1: copies equal the canonical


def test_case_1_every_write_models_copy_is_byte_identical_to_the_canonical_after_the_banner() -> (
    None
):
    found = copies(REPO_ROOT)
    canonical = REPO_ROOT / CANONICAL
    assert canonical in found, (
        "the canonical itself is a copy-candidate: it has a ledger and a file"
    )
    assert divergent_copies(REPO_ROOT, canonical) == []
    # Feature 23 made the population two: Notifications is the first genuine second copy. The set is
    # a literal so that a vanished copy (a renamed file, a lost ledger) fails here by name instead
    # of leaving the comparison to run against the canonical alone (#8's guard passed at n = 1).
    assert {p.parents[2].name for p in found} == {"otc_orders", "otc_notifications"}, found
    print(f"case 1 compared {len(found)} copies")


def test_case_1_sentinel_a_copy_that_differs_by_one_character_is_reported(tmp_path: Path) -> None:
    build_tree(
        tmp_path,
        {
            "orders": {
                "infrastructure/persistence/models.py": LEDGER,
                "infrastructure/messaging/idempotent_consumer.py": SAMPLE,
            },
            "billing": {
                "infrastructure/persistence/models.py": LEDGER,
                "infrastructure/messaging/idempotent_consumer.py": SAMPLE.replace("= 1", "= 2"),
            },
        },
    )
    canonical = tmp_path / CANONICAL
    reported = divergent_copies(tmp_path, canonical, TWO_COPIES)
    assert len(reported) == 1
    assert "otc_billing" in reported[0]


def test_case_1_sentinel_a_differing_banner_alone_is_not_a_divergence(tmp_path: Path) -> None:
    build_tree(
        tmp_path,
        {
            "orders": {
                "infrastructure/persistence/models.py": LEDGER,
                "infrastructure/messaging/idempotent_consumer.py": SAMPLE,
            },
            "billing": {
                "infrastructure/persistence/models.py": LEDGER,
                "infrastructure/messaging/idempotent_consumer.py": SAMPLE.replace(
                    "Banner.", "A different banner."
                ),
            },
        },
    )
    assert divergent_copies(tmp_path, tmp_path / CANONICAL, TWO_COPIES) == []


# ------------------------------------------------------------- case 2: the canonical is adoptable


def test_case_2_the_canonical_is_adoptable_verbatim_naming_no_service() -> None:
    text = (REPO_ROOT / CANONICAL).read_text(encoding="utf-8")
    assert adoptability_problems(text) == []


@pytest.mark.parametrize(
    "intruder",
    ["from otc_orders.domain import x", "BillingDb = 1", "FULFILLMENT_X = 1", "import redis"],
)
def test_case_2_sentinel_a_service_name_or_a_foreign_import_in_the_body_is_reported(
    intruder: str,
) -> None:
    text = (REPO_ROOT / CANONICAL).read_text(encoding="utf-8")
    assert adoptability_problems(text + f"\n{intruder}\n"), intruder


def test_case_2_sentinel_a_dynamic_import_in_the_body_is_reported() -> None:
    """Review F4 (arm H2): `importlib.import_module("redis")` names no module the scan can see."""
    text = (REPO_ROOT / CANONICAL).read_text(encoding="utf-8")
    dynamic = '\nimport importlib\n_DRIVER = importlib.import_module("redis")\n'
    problems = adoptability_problems(text + dynamic)
    assert any("importlib" in p for p in problems), problems
    assert any("import_module" in p for p in problems), problems
    assert adoptability_problems(text + '\n_X = __import__("redis")\n')


def test_case_2_sentinel_the_vocabulary_is_not_exempt_anywhere() -> None:
    text = (REPO_ROOT / CANONICAL).read_text(encoding="utf-8")
    assert adoptability_problems(text) == []
    enum_back = '\nclass ConsumerName(enum.Enum):\n    ORDERS_SAGA = "orders.saga"\n'
    assert adoptability_problems(text + enum_back), "the enum inside the canonical counts"


@pytest.mark.parametrize(
    "extra", ["from .other import X", "from .consumer_name import ConsumerName", "from . import y"]
)
def test_case_2_sentinel_any_other_or_a_second_relative_import_is_reported(extra: str) -> None:
    text = (REPO_ROOT / CANONICAL).read_text(encoding="utf-8")
    assert adoptability_problems(text + f"\n{extra}\n"), extra


def test_case_2_sentinel_a_missing_relative_import_is_reported() -> None:
    text = (REPO_ROOT / CANONICAL).read_text(encoding="utf-8")
    assert adoptability_problems(text.replace("from .consumer_name import ConsumerName\n", ""))


# ------------------------------------------------------- case 3: every consumer carries a copy


def consuming_write_models(root: Path) -> set[str]:
    """The write models (services with a relational ledger) that reference `AIOKafkaConsumer`."""
    return {
        package.name
        for package in service_roots(root)
        if has_relational_ledger(package)
        and any(
            "AIOKafkaConsumer" in source.read_text(encoding="utf-8")
            for source in package.rglob("*.py")
        )
    }


def test_case_3_every_write_model_that_consumes_facts_carries_a_copy() -> None:
    examined, missing = consumers_without_a_copy(REPO_ROOT)
    assert len(examined) >= 3, f"the computation must range over the real population: {examined}"
    assert "otc_orders" in examined
    # Feature 16 built the first fact consumer: the saga's `KafkaFactSubscriber` in Orders; feature
    # 23 the second: Notifications' fact subscriber. The computed set is a literal, so a further
    # consumer is a deliberate edit here. (The Projector has no relational ledger: not a member.)
    assert consuming_write_models(REPO_ROOT) == {"otc_orders", "otc_notifications"}
    assert {"otc_orders", "otc_notifications"} <= set(examined)
    assert missing == [], f"a consuming write model has no idempotent-consumer copy: {missing}"


def test_case_3_sentinel_the_real_orders_tree_without_its_copy_is_reported(tmp_path: Path) -> None:
    import shutil

    package = tmp_path / "services" / "orders" / "src" / "otc_orders"
    shutil.copytree(
        REPO_ROOT / "services" / "orders" / "src" / "otc_orders",
        package,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    assert consuming_write_models(tmp_path) == {"otc_orders"}
    assert consumers_without_a_copy(tmp_path)[1] == [], "the unmodified copy of the tree is fine"

    consumer_file(package).rename(consumer_file(package).with_name("renamed.py"))

    assert consumers_without_a_copy(tmp_path)[1] == ["otc_orders"]


def test_case_3_sentinel_a_consumer_of_facts_without_a_copy_is_reported(tmp_path: Path) -> None:
    build_tree(
        tmp_path,
        {
            "billing": {
                "infrastructure/persistence/models.py": LEDGER,
                "infrastructure/messaging/consumer.py": "from aiokafka import AIOKafkaConsumer\n",
            },
            "fulfillment": {"infrastructure/persistence/models.py": LEDGER},
        },
    )
    examined, missing = consumers_without_a_copy(tmp_path)
    assert examined == ["otc_billing", "otc_fulfillment"]
    assert missing == ["otc_billing"]


# ----------------------------------------------- PR48: the population is declared, not discovered

SPEC_TEXT = (REPO_ROOT / "specs" / "shared" / "asyncapi.yaml").read_text(encoding="utf-8")


def test_pr48_every_service_package_is_registered_and_its_mode_matches_the_files_and_the_spec() -> (
    None
):
    on_disk = {short_name(p) for p in service_roots(REPO_ROOT)}
    assert (
        on_disk
        == set(IDEMPOTENCY_MODE)
        == {
            "gateway",
            "orders",
            "fulfillment",
            "billing",
            "notifications",
            "projector",
            "seed",
        }
    )
    assert registry_problems(REPO_ROOT) == [], "the registry and the packages on disk disagree"
    assert mode_problems(REPO_ROOT) == [], "a registered mode disagrees with the files"
    assert spec_problems(SPEC_TEXT) == [], "the registry disagrees with asyncapi.yaml's consumers"
    assert spec_consumers(SPEC_TEXT) == set(SPEC_CONSUMER_PACKAGE)
    print(f"pr48 registry classified {len(IDEMPOTENCY_MODE)} packages")


def test_pr48_sentinel_the_control_tree_passes(tmp_path: Path) -> None:
    modes = {"orders": RELATIONAL_COPY, "projector": DOCUMENTED_VARIANT, "seed": NO_CONSUMER}
    build_control_tree(tmp_path)
    assert registry_problems(tmp_path, modes) == []
    assert mode_problems(tmp_path, modes) == []
    examined, problems = variant_problems(tmp_path, CANONICAL, modes)
    assert (examined, problems) == (["otc_projector"], [])


def build_control_tree(root: Path) -> None:
    conformance = "services/projector/tests/integration/test_conformance.py"
    (root / conformance).parent.mkdir(parents=True, exist_ok=True)
    (root / conformance).write_text("", encoding="utf-8")
    banner = (
        f'"""Variant of {CANONICAL}.\n\nDivergence: a document store shares no transaction.\n\n'
        f'{CONFORMANCE_LINE} {conformance}\n"""\n'
    )
    build_tree(
        root,
        {
            "orders": {
                "infrastructure/persistence/models.py": LEDGER,
                "infrastructure/messaging/idempotent_consumer.py": SAMPLE,
            },
            "projector": {"infrastructure/messaging/idempotent_consumer.py": banner},
            "seed": {"domain/x.py": "VALUE = 1\n"},
        },
    )


def test_pr48_p1_sentinel_a_package_on_disk_missing_from_the_registry_is_reported(
    tmp_path: Path,
) -> None:
    build_tree(tmp_path, {"ledgerless": {"infrastructure/x.py": "VALUE = 1\n"}})
    assert registry_problems(tmp_path, IDEMPOTENCY_MODE) == [
        "ledgerless: a service package on disk is missing from IDEMPOTENCY_MODE",
        *[
            f"{name}: registered in IDEMPOTENCY_MODE but there is no such package"
            for name in sorted(IDEMPOTENCY_MODE)
        ],
    ]


def test_pr48_p2_sentinel_a_registry_entry_with_no_package_is_reported(tmp_path: Path) -> None:
    build_control_tree(tmp_path)
    modes = {
        "orders": RELATIONAL_COPY,
        "projector": DOCUMENTED_VARIANT,
        "seed": NO_CONSUMER,
        "ghost": NO_CONSUMER,
    }
    assert registry_problems(tmp_path, modes) == [
        "ghost: registered in IDEMPOTENCY_MODE but there is no such package"
    ]


def test_pr48_p3_sentinel_a_no_consumer_that_references_aiokafkaconsumer_is_reported(
    tmp_path: Path,
) -> None:
    build_tree(
        tmp_path, {"seed": {"infrastructure/x.py": "from aiokafka import AIOKafkaConsumer\n"}}
    )
    assert mode_problems(tmp_path, {"seed": NO_CONSUMER}) == [
        "seed: registered no-consumer but x.py references AIOKafkaConsumer"
    ]


def test_pr48_p4_sentinel_a_variant_whose_consumer_file_is_renamed_now_fails(
    tmp_path: Path,
) -> None:
    """The OI12 opt-out: a variant that renames its file used to be examined by no case."""
    build_control_tree(tmp_path)
    modes = {"projector": DOCUMENTED_VARIANT}
    package = tmp_path / "services" / "projector" / "src" / "otc_projector"
    consumer_file(package).rename(consumer_file(package).with_name("renamed.py"))
    assert mode_problems(tmp_path, modes) == [
        "projector: registered documented-variant but has no consumer file"
    ]
    examined, problems = variant_problems(tmp_path, CANONICAL, modes)
    assert examined == ["otc_projector"]
    assert len(problems) == 1
    assert problems[0].startswith("otc_projector: no consumer file at")


def test_pr48_p5_sentinel_a_conformance_line_naming_a_missing_file_or_absent_is_reported(
    tmp_path: Path,
) -> None:
    build_control_tree(tmp_path)
    modes = {"projector": DOCUMENTED_VARIANT}
    package = tmp_path / "services" / "projector" / "src" / "otc_projector"
    file = consumer_file(package)
    original = file.read_text(encoding="utf-8")

    file.write_text(
        original.replace("test_conformance.py", "test_no_such_file.py"), encoding="utf-8"
    )
    _, problems = variant_problems(tmp_path, CANONICAL, modes)
    assert len(problems) == 1
    assert "names 'services/projector/tests/integration/test_no_such_file.py'" in problems[0]
    assert "which is not an existing file" in problems[0]

    file.write_text(
        "\n".join(line for line in original.splitlines() if not line.startswith(CONFORMANCE_LINE))
        + "\n",
        encoding="utf-8",
    )
    _, problems = variant_problems(tmp_path, CANONICAL, modes)
    assert problems == [f"otc_projector: the banner has no '{CONFORMANCE_LINE}' line"]


def test_pr48_p6_sentinel_a_registry_marking_the_projector_no_consumer_is_reported() -> None:
    modes = {**IDEMPOTENCY_MODE, "projector": NO_CONSUMER}
    assert spec_problems(SPEC_TEXT, modes) == [
        "projector: the spec names it a consumer but it is registered no-consumer"
    ]
    # and a consumer the spec does not name
    modes = {**IDEMPOTENCY_MODE, "billing": RELATIONAL_COPY}
    assert spec_problems(SPEC_TEXT, modes) == [
        "billing: registered as a consumer but the spec names no such consumer"
    ]


# ------------------------------------------------------------ case 4: variants name the canonical


def test_case_4_a_variant_carries_a_divergence_banner_naming_the_canonical_and_an_existing_conformance_file() -> (  # noqa: E501
    None
):
    examined, problems = variant_problems(REPO_ROOT, CANONICAL)
    assert problems == []
    assert examined == ["otc_projector"], examined
    print(f"case 4 examined {len(examined)} variant(s)")


def test_case_4_sentinel_a_variant_without_a_divergence_line_is_reported(tmp_path: Path) -> None:
    conformance = "services/projector/tests/integration/test_conformance.py"
    (tmp_path / conformance).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / conformance).write_text("", encoding="utf-8")
    named = (
        f'"""Variant of {CANONICAL}.\n\nDivergence: a document store shares no transaction.\n'
        f'{CONFORMANCE_LINE} {conformance}\n"""\n'
    )
    unnamed = f'"""Variant of {CANONICAL}.\n{CONFORMANCE_LINE} {conformance}\n"""\n'
    build_tree(
        tmp_path,
        {
            "projector": {"infrastructure/messaging/idempotent_consumer.py": unnamed},
            "notifications": {"infrastructure/messaging/idempotent_consumer.py": named},
        },
    )
    modes = {"projector": DOCUMENTED_VARIANT, "notifications": DOCUMENTED_VARIANT}
    examined, problems = variant_problems(tmp_path, CANONICAL, modes)
    assert examined == ["otc_notifications", "otc_projector"]
    assert problems == ["otc_projector: the banner has no line beginning 'Divergence:'"]
