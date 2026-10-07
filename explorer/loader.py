"""Dataset loading for the explorer (read-only).

Demo mode replays the bundled OpenCode envelopes through the same
``OpenCodeEventMapper`` the benchmark uses, so the DAG shows exactly what
capture produced. Live mode opens an existing SQLite file through
``SQLiteEventStore`` and only calls its read methods.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmark.opencode.scoring import resolve_failure, resolve_roles
from opencode_adapter.mapping import OpenCodeEventMapper
from sdk.events import InMemoryEventLog

DEMO_DIR = Path(__file__).resolve().parent / "demo"
DEMO_TRACE_PATH = DEMO_DIR / "failed_test_retry_trace.json"
DEMO_SPEC_PATH = DEMO_DIR / "failed_test_retry_spec.json"


@dataclass
class ExplorerDataset:
    """Events plus the ground-truth context the explorer may show."""

    log: Any
    events: list[Any]
    spec: dict[str, Any]
    source: str
    failure: dict[str, Any] = field(default_factory=dict)
    resolved_roles: dict[str, list[str]] = field(default_factory=dict)
    unresolved_roles: list[str] = field(default_factory=list)


def _resolve(dataset: ExplorerDataset) -> ExplorerDataset:
    spec = dataset.spec
    roles = spec.get("causal_roles", [])
    resolved = resolve_roles(dataset.events, roles) if roles else {"resolved": {}, "unresolved": []}
    failure = resolve_failure(dataset.events, spec.get("failure_selector", {"any": []}))
    dataset.resolved_roles = {k: list(v) for k, v in resolved["resolved"].items()}
    dataset.unresolved_roles = list(resolved["unresolved"])
    dataset.failure = dict(failure)
    return dataset


def load_demo() -> ExplorerDataset:
    """Ingest the bundled demo trace and attach its ground-truth spec."""
    trace = json.loads(DEMO_TRACE_PATH.read_text(encoding="utf-8"))
    spec = json.loads(DEMO_SPEC_PATH.read_text(encoding="utf-8"))
    envelopes = trace["envelopes"]
    log = InMemoryEventLog()
    mapper = OpenCodeEventMapper(log, run_id="opencode-demo")
    dropped = 0
    for envelope in envelopes:
        if mapper.ingest(envelope) is None:
            dropped += 1
    dataset = ExplorerDataset(
        log=log,
        events=log.events(),
        spec=spec,
        source=f"demo:{trace.get('trace', 'failed_test_retry')}",
    )
    _resolve(dataset)
    dataset.failure["envelopes"] = len(envelopes)
    dataset.failure["dropped_envelopes"] = dropped
    return dataset


def load_sqlite(path: str | Path) -> ExplorerDataset:
    """Open a live SQLite event store (reads only; never appends)."""
    from storage.sqlite import SQLiteEventStore

    store = SQLiteEventStore(path)
    dataset = ExplorerDataset(
        log=store,
        events=store.events(),
        spec={},
        source=f"sqlite:{Path(path).name}",
    )
    _resolve(dataset)
    return dataset
