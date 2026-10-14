# Getting Started

Agent-Casuality captures branching agent runs, persists their causal event
graphs, and explains failures from local SQLite. PostgreSQL, external model
providers, and API keys are optional.

## Prerequisites

- Python 3.11 or newer
- `uv`

## Install (PyPI consumer, no clone needed)

You need **both** packages for live OpenCode capture — either one alone
is not enough:

- `agent-casuality` (PyPI): SDK, CLI, `casuality-opencode-ingest` receiver,
  and `casuality-explorer`. Without it there is nowhere to persist or view
  traces.
- `@psionic-labs/opencode-agent-casuality` (npm): OpenCode plugin,
  telemetry capture only. Without it nothing observes the session.

```powershell
pip install agent-casuality
# or: uv add agent-casuality
opencode plugin add @psionic-labs/opencode-agent-casuality
```

Consumer flow: start the receiver → run OpenCode → launch the Visual DAG:

```powershell
casuality-opencode-ingest --db .casuality/opencode.db
opencode run "Inspect the repository, make a small testable change, and run pytest"
casuality-explorer --db .casuality/opencode.db
```

Then open <http://127.0.0.1:8766>. See [docs/opencode.md](docs/opencode.md)
for the full plugin options and [docs/reference.md](docs/reference.md) for
the explorer API.

## Single-run capture (isolated db file, port `8797`)

One SQLite file per task keeps traces separate (`.casuality/single-run.db`
below is just an example — any path works). This is the minimal
reproducible loop (same commands as the unified README):

```powershell
# Terminal 1: receiver (PyPI install; source checkout: uv run casuality-opencode-ingest ...)
casuality-opencode-ingest --db .casuality/single-run.db

# Terminal 2: one instrumented agent task (plugin posts automatically)
opencode run "Run the existing tests before editing. Diagnose and fix the bug in discount.py so both tests pass. Do not modify the tests. Rerun the tests and summarize the change."
```

Optional AI explanations for the project (needs `httpx` + `OPENROUTER_API_KEY`):

```powershell
uv add "agent-casuality[explain]"
# pip equivalent: pip install "agent-casuality[explain]"
```

```powershell
# Terminal 3: explorer on the same file, alternate port to avoid clashing with :8766
casuality-explorer --db .casuality/single-run.db --port 8797
# Source checkout equivalent:
uv run python -m explorer.server --db .casuality/single-run.db --port 8797
```

Then open <http://127.0.0.1:8797>. Use a fresh `--db` path per task for
one-trace-per-file (any filename works).

## Install the source checkout

From the repository root:

```powershell
uv sync
```

This installs the project in editable mode and provides the `casuality` and
`agent-casuality` commands.

## Run the end-to-end demo

```powershell
uv run python examples/customer_approval.py
```

The command is self-contained and does not require PostgreSQL, an API key, or
network access. It performs a complete local flow:

1. `casuality.init()` creates `.casuality/example.db`.
2. Two decorated agents return eligibility and risk values.
3. A merge decision records semantic ports and canonical baselines.
4. A terminal `agent_finish` event marks the incorrect approval as a failure.
5. SQLite is closed.
6. A fresh `casuality` CLI process reloads the evaluator module, reopens the
   database, and renders the offline evidence package.

The key result is:

```text
Diagnosis: The terminal event is marked 'failure' because the decision returned 'approved' with customer_status='eligible' and risk_score=0.2.
Evidence:
- Minimal tested chain: customer_status + risk_score -> decision -> terminal failure (4 events).
- Recorded inputs were customer_status='eligible' and risk_score=0.2; their canonical baselines are 'ineligible' and 0.8.
- The reported interaction between customer_status and risk_score is 1.0.
- The structural slice contains 8 events; replay reduced it to the smaller tested subset above.
Limitations: the evidence does not establish why the upstream tools produced these values.
```

The demo also prints the run ID, failure event ID, database path, raw-evidence
command, and optional LLM command. Repeated runs append to the same ignored
database without linking events across `run_id` values.

## Inspect the persisted run

Use the failure event ID printed by the demo:

```powershell
uv run casuality --load-module examples.customer_approval `
    --db .casuality/example.db slice <failure-event-id>

uv run casuality --load-module examples.customer_approval `
    --db .casuality/example.db explain <failure-event-id> --no-llm
```

`--load-module` is required for persisted custom decisions because the decision
evaluator is application code and is not serialized into the event payload.

Use `--raw-evidence` when the complete JSON package is needed:

```powershell
uv run casuality --load-module examples.customer_approval `
    --db .casuality/example.db explain <failure-event-id> `
    --raw-evidence --no-llm
```

## Use the deterministic fixture

The fixture is a separate, readable control case:

```powershell
uv run casuality --fixture fixture/fixture.json explain A4 --no-llm
```

Useful fixture commands include:

```powershell
uv run casuality --fixture fixture/fixture.json agents
uv run casuality --fixture fixture/fixture.json slice A4
uv run casuality --fixture fixture/fixture.json why A4
uv run casuality --fixture fixture/fixture.json reconstruct B 4
uv run casuality --fixture fixture/fixture.json provenance A3.output.approve
uv run casuality --fixture fixture/fixture.json replay dec_customer_approval_A3 customer_status=ineligible
uv run casuality --fixture fixture/fixture.json interaction dec_customer_approval_A3
uv run casuality --fixture fixture/fixture.json minimize A4
```

The fixture's ground-truth annotations make it useful for tests and
presentations. It is not a substitute for demonstrating live capture and
cross-process persistence.

## Understand the convenience API

The complete example is `examples/customer_approval.py`. Its local flow uses:

- `casuality.init(path)` to create a SQLite runtime;
- `@casuality.agent(role=...)` to capture agent function calls and results; and
- `@casuality.merge_decision(...)` to create decision ports, baselines, a
  decision contract, and an evaluator registration.

For merge inputs, the convenience API looks for the most recent matching
`tool_result` in the active run. This is appropriate for the controlled demo but
is value-based inference, not explicit field provenance. Use `sdk/events.py`,
`sdk/tools.py`, and `core/decision.py` directly when causal parents, clocks,
field sources, or storage behavior must be controlled explicitly.

## CLI backends

The CLI supports these backend selectors:

- `--fixture PATH`: load a JSON fixture without a database;
- `--db PATH`: read a local SQLite database; or
- no selector with `DATABASE_URL` set: read PostgreSQL.

Without an explicit selector or `DATABASE_URL`, the CLI reads
`.casuality/events.db`. It does not create application events; Python capture
code writes the database.

The `agents` command currently supports only the fixture backend because SQLite
does not persist the agent metadata currently needed by that command.

## Optional OpenRouter explanation

Install the optional HTTP dependency and set a key only if you want a
model-generated explanation (default model
`nvidia/nemotron-3-ultra-550b-a55b:free`; override with `OPENROUTER_MODEL`):

```powershell
uv sync --extra explain
# PyPI / uv consumers instead:
# pip install "agent-casuality[explain]"
# uv add "agent-casuality[explain]"
$env:OPENROUTER_API_KEY = "your-key"
uv run casuality --fixture fixture/fixture.json explain A4 `
    --model "your/model"
```

The offline summary remains available with `--no-llm`. If the model call fails or
returns text that violates the output contract, the CLI falls back to the
grounded offline summary.

## Optional PostgreSQL setup

Install the PostgreSQL extra:

```powershell
uv sync --extra postgres
```

Create a local `.env` file for integration testing:

```dotenv
DATABASE_URL=postgresql://user:password@host/database?sslmode=require
```

Do not commit `.env`. `DATABASE_URL` must point to a dedicated testing database
because integration tests create schema objects and leave test rows behind.

Run the marked PostgreSQL integration tests with:

```powershell
uv run --env-file .env pytest `
    tests/test_postgres_integration.py tests/test_phase2.py `
    -m integration -q
```

Run the full suite with PostgreSQL enabled only when a test database is
intentionally available:

```powershell
uv run --env-file .env pytest -q
```

Detailed schema and query verification is in
[docs/verification-archive.md](docs/verification-archive.md). Those SQL
queries work in PostgreSQL generally; a hosted PostgreSQL SQL editor is
optional.

## Run all checks

Run the standard local gates directly:

```powershell
uv run pytest -q
uv run ruff check .
uv run ty check .
```

PowerShell users can run the same commands with:

```powershell
.\scripts\check.ps1
```

If script execution is blocked:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1
```

`scripts/check.ps1` loads `.env` before testing. If `DATABASE_URL` is present,
database-aware tests may run against that configured database.

## OpenCode runtime adapter testing

### 1. Automated adapter tests

Run the unit, privacy redaction, fail-open, timestamp round-trip, and simulated end-to-end session tests:

```powershell
uv run pytest tests/test_opencode_adapter.py -v
```

### 2. Live OpenCode runtime smoke test

OpenCode `1.19.0` (V1 `{ id, server }` plugin contract, supported since
`1.18.29`) loads the project plugin from
`.opencode/plugins/agent-casuality.ts`. Start the Agent-Casuality receiver in
one terminal:

```powershell
uv run casuality-opencode-ingest --db .casuality/opencode.db
```

In a second terminal, from this repository, run a real OpenCode session:

```powershell
$env:CASUALITY_OPENCODE_INGEST_URL = "http://127.0.0.1:8765/v1/opencode/events"
opencode run "Inspect the repository, make a small testable change, and run pytest"
```

The plugin uses OpenCode's V1 `event` hook and tool/permission/message hooks;
it does not scrape terminal output. Verify captured events and causal DAG in
`.casuality/opencode.db`:

```powershell
# Inspect captured events, kinds, and resource URIs
uv run python -c "from storage.sqlite import SQLiteEventStore; store = SQLiteEventStore('.casuality/opencode.db'); print([(e.event_type, e.payload.get('opencode_kind'), e.payload.get('resource_uri')) for e in store.events()])"

# Verify causal graph ancestor traversal
uv run python -c "from storage.sqlite import SQLiteEventStore; store = SQLiteEventStore('.casuality/opencode.db'); latest = store.events()[-1]; print('Causal ancestors count:', len(store.ancestors(latest.id)))"
```

Telemetry delivery is fail-open and quiet by default (no console warnings
unless `CASUALITY_OPENCODE_LOG_TELEMETRY_FAILURES=1`); envelopes are sent in
batches of up to 25. See [docs/opencode.md](docs/opencode.md) for the full
plugin options. The smoke test is not part of CI.

## Current boundaries

- Merge replay evaluates a registered decision function in recorded-output mode;
  downstream side effects are not re-executed.
- Exact interaction enumeration supports up to four decision ports.
- Bootstrap sign proportions are descriptive and are not p-values.
- Structural slices express declared dependency, not proven influence.
- Privacy redaction is opt-in, best-effort, and focused on configured top-level
  payload keys.
- Resource-version tracking requires an explicit resource URI; it does not
  discover arbitrary database or filesystem reads automatically.
- The high-level local API does not yet record the fixture's exact field-level
  provenance chain.
- The Visual DAG Explorer (`casuality-explorer`, default
  <http://127.0.0.1:8766>; source checkout: `uv run python -m explorer.server`) is read-only over recorded causal edges; its
  optional *Generate AI analysis* calls OpenRouter only on click (default
  model `nvidia/nemotron-3-ultra-550b-a55b:free`, override with
  `OPENROUTER_MODEL`).
