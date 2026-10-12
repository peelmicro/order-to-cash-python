"""The stream's two pure rules (R55): the frame cursor and the bounded replay buffer.

Ports of #7 `replay-buffer.spec.ts` (7 cases) and #8 `CursorGeneratorTests` / `ReplayBufferTests`,
each assertion classified in `progress/impl_gateway_sse_push.md` (guard-port table).
"""

import asyncio
import inspect

import pytest

from otc_gateway.domain.sse.cursor import CursorGenerator
from otc_gateway.domain.sse.replay_buffer import ReplayBuffer


class Ms:
    def __init__(self, value: int = 1_755_511_234_567) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def minted(count: int, clock: Ms | None = None) -> tuple[CursorGenerator, list[str]]:
    generator = CursorGenerator(clock or Ms())
    return generator, [generator.next() for _ in range(count)]


# -------------------------------------------------------------------------------- the cursor


def test_r55_a_cursor_is_the_epoch_milliseconds_and_a_sequence() -> None:
    clock = Ms(1_755_511_234_567)
    generator = CursorGenerator(clock)

    assert generator.next() == "1755511234567-1"
    clock.value += 5
    assert generator.next() == "1755511234572-2"


def test_r55_two_cursors_minted_in_one_millisecond_never_collide() -> None:
    _, cursors = minted(50)  # one frozen clock

    assert len(set(cursors)) == 50


def test_r55_the_cursor_sequence_is_monotonic_across_milliseconds() -> None:
    clock = Ms()
    generator = CursorGenerator(clock)
    sequences = []
    for step in range(30):
        clock.value += step % 3  # sometimes the same millisecond, sometimes later
        sequences.append(int(generator.next().rsplit("-", 1)[1]))

    assert sequences == list(range(1, 31))


def test_r55_minting_cannot_be_interrupted_so_concurrent_tasks_never_share_a_cursor() -> None:
    """The hand-built replacement for #8's `Interlocked.Increment` (`CursorGenerator.cs`): #7's
    plain increment was safe because Node ran one thread; #9 is safe because `next` is a plain
    function, with no `await` between reading the sequence and writing it. Both halves are held:
    the method is not a coroutine function (an `async def` could suspend between the two), and
    1000 tasks that yield to the loop between calls still get 1000 distinct, ordered cursors."""
    assert not inspect.iscoroutinefunction(CursorGenerator.next), (
        "CursorGenerator.next became a coroutine function: a suspension between read and write "
        "of the sequence would let two tasks mint one cursor"
    )

    async def run() -> list[str]:
        generator = CursorGenerator(Ms())
        results: list[str] = []

        async def worker() -> None:
            await asyncio.sleep(0)
            results.append(generator.next())
            await asyncio.sleep(0)
            results.append(generator.next())

        async with asyncio.TaskGroup() as group:
            for _ in range(500):
                group.create_task(worker())
        return results

    cursors = asyncio.run(run())

    assert len(cursors) == 1000
    assert len(set(cursors)) == 1000
    assert [int(c.rsplit("-", 1)[1]) for c in cursors] == list(range(1, 1001))


# ------------------------------------------------------------------------- the replay buffer


def filled(capacity: int, count: int) -> tuple[ReplayBuffer[str], list[str]]:
    """`count` values pushed under REAL cursors. Sequences 9 and 10 are in the middle, where the
    string order of the cursors ('...-10' < '...-9') disagrees with their arrival order, so a
    buffer that compared cursors instead of positions answers differently from one that does not."""
    _, cursors = minted(count)
    buffer: ReplayBuffer[str] = ReplayBuffer(capacity)
    for cursor in cursors:
        buffer.push(cursor, f"value-of-{cursor}")
    return buffer, cursors


def test_r55_replay_returns_everything_strictly_after_a_cursor_in_the_middle_of_the_buffer() -> (
    None
):
    buffer, cursors = filled(20, 12)
    middle = cursors[8]  # sequence 9

    result = buffer.replay_after(middle)

    assert result.resumed is True
    # exactly 10, 11, 12 in arrival order: not the cursor's own frame (at-or-after), not the frames
    # before it, not what a string comparison would give ('...-10' and '...-11' sort BEFORE '...-9')
    assert result.missed == tuple(f"value-of-{c}" for c in cursors[9:]), (
        "the replay after a cursor in the middle of the buffer is not exactly the frames after it"
    )
    assert [m.rsplit("-", 1)[1] for m in result.missed] == ["10", "11", "12"]


def test_r55_a_client_that_is_caught_up_resumes_with_nothing_missed() -> None:
    buffer, cursors = filled(20, 5)

    result = buffer.replay_after(cursors[-1])

    assert result.resumed is True
    assert result.missed == ()


def test_r55_a_fresh_connection_with_no_last_event_id_is_never_a_resume() -> None:
    buffer, _ = filled(20, 5)

    result = buffer.replay_after(None)

    assert result.resumed is False
    assert result.missed == ()


def test_r55_a_cursor_that_never_existed_resolves_resumed_false_not_an_error() -> None:
    buffer, _ = filled(20, 5)

    result = buffer.replay_after("1755511234567-9999")

    assert result.resumed is False
    assert result.missed == ()


def test_r55_a_cursor_older_than_the_buffer_holds_resolves_resumed_false_not_a_stale_replay() -> (
    None
):
    buffer, cursors = filled(5, 8)  # capacity 5: cursors 1-3 were evicted

    assert buffer.replay_after(cursors[0]).resumed is False
    assert buffer.replay_after(cursors[2]).resumed is False
    survivor = buffer.replay_after(cursors[3])
    assert survivor.resumed is True
    assert survivor.missed == tuple(f"value-of-{c}" for c in cursors[4:])


def test_r55_the_buffer_never_grows_past_its_capacity() -> None:
    buffer, _ = filled(5, 200)

    assert len(buffer) == 5


def test_r55_a_non_positive_capacity_is_refused() -> None:
    with pytest.raises(ValueError, match="capacity"):
        ReplayBuffer(0)
