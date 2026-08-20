<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { selectedScan, selectScan } from '$lib/stores/selectedScan';
  import { selectedProject } from '$lib/stores/selectedProject';
  import { pushToast } from '$lib/stores/toasts';
  import { api } from '$lib/api';
  import type { ScanSummary } from '$lib/types';

  let open = false;
  let recent: ScanSummary[] = [];
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  // Same identity join as the project page: a scan belongs to the project
  // when its path matches exactly or its github repo folder name does.
  function isProjectScan(scan: ScanSummary, project: string): boolean {
    if (!project) return true;
    if (scan.project_path === project) return true;
    const base = project.replace(/\/$/, '').split('/').pop();
    return (
      scan.project_path.startsWith('github:') &&
      (scan.project_path.split('/').pop() ?? '') === base
    );
  }

  async function loadRecent() {
    try {
      const all = await api.listScansForSelector();
      recent = $selectedProject ? all.filter((s) => isProjectScan(s, $selectedProject)) : all;
      // Drop a selected scan that no longer belongs to this project.
      if ($selectedScan && $selectedProject && !isProjectScan($selectedScan, $selectedProject)) {
        selectScan(recent[0] ?? null);
      }
    } catch (e) {
      /* silent */
    }
  }

  // Refilter when the project selection changes.
  $: if ($selectedProject !== undefined) {
    loadRecent();
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
        finding_count: s.finding_count,
        run_number: s.run_number,
        display_title: s.display_title
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
    // Keep the URL in sync with the selection: scan detail pages change
    // path, project pages take the ?run= deep-link param.
    const scanPathMatch = url.pathname.match(/^\/scans\/[^/]+/);
    if (scanPathMatch) {
      url.pathname = `/scans/${scan.run_id}`;
    }
    if (url.pathname.match(/^\/projects\/[^/]+/)) {
      url.searchParams.set('run', scan.run_id);
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

  function scanLabel(scan: ScanSummary): string {
    if (scan.run_number != null) return `#${scan.run_number} ${scan.display_title ?? scan.run_id}`;
    return scan.run_id;
  }

  function fmtWhen(iso: string): string {
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  $: scanShort = $selectedScan
    ? $selectedScan.run_number != null
      ? `#${$selectedScan.run_number} ${$selectedScan.display_title ?? $selectedScan.run_id}`
      : shortLabel($selectedScan.run_id)
    : null;
  $: isRunning = $selectedScan && ($selectedScan.status === 'queued' || $selectedScan.status === 'running');
</script>

<div class="relative">
  <button
    type="button"
    on:click={toggle}
    disabled={!$selectedProject}
    title={$selectedProject ? '' : 'select a project first'}
    class="flex items-center gap-2 px-2.5 py-1.5 rounded-sm border border-line-hairline hover:border-line-strong hover:bg-surface-elevated transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
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
      class="absolute top-full left-0 mt-1 w-[720px] max-h-[480px] bg-surface-panel border border-line-strong rounded-md overflow-hidden z-50 flex flex-col"
      style="box-shadow: 0 12px 32px rgba(0,0,0,0.4);"
    >
      <div class="px-3 py-2 border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted flex items-center justify-between">
        <span>Scans</span>
        <span class="normal-case tracking-normal">newest first · click to select</span>
      </div>
      <div class="grid grid-cols-[minmax(0,1fr)_110px_80px_70px_60px] gap-3 px-3 py-1.5 border-b border-line-hairline text-[9px] font-mono uppercase tracking-[0.12em] text-ink-muted">
        <div>Scan</div>
        <div>Branch</div>
        <div>Status</div>
        <div class="text-right">When</div>
        <div class="text-right">Finds</div>
      </div>
      <div class="overflow-auto">
        {#each recent as scan (scan.run_id)}
          <button
            type="button"
            on:click={() => pick(scan)}
            class="w-full text-left px-3 py-2 hover:bg-surface-elevated transition-colors border-b border-line-hairline last:border-0 grid grid-cols-[minmax(0,1fr)_110px_80px_70px_60px] gap-3 items-center"
            class:bg-accent-subtle={$selectedScan?.run_id === scan.run_id}
          >
            <div class="font-mono text-[12px] text-ink-primary truncate" title={scan.run_id}>{scanLabel(scan)}</div>
            <div class="font-mono text-[11px] text-ink-secondary truncate">{scan.git_branch ?? '—'}</div>
            <div class="font-mono text-[10px] uppercase tracking-[0.08em] flex items-center gap-1.5">
              {#if scan.status === 'queued' || scan.status === 'running'}
                <span class="w-1.5 h-1.5 rounded-full bg-accent pulse-dot shrink-0"></span><span class="text-ink-secondary">{scan.status}</span>
              {:else if scan.status === 'completed'}
                <span class="text-ink-muted">done</span>
              {:else}
                <span class="text-ink-muted">{scan.status}</span>
              {/if}
            </div>
            <div class="text-right font-mono text-[11px] text-ink-muted tabular-nums whitespace-nowrap">{fmtWhen(scan.started_at)}</div>
            <div class="text-right font-mono text-[11px] text-ink-secondary tabular-nums">{scan.finding_count}</div>
          </button>
        {:else}
          <div class="px-3 py-10 text-center text-[12px] text-ink-muted font-mono">no scans yet for this project</div>
        {/each}
      </div>
    </div>
  {/if}
</div>
