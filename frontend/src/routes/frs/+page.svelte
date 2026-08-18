<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { selectedProject, selectProject } from '$lib/stores/selectedProject';
  import { pushToast } from '$lib/stores/toasts';
  import type { ProjectSummary } from '$lib/types';

  let projects: ProjectSummary[] = [];
  let versions: { snapshot_id: string; version?: string | null; fr_count: number; content_hash: string; created_at: string }[] = [];
  let localPath = '';
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

  async function loadVersions() {
    if (!project) {
      versions = [];
      return;
    }
    try {
      const data = await api.listCatalogueVersions(project);
      versions = data.versions;
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
      pushToast('success', `Catalogue saved — ${res.fr_count} FRs (${res.content_hash.slice(0, 8)})`);
      pastedJson = '';
      await loadVersions();
    } catch (e) {
      pushToast('error', `Save failed: ${e}`);
    } finally {
      saving = false;
    }
  }

  function buildPrompt(): string {
    const repo = project.replace(/^github:/, '');
    return [
      `Create an FR (functional requirements) catalogue for the project "${project}".`,
      ``,
      `1. Analyse the codebase at: ${localPath || '<LOCAL CHECKOUT PATH>'}`,
      `2. Produce a catalogue JSON document with this shape (schema v3):`,
      `   { "schema_version": 3, "project": "${repo.split('/').pop() ?? repo}", "catalogue_version": "<ISO timestamp>",`,
      `     "frs": [ { "id": "FR-001", "title": "...", "description": "...", "category": "...",`,
      `       "lifecycle_status": "in_scope",`,
      `       "implemented_by": [ { "kind": "file|glob|symbol", "ref": "..." } ],`,
      `       "tests": [ { "id": "T-001", "type": "scanner-clean", "scanner": "semgrep", "rule_pattern": "..." },`,
      `                  { "id": "T-002", "type": "unit-test", "name_pattern": "tests/test_x.py::test_y", "expected_result": "pass" } ] } ] }`,
      `   Derive FRs from real security and functional behaviour in this codebase; point implemented_by at actual files/globs/symbols and tests at real scanner rules or test names.`,
      `3. Save it by calling the assurance-scan MCP tool \`save_catalogue\` with project_path="${project}" and the catalogue as a JSON string.`,
      ``,
      `Report the FR ids you created when done.`
    ].join('\n');
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
          The prompt asks an agent to analyse that checkout and save the catalogue to this project via the MCP
          <code class="text-ink-secondary">save_catalogue</code> tool. Local path is remembered per project (a future bridge can supply it automatically).
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
          placeholder='{ "schema_version": 2, "project": "...", "frs": [...] }'
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
