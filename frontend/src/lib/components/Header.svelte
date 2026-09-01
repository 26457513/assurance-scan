<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import { currentUser, loadCurrentUser } from '$lib/stores/currentUser';
  import ProjectSelector from './ProjectSelector.svelte';
  import ScanSelector from './ScanSelector.svelte';

  onMount(() => void loadCurrentUser());

  let confirmLogout = false;

  async function logout() {
    // Cookie clear + redirect must never be skipped because of a fetch error.
    try {
      await api.logout();
    } catch {
      /* session cookie expires on its own */
    }
    window.location.replace('https://tapestry.barkleygen.com/');
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

<header class="relative z-30 h-14 overflow-visible bg-surface-panel border-b border-line-hairline flex items-center px-5 gap-3">
  {#if section}
    <div class="text-[10px] font-mono uppercase tracking-[0.16em] text-ink-muted whitespace-nowrap mr-1">{section}</div>
    <div class="w-px h-3.5 bg-line-hairline"></div>
  {/if}
  <ProjectSelector />
  <span class="text-ink-muted font-mono text-[11px]">·</span>
  <ScanSelector />
  <span class="flex-1"></span>
  {#if $currentUser}
    <a
      href="/setup?tab=account"
      title="Settings"
      class="flex items-center gap-2 px-2.5 py-1.5 rounded-sm border border-line-hairline hover:border-line-strong hover:bg-surface-elevated transition-colors"
    >
      <span class="font-mono text-[11px] text-ink-primary">{$currentUser.email.split('@')[0]}</span>
      <span
        class="font-mono text-[9px] uppercase tracking-[0.1em] px-1.5 py-0.5 rounded-sm border"
        style="color: var(--accent); border-color: color-mix(in srgb, var(--accent) 35%, transparent); background: color-mix(in srgb, var(--accent) 8%, transparent);"
        title={$currentUser.email}
      >{$currentUser.role}</span>
    </a>
    <button
      type="button"
      on:click={() => (confirmLogout = true)}
      title="Sign out"
      class="px-2 py-1.5 rounded-sm border border-line-hairline hover:border-line-strong hover:bg-surface-elevated transition-colors text-[11px] font-mono text-ink-muted hover:text-ink-primary"
    >⏻</button>
  {/if}

  {#if confirmLogout}
    <div class="fixed inset-0 z-50 flex items-center justify-center">
      <button
        type="button"
        class="absolute inset-0 bg-black/65 backdrop-blur-[2px]"
        on:click={() => (confirmLogout = false)}
        aria-label="Close"
      ></button>
      <div class="relative w-[360px] border border-line-strong rounded-md bg-surface-panel p-5" style="box-shadow: 0 12px 32px rgba(0,0,0,0.4);">
        <div class="text-[13px] text-ink-primary mb-1.5">Sign out?</div>
        <p class="text-[12px] text-ink-secondary leading-relaxed mb-4">
          You will be returned to <span class="font-mono text-ink-primary">tapestry.barkleygen.com</span>.
        </p>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            on:click={() => (confirmLogout = false)}
            class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors"
          >Cancel</button>
          <button
            type="button"
            on:click={logout}
            class="px-3 py-1.5 rounded-sm border font-mono text-[11px] uppercase tracking-[0.1em] transition-colors"
            style="color: var(--state-failed); border-color: color-mix(in srgb, var(--state-failed) 35%, transparent);"
          >Sign out</button>
        </div>
      </div>
    </div>
  {/if}
</header>
