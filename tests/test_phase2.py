from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from core.graph import ancestors, assign_causal_parents, record_causal_event
from sdk.client import CapturedClient
from sdk.events import AgentClock, Event, InMemoryEventLog, record_event
from sdk.lifecycle import spawn_agent
from sdk.tools import capture_tool
from storage.postgres import PostgresEventStore


def test_assign_causal_parents_uses_parent_sequences_not_wall_time() -> None:
    log = InMemoryEventLog()
    log.append(
        Event(
            id="research-result",
            agent_id="researcher",
            logical_seq=4,
            event_type="tool_result",
            payload={},
            wall_time=datetime.now(UTC) + timedelta(days=1),
        )
    )
    log.append(
        Event(
            id="coder-result",
            agent_id="coder",
            logical_seq=9,
            event_type="tool_result",
            payload={},
            wall_time=datetime.now(UTC) - timedelta(days=1),
        )
    )

    clock = AgentClock(counter=2)
    sequence = assign_causal_parents(
        "planner",
        clock,
        ["research-result", "coder-result"],
        log,
    )

    assert sequence == 10
    assert clock.counter == 10


def test_record_causal_event_preserves_multiple_parent_ids() -> None:
    log = InMemoryEventLog()
    parent_ids = ["parent-one", "parent-two"]
    for parent_id in parent_ids:
        log.append(
            Event(
                id=parent_id,
                agent_id="worker",
                logical_seq=1,
                event_type="tool_result",
                payload={},
            )
        )

    event = record_causal_event(
        agent_id="planner",
        clock=AgentClock(),
        log=log,
        event_type="model_call",
        payload={"action": "merge"},
        causal_parents=parent_ids,
    )

    assert event.causal_parent_ids == parent_ids
    assert event.logical_seq == 2


def test_record_causal_event_idempotent_retry_does_not_allocate_again() -> None:
    log = InMemoryEventLog()
    clock = AgentClock()
    first = record_causal_event(
        agent_id="planner",
        clock=clock,
        log=log,
        event_type="context_update",
        payload={"attempt": 1},
        causal_parents=[],
        idempotency_key="same-merge",
    )

    retry = record_causal_event(
        agent_id="planner",
        clock=clock,
        log=log,
        event_type="context_update",
        payload={"attempt": 2},
        causal_parents=[],
        idempotency_key="same-merge",
    )

    assert retry == first
    assert clock.current() == first.logical_seq


def test_record_causal_event_rejects_duplicate_parent_ids() -> None:
    log = InMemoryEventLog()
    log.append(
        Event(
            id="parent",
            agent_id="worker",
            logical_seq=1,
            event_type="tool_result",
            payload={},
        )
    )

    with pytest.raises(ValueError, match="must be unique"):
        record_causal_event(
            agent_id="planner",
            clock=AgentClock(),
            log=log,
            event_type="context_update",
            payload={},
            causal_parents=["parent", "parent"],
        )


def test_assign_causal_parents_rejects_duplicate_parent_ids() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        assign_causal_parents("planner", AgentClock(), ["parent", "parent"], InMemoryEventLog())


def test_assign_causal_parents_rejects_missing_parent() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        assign_causal_parents("planner", AgentClock(), ["missing"], InMemoryEventLog())


def test_assign_causal_parents_rejects_cross_run_parent() -> None:
    log = InMemoryEventLog()
    log.append(
        Event(
            id="parent",
            run_id="run-a",
            agent_id="worker",
            logical_seq=1,
            event_type="tool_result",
            payload={},
        )
    )

    with pytest.raises(ValueError, match="another run"):
        assign_causal_parents("planner", AgentClock(), ["parent"], log, "run-b")


class _Response:
    def model_dump(self) -> dict[str, str]:
        return {"content": "ready"}


class _Messages:
    def create(self, **_: object) -> _Response:
        return _Response()


class _Anthropic:
    def __init__(self) -> None:
        self.messages = _Messages()


@pytest.mark.integration
def test_phase2_schema_and_real_three_agent_graph() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("set DATABASE_URL to run the real PostgreSQL integration test")
    psycopg = pytest.importorskip("psycopg")

    run_id = str(uuid4())
    planner_id = str(uuid4())
    with psycopg.connect(database_url) as connection:
        store = PostgresEventStore(connection, lock_dsn=database_url)
        store.create_schema()
        _assert_phase2_schema(connection)

        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO runs (id, name) VALUES (%s, %s)", (run_id, "phase-2"))
            cursor.execute(
                "INSERT INTO agents (id, run_id, role) VALUES (%s, %s, %s)",
                (planner_id, run_id, "planner"),
            )
        connection.commit()

        planner_clock = AgentClock()
        researcher, researcher_spawn, researcher_clock = spawn_agent(
            parent_agent_id=planner_id,
            parent_clock=planner_clock,
            run_id=run_id,
            role="researcher",
            log=store,
            agent_store=store,
            child_agent_id=str(uuid4()),
        )
        coder, coder_spawn, coder_clock = spawn_agent(
            parent_agent_id=planner_id,
            parent_clock=planner_clock,
            run_id=run_id,
            role="coder",
            log=store,
            agent_store=store,
            child_agent_id=str(uuid4()),
        )

        researcher_client = CapturedClient(
            None,
            researcher.id,
            researcher_clock,
            store,
            client=_Anthropic(),
            run_id=run_id,
        )
        coder_client = CapturedClient(
            None,
            coder.id,
            coder_clock,
            store,
            client=_Anthropic(),
            run_id=run_id,
        )
        researcher_model = researcher_client.messages.create(
            model="test-model",
            max_tokens=10,
            messages=[{"role": "user", "content": "research"}],
            causal_parent_ids=[researcher_spawn.id],
        )
        coder_model = coder_client.messages.create(
            model="test-model",
            max_tokens=10,
            messages=[{"role": "user", "content": "code"}],
            causal_parent_ids=[coder_spawn.id],
        )

        @capture_tool
        def inspect(label: str) -> dict[str, str]:
            return {label: "done"}

        inspect(
            "research",
            agent_id=researcher.id,
            clock=researcher_clock,
            log=store,
            run_id=run_id,
            causal_parent_ids=[_latest_event_id(store, researcher.id)],
            invocation_id="phase2-research-tool",
        )
        inspect(
            "code",
            agent_id=coder.id,
            clock=coder_clock,
            log=store,
            run_id=run_id,
            causal_parent_ids=[_latest_event_id(store, coder.id)],
            invocation_id="phase2-code-tool",
        )
        researcher_result = _latest_event(store, researcher.id, "tool_result")
        coder_result = _latest_event(store, coder.id, "tool_result")

        merge = record_causal_event(
            agent_id=planner_id,
            clock=planner_clock,
            log=store,
            event_type="model_call",
            payload={
                "model": "test-model",
                "input": [researcher_model.model_dump(), coder_model.model_dump()],
                "output": {"merged": True},
            },
            causal_parents=[researcher_result.id, coder_result.id],
            run_id=run_id,
        )

        researcher_record = store.get_agent(researcher.id)
        coder_record = store.get_agent(coder.id)
        assert researcher_record is not None
        assert coder_record is not None
        assert researcher_record.parent_agent_id == planner_id
        assert coder_record.parent_agent_id == planner_id
        assert researcher_record.spawned_at_event_id == researcher_spawn.id
        assert coder_record.spawned_at_event_id == coder_spawn.id
        assert merge.causal_parent_ids == [researcher_result.id, coder_result.id]

        fixture = json.loads((Path(__file__).parents[1] / "fixture" / "fixture.json").read_text())
        fixture_agents = {agent["id"]: agent for agent in fixture["agents"]}
        fixture_roles = {agent["role"] for agent in fixture["agents"]}
        assert {"planner", "researcher", "coder"} <= fixture_roles
        planner_record = store.get_agent(planner_id)
        assert planner_record is not None
        assert {
            planner_record.role,
            researcher_record.role,
            coder_record.role,
        } == {"planner", "researcher", "coder"}
        for role, agent in (("researcher", researcher), ("coder", coder)):
            fixture_agent_id = next(
                agent_id for agent_id, value in fixture_agents.items() if value["role"] == role
            )
            fixture_branch = [
                event["event_type"]
                for event in fixture["events"]
                if event["agent_id"] == fixture_agent_id
            ]
            actual_branch = [
                event.event_type
                for event_id in _event_ids(store, agent.id)
                if (event := store.get(event_id)) is not None
            ]
            assert actual_branch == fixture_branch
        fixture_merge = next(
            event
            for event in fixture["events"]
            if event["agent_id"] == "A" and len(event["causal_parent_ids"]) == 3
        )
        fixture_events = {event["id"]: event for event in fixture["events"]}
        fixture_cross_parent_count = sum(
            fixture_events[parent_id]["agent_id"] != "A"
            for parent_id in fixture_merge["causal_parent_ids"]
        )
        assert len(merge.causal_parent_ids) == fixture_cross_parent_count
        researcher_branch = ancestors(researcher_result.id, store)
        coder_branch = ancestors(coder_result.id, store)
        assert ancestors(merge.id, store) == {
            merge.id,
            *researcher_branch,
            *coder_branch,
        }
        assert researcher_branch.isdisjoint(coder_branch)

        root, _ = record_event(
            agent_id=planner_id,
            clock=planner_clock,
            log=store,
            event_type="context_update",
            payload={"shared": True},
            run_id=run_id,
        )
        left = record_causal_event(
            agent_id=researcher.id,
            clock=researcher_clock,
            log=store,
            event_type="context_update",
            payload={"branch": "left"},
            causal_parents=[root.id],
            run_id=run_id,
        )
        right = record_causal_event(
            agent_id=coder.id,
            clock=coder_clock,
            log=store,
            event_type="context_update",
            payload={"branch": "right"},
            causal_parents=[root.id],
            run_id=run_id,
        )
        shared_merge = record_causal_event(
            agent_id=planner_id,
            clock=planner_clock,
            log=store,
            event_type="context_update",
            payload={"shared_merge": True},
            causal_parents=[left.id, right.id],
            run_id=run_id,
        )
        assert ancestors(shared_merge.id, store) == {
            shared_merge.id,
            left.id,
            right.id,
            root.id,
        }
        assert ancestors(root.id, store) == {root.id}
        with pytest.raises(ValueError, match="does not exist"):
            store.ancestors(str(uuid4()))


def _latest_event(store: PostgresEventStore, agent_id: str, event_type: str):
    event_ids = _event_ids(store, agent_id)
    events = [store.get(event_id) for event_id in event_ids]
    return next(event for event in reversed(events) if event and event.event_type == event_type)


def _latest_event_id(store: PostgresEventStore, agent_id: str) -> str:
    return _event_ids(store, agent_id)[-1]


def _event_ids(store: PostgresEventStore, agent_id: str) -> list[str]:
    with store.connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM events WHERE agent_id = %s ORDER BY logical_seq",
            (UUID(agent_id),),
        )
        return [str(row[0]) for row in cursor.fetchall()]


def _assert_phase2_schema(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name IN "
            "('runs', 'agents', 'events', 'snapshots')"
        )
        assert {row[0] for row in cursor.fetchall()} == {
            "runs",
            "agents",
            "events",
            "snapshots",
        }

        cursor.execute(
            "SELECT table_name, column_name, udt_name "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name IN "
            "('runs', 'agents', 'events', 'snapshots')"
        )
        columns = {(row[0], row[1]): row[2] for row in cursor.fetchall()}
        required_columns = {
            ("runs", "id"),
            ("agents", "run_id"),
            ("agents", "parent_agent_id"),
            ("agents", "spawned_at_event_id"),
            ("agents", "lamport_offset"),
            ("events", "run_id"),
            ("events", "agent_id"),
            ("events", "logical_seq"),
            ("events", "wall_time"),
            ("events", "event_type"),
            ("events", "causal_parent_ids"),
            ("events", "payload"),
            ("events", "idempotency_key"),
            ("snapshots", "run_id"),
            ("snapshots", "agent_id"),
            ("snapshots", "logical_seq"),
            ("snapshots", "state"),
            ("snapshots", "state_hash"),
        }
        assert required_columns <= columns.keys()
        assert columns["events", "id"] == "uuid"
        assert columns["events", "agent_id"] == "uuid"
        assert columns["events", "causal_parent_ids"] == "_uuid"
        assert columns["snapshots", "state"] == "jsonb"
        assert columns["snapshots", "state_hash"] == "text"

        cursor.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
            "AND indexname IN ('idx_events_agent_seq', 'idx_events_run_seq', "
            "'idx_snapshots_agent_seq', 'idx_events_idempotency')"
        )
        assert {row[0] for row in cursor.fetchall()} == {
            "idx_events_agent_seq",
            "idx_events_run_seq",
            "idx_snapshots_agent_seq",
            "idx_events_idempotency",
        }

        cursor.execute(
            "SELECT tc.constraint_name, kcu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
            "WHERE tc.table_schema = 'public' AND tc.table_name = 'events' "
            "AND tc.constraint_type = 'UNIQUE'"
        )
        unique_constraints: dict[str, set[str]] = {}
        for constraint_name, column_name in cursor.fetchall():
            unique_constraints.setdefault(constraint_name, set()).add(column_name)
        assert {"agent_id", "logical_seq"} in unique_constraints.values()

        cursor.execute(
            "SELECT kcu.table_name, kcu.column_name, ccu.table_name, ccu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema "
            "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'"
        )
        foreign_keys = {(row[0], row[1], row[2], row[3]) for row in cursor.fetchall()}
        assert ("agents", "run_id", "runs", "id") in foreign_keys
        assert ("agents", "parent_agent_id", "agents", "id") in foreign_keys
        assert ("agents", "spawned_at_event_id", "events", "id") in foreign_keys
        assert ("events", "run_id", "runs", "id") in foreign_keys
        assert ("events", "agent_id", "agents", "id") in foreign_keys
        assert ("snapshots", "run_id", "runs", "id") in foreign_keys
        assert ("snapshots", "agent_id", "agents", "id") in foreign_keys
