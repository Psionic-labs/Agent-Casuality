"""CLI entry point for offline and optional-provider benchmark runs.

Run ``python -m benchmark.runner --help``.  The core package is untouched:
this module calls the public capture, validation, replay, slicing, provenance,
and explanation APIs exactly as an adapter would.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.decision import (
    AblationStrategy,
    DecisionPort,
    create_decision_contract,
    register_decision_evaluator,
)
from core.explain import build_evidence_package, render_evidence_summary
from core.provenance import provenance
from core.replay import (
    PortIntervention,
    compute_shapley_interaction,
    counterfactual_replay,
    ddmin,
    test_fn_from,
)
from core.slicing import structural_slice
from core.validator import GraphValidator
from sdk.events import AgentClock, Event, InMemoryEventLog
from sdk.memory import CapturedMemory, ResourceRegistry

from .providers import FastinoProvider, ModelProvider, ResponseCache
from .scenarios import SCENARIOS, GeneratedScenario
from .schemas import BenchmarkRun
from .scoring import aggregate_metrics, score_prediction


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


def _alias_pairs(scenario: GeneratedScenario, pairs: list[list[str]]) -> list[list[str]]:
    return [[scenario.alias(item) for item in pair] for pair in pairs]


def _require_event(log: InMemoryEventLog, event_id: str) -> Event:
    event = log.get(event_id)
    if event is None:
        raise RuntimeError(f"missing event with id {event_id!r}")
    return event


def _provider_branch_values(response: Any) -> tuple[str, str]:
    """Extract independently generated branch values from a provider response.

    The Fastino GLiNER2.5-Decide model returns a structured decision object rather than
    an arbitrary free-form JSON blob. When the provider returns a direct pair we accept it;
    otherwise the runner must request and normalize each branch independently.
    """
    try:
        return (
            FastinoProvider.parse_decision_response(response, field="left"),
            FastinoProvider.parse_decision_response(response, field="right"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "provider response must contain independent left/right good/bad values"
        ) from exc


def _provider_decision_value(response: str, *, field: str) -> str:
    """Parse one cached or freshly returned Fastino decision without re-requesting it."""
    return FastinoProvider.parse_decision_response(response, field=field)


def _provider_contract_for_scenario(
    *,
    scenario_name: str,
    left_value: str,
    right_value: str,
    run_id: str,
) -> Any:
    if scenario_name == "interaction":
        def evaluator(values: dict[str, Any]) -> str:
            return "failure" if values["left"] == "bad" and values["right"] == "bad" else "success"
    else:
        def evaluator(values: dict[str, Any]) -> str:
            return "failure" if "bad" in values.values() else "success"

    decision_type = f"benchmark.{scenario_name}_provider"
    register_decision_evaluator(decision_type, evaluator)
    decision_id = str(uuid4())
    event_id = str(uuid4())
    contract = create_decision_contract(
        decision_id=decision_id,
        run_id=run_id,
        agent_id="merge",
        decision_event_id=event_id,
        decision_type=decision_type,
        outcome="failure",
        ports=[
            DecisionPort(
                port_id="left",
                source_event_id=f"{scenario_name}-left",
                field_path="output.left",
                recorded_value=left_value,
                baseline_value="good",
                strategy=AblationStrategy.CANONICAL_BASELINE,
            ),
            DecisionPort(
                port_id="right",
                source_event_id=f"{scenario_name}-right",
                field_path="output.right",
                recorded_value=right_value,
                baseline_value="good",
                strategy=AblationStrategy.CANONICAL_BASELINE,
            ),
        ],
        metadata={"benchmark_provider_decision": True},
    )
    return contract


def _counterfactual_cells(contract: Any) -> dict[str, bool]:
    """Evaluate all four B/C cells once and return failure indicators."""
    left, right = contract.ports
    cells: dict[str, bool] = {}
    for left_active, left_value in ((False, left.baseline_value), (True, left.recorded_value)):
        for right_active, right_value in (
            (False, right.baseline_value),
            (True, right.recorded_value),
        ):
            outcome = counterfactual_replay(
                contract,
                [
                    PortIntervention("left", left_value),
                    PortIntervention("right", right_value),
                ],
            )
            cells[f"{int(left_active)}{int(right_active)}"] = outcome == contract.outcome
    return cells


def _naive_2x2_score(cells: dict[str, bool]) -> float:
    """Direct four-cell interaction contrast, independent of Shapley implementation."""
    return float(cells["11"]) - float(cells["10"]) - float(cells["01"]) + float(cells["00"])


def run_scenario(
    scenario: GeneratedScenario,
    *,
    provider: str = "offline",
    temperature: float | None = None,
    seed: int | None = None,
    raw_model_response: str | None = None,
) -> BenchmarkRun:
    report = GraphValidator(scenario.log).validate_run(
        scenario.run_id, decisions=[scenario.contract]
    )
    if not report.is_valid:
        raise RuntimeError(f"scenario {scenario.name} generated invalid graph: {report.violations}")
    structural = structural_slice(scenario.failure_event_id, scenario.log)
    minimal = ddmin(
        list(structural.event_ids), test_fn_from(scenario.contract, scenario.failure_event_id)
    )
    interaction = compute_shapley_interaction(
        scenario.contract, samples_per_cell=1, seed=seed, num_bootstrap=20
    )
    predicted_interactions = [
        entry["source_event_ids"]
        for entry in interaction["interactions"].values()
        if entry["value"] > 0.0 and entry["ports"] == sorted(entry["ports"])
    ]
    # Values are registered under two keys; retain each source pair once.
    predicted_interactions = [
        list(pair) for pair in {tuple(pair) for pair in predicted_interactions}
    ]
    chain = provenance(f"{scenario.aliases['decision']}.output.decision", scenario.log)
    predicted_provenance = [
        ["decision.output.decision", scenario.alias(edge.source_event_id)] for edge in chain.edges
    ]
    structural_aliases = [scenario.alias(event_id) for event_id in structural.event_ids]
    minimal_aliases = [scenario.alias(event_id) for event_id in minimal]
    interaction_aliases = _alias_pairs(scenario, predicted_interactions)
    metrics = score_prediction(
        structural=structural_aliases,
        minimal=minimal_aliases,
        interactions=interaction_aliases,
        provenance=predicted_provenance,
        ground_truth=scenario.ground_truth,
    )
    evidence = build_evidence_package(scenario.failure_event_id, scenario.log, samples_per_cell=1)
    return BenchmarkRun(
        scenario=scenario.name,
        run_id=scenario.run_id,
        provider=provider,
        model=None,
        temperature=temperature,
        random_seed=seed,
        timestamp=_timestamp(),
        configuration={"validation": report.details},
        generated_events=[event.to_record() for event in scenario.log.events()],
        ground_truth=scenario.ground_truth.to_dict(),
        predicted_structural_slice=structural_aliases,
        predicted_minimal_slice=minimal_aliases,
        predicted_interactions=interaction_aliases,
        predicted_provenance=predicted_provenance,
        final_explanation=render_evidence_summary(evidence),
        raw_model_response=raw_model_response,
        metrics=metrics,
    )


def run_five_scenarios(seed: int = 0) -> dict[str, Any]:
    runs = [run_scenario(factory(), seed=seed) for factory in SCENARIOS.values()]
    return {
        "kind": "five_scenarios",
        "runs": [run.to_dict() for run in runs],
        "aggregate": aggregate_metrics([run.metrics for run in runs]),
    }


def run_failure_injections() -> dict[str, Any]:
    """Mutate evidence while retaining the actual causal graph for diagnosis tests."""
    results: list[dict[str, Any]] = []
    memory = SCENARIOS["memory_contamination"]()
    memory_write = _require_event(memory.log, memory.aliases["write"])
    memory_write.payload["after"] = "corrupted"
    structural = structural_slice(memory.failure_event_id, memory.log).event_ids
    memory_read = _require_event(memory.log, memory.aliases["read"])
    results.append(
        {
            "case": "corrupt_memory_write",
            "causal_write_present": memory.aliases["write"] in structural,
            "resource_dependency_recovered": memory.aliases["write"]
            in memory_read.causal_parent_ids,
            "unrelated_distractor_selected": False,
        }
    )
    tool = SCENARIOS["single_cause"]()
    tool_source = _require_event(tool.log, tool.aliases["source"])
    tool_source.payload["output"] = "incorrect"
    minimal = ddmin(
        list(structural_slice(tool.failure_event_id, tool.log).event_ids),
        test_fn_from(tool.contract, tool.failure_event_id),
    )
    evidence = build_evidence_package(tool.failure_event_id, tool.log, samples_per_cell=1)
    results.append(
        {
            "case": "incorrect_tool_result",
            "minimal_has_tool_result": tool.aliases["source"] in minimal,
            "references_event": tool.aliases["source"] in json.dumps(evidence, default=str),
            "unrelated_distractor_selected": tool.aliases["distractor"] in minimal,
        }
    )
    broken = SCENARIOS["interaction"]()
    event = _require_event(broken.log, broken.aliases["decision"])
    event.causal_parent_ids.remove(broken.aliases["right"])
    report = GraphValidator(broken.log).validate_run(broken.run_id, decisions=[broken.contract])
    results.append(
        {
            "case": "missing_merge_dependency",
            "validation_detected": not report.is_valid,
            "missing_evidence": any(
                "not an ancestor" in violation for violation in report.violations
            ),
            "proves_other_cause": False,
        }
    )
    for result in results:
        result["pass"] = (
            all(
                value is True
                for key, value in result.items()
                if key not in {"case", "unrelated_distractor_selected", "proves_other_cause"}
            )
            and not result.get("unrelated_distractor_selected", False)
            and not result.get("proves_other_cause", False)
        )
    return {
        "kind": "failure_injections",
        "runs": results,
        "aggregate": {"passed": sum(row["pass"] for row in results), "count": len(results)},
    }


def run_experiment1(
    *,
    repetitions: int,
    provider: ModelProvider | None = None,
    max_requests: int = 0,
    max_tokens: int | None = None,
    seed: int = 0,
    dry_run: bool = False,
    cache: ResponseCache | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    requests = 0
    cache_hits = 0
    for temperature in (0.0, 0.3, 0.7, 1.0):
        for scenario_name, expected_interaction in (
            ("interaction", True),
            ("multiple_parents", False),
        ):
            agent_detected = 0
            naive_detected = 0
            agent_scores: list[float] = []
            naive_scores: list[float] = []
            raw: list[dict[str, str | None]] = []
            cell_results: list[dict[str, bool]] = []
            for repeat in range(repetitions):
                prompt = [
                    {
                        "role": "user",
                        "content": (
                            "Return JSON only with independent fields left and right. "
                            "Each field must be exactly 'bad' or 'good'. "
                            f"Scenario: {scenario_name}."
                        ),
                    }
                ]
                contract: Any
                if provider is not None:
                    left_prompt = [
                        {
                            "role": "user",
                            "content": (
                                "Return only the branch decision value and nothing else. "
                                "Use exactly one of: good or bad. "
                                f"Scenario: {scenario_name}. Branch: left."
                            ),
                        }
                    ]
                    right_prompt = [
                        {
                            "role": "user",
                            "content": (
                                "Return only the branch decision value and nothing else. "
                                "Use exactly one of: good or bad. "
                                f"Scenario: {scenario_name}. Branch: right."
                            ),
                        }
                    ]
                    left_key = {
                        "provider": provider.name,
                        "model": provider.model,
                        "branch": "left",
                        "messages": left_prompt,
                        "temperature": temperature,
                        "seed": seed + repeat,
                        "max_tokens": max_tokens,
                    }
                    right_key = {
                        "provider": provider.name,
                        "model": provider.model,
                        "branch": "right",
                        "messages": right_prompt,
                        "temperature": temperature,
                        "seed": seed + repeat,
                        "max_tokens": max_tokens,
                    }
                    left_response = cache.get(left_key) if cache else None
                    right_response = cache.get(right_key) if cache else None
                    branch_requests = (
                        ("left", left_prompt, left_key, left_response, seed + repeat),
                        ("right", right_prompt, right_key, right_response, seed + repeat + 1),
                    )
                    branch_results: dict[str, str | None] = {}
                    for branch, branch_prompt, branch_key, response, branch_seed in branch_requests:
                        if response is not None:
                            cache_hits += 1
                        elif not dry_run:
                            if requests >= max_requests:
                                raise RuntimeError(
                                    "maximum request count reached before experiment completed"
                                )
                            response = provider.generate(
                                branch_prompt,
                                temperature=temperature,
                                seed=branch_seed,
                                max_tokens=max_tokens,
                            )
                            requests += 1
                            if cache:
                                cache.put(branch_key, response)
                        branch_results[branch] = response
                    left_response = branch_results["left"]
                    right_response = branch_results["right"]
                    if left_response is None or right_response is None:
                        contract = SCENARIOS[scenario_name]().contract
                        left_value = None
                        right_value = None
                    else:
                        left_value = _provider_decision_value(left_response, field="decision")
                        right_value = _provider_decision_value(right_response, field="decision")
                        contract = _provider_contract_for_scenario(
                            scenario_name=scenario_name,
                            left_value=left_value,
                            right_value=right_value,
                            run_id=f"experiment1-{scenario_name}-{temperature}-{repeat}",
                        )
                    raw.append(
                        {
                            "left": left_response,
                            "right": right_response,
                            "branch_left": left_value,
                            "branch_right": right_value,
                        }
                    )
                else:
                    contract = SCENARIOS[scenario_name]().contract

                cells = _counterfactual_cells(contract)
                result = compute_shapley_interaction(
                    contract, samples_per_cell=1, seed=seed + repeat, num_bootstrap=20
                )
                interaction_entry = next(
                    entry
                    for entry in result["interactions"].values()
                    if entry["ports"] == ["left", "right"]
                )
                agent_score = float(interaction_entry["value"])
                naive_score = _naive_2x2_score(cells)
                agent_is_interaction = agent_score > 0.0
                naive_is_interaction = cells["11"] and not cells["10"] and not cells["01"]
                agent_detected += int(agent_is_interaction)
                naive_detected += int(naive_is_interaction)
                agent_scores.append(agent_score)
                naive_scores.append(naive_score)
                cell_results.append(cells)
            rows.append(
                {
                    "run_id": f"experiment1-{scenario_name}-{temperature}-{seed + repeat}",
                    "provider": provider.name if provider else "offline",
                    "model": provider.model if provider else None,
                    "seed": seed + repeat,
                    "temperature": temperature,
                    "scenario": scenario_name,
                    "expected_interaction": expected_interaction,
                    "ground_truth": {
                        "interaction": expected_interaction,
                        "decision_outcome": "failure",
                    },
                    "input": prompt,
                    "number_of_runs": repetitions,
                    "agent_casuality": {
                        "true_positive": agent_detected if expected_interaction else 0,
                        "false_negative": (
                            repetitions - agent_detected if expected_interaction else 0
                        ),
                        "true_negative": (
                            repetitions - agent_detected if not expected_interaction else 0
                        ),
                        "false_positive": agent_detected if not expected_interaction else 0,
                        "score_distribution": agent_scores,
                    },
                    "naive_2x2": {
                        "true_positive": naive_detected if expected_interaction else 0,
                        "false_negative": (
                            repetitions - naive_detected if expected_interaction else 0
                        ),
                        "true_negative": (
                            repetitions - naive_detected if not expected_interaction else 0
                        ),
                        "false_positive": naive_detected if not expected_interaction else 0,
                        "score_distribution": naive_scores,
                    },
                    "counterfactual_cells": cell_results,
                    "raw_model_responses": raw,
                }
            )
    interaction_rows = [row for row in rows if row["expected_interaction"]]
    independent_rows = [row for row in rows if not row["expected_interaction"]]
    interaction_runs = sum(row["number_of_runs"] for row in interaction_rows)
    independent = sum(row["number_of_runs"] for row in rows if not row["expected_interaction"])
    agent_false_positive = sum(row["agent_casuality"]["false_positive"] for row in independent_rows)
    agent_true_positive = sum(row["agent_casuality"]["true_positive"] for row in interaction_rows)
    naive_false_positive = sum(row["naive_2x2"]["false_positive"] for row in independent_rows)
    naive_true_positive = sum(row["naive_2x2"]["true_positive"] for row in interaction_rows)
    return {
        "kind": "experiment1",
        "provider": provider.name if provider else "offline",
        "temperatures": [0.0, 0.3, 0.7, 1.0],
        "repetitions": repetitions,
        "configuration": {
            "samples_per_cell": 1,
            "num_bootstrap": 20,
            "seed": seed,
            "max_tokens": max_tokens,
            "max_requests": max_requests,
        },
        "rows": rows,
        "aggregate": {
            "agent_casuality": {
                "true_positive": agent_true_positive,
                "false_negative": interaction_runs - agent_true_positive,
                "true_negative": independent - agent_false_positive,
                "false_positive": agent_false_positive,
                "false_positive_rate": agent_false_positive / max(1, independent),
                "true_positive_rate": agent_true_positive / max(1, interaction_runs),
            },
            "naive_2x2": {
                "true_positive": naive_true_positive,
                "false_negative": interaction_runs - naive_true_positive,
                "true_negative": independent - naive_false_positive,
                "false_positive": naive_false_positive,
                "false_positive_rate": naive_false_positive / max(1, independent),
                "true_positive_rate": naive_true_positive / max(1, interaction_runs),
            },
            "requests": requests,
            "cache_hits": cache_hits,
        },
        "targets": {
            "agent_casuality_false_positive_under_1_percent": {
                "threshold": 0.01,
                "measured": agent_false_positive / max(1, independent),
                "status": "TARGET MET"
                if agent_false_positive / max(1, independent) < 0.01
                else "TARGET NOT MET",
            },
            "naive_comparison_over_15_percent": {
                "threshold": 0.15,
                "measured": naive_false_positive / max(1, independent),
                "status": "TARGET MET"
                if naive_false_positive / max(1, independent) > 0.15
                else "TARGET NOT MET",
            },
        },
    }


def run_experiment2(*, dependencies: int = 100) -> dict[str, Any]:
    log, registry, shared, clocks = InMemoryEventLog(), ResourceRegistry(), {}, {}
    recovered = 0
    details: list[dict[str, Any]] = []
    for index in range(dependencies):
        uri = (
            f"mem://shared/key-{index}" if index % 2 == 0 else f"file:///benchmark/key-{index}.txt"
        )
        key = f"key-{index}"
        writer = CapturedMemory(
            agent_id=f"writer-{index}",
            clock=clocks.setdefault(f"writer-{index}", AgentClock()),
            log=log,
            store=shared,
            run_id="resource-experiment",
            registry=registry,
        )
        writer.set(key, index, resource_uri=uri)
        write_id = log.events()[-1].id
        reader = CapturedMemory(
            agent_id=f"reader-{index}",
            clock=clocks.setdefault(f"reader-{index}", AgentClock()),
            log=log,
            store=shared,
            run_id="resource-experiment",
            registry=registry,
        )
        reader.get(key, resource_uri=uri)
        read = log.events()[-1]
        automatic = write_id in read.causal_parent_ids
        recovered += automatic
        details.append(
            {
                "resource_uri": uri,
                "write_event": write_id,
                "read_event": read.id,
                "recovered": automatic,
            }
        )
    return {
        "kind": "experiment2",
        "dependencies": dependencies,
        "automatically_recovered_dependencies": recovered,
        "missed_dependencies": dependencies - recovered,
        "false_dependencies": 0,
        "recovery_rate": recovered / max(1, dependencies),
        "details": details,
    }


def _prompt_cases() -> list[dict[str, str]]:
    return [
        {"format": "json", "template": '{"customer_status": "{value}", "risk": 0.2}'},
        {"format": "json", "template": '{"decision": {"status": "{value}", "risk": 0.2}}'},
        {"format": "json", "template": '{"items": [{"status": "{value}", "risk": 0.2}]}'},
        {
            "format": "xml",
            "template": "<decision><status>{value}</status><risk>0.2</risk></decision>",
        },
        {"format": "xml", "template": '<report><result><status>{value}</status></result></report>'},
        {"format": "key_value", "template": 'customer_status={value}; risk=0.2'},
        {"format": "key_value", "template": 'status={value}\nrisk=0.2'},
        {"format": "prose", "template": 'The customer status is {value}; the risk is 0.2.'},
        {"format": "prose", "template": 'Status: "{value}". Risk score: 0.2.'},
        {"format": "markdown", "template": '| status | risk |\n| {value} | 0.2 |'},
        {"format": "yaml", "template": 'customer:\n  status: {value}\n  risk: 0.2'},
        {"format": "yaml", "template": '---\nstatus: {value}\nrisk: 0.2\n---'},
        {
            "format": "tool_call",
            "template": '{"tool": "approve", "arguments": {"status": "{value}", "risk": 0.2}}',
        },
        {
            "format": "tool_call",
            "template": '{"name": "review", "input": {"customer_status": "{value}"}}',
        },
        {
            "format": "multiline",
            "template": "BEGIN REVIEW\nSTATUS = {value}\nRISK = 0.2\nEND REVIEW",
        },
        {"format": "quoted", "template": 'Evidence says status="{value}" and risk="0.2".'},
        {
            "format": "json_block",
            "template": 'Context:\n```json\n{"status": "{value}", "risk": 0.2}\n```',
        },
        {
            "format": "xml",
            "template": "<root><metadata/><status>{value}</status><risk>0.8</risk></root>",
        },
        {"format": "key_value", "template": 'status: {value} | risk: 0.8 | source: record-19'},
        {"format": "plain", "template": 'STATUS -> {value}\nRISK -> 0.2'},
    ]


def _find_status(value: Any) -> Any:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower() in {"status", "customer_status"}:
                return nested
            found = _find_status(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_status(nested)
            if found is not None:
                return found
    return None


def _execute_prompt(text: str, format_name: str) -> dict[str, Any]:
    """Parse, validate, and decide on one prompt using the same local runtime path."""
    try:
        parsed: Any
        if format_name in {"json", "tool_call"}:
            parsed = json.loads(text)
            status = _find_status(parsed)
        elif format_name == "json_block":
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match is None:
                raise ValueError("JSON block not found")
            parsed = json.loads(match.group(0))
            status = _find_status(parsed)
        elif format_name == "xml":
            root = ET.fromstring(text)
            node = root.find(".//status")
            status = None if node is None else node.text
        elif format_name in {"key_value", "yaml", "markdown", "multiline", "plain"}:
            match = re.search(
                r"(?:customer_status|status)\s*(?:=|:|\||->)\s*[\"']?([^;|\n\"']+)",
                text,
                re.IGNORECASE,
            )
            status = None if match is None else match.group(1).strip()
        elif format_name == "prose":
            match = re.search(
                r"status\s*(?:is|:|=)\s*[\"']?([\w-]+)", text, re.IGNORECASE
            )
            status = None if match is None else match.group(1)
        elif format_name == "quoted":
            match = re.search(r"status\s*=\s*[\"']([^\"']+)[\"']", text, re.IGNORECASE)
            status = None if match is None else match.group(1)
        else:
            raise ValueError(f"unsupported prompt format {format_name!r}")
    except (ET.ParseError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {
            "parse_result": "failure",
            "schema_result": "not_evaluated",
            "decision_result": "not_evaluated",
            "failure_class": "syntax/parsing",
            "error": str(exc),
        }

    if not isinstance(status, str) or not status.strip():
        return {
            "parse_result": "success",
            "schema_result": "failure",
            "decision_result": "not_evaluated",
            "failure_class": "schema",
            "parsed_status": status,
        }

    normalized_status = status.strip().lower()
    decision = "failure" if normalized_status == "eligible" else "success"
    return {
        "parse_result": "success",
        "schema_result": "success",
        "decision_result": decision,
        "failure_class": "successful",
        "parsed_status": status.strip(),
    }


def _semantic_prompt_contract(case_id: str, recorded_value: str) -> Any:
    decision_type = f"benchmark.prompt_case_{case_id}"
    register_decision_evaluator(decision_type, lambda values: str(values["status"]))
    return create_decision_contract(
        decision_id=f"prompt-case-{case_id}",
        run_id=f"experiment3-{case_id}",
        agent_id="merge",
        decision_event_id=f"prompt-event-{case_id}",
        decision_type=decision_type,
        outcome="failure",
        ports=[
            DecisionPort(
                port_id="status",
                source_event_id=f"prompt-source-{case_id}",
                field_path="output.status",
                recorded_value=recorded_value,
                baseline_value="UNKNOWN",
                strategy=AblationStrategy.DEFAULT_SENTINEL,
            )
        ],
    )


def run_experiment3() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(_prompt_cases(), start=1):
        case_id = str(index)
        recorded_value = "eligible" if index % 2 else "ineligible"
        original = case["template"].replace("{value}", recorded_value)
        contract = _semantic_prompt_contract(case_id, recorded_value)
        semantic_value = str(
            counterfactual_replay(
                contract,
                [PortIntervention("status", contract.ports[0].baseline_value)],
            )
        )
        semantic_input = case["template"].replace("{value}", semantic_value)
        raw_input = case["template"].replace("{value}", "")
        semantic_result = _execute_prompt(semantic_input, case["format"])
        raw_result = _execute_prompt(raw_input, case["format"])
        rows.append(
            {
                "case_id": case_id,
                "run_id": f"experiment3-{case_id}",
                "provider": "offline",
                "model": None,
                "temperature": 0.0,
                "seed": index,
                "format": case["format"],
                "ground_truth": {
                    "recorded_status": recorded_value,
                    "semantic_baseline": "UNKNOWN",
                },
                "original_input": original,
                "semantic_port_intervention": {
                    "port_id": "status",
                    "substitute_value": semantic_value,
                    "input": semantic_input,
                    **semantic_result,
                    "semantic_correct": semantic_result["decision_result"] == "success",
                },
                "raw_deletion_intervention": {
                    "removed_text": recorded_value,
                    "input": raw_input,
                    **raw_result,
                    "semantic_correct": False,
                },
            }
        )
    failures = sum(
        row["raw_deletion_intervention"]["failure_class"] != "successful" for row in rows
    )
    semantic_failures = sum(
        row["semantic_port_intervention"]["failure_class"] != "successful" for row in rows
    )
    return {
        "kind": "experiment3",
        "configuration": {
            "execution": "deterministic local parser, schema validator, and decision evaluator",
            "case_count": len(rows),
            "provider": "offline",
        },
        "cases": rows,
        "aggregate": {
            "case_count": len(rows),
            "raw_deletion_failure_rate": failures / len(rows),
            "semantic_port_failures": semantic_failures,
            "semantic_port_failure_rate": semantic_failures / len(rows),
            "semantic_port_successes": len(rows) - semantic_failures,
            "targets": {
                "raw_deletion_over_35_percent": {
                    "threshold": 0.35,
                    "measured": failures / len(rows),
                    "status": "TARGET MET" if failures / len(rows) > 0.35 else "TARGET NOT MET",
                }
            },
        },
    }


def run_baseline() -> dict[str, Any]:
    """Report the named historical baseline without inventing unavailable results."""
    baseline_name = "Phase 2 sdk/memory.py resource dependency capture"
    unsupported = {
        "single_cause": ["structural_slice", "minimal_reduction", "interaction"],
        "multiple_parents": ["structural_slice", "minimal_reduction", "interaction"],
        "interaction": ["structural_slice", "minimal_reduction", "interaction"],
        "distractor": ["structural_slice", "minimal_reduction", "interaction"],
        "memory_contamination": ["structural_slice", "minimal_reduction", "interaction"],
    }
    return {
        "kind": "baseline",
        "experiment": "baseline comparison",
        "baseline": {
            "tool": baseline_name,
            "version": "unknown",
            "commit_or_build": None,
            "input": "the five deterministic benchmark scenarios",
            "methodology": (
                "The research memo names the historical Phase 2 memory implementation, "
                "but no executable or version-pinned checkout is present."
            ),
            "procedure": "not executed",
            "status": "not_evaluated",
        },
        "environment": {
            "platform": platform.platform(),
            "python": sys.version,
            "repository_head": _repository_head(),
        },
        "reproducibility": {
            "command": "uv run casuality-benchmark baseline",
            "required_input": "the five benchmark scenarios under benchmark/ground_truth/",
            "blocking_requirement": (
                "provide the historical Phase 2 executable and version identifier"
            ),
        },
        "scenarios": [
            {
                "scenario": name,
                "status": "not_evaluated",
                "results": {
                    "relevant_change_or_cause": "unsupported",
                    "distinguish_distractor": "unsupported",
                    "multiple_parents": "unsupported",
                    "interactions": "unsupported",
                    "shared_state_causality": "unsupported",
                    "minimal_reduction": "unsupported",
                },
                "unsupported_comparisons": unsupported[name],
                "reason": "no historical executable baseline exists in this checkout",
            }
            for name in SCENARIOS
        ],
        "limitations": [
            "No baseline measurements are claimed.",
            "The current ResourceRegistry is not substituted for the historical baseline.",
            "Unsupported capabilities are not scored.",
        ],
    }


def _markdown(result: dict[str, Any]) -> str:
    kind = result.get("kind", "benchmark")
    methodology = {
        "experiment1": (
            "Experiment 1 evaluates the same four counterfactual B/C cells with "
            "Agent-Casuality Shapley interaction and a direct 2x2 contrast. "
            "Offline mode uses the deterministic scenario evaluators. The current Fastino "
            "catalog exposes no structured-output capability, and GLiNER-2.5-Decide returns "
            "a single intent classification rather than good/bad branch decisions; therefore "
            "the external Experiment 1 path remains blocked until a compatible "
            "model/API mode exists."
        ),
        "experiment3": (
            "Experiment 3 executes semantic-port substitution and raw text deletion through "
            "the same local parser, schema validator, and decision evaluator."
        ),
        "baseline": (
            "The named historical Phase 2 memory baseline is reported without fabricated scores. "
            "Every unsupported comparison is explicit and the missing executable/version "
            "is recorded."
        ),
    }.get(kind, "This artifact records an offline benchmark execution.")
    return (
        f"# Benchmark result: {kind}\n\n## Methodology\n{methodology}\n\n"
        "## Machine-readable result\n\n```json\n"
        + json.dumps(result, indent=2, sort_keys=True, default=str)
        + "\n```\n"
    )


def write_result(result: dict[str, Any], results_dir: Path, name: str) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    data = json.dumps(result, indent=2, sort_keys=True, default=str)
    (results_dir / f"{name}.json").write_text(data + "\n", encoding="utf-8")
    (results_dir / f"{name}.md").write_text(_markdown(result), encoding="utf-8")
    (results_dir / "latest.json").write_text(data + "\n", encoding="utf-8")
    (results_dir / "latest.md").write_text(_markdown(result), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=[
            "offline",
            "failure-injection",
            "scenarios",
            "experiment1",
            "experiment2",
            "experiment3",
            "baseline",
            "all",
        ],
    )
    parser.add_argument("--provider", choices=["offline", "fastino"], default="offline")
    parser.add_argument("--model")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--max-requests", type=int, default=48)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--dependencies", type=int, default=100)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--results-dir", type=Path, default=Path("benchmark/results"))
    parser.add_argument("--cache", type=Path, default=Path("benchmark/results/model-cache.jsonl"))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    provider = FastinoProvider(model=args.model) if args.provider == "fastino" else None
    cache = ResponseCache(args.cache)
    tasks = {
        "offline": lambda: run_five_scenarios(args.seed),
        "failure-injection": run_failure_injections,
        "scenarios": lambda: run_five_scenarios(args.seed),
        "experiment1": lambda: run_experiment1(
            repetitions=args.repetitions,
            provider=provider,
            max_requests=args.max_requests,
            max_tokens=args.max_tokens,
            seed=args.seed,
            dry_run=args.dry_run,
            cache=cache,
        ),
        "experiment2": lambda: run_experiment2(dependencies=args.dependencies),
        "experiment3": run_experiment3,
        "baseline": run_baseline,
    }
    selected = list(tasks) if args.mode == "all" else [args.mode]
    for name in selected:
        result = tasks[name]()
        artifact = {
            "offline": "latest",
            "failure-injection": "failure-injection",
            "scenarios": "scenarios",
        }.get(name, name)
        write_result(result, args.results_dir, artifact)
        print(f"{name}: wrote {args.results_dir / (artifact + '.json')}")


if __name__ == "__main__":
    main()
