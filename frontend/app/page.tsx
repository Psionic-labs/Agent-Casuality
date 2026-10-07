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
  DEFAULT_HIDDEN_TYPES,
  countByType,
  filterOverview,
  filterSession,
  listSessions,
  shortSessionId,
} from "../lib/filter.ts";
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
  // Event-type filter shared by the Graph and Timeline views. Live captures
  // are dominated by per-part context_update streaming noise, so the
  // default hides those plus per-turn model_call events; the toolbar below
  // can restore any type. Filtering never touches the backend data.
  const [hiddenTypes, setHiddenTypes] = useState<ReadonlySet<string>>(
    () => new Set(DEFAULT_HIDDEN_TYPES),
  );

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

  // Views render the session- and type-filtered overview; highlight,
  // inspector, and tabs keep the full dataset so chains and details stay
  // truthful. The session defaults to the latest activity ("All sessions"
  // is opt-in: 1625 events at once is not navigable).
  const sessions = useMemo(
    () => (overview ? listSessions(overview.nodes) : []),
    [overview],
  );
  const [session, setSession] = useState<string | null>(null);
  const activeSession = session ?? sessions[0]?.agent ?? "";
  const scoped = useMemo(
    () => (overview ? filterSession(overview, activeSession) : null),
    [overview, activeSession],
  );
  const typeCounts = useMemo(
    () => (scoped ? countByType(scoped.nodes) : []),
    [scoped],
  );
  const visible = useMemo(
    () => (scoped ? filterOverview(scoped, hiddenTypes, overview?.failure_event_id ?? null) : null),
    [scoped, hiddenTypes, overview],
  );
  const hiddenCount = scoped && visible ? scoped.nodes.length - visible.nodes.length : 0;

  const toggleType = (type: string) => {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

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
  // Past the loading guard overview is set, so the filtered view is too.
  const shown = visible ?? overview;
  const shownScope = scoped ?? overview;
  const isKeyPreset =
    hiddenTypes.size === DEFAULT_HIDDEN_TYPES.size &&
    [...hiddenTypes].every((t) => DEFAULT_HIDDEN_TYPES.has(t));
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
          <div className="filter-bar" role="group" aria-label="Event type filter">
            <label className="session-pick">
              Session{" "}
              <select
                value={activeSession}
                onChange={(e) => setSession(e.target.value)}
                title={activeSession || "all sessions"}
              >
                {sessions.map((s) => (
                  <option key={s.agent} value={s.agent} title={s.agent}>
                    {shortSessionId(s.agent)} ({s.count})
                  </option>
                ))}
                <option value="">All sessions ({overview.nodes.length})</option>
              </select>
            </label>
            <div className="view-toggle">
              <button
                type="button"
                className={isKeyPreset ? "active" : ""}
                aria-pressed={isKeyPreset}
                onClick={() => setHiddenTypes(new Set(DEFAULT_HIDDEN_TYPES))}
              >
                Key events
              </button>
              <button
                type="button"
                className={hiddenTypes.size === 0 ? "active" : ""}
                aria-pressed={hiddenTypes.size === 0}
                onClick={() => setHiddenTypes(new Set())}
              >
                All events
              </button>
            </div>
            <span className="filter-chips">
              {typeCounts.map(({ type, count }) => {
                const off = hiddenTypes.has(type);
                return (
                  <button
                    key={type}
                    type="button"
                    className={off ? "chip off" : "chip"}
                    aria-pressed={!off}
                    title={off ? `show ${type}` : `hide ${type}`}
                    onClick={() => toggleType(type)}
                  >
                    {type} ({count})
                  </button>
                );
              })}
            </span>
            <span className="hint" aria-live="polite">
              showing {shown.nodes.length} of {shownScope.nodes.length} events
              {hiddenCount > 0 ? ` · ${hiddenCount} hidden by filter` : ""}
            </span>
          </div>
          {view === "graph" ? (
            <DagView
              overview={shown}
              selectedId={selectedId}
              lit={lit}
              apiRef={viewApiRef}
            />
          ) : (
            <TimelineView
              overview={shown}
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
