"""Small executions used by the deterministic benchmark suite."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.decision import (
    AblationStrategy,
    DecisionPort,
    create_decision_contract,
    register_decision_evaluator,
)
from core.provenance import ProvenanceEdge
from sdk.events import AgentClock, Event, InMemoryEventLog, record_event
from sdk.memory import CapturedMemory, ResourceRegistry

from .schemas import GroundTruth, load_ground_truth

ROOT = Path(__file__).parent


@dataclass
class GeneratedScenario:
    name: str
    run_id: str
    log: InMemoryEventLog
    contract: Any
    failure_event_id: str
    aliases: dict[str, str]
    ground_truth: GroundTruth

    def alias(self, event_id: str) -> str:
        return next((name for name, value in self.aliases.items() if value == event_id), event_id)


def _truth(name: str) -> GroundTruth:
    return load_ground_truth(ROOT / "ground_truth" / f"{name}.json")


def _require_event(log: InMemoryEventLog, event_id: str) -> Event:
    event = log.get(event_id)
    if event is None:
        raise ValueError(f"missing event with id {event_id!r}")
    return event


def _capture(
    log: InMemoryEventLog,
    clocks: dict[str, AgentClock],
    aliases: dict[str, str],
    name: str,
    agent: str,
    event_type: str,
    payload: dict[str, Any],
    parents: tuple[str, ...] = (),
) -> Event:
    parent_ids = [aliases[p] for p in parents]
    parent_seqs = [
        parent.logical_seq for parent_id in parent_ids if (parent := log.get(parent_id)) is not None
    ]
    event, stored = record_event(
        agent_id=agent,
        clock=clocks.setdefault(agent, AgentClock()),
        log=log,
        event_type=event_type,
        payload=payload,
        causal_parent_ids=parent_ids,
        causal_parent_seqs=parent_seqs,
        run_id="benchmark",
    )
    assert stored
    aliases[name] = event.id
    return event


def _finish(
    log: InMemoryEventLog, clocks: dict[str, AgentClock], aliases: dict[str, str], decision: Event
) -> str:
    event = _capture(
        log,
        clocks,
        aliases,
        "failure",
        "terminal",
        "agent_finish",
        {"status": "failure"},
        ("decision",),
    )
    return event.id


def _decision(
    name: str,
    log: InMemoryEventLog,
    clocks: dict[str, AgentClock],
    aliases: dict[str, str],
    ports: list[tuple[str, str, Any, Any]],
    evaluator: Callable[[dict[str, Any]], str],
    parents: tuple[str, ...],
) -> Any:
    decision_type = f"benchmark.{name}"
    register_decision_evaluator(decision_type, evaluator)
    decision_id = str(uuid4())
    # Give the contract the generated event id after capture; the event carries the
    # same contract data by using a known UUID as its capture id.
    event_id = str(uuid4())
    contract = create_decision_contract(
        decision_id=decision_id,
        run_id="benchmark",
        agent_id="merge",
        decision_event_id=event_id,
        decision_type=decision_type,
        outcome="failure",
        ports=[
            DecisionPort(
                port_id=p,
                source_event_id=aliases[source],
                field_path="output",
                recorded_value=value,
                baseline_value=baseline,
                strategy=AblationStrategy.CANONICAL_BASELINE,
            )
            for p, source, value, baseline in ports
        ],
        metadata={"downstream_failure_event": ""},
    )
    event, stored = record_event(
        agent_id="merge",
        clock=clocks.setdefault("merge", AgentClock()),
        log=log,
        event_type="model_call",
        payload=contract.to_event_payload({"output": "failure"}),
        causal_parent_ids=[aliases[p] for p in parents],
        causal_parent_seqs=[_require_event(log, aliases[p]).logical_seq for p in parents],
        run_id="benchmark",
        event_id=event_id,
    )
    assert stored
    aliases["decision"] = event.id
    return contract


def _add_provenance(
    log: InMemoryEventLog, run_id: str, decision_id: str, sources: list[str]
) -> None:
    for source in sources:
        log.record_provenance_edge(
            ProvenanceEdge(
                field_path=f"{decision_id}.output.decision",
                source_event_id=source,
                run_id=run_id,
                source_path="output",
                transform="benchmark_policy",
            )
        )


def single_cause() -> GeneratedScenario:
    name, log, clocks, aliases = "single_cause", InMemoryEventLog(), {}, {}
    _capture(log, clocks, aliases, "source", "upstream", "tool_result", {"output": "bad"})
    _capture(
        log, clocks, aliases, "distractor", "background", "tool_result", {"output": "bad-looking"}
    )
    contract = _decision(
        name,
        log,
        clocks,
        aliases,
        [("signal", "source", "bad", "good")],
        lambda values: "failure" if values["signal"] == "bad" else "success",
        ("source",),
    )
    failure = _finish(log, clocks, aliases, _require_event(log, aliases["decision"]))
    _add_provenance(log, contract.run_id, aliases["decision"], [aliases["source"]])
    return GeneratedScenario(name, contract.run_id, log, contract, failure, aliases, _truth(name))


def multiple_parents() -> GeneratedScenario:
    name, log, clocks, aliases = "multiple_parents", InMemoryEventLog(), {}, {}
    _capture(log, clocks, aliases, "left", "left", "tool_result", {"output": "bad"})
    _capture(log, clocks, aliases, "right", "right", "tool_result", {"output": "bad"})
    contract = _decision(
        name,
        log,
        clocks,
        aliases,
        [("left", "left", "bad", "good"), ("right", "right", "bad", "good")],
        lambda values: "failure" if "bad" in values.values() else "success",
        ("left", "right"),
    )
    failure = _finish(log, clocks, aliases, _require_event(log, aliases["decision"]))
    _add_provenance(log, contract.run_id, aliases["decision"], [aliases["left"], aliases["right"]])
    return GeneratedScenario(name, contract.run_id, log, contract, failure, aliases, _truth(name))


def interaction() -> GeneratedScenario:
    name, log, clocks, aliases = "interaction", InMemoryEventLog(), {}, {}
    _capture(log, clocks, aliases, "left", "left", "tool_result", {"output": "bad"})
    _capture(log, clocks, aliases, "right", "right", "tool_result", {"output": "bad"})
    contract = _decision(
        name,
        log,
        clocks,
        aliases,
        [("left", "left", "bad", "good"), ("right", "right", "bad", "good")],
        lambda values: (
            "failure" if values["left"] == "bad" and values["right"] == "bad" else "success"
        ),
        ("left", "right"),
    )
    failure = _finish(log, clocks, aliases, _require_event(log, aliases["decision"]))
    _add_provenance(log, contract.run_id, aliases["decision"], [aliases["left"], aliases["right"]])
    return GeneratedScenario(name, contract.run_id, log, contract, failure, aliases, _truth(name))


def distractor() -> GeneratedScenario:
    name, log, clocks, aliases = "distractor", InMemoryEventLog(), {}, {}
    _capture(log, clocks, aliases, "source", "upstream", "tool_result", {"output": "bad"})
    _capture(
        log, clocks, aliases, "distractor", "background", "tool_result", {"output": "plausible"}
    )
    contract = _decision(
        name,
        log,
        clocks,
        aliases,
        [("signal", "source", "bad", "good")],
        lambda values: "failure" if values["signal"] == "bad" else "success",
        ("source", "distractor"),
    )
    failure = _finish(log, clocks, aliases, _require_event(log, aliases["decision"]))
    _add_provenance(log, contract.run_id, aliases["decision"], [aliases["source"]])
    return GeneratedScenario(name, contract.run_id, log, contract, failure, aliases, _truth(name))


def memory_contamination() -> GeneratedScenario:
    name, log, clocks, aliases = "memory_contamination", InMemoryEventLog(), {}, {}
    registry, shared = ResourceRegistry(), {}
    writer = CapturedMemory(
        agent_id="writer",
        clock=clocks.setdefault("writer", AgentClock()),
        log=log,
        store=shared,
        run_id="benchmark",
        registry=registry,
    )
    writer.set("approval", "bad", resource_uri="mem://shared/approval")
    aliases["write"] = log.events()[-1].id
    reader = CapturedMemory(
        agent_id="reader",
        clock=clocks.setdefault("reader", AgentClock()),
        log=log,
        store=shared,
        run_id="benchmark",
        registry=registry,
    )
    value = reader.get("approval", resource_uri="mem://shared/approval")
    aliases["read"] = log.events()[-1].id
    contract = _decision(
        name,
        log,
        clocks,
        aliases,
        [("approval", "read", value, "good")],
        lambda values: "failure" if values["approval"] == "bad" else "success",
        ("read",),
    )
    failure = _finish(log, clocks, aliases, _require_event(log, aliases["decision"]))
    _add_provenance(log, contract.run_id, aliases["decision"], [aliases["read"]])
    return GeneratedScenario(name, contract.run_id, log, contract, failure, aliases, _truth(name))


SCENARIOS: dict[str, Callable[[], GeneratedScenario]] = {
    "single_cause": single_cause,
    "multiple_parents": multiple_parents,
    "interaction": interaction,
    "distractor": distractor,
    "memory_contamination": memory_contamination,
}
