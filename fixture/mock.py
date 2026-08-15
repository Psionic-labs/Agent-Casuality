"""
mock.py

A mock implementation of the six core CausalDebugger methods
(reconstruct, ancestors, slice, provenance, interactions, diff),
backed by fixture.json instead of Postgres.

Structural methods (ancestors, slice, provenance, reconstruct, diff) are
REAL working logic, the same algorithms described in section 30 of the
thesis document, just reading from a JSON file instead of a database.

slice_minimal and interactions are STUBS. They cannot be computed for
real without a working counterfactual replay engine (section 30.7), which
does not exist yet. They return the ground_truth block from the fixture
instead, and say so plainly in the result, so nobody mistakes a stub for
a real answer.

Every method signature here matches what the real Postgres backed version
will expose, so code written against this mock should not need to change
when the real backend is ready. Only the constructor changes.

No external dependencies. Runs with a plain python3 interpreter.
"""

import argparse
import json
from pathlib import Path
from typing import Any


class CausalDebuggerFixture:
    def __init__(self, fixture_path: str):
        data = json.loads(Path(fixture_path).read_text())
        self.run = data["run"]
        self.agents = {a["id"]: a for a in data["agents"]}
        self.events = {e["id"]: e for e in data["events"]}
        self.provenance_edges = data["provenance_edges"]
        self.ground_truth = data["ground_truth"]

    # ---- real logic -------------------------------------------------

    def ancestors(self, event_id: str) -> list[str]:
        """Structural slice. Pure graph traversal, no replay needed.
        Matches section 30.4 of the thesis document exactly."""
        visited: set[str] = set()
        queue = [event_id]
        while queue:
            current = queue.pop()
            if current in visited:
                continue
            visited.add(current)
            event = self.events[current]
            queue.extend(event["causal_parent_ids"])
        visited.discard(event_id)
        return sorted(visited, key=lambda e: self.events[e]["logical_seq"])

    def slice(self, event_id: str) -> list[str]:
        """The structural slice including the failure event itself."""
        return self.ancestors(event_id) + [event_id]

    def provenance(self, field_path: str) -> list[dict[str, Any]]:
        """Walk the provenance chain backward. Real logic, stops on its
        own once it reaches a coarse link, since a coarse row has no
        source_path to continue from. Matches section 30.8."""
        chain = []
        frontier = [field_path]
        seen = set()
        while frontier:
            current_path = frontier.pop()
            if current_path in seen:
                continue
            seen.add(current_path)
            matches = [e for e in self.provenance_edges if e["field_path"] == current_path]
            for edge in matches:
                chain.append(edge)
                if edge["grade"] == "exact" and edge["source_path"]:
                    frontier.append(edge["source_path"])
        return chain

    def reconstruct(self, agent_id: str, target_seq: int) -> dict[str, Any]:
        """Naive state reconstruction, fold every event for this agent up
        to target_seq. The fixture has no snapshots, since the run is
        small enough not to need any, this is the same reducer shape as
        section 30.3 without the snapshot lookup step."""
        state: dict[str, Any] = {"payloads_applied": [], "status": "active"}
        agent_events = sorted(
            (e for e in self.events.values() if e["agent_id"] == agent_id and e["logical_seq"] <= target_seq),
            key=lambda e: e["logical_seq"],
        )
        for event in agent_events:
            state["payloads_applied"].append({"event_id": event["id"], "payload": event["payload"]})
            if event["event_type"] == "agent_finish":
                state["status"] = event["payload"].get("status", "completed")
        return state

    def diff(self, event_a: str, event_b: str) -> dict[str, Any]:
        """Compare reconstructed state at two points for the same agent."""
        agent_a = self.events[event_a]["agent_id"]
        agent_b = self.events[event_b]["agent_id"]
        if agent_a != agent_b:
            return {"error": "diff currently only supports two events on the same agent"}
        seq_a = self.events[event_a]["logical_seq"]
        seq_b = self.events[event_b]["logical_seq"]
        state_a = self.reconstruct(agent_a, seq_a)
        state_b = self.reconstruct(agent_b, seq_b)
        return {
            "added_events": [p["event_id"] for p in state_b["payloads_applied"]
                              if p["event_id"] not in [q["event_id"] for q in state_a["payloads_applied"]]],
            "status_before": state_a["status"],
            "status_after": state_b["status"],
        }

    # ---- stubs, need real replay to compute for real -----------------

    def slice_minimal(self, event_id: str) -> dict[str, Any]:
        """STUB. Real version needs ddmin plus counterfactual_replay,
        section 30.5. Returns the fixture's known ground truth instead."""
        return {
            "result": self.ground_truth["minimal_slice"],
            "note": self.ground_truth["minimal_slice_note"],
            "source": "fixture_ground_truth, not computed by real ddmin yet",
        }

    def interactions(self, event_id: str) -> dict[str, Any]:
        """STUB. Real version needs counterfactual_replay run four ways,
        section 30.6. Returns the fixture's known ground truth instead."""
        result = dict(self.ground_truth["interaction"])
        result["source"] = "fixture_ground_truth, not computed by real replay yet"
        return result

    def explain(self, event_id: str) -> str:
        """STUB. Real version assembles a structured evidence package and
        sends it to an LLM, section 52 of the earlier document. Returns
        the fixture's canned explanation instead."""
        return self.ground_truth["explanation"]


# ---- tiny CLI, mirrors the commands in section 18 of the thesis doc ----

def main():
    parser = argparse.ArgumentParser(description="Causal debugger, fixture backed")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("agents")

    p_graph = sub.add_parser("graph")
    p_graph.add_argument("event_id")

    p_slice = sub.add_parser("slice")
    p_slice.add_argument("event_id")
    p_slice.add_argument("--minimal", action="store_true")

    p_prov = sub.add_parser("provenance")
    p_prov.add_argument("field_path")

    p_inter = sub.add_parser("interactions")
    p_inter.add_argument("event_id")

    p_explain = sub.add_parser("explain")
    p_explain.add_argument("event_id")

    args = parser.parse_args()
    fixture_path = Path(__file__).parent / "fixture.json"
    debugger = CausalDebuggerFixture(str(fixture_path))

    if args.command == "agents":
        for agent_id, agent in debugger.agents.items():
            print(f"{agent_id}  {agent['role']}")

    elif args.command == "graph":
        for event_id in debugger.slice(args.event_id):
            event = debugger.events[event_id]
            parents = ", ".join(event["causal_parent_ids"]) or "none"
            print(f"{event_id}  {event['event_type']:<12} parents: {parents}")

    elif args.command == "slice":
        if args.minimal:
            result = debugger.slice_minimal(args.event_id)
            print(f"Minimal slice: {', '.join(result['result'])}")
            print(f"Note: {result['note']}")
            print(f"({result['source']})")
        else:
            events = debugger.slice(args.event_id)
            total = len(debugger.events)
            print(f"Structural slice: {len(events)} / {total} events")
            print(", ".join(events))

    elif args.command == "provenance":
        chain = debugger.provenance(args.field_path)
        current = args.field_path
        print(current)
        for edge in chain:
            grade_label = f"({edge['grade']})"
            target = edge["source_path"] if edge["source_path"] else "(no further trace, LLM boundary)"
            print(f" <- {edge['source_event_id']}.{target}  {grade_label}")

    elif args.command == "interactions":
        result = debugger.interactions(args.event_id)
        print(f"Potential interaction: {' x '.join(result['candidates'])}")
        print(f"{result['candidates'][0]} alone: {result[result['candidates'][0] + '_alone']}")
        print(f"{result['candidates'][1]} alone: {result[result['candidates'][1] + '_alone']}")
        print(f"{result['candidates'][0]} + {result['candidates'][1]}: {result[result['candidates'][0] + '_and_' + result['candidates'][1]]}")
        print(f"({result['source']})")

    elif args.command == "explain":
        print(debugger.explain(args.event_id))


if __name__ == "__main__":
    main()
