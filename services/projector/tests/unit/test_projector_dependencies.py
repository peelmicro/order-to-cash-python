"""A4: the projector's declared dependencies, read from its own `pyproject.toml` as TOML.

The set is a literal: a dependency added later is a deliberate edit here. `motor` (deprecated in
favour of PyMongo's own async API, absent from `uv.lock`) and the write model's stack
(`sqlalchemy`, `asyncpg`, `alembic`: PR21) are named as forbidden so a failure says which claim
broke.
"""

import re
import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

EXPECTED = {
    "fastapi",
    "uvicorn",
    "otc-shared-kernel",
    "otc-contracts",
    "otc-cqrs",
    "pymongo",
    "aiokafka",
    "nats-py",
    "pydantic-settings",
}
FORBIDDEN = {"motor", "sqlalchemy", "asyncpg", "alembic"}


def declared() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    names = set()
    for requirement in data["project"]["dependencies"]:
        match = re.match(r"[A-Za-z0-9_.-]+", requirement)
        assert match is not None, requirement
        names.add(match.group(0).lower().replace("_", "-"))
    return names


def test_the_projector_declares_pymongo_and_no_motor_sqlalchemy_asyncpg_or_alembic() -> None:
    names = declared()
    assert not names & FORBIDDEN, f"forbidden dependency declared: {sorted(names & FORBIDDEN)}"
    assert names == EXPECTED, (
        f"unexpected {sorted(names - EXPECTED)}, missing {sorted(EXPECTED - names)}"
    )
    assert "pymongo" in names
