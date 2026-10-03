"""Baseline adapter contracts and explicit unavailable-baseline handling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


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


class BaselineAdapter(Protocol):
    name: str
    version: str
    command: str

    def analyze(self, scenario_artifact: Path) -> BaselineExecution: ...


class HistoricalPhase2Adapter:
    """Reference the named baseline without pretending the current SDK is independent."""

    name = "Phase 2 sdk/memory.py resource dependency capture"
    version = "unavailable"
    command = "historical Phase 2 executable (not present in this checkout)"

    def analyze(self, scenario_artifact: Path) -> BaselineExecution:
        raise BaselineUnavailableError(
            "the named historical Phase 2 baseline has no executable, pinned checkout, "
            f"or documented input contract; scenario artifact was {scenario_artifact}"
        )
