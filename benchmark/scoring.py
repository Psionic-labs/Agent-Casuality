"""Transparent per-dimension scoring for benchmark predictions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def set_metrics(predicted: Iterable[str], expected: Iterable[str]) -> dict[str, Any]:
    predicted_set, expected_set = set(predicted), set(expected)
    true_positive = len(predicted_set & expected_set)
    false_positive = len(predicted_set - expected_set)
    false_negative = len(expected_set - predicted_set)
    return {
        "precision": true_positive / len(predicted_set)
        if predicted_set
        else (1.0 if not expected_set else 0.0),
        "recall": true_positive / len(expected_set) if expected_set else 1.0,
        "exact_match": predicted_set == expected_set,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "missing": sorted(expected_set - predicted_set),
        "unexpected": sorted(predicted_set - expected_set),
    }


def pair_metrics(
    predicted: Iterable[Iterable[str]], expected: Iterable[Iterable[str]]
) -> dict[str, Any]:
    def canonical(rows: Iterable[Iterable[str]]) -> set[tuple[str, ...]]:
        return {tuple(sorted(map(str, row))) for row in rows}
    result = set_metrics(
        ("|".join(p) for p in canonical(predicted)), ("|".join(p) for p in canonical(expected))
    )
    result["false_interaction_rate"] = result["false_positive"] / max(
        1, result["true_positive"] + result["false_positive"]
    )
    return result


def score_prediction(
    *,
    structural: list[str],
    minimal: list[str],
    interactions: list[list[str]],
    provenance: list[list[str]],
    ground_truth: Any,
) -> dict[str, Any]:
    structural_score = set_metrics(structural, ground_truth.structural_slice)
    minimal_score = set_metrics(minimal, ground_truth.minimal_slice)
    provenance_score = pair_metrics(provenance, ground_truth.expected_provenance)
    interaction_score = pair_metrics(interactions, ground_truth.expected_interactions)
    return {
        "structural_slice": structural_score,
        "minimal_slice": minimal_score,
        "interaction": interaction_score,
        "provenance": provenance_score,
        "slice_reduction_ratio": 1.0 - (len(minimal) / max(1, len(structural))),
        "pass": all(
            (
                structural_score["exact_match"],
                minimal_score["exact_match"],
                provenance_score["exact_match"],
                interaction_score["exact_match"],
            )
        ),
    }


def aggregate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"scenario_count": 0}
    dimensions = ("structural_slice", "minimal_slice", "interaction", "provenance")
    return {
        "scenario_count": len(rows),
        "passed": sum(bool(row.get("pass")) for row in rows),
        "dimensions": {
            dimension: {
                "precision": sum(row[dimension]["precision"] for row in rows) / len(rows),
                "recall": sum(row[dimension]["recall"] for row in rows) / len(rows),
                "exact_match_rate": sum(bool(row[dimension]["exact_match"]) for row in rows)
                / len(rows),
            }
            for dimension in dimensions
        },
    }
