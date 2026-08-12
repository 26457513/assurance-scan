<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { selectedScan, selectScan } from '$lib/stores/selectedScan';
  import { pushToast } from '$lib/stores/toasts';
  import StatePill from '$lib/components/StatePill.svelte';
  import FolderPicker from '$lib/components/FolderPicker.svelte';
  import { severityMeta } from '$lib/state';
  import type { ScanSummary, TrendsResponse } from '$lib/types';

  let scans: ScanSummary[] = [];
  let trends: TrendsResponse | null = null;
  let loading = true;
  let error: string | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let scanning = false;
  let newScanModalOpen = false;
  let newScanPath = '';
  let showFolderPicker = false;

  $: recentPaths = [...new Set(scans.map((s) => s.project_path))].slice(0, 5);

  // Selection state
  let selected: Set<string> = new Set();
  $: allSelected = scans.length > 0 && selected.size === scans.length;
  $: someSelected = selected.size > 0 && !allSelected;
  $: selectedCount = selected.size;

  // Delete confirmation modal
  let deleteModalOpen = false;

  function toggleRow(runId: string) {
    if (selected.has(runId)) selected.delete(runId);
    else selected.add(runId);
    selected = new Set(selected);
  }

  function toggleAll() {
    if (allSelected) {
      selected = new Set();
    } else {
      selected = new Set(scans.map((s) => s.run_id));
    }
  }

  async function refresh() {
    try {
      const [s, t] = await Promise.all([api.listScans(), api.getTrendsForScanList().catch(() => null)]);
      scans = s;
      trends = t;
      // Prune selection: remove run_ids that no longer exist
      const validIds = new Set(s.map((x) => x.run_id));
      selected = new Set([...selected].filter((id) => validIds.has(id)));
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    refresh();
    pollTimer = setInterval(refresh, 5000);
  });
  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  function severityFor(runId: string, severity: string): number {
    const run = trends?.runs.find((r) => r.run_id === runId);
    return run?.by_severity[severity] ?? 0;
  }

  function totalFor(runId: string): number {
    const run = trends?.runs.find((r) => r.run_id === runId);
    return run?.total_findings ?? 0;
  }

  function openScan(scan: ScanSummary) {
    selectScan(scan);
    goto(`/scans/${scan.run_id}?run_id=${scan.run_id}`);
  }

  function openNewScanModal() {
    newScanPath = $selectedScan?.project_path || recentPaths[0] || '';
    showFolderPicker = false;
    newScanModalOpen = true;
  }

  function onFolderSelect(e: CustomEvent<string>) {
    newScanPath = e.detail;
    showFolderPicker = false;
  }

  async function handleNewScan() {
    if (scanning || !newScanPath.trim()) return;
    scanning = true;
    newScanModalOpen = false;
    pushToast('info', `Queuing scan of ${newScanPath}…`);
    try {
      const res = await api.startScan(newScanPath.trim());
      pushToast('success', `Scan queued: ${res.run_id.slice(-8)}`);
      await refresh();
    } catch (e) {
      pushToast('error', `Scan failed: ${(e as Error).message}`);
    } finally {
      scanning = false;
    }
  }

  function confirmDelete() {
    deleteModalOpen = true;
  }

  async function doDelete() {
    const ids = [...selected];
    let ok = 0;
    let fail = 0;
    for (const id of ids) {
      try {
        await api.deleteScan(id);
        ok++;
      } catch {
        fail++;
      }
    }
    selected = new Set();
    deleteModalOpen = false;
    await refresh();

    // Clear the selected scan if it was among the deleted.
    if ($selectedScan && ids.includes($selectedScan.run_id)) {
      selectScan(null);
      goto('/scans', { noScroll: true });
    }

    if (ok > 0) pushToast('success', `Deleted ${ok} scan${ok === 1 ? '' : 's'}`);
    if (fail > 0) pushToast('error', `${fail} delete${fail === 1 ? '' : 's'} failed`);
    await refresh();
  }

  function fmtTime(s: string): string {
    const d = new Date(s);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  const SEV_ORDER = ['HIGH', 'MEDIUM', 'LOW'];
  $: anyRunning = scans.some((s) => s.status === 'queued' || s.status === 'running');
</script>

<div class="p-6">
  <div class="flex justify-between items-center mb-4">
    <div class="flex items-center gap-4">
      <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted">
        {#if scans.length > 0}{scans.length} scan{scans.length === 1 ? '' : 's'}{/if}
      </div>
      {#if selectedCount > 0}
        <button
          type="button"
          on:click={confirmDelete}
          class="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.08em] px-2.5 py-1 rounded-sm border transition-colors"
          style="color: var(--state-failed); border-color: color-mix(in srgb, var(--state-failed) 35%, transparent); background: color-mix(in srgb, var(--state-failed) 8%, transparent);"
        >
          <svg viewBox="0 0 12 12" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M3 4l1.5 6h3L9 4M3 4h6M4.5 4V3a1 1 0 011-1h1a1 1 0 011 1v1" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          Delete {selectedCount} selected
        </button>
      {/if}
    </div>
    <button
      type="button"
      on:click={openNewScanModal}
      disabled={scanning}
      class="inline-flex items-center gap-2 px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-ink-primary transition-colors disabled:opacity-50"
    >
      <svg viewBox="0 0 12 12" class="h-3 w-3 group-hover:text-accent" stroke="currentColor" stroke-width="1.6" fill="none">
        <path d="M6 2v8M2 6h8" stroke-linecap="round" />
      </svg>
      <span class="text-[11px] font-mono uppercase tracking-[0.1em]">{scanning ? 'Queuing…' : 'New scan'}</span>
    </button>
  </div>

  {#if loading}
    <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else if error}
    <div class="text-[12px] text-state-failed font-mono">{error}</div>
  {:else if scans.length === 0}
    <div class="py-20 text-center">
      <div class="text-[14px] text-ink-primary mb-2">No scans yet</div>
      <div class="text-[12px] text-ink-muted font-mono">Click <span class="text-accent">New scan</span> above to run one.</div>
    </div>
  {:else}
    <div class="border border-line-hairline rounded-sm overflow-hidden bg-surface-panel">
      <!-- Header row with select-all checkbox -->
      <div class="grid grid-cols-[28px_minmax(0,260px)_minmax(0,1fr)_110px_140px_minmax(120px,180px)] gap-4 px-4 py-2 border-b border-line-hairline bg-surface-inset text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted items-center">
        <div class="flex items-center justify-center">
          <input type="checkbox" checked={allSelected} on:change={toggleAll}
            class="accent-[var(--accent)] cursor-pointer {someSelected ? 'opacity-50' : ''}" />
        </div>
        <div>Run</div>
        <div>Project</div>
        <div>Status</div>
        <div>Started</div>
        <div class="text-right">Findings by severity</div>
      </div>

      {#each scans as scan (scan.run_id)}
        {@const isSelected = selected.has(scan.run_id)}
        <div class="grid grid-cols-[28px_minmax(0,260px)_minmax(0,1fr)_110px_140px_minmax(120px,180px)] gap-4 px-4 py-3 border-b border-line-hairline last:border-0 transition-colors duration-150 items-center"
          class:bg-accent-subtle={$selectedScan?.run_id === scan.run_id}
          class:bg-surface-elevated={isSelected && $selectedScan?.run_id !== scan.run_id}
        >
          <div class="flex items-center justify-center">
            <input type="checkbox" checked={isSelected}
              on:change={() => toggleRow(scan.run_id)}
              on:click|stopPropagation
              class="accent-[var(--accent)] cursor-pointer" />
          </div>

          <button type="button" on:click={() => openScan(scan)} class="text-left min-w-0">
            <div class="font-mono text-[12px] text-ink-primary truncate flex items-center gap-1.5">
              {#if scan.status === 'queued' || scan.status === 'running'}
                <span class="w-1.5 h-1.5 rounded-full bg-accent pulse-dot shrink-0"></span>
              {/if}
              {scan.run_id}
            </div>
          </button>

          <div class="font-mono text-[11px] text-ink-muted truncate" title={scan.project_path}>
            {scan.project_path}
          </div>
          <div><StatePill state={scan.status} size="sm" /></div>
          <div class="font-mono text-[11px] text-ink-secondary">{fmtTime(scan.started_at)}</div>
          <div class="flex items-center justify-end gap-3">
            {#if totalFor(scan.run_id) === 0 && !trends?.runs.find(r => r.run_id === scan.run_id)}
              <span class="text-[11px] text-ink-muted font-mono">—</span>
            {:else}
              {#each SEV_ORDER as sev}
                {@const count = severityFor(scan.run_id, sev)}
                {#if count > 0}
                  <span class="font-mono text-[11px] tabular-nums" style="color: {severityMeta(sev).color};" title={`${count} ${sev}`}>{count}<span class="text-ink-muted ml-1">{severityMeta(sev).label}</span></span>
                {/if}
              {/each}
              {#if severityFor(scan.run_id, 'CRITICAL') > 0}
                <span class="font-mono text-[11px] tabular-nums" style="color: {severityMeta('CRITICAL').color};">{severityFor(scan.run_id, 'CRITICAL')}<span class="text-ink-muted ml-1">CRIT</span></span>
              {/if}
            {/if}
          </div>
        </div>
      {/each}
    </div>
    {#if anyRunning}
      <div class="mt-3 text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted">scan in progress · polling every 5s</div>
    {/if}
  {/if}
</div>

{#if deleteModalOpen}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
    <button type="button" class="absolute inset-0 bg-black/65 backdrop-blur-[2px]" on:click={() => (deleteModalOpen = false)} aria-label="Close"></button>
    <div role="dialog" aria-modal="true" class="relative w-full max-w-md bg-surface-panel border border-line-strong rounded-md p-6" style="box-shadow: 0 24px 64px rgba(0,0,0,0.5);">
      <div class="flex items-start gap-3 mb-4">
        <div class="w-9 h-9 rounded-sm flex items-center justify-center shrink-0" style="background: color-mix(in srgb, var(--state-failed) 12%, transparent);">
          <svg viewBox="0 0 16 16" class="h-4 w-4" fill="none" stroke="var(--state-failed)" stroke-width="1.8">
            <path d="M8 3v6M8 11.5v1" stroke-linecap="round" />
            <circle cx="8" cy="8" r="6.5" />
          </svg>
        </div>
        <div class="flex-1">
          <div class="text-[14px] text-ink-primary mb-1">
            Delete {selectedCount} scan{selectedCount === 1 ? '' : 's'}?
          </div>
          <div class="text-[12px] text-ink-secondary leading-relaxed">
            All findings, scanner artifacts, test results, and FR states for the selected
            scan{selectedCount === 1 ? '' : 's'} will be permanently deleted. This cannot be undone.
          </div>
          {#if selectedCount <= 5}
            <div class="mt-3 space-y-0.5">
              {#each [...selected] as id}
                <div class="font-mono text-[10px] text-ink-muted">{id}</div>
              {/each}
            </div>
          {/if}
        </div>
      </div>
      <div class="flex items-center justify-end gap-2 mt-5">
        <button type="button" on:click={() => (deleteModalOpen = false)}
          class="font-mono text-[11px] uppercase tracking-[0.08em] px-3 py-1.5 rounded-sm border border-line-hairline text-ink-secondary hover:bg-surface-elevated transition-colors">
          Cancel
        </button>
        <button type="button" on:click={doDelete}
          class="font-mono text-[11px] uppercase tracking-[0.08em] px-3 py-1.5 rounded-sm border text-state-failed transition-colors"
          style="border-color: color-mix(in srgb, var(--state-failed) 35%, transparent); background: color-mix(in srgb, var(--state-failed) 8%, transparent);"
        >
          Delete permanently
        </button>
      </div>
    </div>
  </div>
{/if}

{#if newScanModalOpen}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
    <button type="button" class="absolute inset-0 bg-black/65 backdrop-blur-[2px]" on:click={() => (newScanModalOpen = false)} aria-label="Close"></button>
    <div role="dialog" aria-modal="true" class="relative w-full {showFolderPicker ? 'max-w-xl' : 'max-w-md'} bg-surface-panel border border-line-strong rounded-md p-6 transition-all duration-200" style="box-shadow: 0 24px 64px rgba(0,0,0,0.5);">
      <div class="text-[14px] text-ink-primary mb-1">New scan</div>
      <div class="text-[12px] text-ink-secondary leading-relaxed mb-4">
        Enter the absolute path of the project to scan, or browse to it. The folder must contain (or will get) an <code class="font-mono text-ink-primary">fr-catalog.json</code>.
      </div>

      <div class="flex items-baseline justify-between mb-1.5">
        <label class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted">Project path</label>
        <button
          type="button"
          on:click={() => (showFolderPicker = !showFolderPicker)}
          class="font-mono text-[10px] uppercase tracking-[0.08em] flex items-center gap-1 transition-colors"
          class:text-accent={showFolderPicker}
        >
          <svg viewBox="0 0 12 12" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="1.4">
            <path d="M1.5 3.5C1.5 3 1.7 2.8 2 2.8h2.5l1 1H10c.3 0 .5.2.5.5v5.4c0 .3-.2.5-.5.5H2c-.3 0-.5-.2-.5-.5V3.5z" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          {showFolderPicker ? 'Hide browser' : 'Browse…'}
        </button>
      </div>
      <input
        type="text"
        bind:value={newScanPath}
        on:keydown={(e) => e.key === 'Enter' && handleNewScan()}
        placeholder="/path/to/your/project"
        class="w-full bg-surface-inset border border-line-hairline rounded-sm px-2.5 py-1.5 text-[12px] text-ink-primary font-mono focus:outline-none focus:border-accent mb-3"
        spellcheck="false"
      />

      {#if showFolderPicker}
        <FolderPicker
          initialPath={newScanPath || null}
          on:select={onFolderSelect}
          on:cancel={() => (showFolderPicker = false)}
        />
      {:else if recentPaths.length > 0}
        <div class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted mb-1.5">Recent</div>
        <div class="flex flex-col gap-1 mb-4">
          {#each recentPaths as path}
            <button type="button" on:click={() => (newScanPath = path)}
              class="text-left text-[11px] font-mono text-ink-secondary hover:text-accent truncate transition-colors"
              title={path}>
              {path}
            </button>
          {/each}
        </div>
      {/if}

      <div class="flex items-center justify-end gap-2 mt-4">
        <button type="button" on:click={() => (newScanModalOpen = false)}
          class="font-mono text-[11px] uppercase tracking-[0.08em] px-3 py-1.5 rounded-sm border border-line-hairline text-ink-secondary hover:bg-surface-elevated transition-colors">
          Cancel
        </button>
        <button type="button" on:click={handleNewScan} disabled={!newScanPath.trim()}
          class="font-mono text-[11px] uppercase tracking-[0.08em] px-3 py-1.5 rounded-sm border transition-colors disabled:opacity-40"
          style="color: var(--accent); border-color: color-mix(in srgb, var(--accent) 35%, transparent); background: color-mix(in srgb, var(--accent) 8%, transparent);">
          Scan
        </button>
      </div>
    </div>
  </div>
{/if}
