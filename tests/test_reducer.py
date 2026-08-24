"""Phase 3 property tests: state reconstruction invariants (thesis section 30.3).

The first four tests are the ones the implementation plan names explicitly;
they encode the invariants every later phase silently depends on. The
remaining tests cover one match arm per event type and the integrity check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from core.graph import record_causal_event
from core.reducer import (
    AgentState,
    ReplayIntegrityError,
    canonical_json,
    hash_state,
    iter_agent_events,
    reconstruct,
    reduce,
    verify_snapshot,
)
from core.snapshots import (
    InMemorySnapshotStore,
    SnapshotManager,
    create_snapshot,
)
from sdk.events import AgentClock, Event, InMemoryEventLog, record_event
from sdk.lifecycle import InMemoryAgentStore, spawn_agent
from sdk.memory import CapturedMemory, ResourceRegistry

RUN_ID = "run_phase3"


@dataclass
class SeededRun:
    """A small planner/two-worker/background-monitor run captured via the SDK."""

    log: InMemoryEventLog
    clocks: dict[str, AgentClock]
    event_ids: dict[str, str] = field(default_factory=dict)


def _seeded_run() -> SeededRun:
    log = InMemoryEventLog()
    clocks = {"A": AgentClock(), "B": AgentClock(), "C": AgentClock(), "D": AgentClock()}
    agents = InMemoryAgentStore()
    ids: dict[str, str] = {}

    a1, _ = record_event(
        agent_id="A",
        clock=clocks["A"],
        log=log,
        event_type="model_call",
        payload={"action": "plan_task"},
        run_id=RUN_ID,
    )
    ids["A1"] = a1.id

    _, _, clock_b = spawn_agent(
        parent_agent_id="A",
        parent_clock=clocks["A"],
        run_id=RUN_ID,
        role="researcher",
        log=log,
        agent_store=agents,
        causal_parent_ids=[a1.id],
        child_agent_id="B",
    )
    clocks["B"] = clock_b
    _, _, clock_c = spawn_agent(
        parent_agent_id="A",
        parent_clock=clocks["A"],
        run_id=RUN_ID,
        role="coder",
        log=log,
        agent_store=agents,
        causal_parent_ids=[a1.id],
        child_agent_id="C",
    )
    clocks["C"] = clock_c

    b_memory = CapturedMemory(
        agent_id="B", clock=clocks["B"], log=log, run_id=RUN_ID, registry=ResourceRegistry()
    )
    b_model, _ = record_event(
        agent_id="B",
        clock=clocks["B"],
        log=log,
        event_type="model_call",
        payload={"action": "start_research"},
        causal_parent_ids=[ids["A1"]],
        run_id=RUN_ID,
    )
    b_call, _ = record_event(
        agent_id="B",
        clock=clocks["B"],
        log=log,
        event_type="tool_call",
        payload={"invocation_id": "inv-b-search", "tool": "search"},
        causal_parent_ids=[b_model.id],
        idempotency_key="inv-b-search",
        run_id=RUN_ID,
    )
    b_result, _ = record_event(
        agent_id="B",
        clock=clocks["B"],
        log=log,
        event_type="tool_result",
        payload={
            "invocation_id": "inv-b-search",
            "tool": "search",
            "output": {"customer_status": "eligible"},
        },
        causal_parent_ids=[b_call.id],
        idempotency_key="inv-b-search:result",
        run_id=RUN_ID,
    )
    b_memory.set("customer_status", "eligible")
    ids["B3"] = b_result.id

    c_memory = CapturedMemory(
        agent_id="C", clock=clocks["C"], log=log, run_id=RUN_ID, registry=ResourceRegistry()
    )
    c_memory.set("risk_score", 0.2)
    c_writer = c_memory.registry.get_latest("mem://C/risk_score", run_id=RUN_ID)
    assert c_writer is not None

    merge, _ = record_event(
        agent_id="A",
        clock=clocks["A"],
        log=log,
        event_type="tool_call",
        payload={"action": "combine_results", "transform": "policy_check_v2"},
        causal_parent_ids=[b_result.id, c_writer.last_writer_event_id],
        run_id=RUN_ID,
    )
    ids["A3"] = merge.id
    finish, _ = record_event(
        agent_id="A",
        clock=clocks["A"],
        log=log,
        event_type="agent_finish",
        payload={"final_answer": "approved", "status": "failure"},
        causal_parent_ids=[merge.id],
        run_id=RUN_ID,
    )
    ids["A4"] = finish.id

    d1, _ = record_event(
        agent_id="D",
        clock=clocks["D"],
        log=log,
        event_type="model_call",
        payload={"action": "log_heartbeat"},
        run_id=RUN_ID,
    )
    ids["D1"] = d1.id
    return SeededRun(log=log, clocks=clocks, event_ids=ids)


@pytest.fixture
def seeded_run() -> SeededRun:
    return _seeded_run()


# --- the four property tests from the implementation plan -------------------


def test_replaying_a_prefix_twice_is_stable(seeded_run: SeededRun) -> None:
    b_event = seeded_run.log.get(seeded_run.event_ids["B3"])
    assert b_event is not None
    b_seq = b_event.logical_seq
    state_1 = reconstruct("B", b_seq, log=seeded_run.log)
    state_2 = reconstruct("B", b_seq, log=seeded_run.log)
    assert state_1 == state_2


def test_unrelated_event_does_not_change_another_agents_state(seeded_run: SeededRun) -> None:
    c_seq = seeded_run.clocks["C"].current()
    before = reconstruct("C", c_seq, log=seeded_run.log)
    record_event(
        agent_id="B",
        clock=seeded_run.clocks["B"],
        log=seeded_run.log,
        event_type="memory_write",
        payload={"operation": "set", "key": "noise", "after": "unrelated", "after_found": True},
        run_id=RUN_ID,
    )
    after = reconstruct("C", c_seq, log=seeded_run.log)
    assert before == after


def test_causal_parent_must_exist_before_being_referenced(seeded_run: SeededRun) -> None:
    # The parent-validated capture path is core.graph.record_causal_event;
    # dangling references are rejected before a sequence is ever allocated.
    with pytest.raises(ValueError, match="does not exist"):
        record_causal_event(
            agent_id="A",
            clock=seeded_run.clocks["A"],
            log=seeded_run.log,
            event_type="tool_call",
            payload={},
            causal_parents=["does_not_exist"],
            run_id=RUN_ID,
        )


def test_snapshot_hash_matches_reconstruction() -> None:
    log = InMemoryEventLog()
    clock = AgentClock()
    for i in range(30):
        record_event(
            agent_id="B",
            clock=clock,
            log=log,
            event_type="memory_write",
            payload={"operation": "set", "key": f"k{i}", "after": i, "after_found": True},
            run_id=RUN_ID,
        )
    snapshot = create_snapshot(agent_id="B", logical_seq=25, log=log, run_id=RUN_ID)
    reconstructed = reconstruct("B", 25, log=log)
    assert hash_state(reconstructed) == snapshot.state_hash
    verify_snapshot(snapshot, log=log)

    store = InMemorySnapshotStore()
    store.save(snapshot)
    shortcut = reconstruct("B", 30, log=log, snapshots=store)
    assert shortcut == reconstruct("B", 30, log=log)
    assert shortcut.memory == {f"k{i}": i for i in range(30)}


# --- reducer arms, one per event type ---------------------------------------


def _event(event_type: str, payload: dict[str, Any], *, seq: int = 1, **kwargs: Any) -> Event:
    return Event(
        agent_id=kwargs.pop("agent_id", "X"),
        logical_seq=kwargs.pop("logical_seq", seq),
        event_type=event_type,
        payload=payload,
        **kwargs,
    )


@pytest.mark.parametrize(
    "event_type",
    ["model_call", "memory_read", "agent_spawn", "run_start", "run_finish"],
)
def test_noop_arms_leave_state_unchanged(event_type: str) -> None:
    event = _event(event_type, {"anything": "goes"})
    assert reduce(AgentState.empty(), event) == AgentState.empty()


def test_context_update_replaces_context() -> None:
    state = reduce(AgentState.empty(), _event("context_update", {"context": {"task": "audit"}}))
    assert state.context == {"task": "audit"}


def test_agent_finish_sets_status_with_default_and_override() -> None:
    finished = reduce(AgentState.empty(), _event("agent_finish", {}))
    assert finished.status == "completed"
    failed = reduce(AgentState.empty(), _event("agent_finish", {"status": "failure"}))
    assert failed.status == "failure"


def test_agent_error_sets_error_status() -> None:
    state = reduce(AgentState.empty(), _event("agent_error", {"error": "boom"}))
    assert state.status == "error"


def test_tool_pair_opens_and_closes_by_invocation_id_and_records_output() -> None:
    call = _event("tool_call", {"invocation_id": "inv-1", "tool": "search"}, seq=1)
    opened = reduce(AgentState.empty(), call)
    assert opened.open_tools == {"inv-1": call.id}

    result = _event(
        "tool_result",
        {"invocation_id": "inv-1", "tool": "search", "output": {"ok": True}},
        seq=2,
        causal_parent_ids=[call.id],
    )
    closed = reduce(opened, result)
    assert closed.open_tools == {}
    assert closed.tool_outputs == {"inv-1": {"ok": True}}


def test_tool_result_without_invocation_id_closes_causal_parent_call() -> None:
    call = _event("tool_call", {"tool": "search"}, seq=1)
    opened = reduce(AgentState.empty(), call)
    result = _event(
        "tool_result",
        {"tool": "search", "output": {"customer_status": "eligible"}},
        seq=2,
        causal_parent_ids=[call.id],
    )
    closed = reduce(opened, result)
    assert closed.open_tools == {}
    assert closed.tool_outputs == {call.id: {"customer_status": "eligible"}}


def test_memory_write_set_then_delete_round_trip() -> None:
    state = reduce(AgentState.empty(), _event("memory_write", {
        "operation": "set", "key": "status", "after": "eligible", "after_found": True
    }))
    assert state.memory == {"status": "eligible"}
    state = reduce(state, _event("memory_write", {
        "operation": "delete", "key": "status", "after": None, "after_found": False
    }, seq=2))
    assert state.memory == {}


@pytest.mark.parametrize(
    "payload",
    [{"after": "value"}, {"operation": "set", "after": "v"}],
)
def test_memory_write_without_key_fails_closed(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="no usable key"):
        reduce(AgentState.empty(), _event("memory_write", payload))


def test_memory_write_without_after_fails_closed() -> None:
    with pytest.raises(ValueError, match="not interpretable"):
        reduce(AgentState.empty(), _event("memory_write", {"operation": "set", "key": "k"}))


def test_unknown_event_type_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown event_type"):
        reduce(AgentState.empty(), _event("teleport", {}))


def test_canonical_json_is_insertion_order_independent() -> None:
    first = AgentState(memory={"a": 1, "b": 2}, open_tools={"t": "e1"})
    second = AgentState(memory={"b": 2, "a": 1}, open_tools={"t": "e1"})
    assert canonical_json(first) == canonical_json(second)
    assert hash_state(first) == hash_state(second)


def test_iter_agent_events_filters_range_and_sorts() -> None:
    log = InMemoryEventLog()
    clock = AgentClock()
    written: list[Event] = []
    for i in range(10):
        event, _ = record_event(
            agent_id="B",
            clock=clock,
            log=log,
            event_type="memory_write",
            payload={"operation": "set", "key": f"k{i}", "after": i, "after_found": True},
            run_id=RUN_ID,
        )
        written.append(event)
    record_event(
        agent_id="C",
        clock=AgentClock(),
        log=log,
        event_type="memory_write",
        payload={"operation": "set", "key": "x", "after": 1, "after_found": True},
        run_id=RUN_ID,
    )

    window = iter_agent_events(log, "B", since=written[2].logical_seq, until=written[5].logical_seq)
    assert [event.logical_seq for event in window] == [
        written[i].logical_seq for i in range(3, 6)
    ]
    shuffled = iter_agent_events(log, "B")
    assert [event.logical_seq for event in shuffled] == sorted(
        event.logical_seq for event in shuffled
    )


def test_verify_snapshot_detects_tampered_state_and_hash() -> None:
    log = InMemoryEventLog()
    clock = AgentClock()
    for i in range(5):
        record_event(
            agent_id="B",
            clock=clock,
            log=log,
            event_type="memory_write",
            payload={"operation": "set", "key": f"k{i}", "after": i, "after_found": True},
            run_id=RUN_ID,
        )
    snapshot = create_snapshot(agent_id="B", logical_seq=5, log=log, run_id=RUN_ID)
    verify_snapshot(snapshot, log=log)

    tampered_state = create_snapshot(agent_id="B", logical_seq=5, log=log, run_id=RUN_ID)
    object.__setattr__(  # simulate storage corruption of the state blob
        tampered_state,
        "state",
        {**tampered_state.state, "memory": {"injected": True}},
    )
    with pytest.raises(ReplayIntegrityError):
        verify_snapshot(tampered_state, log=log)

    from dataclasses import replace as dc_replace

    tampered_hash = dc_replace(snapshot, state_hash="0" * 64)
    with pytest.raises(ReplayIntegrityError):
        verify_snapshot(tampered_hash, log=log)


def test_snapshot_manager_observes_interval_boundaries() -> None:
    log = InMemoryEventLog()
    clock = AgentClock()
    store = InMemorySnapshotStore()
    manager = SnapshotManager(log=log, store=store, interval=8, run_id=RUN_ID)

    created: list[Any] = []
    last_event: Event | None = None
    for i in range(20):
        last_event, _ = record_event(
            agent_id="B",
            clock=clock,
            log=log,
            event_type="memory_write",
            payload={"operation": "set", "key": f"k{i}", "after": i, "after_found": True},
            run_id=RUN_ID,
        )
        record = manager.observe(last_event)
        if record is not None:
            created.append(record)

    assert [snapshot.logical_seq for snapshot in created] == [8, 16]
    assert len(store) == 2
    assert manager.observe(last_event, force=True) is not None
    assert len(store) == 3
    with pytest.raises(ValueError):
        SnapshotManager(log=log, store=store, interval=0)
