// Regression tests: viewport math (fit-to-view, pan, zoom, drag-vs-click).
// Run with `npm test` (node --test).
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  FIT_VIEW,
  fitZoomMax,
  layoutBounds,
  layoutPositions,
  resetView,
  panBy,
  zoomAt,
  clickSuppressed,
} from "../lib/viewport.ts";

describe("fit-to-view", () => {
  it("identity transform shows all content (viewBox spans the bounds)", () => {
    assert.deepEqual(resetView(), { k: 1, tx: 0, ty: 0 });
    assert.deepEqual(FIT_VIEW, { k: 1, tx: 0, ty: 0 });
  });

  it("reset restores the fitted state from any pan/zoom", () => {
    const moved = panBy(zoomAt(resetView(), 10, 10, 3), 50, -20);
    assert.notDeepEqual(moved, resetView());
    assert.deepEqual(resetView(), { k: 1, tx: 0, ty: 0 });
  });

  it("layout bounds leave room so edge labels never clip", () => {
    const bounds = layoutBounds(10, 9);
    assert.ok(bounds.w >= 10 * 110 + 100 + 160, `width ${bounds.w} too small for labels`);
    assert.ok(bounds.h >= 120 + 9 * 64, `height ${bounds.h} too small`);
  });

  it("empty and single-node graphs still get a usable viewport", () => {
    assert.ok(layoutBounds(0, 0).w >= 600);
    assert.ok(layoutBounds(1, 0).h > 0);
  });
});

describe("pan and zoom preserve the graph", () => {
  it("pan only translates", () => {
    assert.deepEqual(panBy({ k: 2, tx: 1, ty: 1 }, 5, -3), { k: 2, tx: 6, ty: -2 });
  });

  it("zoom keeps the cursor-anchored content point fixed", () => {
    const before = { k: 1, tx: 0, ty: 0 };
    const after = zoomAt(before, 100, 50, 2);
    assert.equal(after.k, 2);
    const contentBefore = (100 - before.tx) / before.k;
    const contentAfter = (100 - after.tx) / after.k;
    assert.equal(contentBefore, contentAfter);
  });

  it("zoom clamps to sane limits", () => {
    assert.equal(zoomAt({ k: 1, tx: 0, ty: 0 }, 0, 0, 1000).k, 10);
    assert.equal(zoomAt({ k: 1, tx: 0, ty: 0 }, 0, 0, 0.0001).k, 0.2);
  });
});

describe("drag vs click", () => {
  it("small pointer travel is a click (selects the node)", () => {
    assert.equal(clickSuppressed(2, 2), false);
    assert.equal(clickSuppressed(0, 0), false);
  });

  it("large pointer travel is a drag (must not select)", () => {
    assert.equal(clickSuppressed(20, 0), true);
    assert.equal(clickSuppressed(4, 5), true);
  });
});

describe("layoutPositions", () => {
  const linear = [
    { id: "a", logical_seq: 1 },
    { id: "b", logical_seq: 2 },
    { id: "c", logical_seq: 3 },
  ];
  const linearEdges = [
    { parent: "a", child: "b" },
    { parent: "b", child: "c" },
  ];

  it("orders x by causal sequence for a linear chain", () => {
    const { ordered, pos, bounds } = layoutPositions(linear, linearEdges);
    assert.deepEqual(ordered.map((n) => n.id), ["a", "b", "c"]);
    assert.ok(pos["a"].x < pos["b"].x && pos["b"].x < pos["c"].x);
    assert.ok(pos["a"].y < pos["b"].y && pos["b"].y < pos["c"].y, "chain descends one lane per hop");
    const maxX = Math.max(pos["a"].x, pos["b"].x, pos["c"].x);
    assert.ok(maxX < bounds.w - 100, "rightmost node stays inside padded bounds");
  });

  it("fans branches apart without inventing edges", () => {
    const nodes = [...linear, { id: "d", logical_seq: 4 }];
    const edges = [...linearEdges, { parent: "b", child: "d" }];
    const { pos, depth } = layoutPositions(nodes, edges);
    assert.equal(depth["d"], 2);
    assert.ok(pos["d"].x !== pos["c"].x, "branch child never overlaps its lane-mate");
    assert.ok(pos["d"].y > pos["b"].y && pos["c"].y > pos["b"].y, "children sit below their parent");
    const spots = new Set(Object.values(pos).map((p) => `${p.x},${p.y}`));
    assert.equal(spots.size, 4, "every node owns a distinct position");
  });

  it("merges converge back to a deeper lane", () => {
    const nodes = [...linear, { id: "d", logical_seq: 4 }];
    const edges = [...linearEdges, { parent: "a", child: "d" }, { parent: "c", child: "d" }];
    const { depth } = layoutPositions(nodes, edges);
    assert.equal(depth["d"], 3);
  });

  it("handles empty and cyclic input without throwing", () => {
    assert.deepEqual(layoutPositions([], []).ordered, []);
    const cyclic = layoutPositions([{ id: "a", logical_seq: 1 }], [{ parent: "a", child: "a" }]);
    assert.ok(Number.isFinite(cyclic.pos["a"].x) && Number.isFinite(cyclic.pos["a"].y));
  });
});


describe("content-aware max zoom", () => {
  it("keeps the historic 10x floor for small graphs", () => {
    assert.equal(fitZoomMax(600), 10);
    assert.equal(fitZoomMax(2460), 10);
  });

  it("scales up so labels stay reachable in huge traces", () => {
    assert.equal(fitZoomMax(179000), 179000 / 600);
    assert.ok(fitZoomMax(179000) > 10);
  });

  it("degrades safely on non-positive widths", () => {
    assert.equal(fitZoomMax(0), 10);
    assert.equal(fitZoomMax(-5), 10);
    assert.equal(fitZoomMax(NaN), 10);
  });
});

