"""Packaging regression tests: the wheel must ship the Visual DAG Explorer.

These run from the source tree and fail fast if a future packaging change
accidentally excludes the frontend bundle or the explorer modules:

- ``explorer/static/`` (vendored from ``frontend/out/``) must exist and be
  self-consistent (index + JS + CSS, all referenced ``/_next/`` assets present).
- ``explorer.server.get_frontend_dir()`` must resolve inside the ``explorer``
  package without relying on CWD or the ``frontend/`` checkout layout.
- ``pyproject.toml`` must declare the static package-data and the
  ``casuality-explorer`` / ``casuality-opencode-ingest`` entry points.
"""

from __future__ import annotations

import re
import threading
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "explorer" / "static"


def test_explorer_static_index_bundled() -> None:
    index = STATIC_DIR / "index.html"
    assert index.is_file(), (
        "explorer/static/index.html is missing; run "
        "`uv run python scripts/sync-explorer-static.py` after "
        "`cd frontend && npm ci && npm run build`"
    )
    body = index.read_text(encoding="utf-8")
    assert "DAG Explorer" in body
    next_dir = STATIC_DIR / "_next"
    js_files = list(next_dir.rglob("*.js")) if next_dir.is_dir() else []
    css_files = list(next_dir.rglob("*.css")) if next_dir.is_dir() else []
    assert js_files, "explorer/static/_next contains no JavaScript"
    assert css_files, "explorer/static/_next contains no CSS"


def test_explorer_static_references_resolve() -> None:
    """Every /_next/ URL referenced by index.html must exist in the bundle."""
    body = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    refs = set(re.findall(r"/_next/[A-Za-z0-9_./-]+\.(?:js|css)", body))
    assert refs, "index.html references no /_next/ JS/CSS assets"
    missing = [r for r in sorted(refs) if not (STATIC_DIR / r.lstrip("/")).is_file()]
    assert not missing, f"index.html references missing bundled assets: {missing[:5]}"


def test_get_frontend_dir_prefers_packaged_static(tmp_path, monkeypatch) -> None:
    from explorer.server import FRONTEND_DIR, get_frontend_dir

    resolved = get_frontend_dir()
    assert (resolved / "index.html").is_file()
    # Must live inside the explorer package, not in frontend/out/ or CWD.
    assert resolved.parent.name == "explorer" or resolved.name == "static", resolved
    assert "frontend" not in resolved.parts, f"fell back to checkout layout: {resolved}"
    # CWD independence: the wheel never relies on where the user runs it from.
    monkeypatch.chdir(tmp_path)
    assert get_frontend_dir() == resolved
    assert FRONTEND_DIR == resolved


def test_server_serves_packaged_static_and_api() -> None:
    import json

    from explorer.loader import load_demo
    from explorer.server import create_server

    dataset = load_demo()
    server = create_server(dataset)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def get(path: str) -> tuple[int, bytes]:
            try:
                with urllib.request.urlopen(base + path) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()

        status, body = get("/")
        assert status == 200, "Explorer index did not load from packaged static"
        assert b"DAG Explorer" in body
        status, _ = get("/api/overview")
        assert status == 200
        assert json.loads(_.decode("utf-8"))["event_count"] == 10
        # A real hashed JS asset from the bundle must serve, not 404.
        rel_js = sorted((STATIC_DIR / "_next").rglob("*.js"))[0].relative_to(STATIC_DIR)
        status, js_body = get("/" + rel_js.as_posix())
        assert status == 200 and len(js_body) > 0
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_pyproject_declares_static_and_entry_points() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    explorer_data = data["tool"]["setuptools"]["package-data"]["explorer"]
    joined = " ".join(explorer_data)
    assert "demo" in joined, f"explorer package-data lost demo JSONs: {explorer_data}"
    assert "static" in joined, (
        f"explorer package-data must include the vendored frontend: {explorer_data}"
    )
    scripts = data["project"]["scripts"]
    assert scripts.get("casuality-explorer") == "explorer.server:main"
    assert scripts.get("casuality-opencode-ingest") == "opencode_adapter.server:main"
    assert (ROOT / "MANIFEST.in").is_file()
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "explorer/static" in manifest
