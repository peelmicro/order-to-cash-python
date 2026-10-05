"""The shape of the dataset: counts and the invariants #8's `DatasetTests.cs` pinned.

R-map (feature_list.json id 12): acceptance 2 (same currencies, products, retailers, companies,
GLNs, credit limits and stock) and acceptance 3 (five completed orders and one cancelled order).

The counts are literals re-derived from #7's executed data (`seed_dataset_from_number7.json`), not
copied from a plan: 3 currencies, 12 products, 7 retailers, 22 companies, 154 credit lines (7
primary + 7 x 21 baseline), 215 stock rows, 6 sagas, 11 order items, 50 outbox rows (17 + 12 + 21).
"""

from otc_seed.domain.data.companies import COMPANIES
from otc_seed.domain.data.credits import CREDITS, PRIMARY_SUPPLIER_BY_RETAILER
from otc_seed.domain.data.currencies import CURRENCIES
from otc_seed.domain.data.products import PRODUCTS
from otc_seed.domain.data.retailers import RETAILERS
from otc_seed.domain.data.sagas import CANCELLED_SAGAS, COMPLETED_SAGAS, SAGAS
from otc_seed.domain.data.stock import STOCK
from otc_shared_kernel import GLN


def test_master_data_counts() -> None:
    assert len(CURRENCIES) == 3
    assert len(PRODUCTS) == 12
    assert len(RETAILERS) == 7
    assert len(COMPANIES) == 22
    assert len(CREDITS) == 154
    assert len(STOCK) == 215


def test_saga_counts_five_completed_one_cancelled() -> None:
    assert len(SAGAS) == 6
    assert len(COMPLETED_SAGAS) == 5
    assert len(CANCELLED_SAGAS) == 1
    assert sum(len(s.lines) for s in SAGAS) == 11
    assert sum(len(s.orders_outbox) for s in SAGAS) == 17
    assert sum(len(s.fulfillment_outbox) for s in SAGAS) == 12
    assert sum(len(s.billing_outbox) for s in SAGAS) == 21
    assert sum(len(s.reservations) for s in SAGAS) == 11
    assert sum(len(s.despatch.items) for s in SAGAS if s.despatch) == 10
    assert sum(len(s.invoice.items) for s in SAGAS if s.invoice) == 10
    assert sum(len(s.credit_ledger_entries) for s in SAGAS) == 15


def test_the_cancelled_saga_total_ends_in_point_ninety_nine() -> None:
    (saga,) = CANCELLED_SAGAS
    assert saga.total_amount == 24999
    assert saga.total_amount % 100 == 99
    assert saga.status == "cancelled"
    assert saga.cancellation_reason == "credit_rejected"


def test_every_retailer_has_a_credit_line_against_every_company() -> None:
    pairs = {(c.retailer_code, c.company_code) for c in CREDITS}
    assert pairs == {(r.code, c.code) for r in RETAILERS for c in COMPANIES}
    assert len(pairs) == len(CREDITS)  # one line per pair, no duplicate


def test_credit_references_are_sequential_with_the_primary_lines_first() -> None:
    assert [c.code for c in CREDITS] == [f"CR-{n:06d}" for n in range(1, 155)]
    for index, retailer in enumerate(RETAILERS):
        assert CREDITS[index].retailer_code == retailer.code
        assert CREDITS[index].company_code == PRIMARY_SUPPLIER_BY_RETAILER[retailer.code]


def test_credit_limits_are_int_minor_units_in_the_retailers_currency() -> None:
    currency_of = {r.code: r.currency_code for r in RETAILERS}
    for credit in CREDITS:
        assert type(credit.credit_limit) is int
        assert credit.credit_limit == 500_000
        assert credit.currency_code == currency_of[credit.retailer_code]


def test_every_seeded_gln_is_valid_and_unique_across_retailers_and_companies() -> None:
    glns = [r.gln for r in RETAILERS] + [c.gln for c in COMPANIES]
    for gln in glns:
        GLN(gln)
    assert len(set(glns)) == len(glns) == 29


def test_every_saga_reserved_pair_has_a_stock_row_and_no_row_is_negative() -> None:
    pairs = {(s.company_code, s.product_code) for s in STOCK}
    for saga in SAGAS:
        for reservation in saga.reservations:
            assert (reservation.company_code, reservation.product_code) in pairs
    assert all(s.units >= 0 and s.reserved_units == 0 for s in STOCK)
    assert len(pairs) == len(STOCK)


def test_every_company_outside_the_sagas_has_full_stock_coverage_per_product() -> None:
    covered = {s.company_code for saga in SAGAS for s in saga.reservations}
    for company in COMPANIES:
        if company.code in covered:
            continue
        rows = {s.product_code for s in STOCK if s.company_code == company.code}
        assert rows == {p.code for p in PRODUCTS}


def test_consumed_reservations_are_deducted_and_released_ones_are_not() -> None:
    by_pair = {(s.company_code, s.product_code): s.units for s in STOCK}
    assert by_pair[("IBERFOODS", "PRD-0002")] == 500 - 5  # consumed by order 1
    assert by_pair[("IBERFOODS", "PRD-0001")] == 500  # released by the cancelled order 6


def test_money_in_the_dataset_is_int_everywhere() -> None:
    for saga in SAGAS:
        for value in (saga.initial_amount, saga.initial_discount, saga.total_amount):
            assert type(value) is int
        for line in saga.lines:
            assert type(line.unit_price) is int
            assert type(line.line_discount) is int
    assert all(type(p.price) is int for p in PRODUCTS)
