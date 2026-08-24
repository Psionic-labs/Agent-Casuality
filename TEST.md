# Verify Phase 1, Phase 2, and Phase 3 in PostgreSQL

Run the checks first so the database contains a fresh real run:

```powershell
uv sync
.\scripts\check.ps1
```

The PostgreSQL tests use the `DATABASE_URL` from `.env`. They create the
schema if needed and leave test rows behind, so use a dedicated Neon branch
or database.

The queries below are intended for the Neon SQL Editor. They do not modify
data. Because each test run uses generated UUIDs, the queries select the
latest run by `started_at` instead of hard-coding IDs.

## 1. Confirm the Phase 2 tables exist

Purpose: verifies that the existing Phase 1 schema and the Phase 2
`snapshots` table were created.

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('runs', 'agents', 'events', 'snapshots')
ORDER BY table_name;
```

Expected result: four rows: `agents`, `events`, `runs`, and `snapshots`.

## 2. Inspect the required column types

Purpose: confirms that IDs use UUIDs, causal parents remain a PostgreSQL UUID
array, event payloads use JSONB, and snapshot state uses JSONB.

```sql
SELECT table_name, column_name, udt_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('runs', 'agents', 'events', 'snapshots')
ORDER BY table_name, ordinal_position;
```

Expected result: the required Phase 2 columns are present. In particular:

- `events.id`, `events.run_id`, `events.agent_id` are `uuid`;
- `events.causal_parent_ids` is `_uuid` (PostgreSQL’s `uuid[]` type);
- `events.payload` and `snapshots.state` are `jsonb`;
- `snapshots.state_hash` is `text`.

## 3. Confirm indexes and relationships

Purpose: verifies the indexes used for event ordering, run queries, snapshots,
and retry idempotency.

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname IN (
    'idx_events_agent_seq',
    'idx_events_run_seq',
    'idx_snapshots_agent_seq',
    'idx_events_idempotency'
  )
ORDER BY indexname;
```

Expected result: four rows with those index names.

Purpose: verifies the foreign keys, including
`agents.spawned_at_event_id -> events.id`.

```sql
SELECT
  kcu.table_name,
  kcu.column_name,
  ccu.table_name AS referenced_table,
  ccu.column_name AS referenced_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
  ON tc.constraint_name = ccu.constraint_name
 AND tc.table_schema = ccu.table_schema
WHERE tc.table_schema = 'public'
  AND tc.constraint_type = 'FOREIGN KEY'
ORDER BY kcu.table_name, kcu.column_name;
```

Expected result includes these relationships:

- `agents.run_id -> runs.id`;
- `agents.parent_agent_id -> agents.id`;
- `agents.spawned_at_event_id -> events.id`;
- `events.run_id -> runs.id`;
- `events.agent_id -> agents.id`;
- `snapshots.run_id -> runs.id`;
- `snapshots.agent_id -> agents.id`.

## 4. Find the latest test runs

Purpose: identifies the rows created by the Phase 1 and Phase 2 integration
tests without assuming fixed UUIDs.

```sql
SELECT
  r.id AS run_id,
  r.name,
  r.started_at,
  COUNT(DISTINCT a.id) AS agents,
  COUNT(DISTINCT e.id) AS events
FROM runs r
LEFT JOIN agents a ON a.run_id = r.id
LEFT JOIN events e ON e.run_id = r.id
WHERE r.name IN ('phase-1', 'phase-2', 'sequence')
GROUP BY r.id, r.name, r.started_at
ORDER BY r.started_at DESC;
```

Expected result for a fresh complete run:

- `phase-1`: 3 agents and 7 events;
- `phase-2`: 3 agents and at least 9 events;
- `sequence`: 1 agent and 2 events.

The Phase 2 test also creates a shared-ancestor branch, so its event count is
higher than the minimum nine.

## 5. Confirm planner-to-worker relationships

Purpose: verifies that the planner owns both workers and each worker stores
the exact event that spawned it in `spawned_at_event_id`.

```sql
WITH latest_phase2 AS (
  SELECT id
  FROM runs
  WHERE name = 'phase-2'
  ORDER BY started_at DESC
  LIMIT 1
)
SELECT
  a.id,
  a.role,
  a.parent_agent_id,
  a.spawned_at_event_id,
  spawn.event_type AS spawned_event_type,
  a.lamport_offset
FROM agents a
JOIN latest_phase2 r ON r.id = a.run_id
LEFT JOIN events spawn ON spawn.id = a.spawned_at_event_id
ORDER BY a.role, a.created_at;
```

Expected result: one `planner`, one `researcher`, and one `coder`.
The planner has null parent/spawn fields. Both workers reference the planner,
have non-null `spawned_at_event_id`, and their referenced event type is
`agent_spawn`.

## 6. Inspect the real event branches

Purpose: confirms that the worker branches contain model, tool-call, and
tool-result events, and that the result points to its tool call through
`causal_parent_ids`.

```sql
WITH latest_phase2 AS (
  SELECT id
  FROM runs
  WHERE name = 'phase-2'
  ORDER BY started_at DESC
  LIMIT 1
)
SELECT
  a.role,
  e.id,
  e.logical_seq,
  e.event_type,
  e.causal_parent_ids,
  e.payload
FROM events e
JOIN agents a ON a.id = e.agent_id
JOIN latest_phase2 r ON r.id = e.run_id
ORDER BY a.role, e.logical_seq, e.id;
```

Expected result: the `researcher` and `coder` branches each contain
`model_call -> tool_call -> tool_result`. The worker model calls reference
their spawn events, tool calls reference the model calls, and tool results
reference the tool calls. The planner contains two spawn events and a merge
event.

## 7. Confirm the planner merge has both worker results as parents

Purpose: verifies explicit cross-agent causal assignment and multiple parent
support. This checks actual parent rows rather than just counting array items.

```sql
WITH latest_phase2 AS (
  SELECT id
  FROM runs
  WHERE name = 'phase-2'
  ORDER BY started_at DESC
  LIMIT 1
), merge_event AS (
  SELECT e.*
  FROM events e
  JOIN latest_phase2 r ON r.id = e.run_id
  JOIN agents a ON a.id = e.agent_id
  WHERE a.role = 'planner'
    AND e.event_type = 'model_call'
  ORDER BY e.logical_seq DESC
  LIMIT 1
)
SELECT
  m.id AS merge_event_id,
  m.logical_seq AS merge_logical_seq,
  p.id AS parent_event_id,
  pa.role AS parent_role,
  p.event_type AS parent_event_type,
  p.logical_seq AS parent_logical_seq
FROM merge_event m
CROSS JOIN LATERAL unnest(m.causal_parent_ids) AS parents(parent_id)
JOIN events p ON p.id = parents.parent_id
JOIN agents pa ON pa.id = p.agent_id
ORDER BY pa.role;
```

Expected result: two rows for one merge event. The parent roles are
`researcher` and `coder`, and both parent event types are `tool_result`.
The merge’s `causal_parent_ids` are the real worker result IDs.

## 8. Query all ancestors of the merge event

Purpose: runs the production PostgreSQL recursive query. It must include the
merge event itself and every event reachable through its causal parents.

```sql
WITH RECURSIVE latest_phase2 AS (
  SELECT id
  FROM runs
  WHERE name = 'phase-2'
  ORDER BY started_at DESC
  LIMIT 1
), target AS (
  SELECT e.id, e.agent_id, e.logical_seq, e.causal_parent_ids
  FROM events e
  JOIN latest_phase2 r ON r.id = e.run_id
  JOIN agents a ON a.id = e.agent_id
  WHERE a.role = 'planner'
    AND e.event_type = 'model_call'
  ORDER BY e.logical_seq DESC
  LIMIT 1
), ancestors AS (
  SELECT id, agent_id, logical_seq, causal_parent_ids
  FROM target

  UNION

  SELECT e.id, e.agent_id, e.logical_seq, e.causal_parent_ids
  FROM events e
  JOIN ancestors a ON e.id = ANY(a.causal_parent_ids)
)
SELECT
  a.id,
  agents.role,
  a.logical_seq,
  a.causal_parent_ids
FROM ancestors a
JOIN agents ON agents.id = a.agent_id
ORDER BY a.logical_seq, a.id;
```

Expected result: the merge event, both worker result branches, and the spawn
events reached through the worker model-call parents. No unrelated `sequence`
run or other agent appears.

## 9. Confirm shared ancestors are deduplicated

Purpose: verifies that two reachable paths to the same event return that event
once, not once per path.

```sql
WITH RECURSIVE latest_phase2 AS (
  SELECT id
  FROM runs
  WHERE name = 'phase-2'
  ORDER BY started_at DESC
  LIMIT 1
), target AS (
  SELECT e.id, e.causal_parent_ids
  FROM events e
  JOIN latest_phase2 r ON r.id = e.run_id
  WHERE e.payload->>'shared_merge' = 'true'
  LIMIT 1
), ancestors AS (
  SELECT id, causal_parent_ids FROM target
  UNION
  SELECT e.id, e.causal_parent_ids
  FROM events e
  JOIN ancestors a ON e.id = ANY(a.causal_parent_ids)
)
SELECT
  COUNT(*) AS ancestor_count,
  COUNT(DISTINCT id) AS distinct_ancestor_count
FROM ancestors;
```

Expected result: one row with `ancestor_count = 4` and
`distinct_ancestor_count = 4` for the shared-ancestor branch
(`shared_merge`, `left`, `right`, and the shared `root`). The equal counts
confirm that `UNION` prevented the shared root from appearing twice.

## 10. Confirm every causal parent exists

Purpose: checks that every stored causal-parent UUID resolves to an event.

```sql
SELECT
  child.id AS child_event_id,
  parent_id,
  child.causal_parent_ids
FROM events child
CROSS JOIN LATERAL unnest(child.causal_parent_ids) AS parents(parent_id)
LEFT JOIN events parent ON parent.id = parents.parent_id
WHERE parent.id IS NULL;
```

Expected result: no rows. Any row indicates a dangling causal dependency.

## 11. Confirm no duplicate logical sequences within an agent

Purpose: checks the critical ordering invariant. Logical sequences may match
across different agents, but cannot collide within one agent.

```sql
SELECT agent_id, logical_seq, COUNT(*)
FROM events
GROUP BY agent_id, logical_seq
HAVING COUNT(*) > 1;
```

Expected result: no rows.

Logical sequence numbers are ordering values, not causal edges. Use
`causal_parent_ids` and the ancestor query for dependency relationships.

## 12. Confirm snapshots are only written by Phase 3

Purpose: confirms the `snapshots` table stays empty for Phase 1 and Phase 2
tests. Only the Phase 3 integration test creates snapshot rows.

```sql
SELECT COUNT(*) AS snapshots
FROM snapshots;
```

Expected result: `0` if you have run only the Phase 1 and Phase 2
integration tests. After running the Phase 3 integration test (section 13),
expect one snapshot row per captured worker agent; existing rows are not an
error.

---

# Phase 3 testing

Phase 3 adds state reconstruction (`core/reducer.py`), interval snapshots
(`core/snapshots.py`), and structural slicing with decision evidence
(`core/slicing.py`). The sections below cover every testing layer, from the
one-command script down to manual SQL verification of the snapshot rows.

## 13. Run all Phase 3 checks in one command

Purpose: runs every validation layer in order and fails loudly on the first
broken layer. This is the fastest way to confirm a checkout is healthy.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test_phase3.ps1
```

Skip the database layer when you do not want to touch PostgreSQL:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test_phase3.ps1 -SkipIntegration
```

Expected result: exit code `0` and `All Phase 3 checks passed.` The script
runs these layers in order:

| Layer | What runs | Expected |
|---|---|---|
| 1 | Phase 3 unit and property tests (sections 14) | 36 passed |
| 2 | Full unit suite, integration auto-skipped | 90 passed, 6 skipped |
| 3 | `ruff check .` and `ty check .` | clean |
| 4 | Fixture acceptance through the real CLI (section 15) | all assertions hold |
| 5 | Real PostgreSQL integration tests (section 16) | 5 passed |

Layer 5 loads `DATABASE_URL` from `.env` and retries once automatically,
because hosted Neon endpoints occasionally drop DNS. A red failure there that
disappears on rerun is connectivity, not code.

## 14. Run the Phase 3 test files individually

Purpose: isolates a failing layer without running the whole script.

```powershell
uv run pytest tests/test_reducer.py -q      # reducer + snapshot property tests
uv run pytest tests/test_slicing.py -q     # fixture contract: slice/why/deep_get
uv run pytest tests/test_cli.py -q         # CLI smoke tests
uv run pytest tests/test_postgres_integration.py -m integration -q   # real DB
```

Expected results:

- `test_reducer.py`: 23 passed. Includes the four property tests named in
  `docs/implementation-plan.md`: replaying a prefix twice is stable, an
  unrelated event does not change another agent's state, a causal parent must
  exist before being referenced, and the snapshot hash matches reconstruction.
- `test_slicing.py`: 10 passed. `structural_slice(A4)` returns exactly the
  nine fixture events, excludes agent D, prefers the recursive SQL path when
  the store provides `ancestors`, survives cyclic parents, and resolves
  decision ports against recorded payloads.
- `test_cli.py`: 3 passed.
- Integration file: 5 passed in roughly two minutes against Neon.
  Requires `DATABASE_URL` in `.env`, otherwise the tests self-skip.

## 15. Try the debugger against the fixture, no database

Purpose: exercises the real CLI end to end using `fixture.json` as the event
store. These are the same assertions layer 4 of the script makes.

```powershell
uv run python -m cli.main --fixture fixture/fixture.json agents
uv run python -m cli.main --fixture fixture/fixture.json slice A4
uv run python -m cli.main --fixture fixture/fixture.json why A3
uv run python -m cli.main --fixture fixture/fixture.json reconstruct B 4
```

Expected results:

- `agents` lists `A planner`, `B researcher`, `C coder`,
  `D background_monitor`.
- `slice A4` prints `Structural slice of A4: 9 events (python_bfs)` followed
  by `A1, B1, C1, B2, C2, B3, C3, A3, A4`. No `D*` event appears, matching
  the fixture's ground-truth `structural_slice`.
- `why A3` prints JSON with `contract_present: false` (the plain fixture
  carries no embedded contract) and `declared_inputs` naming `B3` from agent
  B and `C3` from agent C, plus the note that this is structural evidence
  only, not proven influence.
- `reconstruct B 4` prints `status=active`, a SHA-256 state hash, and JSON
  where `tool_outputs.B2` equals `{"customer_status":"eligible"}` — proof the
  recorded tool result folded into reconstructed state.

Against a live run, swap the backend for PostgreSQL:

```powershell
uv run python -m cli.main slice <event-uuid>
```

## 16. Confirm the Phase 3 integration test wrote valid snapshots

Purpose: verifies, directly in SQL, what the integration test claims: one
interval snapshot per worker at `logical_seq = 32` (the first multiple of
32 reached), a full 64-hex-character hash, and a state blob holding the 32
memory keys written before that point.

Run the integration tests first so fresh rows exist:

```powershell
Get-Content .env | ForEach-Object {
  $p = $_ -split '=', 2
  if ($p.Length -eq 2) { [Environment]::SetEnvironmentVariable($p[0], $p[1], 'Process') }
}
uv run pytest tests/test_postgres_integration.py -m integration -q
```

Then inspect in the Neon SQL Editor:

```sql
WITH latest_phase3 AS (
  SELECT id
  FROM runs
  WHERE name = 'phase-3'
  ORDER BY started_at DESC
  LIMIT 1
)
SELECT
  a.role,
  s.logical_seq,
  s.state_hash ~ '^[0-9a-f]{64}$' AS hash_is_sha256_hex,
  (SELECT COUNT(*)
   FROM jsonb_object_keys(s.state->'memory') AS k) AS memory_keys,
  s.state->>'status' AS status,
  (SELECT COUNT(*)
   FROM jsonb_object_keys(s.state->'open_tools') AS t) AS open_tools_count
FROM snapshots s
JOIN latest_phase3 r ON r.id = s.run_id
JOIN agents a ON a.id = s.agent_id
ORDER BY s.created_at DESC;
```

Expected result: one row for the `worker` role with `logical_seq = 32`,
`hash_is_sha256_hex = true`, `memory_keys = 32`, `status = active`, and
`open_tools_count = 0`. The unrelated `outsider` agent has no snapshot row:
it never reaches the 32-event interval boundary, exactly as the policy
prescribes.

## 17. Verify reconstruction agrees with the stored snapshot

Purpose: proves against live PostgreSQL rows that the reducer's integrity
rule from thesis section 30.3 holds end to end. The maintained integration
test performs exactly this check, so run it rather than hand-writing SQL:

```powershell
uv run pytest "tests/test_postgres_integration.py::test_phase3_reconstruction_snapshots_and_sql_slice_against_postgres" -m integration -v
```

Expected result: `1 passed`. The test verifies three things against real
rows:

- the snapshot-shortcut replay equals a from-scratch replay byte for byte
  (`canonical_json` equality);
- `verify_snapshot` accepts an untampered snapshot at its own sequence;
- the recursive SQL slice of the merge event contains its two declared
  parents while excluding the unrelated outsider event.
