# @psionic-labs/opencode-agent-casuality

OpenCode plugin that streams Agent-Casuality telemetry events to the ingest endpoint.

Scope: telemetry capture only. The Visual DAG Explorer is not part of this
package; it ships with the `agent-casuality` Python distribution.

## Usage

Add the package to your OpenCode config:

```json
{
  "$schema": "https://opencode.ai/config",
  "plugin": ["@psionic-labs/opencode-agent-casuality"]
}
```

## Configuration

| Environment variable | Default | Description |
| --- | --- | --- |
| `CASUALITY_OPENCODE_INGEST_URL` | `http://127.0.0.1:8765/v1/opencode/events` | Ingest endpoint that receives telemetry envelopes |
| `CASUALITY_OPENCODE_INGEST_TOKEN` | _(unset)_ | When set, sent as `Authorization: Bearer <token>` |
| `CASUALITY_OPENCODE_INGEST_TIMEOUT_MS` | `5000` | Per-request timeout in milliseconds |
| `CASUALITY_OPENCODE_BATCH_MAX` | `25` | Max envelopes per POST (singletons stay single objects) |
| `CASUALITY_OPENCODE_LOG_TELEMETRY_FAILURES` | _(unset)_ | Set to `1`/`true` to enable delivery warnings (quiet by default) |

## Behavior

- Captures the global OpenCode event stream plus `tool.execute.before/after`,
  `permission.ask`, `command.execute.before`, `chat.message`, and `chat.params` hooks.
- Buffers envelopes in memory (bounded at 256, oldest dropped) and drains them
  in batches with up to 3 attempts per batch (200ms/400ms backoff). Endpoint,
  timeout, batch size, and token are resolved per request, so env changes apply
  without reloading the plugin.
- Fail-open: telemetry errors never interrupt OpenCode. Delivery warnings are
  opt-in (`CASUALITY_OPENCODE_LOG_TELEMETRY_FAILURES=1`), rate-limited; the
  first one names the endpoint and the receiver start command.
- An HTTP 2xx with a short `persisted`/`accepted` count is retried, not treated
  as delivered; bodies without counts are treated as delivered for compatibility.
- Payload redaction is applied server-side by the Agent-Casuality receiver.

## Development

```sh
npm install
npm run typecheck
npm run build
npm test
```
