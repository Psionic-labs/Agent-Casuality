/* API shapes returned by the read-only explorer backend (explorer/queries.py).
 * The frontend never invents fields: every property here mirrors one the
 * six /api endpoints already return. */

export interface OverviewNode {
  id: string;
  event_type: string;
  opencode_kind: string;
  agent_id: string;
  logical_seq: number;
  wall_time: string;
  label: string;
  role: string | null;
  in_failure_slice: boolean;
}

export interface OverviewEdge {
  parent: string;
  child: string;
}

export interface GraphOverview {
  source: string;
  event_count: number;
  edge_count: number;
  failure_event_id: string | null;
  failure_status: string | null;
  failure_method: string | null;
  nodes: OverviewNode[];
  edges: OverviewEdge[];
}

export interface RoleHit {
  event_id: string;
  label: string;
}

export interface FailureReport {
  failure_event_id: string | null;
  status: string | null;
  method: string | null;
  is_fallback: boolean;
  has_ground_truth: boolean;
  roles: Record<string, RoleHit[]>;
  unresolved_roles: string[];
  expected_structural_roles: string[];
}

export interface EventRef {
  event_id: string;
  label: string;
}

/** The stored event record as returned by /api/event (JSON round-tripped). */
export interface EventRecord {
  id?: string;
  event_type?: string;
  agent_id?: string;
  logical_seq?: number;
  wall_time?: string;
  causal_parent_ids?: string[];
  payload?: Record<string, unknown>;
}

export interface EventDetail {
  id: string;
  label: string;
  role: string | null;
  in_failure_slice: boolean;
  parents: EventRef[];
  children: EventRef[];
  record: EventRecord;
}

/** One benchmark diagnosis dimension (exact backend vocabulary preserved). */
export interface DiagnosisDim {
  status?: string;
  metric?: string;
  label?: string;
  [key: string]: unknown;
}

export interface DiagnosisReport {
  status: string;
  dimensions: Record<string, DiagnosisDim>;
}

export interface EvidenceReport {
  status: string;
  summary: string;
  package: {
    provenance?: Array<{ target?: string; edges?: Array<{ grade?: string }> }>;
    [key: string]: unknown;
  };
}

/** Validated model interpretation from /api/ai-diagnosis (opt-in, quarantined
 * from evidence: the backend guarantees this text passed the format contract,
 * never the local template). */
export interface AiDiagnosisSections {
  diagnosis: string;
  evidence: string[];
  limitations: string;
}

export interface AiDiagnosisReport {
  status: string;
  model?: string;
  generated_at?: string;
  sections?: AiDiagnosisSections;
  error?: string;
}
