// Regression tests: DAG/timeline styling sync + inspector rows.
// These pin the exact class logic the views apply, so DAG and timeline can
// never drift into separate selection states. Run with `npm test`.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  nodeClassNames,
  tickClassNames,
  inspectorFieldRows,
  firstSentence,
  capabilityFlags,
  metricsSummary,
  eventReferencesResource,
} from "../lib/render.ts";
import type { EventDetail } from "../lib/types.ts";

const NODES = [
  { id: "a", event_type: "run_start", in_failure_slice: true, role: null },
  { id: "b", event_type: "tool_call", in_failure_slice: true, role: "fix_edit" },
  { id: "c", event_type: "tool_result", in_failure_slice: false, role: null },
  { id: "f", event_type: "run_finish", in_failure_slice: true, role: "retry_success" },
];

describe("DAG node styling", () => {
  it("selected node is highlighted, ancestors lit, others dimmed", () => {
    const lit = new Set(["a", "b"]);
    assert.ok(nodeClassNames(NODES[1], { selectedId: "b", failureId: "x", litSet: lit }).includes("selected"));
    assert.ok(!nodeClassNames(NODES[1], { selectedId: "b", failureId: "x", litSet: lit }).includes("dim"));
    const dimmed = nodeClassNames(NODES[2], { selectedId: "b", failureId: "x", litSet: lit });
    assert.ok(dimmed.includes("dim") && !dimmed.includes("selected"));
  });

  it("failure node is prominent and slice members marked", () => {
    const cls = nodeClassNames(NODES[3], { selectedId: null, failureId: "f", litSet: null });
    assert.ok(cls.includes("failure") && cls.includes("in-slice"));
  });

  it("nothing is dimmed before any selection", () => {
    for (const n of NODES) {
      assert.ok(!nodeClassNames(n, { selectedId: null, failureId: "f", litSet: null }).includes("dim"));
    }
  });
});

describe("DAG <-> timeline synchronization", () => {
  it("same selection id drives both class computations", () => {
    const ctx = { selectedId: "b", failureId: "f" };
    assert.ok(nodeClassNames(NODES[1], { ...ctx, litSet: new Set(["b"]) }).includes("selected"));
    assert.ok(tickClassNames(NODES[1], ctx).includes("selected"));
    assert.ok(!tickClassNames(NODES[0], ctx).includes("selected"));
  });

  it("timeline distinguishes normal / causal / failure / terminal / selected", () => {
    const ctx = { selectedId: "b", failureId: "f" };
    assert.equal(tickClassNames(NODES[0], { selectedId: null, failureId: "f" }), "tick in-slice");
    assert.ok(tickClassNames(NODES[2], { selectedId: null, failureId: "f" }).split(" ").includes("tick"));
    assert.ok(!tickClassNames(NODES[2], { selectedId: null, failureId: "f" }).includes("in-slice"));
    const failureTick = tickClassNames(NODES[3], ctx);
    assert.ok(failureTick.includes("failure") && failureTick.includes("terminal"));
    assert.ok(tickClassNames(NODES[1], ctx).includes("selected"));
  });
});

describe("inspector rows for multiple nodes", () => {
  function detailFor(id: string, tool: string | null, command: string): EventDetail {
    return {
      id,
      label: id,
      role: id === "b" ? "fix_edit" : null,
      in_failure_slice: true,
      record: {
        event_type: tool ? "tool_call" : "run_start",
        agent_id: "agent-1",
        logical_seq: 3,
        wall_time: "2026-01-01T00:00:00+00:00",
        payload: {
          model: "demo-model",
          session_id: "ses-1",
          timestamp: "2026-01-01T00:00:00+00:00",
          payload: tool ? { tool, callID: "call-9", args: { command } } : {},
        },
      },
      parents: [],
      children: [],
    };
  }

  it("five different events produce five distinct structured rows", () => {
    const rows = ["e1", "e2", "e3", "e4", "e5"].map((id, i) =>
      inspectorFieldRows(detailFor(id, "bash", `cmd-${i}`)));
    const idRows = rows.map((r) => r.find(([k]) => k === "Event ID")?.[1]);
    assert.deepEqual(idRows, ["e1", "e2", "e3", "e4", "e5"]);
    const cmdRows = rows.map((r) => r.find(([k]) => k === "Command")?.[1]);
    assert.deepEqual(cmdRows, ["cmd-0", "cmd-1", "cmd-2", "cmd-3", "cmd-4"]);
  });

  it("every row set carries the full structured field list (no raw dump)", () => {
    const labels = inspectorFieldRows(detailFor("e1", "bash", "x")).map(([k]) => k);
    for (const expected of ["Type", "Event ID", "Role", "Agent", "Model", "Sequence",
      "Timestamp", "Tool", "Call ID", "Command", "File / resource", "Session"]) {
      assert.ok(labels.includes(expected), `missing ${expected}`);
    }
  });

  it("missing data degrades to em-dashes, never undefined", () => {
    const rows = inspectorFieldRows({ id: "e", label: "e", role: null, in_failure_slice: false, record: {}, parents: [], children: [] });
    for (const [, v] of rows) assert.ok(v !== undefined && v !== "undefined");
  });
});

describe("diagnosis text helpers", () => {
  it("lede is the first sentence of the backend summary", () => {
    assert.equal(firstSentence("First fact. Second fact."), "First fact.");
    assert.equal(firstSentence("  Spaced   out.  Tail. "), "Spaced out.");
    assert.equal(firstSentence(""), "");
  });

  it("capability flags surface unsupported / not_measurable neutrally", () => {
    const flags = capabilityFlags({ metric: "joint_ancestry", causal_interaction: "not_measurable", recall: 1 });
    assert.deepEqual(flags, [{ key: "causal_interaction", value: "not_measurable" }]);
    assert.deepEqual(capabilityFlags({ recall: 1 }), []);
    assert.deepEqual(capabilityFlags(null), []);
  });

  it("run_finish DAG nodes carry the terminal state", () => {
    const cls = nodeClassNames(NODES[3], { selectedId: null, failureId: "x", litSet: null });
    assert.ok(cls.includes("terminal"));
    assert.ok(!nodeClassNames(NODES[1], { selectedId: null, failureId: "x", litSet: null }).includes("terminal"));
  });
});

describe("metrics summary", () => {
  const DIMS = {
    causal_slice: { status: "ok", size: 8 },
    minimal_slice: { status: "ok", size: 3, causal_minimality: "not_measurable" },
    distractors: { status: "ok", leaked: 0 },
    interaction: { status: "ok", causal_interaction: "unsupported" },
  };

  it("leads with plain-language rows, not raw metric fields", () => {
    const rows = metricsSummary(DIMS);
    const byLabel = Object.fromEntries(rows.map((r) => [r.label, r.value]));
    assert.equal(byLabel["Structural evidence"], "8 events");
    assert.equal(byLabel["Required-cause evidence"], "3 events");
    assert.equal(byLabel["Distractors"], "0");
  });

  it("unmeasurable capabilities read as neutral facts, never failures", () => {
    const byLabel = Object.fromEntries(metricsSummary(DIMS).map((r) => [r.label, r.value]));
    assert.equal(byLabel["Causal minimality"], "Not measurable from this trace");
    assert.equal(byLabel["Causal interaction"], "Unsupported for this trace");
    for (const { value: v } of metricsSummary(DIMS)) assert.ok(!/fail/i.test(v), `reads as failure: ${v}`);
  });

  it("degrades gracefully without a diagnosis", () => {
    assert.deepEqual(metricsSummary(null), []);
    assert.deepEqual(metricsSummary({}), [
      { label: "Structural evidence", value: "—" },
      { label: "Required-cause evidence", value: "—" },
      { label: "Distractors", value: "—" },
      { label: "Causal minimality", value: "—" },
      { label: "Causal interaction", value: "—" },
    ]);
  });
});

describe("resource reference matching", () => {
  function recordWith({ resource_uri, filePath, file }: { resource_uri?: string; filePath?: string; file?: string } = {}) {
    return { payload: { resource_uri, payload: { tool: "edit", args: { filePath }, file } } };
  }

  it("matches resource_uri, args paths, and file fields", () => {
    assert.ok(eventReferencesResource(recordWith({ resource_uri: "file://app.py" }), "app.py"));
    assert.ok(eventReferencesResource(recordWith({ filePath: "work/app.py" }), "app.py"));
    assert.ok(eventReferencesResource(recordWith({ file: "task.py" }), "task.py"));
  });

  it("rejects near-miss names and missing data", () => {
    assert.ok(!eventReferencesResource(recordWith({ file: "myapp.py" }), "app.py"));
    assert.ok(!eventReferencesResource(recordWith({}), "app.py"));
    assert.ok(!eventReferencesResource(null, "app.py"));
    assert.ok(!eventReferencesResource(recordWith({ file: "app.py" }), ""));
  });
});
