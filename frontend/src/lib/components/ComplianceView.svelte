<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import { mcpPrompt } from '$lib/agentPrompts';
  import ComplianceRow from './ComplianceRow.svelte';
  import SummaryStrip from './SummaryStrip.svelte';
  import CopyButton from './CopyButton.svelte';
  import type {
    ComplianceListResponse,
    ComplianceMatrixResponse,
    ComplianceFrameworkSummary,
    FrListResponse,
    MappingVersion,
    ScanSummary
  } from '$lib/types';

  export let scan: ScanSummary;
  export let initialFramework: string | null = null;
  $: mappingPrompt = mcpPrompt([
    { tool: 'get_workflow', args: { name: 'author-fr-compliance-map', parameters: JSON.stringify({ framework: selectedFramework ?? 'ASVS' }) } },
    { tool: 'save_mapping', args: { project_id: scan.project_id } },
  ]);

  let frameworks: ComplianceFrameworkSummary[] = [];
  let matrix: ComplianceMatrixResponse | null = null;
  let frList: FrListResponse | null = null;
  let loading = true;
  let error: string | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let selectedFramework: string | null = initialFramework;

  let mappingVersions: MappingVersion[] = [];
  let selectedMappingHash = '';
  let currentCatalogueHash = '';

  async function loadFrameworks() {
    const data: ComplianceListResponse = await api.listComplianceFrameworks();
    frameworks = data.frameworks;
    if (!selectedFramework && frameworks.length) {
      selectedFramework = frameworks[0].id;
    }
  }

  async function loadMappingVersions() {
    try {
      const [mv, cv] = await Promise.all([
        api.listMappingVersions(scan.project_id),
        api.listCatalogueVersions(scan.project_id)
      ]);
      mappingVersions = mv.versions;
      currentCatalogueHash = cv.versions[0]?.content_hash ?? '';
      if (!selectedMappingHash) selectedMappingHash = mappingVersions[0]?.content_hash ?? '';
    } catch {
      /* selectors stay hidden */
    }
  }

  async function loadMatrix() {
    if (!selectedFramework) return;
    loading = true;
    try {
      matrix = await api.getComplianceMatrix(
        selectedFramework,
        scan.project_id,
        mappingVersions.length > 1 ? selectedMappingHash || undefined : undefined
      );
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  $: selectedMapping = mappingVersions.find((m) => m.content_hash === selectedMappingHash) ?? null;
  $: mappingTargetsOlder =
    selectedMapping?.catalogue_content_hash != null &&
    currentCatalogueHash !== '' &&
    selectedMapping.catalogue_content_hash !== currentCatalogueHash;

  async function loadFrList() {
    try {
      frList = await api.listFRs(scan.project_id);
    } catch (e) {
      /* silent */
    }
  }

  onMount(async () => {
    try {
      await Promise.all([loadFrameworks(), loadMappingVersions()]);
      await Promise.all([loadMatrix(), loadFrList()]);
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
    pollTimer = setInterval(() => {
      loadMatrix();
      loadFrList();
    }, 15000);
  });
  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  function pickFramework(id: string) {
    selectedFramework = id;
    loadMatrix();
  }

  function pickMapping(hash: string) {
    selectedMappingHash = hash;
    loadMatrix();
  }
</script>

{#if frameworks.length === 0 && !loading}
  <div class="py-12 text-center">
    <div class="text-[15px] text-ink-primary mb-2">No compliance mapping loaded</div>
    <div class="text-[12px] text-ink-secondary mb-5 max-w-md mx-auto leading-relaxed">
      Map your FRs to ASVS rules — every row gets assessed as applicable or N/A,
      with rationale and test references.
    </div>
    <div class="border border-line-hairline rounded-sm bg-surface-inset p-3 max-w-lg mx-auto text-left mb-3">
      <div class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted mb-1.5">Paste into Claude Code</div>
      <div class="font-mono text-[11px] text-ink-secondary leading-[1.6] break-words">
        {mappingPrompt}
      </div>
    </div>
    <div class="flex items-center justify-center gap-2">
      <CopyButton text={mappingPrompt} label="Copy prompt" />
    </div>
    <div class="mt-3 text-[11px] text-ink-muted font-mono">
      Requires an FR catalogue first — <a href="/frs" class="text-accent hover:underline">generate one on the FRs tab</a>
    </div>
  </div>
{:else if loading && !matrix}
  <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
{:else if error}
  <div class="text-[12px] text-state-failed font-mono">{error}</div>
{:else}
  <div class="flex items-center gap-1.5 mb-5 flex-wrap">
    {#each frameworks as fw (fw.id)}
      <button
        type="button"
        on:click={() => pickFramework(fw.id)}
        class="font-mono text-[11px] px-2.5 py-1 rounded-sm border transition-colors"
        class:border-line-strong={selectedFramework === fw.id}
        class:text-ink-primary={selectedFramework === fw.id}
        class:bg-surface-elevated={selectedFramework === fw.id}
        class:border-line-hairline={selectedFramework !== fw.id}
        class:text-ink-muted={selectedFramework !== fw.id}
      >
        {fw.id}
        <span class="text-ink-muted ml-1.5 tabular-nums">{fw.rows}</span>
      </button>
    {/each}
    <span class="flex-1"></span>
    {#if mappingVersions.length > 1}
      <select
        value={selectedMappingHash}
        on:change={(e) => pickMapping(e.currentTarget.value)}
        class="font-mono text-[11px] text-ink-secondary bg-surface-inset border border-line-hairline rounded-sm px-1.5 py-0.5"
        title="Mapping snapshot — states shown are from the latest run"
      >
        {#each mappingVersions as mv (mv.snapshot_id)}
          <option value={mv.content_hash}>
            mapping {mv.content_hash.slice(7, 15)} · {mv.packs.map((p) => `${p.ruleset}${p.version ? ` ${p.version}` : ''}`).join(', ') || 'no pack'}{mv.snapshot_id === mappingVersions[0].snapshot_id ? ' (current)' : ''}
          </option>
        {/each}
      </select>
    {/if}
    {#if mappingTargetsOlder}
      <span
        class="px-1.5 py-0.5 border border-state-pending text-state-pending font-mono text-[10px] uppercase tracking-[0.1em]"
        title={`This mapping was authored against catalogue ${selectedMapping?.catalogue_content_hash?.slice(7, 15)}…; the current catalogue differs — rows may reference FRs that no longer exist.`}
      >
        targets older catalogue
      </span>
    {/if}
  </div>

  {#if matrix}
    <div class="mb-5 flex items-center gap-4 flex-wrap">
      <SummaryStrip summary={matrix.summary} />
      <span class="font-mono text-[11px] text-ink-muted">· {matrix.row_count} rows mapped</span>
    </div>

    <div class="border border-line-hairline rounded-sm overflow-hidden bg-surface-panel">
      <div class="sticky top-0 z-20 bg-surface-inset grid grid-cols-[120px_70px_minmax(0,1fr)_50px_60px_80px_auto_24px] gap-3 px-4 py-2 border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted items-center">
        <div>Row</div>
        <div>Section</div>
        <div>Title</div>
        <div>Lvl</div>
        <div class="text-right">FRs</div>
        <div>Conf</div>
        <div class="text-right">State</div>
        <div></div>
      </div>
      {#each matrix.rows as row (row.row_id)}
        <ComplianceRow row={row} />
      {/each}
    </div>
  {/if}
{/if}
