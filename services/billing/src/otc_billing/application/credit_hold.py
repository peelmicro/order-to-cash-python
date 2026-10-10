"""The hold transactional unit (`design.md` 6.2, 7.3): a plain function over ports.

`work` receives the transaction and its own arguments (bound with `functools.partial`) and nothing
else. A business rejection is a RESULT, never a raise (saga.md 7, SO6); a contract violation (no
line, a currency mismatch) raises and rolls back, writing nothing. The reply is built from the
result only after `run()` returns, i.e. after the commit.

The credit-decision port is consulted ONLY for a hold the aggregate found fitting (BC13), inside
the line's row lock; `decide` is synchronous, so nothing can be awaited under the lock.
"""

from collections.abc import Callable
from functools import partial

from otc_billing.application.errors import CreditCurrencyMismatchError, CreditLineNotFoundError
from otc_billing.application.messages import HoldCreditCommand, HoldOutcomeKind, HoldResult
from otc_billing.application.ports.credit_decision import (
    Approve,
    CreditDecisionPort,
    CreditDecisionRequest,
    Refuse,
)
from otc_billing.application.ports.credit_store import CreditTransaction
from otc_billing.application.scope import BillingScope
from otc_billing.domain.buyer_credit import (
    AlreadyHeld,
    CreditContext,
    CurrencyMismatch,
    Fits,
    HoldRequest,
    OverLimit,
)
from otc_billing.domain.reasons import CreditRejectionReason, to_rejection_reason
from otc_shared_kernel import UniqueId


async def _hold_work(
    tx: CreditTransaction,
    *,
    command: HoldCreditCommand,
    context: CreditContext,
    new_id: Callable[[], UniqueId],
    credit_decision: CreditDecisionPort,
) -> HoldResult:
    credits = tx.credits
    credit = await credits.lock_for_order(
        command.retailer_code, command.company_code, command.order_reference
    )
    if credit is None:
        raise CreditLineNotFoundError(command.retailer_code, command.company_code)
    request = HoldRequest(
        order_reference=command.order_reference,
        amount=command.amount,
        correlation_id=command.correlation_id,
    )
    evaluation = credit.evaluate_hold(request)
    match evaluation:
        case AlreadyHeld():
            # BC7: whatever the order's net exposure is now; nothing is written, no port is asked
            return HoldResult(
                outcome=HoldOutcomeKind.ALREADY_HELD,
                order_reference=command.order_reference,
                credit_code=credit.code,
                currency=credit.currency,
                held_amount=evaluation.held_amount.amount,
                available_credit=credit.available_credit.amount,
                reason=None,
            )
        case CurrencyMismatch():
            raise CreditCurrencyMismatchError(evaluation.expected, evaluation.received)
        case OverLimit():
            reason = CreditRejectionReason.OVER_LIMIT
        case Fits():
            decision = credit_decision.decide(
                CreditDecisionRequest(
                    order_reference=command.order_reference,
                    retailer_code=credit.retailer_code,
                    company_code=credit.company_code,
                    credit_code=credit.code,
                    amount=command.amount,
                    available_credit=credit.available_credit,
                )
            )
            match decision:
                case Approve():
                    credit.approve(request, context, new_id)
                    await credits.save(credit)
                    return HoldResult(
                        outcome=HoldOutcomeKind.APPROVED,
                        order_reference=command.order_reference,
                        credit_code=credit.code,
                        currency=credit.currency,
                        held_amount=command.amount.amount,
                        available_credit=credit.available_credit.amount,
                        reason=None,
                    )
                case Refuse():
                    reason = to_rejection_reason(decision.reason)
    credit.refuse(request, reason, context, new_id)
    await credits.save(credit)
    return HoldResult(
        outcome=HoldOutcomeKind.REJECTED,
        order_reference=command.order_reference,
        credit_code=credit.code,
        currency=credit.currency,
        held_amount=None,
        available_credit=credit.available_credit.amount,
        reason=reason,
    )


async def hold(command: HoldCreditCommand, scope: BillingScope) -> HoldResult:
    work = partial(
        _hold_work,
        command=command,
        context=CreditContext(occurred_at=scope.clock.now(), causation_id=command.request_id),
        new_id=scope.ids.new,
        credit_decision=scope.credit_decision,
    )
    return await scope.transactions.run(work)
