"""Acceptance item 1: the document FastAPI generates from the Gateway's routes is compared with the
committed `specs/shared/openapi.yaml`, in BOTH directions.

What "compares" means, decided here (the previous builds' equivalents compared the SET of
operations and nothing else: #7 `apps/gateway/src/contract-drift.integration.spec.ts:62-82`, #8
`tests/Gateway.UnitTests/OpenApiContractTests.cs:42-60`; a route could answer the wrong statuses or
take the wrong parameters and both stayed green). Per operation, `compare` checks:

1. the set of (method, path) pairs, both directions: declared but not mapped, mapped but not
   declared (feature 26 mapped `GET /orders/stream`: the exclusion set is empty, asserted so);
2. `operationId` and `tags`;
3. the set of response status codes, `default` included (SA-9: every operation carries it);
4. for each (status, media type): the media type and the SHAPE of its schema, which is the sorted
   property names of an object (a `$ref` followed, an `allOf` merged), or the shape of an array's
   items, or the scalar type; and the schema's component NAME when both documents use a `$ref`;
5. the set of (name, in, required) parameters, path-item level and operation level merged;
6. the request body: whether it is required, its media types and their schema shape.

Not compared, and said so: response HEADERS (`Location`, `Retry-After`, `X-Correlation-Id`,
`Idempotent-Replay` are set in the handlers and proved by the route tests), `description`s,
`examples`, the nullability of a property (the generated models ARE the contract: the repository
regenerates them from this YAML and fails `quality.sh` when they drift), and security (the public
set is a literal checked against `security: []` in `test_gateway_auth_sweep.py`).

Every clause is armed below on a mutated copy of the generated document: delete an operation, add
one, drop a status, swap a media type, change a schema, change a parameter, drop a body.
"""

import copy
from pathlib import Path
from typing import Any

import yaml

from otc_gateway.presentation.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[4]
EXCLUDED: set[tuple[str, str]] = set()  # feature 26 mapped the stream: nothing is excluded now
METHODS = ("get", "post", "put", "delete", "patch")


def committed() -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(
        (REPO_ROOT / "specs/shared/openapi.yaml").read_text(encoding="utf-8")
    )
    return document


def resolve(node: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        target: Any = doc
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        node = target
    return node


def ref_name(node: dict[str, Any]) -> str | None:
    reference = node.get("$ref")
    return None if reference is None else str(reference).rsplit("/", 1)[-1]


def shape(schema: dict[str, Any], doc: dict[str, Any]) -> Any:
    resolved = resolve(schema, doc)
    alternatives = [
        member
        for member in resolved.get("anyOf", resolved.get("oneOf", []))
        if member.get("type") != "null"
    ]
    if len(alternatives) == 1:  # `X | None`: the shape of X
        return shape(alternatives[0], doc)
    properties: set[str] = set(resolved.get("properties", {}))
    for member in resolved.get("allOf", []):
        properties |= set(resolve(member, doc).get("properties", {}))
    if properties:
        return ("object", sorted(properties))
    if resolved.get("type") == "array":
        return ("array", shape(resolved["items"], doc))
    return ("scalar", resolved.get("type"))


def operations(doc: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for path, item in doc["paths"].items():
        for method in METHODS:
            if method in item:
                operation = dict(item[method])
                operation["parameters"] = [
                    *item.get("parameters", []),
                    *operation.get("parameters", []),
                ]
                found[(method.upper(), path)] = operation
    return found


def parameter_set(operation: dict[str, Any], doc: dict[str, Any]) -> set[tuple[str, str, bool]]:
    resolved = [resolve(p, doc) for p in operation["parameters"]]
    return {(p["name"], p["in"], bool(p.get("required", False))) for p in resolved}


def responses_of(operation: dict[str, Any], doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(s): resolve(r, doc) for s, r in operation["responses"].items()}


def compare(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    differences: list[str] = []
    want = {k: v for k, v in operations(expected).items() if k not in EXCLUDED}
    have = operations(actual)
    for missing in sorted(set(want) - set(have)):
        differences.append(f"declared in openapi.yaml but NOT mapped: {missing[0]} {missing[1]}")
    for extra in sorted(set(have) - set(want)):
        differences.append(f"mapped but NOT declared in openapi.yaml: {extra[0]} {extra[1]}")
    for key in sorted(set(want) & set(have)):
        label = f"{key[0]} {key[1]}"
        exp, act = want[key], have[key]
        if exp.get("operationId") != act.get("operationId"):
            differences.append(
                f"{label}: operationId {act.get('operationId')} != {exp.get('operationId')}"
            )
        if sorted(exp.get("tags", [])) != sorted(act.get("tags", [])):
            differences.append(f"{label}: tags {act.get('tags')} != {exp.get('tags')}")
        exp_responses, act_responses = responses_of(exp, expected), responses_of(act, actual)
        if set(exp_responses) != set(act_responses):
            differences.append(
                f"{label}: statuses {sorted(act_responses)} != {sorted(exp_responses)}"
            )
        for status in sorted(set(exp_responses) & set(act_responses)):
            exp_content = exp_responses[status].get("content", {})
            act_content = act_responses[status].get("content", {})
            if set(exp_content) != set(act_content):
                differences.append(
                    f"{label} {status}: media types {sorted(act_content)} != {sorted(exp_content)}"
                )
            for media in sorted(set(exp_content) & set(act_content)):
                differences += compare_schema(
                    f"{label} {status} {media}",
                    exp_content[media].get("schema", {}),
                    act_content[media].get("schema", {}),
                    expected,
                    actual,
                )
        if parameter_set(exp, expected) != parameter_set(act, actual):
            differences.append(
                f"{label}: parameters {sorted(parameter_set(act, actual))} "
                f"!= {sorted(parameter_set(exp, expected))}"
            )
        exp_body, act_body = exp.get("requestBody"), act.get("requestBody")
        if (exp_body is None) != (act_body is None):
            differences.append(
                f"{label}: requestBody present={act_body is not None}, "
                f"declared={exp_body is not None}"
            )
        elif exp_body is not None and act_body is not None:
            exp_body, act_body = resolve(exp_body, expected), resolve(act_body, actual)
            if bool(exp_body.get("required", False)) != bool(act_body.get("required", False)):
                differences.append(f"{label}: requestBody.required differs")
            if set(exp_body["content"]) != set(act_body["content"]):
                differences.append(f"{label}: requestBody media types differ")
            for media in set(exp_body["content"]) & set(act_body["content"]):
                differences += compare_schema(
                    f"{label} requestBody {media}",
                    exp_body["content"][media].get("schema", {}),
                    act_body["content"][media].get("schema", {}),
                    expected,
                    actual,
                )
    return differences


def compare_schema(
    label: str,
    exp: dict[str, Any],
    act: dict[str, Any],
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[str]:
    found: list[str] = []
    if shape(exp, expected) != shape(act, actual):
        found.append(f"{label}: schema {shape(act, actual)} != {shape(exp, expected)}")
    if ref_name(exp) is not None and ref_name(act) is not None and ref_name(exp) != ref_name(act):
        found.append(f"{label}: schema name {ref_name(act)} != {ref_name(exp)}")
    return found


def generated() -> dict[str, Any]:
    return create_app().openapi()


# ------------------------------------------------------------------------------ the real claim


def test_the_generated_document_matches_the_committed_openapi_yaml_in_both_directions() -> None:
    assert compare(committed(), generated()) == []


def test_the_population_is_everything_the_contract_declares_the_stream_included() -> None:
    declared = set(operations(committed()))
    mapped = set(operations(generated()))

    assert (
        len(declared) == 18
    )  # #7's count, `contract-drift.integration.spec.ts:7-12`: 18 operations
    assert set() == EXCLUDED, "an exclusion would hide a declared operation from the comparison"
    assert ("GET", "/orders/stream") in mapped, "feature 26's stream is not mapped"
    assert mapped == declared
    assert len(mapped) == 18


# ------------------------------------------------------- armed: each clause must be able to fail


def mutated(change: Any) -> list[str]:
    actual = copy.deepcopy(generated())
    change(actual)
    return compare(committed(), actual)


def test_arm_a_declared_operation_that_is_not_mapped_is_reported() -> None:
    def drop(actual: dict[str, Any]) -> None:
        del actual["paths"]["/orders/{id}"]["get"]

    assert "declared in openapi.yaml but NOT mapped: GET /orders/{id}" in mutated(drop)


def test_arm_a_mapped_operation_that_is_not_declared_is_reported() -> None:
    def add(actual: dict[str, Any]) -> None:
        actual["paths"]["/debug"] = {"get": {"responses": {"200": {"description": "x"}}}}

    assert "mapped but NOT declared in openapi.yaml: GET /debug" in mutated(add)


def test_arm_a_method_the_contract_does_not_declare_on_a_declared_path_is_reported() -> None:
    def add(actual: dict[str, Any]) -> None:
        actual["paths"]["/stock"]["delete"] = {"responses": {"200": {"description": "x"}}}

    assert "mapped but NOT declared in openapi.yaml: DELETE /stock" in mutated(add)


def test_arm_a_status_the_route_stopped_declaring_is_reported() -> None:
    def drop(actual: dict[str, Any]) -> None:
        del actual["paths"]["/orders"]["post"]["responses"]["409"]

    found = mutated(drop)
    assert any(d.startswith("POST /orders: statuses") for d in found), found


def test_arm_a_route_that_stopped_declaring_default_is_reported() -> None:
    def drop(actual: dict[str, Any]) -> None:
        del actual["paths"]["/credits"]["get"]["responses"]["default"]

    found = mutated(drop)
    assert any(d.startswith("GET /credits: statuses") and "'default'" in d for d in found), found


def test_every_generated_operation_declares_default_as_a_problem_document() -> None:
    document = generated()
    for (method, path), operation in operations(document).items():
        default = operation["responses"].get("default")
        assert default is not None, f"SA-9: {method} {path} does not declare `default`"
        assert list(default["content"]) == ["application/problem+json"], (method, path)


def test_arm_a_media_type_swap_is_reported() -> None:
    def swap(actual: dict[str, Any]) -> None:
        content = actual["paths"]["/orders/{id}"]["get"]["responses"]["404"]["content"]
        content["application/json"] = content.pop("application/problem+json")

    found = mutated(swap)
    assert any(d.startswith("GET /orders/{id} 404: media types") for d in found), found


def test_arm_a_response_schema_of_another_shape_is_reported() -> None:
    def swap(actual: dict[str, Any]) -> None:
        responses = actual["paths"]["/credits"]["get"]["responses"]["200"]["content"]
        responses["application/json"]["schema"] = {"$ref": "#/components/schemas/StockPage"}

    found = mutated(swap)
    assert any(d.startswith("GET /credits 200 application/json: schema") for d in found), found


def test_arm_a_parameter_the_route_dropped_or_made_required_is_reported() -> None:
    def drop(actual: dict[str, Any]) -> None:
        actual["paths"]["/invoices"]["get"]["parameters"].pop()

    def require(actual: dict[str, Any]) -> None:
        actual["paths"]["/invoices"]["get"]["parameters"][0]["required"] = True

    assert any(d.startswith("GET /invoices: parameters") for d in mutated(drop))
    assert any(d.startswith("GET /invoices: parameters") for d in mutated(require))


def test_arm_a_request_body_the_route_stopped_declaring_is_reported() -> None:
    def drop(actual: dict[str, Any]) -> None:
        del actual["paths"]["/stock/replenish"]["post"]["requestBody"]

    found = mutated(drop)
    assert any("POST /stock/replenish: requestBody present=False" in d for d in found), found


def test_arm_an_operation_id_that_differs_is_reported() -> None:
    def rename(actual: dict[str, Any]) -> None:
        actual["paths"]["/auth/login"]["post"]["operationId"] = "signIn"

    assert any(d.startswith("POST /auth/login: operationId signIn") for d in mutated(rename))


def test_arm_the_stream_losing_its_media_type_or_resume_header_is_reported() -> None:
    def swap(actual: dict[str, Any]) -> None:
        content = actual["paths"]["/orders/stream"]["get"]["responses"]["200"]["content"]
        content["application/json"] = content.pop("text/event-stream")

    def drop_header(actual: dict[str, Any]) -> None:
        parameters = actual["paths"]["/orders/stream"]["get"]["parameters"]
        parameters[:] = [p for p in parameters if p["name"] != "Last-Event-ID"]

    assert any(d.startswith("GET /orders/stream 200: media types") for d in mutated(swap))
    assert any(d.startswith("GET /orders/stream: parameters") for d in mutated(drop_header))


def test_the_comparison_can_say_yes_a_copy_of_the_committed_operations_compares_equal() -> None:
    assert compare(committed(), copy.deepcopy(committed())) == []
