"""The import-linter contracts name every service explicitly; this proves none is left out.

import-linter wildcards cannot express `otc_*.domain`, so the lists are literal. A service added
under services/ without being added to the contracts would otherwise be silently unguarded.
"""

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _contracts() -> dict[str, dict[str, object]]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    return {c["id"]: c for c in data["tool"]["importlinter"]["contracts"]}


VALID_SERVICE_NAME = re.compile(r"[a-z][a-z0-9_]*")


def service_directories(root: Path) -> set[str]:
    """The directories under `services/` that can be a service package.

    A tool cache (`.mypy_cache`, `.ruff_cache`) is not a service; excluding it HERE, where the
    listing is built, keeps it out of the population instead of filtering results.
    """
    return {
        p.name
        for p in (root / "services").iterdir()
        if p.is_dir() and VALID_SERVICE_NAME.fullmatch(p.name)
    }


def _services() -> set[str]:
    return service_directories(REPO_ROOT)


def test_domain_purity_contract_lists_every_service_domain() -> None:
    sources = set(_contracts()["domain-purity"]["source_modules"])  # type: ignore[call-overload]
    assert sources == {f"otc_{s}.domain" for s in _services()}, (
        "domain-purity forbidden contract does not cover exactly every service domain"
    )


def test_every_service_has_a_layers_contract_over_its_own_four_layers() -> None:
    contracts = _contracts()
    for service in _services():
        contract = contracts.get(f"layers-{service}")
        assert contract is not None, f"service {service} has no layers contract"
        assert contract["layers"] == [
            f"otc_{service}.{layer}"
            for layer in ("presentation", "infrastructure", "application", "domain")
        ], f"layers contract of {service} is not the four-layer order"


def test_independence_contract_lists_every_service() -> None:
    modules = set(_contracts()["service-independence"]["modules"])  # type: ignore[call-overload]
    assert modules == {f"otc_{s}" for s in _services()}, (
        "service-independence contract does not cover exactly every service package"
    )


def test_forbidden_lists_include_every_framework_and_otc_cqrs() -> None:
    required = {
        "sqlalchemy", "asyncpg", "alembic", "aiokafka", "nats", "pymongo", "bson", "gridfs",
        "fastapi", "starlette", "pydantic", "pydantic_settings", "httpx", "structlog",
        "opentelemetry",
        "otc_cqrs",
    }  # fmt: skip
    for contract_id in ("domain-purity", "shared-kernel-purity"):
        forbidden = set(_contracts()[contract_id]["forbidden_modules"])  # type: ignore[call-overload]
        assert forbidden == required, f"{contract_id}: forbidden module list drifted"


def test_a_dot_directory_under_services_is_not_a_service_but_a_real_undeclared_one_is(
    tmp_path: Path,
) -> None:
    """S5.10 sentinel: the instrument's premises (P1 a dot-directory is a tool cache; P2 a name that
    is a valid package identifier is a service, declared or not) hold on a temporary tree."""
    (tmp_path / "services" / "orders").mkdir(parents=True)
    cache = tmp_path / "services" / ".sentinel_cache"
    cache.mkdir()
    (cache / "stray.py").write_text("X = 1\n")
    assert service_directories(tmp_path) == {"orders"}, "a dot-directory joined the population"
    (tmp_path / "services" / "undeclared").mkdir()
    assert service_directories(tmp_path) == {"orders", "undeclared"}, (
        "a real undeclared service directory must stay in the population"
    )
