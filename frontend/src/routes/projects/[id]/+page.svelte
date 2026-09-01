<script lang="ts">
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import { pushToast } from '$lib/stores/toasts';
  import { selectProject } from '$lib/stores/selectedProject';
  import { selectedScan, selectScan } from '$lib/stores/selectedScan';
  import { createRequestGate, type RequestTicket } from '$lib/requestGate';
  import { selectedRunFromUrl } from '$lib/scanSelectionUrl';
  import ScanDetail from '$lib/components/ScanDetail.svelte';
  import ScanCommitComparison from '$lib/components/ScanCommitComparison.svelte';
  import ScanOriginBadge from '$lib/components/ScanOriginBadge.svelte';
  import {
    filterScansByOrigin,
    scanRunLabel,
    sameCommitComparison,
    shortCommit,
    type ScanOriginFilter
  } from '$lib/scanProvenance';
  import type { ProjectSummary, ScanSummary } from '$lib/types';

  $: projectId = Number($page.params.id);
  let project: ProjectSummary | null = null;
  let scans: ScanSummary[] = [];
  let selectedRunId = '';
  let loading = true;
  let error: string | null = null;
  let polling = false;
  let scanRef = '';
  let dispatching = false;
  let scanConfirmOpen = false;
  let scanBranches: string[] = [];
  let scanBranchError = false;
  let originFilter: ScanOriginFilter = 'all';
  let comparisonRunId = '';
  const routeGate = createRequestGate<number>();
  const scansGate = createRequestGate<number>();

  $: if (!Number.isInteger(projectId) || projectId <= 0) {
    loading = false;
    error = 'Invalid project ID';
  }

  async function loadScanBranches(repo: string) {
    scanBranchError = false;
    scanBranches = [];
    if (!repo) return;
    try {
      scanBranches = (await api.githubBranches(repo)).branches;
    } catch {
      scanBranchError = true;
    }
  }
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

  $: projectScans = filterScansByOrigin(scans, originFilter); // already scoped to one project by the API
  $: pageCount = Math.max(1, Math.ceil(projectScans.length / pageSize));
  $: visible = projectScans.slice(pg * pageSize, (pg + 1) * pageSize);
  $: comparisonScan = comparisonRunId
    ? scans.find((scan) => scan.run_id === comparisonRunId) ?? null
    : null;
  $: comparison = comparisonScan ? sameCommitComparison(scans, comparisonScan) : null;

  async function loadScans(targetProjectId = projectId, showLoading = false) {
    const ticket = scansGate.begin(targetProjectId, { force: true });
    if (!ticket) return;
    if (showLoading) loading = true;
    const wanted = selectedRunFromUrl($page.url);
    try {
      let nextScans = await api.listScans(targetProjectId, 200);
      // A ?run= deep link selects its run; if it isn't ingested yet, one
      // getScan triggers the server's lazy pull, then we reload.
      let nextSelectedRunId = selectedRunId;
      let nextPage = pg;
      if (wanted) {
        const selectWanted = () => {
          const idx = nextScans.findIndex((s) => s.run_id === wanted);
          if (idx === -1) return false;
          nextSelectedRunId = wanted;
          nextPage = Math.floor(idx / pageSize);  // jump pagination to the row
          return true;
        };
        if (!selectWanted()) {
          try {
            await api.getScan(wanted);  // lazy pull for un-ingested runs
            nextScans = await api.listScans(targetProjectId, 200);
            selectWanted();
          } catch {
            /* unknown run id — fall through to default selection */
          }
        }
      }
      if (!nextScans.some((scan) => scan.run_id === nextSelectedRunId)) {
        nextSelectedRunId = nextScans[0]?.run_id ?? '';
        nextPage = 0;
      }
      if (!scansGate.isCurrent(ticket)) return;
      scans = nextScans;
      selectedRunId = nextSelectedRunId;
      pg = nextPage;
      error = null;
    } catch (e) {
      if (scansGate.isCurrent(ticket)) error = String(e);
    } finally {
      if (scansGate.isCurrent(ticket)) loading = false;
    }
  }

  async function activateProject(targetProjectId: number, ticket: RequestTicket<number>) {
    selectedRunId = '';
    comparisonRunId = '';
    originFilter = 'all';
    pg = 0;
    scans = [];
    project = null;
    defaultScanRef = null;
    error = null;
    loading = true;
    selectProject(targetProjectId);
    void loadScans(targetProjectId, true);
    try {
      const projects = await api.listProjects();
      if (!routeGate.isCurrent(ticket)) return;
      project = projects.projects.find((item) => item.id === targetProjectId) ?? null;
      defaultScanRef = project?.default_scan_ref ?? null;
    } catch {
      if (routeGate.isCurrent(ticket)) defaultScanRef = null;
    }
  }

  // Reactive, not onMount: SvelteKit keeps this component alive across
  // /projects/1 → /projects/2 param changes, so switching project in the
  // header dropdown must reload the table.
  $: if (Number.isInteger(projectId) && projectId > 0) {
    const ticket = routeGate.begin(projectId);
    if (ticket) void activateProject(projectId, ticket);
  }

  function pickScan(runId: string) {
    selectedRunId = runId;
    const s = scans.find((x) => x.run_id === runId);
    if (s) selectScan(s);
  }

  function setOriginFilter(value: ScanOriginFilter) {
    originFilter = value;
    pg = 0;
    const filtered = filterScansByOrigin(scans, value);
    if (selectedRunId && !filtered.some((scan) => scan.run_id === selectedRunId)) {
      selectedRunId = filtered[0]?.run_id ?? '';
      selectScan(filtered[0] ?? null);
    }
  }

  function openComparison(scan: ScanSummary) {
    comparisonRunId = scan.run_id;
  }

  function openComparedRun(runId: string) {
    pickScan(runId);
    const index = projectScans.findIndex((scan) => scan.run_id === runId);
    if (index >= 0) pg = Math.floor(index / pageSize);
  }

  // The header scan dropdown drives the table row + detail view; jump
  // pagination so the highlighted row is visible.
  $: if ($selectedScan && $selectedScan.run_id !== selectedRunId) {
    const idx = scans.findIndex((s) => s.run_id === $selectedScan.run_id);
    if (idx !== -1) {
      if (originFilter !== 'all' && scans[idx].origin !== originFilter) originFilter = 'all';
      selectedRunId = $selectedScan.run_id;
      pg = Math.floor(idx / pageSize);
    }
  }

  $: latestScan = scans.reduce(
    (a, b) => ((a?.started_at ?? '') >= (b.started_at ?? '') ? a : b),
    null as ScanSummary | null
  );
  $: latestFailed = latestScan?.status === 'failed' ? latestScan : null;

  $: projectRepo = project?.github_repo ?? '';

  // Seed the Scan-now ref with the project's default branch preference
  // (from the registry) the first time the field is still empty.
  $: if (defaultScanRef && !scanRef && !dispatching) {
    scanRef = defaultScanRef;
  }
  let defaultScanRef: string | null = null;

  function confirmScan() {
    scanConfirmOpen = true;
    loadScanBranches(projectRepo);
  }

  async function scanNow() {
    scanConfirmOpen = false;
    dispatching = true;
    try {
      const res = await api.scanRemote(projectId, scanRef.trim());
      if (res.warning) {
        pushToast('error', `Dispatched to ${res.repo}@${res.ref}, but: ${res.warning}`);
      } else {
        pushToast('success', `Scan dispatched to ${res.repo}@${res.ref} — watch the scans table`);
      }
      scanRef = '';
    } catch (e) {
      pushToast('error', `${(e as Error).message ?? e}`);
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

<div class="p-6">
  <div class="mb-5">
    <div class="text-[15px] text-ink-primary mb-1">Scans</div>
    <div class="text-[12px] text-ink-secondary">
      Every scan of this project, newest first — select a row for its findings, FRs and compliance.
    </div>
  </div>
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
    <div class="flex flex-wrap justify-between items-center gap-3 mb-3">
      <div class="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-muted">
        <label for="scan-origin-filter">Origin</label>
        <select
          id="scan-origin-filter"
          value={originFilter}
          on:change={(event) => setOriginFilter(event.currentTarget.value as ScanOriginFilter)}
          class="rounded-sm border border-line-hairline bg-surface-inset px-2 py-1.5 font-mono text-[11px] normal-case tracking-normal text-ink-primary"
        >
          <option value="all">All</option>
          <option value="local">Local</option>
          <option value="github-actions">GitHub Actions</option>
        </select>
        <span aria-live="polite" class="normal-case tracking-normal">{projectScans.length} shown</span>
      </div>
      <div class="flex flex-wrap justify-end items-center gap-2">
      <button
        type="button"
        on:click={confirmScan}
        disabled={dispatching || !projectRepo}
        title="Scan now — dispatches this repo's own assurance-scan workflow (stub required)"
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
    </div>
    {#if loading}
      <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
    {:else if error}
      <div class="text-[12px] text-state-failed font-mono">{error}</div>
    {:else if scans.length === 0}
      <div class="py-10 text-center text-[12px] text-ink-muted font-mono">
        No scans for this project yet.
      </div>
    {:else if projectScans.length === 0}
      <div class="py-10 text-center text-[12px] text-ink-muted font-mono">
        No {originFilter === 'local' ? 'local' : 'GitHub Actions'} scans match this origin filter.
      </div>
    {:else}
      <div class="border border-line-hairline rounded-sm overflow-x-auto bg-surface-panel mb-5">
        <div class="grid min-w-[1120px] grid-cols-[26px_minmax(180px,1.6fr)_120px_120px_150px_1.2fr_80px_100px_70px_70px] gap-4 px-4 py-2 bg-surface-inset border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted items-center">
          <div></div>
          <div>Run</div>
          <div>Origin</div>
          <div>Branch</div>
          <div>Commit</div>
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
            class="w-full min-w-[1120px] text-left grid grid-cols-[26px_minmax(180px,1.6fr)_120px_120px_150px_1.2fr_80px_100px_70px_70px] gap-4 px-4 py-2 border-b border-line-hairline last:border-0 transition-colors hover:bg-surface-elevated font-mono text-[12px] items-center cursor-pointer"
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
              {scanRunLabel(s)}
            </span>
            <ScanOriginBadge origin={s.origin} />
            <span class="font-mono text-[11px] text-ink-secondary truncate" title={s.git_branch ?? ''}>{s.git_branch ?? '—'}</span>
            <span class="flex min-w-0 flex-col items-start gap-1">
              <span class="flex max-w-full items-center gap-1.5">
                <span class="truncate font-mono text-[11px] text-ink-secondary" title={s.commit_sha ?? 'Commit provenance unavailable'}>
                  {shortCommit(s.commit_sha)}
                </span>
                {#if s.working_tree_dirty === true}
                  <span
                    class="rounded-sm border border-state-pending/40 px-1 py-0.5 text-[8px] uppercase tracking-[0.08em] text-state-pending"
                    title="Dirty working tree — this scan includes uncommitted or untracked local files"
                    aria-label="Dirty working tree: scan includes uncommitted or untracked local files"
                  >Dirty</span>
                {/if}
              </span>
              {#if sameCommitComparison(scans, s)}
                <button
                  type="button"
                  on:click|stopPropagation={() => openComparison(s)}
                  class="text-left font-mono text-[9px] text-accent hover:text-accent-hover"
                  aria-label={`Compare ${s.run_id} with the ${s.origin === 'local' ? 'GitHub Actions' : 'local'} scan of commit ${shortCommit(s.commit_sha)}`}
                >Compare origins</button>
              {/if}
            </span>
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

      {#if comparison}
        <ScanCommitComparison
          {comparison}
          onOpen={openComparedRun}
          onClose={() => (comparisonRunId = '')}
        />
      {/if}

      {#if selectedRunId}
        <div class="border border-line-hairline rounded-sm overflow-hidden">
          <ScanDetail runId={selectedRunId} />
        </div>
      {/if}
    {/if}
  </div>

  {#if scanConfirmOpen}
    <div class="fixed inset-0 z-50 flex items-center justify-center p-6">
      <button type="button" class="absolute inset-0 bg-black/65 backdrop-blur-[2px]" on:click={() => (scanConfirmOpen = false)} aria-label="Close"></button>
      <div class="relative border border-line-strong rounded-sm bg-surface-panel max-w-md w-full p-5">
        <div class="text-[13px] text-ink-primary mb-3 font-mono">Start scan?</div>
        <div class="space-y-3 mb-4">
          <div>
            <label class="block text-[11px] font-mono text-ink-secondary mb-1" for="scan-repo">Repository</label>
            <div id="scan-repo" class="w-full px-2 py-1 border border-line-hairline rounded-sm bg-surface-inset font-mono text-[11px] text-ink-secondary">
              {projectRepo}
            </div>
          </div>
          <div>
            <label class="block text-[11px] font-mono text-ink-secondary mb-1" for="scan-branch">Branch (defaults to the project's preference or repo default)</label>
            {#if scanBranchError}
              <p class="text-[10px] font-mono mb-1" style="color: var(--state-failed);">couldn't load branches — type a branch or SHA below</p>
            {/if}
            {#if scanBranches.length > 0}
              <select
                id="scan-branch"
                bind:value={scanRef}
                class="w-full px-2 py-1 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary"
              >
                <option value="">(repo default)</option>
                {#each scanBranches as b (b)}
                  <option value={b}>{b}</option>
                {/each}
              </select>
            {:else}
              <input
                id="scan-branch"
                type="text"
                bind:value={scanRef}
                placeholder="branch/sha (default)"
                class="w-full px-2 py-1 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary"
              />
            {/if}
          </div>
        </div>
        <p class="text-[12px] text-ink-secondary leading-relaxed mb-5">
          This dispatches the <code>assurance-scan</code> workflow on the repo's own
          GitHub Actions — you can follow it live on the repo's Actions page. Results
          appear here automatically within a minute, or immediately via the
          <em>Retrieve from GitHub</em> button.
        </p>
        <div class="flex justify-end gap-2">
          <button type="button" on:click={() => (scanConfirmOpen = false)}
            class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary">Cancel</button>
          <button type="button" on:click={scanNow}
            class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary">Start scan</button>
        </div>
      </div>
    </div>
  {/if}

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
