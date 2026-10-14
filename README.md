# Agent-Casuality

[![PyPI version](https://img.shields.io/pypi/v/agent-casuality)](https://pypi.org/project/agent-casuality/)
[![npm version](https://img.shields.io/npm/v/@psionic-labs/opencode-agent-casuality)](https://www.npmjs.com/package/@psionic-labs/opencode-agent-casuality)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green)](https://github.com/Psionic-labs/Agent-Casuality/blob/main/LICENSE)
[![OpenCode 1.19+](https://img.shields.io/badge/opencode-1.19%2B-purple)](https://opencode.ai)

*Causal debugging for branching multi-agent systems — plus the OpenCode capture plugin.*

Agent-Casuality records what your agents did as a causal event graph, then
explains failures with grounded evidence instead of guesses.

> **This README is identical on both registries.** The full system needs
> **both** packages:
>
> - **Python (`agent-casuality` on PyPI)** — SDK, CLI, ingest receiver
>   (`casuality-opencode-ingest`), and Visual DAG Explorer
>   (`casuality-explorer`). Installing only this gives you the offline demo
>   but no live OpenCode capture.
> - **JavaScript (`@psionic-labs/opencode-agent-casuality` on npm)** —
>   OpenCode plugin (telemetry capture only). Installing only this gives you
>   events with nowhere to persist or view them.
>
> Source: <https://github.com/Psionic-labs/Agent-Casuality>

[Demo video](#demo-video) ·
[Install](#install--you-need-both-packages) ·
[30-second demo](#try-it-in-30-seconds-no-server-key-or-network) ·
[Single-run capture](#single-run-capture-ingest--opencode--explorer) ·
[Explorer](#see-it-visual-dag-explorer) ·
[OpenCode](#works-with-opencode) ·
[Docs](#documentation)

---

## Demo video

[![Agent-Casuality demo — watch on YouTube](https://img.youtube.com/vi/bogmzYe9Hzs/hqdefault.jpg)](https://www.youtube.com/watch?v=bogmzYe9Hzs)

*Full walkthrough, click the thumbnail to watch on YouTube.*

*The Video follows the Single-run capture given below*

---

## Why it exists

Logs and traces show *what happened*. When several agents branch, merge, and
share state, that isn't enough to tell *what actually caused* a bad outcome.

Agent-Casuality adds three things ordinary observability lacks:

| Gap in ordinary observability | What Agent-Casuality records |
| --- | --- |
| Scattered logs, no links | **Explicit causal parents** for every event |
| Decisions with no reference point | **Decision contracts with baselines** |
| Guesses about "what if" | **Counterfactual replay** that tests which inputs flip the outcome |

```text
Agent execution → event capture → causal graph → slice / provenance / interaction → grounded diagnosis
```

---

## Install — you need BOTH packages

Published as `agent-casuality==0.1.4`
([PyPI](https://pypi.org/project/agent-casuality/)) and
`@psionic-labs/opencode-agent-casuality==0.1.4`
([npm](https://www.npmjs.com/package/@psionic-labs/opencode-agent-casuality)).
Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
for source checkouts; PyPI/npm consumers only need `pip`/`opencode`.

```bash
# 1. Python side (SDK + receiver + explorer + CLI)
pip install agent-casuality
# or, inside a uv project:
uv add agent-casuality

# 2. JavaScript side (OpenCode capture plugin — telemetry only)
opencode plugin add @psionic-labs/opencode-agent-casuality
```

> **npm-only installers:** you still need the PyPI package — the Visual DAG
> Explorer and the `casuality-opencode-ingest` receiver ship **only** in
> `agent-casuality`, not in this npm package.
>
> **PyPI-only installers:** you still need the npm package for live OpenCode
> capture — `pip install agent-casuality` alone cannot observe an OpenCode
> session without the plugin.

*Optional — AI explanation extra.* Only needed for LLM-grounded `explain` /
*Generate AI analysis* (needs `httpx` + `OPENROUTER_API_KEY`):

```bash
# pip consumer
pip install "agent-casuality[explain]"
# uv project
uv add "agent-casuality[explain]"
# source checkout
uv sync --extra explain
```

---

## Try it in 30 seconds (no server, key, or network)

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

---

## Single-run capture: ingest → opencode → explorer

The minimal end-to-end loop. One isolated SQLite file per run keeps traces
separate (`.casuality/single-run.db` below is just an example — any path
works) and port `8797` avoids clashing with the default `8766` explorer.

**Terminal 1 — start the receiver:**

```bash
# PyPI install
casuality-opencode-ingest --db .casuality/single-run.db
# Source checkout
uv run casuality-opencode-ingest --db .casuality/single-run.db
```

**Terminal 2 — run one instrumented agent task** (plugin posts automatically):

```bash
opencode run "Run the existing tests before editing. Diagnose and fix the bug in discount.py so both tests pass. Do not modify the tests. Rerun the tests and summarize the change."
```

*Optional — enable AI explanations for this project:*

```bash
uv add "agent-casuality[explain]"
# pip equivalent: pip install "agent-casuality[explain]"
```

**Terminal 3 — inspect the trace in the Visual DAG Explorer:**

```bash
# PyPI install
casuality-explorer --db .casuality/single-run.db --port 8797
# Source checkout
uv run python -m explorer.server --db .casuality/single-run.db --port 8797
```

Then open <http://127.0.0.1:8797>. Each `opencode run` appends to the same
`--db` file; use a fresh `--db` path per task for one-trace-per-file
(any filename works).

---

## See it: Visual DAG Explorer

Open any capture as an interactive causal graph — no API key needed.
The Explorer ships inside the `agent-casuality` PyPI wheel (no clone needed):

```bash
# PyPI install
pip install agent-casuality
casuality-explorer
casuality-explorer --db .casuality/opencode.db --port 8766
```

```bash
# Source checkout
uv run python -m explorer.server
uv run python -m explorer.server --db .casuality/opencode.db --port 8766
# Single-run variant from the section above:
uv run python -m explorer.server --db .casuality/single-run.db --port 8797
```

Then open <http://127.0.0.1:8766> (or `:8797` for the single-run variant).
The bundled demo trace loads: a failing test, the fix edit, and the passing
retry, with the failure path highlighted.

![Visual DAG Explorer — live OpenCode trace with the failure target selected, causal edges, and inspector](https://github.com/Psionic-labs/Agent-Casuality/raw/main/docs/screenshots/explorer-shared-state-fresh.png)

*Freshly captured `shared_state_contamination` run (240 events, 6 causal
edges) — the checker's failure node selected, its causal chain in the
inspector.*

![Visual DAG Explorer Timeline view — per-agent lanes in sequence order, the failure target selected, with minimap and event inspector](https://github.com/Psionic-labs/Agent-Casuality/raw/main/docs/screenshots/timeline.png)

*Bundled demo trace in the Timeline view — per-agent lanes (run, bash, edit),
the retry's `tool_result` ("app tests pass") selected as the failure target,
with the "Why did it fail?" strip and event inspector alongside.*

What you get:

- **Graph + Timeline views** of the declared causal parents — every edge
  was recorded at capture time, none inferred.
- **Event inspector** — click any node for its command, result, parents,
  and children.
- **Analysis tabs** (chain, provenance, interaction, evidence, metrics)
  stay informative even with no ground truth, built from capture facts.
- **Your own runs**: point it at a live capture —
  `casuality-explorer --db .casuality/opencode.db`
  (source checkout: `uv run python -m explorer.server --db .casuality/opencode.db`).
- **Optional AI interpretation**: install the `explain` extra
  (`pip install "agent-casuality[explain]"` / `uv add "agent-casuality[explain]"`),
  set `OPENROUTER_API_KEY` (and optionally `OPENROUTER_MODEL`, default
  `nvidia/nemotron-3-ultra-550b-a55b:free`), then click *Generate AI analysis*
  in the "Why did it fail?" strip. The model text lives in its own labeled
  block — never mixed with the evidence.

Full acceptance procedure:
[TEST.md §29](https://github.com/Psionic-labs/Agent-Casuality/blob/main/TEST.md).

---

## Use it with your agents

```python
import casuality

casuality.init(".casuality/events.db")

@casuality.agent(role="risk_checker")
def check_risk(customer): ...

@casuality.merge_decision(...)
def approve(customer_status, risk_score): ...
```

See
[`examples/customer_approval.py`](https://github.com/Psionic-labs/Agent-Casuality/blob/main/examples/customer_approval.py)
for a complete runnable example.

---

## Works with OpenCode

Capture live coding-agent sessions. Telemetry is fail-open: it never
interrupts your agent. **Requires both packages** (receiver from PyPI,
plugin from npm).

```bash
# Terminal 1: receiver (PyPI install; source checkout: uv run casuality-opencode-ingest ...)
casuality-opencode-ingest --db .casuality/opencode.db
# Terminal 2: agent (plugin posts automatically)
opencode run "Read RESEARCH.md, implement sort_items in task.py as recommended, run the test script."
# Terminal 3: Visual DAG
casuality-explorer --db .casuality/opencode.db
```

Full consumer flow: install `agent-casuality` (PyPI) → install the OpenCode
plugin (`opencode plugin add @psionic-labs/opencode-agent-casuality`, npm) →
start the receiver → run OpenCode → launch `casuality-explorer` → inspect the
recorded trace. No repository clone is needed.

> Representative committed result (`stale_research`, OpenCode `1.19.0`):
> `completed (exit 0), 331 events, capture coverage 1.0, diagnosis scored`
> (see `benchmark/results/opencode/opencode.md`). No video artifact ships
> with this release.
> [Setup guide →](https://github.com/Psionic-labs/Agent-Casuality/blob/main/docs/opencode.md)

### What the plugin captures

The npm plugin forwards OpenCode's global event stream plus explicit hooks
(`tool.execute.before/after`, `permission.ask`, `command.execute.before`,
`chat.message`, `chat.params`). The Python receiver maps these onto canonical
events, registers file writes with Resource-Version machinery, and redacts
secrets before SQLite persistence. It is telemetry capture only — the
Explorer and CLI live in the PyPI distribution.

---

## Benchmarks

Offline, provider-neutral suite (`uv run casuality-benchmark ...`) plus a
real OpenCode coding-agent benchmark. Full results in
[`docs/benchmarks.md`](https://github.com/Psionic-labs/Agent-Casuality/blob/main/docs/benchmarks.md)
and `benchmark/results/`.

- Five deterministic scenarios: **5/5 pass**.
- Experiment 2 (shared-state recovery): **100/100**.
- Experiment 3 (semantic-port vs raw deletion): **20/20** semantic-port
  successes; raw-deletion failure rate met target.
- Experiment 1 (offline): passes; external Fastino run is
  provider-blocked/deferred (no structured-output capability).
- Real OpenCode benchmark (5 runs / 5 tasks, OpenCode `1.19.0`): capture
  micro/macro-average `1.0`; cause recall mean `0.3` (structural-slice
  ancestry under explicit-evidence edges only); joint ancestry `0.0` —
  genuine causal interaction is unsupported from live traces.

*Terminology is precise: live-trace branch results are reported as
`joint ancestry` (not causal interaction), and minimal slices as a
`required-cause preservation proxy` (not causal minimality).*

---

## Documentation

| Topic | Link |
| --- | --- |
| Getting started | [GETTING_STARTED.md](https://github.com/Psionic-labs/Agent-Casuality/blob/main/GETTING_STARTED.md) |
| OpenCode integration | [docs/opencode.md](https://github.com/Psionic-labs/Agent-Casuality/blob/main/docs/opencode.md) |
| CLI and Python reference | [docs/reference.md](https://github.com/Psionic-labs/Agent-Casuality/blob/main/docs/reference.md) |
| Benchmarks and results | [docs/benchmarks.md](https://github.com/Psionic-labs/Agent-Casuality/blob/main/docs/benchmarks.md) |
| Scope and limits | [docs/reference.md](https://github.com/Psionic-labs/Agent-Casuality/blob/main/docs/reference.md) |
| Research background | [docs/thesis.md](https://github.com/Psionic-labs/Agent-Casuality/blob/main/docs/thesis.md), [docs/research-memo.md](https://github.com/Psionic-labs/Agent-Casuality/blob/main/docs/research-memo.md) |
| Contributing and tests | [TEST.md](https://github.com/Psionic-labs/Agent-Casuality/blob/main/TEST.md), [CONTRIBUTING.md](https://github.com/Psionic-labs/Agent-Casuality/blob/main/CONTRIBUTING.md) |
| Release notes | [CHANGELOG.md](https://github.com/Psionic-labs/Agent-Casuality/blob/main/CHANGELOG.md) |
