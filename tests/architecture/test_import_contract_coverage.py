"""The import-linter contracts name every service explicitly; this proves none is left out.

import-linter wildcards cannot express `otc_*.domain`, so the lists are literal. A service added
under services/ without being added to the contracts would otherwise be silently unguarded.
"""

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _contracts() -> dict[str, dict[str, object]]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    return {c["id"]: c for c in data["tool"]["importlinter"]["contracts"]}


def _services() -> set[str]:
    return {p.name for p in (REPO_ROOT / "services").iterdir() if p.is_dir()}


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
