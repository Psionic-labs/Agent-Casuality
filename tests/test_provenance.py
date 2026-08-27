"""Phase 4 tests: field-level provenance, exact vs coarse grades, and traversal invariants."""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from cli.main import main
from core.provenance import (
    InMemoryProvenanceStore,
    ProvenanceEdge,
    provenance,
    record_memory_write_provenance,
    record_model_call_provenance,
    record_tool_result_provenance,
    verify_chunk_sensitivity,
)
from sdk.events import AgentClock, Event, InMemoryEventLog, record_event
from sdk.tools import capture_tool

FIXTURE_PATH = Path(__file__).parent.parent / "fixture" / "fixture.json"


@pytest.fixture
def fixture_data() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def fixture_store(fixture_data: dict[str, Any]) -> InMemoryProvenanceStore:
    return InMemoryProvenanceStore(fixture_data.get("provenance_edges", []))


# ============================================================================
# 1. Acceptance Criteria & Fixture Contract Tests
# ============================================================================


def test_provenance_decision_input_returns_exact_fixture_edges(
    fixture_store: InMemoryProvenanceStore,
) -> None:
    """provenance('A3.output.approve') returns the exact edges predicted by fixture.json."""
    chain = provenance("A3.output.approve", fixture_store)

    assert len(chain) == 4
    assert chain.target_field_path == "A3.output.approve"
    assert len(chain.exact_edges) == 4
    assert len(chain.coarse_edges) == 0

    # The 2 immediate parents of approve
    immediate_sources = {
        edge.source_path
        for edge in chain.edges
        if edge.field_path == "A3.output.approve"
    }
    assert immediate_sources == {"output.customer_status", "output.risk_score"}

    # Propagated back to tool invocations
    all_field_paths = {edge.field_path for edge in chain.edges}
    assert all_field_paths == {
        "A3.output.approve",
        "B3.output.customer_status",
        "C3.output.risk_score",
    }


def test_provenance_llm_boundary_halts_at_coarse_grade(
    fixture_store: InMemoryProvenanceStore,
) -> None:
    """provenance('B2.args.query') returns exactly one coarse edge and halts at the LLM boundary."""
    chain = provenance("B2.args.query", fixture_store)

    assert len(chain) == 1
    edge = chain.edges[0]
    assert edge.field_path == "B2.args.query"
    assert edge.source_event_id == "B1"
    assert edge.grade == "coarse"
    assert edge.source_path is None
    assert len(chain.coarse_edges) == 1

    assert len(chain.exact_edges) == 0
    assert "LLM boundary" in chain.terminal_sources[0]


def test_provenance_full_chain_from_final_answer(fixture_store: InMemoryProvenanceStore) -> None:
    """Tracing from A4.final_answer traverses through A3 decision to upstream tool results."""
    chain = provenance("A4.final_answer", fixture_store)

    assert len(chain) == 5
    field_paths = [edge.field_path for edge in chain.edges]
    assert field_paths[0] == "A4.final_answer"
    assert chain.edges[0].source_path == "output.approve"
    assert all(edge.grade == "exact" for edge in chain.edges)


# ============================================================================
# 2. Schema Invariants & Traversal Properties
# ============================================================================


def test_coarse_edge_cannot_have_source_path() -> None:
    """Schema Invariant: A coarse provenance edge must enforce source_path=None."""
    with pytest.raises(ValueError, match="coarse provenance edge must have source_path=None"):
        ProvenanceEdge(
            run_id="run-1",
            field_path="some.field",
            source_event_id="evt-1",
            source_path="some.upstream.path",  # Invalid for coarse
            grade="coarse",
        )


def test_provenance_cycle_detection() -> None:
    """Cyclic provenance definitions do not cause infinite recursion."""
    store = InMemoryProvenanceStore()
    store.append(
        ProvenanceEdge(
            run_id="run-1",
            field_path="node.A",
            source_event_id="evt-1",
            source_path="node.B",
            grade="exact",
        )
    )
    store.append(
        ProvenanceEdge(
            run_id="run-1",
            field_path="node.B",
            source_event_id="evt-2",
            source_path="node.A",  # Cycle back to A
            grade="exact",
        )
    )

    chain = provenance("node.A", store)
    assert len(chain) == 2
    assert set(chain.visited_paths) == {"node.A", "node.B"}


def test_provenance_diamond_graph_deduplication() -> None:
    """Diamond provenance graphs resolve shared ancestors cleanly without duplication."""
    store = InMemoryProvenanceStore()
    # A -> B, A -> C, B -> D, C -> D
    store.append(
        ProvenanceEdge(
            run_id="run-1",
            field_path="root.A",
            source_event_id="evt-1",
            source_path="node.B",
            grade="exact",
        )
    )
    store.append(
        ProvenanceEdge(
            run_id="run-1",
            field_path="root.A",
            source_event_id="evt-1",
            source_path="node.C",
            grade="exact",
        )
    )
    store.append(
        ProvenanceEdge(
            run_id="run-1",
            field_path="node.B",
            source_event_id="evt-2",
            source_path="node.D",
            grade="exact",
        )
    )
    store.append(
        ProvenanceEdge(
            run_id="run-1",
            field_path="node.C",
            source_event_id="evt-3",
            source_path="node.D",
            grade="exact",
        )
    )

    chain = provenance("root.A", store)
    assert len(chain) == 4
    assert set(chain.visited_paths) == {"root.A", "node.B", "node.C", "node.D"}


# ============================================================================
# 3. Capture Helpers (Tool Result, Model Call, Memory Write)
# ============================================================================


def test_record_tool_result_provenance_helper() -> None:
    event = Event(
        id=str(uuid4()),
        agent_id="B",
        logical_seq=3,
        event_type="tool_result",
        payload={"output": {"status": "eligible"}},
        run_id=str(uuid4()),
    )
    log = InMemoryEventLog()
    edges = record_tool_result_provenance(
        event,
        {"output.status": "invocation.query"},
        store=log,
        transform="search_db",
    )

    assert len(edges) == 1
    edge = edges[0]
    assert edge.field_path == "B.output.status"
    assert edge.source_event_id == event.id
    assert edge.source_path == "invocation.query"
    assert edge.grade == "exact"
    assert edge.transform == "search_db"

    # Querying log via provenance traversal
    chain = provenance("B.output.status", log)
    assert len(chain) == 1
    assert chain.edges[0].id == edge.id


def test_record_model_call_provenance_helper() -> None:
    event = Event(
        id=str(uuid4()),
        agent_id="A",
        logical_seq=1,
        event_type="model_call",
        payload={"input": "prompt", "output": "plan"},
        run_id=str(uuid4()),
    )
    log = InMemoryEventLog()
    edges = record_model_call_provenance(
        event,
        ["B1.args.task", "C1.args.task"],
        store=log,
    )

    assert len(edges) == 2
    for edge in edges:
        assert edge.grade == "coarse"
        assert edge.source_path is None
        assert edge.source_event_id == event.id

    chain = provenance("B1.args.task", log)
    assert len(chain) == 1
    assert chain.edges[0].grade == "coarse"


def test_record_memory_write_provenance_helper() -> None:
    event = Event(
        id=str(uuid4()),
        agent_id="A",
        logical_seq=2,
        event_type="memory_write",
        payload={"key": "target", "val": "user_42"},
        run_id=str(uuid4()),
    )
    store = InMemoryProvenanceStore()
    edges = record_memory_write_provenance(
        event,
        {"mem://A/target": "tool_result.user_id"},
        store=store,
    )

    assert len(edges) == 1
    assert edges[0].field_path == "mem://A/target"
    assert edges[0].grade == "exact"
    assert edges[0].transform == "memory_write"


def test_capture_tool_with_field_sources_decorator() -> None:
    log = InMemoryEventLog()
    clock = AgentClock()

    @capture_tool(
        agent_id="Worker",
        clock=clock,
        log=log,
        run_id="run-test",
        field_sources={"output.customer_status": "invocation.user_id"},
        transform="customer_lookup",
    )
    def fetch_customer(user_id: str) -> dict[str, str]:
        return {"customer_status": "verified"}

    result = fetch_customer("user_99")
    assert result == {"customer_status": "verified"}

    # Check that provenance edge was automatically recorded in log
    chain = provenance("Worker.output.customer_status", log)
    assert len(chain) == 1
    edge = chain.edges[0]
    assert edge.field_path == "Worker.output.customer_status"
    assert edge.source_path == "invocation.user_id"
    assert edge.grade == "exact"
    assert edge.transform == "customer_lookup"


# ============================================================================
# 4. Context-Chunk Sensitivity Verification (Thesis §30.8)
# ============================================================================


def test_verify_chunk_sensitivity() -> None:
    model_event = Event(
        id="evt-model",
        agent_id="A",
        logical_seq=1,
        event_type="model_call",
        payload={
            "input": "System context: <chunk_1> User: What is the rate?",
            "output": "The rate is 5.4%",
        },
    )

    # If chunk is present, returns 5.4%; if masked, returns 0.0%
    def mock_evaluator(prompt: str) -> str:
        if "<chunk_1>" in prompt:
            return "The rate is 5.4%"
        return "Unknown rate"

    shift = verify_chunk_sensitivity(model_event, "chunk_1", mock_evaluator)
    assert shift == 1.0

    # Unrelated chunk has 0 sensitivity
    shift_unrelated = verify_chunk_sensitivity(model_event, "chunk_99", mock_evaluator)
    assert shift_unrelated == 0.0


# ============================================================================
# 5. CLI Rendering & Formatting Tests
# ============================================================================


def test_cli_provenance_command_renders_grades() -> None:
    """CLI provenance command renders explicitly tagged [exact] and [coarse] links."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["--fixture", str(FIXTURE_PATH), "provenance", "A3.output.approve"])
    output = buf.getvalue()

    assert "Provenance chain for A3.output.approve:" in output
    assert "[exact]" in output
    assert "A3.output.approve" in output

    buf_coarse = io.StringIO()
    with redirect_stdout(buf_coarse):
        main(["--fixture", str(FIXTURE_PATH), "provenance", "B2.args.query"])
    output_coarse = buf_coarse.getvalue()

    assert "Provenance chain for B2.args.query:" in output_coarse
    assert "[coarse]" in output_coarse
    assert "LLM boundary, halts" in output_coarse


# ============================================================================
# 6. PostgreSQL Integration Tests (if DATABASE_URL is available)
# ============================================================================


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="PostgreSQL DATABASE_URL not set",
)
def test_postgres_provenance_storage_and_recursive_query() -> None:
    import psycopg

    from storage.postgres import PostgresEventStore

    dsn = os.environ["DATABASE_URL"]
    conn = psycopg.connect(dsn)
    store = PostgresEventStore(conn)
    store.create_schema()

    run_id = str(uuid4())
    agent_id = str(uuid4())
    clock = AgentClock()

    # Seed run & agent
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO runs (id, name) VALUES (%s, %s)",
            (run_id, "test_provenance_run"),
        )
        cur.execute(
            "INSERT INTO agents (id, run_id, role) VALUES (%s, %s, %s)",
            (agent_id, run_id, "test_agent"),
        )
    conn.commit()


    # Record two events
    e1, _ = record_event(
        agent_id=agent_id,
        clock=clock,
        log=store,
        event_type="tool_call",
        payload={"task": "init"},
        run_id=run_id,
    )
    e2, _ = record_event(
        agent_id=agent_id,
        clock=clock,
        log=store,
        event_type="tool_result",
        payload={"output": {"score": 42}},
        causal_parent_ids=[e1.id],
        run_id=run_id,
    )

    edge1 = ProvenanceEdge(
        run_id=run_id,
        field_path="agent.decision.output",
        source_event_id=e2.id,
        source_path="agent.tool.result",
        grade="exact",
        transform="filter",
    )
    edge2 = ProvenanceEdge(
        run_id=run_id,
        field_path="agent.tool.result",
        source_event_id=e1.id,
        source_path=None,
        grade="coarse",
    )

    stored_edge1 = store.record_provenance_edge(edge1)
    stored_edge2 = store.record_provenance_edge(edge2)

    assert stored_edge1.field_path == "agent.decision.output"
    assert stored_edge2.grade == "coarse"

    # Query chain via PostgresEventStore
    chain_edges = store.query_provenance_chain("agent.decision.output", run_id=run_id)
    assert len(chain_edges) >= 2
    field_paths = {e.field_path for e in chain_edges}
    assert "agent.decision.output" in field_paths
    assert "agent.tool.result" in field_paths

    # Walk with provenance() traversal function
    chain = provenance("agent.decision.output", store, run_id=run_id)
    assert len(chain) == 2
    assert chain.edges[0].grade == "exact"
    assert chain.edges[1].grade == "coarse"
