"""The REFERENCE implementation of the causal timeline order (`PR10`, `PR31`), in plain Python.

Production never calls this on the write path: the server sorts, inside the atomic apply
(`infrastructure/persistence/timeline_order.py`). This function is the oracle the differential test
checks that aggregation expression against, so it restates the rule independently:

1. `occurredAt` ascending;
2. a tie group is the maximal set of entries sharing one identical `occurredAt`;
3. within a tie group, `p` is the cause of `c` iff `c.causation_id == p.event_id`, `p` is in the
   group and `p` is not `c` (a self-edge is not a cause);
4. causal depth is `0` without a cause, else `1 + depth(cause)`, evaluated as a fixpoint over at
   most `|entries|` rounds, each round computed from the previous one, with the depth capped at
   `|entries|` (the cap never binds: the bounded rounds terminate a cycle, whose members tie on
   depth and fall back to `event_id`);
5. within a tie group: depth ascending, then `event_id` ascending.

An edge is never inferred from an event type, a status, a rank or arrival. A cause naming nothing
in the group (another group, a fact never received, a command id) means depth `0`; an entry with no
`causation_id` is cause-less, not an error. Every entry appears exactly once in the result.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TimelinePosition:
    """The three fields the order depends on; `occurred_at` is the fixed-width `.mmmZ` text."""

    event_id: str
    occurred_at: str
    causation_id: str | None


def causal_order(entries: Sequence[TimelinePosition]) -> list[TimelinePosition]:
    count = len(entries)
    depth = [0] * count
    for _ in range(count):
        depth = [min(count, _cause_depth(entries, depth, index) + 1) for index in range(count)]
    ranked = sorted(
        range(count),
        key=lambda index: (entries[index].occurred_at, depth[index], entries[index].event_id),
    )
    return [entries[index] for index in ranked]


def _cause_depth(entries: Sequence[TimelinePosition], depth: Sequence[int], index: int) -> int:
    """The previous round's depth of the entry's cause, or `-1` when it has none in its group."""
    entry = entries[index]
    if entry.causation_id is None:
        return -1
    for other_index, other in enumerate(entries):
        if (
            other.occurred_at == entry.occurred_at
            and other.event_id != entry.event_id
            and other.event_id == entry.causation_id
        ):
            return depth[other_index]
    return -1
