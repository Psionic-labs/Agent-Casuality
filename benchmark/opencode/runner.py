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


def _dimension_values(
    records: list[dict[str, Any]], dimension: str
) -> list[float]:
    """Extract the comparable score per run for one diagnosis dimension.

    Dimensions without applicable ground truth in a run (no expected
    interactions, no excluded roles, no mention requirements) are skipped
    rather than scored zero.
    """
    values: list[float] = []
    for record in records:
        if record.get("diagnosis_status") != "scored":
            continue
        dim = record.get("diagnosis", {}).get(dimension, {})
        if not isinstance(dim, dict) or dim.get("status") != "ok":
            continue
        if dimension == "cause_identification":
            values.append(float(dim["recall"]))
        elif dimension == "causal_slice":
            values.append(float(dim["recall"]))
        elif dimension == "minimal_slice":
            values.append(float(dim["required_recall"]))
        elif dimension == "provenance":
            values.append(float(dim["resource_recall"]))
        elif dimension == "interaction":
            if not dim.get("expected"):
                continue
            values.append(float(dim["recall"]))
        elif dimension == "distractors":
            if not dim.get("roles"):
                continue
            values.append(1.0 if dim.get("leaked", 0) == 0 else 0.0)
        elif dimension == "explanation_grounding":
            values.append(1.0 if dim.get("grounded") else 0.0)
    return values


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-run records without collapsing dimensions into one score."""
    by_task: dict[str, Any] = {}
    for record in records:
        by_task.setdefault(record["task"], []).append(record)

    def mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 3) if values else 0.0

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
        recalls = _dimension_values(records, dim)
        dimension_summary[dim] = {
            "mean_score": mean(recalls),
            "scored_runs": len(recalls),
        }

    tasks_summary = {}
    for task, runs in by_task.items():
        tasks_summary[task] = {
            "runs": len(runs),
            "statuses": [r["status"] for r in runs],
            "mean_capture_recall": mean(
                [r["capture"]["overall_recall"] for r in runs if r["status"] != "blocked"]
            ),
        }
    return {
        "run_count": len(records),
        "capture_overall_recall": capture_overall,
        "diagnosis_dimensions": dimension_summary,
        "tasks": tasks_summary,
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
            "scored for capture completeness (expected vs captured event "
            "classes) and diagnosis quality (cause, slice, minimal slice, "
            "provenance, interaction, distractors, explanation grounding). "
            "Capture failures and diagnosis failures are reported separately."
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
            "when unavailable.",
            "file.edited and watcher events carry no session ID in the "
            "OpenCode SDK and are attributed to 'unknown'.",
            "Minimal slices use a structural membership test (failure + "
            "required roles) since live traces carry no DecisionContract.",
            "Interaction detection verifies joint ancestry of both "
            "branches in the failure; the receiver chains telemetry "
            "linearly, so branch independence is reported separately.",
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
    lines += [
        "## Capture completeness",
        "",
        f"Overall recall: `{agg.get('capture_overall_recall')}`",
        "",
        "| Task | Runs | Statuses | Mean capture recall |",
        "| --- | --- | --- | --- |",
    ]
    for task, summary in agg.get("tasks", {}).items():
        lines.append(
            f"| {task} | {summary['runs']} | {','.join(summary['statuses'])} "
            f"| {summary['mean_capture_recall']} |"
        )
    lines += ["", "## Diagnosis quality", ""]
    for dim, summary in agg.get("diagnosis_dimensions", {}).items():
        lines.append(
            f"- {dim}: mean score `{summary['mean_score']}` "
            f"(scored runs: {summary['scored_runs']})"
        )
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
