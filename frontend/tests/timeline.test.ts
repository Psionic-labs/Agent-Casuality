// Regression tests: Timeline-view pure logic — lane grouping, clip
// geometry, ancestor-chain edge paths, shared-store sync, visible-window
// culling, and keyboard-step clamping. Run with `npm test`.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createSelectionStore } from "../lib/store.ts";
import {
  ancestorChainPath,
  ancestorChainSegments,
  ancestorsOf,
  clipX,
  contentWidth,
  fitScale,
  groupLanes,
  parentMap,
  stepIndex,
  visibleWindow,
} from "../lib/timeline.ts";
import type { OverviewNode } from "../lib/types.ts";

function node(id: string, event_type: string, logical_seq: number): OverviewNode {
  return {
    id,
    event_type,
    opencode_kind: "",
    agent_id: "",
    logical_seq,
    wall_time: "",
    label: `${logical_seq}: ${event_type}`,
    role: null,
    in_failure_slice: true,
  };
}

// Demo-shaped trace: run_start, file edit result (no tool), model, bash
// call/result, edit call/result, bash call/result (failure), run_finish.
const ORDERED = [
  node("run", "run_start", 1),
  node("edit0", "tool_result", 1),
  node("model", "model_call", 2),
  node("bash1", "tool_call", 3),
  node("bash1r", "tool_result", 4),
  node("edit1", "tool_call", 5),
  node("edit1r", "tool_result", 6),
  node("bash2", "tool_call", 7),
  node("bash2r", "tool_result", 8),
  node("fin", "run_finish", 9),
];
const TOOLS = new Map([
  ["bash1", "bash"],
  ["bash1r", "bash"],
  ["edit1", "edit"],
  ["edit1r", "edit"],
  ["bash2", "bash"],
  ["bash2r", "bash"],
]);

describe("lane grouping and ordering", () => {
  it("groups run, model, then one lane per tool in first-appearance order", () => {
    const lanes = groupLanes(ORDERED, TOOLS);
    assert.deepEqual(lanes.map((l) => l.key), ["run", "model", "bash", "edit", "other"]);
    assert.deepEqual(lanes[0].events.map((n) => n.id), ["run", "fin"]);
    assert.deepEqual(lanes[2].events.map((n) => n.id), ["bash1", "bash1r", "bash2", "bash2r"]);
  });

  it("puts tool events with unknown tools in other, never inventing a lane", () => {
    const lanes = groupLanes(ORDERED, new Map());
    const other = lanes.find((l) => l.key === "other");
    assert.ok(other, "missing other lane");
    assert.ok(other.events.some((n) => n.id === "edit0"), "tool-less event misplaced");
    assert.ok(!lanes.some((l) => l.key !== "other" && l.events.some((n) => n.id === "edit0")));
  });

  it("lanes keep causal order within and the full event set across", () => {
    const lanes = groupLanes(ORDERED, TOOLS);
    for (const lane of lanes) {
      const seqs = lane.events.map((n) => n.logical_seq);
      assert.deepEqual([...seqs].sort((a, b) => a - b), seqs, `lane ${lane.key} out of order`);
    }
    assert.equal(lanes.flatMap((l) => l.events).length, ORDERED.length);
  });
});

describe("clip x-position from sequence index", () => {
  it("positions clips by index with a fixed step", () => {
    assert.equal(clipX(0, 120), 0);
    assert.equal(clipX(1, 120), 128);
    assert.equal(clipX(9, 120), 9 * 128);
  });

  it("content width spans first clip start to last clip end", () => {
    assert.equal(contentWidth(10, 120), 9 * 128 + 120);
    assert.equal(contentWidth(0, 120), 0);
  });

  it("fit-all never zooms in beyond 1x", () => {
    assert.equal(fitScale(2000, 1000), 1);
    assert.ok(Math.abs(fitScale(640, 1400) - 640 / 1400) < 1e-9);
    assert.equal(fitScale(0, 0), 1);
  });
});

describe("ancestor-chain edge path", () => {
  const edges = [
    { parent: "run", child: "model" },
    { parent: "model", child: "bash1" },
    { parent: "bash1", child: "bash1r" },
    { parent: "bash1r", child: "edit1" },
  ];
  const parents = parentMap(edges);

  it("emits one path step per declared ancestor edge of the selection", () => {
    const segments = ancestorChainSegments("edit1", parents);
    assert.equal(segments.length, 4);
    const centers = new Map([
      ["run", { x: 0, y: 0 }],
      ["model", { x: 10, y: 10 }],
      ["bash1", { x: 20, y: 20 }],
      ["bash1r", { x: 30, y: 30 }],
      ["edit1", { x: 40, y: 40 }],
    ]);
    const d = ancestorChainPath(segments, (id) => centers.get(id) ?? null);
    assert.equal(d.split("M ").length - 1, 4);
    assert.ok(d.includes("0 0"), "path misses the chain start");
  });

  it("draws no lines for events with no declared parents", () => {
    assert.deepEqual(ancestorChainSegments("run", parents), []);
    assert.equal(ancestorChainPath([], () => ({ x: 0, y: 0 })), "");
    assert.deepEqual(ancestorChainSegments(null, parents), []);
  });

  it("never follows undeclared links", () => {
    // bash2r has no declared parents: no segments even though it shares a lane.
    assert.deepEqual(ancestorChainSegments("bash2r", parents), []);
    assert.ok(!ancestorsOf("bash2r", parents).size);
  });
});

describe("selection sync: one store drives both views", () => {
  it("graph and timeline selections are the same store read", () => {
    const store = createSelectionStore();
    const graphSeen: Array<string | null> = [];
    const timelineSeen: Array<string | null> = [];
    const unsubs = [
      store.subscribe((id) => graphSeen.push(id)),
      store.subscribe((id) => timelineSeen.push(id)),
    ];
    store.select("bash2r");
    assert.deepEqual(graphSeen, ["bash2r"]);
    assert.deepEqual(timelineSeen, ["bash2r"]);
    assert.equal(store.selectedId, "bash2r");
    unsubs.forEach((u) => u());
  });
});

describe("visible-window culling for a 900+ event trace", () => {
  const COUNT = 934;
  const UNIT = 120;

  it("mounts only clips intersecting the window", () => {
    const total = contentWidth(COUNT, UNIT);
    // First viewport: only the head of the trace.
    const head = visibleWindow(0, 1200, COUNT, UNIT);
    assert.equal(head.start, 0);
    assert.ok(head.end < 20 && head.end > 0, `head window too wide: ${JSON.stringify(head)}`);
    // Mid-trace viewport: a narrow slice far from both ends.
    const mid = visibleWindow(60000, 1200, COUNT, UNIT);
    assert.ok(mid.start > 400 && mid.end - mid.start < 20, `mid window off: ${JSON.stringify(mid)}`);
    // Degenerate inputs mount nothing.
    assert.deepEqual(visibleWindow(0, 0, COUNT, UNIT), { start: 0, end: 0 });
    assert.deepEqual(visibleWindow(0, 1200, 0, UNIT), { start: 0, end: 0 });
    assert.ok(total > 100000, "sanity: live-scale content is wide");
  });
});

describe("keyboard step clamps at the first and last event", () => {
  it("steps within range and clamps at both ends", () => {
    assert.equal(stepIndex(4, 1, 10), 5);
    assert.equal(stepIndex(4, -1, 10), 3);
    assert.equal(stepIndex(0, -1, 10), 0);
    assert.equal(stepIndex(9, 1, 10), 9);
    assert.equal(stepIndex(-1, 1, 10), 0);
  });

  it("reports -1 when there is nothing to step through", () => {
    assert.equal(stepIndex(0, 1, 0), -1);
  });
});
