// Server API response types. Mirrors server/api/schemas/*.

export interface HealthResponse {
  status: string;
  db: string;
  docker_socket: string;
  version: string;
  uptime_seconds: number;
}

export interface ScanSummary {
  run_id: string;
  project_path: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  finding_count: number;
}

export interface ScannerStatus {
  kind: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
}

export interface ScanStatus {
  run_id: string;
  project_path: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  scanner_status: ScannerStatus[];
  options: Record<string, unknown>;
  error_message: string | null;
}

export interface ScanResponse {
  run_id: string;
  project_path: string;
  status: string;
  queued_at: string;
}

export interface FindingResponse {
  id: number;
  run_id: string;
  scanner_kind: string;
  rule_id: string | null;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN' | 'INFO';
  file_path: string | null;
  line_start: number | null;
  line_end: number | null;
  message: string;
  theme: string | null;
  fix_strategy: string | null;
  compliance_tags: string[];
}

export interface FindingsListResponse {
  run_id: string;
  total: number;
  by_severity: Record<string, number>;
  by_scanner: Record<string, number>;
  findings: FindingResponse[];
}

export interface CodeRef {
  kind: 'file' | 'glob' | 'symbol';
  ref: string;
}

export interface EvidenceSpec {
  type: string;
  source_kind?: string;
  rule_id?: string;
  name_pattern?: string;
  format?: string;
  expected_result?: 'pass' | 'fail' | 'info' | 'manual';
}

export interface RequiredEvidence {
  all_of?: EvidenceSpec[];
  any_of?: EvidenceSpec[];
  none_of?: EvidenceSpec[];
}

export interface EvidenceRow {
  id: number;
  type: string;
  source: Record<string, unknown>;
  result: string;
  collected_at: string | null;
  notes: string | null;
}

export interface FrDetailResponse {
  fr_id: string;
  title: string;
  description: string;
  implemented_by: CodeRef[];
  required_evidence: RequiredEvidence;
  satisfies: string[];
  depends_on: string[];
  project_path: string;
  run_id: string;
  state: string;
  reason: Record<string, unknown>;
  evidence: EvidenceRow[];
}

export interface FrHistoryEntry {
  run_id: string;
  state: string;
  reason: Record<string, unknown>;
  computed_at: string | null;
  run_started_at: string | null;
}

export interface FrHistoryResponse {
  fr_id: string;
  history: FrHistoryEntry[];
}

// ---------------------------------------------------------------------------
// Compliance
// ---------------------------------------------------------------------------

export interface ComplianceFrameworkSummary {
  id: string;
  rows: number;
  frs: number;
}

export interface ComplianceListResponse {
  frameworks: ComplianceFrameworkSummary[];
}

export interface ComplianceRow {
  row_id: string;
  fr_ids: string[];
  states: string[];
  projects: string[];
  worst_state: string;
}

export interface ComplianceMatrixResponse {
  framework: string;
  row_count: number;
  summary: Record<string, number>;
  rows: ComplianceRow[];
}

// ---------------------------------------------------------------------------
// Trends
// ---------------------------------------------------------------------------

export interface TrendEntry {
  run_id: string;
  project_path: string;
  status: string;
  started_at: string | null;
  total_findings: number;
  by_severity: Record<string, number>;
}

export interface TrendDelta {
  vs_run_id: string;
  total_delta: number;
  by_severity: Record<string, number>;
}

export interface TrendsResponse {
  runs: TrendEntry[];
  delta: TrendDelta | null;
}
