# @psionic-labs/opencode-agent-casuality

OpenCode plugin that streams Agent-Casuality telemetry events to the ingest endpoint.

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

## Behavior

- Captures the global OpenCode event stream plus `tool.execute.before/after`,
  `permission.ask`, `command.execute.before`, `chat.message`, and `chat.params` hooks.
- Buffers envelopes in memory (bounded at 256, oldest dropped) and drains them
  asynchronously with up to 3 attempts and short exponential backoff.
- Fail-open: telemetry errors never interrupt OpenCode.
- Payload redaction is applied server-side by the Agent-Casuality receiver.

## Development

```sh
npm install
npm run typecheck
npm run build
npm test
```
