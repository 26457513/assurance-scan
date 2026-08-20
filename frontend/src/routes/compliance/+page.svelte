<script lang="ts">
  import { api } from '$lib/api';
  import { selectedProject } from '$lib/stores/selectedProject';
  import { pushToast } from '$lib/stores/toasts';
  import type { MappingVersion } from '$lib/types';

  let versions: MappingVersion[] = [];
  let pastedJson = '';
  let framework = 'ASVS';
  let saving = false;
  let flow: 'agent' | 'paste' | null = null;
  let selectedVersionId: string | null = null;
  let versionJson = '';
  const versionCache = new Map<string, string>();

  $: project = $selectedProject ?? '';

  async function loadVersions() {
    if (!project) {
      versions = [];
      return;
    }
    try {
      versions = (await api.listMappingVersions(project)).versions;
    } catch {
      versions = [];
    }
  }

  // Reload when the top-bar project selection changes.
  $: if (project) {
    flow = null;
    loadVersions();
  }

  $: latest = versions[0] ?? null;

  async function toggleVersion(v: MappingVersion) {
    if (selectedVersionId === v.snapshot_id) {
      selectedVersionId = null;
      versionJson = '';
      return;
    }
    selectedVersionId = v.snapshot_id;
    if (versionCache.has(v.snapshot_id)) {
      versionJson = versionCache.get(v.snapshot_id)!;
      return;
    }
    try {
      const doc = await api.getMappingVersion(v.snapshot_id);
      const text = JSON.stringify(doc, null, 2);
      versionCache.set(v.snapshot_id, text);
      versionJson = text;
    } catch (e) {
      versionJson = `failed to load: ${e}`;
    }
  }

  async function savePasted() {
    if (!project) return;
    saving = true;
    try {
      const res = await api.saveMapping(project, pastedJson);
      pushToast('success', `Mapping saved — ${res.mapping_count ?? 0} rows (${(res.content_hash ?? '').slice(0, 8)})`);
      pastedJson = '';
      await loadVersions();
    } catch (e) {
      pushToast('error', `Save failed: ${e}`);
    } finally {
      saving = false;
    }
  }

  function buildPrompt(): string {
    if (!project) {
      return 'Select a project in the top bar first.';
    }
    return `Call the assurance-scan MCP tool \`get_workflow\` with name="propose-compliance-mapping" and parameters={"framework": "${framework}"} and follow the returned workflow prompt for this project: ${project}`;
  }

  async function copyPrompt() {
    try {
      await navigator.clipboard.writeText(buildPrompt());
      pushToast('success', 'Agent prompt copied — paste it into Claude Code');
    } catch {
      pushToast('error', 'Clipboard unavailable — copy the prompt text manually');
    }
  }

  const TEMPLATE = `{\n  "schema_version": 1,\n  "project": "project-name",\n  "mappings": [\n    {\n      "ruleset": "asvs",\n      "version": "5.0.0",\n      "row": "V3.1.1",\n      "appropriate": true,\n      "satisfied_by": ["FR-001"],\n      "test_refs": ["T-001"],\n      "rationale": "Why these FRs/tests satisfy this row.",\n      "confidence": "high"\n    }\n  ]\n}`;

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
</script>

<div class="p-6 max-w-6xl">
  <div class="mb-5">
    <div class="text-[15px] text-ink-primary mb-1">Compliance mapping</div>
    <div class="text-[12px] text-ink-secondary">
      {#if project}
        <span class="font-mono">{project}</span>
        {#if latest}
          <span class="text-ink-muted">
            · {latest.packs.map((p) => `${p.ruleset}${p.version ? ` ${p.version}` : ''}`).join(', ') || 'no pack'} · saved {fmtDate(latest.loaded_at)}
          </span>
        {:else}
          <span class="text-ink-muted"> · no mapping saved yet</span>
        {/if}
      {:else}
        Select a project in the top bar to manage its compliance mapping.
      {/if}
    </div>
  </div>

  {#if project}
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
            Copy an agentic prompt for Claude Code: it reads the project's FR catalogue and the
            regime pack, maps every row, and saves the mapping via the MCP
            <code class="text-ink-primary">save_mapping</code> tool.
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
            Paste a mapping
          </div>
          <p class="text-[12px] text-ink-secondary leading-relaxed">
            Already have a mapping JSON? Paste it — it's validated against the mapping schema and
            stored as this project's current mapping.
          </p>
        </button>
      </div>
    {:else if flow === 'agent'}
      <section class="border border-line-hairline rounded-sm bg-surface-panel p-5">
        <div class="flex items-center justify-between mb-4">
          <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted">Author with an agent</div>
          <button type="button" on:click={() => (flow = null)} class="text-[11px] font-mono text-ink-muted hover:text-accent">✕ back</button>
        </div>
        <label class="block text-[11px] font-mono text-ink-secondary mb-1" for="framework">Framework (regime pack)</label>
        <input
          id="framework"
          type="text"
          bind:value={framework}
          placeholder="ASVS"
          class="w-48 px-2 py-1 mb-3 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary"
        />
        <p class="text-[11px] text-ink-muted leading-relaxed mb-3 max-w-xl">
          Delegates to the server-side <code class="text-ink-secondary">propose-compliance-mapping</code> workflow.
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
          <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted">Paste a mapping</div>
          <button type="button" on:click={() => (flow = null)} class="text-[11px] font-mono text-ink-muted hover:text-accent">✕ back</button>
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
          <div>
            <div class="text-[11px] font-mono text-ink-secondary mb-1">Expected format</div>
            <pre class="text-[10px] font-mono text-ink-muted whitespace-pre overflow-auto h-56 border border-line-hairline rounded-sm bg-surface-base p-2 mb-2">{TEMPLATE}</pre>
            <button
              type="button"
              on:click={copyTemplate}
              class="px-3 py-1 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[10px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors"
            >Copy template</button>
          </div>
          <div>
            <label class="block text-[11px] font-mono text-ink-secondary mb-1" for="paste-mapping">Your mapping</label>
            <textarea
              id="paste-mapping"
              bind:value={pastedJson}
              rows="14"
              placeholder="Paste your mapping JSON here"
              class="w-full px-2 py-1 mb-3 border border-line-hairline rounded-sm bg-surface-base font-mono text-[10px] text-ink-primary"
            ></textarea>
            <button
              type="button"
              on:click={savePasted}
              disabled={saving || !pastedJson.trim()}
              class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors disabled:opacity-50"
            >{saving ? 'Saving…' : 'Save mapping'}</button>
          </div>
        </div>
      </section>
    {/if}

    {#if versions.length > 0}
      <section class="mt-6">
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-2.5">Versions</div>
        <div class="as-table text-[11px]">
          <div class="as-head grid grid-cols-[minmax(0,1fr)_130px_130px_110px] gap-3">
            <div>Packs</div>
            <div>Catalogue</div>
            <div>Mapping</div>
            <div>Saved</div>
          </div>
          {#each versions as v (v.snapshot_id)}
            <div
              role="button"
              tabindex="0"
              on:click={() => toggleVersion(v)}
              on:keydown={(e) => e.key === 'Enter' && toggleVersion(v)}
              class="as-row as-row-click grid grid-cols-[minmax(0,1fr)_130px_130px_110px] gap-3 px-3 py-2"
              class:as-row-sel={selectedVersionId === v.snapshot_id}
            >
              <span class="text-ink-primary truncate">
                {v.packs.map((p) => `${p.ruleset}${p.version ? ` ${p.version}` : ''}`).join(', ') || '—'}
              </span>
              <span class="text-ink-muted font-mono truncate" title={v.catalogue_content_hash ?? ''}>
                {v.catalogue_content_hash ? v.catalogue_content_hash.slice(0, 12) : '—'}
              </span>
              <span class="text-ink-secondary font-mono truncate" title={v.content_hash}>{v.content_hash.slice(0, 12)}</span>
              <span class="text-ink-muted">{fmtDate(v.loaded_at)}</span>
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
