/* Trace-fact helpers for the analysis tabs (Option B): ground-truth-free
 * bodies built only from capture facts — declared edges, recorded detail
 * metadata, recorded payloads. Pure and framework-free so the logic stays
 * unit-testable with node:test. Nothing here infers causality: branches are
 * edge fan-out, resources come from recorded metadata, commands from
 * recorded payloads (see lib/render.ts for the extractors). */

import { countByType } from "./filter.ts";
import { commandForEvent, eventReferencesResource } from "./render.ts";
import type {
  EventDetail,
  EventRecord,
  GraphOverview,
  OverviewNode,
} from "./types.ts";

/** In-failure-slice nodes in causal (sequence) order. */
export function sliceNodes(overview: GraphOverview): OverviewNode[] {
  return [...(overview.nodes ?? [])]
    .filter((n) => n.in_failure_slice)
    .sort((a, b) => a.logical_seq - b.logical_seq || (a.id < b.id ? -1 : 1));
}

export interface BranchPoint {
  id: string;
  label: string;
  logicalSeq: number;
  childIds: string[];
}

/** Declared fan-out: one event with two or more recorded children. This is
 * edge shape, not proof the branches interacted causally. */
export function branchPoints(overview: GraphOverview): BranchPoint[] {
  const byId = new Map((overview.nodes ?? []).map((n) => [n.id, n]));
  const kids = new Map<string, Set<string>>();
  for (const e of overview.edges ?? []) {
    if (!byId.has(e.parent) || !byId.has(e.child)) continue;
    let s = kids.get(e.parent);
    if (!s) {
      s = new Set();
      kids.set(e.parent, s);
    }
    s.add(e.child);
  }
  const out: BranchPoint[] = [];
  for (const [id, s] of kids) {
    if (s.size < 2) continue;
    const n = byId.get(id);
    out.push({
      id,
      label: n?.label ?? id,
      logicalSeq: n?.logical_seq ?? 0,
      childIds: [...s],
    });
  }
  return out.sort((a, b) => a.logicalSeq - b.logicalSeq || (a.id < b.id ? -1 : 1));
}

export interface MergePoint {
  id: string;
  label: string;
  logicalSeq: number;
  parentIds: string[];
}

/** Declared fan-in: one event with two or more recorded parents. Edge shape
 * only — convergence in the DAG, not proof of combined influence. */
export function mergePoints(overview: GraphOverview): MergePoint[] {
  const byId = new Map((overview.nodes ?? []).map((n) => [n.id, n]));
  const pars = new Map<string, Set<string>>();
  for (const e of overview.edges ?? []) {
    if (!byId.has(e.parent) || !byId.has(e.child)) continue;
    let s = pars.get(e.child);
    if (!s) {
      s = new Set();
      pars.set(e.child, s);
    }
    s.add(e.parent);
  }
  const out: MergePoint[] = [];
  for (const [id, s] of pars) {
    if (s.size < 2) continue;
    const n = byId.get(id);
    out.push({
      id,
      label: n?.label ?? id,
      logicalSeq: n?.logical_seq ?? 0,
      parentIds: [...s],
    });
  }
  return out.sort((a, b) => a.logicalSeq - b.logicalSeq || (a.id < b.id ? -1 : 1));
}

export interface TraceCensus {
  total: number;
  sliceSize: number;
  byType: Array<{ type: string; count: number }>;
  sliceByType: Array<{ type: string; count: number }>;
}

/** Event-type census of the whole dataset plus the failure slice. Counts
 * only — no interpretation of what the types mean. */
export function traceCensus(overview: GraphOverview): TraceCensus {
  const nodes = overview.nodes ?? [];
  return {
    total: nodes.length,
    sliceSize: nodes.filter((n) => n.in_failure_slice).length,
    byType: countByType(nodes),
    sliceByType: countByType(nodes.filter((n) => n.in_failure_slice)),
  };
}

/** Display name for a recorded resource: the path suffix after the last
 * slash (full recorded value stays in the title attribute). */
export function baseName(resource: string): string {
  const s = String(resource ?? "");
  const i = s.lastIndexOf("/");
  return i >= 0 ? s.slice(i + 1) : s;
}

function resourceCandidates(record: EventRecord | null | undefined): string[] {
  if (!record) return [];
  const payload = ((record.payload ?? {}) as Record<string, unknown>);
  const inner = ((payload["payload"] ?? {}) as Record<string, unknown>);
  const args = ((inner["args"] ?? {}) as Record<string, unknown>);
  const out: string[] = [];
  for (const c of [payload["resource_uri"], args["filePath"], args["path"], inner["file"]]) {
    if (typeof c === "string" && c !== "") out.push(c);
  }
  return out;
}

/** Distinct resources named in recorded detail metadata (full recorded
 * values; display via baseName). Discovery only — a resource appears here
 * because capture wrote it down, not because analysis judged it relevant. */
export function resourcesInDetails(details: Array<EventDetail | null>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const d of details) {
    for (const c of resourceCandidates(d?.record)) {
      if (!seen.has(c)) {
        seen.add(c);
        out.push(c);
      }
    }
  }
  return out;
}

/** Fetched slice details referencing a resource, in causal order. Same
 * exact-or-slash-suffix matching as eventReferencesResource. */
export function nodesForResource(
  details: Array<EventDetail | null>,
  resource: string,
): EventDetail[] {
  return details
    .filter((d): d is EventDetail => !!d && eventReferencesResource(d.record, resource))
    .sort(
      (a, b) =>
        (a.record.logical_seq ?? 0) - (b.record.logical_seq ?? 0) ||
        (a.id < b.id ? -1 : 1),
    );
}

export interface ToolStoryStep {
  id: string;
  logicalSeq: number;
  eventType: string;
  label: string;
  tool: string | null;
  command: string | null;
  commandSource: string | null;
}

function innerOf(record: EventRecord | null | undefined): Record<string, unknown> {
  const payload = (((record ?? {}).payload ?? {}) as Record<string, unknown>);
  return ((payload["payload"] ?? {}) as Record<string, unknown>);
}

/** The run's tool story: slice tool_call/tool_result events in order, each
 * with its recorded tool and command. Related records for command borrowing
 * are the event's declared parents only (a result borrows its call's
 * command; borrowing downhill from children would misattribute) — never
 * the whole set. */
export function toolStory(
  overview: GraphOverview,
  byId: ReadonlyMap<string, EventRecord>,
): ToolStoryStep[] {
  const parents = new Map<string, string[]>();
  for (const e of overview.edges ?? []) {
    parents.set(e.child, [...(parents.get(e.child) ?? []), e.parent]);
  }
  const out: ToolStoryStep[] = [];
  for (const n of sliceNodes(overview)) {
    if (n.event_type !== "tool_call" && n.event_type !== "tool_result") continue;
    const record = byId.get(n.id);
    const related: EventRecord[] = [];
    for (const pid of parents.get(n.id) ?? []) {
      const r = byId.get(pid);
      if (r) related.push(r);
    }
    const inner = innerOf(record);
    const tool = typeof inner["tool"] === "string" ? (inner["tool"] as string) : null;
    const cmd = commandForEvent(record, related);
    out.push({
      id: n.id,
      logicalSeq: n.logical_seq,
      eventType: n.event_type,
      label: n.label,
      tool,
      command: cmd.command,
      commandSource: cmd.source,
    });
  }
  return out;
}
