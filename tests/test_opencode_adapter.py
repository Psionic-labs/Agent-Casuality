from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from opencode_adapter.mapping import OpenCodeEventMapper
from opencode_adapter.server import OpenCodeIngestServer
from sdk.events import AgentClock, InMemoryEventLog, record_event
from storage.sqlite import SQLiteEventStore


def _send(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _session_events(session_id: str) -> list[dict[str, object]]:
    return [
        {
            "kind": "event:session.created",
            "timestamp": 1000,
            "payload": {"sessionID": session_id, "info": {"id": session_id}},
        },
        {
            "kind": "event:message.updated",
            "timestamp": 1100,
            "payload": {
                "sessionID": session_id,
                "info": {"id": "message-1", "modelID": "model-a", "providerID": "local"},
            },
        },
        {
            "kind": "hook:tool.execute.before",
            "timestamp": 1200,
            "payload": {
                "sessionID": session_id,
                "callID": "call-1",
                "tool": "read",
                "args": {"filePath": "src/app.py"},
            },
        },
        {
            "kind": "hook:tool.execute.after",
            "timestamp": 1300,
            "payload": {
                "sessionID": session_id,
                "callID": "call-1",
                "tool": "read",
                "output": "old source",
            },
        },
        {
            "kind": "event:file.edited",
            "timestamp": 1400,
            "payload": {"sessionID": session_id, "file": "src/app.py"},
        },
        {
            "kind": "event:command.executed",
            "timestamp": 1500,
            "payload": {
                "sessionID": session_id,
                "name": "pytest",
                "arguments": "tests/test_app.py",
                "exitCode": 1,
            },
        },
        {
            "kind": "event:session.error",
            "timestamp": 1600,
            "payload": {"sessionID": session_id, "error": {"message": "pytest failed"}},
        },
        {
            "kind": "event:message.part.updated",
            "timestamp": 1700,
            "payload": {
                "sessionID": session_id,
                "part": {"id": "retry-1", "type": "retry", "attempt": 1},
            },
        },
        {
            "kind": "event:file.edited",
            "timestamp": 1800,
            "payload": {"sessionID": session_id, "file": "src/app.py"},
        },
        {
            "kind": "event:command.executed",
            "timestamp": 1900,
            "payload": {
                "sessionID": session_id,
                "name": "pytest",
                "arguments": "tests/test_app.py",
                "exitCode": 0,
            },
        },
        {
            "kind": "event:session.status",
            "timestamp": 2000,
            "payload": {"sessionID": session_id, "status": {"type": "idle"}},
        },
        {
            "kind": "event:session.deleted",
            "timestamp": 2100,
            "payload": {"sessionID": session_id, "info": {"id": session_id}},
        },
    ]


def test_opencode_mapping_redacts_and_preserves_correlation() -> None:
    log = InMemoryEventLog()
    mapper = OpenCodeEventMapper(log)
    mapper.ingest(
        {
            "kind": "hook:tool.execute.before",
            "session_id": "session-1",
            "payload": {
                "sessionID": "session-1",
                "callID": "call-1",
                "tool": "bash",
                "args": {"authorization": "Bearer secret-token"},
            },
        }
    )
    result = mapper.ingest(
        {
            "kind": "hook:tool.execute.after",
            "session_id": "session-1",
            "payload": {
                "sessionID": "session-1",
                "callID": "call-1",
                "output": {"headers": {"Authorization": "Bearer secret-token"}},
            },
        }
    )
    assert result is not None
    assert result.event.causal_parent_ids
    encoded = json.dumps(result.event.payload)
    assert "secret-token" not in encoded
    assert "[REDACTED]" in encoded


def test_opencode_fail_open_does_not_raise() -> None:
    class BrokenLog:
        def append(self, event: object) -> object:
            raise OSError("disk unavailable")

    mapper = OpenCodeEventMapper(BrokenLog())
    capture = mapper.ingest(
        {
            "kind": "event:session.created",
            "payload": {"sessionID": "session-broken"},
        }
    )
    assert capture is not None
    assert capture.stored is False


def test_opencode_event_type_mappings() -> None:
    log = InMemoryEventLog()
    mapper = OpenCodeEventMapper(log)

    mappings = [
        ("event:session.created", "run_start"),
        ("event:session.deleted", "run_finish"),
        ("event:session.error", "agent_error"),
        ("event:session.status", "context_update"),
        ("event:session.updated", "context_update"),
        ("event:message.updated", "model_call"),
        ("event:message.part.updated", "context_update"),
        ("event:file.edited", "tool_result"),
        ("event:command.executed", "tool_call"),
        ("hook:command.execute.before", "tool_call"),
        ("hook:tool.execute.before", "tool_call"),
        ("hook:tool.execute.after", "tool_result"),
        ("hook:permission.ask", "tool_call"),
        ("event:permission.replied", "tool_call"),
    ]

    for kind, expected_type in mappings:
        result = mapper.ingest({"kind": kind, "session_id": "test-map", "payload": {"data": 123}})
        assert result is not None
        assert result.event.event_type == expected_type


def test_opencode_resource_causality_linkage() -> None:
    log = InMemoryEventLog()
    mapper = OpenCodeEventMapper(log)

    # 1. Edit a file (writer)
    write_cap = mapper.ingest(
        {
            "kind": "event:file.edited",
            "session_id": "session-resource",
            "payload": {"file": "lib/utils.py"},
        }
    )
    assert write_cap is not None

    # 2. Read the file in a subsequent tool call
    read_cap = mapper.ingest(
        {
            "kind": "hook:tool.execute.before",
            "session_id": "session-resource",
            "payload": {
                "callID": "call-read-1",
                "tool": "file_reader",
                "args": {"filePath": "lib/utils.py"},
            },
        }
    )
    assert read_cap is not None
    assert write_cap.event.id in read_cap.event.causal_parent_ids


def test_opencode_redaction_secrets() -> None:
    log = InMemoryEventLog()
    mapper = OpenCodeEventMapper(log)
    result = mapper.ingest(
        {
            "kind": "hook:chat.message",
            "session_id": "session-secret",
            "payload": {
                "apiKey": "sk-1234567890abcdef",
                "password": "super-secret-pass",
                "nested": {
                    "token": "token-xyz",
                    "auth_header": "Bearer raw-token-here",
                },
                "items": [
                    {"api_key": "secret-api-key"},
                    "Bearer token-in-list",
                ],
            },
        }
    )
    assert result is not None
    encoded = json.dumps(result.event.payload)
    assert "sk-1234567890abcdef" not in encoded
    assert "super-secret-pass" not in encoded
    assert "token-xyz" not in encoded
    assert "raw-token-here" not in encoded
    assert "secret-api-key" not in encoded
    assert "token-in-list" not in encoded


def test_opencode_supplied_wall_time_reaches_persisted_event() -> None:
    log = InMemoryEventLog()
    mapper = OpenCodeEventMapper(log)
    capture = mapper.ingest(
        {
            "kind": "event:session.created",
            "timestamp": 1000,
            "payload": {"sessionID": "session-wall"},
        }
    )
    assert capture is not None
    expected = datetime.fromtimestamp(1000, UTC)
    assert capture.event.wall_time == expected
    persisted = log.events()[0]
    assert persisted.wall_time == expected
    assert persisted.wall_time == capture.event.wall_time


def test_opencode_wall_time_survives_sqlite_round_trip(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "walltime.db")
    mapper = OpenCodeEventMapper(store)
    mapper.ingest(
        {
            "kind": "event:session.created",
            "timestamp": "1970-01-01T00:16:40Z",
            "payload": {"sessionID": "session-roundtrip"},
        }
    )
    expected = datetime.fromtimestamp(1000, UTC)
    assert store.events()[0].wall_time == expected
    store.close()

    reopened = SQLiteEventStore(tmp_path / "walltime.db")
    try:
        reloaded = reopened.events()
        assert len(reloaded) == 1
        assert reloaded[0].wall_time == expected
        assert reloaded[0].wall_time.tzinfo is not None
    finally:
        reopened.close()


def test_record_event_defaults_wall_time_to_now() -> None:
    log = InMemoryEventLog()
    event, stored = record_event(
        agent_id="agent-default",
        clock=AgentClock(),
        log=log,
        event_type="context_update",
        payload={"k": "v"},
    )
    assert stored is True
    assert event.wall_time.tzinfo is not None
    assert abs((datetime.now(UTC) - event.wall_time).total_seconds()) < 5


def test_opencode_resource_registry_uses_event_wall_time(tmp_path: Path) -> None:
    store = SQLiteEventStore(tmp_path / "registry.db")
    mapper = OpenCodeEventMapper(store)
    mapper.ingest(
        {
            "kind": "event:file.edited",
            "timestamp": 2000,
            "payload": {"sessionID": "session-reg", "file": "src/app.py"},
        }
    )
    latest = mapper.resources()[("opencode", "file://src/app.py")]
    assert latest.wall_time == datetime.fromtimestamp(2000, UTC)
    assert latest.wall_time == store.events()[0].wall_time
    store.close()


def test_opencode_server_fail_open_drops_malformed_telemetry(tmp_path: Path) -> None:
    server = OpenCodeIngestServer(tmp_path / "fail_open.db", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://{server.address[0]}:{server.address[1]}/v1/opencode/events"
        # Send invalid JSON
        req = Request(
            url,
            data=b"invalid json non-dict",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as response:
            res = json.loads(response.read().decode("utf-8"))
            assert res.get("accepted") == 0
            assert res.get("error") == "telemetry dropped"
    finally:
        server.close()
        thread.join(timeout=5)


def test_simulated_opencode_session_reaches_sqlite_and_graph(tmp_path: Path) -> None:
    server = OpenCodeIngestServer(tmp_path / "opencode.db", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://{server.address[0]}:{server.address[1]}/v1/opencode/events"
        responses = [_send(url, event) for event in _session_events("session-e2e")]
        assert all(response["accepted"] == 1 for response in responses)
    finally:
        server.close()
        thread.join(timeout=5)

    store = SQLiteEventStore(tmp_path / "opencode.db")
    events = store.events()
    assert [event.event_type for event in events] == [
        "run_start",
        "model_call",
        "tool_call",
        "tool_result",
        "tool_result",
        "tool_call",
        "agent_error",
        "context_update",
        "tool_result",
        "tool_call",
        "context_update",
        "run_finish",
    ]
    file_events = [
        event for event in events if event.payload.get("resource_uri") == "file://src/app.py"
    ]
    assert len(file_events) == 3
    file_writes = [event for event in file_events if event.event_type == "tool_result"]
    assert len(file_writes) == 2
    latest = server.mapper.resources()[("opencode", "file://src/app.py")]
    assert latest.last_writer_event_id == file_writes[-1].id
    assert events[-1].causal_parent_ids == [events[-2].id]
    assert set(store.ancestors(events[-1].id)) == {event.id for event in events}
    store.close()
