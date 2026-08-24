"""Phase 3 slicing tests: structural slice membership and decision evidence.

The fixture scenario is treated as a permanent contract test (implementation
plan, closing advice): ``structural_slice(A4)`` must return exactly the nine
events fixture.json declares, excluding the unrelated background agent D.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from core.decision import (
    AblationStrategy,
    DecisionContract,
    DecisionPort,
    create_decision_contract,
)
from core.slicing import deep_get, structural_slice, why
from sdk.events import Event, InMemoryEventLog

FIXTURE_PATH = Path(__file__).parent.parent / "fixture" / "fixture.json"

EXPECTED_A4_ORDER = ("A1", "B1", "C1", "B2", "C2", "B3", "C3", "A3", "A4")


class FixtureEventLog(InMemoryEventLog):
    """InMemoryEventLog preloaded with fixture.json, IDs preserved."""

    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__()
        self.data = data
        self.agents = {agent["id"]: agent for agent in data["agents"]}
        self.run_info = data["run"]
        for record in data["events"]:
            self.append(
                Event(
                    id=record["id"],
                    agent_id=record["agent_id"],
                    logical_seq=record["logical_seq"],
                    event_type=record["event_type"],
                    payload=record["payload"],
                    causal_parent_ids=list(record["causal_parent_ids"]),
                    run_id=data["run"]["id"],
                )
            )


def load_fixture_log(**overrides: Any) -> FixtureEventLog:
    """Load fixture.json, applying ``{event_id: payload_patch}`` overrides."""
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    patches = overrides.pop("event_payloads", {})
    for record in data["events"]:
        patch = patches.get(record["id"])
        if patch:
            record["payload"] = {**record["payload"], **patch}
    return FixtureEventLog(data)


def _approval_contract(fixture_log: FixtureEventLog, **port_overrides: Any) -> DecisionContract:
    ports = [
        DecisionPort(
            port_id="customer_status",
            source_event_id="B3",
            field_path="output.customer_status",
            recorded_value="eligible",
            baseline_value="ineligible",
            strategy=AblationStrategy.CANONICAL_BASELINE,
        ),
        DecisionPort(
            port_id="risk_score",
            source_event_id="C3",
            field_path="output.risk_score",
            recorded_value=0.2,
            baseline_value=0.8,
            strategy=AblationStrategy.CANONICAL_BASELINE,
        ),
    ]
    return create_decision_contract(
        decision_id="dec_customer_approval_A3",
        run_id=fixture_log.run_info["id"],
        agent_id="A",
        decision_event_id="A3",
        decision_type="policy_merge",
        outcome="failure",
        ports=ports if not port_overrides else port_overrides["ports"],
    )


class SimulatedSqlLog:
    """Exposes an ``ancestors`` method like PostgresEventStore does."""

    def __init__(self, inner: FixtureEventLog) -> None:
        self.inner = inner

    def get(self, event_id: str) -> Event | None:
        return self.inner.get(event_id)

    def ancestors(self, event_id: str) -> list[str]:
        visited: set[str] = set()
        queue: list[str] = [event_id]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            event = self.inner.get(current)
            if event is None:
                raise ValueError(f"event {current} does not exist")
            queue.extend(event.causal_parent_ids)
        return _sorted_ids(self.inner, visited)


def _sorted_ids(log: FixtureEventLog, ids: Iterable[str]) -> list[str]:
    def order_key(event_id: str) -> tuple[int, str, str]:
        event = log.get(event_id)
        return (event.logical_seq, event.agent_id, event.id) if event else (0, "", event_id)

    return sorted(ids, key=order_key)


@pytest.fixture
def fixture_log() -> FixtureEventLog:
    return load_fixture_log()


# --- structural slice --------------------------------------------------------


def test_slice_a4_returns_exactly_the_fixture_nine(fixture_log: FixtureEventLog) -> None:
    ground_truth = set(fixture_log.data["ground_truth"]["structural_slice"])
    slice_result = structural_slice("A4", fixture_log)

    assert len(slice_result) == 9
    assert set(slice_result.event_ids) == ground_truth
    assert {"D1", "D2", "D3"}.isdisjoint(slice_result.event_ids)
    assert "A4" in slice_result  # root is always included
    assert slice_result.source == "python_bfs"
    assert slice_result.to_dict()["note"].startswith("structural evidence only")


def test_slice_ordering_is_deterministic(fixture_log: FixtureEventLog) -> None:
    assert structural_slice("A4", fixture_log).event_ids == EXPECTED_A4_ORDER


def test_sql_recursive_path_preferred_when_store_provides_ancestors(
    fixture_log: FixtureEventLog,
) -> None:
    slice_result = structural_slice("A4", SimulatedSqlLog(fixture_log))
    assert slice_result.source == "sql_recursive"
    assert slice_result.event_ids == EXPECTED_A4_ORDER


def test_missing_root_event_raises(fixture_log: FixtureEventLog) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        structural_slice("NOPE", fixture_log)


def test_dangling_parent_during_traversal_raises() -> None:
    log = InMemoryEventLog()
    log.append(
        Event(
            id="orphan",
            agent_id="X",
            logical_seq=1,
            event_type="model_call",
            payload={},
            causal_parent_ids=["ghost"],
        )
    )
    with pytest.raises(ValueError, match="ghost"):
        structural_slice("orphan", log)


def test_cyclic_parents_terminate() -> None:
    log = InMemoryEventLog()
    log.append(
        Event(id="x1", agent_id="X", logical_seq=1, event_type="model_call", payload={},
              causal_parent_ids=["x2"])
    )
    log.append(
        Event(id="x2", agent_id="X", logical_seq=2, event_type="model_call", payload={},
              causal_parent_ids=["x1"])
    )
    slice_result = structural_slice("x1", log)
    assert set(slice_result.event_ids) == {"x1", "x2"}


# --- path resolution ---------------------------------------------------------


def test_deep_get_resolves_nested_paths_and_misses_gracefully() -> None:
    payload = {"output": {"customer_status": "eligible"}, "n": 42}
    assert deep_get(payload, "output.customer_status") == (True, "eligible")
    assert deep_get(payload, "output.missing") == (False, None)
    assert deep_get(payload, "output.customer_status.deeper") == (False, None)
    assert deep_get(payload, "n") == (True, 42)
    assert deep_get("scalar", "path") == (False, None)


# --- decision evidence (why) --------------------------------------------------


def test_why_resolves_semantic_ports_against_recorded_payloads(
    fixture_log: FixtureEventLog,
) -> None:
    contract = _approval_contract(fixture_log)
    fixture_log_with_contract = load_fixture_log(
        event_payloads={"A3": {"decision_contract": contract.to_dict()}}
    )

    evidence = why("A3", fixture_log_with_contract)

    assert evidence.contract_present is True
    assert evidence.decision_type == "policy_merge"
    assert evidence.outcome == "failure"
    assert len(evidence.ports) == 2
    customer_port, risk_port = evidence.ports
    assert customer_port.port_id == "customer_status"
    assert customer_port.live_value == "eligible"
    assert customer_port.matches_recorded is True
    assert customer_port.in_slice is True
    assert risk_port.matches_recorded is True
    # A3's ancestor slice: everything upstream of the merge, but not the
    # downstream failure A4 (the fixture's nine-event slice is rooted at A4).
    assert evidence.slice.event_ids == ("A1", "B1", "C1", "B2", "C2", "B3", "C3", "A3")
    # State at A3 precedes the failing agent_finish recorded on A4.
    assert evidence.status_at_decision == "active"
    assert evidence.to_dict()["note"] == evidence.note


def test_why_surfaces_port_mismatches_instead_of_hiding_them() -> None:
    contract = create_decision_contract(
        decision_id="dec_bad_record",
        run_id="run_7f42",
        agent_id="A",
        decision_event_id="A3",
        ports=[
            DecisionPort(
                port_id="customer_status",
                source_event_id="B3",
                field_path="output.customer_status",
                recorded_value="ineligible",
                baseline_value="ineligible",
            ),
            DecisionPort(
                port_id="ghost_field",
                source_event_id="C3",
                field_path="output.does_not_exist",
                recorded_value=None,
                baseline_value=None,
            ),
        ],
    )
    log = load_fixture_log(event_payloads={"A3": {"decision_contract": contract.to_dict()}})

    evidence = why("A3", log)
    mismatched, missing = evidence.ports
    assert mismatched.found_in_payload is True
    assert mismatched.matches_recorded is False
    assert missing.found_in_payload is False
    assert missing.live_value is None


def test_why_without_contract_falls_back_to_declared_cross_agent_inputs(
    fixture_log: FixtureEventLog,
) -> None:
    evidence = why("A3", fixture_log)
    assert evidence.contract_present is False
    assert [(item.source_event_id, item.source_agent_id) for item in evidence.declared_inputs] == [
        ("B3", "B"),
        ("C3", "C"),
    ]
    assert evidence.ports == ()
