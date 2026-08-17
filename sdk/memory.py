"""Capture-aware key/value memory."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .events import AgentClock, Event, record_event

_MISSING = object()


class CapturedMemory:
    def __init__(
        self,
        *,
        agent_id: str,
        clock: AgentClock,
        log: Any,
        store: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.clock = clock
        self.log = log
        self.store = store if store is not None else {}
        self.run_id = run_id

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

    def get(self, key: str, *, causal_parent_ids: Iterable[str] = ()) -> Any:
        value = self.store.get(key, _MISSING)
        self._event(
            "memory_read",
            {
                "key": key,
                "value": None if value is _MISSING else value,
                "found": value is not _MISSING,
            },
            causal_parent_ids,
        )
        return None if value is _MISSING else value

    def set(self, key: str, value: Any, *, causal_parent_ids: Iterable[str] = ()) -> None:
        before = self.store.get(key, _MISSING)
        self.store[key] = value
        self._event(
            "memory_write",
            {
                "operation": "set",
                "key": key,
                "before": None if before is _MISSING else before,
                "after": value,
            },
            causal_parent_ids,
        )

    def delete(self, key: str, *, causal_parent_ids: Iterable[str] = ()) -> bool:
        before = self.store.pop(key, _MISSING)
        self._event(
            "memory_write",
            {
                "operation": "delete",
                "key": key,
                "before": None if before is _MISSING else before,
                "after": None,
            },
            causal_parent_ids,
        )
        return before is not _MISSING
