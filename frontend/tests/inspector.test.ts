// Regression tests: inspector command/result correlation + default selection.
// Pure helpers in lib/render.ts; run with `npm test`.
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  commandForEvent,
  resultForEvent,
  defaultSelectedId,
  inspectorFieldRows,
} from "../lib/render.ts";
import type { EventRecord, GraphOverview } from "../lib/types.ts";

const toolCall: EventRecord = {
  event_type: "tool_call",
  payload: {
    payload: {
      tool: "bash",
      callID: "rec-call-1",
      args: { command: "python test_app.py" },
    },
  },
};

const toolResult: EventRecord = {
  event_type: "tool_result",
  payload: {
    payload: {
      tool: "bash",
      callID: "rec-call-1",
      output: "Traceback (most recent call last):\nAssertionError: 23",
      metadata: {},
    },
  },
};

const editCall: EventRecord = {
  event_type: "tool_call",
  payload: {
    payload: { tool: "edit", callID: "rec-call-2", args: { filePath: "app.py" } },
  },
};

describe("tool call command", () => {
  it("a tool_call displays its own command with no correlated source", () => {
    const found = commandForEvent(toolCall, []);
    assert.equal(found.command, "python test_app.py");
    assert.equal(found.source, null);
  });
});

describe("tool result parent command", () => {
  it("a bash tool_result displays its parent tool_call command with source", () => {
    const found = commandForEvent(toolResult, [toolCall]);
    assert.equal(found.command, "python test_app.py");
    assert.equal(found.source, "tool_call · bash");
  });

  it("prefers the first related record that carries a command", () => {
    const found = commandForEvent(toolResult, [editCall, toolCall]);
    assert.equal(found.command, "python test_app.py");
  });
});

describe("result and error output", () => {
  it("a tool_result exposes its recorded output without inventing a status", () => {
    const res = resultForEvent(toolResult, []);
    assert.ok((res.output ?? "").includes("AssertionError"));
    assert.equal(res.status, null);
    assert.equal(res.outputSource, null);
  });

  it("a tool_call borrows result output from its child tool_result", () => {
    const res = resultForEvent(toolCall, [toolResult]);
    assert.ok((res.output ?? "").includes("AssertionError"));
    assert.equal(res.outputSource, "tool_result");
  });

  it("explicit exit codes are surfaced as status", () => {
    const rec: EventRecord = {
      event_type: "tool_result",
      payload: { payload: { tool: "bash", exitCode: 1, output: "boom" } },
    };
    assert.equal(resultForEvent(rec, []).status, "1");
  });
});

describe("missing command handling", () => {
  it("returns nulls when no record carries a command", () => {
    assert.deepEqual(commandForEvent(editCall, [toolResult]), { command: null, source: null });
    assert.deepEqual(commandForEvent(editCall, []), { command: null, source: null });
  });

  it("inspector rows degrade to em-dashes, never blanks", () => {
    const rows = inspectorFieldRows({
      id: "x",
      label: "x",
      role: null,
      in_failure_slice: false,
      record: { event_type: "run_start", payload: {} },
      parents: [],
      children: [],
    });
    const byLabel = new Map(rows);
    assert.equal(byLabel.get("Command"), "—");
    assert.equal(byLabel.get("Tool"), "—");
    assert.equal(byLabel.get("File / resource"), "—");
  });
});

describe("failure event selected by default", () => {
  const nodes = [
    { id: "a", event_type: "run_start", opencode_kind: "", agent_id: "", logical_seq: 1, wall_time: "", label: "a", role: null, in_failure_slice: false },
    { id: "b", event_type: "tool_call", opencode_kind: "", agent_id: "", logical_seq: 2, wall_time: "", label: "b", role: null, in_failure_slice: false },
    { id: "c", event_type: "tool_result", opencode_kind: "", agent_id: "", logical_seq: 3, wall_time: "", label: "c", role: null, in_failure_slice: false },
  ];
  const overview = (failure_event_id: string | null): GraphOverview => ({
    source: "test",
    event_count: 3,
    edge_count: 0,
    failure_event_id,
    failure_status: null,
    failure_method: null,
    nodes,
    edges: [],
  });

  it("prefers the resolved failure target over run order", () => {
    assert.equal(defaultSelectedId(overview("b")), "b");
  });

  it("falls back to the last event by causal order without a failure", () => {
    assert.equal(defaultSelectedId(overview(null)), "c");
  });

  it("returns null for an empty dataset", () => {
    assert.equal(defaultSelectedId({ ...overview(null), nodes: [] }), null);
    assert.equal(defaultSelectedId(null), null);
  });
});
