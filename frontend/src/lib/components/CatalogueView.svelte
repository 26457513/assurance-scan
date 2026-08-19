<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import FrRow from './FrRow.svelte';
  import SummaryStrip from './SummaryStrip.svelte';
  import CopyButton from './CopyButton.svelte';
  import type { CatalogueVersion, FrListResponse, ScanSummary } from '$lib/types';

  export let scan: ScanSummary;

  let data: FrListResponse | null = null;
  let loading = true;
  let error: string | null = null;
  let gapsOnly = false;
  let categoryFilter = '';
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  let versions: CatalogueVersion[] = [];
  let selectedSnapshotId = '';

  async function refresh() {
    try {
      data = await api.listFRs(scan.project_path, selectedSnapshotId || undefined);
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(async () => {
    try {
      const v = await api.listCatalogueVersions(scan.project_path);
      versions = v.versions;
      selectedSnapshotId = versions[0]?.snapshot_id ?? '';
    } catch {
      /* selector stays hidden */
    }
    refresh();
    pollTimer = setInterval(refresh, 10000);
  });
  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  function pickVersion(id: string) {
    selectedSnapshotId = id;
    loading = true;
    refresh();
  }

  $: viewingHistorical = versions.length > 0 && selectedSnapshotId !== versions[0]?.snapshot_id;

  $: categories = data
    ? Array.from(new Set(data.frs.map((f) => f.category).filter(Boolean))).sort()
    : [];

  $: visibleFrs = data
    ? data.frs.filter((f) => {
        if (gapsOnly && !f.is_gap) return false;
        if (categoryFilter && f.category !== categoryFilter) return false;
        return true;
      })
    : [];

  $: grouped = (() => {
    const groups: Record<string, typeof visibleFrs> = {};
    visibleFrs.forEach((fr) => {
      const cat = fr.category || 'uncategorized';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(fr);
    });
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  })();
</script>

{#if loading && !data}
  <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
{:else if error}
  <div class="text-[12px] text-state-failed font-mono">{error}</div>
{:else if !data}
  <div class="text-[12px] text-ink-muted font-mono">No data.</div>
{:else if !data.catalogue}
  <div class="py-12 text-center">
    <div class="text-[15px] text-ink-primary mb-2">No FR catalogue loaded</div>
    <div class="text-[12px] text-ink-secondary mb-5 max-w-md mx-auto leading-relaxed">
      Generate one from your codebase — the agent reads your source, identifies capabilities,
      and drafts FRs with test specs + scanner coverage.
    </div>
    <div class="border border-line-hairline rounded-sm bg-surface-inset p-3 max-w-lg mx-auto text-left mb-3">
      <div class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted mb-1.5">Paste into Claude Code</div>
      <div class="font-mono text-[11px] text-ink-secondary leading-[1.6] break-words">
        Run the generate-fr-catalogue workflow from the assurance-scan MCP server. Use project_path="{scan.project_path}".
      </div>
    </div>
    <div class="flex items-center justify-center gap-2">
      <CopyButton text={`Run the generate-fr-catalogue workflow from the assurance-scan MCP server. Use project_path="${scan.project_path}".`} label="Copy prompt" />
    </div>
  </div>
{:else}
  <div class="mb-5">
    <div class="flex items-baseline gap-3 mb-3">
      <span class="font-mono text-[13px] text-ink-primary">{data.catalogue.project}</span>
      {#if data.catalogue.catalogue_version}
        <span class="font-mono text-[11px] text-ink-muted">v{data.catalogue.catalogue_version}</span>
      {/if}
      <span class="font-mono text-[11px] text-ink-muted">· {data.catalogue.fr_count} FRs</span>
      <span class="flex-1"></span>
      {#if versions.length > 1}
        <select
          value={selectedSnapshotId}
          on:change={(e) => pickVersion(e.currentTarget.value)}
          class="font-mono text-[11px] text-ink-secondary bg-surface-inset border border-line-hairline rounded-sm px-1.5 py-0.5"
          title="Catalogue snapshot — states shown are from the latest run"
        >
          {#each versions as v (v.snapshot_id)}
            <option value={v.snapshot_id}>
              v{v.version ?? '?'} · {v.content_hash.slice(7, 15)} · {v.fr_count} FRs{v.snapshot_id === versions[0].snapshot_id ? ' (current)' : ''}
            </option>
          {/each}
        </select>
      {/if}
      {#if viewingHistorical}
        <span class="px-1.5 py-0.5 border border-state-pending text-state-pending font-mono text-[10px] uppercase tracking-[0.1em]">historical</span>
      {/if}
    </div>
    <SummaryStrip summary={data.summary} />
  </div>

  <div class="flex items-center gap-1.5 mb-4 flex-wrap">
    <button
      type="button"
      on:click={() => (gapsOnly = !gapsOnly)}
      class="font-mono text-[11px] px-2.5 py-1 rounded-sm border transition-colors"
      class:border-line-strong={gapsOnly}
      class:text-accent={gapsOnly}
      class:bg-accent-subtle={gapsOnly}
      class:border-line-hairline={!gapsOnly}
      class:text-ink-secondary={!gapsOnly}
    >
      {#if gapsOnly}✓ {/if}gaps only ({data.summary.gaps})
    </button>
    <div class="w-px h-3.5 bg-line-hairline mx-1"></div>
    <button
      type="button"
      on:click={() => (categoryFilter = '')}
      class="font-mono text-[11px] px-2 py-1 rounded-sm border transition-colors"
      class:border-line-strong={categoryFilter === ''}
      class:text-ink-primary={categoryFilter === ''}
      class:border-line-hairline={categoryFilter !== ''}
      class:text-ink-muted={categoryFilter !== ''}
    >all</button>
    {#each categories as cat (cat)}
      <button
        type="button"
        on:click={() => (categoryFilter = cat)}
        class="font-mono text-[11px] px-2 py-1 rounded-sm border transition-colors"
        class:border-line-strong={categoryFilter === cat}
        class:text-ink-primary={categoryFilter === cat}
        class:border-line-hairline={categoryFilter !== cat}
        class:text-ink-muted={categoryFilter !== cat}
      >{cat}</button>
    {/each}
  </div>

  {#if visibleFrs.length === 0}
    <div class="py-12 text-center text-[12px] text-ink-muted font-mono">
      {gapsOnly || categoryFilter ? 'No FRs match the current filter.' : 'No FRs in catalogue.'}
    </div>
  {:else}
    <div class="border border-line-hairline rounded-sm overflow-hidden bg-surface-panel">
      <div class="sticky top-0 z-20 bg-surface-inset grid grid-cols-[180px_minmax(0,1fr)_40px_60px_auto_24px] gap-3 px-4 py-2 border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted items-center">
        <div>FR</div>
        <div>Title</div>
        <div>Lvl</div>
        <div class="text-right">Tests</div>
        <div class="text-right">State</div>
        <div></div>
      </div>
      {#each grouped as [cat, frs] (cat)}
        <div class="bg-surface-base px-4 py-1.5 border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted">
          {cat} · {frs.length}
        </div>
        {#each frs as fr (fr.fr_id)}
          <FrRow {fr} />
        {/each}
      {/each}
    </div>
  {/if}
{/if}
