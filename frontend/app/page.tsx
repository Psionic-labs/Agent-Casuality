"use client";

/* Visual DAG Explorer page. Presentation only: every fact shown comes from
 * the read-only /api/* endpoints (explorer/server.py). No causal inference
 * happens here.
 *
 * Selection is a single shared store (lib/store.ts): the DAG, the timeline,
 * and the inspector all read the same selectedEventId via useSelection().
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { selectionStore } from "../lib/store.ts";
import { selectEvent, useSelection } from "../lib/use-selection.ts";
import { defaultSelectedId } from "../lib/render.ts";
import { ancestorsOf, parentMap } from "../lib/timeline.ts";
import {
  fetchDiagnosis,
  fetchEvidence,
  fetchFailure,
  fetchOverview,
} from "../lib/api.ts";
import type {
  DiagnosisReport,
  EvidenceReport,
  FailureReport,
  GraphOverview,
} from "../lib/types.ts";
import { Header } from "../components/Header.tsx";
import { WhyStrip } from "../components/WhyStrip.tsx";
import { DagView, type ViewApi } from "../components/DagView.tsx";
import { TimelineView } from "../components/TimelineView.tsx";
import { Inspector } from "../components/Inspector.tsx";
import { TabsPanels } from "../components/TabsPanels.tsx";

type MainView = "graph" | "timeline";

export default function Page() {
  const [overview, setOverview] = useState<GraphOverview | null>(null);
  const [failure, setFailure] = useState<FailureReport | null>(null);
  const [diagnosis, setDiagnosis] = useState<DiagnosisReport | null>(null);
  const [evidence, setEvidence] = useState<EvidenceReport | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [view, setView] = useState<MainView>("graph");
  const viewApiRef = useRef<ViewApi | null>(null);
  const selectedId = useSelection();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [o, f, d, e] = await Promise.all([
          fetchOverview(),
          fetchFailure(),
          fetchDiagnosis(),
          fetchEvidence(),
        ]);
        if (cancelled) return;
        setOverview(o);
        setFailure(f);
        setDiagnosis(d);
        setEvidence(e);
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const parentOf = useMemo(
    () => (overview ? parentMap(overview.edges) : new Map<string, string[]>()),
    [overview],
  );

  /** Ancestor set of the selection (selection included), or null. */
  const lit = useMemo(() => {
    if (!selectedId) return null;
    const s = ancestorsOf(selectedId, parentOf);
    s.add(selectedId);
    return s;
  }, [selectedId, parentOf]);

  // Default selection: the resolved failure target when there is one, else
  // the last event by causal order. Never overrides an existing selection.
  useEffect(() => {
    if (overview && selectionStore.selectedId === null) {
      const initial = defaultSelectedId(overview);
      if (initial) selectEvent(initial);
    }
  }, [overview]);

  const selectedNode = overview?.nodes.find((n) => n.id === selectedId) ?? null;
  const announce = selectedNode
    ? `Selected event ${selectedNode.logical_seq}: ${selectedNode.label}`
    : "No event selected";

  if (loadError) {
    return (
      <header className="topbar">
        <div className="brand">
          <h1>DAG Explorer</h1>
          <span id="dataset-line" className="muted">
            failed to load API: {loadError}
          </span>
        </div>
      </header>
    );
  }
  if (!overview || !failure || !diagnosis || !evidence) {
    return (
      <header className="topbar">
        <div className="brand">
          <h1>DAG Explorer</h1>
          <span id="dataset-line" className="muted">
            loading…
          </span>
        </div>
      </header>
    );
  }

  const controlsHint = "scroll zoom · drag pan · ←/→ step";
  return (
    <>
      <p className="sr-only" role="status">
        {announce}
      </p>
      <Header overview={overview} />
      <WhyStrip overview={overview} failure={failure} evidence={evidence} />
      <main className="debug-grid">
        <section className="card dag-card">
          <div className="card-head">
            <h2>{view === "graph" ? "Causal DAG" : "Timeline"}</h2>
            <div className="dag-controls">
              <div
                className="view-toggle"
                role="group"
                aria-label="DAG panel view"
              >
                <button
                  type="button"
                  className={view === "graph" ? "active" : ""}
                  aria-pressed={view === "graph"}
                  onClick={() => setView("graph")}
                >
                  Graph
                </button>
                <button
                  type="button"
                  className={view === "timeline" ? "active" : ""}
                  aria-pressed={view === "timeline"}
                  onClick={() => setView("timeline")}
                >
                  Timeline
                </button>
              </div>
              <span className="hint">{controlsHint}</span>
              <button type="button" onClick={() => viewApiRef.current?.reset()}>
                Reset view
              </button>
            </div>
          </div>
          {view === "graph" ? (
            <DagView
              overview={overview}
              selectedId={selectedId}
              lit={lit}
              apiRef={viewApiRef}
            />
          ) : (
            <TimelineView
              overview={overview}
              selectedId={selectedId}
              lit={lit}
              parentOf={parentOf}
              apiRef={viewApiRef}
            />
          )}
        </section>
        <aside className="card inspector-card">
          <h2>Event inspector</h2>
          <Inspector selectedId={selectedId} />
        </aside>
      </main>
      <TabsPanels
        overview={overview}
        failure={failure}
        diagnosis={diagnosis}
        evidence={evidence}
      />
    </>
  );
}
