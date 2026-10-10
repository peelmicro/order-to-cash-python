"""The release transactional unit (`design.md` 6.3, 7.3; BC25).

The same lock protocol as the hold (one protocol, not two: the line row is needed anyway for `BC3`
and for `available_credit_after`). A release with nothing outstanding writes nothing, emits nothing
and answers `released=False`: a success, not an error.
"""

from collections.abc import Callable
from functools import partial

from otc_billing.application.errors import CreditLineNotFoundError
from otc_billing.application.messages import ReleaseCreditCommand, ReleaseResult
from otc_billing.application.ports.credit_store import CreditTransaction
from otc_billing.application.scope import BillingScope
from otc_billing.domain.buyer_credit import CreditContext
from otc_billing.domain.reasons import CreditReleaseReason
from otc_shared_kernel import UniqueId


async def _release_work(
    tx: CreditTransaction,
    *,
    command: ReleaseCreditCommand,
    context: CreditContext,
    new_id: Callable[[], UniqueId],
) -> ReleaseResult:
    credits = tx.credits
    credit = await credits.lock_for_order(
        command.retailer_code, command.company_code, command.order_reference
    )
    if credit is None:
        raise CreditLineNotFoundError(command.retailer_code, command.company_code)
    entry = credit.release(
        command.order_reference,
        CreditReleaseReason.ORDER_CANCELLED,
        command.correlation_id,
        context,
        new_id,
    )
    if entry is None:
        return ReleaseResult(
            released=False,
            order_reference=command.order_reference,
            credit_code=credit.code,
            currency=credit.currency,
            released_amount=None,
            available_credit_after=credit.available_credit.amount,
        )
    await credits.save(credit)
    return ReleaseResult(
        released=True,
        order_reference=command.order_reference,
        credit_code=credit.code,
        currency=credit.currency,
        released_amount=entry.amount.amount,
        available_credit_after=credit.available_credit.amount,
    )


async def release(command: ReleaseCreditCommand, scope: BillingScope) -> ReleaseResult:
    work = partial(
        _release_work,
        command=command,
        context=CreditContext(occurred_at=scope.clock.now(), causation_id=command.request_id),
        new_id=scope.ids.new,
    )
    return await scope.transactions.run(work)
