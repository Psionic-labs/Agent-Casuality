"""Agent lifecycle capture, including the parent-to-child spawn edge."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .events import AgentClock, Event, record_event


@dataclass
class AgentRecord:
    id: str
    run_id: str
    role: str | None = None
    parent_agent_id: str | None = None
    spawned_at_event_id: str | None = None
    status: str = "active"
    lamport_offset: int = 0


class InMemoryAgentStore:
    def __init__(self) -> None:
        self.agents: dict[str, AgentRecord] = {}

    def create_agent(self, agent: AgentRecord) -> AgentRecord:
        existing = self.agents.get(agent.id)
        if existing is not None:
            return existing
        self.agents[agent.id] = agent
        return agent

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        return self.agents.get(agent_id)

    def get_by_spawn_event(self, event_id: str) -> AgentRecord | None:
        return next((a for a in self.agents.values() if a.spawned_at_event_id == event_id), None)


def _existing_spawn(log: Any, agent_id: str, key: str) -> Event | None:
    getter = getattr(log, "get_by_idempotency_key", None)
    return getter(agent_id, key) if getter is not None else None


def _latest_agent_seq(log: Any, agent_id: str, fallback: int) -> int:
    getter = getattr(log, "get_latest_logical_seq", None)
    if getter is not None:
        latest = getter(agent_id)
        return max(fallback, latest or 0)
    if hasattr(log, "events"):
        events = log.events()
    elif hasattr(log, "__iter__"):
        events = list(log)
    else:
        events = []
    return max(
        (event.logical_seq for event in events if event.agent_id == agent_id), default=fallback
    )


def _recovered_clock(log: Any, agent: AgentRecord) -> AgentClock:
    return AgentClock(_latest_agent_seq(log, agent.id, agent.lamport_offset))


def spawn_agent(
    *,
    parent_agent_id: str,
    parent_clock: AgentClock,
    run_id: str,
    role: str | None,
    log: Any,
    agent_store: Any,
    causal_parent_ids: Iterable[str] = (),
    child_agent_id: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[AgentRecord, Event, AgentClock]:
    """Create a child and persist the parent spawn event first.

    The child clock starts at the parent's counter *after* allocation of the
    spawn event, as required by the Lamport rule in thesis §30.2.  Supplying a
    stable child ID or idempotency key makes a retried spawn return the same
    child instead of creating another one.
    """
    if child_agent_id is None and idempotency_key is None:
        raise ValueError("retry-safe spawning requires child_agent_id or idempotency_key")
    child_id = child_agent_id or str(uuid4())
    spawn_key = idempotency_key or f"agent-spawn:{child_id}"
    existing_event = _existing_spawn(log, parent_agent_id, spawn_key)
    if existing_event is not None:
        existing_agent = agent_store.get_by_spawn_event(existing_event.id)
        if existing_agent is not None:
            return existing_agent, existing_event, _recovered_clock(log, existing_agent)

    event = record_event(
        agent_id=parent_agent_id,
        clock=parent_clock,
        log=log,
        event_type="agent_spawn",
        payload={"child_agent_id": child_id, "role": role},
        causal_parent_ids=causal_parent_ids,
        idempotency_key=spawn_key,
        run_id=run_id,
    )
    existing_agent = agent_store.get_by_spawn_event(event.id)
    if existing_agent is not None:
        return existing_agent, event, _recovered_clock(log, existing_agent)

    child = agent_store.create_agent(
        AgentRecord(
            id=child_id,
            run_id=run_id,
            role=role,
            parent_agent_id=parent_agent_id,
            spawned_at_event_id=event.id,
            lamport_offset=event.logical_seq,
        ),
    )
    return child, event, AgentClock(event.logical_seq)
