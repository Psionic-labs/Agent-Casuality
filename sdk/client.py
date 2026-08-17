"""Anthropic capture wrapper."""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from .events import AgentClock, record_event


def _dump_response(response: Any) -> Any:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "dict"):
        return response.dict()
    if isinstance(response, dict):
        return response
    return getattr(response, "__dict__", repr(response))


class _CapturedMessages:
    def __init__(self, owner: CapturedClient) -> None:
        self._owner = owner

    def create(
        self,
        *,
        causal_parent_ids: Iterable[str] = (),
        idempotency_key: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Call Anthropic unchanged, then append the observable model event."""
        start = time.monotonic()
        try:
            response = self._owner._client.messages.create(**kwargs)
        except Exception as exc:
            record_event(
                agent_id=self._owner.agent_id,
                clock=self._owner.clock,
                log=self._owner.log,
                event_type="agent_error",
                payload={
                    "operation": "model_call",
                    "error": str(exc),
                    "input": kwargs.get("messages"),
                },
                causal_parent_ids=causal_parent_ids,
                idempotency_key=idempotency_key,
                run_id=self._owner.run_id,
            )
            raise

        latency_ms = int((time.monotonic() - start) * 1000)
        record_event(
            agent_id=self._owner.agent_id,
            clock=self._owner.clock,
            log=self._owner.log,
            event_type="model_call",
            payload={
                "model": kwargs.get("model"),
                "input": kwargs.get("messages"),
                "output": _dump_response(response),
                "latency_ms": latency_ms,
            },
            causal_parent_ids=causal_parent_ids,
            idempotency_key=idempotency_key,
            run_id=self._owner.run_id,
        )
        return response


class CapturedClient:
    """Drop-in-shaped wrapper exposing ``client.messages.create``."""

    def __init__(
        self,
        api_key: str | None,
        agent_id: str,
        clock: AgentClock,
        log: Any,
        *,
        client: Any | None = None,
        run_id: str | None = None,
    ) -> None:
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - deployment setup
                raise RuntimeError("anthropic is required when client is not injected") from exc
            if api_key is None:
                raise ValueError("api_key is required when client is not injected")
            client = anthropic.Anthropic(api_key=api_key)
        self._client = client
        self.agent_id = agent_id
        self.clock = clock
        self.log = log
        self.run_id = run_id
        self.messages = _CapturedMessages(self)

    def messages_create(self, **kwargs: Any) -> Any:
        """Compatibility alias for the original Phase 1 sketch."""
        return self.messages.create(**kwargs)
