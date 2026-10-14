# OpenCode integration

> Live capture needs **both** packages: `agent-casuality` (PyPI — receiver,
> explorer, CLI) **and** `@psionic-labs/opencode-agent-casuality` (npm —
> plugin, telemetry only). The npm plugin alone has nowhere to persist
> traces; the PyPI package alone cannot observe an OpenCode session.

Capture a real coding-agent session live:

```text
real OpenCode execution → captured events → causal analysis → diagnosis
```

Plugin: [`.opencode/plugins/agent-casuality.ts`](../.opencode/plugins/agent-casuality.ts)
(global `event` hook plus tool, permission, command, and chat hooks).
Test: [`tests/test_opencode_adapter.py`](../tests/test_opencode_adapter.py).

## Run it

```powershell
# Terminal 1: receiver (PyPI: casuality-opencode-ingest ...; source: uv run casuality-opencode-ingest ...)
casuality-opencode-ingest --db .casuality/opencode.db
# Terminal 2: agent (plugin posts automatically)
opencode run "Read RESEARCH.md, implement sort_items in task.py as recommended, run the test script."
```

## Single-run capture (example db file, port `8797`)

Isolated one-task loop — same commands as the unified README. One SQLite
file per task (`.casuality/single-run.db` is just an example — any path
works), alternate explorer port so it never clashes with `:8766`:

```powershell
# Terminal 1: receiver
uv run casuality-opencode-ingest --db .casuality/single-run.db
# (PyPI install: casuality-opencode-ingest --db .casuality/single-run.db)

# Terminal 2: instrumented fix task (plugin posts automatically)
opencode run "Run the existing tests before editing. Diagnose and fix the bug in discount.py so both tests pass. Do not modify the tests. Rerun the tests and summarize the change."

# Optional: AI explanations for this project
uv add "agent-casuality[explain]"
# (pip equivalent: pip install "agent-casuality[explain]")

# Terminal 3: explorer on the same file
uv run python -m explorer.server --db .casuality/single-run.db --port 8797
# (PyPI install: casuality-explorer --db .casuality/single-run.db --port 8797)
```

Then open <http://127.0.0.1:8797>. Use a fresh `--db` path per task for
one-trace-per-file (any filename works).

Representative committed result (`stale_research`, OpenCode `1.19.0`):

```text
Status: completed (exit 0), events: 331, capture coverage: 1.0, diagnosis: scored
```

(The 2026-10-11 rerun used `deepseek/deepseek-v4-flash` as the OpenCode model;
that model has since been retired from OpenRouter's free tier. The AI-explanation
default is now `nvidia/nemotron-3-ultra-550b-a55b:free`.)

Full output: `benchmark/results/opencode/opencode.md`. No video artifact ships
with this release.

## View a fresh trace in the Visual DAG Explorer

No extra setup: the explorer ships in the Python distribution and serves
its bundled frontend itself. No API key is needed (only the optional AI
interpretation uses one). No repository clone is needed for the PyPI path.

```powershell
# PyPI consumer flow
pip install agent-casuality
casuality-opencode-ingest --db .casuality/opencode.db
# ... run an OpenCode session (plugin posts automatically) ...
casuality-explorer --db .casuality/opencode.db

# Source checkout flow
# 1. Capture a fresh trace (one benchmark task is enough)
uv run casuality-benchmark opencode --task shared_state_contamination --timeout 300

# 2. Serve the resulting trace in the explorer
uv run python -m explorer.server --db benchmark/results/opencode/runs/<run-id>/trace.db
# (installed equivalent: casuality-explorer --db <path>)

# 3. Open http://127.0.0.1:8766 — graph, timeline, event inspector, and
#    analysis tabs load from the trace's recorded causal edges.
```

The screenshot in [README](../README.md) (`docs/screenshots/explorer-shared-state-fresh.png`)
was produced exactly this way from a `shared_state_contamination` run.

## What the benchmark numbers mean

Three claims are kept strictly separate:

- **Event capture** (micro/macro-average `1.0` on the 2026-10-11 rerun):
  minimum expected event-class coverage — every event class OpenCode
  exposes was captured. This says nothing about causality.
- **Causal ancestry** (cause recall mean `0.3`): structural-slice recall
  under explicit-evidence edges only (tool `callID` pairing, resource
  read-after-write, declared `parent_event_id`). Arrival order is never
  inferred as causality, so slices stay small and honest.
- **Genuine causal interaction** (`unsupported`, joint ancestry `0.0`):
  live traces offer no counterfactual intervention, so branch co-ancestry
  is reported as joint ancestry, never as a causal interaction index.

## Loader compatibility

The plugin default-exports the V1 server-plugin module
`{ id: "agent-casuality", server: AgentCasualityPlugin }`, supported since
OpenCode `1.18.29`. A bare-function default export falls through to the
legacy loader, where any non-function named export (e.g. `telemetryStats`)
silently disables the whole plugin on OpenCode `>= 1.19`
(`Plugin export is not a function`, visible only in `opencode.log`).

- Fast regression test: `test/loader-compat.test.mjs` (runs in `npm test`)
  pins the V1 default-export contract.
- Actual-loading matrix: `uv run python scripts/check-opencode-plugin-compat.py`
  runs a trivial prompt under real binaries and asserts events are ingested
  with no loader rejection. Verified 2026-10-11: `1.19.0` (83 events),
  `1.18.34` (86 events), 0 receiver errors on both.

## Ingest endpoint

```text
POST http://127.0.0.1:8765/v1/opencode/events
```

Plugin options (all resolved per request, so env changes apply without
reloading the plugin):

| Environment variable | Default | Description |
| --- | --- | --- |
| `CASUALITY_OPENCODE_INGEST_URL` | `http://127.0.0.1:8765/v1/opencode/events` | Ingest endpoint |
| `CASUALITY_OPENCODE_INGEST_TOKEN` | _(unset)_ | Sent as `Authorization: Bearer <token>` |
| `CASUALITY_OPENCODE_INGEST_TIMEOUT_MS` | `5000` | Per-request timeout in ms |
| `CASUALITY_OPENCODE_BATCH_MAX` | `25` | Max envelopes per POST (singletons stay single objects) |
| `CASUALITY_OPENCODE_LOG_TELEMETRY_FAILURES` | _(unset)_ | Set to `1`/`true` to enable delivery warnings |

```powershell
$env:CASUALITY_OPENCODE_INGEST_URL = "http://127.0.0.1:8765/v1/opencode/events"
$env:CASUALITY_OPENCODE_INGEST_TOKEN = "your-token"
uv run casuality-opencode-ingest --db .casuality/opencode.db
```

## Privacy

Secret keys/values are redacted to `[REDACTED]` before storage. Redaction is
opt-in and best-effort.

## Fail-open behavior

- The plugin buffers at most 256 envelopes (oldest dropped on overflow),
  sends them in batches (up to `CASUALITY_OPENCODE_BATCH_MAX`, default 25
  per POST; singletons stay single objects for backward compatibility),
  retries each batch 3 times with 200ms/400ms backoff, and drops telemetry
  rather than interrupting OpenCode. Queue overflows and exhausted retries
  are counted in `telemetryStats` (`droppedQueueOverflow`,
  `droppedDeliveryFailed`, `rejectedByReceiver`). Telemetry is quiet by
  default: delivery warnings are emitted only when
  `CASUALITY_OPENCODE_LOG_TELEMETRY_FAILURES=1`/`true`, rate-limited, with
  the first one naming the endpoint plus the receiver start command. An
  HTTP 2xx with an explicit short `persisted`/`accepted` count (fewer than
  the batch size) is retried, not treated as delivered; bodies without
  counts (e.g. plain 200 `{}`) are treated as delivered for compatibility.
- The receiver answers `400` on malformed input and `202` with
  `received`/`normalized`/`persisted` counts (`accepted` aliases `persisted`)
  otherwise, so senders never mistake receipt for persistence. Only durably
  stored events count as persisted.
- `file.edited` and watcher events carry no session ID in the OpenCode SDK and
  are preserved under `unknown` with `session_unassociated: true`; session IDs
  are never invented.
- Causal edges require explicit evidence (`parent_event_id`, tool `callID`
  linkage, or resource read-after-write). Arrival order is preserved by
  `logical_seq`/`wall_time`, never inferred as causality.
