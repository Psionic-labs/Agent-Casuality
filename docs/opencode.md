# OpenCode integration

Capture a real coding-agent session live:

```text
real OpenCode execution → captured events → causal analysis → diagnosis
```

Plugin: [`.opencode/plugins/agent-casuality.ts`](../.opencode/plugins/agent-casuality.ts)
(global `event` hook plus tool, permission, command, and chat hooks).
Test: [`tests/test_opencode_adapter.py`](../tests/test_opencode_adapter.py).

## Run it

```powershell
# Terminal 1: receiver
uv run casuality-opencode-ingest --db .casuality/opencode.db
# Terminal 2: agent (plugin posts automatically)
opencode run "Read RESEARCH.md, implement sort_items in task.py as recommended, run the test script."
```

Representative committed result (`stale_research`, OpenCode `1.19.0`,
`deepseek/deepseek-v4-flash`):

```text
Status: completed (exit 0), events: 331, capture coverage: 1.0, diagnosis: scored
```

Full output: `benchmark/results/opencode/opencode.md`. No video artifact ships
with this release.

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

Optional token (sent as a bearer header):

```powershell
$env:CASUALITY_OPENCODE_INGEST_URL = "http://127.0.0.1:8765/v1/opencode/events"
$env:CASUALITY_OPENCODE_INGEST_TOKEN = "your-token"
uv run casuality-opencode-ingest --db .casuality/opencode.db
```

## Privacy

Secret keys/values are redacted to `[REDACTED]` before storage. Redaction is
opt-in and best-effort.

## Fail-open behavior

- The plugin buffers at most 256 envelopes, retries 3 times, and drops
  telemetry rather than interrupting OpenCode. Queue overflows and exhausted
  retries are counted in `telemetryStats` (`droppedQueueOverflow`,
  `droppedDeliveryFailed`, `rejectedByReceiver`) and emitted via
  `console.warn`; an HTTP 2xx with an explicit zero `persisted`/`accepted`
  count is retried, not treated as delivered.
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
