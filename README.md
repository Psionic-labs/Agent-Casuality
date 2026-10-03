# Agent-Casuality

Causal debugging for branching multi-agent systems.

Agent-Casuality is a causal debugging and observability substrate for branching and merging multi-agent LLM systems. It records agent activity as a causal event graph, persists and reconstructs execution state, and explains decisions through structural slices, decision contracts, and causal dependency analysis.

## Quick start

Requirements:

- Python 3.11 or newer
- `uv`

From the repository root:

```powershell
uv sync
```

### One-command end-to-end demo

```powershell
uv run python examples/customer_approval.py
```

The demo requires no PostgreSQL server, API key, or network access. It:

1. captures two agent results and an incorrect approval decision;
2. persists the run to `.casuality/example.db`;
3. closes SQLite and reopens the database in a fresh CLI process; and
4. prints a grounded offline explanation.

A successful run includes:

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

## Benchmarks

The provider-neutral benchmark suite is offline by default and calls the same
capture, graph, validation, replay, provenance, and explanation APIs as the
application. It never uses an API key during pytest or ordinary benchmark runs.

```powershell
# fixture integration control and five synthetic scenarios
uv run pytest tests/integration/test_customer_approval.py -q
uv run casuality-benchmark scenarios

# causal-evidence corruptions and the three validation experiments
uv run casuality-benchmark failure-injection
uv run casuality-benchmark experiment1 --repetitions 3
uv run casuality-benchmark experiment2 --dependencies 100
uv run casuality-benchmark experiment3
uv run casuality-benchmark baseline
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
