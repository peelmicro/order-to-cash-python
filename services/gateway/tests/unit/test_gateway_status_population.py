"""Backlog 215, acceptance 1: every `(operation, HTTP status)` pair the Gateway can answer, derived
from its code by execution, set against every pair `openapi.yaml` declares.

HOW THE POPULATION IS DERIVED (and why it is complete). A status leaves the Gateway by exactly four
doors, each a finite, enumerable source:

1. `presentation.problems.classify(error)`: a pure function over the exception classes of
   `application/errors.py` (plus `LoginThrottledError` and the fallthrough 500). An error reaches
   it either from a DEPENDENCY the route calls (the RPC client: 5 kinds, the 12 generic `RpcError`
   codes and the 5 specific `(code, details.code)` rows read from `domain.rpc_error_classification`;
   the read model: `ReadModelUnavailableError`; anything else: an unexpected exception) or from a
   HANDLER that raises it itself. Dependency errors are INJECTED, per operation, into the real
   application (`DEPENDENCY_INJECTIONS`); handler-raised errors are the `raise` SITES under
   `application/`, each one a (file, enclosing class and function, exception class) triple found by
   an AST walk (`raise_sites`) and compared with the literal `HANDLER_RAISE_SITES`, so a new raise
   site fails here, naming it, until it is classified (a new `raise` of an already-listed class in
   another handler of an already-listed file included), mapped to the operations whose handler
   raises it and turned into a status by `classify`. A `raise` that is not `raise Name(...)` (a
   bare `raise`, `raise error`, `raise mod.Error(...)`) cannot be classified and fails outright.
2. The validation handler: a malformed request is a 400, and which operations can be malformed is
   read from the GENERATED OpenAPI (an operation with a declared parameter or request body), then
   shown by sending each a request that violates its constraints (`INVALID_REQUESTS`).
3. The bearer middleware: 401 on every protected operation (read from the running app's routes
   minus the public literal), 503 before the lifespan has run (the stream included, driven through
   the cold app by `asgi_stream`).
4. The login limiter: 429 on `POST /auth/login`.

The operations are the running app's routes (`iter_route_contexts`, never a list typed here); a
route without a request builder in `VALID_REQUESTS` fails the sentinel test, so a new route cannot
escape the population. SENTINELS: the pairs the filing of backlog 215 named must be found, and a
pair known to be declared must be found AND not reported undeclared.

STATE AFTER SA-9 (backlog 215 closed). `openapi.yaml` carries `default` (`UnlistedProblem`) on every
operation, so every observed pair is declared, by name or through `default`. This test still
fails on something real: (a) every operation of the committed contract carries `default`; (b)
the count of statuses declared BY NAME is a literal (`DECLARED_BY_NAME`); (c) the pairs answered
ONLY through
`default` (undeclared by name) equal the literals `GATEWAY_ORIGINATED` and `PASS_THROUGH`, each
classified, so a new by-name-undeclared status is still named. An unreadable responder reply is a
503 `UPSTREAM_UNAVAILABLE` (SA-9), so no 502 is answered any more (asserted).
"""

import ast
import re
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi.routing import APIRoute, iter_route_contexts

from otc_gateway.application.errors import (
    GatewayNotFoundError,
    InvalidCredentialsError,
    InvalidTokenError,
    InvoiceNotFoundError,
    InvoiceScanBudgetExceededError,
    OrderNotYetProjectedError,
    ReadModelUnavailableError,
    RpcProtocolError,
    RpcRemoteError,
    RpcTimeoutError,
    RpcUnavailableError,
)
from otc_gateway.domain.rpc_error_classification import GENERIC, SPECIFIC
from otc_gateway.presentation.app import create_app
from otc_gateway.presentation.problems import classify
from otc_gateway.presentation.public_routes import PUBLIC_OPERATIONS

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC = Path(__file__).resolve().parents[2] / "src" / "otc_gateway"
type Operation = tuple[str, str]

ORDER_BODY = {
    "retailerCode": "CarrefourEs",
    "companyCode": "IBERFOODS",
    "currency": "EUR",
    "lines": [{"productCode": "PRD-0001", "quantity": 5}],
}
PAYMENT_BODY = {
    "paymentReference": "PAY-2026-08-18-000019",
    "amount": {"amount": 124250, "currency": "EUR"},
    "valueDate": "2026-08-18T11:02:00.000Z",
    "source": "robot",
}
ANY_ID = "0a0b0c0d-1111-4000-8000-0000000000a1"

# A well-formed request for every operation (the stream is driven by `STREAM`, below).
VALID_REQUESTS: dict[Operation, dict[str, Any]] = {
    ("POST", "/auth/login"): {
        "json": {"username": "operator", "password": "unit-test-operator-password"}
    },
    ("GET", "/auth/me"): {},
    ("POST", "/orders"): {"json": ORDER_BODY},
    ("GET", "/orders"): {},
    ("GET", "/orders/{id}"): {},
    ("POST", "/orders/{id}/cancel"): {"json": {"note": "n"}},
    ("GET", "/stock"): {},
    ("POST", "/stock/replenish"): {
        "json": {"companyCode": "IBERFOODS", "lines": [{"productCode": "PRD-0001", "units": 1}]}
    },
    ("GET", "/invoices"): {},
    ("POST", "/invoices/{id}/payments"): {"json": PAYMENT_BODY},
    ("GET", "/credits"): {},
    ("GET", "/catalog/products"): {},
    ("GET", "/catalog/retailers"): {},
    ("GET", "/catalog/companies"): {},
    ("GET", "/health/live"): {},
    ("GET", "/health/ready"): {},
    ("GET", "/docs"): {},
}
STREAM: Operation = ("GET", "/orders/stream")

# A request that violates the operation's own constraints (only operations that HAVE constraints).
INVALID_REQUESTS: dict[Operation, dict[str, Any]] = {
    ("POST", "/auth/login"): {"json": {}},
    ("POST", "/orders"): {"json": {}},
    ("GET", "/orders"): {"params": {"page": "0"}},
    ("GET", "/orders/{id}"): {"path_id": "not-a-uuid"},
    ("POST", "/orders/{id}/cancel"): {"path_id": "not-a-uuid"},
    ("GET", "/stock"): {"params": {"page": "0"}},
    ("POST", "/stock/replenish"): {"json": {}},
    ("GET", "/invoices"): {"params": {"page": "0"}},
    ("POST", "/invoices/{id}/payments"): {"path_id": "not-a-uuid"},
    ("GET", "/credits"): {"params": {"page": "0"}},
    STREAM: {"params": {"orderId": "not-a-uuid"}},
}

# Dependency failures: (label, how to raise it). Read from the code's own tables, not retyped.
RPC_ERRORS: dict[str, Exception] = {
    **{f"rpc remote {code}": RpcRemoteError("x", code, "m") for code in GENERIC},
    **{
        f"rpc remote {code}+{detail}": RpcRemoteError("x", code, "m", {"code": detail})
        for code, detail in SPECIFIC
    },
    "rpc timeout": RpcTimeoutError("x", 1),
    "rpc unavailable": RpcUnavailableError("x", "m"),
    "rpc protocol": RpcProtocolError("x", "m"),
    "unexpected": RuntimeError("boom"),
}
READ_MODEL_ERRORS: dict[str, Exception] = {
    "read model unavailable": ReadModelUnavailableError("m"),
    "unexpected": RuntimeError("boom"),
}

# The `raise` sites under application/: (file, enclosing class/function, exception class) -> the
# operations whose handler runs that code, and the instance `classify` is asked about. One entry per
# SITE: a new raise anywhere (another handler of a listed file, another function) is not in here.
# `MissingBindingError` is raised at boot (`GatewayScope.__post_init__`), reachable from no request.
type Site = tuple[str, str, str]
HANDLER_RAISE_SITES: dict[Site, tuple[list[Operation], Exception]] = {
    ("auth_handlers.py", "LoginHandler.handle", "InvalidCredentialsError"): (
        [("POST", "/auth/login")],
        InvalidCredentialsError("m"),
    ),
    ("auth_handlers.py", "GetCurrentUserHandler.handle", "InvalidTokenError"): (
        [("GET", "/auth/me")],
        InvalidTokenError("m"),
    ),
    ("payment_handlers.py", "RegisterPaymentHandler.handle", "OrderNotYetProjectedError"): (
        [("POST", "/invoices/{id}/payments")],
        OrderNotYetProjectedError("ORD-000001"),
    ),
    ("payment_handlers.py", "RegisterPaymentHandler._order_reference_of", "InvoiceNotFoundError"): (
        [("POST", "/invoices/{id}/payments")],
        InvoiceNotFoundError("x"),
    ),
    (
        "payment_handlers.py",
        "RegisterPaymentHandler._order_reference_of",
        "InvoiceScanBudgetExceededError",
    ): (
        [("POST", "/invoices/{id}/payments")],
        InvoiceScanBudgetExceededError("x", 1),
    ),
    ("order_commands.py", "CancelOrderHandler.handle", "RpcProtocolError"): (
        [("POST", "/orders/{id}/cancel")],
        RpcProtocolError("x", "m"),
    ),
    ("order_queries.py", "GetOrderHandler.handle", "GatewayNotFoundError"): (
        [("GET", "/orders/{id}")],
        GatewayNotFoundError("m"),
    ),
    ("order_views.py", "order_summary", "IncompleteOrderHeaderError"): (
        [("GET", "/orders")],
        RuntimeError("incomplete"),
    ),
    ("scope.py", "GatewayScope.__post_init__", "MissingBindingError"): (
        [],
        RuntimeError("boot-time"),
    ),
}

# The handler files that use each dependency (found by a search below, compared with these
# literals) and the operations whose routes dispatch to them.
RPC_FILES: dict[str, list[Operation]] = {
    "payment_handlers.py": [("POST", "/invoices/{id}/payments")],
    "stock_handlers.py": [("GET", "/stock"), ("POST", "/stock/replenish")],
    "billing_handlers.py": [("GET", "/invoices"), ("GET", "/credits")],
    "order_commands.py": [("POST", "/orders"), ("POST", "/orders/{id}/cancel")],
    "catalog_handlers.py": [
        ("GET", "/catalog/products"),
        ("GET", "/catalog/retailers"),
        ("GET", "/catalog/companies"),
    ],
}
READ_MODEL_FILES: dict[str, list[Operation]] = {
    "order_queries.py": [("GET", "/orders"), ("GET", "/orders/{id}")],
    "payment_handlers.py": [("POST", "/invoices/{id}/payments")],
}

# Backlog 215 (closed by SA-9 and its #9 code half): the openapi.yaml now carries `default` on every
# operation, so these pairs are answered through `default` and named here: they are undeclared BY
# NAME, in the two classes below (this literal IS the citation: a new by-name-undeclared status
# fails the test and is named).
# The by-name declared statuses (every `responses` key except `default`), counted over the contract.
DECLARED_BY_NAME = 61  # counted over specs/shared/openapi.yaml, `default` excluded

# Produced by the Gateway's own code (validation, the middleware, `classify` over its own
# errors, the fallthrough 500): 24 pairs, 4 of them reachable only without a lifespan.
GATEWAY_ORIGINATED: set[tuple[str, str, int]] = {
    ("GET", "/auth/me", 503),
    ("GET", "/catalog/companies", 500),
    ("GET", "/catalog/products", 500),
    ("GET", "/catalog/retailers", 500),
    ("GET", "/credits", 400),
    ("GET", "/credits", 500),
    ("GET", "/docs", 503),
    ("GET", "/invoices", 400),
    ("GET", "/invoices", 500),
    ("GET", "/orders", 500),
    ("GET", "/orders", 503),
    ("GET", "/orders/stream", 400),
    ("GET", "/orders/stream", 503),
    ("GET", "/orders/{id}", 400),
    ("GET", "/orders/{id}", 500),
    ("GET", "/orders/{id}", 503),
    ("GET", "/stock", 400),
    ("GET", "/stock", 500),
    ("POST", "/auth/login", 503),
    ("POST", "/invoices/{id}/payments", 500),
    ("POST", "/orders", 500),
    ("POST", "/orders/{id}/cancel", 400),
    ("POST", "/orders/{id}/cancel", 500),
    ("POST", "/stock/replenish", 500),
}
# Mapped from a responder-chosen `RpcError.code` (an upper bound: whether the owning context ever
# sends it for that subject is not decided here): 25 pairs. #7 and #8 map the same codes the same
# way (`rpc-error-mapping.ts`, `RpcErrorClassification.cs`).
PASS_THROUGH: set[tuple[str, str, int]] = {
    ("GET", "/catalog/companies", 400),
    ("GET", "/catalog/companies", 404),
    ("GET", "/catalog/companies", 409),
    ("GET", "/catalog/companies", 422),
    ("GET", "/catalog/products", 400),
    ("GET", "/catalog/products", 404),
    ("GET", "/catalog/products", 409),
    ("GET", "/catalog/products", 422),
    ("GET", "/catalog/retailers", 400),
    ("GET", "/catalog/retailers", 404),
    ("GET", "/catalog/retailers", 409),
    ("GET", "/catalog/retailers", 422),
    ("GET", "/credits", 404),
    ("GET", "/credits", 409),
    ("GET", "/credits", 422),
    ("GET", "/invoices", 404),
    ("GET", "/invoices", 409),
    ("GET", "/invoices", 422),
    ("GET", "/stock", 404),
    ("GET", "/stock", 409),
    ("GET", "/stock", 422),
    ("POST", "/orders", 404),
    ("POST", "/orders/{id}/cancel", 422),
    ("POST", "/stock/replenish", 409),
    ("POST", "/stock/replenish", 422),
}


def operations_of(app: Any) -> set[Operation]:
    return {
        (method, str(context.path))
        for context in iter_route_contexts(app.routes)
        if isinstance(context.original_route, APIRoute)
        for method in context.methods or ()
        if method != "HEAD"
    }


def declared_statuses() -> dict[Operation, set[int]]:
    document = yaml.safe_load((REPO_ROOT / "specs/shared/openapi.yaml").read_text("utf-8"))
    return {
        (method.upper(), path): {
            int(status) for status in operation["responses"] if status != "default"
        }
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if method in {"get", "post"}
    }


def operations_with_default() -> set[Operation]:
    """The operations whose `responses` carry `default` (SA-9: `UnlistedProblem`, on every one)."""
    document = yaml.safe_load((REPO_ROOT / "specs/shared/openapi.yaml").read_text("utf-8"))
    return {
        (method.upper(), path)
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if method in {"get", "post"} and "default" in operation["responses"]
    }


def path_of(template: str, path_id: str = ANY_ID) -> str:
    return template.replace("{id}", path_id)


async def raising(error: Exception, *args: Any, **kwargs: Any) -> Any:
    raise error


async def observe(harness: Any, asgi_stream: Any) -> dict[tuple[str, str, int], set[str]]:
    """{(method, path, status): {the sources that produced it}} for every status >= 400."""
    found: dict[tuple[str, str, int], set[str]] = {}

    def note(operation: Operation, status: int, source: str) -> None:
        if status >= 400:
            found.setdefault((*operation, status), set()).add(source)

    async def send(operation: Operation, headers: dict[str, str], **spec: Any) -> int:
        method, template = operation
        if operation == STREAM:
            stream = asgi_stream(
                harness.app,
                STREAM[1] + "".join(f"?{k}={v}" for k, v in spec.get("params", {}).items()),
                headers,
            )
            return int(await stream.response_started("the stream's status line"))
        kwargs = {k: v for k, v in spec.items() if k in {"json", "params"}}
        response = await harness.client.request(
            method,
            path_of(template, spec.get("path_id", ANY_ID)),
            headers=headers,
            **kwargs,
        )
        return int(response.status_code)

    operations = operations_of(harness.app)
    auth = harness.bearer()
    rpc_call, read_model = harness.rpc.call, harness.read_model
    original = {
        n: getattr(read_model, n)
        for n in ("find_by_id", "find_order_id_by_reference", "list_orders")
    }

    # door 3: the bearer middleware
    for operation in operations - PUBLIC_OPERATIONS:
        note(operation, await send(operation, {}), "no token")
        note(operation, await send(operation, {"Authorization": "Bearer x.y.z"}), "bad token")
    # door 2: a malformed request
    for operation, spec in INVALID_REQUESTS.items():
        note(operation, await send(operation, auth, **spec), "invalid request")
    # the baseline: healthy fakes (an unconfigured one answers its own kind of failure)
    for operation in operations - {STREAM}:
        note(operation, await send(operation, auth, **VALID_REQUESTS[operation]), "baseline")
    # door 1: a failing dependency, injected where the handler uses it
    rpc_operations = {op for ops in RPC_FILES.values() for op in ops}
    for label, error in RPC_ERRORS.items():
        harness.rpc.call = lambda *a, e=error, **k: raising(e)
        for operation in sorted(rpc_operations):
            note(
                operation, await send(operation, auth, **VALID_REQUESTS[operation]), f"rpc: {label}"
            )
    harness.rpc.call = rpc_call
    for label, error in READ_MODEL_ERRORS.items():
        for name in original:
            setattr(read_model, name, lambda *a, e=error, **k: raising(e))
        for operation in sorted({("GET", "/orders"), ("GET", "/orders/{id}")}):
            note(
                operation,
                await send(operation, auth, **VALID_REQUESTS[operation]),
                f"read model: {label}",
            )
        # a handler that reads the model AFTER an RPC success: the status classify gives the error
        for file, handler_operations in READ_MODEL_FILES.items():
            for operation in handler_operations:
                if operation not in {("GET", "/orders"), ("GET", "/orders/{id}")}:
                    note(operation, classify(error).status, f"read model (via {file}): {label}")
    for name, method in original.items():
        setattr(read_model, name, method)
    # door 1, handler-raised: the raise sites' errors through `classify`, for their operations
    for (_file, _scope, exception), (handler_operations, error) in HANDLER_RAISE_SITES.items():
        for operation in handler_operations:
            note(operation, classify(error).status, f"handler raises {exception}")
    # door 4: the login limiter (harness limit 3 per window)
    for _ in range(5):
        status = await send(("POST", "/auth/login"), {}, **VALID_REQUESTS[("POST", "/auth/login")])
        note(("POST", "/auth/login"), status, "login limiter")
    # before the lifespan: no runtime
    cold = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=cold), base_url="http://cold.test"
    ) as client:
        for operation in operations - {STREAM}:
            response = await client.request(operation[0], path_of(operation[1]), headers=auth)
            note(operation, response.status_code, "no runtime")
    # the stream, through the same cold app, bounded (ASGITransport would wait for a body forever)
    cold_stream = asgi_stream(cold, STREAM[1], auth)
    note(STREAM, await cold_stream.response_started("the cold stream's status line"), "no runtime")
    return found


def files_using(pattern: str) -> set[str]:
    needle = re.compile(pattern)
    return {
        path.name
        for path in sorted((SRC / "application").glob("*.py"))
        if needle.search(path.read_text("utf-8"))
    }


def test_the_files_that_use_each_dependency_are_exactly_the_ones_listed_here() -> None:
    assert files_using(r"\.rpc\.call\(|scope\.rpc") - {"scope.py", "messages.py"} == set(RPC_FILES)
    assert files_using(r"scope\.read_model") == set(READ_MODEL_FILES)


def raise_sites() -> tuple[set[Site], list[str]]:
    """Every `raise` under application/ as (file, enclosing class/function, exception class), by an
    AST walk, plus the raises that are not `raise Name(...)` (they cannot be classified)."""
    sites: set[Site] = set()
    unclassifiable: list[str] = []

    def walk(node: ast.AST, scope: list[str], file: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Raise):
                exc = child.exc
                if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                    sites.add((file, ".".join(scope), exc.func.id))
                else:
                    unclassifiable.append(f"{file}:{child.lineno} {ast.unparse(child)}")
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                walk(child, [*scope, child.name], file)
            else:
                walk(child, scope, file)

    for path in sorted((SRC / "application").glob("*.py")):
        walk(ast.parse(path.read_text("utf-8")), [], path.name)
    return sites, unclassifiable


def test_the_handler_raise_sites_are_exactly_the_ones_classified_here() -> None:
    sites, unclassifiable = raise_sites()

    assert not unclassifiable, f"a raise the population cannot classify: {unclassifiable}"
    assert sites - set(HANDLER_RAISE_SITES) == set(), (
        "a raise SITE under application/ is not in HANDLER_RAISE_SITES: classify its error "
        "against the operations whose handler runs it"
    )
    assert set(HANDLER_RAISE_SITES) - sites == set(), (
        "HANDLER_RAISE_SITES lists a raise site that no longer exists"
    )


async def test_every_route_of_the_app_has_a_request_in_the_population(harness: Any) -> None:
    assert operations_of(harness.app) == set(VALID_REQUESTS) | {STREAM}
    assert {op for op in operations_of(harness.app) if op not in PUBLIC_OPERATIONS} >= {STREAM}


async def test_every_operation_with_a_declared_parameter_or_body_has_an_invalid_request(
    harness: Any,
) -> None:
    generated = harness.app.openapi()
    constrained = {
        (method.upper(), path)
        for path, item in generated["paths"].items()
        for method, operation in item.items()
        if operation.get("parameters") or operation.get("requestBody")
    }
    assert constrained <= set(INVALID_REQUESTS) | {("GET", "/catalog/products")} | {
        ("GET", "/catalog/retailers"),
        ("GET", "/catalog/companies"),
    }, sorted(constrained - set(INVALID_REQUESTS))


async def test_the_status_population_against_openapi(harness: Any, asgi_stream: Any) -> None:
    observed = await observe(harness, asgi_stream)
    declared = declared_statuses()
    pairs = {(m, p, s) for (m, p, s) in observed}
    # SA-9: every operation carries `default`, so every observed pair IS declared (by name or by
    # `default`); what stays visible is the pairs answered ONLY through `default`
    # (undeclared BY NAME)
    assert operations_with_default() == set(declared), (
        "SA-9: an operation of openapi.yaml does not carry the `default` response"
    )
    assert sum(len(statuses) for statuses in declared.values()) == DECLARED_BY_NAME, (
        "the by-name declared statuses changed: re-derive the by-name-undeclared literals below"
    )
    undeclared = {(m, p, s) for (m, p, s) in pairs if s not in declared[(m, p)]}
    never_observed = {
        (m, p, s) for (m, p), statuses in declared.items() for s in statuses if s >= 400
    } - pairs

    print("\nOBSERVED (operation, status >= 400):", len(pairs))
    for key in sorted(pairs):
        mark = "UNDECLARED" if key in undeclared else "declared  "
        print(f"  {mark} {key[0]:4} {key[1]:24} {key[2]}  <- {sorted(observed[key])[:3]}")
    print("DECLARED >= 400 BUT NOT OBSERVED:", sorted(never_observed))
    print("UNDECLARED:", sorted(undeclared))

    # a pair whose every source is a responder-chosen `RpcError.code` is a PASS-THROUGH: the
    # Gateway maps it, but whether the owning context ever sends it for that subject is not decided
    # here (an upper bound); every other undeclared pair is produced by the Gateway's own code
    pass_through = {
        key for key in undeclared if all(src.startswith("rpc: rpc remote") for src in observed[key])
    }
    originated = undeclared - pass_through
    print("GATEWAY-ORIGINATED UNDECLARED:", len(originated), sorted(originated))
    print("PASS-THROUGH UNDECLARED:", len(pass_through), sorted(pass_through))

    # sentinels: pairs backlog 215's title named must be found, and a declared one must be found
    # and not reported as undeclared
    assert ("POST", "/orders", 404) in undeclared
    assert ("GET", "/orders", 503) in originated
    assert ("GET", "/orders/{id}", 400) in originated
    assert ("POST", "/orders/{id}/cancel", 400) in undeclared
    assert ("POST", "/orders/{id}/cancel", 502) not in pairs, (
        "SA-9: an unreadable reply is a 503 UPSTREAM_UNAVAILABLE, not a 502"
    )
    assert ("POST", "/orders/{id}/cancel", 503) in pairs - undeclared
    assert ("POST", "/orders", 409) in pairs - undeclared
    # and a pair must be found through the source that is supposed to produce it (a pair another
    # source also produces would otherwise survive the loss of the mapping under test)
    assert "read model: read model unavailable" in observed[("GET", "/orders", 503)]
    assert "rpc: rpc protocol" in observed[("POST", "/orders", 503)]
    assert "handler raises GatewayNotFoundError" in observed[("GET", "/orders/{id}", 404)]
    assert "rpc: rpc timeout" in observed[("POST", "/orders", 503)]
    assert "no runtime" in observed[("GET", "/orders/stream", 503)]
    assert originated == GATEWAY_ORIGINATED
    assert pass_through == PASS_THROUGH
