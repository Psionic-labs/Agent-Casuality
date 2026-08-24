"""Interval snapshots of reconstructed agent state (thesis section 30.1).

A snapshot stores the fully reduced :class:`core.reducer.AgentState` for one
agent at one ``logical_seq``, together with ``hash_state`` of that state so
any later reconstruction can be verified instead of trusted. Creation always
replays from an empty start: chaining snapshot-to-snapshot is a tuning
concern explicitly deferred until real numbers say otherwise (implementation
plan, Phase 3 pitfalls).

The default interval of 32 sits inside the 25-50 events per agent window the
implementation plan prescribes for the MVP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol

from core.reducer import hash_state, reconstruct

__all__ = [
    "DEFAULT_SNAPSHOT_INTERVAL",
    "InMemorySnapshotStore",
    "SnapshotManager",
    "SnapshotRecord",
    "create_snapshot",
    "should_snapshot",
]

DEFAULT_SNAPSHOT_INTERVAL = 32


@dataclass(frozen=True)
class SnapshotRecord:
    """One persisted checkpoint of a single agent's reduced state."""

    agent_id: str
    logical_seq: int
    state: dict[str, Any]
    state_hash: str
    run_id: str | None = None
    id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Storage-neutral representation, matching the plan's test shape."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "logical_seq": self.logical_seq,
            "state": dict(self.state),
            "state_hash": self.state_hash,
            "created_at": self.created_at.isoformat(),
        }


class SnapshotStore(Protocol):
    """Storage contract for snapshots."""

    def save(self, record: SnapshotRecord) -> SnapshotRecord: ...

    def latest_at_or_before(self, agent_id: str, logical_seq: int) -> SnapshotRecord | None: ...


def should_snapshot(logical_seq: int, interval: int = DEFAULT_SNAPSHOT_INTERVAL) -> bool:
    """Return True when ``logical_seq`` lands on a snapshot interval boundary."""
    if interval <= 0:
        raise ValueError(f"snapshot interval must be positive, got {interval}")
    return logical_seq > 0 and logical_seq % interval == 0


def create_snapshot(
    *,
    agent_id: str,
    logical_seq: int,
    log: Any,
    run_id: str | None = None,
) -> SnapshotRecord:
    """Replay the agent from empty up to ``logical_seq`` and hash the result.

    Always replays from scratch rather than stacking on an earlier snapshot;
    the stored hash must reflect ground truth, not another snapshot's claim.
    """
    state = reconstruct(agent_id, logical_seq, log=log)
    return SnapshotRecord(
        agent_id=agent_id,
        logical_seq=logical_seq,
        state=state.to_json(),
        state_hash=hash_state(state),
        run_id=run_id,
    )


class InMemorySnapshotStore:
    """Thread-safe snapshot store for tests and local runs."""

    def __init__(self) -> None:
        self._snapshots: list[SnapshotRecord] = []
        self._lock = Lock()

    def save(self, record: SnapshotRecord) -> SnapshotRecord:
        with self._lock:
            self._snapshots.append(record)
            return record

    def latest_at_or_before(self, agent_id: str, logical_seq: int) -> SnapshotRecord | None:
        with self._lock:
            candidates = [
                snapshot
                for snapshot in self._snapshots
                if snapshot.agent_id == agent_id and snapshot.logical_seq <= logical_seq
            ]
        if not candidates:
            return None
        return max(candidates, key=lambda snapshot: snapshot.logical_seq)

    def all(self) -> list[SnapshotRecord]:
        with self._lock:
            return list(self._snapshots)

    def __len__(self) -> int:
        with self._lock:
            return len(self._snapshots)


class SnapshotManager:
    """Creates snapshots on an interval as events are observed.

    Call :meth:`observe` after each persisted event; when the event's
    ``logical_seq`` hits the interval boundary for its agent, the manager
    replays that agent's prefix and persists a new snapshot.
    """

    def __init__(
        self,
        *,
        log: Any,
        store: SnapshotStore,
        interval: int = DEFAULT_SNAPSHOT_INTERVAL,
        run_id: str | None = None,
    ) -> None:
        if interval <= 0:
            raise ValueError(f"snapshot interval must be positive, got {interval}")
        self.log = log
        self.store = store
        self.interval = interval
        self.run_id = run_id
        self._lock = Lock()

    def observe(self, event: Any, *, force: bool = False) -> SnapshotRecord | None:
        """Maybe snapshot after ``event``; returns the record or None."""
        hit = force or should_snapshot(event.logical_seq, self.interval)
        if not hit:
            return None
        with self._lock:
            record = create_snapshot(
                agent_id=event.agent_id,
                logical_seq=event.logical_seq,
                log=self.log,
                run_id=self.run_id if self.run_id is not None else event.run_id,
            )
            return self.store.save(record)
