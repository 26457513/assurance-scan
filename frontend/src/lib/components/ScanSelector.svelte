<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { selectedScan, selectScan } from '$lib/stores/selectedScan';
  import { pushToast } from '$lib/stores/toasts';
  import { api } from '$lib/api';
  import type { ScanSummary } from '$lib/types';

  let open = false;
  let recent: ScanSummary[] = [];
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  async function loadRecent() {
    try {
      recent = await api.listScansForSelector();
    } catch (e) {
      /* silent */
    }
  }

  async function tickPoll() {
    const s = $selectedScan;
    if (!s) return;
    if (s.status !== 'queued' && s.status !== 'running') return;
    try {
      const fresh = await api.getScan(s.run_id);
      selectScan({
        run_id: fresh.run_id,
        project_path: fresh.project_path,
        status: fresh.status,
        started_at: fresh.started_at,
        completed_at: fresh.completed_at,
        finding_count: s.finding_count
      });
      if (fresh.status === 'completed' || fresh.status === 'failed' || fresh.status === 'cancelled') {
        await loadRecent();
      }
    } catch (e) {
      /* silent */
    }
  }

  onMount(() => {
    loadRecent();
    pollTimer = setInterval(tickPoll, 4000);
  });

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  function toggle() {
    open = !open;
    if (open) loadRecent();
  }

  function pick(scan: ScanSummary) {
    open = false;
    selectScan(scan);
    pushToast('info', `Selected ${shortLabel(scan.run_id)}`);
    const url = new URL(window.location.href);
    url.searchParams.set('run_id', scan.run_id);
    // If currently on a scan detail page, navigate to the new scan's detail
    // (preserving the current tab) so the URL path stays in sync with the selection.
    const scanPathMatch = url.pathname.match(/^\/scans\/[^/]+/);
    if (scanPathMatch) {
      url.pathname = `/scans/${scan.run_id}`;
    }
    goto(`${url.pathname}?${url.searchParams.toString()}`, { noScroll: true });
  }

  function shortLabel(id: string): string {
    const m = id.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z_/);
    if (m) {
      const [, y, mo, d, h, mi, s] = m;
      return `${mo}/${d} ${h}:${mi}`;
    }
    return id.slice(-8);
  }

  $: scanShort = $selectedScan ? shortLabel($selectedScan.run_id) : null;
  $: isRunning = $selectedScan && ($selectedScan.status === 'queued' || $selectedScan.status === 'running');
</script>

<div class="relative">
  <button
    type="button"
    on:click={toggle}
    class="flex items-center gap-2 px-2.5 py-1.5 rounded-sm border border-line-hairline hover:border-line-strong hover:bg-surface-elevated transition-colors"
  >
    {#if isRunning}
      <span class="w-1.5 h-1.5 rounded-full bg-accent pulse-dot"></span>
    {/if}
    <span class="font-mono text-[12px] text-ink-primary">{scanShort ?? 'no scan'}</span>
    {#if $selectedScan}
      <span class="text-[11px] text-ink-muted font-mono tabular-nums">{$selectedScan.finding_count} finds</span>
    {/if}
    <svg class="h-3 w-3 text-ink-muted" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M3 4.5l3 3 3-3" stroke-linecap="round" />
    </svg>
  </button>

  {#if open}
    <button
      type="button"
      class="fixed inset-0 z-40 cursor-default"
      on:click={() => (open = false)}
      aria-label="Close dropdown"
    ></button>
    <div
      class="absolute top-full left-0 mt-1 w-[440px] max-h-[480px] bg-surface-panel border border-line-strong rounded-md overflow-hidden z-50 flex flex-col"
      style="box-shadow: 0 12px 32px rgba(0,0,0,0.4);"
    >
      <div class="px-3 py-2 border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted flex items-center justify-between">
        <span>Recent scans</span>
        <span class="text-ink-muted normal-case tracking-normal">click to select</span>
      </div>
      <div class="overflow-auto">
        {#each recent as scan (scan.run_id)}
          <button
            type="button"
            on:click={() => pick(scan)}
            class="w-full text-left px-3 py-2 hover:bg-surface-elevated transition-colors border-b border-line-hairline last:border-0 flex items-center justify-between gap-3"
            class:bg-accent-subtle={$selectedScan?.run_id === scan.run_id}
          >
            <div class="min-w-0 flex-1">
              <div class="font-mono text-[12px] text-ink-primary">{scan.run_id}</div>
              <div class="text-[11px] text-ink-muted font-mono truncate">{scan.project_path}</div>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              {#if scan.status === 'queued' || scan.status === 'running'}
                <span class="w-1.5 h-1.5 rounded-full bg-accent pulse-dot"></span>
              {/if}
              <span class="font-mono text-[11px] text-ink-secondary tabular-nums">{scan.finding_count}</span>
            </div>
          </button>
        {:else}
          <div class="px-3 py-10 text-center text-[12px] text-ink-muted font-mono">no scans yet — click "New scan"</div>
        {/each}
      </div>
    </div>
  {/if}
</div>
