/* Event-type filter for the Graph and Timeline views. Pure and
 * framework-free so it stays unit-testable with node:test.
 *
 * Live OpenCode captures are dominated by streaming noise: every message
 * part update is a context_update event (75-80% of a session) plus one
 * model_call per turn. The story of a run — reads, edits, test commands
 * and their results — is in the tool_call / tool_result events. Filtering
 * hides nodes from the *views* only: no edges are invented, edges touching
 * a hidden endpoint are dropped (never rewired), dataset-level counts and
 * the failure target are preserved, and the inspector still resolves any
 * event by id. */

import type { GraphOverview, OverviewNode } from "./types.ts";

/** Types visible under the default "Key events" preset. */
export const KEY_EVENT_TYPES: ReadonlySet<string> = new Set([
  "run_start",
  "run_finish",
  "agent_error",
  "tool_call",
  "tool_result",
]);

/** Hidden by default: per-part streaming updates and per-turn model calls. */
export const DEFAULT_HIDDEN_TYPES: ReadonlySet<string> = new Set([
  "context_update",
  "model_call",
]);

/** Event-type census of a node list, in first-appearance order. */
export function countByType(nodes: OverviewNode[]): Array<{ type: string; count: number }> {
  const counts = new Map<string, number>();
  for (const n of nodes) counts.set(n.event_type, (counts.get(n.event_type) ?? 0) + 1);
  return [...counts].map(([type, count]) => ({ type, count }));
}

/** Overview restricted to non-hidden types. Edges keep only pairs whose
 * parent AND child are both visible; nothing is rewired or invented. The
 * failure node is always kept regardless of its type: it anchors the
 * diagnosis, and on fallback datasets it is often a hidden-type event
 * (e.g. a trailing context_update), so type-only filtering would otherwise
 * remove the one node the views are about. */
export function filterOverview(
  overview: GraphOverview,
  hidden: ReadonlySet<string>,
  failureId: string | null = null,
): GraphOverview {
  if (hidden.size === 0) return overview;
  const kept = new Set<string>();
  const nodes = overview.nodes.filter((n) => {
    if (n.id === failureId) {
      kept.add(n.id);
      return true;
    }
    if (hidden.has(n.event_type)) return false;
    kept.add(n.id);
    return true;
  });
  const edges = overview.edges.filter((e) => kept.has(e.parent) && kept.has(e.child));
  return { ...overview, nodes, edges };
}

export interface SessionInfo {
  /** Declared capture fact: the agent (session) id, e.g. "opencode:ses_abc". */
  agent: string;
  count: number;
  /** Max wall_time in the session; "" when no node carries one. */
  lastWallTime: string;
}

/** Short display label for a session id: strips the "opencode:" capture
 * prefix and truncates long ids with an ellipsis (full id stays in title). */
export function shortSessionId(agent: string): string {
  const bare = agent.startsWith("opencode:") ? agent.slice("opencode:".length) : agent;
  return bare.length > 18 ? `${bare.slice(0, 12)}…` : bare;
}

/** One entry per declared agent id, latest activity first. Sessions are
 * capture facts (agent_id on every node) — grouping by them invents
 * nothing. */
export function listSessions(nodes: OverviewNode[]): SessionInfo[] {
  const byAgent = new Map<string, { count: number; lastWallTime: string }>();
  for (const n of nodes) {
    const entry = byAgent.get(n.agent_id) ?? { count: 0, lastWallTime: "" };
    entry.count += 1;
    if (n.wall_time && n.wall_time > entry.lastWallTime) entry.lastWallTime = n.wall_time;
    byAgent.set(n.agent_id, entry);
  }
  return [...byAgent]
    .map(([agent, { count, lastWallTime }]) => ({ agent, count, lastWallTime }))
    .sort(
      (a, b) =>
        (b.lastWallTime < a.lastWallTime ? -1 : b.lastWallTime > a.lastWallTime ? 1 : 0) ||
        b.count - a.count ||
        (a.agent < b.agent ? -1 : 1),
    );
}

/** Overview restricted to one session (null/"" keeps all sessions). Edges
 * keep only pairs inside the session; dataset counts and the failure
 * target are preserved untouched. */
export function filterSession(
  overview: GraphOverview,
  agent: string | null,
): GraphOverview {
  if (!agent) return overview;
  const kept = new Set<string>();
  const nodes = overview.nodes.filter((n) => {
    if (n.agent_id !== agent) return false;
    kept.add(n.id);
    return true;
  });
  const edges = overview.edges.filter((e) => kept.has(e.parent) && kept.has(e.child));
  return { ...overview, nodes, edges };
}
