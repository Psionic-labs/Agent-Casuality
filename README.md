# Agent-Casuality
Causal Debugging for Branching Multi-Agent Systems

## Current implementation

Phase 1 captures model calls, tool calls/results, memory operations, and agent
spawns. Phase 2 stores the resulting agent/event graph in PostgreSQL, supports
explicit cross-agent merge parents, and queries event ancestors.

The Phase 2 graph uses `causal_parent_ids` as the source of dependency edges.
`logical_seq` is only the per-agent logical ordering value; it is not inferred
as a causal relationship. State reconstruction, snapshots, slicing, replay,
and provenance belong to later phases and are not implemented yet.

## Install and run

```powershell
uv sync
.\scripts\check.ps1
```

For the real PostgreSQL scenario, put `DATABASE_URL` in a local `.env` file
and use a dedicated Neon branch or test database:

```powershell
uv run --env-file .env pytest tests/test_postgres_integration.py tests/test_phase2.py -m integration -q
```

The integration tests create the schema through the existing PostgreSQL store,
capture the planner/worker scenario, assign the explicit merge parents, and
query `ancestors()` against PostgreSQL. See [GETTING_STARTED.md](GETTING_STARTED.md)
for setup and [TEST.md](TEST.md) for Neon SQL Editor verification queries.

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
