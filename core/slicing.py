"""Structural slicing and the decision-facing ``why`` view.

``structural_slice`` is the cheap half of thesis section 13/30.4: pure graph
traversal over ``causal_parent_ids``, no replay, safe to run on every
failure. When the store exposes an ``ancestors`` method (the recursive
PostgreSQL query) it is preferred over the Python traversal, which remains
the fallback for in-memory logs.

The structural slice is *declared dependency* evidence only. It must never
be presented as proof that every included event influenced the outcome;
that distinction is what later phases (provenance, interaction replay)
exist to earn. ``why`` therefore labels its result accordingly.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from core.decision import DecisionContract
from core.reducer import reconstruct
from sdk.events import Event

__all__ = [
    "DecisionEvidence",
    "DeclaredInput",
    "PortEvidence",
    "StructuralSlice",
    "deep_get",
    "structural_slice",
    "why",
]

_SLICE_NOTE = (
    "structural evidence only: events are included because a causal parent "
    "relationship was declared at capture time; influence is not proven here"
)


@dataclass(frozen=True)
class StructuralSlice:
    """The reachable causal ancestor set of one event, root included."""

    root_event_id: str
    event_ids: tuple[str, ...]
    source: str  # "sql_recursive" or "python_bfs"

    def __len__(self) -> int:
        return len(self.event_ids)

    def __contains__(self, event_id: object) -> bool:
        return event_id in self.event_ids

    def __iter__(self):
        return iter(self.event_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_event_id": self.root_event_id,
            "event_ids": list(self.event_ids),
            "source": self.source,
            "note": _SLICE_NOTE,
        }


def _get_event(log: Any, event_id: str) -> Event:
    getter = getattr(log, "get", None)
    if callable(getter):
        event = getter(event_id)
        if isinstance(event, Event):
            return event
    raise ValueError(f"event {event_id} does not exist in the log")


def _slice_order_key(log: Any, event_ids: Iterable[str]) -> tuple[str, ...]:
    """Deterministic order: (logical_seq, agent_id, id); falls back to id."""
    getter = getattr(log, "get", None)
    metadata: dict[str, tuple[int, str, str]] = {}
    if callable(getter):
        for event_id in event_ids:
            event = getter(event_id)
            if isinstance(event, Event):
                metadata[event.id] = (event.logical_seq, event.agent_id, event.id)
    return tuple(
        sorted(
            event_ids,
            key=lambda event_id: metadata.get(event_id, (0, "", event_id)),
        )
    )


def _python_bfs(log: Any, event_id: str) -> set[str]:
    visited: set[str] = set()
    queue: list[str] = [event_id]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        event = _get_event(log, current)
        for parent_id in event.causal_parent_ids:
            if parent_id not in visited:
                queue.append(parent_id)
    return visited


def structural_slice(event_id: str, log: Any) -> StructuralSlice:
    """Return the event and every causal ancestor reachable from it.

    Prefers the store's recursive SQL query when available and falls back to
    an in-process breadth-first traversal otherwise. Complexity is O(V + E)
    over the reachable subgraph; nothing is re-executed.
    """
    ancestors_fn = getattr(log, "ancestors", None)
    if callable(ancestors_fn):
        ids = list(ancestors_fn(event_id))
        if not ids:
            raise ValueError(f"event {event_id} does not exist")
        source = "sql_recursive"
    else:
        ids = sorted(_python_bfs(log, event_id))
        source = "python_bfs"
    return StructuralSlice(
        root_event_id=event_id,
        event_ids=tuple(_slice_order_key(log, ids)),
        source=source,
    )


def deep_get(payload: Any, field_path: str) -> tuple[bool, Any]:
    """Resolve a dotted path like ``output.customer_status`` inside a payload.

    Returns ``(found, value)``; a missing segment yields ``(False, None)``
    rather than raising, since absent fields are meaningful evidence.
    """
    current = payload
    for segment in field_path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return False, None
    return True, current


@dataclass(frozen=True)
class PortEvidence:
    """One semantic decision port resolved against the recorded events."""

    port_id: str
    source_event_id: str
    field_path: str | None
    recorded_value: Any
    live_value: Any
    found_in_payload: bool
    matches_recorded: bool
    in_slice: bool


@dataclass(frozen=True)
class DeclaredInput:
    """A cross-agent causal parent used as an input when no contract exists."""

    source_event_id: str
    source_agent_id: str


@dataclass(frozen=True)
class DecisionEvidence:
    """What the structure can honestly say about one decision or merge."""

    decision_event_id: str
    run_id: str | None
    agent_id: str
    event_type: str
    contract_present: bool
    decision_type: str | None
    outcome: str | None
    ports: tuple[PortEvidence, ...]
    declared_inputs: tuple[DeclaredInput, ...]
    slice: StructuralSlice
    status_at_decision: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_event_id": self.decision_event_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "event_type": self.event_type,
            "contract_present": self.contract_present,
            "decision_type": self.decision_type,
            "outcome": self.outcome,
            "ports": [
                {
                    "port_id": port.port_id,
                    "source_event_id": port.source_event_id,
                    "field_path": port.field_path,
                    "recorded_value": port.recorded_value,
                    "live_value": port.live_value,
                    "found_in_payload": port.found_in_payload,
                    "matches_recorded": port.matches_recorded,
                    "in_slice": port.in_slice,
                }
                for port in self.ports
            ],
            "declared_inputs": [
                {
                    "source_event_id": item.source_event_id,
                    "source_agent_id": item.source_agent_id,
                }
                for item in self.declared_inputs
            ],
            "slice": self.slice.to_dict(),
            "status_at_decision": self.status_at_decision,
            "note": self.note,
        }


def _port_evidence(
    port: Any,
    *,
    log: Any,
    slice_ids: frozenset[str],
) -> PortEvidence:
    source_event = _get_event(log, port.source_event_id)
    found, live_value = (
        deep_get(source_event.payload, port.field_path) if port.field_path else (False, None)
    )
    return PortEvidence(
        port_id=port.port_id,
        source_event_id=port.source_event_id,
        field_path=port.field_path,
        recorded_value=port.recorded_value,
        live_value=live_value,
        found_in_payload=found,
        matches_recorded=found and live_value == port.recorded_value,
        in_slice=port.source_event_id in slice_ids,
    )


def why(
    decision_event_id: str,
    log: Any,
    *,
    reconstruct_state: bool = True,
) -> DecisionEvidence:
    """Answer the structural half of "why was this decision made".

    Combines the decision contract (Phase 2.5), the structural slice, and
    the reconstructed state at the decision event into one evidence view.
    Ports are resolved against the recorded payload of their source events;
    any mismatch between the contract's ``recorded_value`` and the payload
    actually stored is surfaced instead of hidden.

    This is deliberately not an explanation of influence. Interaction
    testing and provenance (later phases) are what upgrade declared
    dependency into tested influence.
    """
    event = _get_event(log, decision_event_id)
    contract = DecisionContract.from_event(event)
    slice_result = structural_slice(decision_event_id, log)
    slice_ids = frozenset(slice_result.event_ids)

    ports: tuple[PortEvidence, ...] = ()
    declared_inputs: tuple[DeclaredInput, ...] = ()
    if contract is not None:
        ports = tuple(
            _port_evidence(port, log=log, slice_ids=slice_ids) for port in contract.ports
        )
    else:
        own_agent = event.agent_id
        seen_agents: dict[tuple[str, str], DeclaredInput] = {}
        for parent_id in event.causal_parent_ids:
            parent = _get_event(log, parent_id)
            if parent.agent_id != own_agent:
                key = (parent.id, parent.agent_id)
                seen_agents.setdefault(
                    key,
                    DeclaredInput(source_event_id=parent.id, source_agent_id=parent.agent_id),
                )
        declared_inputs = tuple(seen_agents.values())

    status_at_decision = "unknown"
    if reconstruct_state:
        state = reconstruct(event.agent_id, event.logical_seq, log=log)
        status_at_decision = state.status

    return DecisionEvidence(
        decision_event_id=event.id,
        run_id=event.run_id,
        agent_id=event.agent_id,
        event_type=event.event_type,
        contract_present=contract is not None,
        decision_type=contract.decision_type if contract else None,
        outcome=contract.outcome if contract else None,
        ports=ports,
        declared_inputs=declared_inputs,
        slice=slice_result,
        status_at_decision=status_at_decision,
        note=_SLICE_NOTE,
    )
