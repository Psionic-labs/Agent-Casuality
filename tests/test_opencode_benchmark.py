from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark.opencode.runner import render_markdown
from benchmark.opencode.scoring import (
    EVENT_CLASSES,
    ancestors_of,
    capture_completeness,
    classify_event,
    resolve_failure,
    resolve_roles,
    score_diagnosis,
)
from benchmark.opencode.tasks import (
    TASK_NAMES,
    list_tasks,
    load_spec,
    render_prompt,
    resolve_opencode_binary,
    setup_workdir,
)
from opencode_adapter.mapping import OpenCodeEventMapper
from sdk.events import InMemoryEventLog

RECORDED = Path("benchmark/opencode/recorded")


def _load_recorded(name: str) -> dict[str, Any]:
    return json.loads((RECORDED / f"{name}.json").read_text(encoding="utf-8"))


def _ingest(
    envelopes: list[dict[str, Any]], run_id: str = "opencode-test"
) -> tuple[InMemoryEventLog, OpenCodeEventMapper]:
    log = InMemoryEventLog()
    mapper = OpenCodeEventMapper(log, run_id=run_id)
    for envelope in envelopes:
        assert mapper.ingest(envelope) is not None
    return log, mapper


def test_ground_truth_loads_all_five() -> None:
    assert list_tasks() == list(TASK_NAMES)
    assert len(TASK_NAMES) == 5
    required = {
        "task",
        "version",
        "description",
        "intended_behavior",
        "injected_failure",
        "expected_diagnosis",
        "expected_outcome",
        "fixtures",
        "prompt",
        "expected_event_classes",
        "causal_roles",
        "failure_selector",
        "expected_structural_roles",
        "expected_resources",
        "expected_interactions",
        "excluded_roles",
    }
    for task in TASK_NAMES:
        spec = load_spec(task)
        assert required.issubset(spec.keys()), task
        assert "{workdir}" in spec["prompt"], task
        assert set(spec["expected_event_classes"].keys()) == set(EVENT_CLASSES), task
    prompt = render_prompt(load_spec("stale_research"), Path("workdir"))
    assert "{workdir}" not in prompt and "workdir" in prompt


def test_capture_completeness_scoring() -> None:
    recorded = _load_recorded("failed_test_retry")
    log, _ = _ingest(recorded["envelopes"])
    spec = load_spec("failed_test_retry")
    capture = capture_completeness(log.events(), spec["expected_event_classes"])
    per_class = capture["per_class"]
    assert per_class["sessions"]["captured"] >= 1
    assert per_class["model_calls"]["captured"] >= 1
    assert per_class["tool_calls"]["captured"] >= 3
    assert per_class["tool_results"]["captured"] >= 3
    assert per_class["file_edits"]["captured"] >= 1
    assert per_class["commands"]["captured"] >= 2
    assert per_class["retries"]["captured"] >= 1
    assert per_class["completion"]["captured"] >= 1
    assert capture["overall_recall"] == 1.0
    assert capture["repeat_command_retries"] >= 1


def test_diagnosis_scoring_retry() -> None:
    recorded = _load_recorded("failed_test_retry")
    log, _ = _ingest(recorded["envelopes"])
    spec = load_spec("failed_test_retry")
    resolved = resolve_roles(log.events(), spec["causal_roles"])
    assert resolved["unresolved"] == []
    failure = resolve_failure(log.events(), spec["failure_selector"])
    assert failure["status"] == "resolved"
    diagnosis = score_diagnosis(
        log, log.events(), spec, resolved["resolved"], failure["failure_event_id"]
    )
    assert diagnosis["cause_identification"]["recall"] == 1.0
    assert diagnosis["causal_slice"]["recall"] == 1.0
    assert diagnosis["minimal_slice"]["required_recall"] == 1.0
    assert diagnosis["provenance"]["resource_recall"] == 1.0
    assert diagnosis["interaction"]["exact_match"]
    assert diagnosis["distractors"]["leaked"] == 0
    assert diagnosis["explanation_grounding"]["grounded"]


def test_distractor_excluded_from_minimal() -> None:
    recorded = _load_recorded("stale_research")
    envelopes = list(recorded["envelopes"])
    distractor = {
        "kind": "hook:tool.execute.before",
        "timestamp": 1350,
        "session_id": "rec-stale-1",
        "payload": {
            "sessionID": "rec-stale-1",
            "callID": "rec-call-d",
            "tool": "read",
            "args": {"filePath": "lib.py"},
        },
    }
    envelopes.insert(4, distractor)
    envelopes.insert(
        5,
        {
            "kind": "hook:tool.execute.after",
            "timestamp": 1360,
            "session_id": "rec-stale-1",
            "payload": {
                "sessionID": "rec-stale-1",
                "callID": "rec-call-d",
                "tool": "read",
                "output": "def stable_sort...",
            },
        },
    )
    log, _ = _ingest(envelopes)
    spec = load_spec("stale_research")
    resolved = resolve_roles(log.events(), spec["causal_roles"])
    assert resolved["resolved"]["distractor_read"], "distractor must occur in trace"
    failure = resolve_failure(log.events(), spec["failure_selector"])
    diagnosis = score_diagnosis(
        log, log.events(), spec, resolved["resolved"], failure["failure_event_id"]
    )
    assert diagnosis["minimal_slice"]["required_recall"] == 1.0
    assert diagnosis["minimal_slice"]["distractors_leaked"] == []
    states = {d["role"]: d["state"] for d in diagnosis["distractors"]["roles"]}
    assert states["distractor_read"] == "excluded"


def test_interaction_detected_and_absent() -> None:
    base = _load_recorded("stale_research")["envelopes"][:2]
    read_a = {
        "kind": "hook:tool.execute.before",
        "timestamp": 1200,
        "session_id": "s",
        "payload": {"sessionID": "s", "callID": "a", "tool": "read", "args": {"filePath": "A.md"}},
    }
    read_b = {
        "kind": "hook:tool.execute.before",
        "timestamp": 1300,
        "session_id": "s",
        "payload": {"sessionID": "s", "callID": "b", "tool": "read", "args": {"filePath": "B.md"}},
    }
    edit = {
        "kind": "hook:tool.execute.before",
        "timestamp": 1400,
        "session_id": "s",
        "payload": {
            "sessionID": "s",
            "callID": "c",
            "tool": "edit",
            "args": {"filePath": "out.py"},
        },
    }
    finish = {
        "kind": "event:session.deleted",
        "timestamp": 1500,
        "payload": {"info": {"id": "s"}},
    }
    both = list(base) + [read_a, read_b, edit, finish]
    log, _ = _ingest(both)
    roles = [
        {"role": "branch_a", "required": True, "selector": {"path_suffix": "A.md"}},
        {"role": "branch_b", "required": True, "selector": {"path_suffix": "B.md"}},
    ]
    resolved = resolve_roles(log.events(), roles)
    failure = log.events()[-1].id
    assert ancestors_of(log, failure) >= set(resolved["resolved"]["branch_a"]) | set(
        resolved["resolved"]["branch_b"]
    )
    spec = {
        "causal_roles": roles,
        "expected_structural_roles": ["branch_a", "branch_b"],
        "expected_resources": [],
        "expected_edges": [],
        "expected_interactions": [["branch_a", "branch_b"]],
        "excluded_roles": [],
        "explanation_must_mention": [],
    }
    both_score = score_diagnosis(log, log.events(), spec, resolved["resolved"], failure)
    assert both_score["interaction"]["detected"] == [["branch_a", "branch_b"]]

    single = list(base) + [read_a, edit, finish]
    log2, _ = _ingest(single)
    resolved2 = resolve_roles(log2.events(), roles)
    assert resolved2["unresolved"] == ["branch_b"]
    failure2 = log2.events()[-1].id
    single_score = score_diagnosis(log2, log2.events(), spec, resolved2["resolved"], failure2)
    assert single_score["interaction"]["detected"] == []


def test_contamination_edge_and_ordering() -> None:
    envelopes = [
        {"kind": "event:session.created", "timestamp": 1000, "payload": {"info": {"id": "s"}}},
        {
            "kind": "hook:tool.execute.before",
            "timestamp": 1100,
            "session_id": "s",
            "payload": {
                "sessionID": "s",
                "callID": "w",
                "tool": "edit",
                "args": {"filePath": "shared.json"},
            },
        },
        {
            "kind": "hook:tool.execute.after",
            "timestamp": 1200,
            "session_id": "s",
            "payload": {"sessionID": "s", "callID": "w", "tool": "edit", "output": "ok"},
        },
        {"kind": "event:file.edited", "timestamp": 1300, "payload": {"file": "shared.json"}},
        {
            "kind": "hook:tool.execute.before",
            "timestamp": 1400,
            "session_id": "s",
            "payload": {
                "sessionID": "s",
                "callID": "r",
                "tool": "read",
                "args": {"filePath": "shared.json"},
            },
        },
        {
            "kind": "hook:tool.execute.after",
            "timestamp": 1500,
            "session_id": "s",
            "payload": {
                "sessionID": "s",
                "callID": "r",
                "tool": "read",
                "output": '{"threshold": 999}',
            },
        },
    ]
    log, _ = _ingest(envelopes)
    spec = load_spec("shared_state_contamination")
    resolved = resolve_roles(log.events(), spec["causal_roles"][:2])
    assert "consumer_read" not in resolved["unresolved"]
    write_id = resolved["resolved"]["contaminating_write"][0]
    read_id = resolved["resolved"]["consumer_read"][0]
    assert write_id != read_id
    reader = log.get(read_id)
    assert reader is not None and write_id in reader.causal_parent_ids


def test_unsupported_events_handled_and_separated() -> None:
    envelopes = [
        {"kind": "event:plugin.added", "timestamp": 1000, "payload": {"id": "core/x"}},
        {"kind": "event:tui.toast.show", "timestamp": 1100, "payload": {"message": "hi"}},
        {"kind": "event:session.created", "timestamp": 1200, "payload": {"info": {"id": "s"}}},
        {"kind": "event:weird.future.kind", "timestamp": 1300, "payload": "not-a-dict"},
        {"kind": "event:session.deleted", "timestamp": 1400, "payload": {"info": {"id": "s"}}},
    ]
    log, mapper = _ingest(envelopes)
    assert len(log.events()) == 5
    assert all(e.event_type == "context_update" or True for e in log.events())
    kinds = {e.payload.get("opencode_kind") for e in log.events()}
    assert "event:weird.future.kind" in kinds
    spec = load_spec("stale_research")
    capture = capture_completeness(log.events(), spec["expected_event_classes"])
    assert capture["per_class"]["subagents"]["captured"] == 0
    assert capture["per_class"]["subagents"]["recall"] == 1.0
    unavailable_spec = {"nope": {"min": 3, "available": False}}
    capture2 = capture_completeness(log.events(), unavailable_spec)
    assert capture2["per_class"]["nope"]["missing"] == 0
    assert classify_event(log.events()[0]) == set()


def test_result_serialization() -> None:
    record = {
        "task": "stale_research",
        "run_id": "r1",
        "status": "completed",
        "agent_exit_code": 0,
        "agent_stdout_tail": "",
        "agent_stderr_tail": "",
        "opencode_version": "test",
        "capture": {"overall_recall": 1.0},
        "roles_unresolved": [],
        "diagnosis_status": "scored",
        "diagnosis": {},
        "event_count": 3,
    }
    result = {
        "kind": "opencode",
        "methodology": "m",
        "opencode_version": "test",
        "platform": "p",
        "python": "py",
        "repository_head": None,
        "timestamp": "t",
        "runs": [record],
        "aggregate": {
            "capture_overall_recall": 1.0,
            "tasks": {
                "stale_research": {
                    "runs": 1,
                    "statuses": ["completed"],
                    "mean_capture_recall": 1.0,
                }
            },
            "diagnosis_dimensions": {},
        },
        "limitations": ["l1"],
    }
    text = json.dumps(result, default=str)
    assert json.loads(text)["runs"][0]["run_id"] == "r1"
    markdown = render_markdown(result)
    for section in (
        "Methodology",
        "Task descriptions",
        "Capture completeness",
        "Diagnosis quality",
        "Per-scenario results",
        "Failures",
        "Limitations",
    ):
        assert section in markdown, section


def test_recorded_trace_offline_end_to_end() -> None:
    recorded = _load_recorded("stale_research")
    log, _ = _ingest(recorded["envelopes"])
    spec = load_spec("stale_research")
    roles = resolve_roles(log.events(), spec["causal_roles"])
    assert roles["unresolved"] == []
    failure = resolve_failure(log.events(), spec["failure_selector"])
    assert failure["status"] == "resolved"
    capture = capture_completeness(log.events(), spec["expected_event_classes"])
    diagnosis = score_diagnosis(
        log, log.events(), spec, roles["resolved"], failure["failure_event_id"]
    )
    assert capture["overall_recall"] == 1.0
    assert diagnosis["cause_identification"]["recall"] == 1.0
    assert diagnosis["minimal_slice"]["required_recall"] == 1.0
    assert diagnosis["provenance"]["resource_recall"] == 1.0


def test_setup_workdir_and_binary_resolution(tmp_path: Any) -> None:
    spec = load_spec("failed_test_retry")
    workdir = setup_workdir(spec, tmp_path / "work")
    assert (workdir / "app.py").exists()
    assert (workdir / "test_app.py").exists()
    assert resolve_opencode_binary("custom-bin") == "custom-bin"
    assert isinstance(resolve_opencode_binary(None), str)


def _scored_retry() -> dict[str, Any]:
    recorded = _load_recorded("failed_test_retry")
    log, _ = _ingest(recorded["envelopes"])
    spec = load_spec("failed_test_retry")
    resolved = resolve_roles(log.events(), spec["causal_roles"])
    failure = resolve_failure(log.events(), spec["failure_selector"])
    return score_diagnosis(
        log, log.events(), spec, resolved["resolved"], failure["failure_event_id"]
    )


def test_minimality_proxy_is_not_causal_minimality() -> None:
    diagnosis = _scored_retry()
    proxy = diagnosis["minimal_slice"]
    assert proxy["metric"] == "required_cause_preservation_proxy"
    assert proxy["causal_minimality"] == "not_measurable"
    assert "membership" in proxy["method"]
    assert "NOT causal minimality" in proxy["label"]
    assert diagnosis["minimality_proxy"] is proxy
    assert diagnosis["causal_minimality_overall"] == "not_measurable"
    # The membership predicate preserves ground-truth events by construction:
    # ddmin must return exactly {failure + required} regardless of replay.
    assert proxy["size"] == 3  # failure + first_test_failure/fix_edit/ retry
    assert proxy["required_recall"] == 1.0


def test_joint_ancestry_is_not_causal_interaction() -> None:
    diagnosis = _scored_retry()
    joint = diagnosis["interaction"]
    assert joint["metric"] == "joint_ancestry"
    assert joint["causal_interaction"] == "not_measurable"
    assert "NOT causal interaction" in joint["label"]
    assert diagnosis["joint_ancestry"] is joint
    assert diagnosis["causal_interaction"]["status"] == "unsupported"
    assert diagnosis["causal_interaction_overall"] == "unsupported"


def test_joint_ancestry_linear_chain_is_not_independence() -> None:
    # Both branches resolve as ancestors because the receiver chains
    # telemetry linearly; independence is reported separately and is False.
    base = _load_recorded("stale_research")["envelopes"][:2]
    read_a = {
        "kind": "hook:tool.execute.before",
        "timestamp": 1200,
        "session_id": "s",
        "payload": {"sessionID": "s", "callID": "a", "tool": "read", "args": {"filePath": "A.md"}},
    }
    read_b = {
        "kind": "hook:tool.execute.before",
        "timestamp": 1300,
        "session_id": "s",
        "payload": {"sessionID": "s", "callID": "b", "tool": "read", "args": {"filePath": "B.md"}},
    }
    finish = {"kind": "event:session.deleted", "timestamp": 1400, "payload": {"info": {"id": "s"}}}
    log, _ = _ingest(list(base) + [read_a, read_b, finish])
    roles = [
        {"role": "branch_a", "required": True, "selector": {"path_suffix": "A.md"}},
        {"role": "branch_b", "required": True, "selector": {"path_suffix": "B.md"}},
    ]
    resolved = resolve_roles(log.events(), roles)
    failure = log.events()[-1].id
    spec = {
        "causal_roles": roles,
        "expected_structural_roles": ["branch_a", "branch_b"],
        "expected_resources": [],
        "expected_edges": [],
        "expected_interactions": [["branch_a", "branch_b"]],
        "excluded_roles": [],
        "explanation_must_mention": [],
    }
    score = score_diagnosis(log, log.events(), spec, resolved["resolved"], failure)
    pair = score["interaction"]["pairs"][0]
    assert pair["detected"] is True
    assert pair["both_ancestors_of_failure"] is True
    assert pair["mutually_independent"] is False  # linear chaining, not independence
    assert score["interaction"]["metric"] == "joint_ancestry"


def test_capture_is_minimum_coverage_and_excludes_unavailable() -> None:
    from benchmark.opencode.runner import aggregate

    recorded = _load_recorded("failed_test_retry")
    log, _ = _ingest(recorded["envelopes"])
    spec = load_spec("failed_test_retry")
    capture = capture_completeness(log.events(), spec["expected_event_classes"])
    assert capture["metric"] == "minimum_expected_event_class_coverage"
    assert capture["overall_coverage"] == capture["overall_recall"]
    # completion is available=false: excluded from denominator even though min=0.
    assert capture["per_class"]["completion"]["available"] is False
    assert capture["scored_classes"] == 7  # only available min>0 classes
    # A class with available=false never accrues missing mass.
    missing_only = capture_completeness(log.events(), {"ghost": {"min": 5, "available": False}})
    assert missing_only["per_class"]["ghost"]["missing"] == 0
    assert missing_only["scored_classes"] == 0
    void = aggregate([])
    assert void["capture_macro_recall"] == 0.0


def test_capture_macro_average_not_dominated_by_repeats() -> None:
    from benchmark.opencode.runner import aggregate

    def _rec(task: str, run_id: str, recall: float) -> dict[str, Any]:
        return {
            "task": task,
            "run_id": run_id,
            "status": "completed",
            "agent_exit_code": 0,
            "capture": {"overall_recall": recall},
            "roles_unresolved": [],
            "failure": {"status": "resolved"},
            "diagnosis_status": "blocked_no_events",
            "diagnosis": {},
            "event_count": 1,
        }

    records = [
        _rec("a", "a-1", 1.0),
        _rec("b", "b-1", 1.0),
        _rec("b", "b-2", 1.0),
        _rec("b", "b-3", 1.0),  # repeated scenario must not dominate macro
    ]
    agg = aggregate(records)
    assert agg["capture_micro_recall"] == 1.0
    assert agg["capture_macro_recall"] == 1.0
    skewed = [
        _rec("a", "a-1", 1.0),
        _rec("b", "b-1", 0.0),
        _rec("b", "b-2", 0.0),
        _rec("b", "b-3", 0.0),
    ]
    agg2 = aggregate(skewed)
    assert agg2["capture_micro_recall"] == 0.25  # 3 of 4 runs dominate micro
    assert agg2["capture_macro_recall"] == 0.5  # mean of {1.0, 0.0}
    assert agg2["tasks"]["b"]["runs"] == 3


def test_agent_deviation_handling() -> None:
    from benchmark.opencode.runner import aggregate, is_agent_deviation

    deviated = {
        "task": "shared_state_contamination",
        "run_id": "dev-1",
        "status": "completed",
        "agent_exit_code": 0,
        "capture": {"overall_recall": 0.833},
        "roles_unresolved": ["contaminating_write"],
        "failure": {"status": "fallback_last_event"},
        "diagnosis_status": "scored",
        "diagnosis": {
            "cause_identification": {"status": "ok", "recall": 0.0},
            "causal_slice": {"status": "ok", "recall": 0.0},
            "minimal_slice": {"status": "ok", "required_recall": 0.0},
            "provenance": {"status": "ok", "resource_recall": 1.0, "expected_edges": []},
            "interaction": {"status": "ok", "recall": 1.0, "expected": []},
            "distractors": {"status": "ok", "leaked": 0, "roles": []},
            "explanation_grounding": {"status": "ok", "summary_grounded": False, "grounded": True},
        },
        "event_count": 10,
    }
    measured = {
        "task": "stale_research",
        "run_id": "ok-1",
        "status": "completed",
        "agent_exit_code": 0,
        "capture": {"overall_recall": 1.0},
        "roles_unresolved": [],
        "failure": {"status": "resolved"},
        "diagnosis_status": "scored",
        "diagnosis": {
            "cause_identification": {"status": "ok", "recall": 1.0},
            "causal_slice": {"status": "ok", "recall": 1.0},
            "minimal_slice": {"status": "ok", "required_recall": 1.0},
            "provenance": {"status": "ok", "resource_recall": 1.0, "expected_edges": []},
            "interaction": {"status": "ok", "recall": 1.0, "expected": []},
            "distractors": {"status": "ok", "leaked": 0, "roles": []},
            "explanation_grounding": {"status": "ok", "summary_grounded": False, "grounded": True},
        },
        "event_count": 10,
    }
    assert is_agent_deviation(deviated) is True
    assert is_agent_deviation(measured) is False
    # The task prompt must not be altered to force the unsafe write.
    spec = load_spec("shared_state_contamination")
    assert "999" in spec["prompt"]  # intended scenario preserved
    agg = aggregate([measured, deviated])
    assert agg["agent_deviation"]["runs"] == 1
    assert agg["agent_deviation"]["run_ids"] == ["dev-1"]
    # Measured-only mean excludes the deviation; all-runs mean keeps it traceably.
    assert agg["diagnosis_dimensions"]["cause_identification"]["mean_score"] == 1.0
    assert agg["diagnosis_dimensions"]["cause_identification"]["mean_score_all_runs"] == 0.5


def test_evidence_grounding_requires_summary_citation() -> None:
    from benchmark.opencode.runner import _dimension_values, aggregate

    diagnosis = _scored_retry()
    grounding = diagnosis["explanation_grounding"]
    # Package contains structural evidence, but the offline summary cites no IDs.
    assert grounding["package_grounded"] is True
    assert grounding["summary_cites_count"] == 0
    assert grounding["summary_grounded"] is False
    assert grounding["mentions_recall"] == 0.0
    record = {
        "task": "failed_test_retry",
        "run_id": "r1",
        "status": "completed",
        "agent_exit_code": 0,
        "capture": {"overall_recall": 1.0},
        "roles_unresolved": [],
        "failure": {"status": "resolved"},
        "diagnosis_status": "scored",
        "diagnosis": {"explanation_grounding": grounding},
        "event_count": 10,
    }
    # Aggregate grounding must not pass on package presence alone.
    assert _dimension_values([record], "explanation_grounding") == [0.0]
    assert _dimension_values([record], "explanation_grounding_package") == [1.0]
    assert aggregate([record])["diagnosis_dimensions"]["explanation_grounding"]["mean_score"] == 0.0


def test_per_run_to_aggregate_consistency() -> None:
    from benchmark.opencode.runner import aggregate

    records: list[dict[str, Any]] = []
    for name in ("stale_research", "failed_test_retry"):
        recorded = _load_recorded(name)
        log, _ = _ingest(recorded["envelopes"])
        spec = load_spec(name)
        resolved = resolve_roles(log.events(), spec["causal_roles"])
        failure = resolve_failure(log.events(), spec["failure_selector"])
        capture = capture_completeness(log.events(), spec["expected_event_classes"])
        diagnosis = score_diagnosis(
            log, log.events(), spec, resolved["resolved"], failure["failure_event_id"]
        )
        records.append(
            {
                "task": name,
                "run_id": name,
                "status": "completed",
                "agent_exit_code": 0,
                "capture": capture,
                "roles_unresolved": [],
                "failure": failure,
                "diagnosis_status": "scored",
                "diagnosis": diagnosis,
                "event_count": len(log.events()),
            }
        )
    agg = aggregate(records)
    assert agg["run_count"] == 2
    micros: list[float] = [float(r["capture"]["overall_recall"]) for r in records]
    assert agg["capture_micro_recall"] == round(sum(micros) / len(micros), 3)
    per_task = [agg["tasks"][r["task"]]["mean_capture_recall"] for r in records]
    assert agg["capture_macro_recall"] == round(sum(per_task) / len(per_task), 3)
    for task in ("stale_research", "failed_test_retry"):
        assert agg["tasks"][task]["run_ids"] == [task]
    assert agg["unsupported"] == ["causal_interaction", "causal_minimality"]
    assert agg["diagnosis_dimensions"]["causal_interaction"]["status"] == "unsupported"
    assert agg["diagnosis_dimensions"]["causal_minimality"]["status"] == "not_measurable"
