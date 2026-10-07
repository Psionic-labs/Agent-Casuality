"use client";

/* Zoomable / pannable causal DAG (SVG). Edges are the declared
 * causal_parent_ids only; layout and highlight reuse the pure helpers in
 * lib/viewport.ts and lib/render.ts. */

import { useEffect, useMemo, useRef } from "react";
import {
  clickSuppressed,
  layoutPositions,
  panBy,
  resetView,
  zoomAt,
  type View,
} from "../lib/viewport.ts";
import { nodeClassNames } from "../lib/render.ts";
import { selectEvent } from "../lib/use-selection.ts";
import type { GraphOverview } from "../lib/types.ts";

export interface ViewApi {
  reset: () => void;
}

interface Props {
  overview: GraphOverview;
  selectedId: string | null;
  lit: Set<string> | null;
  apiRef: React.MutableRefObject<ViewApi | null>;
}

export function DagView({ overview, selectedId, lit, apiRef }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const gRef = useRef<SVGGElement | null>(null);
  const viewRef = useRef<View>({ k: 1, tx: 0, ty: 0 });
  const suppressRef = useRef(false);
  const boxRef = useRef({ w: 600, h: 300 });

  const layout = useMemo(
    () => layoutPositions(overview.nodes, overview.edges),
    [overview],
  );

  const applyView = () => {
    const g = gRef.current;
    if (!g) return;
    const v = viewRef.current;
    g.setAttribute("transform", `translate(${v.tx} ${v.ty}) scale(${v.k})`);
  };

  useEffect(() => {
    apiRef.current = {
      reset() {
        viewRef.current = resetView();
        applyView();
      },
    };
    return () => {
      apiRef.current = null;
    };
  }, [apiRef]);

  useEffect(() => {
    boxRef.current = { w: layout.bounds.w, h: layout.bounds.h };
    viewRef.current = resetView();
    applyView();
  }, [layout]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const toContent = (clientX: number, clientY: number): [number, number] => {
      const rect = svg.getBoundingClientRect();
      const ux = boxRef.current.w / Math.max(1, rect.width);
      const uy = boxRef.current.h / Math.max(1, rect.height);
      return [(clientX - rect.left) * ux, (clientY - rect.top) * uy];
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const [px, py] = toContent(e.clientX, e.clientY);
      viewRef.current = zoomAt(viewRef.current, px, py, e.deltaY < 0 ? 1.2 : 1 / 1.2);
      applyView();
    };
    let drag: { x: number; y: number } | null = null;
    // No pointer capture here: capturing the pointer to the <svg> would
    // retarget the click to the svg and node onClick handlers would never
    // fire. Move/up are tracked on the window instead, so panning still
    // works when the pointer leaves the svg.
    const onPointerDown = (e: PointerEvent) => {
      drag = { x: e.clientX, y: e.clientY };
    };
    const onPointerMove = (e: PointerEvent) => {
      if (!drag) return;
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      if (clickSuppressed(dx, dy)) suppressRef.current = true;
      const rect = svg.getBoundingClientRect();
      const ux = boxRef.current.w / Math.max(1, rect.width);
      const uy = boxRef.current.h / Math.max(1, rect.height);
      viewRef.current = panBy(viewRef.current, dx * ux, dy * uy);
      drag = { x: e.clientX, y: e.clientY };
      applyView();
    };
    const onPointerUp = () => {
      drag = null;
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    svg.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    return () => {
      svg.removeEventListener("wheel", onWheel);
      svg.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
    };
  }, []);

  if (overview.nodes.length === 0) {
    return (
      <svg id="dag" role="img" aria-label="causal DAG" ref={svgRef}>
        <g ref={gRef}>
          <text x={20} y={30}>
            no events
          </text>
        </g>
      </svg>
    );
  }

  const { ordered, pos, bounds } = layout;
  return (
    <svg
      id="dag"
      role="img"
      aria-label="causal DAG"
      ref={svgRef}
      viewBox={`0 0 ${bounds.w} ${bounds.h}`}
    >
      <g id="viewport" ref={gRef}>
        {overview.edges.map((e, i) => {
          const a = pos[e.parent];
          const b = pos[e.child];
          if (!a || !b) return null;
          const mx = (a.x + b.x) / 2;
          const on = !!lit && lit.has(e.parent) && lit.has(e.child);
          return (
            <path
              key={`${e.parent}→${e.child}#${i}`}
              d={`M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}`}
              className={`edge${on ? " lit" : ""}${lit && !on ? " dim" : ""}`}
            />
          );
        })}
        {ordered.map((n) => {
          const p = pos[n.id];
          const onClick = () => {
            if (suppressRef.current) {
              suppressRef.current = false;
              return;
            }
            selectEvent(n.id);
          };
          return (
            <g
              key={n.id}
              className={nodeClassNames(n, {
                selectedId,
                failureId: overview.failure_event_id,
                litSet: lit,
              })}
              transform={`translate(${p.x} ${p.y})`}
              onClick={onClick}
            >
              <circle r={13} />
              <text x={17} y={4}>
                {n.logical_seq}: {n.event_type}
              </text>
              <title>{n.label + (n.role ? ` [role: ${n.role}]` : "")}</title>
            </g>
          );
        })}
      </g>
    </svg>
  );
}
