"use client";

/* Analysis tabs. Backend vocabulary is repeated verbatim (see DESIGN.md §8):
 * research terms stay exact, capability limits render as neutral notes. */

import { useEffect, useState } from "react";
import {
  capabilityFlags,
  eventReferencesResource,
  metricsSummary,
} from "../lib/render.ts";
import { fetchEventDetail } from "../lib/api.ts";
import {
  baseName,
  branchPoints,
  mergePoints,
  nodesForResource,
  resourcesInDetails,
  sliceNodes,
  toolStory,
  traceCensus,
  type ToolStoryStep,
} from "../lib/tracefacts.ts";
import { selectEvent } from "../lib/use-selection.ts";
import type {
  DiagnosisDim,
  DiagnosisReport,
  EventRecord,
  EvidenceReport,
  FailureReport,
  GraphOverview,
  OverviewNode,
} from "../lib/types.ts";

type Tab = "chain" | "provenance" | "interaction" | "evidence" | "metrics";

function Intro({ text }: { text: string }) {
  return <p className="hint">{text}</p>;
}

function DimBlock({ title, dim }: { title: string; dim: DiagnosisDim | undefined }) {
  if (!dim || dim.status === "error") {
    return (
      <div className="dim">
        <h4>{title}</h4>
        <p className="hint">unavailable: {String((dim as DiagnosisDim | undefined)?.["error"] ?? "unknown")}</p>
      </div>
    );
  }
  const skip = new Set(["metric", "label"]);
  for (const flag of capabilityFlags(dim)) skip.add(flag.key);
  const facts: string[] = [];
  for (const key of [
    "recall", "precision", "exact_match", "size", "structural_size",
    "reduction_ratio", "required_recall", "resource_recall", "edges_present",
    "grounded", "summary_grounded", "mentions_recall", "leaked",
  ]) {
    if (!skip.has(key) && dim[key] !== undefined) facts.push(`${key}: ${JSON.stringify(dim[key])}`);
  }
  return (
    <div className="dim">
      <h4>{title}</h4>
      {typeof dim.metric === "string" && <p className="metric">metric: {dim.metric}</p>}
      {typeof dim.label === "string" && <p className="label">{dim.label}</p>}
      {facts.length > 0 && <p className="metric">{facts.join(" · ")}</p>}
      {capabilityFlags(dim).map((flag) => (
        <span
          key={flag.key}
          className="flag"
          title="A capability limit of the analysis, not a system error."
        >
          {flag.key}: {flag.value}
        </span>
      ))}
      {["identified", "missed", "roles", "detected", "recovered_resources", "mentions_found", "summary_cites_ids"].map(
        (key) => {
          const v = dim[key];
          return Array.isArray(v) && v.length > 0 ? (
            <p key={key} className="label">
              {key}: {v.join(", ")}
            </p>
          ) : null;
        },
      )}
    </div>
  );
}

function ChainTab({ overview }: { overview: GraphOverview }) {
  const slice = [...overview.nodes]
    .filter((n) => n.in_failure_slice)
    .sort((a, b) => a.logical_seq - b.logical_seq);
  const max = 80;
  return (
    <div id="tab-chain" className="tab-panel active">
      <Intro
        text={`The ${slice.length} events the failure structurally depends on, oldest first. ` +
          "Inclusion means a causal parent was declared at capture time; influence is not proven here."}
      />
      <ul className="chain-list">
        {slice.slice(0, max).map((n) => (
          <li key={n.id}>
            <span className="seq">{n.logical_seq}</span>
            <button type="button" className="pill" onClick={() => selectEvent(n.id)}>
              {n.label}
            </button>
            {n.role && <span className="pill role">{n.role}</span>}
            {n.id === overview.failure_event_id && (
              <span className="pill slice">failure target</span>
            )}
          </li>
        ))}
      </ul>
      {slice.length > max && (
        <p className="hint">… {slice.length - max} more events in slice (use the graph to explore).</p>
      )}
    </div>
  );
}

function ChainStepButton({ node, failureId }: { node: OverviewNode; failureId: string | null }) {
  return (
    <button type="button" className="chain-step" title={node.id} onClick={() => selectEvent(node.id)}>
      {node.label}
      {node.role && <span className="pill role">{node.role}</span>}
      {node.id === failureId && <span className="pill slice">failure</span>}
    </button>
  );
}

function ProvenanceTab({
  overview,
  diagnosis,
  evidence,
}: {
  overview: GraphOverview;
  diagnosis: DiagnosisReport;
  evidence: EvidenceReport;
}) {
  const [chains, setChains] = useState<{ resource: string; nodes: OverviewNode[] }[] | null>(null);
  const [discovered, setDiscovered] = useState<{ resource: string; nodes: OverviewNode[] }[] | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [failed, setFailed] = useState(false);

  const dims = diagnosis.status === "ok" ? diagnosis.dimensions : {};
  const prov = (dims["provenance"] ?? {}) as DiagnosisDim & { recovered_resources?: string[]; expected_edges?: { edge?: string[]; present?: boolean }[]; status?: string };
  const pkgProv = evidence?.package?.provenance;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const recovered: string[] = Array.isArray(prov.recovered_resources) ? prov.recovered_resources : [];
        const slice = [...overview.nodes]
          .filter((n) => n.in_failure_slice)
          .sort((a, b) => a.logical_seq - b.logical_seq);
        const CAP = 150;
        const details = await Promise.all(slice.slice(0, CAP).map((n) => fetchEventDetail(n.id)));
        if (cancelled) return;
        setTruncated(slice.length > CAP);
        const byId = new Map(overview.nodes.map((n) => [n.id, n]));
        setChains(
          recovered.map((resource) => ({
            resource: String(resource),
            nodes: details
              .filter((d) => d && eventReferencesResource(d.record, String(resource)))
              .map((d) => byId.get(d.id))
              .filter((n): n is OverviewNode => !!n)
              .sort((a, b) => a.logical_seq - b.logical_seq),
          })),
        );
        // Option B: resources nobody expected — named in recorded capture
        // metadata but absent from ground truth. Same chain treatment.
        const expected = new Set(recovered.map((r) => String(r)));
        setDiscovered(
          resourcesInDetails(details)
            .filter((resource) => !expected.has(resource))
            .map((resource) => ({
              resource,
              nodes: nodesForResource(details, resource)
                .map((d) => byId.get(d.id))
                .filter((n): n is OverviewNode => !!n),
            })),
        );
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overview, diagnosis]);

  const recovered: string[] = Array.isArray(prov.recovered_resources) ? prov.recovered_resources : [];
  const checks = Array.isArray(prov.expected_edges) ? prov.expected_edges : [];
  return (
    <div id="tab-provenance" className="tab-panel active">
      <Intro text="Which files and artifacts the diagnosis could trace back to the captured events." />
      {!Array.isArray(pkgProv) || pkgProv.length === 0 ? (
        <p className="hint">
          No field-level provenance edges recorded for this trace, so no exact/coarse grade
          applies. The chains below link resources through capture-time metadata, not graded
          provenance.
        </p>
      ) : (
        pkgProv.map((entry, i) => {
          const grades = (entry.edges ?? []).map((e) => e.grade).filter(Boolean);
          return (
            <p key={i} className="label">
              {entry.target ?? "field"} — grades: {grades.join(", ") || "none recorded"}
            </p>
          );
        })
      )}
      {prov.status !== "ok" ? (
        <p className="hint">Provenance unavailable.</p>
      ) : (
        <>
          {recovered.length === 0 && (
            <p className="hint">No expected resources were recovered from this trace.</p>
          )}
          {failed && <p className="hint">Could not load event details for the chain view.</p>}
          {truncated && (
            <p className="hint">Chain view covers the first 150 slice events.</p>
          )}
          {(chains ?? recovered.map((r) => ({ resource: String(r), nodes: [] as OverviewNode[] }))).map(
            (chain) => (
              <div key={chain.resource} className="prov-chain">
                <h4>{chain.resource}</h4>
                {chains === null && !failed ? (
                  <p className="hint">loading…</p>
                ) : chain.nodes.length === 0 ? (
                  <p className="hint">No slice event carries this resource in its capture metadata.</p>
                ) : (
                  <div className="chain-steps">
                    {chain.nodes.flatMap((node, i) =>
                      i > 0
                        ? [
                            <div key={`a-${node.id}`} className="chain-arrow">
                              ↓
                            </div>,
                            <ChainStepButton key={node.id} node={node} failureId={overview.failure_event_id} />,
                          ]
                        : [<ChainStepButton key={node.id} node={node} failureId={overview.failure_event_id} />],
                    )}
                  </div>
                )}
              </div>
            ),
          )}
          {discovered !== null && discovered.length > 0 && (
            <>
              <p className="label">
                Discovered in this trace — resources named in recorded capture metadata that no
                ground truth expected:
              </p>
              {discovered.map((chain) => (
                <div key={chain.resource} className="prov-chain">
                  <h4 title={chain.resource}>{baseName(chain.resource)}</h4>
                  {chain.nodes.length === 0 ? (
                    <p className="hint">No slice event carries this resource in its capture metadata.</p>
                  ) : (
                    <div className="chain-steps">
                      {chain.nodes.flatMap((node, i) =>
                        i > 0
                          ? [
                              <div key={`a-${node.id}`} className="chain-arrow">
                                ↓
                              </div>,
                              <ChainStepButton key={node.id} node={node} failureId={overview.failure_event_id} />,
                            ]
                          : [<ChainStepButton key={node.id} node={node} failureId={overview.failure_event_id} />],
                      )}
                    </div>
                  )}
                </div>
              ))}
            </>
          )}
          {checks.length > 0 ? (
            <details className="tech">
              <summary>Expected resource edges</summary>
              {checks.map((check, i) => (
                <p key={i} className="label">
                  {(check.edge ?? []).join(" → ")}: {check.present ? "present in capture" : "not observed"}
                </p>
              ))}
            </details>
          ) : (
            <p className="hint">No expected resource edges in this dataset&apos;s ground truth.</p>
          )}
        </>
      )}
    </div>
  );
}

function InteractionTab({ overview, diagnosis }: { overview: GraphOverview; diagnosis: DiagnosisReport }) {
  const dims = diagnosis.status === "ok" ? diagnosis.dimensions : {};
  const ci = (dims["causal_interaction"] ?? {}) as { status?: string; reason?: string };
  const branches = branchPoints(overview);
  const merges = mergePoints(overview);
  const byId = new Map(overview.nodes.map((n) => [n.id, n]));
  const step = (id: string) => {
    const n = byId.get(id);
    return n ? <ChainStepButton key={id} node={n} failureId={overview.failure_event_id} /> : null;
  };
  return (
    <div id="tab-interaction" className="tab-panel active">
      <Intro
        text="Where the recorded DAG actually fans out or converges. Edge shape only — a shared downstream event is not proof the branches interacted causally."
      />
      {branches.length === 0 && merges.length === 0 ? (
        <p className="hint">No fan-out or fan-in in the recorded edges — this trace is a linear chain.</p>
      ) : (
        <>
          {branches.map((b) => (
            <div key={`fanout-${b.id}`} className="prov-chain">
              <h4 title={b.id}>
                #{b.logicalSeq} {b.label} → {b.childIds.length} branches
              </h4>
              <div className="chain-steps">{b.childIds.map(step)}</div>
            </div>
          ))}
          {merges.map((m) => (
            <div key={`fanin-${m.id}`} className="prov-chain">
              <h4 title={m.id}>
                #{m.logicalSeq} {m.label} ← {m.parentIds.length} parents
              </h4>
              <div className="chain-steps">{m.parentIds.map(step)}</div>
            </div>
          ))}
        </>
      )}
      <details className="tech">
        <summary>Benchmark scoring</summary>
        <DimBlock title="Joint ancestry (NOT causal interaction)" dim={dims["interaction"]} />
        {ci.status && (
          <>
            <p />
            <span className="flag" title={ci.reason ?? ""}>
              Causal interaction: {ci.status}
            </span>
          </>
        )}
      </details>
    </div>
  );
}

function EvidenceTab({
  overview,
  diagnosis,
  evidence,
}: {
  overview: GraphOverview;
  diagnosis: DiagnosisReport;
  evidence: EvidenceReport;
}) {
  const [story, setStory] = useState<ToolStoryStep[] | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [failed, setFailed] = useState(false);
  const dims = diagnosis.status === "ok" ? diagnosis.dimensions : {};

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const slice = sliceNodes(overview);
        const CAP = 150;
        const details = await Promise.all(slice.slice(0, CAP).map((n) => fetchEventDetail(n.id)));
        if (cancelled) return;
        setTruncated(slice.length > CAP);
        const byId = new Map<string, EventRecord>();
        for (const d of details) if (d) byId.set(d.id, d.record);
        setStory(toolStory(overview, byId));
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [overview]);

  return (
    <div id="tab-evidence" className="tab-panel active">
      <Intro
        text="What the run actually did, in order: every tool call and result in the failure slice, with recorded commands. Select a step to inspect it."
      />
      {failed && <p className="hint">Could not load event details for the tool story.</p>}
      {truncated && <p className="hint">Tool story covers the first 150 slice events.</p>}
      {story === null && !failed ? (
        <p className="hint">loading…</p>
      ) : (story ?? []).length === 0 ? (
        <p className="hint">No tool calls or results in the failure slice.</p>
      ) : (
        <ul className="chain-list">
          {(story ?? []).map((s) => (
            <li key={s.id}>
              <span className="seq">{s.logicalSeq}</span>
              <button type="button" className="pill" title={s.id} onClick={() => selectEvent(s.id)}>
                {s.label}
              </button>
              {s.tool && <span className="pill role">{s.tool}</span>}
              {s.command ? (
                <code title={s.commandSource ? `recorded on ${s.commandSource}` : "recorded on this event"}>
                  {s.command}
                </code>
              ) : (
                <span className="hint">no recorded command</span>
              )}
            </li>
          ))}
        </ul>
      )}
      <details className="tech">
        <summary>Backend evidence summary</summary>
        <pre id="evidence">{(evidence.summary || "(no evidence)").trim()}</pre>
        <div id="diagnosis">
          <Intro text="The evidence package behind the diagnosis, and how well the explanation is grounded in captured events." />
          <DimBlock title="Explanation grounding" dim={dims["explanation_grounding"]} />
        </div>
      </details>
    </div>
  );
}

function MetricsTab({ overview, diagnosis }: { overview: GraphOverview; diagnosis: DiagnosisReport }) {
  if (diagnosis.status !== "ok") {
    return (
      <div id="tab-metrics" className="tab-panel active">
        <p className="hint">No diagnosis: dataset has no events.</p>
      </div>
    );
  }
  const dims = diagnosis.dimensions;
  const census = traceCensus(overview);
  return (
    <div id="tab-metrics" className="tab-panel active">
      <Intro
        text="What was captured, in counts — no ground truth needed. Benchmark scoring stays under technical details."
      />
      <dl className="summary-list">
        <div className="field-row">
          <dt>Dataset events</dt>
          <dd>{census.total}</dd>
        </div>
        <div className="field-row">
          <dt>Failure slice</dt>
          <dd>{census.sliceSize} events</dd>
        </div>
        {census.sliceByType.map((t) => (
          <div key={t.type} className="field-row">
            <dt>{t.type}</dt>
            <dd>{t.count}</dd>
          </div>
        ))}
      </dl>
      <details className="tech">
        <summary>Benchmark scoring</summary>
        <dl className="summary-list">
          {metricsSummary(dims).map(({ label, value }) => (
            <div key={label} className="field-row">
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        <DimBlock title="Structural slice (declared-dependency evidence)" dim={dims["causal_slice"]} />
        <DimBlock title="Cause identification" dim={dims["cause_identification"]} />
        <DimBlock title="Required-cause preservation proxy (NOT causal minimality)" dim={dims["minimal_slice"]} />
        <DimBlock title="Distractors" dim={dims["distractors"]} />
        <DimBlock title="Joint ancestry (NOT causal interaction)" dim={dims["interaction"]} />
        <DimBlock title="Explanation grounding" dim={dims["explanation_grounding"]} />
      </details>
    </div>
  );
}

interface Props {
  overview: GraphOverview;
  failure: FailureReport;
  diagnosis: DiagnosisReport;
  evidence: EvidenceReport;
}

const TABS: { id: Tab; label: string }[] = [
  { id: "chain", label: "Causal chain" },
  { id: "provenance", label: "Provenance" },
  { id: "interaction", label: "Interaction" },
  { id: "evidence", label: "Evidence" },
  { id: "metrics", label: "Metrics" },
];

export function TabsPanels({ overview, failure: _failure, diagnosis, evidence }: Props) {
  const [tab, setTab] = useState<Tab>("chain");
  void _failure;
  return (
    <>
      <nav className="tabs" aria-label="analysis sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            data-tab={t.id}
            className={tab === t.id ? "active" : ""}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <section className="card tab-panels">
        {tab === "chain" && <ChainTab overview={overview} />}
        {tab === "provenance" && (
          <ProvenanceTab overview={overview} diagnosis={diagnosis} evidence={evidence} />
        )}
        {tab === "interaction" && <InteractionTab overview={overview} diagnosis={diagnosis} />}
        {tab === "evidence" && <EvidenceTab overview={overview} diagnosis={diagnosis} evidence={evidence} />}
        {tab === "metrics" && <MetricsTab overview={overview} diagnosis={diagnosis} />}
      </section>
    </>
  );
}
