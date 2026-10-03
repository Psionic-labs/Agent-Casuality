from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.baseline import BaselineExecution
from benchmark.providers import FastinoProvider, ResponseCache
from benchmark.runner import (
    _counterfactual_cells,
    _provider_contract_for_scenario,
    run_baseline,
    run_experiment1,
    run_experiment2,
    run_experiment3,
    run_failure_injections,
    run_scenario,
    write_result,
)
from benchmark.scenarios import SCENARIOS
from benchmark.schemas import load_ground_truth
from benchmark.scoring import pair_metrics, score_prediction, set_metrics


def test_ground_truth_loading_and_exact_scoring() -> None:
    truth = load_ground_truth(Path("benchmark/ground_truth/interaction.json"))
    assert truth.scenario == "interaction"
    assert set_metrics(["a"], ["a"])["exact_match"]
    assert not set_metrics(["a"], ["b"])["exact_match"]
    score = score_prediction(
        structural=list(truth.structural_slice),
        minimal=list(truth.minimal_slice),
        interactions=[list(pair) for pair in truth.expected_interactions],
        provenance=[list(pair) for pair in truth.expected_provenance],
        ground_truth=truth,
    )
    assert score["pass"]
    assert pair_metrics([["a", "b"]], [["b", "a"]])["exact_match"]


def test_five_scenario_core_scores_and_resource_recovery() -> None:
    for factory in SCENARIOS.values():
        assert run_scenario(factory(), seed=1).metrics["pass"]
    result = run_experiment2(dependencies=8)
    assert result["automatically_recovered_dependencies"] == 8
    assert result["missed_dependencies"] == 0


def test_failure_injection_mechanics() -> None:
    result = run_failure_injections()
    assert result["aggregate"] == {"passed": 3, "count": 3}


def test_experiment3_executes_both_ablation_paths() -> None:
    result = run_experiment3()
    assert result["aggregate"]["case_count"] == 20
    assert result["aggregate"]["semantic_port_successes"] == 20
    assert result["aggregate"]["raw_deletion_failure_rate"] > 0.35
    first = result["cases"][0]
    assert first["semantic_port_intervention"]["input"] != first[
        "raw_deletion_intervention"
    ]["input"]
    assert first["semantic_port_intervention"]["parse_result"] == "success"
    assert first["raw_deletion_intervention"]["schema_result"] == "failure"


def test_experiment1_provider_values_remain_independently_controllable() -> None:
    both_bad = _provider_contract_for_scenario(
        scenario_name="interaction", left_value="bad", right_value="bad", run_id="both"
    )
    left_only = _provider_contract_for_scenario(
        scenario_name="interaction", left_value="bad", right_value="good", run_id="left"
    )
    assert _counterfactual_cells(both_bad) != _counterfactual_cells(left_only)
    assert _counterfactual_cells(both_bad)["11"]
    assert not _counterfactual_cells(left_only)["11"]


def test_baseline_is_explicitly_blocked_without_history() -> None:
    result = run_baseline()
    assert result["baseline"]["status"] == "blocked"
    assert result["baseline"]["version"] == "unavailable"
    assert result["reproducibility"]["execution_attempted"] is False
    assert [row["scenario"] for row in result["scenarios"]] == list(SCENARIOS)
    assert all(row["status"] == "blocked" for row in result["scenarios"])
    assert all(
        capability["status"] == "unsupported"
        for row in result["scenarios"]
        for capability in row["capabilities"].values()
    )
    assert all(row["normalized_metrics"] == {} for row in result["scenarios"])


def test_baseline_adapter_version_execution_and_scenario_coverage() -> None:
    class FakeAdapter:
        name = "fixture-diff-tool"
        version = "1.2.3"
        command = "fixture-diff-tool --scenario <path>"

        def __init__(self) -> None:
            self.paths: list[Path] = []

        def analyze(self, scenario_artifact: Path) -> BaselineExecution:
            self.paths.append(scenario_artifact)
            return BaselineExecution(
                status="completed",
                exit_code=0,
                stdout='{"capabilities": {}}',
                stderr="",
                output={"capabilities": {}},
            )

    adapter = FakeAdapter()
    result = run_baseline(adapter)
    assert result["baseline"]["version"] == "1.2.3"
    assert result["baseline"]["command"] == "fixture-diff-tool --scenario <path>"
    assert result["reproducibility"]["execution_attempted"] is True
    assert len(adapter.paths) == 5
    assert all(row["execution"]["exit_code"] == 0 for row in result["scenarios"])
    assert all(row["normalized_metrics"] == {} for row in result["scenarios"])


def test_result_serialization(tmp_path: Path) -> None:
    run = run_scenario(SCENARIOS["single_cause"]())
    write_result({"runs": [run.to_dict()]}, tmp_path, "sample")
    assert (
        json.loads((tmp_path / "sample.json").read_text())["runs"][0]["scenario"] == "single_cause"
    )
    assert (tmp_path / "latest.md").exists()


def test_response_cache_and_fastino_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = ResponseCache(tmp_path / "cache.jsonl")
    request = {"model": "m", "temperature": 0.0}
    assert cache.get(request) is None
    cache.put(request, "cached")
    assert ResponseCache(tmp_path / "cache.jsonl").get(request) == "cached"
    assert ResponseCache.key({"model": "m", "temperature": 0.0}) != ResponseCache.key(
        {"model": "m", "temperature": 0.3}
    )
    assert ResponseCache.key({"model": "m", "temperature": 0.0}) != ResponseCache.key(
        {"model": "other", "temperature": 0.0}
    )
    provider = FastinoProvider(api_key="key", base_url="https://example.test/v1", model="m")
    payload = provider.request_payload(
        [{"role": "user", "content": "hi"}], temperature=0.3, seed=2, max_tokens=7
    )
    assert payload == {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.3,
        "seed": 2,
        "max_tokens": 7,
    }

    class Response:
        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"ok"}}]}'

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            pass

    monkeypatch.setattr("benchmark.providers.urlopen", lambda request, timeout: Response())
    assert provider.generate([], temperature=0.0) == "ok"


def test_fastino_labs_api_key_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FASTINO_API_KEY", raising=False)
    monkeypatch.delenv("FASTINO_LABS_API_KEY", raising=False)
    monkeypatch.setenv("FASTINO_LABS_API_KEY", "lab-key")
    provider = FastinoProvider(model="m")
    assert provider.api_key == "lab-key"


def test_fastino_default_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FASTINO_BASE_URL", raising=False)
    monkeypatch.delenv("FASTINO_LABS_BASE_URL", raising=False)
    provider = FastinoProvider(model="m")
    assert provider.base_url == "https://api.fastino.ai/v1"


def test_fastino_structured_decision_mapping() -> None:
    provider = FastinoProvider(
        api_key="key",
        base_url="https://example.test/v1",
        model="m",
    )
    with pytest.raises(ValueError, match="valid good/bad|left/right"):
        provider.parse_decision_response(
            {"intent": {"label": "good", "confidence": 0.9}},
            field="decision",
        )
    assert (
        provider.parse_decision_response({"left": "bad", "right": "good"}, field="left")
        == "bad"
    )
    assert (
        provider.parse_decision_response({"left": "bad", "right": "good"}, field="right")
        == "good"
    )


def test_fastino_branch_outputs_are_independent() -> None:
    provider = FastinoProvider(
        api_key="key",
        base_url="https://example.test/v1",
        model="m",
    )
    samples = [
        {"left": "good", "right": "good"},
        {"left": "good", "right": "bad"},
        {"left": "bad", "right": "good"},
        {"left": "bad", "right": "bad"},
    ]
    for sample in samples:
        assert set(sample) == {"left", "right"}
        assert provider.parse_decision_response(sample, field="left") == sample["left"]
        assert provider.parse_decision_response(sample, field="right") == sample["right"]


def test_fastino_malformed_branch_response_raises_clear_error() -> None:
    provider = FastinoProvider(
        api_key="key",
        base_url="https://example.test/v1",
        model="m",
    )
    with pytest.raises(ValueError, match="valid good/bad|left/right"):
        provider.parse_decision_response(
            {"intent": {"label": "change", "confidence": 0.5}},
            field="decision",
        )
    with pytest.raises(ValueError, match="left/right|missing one branch"):
        provider.parse_decision_response({"left": "good"}, field="left")
    with pytest.raises(ValueError, match="valid good/bad"):
        provider.parse_decision_response("The result is good.")


def test_experiment1_uses_independent_provider_outputs_and_cache(
    tmp_path: Path,
) -> None:
    class FakeProvider:
        name = "fake"
        model: str | None = "fake-model"

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate(
            self,
            messages: list[dict[str, object]],
            *,
            temperature: float,
            seed: int | None = None,
            max_tokens: int | None = None,
        ) -> str:
            content = str(messages[0]["content"])
            branch = "left" if "Branch: left" in content else "right"
            self.calls.append(
                {"temperature": temperature, "seed": seed, "max_tokens": max_tokens}
            )
            return "bad" if branch == "left" else "good"

    cache = ResponseCache(tmp_path / "cache.jsonl")
    provider = FakeProvider()
    first = run_experiment1(
        repetitions=1,
        provider=provider,
        max_requests=16,
        cache=cache,
    )
    assert first["aggregate"]["requests"] == 16
    assert first["aggregate"]["cache_hits"] == 0
    assert len(provider.calls) == 16
    assert {call["temperature"] for call in provider.calls} == {0.0, 0.3, 0.7, 1.0}
    assert all(
        entry["branch_left"] == "bad" and entry["branch_right"] == "good"
        for row in first["rows"]
        for entry in row["raw_model_responses"]
    )

    second_provider = FakeProvider()
    second = run_experiment1(
        repetitions=1,
        provider=second_provider,
        max_requests=0,
        cache=cache,
    )
    assert second["aggregate"]["requests"] == 0
    assert second["aggregate"]["cache_hits"] == 16
    assert second_provider.calls == []


def test_fastino_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FASTINO_API_KEY", raising=False)
    monkeypatch.delenv("FASTINO_LABS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FASTINO_API_KEY|FASTINO_LABS_API_KEY"):
        FastinoProvider(model="m").generate([], temperature=0.0)
