# Agent-Casuality
Causal Debugging for Branching Multi-Agent Systems

## Day-zero fixture

Use `uv` to run the fixture so everyone gets the same Python entrypoint:

```powershell
uv run python fixture/mock.py agents
uv run python fixture/mock.py slice A4
uv run python fixture/mock.py provenance A3.output.approve
```

The first command should list agents `A`, `B`, `C`, and `D`. The slice
command should return the nine-event structural slice for `A4`, and the
provenance command should show exact links from `A3.output.approve` back
to `B3.output.customer_status` and `C3.output.risk_score`.

## Tool result output contract

For a `tool_result` event, `payload.output` means only the actual answer
the tool returned. It should not include extra information like the tool
name, timing, debug notes, retry info, errors, or test annotations.

For example, if the search tool returns:

```json
{
  "customer_status": "eligible"
}
```

then that object is `payload.output`.

A provenance path can point inside that output, like
`B3.output.customer_status`.

If a tool returns a simple value instead of an object, like `"eligible"`
or `42`, then the whole result is addressed as `B3.output`.

In short: `payload.output` is the clean tool result, and everything else
about how the tool ran belongs somewhere else in `payload`.
