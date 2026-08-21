from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier
from uuid import uuid4

import pytest

from sdk.client import CapturedClient
from sdk.events import AgentClock, Event, InMemoryEventLog, next_seq, record_event
from sdk.lifecycle import InMemoryAgentStore, spawn_agent
from sdk.memory import CapturedMemory
from sdk.tools import capture_tool
from storage.postgres import PostgresEventStore


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
    event, _ = record_event(
        agent_id="a",
        clock=AgentClock(),
        log=log,
        event_type="context_update",
        payload={"x": 1},
        causal_parent_ids=["parent-1", "parent-2"],
    )
    assert event.causal_parent_ids == ["parent-1", "parent-2"]


def test_record_event_idempotent_retry_does_not_allocate_again() -> None:
    log = InMemoryEventLog()
    clock = AgentClock()
    first, _ = record_event(
        agent_id="a",
        clock=clock,
        log=log,
        event_type="context_update",
        payload={"attempt": 1},
        idempotency_key="same-event",
    )

    retry, _ = record_event(
        agent_id="a",
        clock=clock,
        log=log,
        event_type="context_update",
        payload={"attempt": 2},
        idempotency_key="same-event",
    )

    assert retry == first
    assert clock.current() == first.logical_seq


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


class FakeStream:
    def __init__(self, chunks: list[object]) -> None:
        self.chunks = chunks

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.chunks)


class CleanupFailingStream:
    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter([{"delta": "partial"}])

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *_: object) -> None:
        raise RuntimeError("cleanup failed")


class CleanupFailingMessages:
    def create(self, **_: object) -> CleanupFailingStream:
        return CleanupFailingStream()


class CleanupFailingAnthropic:
    def __init__(self) -> None:
        self.messages = CleanupFailingMessages()


class StreamingMessages:
    def create(self, **kwargs: object) -> FakeStream:
        assert kwargs["stream"] is True
        return FakeStream([{"delta": "hello"}, {"delta": " world"}])


class StreamingAnthropic:
    def __init__(self) -> None:
        self.messages = StreamingMessages()


class FailingStream:
    def __iter__(self):  # type: ignore[no-untyped-def]
        yield {"delta": "partial"}
        raise RuntimeError("stream failed")


class FailingStreamingMessages:
    def create(self, **_: object) -> FailingStream:
        return FailingStream()


class FailingStreamingAnthropic:
    def __init__(self) -> None:
        self.messages = FailingStreamingMessages()


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


def test_anthropic_stream_is_captured_after_consumption() -> None:
    log = InMemoryEventLog()
    client = CapturedClient(None, "planner", AgentClock(), log, client=StreamingAnthropic())
    stream = client.messages.create(
        model="test-model",
        max_tokens=10,
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )
    assert len(log) == 0
    assert list(stream) == [{"delta": "hello"}, {"delta": " world"}]
    event = log.events()[0]
    assert event.event_type == "model_call"
    assert event.payload["stream"] is True
    assert event.payload["output"] == [{"delta": "hello"}, {"delta": " world"}]


def test_anthropic_stream_iteration_errors_are_captured() -> None:
    log = InMemoryEventLog()
    client = CapturedClient(
        None,
        "planner",
        AgentClock(),
        log,
        client=FailingStreamingAnthropic(),
    )
    stream = client.messages.create(
        model="test-model",
        max_tokens=10,
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )
    with pytest.raises(RuntimeError, match="stream failed"):
        list(stream)
    assert log.events()[0].event_type == "agent_error"
    assert log.events()[0].payload["stream"] is True


def test_anthropic_stream_close_records_abandoned_stream() -> None:
    log = InMemoryEventLog()
    client = CapturedClient(None, "planner", AgentClock(), log, client=StreamingAnthropic())
    stream = client.messages.create(
        model="test-model",
        max_tokens=10,
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )
    next(stream)
    stream.close()

    event = log.events()[0]
    assert event.event_type == "agent_error"
    assert event.payload["stream_status"] == "closed"


def test_anthropic_stream_cleanup_errors_are_captured() -> None:
    log = InMemoryEventLog()
    client = CapturedClient(
        None,
        "planner",
        AgentClock(),
        log,
        client=CleanupFailingAnthropic(),
    )
    stream = client.messages.create(
        model="test-model",
        max_tokens=10,
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )
    with pytest.raises(RuntimeError, match="cleanup failed"):
        with stream:
            next(stream)

    event = log.events()[0]
    assert event.event_type == "agent_error"
    assert event.payload["error"] == "cleanup failed"


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


def test_concurrent_same_tool_invocation_executes_underlying_tool_once() -> None:
    log = InMemoryEventLog()
    clock = AgentClock()
    start_barrier = Barrier(2)
    calls = 0

    @capture_tool
    def lookup(value: str) -> str:
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        return value

    def invoke() -> str:
        start_barrier.wait()
        return lookup(
            "x",
            agent_id="worker",
            clock=clock,
            log=log,
            invocation_id="concurrent-invocation",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result() for future in (pool.submit(invoke), pool.submit(invoke))]

    assert results == ["x", "x"]
    assert calls == 1
    assert [event.event_type for event in log.events()] == ["tool_call", "tool_result"]


def test_tool_retry_lookup_is_scoped_to_the_current_agent() -> None:
    log = InMemoryEventLog()
    calls = 0

    @capture_tool
    def lookup() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    assert lookup(agent_id="worker-a", clock=AgentClock(), log=log, invocation_id="shared") == "ok"
    assert lookup(agent_id="worker-b", clock=AgentClock(), log=log, invocation_id="shared") == "ok"
    assert calls == 2
    assert len(log) == 4


def test_configured_tool_can_accept_capture_context_named_arguments() -> None:
    log = InMemoryEventLog()

    @capture_tool(agent_id="trace-agent", clock=AgentClock(), log=log, run_id="trace-run")
    def inspect(
        agent_id: str,
        clock: str,
        log: str,
        run_id: str,
        causal_parent_ids: list[str],
        invocation_id: str,
    ) -> tuple[str, str, str, str, list[str], str]:
        return agent_id, clock, log, run_id, causal_parent_ids, invocation_id

    assert inspect(
        agent_id="function-agent",
        clock="function-clock",
        log="function-log",
        run_id="function-run",
        causal_parent_ids=["function-parent"],
        invocation_id="function-invocation",
    ) == (
        "function-agent",
        "function-clock",
        "function-log",
        "function-run",
        ["function-parent"],
        "function-invocation",
    )
    assert log.events()[0].agent_id == "trace-agent"


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
    assert events[1].payload["before_found"] is False
    assert events[1].payload["after"] == 42
    assert events[1].payload["after_found"] is True
    assert events[3].payload["operation"] == "delete"
    assert events[3].payload["before"] == 42
    assert events[3].payload["before_found"] is True
    assert events[3].payload["after_found"] is False

    memory.set("nullable", None)
    memory.set("nullable", 1)
    nullable_events = log.events()[-2:]
    assert nullable_events[0].payload["before_found"] is False
    assert nullable_events[0].payload["after_found"] is True
    assert nullable_events[1].payload["before"] is None
    assert nullable_events[1].payload["before_found"] is True


def test_concurrent_memory_writes_have_consistent_before_after_chain() -> None:
    from concurrent.futures import ThreadPoolExecutor

    log = InMemoryEventLog()
    memory = CapturedMemory(agent_id="worker", clock=AgentClock(), log=log)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda value: memory.set("answer", value), range(50)))

    writes = [event for event in log.events() if event.event_type == "memory_write"]
    assert len(writes) == 50
    for previous, current in zip(writes, writes[1:], strict=False):
        assert current.payload["before"] == previous.payload["after"]


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
    child_event, _ = record_event(
        agent_id=child.id,
        clock=child_clock,
        log=log,
        event_type="context_update",
        payload={"ready": True},
    )
    assert child_event.logical_seq == 2

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
    assert retry_clock.counter == child_event.logical_seq
    assert len(log) == 2


def test_spawn_requires_retry_identity_and_supports_key_only_retries() -> None:
    log = InMemoryEventLog()
    agents = InMemoryAgentStore()
    parent_clock = AgentClock()
    with pytest.raises(ValueError, match="requires child_agent_id or idempotency_key"):
        spawn_agent(
            parent_agent_id="planner",
            parent_clock=parent_clock,
            run_id="run",
            role="worker",
            log=log,
            agent_store=agents,
        )

    child, event, _ = spawn_agent(
        parent_agent_id="planner",
        parent_clock=parent_clock,
        run_id="run",
        role="worker",
        log=log,
        agent_store=agents,
        idempotency_key="spawn-request-1",
    )
    retry_child, retry_event, _ = spawn_agent(
        parent_agent_id="planner",
        parent_clock=parent_clock,
        run_id="run",
        role="worker",
        log=log,
        agent_store=agents,
        idempotency_key="spawn-request-1",
    )
    assert retry_child == child
    assert retry_event == event
    assert len(log) == 1

    with pytest.raises(ValueError, match="already exists with another spawn request"):
        spawn_agent(
            parent_agent_id="planner",
            parent_clock=parent_clock,
            run_id="run",
            role="worker",
            log=log,
            agent_store=agents,
            child_agent_id=child.id,
            idempotency_key="different-spawn-request",
        )
    assert len(log) == 1


def test_tool_errors_are_captured_and_re_raised() -> None:
    log = InMemoryEventLog()

    @capture_tool(agent_id="worker", clock=AgentClock(), log=log)
    def fail() -> None:
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        fail()
    assert [event.event_type for event in log.events()] == ["tool_call", "agent_error"]


class FailingCursor:
    def __enter__(self) -> FailingCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, *_: object) -> None:
        raise RuntimeError("insert failed")


class FailingConnection:
    def __init__(self) -> None:
        self.rollback_called = False

    def cursor(self) -> FailingCursor:
        return FailingCursor()

    def commit(self) -> None:
        raise AssertionError("commit must not run after insert failure")

    def rollback(self) -> None:
        self.rollback_called = True


def test_postgres_append_rolls_back_failed_transactions() -> None:
    connection = FailingConnection()
    store = PostgresEventStore(connection)
    event = Event(
        id=str(uuid4()),
        run_id=str(uuid4()),
        agent_id=str(uuid4()),
        logical_seq=1,
        event_type="context_update",
        payload={},
    )
    with pytest.raises(RuntimeError, match="insert failed"):
        store.append(event)
    assert connection.rollback_called


def test_postgres_append_rejects_non_uuid_identifiers_before_sql() -> None:
    store = PostgresEventStore(FailingConnection())
    event = Event(
        run_id=str(uuid4()),
        agent_id="planner",
        logical_seq=1,
        event_type="context_update",
        payload={},
    )
    with pytest.raises(ValueError, match="Event.agent_id must be a UUID"):
        store.append(event)
