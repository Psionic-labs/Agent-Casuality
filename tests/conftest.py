"""Pytest configuration and shared fixtures for Agent-Casuality tests.

Global autouse fixture:
    reset_default_registry - clears sdk.memory.default_resource_registry before
    every test so that module-level singleton state cannot bleed between tests
    that instantiate CapturedMemory without an explicit registry= argument.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from sdk.memory import default_resource_registry

# Snapshot DATABASE_URL at collection time, before any test can leak `.env`
# into os.environ (e.g. generate_explanation(load_env=True) loads the whole
# file, including DATABASE_URL). Plain `uv run pytest -q` must stay a fast
# unit run that skips integration; explicit opt-in (`uv run --env-file .env
# pytest`, `$env:DATABASE_URL=...`, CI postgres job) is captured here.
_INITIAL_DATABASE_URL = os.environ.get("DATABASE_URL")


@pytest.fixture(autouse=True)
def reset_default_registry() -> None:
    """Clear the module-level ResourceRegistry singleton before each test.

    CapturedMemory falls back to ``default_resource_registry`` when no
    ``registry=`` is supplied. Without this fixture, writes from one test
    would be visible to reads in a later test sharing the same key, causing
    spurious causal-parent injection and assertion failures.
    """
    default_resource_registry.clear()


def postgres_dsn_or_skip() -> str:
    """Return the pre-test DATABASE_URL or skip the calling integration test."""
    database_url = _INITIAL_DATABASE_URL
    if not database_url:
        pytest.skip("set DATABASE_URL to run the real PostgreSQL integration test")
    assert database_url is not None
    return database_url


def postgres_connect_or_skip(psycopg: Any, dsn: str) -> Any:
    """Connect with a short timeout, skipping when PostgreSQL is unreachable.

    ``uv run pytest -q`` and ``scripts/check.ps1`` (which loads ``.env``)
    must not fail when DATABASE_URL points at a dead/transient host
    (e.g. expired Neon DNS). A fast skip keeps the unit suite green;
    real integration runs in CI provide a reachable database.
    """
    try:
        return psycopg.connect(dsn, connect_timeout=5)
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable, skipping integration test: {exc}")


@contextmanager
def skip_on_postgres_unavailable(psycopg: Any) -> Iterator[None]:
    """Convert mid-test connection drops into a skip instead of a failure."""
    try:
        yield
    except Exception as exc:
        if _is_postgres_connection_error(psycopg, exc):
            pytest.skip(f"PostgreSQL unavailable mid-test, skipping: {exc}")
        raise


def _is_postgres_connection_error(psycopg: Any, exc: BaseException) -> bool:
    operational_error = getattr(psycopg, "OperationalError", None)
    if operational_error is not None and isinstance(exc, operational_error):
        return True
    if isinstance(exc, OSError):
        return True
    message = str(exc).lower()
    return any(
        needle in message
        for needle in (
            "failed to resolve host",
            "getaddrinfo failed",
            "connection refused",
            "connection timed out",
            "could not connect",
            "no such host",
            "temporary failure in name resolution",
        )
    )
