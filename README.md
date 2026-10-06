# Agent-Casuality

Causal debugging for branching multi-agent systems.

## 60 seconds

**What is Agent-Casuality?** A causal debugging substrate for branching and
merging multi-agent LLM systems. It records agent activity as a causal event
graph and explains failures with grounded evidence instead of guesses.

**Why is causal debugging different from ordinary agent observability?**
Ordinary observability shows you logs and traces. Agent-Casuality records
explicit causal parents, decision contracts with baselines, and resource
versions, then *tests* which inputs actually flip the outcome via merge-local
counterfactual replay. A structural slice is declared-dependency evidence;
replay reduces it to the smaller subset that was actually tested.

**How does it work?**

```text
Agent execution
→ event capture
→ causal graph
→ slice / provenance / interaction
→ grounded diagnosis
```

Capture records tool, memory, model, and lifecycle events. The graph validator
checks dangling parents, cross-run edges, sequence progression, and
decision-port reachability. Slice, provenance, Shapley interaction, and replay
produce an offline evidence package; the optional LLM explanation must stay
grounded in that package.

**How do I install it?** See [Installation](#installation).

**How do I run the demo?** See [Quick start](#quick-start) (30 seconds,
offline) and [Real OpenCode demo](#real-opencode-demo) (the strongest demo:
real agent execution → captured events → causal analysis → diagnosis).

**How do I use the OpenCode integration?** See [OpenCode integration](#opencode-integration):
start the local receiver, run OpenCode in this repo, the plugin ships
telemetry fail-open.

## Installation

Requirements: Python 3.11 or newer, `uv`.

From the published package (no repository checkout needed, v0.1.0 on PyPI):

```powershell
uv add agent-casuality
```

or:

```powershell
uv pip install agent-casuality
```

From the repository root (development workflow):

```powershell
uv sync
```

## Quick start

The fastest runnable proof (no PostgreSQL server, API key, or network access):

```powershell
uv run python examples/customer_approval.py
```

It captures two agent results and an incorrect approval decision, persists the
run to `.casuality/example.db`, closes SQLite, reopens it in a fresh CLI
process, and prints a grounded offline explanation. A successful run includes:

```text
Captured customer approval failure
Outcome: approved

Offline explanation
Diagnosis: The terminal event is marked 'failure' because the decision returned 'approved' with customer_status='eligible' and risk_score=0.2.
Evidence:
- Minimal tested chain: customer_status + risk_score -> decision -> terminal failure (4 events).
- Recorded inputs were customer_status='eligible' and risk_score=0.2; their canonical baselines are 'ineligible' and 0.8.
- The reported interaction between customer_status and risk_score is 1.0.
- The structural slice contains 8 events; replay reduced it to the smaller tested subset above.
Limitations: the evidence does not establish why the upstream tools produced these values.
```

The example prints the run and failure event IDs plus follow-up commands. Its
default database is ignored by Git, and repeated executions remain isolated by
`run_id`.

Inspect the same failure with the CLI:

```powershell
uv run casuality --load-module examples.customer_approval `
    --db .casuality/example.db explain <failure-event-id> --no-llm
```

## Real OpenCode demo

The strongest demo is a real OpenCode coding-agent session captured live:

```text
real OpenCode execution
→ captured events
→ causal analysis
→ diagnosis
```

There is no GIF/video artifact in this release, so the walkthrough below uses
the actual commands and representative committed output
(`benchmark/results/opencode/opencode.md`, OpenCode `1.18.34`).

Terminal 1 — start the local receiver:

```powershell
uv run casuality-opencode-ingest --db .casuality/opencode.db
# Agent-Casuality OpenCode ingest listening on http://127.0.0.1:8765/v1/opencode/events
```

Terminal 2 — run a real session in this repository with the plugin enabled
(the benchmark harness does exactly this per task via
`opencode run "<prompt>"` with `CASUALITY_OPENCODE_INGEST_URL` pointed at the
receiver):

```powershell
opencode run "Read RESEARCH.md, implement sort_items in task.py as recommended, run the test script."
```

The plugin posts envelopes to `POST /v1/opencode/events`; the receiver maps
them through `record_event`, persists them with `SQLiteEventStore`, and tracks
`file.edited` versions in the `ResourceRegistry`.

Representative committed result (`stale_research-cfbdcbee`):

```text
Status: completed (exit 0), events: 211, capture coverage: 1.0, diagnosis: scored
Unresolved roles: none
```

Across the committed benchmark (7 runs, 5 tasks): capture micro-average
`0.928`, macro-average `0.967` (minimum expected event-class coverage);
cause identification `1.0` on the 4 non-deviated runs. The 3
`shared_state_contamination` runs are agent deviations — the agent refused the
unsafe `shared.json` override, so there is no ground-truth evidence to find —
reported as agent deviation, not adapter failure. Reproduce the full harness
with `uv run casuality-benchmark opencode` (real agent execution; not part of
normal CI).

## Benchmarks / results

Compact summary of committed artifacts in `benchmark/results/`
(JSON plus readable Markdown; `latest.*` names the most recent command).
Each run records scenario, configuration, generated events, canonical JSON
ground truth, predictions, and per-dimension metrics.

| Suite | Command | Committed result |
| --- | --- | --- |
| Five deterministic scenarios | `uv run casuality-benchmark scenarios` | 5/5 pass (`single_cause`, `multiple_parents`, `interaction`, `distractor`, `memory_contamination`); exact-match `1.0` on structural slice, minimal slice, provenance, interaction |
| Experiment 2 (shared-state recovery) | `uv run casuality-benchmark experiment2 --dependencies 100` | 100/100 resource dependencies recovered, recovery rate `1.0` |
| Experiment 3 (semantic-port vs raw deletion) | `uv run casuality-benchmark experiment3` | 20 cases; semantic-port 20/20 successes (failure rate `0.0`); raw-deletion failure rate `0.7` (target > `0.35` met) |
| Failure injection | `uv run casuality-benchmark failure-injection` | 3/3 pass |
| Experiment 1 (offline) | `uv run casuality-benchmark experiment1 --repetitions 3` | Deterministic 2x2 cells pass (12 true positives / 12 true negatives, both Shapley and naive 2x2) |
| Experiment 1 (external Fastino) | `uv run casuality-benchmark experiment1 --provider fastino --repetitions 3 --max-requests 12` | Provider-blocked / deferred: catalog exposes no structured-output capability; `fastino/GLiNER-2.5-Decide` returns a single `intent` classification, not independent `good`/`bad` branch decisions. Not completed. |
| `agent-replay 0.2.0` baseline | `uv run casuality-benchmark baseline` | Real `ingest`/`list`/`diff` (commit `ccda6229a9451692fb6f1d6d323dd825c2be9dbb`); divergence localization supported; multi-parent causality, interactions, shared-state causality, distractor reasoning, minimal reduction explicitly unsupported |
| OpenCode coding-agent benchmark | `uv run casuality-benchmark opencode` | Capture micro `0.928` / macro `0.967`; non-deviated cause `1.0`; see [Real OpenCode demo](#real-opencode-demo) |

Terminology used throughout (do not over-read the proxies):

- Capture is **minimum expected event-class coverage** (captured / expected
  minimum per class), not generic recall.
- Branch results on live traces are **joint ancestry** (both branches are
  ancestors of the failure), not causal interaction — true causal interaction
  is unsupported without counterfactual intervention.
- Minimal-slice results are a **required-cause preservation proxy** (ddmin
  with a ground-truth membership predicate), not causal minimality — true
  causal minimality is not measurable on live traces (no `DecisionContract`
  or observable failure predicate).
- Capabilities that are unsupported or not measurable are stated explicitly in
  each artifact (`unsupported` / `not_measurable`); proxy metrics are never
  presented as stronger claims.

## OpenCode integration

The repository includes a current OpenCode V1 plugin at
[.opencode/plugins/agent-casuality.ts](.opencode/plugins/agent-casuality.ts).
It uses OpenCode's global `event` hook plus `tool.execute.before/after`,
`permission.ask`, `command.execute.before`, `chat.message`, and `chat.params`
hooks. The deterministic adapter test is in
[tests/test_opencode_adapter.py](tests/test_opencode_adapter.py).

Ingest endpoint (local receiver):

```text
POST http://127.0.0.1:8765/v1/opencode/events
```

Token configuration (optional bearer header):

```powershell
$env:CASUALITY_OPENCODE_INGEST_URL = "http://127.0.0.1:8765/v1/opencode/events"
$env:CASUALITY_OPENCODE_INGEST_TOKEN = "your-token"
uv run casuality-opencode-ingest --db .casuality/opencode.db
```

Privacy / redaction: the adapter deep-copies each payload and redacts secret
keys/values (matches `api-key`, `authorization`, `bearer`, `token`, `secret`,
`password`, plus `headers`, `apiKey`, `accessToken`) to `[REDACTED]` via
`PayloadRedactor` before storage. Redaction is opt-in and best-effort.

Fail-open behavior: the plugin buffers at most 256 envelopes (drops oldest
when full), retries delivery 3 times with short backoff and a 1s timeout, and
drops telemetry rather than interrupting OpenCode. The receiver answers `202`
(`{"accepted": n}`, or `{"accepted": 0, "error": "telemetry dropped"}`) on any
malformed input instead of failing the agent run.

How to run a real session:

```powershell
# Terminal 1: receiver
uv run casuality-opencode-ingest --db .casuality/opencode.db
# Terminal 2: agent (plugin posts automatically)
opencode run "<task prompt>"
```

The captured event payload preserves session/message/tool/call IDs, model and
agent metadata, file resources, command and permission data, correlation
parents, and session errors/statuses. `file.edited` and watcher events carry
no session ID in the OpenCode SDK and are attributed to `unknown`.

## Deterministic fixture

The fixture uses readable event IDs and ground-truth annotations, making it the
best control for inspecting individual analytical operations:

```powershell
uv run casuality --fixture fixture/fixture.json slice A4
uv run casuality --fixture fixture/fixture.json minimize A4
uv run casuality --fixture fixture/fixture.json interaction dec_customer_approval_A3
uv run casuality --fixture fixture/fixture.json explain A4 --no-llm
```

The fixture demonstrates a nine-event structural slice reduced to
`B3, C3, A3, A4`, a `customer_status × risk_score` interaction of `1.0`, and
exact provenance over the recorded deterministic path. The live demo proves
persistence and process-reopen behavior; it does not yet record the same
field-level provenance automatically.

## Python API

`examples/customer_approval.py` is the complete runnable convenience-API example.
The local API provides:

- `casuality.init(path)` for a SQLite-backed runtime;
- `@casuality.agent(role=...)` for captured tool-like agents; and
- `@casuality.merge_decision(...)` for decision ports, baselines, and evaluator
  registration.

The convenience API links merge inputs to matching `tool_result` events in the
active run. Use the low-level SDK when an application needs explicit clocks,
causal parents, field provenance, lifecycle management, or non-local storage.
See [GETTING_STARTED.md](GETTING_STARTED.md) for those boundaries.

## CLI workflow

Available commands are:

```text
agents       list fixture agents
slice        show the declared causal ancestor set
why          show decision-port evidence
reconstruct  rebuild agent state at a logical sequence
provenance   trace a recorded field path
replay       evaluate a decision under port interventions
interaction  compute Shapley values and interaction indices
minimize     reduce a structural slice with delta debugging
explain      render offline evidence or request an LLM explanation
```

Choose a backend with `--fixture PATH`, `--db PATH`, or `DATABASE_URL`.
Without either option, the CLI reads `.casuality/events.db`. Python capture code,
not the CLI, creates and writes that database.

Persisted custom decisions require the module that registers their evaluator:

```powershell
uv run casuality --load-module examples.customer_approval `
    --db .casuality/example.db explain <failure-event-id> --no-llm
```

## What the analysis establishes

- **Capture:** Tool, memory, model, and lifecycle events can be recorded with
  logical sequences and explicit causal parents.
- **Storage:** In-memory, SQLite, and PostgreSQL adapters persist event graphs.
- **Validation:** The graph validator checks dangling parents, cross-run edges,
  sequence progression, and decision-port reachability.
- **State:** Recorded events can be reconstructed deterministically.
- **Structure:** A structural slice is declared-dependency evidence, not proof
  that every included event influenced the outcome.
- **Provenance:** Explicit deterministic edges are exact; unverified neural
  boundaries are coarse. Redaction is opt-in and best-effort.
- **Replay:** Merge-local counterfactual replay requires a registered evaluator
  and does not re-execute downstream side effects.
- **Attribution:** Exact enumeration supports up to four decision ports.
  Bootstrap sign proportions are descriptive and are not p-values.
- **Explanation:** Offline summaries expose missing replay results. Optional LLM
  explanations must remain grounded in the supplied evidence package.

## Optional services

### OpenRouter explanations

```powershell
uv sync --extra explain
$env:OPENROUTER_API_KEY = "your-key"
uv run casuality --fixture fixture/fixture.json explain A4 --model "your/model"
```

Without a key, use `--no-llm`. Provider model availability and output are not
required for the local demo.

### PostgreSQL

```powershell
uv sync --extra postgres
$env:DATABASE_URL = "postgresql://user:password@host/database"
```

Use a dedicated database for integration tests because they create schema objects
and leave test rows behind.

## Checks

```powershell
uv run pytest -q
uv run ruff check .
uv run ty check .
```

PowerShell users can run the same gates with:

```powershell
.\scripts\check.ps1
```

The PostgreSQL integration command and detailed verification queries are in
[GETTING_STARTED.md](GETTING_STARTED.md) and [TEST.md](TEST.md). Historical design
and research context is retained in [docs/thesis.md](docs/thesis.md),
[docs/implementation-plan.md](docs/implementation-plan.md), and
[docs/research-memo.md](docs/research-memo.md).

## Full benchmark commands

The provider-neutral benchmark suite is offline by default and calls the same
capture, graph, validation, replay, provenance, and explanation APIs as the
application. It never uses an API key during pytest or ordinary benchmark runs.

```powershell
# fixture integration control and five synthetic scenarios
uv run pytest tests/integration/test_customer_approval.py -q
uv run casuality-benchmark scenarios

# causal-evidence corruptions and the validation experiments
uv run casuality-benchmark failure-injection
uv run casuality-benchmark experiment1 --repetitions 3
uv run casuality-benchmark experiment2 --dependencies 100
uv run casuality-benchmark experiment3
uv run casuality-benchmark baseline
uv run casuality-benchmark opencode
uv run casuality-benchmark all
```

The baseline command uses `clay-good/agent-replay` at commit
`ccda6229a9451692fb6f1d6d323dd825c2be9dbb` and runs its real `ingest`, `list`,
and `diff` workflow against all five scenarios. It measures divergence
localization only; multi-parent causality, interactions, shared-state
causality, distractor reasoning, and minimal reduction remain unsupported.

Results are JSON plus a readable Markdown rendering in `benchmark/results/`;
`latest.*` always names the most recent command. Each run records its scenario,
configuration, generated events, canonical JSON ground truth, predictions, and
per-dimension precision/recall/exact-match metrics. Slice reduction is the
fraction removed from a structural slice. Interaction results separately show
true/false positives and false negatives; provenance reports exact links,
missing links, and unexpected links.

`experiment1` uses deterministic replay offline. To make explicitly opt-in
Fastino requests, set `FASTINO_API_KEY`, `FASTINO_MODEL`, and optionally
`FASTINO_BASE_URL` (default `https://api.fastino.ai/v1`), then run:

```powershell
uv run casuality-benchmark experiment1 --provider fastino --repetitions 3 --max-requests 12
```

Responses are cached in `benchmark/results/model-cache.jsonl` by provider,
model, prompt, temperature, seed, and token limit. Use `--dry-run` to inspect
the experiment without uncached requests. Reported acceptance thresholds are
measured fields in result artifacts, not assertions baked into the test suite.

The current Fastino catalog exposes ten models, all with structured outputs
disabled. `fastino/GLiNER-2.5-Decide` is the only decision-oriented model, but
its live response is a single `intent` classification and not an independent
`good`/`bad` branch decision. The provider rejects that response; the external
Experiment 1 is therefore blocked, while the offline benchmark remains valid.

See [CHANGELOG.md](CHANGELOG.md) for the v0.1.0 release notes.
