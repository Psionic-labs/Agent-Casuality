"""Tests for Phase 2.5: Decision SCM Contract, Resource Invariants, and Validator."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from core.decision import (
    AblationStrategy,
    DecisionContract,
    DecisionPort,
    create_decision_contract,
    create_fixture_decision,
)
from core.validator import GraphValidator
from sdk.events import AgentClock, Event, InMemoryEventLog, record_event
from sdk.memory import CapturedMemory, ResourceRegistry
from sdk.privacy import IDENTITY_REDACTOR, PayloadRedactor, make_fail_open_append
from sdk.tools import capture_tool

# --- 1. ResourceRegistry Tests ---


def test_resource_registry_registers_monotonic_versions() -> None:
    registry = ResourceRegistry()
    r1 = registry.register_write(
        resource_uri="mem://agent_B/status",
        writer_event_id="ev_b1",
        writer_agent_id="B",
        logical_seq=2,
    )
    assert r1.version == 1
    assert r1.last_writer_event_id == "ev_b1"

    r2 = registry.register_write(
        resource_uri="mem://agent_B/status",
        writer_event_id="ev_b2",
        writer_agent_id="B",
        logical_seq=4,
    )
    assert r2.version == 2
    assert r2.last_writer_event_id == "ev_b2"
    assert registry.get_latest("mem://agent_B/status") == r2


def test_resource_registry_is_thread_safe_under_concurrency() -> None:
    registry = ResourceRegistry()
    num_threads = 8
    writes_per_thread = 50

    def worker(thread_idx: int) -> None:
        for i in range(writes_per_thread):
            registry.register_write(
                resource_uri=f"mem://shared/key_{thread_idx % 4}",
                writer_event_id=f"ev_{thread_idx}_{i}",
                writer_agent_id=f"agent_{thread_idx}",
                logical_seq=i + 1,
            )

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, t) for t in range(num_threads)]
        for f in futures:
            f.result()

    resources = registry.all_resources()
    total_versions = sum(r.version for r in resources.values())
    assert total_versions == num_threads * writes_per_thread


def test_resource_registry_hydrates_from_event_stream() -> None:
    events = [
        Event(
            id="ev_1",
            agent_id="B",
            logical_seq=1,
            event_type="memory_write",
            payload={"key": "customer_status", "after": "eligible"},
        ),
        Event(
            id="ev_2",
            agent_id="C",
            logical_seq=2,
            event_type="tool_result",
            payload={"tool": "write_patch", "resource_uri": "file:///workspace/diff.patch"},
        ),
        Event(
            id="ev_3",
            agent_id="B",
            logical_seq=3,
            event_type="memory_write",
            payload={"key": "customer_status", "after": "ineligible"},
        ),
    ]

    registry = ResourceRegistry()
    registry.hydrate_from_events(events)

    status_entry = registry.get_latest("mem://shared/customer_status")
    assert status_entry is not None
    assert status_entry.version == 2
    assert status_entry.last_writer_event_id == "ev_3"

    file_entry = registry.get_latest("file:///workspace/diff.patch")
    assert file_entry is not None
    assert file_entry.version == 1
    assert file_entry.last_writer_event_id == "ev_2"


# --- 2. CapturedMemory Implicit Causal Edge Auto-Injection ---


def test_captured_memory_auto_injects_prior_writer_dependency() -> None:
    log = InMemoryEventLog()
    registry = ResourceRegistry()
    shared_store: dict[str, Any] = {}
    clock_b = AgentClock()
    clock_c = AgentClock()

    mem_b = CapturedMemory(
        agent_id="B", clock=clock_b, log=log, store=shared_store, registry=registry, run_id="run_1"
    )
    mem_c = CapturedMemory(
        agent_id="C", clock=clock_c, log=log, store=shared_store, registry=registry, run_id="run_1"
    )

    # Agent B writes to shared key "policy_limit"
    mem_b.set("policy_limit", 5000)
    write_events = [e for e in log.events() if e.event_type == "memory_write" and e.agent_id == "B"]
    assert len(write_events) == 1
    b_write_id = write_events[0].id

    # Agent C reads "policy_limit" without specifying explicit causal_parent_ids
    val = mem_c.get("policy_limit")
    assert val == 5000

    read_events = [e for e in log.events() if e.event_type == "memory_read" and e.agent_id == "C"]
    assert len(read_events) == 1
    c_read_event = read_events[0]

    # Invariant holds: C's read automatically captured B's write as a causal parent
    assert c_read_event.causal_parent_ids == [b_write_id]


def test_captured_memory_with_custom_resource_uri() -> None:
    log = InMemoryEventLog()
    registry = ResourceRegistry()
    shared_store: dict[str, Any] = {}
    clock_b = AgentClock()
    clock_c = AgentClock()

    mem_b = CapturedMemory(
        agent_id="B", clock=clock_b, log=log, store=shared_store, registry=registry
    )
    mem_c = CapturedMemory(
        agent_id="C", clock=clock_c, log=log, store=shared_store, registry=registry
    )

    custom_uri = "db://orders/order_9981"
    mem_b.set("order", {"status": "paid"}, resource_uri=custom_uri)
    b_write_event = log.events()[-1]

    # C reads with the same custom resource_uri
    val = mem_c.get("order", resource_uri=custom_uri)
    assert val == {"status": "paid"}
    c_read_event = log.events()[-1]

    assert c_read_event.causal_parent_ids == [b_write_event.id]


# --- 3. AgentClock & Intra-Agent Auto-Chaining ---


def test_agent_clock_tracks_last_event_id_and_auto_chains() -> None:
    clock = AgentClock()
    log = InMemoryEventLog()

    e1, _ = record_event(agent_id="A", clock=clock, log=log, event_type="step1", payload={})
    assert clock.get_last_event_id() == e1.id

    e2, _ = record_event(
        agent_id="A", clock=clock, log=log, event_type="step2", payload={}, auto_chain=True
    )
    assert clock.get_last_event_id() == e2.id
    assert e2.causal_parent_ids == [e1.id]


# --- 4. DecisionContract & Semantic Ports ---


def test_decision_contract_serialization_roundtrip() -> None:
    port_1 = DecisionPort(
        port_id="eligibility_flag",
        source_event_id="B3",
        field_path="output.customer_status",
        recorded_value="eligible",
        baseline_value="ineligible",
        strategy=AblationStrategy.CANONICAL_BASELINE,
        description="Eligibility report from researcher",
    )
    port_2 = DecisionPort(
        port_id="risk_metric",
        source_event_id="C3",
        field_path="output.risk_score",
        recorded_value=0.15,
        baseline_value=0.90,
        strategy=AblationStrategy.CANONICAL_BASELINE,
    )

    contract = create_decision_contract(
        decision_id="dec_42",
        run_id="run_100",
        agent_id="A",
        decision_event_id="A3",
        ports=[port_1, port_2],
        decision_type="policy_check",
        policy_version="v2.1",
        outcome="failure",
        metadata={"reviewer": "audit_engine"},
    )

    data = contract.to_dict()
    restored = DecisionContract.from_dict(data)

    assert restored.decision_id == "dec_42"
    assert len(restored.ports) == 2
    assert restored.get_port("eligibility_flag") == port_1
    assert restored.get_port("risk_metric") == port_2
    assert restored == contract


def test_decision_contract_embedded_in_event_payload() -> None:
    contract = create_decision_contract(
        decision_id="dec_01",
        run_id="run_1",
        agent_id="A",
        decision_event_id="A3",
        ports=[],
        decision_type="merge",
    )

    payload = contract.to_event_payload({"action": "evaluate"})
    assert "decision_contract" in payload
    assert payload["action"] == "evaluate"

    event = Event(
        id="A3",
        agent_id="A",
        logical_seq=5,
        event_type="tool_call",
        payload=payload,
    )

    extracted = DecisionContract.from_event(event)
    assert extracted is not None
    assert extracted.decision_id == "dec_01"


def test_fixture_decision_matches_ground_truth_merge() -> None:
    contract = create_fixture_decision()
    assert contract.decision_event_id == "A3"
    assert len(contract.ports) == 2

    port_b = contract.get_port("customer_status")
    assert port_b is not None
    assert port_b.source_event_id == "B3"
    assert port_b.recorded_value == "eligible"
    assert port_b.baseline_value == "ineligible"

    port_c = contract.get_port("risk_score")
    assert port_c is not None
    assert port_c.source_event_id == "C3"
    assert port_c.recorded_value == 0.2
    assert port_c.baseline_value == 0.8


# --- 5. GraphValidator Tests ---


def build_seeded_fixture_log() -> InMemoryEventLog:
    fixture_path = Path(__file__).parent.parent / "fixture" / "fixture.json"
    with fixture_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    log = InMemoryEventLog()
    for ev_data in data["events"]:
        log.append(
            Event(
                id=ev_data["id"],
                agent_id=ev_data["agent_id"],
                logical_seq=ev_data["logical_seq"],
                event_type=ev_data["event_type"],
                payload=ev_data.get("payload", {}),
                causal_parent_ids=ev_data.get("causal_parent_ids", []),
                run_id=data["run"]["id"],
            )
        )
    return log


def test_validator_passes_on_valid_fixture_run() -> None:
    log = build_seeded_fixture_log()
    validator = GraphValidator(log)
    decision = create_fixture_decision()

    report = validator.validate_run(run_id="run_7f42", decisions=[decision])
    assert report.is_valid is True
    assert len(report.violations) == 0
    assert report.details["violation_count"] == 0


def test_validator_catches_dangling_causal_parent() -> None:
    log = build_seeded_fixture_log()
    # Inject an event declaring a non-existent parent
    log.append(
        Event(
            id="bad_event",
            agent_id="A",
            logical_seq=10,
            event_type="test",
            payload={},
            causal_parent_ids=["phantom_parent_999"],
            run_id="run_7f42",
        )
    )

    validator = GraphValidator(log)
    dangling = validator.check_dangling_parents(run_id="run_7f42")
    assert len(dangling) == 1
    assert "phantom_parent_999" in dangling[0]

    report = validator.validate_run(run_id="run_7f42")
    assert report.is_valid is False
    assert any("phantom_parent_999" in v for v in report.violations)


def test_validator_catches_cross_run_edge_violation() -> None:
    log = build_seeded_fixture_log()
    # Add an event in run_other
    log.append(
        Event(
            id="foreign_event",
            agent_id="X",
            logical_seq=1,
            event_type="init",
            payload={},
            run_id="run_other",
        )
    )
    # Add an event in run_7f42 referencing the foreign event
    log.append(
        Event(
            id="leaking_event",
            agent_id="A",
            logical_seq=10,
            event_type="merge",
            payload={},
            causal_parent_ids=["foreign_event"],
            run_id="run_7f42",
        )
    )

    validator = GraphValidator(log)
    cross_run = validator.check_cross_run_isolation(run_id="run_7f42")
    assert len(cross_run) == 1
    assert "run_other" in cross_run[0]

    report = validator.validate_run(run_id="run_7f42")
    assert report.is_valid is False


def test_validator_catches_lamport_sequence_violation() -> None:
    log = InMemoryEventLog()
    # Parent has logical_seq 5
    log.append(Event(id="parent_ev", agent_id="A", logical_seq=5, event_type="write", payload={}))
    # Child erroneously has logical_seq 3 (less than parent)
    log.append(
        Event(
            id="child_ev",
            agent_id="A",
            logical_seq=3,
            event_type="read",
            payload={},
            causal_parent_ids=["parent_ev"],
        )
    )

    validator = GraphValidator(log)
    violations, _ = validator.check_intra_agent_continuity()
    assert len(violations) >= 1
    assert any("Lamport progression violated" in v for v in violations)


def test_validator_catches_decision_port_unreachable_source() -> None:
    log = build_seeded_fixture_log()
    validator = GraphValidator(log)

    # Port source D1 is on background agent D, not reachable from A3
    invalid_contract = create_decision_contract(
        decision_id="invalid_dec",
        run_id="run_7f42",
        agent_id="A",
        decision_event_id="A3",
        ports=[
            DecisionPort(
                port_id="unrelated_metric",
                source_event_id="D1",
                field_path="payload.action",
                recorded_value="log_heartbeat",
                baseline_value="none",
            )
        ],
    )

    violations, _ = validator.check_decision_ports(invalid_contract)
    assert len(violations) == 1
    assert "not an ancestor of decision event 'A3'" in violations[0]


# --- 6. Privacy: PayloadRedactor ---


def test_payload_redactor_strips_builtin_sensitive_keys() -> None:
    redactor = PayloadRedactor()
    payload = {"api_key": "sk-secret", "action": "enroll", "token": "bearer-xyz"}
    safe = redactor.redact(payload)

    assert safe["api_key"] == "[REDACTED]"
    assert safe["token"] == "[REDACTED]"
    assert safe["action"] == "enroll"  # non-sensitive key preserved


def test_payload_redactor_merges_extra_keys() -> None:
    redactor = PayloadRedactor(extra_keys={"ssn", "dob"}, redaction_marker="***")
    payload = {"ssn": "123-45-6789", "dob": "1990-01-01", "name": "Alice"}
    safe = redactor.redact(payload)

    assert safe["ssn"] == "***"
    assert safe["dob"] == "***"
    assert safe["name"] == "Alice"
    assert redactor.is_sensitive("ssn") is True
    assert redactor.is_sensitive("name") is False


def test_identity_redactor_is_a_passthrough() -> None:
    payload = {"api_key": "sk-secret", "value": 42}
    assert IDENTITY_REDACTOR.redact(payload) is payload  # same object, no copy
    assert IDENTITY_REDACTOR.sensitive_keys == frozenset()


# --- 7. Privacy: make_fail_open_append ---


def test_make_fail_open_append_swallows_storage_errors(capsys: Any) -> None:
    log = InMemoryEventLog()

    # Patch append to always raise
    def _bad_append(event: Any) -> Any:
        raise RuntimeError("disk full")

    log.append = _bad_append  # type: ignore

    fail_open_log = make_fail_open_append(log)
    clock = AgentClock()

    # Should NOT raise even though the underlying append explodes
    event, _ = record_event(
        agent_id="A",
        clock=clock,
        log=fail_open_log,
        event_type="test",
        payload={"x": 1},
    )
    assert event is not None  # original event returned unchanged

    captured = capsys.readouterr()
    assert "fail_open=True" in captured.err
    assert "disk full" in captured.err


# --- 8. capture_tool registry wiring ---


def test_capture_tool_registers_resource_uri_in_registry() -> None:
    log = InMemoryEventLog()
    registry = ResourceRegistry()
    clock = AgentClock()

    @capture_tool
    def write_patch(content: str) -> str:
        return f"patch:{content}"

    write_patch(
        "diff --git a/x",
        agent_id="C",
        clock=clock,
        log=log,
        registry=registry,
        resource_uri="file:///workspace/changes.patch",
    )

    entry = registry.get_latest("file:///workspace/changes.patch")
    assert entry is not None
    assert entry.last_writer_agent_id == "C"

    # Verify the tool_result event embeds the resource_uri in its payload
    result_events = [e for e in log.events() if e.event_type == "tool_result"]
    assert len(result_events) == 1
    assert result_events[0].payload["resource_uri"] == "file:///workspace/changes.patch"


def test_capture_tool_reader_auto_injects_tool_result_as_causal_parent() -> None:
    """A memory read after a cross-agent tool write inherits the tool_result event."""
    log = InMemoryEventLog()
    registry = ResourceRegistry()
    shared_store: dict[str, Any] = {}
    clock_c = AgentClock()
    clock_d = AgentClock()

    @capture_tool
    def generate_report() -> str:
        return "report_v1"

    generate_report(
        agent_id="C",
        clock=clock_c,
        log=log,
        registry=registry,
        resource_uri="mem://shared/report",
    )
    tool_result_id = next(e for e in log.events() if e.event_type == "tool_result").id

    # Agent D writes to shared store with the same key as the resource_uri prefix
    mem_d = CapturedMemory(
        agent_id="D", clock=clock_d, log=log, store=shared_store, registry=registry
    )
    # Manually register the tool write under the shared key so the memory lookup works
    registry.register_write(
        resource_uri="mem://shared/report",
        writer_event_id=tool_result_id,
        writer_agent_id="C",
        logical_seq=1,
    )
    mem_d.get("report", resource_uri="mem://shared/report")

    d_read = next(e for e in log.events() if e.event_type == "memory_read" and e.agent_id == "D")
    assert tool_result_id in d_read.causal_parent_ids
