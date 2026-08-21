from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest

from core.graph import record_causal_event
from sdk.client import CapturedClient
from sdk.events import AgentClock, Event, record_event
from sdk.lifecycle import spawn_agent
from sdk.tools import capture_tool
from storage.postgres import PostgresEventStore


class FakeResponse:
    def model_dump(self) -> dict[str, str]:
        return {"content": "merged"}


class FakeMessages:
    def create(self, **_: object) -> FakeResponse:
        return FakeResponse()


class FakeAnthropic:
    def __init__(self) -> None:
        self.messages = FakeMessages()


@pytest.mark.integration
def test_real_postgres_planner_two_workers_tools_and_merge() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("set DATABASE_URL to run the real Postgres integration test")
    psycopg = pytest.importorskip("psycopg")
    run_id = str(uuid4())
    planner_id = str(uuid4())
    with psycopg.connect(database_url) as connection:
        store = PostgresEventStore(connection, lock_dsn=database_url)
        store.create_schema()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO runs (id, name) VALUES (%s, %s)", (run_id, "phase-1"))
            cursor.execute(
                "INSERT INTO agents (id, run_id, role) VALUES (%s, %s, %s)",
                (planner_id, run_id, "planner"),
            )
        connection.commit()
        planner_clock = AgentClock()
        planner_log = store
        worker_one, _, worker_one_clock = spawn_agent(
            parent_agent_id=planner_id,
            parent_clock=planner_clock,
            run_id=run_id,
            role="worker-1",
            log=planner_log,
            agent_store=store,
            child_agent_id=str(uuid4()),
        )
        worker_two, _, worker_two_clock = spawn_agent(
            parent_agent_id=planner_id,
            parent_clock=planner_clock,
            run_id=run_id,
            role="worker-2",
            log=planner_log,
            agent_store=store,
            child_agent_id=str(uuid4()),
        )

        @capture_tool
        def inspect(label: str) -> dict[str, str]:
            return {label: "done"}

        result_one = inspect(
            "one",
            agent_id=worker_one.id,
            clock=worker_one_clock,
            log=store,
            run_id=run_id,
            invocation_id="worker-one-tool",
        )
        result_two = inspect(
            "two",
            agent_id=worker_two.id,
            clock=worker_two_clock,
            log=store,
            run_id=run_id,
            invocation_id="worker-two-tool",
        )
        worker_events_one = [
            store.get(event_id) for event_id in _event_ids(connection, worker_one.id)
        ]
        worker_events_two = [
            store.get(event_id) for event_id in _event_ids(connection, worker_two.id)
        ]
        result_event_one = next(
            event for event in worker_events_one if event and event.event_type == "tool_result"
        )
        result_event_two = next(
            event for event in worker_events_two if event and event.event_type == "tool_result"
        )

        client = CapturedClient(
            None,
            planner_id,
            planner_clock,
            store,
            client=FakeAnthropic(),
            run_id=run_id,
        )
        client.messages.create(
            model="test-model",
            max_tokens=10,
            messages=[{"role": "user", "content": f"merge {result_one} {result_two}"}],
            causal_parent_ids=[result_event_one.id, result_event_two.id],
        )

        planner_events = [store.get(event_id) for event_id in _event_ids(connection, planner_id)]
        assert {event.event_type for event in planner_events if event} >= {
            "agent_spawn",
            "model_call",
        }
        merge = next(
            event for event in planner_events if event and event.event_type == "model_call"
        )
        assert merge.causal_parent_ids == [result_event_one.id, result_event_two.id]


@pytest.mark.integration
def test_postgres_allocates_agent_sequences_across_connections() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("set DATABASE_URL to run the real Postgres integration test")
    psycopg = pytest.importorskip("psycopg")
    run_id = str(uuid4())
    agent_id = str(uuid4())
    with psycopg.connect(database_url) as setup_connection:
        setup_store = PostgresEventStore(setup_connection, lock_dsn=database_url)
        setup_store.create_schema()
        with setup_connection.cursor() as cursor:
            cursor.execute("INSERT INTO runs (id, name) VALUES (%s, %s)", (run_id, "sequence"))
            cursor.execute(
                "INSERT INTO agents (id, run_id, role) VALUES (%s, %s, %s)",
                (agent_id, run_id, "worker"),
            )
        setup_connection.commit()

    with (
        psycopg.connect(database_url) as connection_one,
        psycopg.connect(database_url) as connection_two,
    ):
        store_one = PostgresEventStore(connection_one, lock_dsn=database_url)
        store_two = PostgresEventStore(connection_two, lock_dsn=database_url)
        clock_one = AgentClock()
        clock_two = AgentClock()
        start_barrier = Barrier(2)

        def write_event(store: PostgresEventStore, clock: AgentClock) -> int:
            start_barrier.wait()
            event, _ = record_event(
                agent_id=agent_id,
                clock=clock,
                log=store,
                event_type="context_update",
                payload={"source": "concurrent"},
                run_id=run_id,
            )
            return event.logical_seq

        with ThreadPoolExecutor(max_workers=2) as pool:
            sequences = list(
                pool.map(
                    write_event,
                    (store_one, store_two),
                    (clock_one, clock_two),
                )
            )

        assert sorted(sequences) == [1, 2]


@pytest.mark.integration
def test_postgres_sequence_allocation_rolls_back_with_failed_append() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("set DATABASE_URL to run the real Postgres integration test")
    psycopg = pytest.importorskip("psycopg")
    run_id = str(uuid4())
    agent_id = str(uuid4())
    with psycopg.connect(database_url) as connection:
        store = PostgresEventStore(connection, lock_dsn=database_url)
        store.create_schema()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO runs (id, name) VALUES (%s, %s)", (run_id, "sequence"))
            cursor.execute(
                "INSERT INTO agents (id, run_id, role) VALUES (%s, %s, %s)",
                (agent_id, run_id, "worker"),
            )
        connection.commit()

        with pytest.raises(psycopg.Error):
            _, _ = record_event(
                agent_id=agent_id,
                clock=AgentClock(),
                log=store,
                event_type="not_an_event_type",
                payload={},
                run_id=run_id,
            )

        event, _ = record_event(
            agent_id=agent_id,
            clock=AgentClock(),
            log=store,
            event_type="context_update",
            payload={},
            idempotency_key="sequence-retry",
            run_id=run_id,
        )
        allocated = store.allocate_logical_seq(agent_id, AgentClock())
        conflicting_retry = store.append(
            Event(
                run_id=run_id,
                agent_id=agent_id,
                logical_seq=allocated,
                event_type="context_update",
                payload={"conflict": True},
                causal_parent_ids=["not-a-uuid"],
                idempotency_key="sequence-retry",
            )
        )
        retry, _ = record_event(
            agent_id=agent_id,
            clock=AgentClock(),
            log=store,
            event_type="context_update",
            payload={"changed": True},
            idempotency_key="sequence-retry",
            run_id=run_id,
        )

        assert event.logical_seq == 1
        assert allocated == 2
        assert conflicting_retry.id == event.id
        assert conflicting_retry.logical_seq == 1
        assert retry.id == event.id
        assert retry.logical_seq == 1
        with connection.cursor() as cursor:
            cursor.execute("SELECT lamport_offset FROM agents WHERE id = %s", (agent_id,))
            assert cursor.fetchone()[0] == 1


@pytest.mark.integration
def test_postgres_graph_rejects_and_isolates_cross_run_parents() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("set DATABASE_URL to run the real Postgres integration test")
    psycopg = pytest.importorskip("psycopg")
    from psycopg.types.json import Jsonb

    run_a, run_b = str(uuid4()), str(uuid4())
    agent_a, agent_b = str(uuid4()), str(uuid4())
    with psycopg.connect(database_url) as connection:
        store = PostgresEventStore(connection, lock_dsn=database_url)
        store.create_schema()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO runs (id, name) VALUES (%s, %s)", (run_a, "graph-a"))
            cursor.execute("INSERT INTO runs (id, name) VALUES (%s, %s)", (run_b, "graph-b"))
            cursor.execute(
                "INSERT INTO agents (id, run_id, role) VALUES (%s, %s, %s)",
                (agent_a, run_a, "worker-a"),
            )
            cursor.execute(
                "INSERT INTO agents (id, run_id, role) VALUES (%s, %s, %s)",
                (agent_b, run_b, "worker-b"),
            )
        connection.commit()

        parent, _ = record_event(
            agent_id=agent_a,
            clock=AgentClock(),
            log=store,
            event_type="context_update",
            payload={},
            run_id=run_a,
        )
        with pytest.raises(ValueError, match="another run"):
            record_causal_event(
                agent_id=agent_b,
                clock=AgentClock(),
                log=store,
                event_type="context_update",
                payload={},
                causal_parents=[parent.id],
                run_id=run_b,
            )

        with pytest.raises(ValueError, match="must belong to the event run"):
            store.append(
                Event(
                    run_id=run_b,
                    agent_id=agent_b,
                    logical_seq=1,
                    event_type="context_update",
                    payload={},
                    causal_parent_ids=[parent.id],
                )
            )

        legacy_event = Event(
            run_id=run_b,
            agent_id=agent_b,
            logical_seq=1,
            event_type="context_update",
            payload={},
            causal_parent_ids=[parent.id],
        )
        record = legacy_event.to_record()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO events "
                "(id, run_id, agent_id, logical_seq, event_type, "
                "causal_parent_ids, payload) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    record["id"],
                    record["run_id"],
                    record["agent_id"],
                    record["logical_seq"],
                    record["event_type"],
                    record["causal_parent_ids"],
                    Jsonb(record["payload"]),
                ),
            )
        connection.commit()

        assert store.ancestors(legacy_event.id) == [legacy_event.id]


def _event_ids(connection: Any, agent_id: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM events WHERE agent_id = %s ORDER BY logical_seq", (agent_id,)
        )
        return [str(row[0]) for row in cursor.fetchall()]
