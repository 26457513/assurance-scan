<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import FrRow from './FrRow.svelte';
  import SummaryStrip from './SummaryStrip.svelte';
  import type { FrListResponse, ScanSummary } from '$lib/types';

  export let scan: ScanSummary;

  let data: FrListResponse | null = null;
  let loading = true;
  let error: string | null = null;
  let gapsOnly = false;
  let categoryFilter = '';
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  async function refresh() {
    try {
      data = await api.listFRs(scan.project_path);
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    refresh();
    pollTimer = setInterval(refresh, 10000);
  });
  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

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
  <div class="py-16 text-center">
    <div class="text-[13px] text-ink-primary mb-2">No FR catalogue loaded</div>
    <div class="text-[12px] text-ink-muted font-mono">Run a scan with <span class="text-ink-secondary">fr_catalog_path</span> set.</div>
  </div>
{:else}
  <div class="mb-5">
    <div class="flex items-baseline gap-3 mb-3">
      <span class="font-mono text-[13px] text-ink-primary">{data.catalogue.project}</span>
      {#if data.catalogue.catalogue_version}
        <span class="font-mono text-[11px] text-ink-muted">v{data.catalogue.catalogue_version}</span>
      {/if}
      <span class="font-mono text-[11px] text-ink-muted">· {data.catalogue.fr_count} FRs</span>
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
