// Regression tests: single shared selection state.
// Run with `npm test` (node --test).
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createSelectionStore, selectionStore } from "../lib/store.ts";

describe("shared selectedEventId", () => {
  it("starts unselected", () => {
    assert.equal(createSelectionStore().selectedId, null);
  });

  it("one store notifies every subscriber (DAG, timeline, inspector)", () => {
    const store = createSelectionStore();
    const seen: Array<[string, string | null]> = [];
    const unsubDag = store.subscribe((id) => seen.push(["dag", id]));
    const unsubTimeline = store.subscribe((id) => seen.push(["timeline", id]));
    const unsubInspector = store.subscribe((id) => seen.push(["inspector", id]));
    store.select("evt-1");
    assert.deepEqual(seen, [["dag", "evt-1"], ["timeline", "evt-1"], ["inspector", "evt-1"]]);
    unsubDag();
    unsubTimeline();
    unsubInspector();
  });

  it("re-selecting the same id does not re-notify", () => {
    const store = createSelectionStore();
    let calls = 0;
    store.subscribe(() => {
      calls += 1;
    });
    store.select("evt-1");
    store.select("evt-1");
    assert.equal(calls, 1);
  });

  it("selecting five different nodes yields five distinct selections", () => {
    const store = createSelectionStore();
    const history: Array<string | null> = [];
    store.subscribe((id) => history.push(id));
    for (const id of ["a", "b", "c", "d", "e"]) store.select(id);
    assert.deepEqual(history, ["a", "b", "c", "d", "e"]);
    assert.equal(store.selectedId, "e");
  });

  it("unsubscribe stops notifications", () => {
    const store = createSelectionStore();
    let calls = 0;
    const unsub = store.subscribe(() => {
      calls += 1;
    });
    unsub();
    store.select("evt-1");
    assert.equal(calls, 0);
  });

  it("the shared singleton is a single selection state", () => {
    const seen: Array<string | null> = [];
    const unsub = selectionStore.subscribe((id) => seen.push(id));
    selectionStore.select("shared-probe");
    assert.ok(seen.includes("shared-probe"));
    assert.equal(selectionStore.selectedId, "shared-probe");
    unsub();
  });
});
