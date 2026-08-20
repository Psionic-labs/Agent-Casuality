"""Capture-aware key/value memory with Resource-Version causal tracking."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from .events import AgentClock, Event, record_event

_MISSING = object()


@dataclass(frozen=True)
class ResourceVersionTuple:
    """Monotonic resource versioning tracking the last writer event."""

    resource_uri: str
    version: int
    last_writer_event_id: str
    last_writer_agent_id: str
    logical_seq: int
    wall_time: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_uri": self.resource_uri,
            "version": self.version,
            "last_writer_event_id": self.last_writer_event_id,
            "last_writer_agent_id": self.last_writer_agent_id,
            "logical_seq": self.logical_seq,
            "wall_time": self.wall_time.isoformat(),
        }


class ResourceRegistry:
    """Thread-safe registry mapping resource URIs to their monotonic version and last writer event."""

    def __init__(self) -> None:
        self._resources: dict[str, ResourceVersionTuple] = {}
        self._lock = RLock()

    def register_write(
        self,
        resource_uri: str,
        writer_event_id: str,
        writer_agent_id: str,
        logical_seq: int,
        wall_time: datetime | None = None,
    ) -> ResourceVersionTuple:
        with self._lock:
            current = self._resources.get(resource_uri)
            next_version = 1 if current is None else current.version + 1
            entry = ResourceVersionTuple(
                resource_uri=resource_uri,
                version=next_version,
                last_writer_event_id=writer_event_id,
                last_writer_agent_id=writer_agent_id,
                logical_seq=logical_seq,
                wall_time=wall_time or datetime.now(UTC),
            )
            self._resources[resource_uri] = entry
            return entry

    def get_latest(self, resource_uri: str) -> ResourceVersionTuple | None:
        with self._lock:
            return self._resources.get(resource_uri)

    def hydrate_from_events(self, events: Iterable[Event]) -> None:
        """Replay events to rebuild resource-version mappings from historical records."""
        with self._lock:
            for event in events:
                if event.event_type == "memory_write":
                    key = event.payload.get("key")
                    if key:
                        uris = [f"mem://{event.agent_id}/{key}", f"mem://shared/{key}"]
                        custom_uri = event.payload.get("resource_uri")
                        if custom_uri:
                            uris.append(custom_uri)
                        for uri in uris:
                            self.register_write(
                                resource_uri=uri,
                                writer_event_id=event.id,
                                writer_agent_id=event.agent_id,
                                logical_seq=event.logical_seq,
                                wall_time=event.wall_time,
                            )
                elif event.event_type == "tool_result":
                    custom_uri = event.payload.get("resource_uri")
                    if custom_uri:
                        self.register_write(
                            resource_uri=custom_uri,
                            writer_event_id=event.id,
                            writer_agent_id=event.agent_id,
                            logical_seq=event.logical_seq,
                            wall_time=event.wall_time,
                        )

    def all_resources(self) -> dict[str, ResourceVersionTuple]:
        with self._lock:
            return dict(self._resources)

    def clear(self) -> None:
        with self._lock:
            self._resources.clear()


default_resource_registry = ResourceRegistry()


class CapturedMemory:
    def __init__(
        self,
        *,
        agent_id: str,
        clock: AgentClock,
        log: Any,
        store: dict[str, Any] | None = None,
        run_id: str | None = None,
        registry: ResourceRegistry | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.clock = clock
        self.log = log
        self.store = store if store is not None else {}
        self.run_id = run_id
        self.registry = registry if registry is not None else default_resource_registry
        self._lock = RLock()

    def _event(
        self,
        event_type: str,
        payload: dict[str, Any],
        causal_parent_ids: Iterable[str],
    ) -> Event:
        return record_event(
            agent_id=self.agent_id,
            clock=self.clock,
            log=self.log,
            event_type=event_type,
            payload=payload,
            causal_parent_ids=causal_parent_ids,
            run_id=self.run_id,
        )

    def get(
        self,
        key: str,
        *,
        causal_parent_ids: Iterable[str] = (),
        resource_uri: str | None = None,
    ) -> Any:
        with self._lock:
            value = self.store.get(key, _MISSING)
            parents = list(causal_parent_ids)
            if not parents and self.registry is not None:
                # Auto-inject causal dependency from the last writer
                lookup_uris = []
                if resource_uri:
                    lookup_uris.append(resource_uri)
                lookup_uris.extend([f"mem://{self.agent_id}/{key}", f"mem://shared/{key}"])
                for uri in lookup_uris:
                    latest = self.registry.get_latest(uri)
                    if latest is not None and latest.last_writer_event_id:
                        parents = [latest.last_writer_event_id]
                        break

            self._event(
                "memory_read",
                {
                    "key": key,
                    "value": None if value is _MISSING else value,
                    "found": value is not _MISSING,
                    "resource_uri": resource_uri or f"mem://{self.agent_id}/{key}",
                },
                parents,
            )
            return None if value is _MISSING else value

    def set(
        self,
        key: str,
        value: Any,
        *,
        causal_parent_ids: Iterable[str] = (),
        resource_uri: str | None = None,
    ) -> None:
        with self._lock:
            before = self.store.get(key, _MISSING)
            self.store[key] = value
            event = self._event(
                "memory_write",
                {
                    "operation": "set",
                    "key": key,
                    "before": None if before is _MISSING else before,
                    "before_found": before is not _MISSING,
                    "after": value,
                    "after_found": True,
                    "resource_uri": resource_uri or f"mem://{self.agent_id}/{key}",
                },
                causal_parent_ids,
            )
            if self.registry is not None:
                uris = [f"mem://{self.agent_id}/{key}", f"mem://shared/{key}"]
                if resource_uri:
                    uris.append(resource_uri)
                for uri in uris:
                    self.registry.register_write(
                        resource_uri=uri,
                        writer_event_id=event.id,
                        writer_agent_id=self.agent_id,
                        logical_seq=event.logical_seq,
                        wall_time=event.wall_time,
                    )

    def delete(
        self,
        key: str,
        *,
        causal_parent_ids: Iterable[str] = (),
        resource_uri: str | None = None,
    ) -> bool:
        with self._lock:
            before = self.store.pop(key, _MISSING)
            event = self._event(
                "memory_write",
                {
                    "operation": "delete",
                    "key": key,
                    "before": None if before is _MISSING else before,
                    "before_found": before is not _MISSING,
                    "after": None,
                    "after_found": False,
                    "resource_uri": resource_uri or f"mem://{self.agent_id}/{key}",
                },
                causal_parent_ids,
            )
            if self.registry is not None:
                uris = [f"mem://{self.agent_id}/{key}", f"mem://shared/{key}"]
                if resource_uri:
                    uris.append(resource_uri)
                for uri in uris:
                    self.registry.register_write(
                        resource_uri=uri,
                        writer_event_id=event.id,
                        writer_agent_id=self.agent_id,
                        logical_seq=event.logical_seq,
                        wall_time=event.wall_time,
                    )
            return before is not _MISSING
