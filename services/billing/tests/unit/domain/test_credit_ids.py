"""Every entry id and every fact `eventId` is the one the id source supplied (task B6; BC36).

Six sites: the hold entry, the approved fact, the rejected fact, the release entry, the released
fact and the consume entry. One assertion per site, each on its own line, so a site that mints its
own id (`UniqueId.new()`) fails at ITS assertion and nowhere else. #8 id 49 guarded one of four
sites; #9 feature 17 recurred it.

Loop scope: nothing here is async.
"""

from collections.abc import Callable, Sequence

from otc_billing.domain.buyer_credit import BuyerCredit, CreditContext, HoldRequest
from otc_billing.domain.credit_entry_type import CreditEntryType as T
from otc_billing.domain.events import CreditApproved, CreditRejected, CreditReleased
from otc_billing.domain.reasons import CreditRejectionReason, CreditReleaseReason
from otc_shared_kernel import UniqueId

ORDER = "ORD-000101"
OTHER = "ORD-000202"


def test_bc36_every_entry_id_and_event_id_is_the_one_the_id_source_supplied(
    uid: Callable[[int], UniqueId],
    id_source: Callable[[Sequence[UniqueId]], Callable[[], UniqueId]],
    build_credit: Callable[..., BuyerCredit],
    hold_request: Callable[..., HoldRequest],
    context: CreditContext,
) -> None:
    # sites 1 and 2: the hold entry, then the approved fact (one call, two ids, in this order)
    credit = build_credit(limit=1000)
    entry = credit.approve(hold_request(ORDER, 250), context, id_source([uid(0xA1), uid(0xA2)]))
    [approved] = credit.domain_events
    assert isinstance(approved, CreditApproved)
    assert entry.entry_id == uid(0xA1), "site 1: the hold entry id is not the supplied one"
    assert approved.event_id == uid(0xA2), (
        "site 2: the approved fact's event id is not the supplied one"
    )

    # site 3: the rejected fact (a refusal appends no entry, so exactly one id is asked for)
    credit = build_credit(limit=1000)
    credit.refuse(
        hold_request(ORDER, 2000),
        CreditRejectionReason.OVER_LIMIT,
        context,
        id_source([uid(0xA3)]),
    )
    [rejected] = credit.domain_events
    assert isinstance(rejected, CreditRejected)
    assert rejected.event_id == uid(0xA3), (
        "site 3: the rejected fact's event id is not the supplied one"
    )

    # sites 4 and 5: the release entry, then the released fact
    credit = build_credit(limit=1000, committed=300, entries=[(0x10, ORDER, 300, T.HOLD)])
    released_entry = credit.release(
        ORDER,
        CreditReleaseReason.ORDER_CANCELLED,
        uid(0xC0),
        context,
        id_source([uid(0xA4), uid(0xA5)]),
    )
    [released] = credit.domain_events
    assert released_entry is not None
    assert isinstance(released, CreditReleased)
    assert released_entry.entry_id == uid(0xA4), (
        "site 4: the release entry id is not the supplied one"
    )
    assert released.event_id == uid(0xA5), (
        "site 5: the released fact's event id is not the supplied one"
    )

    # site 6: the consume entry
    credit = build_credit(limit=1000, committed=300, entries=[(0x11, OTHER, 300, T.HOLD)])
    consumed = credit.consume(OTHER, context, id_source([uid(0xA6)]))
    assert consumed.entry_id == uid(0xA6), "site 6: the consume entry id is not the supplied one"
