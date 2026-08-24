"""State reconstruction from the event log (thesis section 30.3).

The reducer is a pure fold over an agent's events in ``logical_seq`` order.
One match arm per event type; unknown event types fail closed rather than
being silently ignored, because a silently skipped write would corrupt every
later reconstruction without any visible signal.

Reconstruction finds the nearest snapshot at or before the target sequence,
starts from its recorded state, and replays forward:

    state = snapshot.state (or empty)
    for event in agent_events[snapshot.logical_seq + 1 .. target_seq]:
        state = reduce(state, event)

Snapshots carry a ``state_hash`` of the canonical JSON encoding so a later
reconstruction can be checked against it instead of trusted blindly. See
``core.snapshots`` for creation and storage; this module owns the fold and
the integrity check.
"""

from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from sdk.events import Event

__all__ = [
    "AgentState",
    "ReplayIntegrityError",
    "canonical_json",
    "hash_state",
    "iter_agent_events",
    "reduce",
    "reconstruct",
    "verify_snapshot",
]

_MISSING = object()


class ReplayIntegrityError(RuntimeError):
    """A reconstructed state does not match the recorded snapshot hash."""


@dataclass(frozen=True)
class AgentState:
    """Semantic state of one agent at a point in its logical timeline.

    All fields are JSON-serializable so a state can round-trip through the
    ``snapshots`` table and through :func:`canonical_json` unchanged. The
    dataclass is frozen; :func:`reduce` returns new instances via
    ``dataclasses.replace``, which makes concurrent reads safe by
    construction.
    """

    memory: dict[str, Any] = field(default_factory=dict)
    open_tools: dict[str, str] = field(default_factory=dict)
    tool_outputs: dict[str, Any] = field(default_factory=dict)
    context: Any = None
    status: str = "active"

    @classmethod
    def empty(cls) -> AgentState:
        return cls()

    def to_json(self) -> dict[str, Any]:
        """Return the JSON-serializable form stored inside snapshots."""
        return {
            "memory": dict(self.memory),
            "open_tools": dict(self.open_tools),
            "tool_outputs": dict(self.tool_outputs),
            "context": self.context,
            "status": self.status,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> AgentState:
        return cls(
            memory=dict(data.get("memory", {})),
            open_tools=dict(data.get("open_tools", {})),
            tool_outputs=dict(data.get("tool_outputs", {})),
            context=data.get("context"),
            status=str(data.get("status", "active")),
        )


def canonical_json(state: AgentState) -> str:
    """Serialize state deterministically so equal states hash equally."""
    return json.dumps(
        state.to_json(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=repr,
    )


def hash_state(state: AgentState) -> str:
    """SHA-256 of the canonical JSON encoding of ``state``."""
    return hashlib.sha256(canonical_json(state).encode("utf-8")).hexdigest()


def _invocation_key(event: Event) -> str:
    value = event.payload.get("invocation_id")
    return str(value) if value else event.id


def _apply_memory_write(memory: dict[str, Any], payload: Mapping[str, Any]) -> None:
    operation = payload.get("operation")
    key = payload.get("key", _MISSING)
    if key is _MISSING or not isinstance(key, str):
        raise ValueError(f"memory_write payload has no usable key: {dict(payload)!r}")
    if operation == "delete" or payload.get("after_found") is False:
        memory.pop(key, None)
        return
    if "after" in payload:
        memory[key] = payload["after"]
        return
    raise ValueError(f"memory_write payload is not interpretable: {dict(payload)!r}")


def reduce(state: AgentState, event: Event) -> AgentState:
    """Apply one event to ``state`` and return the next state.

    Pure function: ``state`` is never mutated. Exactly one match arm per
    persisted event type; anything else raises so replay never invents
    semantics it was not given.
    """
    match event.event_type:
        case "model_call":
            return state
        case "tool_call":
            key = _invocation_key(event)
            open_tools = dict(state.open_tools)
            open_tools[key] = event.id
            return replace(state, open_tools=open_tools)
        case "tool_result":
            open_tools = dict(state.open_tools)
            tool_outputs = dict(state.tool_outputs)
            invocation_id = event.payload.get("invocation_id")
            if invocation_id:
                output_key = str(invocation_id)
                open_tools.pop(output_key, None)
            else:
                # Without an invocation id, close the open tool_call this
                # result causally descends from, which is deterministic
                # under the ordered replay this reducer guarantees.
                match_key = next(
                    (
                        key
                        for key, call_event_id in open_tools.items()
                        if call_event_id in event.causal_parent_ids
                    ),
                    None,
                )
                output_key = match_key or event.id
                if match_key is not None:
                    del open_tools[match_key]
            if "output" in event.payload:
                tool_outputs[output_key] = event.payload["output"]
            return replace(state, open_tools=open_tools, tool_outputs=tool_outputs)
        case "memory_write":
            memory = dict(state.memory)
            _apply_memory_write(memory, event.payload)
            return replace(state, memory=memory)
        case "memory_read":
            return state
        case "context_update":
            return replace(state, context=event.payload.get("context"))
        case "agent_spawn":
            return state
        case "agent_finish":
            return replace(state, status=str(event.payload.get("status", "completed")))
        case "agent_error":
            return replace(state, status="error")
        case "run_start":
            return state
        case "run_finish":
            return state
        case other:
            raise ValueError(f"unknown event_type {other!r}; cannot reduce event {event.id}")


def iter_agent_events(
    log: Any,
    agent_id: str,
    *,
    since: int = 0,
    until: int | None = None,
) -> list[Event]:
    """Fetch one agent's events with ``since < logical_seq <= until``.

    Uses ``log.fetch_events(agent_id, since=..., until=...)`` when the store
    provides it (PostgreSQL), otherwise filters an in-memory iterable. The
    returned list is always ordered by ``logical_seq`` ascending.
    """
    fetcher = getattr(log, "fetch_events", None)
    if callable(fetcher):
        events = list(fetcher(agent_id, since=since, until=until))
    else:
        if hasattr(log, "events"):
            source: Iterable[Event] = log.events()
        elif hasattr(log, "__iter__"):
            source = log
        else:
            raise TypeError("log must expose fetch_events, events(), or be iterable")
        events = [
            event
            for event in source
            if event.agent_id == agent_id and since < event.logical_seq
        ]
    if until is not None:
        events = [event for event in events if event.logical_seq <= until]
    return sorted(events, key=lambda event: event.logical_seq)


def reconstruct(
    agent_id: str,
    target_seq: int,
    *,
    log: Any,
    snapshots: Any | None = None,
    verify: bool = False,
) -> AgentState:
    """Rebuild the agent's state as of ``target_seq`` inclusive.

    Args:
        agent_id: Agent whose state should be rebuilt.
        target_seq: Inclusive upper bound on ``logical_seq`` to replay.
        log: Event store (PostgresEventStore or InMemoryEventLog).
        snapshots: Optional snapshot store; the nearest snapshot at or
            before ``target_seq`` shortens the replay when present.
        verify: When True and a snapshot was used, first re-derive the
            snapshot's state from scratch and check its recorded hash.

    Returns:
        The reconstructed :class:`AgentState`.

    Raises:
        ReplayIntegrityError: If ``verify`` is set and the snapshot does not
            match a fresh replay of its own prefix.
    """
    snapshot = None
    if snapshots is not None:
        latest = getattr(snapshots, "latest_at_or_before", None)
        if callable(latest):
            snapshot = latest(agent_id, target_seq)

    if snapshot is not None:
        if verify:
            verify_snapshot(snapshot, log=log)
        start_state = AgentState.from_json(snapshot.state)
        since = snapshot.logical_seq
    else:
        start_state = AgentState.empty()
        since = 0

    events = iter_agent_events(log, agent_id, since=since, until=target_seq)
    return functools.reduce(reduce, events, start_state)


def verify_snapshot(snapshot: Any, *, log: Any) -> None:
    """Check a snapshot against a fresh replay of its own prefix.

    Recomputes the state from an empty start up to
    ``snapshot.logical_seq`` and compares both the recorded hash and the
    recorded state blob. Raises :class:`ReplayIntegrityError` on any
    mismatch, per the integrity rule in thesis section 30.3.
    """
    events = iter_agent_events(log, snapshot.agent_id, since=0, until=snapshot.logical_seq)
    replayed = functools.reduce(reduce, events, AgentState.empty())
    replayed_hash = hash_state(replayed)
    if replayed_hash != snapshot.state_hash:
        raise ReplayIntegrityError(
            f"snapshot {snapshot.agent_id}@{snapshot.logical_seq} hash mismatch: "
            f"recorded {snapshot.state_hash}, replay produced {replayed_hash}"
        )
    if canonical_json(AgentState.from_json(snapshot.state)) != canonical_json(replayed):
        raise ReplayIntegrityError(
            f"snapshot {snapshot.agent_id}@{snapshot.logical_seq} state blob does not "
            f"match a fresh replay of its prefix"
        )
