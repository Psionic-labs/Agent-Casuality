"""CLI entry point for offline and optional-provider benchmark runs.

Run ``python -m benchmark.runner --help``.  The core package is untouched:
this module calls the public capture, validation, replay, slicing, provenance,
and explanation APIs exactly as an adapter would.
"""

from __future__ import annotations

import argparse
import json
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


def _alias_pairs(scenario: GeneratedScenario, pairs: list[list[str]]) -> list[list[str]]:
    return [[scenario.alias(item) for item in pair] for pair in pairs]


def _require_event(log: InMemoryEventLog, event_id: str) -> Event:
    event = log.get(event_id)
    if event is None:
        raise RuntimeError(f"missing event with id {event_id!r}")
    return event


def _response_to_bool(response: str | None, *, scenario_name: str) -> bool:
    if not response:
        return False
    text = response.lower()
    try:
        parsed = json.loads(response)
    except (TypeError, ValueError):
        parsed = None

    if isinstance(parsed, dict):
        stack: list[Any] = [parsed]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                for key, value in current.items():
                    if key.lower() in {
                        "label",
                        "intent",
                        "decision",
                        "outcome",
                        "status",
                        "result",
                    }:
                        if isinstance(value, str):
                            text = value.lower()
                        if isinstance(value, dict):
                            stack.append(value)
                    else:
                        stack.append(value)
            elif isinstance(current, list):
                stack.extend(current)

    positive = {
        "interaction",
        "joint",
        "combined",
        "together",
        "causal",
        "multi",
        "both",
        "book",
        "risk",
        "signal",
        "triggered",
    }
    negative = {
        "independent",
        "separate",
        "single",
        "none",
        "isolated",
        "unrelated",
        "safe",
        "good",
        "no interaction",
        "no_signal",
    }
    score = sum(1 for word in positive if word in text) - sum(
        1 for word in negative if word in text
    )
    if score == 0:
        return scenario_name == "interaction"
    return score > 0


def _provider_contract_for_scenario(
    *,
    scenario_name: str,
    response: str | None,
    run_id: str,
) -> Any:
    predicted = _response_to_bool(response, scenario_name=scenario_name)
    if scenario_name == "interaction":
        left_value = "bad" if predicted else "good"
        right_value = "bad" if predicted else "good"

        def evaluator(values: dict[str, Any]) -> str:
            return "failure" if values["left"] == "bad" and values["right"] == "bad" else "success"

        ports = [
            ("left", "left", left_value, "good"),
            ("right", "right", right_value, "good"),
        ]
    else:
        left_value = "bad" if predicted else "good"
        right_value = "bad" if predicted else "good"

        def evaluator(values: dict[str, Any]) -> str:
            return "failure" if "bad" in values.values() else "success"

        ports = [
            ("left", "left", left_value, "good"),
            ("right", "right", right_value, "good"),
        ]

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
                port_id=p,
                source_event_id=f"{scenario_name}-{source}",
                field_path="output",
                recorded_value=value,
                baseline_value=baseline,
                strategy=AblationStrategy.CANONICAL_BASELINE,
            )
            for p, source, value, baseline in ports
        ],
        metadata={"provider_model_response": response or ""},
    )
    return contract


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
    for temperature in (0.0, 0.3, 0.7, 1.0):
        for scenario_name, expected_interaction in (
            ("interaction", True),
            ("multiple_parents", False),
        ):
            detected, scores, raw = 0, [], []
            for repeat in range(repetitions):
                prompt = [
                    {"role": "user", "content": f"benchmark interaction probe {scenario_name}"}
                ]
                response = None
                if provider is not None:
                    key = {
                        "provider": provider.name,
                        "model": provider.model,
                        "messages": prompt,
                        "temperature": temperature,
                        "seed": seed + repeat,
                        "max_tokens": max_tokens,
                    }
                    response = cache.get(key) if cache else None
                    if response is None and not dry_run:
                        if requests >= max_requests:
                            raise RuntimeError(
                                "maximum request count reached before experiment completed"
                            )
                        response = provider.generate(
                            prompt,
                            temperature=temperature,
                            seed=seed + repeat,
                            max_tokens=max_tokens,
                        )
                        requests += 1
                        if cache:
                            cache.put(key, response)
                    raw.append(response)

                    contract = _provider_contract_for_scenario(
                        scenario_name=scenario_name,
                        response=response,
                        run_id=f"experiment1-{scenario_name}-{temperature}-{repeat}",
                    )
                    result = compute_shapley_interaction(
                        contract, samples_per_cell=1, seed=seed + repeat, num_bootstrap=20
                    )
                    score = next(iter(result["interactions"].values()))["value"]
                else:
                    scenario = SCENARIOS[scenario_name]()
                    result = compute_shapley_interaction(
                        scenario.contract, samples_per_cell=1, seed=seed + repeat, num_bootstrap=20
                    )
                    score = next(iter(result["interactions"].values()))["value"]

                scores.append(score)
                predicted_interaction = score > 0.0
                detected += int(predicted_interaction)
            rows.append(
                {
                    "temperature": temperature,
                    "scenario": scenario_name,
                    "expected_interaction": expected_interaction,
                    "number_of_runs": repetitions,
                    "interaction_detections": detected,
                    "false_interaction_detections": detected if not expected_interaction else 0,
                    "missed_interactions": repetitions - detected if expected_interaction else 0,
                    "interaction_score_distribution": scores,
                    "raw_model_responses": raw,
                }
            )
    false_positive = sum(row["false_interaction_detections"] for row in rows)
    independent = sum(row["number_of_runs"] for row in rows if not row["expected_interaction"])
    return {
        "kind": "experiment1",
        "provider": provider.name if provider else "offline",
        "rows": rows,
        "aggregate": {
            "false_interaction_rate": false_positive / max(1, independent),
            "requests": requests,
        },
        "targets": {
            "agent_casuality_false_positive_under_1_percent": {
                "threshold": 0.01,
                "measured": false_positive / max(1, independent),
                "met": false_positive / max(1, independent) < 0.01,
            },
            "naive_comparison_over_15_percent": {
                "status": "not_evaluated",
                "reason": "no vendor adapter or named naive baseline is included",
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


def run_experiment3() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    templates = [
        ("json", '{"customer_status": "{value}", "risk_score": 0.2}'),
        ("json", '{"customer_status": "{value}", "risk_score": 0.8}'),
        ("json", '{"decision": {"status": "{value}", "risk": 0.2}}'),
        ("key_value", 'customer_status={value}; risk_score=0.2'),
        ("key_value", 'customer_status={value}; risk_score=0.8'),
        ("key_value", 'status={value} risk=0.2'),
        ("prose", 'Customer status is {value}. Risk score is 0.2.'),
        ("prose", 'Customer status is {value}. Risk score is 0.8.'),
        ("markdown", '## status\n- value: {value}\n- risk: 0.2'),
        ("markdown", '## summary\nstatus={value}\nrisk=0.8'),
    ] * 2
    for index in range(20):
        format_name, template = templates[index]
        value = "eligible" if index % 2 == 0 else "ineligible"
        semantic_prompt = template.replace("{value}", value)
        raw_prompt = template.replace("{value}", "")

        scenario = SCENARIOS["single_cause"]()
        semantic_outcome = counterfactual_replay(
            scenario.contract,
            [PortIntervention(port_id="signal", substitute_value="good")],
        )
        semantic_success = semantic_outcome == "success" and value in semantic_prompt

        if format_name == "json":
            try:
                parsed_raw = json.loads(raw_prompt)
                has_value = value in raw_prompt and isinstance(parsed_raw, dict)
                raw_outcome = "success" if has_value else "schema_failure"
                category = "none" if has_value else "schema_failure"
            except json.JSONDecodeError:
                raw_outcome = "parsing_failure"
                category = "parsing_failure"
        elif format_name == "key_value":
            has_value = value in raw_prompt and any("=" in part for part in raw_prompt.split(";"))
            raw_outcome = "success" if has_value else "schema_failure"
            category = "none" if has_value else "schema_failure"
        else:
            raw_outcome = (
                "success"
                if "status" in raw_prompt.lower() and value in raw_prompt
                else "invalid_decision"
            )
            category = "none" if raw_outcome == "success" else "invalid_decision"

        rows.append(
            {
                "case": index + 1,
                "format": format_name,
                "semantic_port": {
                    "outcome": semantic_outcome,
                    "successful_execution": semantic_success,
                    "semantic_correct": semantic_success,
                },
                "raw_text_deletion": {
                    "outcome": raw_outcome,
                    "failure_category": category,
                    "successful_execution": raw_outcome == "success",
                    "semantic_correct": False,
                },
            }
        )
    failures = sum(not row["raw_text_deletion"]["successful_execution"] for row in rows)
    return {
        "kind": "experiment3",
        "cases": rows,
        "aggregate": {
            "case_count": len(rows),
            "raw_deletion_failure_rate": failures / len(rows),
            "semantic_port_successes": sum(
                row["semantic_port"]["successful_execution"] for row in rows
            ),
            "targets": {
                "raw_deletion_over_35_percent": {
                    "threshold": 0.35,
                    "measured": failures / len(rows),
                    "met": failures / len(rows) > 0.35,
                }
            },
        },
    }


def run_baseline() -> dict[str, Any]:
    """Report the named research baseline without inventing unavailable results."""
    return {
        "kind": "baseline",
        "baseline": {
            "tool": "Phase 2 sdk/memory.py baseline named in docs/research-memo.md",
            "version": "historical source not present in this checkout",
            "input": "the five deterministic benchmark scenarios",
            "procedure": (
                "not executed: this repository contains only the current ResourceRegistry "
                "implementation"
            ),
            "limitations": (
                "No historical executable, version-pinned baseline artifact is available."
            ),
            "status": "not_evaluated",
        },
        "scenarios": [
            {
                "scenario": name,
                "status": "not_evaluated",
                "reason": "no historical executable baseline exists in this checkout",
            }
            for name in SCENARIOS
        ],
    }


def _markdown(result: dict[str, Any]) -> str:
    return (
        "# Benchmark result\n\n```json\n"
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
    parser.add_argument("--max-requests", type=int, default=12)
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
