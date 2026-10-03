"""Typed, JSON-backed benchmark contracts.

Ground truth lives in ``benchmark/ground_truth/*.json`` (and the historical
customer fixture), not in Python assertions.  These small dataclasses make
that data explicit without forcing the core engine to know about benchmarks.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GroundTruth:
    scenario: str
    failure_event: str
    structural_slice: tuple[str, ...]
    minimal_slice: tuple[str, ...] = ()
    expected_interactions: tuple[tuple[str, ...], ...] = ()
    expected_provenance: tuple[tuple[str, ...], ...] = ()
    required_events: tuple[str, ...] = ()
    excluded_events: tuple[str, ...] = ()
    expected_outcome: str | None = None
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroundTruth:
        interaction_rows = data.get("expected_interactions", [])
        provenance_rows = data.get("expected_provenance", [])
        return cls(
            scenario=str(data["scenario"]),
            failure_event=str(data["failure_event"]),
            structural_slice=tuple(str(v) for v in data.get("structural_slice", [])),
            minimal_slice=tuple(str(v) for v in data.get("minimal_slice", [])),
            expected_interactions=tuple(tuple(str(v) for v in row) for row in interaction_rows),
            expected_provenance=tuple(tuple(str(v) for v in row) for row in provenance_rows),
            required_events=tuple(str(v) for v in data.get("required_events", [])),
            excluded_events=tuple(str(v) for v in data.get("excluded_events", [])),
            expected_outcome=data.get("expected_outcome"),
            notes=str(data.get("notes", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in (
            "structural_slice",
            "minimal_slice",
            "expected_interactions",
            "expected_provenance",
            "required_events",
            "excluded_events",
        ):
            result[key] = [list(item) if isinstance(item, tuple) else item for item in result[key]]
        return result


def load_ground_truth(path: Path) -> GroundTruth:
    return GroundTruth.from_dict(json.loads(path.read_text(encoding="utf-8")))


@dataclass
class BenchmarkRun:
    scenario: str
    run_id: str
    provider: str
    model: str | None
    temperature: float | None
    random_seed: int | None
    timestamp: str
    configuration: dict[str, Any]
    generated_events: list[dict[str, Any]]
    ground_truth: dict[str, Any]
    predicted_structural_slice: list[str]
    predicted_minimal_slice: list[str]
    predicted_interactions: list[list[str]]
    predicted_provenance: list[list[str]]
    final_explanation: str | None
    raw_model_response: str | None
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
