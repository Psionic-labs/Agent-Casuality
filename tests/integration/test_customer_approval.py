"""Regression control: execute the readable fixture through real capture and SQLite."""

from __future__ import annotations

import json
from pathlib import Path

from core.decision import create_fixture_decision
from core.explain import build_evidence_package
from core.provenance import ProvenanceEdge, provenance
from core.reducer import reconstruct
from core.replay import compute_shapley_interaction, ddmin, test_fn_from
from core.slicing import structural_slice
from core.validator import GraphValidator
from sdk.events import AgentClock, Event, record_event
from storage.sqlite import SQLiteEventStore


def test_customer_approval_fixture_is_a_real_runtime_regression(tmp_path: Path) -> None:
    data = json.loads((Path(__file__).parents[2] / "fixture" / "fixture.json").read_text())
    path = tmp_path / "customer-control.db"
    log = SQLiteEventStore(path)
    clocks: dict[str, AgentClock] = {}
    by_id: dict[str, Event] = {}
    contract = create_fixture_decision(data)
    for row in data["events"]:
        agent_id = row["agent_id"]
        parents = row["causal_parent_ids"]
        payload = dict(row["payload"])
        if row["id"] == "A3":
            payload = contract.to_event_payload(payload)
        event, stored = record_event(
            agent_id=agent_id,
            clock=clocks.setdefault(agent_id, AgentClock()),
            log=log,
            event_type=row["event_type"],
            payload=payload,
            causal_parent_ids=parents,
            causal_parent_seqs=[by_id[parent].logical_seq for parent in parents],  # type: ignore[attr-defined]
            run_id=data["run"]["id"],
            event_id=row["id"],
        )
        assert stored
        by_id[event.id] = event
    for edge in data["provenance_edges"]:
        log.record_provenance_edge(ProvenanceEdge.from_dict({**edge, "run_id": data["run"]["id"]}))
    log.close()

    # A fresh store makes persistence part of the regression rather than an in-memory comparison.
    reopened = SQLiteEventStore(path)
    truth = data["ground_truth"]
    report = GraphValidator(reopened).validate_run(data["run"]["id"], decisions=[contract])
    assert report.is_valid, report.violations
    assert set(structural_slice("A4", reopened).event_ids) == set(truth["structural_slice"])
    assert reconstruct("B", 4, log=reopened).tool_outputs["B2"] == {"customer_status": "eligible"}
    chain = provenance("A3.output.approve", reopened)
    assert {edge.source_event_id for edge in chain.edges} >= {"B3", "C3"}
    assert (
        ddmin(list(structural_slice("A4", reopened).event_ids), test_fn_from(contract, "A4"))
        == truth["minimal_slice"]
    )
    interaction = compute_shapley_interaction(contract, samples_per_cell=1, num_bootstrap=20)
    assert interaction["B3_x_C3"]["value"] == 1.0
    evidence = build_evidence_package("A4", reopened, samples_per_cell=1)
    assert set(evidence["minimal_slice"]["event_ids"]) == set(truth["minimal_slice"])
    assert {
        edge["source_event_id"] for item in evidence["provenance"] for edge in item["edges"]
    } >= {"B3", "C3", "A3"}
    reopened.close()
