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

export interface ComplianceRef {
  ruleset: string;
  row: string;
}

export type TestType =
  | 'unit-test'
  | 'integration-test'
  | 'e2e-test'
  | 'scanner-clean'
  | 'scanner-clean-by-rule'
  | 'scanner-clean-by-severity'
  | 'scanner-finds'
  | 'manual-attestation'
  | 'imported';

export type TestResult = 'pass' | 'fail' | 'pending';

export interface TestSpec {
  id: string;
  type: TestType;
  description?: string;
  name_pattern?: string;
  scanner?: string;
  severity_floor?: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'UNKNOWN';
  rule_pattern?: string;
  format?: string;
  expected_result?: 'pass' | 'fail' | 'info' | 'manual';
}

export interface TestSpecWithResult extends TestSpec {
  result: TestResult;
  detail: Record<string, unknown>;
}

export interface FrDetailResponse {
  fr_id: string;
  title: string;
  description: string;
  category: string;
  implemented_by: CodeRef[];
  tests: TestSpecWithResult[];
  satisfies: ComplianceRef[];
  depends_on: string[];
  project_path: string;
  run_id: string;
  state: string;
  reason: Record<string, unknown>;
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

// ---------------------------------------------------------------------------
// FRs list (v3)
// ---------------------------------------------------------------------------

export interface FrListEntry {
  fr_id: string;
  title: string;
  category: string;
  state: string;
  is_gap: boolean;
  test_count: number;
  test_results: {
    pass: number;
    fail: number;
    pending: number;
  };
  satisfies: ComplianceRef[];
  depends_on: string[];
}

export interface FrListSummary {
  total: number;
  passed: number;
  failed: number;
  pending: number;
  untested: number;
  waived: number;
  blocked: number;
  gaps: number;
}

export interface FrListResponse {
  catalogue: {
    project: string;
    catalogue_version: string | null;
    fr_count: number;
    snapshot_id: string;
    created_at: string;
  } | null;
  run_id: string | null;
  summary: FrListSummary;
  frs: FrListEntry[];
}
