<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { selectedProject, selectProject } from '$lib/stores/selectedProject';
  import { pushToast } from '$lib/stores/toasts';
  import type { ProjectSummary } from '$lib/types';

  let projects: ProjectSummary[] = [];
  let versions: { snapshot_id: string; version?: string | null; fr_count: number; content_hash: string; created_at: string }[] = [];
  let localPath = '';
  let org = '';
  let pastedJson = '';
  let loading = true;
  let saving = false;

  const LOCAL_PATH_KEY = 'assurance-scan:local-paths';

  $: project = $selectedProject ?? '';

  function rememberLocalPath(p: string, path: string) {
    if (!p || !path) return;
    const store = JSON.parse(localStorage.getItem(LOCAL_PATH_KEY) ?? '{}');
    store[p] = path;
    localStorage.setItem(LOCAL_PATH_KEY, JSON.stringify(store));
  }

  function recallLocalPath(p: string): string {
    const store = JSON.parse(localStorage.getItem(LOCAL_PATH_KEY) ?? '{}');
    return store[p] ?? '';
  }

  function derivedGithubPath(): string | null {
    const base = localPath.replace(/\/$/, '').split('/').pop();
    if (!org || !base) return null;
    return `github:${org}/${base}`;
  }

  async function loadVersions() {
    if (!project) {
      versions = [];
      return;
    }
    const identities = [project, derivedGithubPath()].filter(Boolean) as string[];
    try {
      const lists = await Promise.all(identities.map((id) => api.listCatalogueVersions(id)));
      versions = lists
        .flatMap((l) => l.versions)
        .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''));
    } catch {
      versions = [];
    }
  }

  $: latest = versions[0] ?? null;

  async function savePasted() {
    if (!project) return;
    saving = true;
    try {
      const res = await api.saveCatalogue(project, pastedJson);
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
    if (!localPath.trim()) {
      return 'Enter the local checkout path first — the workflow needs it to explore the codebase.';
    }
    const identity = derivedGithubPath();
    const lines = [
      `Call the assurance-scan MCP tool \`get_workflow\` with name="generate-fr-catalogue" and parameters={"project_path": "${localPath}"} and follow the returned workflow prompt.`
    ];
    if (identity && identity !== project) {
      lines.push(
        ``,
        `One change: when saving via \`save_catalogue\`, use project_path="${identity}" — this project's GitHub identity — not the local path.`
      );
    }
    return lines.join('\n');
  }

  async function copyPrompt() {
    if (!project) return;
    rememberLocalPath(project, localPath);
    try {
      await navigator.clipboard.writeText(buildPrompt());
      pushToast('success', 'Agent prompt copied — paste it into Claude Code');
    } catch {
      pushToast('error', 'Clipboard unavailable — copy the prompt text manually');
    }
  }

  function onProjectChange(e: Event) {
    const value = (e.target as HTMLSelectElement).value;
    selectProject(value);
    localPath = recallLocalPath(value);
    loadVersions();
  }

  function fmtDate(iso: string | null): string {
    if (!iso) return '—';
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  onMount(async () => {
    try {
      const gh = await api.githubRepos().catch(() => ({ org: '', repos: [] }));
      org = gh.org ?? '';
    } catch {
      /* org stays empty — identity falls back to the selected project */
    }
    try {
      const data = await api.listProjects();
      projects = data.projects;
      if (!project && projects.length) selectProject(projects[0].project_path);
    } catch {
      /* leave selection empty */
    }
    localPath = recallLocalPath(project);
    await loadVersions();
    loading = false;
  });
</script>

<div class="p-6 max-w-6xl">
  <div class="mb-4">
    <div class="text-[15px] text-ink-primary mb-1">FR catalogue</div>
    <div class="text-[12px] text-ink-secondary">
      The project's functional requirements. Paste a catalogue, or hand an agent prompt to Claude Code to author one.
    </div>
  </div>

  <div class="flex items-center gap-3 mb-5 font-mono text-[11px]">
    <select
      value={project}
      on:change={onProjectChange}
      class="px-2 py-1 border border-line-strong rounded-sm bg-surface-elevated text-ink-primary max-w-md"
      aria-label="Project"
    >
      {#each projects as p (p.project_path)}
        <option value={p.project_path}>{p.project_path}</option>
      {/each}
    </select>
    {#if latest}
      <span class="text-ink-muted">
        current: v{latest.version ?? '—'} · {latest.fr_count} FRs · saved {fmtDate(latest.created_at)}
      </span>
    {:else}
      <span class="text-ink-muted">no catalogue saved yet</span>
    {/if}
  </div>

  {#if loading}
    <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else}
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
      <section class="border border-line-hairline rounded-sm bg-surface-panel p-4">
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-3">Agent prompt</div>
        <label class="block text-[11px] font-mono text-ink-secondary mb-1" for="local-path">Local checkout path</label>
        <input
          id="local-path"
          type="text"
          bind:value={localPath}
          on:blur={() => rememberLocalPath(project, localPath)}
          placeholder="/Users/you/Development/project"
          class="w-full px-2 py-1 mb-3 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary"
        />
        <p class="text-[11px] text-ink-muted leading-relaxed mb-3">
          Delegates to the server-side <code class="text-ink-secondary">generate-fr-catalogue</code> workflow; the agent
          explores the local checkout and saves the catalogue under this project's identity. Local path is remembered
          per project (a future bridge can supply it automatically).
        </p>
        <pre class="text-[10px] font-mono text-ink-muted whitespace-pre-wrap max-h-48 overflow-y-auto border border-line-hairline rounded-sm bg-surface-base p-2 mb-3">{buildPrompt()}</pre>
        <button
          type="button"
          on:click={copyPrompt}
          disabled={!project}
          class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors disabled:opacity-50"
        >Copy prompt</button>
      </section>

      <section class="border border-line-hairline rounded-sm bg-surface-panel p-4">
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-3">Paste catalogue</div>
        <textarea
          bind:value={pastedJson}
          rows="10"
          placeholder={'{ "schema_version": 3, "project": "...", "frs": [...] }'}
          class="w-full px-2 py-1 mb-3 border border-line-hairline rounded-sm bg-surface-base font-mono text-[10px] text-ink-primary"
        ></textarea>
        <button
          type="button"
          on:click={savePasted}
          disabled={!project || saving || !pastedJson.trim()}
          class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors disabled:opacity-50"
        >{saving ? 'Saving…' : 'Save catalogue'}</button>
      </section>
    </div>

    {#if versions.length > 0}
      <section class="mt-6">
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-2.5">Versions</div>
        <div class="border border-line-hairline rounded-sm overflow-hidden bg-surface-panel font-mono text-[11px]">
          {#each versions as v (v.snapshot_id)}
            <div class="flex items-center gap-4 px-3 py-2 border-b border-line-hairline last:border-0">
              <span class="text-ink-primary w-40 truncate">{v.version ?? '(unversioned)'}</span>
              <span class="text-ink-secondary tabular-nums w-16">{v.fr_count} FRs</span>
              <span class="text-ink-muted truncate flex-1" title={v.content_hash}>{v.content_hash.slice(0, 16)}</span>
              <span class="text-ink-muted">{fmtDate(v.created_at)}</span>
            </div>
          {/each}
        </div>
      </section>
    {/if}
  {/if}
</div>
