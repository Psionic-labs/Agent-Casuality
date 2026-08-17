"""Events, logical clocks, and the small storage contract used by capture."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4


@dataclass
class AgentClock:
    """A thread-safe Lamport clock owned by one agent.

    The lock covers both reading the current counter and allocating the next
    value.  Allocation is deliberately a separate operation from persistence:
    callers receive the sequence number before they hand an event to a log or
    buffer.
    """

    counter: int = 0
    _lock: Lock = field(default_factory=Lock, init=False, repr=False, compare=False)

    def allocate(self, causal_parent_seqs: Iterable[int] = ()) -> int:
        parent_max = max(causal_parent_seqs, default=self.counter)
        with self._lock:
            self.counter = max(self.counter, parent_max) + 1
            return self.counter


@dataclass(frozen=True)
class Event:
    """One observable occurrence in an agent run."""

    agent_id: str
    logical_seq: int
    event_type: str
    payload: dict[str, Any]
    causal_parent_ids: list[str] = field(default_factory=list)
    idempotency_key: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    run_id: str | None = None
    wall_time: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_record(self) -> dict[str, Any]:
        """Return a storage-neutral representation of this event."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "logical_seq": self.logical_seq,
            "wall_time": self.wall_time,
            "event_type": self.event_type,
            "causal_parent_ids": list(self.causal_parent_ids),
            "payload": self.payload,
            "idempotency_key": self.idempotency_key,
        }


class EventLog(Protocol):
    def append(self, event: Event) -> Event: ...


def next_seq(agent_state: AgentClock, causal_parents: Iterable[int]) -> int:
    """Allocate the next sequence number before persistence or buffering."""
    return agent_state.allocate(causal_parents)


def _append(log: Any, event: Event) -> Event:
    result = log.append(event)
    return result if isinstance(result, Event) else event


def record_event(
    *,
    agent_id: str,
    clock: AgentClock,
    log: Any,
    event_type: str,
    payload: dict[str, Any],
    causal_parent_ids: Iterable[str] = (),
    causal_parent_seqs: Iterable[int] = (),
    idempotency_key: str | None = None,
    run_id: str | None = None,
) -> Event:
    """Allocate and append an event while preserving its causal metadata."""
    parent_ids = list(causal_parent_ids)
    sequence = next_seq(clock, causal_parent_seqs)
    return _append(
        log,
        Event(
            agent_id=agent_id,
            logical_seq=sequence,
            event_type=event_type,
            payload=payload,
            causal_parent_ids=parent_ids,
            idempotency_key=idempotency_key,
            run_id=run_id,
        ),
    )


class InMemoryEventLog:
    """A thread-safe log useful for unit tests and local capture."""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._by_id: dict[str, Event] = {}
        self._by_idempotency: dict[tuple[str, str], Event] = {}
        self._lock = Lock()

    def append(self, event: Event) -> Event:
        with self._lock:
            if event.idempotency_key is not None:
                key = (event.agent_id, event.idempotency_key)
                existing = self._by_idempotency.get(key)
                if existing is not None:
                    return existing
                self._by_idempotency[key] = event
            self._events.append(event)
            self._by_id[event.id] = event
            return event

    def get(self, event_id: str) -> Event | None:
        with self._lock:
            return self._by_id.get(event_id)

    def get_by_idempotency_key(self, agent_id: str, key: str) -> Event | None:
        with self._lock:
            return self._by_idempotency.get((agent_id, key))

    def events(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.events())

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
