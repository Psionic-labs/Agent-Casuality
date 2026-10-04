"""Local OpenCode ingest endpoint backed by the existing SQLite event store."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any, cast

from sdk.memory import ResourceRegistry
from storage.sqlite import SQLiteEventStore

from .mapping import OpenCodeEventMapper


# HTTP Request Handler: receives telemetry envelopes posted by the OpenCode plugin
class _Handler(BaseHTTPRequestHandler):
    server_version = "AgentCasualityOpenCode/1"

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        # Only accept telemetry at the dedicated ingest path
        if self.path != "/v1/opencode/events":
            self.send_error(404)
            return
        server = cast(_Server, self.server)
        try:
            # Read and parse incoming JSON payload (supports both single event or a list)
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            envelopes = body if isinstance(body, list) else [body]
            accepted = 0
            # Feed each envelope through the mapper to record in SQLite
            for envelope in envelopes:
                if isinstance(envelope, dict) and server.mapper.ingest(envelope) is not None:
                    accepted += 1
            # HTTP 202 Accepted: confirms receipt of telemetry
            self._json(202, {"accepted": accepted})
        except Exception as exc:  # noqa: BLE001 - fail-open telemetry boundary
            # Fail-open guarantee: malformed body or processing error drops telemetry safely
            server.errors.append(str(exc))
            self._json(202, {"accepted": 0, "error": "telemetry dropped"})

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default noisy stderr HTTP logging during agent runs
        return

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        # Helper to encode and send a JSON response with proper headers
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


# Threaded HTTP server holding the shared event mapper and error list
class _Server(ThreadingHTTPServer):
    mapper: OpenCodeEventMapper
    errors: list[str]


class OpenCodeIngestServer:
    """Threaded local receiver suitable for the OpenCode plugin smoke test."""

    def __init__(self, db_path: str | Path, host: str = "127.0.0.1", port: int = 8765) -> None:
        # Initialize SQLite event store for persistence
        self.store = SQLiteEventStore(db_path)
        # Create mapper with dedicated resource registry for file versioning
        self.mapper = OpenCodeEventMapper(
            self.store,
            run_id="opencode",
            registry=ResourceRegistry(),
        )
        # Spin up HTTP server listening on configured host and port
        self._server = _Server((host, port), _Handler)
        self._server.mapper = self.mapper
        self._server.errors = []
        self._lock = Lock()

    @property
    def address(self) -> tuple[str, int]:
        # Bound (host, port) tuple (useful when port=0 picks an ephemeral port)
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    @property
    def errors(self) -> list[str]:
        # Thread-safe copy of caught ingest errors
        return list(self._server.errors)

    def serve_forever(self) -> None:
        # Start listening and serving HTTP requests indefinitely
        self._server.serve_forever()

    def close(self) -> None:
        # Cleanly shut down HTTP server socket and close the underlying SQLite DB
        with self._lock:
            self._server.shutdown()
            self._server.server_close()
            self.store.close()


def main() -> None:
    # CLI entrypoint for `casuality-opencode-ingest` command
    parser = argparse.ArgumentParser(description="Local OpenCode Agent-Casuality ingest receiver")
    parser.add_argument("--db", type=Path, default=Path(".casuality/opencode.db"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = OpenCodeIngestServer(args.db, host=args.host, port=args.port)
    print(f"Agent-Casuality OpenCode ingest listening on http://{args.host}:{args.port}/v1/opencode/events")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()


if __name__ == "__main__":
    main()
