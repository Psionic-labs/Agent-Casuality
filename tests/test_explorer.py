"""Tests for the read-only visual DAG explorer."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from explorer.loader import load_demo
from explorer.queries import (
    diagnosis_report,
    event_detail,
    evidence_report,
    failure_report,
    graph_overview,
)
from explorer.server import create_server


def _demo():
    dataset = load_demo()
    assert dataset.failure["dropped_envelopes"] == 0
    return dataset


def test_demo_loads_all_envelopes_and_resolves_failure() -> None:
    dataset = _demo()
    assert len(dataset.events) == 10
    assert dataset.failure["status"] == "resolved"
    assert dataset.failure["method"] == "selector"
    assert dataset.unresolved_roles == []


def test_graph_overview_is_consistent_and_json_safe() -> None:
    overview = graph_overview(_demo())
    assert overview["event_count"] == 10
    assert overview["edge_count"] > 0
    ids = {n["id"] for n in overview["nodes"]}
    assert len(ids) == 10
    for edge in overview["edges"]:
        assert edge["parent"] in ids and edge["child"] in ids
    seqs = [n["logical_seq"] for n in overview["nodes"]]
    assert seqs == sorted(seqs)
    json.dumps(overview)  # must survive the API boundary


def test_failure_report_roles_match_spec() -> None:
    report = failure_report(_demo())
    assert report["is_fallback"] is False
    assert set(report["roles"]) == {"first_test_failure", "fix_edit", "retry_success"}
    assert all(len(hits) == 1 for hits in report["roles"].values())


def test_diagnosis_keeps_honest_labels() -> None:
    report = diagnosis_report(_demo())
    dims = report["dimensions"]
    assert dims["cause_identification"]["recall"] == 1.0
    minimal = dims["minimal_slice"]
    assert minimal["metric"] == "required_cause_preservation_proxy"
    assert minimal["causal_minimality"] == "not_measurable"
    interaction = dims["interaction"]
    assert interaction["metric"] == "joint_ancestry"
    assert interaction["causal_interaction"] == "not_measurable"
    assert "NOT causal minimality" in minimal["label"]
    json.dumps(report)


def test_event_detail_links_parents_and_children() -> None:
    dataset = _demo()
    failure_id = dataset.failure["failure_event_id"]
    detail = event_detail(dataset, failure_id)
    assert detail["id"] == failure_id
    assert len(detail["parents"]) >= 1
    parent_id = detail["parents"][0]["event_id"]
    parent = event_detail(dataset, parent_id)
    assert failure_id in [c["event_id"] for c in parent["children"]]
    json.dumps(detail)


def test_evidence_report_summarizes_failure() -> None:
    report = evidence_report(_demo())
    assert report["status"] == "ok"
    assert isinstance(report["summary"], str) and report["summary"]
    json.dumps(report)


def test_server_serves_api_and_static() -> None:
    server = create_server(_demo())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def get(path: str) -> tuple[int, str]:
            try:
                with urllib.request.urlopen(base + path) as response:
                    return response.status, response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read().decode("utf-8")

        status, body = get("/api/overview")
        assert status == 200
        assert json.loads(body)["event_count"] == 10
        status, _ = get("/api/failure")
        assert status == 200
        status, _ = get("/api/diagnosis")
        assert status == 200
        status, body = get("/api/event?id=missing")
        assert status == 404
        status, body = get("/")
        assert status == 200 and "DAG Explorer" in body
    finally:
        server.shutdown()
        thread.join()
