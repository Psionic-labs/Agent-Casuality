"""Real OpenCode benchmark execution and artifact generation.

Flow per task run: setup workdir → start ingest receiver → run OpenCode →
persisted trace → causal graph → slice/provenance/interaction/why →
capture + diagnosis scoring → per-run record (no payloads, no secrets).
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from opencode_adapter.server import OpenCodeIngestServer
from storage.sqlite import SQLiteEventStore

from .scoring import (
    capture_completeness,
    resolve_failure,
    resolve_roles,
    score_diagnosis,
)
from .tasks import (
    TASK_NAMES,
    list_tasks,
    load_spec,
    render_prompt,
    setup_workdir,
)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _repository_head() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def opencode_version(opencode_bin: str) -> str:
    """Return the OpenCode version string (best effort, never raises)."""
    try:
        result = subprocess.run(
            [opencode_bin, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return result.stdout.strip() or result.stderr.strip() or "unknown"
    except Exception:
        return "unknown"


def model_from_events(events: list[Any]) -> dict[str, Any]:
    """Extract model/provider identity from captured chat params (if any)."""
    for event in reversed(events):
        inner = event.payload.get("payload", {}) if isinstance(event.payload, dict) else {}
        if not isinstance(inner, dict):
            continue
        model = inner.get("model")
        provider = inner.get("provider")
        info = inner.get("info", {})
        if isinstance(model, dict):
            return {
                "model": model.get("modelID"),
                "provider": model.get("providerID"),
            }
        if isinstance(model, str):
            return {"model": model, "provider": provider}
        if isinstance(info, dict) and info.get("modelID"):
            return {"model": info.get("modelID"), "provider": info.get("providerID")}
    return {"model": None, "provider": None}


def run_task(
    task: str,
    *,
    opencode_bin: str,
    output_dir: Path,
    ingest_url: str | None = None,
    timeout: int = 300,
    model: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Execute one benchmark task through real OpenCode and score the trace."""
    spec = load_spec(task)
    run_id = f"{task}-{uuid4().hex[:8]}"
    root = repo_root or Path.cwd()
    work_base = root / ".casuality" / "opencode-bench"
    workdir = work_base / run_id
    run_dir = output_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    db_path = run_dir / "trace.db"

    setup_workdir(spec, workdir)
    prompt = render_prompt(spec, workdir.resolve())

    server: OpenCodeIngestServer | None = None
    port_hint = ""
    if ingest_url is None:
        server = OpenCodeIngestServer(db_path, port=0)
        host, port = server.address
        ingest_url = f"http://{host}:{port}/v1/opencode/events"
        port_hint = f"{host}:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(1)

    version = opencode_version(opencode_bin)
    command = [opencode_bin, "run", prompt]
    if model:
        command += ["-m", model]
    env = dict(__import__("os").environ)
    if ingest_url:
        env["CASUALITY_OPENCODE_INGEST_URL"] = ingest_url

    started = _timestamp()
    try:
        proc = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        exit_code: int | None = proc.returncode
        stdout_tail = (proc.stdout or "")[-4000:]
        stderr_tail = (proc.stderr or "")[-4000:]
        agent_status = "completed" if proc.returncode == 0 else "failed"
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout_tail = str(exc.stdout)[-4000:] if exc.stdout else ""
        stderr_tail = "timeout expired"
        agent_status = "timeout"
    except OSError as exc:
        exit_code = None
        stdout_tail = ""
        stderr_tail = str(exc)
        agent_status = "blocked"
    finished = _timestamp()

    # Allow the plugin's async drain to flush before reading the trace.
    time.sleep(3)
    errors: list[str] = list(server.errors) if server is not None else []
    if server is not None:
        server.close()

    store = SQLiteEventStore(db_path)
    try:
        events = store.events()
        roles = resolve_roles(events, spec.get("causal_roles", []))
        failure = resolve_failure(events, spec.get("failure_selector", {}))
        capture = capture_completeness(events, spec.get("expected_event_classes", {}))
        identity = model_from_events(events)
        if failure["failure_event_id"] is not None:
            diagnosis = score_diagnosis(
                store, events, spec, roles["resolved"], failure["failure_event_id"]
            )
            diagnosis_status = "scored"
        else:
            diagnosis = {"status": "blocked_no_events"}
            diagnosis_status = "blocked"
    finally:
        store.close()

    record = {
        "task": task,
        "run_id": run_id,
        "status": agent_status,
        "agent_exit_code": exit_code,
        "agent_stdout_tail": stdout_tail,
        "agent_stderr_tail": stderr_tail,
        "opencode_version": version,
        "opencode_bin": opencode_bin,
        "model": identity.get("model"),
        "provider": identity.get("provider"),
        "requested_model": model,
        "working_directory": str(workdir),
        "repository_root": str(root),
        "configuration": {"timeout": timeout, "ingest_port_hint": port_hint},
        "started": started,
        "finished": finished,
        "timestamp": finished,
        "trace_db": str(db_path),
        "ground_truth_version": spec.get("version", 1),
        "event_count": len(events),
        "receiver_errors": errors,
        "capture": capture,
        "roles_resolved": {k: v for k, v in roles["resolved"].items()},
        "roles_unresolved": roles["unresolved"],
        "failure": failure,
        "diagnosis": diagnosis,
        "diagnosis_status": diagnosis_status,
    }
    (run_dir / "record.json").write_text(
        json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return record


def is_agent_deviation(record: dict[str, Any]) -> bool:
    """True when the intended injected scenario did not materialize.

    The agent completed but skipped the injected actions (e.g. refused the
    unsafe shared.json override), so required roles are unresolved and the
    failure selector fell back to the last event. Diagnosis over such runs
    has no ground-truth evidence to find; it is agent deviation, not a
    benchmark pass or an adapter failure.
    """
    unresolved = record.get("roles_unresolved") or []
    failure_info = record.get("failure", {})
    return bool(unresolved) and failure_info.get("status") == "fallback_last_event"


def _dimension_values(
    records: list[dict[str, Any]],
    dimension: str,
    *,
    exclude_deviations: bool = False,
) -> list[float]:
    """Extract the comparable score per run for one diagnosis dimension.

    Dimensions without applicable ground truth in a run (no expected
    interactions, no excluded roles, no mention requirements) are skipped
    rather than scored zero. ``minimal_slice`` is an alias of the
    ``minimality_proxy`` (required-cause preservation, NOT causal
    minimality); ``interaction`` is joint-branch ancestry detection (NOT
    causal interaction). Explanation grounding uses summary-level citation
    (``summary_grounded``), not mere package presence, so a plausible
    paragraph without event-ID citations does not pass.
    """
    canonical = {
        "minimality_proxy": "minimal_slice",
        "minimal_slice": "minimal_slice",
        "joint_ancestry": "interaction",
        "interaction": "interaction",
        "explanation_grounding": "explanation_grounding",
        "explanation_grounding_package": "explanation_grounding",
    }.get(dimension, dimension)
    values: list[float] = []
    for record in records:
        if record.get("diagnosis_status") != "scored":
            continue
        if exclude_deviations and is_agent_deviation(record):
            continue
        dim = record.get("diagnosis", {}).get(canonical, {})
        if not isinstance(dim, dict) or dim.get("status") != "ok":
            continue
        if dimension == "cause_identification":
            values.append(float(dim["recall"]))
        elif dimension == "causal_slice":
            values.append(float(dim["recall"]))
        elif dimension in ("minimal_slice", "minimality_proxy"):
            values.append(float(dim["required_recall"]))
        elif dimension == "provenance":
            # Resource presence alone is file-presence evidence, not a
            # causal-edge proof. When expected_edges exist, average resource
            # recall with edge presence so a missing write->read link is not
            # hidden by a passing file mention.
            resource = float(dim["resource_recall"])
            edges = dim.get("expected_edges") or []
            if edges:
                present = sum(1 for e in edges if e.get("present"))
                edge_frac = present / max(1, len(edges))
                values.append(round((resource + edge_frac) / 2.0, 3))
            else:
                values.append(resource)
        elif dimension in ("interaction", "joint_ancestry"):
            if not dim.get("expected"):
                continue
            values.append(float(dim["recall"]))
        elif dimension == "distractors":
            if not dim.get("roles"):
                continue
            values.append(1.0 if dim.get("leaked", 0) == 0 else 0.0)
        elif dimension == "explanation_grounding":
            values.append(1.0 if dim.get("summary_grounded") else 0.0)
        elif dimension == "explanation_grounding_package":
            values.append(1.0 if dim.get("grounded") else 0.0)
    return values


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-run records without collapsing dimensions into one score.

    Capture uses minimum expected event-class coverage (NOT general
    precision/recall). The micro-average pools all runs; the macro-average
    means per-task means so repeated runs of one scenario cannot dominate
    silently. Diagnosis dimensions report measured runs only for the primary
    ``mean_score`` (agent deviations excluded) alongside the inclusive
    ``mean_score_all_runs`` for traceability. True causal minimality is
    ``not_measurable`` and true causal interaction is ``unsupported``; the
    reported proxies are required-cause preservation and joint ancestry.
    """
    by_task: dict[str, Any] = {}
    for record in records:
        by_task.setdefault(record["task"], []).append(record)

    def mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 3) if values else 0.0

    capture_metric = "minimum_expected_event_class_coverage"
    capture_overall = mean(
        [r["capture"]["overall_recall"] for r in records if r["status"] != "blocked"]
    )
    diagnosis_dims = (
        "cause_identification",
        "causal_slice",
        "minimal_slice",
        "provenance",
        "interaction",
        "distractors",
        "explanation_grounding",
    )
    dimension_summary: dict[str, Any] = {}
    for dim in diagnosis_dims:
        recalls_all = _dimension_values(records, dim)
        recalls_measured = _dimension_values(records, dim, exclude_deviations=True)
        entry: dict[str, Any] = {
            "mean_score": mean(recalls_measured),
            "mean_score_all_runs": mean(recalls_all),
            "scored_runs": len(recalls_measured),
            "scored_runs_all": len(recalls_all),
        }
        if dim == "minimal_slice":
            entry["metric"] = "required_cause_preservation_proxy"
            entry["causal_minimality"] = "not_measurable"
        if dim == "interaction":
            entry["metric"] = "joint_ancestry"
            entry["causal_interaction"] = "unsupported"
        if dim == "explanation_grounding":
            entry["metric"] = "summary_citation_grounding"
        dimension_summary[dim] = entry
    # Preserve the joint-ancestry alias and the unsupported causal claim.
    joint_all = _dimension_values(records, "joint_ancestry")
    joint_measured = _dimension_values(
        records, "joint_ancestry", exclude_deviations=True
    )
    dimension_summary["joint_ancestry"] = {
        "metric": "joint_ancestry",
        "causal_interaction": "unsupported",
        "mean_score": mean(joint_measured),
        "mean_score_all_runs": mean(joint_all),
        "scored_runs": len(joint_measured),
        "scored_runs_all": len(joint_all),
    }
    dimension_summary["causal_interaction"] = {
        "status": "unsupported",
        "reason": (
            "no counterfactual intervention available from live OpenCode "
            "traces; see joint_ancestry"
        ),
    }
    dimension_summary["minimality_proxy"] = dimension_summary["minimal_slice"]
    dimension_summary["causal_minimality"] = {
        "status": "not_measurable",
        "reason": (
            "live OpenCode traces carry no DecisionContract or observable "
            "failure predicate; minimal_slice is required-cause preservation"
        ),
    }

    tasks_summary: dict[str, dict[str, Any]] = {}
    for task, runs in by_task.items():
        task_capture = mean(
            [r["capture"]["overall_recall"] for r in runs if r["status"] != "blocked"]
        )
        cause_vals = [
            float(r["diagnosis"]["cause_identification"]["recall"])
            for r in runs
            if r.get("diagnosis_status") == "scored"
            and isinstance(r.get("diagnosis", {}).get("cause_identification"), dict)
            and r["diagnosis"]["cause_identification"].get("status") == "ok"
        ]
        tasks_summary[task] = {
            "runs": len(runs),
            "statuses": [r["status"] for r in runs],
            "mean_capture_recall": task_capture,
            "mean_capture_coverage": task_capture,
            "mean_cause_recall_all_runs": mean(cause_vals),
            "deviated_runs": sum(1 for r in runs if is_agent_deviation(r)),
            "run_ids": [r["run_id"] for r in runs],
        }
    task_means: list[float] = [
        float(v["mean_capture_recall"]) for v in tasks_summary.values()
    ]
    macro_capture = (
        round(sum(task_means) / len(task_means), 3) if task_means else 0.0
    )
    deviated = [r for r in records if is_agent_deviation(r)]
    return {
        "run_count": len(records),
        "capture_metric": capture_metric,
        "capture_overall_recall": capture_overall,
        "capture_micro_recall": capture_overall,
        "capture_macro_recall": macro_capture,
        "diagnosis_dimensions": dimension_summary,
        "tasks": tasks_summary,
        "agent_deviation": {
            "runs": len(deviated),
            "run_ids": [r["run_id"] for r in deviated],
            "note": (
                "agent deviation: intended injected scenario did not "
                "materialize (e.g. refused unsafe override); diagnosis has "
                "no ground-truth evidence to find"
            ),
        },
        "unsupported": ["causal_interaction", "causal_minimality"],
    }


def write_artifacts(
    records: list[dict[str, Any]], output_dir: Path, version: str
) -> dict[str, Path]:
    """Write benchmark/results/opencode.json + opencode.md (no payloads/secrets)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "kind": "opencode",
        "methodology": (
            "Each task runs a real OpenCode coding-agent session with the "
            "Agent-Casuality plugin enabled. The trace is captured through "
            "the validated /v1/opencode/events receiver into SQLite, then "
            "scored for minimum expected event-class coverage (captured / "
            "expected minimum per class; NOT general precision/recall) and "
            "diagnosis quality (cause, structural slice, required-cause "
            "preservation proxy, provenance, joint-branch ancestry, "
            "distractors, summary-citation grounding). Minimal-slice results "
            "are a required-cause preservation proxy and are NOT causal "
            "minimality (not measurable: no DecisionContract or observable "
            "failure predicate on live traces). Interaction results are "
            "joint-branch ancestry detection and are NOT causal interaction "
            "(unsupported: no counterfactual intervention). Capture "
            "failures, diagnosis failures, and agent deviations are reported "
            "separately; capture shows micro- and macro-averages across task "
            "types."
        ),
        "opencode_version": version,
        "platform": platform.platform(),
        "python": sys.version,
        "repository_head": _repository_head(),
        "timestamp": _timestamp(),
        "runs": records,
        "aggregate": aggregate(records),
        "limitations": [
            "Real agent behavior is nondeterministic; prompts steer "
            "but do not guarantee exact tool sequences.",
            "OpenCode does not expose every desired observable "
            "(e.g. permission flows appear only when the agent triggers "
            "them); such classes are reported per task, not penalized "
            "when unavailable (available=false excluded from denominator).",
            "file.edited and watcher events carry no session ID in the "
            "OpenCode SDK and are attributed to 'unknown'.",
            "Minimal slices are a required-cause preservation proxy "
            "(ddmin with a ground-truth membership predicate), NOT causal "
            "minimality; true causal minimality is not measurable from "
            "live traces (no DecisionContract / observable failure "
            "predicate). Do not report 100% causal accuracy.",
            "Joint-ancestry detection verifies both branches are ancestors "
            "of the failure; it is NOT causal interaction. True causal "
            "interaction (counterfactual/Shapley) is unsupported from live "
            "traces; branch independence is reported separately and the "
            "receiver chains telemetry linearly.",
            "Provenance resource recall is file-presence evidence, not a "
            "causal-edge proof; expected_edges are checked separately.",
            "Explanation grounding requires summary-level event-ID "
            "citation; package-level evidence presence alone does not pass.",
            "Agent deviations (e.g. refusing the unsafe shared.json "
            "override) are reported as agent deviation, not benchmark "
            "passes or adapter failures.",
            "No payload contents or secrets are stored in these artifacts.",
        ],
    }
    json_path = output_dir / "opencode.json"
    json_path.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    md_path = output_dir / "opencode.md"
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def render_markdown(result: dict[str, Any]) -> str:
    """Render the human-readable benchmark report."""
    lines = [
        "# OpenCode coding-agent benchmark",
        "",
        "## Methodology",
        "",
        str(result.get("methodology", "")),
        "",
        f"OpenCode version: `{result.get('opencode_version')}`",
        "",
        f"Platform: `{result.get('platform')}`",
        "",
        f"Timestamp: `{result.get('timestamp')}`",
        "",
        f"Repository head: `{result.get('repository_head')}`",
        "",
        "## Task descriptions",
        "",
    ]
    for task in TASK_NAMES:
        spec = load_spec(task)
        lines += [
            f"### {task}",
            "",
            str(spec.get("description", "")),
            "",
            f"Intended behavior: {spec.get('intended_behavior', '')}",
            "",
            f"Injected failure: {spec.get('injected_failure', '')}",
            "",
            f"Expected diagnosis: {spec.get('expected_diagnosis', '')}",
            "",
        ]
    agg = result.get("aggregate", {})
    dim_labels = {
        "cause_identification": "cause ID in slice",
        "causal_slice": "structural slice presence (extras via precision)",
        "minimal_slice": "required-cause preservation proxy (NOT causal minimality)",
        "minimality_proxy": "required-cause preservation proxy (NOT causal minimality)",
        "provenance": "provenance resource recall (edges reported separately)",
        "interaction": "joint-branch ancestry detection (NOT causal interaction)",
        "joint_ancestry": "joint-branch ancestry detection (NOT causal interaction)",
        "distractors": "distractor exclusion (explicit expected distractors absent)",
        "explanation_grounding": "explanation grounding (summary cites real event IDs)",
    }
    micro = agg.get("capture_micro_recall", agg.get("capture_overall_recall"))
    lines += [
        "## Capture completeness",
        "",
        "Metric: minimum expected event-class coverage "
        "(captured / expected minimum; NOT general precision/recall; "
        "`available=false` classes excluded from the denominator).",
        "",
        f"Micro-average (all runs): `{micro}`",
        "",
        f"Macro-average (mean of per-task means): `{agg.get('capture_macro_recall')}`",
        "",
        "| Task | Runs | Statuses | Mean capture coverage | Deviated |",
        "| --- | --- | --- | --- | --- |",
    ]
    for task, summary in agg.get("tasks", {}).items():
        lines.append(
            f"| {task} | {summary['runs']} | {','.join(summary['statuses'])} "
            f"| {summary.get('mean_capture_coverage', summary['mean_capture_recall'])} "
            f"| {summary.get('deviated_runs', 0)} |"
        )
    lines += ["", "## Diagnosis quality", ""]
    lines += [
        "No single opaque score. `mean_score` excludes agent-deviation runs "
        "(no ground-truth evidence to find); `mean_score_all_runs` includes "
        "them for traceability. True causal minimality is not measurable; "
        "true causal interaction is unsupported.",
        "",
    ]
    for dim, summary in agg.get("diagnosis_dimensions", {}).items():
        if not isinstance(summary, dict) or "mean_score" not in summary:
            if dim in ("causal_interaction", "causal_minimality"):
                lines.append(f"- {dim}: `{summary.get('status')}` ({summary.get('reason')})")
            continue
        label = dim_labels.get(dim, dim)
        lines.append(
            f"- {dim} ({label}): measured mean `{summary['mean_score']}` "
            f"(measured runs: {summary['scored_runs']}; all-runs mean: "
            f"`{summary.get('mean_score_all_runs')}` over "
            f"{summary.get('scored_runs_all')})"
        )
    deviation = agg.get("agent_deviation", {})
    if deviation.get("runs"):
        lines += [
            "",
            f"Agent deviations: `{deviation.get('runs')}` "
            f"({', '.join(deviation.get('run_ids', []))})",
        ]
    lines += ["", "## Per-scenario results", ""]
    for run in result.get("runs", []):
        lines += [
            f"### {run['task']} ({run['run_id']})",
            "",
            f"Status: `{run['status']}` (exit {run['agent_exit_code']}), "
            f"events: `{run['event_count']}`, "
            f"capture recall: `{run['capture']['overall_recall']}`, "
            f"diagnosis: `{run['diagnosis_status']}`",
            "",
            f"Unresolved roles: `{run['roles_unresolved'] or 'none'}`",
            "",
        ]
    lines += ["## Failures / missing data", ""]
    failed = [r for r in result.get("runs", []) if r["status"] != "completed"]
    deviated = [
        r
        for r in result.get("runs", [])
        if r["status"] == "completed"
        and (
            r["roles_unresolved"]
            or r.get("diagnosis", {}).get("cause_identification", {}).get("recall", 1.0) < 1.0
        )
    ]
    if failed:
        for run in failed:
            lines.append(
                f"- {run['task']} ({run['run_id']}): status `{run['status']}`, "
                f"stderr: {run['agent_stderr_tail'][-300:]}"
            )
    else:
        lines.append("No agent execution failures.")
    if deviated:
        lines += [
            "",
            "Runs where the intended causal structure did not materialize "
            "(agent deviation, not adapter failure):",
            "",
        ]
        for run in deviated:
            lines.append(
                f"- {run['task']} ({run['run_id']}): unresolved roles "
                f"`{run['roles_unresolved']}`; cause recall "
                f"`{run.get('diagnosis', {}).get('cause_identification', {}).get('recall')}`. "
                "The agent run completed but skipped the injected actions, so "
                "diagnosis has no ground-truth events to find."
            )
    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in result.get("limitations", [])]
    lines += [
        "",
        "## Reproduction",
        "",
        "```powershell",
        "uv run casuality-benchmark opencode",
        "```",
        "",
        "Real OpenCode execution is not part of normal CI (`uv run pytest -q`).",
        "",
    ]
    return "\n".join(lines) + "\n"


def run_suite(
    tasks: list[str] | None = None,
    *,
    opencode_bin: str,
    output_dir: Path,
    ingest_url: str | None = None,
    runs_per_task: int = 1,
    timeout: int = 300,
    model: str | None = None,
    repo_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Run the full suite (tasks × runs) and write aggregate artifacts."""
    selected = tasks or list_tasks()
    records: list[dict[str, Any]] = []
    for task in selected:
        for _ in range(runs_per_task):
            records.append(
                run_task(
                    task,
                    opencode_bin=opencode_bin,
                    output_dir=output_dir,
                    ingest_url=ingest_url,
                    timeout=timeout,
                    model=model,
                    repo_root=repo_root,
                )
            )
    version = opencode_version(opencode_bin)
    write_artifacts(records, output_dir, version)
    return records
