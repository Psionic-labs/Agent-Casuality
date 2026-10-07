"use client";

/* Premiere-style timeline: horizontal sequence, stacked lanes. Position is
 * sequence order (demo timestamps are synthetic); edges are the selected
 * event's declared ancestor chain only. All geometry and grouping reuse the
 * pure helpers in lib/timeline.ts, lib/viewport.ts, and lib/render.ts. */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { clickSuppressed, zoomAt } from "../lib/viewport.ts";
import { tickClassNames } from "../lib/render.ts";
import { selectEvent } from "../lib/use-selection.ts";
import { fetchToolName } from "../lib/api.ts";
import {
  ancestorChainSegments,
  clipX,
  contentWidth,
  fitScale,
  groupLanes,
  stepIndex,
  visibleWindow,
} from "../lib/timeline.ts";
import type { GraphOverview } from "../lib/types.ts";
import type { ViewApi } from "./DagView.tsx";
import { Legend } from "./Legend.tsx";

const BASE_UNIT = 120;
const GAP = 8;
const LANE_H = 56;
const HEADER_W = 120;

interface Props {
  overview: GraphOverview;
  selectedId: string | null;
  lit: Set<string> | null;
  parentOf: Map<string, string[]>;
  apiRef: React.MutableRefObject<ViewApi | null>;
}

export function TimelineView({ overview, selectedId, lit, parentOf, apiRef }: Props) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const clipRefs = useRef(new Map<string, HTMLButtonElement>());
  const suppressRef = useRef(false);
  const anchorRef = useRef<{ viewportX: number; contentX: number; step: number } | null>(null);
  const fittedRef = useRef(false);
  const fitRef = useRef(1);
  const [k, setK] = useState(1);
  const [toolById, setToolById] = useState<Map<string, string>>(new Map());
  const [lanesPending, setLanesPending] = useState(true);
  const [scroll, setScroll] = useState({ left: 0, client: 0, total: 1 });

  const ordered = useMemo(
    () =>
      [...overview.nodes].sort(
        (a, b) => a.logical_seq - b.logical_seq || (a.id < b.id ? -1 : 1),
      ),
    [overview],
  );
  const indexOf = useMemo(() => new Map(ordered.map((n, i) => [n.id, i])), [ordered]);
  const lanes = useMemo(() => groupLanes(ordered, toolById), [ordered, toolById]);
  const laneOf = useMemo(() => {
    const map = new Map<string, number>();
    lanes.forEach((lane, li) => lane.events.forEach((n) => map.set(n.id, li)));
    return map;
  }, [lanes]);

  const unit = BASE_UNIT * k;
  const totalW = contentWidth(ordered.length, unit, GAP);

  // Resolve tool names for lanes from recorded /api/event details (cached).
  useEffect(() => {
    let cancelled = false;
    setLanesPending(true);
    (async () => {
      const ids = ordered
        .filter((n) => n.event_type === "tool_call" || n.event_type === "tool_result")
        .map((n) => n.id);
      const entries: Array<[string, string]> = [];
      await Promise.all(
        ids.map(async (id) => {
          const tool = await fetchToolName(id);
          if (tool) entries.push([id, tool]);
        }),
      );
      if (cancelled) return;
      setToolById(new Map(entries));
      setLanesPending(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [overview, ordered]);

  const reset = () => {
    const scroller = scrollRef.current;
    const w = scroller ? scroller.clientWidth - HEADER_W : 0;
    const kFit = fitScale(w, contentWidth(ordered.length, BASE_UNIT, GAP));
    fitRef.current = kFit;
    setK(kFit);
    if (scroller) scroller.scrollLeft = 0;
  };

  useEffect(() => {
    apiRef.current = { reset };
    return () => {
      apiRef.current = null;
    };
  });

  // Fit-all on first mount, with the selected clip scrolled into view.
  useLayoutEffect(() => {
    if (fittedRef.current || ordered.length === 0) return;
    fittedRef.current = true;
    const scroller = scrollRef.current;
    const w = scroller ? scroller.clientWidth - HEADER_W : 0;
    const kFit = fitScale(w, contentWidth(ordered.length, BASE_UNIT, GAP));
    fitRef.current = kFit;
    setK(kFit);
    const sel = selectedId ? (indexOf.get(selectedId) ?? -1) : -1;
    if (scroller && sel >= 0) {
      const step = BASE_UNIT * kFit + GAP;
      scroller.scrollLeft = Math.max(0, sel * step - scroller.clientWidth / 2);
    }
  }, [ordered, selectedId, indexOf]);

  // Apply a pending cursor-anchored zoom after the new scale renders.
  useLayoutEffect(() => {
    const scroller = scrollRef.current;
    const pending = anchorRef.current;
    if (!scroller || !pending) return;
    anchorRef.current = null;
    const ratio = (unit + GAP) / pending.step;
    scroller.scrollLeft = pending.contentX * ratio - pending.viewportX;
  }, [k, unit]);

  // Keep keyboard focus on the selected clip.
  useEffect(() => {
    if (selectedId) clipRefs.current.get(selectedId)?.focus({ preventScroll: true });
  }, [selectedId]);

  const readScroll = () => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    setScroll({
      left: scroller.scrollLeft,
      client: scroller.clientWidth,
      total: Math.max(1, scroller.scrollWidth),
    });
  };

  useEffect(() => {
    readScroll();
    window.addEventListener("resize", readScroll);
    return () => window.removeEventListener("resize", readScroll);
  });

  // Cursor-anchored scroll zoom. The floor is the fit-all scale (zooming
  // out stops at fit, so the trace can never be lost); the ceiling stays 10x.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = scroller.getBoundingClientRect();
      const viewportX = e.clientX - rect.left - HEADER_W;
      anchorRef.current = {
        viewportX,
        contentX: viewportX + scroller.scrollLeft,
        step: unit + GAP,
      };
      const next = zoomAt({ k, tx: 0, ty: 0 }, 0, 0, e.deltaY < 0 ? 1.2 : 1 / 1.2, fitRef.current, 10);
      setK(next.k);
    };
    scroller.addEventListener("wheel", onWheel, { passive: false });
    return () => scroller.removeEventListener("wheel", onWheel);
  }, [k, unit]);

  // Drag-to-pan with a 6px drag-vs-click threshold (reuses clickSuppressed).
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    let drag: { x: number; y: number; left: number; top: number } | null = null;
    const onPointerDown = (e: PointerEvent) => {
      if ((e.target as HTMLElement).closest("button")) return;
      drag = { x: e.clientX, y: e.clientY, left: scroller.scrollLeft, top: scroller.scrollTop };
    };
    const onPointerMove = (e: PointerEvent) => {
      if (!drag) return;
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      if (clickSuppressed(dx, dy)) suppressRef.current = true;
      scroller.scrollLeft = drag.left - dx;
      scroller.scrollTop = drag.top - dy;
    };
    const onPointerUp = () => {
      drag = null;
    };
    scroller.addEventListener("pointerdown", onPointerDown);
    scroller.addEventListener("pointermove", onPointerMove);
    scroller.addEventListener("pointerup", onPointerUp);
    scroller.addEventListener("pointercancel", onPointerUp);
    return () => {
      scroller.removeEventListener("pointerdown", onPointerDown);
      scroller.removeEventListener("pointermove", onPointerMove);
      scroller.removeEventListener("pointerup", onPointerUp);
      scroller.removeEventListener("pointercancel", onPointerUp);
    };
  }, []);

  const indexFromClientX = (clientX: number, ruler: HTMLElement): number => {
    const rect = ruler.getBoundingClientRect();
    return Math.min(
      ordered.length - 1,
      Math.max(0, Math.floor((clientX - rect.left) / (unit + GAP))),
    );
  };

  const onRulerPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (ordered.length === 0) return;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    const ruler = e.currentTarget;
    const scrub = (clientX: number) => {
      const node = ordered[indexFromClientX(clientX, ruler)];
      if (node) selectEvent(node.id);
    };
    scrub(e.clientX);
    const onMove = (ev: PointerEvent) => scrub(ev.clientX);
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointercancel", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp, { once: true });
    window.addEventListener("pointercancel", onUp, { once: true });
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const cur = selectedId ? (indexOf.get(selectedId) ?? -1) : -1;
    const next = stepIndex(cur, e.key === "ArrowRight" ? 1 : -1, ordered.length);
    const node = ordered[next];
    if (!node) return;
    const scroller = scrollRef.current;
    if (scroller) {
      const x = clipX(next, unit, GAP);
      if (x < scroller.scrollLeft || x + unit > scroller.scrollLeft + scroller.clientWidth) {
        scroller.scrollLeft = Math.max(0, x - scroller.clientWidth / 2);
      }
    }
    selectEvent(node.id);
  };

  const onMinimapClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (ordered.length === 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const idx = Math.min(
      ordered.length - 1,
      Math.max(0, Math.floor(((e.clientX - rect.left) / Math.max(1, rect.width)) * ordered.length)),
    );
    const node = ordered[idx];
    if (node) selectEvent(node.id);
  };

  // Visible-window culling: mount only clips intersecting the viewport.
  const win = visibleWindow(scroll.left, Math.max(0, scroll.client - HEADER_W), ordered.length, unit, GAP);
  const visibleIdx = new Set<number>();
  for (let i = win.start; i < win.end; i++) visibleIdx.add(i);

  const segments = useMemo(
    () => ancestorChainSegments(selectedId, parentOf),
    [selectedId, parentOf],
  );
  // Edge-to-edge routing: each declared ancestor edge runs from the parent
  // clip's right edge to the child clip's left edge, so lines never cross
  // their own clips' labels. Straight segments only — no elbows.
  const chainPath = useMemo(() => {
    const orderedSegs = [...segments].sort((a, b) =>
      a.fromId < b.fromId ? -1 : a.fromId > b.fromId ? 1 : a.toId < b.toId ? -1 : 1,
    );
    const parts: string[] = [];
    for (const s of orderedSegs) {
      const ip = indexOf.get(s.fromId);
      const ic = indexOf.get(s.toId);
      const lp = laneOf.get(s.fromId);
      const lc = laneOf.get(s.toId);
      if (ip === undefined || ic === undefined || lp === undefined || lc === undefined) continue;
      const x1 = clipX(ip, unit, GAP) + unit;
      const y1 = lp * LANE_H + LANE_H / 2;
      const x2 = clipX(ic, unit, GAP);
      const y2 = lc * LANE_H + LANE_H / 2;
      parts.push(`M ${x1} ${y1} L ${x2} ${y2}`);
    }
    return parts.join(" ");
  }, [segments, indexOf, laneOf, unit]);

  const selIdx = selectedId ? (indexOf.get(selectedId) ?? -1) : -1;
  const playX = selIdx >= 0 ? clipX(selIdx, unit, GAP) + unit / 2 : null;

  const clipClass = (nodeId: string, inSlice: boolean, eventType: string): string => {
    let cls = tickClassNames(
      { id: nodeId, event_type: eventType, in_failure_slice: inSlice },
      { selectedId, failureId: overview.failure_event_id },
    ).replace(/^tick/, "clip");
    if (lit && !lit.has(nodeId) && nodeId !== selectedId) cls += " dim";
    return cls;
  };

  if (ordered.length === 0) {
    return (
      <div id="timeline">
        <p className="hint">no events</p>
      </div>
    );
  }

  return (
    <div id="timeline">
      <div className="tl-scroll" ref={scrollRef} onScroll={readScroll} onKeyDown={onKeyDown} aria-label="event timeline. arrow keys step through events">
        <div style={{ width: HEADER_W + totalW }}>
          <div className="tl-ruler-row">
            <div className="tl-corner" style={{ width: HEADER_W }} aria-hidden="true" />
            <div
              className="tl-ruler"
              style={{ width: totalW }}
              onPointerDown={onRulerPointerDown}
              aria-hidden="true"
            >
              {ordered.map((n, i) =>
                visibleIdx.has(i) ? (
                  <span
                    key={n.id}
                    className={`tl-num${n.id === selectedId ? " sel" : ""}`}
                    style={{ left: clipX(i, unit, GAP), width: unit + GAP }}
                  >
                    {n.logical_seq}
                  </span>
                ) : null,
              )}
              {playX !== null && (
                <span className="tl-knob" style={{ left: playX }} />
              )}
            </div>
          </div>
          <div style={{ position: "relative" }}>
            <svg
              className="tl-edges"
              style={{ left: HEADER_W, width: totalW, height: lanes.length * LANE_H }}
              width={totalW}
              height={lanes.length * LANE_H}
              aria-hidden="true"
            >
              {chainPath && <path d={chainPath} vectorEffect="non-scaling-stroke" />}
            </svg>
            {lanes.map((lane) => (
              <div className="tl-lane-row" key={lane.key} style={{ height: LANE_H }}>
                <div className="tl-lane-head" style={{ width: HEADER_W }}>
                  {lane.key}
                </div>
                <div className="tl-lane-body" style={{ width: totalW, height: LANE_H }}>
                  {lanesPending ? null : (
                    lane.events.map((n) => {
                      const i = indexOf.get(n.id) ?? -1;
                      if (!visibleIdx.has(i)) return null;
                      return (
                        <button
                          key={n.id}
                          type="button"
                          ref={(btn) => {
                            if (btn) clipRefs.current.set(n.id, btn);
                            else clipRefs.current.delete(n.id);
                          }}
                          className={clipClass(n.id, n.in_failure_slice, n.event_type)}
                          style={{ left: clipX(i, unit, GAP), width: unit }}
                          title={`#${n.logical_seq} ${n.label}`}
                          aria-label={`Event ${n.logical_seq} ${n.event_type}`}
                          onClick={() => {
                            if (suppressRef.current) {
                              suppressRef.current = false;
                              return;
                            }
                            selectEvent(n.id);
                          }}
                        >
                          <span className="lbl">{n.event_type}</span>
                        </button>
                      );
                    })
                  )}
                </div>
              </div>
            ))}
            {playX !== null && (
              <div className="tl-playhead" style={{ left: HEADER_W + playX, top: 0, bottom: 0 }} />
            )}
          </div>
        </div>
      </div>
      <div className="minimap">
        <div className="minimap-track" onClick={onMinimapClick} role="presentation">
          {ordered.map((n) => (
            <div
              key={n.id}
              className={tickClassNames(n, {
                selectedId,
                failureId: overview.failure_event_id,
              }).replace(/^tick/, "mm-seg")}
              title={`#${n.logical_seq} ${n.label}`}
            />
          ))}
          <div
            className="mm-view"
            style={{
              left: `${(scroll.left / scroll.total) * 100}%`,
              width: `${(Math.max(scroll.client - HEADER_W, 0) / scroll.total) * 100}%`,
            }}
          />
        </div>
        <div className="minimap-foot">
          <Legend />
        </div>
      </div>
      <p className="hint tl-note">
        Lines show declared causal parents of the selected event only. Position is sequence
        order; influence is not proven.
      </p>
    </div>
  );
}
