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
  import { createRequestGate } from '$lib/requestGate';
  import { selectedRunFromUrl, urlForSelectedRun } from '$lib/scanSelectionUrl';

  let bootstrapped = false;
  let lastUrlRunId: string | null = null;
  const syncGate = createRequestGate<string>();

  async function syncFromUrl(runId: string | null) {
    if (!runId) return;
    if ($selectedScan?.run_id === runId) return;
    const ticket = syncGate.begin(runId);
    if (!ticket) return;
    try {
      const status = await api.getScan(runId);
      if (!syncGate.isCurrent(ticket)) return;
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
        goto(urlForSelectedRun(url, scan.run_id), { replaceState: true, noScroll: true });
        pushToast('info', `Auto-selected latest scan: ${scan.run_id.slice(-8)}`);
      }
    } catch (e) {
      /* silent */
    }
  }

  onMount(async () => {
    const initialRunId = selectedRunFromUrl($page.url);
    lastUrlRunId = initialRunId;
    if (initialRunId) {
      await syncFromUrl(initialRunId);
    } else if (
      $page.url.pathname !== '/setup' &&
      !$page.url.pathname.match(/^\/projects\/[^/]+$/)
    ) {
      await autoSelectLatest();
    }
    bootstrapped = true;
  });

  onDestroy(() => {
    bootstrapped = false;
  });

  // React to URL changes (back/forward, dropdown picks, deep links)
  $: currentUrlRunId = selectedRunFromUrl($page.url);
  $: if (bootstrapped && currentUrlRunId !== lastUrlRunId) {
    lastUrlRunId = currentUrlRunId;
    syncFromUrl(currentUrlRunId);
  }
</script>

<div
  class="app-shell grid h-screen overflow-hidden bg-surface-base"
>
  <div class="col-start-1 col-end-2 row-start-1 row-end-3 min-h-0">
    <Sidebar />
  </div>
  <div class="relative z-30 col-start-2 col-end-3 row-start-1 row-end-2 min-w-0 overflow-visible">
    <Header />
  </div>
  <main class="relative z-0 col-start-2 col-end-3 row-start-2 row-end-3 overflow-auto min-w-0">
    <slot />
  </main>
</div>

<Toaster />

<style>
  .app-shell {
    grid-template-columns: 220px minmax(0, 1fr);
    grid-template-rows: 56px minmax(0, 1fr);
  }

  @media (max-width: 640px) {
    .app-shell {
      grid-template-columns: 52px minmax(0, 1fr);
    }
  }
</style>
