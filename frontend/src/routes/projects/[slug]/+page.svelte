<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { pushToast } from '$lib/stores/toasts';
  import { selectProject, slugToProject } from '$lib/stores/selectedProject';
  import ScanDetail from '$lib/components/ScanDetail.svelte';
  import CatalogueView from '$lib/components/CatalogueView.svelte';
  import ComplianceView from '$lib/components/ComplianceView.svelte';
  import type { ScanSummary } from '$lib/types';

  $: projectPath = slugToProject($page.params.slug ?? '');
  $: view = $page.url.searchParams.get('view') ?? 'scans';

  const VIEWS = [
    { id: 'scans', label: 'Scans' },
    { id: 'frs', label: 'Functional Requirements' },
    { id: 'compliance', label: 'Compliance' }
  ] as const;

  let scans: ScanSummary[] = [];
  let selectedRunId = '';
  let loading = true;
  let error: string | null = null;
  let polling = false;

  const PAGE_SIZE = 5;
  let pg = 0;

  $: projectScans = scans; // already filtered by project on load
  $: pageCount = Math.max(1, Math.ceil(projectScans.length / PAGE_SIZE));
  $: visible = projectScans.slice(pg * PAGE_SIZE, (pg + 1) * PAGE_SIZE);

  // Catalogue/Compliance views only need project_path; a stub scan suffices
  // when no scan is selected.
  $: stubScan = {
    run_id: '',
    project_path: projectPath,
    status: '',
    started_at: '',
    completed_at: null,
    finding_count: 0
  };

  async function loadScans() {
    try {
      const all = await api.listScans(200);
      scans = all.filter((s) => s.project_path === projectPath);
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
    <div class="flex justify-end mb-3">
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
        <span class="text-[11px] font-mono uppercase tracking-[0.1em]">{polling ? 'Polling…' : 'From GitHub'}</span>
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
        <div class="grid grid-cols-[minmax(0,2fr)_1fr_1.3fr_80px_100px_70px_70px] gap-4 px-4 py-2 bg-surface-inset border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted items-center">
          <div>Run</div>
          <div>Branch</div>
          <div>Trigger</div>
          <div>Status</div>
          <div>Started</div>
          <div>Duration</div>
          <div class="text-right">Findings</div>
        </div>
        {#each visible as s (s.run_id)}
          <button
            type="button"
            on:click={() => pickScan(s.run_id)}
            class="w-full text-left grid grid-cols-[minmax(0,2fr)_1fr_1.3fr_80px_100px_70px_70px] gap-4 px-4 py-2 border-b border-line-hairline last:border-0 transition-colors hover:bg-surface-elevated font-mono text-[12px]"
            class:bg-accent-subtle={selectedRunId === s.run_id}
          >
            <span class="text-ink-primary truncate" title={s.run_id}>
              {#if s.run_number != null}#{s.run_number} · {s.display_title || s.run_id}{:else}{s.run_id}{/if}
            </span>
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
          </button>
        {/each}
      </div>

      {#if pageCount > 1}
        <div class="flex items-center gap-2 mb-4 font-mono text-[11px]">
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

      {#if selectedRunId}
        <div class="border border-line-hairline rounded-sm overflow-hidden">
          <ScanDetail runId={selectedRunId} />
        </div>
      {/if}
    {/if}
  </div>
{:else if view === 'frs'}
  <div class="p-6">
    <CatalogueView scan={stubScan} />
  </div>
{:else if view === 'compliance'}
  <div class="p-6">
    <ComplianceView scan={stubScan} />
  </div>
{/if}
