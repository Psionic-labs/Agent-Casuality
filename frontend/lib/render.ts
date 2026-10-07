/* Pure presentation helpers. No DOM access here: given API data +
 * selection state, these return the exact class names, inspector rows, and
 * text the UI renders. */

import type { EventDetail, EventRecord, GraphOverview } from "./types.ts";

export interface ClassCtx {
  selectedId: string | null;
  failureId: string | null;
  litSet?: Set<string> | null;
}

/** Class string for a DAG node. litSet is the selected node's ancestor set
 * (including itself), or null when nothing is selected. */
export function nodeClassNames(
  node: { id: string; event_type: string; in_failure_slice: boolean },
  { selectedId, failureId, litSet }: ClassCtx,
): string {
  const classes = ["node"];
  if (node.in_failure_slice) classes.push("in-slice");
  if (node.id === failureId) classes.push("failure");
  if (node.event_type === "run_finish") classes.push("terminal");
  if (node.id === selectedId) classes.push("selected");
  else if (litSet && !litSet.has(node.id)) classes.push("dim");
  return classes.join(" ");
}

/** Class string for a timeline tick. Terminal = run_finish events. */
export function tickClassNames(
  node: { id: string; event_type: string; in_failure_slice: boolean },
  { selectedId, failureId }: { selectedId: string | null; failureId: string | null },
): string {
  const classes = ["tick"];
  if (node.in_failure_slice) classes.push("in-slice");
  if (node.id === failureId) classes.push("failure");
  if (node.event_type === "run_finish") classes.push("terminal");
  if (node.id === selectedId) classes.push("selected");
  return classes.join(" ");
}

/** Structured inspector rows for one /api/event payload. Full values are
 * returned; visual truncation of long IDs is CSS-only (with tooltip/copy). */
export function inspectorFieldRows(detail: EventDetail): Array<[string, string]> {
  const rec = detail.record ?? {};
  const payload = (rec.payload ?? {}) as Record<string, unknown>;
  const inner = (payload["payload"] ?? {}) as Record<string, unknown>;
  const args = (inner["args"] ?? {}) as Record<string, unknown>;
  const str = (v: unknown): string => (typeof v === "string" && v ? v : "—");
  return [
    ["Type", str(rec.event_type)],
    ["Event ID", detail.id || "—"],
    ["Role", detail.role || "—"],
    ["Agent", str(rec.agent_id)],
    ["Model", str(payload["model"] ?? inner["model"])],
    ["Sequence", rec.logical_seq === undefined || rec.logical_seq === null ? "—" : String(rec.logical_seq)],
    ["Timestamp", str(payload["timestamp"] ?? rec.wall_time)],
    ["Tool", str(inner["tool"])],
    ["Call ID", str(inner["callID"] ?? inner["call_id"])],
    ["Command", str(args["command"])],
    ["File / resource", str(payload["resource_uri"] ?? args["filePath"] ?? args["path"] ?? inner["file"])],
    ["Session", str(payload["session_id"])],
  ];
}

/** First sentence of a text, for the concise diagnosis lede. */
export function firstSentence(text: string | null | undefined): string {
  const clean = String(text ?? "").trim().replace(/\s+/g, " ");
  if (!clean) return "";
  const match = clean.match(/^.+?[.!?](?=\s|$)/);
  return match ? match[0] : clean;
}

export interface CapabilityFlag {
  key: string;
  value: string;
}

/** Capability limitations (unsupported / not_measurable) found in a
 * diagnosis dimension — rendered as neutral notes, never as errors. */
export function capabilityFlags(dim: unknown): CapabilityFlag[] {
  const flags: CapabilityFlag[] = [];
  if (!dim || typeof dim !== "object") return flags;
  for (const [key, value] of Object.entries(dim as Record<string, unknown>)) {
    if (value === "not_measurable" || value === "unsupported") {
      flags.push({ key, value });
    }
  }
  return flags;
}

export interface SummaryRow {
  label: string;
  value: string;
}

/** Human-readable Metrics-tab summary rows derived from diagnosis
 * dimensions. Research terms stay exact; unmeasurable capabilities read
 * as neutral facts, never as failures. Returns [] when no diagnosis. */
export function metricsSummary(dims: unknown): SummaryRow[] {
  if (!dims || typeof dims !== "object") return [];
  const d = dims as Record<string, Record<string, unknown>>;
  const rows: SummaryRow[] = [];
  const slice = d["causal_slice"] ?? {};
  const minimal = d["minimal_slice"] ?? {};
  const distractors = d["distractors"] ?? {};
  const interaction = d["interaction"] ?? {};
  rows.push({
    label: "Structural evidence",
    value: slice["size"] !== undefined ? `${String(slice["size"])} events` : "—",
  });
  rows.push({
    label: "Required-cause evidence",
    value: minimal["size"] !== undefined ? `${String(minimal["size"])} events` : "—",
  });
  rows.push({
    label: "Distractors",
    value: distractors["leaked"] !== undefined ? String(distractors["leaked"]) : "—",
  });
  const minimality = minimal["causal_minimality"];
  rows.push({
    label: "Causal minimality",
    value:
      minimality === "not_measurable"
        ? "Not measurable from this trace"
        : typeof minimality === "string" && minimality
          ? minimality
          : "—",
  });
  const interplay = interaction["causal_interaction"];
  rows.push({
    label: "Causal interaction",
    value:
      interplay === "unsupported"
        ? "Unsupported for this trace"
        : interplay === "not_measurable"
          ? "Not measurable from this trace"
          : typeof interplay === "string" && interplay
            ? interplay
            : "—",
  });
  return rows;
}

/** True when a stored event record references a resource name — via the
 * capture-time resource_uri or a tool/file field. Powers the provenance
 * chain view; uses recorded metadata only, never inferred links. */
export function eventReferencesResource(record: EventRecord | null | undefined, resource: string): boolean {
  if (!record || !resource) return false;
  const name = String(resource);
  const payload = (record.payload ?? {}) as Record<string, unknown>;
  const inner = (payload["payload"] ?? {}) as Record<string, unknown>;
  const args = (inner["args"] ?? {}) as Record<string, unknown>;
  const candidates = [payload["resource_uri"], args["filePath"], args["path"], inner["file"]];
  return candidates.some(
    (c) => typeof c === "string" && (c === name || c.endsWith(`/${name}`)),
  );
}

function innerOf(record: EventRecord | null | undefined): Record<string, unknown> {
  const payload = ((record ?? {}).payload ?? {}) as Record<string, unknown>;
  return (payload["payload"] ?? {}) as Record<string, unknown>;
}

/** Best-known tool name for an overview event: run/model/context lanes come
 * from the event type; tool lanes need the recorded `tool` from the event's
 * /api/event detail (fetched, never guessed). Returns null when the event
 * is a tool event whose tool is not (yet) known. */
export function toolForEvent(
  eventType: string,
  toolById: ReadonlyMap<string, string>,
  eventId: string,
): string | null {
  if (eventType === "run_start" || eventType === "run_finish") return "run";
  if (eventType === "model_call") return "model";
  if (eventType === "context_update") return "context";
  if (eventType === "tool_call" || eventType === "tool_result") {
    return toolById.get(eventId) ?? null;
  }
  return null;
}

export interface CommandInfo {
  command: string | null;
  source: string | null;
}

/** Command for an event: its own args.command, else the first related
 * record carrying one (e.g. a tool_result borrowing its parent tool_call's
 * command). source is null for an own command or a "type · tool" label
 * naming the correlated event. Recorded data only. */
export function commandForEvent(
  record: EventRecord | null | undefined,
  related: Array<EventRecord | null | undefined>,
): CommandInfo {
  const own = (innerOf(record)["args"] ?? {}) as Record<string, unknown>;
  if (own["command"]) return { command: String(own["command"]), source: null };
  for (const rel of related ?? []) {
    const cmd = ((innerOf(rel)["args"] ?? {}) as Record<string, unknown>)["command"];
    if (cmd) {
      const rInner = innerOf(rel);
      const tool = rInner["tool"] ? ` · ${String(rInner["tool"])}` : "";
      const relType = (rel as EventRecord | null)?.event_type ?? "event";
      return { command: String(cmd), source: `${relType}${tool}` };
    }
  }
  return { command: null, source: null };
}

export interface ResultInfo {
  status: string | null;
  output: string | null;
  outputSource: string | null;
}

/** Result for an event: an explicit status plus output text. Status comes
 * only from recorded status fields (exitCode/status, own then related) and
 * is never inferred from output text. Output is the first recorded
 * output/error/stdout/stderr found. */
export function resultForEvent(
  record: EventRecord | null | undefined,
  related: Array<EventRecord | null | undefined>,
): ResultInfo {
  const chain = [record, ...(related ?? [])];
  let status: string | null = null;
  let output: string | null = null;
  let outputSource: string | null = null;
  for (const rec of chain) {
    const inner = innerOf(rec);
    const meta = (inner["metadata"] ?? {}) as Record<string, unknown>;
    if (status === null) {
      const s =
        inner["exitCode"] ?? inner["exit_code"] ?? inner["status"] ?? meta["exitCode"] ?? meta["exit_code"] ?? meta["status"];
      if (s !== undefined && s !== null && s !== "") status = String(s);
    }
    if (output === null) {
      const o = inner["output"] ?? inner["error"] ?? inner["stdout"] ?? inner["stderr"];
      if (typeof o === "string" && o !== "") {
        output = o;
        outputSource = rec === record ? null : ((rec as EventRecord | null)?.event_type ?? "event");
      }
    }
    if (status !== null && output !== null) break;
  }
  return { status, output, outputSource };
}

/** Default selection when a run opens: the resolved failure target when
 * there is one, else the last event by causal order, else null. */
export function defaultSelectedId(overview: GraphOverview | null | undefined): string | null {
  if (!overview || !Array.isArray(overview.nodes) || overview.nodes.length === 0) return null;
  if (overview.failure_event_id) return overview.failure_event_id;
  const ordered = [...overview.nodes].sort(
    (a, b) => a.logical_seq - b.logical_seq || (a.id < b.id ? -1 : 1),
  );
  return ordered[ordered.length - 1].id;
}
