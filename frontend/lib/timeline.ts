/* Pure Timeline-view logic: lane grouping, clip geometry, ancestor-chain
 * edge paths, visible-window culling, and keyboard stepping. No DOM access:
 * the React components in components/TimelineView.tsx only position what
 * these helpers compute. All causality comes from declared edges. */

import { toolForEvent } from "./render.ts";
import type { OverviewEdge, OverviewNode } from "./types.ts";

export interface TimelineLane {
  /** Lane key: "run" | "model" | "context" | tool name | "other". */
  key: string;
  /** Events in causal (logical_seq) order. */
  events: OverviewNode[];
}

/** Group sequence-ordered events into Premiere-style lanes: run
 * (run_start, run_finish), model (model_call), context (context_update),
 * then one lane per tool name in order of first appearance. Tool names come
 * from fetched /api/event details (toolById); tool events whose tool is
 * unknown — and any other unclassified type — fall into a trailing "other"
 * lane rather than an invented tool lane. */
export function groupLanes(
  ordered: OverviewNode[],
  toolById: ReadonlyMap<string, string>,
): TimelineLane[] {
  const lanes: TimelineLane[] = [];
  const byKey = new Map<string, TimelineLane>();
  const push = (key: string, node: OverviewNode): void => {
    let lane = byKey.get(key);
    if (!lane) {
      lane = { key, events: [] };
      byKey.set(key, lane);
      lanes.push(lane);
    }
    lane.events.push(node);
  };
  for (const node of ordered) {
    push(toolForEvent(node.event_type, toolById, node.id) ?? "other", node);
  }
  // Fixed lane order: run, model, context, tools (first-appearance order),
  // other last — regardless of which appears first in the trace.
  const rank = (key: string): [number, number] => {
    if (key === "run") return [0, 0];
    if (key === "model") return [1, 0];
    if (key === "context") return [2, 0];
    if (key === "other") return [4, 0];
    return [3, lanes.findIndex((l) => l.key === key)];
  };
  return [...lanes].sort((a, b) => {
    const [ra, ia] = rank(a.key);
    const [rb, ib] = rank(b.key);
    return ra - rb || ia - ib;
  });
}

/** X (content units) of the clip for the i-th event in sequence order. */
export function clipX(index: number, unit: number, gap = 8): number {
  return index * (unit + gap);
}

/** Total content width for `count` clips at the given unit size. */
export function contentWidth(count: number, unit: number, gap = 8): number {
  return count === 0 ? 0 : clipX(count - 1, unit, gap) + unit;
}

/** Fit-all zoom for a container: scale the whole sequence into view. */
export function fitScale(containerW: number, totalW: number): number {
  if (totalW <= 0 || containerW <= 0) return 1;
  return Math.min(1, containerW / totalW);
}

/** Index range of clips intersecting the visible window (plus one clip of
 * margin each side), so large traces mount only visible clips. Returns
 * {start, end} with end exclusive; {0, 0} when nothing is visible. */
export function visibleWindow(
  viewLeft: number,
  viewWidth: number,
  count: number,
  unit: number,
  gap = 8,
): { start: number; end: number } {
  if (count === 0 || viewWidth <= 0) return { start: 0, end: 0 };
  const step = unit + gap;
  const start = Math.max(0, Math.floor(viewLeft / step) - 1);
  const end = Math.min(count, Math.ceil((viewLeft + viewWidth) / step) + 1);
  if (end <= start) return { start: 0, end: 0 };
  return { start, end };
}

/** Step the selection through sequence order, clamped to both ends. */
export function stepIndex(current: number, delta: number, count: number): number {
  if (count <= 0) return -1;
  return Math.min(count - 1, Math.max(0, current + delta));
}

export interface ChainSegment {
  fromId: string;
  toId: string;
}

/** Declared ancestor-chain edges touching the selected event: every edge
 * whose parent AND child are both in the selected event's ancestor set
 * (selected event included). Walks real causal_parent_ids only; events with
 * no declared parents yield no segments. */
export function ancestorChainSegments(
  selectedId: string | null,
  parentOf: ReadonlyMap<string, string[]>,
): ChainSegment[] {
  if (!selectedId) return [];
  const lit = new Set<string>([selectedId]);
  const stack = [...(parentOf.get(selectedId) ?? [])];
  while (stack.length > 0) {
    const cur = stack.pop() as string;
    if (lit.has(cur)) continue;
    lit.add(cur);
    for (const p of parentOf.get(cur) ?? []) stack.push(p);
  }
  const segments: ChainSegment[] = [];
  for (const [child, parents] of parentOf) {
    if (!lit.has(child)) continue;
    for (const parent of parents) {
      if (lit.has(parent)) segments.push({ fromId: parent, toId: child });
    }
  }
  return segments;
}

/** A single SVG path (content units) connecting ancestor-chain clip centers:
 * one horizontal-then-diagonal step per segment, in deterministic order.
 * Returns "" when there is nothing to draw. */
export function ancestorChainPath(
  segments: ChainSegment[],
  centerOf: (id: string) => { x: number; y: number } | null,
): string {
  const parts: string[] = [];
  const ordered = [...segments].sort((a, b) =>
    a.fromId < b.fromId ? -1 : a.fromId > b.fromId ? 1 : a.toId < b.toId ? -1 : 1,
  );
  for (const s of ordered) {
    const a = centerOf(s.fromId);
    const b = centerOf(s.toId);
    if (!a || !b) continue;
    parts.push(`M ${a.x} ${a.y} L ${(a.x + b.x) / 2} ${a.y} L ${(a.x + b.x) / 2} ${b.y} L ${b.x} ${b.y}`);
  }
  return parts.join(" ");
}

/** Build a child→parents map from declared overview edges (deduplicated). */
export function parentMap(edges: OverviewEdge[]): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const e of edges) {
    if (!e || e.parent === undefined || e.child === undefined) continue;
    const list = map.get(e.child) ?? [];
    if (!list.includes(e.parent)) list.push(e.parent);
    map.set(e.child, list);
  }
  return map;
}

/** Full ancestor set of an event (excluding itself), walking real edges. */
export function ancestorsOf(id: string, parentOf: ReadonlyMap<string, string[]>): Set<string> {
  const seen = new Set<string>([id]);
  const stack = [...(parentOf.get(id) ?? [])];
  while (stack.length > 0) {
    const cur = stack.pop() as string;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const p of parentOf.get(cur) ?? []) stack.push(p);
  }
  seen.delete(id);
  return seen;
}
