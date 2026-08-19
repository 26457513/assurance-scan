<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { selectedScan } from '$lib/stores/selectedScan';
  import { selectedProject, projectSlug } from '$lib/stores/selectedProject';
  import { api } from '$lib/api';

  onMount(async () => {
    let project = $selectedProject ?? $selectedScan?.project_path ?? null;
    if (!project) {
      try {
        const data = await api.listProjects();
        project = data.projects[0]?.project_path ?? null;
      } catch {
        /* fall through */
      }
    }
    if (project) {
      goto(`/projects/${projectSlug(project)}?view=compliance`, { replaceState: true });
    } else {
      goto('/projects', { replaceState: true });
    }
  });
</script>

<div class="p-6 text-[12px] text-ink-muted font-mono">Redirecting…</div>
