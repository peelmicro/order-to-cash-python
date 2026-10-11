"""The committed instrument for the Notifications templates' payload-interpolation-site population.

    uv run python scripts/notification-template-sweep.py --enumerate
    uv run python scripts/notification-template-sweep.py --probe 7
    uv run python scripts/notification-template-sweep.py --all
    uv run python scripts/notification-template-sweep.py --sentinels

Why it exists. In #8 the population "every place a payload field's value reaches an outgoing
email" was counted by hand three times, by three parties, and produced 14, 89 and 95 (the 95th a
nested list element), after 45 of 68 template mutations had survived (ids 58, 59). The maintainer's
ruling there made a committed, re-runnable instrument required: a population that changes every
time somebody counts it by hand is what an instrument settles, and it counts the same way twice.

What it does.
* ENUMERATES (a search over the AST, never a cached list) every attribute read of the event, its
  payload or a list element in `application/templates/*.py` except `format.py`: `event.<field>`,
  `payload.<field>`, and the comprehension variables `line` / `step` (resolved to the element model
  of the list they iterate). Names, comments, docstrings and strings are not reads (they are not
  `ast.Attribute` nodes), and a read inside a nested list element, a comprehension or a condition
  IS one. Each site is classified by the field's declared type (string, instant, money/int, id,
  enum, collection) taken from the generated pydantic model.
* MUTATES one site at a time, in a COPY of the package in a temporary directory (the working tree
  is never touched, so there is nothing to restore; the copy is what `PYTHONPATH` makes the tests
  import, which the CAUGHT sentinel proves), by two families: M1 a type-correct constant or the
  envelope's instant/another id (the "plausible wrong value"), M2 a sibling field of the same kind
  of the same model (where one exists). Then runs the template tests.
* REPORTS CAUGHT (a test failed; the first failing test is named), SURVIVED (all green), or
  NOT-APPLIED (the expected old text is not at the recorded position: the source moved, and no
  test was run).

Sentinels (`--sentinels`; a sweep needs cases that must fail to detect): an unmutated copy must be
green (the baseline every verdict depends on); a mutation whose target does not exist must report
NOT-APPLIED; an edit confined to a comment must report SURVIVED; and one known mutation of a real
site (the subject of `order_placed`) must report CAUGHT, which also proves the tests import the
mutated copy.
"""

import argparse
import ast
import concurrent.futures
import dataclasses
import enum
import importlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import typing
from datetime import datetime
from pathlib import Path
from uuid import UUID

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "services" / "notifications" / "src" / "otc_notifications"
TEMPLATES = PACKAGE / "application" / "templates"
TESTS = [
    "services/notifications/tests/unit/templates",
    "services/notifications/tests/unit/test_notification_facts_consumer.py",
    # the population test reads the SOURCE this sweep mutates: it is not a template test
    "--ignore=services/notifications/tests/unit/templates/test_template_sweep_population.py",
]
EXCLUDED_MODULES = {"format.py", "__init__.py"}


class Verdict(enum.Enum):
    CAUGHT = "CAUGHT"
    SURVIVED = "SURVIVED"
    NOT_APPLIED = "NOT-APPLIED"


@dataclasses.dataclass(frozen=True)
class Site:
    number: int
    path: Path
    line: int
    col: int
    end_col: int
    text: str  # the expression, e.g. `payload.order_reference`
    owner: str  # the model class name the attribute belongs to
    field: str
    kind: str  # string | instant | int | id | enum | collection | other
    siblings: tuple[str, ...]  # same-kind fields of the owner, other than `field`

    @property
    def where(self) -> str:
        return f"{self.path.relative_to(PACKAGE).as_posix()}:{self.line}"


def _unwrap(annotation: object) -> object:
    """`Annotated[X, ...]` and `X | None` down to `X`."""
    while True:
        origin = typing.get_origin(annotation)
        if origin is typing.Annotated:
            annotation = typing.get_args(annotation)[0]
        elif origin in (typing.Union, getattr(__import__("types"), "UnionType", None)):
            args = [a for a in typing.get_args(annotation) if a is not type(None)]
            if len(args) != 1:
                return annotation
            annotation = args[0]
        else:
            return annotation


def _kind(annotation: object) -> str:
    inner = _unwrap(annotation)
    if typing.get_origin(inner) is list:
        return "collection"
    if inner is str:
        return "string"
    if inner is int:
        return "int"
    if inner is datetime or getattr(inner, "__name__", "") == "AwareDatetime":
        return "instant"
    if inner is UUID:
        return "id"
    if isinstance(inner, type) and issubclass(inner, enum.Enum):
        return "enum"
    return "other"


def _models() -> object:
    importlib.invalidate_caches()
    return importlib.import_module("otc_contracts.generated.asyncapi")


def _element_type(annotation: object) -> object:
    inner = _unwrap(annotation)
    return _unwrap(typing.get_args(inner)[0])


def _fields(model: type) -> dict[str, object]:
    return {name: field.annotation for name, field in model.model_fields.items()}  # type: ignore[attr-defined]


def enumerate_sites() -> list[Site]:
    asyncapi = _models()
    sites: list[Site] = []
    for path in sorted(TEMPLATES.glob("*.py")):
        if path.name in EXCLUDED_MODULES:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        lines = source.splitlines()
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        if len(functions) != 1:
            raise SystemExit(f"{path.name}: one render function per template module")
        function = functions[0]
        event_class = getattr(asyncapi, ast.unparse(function.args.args[0].annotation))  # type: ignore[arg-type]
        event_fields = _fields(event_class)
        payload_class = _unwrap(event_fields["payload"])
        payload_fields = _fields(payload_class)  # type: ignore[arg-type]
        element_models: dict[str, type] = {}
        for node in ast.walk(function):
            if isinstance(node, ast.comprehension) and isinstance(node.target, ast.Name):
                iterated = node.iter
                if not (
                    isinstance(iterated, ast.Attribute) and ast.unparse(iterated.value) == "payload"
                ):
                    raise SystemExit(f"{path.name}:{node.iter.lineno}: unsupported iteration")
                element_models[node.target.id] = _element_type(payload_fields[iterated.attr])  # type: ignore[assignment]
        owners: dict[str, tuple[str, dict[str, object]]] = {
            "event": (event_class.__name__, event_fields),
            "payload": (payload_class.__name__, payload_fields),  # type: ignore[attr-defined]
        }
        for variable, model in element_models.items():
            owners[variable] = (model.__name__, _fields(model))
        reads = [
            n
            for n in ast.walk(function)
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id in owners
            and n.attr != "payload"
        ]
        for node in sorted(reads, key=lambda n: (n.lineno, n.col_offset)):
            if not isinstance(node.value, ast.Name):
                raise SystemExit("unreachable: reads are filtered to Name roots")
            owner_name, fields = owners[node.value.id]
            kind = _kind(fields[node.attr])
            siblings = tuple(
                name
                for name, annotation in fields.items()
                if name != node.attr and name != "payload" and _kind(annotation) == kind
            )
            if node.end_col_offset is None or node.lineno != node.end_lineno:
                raise SystemExit(f"{path.name}:{node.lineno}: a read spanning lines")
            text = lines[node.lineno - 1][node.col_offset : node.end_col_offset]
            if text != f"{node.value.id}.{node.attr}":
                raise SystemExit(f"{path.name}:{node.lineno}: expected a plain read, got {text!r}")
            sites.append(
                Site(
                    len(sites) + 1,
                    path,
                    node.lineno,
                    node.col_offset,
                    node.end_col_offset,
                    text,
                    owner_name,
                    node.attr,
                    kind,
                    siblings,
                )
            )
    return sites


def constant_for(site: Site) -> str:
    """M1: a type-correct wrong value for the site."""
    return {
        "string": '"MUTANT"',
        "int": "-7",
        "instant": "event.occurred_at",
        "id": "event.aggregate_id",
        "enum": '"MUTANT"',
        "collection": "[]",
    }.get(site.kind, '"MUTANT"')


def mutations_for(site: Site) -> list[tuple[str, str]]:
    found = [("M1 constant", constant_for(site))]
    if site.siblings:
        root = site.text.split(".")[0]
        found.append((f"M2 sibling {site.siblings[0]}", f"{root}.{site.siblings[0]}"))
    return found


def apply_mutation(copy: Path, site: Site, expected: str, replacement: str) -> bool:
    target = copy / site.path.relative_to(PACKAGE)
    lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    line = lines[site.line - 1]
    if line[site.col : site.end_col] != expected:
        return False
    lines[site.line - 1] = line[: site.col] + replacement + line[site.end_col :]
    target.write_text("".join(lines), encoding="utf-8")
    return True


EXTRA_IGNORES: list[str] = []


def run_tests(copy_root: Path) -> tuple[bool, str]:
    environment = {**os.environ, "PYTHONPATH": str(copy_root), "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run(  # noqa: S603 - the interpreter running this script, fixed arguments
        [
            sys.executable,
            "-m",
            "pytest",
            *TESTS,
            "-x",
            "-q",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=--import-mode=importlib",
            "--no-header",
            "-rf",
        ],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    failing = re.search(r"^FAILED (\S+)", done.stdout, re.MULTILINE)
    return done.returncode == 0, (failing.group(1) if failing else done.stdout[-300:])


def probe(
    site: Site, label: str, replacement: str, *, expected: str | None = None
) -> tuple[Verdict, str]:
    with tempfile.TemporaryDirectory(prefix="otc-sweep-") as temp:
        root = Path(temp)
        shutil.copytree(
            PACKAGE, root / "otc_notifications", ignore=shutil.ignore_patterns("__pycache__")
        )
        if not apply_mutation(root / "otc_notifications", site, expected or site.text, replacement):
            return Verdict.NOT_APPLIED, f"{label}: {expected or site.text!r} not at {site.where}"
        green, detail = run_tests(root)
        return (Verdict.SURVIVED, label) if green else (Verdict.CAUGHT, f"{label} -> {detail}")


def baseline_is_green() -> bool:
    with tempfile.TemporaryDirectory(prefix="otc-sweep-") as temp:
        root = Path(temp)
        shutil.copytree(
            PACKAGE, root / "otc_notifications", ignore=shutil.ignore_patterns("__pycache__")
        )
        return run_tests(root)[0]


def print_enumeration(sites: list[Site]) -> None:
    for site in sites:
        owner = f"{site.owner}.{site.field}"
        print(f"{site.number:3d}  {site.where:<42s} {site.text:<38s} {owner}  [{site.kind}]")
    per_kind: dict[str, int] = {}
    per_file: dict[str, int] = {}
    for site in sites:
        per_kind[site.kind] = per_kind.get(site.kind, 0) + 1
        per_file[site.path.name] = per_file.get(site.path.name, 0) + 1
    print(f"\n{len(sites)} sites in {len(per_file)} templates")
    print("per kind: " + ", ".join(f"{k}={v}" for k, v in sorted(per_kind.items())))
    print("per file: " + ", ".join(f"{k}={v}" for k, v in sorted(per_file.items())))


def sentinels(sites: list[Site]) -> int:
    failures = 0

    def check(name: str, ok: bool, detail: str) -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {detail}")

    check("baseline", baseline_is_green(), "the unmutated copy passes the template tests")
    first = sites[0]
    verdict, detail = probe(first, "wrong-target", '"x"', expected="payload.does_not_exist")
    check("NOT-APPLIED", verdict is Verdict.NOT_APPLIED, detail)

    placed = next(
        s for s in sites if s.path.name == "order_placed.py" and s.field == "order_reference"
    )
    comment_site = dataclasses.replace(
        placed, line=1, col=0, end_col=len("# ruff: noqa: E501"), text="# ruff: noqa: E501"
    )
    verdict, detail = probe(comment_site, "comment-only", "# ruff: noqa: E501 # edited")
    check("SURVIVED", verdict is Verdict.SURVIVED, detail)
    verdict, detail = probe(placed, "known-kill", '"MUTANT"')
    check("CAUGHT", verdict is Verdict.CAUGHT, detail)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--enumerate", action="store_true")
    group.add_argument("--probe", type=int, metavar="SITE")
    group.add_argument("--all", action="store_true")
    group.add_argument("--sentinels", action="store_true")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument(
        "--also-ignore",
        action="append",
        default=[],
        metavar="TESTFILE",
        help="run the sweep without this test file (to see which layer kills what)",
    )
    args = parser.parse_args()
    EXTRA_IGNORES.extend(f"--ignore={path}" for path in args.also_ignore)
    sites = enumerate_sites()
    if args.enumerate:
        print_enumeration(sites)
        return 0
    if args.sentinels:
        return 1 if sentinels(sites) else 0
    if not baseline_is_green():
        print("ABORT: the unmutated copy is not green; no verdict would mean anything")
        return 2
    selected = [sites[args.probe - 1]] if args.probe else sites
    jobs = [(s, label, replacement) for s in selected for label, replacement in mutations_for(s)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda j: (j[0], j[1], *probe(j[0], j[1], j[2])), jobs))
    survivors = 0
    for site, _label, verdict, detail in results:
        print(f"{site.number:3d} {verdict.value:<11s} {site.where:<42s} {site.text:<36s} {detail}")
        survivors += verdict is not Verdict.CAUGHT
    caught = len(results) - survivors
    print(
        f"\n{len(sites)} sites, {len(results)} mutations: {caught} caught, {survivors} not caught"
    )
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
