# Agent-Casuality

Causal debugging for branching multi-agent systems.

Agent-Casuality records what your agents did as a causal event graph, then
explains failures with grounded evidence instead of guesses.

## Why it exists

Logs and traces show *what happened*. When several agents branch, merge, and
share state, that isn't enough to tell *what actually caused* a bad outcome.

Agent-Casuality adds three things ordinary observability lacks:

- **Explicit causal parents** for every event
- **Decision contracts with baselines**, so each decision has a reference point
- **Counterfactual replay**, which tests which inputs actually flip the outcome

```text
Agent execution → event capture → causal graph → slice / provenance / interaction → grounded diagnosis
```

## Install

Published as `agent-casuality==0.1.0` (PyPI) and
`@psionic-labs/opencode-agent-casuality==0.1.0` (npm).

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv init
```

```bash
uv add agent-casuality
opencode plugin add @psionic-labs/opencode-agent-casuality
```

## Try it in 30 seconds

No server, API key, or network needed:

```bash
uv run python examples/customer_approval.py
```

It captures two agent results and a wrong approval, then explains the failure:

```text
Outcome: approved
Diagnosis: The terminal event is marked 'failure' because the decision returned
'approved' with customer_status='eligible' and risk_score=0.2.
Evidence:
- Minimal tested chain: customer_status + risk_score -> decision -> terminal failure
- Canonical baselines were 'ineligible' and 0.8
- Interaction between customer_status and risk_score: 1.0
Limitations: the evidence does not establish why the upstream tools produced these values.
```

## See it: Visual DAG Explorer

Open the capture as an interactive causal graph — no API key needed:

```bash
uv run python -m explorer.server
```

Then open <http://127.0.0.1:8766>. The bundled demo trace loads:
a failing test, the fix edit, and the passing retry, with the failure
path highlighted.

![Visual DAG Explorer — graph view with the failure path highlighted](docs/screenshots/explorer-graph-fallback.png)

- **Graph + Timeline views** of the declared causal parents — every edge
  was recorded at capture time, none inferred.
- **Event inspector** — click any node for its command, result, parents,
  and children.
- **Analysis tabs** (chain, provenance, interaction, evidence, metrics)
  stay informative even with no ground truth, built from capture facts.
- **Your own runs**: point it at a live capture —
  `uv run python -m explorer.server --db .casuality/opencode.db`.
- **Optional AI interpretation**: set `OPENROUTER_API_KEY` (and optionally
  `OPENROUTER_MODEL`), then click *Generate AI analysis* in the
  "Why did it fail?" strip. The model text lives in its own labeled
  block — never mixed with the evidence.

Full acceptance procedure: [TEST.md §29](TEST.md).

## Use it with your agents

```python
import casuality

casuality.init(".casuality/events.db")

@casuality.agent(role="risk_checker")
def check_risk(customer): ...

@casuality.merge_decision(...)
def approve(customer_status, risk_score): ...
```

See [`examples/customer_approval.py`](examples/customer_approval.py) for a
complete runnable example.

## Works with OpenCode

Capture live coding-agent sessions. Telemetry is fail-open: it never
interrupts your agent.

```powershell
# Terminal 1: receiver
uv run casuality-opencode-ingest --db .casuality/opencode.db
# Terminal 2: agent (plugin posts automatically)
opencode run "Read RESEARCH.md, implement sort_items in task.py as recommended, run the test script."
```

Representative committed result (`stale_research`, OpenCode `1.18.34`):
`completed (exit 0), 211 events, capture coverage 1.0, diagnosis scored`
(see `benchmark/results/opencode/opencode.md`). No video artifact ships
with this release. [Setup guide →](docs/opencode.md)

## Benchmarks

Offline, provider-neutral suite (`uv run casuality-benchmark ...`) plus a
real OpenCode coding-agent benchmark. Full results in
[`docs/benchmarks.md`](docs/benchmarks.md) and `benchmark/results/`.

- Five deterministic scenarios: 5/5 pass.
- Experiment 2 (shared-state recovery): 100/100.
- Experiment 3 (semantic-port vs raw deletion): 20/20 semantic-port
  successes; raw-deletion failure rate met target.
- Experiment 1 (offline): passes; external Fastino run is
  provider-blocked/deferred (no structured-output capability).
- Real OpenCode benchmark (7 runs / 5 tasks): capture micro-average `0.928`,
  macro-average `0.967`; cause identification `1.0` on non-deviated runs.

Terminology is precise: live-trace branch results are reported as
`joint ancestry` (not causal interaction), and minimal slices as a
`required-cause preservation proxy` (not causal minimality).

## Documentation

| Topic | Link |
| --- | --- |
| Getting started | [GETTING_STARTED.md](GETTING_STARTED.md) |
| OpenCode integration | [docs/opencode.md](docs/opencode.md) |
| CLI and Python reference | [docs/reference.md](docs/reference.md) |
| Benchmarks and results | [docs/benchmarks.md](docs/benchmarks.md) |
| Scope and limits | [docs/reference.md#scope-and-limits](docs/reference.md#scope-and-limits) |
| Research background | [docs/thesis.md](docs/thesis.md), [docs/research-memo.md](docs/research-memo.md) |
| Contributing and tests | [TEST.md](TEST.md), [CONTRIBUTING.md](CONTRIBUTING.md) |
| Release notes | [CHANGELOG.md](CHANGELOG.md) |
