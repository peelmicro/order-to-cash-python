"""Whether a send failure is worth retrying.

RFC 5321 section 4.2.1 is the rule: a `5yz` reply is a Permanent Negative Completion, a `4yz`
reply is Transient. #7 applied it to nodemailer's `responseCode` (`send-failure-classifier.ts`) and
#8 to MailKit's `SmtpCommandException.StatusCode`; here it is aiosmtplib's
`SMTPResponseException.code` (every server-reply error subclasses it: sender refused, data
refused, authentication refused, connect response) and `SMTPRecipientsRefused`, which carries one
reply per refused recipient and is permanent only when EVERY recipient was refused with a `5yz`.

Anything else (a refused or dropped connection, a timeout, an unrecognised exception) defaults to
`TRANSIENT`, #7's reasoning: dead-lettering is visible (a row on a `.dlq` topic, alertable),
silently swallowing an unknown failure as permanent is not.
"""

import enum

from aiosmtplib import SMTPRecipientsRefused, SMTPResponseException


class SendFailure(enum.Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"


def _is_permanent_code(code: int) -> bool:
    return 500 <= code < 600


def classify_send_failure(error: BaseException) -> SendFailure:
    if isinstance(error, SMTPResponseException) and _is_permanent_code(error.code):
        return SendFailure.PERMANENT
    if (
        isinstance(error, SMTPRecipientsRefused)
        and error.recipients
        and all(_is_permanent_code(refusal.code) for refusal in error.recipients)
    ):
        return SendFailure.PERMANENT
    return SendFailure.TRANSIENT
