"""Baseline adapter for the pinned clay-good/agent-replay diff tool."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .scenarios import GeneratedScenario

AGENT_REPLAY_COMMIT = "ccda6229a9451692fb6f1d6d323dd825c2be9dbb"
AGENT_REPLAY_VERSION = "0.2.0"
AGENT_REPLAY_REPOSITORY = "https://github.com/clay-good/agent-replay.git"


class BaselineUnavailableError(RuntimeError):
    """Raised when the configured baseline has no runnable implementation."""


@dataclass(frozen=True)
class BaselineExecution:
    """Normalized evidence returned by a real baseline invocation."""

    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    output: dict[str, object] | None = None
    commands: tuple[str, ...] = ()


class BaselineAdapter(Protocol):
    name: str
    version: str
    command: str

    def analyze(self, scenario_name: str, scenario_artifact: Path) -> BaselineExecution: ...


class BaselineCommandError(RuntimeError):
    """Raised when agent-replay cannot execute or parse a requested command."""


def _replace_bad(value: object) -> object:
    if isinstance(value, dict):
        return {key: _replace_bad(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_replace_bad(nested) for nested in value]
    return "good" if value == "bad" else value


def _step_type(event_type: str) -> str:
    return {
        "model_call": "llm_call",
        "tool_call": "tool_call",
        "tool_result": "tool_call",
        "memory_read": "retrieval",
        "memory_write": "tool_call",
        "agent_finish": "output",
        "agent_spawn": "thought",
    }.get(event_type, "thought")


def _trace_document(
    scenario: GeneratedScenario, *, variant: str, targets: set[str]
) -> dict[str, object]:
    events = scenario.log.events()
    step_numbers = {event.id: index for index, event in enumerate(events, start=1)}
    steps: list[dict[str, object]] = []
    for step_number, event in enumerate(events, start=1):
        payload = copy.deepcopy(event.payload)
        if variant == "counterfactual" and event.id in targets:
            payload = _replace_bad(payload)
        parents = list(event.causal_parent_ids)
        steps.append(
            {
                "step_number": step_number,
                "step_type": _step_type(event.event_type),
                "name": event.event_type,
                "input": {
                    "event_id": event.id,
                    "event_type": event.event_type,
                    "causal_parent_ids": parents,
                },
                "output": payload,
                "metadata": {
                    "agent_casuality_event_id": event.id,
                    "agent_id": event.agent_id,
                    "causal_parent_ids": parents,
                    "run_id": event.run_id,
                },
                "parent_step_number": step_numbers.get(parents[0]) if parents else None,
                "caused_by_step_number": step_numbers.get(parents[0]) if parents else None,
            }
        )
    return {
        "agent_name": f"agent-casuality-{scenario.name}",
        "agent_version": "benchmark",
        "trigger": "event",
        "status": "failed",
        "input": {"scenario": scenario.name},
        "output": {"status": "failure"},
        "started_at": "2026-01-01T00:00:00.000Z",
        "ended_at": "2026-01-01T00:00:01.000Z",
        "total_duration_ms": 1000,
        "tags": ["agent-casuality", "baseline", scenario.name, variant],
        "metadata": {
            "benchmark_scenario": scenario.name,
            "variant": variant,
            "source": "Agent-Casuality scenario event records",
        },
        "steps": steps,
    }


def write_agent_replay_pair(scenario: GeneratedScenario, destination: Path) -> set[str]:
    """Write recorded/counterfactual trace documents without changing ground truth."""
    aliases = scenario.aliases
    target_aliases = {
        "single_cause": {"source"},
        "multiple_parents": {"left", "right"},
        "interaction": {"left", "right"},
        "distractor": {"source"},
        "memory_contamination": {"write", "read"},
    }[scenario.name]
    targets = {aliases[alias] for alias in target_aliases}
    documents = [
        _trace_document(scenario, variant="recorded", targets=targets),
        _trace_document(scenario, variant="counterfactual", targets=targets),
    ]
    destination.write_text(json.dumps(documents, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return targets


class AgentReplayAdapter:
    """Run the pinned agent-replay CLI and expose only its trace-diff evidence."""

    name = "clay-good/agent-replay"
    version = AGENT_REPLAY_VERSION
    command = "agent-replay ingest/list/diff"

    def __init__(self, executable: str | None = None) -> None:
        self.executable = (
            executable
            or shutil.which("agent-replay.cmd")
            or shutil.which("agent-replay")
        )

    def _run(
        self, args: list[str], *, data_dir: Path
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        if self.executable is None:
            raise BaselineUnavailableError("agent-replay executable is not available")
        command: list[str] = [self.executable, *args, "--dir", str(data_dir)]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BaselineCommandError(f"failed to execute {' '.join(command)}: {exc}") from exc
        return result, " ".join(command)

    def analyze(self, scenario_name: str, scenario_artifact: Path) -> BaselineExecution:
        if self.executable is None:
            raise BaselineUnavailableError(
                "agent-replay is not installed; install the pinned commit "
                f"{AGENT_REPLAY_COMMIT} from {AGENT_REPLAY_REPOSITORY}"
            )
        with tempfile.TemporaryDirectory(prefix=f"agent-replay-{scenario_name}-") as directory:
            data_dir = Path(directory) / "store"
            ingest, ingest_command = self._run(
                ["ingest", str(scenario_artifact)], data_dir=data_dir
            )
            commands = [ingest_command]
            if ingest.returncode != 0:
                return BaselineExecution(
                    status="failed",
                    exit_code=ingest.returncode,
                    stdout=ingest.stdout,
                    stderr=ingest.stderr,
                    commands=tuple(commands),
                )
            listing, list_command = self._run(["list", "--json"], data_dir=data_dir)
            commands.append(list_command)
            if listing.returncode != 0:
                return BaselineExecution(
                    status="failed",
                    exit_code=listing.returncode,
                    stdout=listing.stdout,
                    stderr=listing.stderr,
                    commands=tuple(commands),
                )
            try:
                items = json.loads(listing.stdout)["items"]
                traces = {
                    item["metadata"]["variant"]: item["id"]
                    for item in items
                    if item["metadata"].get("benchmark_scenario") == scenario_name
                }
                left_id, right_id = traces["recorded"], traces["counterfactual"]
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise BaselineCommandError(
                    f"agent-replay list output did not contain the two scenario traces: {exc}"
                ) from exc
            diff, diff_command = self._run(
                ["diff", "--json", left_id, right_id], data_dir=data_dir
            )
            commands.append(diff_command)
            output: dict[str, object] | None = None
            try:
                output = json.loads(diff.stdout)
            except json.JSONDecodeError:
                pass
            return BaselineExecution(
                status="completed" if diff.returncode == 0 else "failed",
                exit_code=diff.returncode,
                stdout=diff.stdout,
                stderr=diff.stderr,
                output=output,
                commands=tuple(commands),
            )
