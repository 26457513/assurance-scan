<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import CopyButton from '$lib/components/CopyButton.svelte';
  import type { CompliancePack } from '$lib/types';

  let packs: CompliancePack[] = [];
  let selected: CompliancePack | null = null;
  let packJson = '';
  let loading = true;
  let error: string | null = null;

  const PAGE_SIZE = 5;
  let page = 0;

  $: pageCount = Math.max(1, Math.ceil(packs.length / PAGE_SIZE));
  $: visible = packs.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  async function load() {
    try {
      const data = await api.listCompliancePacks();
      packs = data.packs;
      if (packs.length) await pick(packs[0]);
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function pick(p: CompliancePack) {
    selected = p;
    try {
      const doc = await api.getCompliancePack(p.file);
      packJson = JSON.stringify(doc, null, 2);
    } catch (e) {
      packJson = '';
      error = String(e);
    }
  }

  onMount(load);
</script>

<div class="p-6 max-w-6xl">
  <div class="mb-4">
    <div class="text-[15px] text-ink-primary mb-1">Compliance regimes</div>
    <div class="text-[12px] text-ink-secondary">
      Pre-loaded, versioned frameworks available to every project.
    </div>
  </div>

  {#if loading}
    <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else if error}
    <div class="text-[12px] text-state-failed font-mono">{error}</div>
  {:else if packs.length === 0}
    <div class="text-[12px] text-ink-muted font-mono">No regimes loaded.</div>
  {:else}
    <div class="border border-line-hairline rounded-sm overflow-hidden bg-surface-panel mb-5">
      <div class="grid grid-cols-[160px_100px_minmax(0,1fr)_90px] gap-3 px-4 py-2 bg-surface-inset border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted">
        <div>Regime</div>
        <div>Version</div>
        <div>File</div>
        <div class="text-right">Rows</div>
      </div>
      {#each visible as p (p.file)}
        <button
          type="button"
          on:click={() => pick(p)}
          class="w-full text-left grid grid-cols-[160px_100px_minmax(0,1fr)_90px] gap-3 px-4 py-2 border-b border-line-hairline last:border-0 transition-colors hover:bg-surface-elevated font-mono text-[12px]"
          class:bg-accent-subtle={selected?.file === p.file}
        >
          <span class="text-ink-primary">{p.id}</span>
          <span class="text-ink-secondary">{p.version || '—'}</span>
          <span class="text-ink-muted truncate">{p.file}</span>
          <span class="text-right text-ink-muted">
            {#if selected?.file === p.file && packJson}
              {JSON.parse(packJson).rows?.length ?? '—'}
            {:else}—{/if}
          </span>
        </button>
      {/each}
    </div>

    {#if pageCount > 1}
      <div class="flex items-center gap-2 mb-5 font-mono text-[11px]">
        <button
          type="button"
          on:click={() => (page = Math.max(0, page - 1))}
          disabled={page === 0}
          class="px-2 py-0.5 border border-line-hairline rounded-sm text-ink-secondary disabled:opacity-40"
        >‹ prev</button>
        <span class="text-ink-muted">page {page + 1} / {pageCount}</span>
        <button
          type="button"
          on:click={() => (page = Math.min(pageCount - 1, page + 1))}
          disabled={page >= pageCount - 1}
          class="px-2 py-0.5 border border-line-hairline rounded-sm text-ink-secondary disabled:opacity-40"
        >next ›</button>
      </div>
    {/if}

    {#if selected}
      <div class="flex items-center justify-between mb-2">
        <div class="font-mono text-[10px] text-ink-muted uppercase tracking-[0.12em]">
          {selected.id}{selected.version ? ` ${selected.version}` : ''} · detail
        </div>
        <CopyButton text={packJson} label="Copy JSON" />
      </div>
      <div class="border border-line-hairline rounded-sm bg-surface-inset max-h-[60vh] overflow-auto">
        <pre class="font-mono text-[11px] leading-[1.6] p-3 whitespace-pre">{packJson}</pre>
      </div>
    {/if}
  {/if}
</div>
