<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import {
    currentUser,
    currentUserResolved,
    isPrivilegedUser,
    loadCurrentUser
  } from '$lib/stores/currentUser';
  import { visibleNavigation } from '$lib/navigation';
  import { selectedProject } from '$lib/stores/selectedProject';

  onMount(() => void loadCurrentUser());

  // Project-scoped items are disabled until a project is in focus (set by
  // clicking a row in the Projects table or the header dropdown).
  $: projectBase = $selectedProject != null ? `/projects/${$selectedProject}` : null;

  $: path = $page.url.pathname;
  $: showPrivileged = $currentUserResolved && isPrivilegedUser($currentUser);
  $: nav = visibleNavigation(showPrivileged);
  // Exact match: parent nav items highlight only on their own page, not on
  // nested detail pages (e.g. /scans/[id] is owned by the scan selector).
  const isActive = (match: string) => path === match;
</script>

<aside class="bg-surface-panel border-r border-line-hairline flex flex-col h-full">
  <div class="brand px-5 h-14 flex items-center border-b border-line-hairline">
    <div class="flex items-center gap-2">
      <span class="text-accent text-base leading-none">⬡</span>
      <span class="brand-label text-[13px] font-medium tracking-tight text-ink-primary">Assurance Scan</span>
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
        aria-label={item.label}
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
        <span class="nav-label">{item.label}</span>
      </a>

      {#if item.divider}
        <div class="nav-divider my-1 mx-3 border-t border-line-hairline"></div>
      {/if}
    {/each}
  </nav>
</aside>

<style>
  @media (max-width: 640px) {
    .brand {
      justify-content: center;
      padding-inline: 0;
    }

    .brand-label,
    .nav-label {
      display: none;
    }

    nav {
      padding-inline: 0.375rem;
    }

    nav a {
      justify-content: center;
      padding-inline: 0;
    }

    .nav-divider {
      margin-inline: 0.25rem;
    }
  }
</style>
