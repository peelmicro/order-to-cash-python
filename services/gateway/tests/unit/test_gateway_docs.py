"""`GET /docs` (`openapi.yaml:896-911`): an unauthenticated, human-facing `text/html` rendering of
the COMMITTED contract, not of FastAPI's generated one.

Decided, with the previous builds' equivalents: #7 renders the parsed committed file with
swagger-ui-express (`apps/gateway/src/presentation/setup-docs.ts:15-21`), which needs a script
bundle; #8 wraps the committed file's escaped text in a `<pre>` (`DocsEndpoints.cs:26-47`). #9 does
what #8 does: a page that needs no script and no network resource, whose body is the committed file
VERBATIM (so a reviewer reads the contract the repository holds), HTML-escaped. The discriminators
below are text only the committed document has: the stream (`/orders/stream`, feature 26's, which is
not mapped yet) and `x-sse-events`.
"""

import html
import re
from pathlib import Path
from typing import Any

COMMITTED = (Path(__file__).resolve().parents[4] / "specs/shared/openapi.yaml").read_text("utf-8")


async def test_docs_is_an_anonymous_text_html_page(harness: Any) -> None:
    response = await harness.client.get("/docs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.startswith("<!DOCTYPE html>")


async def test_docs_renders_the_committed_contract_verbatim_not_the_generated_one(
    harness: Any,
) -> None:
    body = (await harness.client.get("/docs")).text

    match = re.search(r"<pre>(.*)</pre>", body, re.DOTALL)
    assert match is not None
    assert html.unescape(match.group(1)) == COMMITTED
    # text that only the committed document holds (feature 26 mapped the stream, so the generated
    # document has `/orders/stream` too; it has no `x-sse-events`, which only the committed one has)
    assert "x-sse-events" in body
    assert "x-sse-events" not in str(harness.app.openapi())  # and not the generated one


async def test_docs_escapes_the_contract_text_so_it_is_never_markup(harness: Any) -> None:
    harness.runtime = harness.runtime.__class__(
        **{
            **{f: getattr(harness.runtime, f) for f in harness.runtime.__slots__},
            "openapi_document": "<script>alert(1)</script> & more",
        }
    )
    harness.app.state.runtime = harness.runtime

    body = (await harness.client.get("/docs")).text

    assert "<script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; more" in body


async def test_docs_needs_no_script_and_no_network_resource(harness: Any) -> None:
    body = (await harness.client.get("/docs")).text

    assert "<script" not in body.lower()
    head = body.split("<pre>")[0]
    assert "http://" not in head
    assert "https://" not in head
