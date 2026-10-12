"""The stream's bounded replay buffer (`openapi.yaml` `/orders/stream`, "Reconnection"; R55).

A fixed-capacity history of the frames emitted, oldest evicted first, keyed by their opaque cursor.
The two limitations the contract states are both consequences of this shape, not special cases: a
cursor older than the oldest surviving entry is indistinguishable from one that never existed
(`resumed=False`, the client re-fetches), and `replay_after` returns everything STRICTLY after the
cursor, never the cursor's own frame ("resumes after"). Ported from #7 `replay-buffer.ts` and #8
`ReplayBuffer.cs`; #8's `lock` is not needed on one event loop (no `await` inside either method).
"""

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReplayResult[T]:
    resumed: bool
    missed: tuple[T, ...]


class ReplayBuffer[T]:
    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError(f"ReplayBuffer: capacity must be at least 1, got {capacity}")
        self._entries: deque[tuple[str, T]] = deque(maxlen=capacity)

    def push(self, cursor: str, value: T) -> None:
        self._entries.append((cursor, value))  # `maxlen` evicts the oldest

    def replay_after(self, cursor: str | None) -> ReplayResult[T]:
        """`cursor` is None for a fresh connection (no `Last-Event-ID`): never a resume."""
        if cursor is None:
            return ReplayResult(False, ())
        entries = list(self._entries)
        for position, (candidate, _) in enumerate(entries):
            if candidate == cursor:
                return ReplayResult(True, tuple(value for _, value in entries[position + 1 :]))
        return ReplayResult(False, ())

    def __len__(self) -> int:
        return len(self._entries)
