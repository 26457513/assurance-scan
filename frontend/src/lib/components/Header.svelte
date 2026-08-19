<script lang="ts">
  import { page } from '$app/stores';
  import ProjectSelector from './ProjectSelector.svelte';
  import CatalogueSelector from './CatalogueSelector.svelte';
  import ScanSelector from './ScanSelector.svelte';

  $: path = $page.url.pathname;
  $: section = (() => {
    if (path === '/setup') return 'Setup';
    if (path === '/regimes') return 'Regimes';
    if (path === '/projects' || path.startsWith('/projects/')) return 'Projects';
    if (path === '/scans' || path.startsWith('/scans/')) return 'Scans';
    if (path === '/fix') return 'Fix';
    if (path === '/trends') return 'Trends';
    return '';
  })();
</script>

<header class="h-14 bg-surface-panel border-b border-line-hairline flex items-center px-5 z-30 gap-3">
  {#if section}
    <div class="text-[10px] font-mono uppercase tracking-[0.16em] text-ink-muted whitespace-nowrap mr-1">{section}</div>
    <div class="w-px h-3.5 bg-line-hairline"></div>
  {/if}
  <ProjectSelector />
  <span class="text-ink-muted font-mono text-[11px]">·</span>
  <ScanSelector />
  <span class="text-ink-muted font-mono text-[11px]">·</span>
  <CatalogueSelector />
</header>
