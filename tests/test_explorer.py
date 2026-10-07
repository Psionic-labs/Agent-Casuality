"""Tests for the read-only visual DAG explorer."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from explorer import queries as _queries_module
from explorer.loader import load_demo
from explorer.queries import (
    ai_diagnosis_report,
    diagnosis_report,
    event_detail,
    evidence_report,
    failure_report,
    graph_overview,
)
from explorer.server import FRONTEND_DIR, create_server


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
    if not (FRONTEND_DIR / "index.html").is_file():
        pytest.skip("frontend not built; run `npm run build` in frontend/ first")
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


_VALID_AI_TEXT = """Diagnosis: The retry passed because the fix edit
corrected the code after the first test failure.
Evidence:
- The first test failure event shows the failing run.
- The fix edit event shows the correction.
Limitations: the evidence does not establish why the first version was wrong."""


def _clear_ai_cache() -> None:
    with _queries_module._ai_cache_lock:
        _queries_module._ai_cache.clear()


def test_ai_diagnosis_sections_valid_model_text() -> None:
    _clear_ai_cache()
    calls = []

    def stub(package: dict) -> str:
        calls.append(package)
        return _VALID_AI_TEXT

    status, payload = ai_diagnosis_report(_demo(), explain_fn=stub)
    assert status == 200
    assert payload["status"] == "ok"
    assert payload["model"]
    assert payload["generated_at"]
    sections = payload["sections"]
    assert "fix edit" in sections["diagnosis"]
    assert len(sections["evidence"]) == 2
    assert sections["limitations"]
    json.dumps(payload)  # must survive the API boundary
    # Second call is served from the per-dataset cache: no second model call.
    status2, payload2 = ai_diagnosis_report(_demo(), explain_fn=stub)
    assert status2 == 200 and payload2 == payload and len(calls) == 1


def test_ai_diagnosis_rejects_contract_violations() -> None:
    _clear_ai_cache()
    status, payload = ai_diagnosis_report(
        _demo(), explain_fn=lambda package: "the tests failed, probably"
    )
    assert status == 502
    assert payload["status"] == "format_rejected"


def test_ai_diagnosis_reports_missing_key_as_503() -> None:
    _clear_ai_cache()

    def no_key(package: dict) -> str:
        raise ValueError("OPENROUTER_API_KEY is not set")

    status, payload = ai_diagnosis_report(_demo(), explain_fn=no_key)
    assert status == 503
    assert payload["status"] == "ai_unavailable"


def test_ai_diagnosis_reports_provider_errors_as_502() -> None:
    _clear_ai_cache()

    def boom(package: dict) -> str:
        raise RuntimeError("OpenRouter request failed with status 500")

    status, payload = ai_diagnosis_report(_demo(), explain_fn=boom)
    assert status == 502
    assert payload["status"] == "ai_error"
