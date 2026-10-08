"""FS19 / L3 / L4 (E3): the lock order is the distinct keys in code-point order, exact equality."""

import itertools

from otc_fulfillment.application.ports.stock_store import distinct_stock_keys

KEYS = [("ACME-CO", "PRD-C3"), ("ACME-CO", "PRD-A1"), ("ACME-CO", "PRD-B2")]
SORTED = (("ACME-CO", "PRD-A1"), ("ACME-CO", "PRD-B2"), ("ACME-CO", "PRD-C3"))


def test_fs19_orders_distinct_stock_keys_by_code_point_independently_of_request_order() -> None:
    orders = {distinct_stock_keys(permutation) for permutation in itertools.permutations(KEYS)}

    assert orders == {SORTED}, "every request order of the same set locks in ONE order"
    # duplicates collapse
    assert distinct_stock_keys([*KEYS, KEYS[1], KEYS[0]]) == SORTED
    # the company is part of the key and sorts first
    assert distinct_stock_keys([("ZZ-CO", "PRD-A1"), ("AA-CO", "PRD-Z9")]) == (
        ("AA-CO", "PRD-Z9"),
        ("ZZ-CO", "PRD-A1"),
    )
    # code-point order, not locale order: upper case sorts before lower case
    assert distinct_stock_keys([("C", "prd-a1"), ("C", "PRD-Z9")]) == (
        ("C", "PRD-Z9"),
        ("C", "prd-a1"),
    )


def test_codes_differing_only_in_letter_case_are_two_keys() -> None:
    keys = distinct_stock_keys([("ACME-CO", "PRD-A1"), ("ACME-CO", "prd-a1")])

    assert keys == (("ACME-CO", "PRD-A1"), ("ACME-CO", "prd-a1"))
    assert len(keys) == 2
