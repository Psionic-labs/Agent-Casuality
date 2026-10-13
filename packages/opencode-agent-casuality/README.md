# @psionic-labs/opencode-agent-casuality

OpenCode plugin that records your coding sessions as causal telemetry, so
they can later be replayed, sliced, and explained with Agent-Casuality.

Scope: telemetry capture only. The Visual DAG Explorer is not part of this
package; it ships with the `agent-casuality` Python distribution.

## How it fits together

1. This plugin observes your OpenCode session (events + tool hooks) and
   POSTs telemetry envelopes to a local ingest endpoint.
2. The Agent-Casuality receiver (`casuality-opencode-ingest`, from the
   Python distribution) translates envelopes into the canonical event
   model and persists them to SQLite.
3. You inspect the captured trace with the CLI (`slice`, `provenance`,
   `explain`) or the Visual DAG Explorer.

```text
OpenCode session → plugin (this package) → :8765/v1/opencode/events
      → receiver → .casuality/opencode.db → explorer / CLI
```

## Prerequisites

- OpenCode 1.19+ (uses the V1 `{ id, server }` plugin export).
- The `agent-casuality` Python distribution installed where the receiver
  will run (`uv` + Python 3.11+). Full setup:
  [Agent-Casuality repo](https://github.com/Psionic-labs/Agent-Casuality).

## Quickstart

Terminal 1 — start the receiver:

```sh
uv run casuality-opencode-ingest --db .casuality/opencode.db
```

Terminal 2 — register the plugin in your OpenCode config, then run a session:

```json
{
  "$schema": "https://opencode.ai/config",
  "plugin": ["@psionic-labs/opencode-agent-casuality"]
}
```

```sh
opencode run "Inspect the repository, make a small testable change, and run pytest"
```

Then inspect what was captured:

```sh
uv run python -c "
from storage.sqlite import SQLiteEventStore
store = SQLiteEventStore('.casuality/opencode.db')
events = store.events()
print(f'Total captured events: {len(events)}')
print(f'Causal ancestors of latest event: {len(store.ancestors(events[-1].id))}')
"
```

Or serve it visually:

```sh
uv run python -m explorer.server --db .casuality/opencode.db --port 8797
```

## What is captured

The plugin forwards OpenCode's global event stream (`event:*`: session
lifecycle, message updates, file edits, errors) plus six explicit hooks:

| Hook | Captured as |
| --- | --- |
| `tool.execute.before` / `tool.execute.after` | tool call / result (linked by call ID) |
| `permission.ask` | tool call awaiting approval |
| `command.execute.before` | command invocation |
| `chat.message` | chat activity |
| `chat.params` | chat parameters |

The receiver maps these onto canonical events (`run_start`,
`run_finish`, `model_call`, `tool_call`, `tool_result`, …), registers
file writes with the Resource-Version machinery, and redacts secrets
before persistence. See
[`docs/opencode.md`](https://github.com/Psionic-labs/Agent-Casuality/blob/main/docs/opencode.md)
for the full mapping.

## Configuration

| Environment variable | Default | Description |
| --- | --- | --- |
| `CASUALITY_OPENCODE_INGEST_URL` | `http://127.0.0.1:8765/v1/opencode/events` | Ingest endpoint that receives telemetry envelopes |
| `CASUALITY_OPENCODE_INGEST_TOKEN` | _(unset)_ | When set, sent as `Authorization: Bearer <token>` |
| `CASUALITY_OPENCODE_INGEST_TIMEOUT_MS` | `5000` | Per-request timeout in milliseconds |
| `CASUALITY_OPENCODE_BATCH_MAX` | `25` | Max envelopes per POST (singletons stay single objects) |
| `CASUALITY_OPENCODE_LOG_TELEMETRY_FAILURES` | _(unset)_ | Set to `1`/`true` to enable delivery warnings (quiet by default) |

Endpoint, token, timeout, and batch size resolve per request, so env
changes apply without reloading the plugin.

## Behavior

- Buffers envelopes in memory (bounded at 256, oldest dropped) and drains
  them in batches with up to 3 attempts per batch (200ms/400ms backoff).
- Fail-open: telemetry errors never interrupt OpenCode. Delivery warnings
  are opt-in (`CASUALITY_OPENCODE_LOG_TELEMETRY_FAILURES=1`),
  rate-limited; the first one names the endpoint and the receiver start
  command.
- An HTTP 2xx with a short `persisted`/`accepted` count is retried, not
  treated as delivered; bodies without counts are treated as delivered
  for compatibility.
- Payload redaction is applied server-side by the Agent-Casuality receiver.

## Troubleshooting

- **No events arriving?** The plugin is quiet by default. Set
  `CASUALITY_OPENCODE_LOG_TELEMETRY_FAILURES=1` and check whether the
  receiver is running on the configured URL.
- **Receiver not running?** Start it with
  `uv run casuality-opencode-ingest --db .casuality/opencode.db`
  (default endpoint `http://127.0.0.1:8765/v1/opencode/events`).
- **Still nothing?** Confirm the plugin loaded (it exports a V1
  server-plugin module; OpenCode < 1.19 will not load it) and that no
  firewall blocks localhost HTTP.

## Development

```sh
npm install
npm run typecheck
npm run build
npm test
```
