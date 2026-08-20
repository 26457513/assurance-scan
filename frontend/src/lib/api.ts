import type {
  CatalogueDriftResponse,
  CatalogueVersion,
  ComplianceListResponse,
  CompliancePack,
  ComplianceMatrixResponse,
  ConfigResponse,
  FindingAcceptance,
  FindingsListResponse,
  FrDetailResponse,
  FrHistoryResponse,
  FrListResponse,
  FoldersResponse,
  HealthResponse,
  MappingVersion,
  ProjectSummary,
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

  getCatalogueDrift: (projectPath: string) =>
    getJson<CatalogueDriftResponse>(
      `/api/catalogue/drift?project_path=${encodeURIComponent(projectPath)}`
    ),

  getCatalogueVersion: (snapshotId: string) =>
    getJson<Record<string, unknown>>(`/api/catalogue/versions/${encodeURIComponent(snapshotId)}`),

  listCatalogueVersions: (projectPath: string) =>
    getJson<{ versions: CatalogueVersion[] }>(
      `/api/catalogue/versions?project_path=${encodeURIComponent(projectPath)}`
    ),

  listMappingVersions: (projectPath: string) =>
    getJson<{ versions: MappingVersion[] }>(
      `/api/mappings/versions?project_path=${encodeURIComponent(projectPath)}`
    ),

  listCompliancePacks: () =>
    getJson<{ packs: CompliancePack[] }>('/api/compliance/packs'),

  getCompliancePack: (file: string) =>
    getJson<Record<string, unknown>>(`/api/compliance/packs/${encodeURIComponent(file)}`),

  listProjects: () => getJson<{ projects: ProjectSummary[] }>('/api/projects'),

  githubRepos: () =>
    getJson<{ org?: string; repos: { full_name: string; name?: string; pushed_at?: string; html_url?: string }[] }>(
      '/api/github/repos'
    ),

  githubSource: (repo: string, commit: string, path: string, line?: number | null) =>
    getJson<{
      unavailable?: boolean;
      start_line?: number;
      end_line?: number;
      highlight?: number;
      lines?: { n: number; text: string }[];
    }>(`/api/github/source?repo=${encodeURIComponent(repo)}&commit=${encodeURIComponent(commit)}&path=${encodeURIComponent(path)}${line ? `&line=${line}` : ''}`),

  createProject: (tag: string, localPath: string, githubUrl: string) =>
    getJson<{ status: string; tag: string; local_path: string; github_repo: string | null }>(
      '/api/projects',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag, local_path: localPath, github_url: githubUrl })
      }
    ),

  updateProject: (id: number, fields: { tag?: string; local_path?: string; github_url?: string }) =>
    getJson<{ status: string; tag: string; local_path: string; github_repo: string | null }>(
      `/api/projects/${id}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields)
      }
    ),

  deleteProject: (id: number) =>
    getJson<{ status: string }>(`/api/projects/${id}`, { method: 'DELETE' }),

  saveCatalogue: (projectPath: string, catalogueJson: string, tag = '') =>
    getJson<{ status: string; project?: string; catalogue_version?: string; fr_count?: number; content_hash?: string }>(
      `/api/catalogue?project_path=${encodeURIComponent(projectPath)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ catalogue_json: catalogueJson, tag })
      }
    ),

  me: () => getJson<{ email: string; role: string }>('/api/users/me'),

  listUsers: () => getJson<{ users: { email: string; role: string; last_login_at: string | null }[] }>('/api/users'),

  setUserRole: (email: string, role: string) =>
    getJson<{ email: string; role: string }>('/api/users', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, role })
    }),

  listOrgs: () => getJson<{ orgs: { name: string; login: string | null; created_at: string }[] }>('/api/orgs'),

  putOrg: (name: string, token: string) =>
    getJson<{ status: string; name: string; login: string; repos_visible: number }>('/api/orgs', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, token })
    }),

  deleteOrg: (name: string) =>
    getJson<{ status: string }>(`/api/orgs?name=${encodeURIComponent(name)}`, { method: 'DELETE' }),

  getGithubToken: () => getJson<{ configured: boolean; login?: string; created_at?: string }>('/api/github/token'),

  putGithubToken: (token: string) =>
    getJson<{ configured: boolean; login: string }>('/api/github/token', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token })
    }),

  deleteGithubToken: () =>
    getJson<{ configured: boolean }>('/api/github/token', { method: 'DELETE' }),

  scanRemote: (repo: string, ref = '') =>
    getJson<{ status: string; mode: string; repo: string; ref: string; warning?: string }>('/api/scans/remote', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo, ref })
    }),

  pollNow: () =>
    getJson<{ ingested?: number; skipped?: number; failed?: number; error?: string; hint?: string }>(
      '/api/poller/poll-now',
      { method: 'POST' }
    ),

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

  listFolders: (path?: string) => {
    const qs = path ? `?path=${encodeURIComponent(path)}` : '';
    return getJson<FoldersResponse>(`/api/folders${qs}`);
  },

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

  getComplianceMatrix: (framework: string, projectPath?: string, mappingHash?: string) => {
    const params = new URLSearchParams();
    if (projectPath) params.set('project_path', projectPath);
    if (mappingHash) params.set('mapping_hash', mappingHash);
    const qs = params.toString();
    return getJson<ComplianceMatrixResponse>(
      `/api/compliance/${encodeURIComponent(framework)}${qs ? `?${qs}` : ''}`
    );
  },

  getTrends: (projectPath?: string, limit = 20) => {
    const params = new URLSearchParams();
    if (projectPath) params.set('project_path', projectPath);
    params.set('limit', String(limit));
    return getJson<TrendsResponse>(`/api/trends?${params.toString()}`);
  },

  listFRs: (projectPath?: string, snapshotId?: string) => {
    const params = new URLSearchParams();
    if (projectPath) params.set('project_path', projectPath);
    if (snapshotId) params.set('snapshot_id', snapshotId);
    const qs = params.toString();
    return getJson<FrListResponse>(`/api/frs${qs ? `?${qs}` : ''}`);
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
