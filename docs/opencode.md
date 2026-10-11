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

Representative committed result (`stale_research`, OpenCode `1.18.34`):

```text
Status: completed (exit 0), events: 211, capture coverage: 1.0, diagnosis: scored
```

Full output: `benchmark/results/opencode/opencode.md`. No video artifact ships
with this release.

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
