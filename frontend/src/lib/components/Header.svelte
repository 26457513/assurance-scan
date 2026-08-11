<script lang="ts">
  import { page } from '$app/stores';
  import ScanSelector from './ScanSelector.svelte';

  $: path = $page.url.pathname;
  $: section = (() => {
    if (path === '/scans' || path.startsWith('/scans/')) return 'Scans';
    if (path === '/frs' || path.startsWith('/frs/')) return 'Catalogue';
    if (path === '/compliance') return 'Compliance';
    if (path === '/trends') return 'Trends';
    return '';
  })();
</script>

<header class="h-14 bg-surface-panel border-b border-line-hairline flex items-center px-5 z-30">
  {#if section}
    <div class="text-[10px] font-mono uppercase tracking-[0.16em] text-ink-muted whitespace-nowrap mr-3">{section}</div>
    <div class="w-px h-3.5 bg-line-hairline mr-3"></div>
  {/if}
  <ScanSelector />
</header>
