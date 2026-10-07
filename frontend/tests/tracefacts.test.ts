// Regression tests: trace-fact helpers for the Option B tab bodies —
// branching from declared edges, census counts, resource discovery from
// recorded metadata, and the tool story with parent/child-only command
// borrowing. Run with `npm test` (node --test, zero dependencies).
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  baseName,
  branchPoints,
  mergePoints,
  nodesForResource,
  resourcesInDetails,
  sliceNodes,
  toolStory,
  traceCensus,
} from "../lib/tracefacts.ts";
import type {
  EventDetail,
  EventRecord,
  GraphOverview,
  OverviewNode,
} from "../lib/types.ts";

function node(id: string, eventType: string, seq: number, inSlice = true): OverviewNode {
  return {
    id,
    event_type: eventType,
    opencode_kind: "",
    agent_id: "opencode:ses_demo",
    logical_seq: seq,
    wall_time: "",
    label: `${seq}: ${eventType}`,
    role: null,
    in_failure_slice: inSlice,
  };
}

// Diamond: run -> read + model; read + model -> bash (branch AND merge);
// tail linear: bash -> out. stray is outside the slice.
const NODES = [
  node("run", "run_start", 1),
  node("read", "tool_call", 2),
  node("model1", "model_call", 3),
  node("bash", "tool_call", 4),
  node("out", "tool_result", 5),
  node("stray", "context_update", 6, false),
];
const EDGES = [
  { parent: "run", child: "read" },
  { parent: "run", child: "model1" },
  { parent: "read", child: "bash" },
  { parent: "model1", child: "bash" },
  { parent: "bash", child: "out" },
];

function overview(): GraphOverview {
  return {
    source: "test",
    event_count: NODES.length,
    edge_count: EDGES.length,
    failure_event_id: "out",
    failure_status: "fallback_last_event",
    failure_method: "fallback",
    nodes: NODES,
    edges: EDGES,
  };
}

function record(inner: Record<string, unknown>, extra?: Partial<EventRecord>): EventRecord {
  return {
    event_type: "tool_call",
    agent_id: "opencode:ses_demo",
    logical_seq: 0,
    payload: { payload: inner },
    ...extra,
  };
}

function detail(id: string, inner: Record<string, unknown>, seq: number): EventDetail {
  return {
    id,
    label: `${seq}: tool_call`,
    role: null,
    in_failure_slice: true,
    parents: [],
    children: [],
    record: record(inner, { logical_seq: seq }),
  };
}

describe("sliceNodes", () => {
  it("keeps slice members in causal order", () => {
    assert.deepEqual(
      sliceNodes(overview()).map((n) => n.id),
      ["run", "read", "model1", "bash", "out"],
    );
  });
  it("degrades to empty, not an error", () => {
    assert.deepEqual(sliceNodes({ nodes: [], edges: [] } as unknown as GraphOverview), []);
  });
});

describe("branchPoints", () => {
  it("reports declared fan-out in causal order", () => {
    const pts = branchPoints(overview());
    assert.equal(pts.length, 1);
    assert.equal(pts[0].id, "run");
    assert.deepEqual([...pts[0].childIds].sort(), ["model1", "read"]);
  });
  it("ignores linear chains and dangling edges", () => {
    const o = overview();
    o.edges = [...EDGES, { parent: "ghost", child: "out" }, { parent: "bash", child: "ghost" }];
    assert.equal(branchPoints(o).length, 1);
  });
});

describe("mergePoints", () => {
  it("reports declared fan-in", () => {
    const pts = mergePoints(overview());
    assert.equal(pts.length, 1);
    assert.equal(pts[0].id, "bash");
    assert.deepEqual([...pts[0].parentIds].sort(), ["model1", "read"]);
  });
  it("empty on a linear chain", () => {
    const o = overview();
    o.edges = [
      { parent: "run", child: "read" },
      { parent: "read", child: "bash" },
      { parent: "bash", child: "out" },
    ];
    assert.deepEqual(branchPoints(o), []);
    assert.deepEqual(mergePoints(o), []);
  });
});

describe("traceCensus", () => {
  it("counts the dataset and the slice separately", () => {
    const c = traceCensus(overview());
    assert.equal(c.total, 6);
    assert.equal(c.sliceSize, 5);
    assert.deepEqual(c.byType, [
      { type: "run_start", count: 1 },
      { type: "tool_call", count: 2 },
      { type: "model_call", count: 1 },
      { type: "tool_result", count: 1 },
      { type: "context_update", count: 1 },
    ]);
    assert.ok(!c.sliceByType.some((t) => t.type === "context_update"));
  });
});

describe("baseName", () => {
  it("takes the suffix after the last slash", () => {
    assert.equal(baseName("file:///repo/app.py"), "app.py");
    assert.equal(baseName("app.py"), "app.py");
    assert.equal(baseName(""), "");
  });
});

const DETAILS: Array<EventDetail | null> = [
  detail("read", { tool: "read", args: { filePath: "/repo/app.py" } }, 2),
  detail("bash", { tool: "bash", args: { command: "python test_app.py" } }, 4),
  detail("out", { tool: "bash", output: "app tests pass" }, 5),
  null,
];

describe("resourcesInDetails", () => {
  it("discovers distinct recorded resources, skips nulls", () => {
    assert.deepEqual(resourcesInDetails(DETAILS), ["/repo/app.py"]);
  });
  it("nodesForResource matches exact or slash-suffix in causal order", () => {
    const got = nodesForResource(DETAILS, "app.py");
    assert.deepEqual(got.map((d) => d.id), ["read"]);
    assert.deepEqual(nodesForResource(DETAILS, "other.py"), []);
  });
});

describe("toolStory", () => {
  function byId(): Map<string, EventRecord> {
    const m = new Map<string, EventRecord>();
    for (const d of DETAILS) if (d) m.set(d.id, d.record);
    return m;
  }
  it("lists slice tool events with recorded tool and own command", () => {
    const story = toolStory(overview(), byId());
    assert.deepEqual(story.map((s) => s.id), ["read", "bash", "out"]);
    assert.equal(story[0].tool, "read");
    assert.equal(story[1].command, "python test_app.py");
    assert.equal(story[1].commandSource, null);
  });
  it("borrows a parent command with a source label, never a far event", () => {
    const story = toolStory(overview(), byId());
    const borrowed = story.find((s) => s.id === "out")!;
    assert.equal(borrowed.command, "python test_app.py");
    assert.equal(borrowed.commandSource, "tool_call · bash");
    // read's parent is run (no record): no command invented for it.
    assert.equal(story[0].command, null);
  });
  it("excludes non-tool events and empty inputs", () => {
    const story = toolStory(overview(), new Map());
    assert.ok(story.every((s) => s.eventType === "tool_call" || s.eventType === "tool_result"));
    assert.equal(story.find((s) => s.id === "bash")!.command, null);
  });
});
