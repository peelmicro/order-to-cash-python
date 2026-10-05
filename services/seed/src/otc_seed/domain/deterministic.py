"""Deterministic derivation helpers: the backbone of "running the seed twice changes nothing".

Every id, GLN and EAN the seed writes is a pure function of a stable string namespace, never
`uuid4()` or `datetime.now()`. This module reproduces #7's `apps/seed/src/deterministic.ts`
byte for byte (the fixed `namespace -> uuid` vectors are in
`services/seed/tests/unit/test_deterministic_parity.py`; #8's `DeterministicId.cs` reproduces
the same).
"""

import hashlib

from otc_shared_kernel import GLN

_GLN_PREFIX = 540_000_000_000  # a GS1 prefix; the sequence is added to it, the check digit appended
_GLN_MAX_SEQUENCE = 999_999_999
_EAN_PREFIX = "590100"
_EAN_MAX_SEQUENCE = 999_999


def deterministic_id(namespace: str) -> str:
    """A UUID-SHAPED (RFC 4122 version-4 bit pattern), fully deterministic id from `namespace`.

    SHA-256 of `otc-seed:<namespace>`, laid out as a UUID. Not a random UUIDv4: the version and
    variant nibbles are forced so the value passes `UniqueId`'s v4 shape check, and two calls with
    the same namespace always return the same string.

    LOAD-BEARING WART, reproduced on purpose: the version nibble is `4` followed by hex characters
    13..15, so hex character INDEX 12 IS NEVER USED. A "tidy" `hex[12:15]` would produce different
    ids from #7 and #8 for every row (`currency:USD` would become `...-4250-...` instead of
    `...-4507-...`) and the datasets would no longer be the same dataset. The skipped character is
    pinned by `test_the_skipped_hex_character_is_load_bearing`.
    """
    digest = hashlib.sha256(f"otc-seed:{namespace}".encode()).hexdigest()
    time_low = digest[0:8]
    time_mid = digest[8:12]
    time_hi_and_version = "4" + digest[13:16]  # index 12 is skipped: see the docstring
    variant_nibble = f"{(int(digest[16], 16) & 0x3) | 0x8:x}"  # 8, 9, a or b
    clock_seq_and_reserved = variant_nibble + digest[17:20]
    node = digest[20:32]
    return f"{time_low}-{time_mid}-{time_hi_and_version}-{clock_seq_and_reserved}-{node}"


def make_gln(sequence: int) -> str:
    """A valid 13-digit GLN: `540000000000 + sequence` plus the genuine GS1 mod-10 check digit.

    The check digit comes from the shared kernel's `GLN.compute_check_digit` (the same function the
    domain validates with), and the result is round-tripped through `GLN(...)`, so an invalid party
    identifier fails here, at seed time, never at the first order.
    """
    if type(sequence) is not int or not 0 <= sequence <= _GLN_MAX_SEQUENCE:
        raise ValueError(f"make_gln: sequence out of range: {sequence!r}")
    body = str(_GLN_PREFIX + sequence)
    value = f"{body}{GLN.compute_check_digit(body)}"
    return str(GLN(value))


def make_ean13(sequence: int) -> str:
    """A 13-digit EAN barcode with a genuine mod-10 check digit (weights 3, 1 from the right)."""
    if type(sequence) is not int or not 0 <= sequence <= _EAN_MAX_SEQUENCE:
        raise ValueError(f"make_ean13: sequence out of range: {sequence!r}")
    body = f"{_EAN_PREFIX}{sequence:06d}"
    total = sum(
        int(digit) * (3 if distance % 2 == 0 else 1)
        for distance, digit in enumerate(reversed(body))
    )
    return f"{body}{(10 - total % 10) % 10}"
