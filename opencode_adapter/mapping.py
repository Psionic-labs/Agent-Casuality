"""Map current OpenCode V1 plugin payloads into Agent-Casuality events."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sdk.events import AgentClock, Event, record_event
from sdk.memory import ResourceRegistry
from sdk.privacy import PayloadRedactor, make_fail_open_append

# Regex patterns detecting sensitive keys and secret values
_SECRET_KEY_RE = re.compile(r"(?:api[_-]?key|authorization|bearer|token|secret|password)", re.I)
_SECRET_VALUE_RE = re.compile(r"(?:bearer\s+|sk[-_]|api[_-]?key\s*[=:])", re.I)


# Recursively sanitize nested dictionaries and lists before persistence
def _redact(value: Any, redactor: PayloadRedactor) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, nested in value.items():
            if _SECRET_KEY_RE.search(str(key)):
                safe[key] = "[REDACTED]"
            else:
                safe[key] = _redact(nested, redactor)
        return redactor.redact(safe)
    if isinstance(value, list):
        return [_redact(item, redactor) for item in value]
    if isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        return "[REDACTED]"
    return value


# Deterministic UUID5 generator based on session, kind, and source event ID
def _event_id(session_id: str, source_id: str, kind: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"opencode:{session_id}:{kind}:{source_id}"))


# Convert OpenCode epoch millisecond timestamps or ISO strings to timezone-aware UTC datetime
def _timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _source_id(payload: dict[str, Any], fallback: str) -> str:
    base: str | None = None
    for key in ("event_id", "id", "callID", "messageID", "permissionID", "partID"):
        value = payload.get(key)
        if value:
            base = str(value)
            break
    # Real OpenCode event shapes nest IDs (info.id, part.id, message.id).
    if base is None:
        info = payload.get("info")
        if isinstance(info, dict):
            for key in ("id", "messageID", "sessionID"):
                value = info.get(key)
                if value:
                    base = str(value)
                    break
    if base is None:
        part = payload.get("part")
        if isinstance(part, dict):
            for key in ("id", "partID", "messageID", "sessionID"):
                value = part.get(key)
                if value:
                    base = str(value)
                    break
    if base is None:
        message = payload.get("message")
        if isinstance(message, dict):
            for key in ("id", "messageID"):
                value = message.get(key)
                if value:
                    base = str(value)
                    break
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
    if base is None:
        return digest[:24] or fallback
    # messageID is shared by every event in a message (commands, parts), so a
    # bare messageID would collapse distinct executions via the idempotency key.
    # Suffixing with a short payload hash preserves the original ID for
    # correlation while keeping distinct payloads (exitCode, timestamps)
    # distinct and identical HTTP retries deduplicated.
    return f"{base}:{digest[:8]}"


def _session_id(payload: dict[str, Any], kind: str = "") -> str:
    direct = payload.get("session_id") or payload.get("sessionID")
    if direct:
        return str(direct)
    # Real OpenCode global events nest the session (info.sessionID, part.sessionID).
    info = payload.get("info")
    if isinstance(info, dict):
        nested = info.get("sessionID") or info.get("session_id")
        if nested:
            return str(nested)
        # Session lifecycle events carry only info.id as the session identity.
        if kind in {
            "event:session.created",
            "session.created",
            "event:session.updated",
            "session.updated",
            "event:session.deleted",
            "session.deleted",
        }:
            info_id = info.get("id")
            if info_id:
                return str(info_id)
    part = payload.get("part")
    if isinstance(part, dict):
        nested = part.get("sessionID") or part.get("session_id")
        if nested:
            return str(nested)
    return "unknown"


@dataclass
class _SessionState:
    clock: AgentClock = field(default_factory=AgentClock)
    last_event_id: str | None = None
    calls: dict[str, str] = field(default_factory=dict)
    model: str | None = None
    agent: str | None = None


@dataclass(frozen=True)
class OpenCodeCapture:
    event: Event
    stored: bool


class OpenCodeEventMapper:
    """Translate OpenCode V1 events/hooks through the existing event recorder."""

    def __init__(
        self,
        log: Any,
        *,
        run_id: str = "opencode",
        registry: ResourceRegistry | None = None,
        redactor: PayloadRedactor | None = None,
    ) -> None:
        self.log = make_fail_open_append(log)
        self.run_id = run_id
        self.registry = registry or ResourceRegistry()
        self.redactor = redactor or PayloadRedactor(
            extra_keys={"headers", "authorization", "apiKey", "api_key", "accessToken"}
        )
        self._sessions: dict[str, _SessionState] = {}

    def _state(self, session_id: str) -> _SessionState:
        return self._sessions.setdefault(session_id, _SessionState())

    def _record(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        source_id: str,
        parents: list[str] | None = None,
        wall_time: datetime | None = None,
    ) -> OpenCodeCapture:
        state = self._state(session_id)
        parent_ids = list(parents or [])
        if not parent_ids and state.last_event_id:
            parent_ids = [state.last_event_id]
        safe_payload = _redact(copy.deepcopy(payload), self.redactor)
        event, stored = record_event(
            agent_id=f"opencode:{session_id}",
            clock=state.clock,
            log=self.log,
            event_type=event_type,
            payload=safe_payload,
            causal_parent_ids=parent_ids,
            run_id=self.run_id,
            idempotency_key=f"opencode:{session_id}:{event_type}:{source_id}",
            event_id=_event_id(session_id, source_id, event_type),
            wall_time=wall_time,
        )
        if stored:
            state.last_event_id = event.id
        return OpenCodeCapture(event=event, stored=stored)

    def ingest(self, envelope: dict[str, Any]) -> OpenCodeCapture | None:
        """Map one plugin envelope; telemetry errors are intentionally swallowed."""
        try:
            kind = str(envelope.get("kind", "event"))
            payload = envelope.get("payload")
            if not isinstance(payload, dict):
                payload = {"value": payload}
            session_id = _session_id(envelope | payload, kind)
            source_id = _source_id(envelope | payload, kind)
            timestamp = _timestamp(envelope.get("timestamp") or payload.get("timestamp"))
            state = self._state(session_id)
            if payload.get("model"):
                state.model = str(payload["model"])
            if payload.get("agent"):
                state.agent = str(payload["agent"])
            common = {
                "opencode_kind": kind,
                "session_id": session_id,
                "event_id": source_id,
                "timestamp": timestamp.isoformat(),
                "model": state.model,
                "agent": state.agent,
                "payload": payload,
            }
            parent = payload.get("parent_event_id")
            parents = [str(parent)] if parent else None
            event_type = "context_update"
            # 1. Session lifecycle mappings
            if kind in {"event:session.created", "session.created"}:
                event_type = "run_start"
            elif kind in {"event:session.deleted", "session.deleted"}:
                event_type = "run_finish"
            elif kind in {"event:session.error", "session.error"}:
                event_type = "agent_error"
            elif kind in {"event:session.status", "session.status", "event:session.idle"}:
                event_type = "context_update"
            # 2. Model call activity
            elif kind in {"event:message.updated", "message.updated"}:
                event_type = "model_call"
            # 3. File modifications (treated as tool_result writes)
            elif kind in {"event:file.edited", "file.edited"}:
                event_type = "tool_result"
                path = payload.get("file") or payload.get("path")
                if path:
                    common["resource_uri"] = f"file://{path}"
            # 4. Command execution
            elif kind in {
                "event:command.executed",
                "command.executed",
                "hook:command.execute.before",
            }:
                event_type = "tool_call"
            # 5. Tool invocation before: inspect file path and inject last writer as causal parent
            elif kind in {"hook:tool.execute.before", "tool.execute.before"}:
                event_type = "tool_call"
                args = payload.get("args")
                if isinstance(args, dict):
                    path = args.get("filePath") or args.get("path")
                    if isinstance(path, str):
                        resource_uri = f"file://{path}"
                        common["resource_uri"] = resource_uri
                        latest = self.registry.get_latest(resource_uri, run_id=self.run_id)
                        if latest is not None:
                            parents = [latest.last_writer_event_id]
            # 6. Tool completion after: link back to the preceding tool call as causal parent
            elif kind in {"hook:tool.execute.after", "tool.execute.after"}:
                event_type = "tool_result"
                call_id = payload.get("callID") or payload.get("call_id")
                if call_id and str(call_id) in state.calls:
                    parents = [state.calls[str(call_id)]]
            # 7. User permission interactions
            elif kind in {
                "hook:permission.ask",
                "event:permission.asked",
                "event:permission.updated",
                "event:permission.replied",
                "permission.asked",
                "permission.updated",
                "permission.replied",
            }:
                event_type = "tool_call"
            elif kind in {"event:message.part.updated", "message.part.updated"}:
                event_type = "context_update"
            elif kind in {"event:session.updated", "session.updated"}:
                event_type = "context_update"

            # Persist event into the event store with Lamport clock and causal parents
            capture = self._record(
                session_id=session_id,
                event_type=event_type,
                payload=common,
                source_id=source_id,
                parents=parents,
                wall_time=timestamp,
            )
            # Remember tool call ID -> event ID to correlate subsequent tool result
            if kind in {"hook:tool.execute.before", "tool.execute.before"}:
                call_id = payload.get("callID") or payload.get("call_id")
                if call_id and capture.stored:
                    state.calls[str(call_id)] = capture.event.id
            # On file write (file.edited), record write in ResourceRegistry
            # to enable read-after-write causal linkage
            resource_uri = common.get("resource_uri")
            if capture.stored and isinstance(resource_uri, str) and event_type == "tool_result":
                self.registry.register_write(
                    resource_uri=resource_uri,
                    writer_event_id=capture.event.id,
                    writer_agent_id=capture.event.agent_id,
                    logical_seq=capture.event.logical_seq,
                    wall_time=capture.event.wall_time,
                    run_id=self.run_id,
                )
            return capture
        except Exception:
            # Telemetry error swallowed: fail-open guarantee
            return None

    def resources(self) -> dict[tuple[str | None, str], Any]:
        return self.registry.all_resources()
