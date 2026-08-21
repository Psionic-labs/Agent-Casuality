"""Payload redaction and storage failure policies for the capture SDK.

Two concerns are addressed here:

1. **Payload redaction** - sensitive keys (e.g. ``api_key``, ``token``) are
   replaced with ``"[REDACTED]"`` before the event reaches the event log.
   This is a best-effort shallow pass over the top-level payload dict.
   Deep/nested redaction is intentionally deferred to a future phase.

2. **Fail-open / fail-closed policy** - ``make_fail_open_append`` wraps any
   event log so that storage backend failures are swallowed rather than
   propagated to agent code. Fail-closed callers simply do not wrap.
"""

from __future__ import annotations

from typing import Any

# Keys that are always redacted, regardless of caller configuration.
_BUILTIN_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "api_secret",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "authorization",
        "private_key",
        "client_secret",
    }
)


class PayloadRedactor:
    """Strips sensitive keys from event payloads before persistence.

    Args:
        extra_keys: Additional top-level payload keys to redact, merged with
            the built-in sensitive key list.
        redaction_marker: The string written in place of a redacted value.
            Defaults to ``"[REDACTED]"``.

    Example::

        redactor = PayloadRedactor(extra_keys={"ssn", "dob"})
        safe = redactor.redact({"ssn": "123-45-6789", "action": "enroll"})
        # safe == {"ssn": "[REDACTED]", "action": "enroll"}
    """

    def __init__(
        self,
        extra_keys: frozenset[str] | set[str] | None = None,
        *,
        redaction_marker: str = "[REDACTED]",
    ) -> None:
        self._sensitive: frozenset[str] = _BUILTIN_SENSITIVE_KEYS | frozenset(
            extra_keys or set()
        )
        self._marker = redaction_marker

    @property
    def sensitive_keys(self) -> frozenset[str]:
        """The complete set of keys that will be redacted."""
        return self._sensitive

    def redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a shallow copy of *payload* with sensitive keys replaced.

        Only top-level keys are examined. Nested dicts/lists are left intact
        to avoid accidental mutation of complex value types.
        """
        return {k: (self._marker if k in self._sensitive else v) for k, v in payload.items()}

    def is_sensitive(self, key: str) -> bool:
        """Return True if *key* would be redacted."""
        return key in self._sensitive


class _IdentityRedactor(PayloadRedactor):
    """Pass-through redactor that never modifies the payload.

    Used as the default when no redaction is configured, so callers can
    always call ``.redact()`` without a None-check.
    """

    def __init__(self) -> None:
        # Bypass normal __init__; no sensitive keys configured.
        self._sensitive: frozenset[str] = frozenset()
        self._marker = "[REDACTED]"

    def redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        return payload  # No copy -- safe because callers do not mutate.


IDENTITY_REDACTOR: PayloadRedactor = _IdentityRedactor()
"""Singleton no-op redactor. Use as the default when redaction is not needed."""


def make_fail_open_append(log: Any) -> Any:
    """Wrap *log* so that storage failures are swallowed rather than raised.

    Returns a thin proxy that delegates every attribute and method to *log*
    but replaces ``.append()`` with a version that catches all exceptions,
    emits a stderr warning (so failures are still visible in logs), and
    returns the original event unchanged so the agent run continues uninterrupted.

    **Fail-closed** callers simply do not use this wrapper; they allow
    exceptions from ``.append()`` to propagate naturally.

    Args:
        log: Any object implementing the ``EventLog`` protocol.

    Returns:
        A proxy object with the same interface as *log* but with a
        fail-safe ``.append()`` method. Also provides ``append_with_status()``,
        which returns ``(event, stored)`` for that exact call, and
        ``_last_append_failed()`` to check if the most recent append failed.
    """
    import sys

    class FailOpenLog:
        """Proxy that wraps an EventLog and swallows append failures."""

        def __init__(self, wrapped: Any) -> None:
            self._wrapped = wrapped
            self._last_append_failed = False

        def append_with_status(self, event: Any) -> tuple[Any, bool]:
            """Append *event* and return ``(event, stored)`` for this exact call.

            The status travels with the call, so concurrent appends on the
            same proxy cannot observe each other's results.
            """
            try:
                result = self._wrapped.append(event)
                self._last_append_failed = False
                return result, True
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[agent-casuality] WARN: event log append failed (fail_open=True): {exc}",
                    file=sys.stderr,
                )
                self._last_append_failed = True
                return event, False

        def append(self, event: Any) -> Any:
            result, _ = self.append_with_status(event)
            return result

        def __getattr__(self, name: str) -> Any:
            return getattr(self._wrapped, name)

    return FailOpenLog(log)
