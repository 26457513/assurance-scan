<script lang="ts">
  import { page } from '$app/stores';
  import { selectedScan } from '$lib/stores/selectedScan';
  import { selectedProject, projectSlug } from '$lib/stores/selectedProject';

  const nav = [
    { href: '/setup', label: 'Setup', glyph: '⚙', match: '/setup' },
    { href: '/regimes', label: 'Regimes', glyph: '§', match: '/regimes' },
    { href: '/projects', label: 'Projects', glyph: '❏', match: '/projects' },
    { href: '/fix', label: 'Fix', glyph: '⚑', match: '/fix' },
    { href: '/trends', label: 'Trends', glyph: '↗', match: '/trends' },
    { href: '/settings', label: 'Settings', glyph: '⚙', match: '/settings' }
  ];

  $: path = $page.url.pathname;
  // Exact match: parent nav items highlight only on their own page, not on
  // nested detail pages (e.g. /scans/[id] is owned by the per-scan sub-link).
  const isActive = (match: string) => path === match;

  $: projectBase = $selectedProject ? `/projects/${projectSlug($selectedProject)}` : null;
  $: projectActive = projectBase !== null && path.startsWith(projectBase);
  $: projectShort = $selectedProject
    ? $selectedProject.split('/').filter(Boolean).pop()
    : null;

  // Project sub-links: scans live under the project; FRs and Compliance
  // are standalone pages.
  const PROJECT_VIEWS = [
    { view: 'scans', label: 'Scans', href: '' },
    { view: 'frs', label: 'FRs', href: '/frs' },
    { view: 'compliance', label: 'Compliance', href: '/compliance' }
  ];
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

      {#if item.href === '/projects' && projectBase}
        <a
          href={projectBase}
          class="relative ml-3 flex items-center gap-2 pl-7 pr-3 py-1.5 text-[11px] font-mono transition-colors duration-150 rounded-sm"
          class:bg-accent-subtle={projectActive && path === projectBase}
          class:text-accent={projectActive && path === projectBase}
          class:text-ink-secondary={!(projectActive && path === projectBase)}
          class:hover:bg-surface-elevated={!(projectActive && path === projectBase)}
          title={$selectedProject ?? ''}
        >
          <span class="text-ink-muted select-none">└</span>
          <span class="truncate flex-1">{projectShort}</span>
        </a>
        {#each PROJECT_VIEWS as v (v.view)}
          {@const active = v.view === 'scans' ? projectActive && path === projectBase : isActive(v.href)}
          <a
            href={v.view === 'scans' ? projectBase : v.href}
            class="relative ml-6 flex items-center gap-2 pl-7 pr-3 py-1.5 text-[11px] font-mono transition-colors duration-150 rounded-sm"
            class:bg-accent-subtle={active}
            class:text-accent={active}
            class:text-ink-secondary={!active}
            class:hover:bg-surface-elevated={!active}
          >
            <span class="text-ink-muted select-none">└</span>
            <span class="truncate flex-1">{v.label}</span>
          </a>
        {/each}
      {/if}
    {/each}
  </nav>
</aside>
