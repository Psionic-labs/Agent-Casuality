"""Sync the built Next.js static export into the Python package.

Source: ``frontend/out/`` (produced by ``npm run build`` in ``frontend/``).
Destination: ``explorer/static/`` (shipped inside the ``agent-casuality`` wheel).

The vendored copy is committed so ``uv build`` works without Node, and so
PyPI installs render the Visual DAG without cloning the repository.

Usage:
    uv run python scripts/sync-explorer-static.py
    uv run python scripts/sync-explorer-static.py --check   # CI: fail if stale
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "out"
DST = ROOT / "explorer" / "static"


def _fail(message: str) -> int:
    print(f"sync-explorer-static: {message}", file=sys.stderr)
    return 1


def sync() -> int:
    if not (SRC / "index.html").is_file():
        return _fail(
            "frontend/out/index.html is missing. Build it first:\n"
            "  cd frontend && npm ci && npm run build\n"
            "Refusing to silently ship an empty Explorer."
        )
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST)
    # Guard against an empty or partial export slipping into the wheel.
    index = DST / "index.html"
    if not index.is_file():
        return _fail("copy failed: explorer/static/index.html missing after sync")
    js = list((DST / "_next").rglob("*.js")) if (DST / "_next").is_dir() else []
    css = list((DST / "_next").rglob("*.css")) if (DST / "_next").is_dir() else []
    if not js or not css:
        return _fail(
            f"copy looks partial: found {len(js)} JS and {len(css)} CSS files "
            "under explorer/static/_next (expected at least one of each)"
        )
    body = index.read_text(encoding="utf-8")
    if "DAG Explorer" not in body:
        return _fail("explorer/static/index.html does not contain 'DAG Explorer'")
    n_files = sum(1 for _ in DST.rglob("*") if _.is_file())
    print(f"synced {n_files} files: frontend/out/ -> explorer/static/")
    return 0


def check() -> int:
    """Fail if the vendored copy is missing or differs from frontend/out/."""
    if not (SRC / "index.html").is_file():
        return _fail("frontend/out/index.html missing; cannot check freshness")
    if not (DST / "index.html").is_file():
        return _fail(
            "explorer/static/index.html missing; run "
            "`uv run python scripts/sync-explorer-static.py`"
        )
    src_files = sorted(p.relative_to(SRC) for p in SRC.rglob("*") if p.is_file())
    dst_files = sorted(p.relative_to(DST) for p in DST.rglob("*") if p.is_file())
    if [str(p) for p in src_files] != [str(p) for p in dst_files]:
        only_src = sorted(set(map(str, src_files)) - set(map(str, dst_files)))
        only_dst = sorted(set(map(str, dst_files)) - set(map(str, src_files)))
        details = []
        if only_src:
            details.append(f"only in frontend/out: {only_src[:5]}")
        if only_dst:
            details.append(f"only in explorer/static: {only_dst[:5]}")
        return _fail("vendored copy is stale (" + "; ".join(details) + "); re-run sync")
    for rel in src_files:
        if not filecmp.cmp(SRC / rel, DST / rel, shallow=False):
            return _fail(f"vendored copy differs at {rel}; re-run sync")
    print("explorer/static/ is in sync with frontend/out/")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync explorer static assets")
    parser.add_argument("--check", action="store_true", help="fail if vendored copy is stale")
    args = parser.parse_args(argv)
    return check() if args.check else sync()


if __name__ == "__main__":
    raise SystemExit(main())
