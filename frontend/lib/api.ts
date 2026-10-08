/* Typed fetchers for the six read-only /api endpoints. Same origin in
 * production (the Python backend serves the exported app); in `npm run dev`
 * next.config.ts rewrites /api/* to the backend. Includes one shared
 * detail cache so the inspector, timeline lanes, and provenance chains never
 * refetch the same event. */

import type { AiDiagnosisReport, DiagnosisReport, EventDetail, EvidenceReport, FailureReport, GraphOverview } from "./types.ts";

export const ENDPOINTS = [
  "/api/overview",
  "/api/failure",
  "/api/diagnosis",
  "/api/evidence",
  "/api/event",
  "/api/ai-diagnosis",
] as const;

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

export function fetchOverview(): Promise<GraphOverview> {
  return getJson<GraphOverview>("/api/overview");
}

export function fetchFailure(): Promise<FailureReport> {
  return getJson<FailureReport>("/api/failure");
}

export function fetchDiagnosis(): Promise<DiagnosisReport> {
  return getJson<DiagnosisReport>("/api/diagnosis");
}

export function fetchEvidence(): Promise<EvidenceReport> {
  return getJson<EvidenceReport>("/api/evidence");
}

/** Opt-in model interpretation of the evidence package. Never auto-called:
 * only the WhyStrip "Generate AI analysis" button triggers it. Throws on
 * non-OK (503 no key, 502 model/format failure) — callers must surface the
 * error, never the local template, as the reply. */
export function fetchAiDiagnosis(): Promise<AiDiagnosisReport> {
  return getJson<AiDiagnosisReport>("/api/ai-diagnosis");
}

const detailCache = new Map<string, Promise<EventDetail>>();

/** Cached /api/event fetch shared by inspector, timeline, and provenance. */
export function fetchEventDetail(id: string): Promise<EventDetail> {
  let pending = detailCache.get(id);
  if (!pending) {
    pending = getJson<EventDetail>(`/api/event?id=${encodeURIComponent(id)}`);
    // A 404 must not poison the cache for every later caller.
    pending.catch(() => {
      detailCache.delete(id);
    });
    detailCache.set(id, pending);
  }
  return pending;
}

/** Recorded tool name for one event, or null when it has none. */
export async function fetchToolName(id: string): Promise<string | null> {
  try {
    const detail = await fetchEventDetail(id);
    const payload = (detail.record.payload ?? {}) as Record<string, unknown>;
    const inner = (payload["payload"] ?? {}) as Record<string, unknown>;
    return typeof inner["tool"] === "string" ? (inner["tool"] as string) : null;
  } catch {
    return null;
  }
}
