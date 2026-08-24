"""Core engine: graph queries (Phase 2) and state reconstruction/slicing (Phase 3)."""

from .graph import ancestors, assign_causal_parents, record_causal_event
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
    "ReplayIntegrityError",
    "SnapshotManager",
    "SnapshotRecord",
    "SnapshotStore",
    "StructuralSlice",
    "ancestors",
    "assign_causal_parents",
    "create_snapshot",
    "hash_state",
    "record_causal_event",
    "reconstruct",
    "should_snapshot",
    "structural_slice",
    "verify_snapshot",
    "why",
]
