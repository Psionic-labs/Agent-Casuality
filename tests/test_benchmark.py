from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.providers import FastinoProvider, ResponseCache
from benchmark.runner import run_experiment2, run_failure_injections, run_scenario, write_result
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


def test_fastino_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FASTINO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FASTINO_API_KEY"):
        FastinoProvider(model="m").generate([], temperature=0.0)
