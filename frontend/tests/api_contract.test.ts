// Contract checks between the Next.js frontend and the explorer API + demo
// dataset. Run with `npm test` (node --test, zero dependencies).
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontendDir = dirname(here);
const repoRoot = dirname(frontendDir);

const api = readFileSync(join(frontendDir, "lib", "api.ts"), "utf-8");
const page = readFileSync(join(frontendDir, "app", "page.tsx"), "utf-8");
const dag = readFileSync(join(frontendDir, "components", "DagView.tsx"), "utf-8");
const timeline = readFileSync(join(frontendDir, "components", "TimelineView.tsx"), "utf-8");
const inspector = readFileSync(join(frontendDir, "components", "Inspector.tsx"), "utf-8");
const header = readFileSync(join(frontendDir, "components", "Header.tsx"), "utf-8");
const whystrip = readFileSync(join(frontendDir, "components", "WhyStrip.tsx"), "utf-8");
const tabs = readFileSync(join(frontendDir, "components", "TabsPanels.tsx"), "utf-8");
const legend = readFileSync(join(frontendDir, "components", "Legend.tsx"), "utf-8");
const trace = JSON.parse(
  readFileSync(resolve(repoRoot, "explorer/demo/failed_test_retry_trace.json"), "utf-8"),
);
const spec = JSON.parse(
  readFileSync(resolve(repoRoot, "explorer/demo/failed_test_retry_spec.json"), "utf-8"),
);

describe("frontend api usage matches explorer server endpoints", () => {
  const endpoints = ["/api/overview", "/api/failure", "/api/diagnosis", "/api/evidence", "/api/event", "/api/ai-diagnosis"];
  for (const endpoint of endpoints) {
    it(`lib/api.ts calls ${endpoint}`, () => {
      assert.ok(api.includes(endpoint), `lib/api.ts missing fetch of ${endpoint}`);
    });
  }
  it("exactly six endpoints are declared", () => {
    const matches = api.match(/\/api\/[a-z-]+/g) ?? [];
    assert.deepEqual([...new Set(matches)].sort(), [...endpoints].sort());
  });
});

describe("opt-in AI analysis stays quarantined", () => {
  it("WhyStrip renders an explicit generate button", () => {
    assert.ok(whystrip.includes("Generate AI analysis"), "no explicit AI trigger button");
  });
  it("the interpretation block is labeled as not evidence", () => {
    assert.ok(
      whystrip.includes("Model interpretation — not evidence"),
      "AI block lacks the quarantine label",
    );
  });
  it("AI is never fetched on load (button click only)", () => {
    assert.ok(!whystrip.includes("useEffect"), "WhyStrip auto-fires AI on mount");
    assert.ok(
      whystrip.includes("onClick={generateAiAnalysis}"),
      "AI fetch is not wired to the button",
    );
  });
  it("model identity travels with the interpretation", () => {
    assert.ok(whystrip.includes("aiReport.model"), "model name not shown with AI text");
  });
});

describe("shared element ids across views", () => {
  const ids: Array<[string, string[]]> = [
    ["dag", [dag]],
    ["timeline", [timeline]],
    ["event-detail", [inspector]],
    ["failure-banner", [page, header]],
    ["failure-info", [page, whystrip]],
    ["diagnosis", [tabs]],
    ["evidence", [tabs]],
    ["dataset-line", [page]],
  ];
  for (const [id, sources] of ids) {
    it(`#${id} rendered`, () => {
      assert.ok(
        sources.some((s) => s.includes(`id="${id}"`)),
        `no component renders #${id}`,
      );
    });
  }
});

describe("timeline view hooks exist", () => {
  const hooks = ["tl-ruler", "tl-lane", "tl-playhead", "tl-edges", "tl-knob", "minimap-track", "mm-view", "mm-seg", "view-toggle"];
  for (const hook of hooks) {
    it(`.${hook} present`, () => {
      assert.ok(
        timeline.includes(hook) || page.includes(hook),
        `missing timeline hook ${hook}`,
      );
    });
  }
  it("clips are buttons with event aria-labels", () => {
    assert.ok(timeline.includes("aria-label={`Event"), "clips lack Event N type labels");
  });
  it("selection is announced via a live region", () => {
    assert.ok(page.includes('role="status"'), "no ARIA live region for selection");
  });
});

describe("demo dataset behind the explorer", () => {
  it("trace has envelopes", () => {
    assert.ok(Array.isArray(trace.envelopes) && trace.envelopes.length > 0);
  });
  it("spec has causal roles and a failure selector", () => {
    assert.ok(Array.isArray(spec.causal_roles) && spec.causal_roles.length > 0);
    assert.ok(spec.failure_selector && Array.isArray(spec.failure_selector.any));
  });
});

describe("graph node clicks reach the selection store", () => {  it("DagView never captures the pointer (capture retargets clicks to the svg, so node onClick would never fire)", () => {
    assert.ok(!dag.includes("setPointerCapture"), "DagView calls setPointerCapture: node clicks are swallowed");
  });
  it("node clicks call selectEvent", () => {
    assert.ok(dag.includes("onClick={onClick}"), "DAG nodes lack click wiring");
    assert.ok(dag.includes("selectEvent(n.id)"), "DAG node clicks do not select");
  });
});

describe("graph and timeline share one legend", () => {  it("Legend defines all five node states", () => {
    for (const sw of ["sw normal", "sw slice", "sw failure", "sw terminal", "sw selected"]) {
      assert.ok(legend.includes(sw), `Legend missing swatch ${sw}`);
    }
    for (const label of ["normal", "in failure slice", "failure target", "terminal", "selected"]) {
      assert.ok(legend.includes(label), `Legend missing label ${label}`);
    }
  });
  it("both views render the shared Legend component", () => {
    assert.ok(dag.includes("<Legend"), "DagView does not render <Legend>");
    assert.ok(timeline.includes("<Legend"), "TimelineView does not render <Legend>");
  });
  it("no view keeps its own copy of the legend markup", () => {
    assert.ok(!timeline.includes("sw slice"), "TimelineView still has an inline legend copy");
    assert.ok(!dag.includes("sw slice"), "DagView has an inline legend copy");
  });
});

describe("analysis tabs lead with trace facts, scoring stays collapsed", () => {
  it("interaction, evidence and metrics tabs receive the overview", () => {
    assert.ok(tabs.includes("<InteractionTab overview"), "InteractionTab lacks overview");
    assert.ok(tabs.includes("<EvidenceTab overview"), "EvidenceTab lacks overview");
    assert.ok(tabs.includes("<MetricsTab overview"), "MetricsTab lacks overview");
  });
  it("tab bodies use pure trace-fact helpers, not inline logic", () => {
    for (const fn of ["toolStory", "branchPoints", "mergePoints", "traceCensus", "resourcesInDetails", "nodesForResource"]) {
      assert.ok(tabs.includes(fn), `TabsPanels does not use ${fn}`);
    }
  });
  it("benchmark scoring is collapsed and discovery sections exist", () => {
    assert.ok(tabs.includes("Benchmark scoring"), "no collapsed scoring sections");
    assert.ok(tabs.includes("Discovered in this trace"), "no discovered-resources section");
  });
  it("honest empty states survive (no invented content)", () => {
    assert.ok(tabs.includes("linear chain"), "interaction loses its linear-trace note");
    assert.ok(tabs.includes("No tool calls or results"), "evidence loses its empty note");
  });
});
