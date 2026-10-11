"""B4: the projector's domain imports ONLY the standard library and `otc_shared_kernel`.

An AST walk; import-linter's `domain-purity` is the second instrument and also counts indirect
chains.
"""

import ast
import sys
from pathlib import Path

DOMAIN = Path(__file__).resolve().parents[2] / "src" / "otc_projector" / "domain"
ALLOWED_ROOTS = frozenset(sys.stdlib_module_names) | {"otc_shared_kernel"}


def imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path}: a relative import hides its module"
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_the_domain_imports_only_the_standard_library_and_the_shared_kernel() -> None:
    files = sorted(DOMAIN.rglob("*.py"))
    assert {f.name for f in files} >= {
        "projection_delta.py",
        "status_rank.py",
        "timeline_order.py",
    }, f"the guard must range over the real domain files: {files}"
    for file in files:
        foreign = imported_roots(file) - ALLOWED_ROOTS
        assert not foreign, f"{file.relative_to(DOMAIN.parents[3])} imports {sorted(foreign)}"
