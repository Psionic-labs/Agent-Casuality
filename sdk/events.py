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

    The lock covers reading the current counter, allocating the next
    value, and tracking the last recorded event ID for intra-agent timeline continuity.
    """

    counter: int = 0
    last_event_id: str | None = None
    _lock: Lock = field(default_factory=Lock, init=False, repr=False, compare=False)

    def allocate(self, causal_parent_seqs: Iterable[int] = ()) -> int:
        parent_seqs = list(causal_parent_seqs)
        with self._lock:
            parent_max = max(parent_seqs, default=self.counter)
            self.counter = max(self.counter, parent_max) + 1
            return self.counter

    def current(self) -> int:
        with self._lock:
            return self.counter

    def observe(self, logical_seq: int) -> None:
        with self._lock:
            self.counter = max(self.counter, logical_seq)

    def set_last_event_id(self, event_id: str) -> None:
        with self._lock:
            self.last_event_id = event_id

    def get_last_event_id(self) -> str | None:
        with self._lock:
            return self.last_event_id


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


def _append(log: Any, event: Event) -> tuple[Event, bool]:
    """Append event to log and return (event, was_stored).
    
    Returns True if the append succeeded, False if fail-open mode swallowed an error.
    Checks for _last_append_failed attribute set by make_fail_open_append wrapper.
    """
    result = log.append(event)
    # Check if this is a fail-open wrapper that tracks append failures
    append_failed = getattr(log, "_last_append_failed", False)
    was_stored = not append_failed
    return (result if isinstance(result, Event) else event, was_stored)


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
    auto_chain: bool = False,
    redactor: Any = None,
) -> tuple[Event, bool]:
    """Allocate and append an event while preserving its causal metadata.
    
    Args:
        redactor: Optional PayloadRedactor to redact sensitive keys before storage.
                  If provided, redactor.redact(payload) is applied.
    
    Returns:
        Tuple of (event, was_stored) where was_stored indicates if persistence succeeded.
    """
    parent_ids = list(causal_parent_ids)
    if idempotency_key is not None:
        getter = getattr(log, "get_by_idempotency_key", None)
        if getter is not None:
            existing = getter(agent_id, idempotency_key)
            if isinstance(existing, Event):
                clock.set_last_event_id(existing.id)
                return existing, True
    if auto_chain and not parent_ids:
        prev_id = clock.get_last_event_id()
        if prev_id is not None:
            parent_ids = [prev_id]
    if len(parent_ids) != len(set(parent_ids)):
        raise ValueError("causal parent IDs must be unique")
    allocator = getattr(log, "allocate_logical_seq", None)
    if allocator is None:
        sequence = next_seq(clock, causal_parent_seqs)
    else:
        sequence = allocator(agent_id, clock, causal_parent_seqs)
    
    # Apply redaction if redactor is provided
    safe_payload = payload
    if redactor is not None:
        safe_payload = redactor.redact(payload)
    
    event, was_stored = _append(
        log,
        Event(
            agent_id=agent_id,
            logical_seq=sequence,
            event_type=event_type,
            payload=safe_payload,
            causal_parent_ids=parent_ids,
            idempotency_key=idempotency_key,
            run_id=run_id,
        ),
    )
    # Only update clock if the event was actually stored
    if was_stored:
        clock.set_last_event_id(event.id)
    return event, was_stored


class InMemoryEventLog:
    """A thread-safe log useful for unit tests and local capture."""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._by_id: dict[str, Event] = {}
        self._by_idempotency: dict[tuple[str, str], Event] = {}
        self._tool_locks: dict[tuple[str, str], Lock] = {}
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

    def tool_invocation_lock(self, agent_id: str, invocation_id: str) -> Lock:
        """Return the lock that serializes one tool invocation identity."""
        with self._lock:
            return self._tool_locks.setdefault((agent_id, invocation_id), Lock())

    def events(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.events())

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
