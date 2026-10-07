# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-10-06

First public release. Published to PyPI as `agent-casuality==0.1.0`.

### Causal graph / capture

- Event capture for tool, memory, model, and lifecycle events with logical
  sequences and explicit causal parents (`sdk`, `core`).
- SQLite, in-memory, and PostgreSQL event stores plus a graph validator
  (dangling parents, cross-run edges, sequence progression, decision-port
  reachability).
- Deterministic state reconstruction at a logical sequence.

### Replay

- Merge-local counterfactual replay via registered decision evaluators.
- Replay does not re-execute downstream side effects.

### Structural / minimal causal analysis

- Structural slices over declared dependencies.
- Delta-debugging reduction to a tested minimal subset (reported as a
  required-cause preservation proxy, not causal minimality).

### Provenance

- Exact provenance over recorded deterministic field paths; unverified neural
  boundaries stay coarse. Redaction is opt-in and best-effort.

### Interaction analysis

- Shapley values and interaction indices over decision ports (up to four
  ports exact enumeration). Bootstrap sign proportions are descriptive, not
  p-values. Live-trace joint-branch ancestry is reported as joint ancestry,
  not causal interaction.

### Benchmark suite

- Offline, provider-neutral suite calling the same capture/graph/replay
  APIs as the application (`uv run casuality-benchmark ...`):
  - five deterministic scenarios (`single_cause`, `multiple_parents`,
    `interaction`, `distractor`, `memory_contamination`): 5/5 pass;
  - Experiment 2 (shared-state dependency recovery): 100/100;
  - Experiment 3 (semantic-port vs raw-text deletion): 20/20 semantic-port
    successes, raw-deletion failure rate 0.7 (target > 0.35 met);
  - failure-injection controls: 3/3 pass.
- Experiment 1 (offline): deterministic 2x2 counterfactual evaluation passes
  (12 true positives / 12 true negatives for both Agent-Casuality Shapley and
  the naive 2x2 contrast).
- Experiment 1 (external, Fastino): explicitly provider-blocked and deferred.
  The current Fastino catalog exposes no structured-output capability and
  `fastino/GLiNER-2.5-Decide` returns a single `intent` classification rather
  than independent `good`/`bad` branch decisions, so no external Experiment 1
  was completed.

### `agent-replay` baseline

- `uv run casuality-benchmark baseline` runs real `ingest` / `list` / `diff`
  with `clay-good/agent-replay 0.2.0` (commit
  `ccda6229a9451692fb6f1d6d323dd825c2be9dbb`) against all five scenarios.
- Scored as divergence localization only; multi-parent causality,
  interactions, shared-state causality, distractor reasoning, and minimal
  reduction are explicitly unsupported by the baseline.

### OpenCode adapter

- Fail-open OpenCode V1 plugin at `.opencode/plugins/agent-casuality.ts`
  (global `event` hook plus `tool.execute.before/after`, `permission.ask`,
  `command.execute.before`, `chat.message`, `chat.params`; 256-envelope
  buffer, 3 retries, telemetry never interrupts OpenCode).
- Local ingest receiver `casuality-opencode-ingest`
  (`POST /v1/opencode/events`, optional bearer token, privacy redaction
  before SQLite storage).

### Real OpenCode benchmark

- `uv run casuality-benchmark opencode` runs real OpenCode coding-agent
  sessions (`1.18.34`) with the plugin enabled, then scores minimum expected
  event-class coverage and diagnosis quality.
- Committed result: capture micro-average `0.928`, macro-average `0.967`
  across 7 runs / 5 tasks; non-deviated cause identification `1.0` (4 runs);
  3 `shared_state_contamination` runs are agent deviations (the agent refused
  the unsafe override), not adapter failures.
- Live-trace minimal slices are a required-cause preservation proxy
  (causal minimality not measurable); live-trace branch results are joint
  ancestry (causal interaction unsupported).

### Availability

- Python: install with `uv add agent-casuality` or `uv pip install agent-casuality`
  (`agent-casuality==0.1.0` on PyPI).
- OpenCode plugin: `opencode plugin add @psionic-labs/opencode-agent-casuality`
  (`@psionic-labs/opencode-agent-casuality==0.1.0` on npm).
- Ground-truth JSONs ship inside the distribution (`benchmark/ground_truth`,
  `benchmark/opencode/ground_truth`).
