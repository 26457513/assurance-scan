<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { selectScan } from '$lib/stores/selectedScan';
  import ScanResultsView from './ScanResultsView.svelte';
  import CatalogueView from './CatalogueView.svelte';
  import ComplianceView from './ComplianceView.svelte';
  import FixView from './FixView.svelte';
  import EvidenceTreeView from './EvidenceTreeView.svelte';
  import ConfigView from './ConfigView.svelte';
  import ProvenanceStrip from './ProvenanceStrip.svelte';
  import type { ScanStatus, ScanSummary } from '$lib/types';

  export let runId: string;

  let scan: ScanSummary | null = null;
  let status: ScanStatus | null = null;
  let loading = true;
  let error: string | null = null;

  const tabs = [
    { id: 'config', label: 'Config' },
    { id: 'results', label: 'Results' },
    { id: 'evidence', label: 'Evidence' },
    { id: 'fix', label: 'Fix' }
  ] as const;

  type TabId = (typeof tabs)[number]['id'];

  const RESULTS_SUB_TABS = [
    { id: 'scan', label: 'Scan' },
    { id: 'frs', label: 'FRs' },
    { id: 'compliance', label: 'Compliance' }
  ] as const;

  type ResultsSubId = (typeof RESULTS_SUB_TABS)[number]['id'];

  let activeTab: TabId = 'results';
  let resultsSub: ResultsSubId = 'scan';

  // URL tab state only on the standalone /scans/[id] page — embedded use
  // (project page) keeps local state so it doesn't fight the ?view= param.
  $: standalone = $page.url.pathname.startsWith('/scans/');
  $: if (standalone) {
    const raw = $page.url.searchParams.get('tab');
    activeTab = tabs.some((t) => t.id === raw) ? (raw as TabId) : 'results';
    const rawSub = $page.url.searchParams.get('sub');
    resultsSub = RESULTS_SUB_TABS.some((t) => t.id === rawSub) ? (rawSub as ResultsSubId) : 'scan';
  }

  async function loadScan() {
    try {
      const fetched: ScanStatus = await api.getScan(runId);
      status = fetched;
      scan = {
        run_id: fetched.run_id,
        project_path: fetched.project_path,
        status: fetched.status,
        started_at: fetched.started_at,
        completed_at: fetched.completed_at,
        finding_count: 0
      };
      selectScan(scan);
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  $: runUrl = typeof status?.options?.run_url === 'string' ? status.options.run_url : null;

  $: ghRepo = status?.project_path?.startsWith('github:')
    ? status.project_path.slice('github:'.length)
    : null;
  $: ghCommit = status?.commit_sha ?? null;

  onMount(() => {
    loadScan();
  });

  function switchTab(id: TabId) {
    activeTab = id;
    if (!standalone) return;
    const url = new URL(window.location.href);
    if (id === 'results') {
      url.searchParams.delete('tab');
    } else {
      url.searchParams.set('tab', id);
    }
    const qs = url.searchParams.toString();
    goto(`${url.pathname}${qs ? `?${qs}` : ''}`, { noScroll: true });
  }

  function switchResultsSub(id: ResultsSubId) {
    resultsSub = id;
    if (!standalone) return;
    const url = new URL(window.location.href);
    if (id === 'scan') {
      url.searchParams.delete('sub');
    } else {
      url.searchParams.set('sub', id);
    }
    const qs = url.searchParams.toString();
    goto(`${url.pathname}${qs ? `?${qs}` : ''}`, { noScroll: true });
  }
</script>

<div class="border-b border-line-hairline">
  <div class="px-6 pt-3 flex items-center gap-0.5 overflow-x-auto">
    {#each tabs as t (t.id)}
      <button
        type="button"
        on:click={() => switchTab(t.id)}
        class="relative px-3.5 py-2.5 text-[11px] font-mono uppercase tracking-[0.12em] transition-colors whitespace-nowrap"
        class:text-accent={activeTab === t.id}
        class:text-ink-muted={activeTab !== t.id}
        class:hover:text-ink-secondary={activeTab !== t.id}
      >
        {t.label}
        {#if activeTab === t.id}
          <span class="absolute left-0 right-0 -bottom-px h-[2px] bg-accent"></span>
        {/if}
      </button>
    {/each}
    <span class="flex-1"></span>
    {#if status?.git_branch}
      <span class="font-mono text-[11px] text-state-pending pr-2">
        {status.git_branch}{status.commit_sha ? ` @ ${status.commit_sha.slice(0, 8)}` : ''}
      </span>
    {/if}
    <span class="font-mono text-[11px] text-ink-muted pr-1">{runId}</span>
    {#if runUrl}
      <a
        href={runUrl}
        target="_blank"
        rel="noreferrer"
        title="Open the GitHub Actions run"
        class="ml-1 inline-flex items-center gap-1 font-mono text-[11px] text-ink-muted hover:text-accent pr-1 transition-colors"
      >GH<svg class="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4">
          <path d="M4 2h6v6M10 2L5.5 6.5M8 7v3H2V4h3" stroke-linecap="round" stroke-linejoin="round" />
        </svg></a>
    {/if}
  </div>
</div>

{#if status?.provenance}
  <ProvenanceStrip provenance={status.provenance} projectPath={status.project_path} />
{/if}

<div>
  {#if loading}
    <div class="p-6 text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else if error}
    <div class="p-6 text-[12px] text-state-failed font-mono">{error}</div>
  {:else if scan}
    {#key scan.run_id + activeTab + (activeTab === 'results' ? resultsSub : '')}
      {#if activeTab === 'config'}
        <ConfigView {scan} />
      {:else if activeTab === 'results'}
        <div>
          <div class="border-b border-line-hairline px-6 pt-2 pb-0 flex items-center gap-0.5">
            {#each RESULTS_SUB_TABS as st (st.id)}
              <button
                type="button"
                on:click={() => switchResultsSub(st.id)}
                class="relative px-3 py-1.5 text-[10px] font-mono uppercase tracking-[0.12em] transition-colors whitespace-nowrap"
                class:text-accent={resultsSub === st.id}
                class:text-ink-muted={resultsSub !== st.id}
                class:hover:text-ink-secondary={resultsSub !== st.id}
              >
                {st.label}
                {#if resultsSub === st.id}
                  <span class="absolute left-0 right-0 -bottom-px h-[1px] bg-accent"></span>
                {/if}
              </button>
            {/each}
          </div>
          <div class="p-6">
            {#if resultsSub === 'scan'}
              <ScanResultsView {scan} repo={ghRepo} commit={ghCommit} />
            {:else if resultsSub === 'frs'}
              <CatalogueView {scan} />
            {:else if resultsSub === 'compliance'}
              <ComplianceView {scan} />
            {/if}
          </div>
        </div>
      {:else if activeTab === 'evidence'}
        <div class="p-6">
          <EvidenceTreeView {scan} />
        </div>
      {:else if activeTab === 'fix'}
        <div class="p-6">
          <FixView {scan} />
        </div>
      {/if}
    {/key}
  {/if}
</div>
