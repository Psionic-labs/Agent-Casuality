# Agent-Casuality

Causal debugging for branching multi-agent systems.

## 60 seconds

**What is it?** A causal debugging substrate for branching and merging
multi-agent LLM systems. It records agent activity as a causal event graph
and explains failures with grounded evidence instead of guesses.

**Why not ordinary observability?** Logs and traces show what happened.
Agent-Casuality records explicit causal parents, decision contracts with
baselines, and resource versions — then *tests* which inputs actually flip
the outcome via merge-local counterfactual replay.

**How does it work?**

```text
Agent execution
→ event capture
→ causal graph
→ slice / provenance / interaction
→ grounded diagnosis
```

**Install?** `uv add agent-casuality` ([details](#installation)).

**Demo?** [Quick start](#quick-start) (30 seconds, offline) or the
[real OpenCode demo](#real-opencode-demo) below.

**OpenCode?** Start the receiver, run OpenCode, the plugin ships telemetry
fail-open ([details](#opencode-integration)).

## Installation

Requires Python 3.11+ and `uv`. Published on PyPI as `agent-casuality`
(v0.1.0):

```powershell
uv init
```

```powershell
uv add agent-casuality
```
OR 

```powershell
uv pip install agent-casuality
```

From a repository checkout (development):

```powershell
uv sync
```

## Quick start

Offline demo, no server, key, or network needed:

```powershell
uv run python examples/customer_approval.py
```

It captures two agent results plus a wrong approval, persists the run to
`.casuality/example.db`, reopens it in a fresh CLI process, and prints a
grounded offline explanation:

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

Inspect the same failure directly:

```powershell
uv run casuality --load-module examples.customer_approval --db .casuality/example.db explain <failure-event-id> --no-llm
```

## Real OpenCode demo

The strongest demo - a real coding-agent session captured live:

```text
real OpenCode execution
→ captured events
→ causal analysis
→ diagnosis
```

No video artifact ships with this release; the walkthrough uses the actual
commands and committed output (`benchmark/results/opencode/opencode.md`,
OpenCode `1.18.34`).

```powershell
# Terminal 1: receiver
uv run casuality-opencode-ingest --db .casuality/opencode.db
# Terminal 2: agent (plugin posts automatically)
opencode run "Read RESEARCH.md, implement sort_items in task.py as recommended, run the test script."
```

Representative committed result (`stale_research`):

```text
Status: completed (exit 0), events: 211, capture coverage: 1.0, diagnosis: scored
```

Committed benchmark: 7 runs across 5 tasks, capture micro-average `0.928` /
macro-average `0.967`, cause identification `1.0` on non-deviated runs.
Three `shared_state_contamination` runs are agent deviations (the agent
refused the unsafe override), not adapter failures.

## Benchmarks / results

Summary of committed artifacts in `benchmark/results/` (JSON + Markdown).
Full methodology lives in the artifacts and `docs/`; headlines:

| Suite | Command | Result |
| --- | --- | --- |
| Five deterministic scenarios | `uv run casuality-benchmark scenarios` | 5/5 pass; exact-match `1.0` on slice, provenance, interaction |
| Experiment 2 (shared-state recovery) | `uv run casuality-benchmark experiment2 --dependencies 100` | 100/100 recovered |
| Experiment 3 (semantic-port vs raw deletion) | `uv run casuality-benchmark experiment3` | 20/20 semantic-port successes; raw-deletion failure rate 70% (target > 35% met) |
| Failure injection | `uv run casuality-benchmark failure-injection` | 3/3 pass |
| Experiment 1 (offline) | `uv run casuality-benchmark experiment1 --repetitions 3` | Passes (12 true positives / 12 true negatives) |
| Experiment 1 (external Fastino) | `uv run casuality-benchmark experiment1 --provider fastino` | Provider-blocked / deferred — catalog has no structured-output capability, so no external run was completed |
| `agent-replay 0.2.0` baseline | `uv run casuality-benchmark baseline` | Divergence localization only; multi-parent causality, interactions, shared-state causality, distractor reasoning, and minimal reduction unsupported |
| OpenCode coding-agent benchmark | `uv run casuality-benchmark opencode` | See [demo](#real-opencode-demo) above |

Terminology (proxies are never presented as stronger claims):

- Capture is **minimum expected event-class coverage**, not generic recall.
- Live-trace branch results are **joint ancestry**, not causal interaction
  (true causal interaction is **unsupported** without counterfactuals).
- Minimal slices are a **required-cause preservation proxy**, not causal
  minimality (true minimality is **not_measurable** on live traces).
- Unsupported / unmeasurable capabilities are stated explicitly in each
  artifact.

## OpenCode integration

Plugin: [.opencode/plugins/agent-casuality.ts](.opencode/plugins/agent-casuality.ts)
(global `event` hook plus tool, permission, command, and chat hooks).
Test: [tests/test_opencode_adapter.py](tests/test_opencode_adapter.py).

Ingest endpoint:

```text
POST http://127.0.0.1:8765/v1/opencode/events
```

Optional token (sent as a bearer header):

```powershell
$env:CASUALITY_OPENCODE_INGEST_URL = "http://127.0.0.1:8765/v1/opencode/events"
$env:CASUALITY_OPENCODE_INGEST_TOKEN = "your-token"
uv run casuality-opencode-ingest --db .casuality/opencode.db
```

Privacy: secret keys/values are redacted to `[REDACTED]` before storage.
Redaction is opt-in and best-effort.

Fail-open: the plugin buffers at most 256 envelopes, retries 3 times, and
drops telemetry rather than interrupting OpenCode; the receiver answers
`202` on malformed input instead of failing the run. `file.edited` and
watcher events carry no session ID in the OpenCode SDK and are attributed
to `unknown`.

## Python and CLI usage

`examples/customer_approval.py` is the complete runnable API example:

- `casuality.init(path)` — SQLite-backed runtime;
- `@casuality.agent(role=...)` — captured tool-like agents;
- `@casuality.merge_decision(...)` — decision ports, baselines, evaluators.

Use the low-level SDK for explicit clocks, causal parents, field
provenance, or non-local storage (see [GETTING_STARTED.md](GETTING_STARTED.md)).

```powershell
uv run casuality --fixture fixture/fixture.json slice A4
uv run casuality --fixture fixture/fixture.json minimize A4
uv run casuality --fixture fixture/fixture.json interaction dec_customer_approval_A3
uv run casuality --fixture fixture/fixture.json explain A4 --no-llm
```

Commands: `agents`, `slice`, `why`, `reconstruct`, `provenance`, `replay`,
`interaction`, `minimize`, `explain`. Pick a backend with `--fixture PATH`,
`--db PATH`, or `DATABASE_URL` (defaults to `.casuality/events.db`,
which only Python capture code creates).

## Scope and limits

- A structural slice is declared-dependency evidence, not proof every
  included event influenced the outcome.
- Replay needs a registered evaluator and never re-executes side effects.
- Exact attribution supports up to four decision ports; bootstrap sign
  proportions are descriptive, not p-values.
- LLM explanations must stay grounded in the supplied evidence package.
- Research background: [docs/thesis.md](docs/thesis.md),
  [docs/implementation-plan.md](docs/implementation-plan.md),
  [docs/research-memo.md](docs/research-memo.md).

## Optional services and checks

```powershell
uv sync --extra explain
$env:OPENROUTER_API_KEY = "your-key"
uv run casuality --fixture fixture/fixture.json explain A4 --model "your/model"
```

```powershell
uv sync --extra postgres
$env:DATABASE_URL = "postgresql://user:password@host/database"
```

```powershell
uv run pytest -q
uv run ruff check .
uv run ty check .
```

Details: [GETTING_STARTED.md](GETTING_STARTED.md),
[TEST.md](TEST.md). Release notes: [CHANGELOG.md](CHANGELOG.md).
