# Changelog

All notable changes to this project will be documented in this file.

## [0.1.2] - 2026-10-11

### AI diagnosis model default and error mapping (Python distribution)

- `DEFAULT_MODEL` is now `nvidia/nemotron-3-ultra-550b-a55b:free`:
  `deepseek/deepseek-v4-flash:free` was retired from OpenRouter's free
  tier (HTTP 404, "unavailable for free"), which broke the explorer's
  opt-in *Generate AI analysis* (`/api/ai-diagnosis` → 502) and the
  `explain` CLI default. Override per call with `OPENROUTER_MODEL`.
- `/api/ai-diagnosis` no longer leaks model-layer failures as HTTP 500:
  `ImportError` (e.g. missing `httpx`) maps to 503 `ai_unavailable` and
  any other unexpected model error maps to 502 `ai_error` with the
  cause attached. The frontend now surfaces the backend's error body
  instead of a bare status code.

## [0.1.1] - 2026-10-11

### OpenCode plugin loader compatibility

- The plugin default export is now the V1 server-plugin module
  (`{ id: "agent-casuality", server: AgentCasualityPlugin }`), supported
  since OpenCode `1.18.29`. Previously the bare-function default export
  fell through to the legacy loader, where the `telemetryStats` object
  export silently disabled the whole plugin on OpenCode `>= 1.19`
  (`Plugin export is not a function`, 0 events ingested).
- Regression coverage: `test/loader-compat.test.mjs` pins the V1 contract
  in `npm test`; `scripts/check-opencode-plugin-compat.py` verifies actual
  loading on real binaries (verified: `1.19.0` with 83 events, `1.18.34`
  with 86 events, 0 receiver errors).

### Real OpenCode benchmark (fresh rerun, 2026-10-11)

- `uv run casuality-benchmark opencode --model
  openrouter/deepseek/deepseek-v4-flash`: 5 runs / 5 tasks on OpenCode
  `1.19.0`, all completed, 0 deviations; artifacts committed under
  `benchmark/results/opencode/`.
- Capture micro/macro-average `1.0`; cause recall mean `0.3`
  (structural-slice ancestry under explicit-evidence edges only); joint
  ancestry `0.0` (genuine causal interaction unsupported from live
  traces); provenance `1.0`; distractors `1.0`.
- This replaces the earlier 7-run result (capture `0.928`/`0.967`, cause
  `1.0`), which was scored from stale traces with linear chaining and
  must not be reused.

### Visual DAG Explorer (core feature, Python distribution)

- The explorer (`uv run python -m explorer.server`, serves its own
  bundled frontend) is part of this release: graph + timeline over
  recorded causal edges, event inspector, and analysis tabs that stay
  informative with no ground truth.
- README showcases a screenshot captured from a fresh
  `shared_state_contamination` trace (240 events, 6 causal edges,
  `docs/screenshots/explorer-shared-state-fresh.png`); the reproducible
  capture → serve → view flow is documented in `docs/opencode.md`.
- Scope note: `@psionic-labs/opencode-agent-casuality@0.1.1` is the
  telemetry-capture plugin only (hooks, buffering, fail-open delivery) —
  installing it does not install the visual interface, which ships with
  the `agent-casuality` Python distribution.

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
