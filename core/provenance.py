"""Phase 4: Field-level provenance and grade attribution (thesis section 12 & 30.8).

Provenance answers where a particular input or value entered into a decision
or state transition, distinguishing:
1. Exact provenance: tool results, memory reads/writes, and explicit transforms.
2. Coarse provenance: values downstream of an unverified LLM call.

Coarse provenance links enforce source_path=None and dead-end at the LLM boundary
during graph traversal rather than fabricating sub-token causality.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

ProvenanceGrade = Literal["exact", "coarse"]


@dataclass(frozen=True)
class ProvenanceEdge:
    """A directed provenance link connecting a field to its source event/path."""

    field_path: str
    source_event_id: str
    run_id: str
    source_path: str | None = None
    grade: ProvenanceGrade = "exact"
    transform: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        # Schema Invariant: coarse links have nowhere further to point
        if self.grade == "coarse" and self.source_path is not None:
            raise ValueError("coarse provenance edge must have source_path=None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "field_path": self.field_path,
            "source_event_id": self.source_event_id,
            "source_path": self.source_path,
            "grade": self.grade,
            "transform": self.transform,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvenanceEdge:
        created_at_raw = data.get("created_at")
        if isinstance(created_at_raw, str):
            created_at = datetime.fromisoformat(created_at_raw)
        elif isinstance(created_at_raw, datetime):
            created_at = created_at_raw
        else:
            created_at = datetime.now(UTC)

        return cls(
            id=str(data["id"]) if "id" in data else str(uuid4()),
            run_id=str(data.get("run_id", "")),
            field_path=str(data["field_path"]),
            source_event_id=str(data["source_event_id"]),
            source_path=data.get("source_path"),
            grade=data.get("grade", "exact"),
            transform=data.get("transform"),
            created_at=created_at,
        )


@dataclass
class ProvenanceChain:
    """The result of walking a provenance chain backward from a target field path."""

    target_field_path: str
    edges: list[ProvenanceEdge] = field(default_factory=list)
    visited_paths: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.edges)

    def __iter__(self) -> Iterable[ProvenanceEdge]:
        return iter(self.edges)

    def __getitem__(self, index: int) -> ProvenanceEdge:
        return self.edges[index]

    @property
    def exact_edges(self) -> list[ProvenanceEdge]:
        return [edge for edge in self.edges if edge.grade == "exact"]

    @property
    def coarse_edges(self) -> list[ProvenanceEdge]:
        return [edge for edge in self.edges if edge.grade == "coarse"]

    @property
    def terminal_sources(self) -> list[str]:
        """Field paths or events where traversal ended."""
        sources: list[str] = []
        for edge in self.edges:
            if edge.grade == "coarse":
                sources.append(f"event:{edge.source_event_id} (LLM boundary)")
            elif edge.source_path:
                sources.append(edge.source_path)
            else:
                sources.append(f"event:{edge.source_event_id}")
        return list(dict.fromkeys(sources))

    def render(self) -> str:
        """Render human-readable provenance chain with explicit grades."""
        if not self.edges:
            return f"No provenance edges recorded for {self.target_field_path}"
        lines = [f"Provenance chain for {self.target_field_path}:"]
        for edge in self.edges:
            grade_tag = f"[{edge.grade}]"
            transform_str = f" via {edge.transform}" if edge.transform else ""
            if edge.grade == "coarse":
                lines.append(
                    f"  {edge.field_path} <- event:{edge.source_event_id} "
                    f"{grade_tag}{transform_str} (LLM boundary, halts)"
                )
            else:
                target_str = edge.source_path or f"event:{edge.source_event_id}"
                lines.append(
                    f"  {edge.field_path} <- {target_str} "
                    f"{grade_tag}{transform_str} (from event {edge.source_event_id})"
                )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_field_path": self.target_field_path,
            "edges": [edge.to_dict() for edge in self.edges],
            "visited_paths": self.visited_paths,
            "terminal_sources": self.terminal_sources,
            "total_edges": len(self.edges),
            "exact_count": len(self.exact_edges),
            "coarse_count": len(self.coarse_edges),
        }


class InMemoryProvenanceStore:
    """Thread-safe in-memory store for provenance edges."""

    def __init__(self, edges: Iterable[ProvenanceEdge | dict[str, Any]] | None = None) -> None:
        self._edges: list[ProvenanceEdge] = []
        if edges:
            for item in edges:
                if isinstance(item, ProvenanceEdge):
                    self._edges.append(item)
                elif isinstance(item, dict):
                    self._edges.append(ProvenanceEdge.from_dict(item))

    def append(self, edge: ProvenanceEdge) -> ProvenanceEdge:
        self._edges.append(edge)
        return edge

    def extend(self, edges: Iterable[ProvenanceEdge]) -> list[ProvenanceEdge]:
        new_edges = list(edges)
        self._edges.extend(new_edges)
        return new_edges

    def get_by_field_path(
        self, field_path: str, run_id: str | None = None
    ) -> list[ProvenanceEdge]:
        return [
            e
            for e in self._edges
            if e.field_path == field_path and (run_id is None or e.run_id == run_id)
        ]

    def get_by_source_event_id(self, source_event_id: str) -> list[ProvenanceEdge]:
        return [e for e in self._edges if e.source_event_id == source_event_id]

    def all(self, run_id: str | None = None) -> list[ProvenanceEdge]:
        if run_id is None:
            return list(self._edges)
        return [e for e in self._edges if e.run_id == run_id]


def _extract_edges_from_source(
    source: Any, field_path: str, run_id: str | None
) -> list[ProvenanceEdge]:
    """Retrieve matching ProvenanceEdge items from various store implementations."""
    raw_edges: list[Any] = []
    if hasattr(source, "get_provenance_edges_for_field"):
        raw_edges = source.get_provenance_edges_for_field(field_path, run_id=run_id)
    elif hasattr(source, "get_by_field_path"):
        raw_edges = source.get_by_field_path(field_path, run_id=run_id)
    elif (
        hasattr(source, "provenance_store")
        and hasattr(source.provenance_store, "get_by_field_path")
    ):
        raw_edges = source.provenance_store.get_by_field_path(field_path, run_id=run_id)
    elif hasattr(source, "provenance_edges"):
        edges_source = source.provenance_edges
        if callable(edges_source):
            edges_source = edges_source()
        for raw in edges_source:
            if isinstance(raw, ProvenanceEdge) and raw.field_path == field_path:
                raw_edges.append(raw)
            elif isinstance(raw, dict) and raw.get("field_path") == field_path:
                raw_edges.append(raw)

    results: list[ProvenanceEdge] = []
    for raw in raw_edges:
        if isinstance(raw, ProvenanceEdge):
            if run_id is None or raw.run_id == run_id:
                results.append(raw)
        elif isinstance(raw, dict):
            edge_run_id = raw.get("run_id")
            if run_id is None or not edge_run_id or edge_run_id == run_id:
                results.append(ProvenanceEdge.from_dict(raw))
    return results


def provenance(
    field_path: str,
    store_or_log: Any,
    run_id: str | None = None,
) -> ProvenanceChain:
    """Walk the provenance chain backward from field_path.

    Traversal rules:
    - If edge.grade == 'exact' and edge.source_path is present, recursively continues.
    - If edge.grade == 'coarse' or edge.source_path is None, halts immediately at
      the LLM boundary, carrying the honesty from thesis section 12.
    - Uses cycle detection to prevent infinite loops on circular paths.
    """
    chain_edges: list[ProvenanceEdge] = []
    frontier: list[str] = [field_path]
    seen_paths: set[str] = set()
    seen_edge_ids: set[str] = set()

    while frontier:
        current_path = frontier.pop(0)
        if current_path in seen_paths:
            continue
        seen_paths.add(current_path)

        matches = _extract_edges_from_source(store_or_log, current_path, run_id)
        for edge in matches:
            if edge.id not in seen_edge_ids:
                seen_edge_ids.add(edge.id)
                chain_edges.append(edge)

            if edge.grade == "exact" and edge.source_path:
                next_path = edge.source_path
                # If source_path doesn't match any edges, try prefixing source_event_id
                if not _extract_edges_from_source(store_or_log, next_path, run_id):
                    has_prefix = (
                        edge.source_event_id
                        and not next_path.startswith(f"{edge.source_event_id}.")
                    )
                    if has_prefix:
                        qualified = f"{edge.source_event_id}.{next_path}"
                        if _extract_edges_from_source(store_or_log, qualified, run_id):
                            next_path = qualified

                if next_path not in seen_paths and next_path not in frontier:
                    frontier.append(next_path)

    return ProvenanceChain(
        target_field_path=field_path,
        edges=chain_edges,
        visited_paths=list(seen_paths),
    )


def record_provenance_edge(
    store_or_log: Any,
    edge: ProvenanceEdge,
) -> ProvenanceEdge:
    """Persist a provenance edge into the given store or log."""
    if isinstance(store_or_log, InMemoryProvenanceStore):
        return store_or_log.append(edge)
    if hasattr(store_or_log, "record_provenance_edge"):
        return store_or_log.record_provenance_edge(edge)
    if hasattr(store_or_log, "append_provenance_edge"):
        return store_or_log.append_provenance_edge(edge)
    if hasattr(store_or_log, "provenance_store") and hasattr(
        store_or_log.provenance_store, "append"
    ):
        return store_or_log.provenance_store.append(edge)
    if hasattr(store_or_log, "provenance_edges") and isinstance(
        store_or_log.provenance_edges, list
    ):
        store_or_log.provenance_edges.append(edge)
        return edge
    raise TypeError(f"Cannot record provenance edge to {type(store_or_log).__name__}")




def record_tool_result_provenance(
    event: Any,
    field_sources: dict[str, str],
    *,
    store: Any = None,
    transform: str | None = "tool_call",
    prefix_agent: bool = True,
) -> list[ProvenanceEdge]:
    """Record exact provenance edges for output fields of a tool result (thesis §30.8)."""
    edges: list[ProvenanceEdge] = []
    run_id = getattr(event, "run_id", "")
    agent_id = getattr(event, "agent_id", "")
    event_id = getattr(event, "id", "")

    for field_name, source_path in field_sources.items():
        if prefix_agent and not field_name.startswith(f"{agent_id}."):
            target_path = f"{agent_id}.{field_name}"
        else:
            target_path = field_name

        edge = ProvenanceEdge(
            run_id=run_id,
            field_path=target_path,
            source_event_id=event_id,
            source_path=source_path,
            grade="exact",
            transform=transform,
        )
        edges.append(edge)
        if store is not None:
            record_provenance_edge(store, edge)

    return edges


def record_model_call_provenance(
    event: Any,
    downstream_field_paths: list[str],
    *,
    store: Any = None,
    transform: str | None = None,
) -> list[ProvenanceEdge]:
    """Record coarse provenance edges for values passing through an LLM call (thesis §30.8)."""
    edges: list[ProvenanceEdge] = []
    run_id = getattr(event, "run_id", "")
    event_id = getattr(event, "id", "")

    for field_path in downstream_field_paths:
        edge = ProvenanceEdge(
            run_id=run_id,
            field_path=field_path,
            source_event_id=event_id,
            source_path=None,
            grade="coarse",
            transform=transform,
        )
        edges.append(edge)
        if store is not None:
            record_provenance_edge(store, edge)

    return edges


def record_memory_write_provenance(
    event: Any,
    field_sources: dict[str, str],
    *,
    store: Any = None,
    transform: str | None = "memory_write",
) -> list[ProvenanceEdge]:
    """Record exact provenance edges for memory writes."""
    edges: list[ProvenanceEdge] = []
    run_id = getattr(event, "run_id", "")
    event_id = getattr(event, "id", "")

    for field_name, source_path in field_sources.items():
        edge = ProvenanceEdge(
            run_id=run_id,
            field_path=field_name,
            source_event_id=event_id,
            source_path=source_path,
            grade="exact",
            transform=transform,
        )
        edges.append(edge)
        if store is not None:
            record_provenance_edge(store, edge)

    return edges


def verify_chunk_sensitivity(
    model_event: Any,
    chunk_id: str,
    evaluate_fn: Callable[[Any], Any],
    mask_fn: Callable[[Any, str], Any] | None = None,
    distance_fn: Callable[[Any, Any], float] | None = None,
) -> float:
    """Mask chunk_id with a neutral baseline and measure semantic output shift (thesis §30.8).

    If the sensitivity exceeds a threshold, coarse provenance can be empirically
    annotated or promoted to verified chunk-level provenance.
    """
    payload = getattr(model_event, "payload", {})
    prompt_input = payload.get("input")
    original_output = payload.get("output")

    if mask_fn is not None:
        masked_prompt = mask_fn(prompt_input, chunk_id)
    else:
        # Default string or list masking
        if isinstance(prompt_input, str):
            masked_prompt = prompt_input.replace(f"<{chunk_id}>", "[MASKED]")
        elif isinstance(prompt_input, list):
            masked_prompt = [
                msg
                for msg in prompt_input
                if not (isinstance(msg, dict) and msg.get("chunk_id") == chunk_id)
            ]
        else:
            masked_prompt = prompt_input

    perturbed_output = evaluate_fn(masked_prompt)

    if distance_fn is not None:
        return distance_fn(original_output, perturbed_output)

    # Fallback distance heuristic: 0.0 if identical, 1.0 if different
    return 0.0 if original_output == perturbed_output else 1.0
