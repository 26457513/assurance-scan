<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { selectedScan } from '$lib/stores/selectedScan';
  import { api } from '$lib/api';

  onMount(async () => {
    let runId = $selectedScan?.run_id;
    if (!runId) {
      try {
        const scans = await api.listScansForSelector();
        if (scans.length > 0) runId = scans[0].run_id;
      } catch (e) {
        /* silent */
      }
    }
    if (runId) {
      goto(`/scans/${runId}?run_id=${runId}&tab=frs`, { replaceState: true });
    } else {
      goto('/scans', { replaceState: true });
    }
  });
</script>

<div class="p-6 text-[12px] text-ink-muted font-mono">Redirecting…</div>
