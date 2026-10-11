"""C1 (ledger L30): no `typing.Any` crosses a port or enters the domain.

The driver's untyped documents (`Mapping[str, Any]`) are confined to `infrastructure`; the writer
converts them into the typed `AppliedDocument` before they reach `application`. An AST walk of
`domain/` and `application/ports/` finds no `Any`, whether imported by name, aliased or reached
through `typing.Any`.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "otc_projector"
GUARDED = (SRC / "domain", SRC / "application" / "ports")


def any_uses(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name) and node.id == "Any":
            found.append(f"{path.name}:{node.lineno} Name Any")
        elif isinstance(node, ast.Attribute) and node.attr == "Any":
            found.append(f"{path.name}:{node.lineno} .Any")
        elif isinstance(node, ast.ImportFrom) and any(a.name == "Any" for a in node.names):
            found.append(f"{path.name}:{node.lineno} import Any")
        elif isinstance(node, ast.alias) and node.name == "Any":
            found.append(f"{path.name}:{node.lineno} alias Any")
    return found


def test_no_typing_any_in_the_domain_or_the_application_ports() -> None:
    files = [f for root in GUARDED for f in sorted(root.rglob("*.py"))]
    names = {f.name for f in files}
    assert {"read_model.py", "update_signal.py", "fact_stream.py", "timeline_order.py"} <= names, (
        f"the guard must range over the real port and domain files: {sorted(names)}"
    )
    offenders = [hit for f in files for hit in any_uses(f)]
    assert offenders == [], f"typing.Any found: {offenders}"
