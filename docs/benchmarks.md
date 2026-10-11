# Benchmarks and results

Summary of committed artifacts in `benchmark/results/` (JSON + Markdown).

| Suite | Command | Result |
| --- | --- | --- |
| Five deterministic scenarios | `uv run casuality-benchmark scenarios` | 5/5 pass; exact-match `1.0` on slice, provenance, interaction |
| Experiment 2 (shared-state recovery) | `uv run casuality-benchmark experiment2 --dependencies 100` | 100/100 recovered |
| Experiment 3 (semantic-port vs raw deletion) | `uv run casuality-benchmark experiment3` | 20/20 semantic-port successes; raw-deletion failure rate 70% (target > 35% met) |
| Failure injection | `uv run casuality-benchmark failure-injection` | 3/3 pass |
| Experiment 1 (offline) | `uv run casuality-benchmark experiment1 --repetitions 3` | Passes (12 true positives / 12 true negatives) |
| Experiment 1 (external Fastino) | `uv run casuality-benchmark experiment1 --provider fastino` | Provider-blocked / deferred — catalog has no structured-output capability, so no external run was completed |
| `agent-replay 0.2.0` baseline | `uv run casuality-benchmark baseline` | Divergence localization only; multi-parent causality, interactions, shared-state causality, distractor reasoning, and minimal reduction unsupported |
| OpenCode coding-agent benchmark | `uv run casuality-benchmark opencode` | 5 runs across 5 tasks (OpenCode `1.19.0`, `deepseek/deepseek-v4-flash`); capture micro/macro-average `1.0`; cause recall mean `0.3`; joint ancestry `0.0` (genuine causal interaction unsupported) |

The 2026-10-11 rerun (after the honest-causality fix `fe7a4ef`, which
removed arrival-order edges) completed all 5 tasks with 0 deviations.
Cause recall mean `0.3` measures structural-slice ancestry under
explicit-evidence edges only (tool `callID` pairing, resource
read-after-write, declared `parent_event_id`); arrival order is preserved
by `logical_seq`/`wall_time` but never inferred as causality. It replaces
the earlier 7-run result (capture `0.928`/`0.967`, cause `1.0`), which was
scored from stale traces with linear chaining and must not be reused.

## Terminology

Proxies are never presented as stronger claims:

- Capture is **minimum expected event-class coverage**, not generic recall.
- Live-trace branch results are **joint ancestry**, not causal interaction
  (true causal interaction is **unsupported** without counterfactuals).
- Minimal slices are a **required-cause preservation proxy**, not causal
  minimality (true minimality is **not_measurable** on live traces).
- Unsupported / unmeasurable capabilities are stated explicitly in each artifact.
