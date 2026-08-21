"""Decision Structural Causal Model (SCM) and Semantic Ports contract."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from sdk.events import Event


class AblationStrategy(StrEnum):
    """Strategy used to substitute baseline values during counterfactual ablation."""

    DEFAULT_SENTINEL = "default_sentinel"  # Typed neutral sentinel (e.g. 0.0, None, "UNSPECIFIED")
    CANONICAL_BASELINE = (
        "canonical_baseline"  # Golden domain reference value (e.g., "ineligible", risk 0.8)
    )
    HISTORICAL_PRIOR = "historical_prior"  # Value sampled from a known passing run


@dataclass(frozen=True)
class DecisionPort:
    """A semantic, typed input port feeding a decision event."""

    port_id: str
    source_event_id: str
    field_path: str
    recorded_value: Any
    baseline_value: Any
    strategy: AblationStrategy = AblationStrategy.DEFAULT_SENTINEL
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "port_id": self.port_id,
            "source_event_id": self.source_event_id,
            "field_path": self.field_path,
            "recorded_value": self.recorded_value,
            "baseline_value": self.baseline_value,
            "strategy": self.strategy.value
            if isinstance(self.strategy, AblationStrategy)
            else str(self.strategy),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionPort:
        strategy_raw = data.get("strategy", AblationStrategy.DEFAULT_SENTINEL)
        strategy = (
            AblationStrategy(strategy_raw)
            if isinstance(strategy_raw, str)
            else AblationStrategy.DEFAULT_SENTINEL
        )
        return cls(
            port_id=data["port_id"],
            source_event_id=data["source_event_id"],
            field_path=data["field_path"],
            recorded_value=data.get("recorded_value"),
            baseline_value=data.get("baseline_value"),
            strategy=strategy,
            description=data.get("description", ""),
        )


@dataclass(frozen=True)
class DecisionContract:
    """Structural Causal Model contract for a decision formed by converging agent branches."""

    decision_id: str
    run_id: str
    agent_id: str
    decision_event_id: str
    ports: list[DecisionPort]
    decision_type: str
    policy_version: str | None = None
    outcome: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_port(self, port_id: str) -> DecisionPort | None:
        """Find a port by its port_id."""
        return next((p for p in self.ports if p.port_id == port_id), None)

    def to_dict(self) -> dict[str, Any]:
        """Serialize contract to dictionary."""
        return {
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "decision_event_id": self.decision_event_id,
            "ports": [p.to_dict() for p in self.ports],
            "decision_type": self.decision_type,
            "policy_version": self.policy_version,
            "outcome": self.outcome,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionContract:
        """Deserialize contract from dictionary."""
        ports = [DecisionPort.from_dict(p) for p in data.get("ports", [])]
        return cls(
            decision_id=data["decision_id"],
            run_id=data.get("run_id", ""),
            agent_id=data.get("agent_id", ""),
            decision_event_id=data.get("decision_event_id", ""),
            ports=ports,
            decision_type=data.get("decision_type", "merge_decision"),
            policy_version=data.get("policy_version"),
            outcome=data.get("outcome"),
            metadata=data.get("metadata", {}),
        )

    def to_event_payload(self, base_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Embed decision contract into event payload for backward-compatible persistence."""
        payload = dict(base_payload) if base_payload is not None else {}
        payload["decision_contract"] = self.to_dict()
        return payload

    @classmethod
    def from_event(cls, event: Event) -> DecisionContract | None:
        """Extract a DecisionContract from an Event payload if present."""
        contract_data = event.payload.get("decision_contract")
        if not isinstance(contract_data, dict):
            return None
        return cls.from_dict(contract_data)


def create_decision_contract(
    *,
    decision_id: str,
    run_id: str,
    agent_id: str,
    decision_event_id: str,
    ports: list[DecisionPort],
    decision_type: str = "merge_decision",
    policy_version: str | None = None,
    outcome: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DecisionContract:
    """Helper constructor for creating a validated DecisionContract."""
    return DecisionContract(
        decision_id=decision_id,
        run_id=run_id,
        agent_id=agent_id,
        decision_event_id=decision_event_id,
        ports=list(ports),
        decision_type=decision_type,
        policy_version=policy_version,
        outcome=outcome,
        metadata=dict(metadata) if metadata is not None else {},
    )


def create_fixture_decision(fixture_data: dict[str, Any] | None = None) -> DecisionContract:
    """Construct the canonical Customer Approval DecisionContract from fixture.json (Event A3)."""
    if fixture_data is None:
        fixture_path = Path(__file__).parent.parent / "fixture" / "fixture.json"
        with fixture_path.open("r", encoding="utf-8") as f:
            fixture_data = json.load(f)

    run_id = fixture_data.get("run", {}).get("id", "run_7f42")
    return create_decision_contract(
        decision_id="dec_customer_approval_A3",
        run_id=run_id,
        agent_id="A",
        decision_event_id="A3",
        decision_type="policy_merge",
        policy_version="policy_check_v2",
        outcome="failure",
        metadata={
            "description": "Customer approval merge combining research eligibility and risk score",
            "downstream_failure_event": "A4",
        },
        ports=[
            DecisionPort(
                port_id="customer_status",
                source_event_id="B3",
                field_path="output.customer_status",
                recorded_value="eligible",
                baseline_value="ineligible",
                strategy=AblationStrategy.CANONICAL_BASELINE,
                description="Customer research eligibility status from researcher agent B",
            ),
            DecisionPort(
                port_id="risk_score",
                source_event_id="C3",
                field_path="output.risk_score",
                recorded_value=0.2,
                baseline_value=0.8,
                strategy=AblationStrategy.CANONICAL_BASELINE,
                description="Customer risk score evaluation from coder agent C",
            ),
        ],
    )
