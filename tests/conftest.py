"""Pytest configuration and shared fixtures for Agent-Casuality tests.

Global autouse fixture:
    reset_default_registry - clears sdk.memory.default_resource_registry before
    every test so that module-level singleton state cannot bleed between tests
    that instantiate CapturedMemory without an explicit registry= argument.
"""

from __future__ import annotations

import pytest

from sdk.memory import default_resource_registry


@pytest.fixture(autouse=True)
def reset_default_registry() -> None:
    """Clear the module-level ResourceRegistry singleton before each test.

    CapturedMemory falls back to ``default_resource_registry`` when no
    ``registry=`` is supplied. Without this fixture, writes from one test
    would be visible to reads in a later test sharing the same key, causing
    spurious causal-parent injection and assertion failures.
    """
    default_resource_registry.clear()
