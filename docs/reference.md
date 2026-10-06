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

## Optional services

```powershell
uv sync --extra explain
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
