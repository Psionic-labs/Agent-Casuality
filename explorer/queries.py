"""Read-only query helpers behind the explorer's JSON API.

Every helper reuses an existing analysis function (structural slicing,
benchmark scoring, evidence packaging) and converts the result into
JSON-serializable dicts. Nothing here writes to any store.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from benchmark.opencode.scoring import score_diagnosis
from core.explain import build_evidence_package, render_evidence_summary
from core.slicing import structural_slice


def jsonable(obj: Any) -> Any:
    """Round-trip through JSON so datetimes/sets become plain values."""
    return json.loads(json.dumps(obj, default=str))


def _common(event: Any) -> dict[str, Any]:
    payload = getattr(event, "payload", {})
    return payload if isinstance(payload, dict) else {}


def _inner(event: Any) -> dict[str, Any]:
    inner = _common(event).get("payload", {})
    return inner if isinstance(inner, dict) else {}


def short_label(event: Any) -> str:
    """One-line human label: event type plus the interesting OpenCode detail."""
    kind = str(_common(event).get("opencode_kind", ""))
    inner = _inner(event)
    tool = str(inner.get("tool", ""))
    args = inner.get("args", {})
    detail = ""
    if isinstance(args, dict):
        detail = str(args.get("command") or args.get("filePath") or args.get("path") or "")
    if not detail and kind == "event:file.edited":
        detail = str(inner.get("file", ""))
    if tool:
        headline = tool + (f" {detail}" if detail else "")
    else:
        headline = detail or kind or getattr(event, "event_type", "")
    return f"{getattr(event, 'event_type', '')} · {headline}".strip(" ·")


def _role_of(event_id: str, resolved: dict[str, list[str]]) -> str | None:
    for role, ids in resolved.items():
        if event_id in ids:
            return role
    return None


def _failure_slice_ids(dataset: Any) -> set[str]:
    failure_id = dataset.failure.get("failure_event_id")
    if not failure_id:
        return set()
    try:
        return set(structural_slice(failure_id, dataset.log).event_ids)
    except Exception:
        return set()


def graph_overview(dataset: Any) -> dict[str, Any]:
    """Nodes and causal edges for the DAG view, in deterministic order."""
    known = {getattr(e, "id", "") for e in dataset.events}
    slice_ids = _failure_slice_ids(dataset)
    ordered = sorted(
        dataset.events,
        key=lambda e: (
            getattr(e, "logical_seq", 0),
            getattr(e, "agent_id", ""),
            getattr(e, "id", ""),
        ),
    )
    nodes = [
        {
            "id": getattr(e, "id", ""),
            "event_type": getattr(e, "event_type", ""),
            "opencode_kind": str(_common(e).get("opencode_kind", "")),
            "agent_id": getattr(e, "agent_id", ""),
            "logical_seq": getattr(e, "logical_seq", 0),
            "wall_time": str(getattr(e, "wall_time", "")),
            "label": short_label(e),
            "role": _role_of(getattr(e, "id", ""), dataset.resolved_roles),
            "in_failure_slice": getattr(e, "id", "") in slice_ids,
        }
        for e in ordered
    ]
    edges = [
        {"parent": parent, "child": getattr(e, "id", "")}
        for e in ordered
        for parent in (getattr(e, "causal_parent_ids", []) or [])
        if parent in known
    ]
    failure = dataset.failure
    return {
        "source": dataset.source,
        "event_count": len(nodes),
        "edge_count": len(edges),
        "failure_event_id": failure.get("failure_event_id"),
        "failure_status": failure.get("status"),
        "failure_method": failure.get("method"),
        "nodes": nodes,
        "edges": edges,
    }


def failure_report(dataset: Any) -> dict[str, Any]:
    """How the failure target was chosen, and which roles resolved where."""
    by_id = {getattr(e, "id", ""): e for e in dataset.events}
    roles = {}
    for role, ids in dataset.resolved_roles.items():
        roles[role] = [
            {"event_id": i, "label": short_label(by_id[i]) if i in by_id else i} for i in ids
        ]
    return {
        "failure_event_id": dataset.failure.get("failure_event_id"),
        "status": dataset.failure.get("status"),
        "method": dataset.failure.get("method"),
        "is_fallback": dataset.failure.get("method") == "fallback",
        "has_ground_truth": bool(dataset.spec.get("causal_roles")),
        "roles": roles,
        "unresolved_roles": list(dataset.unresolved_roles),
        "expected_structural_roles": list(dataset.spec.get("expected_structural_roles", [])),
    }


def diagnosis_report(dataset: Any) -> dict[str, Any]:
    """The six benchmark diagnosis dimensions for the resolved failure."""
    failure_id = dataset.failure.get("failure_event_id")
    if not failure_id:
        return {"status": "no_events", "dimensions": {}}
    result = score_diagnosis(
        dataset.log, dataset.events, dataset.spec, dataset.resolved_roles, failure_id
    )
    return jsonable({"status": "ok", "dimensions": result})


def event_detail(dataset: Any, event_id: str) -> dict[str, Any]:
    """One event with its declared parents and observed children."""
    event = dataset.log.get(event_id)
    if event is None:
        raise KeyError(f"unknown event {event_id}")
    by_id = {getattr(e, "id", ""): e for e in dataset.events}
    parents = [p for p in (getattr(event, "causal_parent_ids", []) or [])]
    children = sorted(
        getattr(e, "id", "")
        for e in dataset.events
        if event_id in (getattr(e, "causal_parent_ids", []) or [])
    )
    record = jsonable(getattr(event, "to_record", lambda: {})())
    return {
        "id": event_id,
        "label": short_label(event),
        "role": _role_of(event_id, dataset.resolved_roles),
        "in_failure_slice": event_id in _failure_slice_ids(dataset),
        "parents": [
            {"event_id": p, "label": short_label(by_id[p]) if p in by_id else p} for p in parents
        ],
        "children": [
            {"event_id": c, "label": short_label(by_id[c]) if c in by_id else c} for c in children
        ],
        "record": record,
    }


def evidence_report(dataset: Any) -> dict[str, Any]:
    """Evidence package plus rendered summary for the failure event."""
    failure_id = dataset.failure.get("failure_event_id")
    if not failure_id:
        return {"status": "no_events", "summary": "", "package": {}}
    package = build_evidence_package(failure_id, dataset.log)
    return jsonable(
        {"status": "ok", "summary": render_evidence_summary(package), "package": package}
    )


_ai_cache: dict[tuple[str, str], dict[str, Any]] = {}
_ai_cache_lock = threading.Lock()


def _split_explanation(text: str) -> dict[str, Any]:
    """Split validated model text into its three enforced sections."""
    diagnosis, _, rest = text.partition("Evidence:")
    evidence, _, limitations = rest.partition("Limitations:")
    bullets = [
        line.strip()[1:].strip()
        for line in evidence.strip().splitlines()
        if line.strip().startswith("-")
    ]
    return {
        "diagnosis": diagnosis.replace("Diagnosis:", "", 1).strip(),
        "evidence": bullets,
        "limitations": limitations.strip(),
    }


def ai_diagnosis_report(
    dataset: Any,
    explain_fn: Callable[[dict[str, Any]], str] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Model interpretation of the failure, quarantined from recorded facts.

    Returns an (HTTP status, payload) pair. The payload is either the
    sectioned interpretation or a machine-readable error (ai_unavailable /
    format_rejected / ai_error). Anything the model says stays labeled as
    interpretation; recorded evidence keeps coming from /api/evidence.
    """
    failure_id = dataset.failure.get("failure_event_id")
    if not failure_id:
        return 200, {"status": "no_events", "sections": {}, "model": None}
    try:
        from core.explain import DEFAULT_MODEL, explain, explanation_matches_format
    except ImportError:
        return 503, {
            "status": "ai_unavailable",
            "hint": "httpx is not installed; install the explain extra to enable AI analysis.",
        }
    cache_key = (str(dataset.source), str(failure_id))
    with _ai_cache_lock:
        hit = _ai_cache.get(cache_key)
    if hit is not None:
        return 200, hit
    package = build_evidence_package(failure_id, dataset.log)
    try:
        text = (explain_fn or explain)(jsonable(package))
    except ValueError:
        return 503, {
            "status": "ai_unavailable",
            "hint": "set OPENROUTER_API_KEY (or OPENROUTER_MODEL) to enable AI analysis.",
        }
    except RuntimeError as exc:
        return 502, {"status": "ai_error", "error": str(exc)}
    if not explanation_matches_format(text, package):
        return 502, {
            "status": "format_rejected",
            "error": "model output violated the Diagnosis/Evidence/Limitations contract.",
        }
    payload = jsonable(
        {
            "status": "ok",
            "model": os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "sections": _split_explanation(text),
        }
    )
    with _ai_cache_lock:
        _ai_cache[cache_key] = payload
    return 200, payload
