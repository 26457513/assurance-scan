<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { selectedProject, selectProject, projectSlug } from '$lib/stores/selectedProject';
  import type { ProjectSummary } from '$lib/types';

  let open = false;
  let projects: ProjectSummary[] = [];

  onMount(async () => {
    try {
      const data = await api.listProjects();
      projects = data.projects;
      if (!$selectedProject && projects.length) selectProject(projects[0].project_path);
    } catch {
      /* silent */
    }
  });

  function toggle() {
    open = !open;
  }

  function pick(p: ProjectSummary) {
    open = false;
    selectProject(p.project_path);
    // If currently inside a project page, navigate to the newly selected
    // project (same view) so the URL follows the selection.
    const m = $page.url.pathname.match(/^\/projects\/(.+)$/);
    if (m && decodeURIComponent(m[1]) !== p.project_path) {
      const view = $page.url.searchParams.get('view') ?? 'scans';
      goto(`/projects/${projectSlug(p.project_path)}?view=${view}`, { noScroll: true });
    }
  }

  $: shortName = (path: string) => path.split('/').filter(Boolean).pop() ?? path;
  $: projectLabel = projects.find((p) => p.project_path === $selectedProject)?.tag ?? shortName($selectedProject ?? '');
</script>

<div class="relative">
  <button
    type="button"
    on:click={toggle}
    class="flex items-center gap-2 px-2.5 py-1.5 rounded-sm border border-line-hairline hover:border-line-strong hover:bg-surface-elevated transition-colors"
    title={$selectedProject ?? 'no project'}
  >
    <span class="font-mono text-[12px] text-ink-primary">
      {$selectedProject ? shortName($selectedProject) : 'no project'}
    </span>
    <svg class="h-3 w-3 text-ink-muted" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M3 4.5l3 3 3-3" stroke-linecap="round" />
    </svg>
  </button>

  {#if open}
    <button
      type="button"
      class="fixed inset-0 z-40 cursor-default"
      on:click={() => (open = false)}
      aria-label="Close dropdown"
    ></button>
    <div
      class="absolute top-full left-0 mt-1 w-[380px] max-h-[420px] bg-surface-panel border border-line-strong rounded-md overflow-hidden z-50 flex flex-col"
      style="box-shadow: 0 12px 32px rgba(0,0,0,0.4);"
    >
      <div class="px-3 py-2 border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted">
        Projects
      </div>
      <div class="overflow-auto">
        {#each projects as p (p.project_path)}
          <button
            type="button"
            on:click={() => pick(p)}
            class="w-full text-left px-3 py-2 hover:bg-surface-elevated transition-colors border-b border-line-hairline last:border-0 flex items-center justify-between gap-3"
            class:bg-accent-subtle={$selectedProject === p.project_path}
          >
            <div class="min-w-0 flex-1">
              <div class="font-mono text-[12px] text-ink-primary truncate">{p.tag ?? p.project_path}</div>
              <div class="text-[10px] text-ink-muted font-mono truncate">{p.project_path}</div>
              <div class="text-[11px] text-ink-muted font-mono">
                {p.run_count} runs{p.has_catalogue ? ' · catalogue' : ''}
              </div>
            </div>
          </button>
        {:else}
          <div class="px-3 py-10 text-center text-[12px] text-ink-muted font-mono">
            no projects — run a scan first
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>
