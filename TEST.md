## Testing Phase 1

The commands below verify the implementation locally. The database command
also runs the real PostgreSQL integration test against the database in
`.env`.

```pwsh
uv sync
.\scripts\check.ps1
```

Expected result: tests, Ruff, and ty all pass. If `.env` contains a valid
`DATABASE_URL`, the PostgreSQL integration test runs automatically; otherwise
it is skipped.

### Check the PostgreSQL console on Neon

#### 1. Confirm captured runs, agents, and event counts

Purpose: confirms that the integration test created runs and that each run
contains the expected three agents and seven Phase 1 events. `DISTINCT` is
important because joining agents and events otherwise multiplies the count.

```sql
SELECT
  r.id AS run_id,
  r.name,
  COUNT(DISTINCT a.id) AS agents,
  COUNT(DISTINCT e.id) AS events
FROM runs r
LEFT JOIN agents a ON a.run_id = r.id
LEFT JOIN events e ON e.run_id = r.id
WHERE r.name = 'phase-1'
GROUP BY r.id, r.name
ORDER BY MAX(r.started_at) DESC;
```

Expected result: one row per test run, with `agents = 3` and `events = 7`.
If the test was run twice, two `phase-1` rows are expected.

RESULT:
```json
[{
  "run_id": "076e3473-fc4e-4c36-9441-698aa6b258e3",
  "name": "phase-1",
  "agents": 3,
  "events": 7
}, {
  "run_id": "12e5846b-26fc-4de1-b054-76a4194fd0eb",
  "name": "phase-1",
  "agents": 3,
  "events": 7
}]
```

#### 2. Confirm the planner-to-worker spawn relationships

Purpose: verifies that the planner is the parent of both workers and that
each child stores the ID of its parent `agent_spawn` event in
`spawned_at_event_id`.

```sql
SELECT
  a.id,
  a.role,
  a.parent_agent_id,
  a.spawned_at_event_id,
  a.lamport_offset
FROM agents a
JOIN runs r ON r.id = a.run_id
WHERE r.name = 'phase-1'
ORDER BY a.created_at;
```

Expected result per run:

- one `planner` with null `parent_agent_id` and `spawned_at_event_id`
- one `worker-1` and one `worker-2`
- both workers have the planner ID as `parent_agent_id`
- both workers have non-null `spawned_at_event_id`
- worker Lamport offsets match their spawn sequence numbers

RESULT:
```json
[{
  "id": "d9a13702-5452-4a19-819e-8530400760cc",
  "role": "planner",
  "parent_agent_id": null,
  "spawned_at_event_id": null,
  "lamport_offset": 0
}, {
  "id": "18e7a9a3-5c2a-4ca2-b08b-a5bdd94b5752",
  "role": "worker-1",
  "parent_agent_id": "d9a13702-5452-4a19-819e-8530400760cc",
  "spawned_at_event_id": "11de9524-9b4c-46c7-998b-b8080b163498",
  "lamport_offset": 1
}, {
  "id": "1c62667d-5555-4c55-b655-eb6196fa70fb",
  "role": "worker-2",
  "parent_agent_id": "d9a13702-5452-4a19-819e-8530400760cc",
  "spawned_at_event_id": "58d03d69-90e8-4d69-89f2-f363864d6725",
  "lamport_offset": 2
}, {
  "id": "dda7e35a-6d0c-4eec-901b-52412e8b92a1",
  "role": "planner",
  "parent_agent_id": null,
  "spawned_at_event_id": null,
  "lamport_offset": 0
}, {
  "id": "28571a75-678d-4e08-8853-5288d731f30c",
  "role": "worker-1",
  "parent_agent_id": "dda7e35a-6d0c-4eec-901b-52412e8b92a1",
  "spawned_at_event_id": "a69fbe1c-91dc-47c8-8cee-a42e691acf49",
  "lamport_offset": 1
}, {
  "id": "0a212b0a-dd31-447c-a58a-5ed063471fba",
  "role": "worker-2",
  "parent_agent_id": "dda7e35a-6d0c-4eec-901b-52412e8b92a1",
  "spawned_at_event_id": "b4b6b4aa-653b-4e9a-9065-34d9fdf09efc",
  "lamport_offset": 2
}]
```

#### 3. Inspect event types, logical sequences, and causal parents

Purpose: verifies that all expected events were persisted and that causal
relationships are represented by `causal_parent_ids`, not by wall-clock
ordering.

```sql
SELECT
  e.agent_id,
  a.role,
  e.id,
  e.logical_seq,
  e.event_type,
  e.causal_parent_ids,
  e.payload
FROM events e
JOIN agents a ON a.id = e.agent_id
JOIN runs r ON r.id = e.run_id
WHERE r.name = 'phase-1'
ORDER BY a.role, e.logical_seq;
```

Expected result per run: seven events—two `agent_spawn` events, two worker
`tool_call` events, two linked `tool_result` events, and one planner
`model_call` merge event. Each tool result should contain its tool call ID in
`causal_parent_ids`.

RESULT: 
```json
[{
  "agent_id": "d9a13702-5452-4a19-819e-8530400760cc",
  "role": "planner",
  "id": "11de9524-9b4c-46c7-998b-b8080b163498",
  "logical_seq": 1,
  "event_type": "agent_spawn",
  "causal_parent_ids": "{}",
  "payload": "{\"role\": \"worker-1\", \"child_agent_id\": \"18e7a9a3-5c2a-4ca2-b08b-a5bdd94b5752\"}"
}, {
  "agent_id": "dda7e35a-6d0c-4eec-901b-52412e8b92a1",
  "role": "planner",
  "id": "a69fbe1c-91dc-47c8-8cee-a42e691acf49",
  "logical_seq": 1,
  "event_type": "agent_spawn",
  "causal_parent_ids": "{}",
  "payload": "{\"role\": \"worker-1\", \"child_agent_id\": \"28571a75-678d-4e08-8853-5288d731f30c\"}"
}, {
  "agent_id": "d9a13702-5452-4a19-819e-8530400760cc",
  "role": "planner",
  "id": "58d03d69-90e8-4d69-89f2-f363864d6725",
  "logical_seq": 2,
  "event_type": "agent_spawn",
  "causal_parent_ids": "{}",
  "payload": "{\"role\": \"worker-2\", \"child_agent_id\": \"1c62667d-5555-4c55-b655-eb6196fa70fb\"}"
}, {
  "agent_id": "dda7e35a-6d0c-4eec-901b-52412e8b92a1",
  "role": "planner",
  "id": "b4b6b4aa-653b-4e9a-9065-34d9fdf09efc",
  "logical_seq": 2,
  "event_type": "agent_spawn",
  "causal_parent_ids": "{}",
  "payload": "{\"role\": \"worker-2\", \"child_agent_id\": \"0a212b0a-dd31-447c-a58a-5ed063471fba\"}"
}, {
  "agent_id": "d9a13702-5452-4a19-819e-8530400760cc",
  "role": "planner",
  "id": "1c9f4bd2-4d4e-4ebf-9349-dfddea6b9449",
  "logical_seq": 3,
  "event_type": "model_call",
  "causal_parent_ids": "{21a24dfa-4e6c-4762-b3f4-d302568e9023,323c4acb-b1ad-4852-9230-fd7968b3e4bf}",
  "payload": "{\"input\": [{\"role\": \"user\", \"content\": \"merge {'one': 'done'} {'two': 'done'}\"}], \"model\": \"test-model\", \"output\": {\"content\": \"merged\"}, \"latency_ms\": 0}"
}, {
  "agent_id": "dda7e35a-6d0c-4eec-901b-52412e8b92a1",
  "role": "planner",
  "id": "6c823591-b622-43a2-90fa-751f97731f0e",
  "logical_seq": 3,
  "event_type": "model_call",
  "causal_parent_ids": "{1dcae5aa-f478-4586-a0a8-9617a09aabc2,2ca4ee78-1658-4450-9fd5-59d71333893f}",
  "payload": "{\"input\": [{\"role\": \"user\", \"content\": \"merge {'one': 'done'} {'two': 'done'}\"}], \"model\": \"test-model\", \"output\": {\"content\": \"merged\"}, \"latency_ms\": 0}"
}, {
  "agent_id": "18e7a9a3-5c2a-4ca2-b08b-a5bdd94b5752",
  "role": "worker-1",
  "id": "14f289d0-ee44-40ce-86f2-8b9c99dc072c",
  "logical_seq": 2,
  "event_type": "tool_call",
  "causal_parent_ids": "{}",
  "payload": "{\"args\": [\"one\"], \"name\": \"inspect\", \"kwargs\": {}, \"invocation_id\": \"worker-one-tool\"}"
}, {
  "agent_id": "28571a75-678d-4e08-8853-5288d731f30c",
  "role": "worker-1",
  "id": "143a75a3-e121-4c64-9036-b3b8dd5f49ed",
  "logical_seq": 2,
  "event_type": "tool_call",
  "causal_parent_ids": "{}",
  "payload": "{\"args\": [\"one\"], \"name\": \"inspect\", \"kwargs\": {}, \"invocation_id\": \"worker-one-tool\"}"
}, {
  "agent_id": "18e7a9a3-5c2a-4ca2-b08b-a5bdd94b5752",
  "role": "worker-1",
  "id": "21a24dfa-4e6c-4762-b3f4-d302568e9023",
  "logical_seq": 3,
  "event_type": "tool_result",
  "causal_parent_ids": "{14f289d0-ee44-40ce-86f2-8b9c99dc072c}",
  "payload": "{\"output\": {\"one\": \"done\"}, \"invocation_id\": \"worker-one-tool\"}"
}, {
  "agent_id": "28571a75-678d-4e08-8853-5288d731f30c",
  "role": "worker-1",
  "id": "1dcae5aa-f478-4586-a0a8-9617a09aabc2",
  "logical_seq": 3,
  "event_type": "tool_result",
  "causal_parent_ids": "{143a75a3-e121-4c64-9036-b3b8dd5f49ed}",
  "payload": "{\"output\": {\"one\": \"done\"}, \"invocation_id\": \"worker-one-tool\"}"
}, {
  "agent_id": "1c62667d-5555-4c55-b655-eb6196fa70fb",
  "role": "worker-2",
  "id": "9d476664-2583-44b6-8e24-3fb652c5ee25",
  "logical_seq": 3,
  "event_type": "tool_call",
  "causal_parent_ids": "{}",
  "payload": "{\"args\": [\"two\"], \"name\": \"inspect\", \"kwargs\": {}, \"invocation_id\": \"worker-two-tool\"}"
}, {
  "agent_id": "0a212b0a-dd31-447c-a58a-5ed063471fba",
  "role": "worker-2",
  "id": "bb0ee288-e727-4301-aba0-f91ba7db864d",
  "logical_seq": 3,
  "event_type": "tool_call",
  "causal_parent_ids": "{}",
  "payload": "{\"args\": [\"two\"], \"name\": \"inspect\", \"kwargs\": {}, \"invocation_id\": \"worker-two-tool\"}"
}, {
  "agent_id": "0a212b0a-dd31-447c-a58a-5ed063471fba",
  "role": "worker-2",
  "id": "2ca4ee78-1658-4450-9fd5-59d71333893f",
  "logical_seq": 4,
  "event_type": "tool_result",
  "causal_parent_ids": "{bb0ee288-e727-4301-aba0-f91ba7db864d}",
  "payload": "{\"output\": {\"two\": \"done\"}, \"invocation_id\": \"worker-two-tool\"}"
}, {
  "agent_id": "1c62667d-5555-4c55-b655-eb6196fa70fb",
  "role": "worker-2",
  "id": "323c4acb-b1ad-4852-9230-fd7968b3e4bf",
  "logical_seq": 4,
  "event_type": "tool_result",
  "causal_parent_ids": "{9d476664-2583-44b6-8e24-3fb652c5ee25}",
  "payload": "{\"output\": {\"two\": \"done\"}, \"invocation_id\": \"worker-two-tool\"}"
}]
```

#### 4. Confirm the planner merge has both worker results as parents

Purpose: verifies the multi-agent causal merge. The planner's final model
event must preserve both worker result IDs.

```sql
SELECT
  e.id AS merge_event_id,
  e.logical_seq,
  e.causal_parent_ids,
  e.payload->>'model' AS model
FROM events e
JOIN runs r ON r.id = e.run_id
WHERE r.name = 'phase-1'
  AND e.event_type = 'model_call'
ORDER BY r.started_at DESC
LIMIT 1;
```

Expected result: one `model_call` with `model = 'test-model'`, and exactly two
IDs in `causal_parent_ids`. Those IDs should be the two worker
`tool_result` event IDs.

RESULT: 
```json
[{
  "merge_event_id": "6c823591-b622-43a2-90fa-751f97731f0e",
  "logical_seq": 3,
  "causal_parent_ids": "{1dcae5aa-f478-4586-a0a8-9617a09aabc2,2ca4ee78-1658-4450-9fd5-59d71333893f}",
  "model": "test-model"
}]
```

#### 5. Confirm no duplicate logical sequences within an agent

Purpose: checks the critical sequence invariant. Logical sequence numbers
may be equal across different agents, but must not collide for the same
agent.

```sql
SELECT agent_id, logical_seq, COUNT(*)
FROM events
GROUP BY agent_id, logical_seq
HAVING COUNT(*) > 1;
```

Expected result: no rows. Any returned row means that one agent has multiple
events with the same `logical_seq` and the capture/storage path is not safe
for that case.
