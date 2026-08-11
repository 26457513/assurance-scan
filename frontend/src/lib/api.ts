import type {
  ComplianceListResponse,
  ComplianceMatrixResponse,
  ConfigResponse,
  FindingAcceptance,
  FindingsListResponse,
  FrDetailResponse,
  FrHistoryResponse,
  FrListResponse,
  HealthResponse,
  ScanResponse,
  ScanStatus,
  ScanSummary,
  TestSourceResponse,
  TrendsResponse
} from './types';

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => getJson<HealthResponse>('/health'),

  listScans: (limit?: number) => {
    const qs = limit ? `?limit=${limit}` : '';
    return getJson<ScanSummary[]>(`/api/scans${qs}`);
  },

  listScansForSelector: () => getJson<ScanSummary[]>('/api/scans?limit=15'),

  getTrendsForScanList: () => getJson<TrendsResponse>('/api/trends?limit=30'),

  getScan: (runId: string) => getJson<ScanStatus>(`/api/scans/${runId}`),

  deleteScan: (runId: string) =>
    getJson<{ status: string; run_id: string }>(`/api/scans/${runId}`, { method: 'DELETE' }),

  deleteAllScans: (projectPath?: string) => {
    const qs = projectPath ? `?project_path=${encodeURIComponent(projectPath)}` : '';
    return getJson<{ status: string; count: number }>(`/api/scans${qs}`, { method: 'DELETE' });
  },

  startScan: (projectPath?: string, options?: Record<string, unknown>) =>
    getJson<ScanResponse>('/api/scans', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ project_path: projectPath, options: options ?? {} })
    }),

  listFindings: (runId: string, severity?: string) => {
    const qs = severity ? `?severity=${encodeURIComponent(severity)}` : '';
    return getJson<FindingsListResponse>(`/api/scans/${runId}/findings${qs}`);
  },

  findingsJson: async (runId: string): Promise<string> => {
    const res = await fetch(`/api/scans/${runId}/findings.json`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.text();
  },

  getFr: (frId: string, runId?: string) => {
    const qs = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
    return getJson<FrDetailResponse>(`/api/frs/${encodeURIComponent(frId)}${qs}`);
  },

  getFrHistory: (frId: string) =>
    getJson<FrHistoryResponse>(`/api/frs/${encodeURIComponent(frId)}/history`),

  listComplianceFrameworks: () =>
    getJson<ComplianceListResponse>('/api/compliance'),

  getComplianceMatrix: (framework: string, projectPath?: string) => {
    const qs = projectPath ? `?project_path=${encodeURIComponent(projectPath)}` : '';
    return getJson<ComplianceMatrixResponse>(`/api/compliance/${encodeURIComponent(framework)}${qs}`);
  },

  getTrends: (projectPath?: string, limit = 20) => {
    const params = new URLSearchParams();
    if (projectPath) params.set('project_path', projectPath);
    params.set('limit', String(limit));
    return getJson<TrendsResponse>(`/api/trends?${params.toString()}`);
  },

  listFRs: (projectPath?: string) => {
    const qs = projectPath ? `?project_path=${encodeURIComponent(projectPath)}` : '';
    return getJson<FrListResponse>(`/api/frs${qs}`);
  },

  getTestSource: (namePattern: string, projectPath: string) => {
    const params = new URLSearchParams({
      name_pattern: namePattern,
      project_path: projectPath
    });
    return getJson<TestSourceResponse>(`/api/test-source?${params.toString()}`);
  },

  getConfig: (projectPath: string) => {
    const params = new URLSearchParams({ project_path: projectPath });
    return getJson<ConfigResponse>(`/api/config?${params.toString()}`);
  },

  acceptFinding: (params: {
    project_path: string;
    scanner_kind: string;
    rule_id: string;
    risk_level: string;
    rationale: string;
    fix_assessment?: string | null;
    invalidation_conditions?: string | null;
    accepted_by?: string;
  }) => getJson<{ status: string }>('/api/findings/accept', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(params)
  }),

  unacceptFinding: (id: number) =>
    getJson<{ status: string }>(`/api/findings/accept/${id}`, { method: 'DELETE' }),

  listAcceptedFindings: (projectPath: string) => {
    const params = new URLSearchParams({ project_path: projectPath });
    return getJson<{ acceptances: FindingAcceptance[] }>(`/api/findings/accepted?${params.toString()}`);
  }
};
