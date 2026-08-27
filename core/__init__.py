"""Core engine: graph queries, state reconstruction/slicing, and provenance."""

from .graph import ancestors, assign_causal_parents, record_causal_event
from .provenance import (
    InMemoryProvenanceStore,
    ProvenanceChain,
    ProvenanceEdge,
    ProvenanceGrade,
    provenance,
    record_memory_write_provenance,
    record_model_call_provenance,
    record_provenance_edge,
    record_tool_result_provenance,
    verify_chunk_sensitivity,
)
from .reducer import AgentState, ReplayIntegrityError, hash_state, reconstruct, verify_snapshot
from .slicing import DecisionEvidence, StructuralSlice, structural_slice, why
from .snapshots import (
    SnapshotManager,
    SnapshotRecord,
    SnapshotStore,
    create_snapshot,
    should_snapshot,
)

__all__ = [
    "AgentState",
    "DecisionEvidence",
    "InMemoryProvenanceStore",
    "ProvenanceChain",
    "ProvenanceEdge",
    "ProvenanceGrade",
    "ReplayIntegrityError",
    "SnapshotManager",
    "SnapshotRecord",
    "SnapshotStore",
    "StructuralSlice",
    "ancestors",
    "assign_causal_parents",
    "create_snapshot",
    "hash_state",
    "provenance",
    "record_causal_event",
    "record_memory_write_provenance",
    "record_model_call_provenance",
    "record_provenance_edge",
    "record_tool_result_provenance",
    "reconstruct",
    "should_snapshot",
    "structural_slice",
    "verify_chunk_sensitivity",
    "verify_snapshot",
    "why",
]

