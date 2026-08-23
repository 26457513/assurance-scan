<script lang="ts">
  import { page } from '$app/stores';
  import { selectedProject, projectSlug } from '$lib/stores/selectedProject';

  // Project-scoped items are disabled until a project is in focus (set by
  // clicking a row in the Projects table or the header dropdown).
  $: projectBase = $selectedProject ? `/projects/${projectSlug($selectedProject)}` : null;

  const nav = [
    { href: '/setup', label: 'Setup', glyph: '⚙', match: '/setup', scoped: false, divider: false },
    { href: '/projects', label: 'Projects', glyph: '❏', match: '/projects', scoped: false, divider: false },
    { href: '', label: 'Scans', glyph: '⌗', match: '', scoped: true, divider: true },
    { href: '/trends', label: 'Trends', glyph: '↗', match: '/trends', scoped: true, divider: false },
    { href: '/regimes', label: 'Regimes', glyph: '§', match: '/regimes', scoped: false, divider: false },
    { href: '/frs', label: 'FRs', glyph: '☰', match: '/frs', scoped: true, divider: false },
    { href: '/compliance', label: 'Compliance', glyph: '⚖', match: '/compliance', scoped: true, divider: false },
    { href: '/fix', label: 'Fix', glyph: '⚑', match: '/fix', scoped: false, divider: true }
  ];

  $: path = $page.url.pathname;
  // Exact match: parent nav items highlight only on their own page, not on
  // nested detail pages (e.g. /scans/[id] is owned by the scan selector).
  const isActive = (match: string) => path === match;
</script>

<aside class="bg-surface-panel border-r border-line-hairline flex flex-col h-full">
  <div class="px-5 h-14 flex items-center border-b border-line-hairline">
    <div class="flex items-center gap-2">
      <span class="text-accent text-base leading-none">⬡</span>
      <span class="text-[13px] font-medium tracking-tight text-ink-primary">Assurance Scan</span>
    </div>
  </div>

  <nav class="flex-1 px-2 py-3 flex flex-col gap-0.5">
    {#each nav as item (item.label)}
      {@const disabled = item.scoped && !projectBase}
      {@const href = item.label === 'Scans' ? projectBase : item.href}
      {@const active = item.label === 'Scans'
        ? projectBase !== null && path === projectBase
        : isActive(item.match)}
      <a
        href={disabled ? undefined : href}
        aria-disabled={disabled}
        class="relative flex items-center gap-2.5 px-3 py-2 text-[13px] transition-colors duration-150 rounded-sm"
        class:cursor-not-allowed={disabled}
        class:opacity-40={disabled}
        class:bg-accent-subtle={active}
        class:text-accent={active}
        class:text-ink-secondary={!active && !disabled}
        class:hover:bg-surface-elevated={!active && !disabled}
      >
        {#if active}
          <span class="absolute left-0 top-1.5 bottom-1.5 w-[2px] bg-accent"></span>
        {/if}
        <span
          class="text-[14px] w-3 text-center transition-colors"
          class:text-accent={active}
          class:text-ink-muted={!active}
        >{item.glyph}</span>
        <span>{item.label}</span>
      </a>

      {#if item.divider}
        <div class="my-1 mx-3 border-t border-line-hairline"></div>
      {/if}
    {/each}
  </nav>
</aside>
