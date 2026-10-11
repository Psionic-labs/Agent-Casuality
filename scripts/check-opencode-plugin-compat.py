"""Verify the Agent-Casuality OpenCode plugin loads on real OpenCode binaries.

Runs a trivial prompt under each given `opencode` binary with the repo's
`.opencode/plugins/agent-casuality.ts` on the plugin path (cwd = repo root)
and an ephemeral ingest receiver, then asserts:

  1. the receiver persisted at least one event (hooks actually fired), with
     zero receiver errors;
  2. the OpenCode server log shows no `failed to load plugin` line for the
     agent-casuality plugin (loader regressions are otherwise silent).

The agent's own exit code is informational only: a model failure still
proves the plugin loaded as long as session/tool events were ingested.

Requires an OpenRouter key (``OPENROUTER_API_KEY`` env var or repo `.env`;
the benchmark runner does not auto-load `.env`). The 1.18.34 binary is not
shipped; fetch it once with::

    npm install opencode-ai@1.18.34 --prefix <dir> --no-audit --no-fund

Usage (PowerShell)::

    uv run python scripts/check-opencode-plugin-compat.py
    uv run python scripts/check-opencode-plugin-compat.py --bin 1.19.0:C:/path/to/opencode.exe
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from opencode_adapter.server import OpenCodeIngestServer  # noqa: E402
from storage.sqlite import SQLiteEventStore  # noqa: E402

DEFAULT_MODEL = "openrouter/deepseek/deepseek-v4-flash"
DEFAULT_PROMPT = "reply with exactly: compat-ok"
INSTALLED_BIN = (
    Path(os.environ.get("APPDATA", r"C:\Users\Nyx\AppData\Roaming"))
    / "npm"
    / "node_modules"
    / "opencode-ai"
    / "bin"
    / "opencode.exe"
)
DOWNLOADED_1834_BIN = (
    Path(tempfile.gettempdir())
    / "opencode"
    / "v1834"
    / "node_modules"
    / "opencode-ai"
    / "bin"
    / "opencode.exe"
)
DEFAULT_LOG = (
    Path.home() / ".local" / "share" / "opencode" / "log" / "opencode.log"
)


def resolve_key(workdir: Path) -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    dotenv = workdir / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return key
    raise SystemExit(
        "OPENROUTER_API_KEY not found: export it or add it to the repo .env"
    )


def new_log_text(log_path: Path, offset: int) -> str:
    if not log_path.exists():
        return ""
    size = log_path.stat().st_size
    start = offset if size >= offset else 0  # log rotated/truncated
    with log_path.open("rb") as fh:
        fh.seek(start)
        return fh.read().decode("utf-8", errors="replace")


def check_binary(
    label: str,
    binary: Path,
    *,
    model: str,
    prompt: str,
    timeout: int,
    workdir: Path,
    log_path: Path,
    drain_seconds: int,
    api_key: str,
) -> bool:
    print(f"\n=== {label}: {binary} ===")
    if not binary.exists():
        print(f"FAIL: binary not found: {binary}")
        return False

    db_path = Path(tempfile.gettempdir()) / "opencode" / f"compat-{label}.db"
    if db_path.exists():
        db_path.unlink()
    server = OpenCodeIngestServer(str(db_path), port=0)
    host, port = server.address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    env = dict(os.environ)
    env["OPENROUTER_API_KEY"] = api_key
    env["CASUALITY_OPENCODE_INGEST_URL"] = (
        f"http://{host}:{port}/v1/opencode/events"
    )
    log_offset = log_path.stat().st_size if log_path.exists() else 0
    try:
        proc = subprocess.run(
            [str(binary), "run", "-m", model, prompt],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        print(f"FAIL: `opencode run` timed out after {timeout}s")
        server.close()
        return False
    time.sleep(drain_seconds)

    store = SQLiteEventStore(str(db_path))
    try:
        events = store.events()
    finally:
        store.close()
    receiver_errors = list(server.errors)
    server.close()

    fresh_log = new_log_text(log_path, log_offset)
    load_failures = [
        line
        for line in fresh_log.splitlines()
        if "failed to load plugin" in line and "agent-casuality" in line
    ]
    other_failures = [
        line
        for line in fresh_log.splitlines()
        if "failed to load plugin" in line and "agent-casuality" not in line
    ]

    print(f"exit code: {proc.returncode} (informational)")
    print(f"events ingested: {len(events)}; receiver errors: {len(receiver_errors)}")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-300:].replace("\n", " | ")
        print(f"agent stderr tail: {tail}")
    for line in other_failures[:3]:
        print(f"note (unrelated plugin): {line[-200:]}")

    ok = True
    if load_failures:
        ok = False
        for line in load_failures[:3]:
            print(f"FAIL: loader rejected the plugin: {line[-250:]}")
    if not events:
        ok = False
        print("FAIL: no events reached the receiver; hooks did not fire")
    if receiver_errors:
        ok = False
        print(f"FAIL: {len(receiver_errors)} receiver errors: {receiver_errors[:2]}")
    print("PASS" if ok else "FAIL", f"for {label}")
    return ok


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify plugin loading on real OpenCode binaries."
    )
    parser.add_argument(
        "--bin",
        action="append",
        dest="bins",
        metavar="LABEL:PATH",
        default=[],
        help="Extra binary as LABEL:PATH (repeatable).",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--workdir", default=str(REPO_ROOT))
    parser.add_argument("--log-path", default=str(DEFAULT_LOG))
    parser.add_argument("--drain-seconds", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workdir = Path(args.workdir)
    targets = [
        ("1.19.0", INSTALLED_BIN),
        ("1.18.34", DOWNLOADED_1834_BIN),
    ]
    for spec in args.bins:
        label, _, path = spec.partition(":")
        if not label or not path:
            raise SystemExit(f"bad --bin spec (want LABEL:PATH): {spec!r}")
        targets.append((label, Path(path)))
    api_key = resolve_key(workdir)
    results = [
        check_binary(
            label,
            binary,
            model=args.model,
            prompt=args.prompt,
            timeout=args.timeout,
            workdir=workdir,
            log_path=Path(args.log_path),
            drain_seconds=args.drain_seconds,
            api_key=api_key,
        )
        for label, binary in targets
    ]
    print(f"\ncompat matrix: {sum(results)}/{len(results)} binaries PASS")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
