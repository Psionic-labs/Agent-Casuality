# Verify Phase 1 and Phase 2 in PostgreSQL

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

## 12. Confirm Phase 2 does not write snapshots yet

Purpose: confirms the `snapshots` table exists for the schema contract while
snapshot creation remains intentionally deferred to Phase 3.

```sql
SELECT COUNT(*) AS snapshots
FROM snapshots;
```

Expected result: usually `0` for this Phase 2 test database. Existing rows are
not an error; Phase 2 does not create or reconstruct snapshots.
