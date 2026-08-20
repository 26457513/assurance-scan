<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { pushToast } from '$lib/stores/toasts';
  import { selectProject, slugToProject } from '$lib/stores/selectedProject';
  import ScanDetail from '$lib/components/ScanDetail.svelte';
  import type { ScanSummary } from '$lib/types';

  $: projectPath = slugToProject($page.params.slug ?? '');
  // FR/compliance views live as sub-tabs inside each scan (ScanDetail);
  // anything else normalizes to the scans view.
  $: view = 'scans';

  const VIEWS = [{ id: 'scans', label: 'Scans' }] as const;

  let scans: ScanSummary[] = [];
  let selectedRunId = '';
  let loading = true;
  let error: string | null = null;
  let polling = false;
  let scanRepo = '';
  let scanRef = '';
  let dispatching = false;
  let selected = new Set<string>();
  let deleteModalOpen = false;
  $: selectedCount = selected.size;

  function toggleRow(runId: string) {
    if (selected.has(runId)) selected.delete(runId);
    else selected.add(runId);
    selected = new Set(selected);
  }

  async function confirmDelete() {
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
    if (ids.includes(selectedRunId)) selectedRunId = '';
    if (ok > 0) pushToast('success', `Deleted ${ok} scan${ok === 1 ? '' : 's'} from assurance-scan`);
    if (fail > 0) pushToast('error', `${fail} delete${fail === 1 ? '' : 's'} failed`);
    await loadScans();
  }

  const PAGE_SIZES = [5, 10, 25, 50];
  let pageSize = 10;
  let pg = 0;

  $: projectScans = scans; // already filtered by project on load
  $: pageCount = Math.max(1, Math.ceil(projectScans.length / pageSize));
  $: visible = projectScans.slice(pg * pageSize, (pg + 1) * pageSize);

  // Path-derived identity: the same project exists locally and as
  // github:{org}/{folder} — join by folder name.
  $: baseName = projectPath.replace(/\/$/, '').split('/').pop() ?? '';
  function isProjectScan(s: ScanSummary): boolean {
    if (s.project_path === projectPath) return true;
    return (
      s.project_path.startsWith('github:') &&
      (s.project_path.split('/').pop() ?? '') === baseName
    );
  }

  async function loadScans() {
    try {
      const all = await api.listScans(200);
      scans = all.filter(isProjectScan);
      // A ?run= deep link selects its run; if it isn't ingested yet, one
      // getScan triggers the server's lazy pull, then we reload.
      const wanted = $page.url.searchParams.get('run');
      if (wanted) {
        const selectWanted = () => {
          const idx = scans.findIndex((s) => s.run_id === wanted);
          if (idx === -1) return false;
          selectedRunId = wanted;
          pg = Math.floor(idx / pageSize);  // jump pagination to the row
          return true;
        };
        if (!selectWanted()) {
          try {
            await api.getScan(wanted);  // lazy pull for un-ingested runs
            scans = (await api.listScans(200)).filter(isProjectScan);
            selectWanted();
          } catch {
            /* unknown run id — fall through to default selection */
          }
        }
      }
      if (!selectedRunId && scans.length) selectedRunId = scans[0].run_id;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    selectProject(projectPath);
    loadScans();
  });

  function switchView(id: string) {
    goto(`/projects/${$page.params.slug}?view=${id}`, { noScroll: true });
  }

  function pickScan(runId: string) {
    selectedRunId = runId;
  }

  $: latestScan = projectScans.reduce(
    (a, b) => ((a?.started_at ?? '') >= (b.started_at ?? '') ? a : b),
    null as ScanSummary | null
  );
  $: latestFailed = latestScan?.status === 'failed' ? latestScan : null;

  $: projectRepo = projectPath.startsWith('github:')
    ? projectPath.replace('github:', '')
    : '';

  async function scanNow() {
    dispatching = true;
    try {
      const res = await api.scanRemote(scanRepo.trim() || projectRepo, scanRef.trim());
      pushToast('success', `Scan dispatched to ${res.repo}@${res.ref} — watch the scans table`);
      scanRepo = '';
      scanRef = '';
    } catch (e) {
      pushToast('error', `Dispatch failed: ${e}`);
    } finally {
      dispatching = false;
    }
  }

  async function pollNow() {
    polling = true;
    try {
      const res = await api.pollNow();
      if (res.error) {
        pushToast('error', res.error);
      } else {
        const parts = [`${res.ingested ?? 0} new`, `${res.skipped ?? 0} up to date`];
        if (res.failed) parts.push(`${res.failed} failed`);
        pushToast(res.failed ? 'error' : 'success', `GitHub poll: ${parts.join(', ')}`);
      }
    } catch (e) {
      pushToast('error', `GitHub poll failed: ${e}`);
    } finally {
      polling = false;
      await loadScans();
    }
  }

  function fmtDuration(s: ScanSummary): string {
    if (!s.completed_at) return '—';
    const secs = Math.max(1, Math.round((new Date(s.completed_at).getTime() - new Date(s.started_at).getTime()) / 1000));
    if (secs < 60) return `${secs}s`;
    return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  }

  function repoName(s: ScanSummary): string {
    const parts = s.project_path.replace(/^github:/, '').split('/').filter(Boolean);
    return parts[parts.length - 1] ?? s.project_path;
  }

  function eventLabel(s: ScanSummary): string {
    if (!s.event) return '';
    if (s.event === 'pull_request') return `PR synchronize by ${s.actor ?? 'unknown'}`;
    if (s.event === 'workflow_dispatch') return `manual scan by ${s.actor ?? 'unknown'}`;
    if (s.event === 'schedule') return 'nightly SCA';
    if (s.event === 'push') return `commit pushed by ${s.actor ?? 'unknown'}`;
    return s.event;
  }

  function fmtDate(iso: string | null): string {
    if (!iso) return '—';
    const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    return m ? `${m[2]}/${m[3]} ${m[4]}:${m[5]}` : iso;
  }
</script>

<div class="border-b border-line-hairline px-6 pt-3 flex items-center gap-0.5 overflow-x-auto">
  {#each VIEWS as v (v.id)}
    <button
      type="button"
      on:click={() => switchView(v.id)}
      class="relative px-3.5 py-2.5 text-[11px] font-mono uppercase tracking-[0.12em] transition-colors whitespace-nowrap"
      class:text-accent={view === v.id}
      class:text-ink-muted={view !== v.id}
      class:hover:text-ink-secondary={view !== v.id}
    >
      {v.label}
      {#if view === v.id}
        <span class="absolute left-0 right-0 -bottom-px h-[2px] bg-accent"></span>
      {/if}
    </button>
  {/each}
  <span class="flex-1"></span>
  <span class="font-mono text-[11px] text-ink-muted truncate pr-1" title={projectPath}>{projectPath}</span>
</div>

{#if view === 'scans'}
  <div class="p-6">
    {#if latestFailed}
      <button
        type="button"
        on:click={() => pickScan(latestFailed.run_id)}
        class="w-full flex items-center gap-2 px-3 py-2 mb-3 text-left border border-line-strong rounded-sm font-mono text-[11px] transition-colors"
        style="color: var(--state-failed); background: color-mix(in srgb, var(--state-failed) 8%, transparent);"
      >
        <span class="uppercase tracking-[0.1em]">Latest scan failed</span>
        <span class="text-ink-primary">{latestFailed.run_id}</span>
        <span class="text-ink-muted">— needs investigation, click to open</span>
      </button>
    {/if}
    <div class="flex justify-end items-center gap-2 mb-3">
      <input
        type="text"
        bind:value={scanRepo}
        placeholder={projectRepo || 'owner/repo'}
        title="Repository to scan (defaults to this project's repo)"
        class="w-56 px-2 py-1.5 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary"
      />
      <input
        type="text"
        bind:value={scanRef}
        placeholder="branch/sha (default)"
        class="w-40 px-2 py-1.5 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary"
      />
      <button
        type="button"
        on:click={scanNow}
        disabled={dispatching || (!scanRepo.trim() && !projectRepo)}
        title="Scan now — dispatches the repo workflow, or the remote runner for repos outside the org"
        class="inline-flex items-center gap-2 px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors disabled:opacity-50"
      >
        <svg viewBox="0 0 12 12" class="h-3 w-3" stroke="currentColor" stroke-width="1.6" fill="none">
          <path d="M6 1.5v6M3.2 5.8L6 8.5l2.8-2.7M2 10.5h8" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <span>{dispatching ? 'Dispatching…' : 'Scan now'}</span>
      </button>
      {#if selectedCount > 0}
        <button
          type="button"
          on:click={() => (deleteModalOpen = true)}
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-sm border transition-colors font-mono text-[11px] uppercase tracking-[0.1em]"
          style="color: var(--state-failed); border-color: color-mix(in srgb, var(--state-failed) 35%, transparent); background: color-mix(in srgb, var(--state-failed) 8%, transparent);"
        >Delete {selectedCount} selected</button>
      {/if}
      <button
        type="button"
        on:click={pollNow}
        disabled={polling}
        title="Fetch completed assurance-scan runs from GitHub Actions"
        class="inline-flex items-center gap-2 px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-ink-primary transition-colors disabled:opacity-50"
      >
        <svg viewBox="0 0 12 12" class="h-3 w-3" stroke="currentColor" stroke-width="1.6" fill="none">
          <path d="M10 6a4 4 0 11-1.2-2.8M10 1v2.5H7.5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <span class="text-[11px] font-mono uppercase tracking-[0.1em]">{polling ? 'Retrieving…' : 'Retrieve from GitHub'}</span>
      </button>
    </div>
    {#if loading}
      <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
    {:else if error}
      <div class="text-[12px] text-state-failed font-mono">{error}</div>
    {:else if projectScans.length === 0}
      <div class="py-10 text-center text-[12px] text-ink-muted font-mono">
        No scans for this project yet.
      </div>
    {:else}
      <div class="border border-line-hairline rounded-sm overflow-hidden bg-surface-panel mb-5">
        <div class="grid grid-cols-[26px_minmax(0,1.8fr)_1fr_1fr_1.3fr_80px_100px_70px_70px] gap-4 px-4 py-2 bg-surface-inset border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted items-center">
          <div></div>
          <div>Run</div>
          <div>Repo</div>
          <div>Branch</div>
          <div>Trigger</div>
          <div>Status</div>
          <div>Started</div>
          <div>Duration</div>
          <div class="text-right">Findings</div>
        </div>
        {#each visible as s (s.run_id)}
          <div
            role="button"
            tabindex="0"
            on:click={() => pickScan(s.run_id)}
            on:keydown={(e) => e.key === 'Enter' && pickScan(s.run_id)}
            class="w-full text-left grid grid-cols-[26px_minmax(0,1.8fr)_1fr_1fr_1.3fr_80px_100px_70px_70px] gap-4 px-4 py-2 border-b border-line-hairline last:border-0 transition-colors hover:bg-surface-elevated font-mono text-[12px] items-center cursor-pointer"
            class:bg-accent-subtle={selectedRunId === s.run_id}
          >
            <input
              type="checkbox"
              checked={selected.has(s.run_id)}
              on:click|stopPropagation={() => toggleRow(s.run_id)}
              class="cursor-pointer accent-current"
              aria-label="Select {s.run_id}"
            />
            <span class="text-ink-primary truncate" title={s.run_id}>
              {#if s.run_number != null}#{s.run_number} · {s.display_title || s.run_id}{:else}{s.run_id}{/if}
            </span>
            <span class="font-mono text-[11px] text-ink-secondary truncate" title={s.project_path}>{repoName(s)}</span>
            <span class="font-mono text-[11px] text-ink-secondary truncate" title={s.git_branch ?? ''}>{s.git_branch ?? '—'}</span>
            <span class="text-[11px] text-ink-muted truncate">{eventLabel(s) || '—'}</span>
            <span class={s.status === 'completed'
              ? 'text-state-passed'
              : s.status === 'failed'
                ? 'text-state-failed'
                : 'text-state-pending'}>{s.status}</span>
            <span class="text-ink-muted">{fmtDate(s.started_at)}</span>
            <span class="text-ink-muted tabular-nums">{fmtDuration(s)}</span>
            <span class="text-right text-ink-secondary tabular-nums">{s.finding_count}</span>
          </div>
        {/each}
      </div>

      <div class="flex items-center justify-between mb-4 font-mono text-[11px]">
        <div class="flex items-center gap-1.5 text-ink-muted">
          <span class="uppercase tracking-[0.1em] text-[10px]">rows</span>
          {#each PAGE_SIZES as size (size)}
            <button
              type="button"
              on:click={() => { pageSize = size; pg = 0; }}
              class="px-2 py-0.5 border rounded-sm transition-colors"
              class:border-line-strong={pageSize === size}
              class:text-ink-primary={pageSize === size}
              class:border-line-hairline={pageSize !== size}
              class:hover:text-ink-secondary={pageSize !== size}
            >{size}</button>
          {/each}
        </div>
        {#if pageCount > 1}
          <div class="flex items-center gap-2">
            <button
              type="button"
              on:click={() => (pg = Math.max(0, pg - 1))}
              disabled={pg === 0}
              class="px-2 py-0.5 border border-line-hairline rounded-sm text-ink-secondary disabled:opacity-40"
            >‹ prev</button>
            <span class="text-ink-muted">page {pg + 1} / {pageCount}</span>
            <button
              type="button"
              on:click={() => (pg = Math.min(pageCount - 1, pg + 1))}
              disabled={pg >= pageCount - 1}
              class="px-2 py-0.5 border border-line-hairline rounded-sm text-ink-secondary disabled:opacity-40"
            >next ›</button>
          </div>
        {/if}
      </div>

      {#if selectedRunId}
        <div class="border border-line-hairline rounded-sm overflow-hidden">
          <ScanDetail runId={selectedRunId} />
        </div>
      {/if}
    {/if}
  </div>

  {#if deleteModalOpen}
    <div class="fixed inset-0 z-50 flex items-center justify-center p-6">
      <button type="button" class="absolute inset-0 bg-black/65 backdrop-blur-[2px]" on:click={() => (deleteModalOpen = false)} aria-label="Close"></button>
      <div class="relative border border-line-strong rounded-sm bg-surface-panel max-w-md w-full p-5">
        <div class="text-[13px] text-ink-primary mb-2 font-mono">Delete {selectedCount} scan{selectedCount === 1 ? '' : 's'}?</div>
        <p class="text-[12px] text-ink-secondary leading-relaxed mb-5">
          This removes the scan information from <strong>assurance-scan only</strong> — nothing is deleted from GitHub.
          The scans will be restored the next time <em>Retrieve from GitHub</em> runs.
        </p>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            on:click={() => (deleteModalOpen = false)}
            class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary"
          >Cancel</button>
          <button
            type="button"
            on:click={confirmDelete}
            class="px-3 py-1.5 rounded-sm text-[11px] font-mono uppercase tracking-[0.1em]"
            style="color: var(--state-failed); border: 1px solid color-mix(in srgb, var(--state-failed) 35%, transparent); background: color-mix(in srgb, var(--state-failed) 8%, transparent);"
          >Delete</button>
        </div>
      </div>
    </div>
  {/if}
{/if}
