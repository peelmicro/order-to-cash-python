"""C3 (PR2): `mypy --strict` rejects a `project` match that omits a fact.

The fixture is a copy of the REAL `application/projection.py` with exactly one `case` arm removed
(by AST, so it follows the source), type-checked in a temporary directory against the workspace's
source roots. The control copy (nothing removed) must pass, so the instrument can say yes as well as
no; the omitting copy must fail and the failure must name `assert_never`.
"""

import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PROJECTION = REPO / "services/projector/src/otc_projector/application/projection.py"
SOURCE_ROOTS = [
    REPO / "packages/shared_kernel/src",
    REPO / "packages/contracts/src",
    REPO / "packages/cqrs/src",
    REPO / "services/projector/src",
]


def without_arm(source: str, class_name: str) -> str:
    tree = ast.parse(source)
    removed = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Match):
            kept = [
                case
                for case in node.cases
                if not (
                    isinstance(case.pattern, ast.MatchClass)
                    and isinstance(case.pattern.cls, ast.Name)
                    and case.pattern.cls.id == class_name
                )
            ]
            removed += len(node.cases) - len(kept)
            node.cases = kept
    assert removed == 1, f"expected to remove exactly one arm for {class_name}, removed {removed}"
    return ast.unparse(tree)


def mypy(directory: Path, source: str) -> tuple[int, str]:
    directory.mkdir()
    module = directory / "snippet.py"
    module.write_text(source)
    config = directory / "mypy.ini"
    config.write_text(
        "[mypy]\nstrict = True\nexplicit_package_bases = True\nnamespace_packages = True\n"
        f"mypy_path = {':'.join(str(p) for p in SOURCE_ROOTS)}\n"
        "[mypy-aiokafka.*]\nignore_missing_imports = True\n"
    )
    completed = subprocess.run(  # noqa: S603 - fixed argv: this interpreter running mypy
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(config),
            "--cache-dir",
            str(directory / ".mypy_cache"),
            str(module),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=directory,
    )
    return completed.returncode, completed.stdout + completed.stderr


def test_pr2_mypy_rejects_a_projection_match_that_omits_a_fact(tmp_path: Path) -> None:
    source = PROJECTION.read_text(encoding="utf-8")
    code, output = mypy(tmp_path / "control", source)
    assert code == 0, f"PR2 control: the complete match was rejected by mypy --strict:\n{output}"
    code, output = mypy(tmp_path / "omits", without_arm(source, "OrderSagaFailedEvent"))
    assert code != 0, "PR2: mypy --strict accepted a match over FactEvent that omits a fact"
    assert "assert_never" in output, f"PR2: mypy failed for another reason:\n{output}"
