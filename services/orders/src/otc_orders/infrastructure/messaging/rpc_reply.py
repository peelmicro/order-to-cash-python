"""The shared first step of decoding an RPC reply: JSON, then "is it an `RpcError`?" (#8 id 46).

Moved out of the stock-check client (feature 15) so both NATS clients of this service tell an error
reply from a success reply the same way, BEFORE any typed decoding: the body is parsed as JSON and
an object with a string `code` is the responder's own error. What each client does next differs on
purpose (the stock check keeps the code as the responder sent it; the saga adapter validates it
against the generated `RpcError` and fails open to the retryable side on an unknown code), so this
module classifies and nothing more.
"""

import json
from dataclasses import dataclass
from typing import Any


class ReplyNotJsonError(ValueError):
    """The reply body is not JSON (`JSONDecodeError` and `UnicodeDecodeError` are both
    ValueErrors)."""


@dataclass(frozen=True, slots=True)
class RpcErrorBody:
    code: str
    message: str  # "" when the responder sent no string message


@dataclass(frozen=True, slots=True)
class ParsedReply:
    document: Any  # whatever JSON the body held: not yet known to be an object
    error: RpcErrorBody | None  # set when the document is an object with a string `code`


def parse_reply(body: bytes) -> ParsedReply:
    try:
        document: Any = json.loads(body)
    except ValueError as defect:
        raise ReplyNotJsonError(str(defect)) from None
    if isinstance(document, dict) and isinstance(document.get("code"), str):
        message = document.get("message")
        return ParsedReply(
            document, RpcErrorBody(document["code"], message if isinstance(message, str) else "")
        )
    return ParsedReply(document, None)
