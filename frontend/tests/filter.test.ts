// Regression tests: event-type filter pure logic — default preset hides
// streaming noise, edges are dropped (never rewired), dataset counts and
// the failure target survive filtering. Run with `npm test`.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_HIDDEN_TYPES,
  KEY_EVENT_TYPES,
  countByType,
  filterOverview,
  filterSession,
  listSessions,
  shortSessionId,
} from "../lib/filter.ts";
import type { GraphOverview, OverviewNode } from "../lib/types.ts";

function node(id: string, event_type: string, logical_seq: number): OverviewNode {
  return {
    id,
    event_type,
    opencode_kind: "",
    agent_id: "opencode:ses_demo",
    logical_seq,
    wall_time: "",
    label: `${logical_seq}: ${event_type}`,
    role: null,
    in_failure_slice: true,
  };
}

// Live-capture shape: streaming parts + model turns dwarf the tool story.
const NODES = [
  node("run", "run_start", 1),
  node("part1", "context_update", 2),
  node("model1", "model_call", 3),
  node("read", "tool_call", 4),
  node("read-out", "tool_result", 5),
  node("part2", "context_update", 6),
  node("model2", "model_call", 7),
  node("edit", "tool_call", 8),
  node("edit-out", "tool_result", 9),
  node("bash", "tool_call", 10),
  node("bash-out", "tool_result", 11),
];

const EDGES = [
  { parent: "run", child: "part1" },
  { parent: "part1", child: "model1" },
  { parent: "model1", child: "read" },
  { parent: "read", child: "read-out" },
  { parent: "read-out", child: "part2" },
  { parent: "part2", child: "model2" },
  { parent: "model2", child: "edit" },
  { parent: "edit", child: "edit-out" },
  { parent: "edit-out", child: "bash" },
  { parent: "bash", child: "bash-out" },
];

function overview(): GraphOverview {
  return {
    source: "test",
    event_count: NODES.length,
    edge_count: EDGES.length,
    failure_event_id: "bash-out",
    failure_status: "fallback_last_event",
    failure_method: "fallback",
    nodes: NODES,
    edges: EDGES,
  };
}

describe("event-type filter", () => {
  it("default preset hides streaming noise, keeps the tool story", () => {
    assert.ok(DEFAULT_HIDDEN_TYPES.has("context_update"));
    assert.ok(DEFAULT_HIDDEN_TYPES.has("model_call"));
    const visible = filterOverview(overview(), DEFAULT_HIDDEN_TYPES);
    assert.deepEqual(
      visible.nodes.map((n) => n.id),
      ["run", "read", "read-out", "edit", "edit-out", "bash", "bash-out"],
    );
    for (const n of visible.nodes) assert.ok(KEY_EVENT_TYPES.has(n.event_type));
  });

  it("drops edges touching hidden endpoints, never rewires", () => {
    const visible = filterOverview(overview(), DEFAULT_HIDDEN_TYPES);
    // Only read→read-out, edit→edit-out, edit-out→bash, bash→bash-out survive:
    // every kept edge joins two visible nodes, and no edge jumps over a
    // hidden node (e.g. no read-out→edit, no model2→edit shortcut).
    assert.deepEqual(visible.edges, [
      { parent: "read", child: "read-out" },
      { parent: "edit", child: "edit-out" },
      { parent: "edit-out", child: "bash" },
      { parent: "bash", child: "bash-out" },
    ]);
  });

  it("empty hidden set returns the overview untouched", () => {
    const o = overview();
    const visible = filterOverview(o, new Set());
    assert.equal(visible, o);
    assert.equal(visible.nodes.length, 11);
    assert.equal(visible.edges.length, 10);
  });

  it("preserves dataset counts and the failure target", () => {
    const visible = filterOverview(overview(), DEFAULT_HIDDEN_TYPES);
    assert.equal(visible.event_count, 11);
    assert.equal(visible.edge_count, 10);
    assert.equal(visible.failure_event_id, "bash-out");
  });

  it("always keeps the failure node even when its type is hidden", () => {
    // Fallback datasets point at the last event, often a streaming part.
    const o = overview();
    o.failure_event_id = "part2"; // a context_update
    const visible = filterOverview(o, DEFAULT_HIDDEN_TYPES, o.failure_event_id);
    assert.ok(visible.nodes.some((n) => n.id === "part2"), "failure node filtered out");
    // Edges to visible neighbours survive (read-out is visible, so
    // read-out→part2 stays); edges into hidden nodes still drop.
    assert.ok(
      visible.edges.some((e) => e.parent === "read-out" && e.child === "part2"),
      "edge into the kept failure node dropped",
    );
    assert.ok(
      !visible.edges.some((e) => e.parent === "part2"),
      "edge out of the failure node into hidden model2 rewired/kept",
    );
  });

  it("null failure id keeps the old type-only behavior", () => {
    const o = overview();
    o.failure_event_id = "part2";
    const visible = filterOverview(o, DEFAULT_HIDDEN_TYPES, null);
    assert.ok(!visible.nodes.some((n) => n.id === "part2"));
  });

  it("hiding everything keeps only the pinned failure node", () => {
    const all = new Set(NODES.map((n) => n.event_type));
    const visible = filterOverview(overview(), all, "bash-out");
    assert.deepEqual(visible.nodes.map((n) => n.id), ["bash-out"]);
    assert.deepEqual(visible.edges, []);
  });

  it("hiding everything yields empty views, not an error", () => {
    const all = new Set(NODES.map((n) => n.event_type));
    const visible = filterOverview(overview(), all);
    assert.deepEqual(visible.nodes, []);
    assert.deepEqual(visible.edges, []);
    assert.equal(visible.failure_event_id, "bash-out");
  });

  it("countByType censuses in first-appearance order", () => {
    assert.deepEqual(countByType(NODES), [
      { type: "run_start", count: 1 },
      { type: "context_update", count: 2 },
      { type: "model_call", count: 2 },
      { type: "tool_call", count: 3 },
      { type: "tool_result", count: 3 },
    ]);
    assert.deepEqual(countByType([]), []);
  });
});

describe("session scope", () => {
  function sessionNode(id: string, agent: string, wall: string): OverviewNode {
    return { ...node(id, "tool_call", 1), agent_id: agent, wall_time: wall };
  }

  const MIXED: GraphOverview = {
    source: "test",
    event_count: 5,
    edge_count: 3,
    failure_event_id: "b2",
    failure_status: null,
    failure_method: null,
    nodes: [
      sessionNode("a1", "opencode:ses_old", "2026-10-04T21:00:00+00:00"),
      sessionNode("a2", "opencode:ses_old", "2026-10-04T21:01:00+00:00"),
      sessionNode("b1", "opencode:ses_new", "2026-10-07T22:26:00+00:00"),
      sessionNode("b2", "opencode:ses_new", "2026-10-07T22:27:00+00:00"),
      sessionNode("u1", "opencode:unknown", "2026-10-07T22:26:30+00:00"),
    ],
    edges: [
      { parent: "a1", child: "a2" },
      { parent: "b1", child: "b2" },
      { parent: "a2", child: "b1" },
    ],
  };

  it("lists sessions latest-activity first with counts", () => {
    assert.deepEqual(listSessions(MIXED.nodes), [
      { agent: "opencode:ses_new", count: 2, lastWallTime: "2026-10-07T22:27:00+00:00" },
      { agent: "opencode:unknown", count: 1, lastWallTime: "2026-10-07T22:26:30+00:00" },
      { agent: "opencode:ses_old", count: 2, lastWallTime: "2026-10-04T21:01:00+00:00" },
    ]);
    assert.deepEqual(listSessions([]), []);
  });

  it("scopes nodes and edges to one session without rewiring", () => {
    const scoped = filterSession(MIXED, "opencode:ses_new");
    assert.deepEqual(
      scoped.nodes.map((n) => n.id),
      ["b1", "b2"],
    );
    // a2→b1 crosses the session boundary, so it drops: only b1→b2 remains.
    assert.deepEqual(scoped.edges, [{ parent: "b1", child: "b2" }]);
    assert.equal(scoped.event_count, 5);
    assert.equal(scoped.failure_event_id, "b2");
  });

  it("null session returns the overview untouched", () => {
    assert.equal(filterSession(MIXED, null), MIXED);
    assert.equal(filterSession(MIXED, ""), MIXED);
  });

  it("unknown session yields empty views, not an error", () => {
    const scoped = filterSession(MIXED, "opencode:ses_missing");
    assert.deepEqual(scoped.nodes, []);
    assert.deepEqual(scoped.edges, []);
  });

  it("shortSessionId strips the capture prefix and truncates", () => {
    assert.equal(shortSessionId("opencode:ses_ee8397022ffe3y6z2frr9qisLJ"), "ses_ee839702…");
    assert.equal(shortSessionId("opencode:unknown"), "unknown");
    assert.equal(shortSessionId("demo"), "demo");
  });
});
