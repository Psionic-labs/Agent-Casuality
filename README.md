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

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv init
```

```bash
uv add agent-casuality
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

Capture live coding-agent sessions with the OpenCode plugin. Telemetry is
fail-open: it never interrupts your agent. On the committed OpenCode benchmark, the ground-truth cause was recovered on every non-deviated run.
[Setup guide →](docs/opencode.md)

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
