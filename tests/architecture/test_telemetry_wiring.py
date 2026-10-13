"""Telemetry wiring guards (feature 27, `design.md` 4.1, 4.6, 6.3; ledger L37, L40).

Stage S0 holds one guard: the five OpenTelemetry distributions that must move together resolve to
ONE version in `uv.lock` (a mixed set imports fine and fails at export time). The reader is
`one_version_of`, a pure function of the lock text, so the arm edits a COPY of that text (a
test-local fixture, never `uv.lock`) and the same function says no.
"""

import importlib
import os
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK = REPO_ROOT / "uv.lock"

# The distributions released in lockstep. `opentelemetry-semantic-conventions` is a beta (0.66b0)
# with its own number and is deliberately not in the set.
LOCKSTEP = (
    "opentelemetry-api",
    "opentelemetry-sdk",
    "opentelemetry-exporter-otlp-proto-http",
    "opentelemetry-exporter-otlp-proto-common",
    "opentelemetry-proto",
)


def versions_of(lock_text: str) -> dict[str, list[str]]:
    """Every locked version of each lockstep distribution (a list: the lock may hold several)."""
    found: dict[str, list[str]] = {name: [] for name in LOCKSTEP}
    for package in tomllib.loads(lock_text)["package"]:
        if package["name"] in found:
            found[package["name"]].append(package["version"])
    return found


def disagreement(lock_text: str) -> str | None:
    """None when each lockstep package is locked exactly once and all share one version."""
    versions = versions_of(lock_text)
    missing = [name for name, found in versions.items() if not found]
    if missing:
        return f"not locked: {', '.join(missing)}"
    distinct = {version for found in versions.values() for version in found}
    if len(distinct) != 1 or any(len(found) != 1 for found in versions.values()):
        return f"OpenTelemetry packages disagree: {versions}"
    return None


def test_every_opentelemetry_package_resolves_to_one_version() -> None:
    assert disagreement(LOCK.read_text(encoding="utf-8")) is None


def test_the_one_version_check_sees_a_package_that_differs() -> None:
    """The arm of S0.3: the instrument says no when one package is edited in a copy of the lock."""
    text = LOCK.read_text(encoding="utf-8")
    needle = 'name = "opentelemetry-proto"\nversion = "1.45.0"'
    assert needle in text, "premise: the lock holds opentelemetry-proto 1.45.0 in this exact form"
    mutated = text.replace(needle, 'name = "opentelemetry-proto"\nversion = "1.44.0"')
    message = disagreement(mutated)
    assert message is not None
    assert "disagree" in message
    assert "1.44.0" in message


def test_the_one_version_check_sees_a_package_that_is_missing() -> None:
    text = LOCK.read_text(encoding="utf-8")
    mutated = text.replace('name = "opentelemetry-proto"', 'name = "opentelemetry-proto-gone"')
    message = disagreement(mutated)
    assert message is not None
    assert "opentelemetry-proto" in message


# ------------------------------------------------------------------ FastAPI's native telemetry
# (S3.3, design 4.6). FastAPI 0.142 creates server spans and `http.server.*` metrics whenever a
# global provider is configured, and at lifespan startup builds OTLP exporters from
# `OTEL_EXPORTER_OTLP_ENDPOINT` unless `auto_configure` is false. Every service's `create_app`
# passes `telemetry={...all off...}`. The guard drives the real ASGI lifespan and one real request
# to each app in a FRESH interpreter (global providers are set-once per process, and this suite
# runs other tests that must not meet one), with a global SDK provider and an in-memory reader that
# THE CHILD installs and the endpoint set. A control FastAPI app WITHOUT the argument runs LAST in
# the same child and must be seen by the same instruments (a sweep needs a case that must fail to
# detect), so a green result for the six is not a deaf instrument.

APPS = ("orders", "gateway", "fulfillment", "billing", "notifications", "projector")

NATIVE_TELEMETRY_CHILD = r"""
import asyncio, importlib, json
import httpx
from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)
reader = InMemoryMetricReader()
metrics.set_meter_provider(MeterProvider(metric_readers=[reader]))

built = []
for cls in (OTLPSpanExporter, OTLPMetricExporter):
    def instrument(original, name):
        def init(self, *args, **kwargs):
            built.append(name)
            original(self, *args, **kwargs)
        return init
    cls.__init__ = instrument(cls.__init__, cls.__name__)


async def drive(app):
    inbox, outbox = asyncio.Queue(), asyncio.Queue()
    lifespan = asyncio.create_task(
        app({"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, inbox.get, outbox.put)
    )
    await inbox.put({"type": "lifespan.startup"})
    started = await outbox.get()
    assert started["type"] == "lifespan.startup.complete", started
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        response = await c.get("/health/live")
    await inbox.put({"type": "lifespan.shutdown"})
    await outbox.get()
    await lifespan
    return response.status_code


def observed():
    spans = [span.name for span in exporter.get_finished_spans()]
    exporter.clear()
    data = reader.get_metrics_data()
    requests = 0
    for resource in data.resource_metrics if data else []:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name.startswith("http.server."):
                    requests += sum(getattr(p, "count", 1) for p in metric.data.data_points)
    exporters = len(built)
    built.clear()
    return {"spans": spans, "http_server_points": requests, "exporters_built": exporters}


async def main():
    report = {}
    for service in __APPS__:
        app = importlib.import_module(f"otc_{service}.presentation.app").create_app()
        status = await drive(app)
        report[service] = {
            "status": status,
            "metrics_routes": sorted(
                r.path for r in app.routes if str(getattr(r, "path", "")).startswith("/metrics")
            ),
            **observed(),
        }
    control = FastAPI()

    @control.get("/health/live")
    async def live():
        return {}

    report["control"] = {"status": await drive(control), **observed()}
    print(json.dumps(report))


asyncio.run(main())
""".replace("__APPS__", repr(APPS))


def run_native_telemetry_child() -> dict[str, dict[str, object]]:
    import json
    import os
    import subprocess
    import sys

    environment = {**os.environ, "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:1"}
    result = subprocess.run(  # noqa: S603 - the interpreter running this suite, a fixed script
        [sys.executable, "-I", "-c", NATIVE_TELEMETRY_CHILD],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    reported = [line for line in result.stdout.splitlines() if line.startswith("{")]
    parsed: dict[str, dict[str, object]] = json.loads(reported[-1])
    return parsed


def test_fastapi_native_telemetry_is_off_in_every_app() -> None:
    report = run_native_telemetry_child()

    for service in APPS:
        seen = report[service]
        assert seen["status"] == 200, (service, seen)
        assert seen["spans"] == [], f"{service}: FastAPI's native spans are on: {seen['spans']}"
        assert seen["http_server_points"] == 0, f"{service}: http.server.* metrics are recorded"
        assert seen["exporters_built"] == 0, f"{service}: FastAPI built an OTLP exporter from env"
    # the control app has no argument and runs last: the same instruments must see it, or a green
    # result above would be a deaf instrument (its exporters may be zero when a service above was
    # the process's first to auto-configure, which has already failed the loop)
    control = report["control"]
    assert control["spans"], "the instrument is deaf: FastAPI's own spans were not seen"
    assert control["http_server_points"], "the instrument is deaf: no http.server.* on the control"
    assert control["exporters_built"], "the instrument is deaf: no auto-configured exporter seen"


# ----------------------------------------------------------- OR5: no scrape endpoint, no exporter

SOURCES = REPO_ROOT / "services"


def prometheus_findings(root: Path) -> list[str]:
    """Every sign of a pull-based metrics endpoint under `root/*/src`: an import of a Prometheus
    package, or a string constant that is a `/metrics` route. AST, any region of the module."""
    import ast

    found: list[str] = []
    for path in sorted(root.glob("*/src/**/*.py")):
        if "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
            for module in modules:
                if "prometheus" in module.lower():
                    found.append(
                        f"{path.relative_to(root)}:{getattr(node, 'lineno', 0)}: imports {module}"
                    )
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith("/metrics")
            ):
                found.append(
                    f"{path.relative_to(root)}:{getattr(node, 'lineno', 0)}: route {node.value!r}"
                )
    return found


def test_or5_no_service_serves_a_metrics_route_or_installs_a_prometheus_exporter() -> None:
    assert prometheus_findings(SOURCES) == []
    report = run_native_telemetry_child()
    for service in APPS:
        assert report[service]["metrics_routes"] == [], f"{service} serves a /metrics route"


def test_or5_the_scan_sees_a_metrics_route_and_a_prometheus_import_on_a_temporary_tree(
    tmp_path: Path,
) -> None:
    package = tmp_path / "demo" / "src" / "otc_demo"
    package.mkdir(parents=True)
    (package / "app.py").write_text(
        "from prometheus_client import make_asgi_app\n"
        "def create(app):\n"
        "    app.mount('/metrics', make_asgi_app())\n",
        encoding="utf-8",
    )

    findings = prometheus_findings(tmp_path)

    assert any("route '/metrics'" in item for item in findings), findings
    assert any("imports prometheus_client" in item for item in findings), findings


def prometheus_packages_of(lock_text: str) -> list[str]:
    """Every locked distribution whose name says Prometheus (the exporter, the client library)."""
    return sorted(
        package["name"]
        for package in tomllib.loads(lock_text)["package"]
        if "prometheus" in package["name"].lower()
    )


def test_or5_no_prometheus_distribution_is_locked_for_any_service() -> None:
    """#8's `OR5_DirectoryPackagesPropsNeverPinsThePrometheusExporterPackage`: the import scan
    above cannot see a package that is installed and never imported, so the lock is read too."""
    assert prometheus_packages_of(LOCK.read_text(encoding="utf-8")) == []


def test_or5_the_lock_scan_sees_a_prometheus_package() -> None:
    text = LOCK.read_text(encoding="utf-8")
    needle = 'name = "opentelemetry-proto"\nversion'
    assert needle in text, "premise: the lock holds opentelemetry-proto as a package entry"
    mutated = text.replace(needle, 'name = "opentelemetry-exporter-prometheus"\nversion', 1)
    assert prometheus_packages_of(mutated) == ["opentelemetry-exporter-prometheus"]


# ------------------------------------------- L40: the new packages raise no DeprecationWarning

TELEMETRY_IMPORTS = (
    "structlog",
    "opentelemetry.sdk.trace",
    "opentelemetry.sdk.metrics",
    "opentelemetry.sdk.resources",
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "opentelemetry.exporter.otlp.proto.http.metric_exporter",
)


def child_stderr_under_warnings_as_errors(code: str) -> tuple[int, str]:
    """Run `code` in a fresh interpreter where a Deprecation or PendingDeprecation warning is an
    error (the suite's own policy), and return its exit code and stderr."""
    import subprocess
    import sys

    done = subprocess.run(  # noqa: S603 - the interpreter running this test and a literal code string
        [
            sys.executable,
            "-W",
            "error::DeprecationWarning",
            "-W",
            "error::PendingDeprecationWarning",
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return done.returncode, done.stderr


def test_l40_the_telemetry_packages_import_without_a_deprecation_warning() -> None:
    """Ledger L40: structlog and the OpenTelemetry SDK and OTLP exporters, imported under `-W error`
    (the first import of each is what a dependency's own DeprecationWarning would fire on)."""
    code, stderr = child_stderr_under_warnings_as_errors("import " + ", ".join(TELEMETRY_IMPORTS))
    assert (code, stderr) == (0, ""), stderr


def test_l40_the_probe_sees_a_deprecation_warning() -> None:
    code, stderr = child_stderr_under_warnings_as_errors(
        "import warnings; warnings.warn('a dependency deprecates itself', DeprecationWarning)"
    )
    assert code != 0
    assert "DeprecationWarning" in stderr


# ------------------------------------------- R59: every gauge is synchronous (design 6.2, L12)


def observable_instrument_findings(root: Path) -> list[str]:
    """Every creation of an observable instrument under `root/*/src`: a call to any
    `create_observable_*` method, or a use of the SDK's `Observable*` classes. AST, any region of
    the module (a dead region counts; a comment or a string does not). An observable instrument's
    callback runs on the metric reader's THREAD at export time, where asyncpg and aiokafka objects,
    which belong to the loop, must not be touched."""
    import ast

    found: list[str] = []
    for path in sorted(root.glob("*/src/**/*.py")):
        if "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            name: str | None = None
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            elif isinstance(node, ast.ImportFrom):
                name = next((a.name for a in node.names if a.name.startswith("Observable")), None)
            if name is not None and (
                name.startswith("create_observable_") or name.startswith("Observable")
            ):
                found.append(f"{path.relative_to(root)}:{getattr(node, 'lineno', 0)}: {name}")
    return found


def test_no_observable_instrument_is_created_under_src() -> None:
    scanned = [p for p in SOURCES.glob("*/src/**/metrics.py") if "__pycache__" not in p.parts]
    assert len(scanned) == len(APPS), f"the scan did not reach the six metrics modules: {scanned}"
    assert observable_instrument_findings(SOURCES) == []


def test_the_observable_scan_sees_a_create_call_in_any_region_and_ignores_text(
    tmp_path: Path,
) -> None:
    package = tmp_path / "demo" / "src" / "otc_demo"
    package.mkdir(parents=True)
    (package / "live.py").write_text(
        "def make(meter, cb):\n    return meter.create_observable_gauge('x', callbacks=[cb])\n",
        encoding="utf-8",
    )
    (package / "dead.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    meter.create_observable_counter('y')\n"
        "if False:\n"
        "    meter.create_observable_up_down_counter('z')\n",
        encoding="utf-8",
    )
    (package / "text.py").write_text(
        "# meter.create_observable_gauge('c')\n"
        "NOTE = 'meter.create_observable_gauge(x)'\n"
        'DOC = """create_observable_gauge("y")"""\n',
        encoding="utf-8",
    )

    findings = observable_instrument_findings(tmp_path)

    assert sorted(item.split(":")[0] for item in findings) == sorted(
        ["demo/src/otc_demo/live.py", "demo/src/otc_demo/dead.py", "demo/src/otc_demo/dead.py"]
    ), findings


# --------------------------------------------- the session never exports (design 9.2, S3.1)


def test_the_test_session_blanks_the_otlp_endpoint_so_a_developers_dotenv_cannot_start_an_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every settings class reads `.env`, and the developer's `.env` carries the collector's address
    (S8.4). The root `conftest.py` sets the variable to the empty string for the whole session, and
    a process variable outranks the dotenv file. Nothing in this test sets or clears the variable:
    it only plants a `.env` naming a collector and asks each service's settings what they hold."""
    (tmp_path / ".env").write_text(
        "OTEL_EXPORTER_OTLP_ENDPOINT=http://collector.developer.sentinel:4318\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    held: dict[str, str] = {}
    for service in APPS:
        settings = importlib.import_module(f"otc_{service}.infrastructure.settings")
        held[service] = settings.TelemetrySettings().otlp_endpoint

    assert held == dict.fromkeys(APPS, ""), "a runtime built by the suite would export"
    assert os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] == ""


# ------------------------------------------- every traced component is handed the runtime's tracer

# Components that default their tracer to a no-op (`NO_TRACER`) so a unit test can build one without
# a provider. The default makes a forgotten argument SILENT: the hop would simply stop producing
# spans. Each composition root must therefore pass `tracer=telemetry.tracer` to every one of them.
# (The Projector's subscriber is built through the `Externals.subscriber` seam, which takes the
# tracer as a parameter; `test_composition.py` records what the seam receives.)
TRACED_COMPONENTS: dict[str, set[str]] = {
    "orders": {
        "SqlAlchemyUnitOfWork",
        "NatsStockAvailability",
        "NatsSagaCommandsAdapter",
        "SagaCommandDispatcher",
        "OrdersCreateResponder",
        "KafkaFactSubscriber",
        "OutboxRelay",
    },
    "fulfillment": {"SqlAlchemyStockTransactions", "StockResponder", "OutboxRelay"},
    "billing": {"SqlAlchemyCreditTransactions", "CreditResponder", "OutboxRelay"},
    "notifications": {"SqlAlchemyDeliveryLedger", "KafkaFactSubscriber"},
    "gateway": {"NatsRpcClient"},
    "projector": set(),
}


def untraced_constructions(source: str, expected: set[str]) -> list[str]:
    """Constructions of `expected` classes in `source` whose `tracer` argument is not
    `telemetry.tracer`, plus the expected classes never constructed at all."""
    import ast

    seen: dict[str, list[str]] = {name: [] for name in expected}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in seen:
            passed = [ast.unparse(k.value) for k in node.keywords if k.arg == "tracer"]
            seen[node.func.id].append(passed[0] if passed else "<no tracer argument>")
    problems = [f"{name}: never constructed" for name, calls in seen.items() if not calls]
    problems += [
        f"{name}: tracer={argument}"
        for name, calls in seen.items()
        for argument in calls
        if argument != "telemetry.tracer"
    ]
    return problems


@pytest.mark.parametrize("service", sorted(TRACED_COMPONENTS))
def test_every_traced_component_is_constructed_with_the_runtimes_tracer(service: str) -> None:
    source = (SOURCES / service / "src" / f"otc_{service}" / "composition.py").read_text(
        encoding="utf-8"
    )

    assert untraced_constructions(source, TRACED_COMPONENTS[service]) == []


def test_the_tracer_wiring_check_sees_a_missing_and_a_wrong_argument() -> None:
    source = "x = Traced(tracer=telemetry.tracer)\ny = Traced()\nz = Traced(tracer=other.tracer)\n"

    assert untraced_constructions(source, {"Traced", "Absent"}) == [
        "Absent: never constructed",
        "Traced: tracer=<no tracer argument>",
        "Traced: tracer=other.tracer",
    ]
