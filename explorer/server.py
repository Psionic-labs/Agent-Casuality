"""Static frontend plus read-only JSON API for the DAG explorer.

Only the standard library is used. ``create_server`` binds a dataset to a
``ThreadingHTTPServer``; ``main`` wires it to ``--db`` (live SQLite) or the
bundled demo trace and serves ``frontend/`` at ``/``.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from explorer import loader
from explorer.queries import (
    diagnosis_report,
    event_detail,
    evidence_report,
    failure_report,
    graph_overview,
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "out"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
}


class _ExplorerServer(ThreadingHTTPServer):
    dataset: Any


class _Handler(BaseHTTPRequestHandler):
    server_version = "AgentCasualityExplorer/1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Any) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        dataset = cast(_ExplorerServer, self.server).dataset
        if parsed.path.startswith("/api/"):
            self._handle_api(parsed, dataset)
            return
        self._handle_static(parsed.path)

    def _handle_api(self, parsed: Any, dataset: Any) -> None:
        try:
            if parsed.path == "/api/overview":
                self._send_json(200, graph_overview(dataset))
            elif parsed.path == "/api/failure":
                self._send_json(200, failure_report(dataset))
            elif parsed.path == "/api/diagnosis":
                self._send_json(200, diagnosis_report(dataset))
            elif parsed.path == "/api/evidence":
                self._send_json(200, evidence_report(dataset))
            elif parsed.path == "/api/event":
                event_id = parse_qs(parsed.query).get("id", [""])[0]
                try:
                    self._send_json(200, event_detail(dataset, event_id))
                except KeyError:
                    self._send_json(404, {"error": f"unknown event {event_id}"})
            else:
                self._send_json(404, {"error": "unknown endpoint"})
        except Exception as exc:  # noqa: BLE001 - read-only boundary reports errors as JSON
            self._send_json(500, {"error": str(exc)})

    def _handle_static(self, path: str) -> None:
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (FRONTEND_DIR / rel).resolve()
        if FRONTEND_DIR.resolve() not in target.parents and target != FRONTEND_DIR.resolve():
            self._send(403, b"forbidden", "text/plain")
            return
        if not target.is_file():
            self._send(404, b"not found", "text/plain")
            return
        suffix = target.suffix.lower()
        content_type = (
            _CONTENT_TYPES.get(suffix)
            or mimetypes.guess_type(str(target))[0]
            or ("application/octet-stream")
        )
        self._send(200, target.read_bytes(), content_type)


def create_server(dataset: Any, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """Bind *dataset* to a threaded HTTP server (port 0 picks a free port)."""
    server = _ExplorerServer((host, port), _Handler)
    server.dataset = dataset
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Visual DAG explorer (read-only)")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--db", default=None, help="Live SQLite file (default: demo trace)")
    args = parser.parse_args(argv)
    dataset = loader.load_sqlite(args.db) if args.db else loader.load_demo()
    server = create_server(dataset, args.host, args.port)
    print(f"serving {dataset.source} at http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
