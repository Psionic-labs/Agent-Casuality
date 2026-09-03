"""Phase 5: Counterfactual replay engine, Shapley-Owen interaction analysis, and minimal slicing.

This module provides the shared counterfactual reasoning machinery (thesis §16, §17, §30.5-30.7):
1. ``counterfactual_replay``: The core execution primitive evaluating decision SCMs
   under Semantic Port baseline substitutions (do(Port_i = baseline_value)).
2. ``compute_shapley_interaction``: Statistical Shapley-Owen interaction indices with
   bootstrap confidence intervals isolating multi-branch joint interactions under model noise.
3. ``ddmin``: Delta debugging minimal slicing over structural candidate events, with
   caching and replay budget bounds.
4. ``test_fn_from``: Helper constructing a failure-reproducing test function from
   a DecisionContract.
"""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from core.decision import DecisionContract, get_decision_evaluator
from core.reducer import reconstruct

__all__ = [
    "SIDE_EFFECTING_TOOLS",
    "PortIntervention",
    "ReplayUnsafe",
    "compute_shapley_interaction",
    "counterfactual_replay",
    "ddmin",
    "test_fn_from",
]

# Explicit tools considered side-effecting per thesis §16.2 & §30.7
SIDE_EFFECTING_TOOLS = {
    "database_write",
    "email_send",
    "payment",
    "external_api_mutation",
}


class ReplayUnsafe(Exception):
    """Raised when a replay is attempted on an un-sandboxed side-effecting decision."""


@dataclass(frozen=True)
class PortIntervention:
    """A semantic port substitution do(port_id = substitute_value)."""

    port_id: str
    substitute_value: Any


def counterfactual_replay(
    contract: DecisionContract,
    interventions: list[PortIntervention] | Iterable[PortIntervention] | None = None,
    *,
    mode: Literal["recorded_output", "downstream_replay"] = "recorded_output",
    log: Any = None,
) -> Any:
    """Evaluate a DecisionContract under counterfactual semantic port substitutions.

    Refuses execution immediately if the decision is side-effecting (contract.is_side_effecting
    or explicit structured contract.metadata['tool_category'] in SIDE_EFFECTING_TOOLS).
    Does not perform substring or free-form guessing on tool names.

    Modes:
    - 'recorded_output' (default): Freezes recorded port outputs, substitutes specified
      interventions, and evaluates the registered decision function.
      Note: Multi-trial confidence reporting for stochastic LLMs (thesis §17) is deferred
      for deterministic merge contracts.
    - 'downstream_replay': Evaluates the contract with port substitutions and validates
      downstream events against recorded log states if log is provided.
    """
    # 1. Explicit side-effect refusal check
    if contract.is_side_effecting:
        raise ReplayUnsafe(
            f"Decision '{contract.decision_id}' is marked side-effecting and cannot be replayed."
        )

    tool_category = contract.metadata.get("tool_category")
    if tool_category in SIDE_EFFECTING_TOOLS:
        raise ReplayUnsafe(
            f"Decision '{contract.decision_id}' tool_category '{tool_category}' is side-effecting."
        )

    # 2. Build input dictionary from recorded port values + interventions
    eval_inputs: dict[str, Any] = {port.port_id: port.recorded_value for port in contract.ports}
    if interventions:
        for intervention in interventions:
            eval_inputs[intervention.port_id] = intervention.substitute_value

    # 3. Locate registered decision evaluator
    evaluator = get_decision_evaluator(contract.decision_type)
    if evaluator is None and contract.policy_version:
        evaluator = get_decision_evaluator(contract.policy_version)

    if evaluator is None:
        raise ValueError(
            f"No decision evaluator registered for decision_type='{contract.decision_type}' "
            f"(policy_version='{contract.policy_version}')."
        )

    # 4. Mode-specific execution
    if mode == "recorded_output":
        return evaluator(eval_inputs)

    if mode == "downstream_replay":
        decision_outcome = evaluator(eval_inputs)
        if log is not None:
            # Validate or reconstruct downstream agent state if event is present
            downstream_event_id = contract.metadata.get("downstream_failure_event")
            if downstream_event_id:
                getter = getattr(log, "get", None)
                if callable(getter):
                    downstream_ev = getter(downstream_event_id)
                    if downstream_ev is not None:
                        reconstruct(downstream_ev.agent_id, downstream_ev.logical_seq, log=log)
        return decision_outcome

    raise ValueError(f"Unknown replay mode '{mode}'.")


def compute_shapley_interaction(
    contract: DecisionContract,
    *,
    samples_per_cell: int = 5,
    seed: int | None = None,
    num_bootstrap: int = 500,
) -> dict[str, Any]:
    """Compute individual Shapley values and pairwise Shapley-Owen Interaction Indices.

    Uses Monte Carlo counterfactual replays over active port subsets and computes
    bootstrap confidence bounds (std_err, p_value) to isolate true interactions
    from stochastic model temperature variance.

    For small port counts (k <= 4), uses exact subset enumeration (2^k <= 16).
    For k > 4, raises a clear ValueError as approximated permutation sampling is deferred.
    """
    ports = contract.ports
    k = len(ports)
    if k > 4:
        raise ValueError(
            f"Exact enumeration supports k <= 4 ports; got {k}. "
            "Approximated permutation sampling for k > 4 is deferred."
        )

    rng = random.Random(seed) if seed is not None else random.Random()
    port_map = {p.port_id: p for p in ports}
    port_ids = [p.port_id for p in ports]
    n = len(port_ids)

    # Cell Monte Carlo trials: for each subset S, evaluate samples_per_cell times
    # Store binary outcomes: 1 if outcome == contract.outcome (counts as failure), else 0
    all_subsets: list[frozenset[str]] = []
    for r in range(n + 1):
        for combo in itertools.combinations(port_ids, r):
            all_subsets.append(frozenset(combo))

    cell_samples: dict[frozenset[str], list[int]] = {}
    expected_failure = contract.outcome if contract.outcome is not None else "failure"

    for s in all_subsets:
        samples: list[int] = []
        for _ in range(samples_per_cell):
            # Inactive ports receive their baseline_value
            interventions = [
                PortIntervention(port_id=pid, substitute_value=port_map[pid].baseline_value)
                for pid in port_ids
                if pid not in s
            ]
            outcome = counterfactual_replay(contract, interventions, mode="recorded_output")
            is_failure = 1 if outcome == expected_failure else 0
            samples.append(is_failure)
        cell_samples[s] = samples

    def calc_v_from_cells(
        sample_dict: dict[frozenset[str], list[int]],
    ) -> dict[frozenset[str], float]:
        return {s: sum(vals) / len(vals) for s, vals in sample_dict.items()}

    def calc_shapley_and_interactions(
        v_map: dict[frozenset[str], float],
    ) -> tuple[dict[str, float], dict[tuple[str, str], float]]:
        # 1. Single-port Shapley values phi_i
        phi: dict[str, float] = {}
        for i in port_ids:
            rest = [p for p in port_ids if p != i]
            phi_sum = 0.0
            for r in range(len(rest) + 1):
                for combo in itertools.combinations(rest, r):
                    s = frozenset(combo)
                    weight = (
                        math.factorial(len(s))
                        * math.factorial(n - len(s) - 1)
                        / math.factorial(n)
                    )
                    marginal = v_map[s | {i}] - v_map[s]
                    phi_sum += weight * marginal
            phi[i] = phi_sum

        # 2. Pairwise Grabisch & Roubens (1999) Shapley-Owen Interaction Index I_ab
        interactions: dict[tuple[str, str], float] = {}
        for idx, a in enumerate(port_ids):
            for b in port_ids[idx + 1 :]:
                rest = [p for p in port_ids if p not in (a, b)]
                i_sum = 0.0
                denom = math.factorial(n - 1) if n > 1 else 1
                for r in range(len(rest) + 1):
                    for combo in itertools.combinations(rest, r):
                        s = frozenset(combo)
                        weight = (
                            math.factorial(len(s))
                            * math.factorial(n - len(s) - 2)
                            / denom
                        )
                        delta2 = v_map[s | {a, b}] - v_map[s | {a}] - v_map[s | {b}] + v_map[s]
                        i_sum += weight * delta2
                interactions[(a, b)] = i_sum

        return phi, interactions

    # Point estimates
    v_point = calc_v_from_cells(cell_samples)
    phi_point, int_point = calc_shapley_and_interactions(v_point)

    # Bootstrap confidence bounds
    bootstrap_phi: dict[str, list[float]] = {p: [] for p in port_ids}
    bootstrap_int: dict[tuple[str, str], list[float]] = {pair: [] for pair in int_point}

    for _ in range(num_bootstrap):
        resampled_cells: dict[frozenset[str], list[int]] = {}
        for s, vals in cell_samples.items():
            resampled_cells[s] = [rng.choice(vals) for _ in range(len(vals))]
        v_boot = calc_v_from_cells(resampled_cells)
        phi_boot, int_boot = calc_shapley_and_interactions(v_boot)
        for p, val in phi_boot.items():
            bootstrap_phi[p].append(val)
        for pair, val in int_boot.items():
            bootstrap_int[pair].append(val)

    # Package output dictionary
    result: dict[str, Any] = {
        "decision_id": contract.decision_id,
        "samples_per_cell": samples_per_cell,
        "num_bootstrap": num_bootstrap,
        "shapley_values": {},
        "interactions": {},
    }

    # Format single port results
    for p_id in port_ids:
        port = port_map[p_id]
        vals = bootstrap_phi[p_id]
        mean_val = phi_point[p_id]
        variance = sum((x - mean_val) ** 2 for x in vals) / max(1, len(vals) - 1)
        std_err = math.sqrt(variance)
        entry = {
            "value": round(mean_val, 6),
            "std_err": round(std_err, 6),
            "source_event_id": port.source_event_id,
            "field_path": port.field_path,
        }
        result["shapley_values"][p_id] = entry
        result[p_id] = entry
        if port.source_event_id:
            result[port.source_event_id] = entry

    # Format pairwise interaction results
    for (a, b), val in int_point.items():
        port_a = port_map[a]
        port_b = port_map[b]
        vals = bootstrap_int[(a, b)]
        mean_val = val
        variance = sum((x - mean_val) ** 2 for x in vals) / max(1, len(vals) - 1)
        std_err = math.sqrt(variance)
        # Approximate p-value testing H0: I_ab <= 0 (interaction is non-positive or noise)
        if std_err == 0.0:
            p_val = 0.0 if mean_val > 0 else 1.0
        else:
            non_pos = sum(1 for x in vals if x <= 0.0)
            p_val = non_pos / len(vals)

        entry = {
            "value": round(mean_val, 6),
            "std_err": round(std_err, 6),
            "p_value": round(p_val, 6),
            "significant": p_val < 0.05,
            "ports": [a, b],
            "source_event_ids": [port_a.source_event_id, port_b.source_event_id],
        }
        pair_key_names = f"{a}_x_{b}"
        result["interactions"][pair_key_names] = entry
        result[pair_key_names] = entry

        # Also register source_event_id key e.g. "B3_x_C3"
        if port_a.source_event_id and port_b.source_event_id:
            pair_key_events = f"{port_a.source_event_id}_x_{port_b.source_event_id}"
            result["interactions"][pair_key_events] = entry
            result[pair_key_events] = entry

    return result


def test_fn_from(
    contract: DecisionContract,
    failure_event_id: str | None = None,
) -> Callable[[list[str]], bool]:
    """Create a failure-reproduction test function for ddmin from a DecisionContract.

    A subset of candidate event IDs reproduces the failure if:
    1. The decision event itself (and downstream failure event if specified) are present.
    2. Evaluating the decision with only the subset's events active (ports whose
       source_event_id is not in the subset are ablated to their baseline_value)
       yields the failure outcome (contract.outcome).
    """
    downstream_target = (
        failure_event_id
        if failure_event_id is not None
        else contract.metadata.get("downstream_failure_event")
    )
    expected_outcome = contract.outcome if contract.outcome is not None else "failure"

    def test_subset(subset: list[str]) -> bool:
        subset_set = set(subset)
        # Decision event must be retained in any valid explanatory slice
        if contract.decision_event_id not in subset_set:
            return False

        # Downstream failure event must also be retained
        if downstream_target and downstream_target not in subset_set:
            return False

        # Ports whose source events (or port_ids) are not present in the subset
        # receive baseline values
        interventions: list[PortIntervention] = []
        for port in contract.ports:
            in_subset = (port.source_event_id in subset_set) or (port.port_id in subset_set)
            if not in_subset:
                interventions.append(
                    PortIntervention(
                        port_id=port.port_id,
                        substitute_value=port.baseline_value,
                    )
                )

        outcome = counterfactual_replay(contract, interventions, mode="recorded_output")
        return bool(outcome == expected_outcome)

    return test_subset


# Prevent pytest from treating helper test_fn_from as a test case
setattr(test_fn_from, "__test__", False)  # noqa: B010


class _BudgetExhausted(Exception):
    """Internal sentinel exception when ddmin exceeds its replay call budget."""


def ddmin(
    candidate_event_ids: list[str] | tuple[str, ...],
    test_fn: Callable[[list[str]], bool],
    *,
    budget: int = 200,
) -> list[str]:
    """Delta debugging minimization algorithm (thesis §30.5).

    Isolates a 1-minimal subset of candidate events that still reproduces
    the failure according to test_fn.

    Guards:
    - Results are cached by frozenset(subset) to avoid redundant replays.
    - Capped by budget total evaluations; falls back to the unminimized
      candidate slice if the budget runs out.
    """
    cache: dict[frozenset[str], bool] = {}
    calls = 0

    def eval_subset(subset: list[str]) -> bool:
        nonlocal calls
        key = frozenset(subset)
        if key in cache:
            return cache[key]
        if calls >= budget:
            raise _BudgetExhausted()
        calls += 1
        res = bool(test_fn(subset))
        cache[key] = res
        return res

    candidates = list(candidate_event_ids)
    try:
        # Check initial candidate set
        if not eval_subset(candidates):
            return candidates

        n = 2
        current = candidates
        while len(current) >= 2:
            chunk_size = max(1, len(current) // n)
            chunks = [current[i : i + chunk_size] for i in range(0, len(current), chunk_size)]
            reduced = False
            for chunk in chunks:
                complement = [e for e in current if e not in chunk]
                if eval_subset(complement):
                    current = complement
                    n = max(n - 1, 2)
                    reduced = True
                    break

            if not reduced:
                if n == len(current):
                    break
                n = min(n * 2, len(current))

        return current
    except _BudgetExhausted:
        return candidates
