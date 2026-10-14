# Reference

## Python API

`examples/customer_approval.py` is the complete runnable example:

- `casuality.init(path)` — SQLite-backed runtime
- `@casuality.agent(role=...)` — captured tool-like agents
- `@casuality.merge_decision(...)` — decision ports, baselines, evaluators

Use the low-level SDK for explicit clocks, causal parents, field provenance,
or non-local storage (see [GETTING_STARTED.md](../GETTING_STARTED.md)).

## CLI

```powershell
uv run casuality --load-module examples.customer_approval --db .casuality/example.db explain <failure-event-id> --no-llm
uv run casuality --fixture fixture/fixture.json slice A4
uv run casuality --fixture fixture/fixture.json minimize A4
uv run casuality --fixture fixture/fixture.json interaction dec_customer_approval_A3
uv run casuality --fixture fixture/fixture.json explain A4 --no-llm
```

Commands: `agents`, `slice`, `why`, `reconstruct`, `provenance`, `replay`,
`interaction`, `minimize`, `explain`.

Pick a backend with `--fixture PATH`, `--db PATH`, or `DATABASE_URL`. The
default is `.casuality/events.db`, which only Python capture code creates.

## Scope and limits

- A structural slice is declared-dependency evidence, not proof every included
  event influenced the outcome.
- Replay needs a registered evaluator and never re-executes side effects.
- Exact attribution supports up to four decision ports; bootstrap sign
  proportions are descriptive, not p-values.
- LLM explanations must stay grounded in the supplied evidence package.

## Visual DAG Explorer

Read-only viewer over recorded causal edges (never inferred).
Ships inside the `agent-casuality` wheel as vendored static assets
(`explorer/static/`, synced from `frontend/out/`); no clone needed:

```powershell
# PyPI install
casuality-explorer
casuality-explorer --db .casuality/opencode.db --port 8766
# Isolated single-run file (any path works — name is just an example)
casuality-explorer --db .casuality/single-run.db --port 8797
# Source checkout
uv run python -m explorer.server
uv run python -m explorer.server --db .casuality/opencode.db --port 8766
uv run python -m explorer.server --db .casuality/single-run.db --port 8797
```

Open <http://127.0.0.1:8766>. Default serves the bundled demo trace; `--db`
points at a live SQLite capture. No API key is needed except for the opt-in
*Generate AI analysis* button.

| Endpoint | Content |
| --- | --- |
| `GET /api/overview` | Nodes + declared causal edges, failure target |
| `GET /api/failure` | How the failure target was chosen (resolved / fallback) |
| `GET /api/diagnosis` | Benchmark diagnosis dimensions for the failure |
| `GET /api/event?id=<id>` | One event with parents, children, full record |
| `GET /api/evidence` | Evidence package + offline summary |
| `GET /api/ai-diagnosis` | Opt-in model interpretation, quarantined from facts |

`/api/ai-diagnosis` needs `OPENROUTER_API_KEY` (model via `OPENROUTER_MODEL`,
default `nvidia/nemotron-3-ultra-550b-a55b:free`). Without a key it returns
`503 ai_unavailable`; model/format failures return `502` with the cause. The
model text is always labeled interpretation, never mixed with evidence.

## OpenCode ingest

```text
POST http://127.0.0.1:8765/v1/opencode/events
```

Receiver: `uv run casuality-opencode-ingest --db .casuality/opencode.db`.
Answers `400` on malformed input, `202` with `received`/`normalized`/
`persisted` counts otherwise.

```powershell
# Default shared capture
casuality-opencode-ingest --db .casuality/opencode.db
# Isolated single-run capture (pairs with the discount.py opencode task;
# `.casuality/single-run.db` is just an example — any path works)
casuality-opencode-ingest --db .casuality/single-run.db
# Source checkout: prefix either with `uv run `
```

Single-run agent task (plugin posts automatically once both packages are
installed):

```powershell
opencode run "Run the existing tests before editing. Diagnose and fix the bug in discount.py so both tests pass. Do not modify the tests. Rerun the tests and summarize the change."
```

Plugin environment (see [docs/opencode.md](opencode.md)):

| Variable | Default | Description |
| --- | --- | --- |
| `CASUALITY_OPENCODE_INGEST_URL` | `http://127.0.0.1:8765/v1/opencode/events` | Ingest endpoint |
| `CASUALITY_OPENCODE_INGEST_TOKEN` | _(unset)_ | Sent as `Authorization: Bearer <token>` |
| `CASUALITY_OPENCODE_INGEST_TIMEOUT_MS` | `5000` | Per-request timeout in ms |
| `CASUALITY_OPENCODE_BATCH_MAX` | `25` | Max envelopes per POST (singletons stay single objects) |
| `CASUALITY_OPENCODE_LOG_TELEMETRY_FAILURES` | _(unset)_ | Set to `1`/`true` to enable delivery warnings |

Telemetry is fail-open and quiet by default: bounded 256-envelope buffer,
batched POSTs with 3 attempts per batch, drops counted in `telemetryStats`
rather than interrupting OpenCode.

## Benchmarks

```powershell
uv run casuality-benchmark scenarios
uv run casuality-benchmark experiment2 --dependencies 100
uv run casuality-benchmark experiment3
uv run casuality-benchmark opencode --timeout 420
```

Full results in [benchmarks.md](benchmarks.md) and `benchmark/results/`.

## Optional services

```powershell
uv sync --extra explain
# PyPI / uv consumers instead:
# pip install "agent-casuality[explain]"
# uv add "agent-casuality[explain]"
$env:OPENROUTER_API_KEY = "your-key"
uv run casuality --fixture fixture/fixture.json explain A4 --model "your/model"
```

```powershell
uv sync --extra postgres
$env:DATABASE_URL = "postgresql://user:password@host/database"
```

## Development

```powershell
uv sync
uv run pytest -q
uv run ruff check .
uv run ty check .
```

See [TEST.md](../TEST.md) and [CHANGELOG.md](../CHANGELOG.md).

Research background: [thesis.md](thesis.md),
[implementation-plan.md](implementation-plan.md),
[research-memo.md](research-memo.md).
