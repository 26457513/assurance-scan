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
  ScanTokenCreateResponse,
  ScanTokenExpiryDays,
  ScanTokenListResponse,
  ScanResponse,
  ScanStatus,
  ScanSummary,
  SourceContextResponse,
  TestSourceResponse,
  TrendCommits,
  TrendsResponse,
} from './types';

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.text();
    try {
      const detail = JSON.parse(body)?.detail;
      if (typeof detail === 'string') throw new Error(detail);
    } catch (e) {
      if (e instanceof SyntaxError) { /* not JSON — fall through */ }
      else throw e;
    }
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => getJson<HealthResponse>('/health'),

  listScans: (projectId?: number, limit?: number) => {
    const params = new URLSearchParams();
    if (projectId != null) params.set('project_id', String(projectId));
    if (limit != null) params.set('limit', String(limit));
    const qs = params.toString();
    return getJson<ScanSummary[]>(`/api/scans${qs ? `?${qs}` : ''}`);
  },

  listScansForSelector: () => getJson<ScanSummary[]>('/api/scans?limit=15'),

  listWorkflows: () =>
    getJson<{ workflows: { name: string; description: string; parameters: { name: string; description?: string }[] }[] }>('/api/workflows'),

  getCiWorkflowTemplate: () =>
    getJson<{ filename: string; image: string; uploader_image: string; workflow: string }>(
      '/api/ci/workflow-template'
    ),

  postNotionDigest: () =>
    getJson<{ status: string; projects: number; critical: number; high: number; failed_runs: number; blocks: number }>('/api/notion/digest', { method: 'POST' }),

  getTrendsForScanList: () => getJson<TrendsResponse>('/api/trends?limit=30'),

  getTrendCommits: (projectId: number, branch = '') =>
    getJson<TrendCommits>(`/api/trends/commits?project_id=${projectId}&branch=${encodeURIComponent(branch)}`),

  getScan: (runId: string) => getJson<ScanStatus>(`/api/scans/${runId}`),

  getCatalogueDrift: (projectId: number) =>
    getJson<CatalogueDriftResponse>(
      `/api/catalogue/drift?project_id=${projectId}`
    ),

  getCatalogueVersion: (projectId: number, snapshotId: string) =>
    getJson<Record<string, unknown>>(
      `/api/catalogue/versions/${encodeURIComponent(snapshotId)}?project_id=${projectId}`
    ),

  listCatalogueVersions: (projectId: number) =>
    getJson<{ versions: CatalogueVersion[] }>(
      `/api/catalogue/versions?project_id=${projectId}`
    ),

  listMappingVersions: (projectId: number) =>
    getJson<{ versions: MappingVersion[] }>(
      `/api/mappings/versions?project_id=${projectId}`
    ),

  getMappingVersion: (projectId: number, snapshotId: string) =>
    getJson<Record<string, unknown>>(
      `/api/mappings/versions/${encodeURIComponent(snapshotId)}?project_id=${projectId}`
    ),

  saveMapping: (projectId: number, mappingJson: string) =>
    getJson<{ status: string; project_id?: number; content_hash?: string; mapping_count?: number }>(
      `/api/mappings?project_id=${projectId}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mapping_json: mappingJson })
      }
    ),

  complianceGrid: (projectId: number) =>
    getJson<{
      versions: { snapshot_id: string; tag: string | null; version: string | null; source_branch: string | null; source_commit_sha: string | null; created_at: string }[];
      branches: string[];
      cells: Record<string, { run_id: string; started_at: string | null; ok: number; gaps: number; states: Record<string, number> }>;
    }>(`/api/compliance/grid?project_id=${projectId}`),

  listCompliancePacks: () =>
    getJson<{ packs: CompliancePack[] }>('/api/compliance/packs'),

  getCompliancePack: (file: string) =>
    getJson<Record<string, unknown>>(`/api/compliance/packs/${encodeURIComponent(file)}`),

  listProjects: () => getJson<{ projects: ProjectSummary[] }>('/api/projects'),

  githubBranches: (repo: string) =>
    getJson<{ repo: string; branches: string[] }>(`/api/github/branches?repo=${encodeURIComponent(repo)}`),

  githubRepos: () =>
    getJson<{
      org?: string;
      repos: { full_name: string; name?: string; org?: string; pushed_at?: string; html_url?: string }[];
      errors?: string[];
    }>('/api/github/repos'),

  createProject: (
    tag: string,
    localPath: string | null,
    githubRepo: string | null,
    defaultScanRef: string | null = null
  ) =>
    getJson<ProjectSummary>(
      '/api/projects',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tag,
          local_path: localPath,
          github_repo: githubRepo,
          default_scan_ref: defaultScanRef
        })
      }
    ),

  updateProject: (id: number, fields: { tag?: string; local_path?: string | null; github_repo?: string | null }) =>
    getJson<ProjectSummary>(
      `/api/projects/${id}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields)
      }
    ),

  deleteProject: (id: number) =>
    getJson<{ status: string }>(`/api/projects/${id}`, { method: 'DELETE' }),

  saveCatalogue: (projectId: number, catalogueJson: string, tag = '') =>
    getJson<{ status: string; project_id?: number; catalogue_version?: string; fr_count?: number; content_hash?: string }>(
      `/api/catalogue?project_id=${projectId}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ catalogue_json: catalogueJson, tag })
      }
    ),

  logout: async (): Promise<void> => {
    // redirect:'manual' — the endpoint 307s to the login flow, and following
    // it into the Google redirect chain fails fetch on CORS. The cookie is
    // cleared by the first response either way.
    await fetch('/auth/logout', { method: 'GET', redirect: 'manual' });
  },

  getMcpTokenStatus: () =>
    getJson<{ has_token: boolean; generated_at: string | null }>('/api/users/me/mcp-token'),

  previewMcpToken: () =>
    getJson<{ token: string; command: string; base_url: string }>('/api/users/me/mcp-token/preview', {
      method: 'POST'
    }),

  applyMcpToken: (token: string) =>
    getJson<{ status: string }>('/api/users/me/mcp-token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token })
    }),

  revokeMcpToken: () =>
    getJson<{ status: string }>('/api/users/me/mcp-token', { method: 'DELETE' }),

  listScanTokens: () =>
    getJson<ScanTokenListResponse>('/api/users/me/scan-tokens'),

  createScanToken: (label: string, expiresInDays: ScanTokenExpiryDays, csrfToken: string) =>
    getJson<ScanTokenCreateResponse>('/api/users/me/scan-tokens', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken
      },
      body: JSON.stringify({ label, expires_in_days: expiresInDays })
    }),

  revokeScanToken: (tokenId: string, csrfToken: string) =>
    getJson<{ status: string }>(
      `/api/users/me/scan-tokens/${encodeURIComponent(tokenId)}`,
      {
        method: 'DELETE',
        headers: { 'X-CSRF-Token': csrfToken }
      }
    ),

  me: () => getJson<{ email: string; role: string }>('/api/users/me'),

  githubAccountLinkStatus: () =>
    getJson<{ enabled: boolean; linked: boolean; login: string | null }>(
      '/api/v2/github/link/status'
    ),

  listUsers: () => getJson<{ users: { email: string; role: string; last_login_at: string | null }[] }>('/api/users'),

  setUserRole: (email: string, role: string) =>
    getJson<{ email: string; role: string }>('/api/users', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, role })
    }),

  listOrgs: () => getJson<{ orgs: { name: string; login: string | null; created_at: string | null; home?: boolean }[] }>('/api/orgs'),

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

  scanRemote: (projectId: number, ref = '') =>
    getJson<{ status: string; mode: string; repo: string; ref: string; warning?: string; detail?: string }>('/api/scans/remote', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId, ref })
    }),

  pollNow: () =>
    getJson<{ ingested?: number; skipped?: number; failed?: number; error?: string; hint?: string }>(
      '/api/poller/poll-now',
      { method: 'POST' }
    ),

  deleteScan: (runId: string) =>
    getJson<{ status: string; run_id: string }>(`/api/scans/${runId}`, { method: 'DELETE' }),

  deleteAllScans: (projectId: number) =>
    getJson<{ status: string; count: number }>(`/api/scans?project_id=${projectId}`, { method: 'DELETE' }),

  startScan: (projectId: number, options?: Record<string, unknown>) =>
    getJson<ScanResponse>('/api/scans', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ project_id: projectId, options: options ?? {} })
    }),

  listFolders: (path?: string) => {
    const qs = path ? `?path=${encodeURIComponent(path)}` : '';
    return getJson<FoldersResponse>(`/api/folders${qs}`);
  },

  listFindings: (runId: string, severity?: string) => {
    const qs = severity ? `?severity=${encodeURIComponent(severity)}` : '';
    return getJson<FindingsListResponse>(`/api/scans/${runId}/findings${qs}`);
  },

  findingSourceContext: (runId: string, findingId: number) =>
    getJson<SourceContextResponse>(
      `/api/scans/${encodeURIComponent(runId)}/findings/${findingId}/source-context`
    ),

  findingsJson: async (runId: string): Promise<string> => {
    const res = await fetch(`/api/scans/${runId}/findings.json`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.text();
  },

  getFr: (frId: string, projectId: number, runId?: string) => {
    const params = new URLSearchParams({ project_id: String(projectId) });
    if (runId) params.set('run_id', runId);
    return getJson<FrDetailResponse>(
      `/api/frs/${encodeURIComponent(frId)}?${params.toString()}`
    );
  },

  getFrHistory: (frId: string, projectId: number) =>
    getJson<FrHistoryResponse>(
      `/api/frs/${encodeURIComponent(frId)}/history?project_id=${projectId}`
    ),

  listComplianceFrameworks: () =>
    getJson<ComplianceListResponse>('/api/compliance'),

  getComplianceMatrix: (framework: string, projectId?: number, mappingHash?: string) => {
    const params = new URLSearchParams();
    if (projectId != null) params.set('project_id', String(projectId));
    if (mappingHash) params.set('mapping_hash', mappingHash);
    const qs = params.toString();
    return getJson<ComplianceMatrixResponse>(
      `/api/compliance/${encodeURIComponent(framework)}${qs ? `?${qs}` : ''}`
    );
  },

  getTrends: (projectId?: number, limit = 20) => {
    const params = new URLSearchParams();
    if (projectId != null) params.set('project_id', String(projectId));
    params.set('limit', String(limit));
    return getJson<TrendsResponse>(`/api/trends?${params.toString()}`);
  },

  listFRs: (projectId?: number, snapshotId?: string) => {
    const params = new URLSearchParams();
    if (projectId != null) params.set('project_id', String(projectId));
    if (snapshotId) params.set('snapshot_id', snapshotId);
    const qs = params.toString();
    return getJson<FrListResponse>(`/api/frs${qs ? `?${qs}` : ''}`);
  },

  getTestSource: (namePattern: string, projectId: number) => {
    const params = new URLSearchParams({
      name_pattern: namePattern,
      project_id: String(projectId)
    });
    return getJson<TestSourceResponse>(`/api/test-source?${params.toString()}`);
  },

  getConfig: (projectId: number) => {
    const params = new URLSearchParams({ project_id: String(projectId) });
    return getJson<ConfigResponse>(`/api/config?${params.toString()}`);
  },

  acceptFinding: (params: {
    project_id: number;
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

  listAcceptedFindings: (projectId: number) => {
    const params = new URLSearchParams({ project_id: String(projectId) });
    return getJson<{ acceptances: FindingAcceptance[] }>(`/api/findings/accepted?${params.toString()}`);
  }
};
