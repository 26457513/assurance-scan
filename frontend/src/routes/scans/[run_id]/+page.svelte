<script lang="ts">
  // Compatibility shim: old /scans/{id} links (CI comments posted before the
  // consolidation) resolve their project and land in the project scans view.
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { api } from '$lib/api';

  const runId = $page.params.run_id ?? '';

  onMount(async () => {
    try {
      // Resolve only scan evidence already accepted by Assurance Scan.
      const scan = await api.getScan(runId);
      goto(`/projects/${scan.project_id}?run=${runId}`, { replaceState: true });
    } catch {
      goto('/projects', { replaceState: true });
    }
  });
</script>

<div class="p-6 text-[12px] text-ink-muted font-mono">Resolving scan…</div>
