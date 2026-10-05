"""The derivation helpers reproduce #7 (and #8) exactly: literal expected values, no re-derivation.

Provenance of every literal: executed from #7's own `apps/seed/src/deterministic.ts` over the
namespaces and sequences below (`order-to-cash-nestjs/apps/seed`, run with its `tsx`), and
identical to the values #8's `DeterministicParityTests.cs` pins. A value produced by running THIS
port and copying its output would prove only that the port agrees with itself.

R-map (feature_list.json id 12, acceptance 1): deterministic ids by SHA-256 of `otc-seed:` + ns,
reproducing #7's skipped hex index 12.
"""

import hashlib

import pytest

from otc_seed.domain.data.currencies import CURRENCIES
from otc_seed.domain.data.retailers import RETAILERS
from otc_seed.domain.data.sagas import SAGAS
from otc_seed.domain.deterministic import deterministic_id, make_ean13, make_gln
from otc_shared_kernel import GLN, UniqueId

ID_VECTORS = [
    ("currency:USD", "8a2ac568-0944-4507-872a-38acbce9724c"),
    ("currency:EUR", "23ab1a2b-bce4-4b83-8304-6b5a1084990c"),
    ("currency:GBP", "ac45711f-e2ac-456b-975f-8aef85070564"),
    ("retailer:CarrefourEs", "0e47f181-c92e-416a-bff1-5c8d497768b1"),
    ("order:1", "1741d5aa-cfba-4205-a1c0-82e7a5cb8984"),
    ("product:PRD-0001", "1164d610-b1d9-493c-980e-1b4a37d00e1e"),
    ("stock:IBERFOODS:PRD-0002", "9ad0863b-e61e-4e1d-9488-c60850b82779"),
    ("order:6:event:order.cancelled.v1", "fa91097d-adb4-49ec-8bc2-1a4c4acc52cb"),
]
GLN_VECTORS = [
    (1, "5400000000010"),
    (2, "5400000000027"),
    (3, "5400000000034"),
    (4, "5400000000041"),
    (5, "5400000000058"),
    (6, "5400000000065"),
    (7, "5400000000072"),
    (21, "5400000000218"),
    (42, "5400000000423"),
]
EAN_VECTORS = [
    (1, "5901000000012"),
    (2, "5901000000029"),
    (12, "5901000000128"),
    (999999, "5901009999997"),
]


@pytest.mark.parametrize(("namespace", "expected"), ID_VECTORS)
def test_deterministic_id_matches_the_value_7s_typescript_produced(
    namespace: str, expected: str
) -> None:
    assert deterministic_id(namespace) == expected


def test_deterministic_id_is_stable_and_distinguishes_namespaces() -> None:
    assert deterministic_id("order:42") == deterministic_id("order:42")
    assert deterministic_id("order:42") != deterministic_id("order:43")


def test_every_derived_id_is_a_lowercase_version_4_variant_1_uuid() -> None:
    for namespace, _ in ID_VECTORS:
        value = deterministic_id(namespace)
        assert value == value.lower()
        assert value[14] == "4"  # version nibble
        assert value[19] in "89ab"  # variant nibble
        assert str(UniqueId.parse(value)) == value  # the shared kernel accepts the shape


def test_the_skipped_hex_character_is_load_bearing() -> None:
    """Reconstruct the 'tidied' derivation (`hex[12:15]`) locally: it gives `...-4250-...`, not the
    `...-4507-...` of #7. If someone 'fixes' the wart in production code, every id of the dataset
    changes and this test names the claim."""
    digest = hashlib.sha256(b"otc-seed:currency:USD").hexdigest()
    tidied = (
        f"{digest[0:8]}-{digest[8:12]}-4{digest[12:15]}-"
        f"{(int(digest[16], 16) & 0x3) | 0x8:x}{digest[17:20]}-{digest[20:32]}"
    )
    assert tidied == "8a2ac568-0944-4250-872a-38acbce9724c"
    assert deterministic_id("currency:USD") != tidied
    assert deterministic_id("currency:USD") == "8a2ac568-0944-4507-872a-38acbce9724c"


def test_the_datasets_own_ids_match_the_value_7_produced() -> None:
    """Ties the PRODUCTION dataset to the oracle, not just the helper called with a typed string:
    a broken namespace literal inside the data modules would slip past the vectors above."""
    assert next(c.id for c in CURRENCIES if c.code == "USD") == (
        "8a2ac568-0944-4507-872a-38acbce9724c"
    )
    assert next(r.id for r in RETAILERS if r.code == "CarrefourEs") == (
        "0e47f181-c92e-416a-bff1-5c8d497768b1"
    )
    assert next(s.order_id for s in SAGAS if s.sequence == 1) == (
        "1741d5aa-cfba-4205-a1c0-82e7a5cb8984"
    )


@pytest.mark.parametrize(("sequence", "expected"), GLN_VECTORS)
def test_make_gln_matches_the_value_7_produced(sequence: int, expected: str) -> None:
    assert make_gln(sequence) == expected
    GLN(expected)  # and the shared kernel validates it: a genuine check digit


@pytest.mark.parametrize(("sequence", "expected"), EAN_VECTORS)
def test_make_ean13_matches_the_value_7_produced(sequence: int, expected: str) -> None:
    assert make_ean13(sequence) == expected


def test_a_gln_with_a_wrong_check_digit_is_refused_by_the_shared_kernel() -> None:
    """The check digit is genuine, not decorative: the neighbouring digit is a different GLN that
    the shared kernel refuses (a mutation of `make_gln`'s digit cannot pass the vectors above)."""
    from otc_shared_kernel import InvalidGlnError

    with pytest.raises(InvalidGlnError):
        GLN("5400000000011")


@pytest.mark.parametrize("bad", [-1, 1_000_000_000, True, 1.0])
def test_make_gln_refuses_a_sequence_outside_its_range(bad: object) -> None:
    with pytest.raises(ValueError, match="out of range"):
        make_gln(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [-1, 1_000_000, True])
def test_make_ean13_refuses_a_sequence_outside_its_range(bad: object) -> None:
    with pytest.raises(ValueError, match="out of range"):
        make_ean13(bad)  # type: ignore[arg-type]
