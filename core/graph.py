"""Explicit causal-parent assignment and graph queries."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sdk.events import AgentClock, Event, next_seq


def _get_event(log: Any, event_id: str) -> Event:
    getter = getattr(log, "get", None)
    event = getter(event_id) if getter is not None else None
    if event is None:
        raise ValueError(f"causal parent event {event_id} does not exist")
    return event


def assign_causal_parents(
    agent_id: str,
    clock: AgentClock,
    causal_parents: list[str],
    log: Any,
    run_id: str | None = None,
) -> int:
    """Validate explicit parents and allocate the dependent event sequence."""
    if len(causal_parents) != len(set(causal_parents)):
        raise ValueError("causal parent IDs must be unique")
    parent_events = [_get_event(log, event_id) for event_id in causal_parents]
    if run_id is not None:
        for event in parent_events:
            if event.run_id is not None and event.run_id != run_id:
                raise ValueError(f"causal parent event {event.id} belongs to another run")
    parent_seqs = [event.logical_seq for event in parent_events]
    allocator = getattr(log, "allocate_logical_seq", None)
    if allocator is not None:
        return allocator(agent_id, clock, parent_seqs)
    return next_seq(clock, parent_seqs)


def record_causal_event(
    *,
    agent_id: str,
    clock: AgentClock,
    log: Any,
    event_type: str,
    payload: dict[str, Any],
    causal_parents: Iterable[str],
    idempotency_key: str | None = None,
    run_id: str | None = None,
) -> Event:
    """Append an event whose explicit parents were used by the caller."""
    parent_ids = list(causal_parents)
    if idempotency_key is not None:
        getter = getattr(log, "get_by_idempotency_key", None)
        if getter is not None:
            existing = getter(agent_id, idempotency_key)
            if isinstance(existing, Event):
                return existing
    if len(parent_ids) != len(set(parent_ids)):
        raise ValueError("causal parent IDs must be unique")
    logical_seq = assign_causal_parents(agent_id, clock, parent_ids, log, run_id)
    event = Event(
        agent_id=agent_id,
        logical_seq=logical_seq,
        event_type=event_type,
        payload=payload,
        causal_parent_ids=parent_ids,
        idempotency_key=idempotency_key,
        run_id=run_id,
    )
    result = log.append(event)
    return result if isinstance(result, Event) else event


def ancestors(event_id: str, log: Any) -> set[str]:
    """Return the starting event and all of its PostgreSQL-backed ancestors."""
    getter = getattr(log, "ancestors", None)
    if getter is None:
        raise TypeError("ancestors requires a storage adapter with an ancestors method")
    return set(getter(event_id))
