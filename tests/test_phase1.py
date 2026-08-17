from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest

from sdk.client import CapturedClient
from sdk.events import AgentClock, Event, InMemoryEventLog, next_seq, record_event
from sdk.lifecycle import InMemoryAgentStore, spawn_agent
from sdk.memory import CapturedMemory
from sdk.tools import capture_tool


def test_agent_clock_allocates_unique_sequences_concurrently() -> None:
    clock = AgentClock()
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: next_seq(clock, []), range(100)))
    assert sorted(values) == list(range(1, 101))


def test_record_event_allocates_before_sink_and_preserves_parents() -> None:
    class InspectingLog:
        def __init__(self) -> None:
            self.event: Event | None = None

        def append(self, event: Event) -> Event:
            self.event = event
            assert event.logical_seq == 1
            return event

    log = InspectingLog()
    event = record_event(
        agent_id="a",
        clock=AgentClock(),
        log=log,
        event_type="context_update",
        payload={"x": 1},
        causal_parent_ids=["parent-1", "parent-2"],
    )
    assert event.causal_parent_ids == ["parent-1", "parent-2"]


@dataclass
class FakeResponse:
    answer: str

    def model_dump(self) -> dict[str, str]:
        return {"answer": self.answer}


class FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        return FakeResponse("ok")


class FakeAnthropic:
    def __init__(self) -> None:
        self.messages = FakeMessages()


def test_anthropic_messages_create_is_captured_without_changing_call() -> None:
    log = InMemoryEventLog()
    fake = FakeAnthropic()
    client = CapturedClient(None, "planner", AgentClock(), log, client=fake)
    response = client.messages.create(
        model="test-model",
        max_tokens=10,
        messages=[{"role": "user", "content": "hello"}],
        causal_parent_ids=["worker-result"],
    )
    assert response.answer == "ok"
    assert fake.messages.calls == [
        {
            "model": "test-model",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "hello"}],
        }
    ]
    event = log.events()[0]
    assert event.event_type == "model_call"
    assert event.causal_parent_ids == ["worker-result"]
    assert event.payload["output"] == {"answer": "ok"}


def test_capture_tool_logs_linked_call_and_result_and_retries_once() -> None:
    log = InMemoryEventLog()
    clock = AgentClock()
    calls = 0

    @capture_tool
    def lookup(value: str) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"value": value}

    first = lookup(
        "x",
        agent_id="worker",
        clock=clock,
        log=log,
        causal_parent_ids=["input-event"],
        invocation_id="stable-invocation",
    )
    second = lookup(
        "x",
        agent_id="worker",
        clock=clock,
        log=log,
        invocation_id="stable-invocation",
    )
    events = log.events()
    assert first == second == {"value": "x"}
    assert calls == 1
    assert [event.event_type for event in events] == ["tool_call", "tool_result"]
    assert events[0].causal_parent_ids == ["input-event"]
    assert events[1].causal_parent_ids == [events[0].id]


def test_captured_memory_records_get_set_delete_with_before_after() -> None:
    log = InMemoryEventLog()
    memory = CapturedMemory(agent_id="worker", clock=AgentClock(), log=log)
    assert memory.get("answer") is None
    memory.set("answer", 42)
    assert memory.get("answer") == 42
    assert memory.delete("answer") is True
    assert memory.delete("answer") is False
    events = log.events()
    assert [event.event_type for event in events] == [
        "memory_read",
        "memory_write",
        "memory_read",
        "memory_write",
        "memory_write",
    ]
    assert events[1].payload["before"] is None
    assert events[1].payload["after"] == 42
    assert events[3].payload["operation"] == "delete"
    assert events[3].payload["before"] == 42


def test_spawn_persists_spawn_event_and_seeds_child_clock() -> None:
    log = InMemoryEventLog()
    agents = InMemoryAgentStore()
    parent_clock = AgentClock()
    child, event, child_clock = spawn_agent(
        parent_agent_id="planner",
        parent_clock=parent_clock,
        run_id="run",
        role="worker",
        log=log,
        agent_store=agents,
        causal_parent_ids=["planner-input"],
        child_agent_id="worker-1",
    )
    assert event.event_type == "agent_spawn"
    assert child.parent_agent_id == "planner"
    assert child.spawned_at_event_id == event.id
    assert child_clock.counter == event.logical_seq == 1
    assert agents.get_by_spawn_event(event.id) == child

    retry_child, retry_event, retry_clock = spawn_agent(
        parent_agent_id="planner",
        parent_clock=parent_clock,
        run_id="run",
        role="worker",
        log=log,
        agent_store=agents,
        child_agent_id="worker-1",
    )
    assert retry_child == child
    assert retry_event == event
    assert retry_clock.counter == child_clock.counter
    assert len(log) == 1


def test_tool_errors_are_captured_and_re_raised() -> None:
    log = InMemoryEventLog()

    @capture_tool(agent_id="worker", clock=AgentClock(), log=log)
    def fail() -> None:
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        fail()
    assert [event.event_type for event in log.events()] == ["tool_call", "agent_error"]
