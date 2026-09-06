"""Phase 5 tests: counterfactual replay, Shapley-Owen interaction attribution, and ddmin.

Tests the shared counterfactual reasoning primitive (thesis §16, §17, §30.5-30.7):
1. Counterfactual baseline substitution on the fixture decision.
2. Refusal on side-effecting decisions (ReplayUnsafe).
3. Ground-truth acceptance test: B3 x C3 interaction and 1-minimal slice {"B3", "C3", "A3", "A4"}.
4. ddmin budget cap enforcement.
5. ddmin cache hit verification.
6. CLI subcommands (replay, interaction, minimize).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from cli.main import FixtureEventLog, main
from core.decision import (
    DecisionPort,
    create_decision_contract,
    create_fixture_decision,
)
from core.replay import (
    SIDE_EFFECTING_TOOLS,
    PortIntervention,
    ReplayUnsafe,
    compute_shapley_interaction,
    counterfactual_replay,
    ddmin,
    test_fn_from,
)
from core.slicing import structural_slice

FIXTURE_PATH = Path(__file__).parent.parent / "fixture" / "fixture.json"


@pytest.fixture
def fixture_data() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def fixture_log(fixture_data: dict[str, Any]) -> FixtureEventLog:
    return FixtureEventLog(fixture_data)


# ============================================================================
# 1. Counterfactual Replay & Baseline Invariants
# ============================================================================


def test_counterfactual_replay_all_baselines_reverses_failure():
    """Evaluating the fixture decision with all ports at baseline must not produce failure."""
    contract = create_fixture_decision()
    # Substitute all ports to their baseline values
    interventions = [
        PortIntervention(port_id=p.port_id, substitute_value=p.baseline_value)
        for p in contract.ports
    ]
    cf_outcome = counterfactual_replay(contract, interventions, mode="recorded_output")

    # Invariant: outcome must not be the recorded failure
    assert cf_outcome != contract.outcome
    assert cf_outcome == "success"


def test_counterfactual_replay_unmodified_reproduces_failure():
    """Replaying with zero interventions must reproduce recorded failure."""
    contract = create_fixture_decision()
    outcome = counterfactual_replay(contract, [], mode="recorded_output")
    assert outcome == contract.outcome
    assert outcome == "failure"


# ============================================================================
# 2. Side-Effect Safety & Explicit Refusal
# ============================================================================


def test_counterfactual_replay_refuses_when_is_side_effecting():
    """Decisions marked is_side_effecting must raise ReplayUnsafe immediately."""
    contract = create_fixture_decision()
    side_effecting_contract = create_decision_contract(
        decision_id=contract.decision_id,
        run_id=contract.run_id,
        agent_id=contract.agent_id,
        decision_event_id=contract.decision_event_id,
        ports=contract.ports,
        decision_type=contract.decision_type,
        outcome=contract.outcome,
        is_side_effecting=True,
    )
    with pytest.raises(ReplayUnsafe, match="side-effecting"):
        counterfactual_replay(side_effecting_contract, [])


def test_counterfactual_replay_refuses_structured_side_effect_category():
    """Decisions with metadata['tool_category'] in SIDE_EFFECTING_TOOLS must raise ReplayUnsafe."""
    contract = create_fixture_decision()
    for tool_cat in SIDE_EFFECTING_TOOLS:
        cat_contract = create_decision_contract(
            decision_id=contract.decision_id,
            run_id=contract.run_id,
            agent_id=contract.agent_id,
            decision_event_id=contract.decision_event_id,
            ports=contract.ports,
            decision_type=contract.decision_type,
            outcome=contract.outcome,
            metadata={"tool_category": tool_cat},
        )
        with pytest.raises(ReplayUnsafe, match="side-effecting"):
            counterfactual_replay(cat_contract, [])


def test_counterfactual_replay_allows_safe_metadata():
    """Decisions with non-side-effecting metadata must be allowed to replay."""
    contract = create_fixture_decision()
    safe_contract = create_decision_contract(
        decision_id=contract.decision_id,
        run_id=contract.run_id,
        agent_id=contract.agent_id,
        decision_event_id=contract.decision_event_id,
        ports=contract.ports,
        decision_type=contract.decision_type,
        outcome=contract.outcome,
        metadata={"tool_category": "search_query"},
    )
    outcome = counterfactual_replay(safe_contract, [])
    assert outcome == "failure"


# ============================================================================
# 3. Acceptance Test: Fixture Ground Truth Match
# ============================================================================


def test_fixture_matches_ground_truth(fixture_log: FixtureEventLog):
    """The system must reproduce fixture.json's ground truth exactly.

    - B3 x C3 interaction must be large and positive, p < 0.01.
    - Neither B3 nor C3 alone explains the failure.
    - Minimal slice of A4 via ddmin must reduce to exactly {B3, C3, A3, A4}.
    """
    contract = create_fixture_decision()
    interaction = compute_shapley_interaction(contract, samples_per_cell=5, seed=42)

    # B3 x C3 interaction must be large and positive, bootstrap_sign_proportion < 0.01
    # (meaning <1% of bootstrap samples show non-positive interaction)
    assert "B3_x_C3" in interaction
    assert interaction["B3_x_C3"]["value"] > 0
    assert interaction["B3_x_C3"]["bootstrap_sign_proportion"] < 0.01

    # Individual Shapley values exist and are positive
    assert "B3" in interaction
    assert "C3" in interaction
    assert interaction["B3"]["value"] > 0
    assert interaction["C3"]["value"] > 0

    # Minimal slice reduction over structural slice
    slice_result = structural_slice("A4", fixture_log)
    minimal = ddmin(slice_result.event_ids, test_fn_from(contract))
    assert set(minimal) == {"B3", "C3", "A3", "A4"}


# ============================================================================
# 4. ddmin Budget Cap Enforcement
# ============================================================================


def test_ddmin_respects_budget_cap_and_falls_back():
    """ddmin must not exceed its budget and must fall back to the unminimized slice."""
    contract = create_fixture_decision()
    candidates = ["A1", "B1", "C1", "B2", "C2", "B3", "C3", "A3", "A4"]
    test_fn = test_fn_from(contract)

    # Force exhaustion with budget=1 (where initial check or 1st chunk exceeds budget)
    minimal = ddmin(candidates, test_fn, budget=1)

    # Should fall back to the unminimized candidate list
    assert minimal == candidates


# ============================================================================
# 5. ddmin Caching Verification
# ============================================================================


def test_ddmin_caches_evaluations():
    """ddmin must cache test_fn calls on identical subsets."""
    mock_test = MagicMock(return_value=True)
    candidates = ["X", "Y", "Z"]

    # Run ddmin where mock returns True everywhere
    result = ddmin(candidates, mock_test, budget=50)

    # Distinct subsets passed to mock_test must equal total calls (no redundant calls)
    invoked_subsets = [frozenset(call.args[0]) for call in mock_test.call_args_list]
    assert len(invoked_subsets) == len(set(invoked_subsets))
    assert isinstance(result, list)


# ============================================================================
# 6. Shapley Port Limits (k > 4)
# ============================================================================


def test_shapley_rejects_more_than_four_ports():
    """compute_shapley_interaction must raise ValueError for k > 4."""
    ports = [
        DecisionPort(
            port_id=f"p{i}",
            source_event_id=f"E{i}",
            field_path=f"f{i}",
            recorded_value=1,
            baseline_value=0,
        )
        for i in range(5)
    ]
    contract = create_decision_contract(
        decision_id="dec_5_ports",
        run_id="run_1",
        agent_id="A",
        decision_event_id="E_dec",
        ports=ports,
        decision_type="policy_merge",
    )
    with pytest.raises(ValueError, match="Exact enumeration supports k <= 4"):
        compute_shapley_interaction(contract)


# ============================================================================
# 7. Downstream Replay Mode
# ============================================================================


def test_downstream_replay_mode(fixture_log: FixtureEventLog):
    """Downstream replay mode is not yet implemented; raises NotImplementedError."""
    contract = create_fixture_decision()
    error_msg = "downstream_replay mode validation is not yet fully implemented"
    with pytest.raises(NotImplementedError, match=error_msg):
        counterfactual_replay(
            contract,
            [PortIntervention("customer_status", "ineligible")],
            mode="downstream_replay",
            log=fixture_log,
        )


# ============================================================================
# 8. CLI Subcommands
# ============================================================================


def test_cli_replay_subcommand():
    """Test CLI 'replay' subcommand against fixture."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(
            [
                "--fixture",
                str(FIXTURE_PATH),
                "replay",
                "dec_customer_approval_A3",
                "customer_status=ineligible",
            ]
        )
    output = buf.getvalue()
    assert "Original outcome: failure" in output
    assert "Counterfactual outcome: success" in output


def test_cli_interaction_subcommand():
    """Test CLI 'interaction' subcommand against fixture."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(
            [
                "--fixture",
                str(FIXTURE_PATH),
                "interaction",
                "dec_customer_approval_A3",
                "--samples",
                "5",
            ]
        )
    data = json.loads(buf.getvalue())
    assert data["decision_id"] == "dec_customer_approval_A3"
    assert "B3_x_C3" in data
    assert data["B3_x_C3"]["value"] > 0
    assert data["B3_x_C3"]["bootstrap_sign_proportion"] < 0.01


def test_cli_minimize_subcommand():
    """Test CLI 'minimize' subcommand against fixture."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["--fixture", str(FIXTURE_PATH), "minimize", "A4"])
    output = buf.getvalue()
    assert "Minimal slice of A4: 4 events (ddmin)" in output
    assert "B3" in output
    assert "C3" in output
    assert "A3" in output
    assert "A4" in output
