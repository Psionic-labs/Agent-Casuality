/* Pure viewport math: fit-to-view, pan, zoom, and drag-vs-click detection.
 * Operates on plain {k, tx, ty} view objects so it is unit-testable without
 * a DOM. Relative imports carry explicit `.ts` extensions so these modules
 * load both in Next.js and directly under node --test. */

export interface View {
  k: number;
  tx: number;
  ty: number;
}

export const FIT_VIEW: View = Object.freeze({ k: 1, tx: 0, ty: 0 });

/** Content bounds for the layered DAG layout, with room for node labels. */
export function layoutBounds(
  nodeCount: number,
  maxDepth: number,
  colW = 110,
  rowH = 64,
): { w: number; h: number } {
  const w = Math.max(600, nodeCount * colW + 100 + 160); // +160: right-side labels never clip
  const h = 120 + Math.max(0, maxDepth) * rowH + 40; // +40: bottom labels never clip
  return { w, h };
}

/**
 * Fit state for a viewBox that already spans the content bounds:
 * identity transform shows every node, centered by construction.
 */
export function resetView(): View {
  return { k: 1, tx: 0, ty: 0 };
}

export function panBy(view: View, dx: number, dy: number): View {
  return { k: view.k, tx: view.tx + dx, ty: view.ty + dy };
}

/** Zoom around a cursor point given in content units. */
export function zoomAt(
  view: View,
  cx: number,
  cy: number,
  factor: number,
  min = 0.2,
  max = 10,
): View {
  const k2 = Math.min(max, Math.max(min, view.k * factor));
  return {
    k: k2,
    tx: cx - ((cx - view.tx) / view.k) * k2,
    ty: cy - ((cy - view.ty) / view.k) * k2,
  };
}

/** True when pointer travel exceeds the click threshold → it was a drag. */
export function clickSuppressed(dx: number, dy: number, threshold = 6): boolean {
  return Math.hypot(dx, dy) > threshold;
}

/** Upper zoom clamp scaled to content width: at max zoom roughly one
 * screenful of content units (~600) fills the screen, so node labels stay
 * reachable in traces of any size. Never below the historic 10x, so small
 * graphs behave exactly as before. */
export function fitZoomMax(boundsW: number, screenful = 600, floor = 10): number {
  if (!(boundsW > 0)) return floor;
  return Math.max(floor, boundsW / screenful);
}

export interface LayoutNode {
  id: string;
  logical_seq: number;
}

export interface LayoutEdge {
  parent: string;
  child: string;
}

/**
 * Layered DAG layout as pure data: x follows causal (logical_seq) order,
 * y is the longest ancestor-chain depth, so parents sit above children
 * and branches fan out onto separate lanes. Uses only the given edges —
 * no causality is inferred. Returns plain objects for tests.
 */
export function layoutPositions<T extends LayoutNode>(
  nodes: T[],
  edges: LayoutEdge[] | undefined | null,
  colW = 110,
  rowH = 64,
): {
  ordered: T[];
  pos: Record<string, { x: number; y: number }>;
  depth: Record<string, number>;
  bounds: { w: number; h: number };
} {
  const parentOf: Record<string, string[]> = {};
  for (const e of edges ?? []) {
    if (!e || e.parent === undefined || e.child === undefined) continue;
    (parentOf[e.child] = parentOf[e.child] ?? []).push(e.parent);
  }
  const depth: Record<string, number> = {};
  const visit = (id: string, stack: Set<string>): number => {
    if (depth[id] !== undefined) return depth[id];
    if (stack.has(id)) return 0;
    stack.add(id);
    let d = 0;
    for (const p of parentOf[id] ?? []) d = Math.max(d, visit(p, stack) + 1);
    stack.delete(id);
    depth[id] = d;
    return d;
  };
  const list = nodes ?? [];
  for (const n of list) visit(n.id, new Set());
  const ordered = [...list].sort(
    (a, b) => a.logical_seq - b.logical_seq || (a.id < b.id ? -1 : 1),
  );
  const maxDepth = Math.max(0, ...Object.values(depth));
  const bounds = layoutBounds(ordered.length, maxDepth, colW, rowH);
  const innerW = bounds.w - 160; // keep the label padding out of node placement
  const pos: Record<string, { x: number; y: number }> = {};
  ordered.forEach((n, i) => {
    pos[n.id] = {
      x: 50 + (ordered.length === 1 ? 0 : (i * (innerW - 100)) / (ordered.length - 1)),
      y: 56 + depth[n.id] * rowH,
    };
  });
  return { ordered, pos, depth, bounds };
}
