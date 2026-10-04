"""Real OpenCode coding-agent benchmark for Agent-Casuality.

Measures capture completeness and diagnosis quality on live OpenCode
executions through the validated `.opencode/plugins/agent-casuality.ts`
integration. Ground truth lives in `ground_truth/*.json` (single source
of truth); this package only loads and executes it.
"""

from .scoring import (
    EVENT_CLASSES,
    capture_completeness,
    classify_event,
    resolve_roles,
    score_diagnosis,
)
from .tasks import TASK_NAMES, get_task, list_tasks, load_spec

__all__ = [
    "EVENT_CLASSES",
    "TASK_NAMES",
    "capture_completeness",
    "classify_event",
    "get_task",
    "list_tasks",
    "load_spec",
    "resolve_roles",
    "score_diagnosis",
]
