"use client";

import { firstSentence } from "../lib/render.ts";
import { selectEvent } from "../lib/use-selection.ts";
import type { EvidenceReport, FailureReport, GraphOverview } from "../lib/types.ts";

interface Props {
  overview: GraphOverview;
  failure: FailureReport;
  evidence: EvidenceReport;
}

export function WhyStrip({ overview, failure, evidence }: Props) {
  if (!overview.failure_event_id) {
    return (
      <section className="card why" aria-labelledby="why-heading">
        <div className="why-head">
          <h2 id="why-heading">Why did it fail?</h2>
          <div id="failure-info" className="muted" />
        </div>
        <p id="why-text" className="why-text">
          This dataset contains no events, so there is nothing to diagnose.
        </p>
        <div className="causal-path" id="causal-path" aria-label="causal path">
          <span className="path-label">Causal path: </span>
        </div>
      </section>
    );
  }
  const roleEntries = Object.entries(failure.roles ?? {});
  const byId = new Map(overview.nodes.map((n) => [n.id, n]));
  const sliceSize = overview.nodes.filter((n) => n.in_failure_slice).length;
  const info = failure.is_fallback
    ? "Failure status: fallback — no ground-truth selector matched, so the last event is shown positionally, not as a causal claim."
    : `Failure status: resolved via ${failure.method} · ` +
      `${roleEntries.length} role${roleEntries.length === 1 ? "" : "s"} resolved` +
      (failure.unresolved_roles.length > 0
        ? ` · unresolved: ${failure.unresolved_roles.join(", ")}`
        : "");
  const ordered = roleEntries
    .map(([role, hits]) => ({ role, node: byId.get(hits[0]?.event_id) }))
    .filter((s) => s.node)
    .sort((a, b) => (a.node?.logical_seq ?? 0) - (b.node?.logical_seq ?? 0));

  return (
    <section className="card why" aria-labelledby="why-heading">
      <div className="why-head">
        <h2 id="why-heading">Why did it fail?</h2>
        <div id="failure-info" className="muted">
          {info}
        </div>
      </div>
      <p id="why-text" className="why-text">
        {firstSentence(evidence.summary) || "No evidence summary available."}
      </p>
      <div className="causal-path" id="causal-path" aria-label="causal path">
        <span className="path-label">Causal path: </span>
        {ordered.length > 0 ? (
          ordered.flatMap((s, i) => {
            const btn = (
              <button
                key={s.role}
                className="path-step role"
                type="button"
                title={s.node?.label}
                onClick={() => s.node && selectEvent(s.node.id)}
              >
                {s.role}
              </button>
            );
            return i > 0
              ? [
                  <span key={`arrow-${s.role}`} className="path-arrow">
                    →
                  </span>,
                  btn,
                ]
              : [btn];
          })
        ) : (
          <span className="path-note muted">
            No ground-truth roles — showing the {sliceSize}-event structural slice instead.
          </span>
        )}
      </div>
      <details className="tech">
        <summary>Full technical explanation</summary>
        <pre>{(evidence.summary || "(no evidence)").trim()}</pre>
      </details>
    </section>
  );
}
