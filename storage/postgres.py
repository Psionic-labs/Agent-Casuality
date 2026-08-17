"""Minimal psycopg 3 storage adapter for Phase 1.

The adapter intentionally owns only event and agent persistence. Graph
queries, reducers, snapshots, and provenance are later phases.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sdk.events import Event
from sdk.lifecycle import AgentRecord

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
DO $$ BEGIN
    CREATE TYPE event_type AS ENUM (
        'model_call', 'tool_call', 'tool_result', 'memory_read',
        'memory_write', 'context_update', 'agent_spawn', 'agent_finish',
        'agent_error', 'run_start', 'run_finish'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
CREATE TABLE IF NOT EXISTS runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text,
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS agents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES runs(id),
    parent_agent_id uuid REFERENCES agents(id),
    spawned_at_event_id uuid,
    role text,
    status text NOT NULL DEFAULT 'active',
    lamport_offset bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES runs(id),
    agent_id uuid NOT NULL REFERENCES agents(id),
    logical_seq bigint NOT NULL,
    wall_time timestamptz NOT NULL DEFAULT now(),
    event_type event_type NOT NULL,
    causal_parent_ids uuid[] NOT NULL DEFAULT '{}',
    payload jsonb NOT NULL,
    idempotency_key text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (agent_id, logical_seq)
);
ALTER TABLE agents DROP CONSTRAINT IF EXISTS fk_spawned_at_event;
ALTER TABLE agents ADD CONSTRAINT fk_spawned_at_event
    FOREIGN KEY (spawned_at_event_id) REFERENCES events(id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_idempotency
    ON events (agent_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_agent_seq ON events (agent_id, logical_seq);
"""


class PostgresEventStore:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def create_schema(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(SCHEMA_SQL)
        self.connection.commit()

    def append(self, event: Event) -> Event:
        try:
            from psycopg.types.json import Jsonb
        except ImportError as exc:  # pragma: no cover - dependency is declared by the project
            raise RuntimeError("psycopg is required for PostgresEventStore") from exc
        record = event.to_record()
        columns = (
            "id, run_id, agent_id, logical_seq, wall_time, event_type, "
            "causal_parent_ids, payload, idempotency_key"
        )
        sql = f"""
            INSERT INTO events ({columns})
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (agent_id, idempotency_key)
                WHERE idempotency_key IS NOT NULL DO NOTHING
            RETURNING id, run_id, agent_id, logical_seq, wall_time,
                      event_type, causal_parent_ids, payload, idempotency_key
        """
        with self.connection.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    record["id"],
                    record["run_id"],
                    record["agent_id"],
                    record["logical_seq"],
                    record["wall_time"],
                    record["event_type"],
                    record["causal_parent_ids"],
                    Jsonb(record["payload"]),
                    record["idempotency_key"],
                ),
            )
            row = cursor.fetchone()
            if row is None and event.idempotency_key is not None:
                cursor.execute(
                    "SELECT id, run_id, agent_id, logical_seq, wall_time, event_type, "
                    "causal_parent_ids, payload, idempotency_key FROM events "
                    "WHERE agent_id = %s AND idempotency_key = %s",
                    (event.agent_id, event.idempotency_key),
                )
                row = cursor.fetchone()
        self.connection.commit()
        if row is None:
            raise RuntimeError("event insert did not return an event")
        return self._row_to_event(row)

    def get(self, event_id: str) -> Event | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, run_id, agent_id, logical_seq, wall_time, event_type, "
                "causal_parent_ids, payload, idempotency_key FROM events WHERE id = %s",
                (event_id,),
            )
            row = cursor.fetchone()
        return None if row is None else self._row_to_event(row)

    def get_by_idempotency_key(self, agent_id: str, key: str) -> Event | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, run_id, agent_id, logical_seq, wall_time, event_type, "
                "causal_parent_ids, payload, idempotency_key FROM events "
                "WHERE agent_id = %s AND idempotency_key = %s",
                (agent_id, key),
            )
            row = cursor.fetchone()
        return None if row is None else self._row_to_event(row)

    def create_agent(self, agent: AgentRecord) -> AgentRecord:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO agents (id, run_id, parent_agent_id, spawned_at_event_id, role, "
                "status, lamport_offset) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (
                    agent.id,
                    agent.run_id,
                    agent.parent_agent_id,
                    agent.spawned_at_event_id,
                    agent.role,
                    agent.status,
                    agent.lamport_offset,
                ),
            )
        self.connection.commit()
        return agent

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, run_id, parent_agent_id, spawned_at_event_id, role, status, "
                "lamport_offset FROM agents WHERE id = %s",
                (agent_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return AgentRecord(
            id=str(row[0]),
            run_id=str(row[1]),
            parent_agent_id=None if row[2] is None else str(row[2]),
            spawned_at_event_id=None if row[3] is None else str(row[3]),
            role=row[4],
            status=row[5],
            lamport_offset=row[6],
        )

    def get_by_spawn_event(self, event_id: str) -> AgentRecord | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, run_id, parent_agent_id, spawned_at_event_id, role, status, "
                "lamport_offset FROM agents WHERE spawned_at_event_id = %s",
                (event_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self.get_agent(str(row[0]))

    @staticmethod
    def _row_to_event(row: tuple[Any, ...]) -> Event:
        wall_time = row[4]
        if not isinstance(wall_time, datetime):
            raise TypeError("Postgres returned a non-datetime wall_time")
        return Event(
            id=str(row[0]),
            run_id=None if row[1] is None else str(row[1]),
            agent_id=str(row[2]),
            logical_seq=row[3],
            wall_time=wall_time,
            event_type=str(row[5]),
            causal_parent_ids=[str(value) for value in (row[6] or [])],
            payload=dict(row[7]),
            idempotency_key=row[8],
        )
