<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import CopyButton from './CopyButton.svelte';
  import type { ConfigResponse, ScanSummary } from '$lib/types';

  export let scan: ScanSummary;

  let config: ConfigResponse | null = null;
  let loading = true;
  let error: string | null = null;
  let activeSub: SubTabId = 'catalogue';

  const SUB_TABS = [
    { id: 'catalogue', label: 'Catalogue', file: 'db · catalogue_snapshots (latest)' },
    { id: 'mapping', label: 'Mapping', file: 'db · compliance_mappings (latest)' },
    { id: 'pack', label: 'Compliance Pack', file: 'data/compliance-packs/asvs-5.0.0.json' }
  ] as const;

  type SubTabId = (typeof SUB_TABS)[number]['id'];

  async function load() {
    try {
      config = await api.getConfig(scan.project_path);
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(load);

  function jsonFor(sub: SubTabId): string {
    if (!config) return '';
    if (sub === 'catalogue') return JSON.stringify(config.catalogue, null, 2);
    if (sub === 'mapping') return JSON.stringify(config.mapping, null, 2);
    // Compliance pack(s) — show first available
    const packs = Object.entries(config.compliance_packs);
    if (packs.length === 0) return '(no compliance pack loaded)';
    const [_name, data] = packs[0];
    return JSON.stringify(data, null, 2);
  }

  $: lines = jsonFor(activeSub).split('\n');
</script>

<div class="p-6 max-w-6xl">
  <div class="flex items-center gap-1 mb-4">
    {#each SUB_TABS as tab (tab.id)}
      <button
        type="button"
        on:click={() => (activeSub = tab.id)}
        class="font-mono text-[11px] uppercase tracking-[0.1em] px-2.5 py-1 rounded-sm border transition-colors"
        class:border-line-strong={activeSub === tab.id}
        class:text-ink-primary={activeSub === tab.id}
        class:bg-surface-elevated={activeSub === tab.id}
        class:border-line-hairline={activeSub !== tab.id}
        class:text-ink-muted={activeSub !== tab.id}
      >{tab.label}</button>
    {/each}
  </div>

  {#if loading}
    <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else if error}
    <div class="text-[12px] text-state-failed font-mono">{error}</div>
  {:else}
    {@const content = jsonFor(activeSub)}
    <div class="flex items-center justify-between mb-2">
      <div class="font-mono text-[10px] text-ink-muted">
        {SUB_TABS.find((t) => t.id === activeSub)?.file}  ·  {lines.length} lines
      </div>
      <CopyButton text={content} label="Copy JSON" />
    </div>
    <div class="border border-line-hairline rounded-sm bg-surface-inset max-h-[70vh] overflow-auto">
      <pre class="font-mono text-[11px] leading-[1.6] py-2"><code>{#each lines as line, i (i)}<span class="grid grid-cols-[52px_1fr]"><span class="text-ink-muted select-none pr-3 text-right border-r border-line-hairline mr-3">{i + 1}</span><span class="text-ink-secondary whitespace-pre">{line || ' '}</span></span>{/each}</code></pre>
    </div>
  {/if}
</div>
