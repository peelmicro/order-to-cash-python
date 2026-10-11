"""The SMTP adapter and the MIME builder, without a network (the real server is
`integration/test_notification_mailpit_inbox.py`): the shape of the message (a text and an HTML
alternative, the `Message-ID` and address headers, non-ASCII intact) and what reaches the transport.
"""

from email import message_from_bytes, policy
from typing import Any

from otc_notifications.application.ports.notification_sender import NotificationMessage
from otc_notifications.infrastructure.notification.mime import build_mime_message
from otc_notifications.infrastructure.notification.smtp_sender import SmtpNotificationSender
from otc_notifications.infrastructure.settings import SmtpSettings

MESSAGE = NotificationMessage(
    to="acme@retailer.order-to-cash.example",
    subject="[order-to-cash] Order ORD-000101 confirmed — ünïcode (correlationId: c)",
    text_body="Order confirmed — stock reserved.\nLine two",
    html_body="<p>Order confirmed — stock reserved.</p>",
    message_id="0000abcd-0000-4000-8000-00000000abcd@order-to-cash",
)


def parse(raw: bytes) -> Any:
    return message_from_bytes(raw, policy=policy.default)


def test_the_mime_message_carries_both_bodies_and_the_headers() -> None:
    mime = parse(build_mime_message(MESSAGE, "no-reply@order-to-cash.example").as_bytes())

    assert mime["From"] == "no-reply@order-to-cash.example"
    assert mime["To"] == "acme@retailer.order-to-cash.example"
    assert mime["Subject"] == MESSAGE.subject, "non-ASCII survives the header encoding"
    assert mime["Message-ID"] == "<0000abcd-0000-4000-8000-00000000abcd@order-to-cash>"
    assert mime.get_content_type() == "multipart/alternative"
    text, html = mime.get_payload()
    assert (text.get_content_type(), html.get_content_type()) == ("text/plain", "text/html")
    assert text.get_content().rstrip("\n") == MESSAGE.text_body
    assert html.get_content().rstrip("\n") == MESSAGE.html_body


def test_a_message_without_an_id_has_no_message_id_header_of_ours() -> None:
    bare = NotificationMessage("a@x.example", "s", "t", "<p>h</p>")
    assert "<" not in str(build_mime_message(bare, "f@x.example")["Message-ID"] or "")


async def test_the_sender_hands_the_transport_the_message_the_envelope_and_the_settings() -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def transport(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    settings = SmtpSettings.model_validate(
        {
            "NOTIFICATIONS_SENDER": "smtp",
            "SMTP_HOST": "smtp.sentinel",
            "SMTP_PORT": "2525",
            "SMTP_FROM_EMAIL": "from@sentinel.example",
            "SMTP_USER": "user-sentinel",
            "SMTP_PASSWORD": "password-sentinel",
            "SMTP_START_TLS": "true",
        }
    )
    await SmtpNotificationSender(settings, transport=transport).send(MESSAGE)

    [(args, kwargs)] = calls
    assert parse(args[0].as_bytes())["To"] == MESSAGE.to
    assert kwargs == {
        "sender": "from@sentinel.example",
        "recipients": [MESSAGE.to],
        "hostname": "smtp.sentinel",
        "port": 2525,
        "username": "user-sentinel",
        "password": "password-sentinel",
        "start_tls": True,
        "use_tls": False,
    }
