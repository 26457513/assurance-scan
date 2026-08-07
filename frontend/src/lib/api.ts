import type {
  ComplianceListResponse,
  ComplianceMatrixResponse,
  FindingsListResponse,
  FrDetailResponse,
  FrHistoryResponse,
  HealthResponse,
  ScanResponse,
  ScanStatus,
  ScanSummary,
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

  listScans: () => getJson<ScanSummary[]>('/api/scans'),

  getScan: (runId: string) => getJson<ScanStatus>(`/api/scans/${runId}`),

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
  }
};
