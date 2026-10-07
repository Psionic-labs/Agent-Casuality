"""Read-only visual DAG explorer for Agent-Casuality traces.

The explorer never mutates the causal engine, the benchmark, the OpenCode
adapter, or any event store. It loads events (a bundled demo trace or a
live SQLite file), reuses the existing analysis functions, and serves a
static frontend over small JSON endpoints.
"""

from __future__ import annotations

from explorer.loader import ExplorerDataset, load_demo, load_sqlite
from explorer.queries import (
    diagnosis_report,
    event_detail,
    evidence_report,
    failure_report,
    graph_overview,
)

__all__ = [
    "ExplorerDataset",
    "diagnosis_report",
    "event_detail",
    "evidence_report",
    "failure_report",
    "graph_overview",
    "load_demo",
    "load_sqlite",
]
