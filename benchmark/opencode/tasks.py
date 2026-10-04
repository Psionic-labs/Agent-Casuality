"""Task loading, workdir setup, and OpenCode invocation helpers.

Declarative expectations live exclusively in `ground_truth/*.json`.
This module contains only procedures: reading the spec, writing fixture
files, rendering the prompt, and locating the OpenCode binary.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

GROUND_TRUTH_DIR = Path(__file__).resolve().parent / "ground_truth"

TASK_NAMES = (
    "stale_research",
    "conflicting_review",
    "failed_test_retry",
    "subagent_disagreement",
    "shared_state_contamination",
)


def list_tasks() -> list[str]:
    """Return the benchmark task names in canonical order."""
    return list(TASK_NAMES)


def load_spec(task: str) -> dict[str, Any]:
    """Load the single-source-of-truth spec for one task."""
    path = GROUND_TRUTH_DIR / f"{task}.json"
    if not path.exists():
        raise ValueError(f"unknown OpenCode benchmark task {task!r}")
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def get_task(task: str) -> dict[str, Any]:
    """Alias for load_spec (CLI-friendly name)."""
    return load_spec(task)


def setup_workdir(spec: dict[str, Any], workdir: Path) -> Path:
    """Write fixture files from the spec into a fresh work directory."""
    workdir.mkdir(parents=True, exist_ok=True)
    fixtures = spec.get("fixtures", {})
    if not isinstance(fixtures, dict):
        raise ValueError("task spec 'fixtures' must be an object")
    for name, content in fixtures.items():
        target = workdir / name
        if ".." in Path(name).parts:
            raise ValueError(f"unsafe fixture name {name!r}")
        target.write_text(str(content), encoding="utf-8")
    return workdir


def render_prompt(spec: dict[str, Any], workdir: Path) -> str:
    """Render the agent prompt with the concrete work directory."""
    return str(spec["prompt"]).replace("{workdir}", str(workdir))


def resolve_opencode_binary(explicit: str | None = None) -> str:
    """Locate the OpenCode executable without hardcoding one location."""
    if explicit:
        return explicit
    candidates: list[str] = []
    bundled = (
        Path.home()
        / "AppData/Roaming/npm/node_modules/opencode-ai/bin/opencode.exe"
    )
    if bundled.exists():
        candidates.append(str(bundled))
    found = shutil.which("opencode")
    if found:
        candidates.append(found)
    if candidates:
        return candidates[0]
    return "opencode"
