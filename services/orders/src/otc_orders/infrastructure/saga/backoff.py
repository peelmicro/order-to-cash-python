"""The saga's back-off arithmetic: pure, `int`-only, milliseconds (`design.md` 9.5; L14, L15).

Python's `int` is exact and unbounded: `2 ** n` never saturates the way #7's JS number (to
`Infinity`) or #8's `double` did, it grows. So the exponent is clamped BEFORE the power (written as
a shift, which stays an `int` for the type checker), and the division that turns total attempts into
park cycles is floor division: `/` would make every later value a `float`.
"""

PARK_BASE_MS = 30_000  # #8's formula (gate G2): the first park is retried after 60 s
MAX_PARK_EXPONENT = 31


def in_line_backoff_ms(attempt: int, *, base_ms: int) -> int:
    """The pause after in-line attempt `attempt` (1-based): `base_ms * 2 ** (attempt - 1)`."""
    if not 1 <= attempt <= 10:
        raise ValueError(f"an in-line attempt is 1..10 (SAGA_COMMAND_MAX_ATTEMPTS), got {attempt}")
    return base_ms * (1 << (attempt - 1))


def park_exponent(total_attempts: int, *, max_attempts: int) -> int:
    """How many whole in-line cycles the row has exhausted, clamped to 31."""
    return min(total_attempts // max_attempts, MAX_PARK_EXPONENT)


def park_backoff_ms(total_attempts: int, *, max_attempts: int, cap_ms: int) -> int:
    """`30 s * 2 ** cycles`, capped: 60 s, 120 s, 240 s ... for 3, 6, 9 attempts at three per
    cycle."""
    exponent = park_exponent(total_attempts, max_attempts=max_attempts)
    return min(PARK_BASE_MS * (1 << exponent), cap_ms)
