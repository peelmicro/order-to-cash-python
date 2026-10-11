"""Whether a send failure is permanent (RFC 5321 4.2.1: `5yz`) or transient (`4yz`, and anything
unrecognised). Ported from #7 `send-failure-classifier.ts` and #8 `SendFailureClassifier.cs`,
rebuilt on aiosmtplib's own types. The behaviour against a REAL server forced to answer 550 and 451
is `integration/test_notification_send_failure_real_smtp.py`."""

import pytest
from aiosmtplib import (
    SMTPConnectError,
    SMTPDataError,
    SMTPException,
    SMTPNotSupported,
    SMTPReadTimeoutError,
    SMTPRecipientRefused,
    SMTPRecipientsRefused,
    SMTPResponseException,
    SMTPSenderRefused,
    SMTPServerDisconnected,
)

from otc_notifications.infrastructure.notification.send_failure_classifier import (
    SendFailure,
    classify_send_failure,
)

PERMANENT = SendFailure.PERMANENT
TRANSIENT = SendFailure.TRANSIENT


@pytest.mark.parametrize("code", [500, 501, 530, 535, 550, 553, 554, 599])
def test_a_5yz_reply_is_permanent(code: int) -> None:
    assert classify_send_failure(SMTPResponseException(code, "refused")) is PERMANENT


@pytest.mark.parametrize("code", [400, 421, 450, 451, 452, 499, 600])
def test_a_4yz_reply_or_anything_outside_5yz_is_transient(code: int) -> None:
    assert classify_send_failure(SMTPResponseException(code, "try later")) is TRANSIENT


def test_every_reply_error_subclass_is_classified_by_its_code() -> None:
    assert classify_send_failure(SMTPSenderRefused(550, "no", "a@x.example")) is PERMANENT
    assert classify_send_failure(SMTPRecipientRefused(553, "no", "b@x.example")) is PERMANENT
    assert classify_send_failure(SMTPDataError(554, "no")) is PERMANENT
    assert classify_send_failure(SMTPSenderRefused(451, "later", "a@x.example")) is TRANSIENT
    assert classify_send_failure(SMTPDataError(451, "later")) is TRANSIENT


def test_authentication_required_is_permanent() -> None:
    """#8's second permanent case (`ServiceNotAuthenticatedException`): a server that REQUIRES
    authentication answers 530 to MAIL FROM, which aiosmtplib raises as a sender refusal."""
    assert (
        classify_send_failure(SMTPSenderRefused(530, "Authentication required", "a@x")) is PERMANENT
    )


def test_recipients_refused_is_permanent_only_when_every_refusal_is_5yz() -> None:
    def refused(*codes: int) -> SMTPRecipientsRefused:
        return SMTPRecipientsRefused(
            [SMTPRecipientRefused(code, "r", f"r{i}@x.example") for i, code in enumerate(codes)]
        )

    assert classify_send_failure(refused(550)) is PERMANENT
    assert classify_send_failure(refused(550, 553)) is PERMANENT
    assert classify_send_failure(refused(550, 450)) is TRANSIENT
    assert classify_send_failure(refused(451)) is TRANSIENT
    assert classify_send_failure(SMTPRecipientsRefused([])) is TRANSIENT


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError("nothing listens"),
        TimeoutError("slow"),
        SMTPServerDisconnected("dropped"),
        SMTPConnectError("cannot connect"),
        SMTPReadTimeoutError("no answer"),
        SMTPNotSupported("no STARTTLS"),
        SMTPException("generic"),
        RuntimeError("unrecognised"),
    ],
)
def test_a_failure_with_no_reply_code_is_transient_the_visible_default(
    error: BaseException,
) -> None:
    """Dead-lettering is visible and alertable; silently swallowing an unknown failure as permanent
    is not (#7's reasoning)."""
    assert classify_send_failure(error) is TRANSIENT
