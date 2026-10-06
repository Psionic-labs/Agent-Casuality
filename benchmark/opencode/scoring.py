"""Pure scoring helpers for the real OpenCode benchmark.

All functions operate on already-captured events/logs; nothing here runs
OpenCode. Capture failures (event missing from the trace) and diagnosis
failures (event present but analysis wrong) are reported separately.
"""

from __future__ import annotations

import json
import re
from typing import Any

from benchmark.scoring import pair_metrics, set_metrics
from core.explain import build_evidence_package, render_evidence_summary
from core.replay import ddmin
from core.slicing import structural_slice

EVENT_CLASSES = (
    "sessions",
    "model_calls",
    "tool_calls",
    "tool_results",
    "file_edits",
    "commands",
    "errors",
    "retries",
    "subagents",
    "completion",
)

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _common(event: Any) -> dict[str, Any]:
    payload = getattr(event, "payload", {})
    return payload if isinstance(payload, dict) else {}


def _inner(event: Any) -> dict[str, Any]:
    inner = _common(event).get("payload", {})
    return inner if isinstance(inner, dict) else {}


def classify_event(event: Any) -> set[str]:
    """Return the observable classes one captured event belongs to."""
    kind = str(_common(event).get("opencode_kind", ""))
    inner = _inner(event)
    classes: set[str] = set()
    if kind in {
        "event:session.created",
        "session.created",
        "event:session.deleted",
        "session.deleted",
    }:
        classes.add("sessions")
    if kind in {"event:message.updated", "message.updated"}:
        classes.add("model_calls")
    if kind in {"hook:tool.execute.before", "tool.execute.before"}:
        classes.add("tool_calls")
        tool_name = str(inner.get("tool", "")).lower()
        args = inner.get("args", {})
        if tool_name == "task" or (
            isinstance(args, dict)
            and "subagent" in json.dumps(args, default=str).lower()
        ):
            classes.add("subagents")
        # Shell executions are the observable form of commands/tests:
        # OpenCode emits command.executed only for slash-commands, while
        # `python test_x.py` runs through the bash tool.
        if tool_name in {"bash", "shell"} or (
            isinstance(args, dict) and "command" in args
        ):
            classes.add("commands")
    if kind in {"hook:tool.execute.after", "tool.execute.after"}:
        classes.add("tool_results")
        tool_name = str(inner.get("tool", "")).lower()
        if tool_name in {"bash", "shell"}:
            classes.add("commands")
    if kind in {"hook:tool.execute.after", "tool.execute.after"}:
        classes.add("tool_results")
    if kind in {"event:file.edited", "file.edited"}:
        classes.add("file_edits")
    if kind in {
        "event:command.executed",
        "command.executed",
        "hook:command.execute.before",
    }:
        classes.add("commands")
    if kind in {"event:session.error", "session.error"}:
        classes.add("errors")
    if kind in {"event:message.part.updated", "message.part.updated"}:
        part = inner.get("part", {})
        if isinstance(part, dict) and str(part.get("type", "")).lower() in {
            "retry",
            "subtask",
            "agent",
        }:
            if str(part.get("type", "")).lower() == "retry":
                classes.add("retries")
            else:
                classes.add("subagents")
    if kind in {"event:session.status", "session.status"}:
        status = inner.get("status", {})
        if isinstance(status, dict) and str(status.get("type", "")).lower() == "retry":
            classes.add("retries")
    if kind in {
        "event:session.deleted",
        "session.deleted",
        "event:session.idle",
        "session.idle",
    }:
        classes.add("completion")
    return classes


def _command_signature(event: Any) -> str | None:
    inner = _inner(event)
    name = inner.get("name") or inner.get("command") or inner.get("tool")
    args = inner.get("arguments", "")
    if isinstance(inner.get("args"), dict):
        args = inner["args"].get("command", args)
    if name:
        return f"{name} {args}".strip()
    return None


def capture_completeness(
    events: list[Any], expected: dict[str, Any]
) -> dict[str, Any]:
    """Score minimum expected event-class coverage per observable class.

    This is NOT general event precision/recall. Each class contributes
    ``min(1, captured / expected_min)`` and the overall figure is the mean
    over classes with ``available == True`` and ``min > 0`` only.
    Classes with min == 0 are reported informationally and excluded from
    the overall average, as are classes marked unavailable from OpenCode
    (e.g. terminal ``completion`` events in ``run`` mode). Repeat
    executions of the same command count as retries (in addition to
    explicit retry parts).
    """
    counts: dict[str, int] = {name: 0 for name in EVENT_CLASSES}
    file_edit_files: list[str] = []
    command_events = 0
    seen_signatures: set[str] = set()
    repeat_commands = 0
    for event in events:
        classes = classify_event(event)
        for name in classes:
            counts[name] += 1
        if "file_edits" in classes:
            uri = str(_common(event).get("resource_uri", ""))
            file_edit_files.append(uri)
        if "commands" in classes:
            command_events += 1
            sig = _command_signature(event)
            if sig is not None:
                if sig in seen_signatures:
                    repeat_commands += 1
                seen_signatures.add(sig)
    counts["retries"] += repeat_commands

    per_class: dict[str, Any] = {}
    recalls: list[float] = []
    class_names = list(EVENT_CLASSES) + [
        name for name in expected if name not in EVENT_CLASSES
    ]
    for name in class_names:
        spec = expected.get(name, {"min": 0, "available": True})
        minimum = int(spec.get("min", 0))
        available = bool(spec.get("available", True))
        captured = counts.get(name, 0)
        missing = max(0, minimum - captured) if available else 0
        recall = 1.0 if minimum == 0 else min(1.0, captured / minimum)
        if available and minimum > 0:
            recalls.append(recall)
        per_class[name] = {
            "expected_min": minimum,
            "available": available,
            "captured": captured,
            "missing": missing,
            "recall": round(recall, 3),
        }
    overall = round(sum(recalls) / len(recalls), 3) if recalls else 1.0
    return {
        "metric": "minimum_expected_event_class_coverage",
        "per_class": per_class,
        "command_count": command_events,
        "repeat_command_retries": repeat_commands,
        "file_edit_resources": file_edit_files,
        "overall_recall": overall,
        "overall_coverage": overall,
        "scored_classes": len(recalls),
    }


def _event_matches(event: Any, selector: dict[str, Any]) -> bool:
    common = _common(event)
    inner = _inner(event)
    kinds = selector.get("opencode_kind")
    if kinds and str(common.get("opencode_kind", "")) not in kinds:
        return False
    types = selector.get("event_type")
    if types and str(getattr(event, "event_type", "")) not in types:
        return False
    tool = selector.get("tool")
    if tool and str(inner.get("tool", "")) != str(tool):
        return False
    part_type = selector.get("part_type")
    if part_type:
        part = inner.get("part", {})
        if not isinstance(part, dict) or str(part.get("type", "")) != str(part_type):
            return False
    exit_code = selector.get("exit_code")
    if exit_code is not None and inner.get("exitCode") != exit_code:
        return False
    suffix = selector.get("path_suffix")
    if suffix:
        candidates: list[str] = []
        args = inner.get("args", {})
        if isinstance(args, dict):
            for key in ("filePath", "path"):
                value = args.get(key)
                if isinstance(value, str):
                    candidates.append(value)
        for key in ("file", "path"):
            value = inner.get(key)
            if isinstance(value, str):
                candidates.append(value)
        uri = common.get("resource_uri")
        if isinstance(uri, str):
            candidates.append(uri)
        if not any(str(item).endswith(str(suffix)) for item in candidates):
            return False
    text = selector.get("text_contains")
    if text and str(text) not in json.dumps(common, default=str):
        return False
    return True


def resolve_roles(
    events: list[Any], roles: list[dict[str, Any]]
) -> dict[str, Any]:
    """Resolve causal roles to event IDs in trace order.

    Roles are resolved sequentially so ``after_role`` can constrain a
    match to events occurring after another role's event.
    """
    resolved: dict[str, list[str]] = {}
    unresolved: list[str] = []
    index_of: dict[str, int] = {}
    for position, event in enumerate(events):
        index_of[getattr(event, "id", "")] = position
    for spec in roles:
        role = str(spec["role"])
        selector = dict(spec.get("selector", {}))
        after = selector.pop("after_role", None)
        after_index = -1
        if after is not None:
            earlier = resolved.get(str(after), [])
            if not earlier:
                if bool(spec.get("required", False)):
                    unresolved.append(role)
                resolved[role] = []
                continue
            after_index = max(index_of.get(item, -1) for item in earlier)
        matches = [
            getattr(event, "id", "")
            for position, event in enumerate(events)
            if position > after_index and _event_matches(event, selector)
        ]
        pick = str(selector.get("pick", "first"))
        if pick == "all":
            chosen = matches
        elif pick == "last":
            chosen = matches[-1:] if matches else []
        else:
            chosen = matches[:1]
        resolved[role] = chosen
        if not chosen and bool(spec.get("required", False)):
            unresolved.append(role)
    return {"resolved": resolved, "unresolved": sorted(unresolved)}


def resolve_failure(
    events: list[Any], failure_selector: dict[str, Any]
) -> dict[str, Any]:
    """Resolve the diagnosis target event (first matching alternative)."""
    for selector in failure_selector.get("any", []):
        matches = [
            getattr(event, "id", "") for event in events if _event_matches(event, selector)
        ]
        if matches:
            pick = str(selector.get("pick", "last"))
            return {
                "failure_event_id": matches[-1] if pick == "last" else matches[0],
                "status": "resolved",
                "method": "selector",
            }
    if events:
        return {
            "failure_event_id": getattr(events[-1], "id", ""),
            "status": "fallback_last_event",
            "method": "fallback",
        }
    return {"failure_event_id": None, "status": "no_events", "method": "none"}


def ancestors_of(log: Any, event_id: str) -> set[str]:
    """Iterative ancestor walk via causal_parent_ids (any log backend)."""
    getter = getattr(log, "get", None)
    seen: set[str] = set()
    pending = [event_id]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        event = getter(current) if callable(getter) else None
        if event is not None:
            for parent in getattr(event, "causal_parent_ids", []):
                if parent not in seen:
                    pending.append(parent)
    return seen


def _role_of(event_id: str, resolved: dict[str, list[str]]) -> str | None:
    for role, ids in resolved.items():
        if event_id in ids:
            return role
    return None


def score_diagnosis(
    log: Any,
    events: list[Any],
    spec: dict[str, Any],
    resolved: dict[str, list[str]],
    failure_event_id: str,
) -> dict[str, Any]:
    """Score diagnosis quality across six reported dimensions (no single score)."""
    by_id = {getattr(event, "id", ""): event for event in events}
    required_roles = [
        str(item["role"]) for item in spec.get("causal_roles", []) if item.get("required")
    ]
    required_ids = [i for role in required_roles for i in resolved.get(role, [])]
    expected_structural = [str(r) for r in spec.get("expected_structural_roles", [])]
    excluded_roles = [str(r) for r in spec.get("excluded_roles", [])]

    result: dict[str, Any] = {
        "failure_event_id": failure_event_id,
        "causal_minimality_overall": "not_measurable",
        "causal_interaction_overall": "unsupported",
    }

    try:
        structural = structural_slice(failure_event_id, log)
        slice_ids = list(structural.event_ids)
        slice_roles = sorted(
            {role for i in slice_ids if (role := _role_of(i, resolved)) is not None}
        )
        result["causal_slice"] = {
            "status": "ok",
            "metric": "structural_ancestor_recall",
            "label": (
                "structural ancestor presence (declared-dependency "
                "evidence; influence not proven; extra events not ignored)"
            ),
            "size": len(slice_ids),
            "roles": slice_roles,
            **set_metrics(slice_roles, expected_structural),
        }
    except Exception as exc:
        result["causal_slice"] = {"status": "error", "error": str(exc)}
        slice_ids = []

    try:
        raw_roles = result["causal_slice"].get("roles", [])
        slice_roles = [str(r) for r in raw_roles] if isinstance(raw_roles, list) else []
        identified = [r for r in required_roles if r in slice_roles]
        result["cause_identification"] = {
            "status": "ok",
            "identified": sorted(identified),
            "missed": sorted(set(required_roles) - set(identified)),
            "recall": round(len(identified) / max(1, len(required_roles)), 3),
        }
    except Exception as exc:
        result["cause_identification"] = {"status": "error", "error": str(exc)}

    try:
        # NOTE: live OpenCode traces carry no DecisionContract, so there is
        # no observable failure/decision predicate to re-evaluate after
        # removing events. The predicate below preserves ground-truth event
        # membership only. It must NOT be reported as causal minimality.
        must_keep = {failure_event_id, *required_ids}

        def membership(subset: list[str]) -> bool:
            return must_keep.issubset(set(subset))

        minimal = ddmin(list(slice_ids), membership, budget=200)
        minimal_roles = sorted(
            {role for i in minimal if (role := _role_of(i, resolved)) is not None}
        )
        leaked = sorted(
            role
            for role in excluded_roles
            if role in minimal_roles or any(i in minimal for i in resolved.get(role, []))
        )
        occurred_excluded = sorted(
            role for role in excluded_roles if resolved.get(role)
        )
        result["minimal_slice"] = {
            "status": "ok",
            "metric": "required_cause_preservation_proxy",
            "label": "required-cause preservation (minimality proxy; NOT causal minimality)",
            "method": "ddmin_with_ground_truth_membership_predicate",
            "causal_minimality": "not_measurable",
            "size": len(minimal),
            "structural_size": len(slice_ids),
            "reduction_ratio": round(1.0 - (len(minimal) / max(1, len(slice_ids))), 3),
            "roles": minimal_roles,
            "required_recall": round(
                sum(1 for r in required_roles if r in minimal_roles)
                / max(1, len(required_roles)),
                3,
            ),
            "distractors_leaked": leaked,
            "distractors_occurred": occurred_excluded,
            **{
                k: v
                for k, v in set_metrics(minimal_roles, expected_structural).items()
                if k in ("precision", "recall", "exact_match")
            },
        }
        # Explicit alias so consumers do not mistake the legacy key for a
        # causal-minimality claim.
        result["minimality_proxy"] = result["minimal_slice"]
    except Exception as exc:
        result["minimal_slice"] = {"status": "error", "error": str(exc)}

    try:
        resources = [str(r) for r in spec.get("expected_resources", [])]
        recovered = []
        for name in resources:
            hit = any(
                str(_common(e).get("resource_uri", "")).endswith(name) for e in events
            )
            if not hit:
                hit = any(
                    name in json.dumps(_inner(e), default=str) for e in events
                )
            if hit:
                recovered.append(name)
        edge_checks = []
        for writer_role, reader_role in spec.get("expected_edges", []):
            writers = resolved.get(str(writer_role), [])
            readers = resolved.get(str(reader_role), [])
            present = any(
                w in getattr(by_id.get(r), "causal_parent_ids", [])
                for w in writers
                for r in readers
                if r in by_id
            )
            edge_checks.append(
                {"edge": [writer_role, reader_role], "present": present}
            )
        result["provenance"] = {
            "status": "ok",
            "expected_resources": resources,
            "recovered_resources": sorted(recovered),
            "resource_recall": round(len(recovered) / max(1, len(resources)), 3),
            "expected_edges": edge_checks,
            "edges_present": sum(1 for e in edge_checks if e["present"]),
        }
    except Exception as exc:
        result["provenance"] = {"status": "error", "error": str(exc)}

    try:
        expected_pairs = [sorted(p) for p in spec.get("expected_interactions", [])]
        failure_ancestors = ancestors_of(log, failure_event_id)
        detected: list[list[str]] = []
        pair_details = []
        for pair in expected_pairs:
            if len(pair) != 2:
                continue
            left_ids = resolved.get(pair[0], [])
            right_ids = resolved.get(pair[1], [])
            if not left_ids or not right_ids:
                pair_details.append({"pair": pair, "detected": False, "reason": "unresolved"})
                continue
            both_in = all(i in failure_ancestors for i in (*left_ids, *right_ids))
            # Telemetry chains events linearly, so branch events are usually
            # reachable from one another; independence is reported
            # informationally and does not gate detection.
            left_anc = set().union(*(ancestors_of(log, i) - {i} for i in left_ids))
            right_anc = set().union(*(ancestors_of(log, i) - {i} for i in right_ids))
            independent = not (set(left_ids) & right_anc or set(right_ids) & left_anc)
            hit = both_in
            if hit:
                detected.append(sorted(pair))
            pair_details.append(
                {
                    "pair": pair,
                    "detected": hit,
                    "both_ancestors_of_failure": both_in,
                    "mutually_independent": independent,
                }
            )
        # NOTE: this checks joint ancestry (both branches reachable from
        # the failure via declared causal parents). It performs no
        # counterfactual intervention and no Shapley computation, so it
        # must NOT be reported as causal interaction. True causal
        # interaction is not measurable from a live OpenCode trace.
        result["interaction"] = {
            "status": "ok",
            "metric": "joint_ancestry",
            "label": "joint-branch ancestry detection (NOT causal interaction)",
            "method": "joint_ancestry_check",
            "causal_interaction": "not_measurable",
            "expected": expected_pairs,
            "detected": sorted(detected),
            "pairs": pair_details,
            **pair_metrics(detected, expected_pairs),
        }
        result["joint_ancestry"] = result["interaction"]
        result["causal_interaction"] = {
            "status": "unsupported",
            "reason": (
                "live OpenCode traces support no counterfactual "
                "intervention; joint ancestry is reported separately and "
                "must not be called causal interaction"
            ),
        }
    except Exception as exc:
        result["interaction"] = {"status": "error", "error": str(exc)}

    try:
        distractor_status = []
        for role in excluded_roles:
            occurred = bool(resolved.get(role))
            in_minimal = role in result.get("minimal_slice", {}).get("roles", [])
            if not occurred:
                state = "not_observed"
            elif in_minimal:
                state = "leaked"
            else:
                state = "excluded"
            distractor_status.append(
                {"role": role, "occurred": occurred, "state": state}
            )
        result["distractors"] = {
            "status": "ok",
            "roles": distractor_status,
            "leaked": sum(1 for d in distractor_status if d["state"] == "leaked"),
        }
    except Exception as exc:
        result["distractors"] = {"status": "error", "error": str(exc)}

    try:
        evidence = build_evidence_package(failure_event_id, log)
        summary = render_evidence_summary(evidence)
        known_ids = {getattr(e, "id", "") for e in events}
        package_refs = sorted(
            {
                r
                for r in set(_UUID_RE.findall(json.dumps(evidence, default=str)))
                if r in known_ids
            }
        )
        summary_cites = sorted(
            {r for r in set(_UUID_RE.findall(summary)) if r in known_ids}
        )
        mentions = [
            m
            for m in spec.get("explanation_must_mention", [])
            if str(m).lower() in summary.lower()
        ]
        summary_grounded = len(summary_cites) > 0
        result["explanation_grounding"] = {
            "status": "ok",
            "event_ids_in_evidence": len(package_refs),
            "evidence_ids_valid": len(package_refs) > 0,
            "summary_cites_ids": sorted(summary_cites)[:10],
            "summary_cites_count": len(summary_cites),
            # Package-level grounding (structural evidence exists) is weak:
            # the offline summary rarely cites event IDs. A pass on the
            # explanation itself requires summary-level citation.
            "grounded": len(package_refs) > 0,
            "package_grounded": len(package_refs) > 0,
            "summary_grounded": summary_grounded,
            "required_mentions": spec.get("explanation_must_mention", []),
            "mentions_found": mentions,
            "mentions_recall": round(
                len(mentions) / max(1, len(spec.get("explanation_must_mention", []))), 3
            ),
        }
    except Exception as exc:
        result["explanation_grounding"] = {"status": "error", "error": str(exc)}

    return result
