"use client";

import type { GraphOverview } from "../lib/types.ts";

export function Header({ overview }: { overview: GraphOverview }) {
  const pill = (() => {
    if (!overview.failure_event_id) {
      return {
        className: "status-pill fallback",
        text: "No events",
        title: "This dataset contains no events.",
      };
    }
    if (overview.failure_method === "fallback") {
      return {
        className: "status-pill fallback",
        text: "Fallback target",
        title:
          "Failure status: fallback — no selector matched, showing the last event positionally, not as a causal claim.",
      };
    }
    return {
      className: "status-pill resolved",
      text: "Resolved",
      title:
        "Failure status: resolved — the failure target matched a ground-truth selector.",
    };
  })();
  return (
    <header className="topbar">
      <div className="brand">
        <h1>DAG Explorer</h1>
        <span id="dataset-line" className="muted">
          {overview.source} · {overview.event_count} events · {overview.edge_count} causal edges
        </span>
      </div>
      <div id="failure-banner" className={pill.className} title={pill.title}>
        {pill.text}
      </div>
    </header>
  );
}
