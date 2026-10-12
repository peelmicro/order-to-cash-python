"""R54, the Gateway's half of the sole-writer claim: the Gateway only READS the read model.

The cross-service guard `services/projector/tests/unit/test_read_model_sole_writer.py` scans every
`services/*/src` for a write-shaped pymongo call and allows exactly the projector and the seed; the
Gateway reading `order_timeline` passes it and a Gateway write fails it (armed in the impl record
by planting `update_one` in `mongo_order_read_model.py`). This file is the Gateway's own, stricter
statement, a positive set rather than a deny-list: the only methods the service calls on a MongoDB
collection are `find`, `find_one` and `count_documents`, and no aggregation pipeline mentions a
writing stage (`$out`, `$merge`). Limitations stated: a collection reached under another name is not
followed (the scan reads the attribute names of every call in the service).
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "otc_gateway"
COLLECTION_READS = {"find", "find_one", "count_documents"}
WRITING_STAGES = ("$out", "$merge")


def collection_calls(source: str) -> set[str]:
    """Names called on `self._collection` (the adapter's one handle)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "_collection"
        ):
            names.add(node.func.attr)
    return names


def test_the_only_calls_on_the_collection_handle_are_reads() -> None:
    adapter = SRC / "infrastructure" / "mongo_order_read_model.py"

    assert collection_calls(adapter.read_text(encoding="utf-8")) == COLLECTION_READS


def test_no_module_of_the_gateway_names_a_writing_aggregation_stage() -> None:
    offenders = [
        f"{path.relative_to(SRC)}: {stage}"
        for path in sorted(SRC.rglob("*.py"))
        for stage in WRITING_STAGES
        if stage in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_the_collection_handle_is_reached_only_from_the_read_model_adapter() -> None:
    """Which modules mention the MongoDB client library at all: the adapter and the composition
    root that builds the client, and nobody else."""
    importers = sorted(
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if any(
            (
                isinstance(node, ast.Import)
                and any(a.name.split(".")[0] == "pymongo" for a in node.names)
            )
            or (isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "pymongo")
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        )
    )

    assert importers == ["composition.py", "infrastructure/mongo_order_read_model.py"]


def test_sentinel_the_scan_sees_a_write_planted_on_the_handle() -> None:
    planted = "async def f(self):\n    await self._collection.update_one({}, {})\n"

    assert collection_calls(planted) == {"update_one"}
    assert collection_calls(planted) != COLLECTION_READS
