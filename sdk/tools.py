"""Tool capture decorator."""

from __future__ import annotations

import functools
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import uuid4

from .events import AgentClock, Event, record_event

if TYPE_CHECKING:
    from .memory import ResourceRegistry

F = TypeVar("F", bound=Callable[..., Any])
_fallback_lock_guard = Lock()
_fallback_locks: dict[tuple[int, str, str], Lock] = {}


def _find_events(log: Any, agent_id: str, invocation_id: str) -> list[Event]:
    getter = getattr(log, "get_by_idempotency_key", None)
    if getter is not None:
        events = [getter(agent_id, key) for key in (invocation_id, f"{invocation_id}:result")]
        return [event for event in events if event is not None]
    if hasattr(log, "events"):
        events = log.events()
    elif hasattr(log, "__iter__"):
        events = list(log)
    else:
        events = []
    return [
        event
        for event in events
        if event.agent_id == agent_id and event.payload.get("invocation_id") == invocation_id
    ]


def _invocation_lock(log: Any, agent_id: str, invocation_id: str) -> Any:
    factory = getattr(log, "tool_invocation_lock", None)
    if factory is not None:
        return factory(agent_id, invocation_id)
    key = (id(log), agent_id, invocation_id)
    with _fallback_lock_guard:
        return _fallback_locks.setdefault(key, Lock())


def _run_captured_tool(
    fn: F,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    agent_id: str,
    clock: AgentClock,
    log: Any,
    run_id: str | None,
    causal_parent_ids: Any,
    invocation_id: str,
    registry: ResourceRegistry | None = None,
    resource_uri: str | None = None,
) -> Any:
    prior = _find_events(log, agent_id, invocation_id)
    prior_result = next((event for event in prior if event.event_type == "tool_result"), None)
    if prior_result is not None:
        return prior_result.payload.get("output")
    prior_error = next((event for event in prior if event.event_type == "agent_error"), None)
    if prior_error is not None:
        raise RuntimeError(prior_error.payload.get("error", "captured tool failed"))

    invoke = record_event(
        agent_id=agent_id,
        clock=clock,
        log=log,
        event_type="tool_call",
        payload={
            "name": getattr(fn, "__name__", type(fn).__name__),
            "args": list(args),
            "kwargs": kwargs,
            "invocation_id": invocation_id,
        },
        causal_parent_ids=causal_parent_ids,
        idempotency_key=invocation_id,
        run_id=run_id,
    )
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:
        record_event(
            agent_id=agent_id,
            clock=clock,
            log=log,
            event_type="agent_error",
            payload={"invocation_id": invocation_id, "error": str(exc)},
            causal_parent_ids=[invoke.id],
            idempotency_key=f"{invocation_id}:result",
            run_id=run_id,
        )
        raise
    result_payload: dict[str, Any] = {"invocation_id": invocation_id, "output": result}
    if resource_uri is not None:
        result_payload["resource_uri"] = resource_uri
    result_event = record_event(
        agent_id=agent_id,
        clock=clock,
        log=log,
        event_type="tool_result",
        payload=result_payload,
        causal_parent_ids=[invoke.id],
        idempotency_key=f"{invocation_id}:result",
        run_id=run_id,
    )
    # Register file/resource writes so readers can auto-inject causal edges
    if registry is not None and resource_uri is not None:
        registry.register_write(
            resource_uri=resource_uri,
            writer_event_id=result_event.id,
            writer_agent_id=agent_id,
            logical_seq=result_event.logical_seq,
            wall_time=result_event.wall_time,
        )
    return result


def _decorate(
    fn: F,
    configured_agent_id: str | None,
    configured_clock: AgentClock | None,
    configured_log: Any | None,
    configured_run_id: str | None,
    configured_registry: ResourceRegistry | None = None,
    configured_resource_uri: str | None = None,
) -> Any:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        configured_context = any(
            value is not None
            for value in (configured_agent_id, configured_clock, configured_log, configured_run_id)
        )
        if configured_context:
            agent_id = kwargs.pop("_capture_agent_id", configured_agent_id)
            clock = kwargs.pop("_capture_clock", configured_clock)
            log = kwargs.pop("_capture_log", configured_log)
            run_id = kwargs.pop("_capture_run_id", configured_run_id)
            causal_parent_ids = kwargs.pop("_capture_causal_parent_ids", ())
            invocation_id = kwargs.pop("_capture_invocation_id", None) or str(uuid4())
            registry = kwargs.pop("_capture_registry", configured_registry)
            resource_uri = kwargs.pop("_capture_resource_uri", configured_resource_uri)
        else:
            agent_id = kwargs.pop("agent_id", None)
            clock = kwargs.pop("clock", None)
            log = kwargs.pop("log", None)
            run_id = kwargs.pop("run_id", None)
            causal_parent_ids = kwargs.pop("causal_parent_ids", ())
            invocation_id = kwargs.pop("invocation_id", None) or str(uuid4())
            registry = kwargs.pop("registry", configured_registry)
            resource_uri = kwargs.pop("resource_uri", configured_resource_uri)
        if agent_id is None or clock is None or log is None:
            raise TypeError("captured tools require agent_id, clock, and log")

        with _invocation_lock(log, agent_id, invocation_id):
            return _run_captured_tool(
                fn,
                args,
                kwargs,
                agent_id=agent_id,
                clock=clock,
                log=log,
                run_id=run_id,
                causal_parent_ids=causal_parent_ids,
                invocation_id=invocation_id,
                registry=registry,
                resource_uri=resource_uri,
            )

    return cast(F, wrapper)


def capture_tool(
    fn: F | None = None,
    *,
    agent_id: str | None = None,
    clock: AgentClock | None = None,
    log: Any | None = None,
    run_id: str | None = None,
    registry: ResourceRegistry | None = None,
    resource_uri: str | None = None,
) -> Any:
    """Decorate a tool with trace context supplied at decoration or call time.

    The documented call-time form reserves ``agent_id``, ``clock``, ``log``,
    ``run_id``, ``causal_parent_ids``, ``invocation_id``, ``registry``, and
    ``resource_uri``.  When context is configured on the decorator, those names
    remain available to the wrapped function; private ``_capture_*`` keywords
    can override the configured capture context for a particular invocation.

    Supplying ``registry`` and ``resource_uri`` enables the Resource-Version
    Invariant: the ``tool_result`` event is automatically registered as the
    latest writer for the given URI, so downstream reads auto-inject the causal
    edge without manual wiring.
    """
    if fn is None:
        return lambda wrapped: _decorate(
            wrapped, agent_id, clock, log, run_id, registry, resource_uri
        )
    return _decorate(fn, agent_id, clock, log, run_id, registry, resource_uri)
