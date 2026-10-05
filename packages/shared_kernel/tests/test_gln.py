"""R4: a GLN is 13 ASCII digits whose last digit is the GS1 mod-10 check digit."""

import math
from typing import Any

import pytest

from otc_shared_kernel import GLN, DomainError, InvalidGlnError

# Real, independently sourced vectors, each a (12-digit body, expected check digit) pair written
# out as literals. `4006381333931` is the EAN-13/GS1 worked example; `1234567890128` is worked by
# hand below; the others are recomputed by `oracle_check_digit`, which is a DIFFERENT formulation
# from the implementation (weights counted from the LEFT, no `reversed`, no `% 2 == 0` on the
# distance) and is itself pinned to the hand-worked values.
REAL_GLNS = [
    "4006381333931",
    "4890123456787",
    "9520012345605",
    "1234567890128",
    "9501101530003",
    "0614141000036",
    "7350053850019",
]
ZERO_GLN = "0000000000000"  # valid under ANY weighting: never evidence of the weights


def oracle_check_digit(body: str) -> int:
    # Left-to-right: the 12th (last) body digit has weight 3, so odd 0-based indexes carry 3.
    total = 0
    for index, character in enumerate(body):
        total += int(character) * (3 if index % 2 == 1 else 1)
    return -total % 10


def swapped_weights_check_digit(body: str) -> int:
    total = 0
    for index, character in enumerate(body):
        total += int(character) * (1 if index % 2 == 1 else 3)
    return -total % 10


def test_the_oracle_matches_the_hand_worked_vectors() -> None:
    # Hand work for 123456789012, digits from the right with weights 3,1,3,1,...:
    # 2*3 + 1*1 + 0*3 + 9*1 + 8*3 + 7*1 + 6*3 + 5*1 + 4*3 + 3*1 + 2*3 + 1*1
    #   = 6 + 1 + 0 + 9 + 24 + 7 + 18 + 5 + 12 + 3 + 6 + 1 = 92, and (10 - 92 mod 10) mod 10 = 8.
    assert oracle_check_digit("123456789012") == 8
    assert oracle_check_digit("400638133393") == 1
    assert oracle_check_digit("000000000000") == 0


@pytest.mark.parametrize("value", [*REAL_GLNS, ZERO_GLN])
def test_r4_gln_accepts_a_real_valid_gln(value: str) -> None:
    assert oracle_check_digit(value[:12]) == int(value[12]), "the vector is not actually valid"
    assert GLN(value).value == value
    assert str(GLN(value)) == value
    assert GLN.compute_check_digit(value[:12]) == int(value[12])


def test_r4_the_real_vectors_discriminate_the_weights() -> None:
    # A swapped-weights implementation (1,3,1,3 instead of 3,1,3,1) must fail on the real vectors.
    differing = [v for v in REAL_GLNS if swapped_weights_check_digit(v[:12]) != int(v[12])]
    assert differing == REAL_GLNS, "a real vector survives swapped weights and proves nothing"
    # ...whereas the all-zero GLN is valid under both, which is why it cannot be the only vector.
    assert swapped_weights_check_digit("000000000000") == 0


def test_r4_gln_check_digit_agrees_with_the_oracle_over_a_wide_sweep() -> None:
    for i in range(3000):
        body = f"{(i * 7_919_191 + 13) % 10**12:012d}"
        assert GLN.compute_check_digit(body) == oracle_check_digit(body), body


def test_r4_gln_refuses_wrong_length_non_digits_and_a_bad_check_digit() -> None:
    valid = "4006381333931"
    for bad in (
        valid[:12],  # 12 digits
        valid + "1",  # 14 digits
        "",
        valid[:12] + "A",  # a letter where the check digit goes
        "A" + valid[1:],  # a letter in the body
        valid[:6] + " " + valid[7:],  # whitespace inside
        valid[:12] + "0",  # 4006381333930: wrong check digit
    ):
        with pytest.raises(InvalidGlnError) as raised:
            GLN(bad)
        assert isinstance(raised.value, DomainError)
        assert raised.value.code == "gln.invalid"


@pytest.mark.parametrize(
    "bad",
    [
        "".join(chr(0x660 + int(d)) for d in "1234567890128"),  # Arabic-Indic digits, 13 chars
        "".join(chr(0xFF10 + int(d)) for d in "4006381333931"),  # fullwidth digits, 13 chars
        "400638133393¹",  # superscript one: isdigit() is True, isdecimal() is False
        "4006381333931\n",
        "\n4006381333931",
        "400638133393\n",  # 13 characters, newline last
        " 4006381333931",
        "4006381333931 ",
        "+006381333931",
        "-006381333931",
    ],
    ids=repr,
)
def test_r4_gln_refuses_unicode_digits_whitespace_and_signs(bad: str) -> None:
    assert len(bad) in (13, 14)
    with pytest.raises(InvalidGlnError):
        GLN(bad)


@pytest.mark.parametrize("bad", [None, 4006381333931, 4006381333931.0, b"4006381333931", [1]])
def test_r4_gln_refuses_a_non_str(bad: Any) -> None:
    with pytest.raises(InvalidGlnError):
        GLN(bad)


@pytest.mark.parametrize("bad", ["12345678901", "1234567890123", "12345678901a", "", None, 123])
def test_r4_compute_check_digit_refuses_a_body_that_is_not_twelve_ascii_digits(bad: Any) -> None:
    with pytest.raises(InvalidGlnError):
        GLN.compute_check_digit(bad)


@pytest.mark.parametrize("valid", REAL_GLNS)
def test_r4_every_single_digit_mutation_of_a_valid_gln_is_rejected(valid: str) -> None:
    # 13 positions x 9 other digits = 117 mutants per vector. Exhaustive because it can be: a
    # one-digit change moves the weighted sum by w * delta with w in {1, 3} and 0 < |delta| < 10;
    # gcd(3, 10) = 1 and gcd(1, 10) = 1, so w * delta is never a multiple of 10 and the sum mod
    # 10 always changes. (#7's gln.spec.ts did the sweep; #8 never did.)
    assert math.gcd(3, 10) == 1
    rejected = 0
    for position in range(13):
        for replacement in "0123456789":
            if replacement == valid[position]:
                continue
            mutant = valid[:position] + replacement + valid[position + 1 :]
            with pytest.raises(InvalidGlnError):
                GLN(mutant)
            rejected += 1
    assert rejected == 13 * 9


def test_r4_gln_is_a_value_object() -> None:
    assert GLN("4006381333931") == GLN("4006381333931")
    assert GLN("4006381333931") != GLN("4890123456787")
    assert len({GLN("4006381333931"), GLN("4006381333931")}) == 1
    with pytest.raises(AttributeError):
        GLN("4006381333931").value = "x"  # type: ignore[misc]
