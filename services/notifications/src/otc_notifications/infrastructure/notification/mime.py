"""`build_mime_message`: a provider-neutral `NotificationMessage` as an RFC 5322 message.

Pure (no I/O), split out of the SMTP adapter so the MIME shape (a text and an HTML alternative,
the `Message-ID` header) is unit-testable without a network call.
"""

from email.message import EmailMessage

from otc_notifications.application.ports.notification_sender import NotificationMessage


def build_mime_message(message: NotificationMessage, from_address: str) -> EmailMessage:
    mime = EmailMessage()
    mime["From"] = from_address
    mime["To"] = message.to
    mime["Subject"] = message.subject
    if message.message_id:
        mime["Message-ID"] = f"<{message.message_id}>"
    mime.set_content(message.text_body)
    mime.add_alternative(message.html_body, subtype="html")
    return mime
