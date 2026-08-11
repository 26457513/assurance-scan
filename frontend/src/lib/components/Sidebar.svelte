<script lang="ts">
  import { page } from '$app/stores';
  import { selectedScan } from '$lib/stores/selectedScan';

  const nav = [
    { href: '/scans', label: 'Scans', glyph: '⟳', match: '/scans', showScanSubitem: true },
    { href: '/fix', label: 'Fix', glyph: '⚑', match: '/fix', showScanSubitem: false },
    { href: '/setup', label: 'Setup', glyph: '⚙', match: '/setup', showScanSubitem: false },
    { href: '/trends', label: 'Trends', glyph: '↗', match: '/trends', showScanSubitem: false }
  ];

  $: path = $page.url.pathname;
  // Exact match: parent nav items highlight only on their own page, not on
  // nested detail pages (e.g. /scans/[id] is owned by the per-scan sub-link).
  const isActive = (match: string) => path === match;

  $: scanDetailHref = $selectedScan ? `/scans/${$selectedScan.run_id}` : null;
  $: scanDetailActive = scanDetailHref !== null && path === scanDetailHref;
  $: scanShortLabel = $selectedScan ? shortLabel($selectedScan.run_id) : null;
  $: scanIsRunning =
    !!$selectedScan && ($selectedScan.status === 'queued' || $selectedScan.status === 'running');

  function shortLabel(id: string): string {
    const m = id.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z_/);
    if (m) {
      const [, , mo, d, h, mi] = m;
      return `${mo}/${d} ${h}:${mi}`;
    }
    return id.slice(-8);
  }
</script>

<aside class="bg-surface-panel border-r border-line-hairline flex flex-col h-full">
  <div class="px-5 h-14 flex items-center border-b border-line-hairline">
    <div class="flex items-center gap-2">
      <span class="text-accent text-base leading-none">⬡</span>
      <span class="text-[13px] font-medium tracking-tight text-ink-primary">Assurance Scan</span>
    </div>
  </div>

  <nav class="flex-1 px-2 py-3 flex flex-col gap-0.5">
    {#each nav as item (item.href)}
      <a
        href={item.href}
        class="relative flex items-center gap-2.5 px-3 py-2 text-[13px] transition-colors duration-150 rounded-sm"
        class:bg-accent-subtle={isActive(item.match)}
        class:text-accent={isActive(item.match)}
        class:text-ink-secondary={!isActive(item.match)}
        class:hover:bg-surface-elevated={!isActive(item.match)}
      >
        {#if isActive(item.match)}
          <span class="absolute left-0 top-1.5 bottom-1.5 w-[2px] bg-accent"></span>
        {/if}
        <span
          class="text-[14px] w-3 text-center transition-colors"
          class:text-accent={isActive(item.match)}
          class:text-ink-muted={!isActive(item.match)}
        >{item.glyph}</span>
        <span>{item.label}</span>
      </a>

      {#if item.showScanSubitem && scanDetailHref}
        <a
          href={scanDetailHref}
          class="relative ml-3 flex items-center gap-2 pl-7 pr-3 py-1.5 text-[11px] font-mono transition-colors duration-150 rounded-sm"
          class:bg-accent-subtle={scanDetailActive}
          class:text-accent={scanDetailActive}
          class:text-ink-secondary={!scanDetailActive}
          class:hover:bg-surface-elevated={!scanDetailActive}
          title={$selectedScan?.run_id}
        >
          {#if scanDetailActive}
            <span class="absolute left-0 top-1.5 bottom-1.5 w-[2px] bg-accent"></span>
          {/if}
          <span class="text-ink-muted select-none">└</span>
          <span class="truncate flex-1">{scanShortLabel}</span>
          {#if scanIsRunning}
            <span class="w-1.5 h-1.5 rounded-full bg-accent pulse-dot shrink-0"></span>
          {/if}
        </a>
      {/if}
    {/each}
  </nav>
</aside>
