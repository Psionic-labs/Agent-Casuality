"""Graph Completeness Validator.

Validates DAG invariants, causal parent existence, cross-run isolation,
intra-agent timeline continuity, and decision port reachability.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from core.decision import DecisionContract
from sdk.events import Event


@dataclass
class ValidationReport:
    """Detailed report produced by the GraphValidator."""

    is_valid: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class GraphValidator:
    """Audits the causal graph for integrity, reachability, and isolation invariants."""

    def __init__(self, log: Any) -> None:
        self.log = log

    def get_events(self, run_id: str | None = None) -> list[Event]:
        """Fetch events from log, optionally filtering by run_id."""
        events_fn = getattr(self.log, "events", None)
        if callable(events_fn):
            raw = list(events_fn())
        elif hasattr(self.log, "__iter__"):
            raw = list(self.log)
        else:
            raw = []

        if run_id is not None:
            return [e for e in raw if e.run_id is None or e.run_id == run_id]
        return raw

    def get_event(self, event_id: str) -> Event | None:
        """Fetch a specific event by ID from log."""
        getter = getattr(self.log, "get", None)
        if callable(getter):
            ev = getter(event_id)
            if isinstance(ev, Event):
                return ev
        for ev in self.get_events():
            if ev.id == event_id:
                return ev
        return None

    def get_ancestors(self, event_id: str) -> set[str]:
        """Return the starting event and all reachable ancestor event IDs."""
        ancestors_fn = getattr(self.log, "ancestors", None)
        if callable(ancestors_fn):
            try:
                return set(ancestors_fn(event_id))
            except Exception:
                pass  # fallback to in-memory traversal

        visited: set[str] = set()
        queue: list[str] = [event_id]
        while queue:
            curr_id = queue.pop(0)
            if curr_id in visited:
                continue
            visited.add(curr_id)
            curr_ev = self.get_event(curr_id)
            if curr_ev is not None:
                for p_id in curr_ev.causal_parent_ids:
                    if p_id not in visited:
                        queue.append(p_id)
        return visited

    def check_dangling_parents(self, run_id: str | None = None) -> list[str]:
        """Verify that every declared causal parent ID exists in storage (Hard Violation)."""
        violations: list[str] = []
        for event in self.get_events(run_id):
            for parent_id in event.causal_parent_ids:
                if self.get_event(parent_id) is None:
                    violations.append(
                        f"Dangling causal parent: Event {event.id} (agent {event.agent_id}, seq {event.logical_seq}) "
                        f"declares parent '{parent_id}' which does not exist in storage."
                    )
        return violations

    def check_cross_run_isolation(self, run_id: str | None = None) -> list[str]:
        """Verify that events do not reference causal parents from foreign runs (Hard Violation)."""
        violations: list[str] = []
        for event in self.get_events(run_id):
            if event.run_id is not None:
                for parent_id in event.causal_parent_ids:
                    parent_ev = self.get_event(parent_id)
                    if parent_ev is not None and parent_ev.run_id is not None and parent_ev.run_id != event.run_id:
                        violations.append(
                            f"Cross-run edge violation: Event {event.id} (run '{event.run_id}') "
                            f"references parent {parent_ev.id} from foreign run '{parent_ev.run_id}'."
                        )
        return violations

    def check_intra_agent_continuity(self, run_id: str | None = None) -> tuple[list[str], list[str]]:
        """Verify sequence monotonicity, uniqueness, and progression within each agent."""
        violations: list[str] = []
        warnings: list[str] = []

        by_agent: dict[str, list[Event]] = defaultdict(list)
        for event in self.get_events(run_id):
            by_agent[event.agent_id].append(event)

        for agent_id, agent_events in by_agent.items():
            agent_events.sort(key=lambda e: e.logical_seq)
            seen_seqs: dict[int, str] = {}

            for i, event in enumerate(agent_events):
                # 1. Sequence collisions (uniqueness violation)
                if event.logical_seq in seen_seqs:
                    other_id = seen_seqs[event.logical_seq]
                    violations.append(
                        f"Sequence collision on agent {agent_id}: Events {event.id} and {other_id} "
                        f"both have logical_seq {event.logical_seq}."
                    )
                else:
                    seen_seqs[event.logical_seq] = event.id

                # 2. Lamport progression rule: event.logical_seq > parent.logical_seq
                for parent_id in event.causal_parent_ids:
                    parent_ev = self.get_event(parent_id)
                    if parent_ev is not None and parent_ev.logical_seq >= event.logical_seq:
                        violations.append(
                            f"Lamport progression violated: Event {event.id} (seq {event.logical_seq}) "
                            f"has parent {parent_ev.id} with greater or equal seq {parent_ev.logical_seq}."
                        )

                # 3. Soft Warning: Intermediate event on an agent with zero parents
                if i > 0 and not event.causal_parent_ids:
                    warnings.append(
                        f"Timeline gap on agent {agent_id}: Event {event.id} (seq {event.logical_seq}) "
                        f"has no causal parents and does not link to previous event {agent_events[i-1].id}."
                    )

        return violations, warnings

    def check_decision_ports(self, decision: DecisionContract) -> tuple[list[str], list[str]]:
        """Verify that all decision ports exist and resolve to valid ancestors of the decision event."""
        violations: list[str] = []
        warnings: list[str] = []

        decision_ev = self.get_event(decision.decision_event_id)
        if decision_ev is None:
            violations.append(
                f"Decision event '{decision.decision_event_id}' for decision '{decision.decision_id}' "
                f"does not exist in storage."
            )
            return violations, warnings

        ancestor_ids = self.get_ancestors(decision.decision_event_id)

        for port in decision.ports:
            source_ev = self.get_event(port.source_event_id)
            if source_ev is None:
                violations.append(
                    f"Decision port '{port.port_id}' references non-existent source_event_id '{port.source_event_id}'."
                )
            elif port.source_event_id not in ancestor_ids:
                violations.append(
                    f"Decision port '{port.port_id}' source event '{port.source_event_id}' "
                    f"is not an ancestor of decision event '{decision.decision_event_id}'."
                )

            if port.baseline_value is None and not port.description:
                warnings.append(
                    f"Decision port '{port.port_id}' has a null baseline_value without descriptive documentation."
                )

        return violations, warnings

    def validate_run(
        self,
        run_id: str | None = None,
        decisions: list[DecisionContract] | None = None,
    ) -> ValidationReport:
        """Run all validation checks and return an aggregated ValidationReport."""
        violations: list[str] = []
        warnings: list[str] = []

        violations.extend(self.check_dangling_parents(run_id))
        violations.extend(self.check_cross_run_isolation(run_id))

        continuity_violations, continuity_warnings = self.check_intra_agent_continuity(run_id)
        violations.extend(continuity_violations)
        warnings.extend(continuity_warnings)

        if decisions:
            for decision in decisions:
                port_violations, port_warnings = self.check_decision_ports(decision)
                violations.extend(port_violations)
                warnings.extend(port_warnings)

        # Also discover any DecisionContracts embedded directly in event payloads
        for event in self.get_events(run_id):
            embedded_contract = DecisionContract.from_event(event)
            if embedded_contract is not None:
                port_violations, port_warnings = self.check_decision_ports(embedded_contract)
                violations.extend(port_violations)
                warnings.extend(port_warnings)

        events_count = len(self.get_events(run_id))
        return ValidationReport(
            is_valid=len(violations) == 0,
            violations=violations,
            warnings=warnings,
            details={
                "run_id": run_id,
                "event_count": events_count,
                "violation_count": len(violations),
                "warning_count": len(warnings),
            },
        )
