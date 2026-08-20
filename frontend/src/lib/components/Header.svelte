<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import ProjectSelector from './ProjectSelector.svelte';
  import CatalogueSelector from './CatalogueSelector.svelte';
  import ScanSelector from './ScanSelector.svelte';

  import { goto } from '$app/navigation';

  let me: { email: string; role: string } | null = null;
  onMount(async () => {
    try {
      me = await api.me();
    } catch {
      me = null;
    }
  });

  async function logout() {
    await api.logout();
    me = null;
    goto('/');
    location.reload();
  }

  $: path = $page.url.pathname;
  $: section = (() => {
    if (path === '/setup') return 'Setup';
    if (path === '/regimes') return 'Regimes';
    if (path === '/projects' || path.startsWith('/projects/')) return 'Projects';
    if (path === '/scans' || path.startsWith('/scans/')) return 'Scans';
    if (path === '/frs') return 'FRs';
    if (path === '/compliance') return 'Compliance';
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
  <span class="flex-1"></span>
  {#if me}
    <a
      href="/setup?tab=account"
      title="Settings"
      class="flex items-center gap-2 px-2.5 py-1.5 rounded-sm border border-line-hairline hover:border-line-strong hover:bg-surface-elevated transition-colors"
    >
      <span class="font-mono text-[11px] text-ink-primary">{me.email.split('@')[0]}</span>
      <span
        class="font-mono text-[9px] uppercase tracking-[0.1em] px-1.5 py-0.5 rounded-sm border"
        style="color: var(--accent); border-color: color-mix(in srgb, var(--accent) 35%, transparent); background: color-mix(in srgb, var(--accent) 8%, transparent);"
        title={me.email}
      >{me.role}</span>
    </a>
    <button
      type="button"
      on:click={logout}
      title="Sign out"
      class="px-2 py-1.5 rounded-sm border border-line-hairline hover:border-line-strong hover:bg-surface-elevated transition-colors text-[11px] font-mono text-ink-muted hover:text-ink-primary"
    >⏻</button>
  {/if}
</header>
