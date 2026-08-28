<script lang="ts">
  import '../app.css';
  import { onMount, onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import Sidebar from '$lib/components/Sidebar.svelte';
  import Header from '$lib/components/Header.svelte';
  import Toaster from '$lib/components/Toaster.svelte';
  import { selectedScan, selectScan } from '$lib/stores/selectedScan';
  import { pushToast } from '$lib/stores/toasts';
  import { api } from '$lib/api';

  let bootstrapped = false;
  let lastUrlRunId: string | null = null;

  async function syncFromUrl(runId: string | null) {
    if (!runId) return;
    if ($selectedScan?.run_id === runId) return;
    try {
      const status = await api.getScan(runId);
      selectScan({
        run_id: status.run_id,
        project_id: status.project_id,
        origin: status.origin,
        status: status.status,
        started_at: status.started_at,
        completed_at: status.completed_at,
        finding_count: $selectedScan?.finding_count ?? 0
      });
    } catch (e) {
      /* stale URL run_id — ignore */
    }
  }

  async function autoSelectLatest() {
    if ($selectedScan) return;
    try {
      const scans = await api.listScansForSelector();
      if (scans.length > 0) {
        const scan = scans[0];
        selectScan(scan);
        const url = new URL(window.location.href);
        url.searchParams.set('run_id', scan.run_id);
        goto(`${url.pathname}?${url.searchParams.toString()}`, { replaceState: true, noScroll: true });
        pushToast('info', `Auto-selected latest scan: ${scan.run_id.slice(-8)}`);
      }
    } catch (e) {
      /* silent */
    }
  }

  onMount(async () => {
    const initialRunId = $page.url.searchParams.get('run_id');
    lastUrlRunId = initialRunId;
    if (initialRunId) {
      await syncFromUrl(initialRunId);
    } else {
      await autoSelectLatest();
    }
    bootstrapped = true;
  });

  onDestroy(() => {
    bootstrapped = false;
  });

  // React to URL changes (back/forward, dropdown picks, deep links)
  $: currentUrlRunId = $page.url.searchParams.get('run_id');
  $: if (bootstrapped && currentUrlRunId !== lastUrlRunId) {
    lastUrlRunId = currentUrlRunId;
    syncFromUrl(currentUrlRunId);
  }
</script>

<div
  class="grid h-screen overflow-hidden bg-surface-base"
  style="grid-template-columns: 220px 1fr; grid-template-rows: 56px 1fr;"
>
  <div class="col-start-1 col-end-2 row-start-1 row-end-3 min-h-0">
    <Sidebar />
  </div>
  <div class="col-start-2 col-end-3 row-start-1 row-end-2 min-w-0">
    <Header />
  </div>
  <main class="col-start-2 col-end-3 row-start-2 row-end-3 overflow-auto min-w-0">
    <slot />
  </main>
</div>

<Toaster />
