<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { selectScan } from '$lib/stores/selectedScan';
  import ScanResultsView from '$lib/components/ScanResultsView.svelte';
  import CatalogueView from '$lib/components/CatalogueView.svelte';
  import ComplianceView from '$lib/components/ComplianceView.svelte';
  import FixView from '$lib/components/FixView.svelte';
  import EvidenceTreeView from '$lib/components/EvidenceTreeView.svelte';
  import ConfigView from '$lib/components/ConfigView.svelte';
  import type { ScanStatus, ScanSummary } from '$lib/types';

  const runId = $page.params.run_id ?? '';

  let scan: ScanSummary | null = null;
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

  $: {
    const raw = $page.url.searchParams.get('tab');
    activeTab = tabs.some((t) => t.id === raw) ? (raw as TabId) : 'results';
    const rawSub = $page.url.searchParams.get('sub');
    resultsSub = RESULTS_SUB_TABS.some((t) => t.id === rawSub) ? (rawSub as ResultsSubId) : 'scan';
  }

  async function loadScan() {
    try {
      const status: ScanStatus = await api.getScan(runId);
      scan = {
        run_id: status.run_id,
        project_path: status.project_path,
        status: status.status,
        started_at: status.started_at,
        completed_at: status.completed_at,
        finding_count: 0
      };
      selectScan(scan);
      const url = new URL(window.location.href);
      if (url.searchParams.get('run_id') !== runId) {
        url.searchParams.set('run_id', runId);
        goto(`${url.pathname}?${url.searchParams.toString()}`, { replaceState: true, noScroll: true });
      }
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    loadScan();
  });

  function switchTab(id: TabId) {
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
  </div>
</div>

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
              <ScanResultsView {scan} />
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
