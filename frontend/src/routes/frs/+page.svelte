<script lang="ts">
  import { api } from '$lib/api';
  import { selectedProject } from '$lib/stores/selectedProject';
  import { pushToast } from '$lib/stores/toasts';
  import type { CatalogueVersion } from '$lib/types';

  let versions: CatalogueVersion[] = [];
  let org = '';
  // Registered/local projects carry their checkout path at setup; only
  // github:-only selections need the user to supply one.
  let manualPath = '';
  let pastedJson = '';
  let catalogueTag = '';
  let loading = true;
  let saving = false;
  let flow: 'agent' | 'paste' | null = null;
  let selectedVersionId: string | null = null;
  let versionJson = '';
  let showJson = false;
  let frRows: { fr_id: string; title: string; category: string | null; state: string; test_count: number; test_results: Record<string, number> }[] = [];
  const versionCache = new Map<string, string>();

  async function toggleVersion(v: CatalogueVersion) {
    if (selectedVersionId === v.snapshot_id) {
      selectedVersionId = null;
      versionJson = '';
      return;
    }
    selectedVersionId = v.snapshot_id;
    showJson = false;
    frRows = [];
    api.listFRs(undefined, v.snapshot_id)
      .then((res) => (frRows = res.frs))
      .catch(() => (frRows = []));
    if (versionCache.has(v.snapshot_id)) {
      versionJson = versionCache.get(v.snapshot_id)!;
      return;
    }
    try {
      const doc = await api.getCatalogueVersion(v.snapshot_id);
      const text = JSON.stringify(doc, null, 2);
      versionCache.set(v.snapshot_id, text);
      versionJson = text;
    } catch (e) {
      versionJson = `failed to load: ${e}`;
    }
  }

  function stateColor(state: string): string {
    if (state === 'pass' || state === 'passed') return 'var(--state-passed)';
    if (state === 'fail' || state === 'failed') return 'var(--state-failed)';
    if (state === 'waived') return 'var(--state-waived)';
    if (state === 'untested') return 'var(--state-untested)';
    return 'var(--state-pending)';
  }

  const LOCAL_PATH_KEY = 'assurance-scan:local-paths';

  $: project = $selectedProject ?? '';

  function rememberManualPath(p: string, path: string) {
    if (!p || !path) return;
    const store = JSON.parse(localStorage.getItem(LOCAL_PATH_KEY) ?? '{}');
    store[p] = path;
    localStorage.setItem(LOCAL_PATH_KEY, JSON.stringify(store));
  }

  $: isGithubOnly = project.startsWith('github:');
  $: agentPath = isGithubOnly ? manualPath.trim() : project;

  function derivedGithubPath(): string | null {
    const base = agentPath.replace(/\/$/, '').split('/').pop();
    if (!org || !base) return null;
    return `github:${org}/${base}`;
  }

  async function loadVersions() {
    if (!project) {
      versions = [];
      return;
    }
    try {
      // The server expands identities (registry pair + org alias).
      versions = (await api.listCatalogueVersions(project)).versions;
    } catch {
      versions = [];
    }
  }

  // Reload when the top-bar project selection changes.
  $: if (project) {
    if (isGithubOnly) {
      const store = JSON.parse(localStorage.getItem(LOCAL_PATH_KEY) ?? '{}');
      manualPath = store[project] ?? '';
    }
    flow = null;
    loadVersions();
  }

  $: latest = versions[0] ?? null;

  async function savePasted() {
    if (!project) return;
    saving = true;
    try {
      const res = await api.saveCatalogue(project, pastedJson, catalogueTag);
      pushToast('success', `Catalogue saved — ${res.fr_count ?? 0} FRs (${(res.content_hash ?? '').slice(0, 8)})`);
      pastedJson = '';
      await loadVersions();
    } catch (e) {
      pushToast('error', `Save failed: ${e}`);
    } finally {
      saving = false;
    }
  }

  function buildPrompt(): string {
    if (!agentPath) {
      return 'Enter the local checkout path first — the workflow needs it to explore the codebase.';
    }
    return `Call the assurance-scan MCP tool \`get_workflow\` with name="author-fr-catalogue" and parameters={"project_path": "${agentPath}"} and follow the returned workflow prompt.`;
  }

  async function copyPrompt() {
    if (!project) return;
    if (isGithubOnly) rememberManualPath(project, manualPath);
    try {
      await navigator.clipboard.writeText(buildPrompt());
      pushToast('success', 'Agent prompt copied — paste it into Claude Code');
    } catch {
      pushToast('error', 'Clipboard unavailable — copy the prompt text manually');
    }
  }

  const TEMPLATE = `{\n  "schema_version": 3,\n  "project": "project-name",\n  "catalogue_version": "2026-08-18T00:00:00Z",\n  "frs": [\n    {\n      "id": "FR-001",\n      "title": "Short capability name",\n      "description": "What the system must do.",\n      "category": "security",\n      "lifecycle_status": "in_scope",\n      "implemented_by": [{ "kind": "glob", "ref": "src/**/*.py" }],\n      "tests": [\n        { "id": "T-001", "type": "scanner-clean", "scanner": "semgrep", "rule_pattern": "python.lang.security.audit.eval*" },\n        { "id": "T-002", "type": "unit-test", "name_pattern": "tests/test_x.py::test_y", "expected_result": "pass" }\n      ]\n    }\n  ]\n}`;

  async function copyTemplate() {
    try {
      await navigator.clipboard.writeText(TEMPLATE);
      pushToast('success', 'Template copied');
    } catch {
      pushToast('error', 'Clipboard unavailable');
    }
  }

  function fmtDate(iso: string | null): string {
    if (!iso) return '—';
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  async function init() {
    try {
      const gh = await api.githubRepos().catch(() => ({ org: '', repos: [] }));
      org = gh.org ?? '';
    } catch {
      /* org stays empty — identity falls back to the selected project */
    }
    loading = false;
  }
  init();
</script>

<div class="p-6 max-w-6xl">
  <div class="mb-5">
    <div class="text-[15px] text-ink-primary mb-1">FR catalogue</div>
    <div class="text-[12px] text-ink-secondary">
      {#if project}
        <span class="font-mono">{project}</span>
        {#if latest}
          <span class="text-ink-muted"> · v{latest.version ?? '—'} · {latest.fr_count} FRs · saved {fmtDate(latest.created_at)}</span>
        {:else}
          <span class="text-ink-muted"> · no catalogue saved yet</span>
        {/if}
      {:else}
        Select a project in the top bar to manage its FR catalogue.
      {/if}
    </div>
  </div>

  {#if loading}
    <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else if project}
    {#if flow === null}
      <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
        <button
          type="button"
          on:click={() => (flow = 'agent')}
          class="text-left border border-line-strong rounded-sm bg-surface-panel hover:border-accent hover:bg-surface-elevated transition-colors p-6"
        >
          <div class="text-[14px] text-ink-primary mb-2 flex items-center gap-2">
            <svg class="h-4 w-4 text-accent" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
              <path d="M9 2l-5 9h3l-1 4 5-9H8l1-4z" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            Author with an agent
          </div>
          <p class="text-[12px] text-ink-secondary leading-relaxed">
            Copy an agentic prompt for Claude Code: it analyses the local checkout and saves a v3
            catalogue to this project via the MCP <code class="text-ink-primary">save_catalogue</code> tool.
          </p>
        </button>
        <button
          type="button"
          on:click={() => (flow = 'paste')}
          class="text-left border border-line-strong rounded-sm bg-surface-panel hover:border-accent hover:bg-surface-elevated transition-colors p-6"
        >
          <div class="text-[14px] text-ink-primary mb-2 flex items-center gap-2">
            <svg class="h-4 w-4 text-accent" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
              <rect x="4" y="2" width="8" height="12" rx="1" />
              <path d="M6.5 6.5h3M6.5 9h3" stroke-linecap="round" />
            </svg>
            Paste a catalogue
          </div>
          <p class="text-[12px] text-ink-secondary leading-relaxed">
            Already have a catalogue JSON? Paste it — it's validated against the v3 schema and stored
            as this project's current version.
          </p>
        </button>
      </div>
    {:else if flow === 'agent'}
      <section class="border border-line-hairline rounded-sm bg-surface-panel p-5">
        <div class="flex items-center justify-between mb-4">
          <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted">Author with an agent</div>
          <button type="button" on:click={() => (flow = null)} class="text-[11px] font-mono text-ink-muted hover:text-accent">✕ back</button>
        </div>
        {#if isGithubOnly}
          <label class="block text-[11px] font-mono text-ink-secondary mb-1" for="local-path">Local checkout path</label>
          <input
            id="local-path"
            type="text"
            bind:value={manualPath}
            on:blur={() => rememberManualPath(project, manualPath)}
            placeholder="/Users/you/Development/project"
            class="w-full max-w-xl px-2 py-1 mb-3 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary"
          />
        {:else}
          <div class="mb-3">
            <div class="text-[11px] font-mono text-ink-secondary mb-1">Local checkout (from project setup)</div>
            <div class="font-mono text-[11px] text-ink-primary border border-line-hairline rounded-sm bg-surface-base px-2 py-1 inline-block">{agentPath}</div>
          </div>
        {/if}
        <p class="text-[11px] text-ink-muted leading-relaxed mb-3 max-w-xl">
          Delegates to the server-side <code class="text-ink-secondary">author-fr-catalogue</code> workflow.
        </p>
        <pre class="text-[10px] font-mono text-ink-muted whitespace-pre-wrap max-h-48 overflow-y-auto border border-line-hairline rounded-sm bg-surface-base p-2 mb-3 max-w-xl">{buildPrompt()}</pre>
        <button
          type="button"
          on:click={copyPrompt}
          class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors"
        >Copy prompt</button>
      </section>
    {:else if flow === 'paste'}
      <section class="border border-line-hairline rounded-sm bg-surface-panel p-5">
        <div class="flex items-center justify-between mb-4">
          <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted">Paste a catalogue</div>
          <button type="button" on:click={() => (flow = null)} class="text-[11px] font-mono text-ink-muted hover:text-accent">✕ back</button>
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
          <div>
            <div class="text-[11px] font-mono text-ink-secondary mb-1">Expected format (v3)</div>
            <pre class="text-[10px] font-mono text-ink-muted whitespace-pre overflow-auto h-56 border border-line-hairline rounded-sm bg-surface-base p-2 mb-2">{TEMPLATE}</pre>
            <button
              type="button"
              on:click={copyTemplate}
              class="px-3 py-1 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[10px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors"
            >Copy template</button>
          </div>
          <div>
            <label class="block text-[11px] font-mono text-ink-secondary mb-1" for="paste-tag">Tag (shown in the catalogue dropdown)</label>
        <input
          id="paste-tag"
          type="text"
          bind:value={catalogueTag}
          placeholder="e.g. baseline-2026-08"
          class="w-full max-w-md px-2 py-1 mb-3 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary"
        />
        <label class="block text-[11px] font-mono text-ink-secondary mb-1" for="paste-json">Your catalogue</label>
            <textarea
              id="paste-json"
              bind:value={pastedJson}
              rows="14"
              placeholder="Paste your catalogue JSON here"
              class="w-full px-2 py-1 mb-3 border border-line-hairline rounded-sm bg-surface-base font-mono text-[10px] text-ink-primary"
            ></textarea>
            <button
              type="button"
              on:click={savePasted}
              disabled={saving || !pastedJson.trim()}
              class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors disabled:opacity-50"
            >{saving ? 'Saving…' : 'Save catalogue'}</button>
          </div>
        </div>
      </section>
    {/if}

    {#if versions.length > 0}
      <section class="mt-6">
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-2.5">Versions</div>
        <div class="as-table text-[11px]">
          <div class="as-head grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_80px_70px_140px_110px] gap-3">
            <div>Tag</div>
            <div>Version</div>
            <div class="text-right">FRs</div>
            <div>Origin</div>
            <div>Source</div>
            <div>Saved</div>
          </div>
          {#each versions as v (v.snapshot_id)}
            <div
              role="button"
              tabindex="0"
              on:click={() => toggleVersion(v)}
              on:keydown={(e) => e.key === 'Enter' && toggleVersion(v)}
              class="as-row as-row-click grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_80px_70px_140px_110px] gap-3 px-3 py-2"
              class:as-row-sel={selectedVersionId === v.snapshot_id}
            >
              <span class="text-ink-primary truncate">{v.tag ?? '—'}</span>
              <span class="text-ink-secondary truncate">{v.version ?? '(unversioned)'}</span>
              <span class="text-right text-ink-secondary tabular-nums">{v.fr_count}</span>
              <span class="text-ink-muted truncate" title={v.project_path ?? ''}>
                {v.project_path?.startsWith('github:') ? 'repo' : 'local'}
              </span>
              <span
                class="font-mono truncate {v.source_commit_sha ? 'text-ink-secondary' : 'text-ink-muted opacity-60'}"
                title={v.source_commit_sha ?? 'provenance not captured'}
              >
                {v.source_commit_sha ? `${v.source_branch ?? '?'}@${v.source_commit_sha.slice(0, 8)}` : '—'}
              </span>
              <span class="text-ink-muted">{fmtDate(v.created_at)}</span>
            </div>
          {/each}
        </div>
        {#if selectedVersionId}
          <pre class="mt-3 text-[10px] font-mono text-ink-secondary whitespace-pre overflow-auto max-h-[480px] border border-line-hairline rounded-sm bg-surface-base p-3">{versionJson}</pre>
        {/if}
      </section>
    {/if}
  {/if}
</div>
