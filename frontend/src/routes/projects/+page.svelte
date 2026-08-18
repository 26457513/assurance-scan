<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { selectProject, projectSlug } from '$lib/stores/selectedProject';
  import type { ProjectSummary } from '$lib/types';

  let projects: ProjectSummary[] = [];
  let loading = true;
  let error: string | null = null;

  const PAGE_SIZE = 5;
  let page = 0;

  $: pageCount = Math.max(1, Math.ceil(projects.length / PAGE_SIZE));
  $: visible = projects.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function open(p: ProjectSummary) {
    selectProject(p.project_path);
    goto(`/projects/${projectSlug(p.project_path)}`);
  }

  onMount(async () => {
    try {
      const [data, gh] = await Promise.all([
        api.listProjects(),
        api.githubRepos().catch(() => ({ repos: [] }))
      ]);
      projects = data.projects;
      // Org repos with no scans yet still belong in the list; ones already
      // scanned arrive via the projects API as github:{full_name}.
      const known = new Set(
        projects.flatMap((p) => [p.project_path, p.github_project].filter(Boolean) as string[])
      );
      const unscanned = gh.repos
        .filter((r) => !known.has(`github:${r.full_name}`))
        .map((r) => ({
          project_path: `github:${r.full_name}`,
          run_count: 0,
          last_scan_at: r.pushed_at ?? null,
          has_catalogue: false
        }));
      projects = [...projects, ...unscanned];
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  });

  function fmtDate(iso: string | null): string {
    if (!iso) return '—';
    const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    return m ? `${m[2]}/${m[3]} ${m[4]}:${m[5]}` : iso;
  }
</script>

<div class="p-6 max-w-6xl">
  <div class="mb-4">
    <div class="text-[15px] text-ink-primary mb-1">Projects</div>
    <div class="text-[12px] text-ink-secondary">
      Local scanned folders and the org's GitHub repos — select one to browse its scans,
      requirements, and compliance.
    </div>
  </div>

  {#if loading}
    <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else if error}
    <div class="text-[12px] text-state-failed font-mono">{error}</div>
  {:else if projects.length === 0}
    <div class="py-12 text-center text-[12px] text-ink-muted font-mono">
      No projects yet — start a scan from any project folder.
    </div>
  {:else}
    <div class="border border-line-hairline rounded-sm overflow-hidden bg-surface-panel">
      <div class="grid grid-cols-[minmax(0,2fr)_80px_130px_110px] gap-3 px-4 py-2 bg-surface-inset border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted">
        <div>Path</div>
        <div class="text-right">Runs</div>
        <div>Last scan</div>
        <div>Catalogue</div>
      </div>
      {#each visible as p (p.project_path)}
        <button
          type="button"
          on:click={() => open(p)}
          class="w-full text-left grid grid-cols-[minmax(0,2fr)_80px_130px_110px] gap-3 px-4 py-2 border-b border-line-hairline last:border-0 transition-colors hover:bg-surface-elevated font-mono text-[12px]"
        >
          <span class="text-ink-primary truncate flex items-center gap-2">
            {p.project_path}
            {#if p.github_project}
              <span class="text-[10px] text-ink-muted border border-line-hairline rounded-sm px-1.5 py-0.5" title={p.github_project}>repo</span>
            {/if}
          </span>
          <span class="text-right text-ink-secondary tabular-nums">{p.run_count}</span>
          <span class="text-ink-muted">{fmtDate(p.last_scan_at)}</span>
          <span class={p.has_catalogue ? 'text-state-passed' : 'text-ink-muted'}>
            {p.has_catalogue ? 'yes' : 'none'}
          </span>
        </button>
      {/each}
    </div>

    {#if pageCount > 1}
      <div class="flex items-center gap-2 mt-4 font-mono text-[11px]">
        <button
          type="button"
          on:click={() => (page = Math.max(0, page - 1))}
          disabled={page === 0}
          class="px-2 py-0.5 border border-line-hairline rounded-sm text-ink-secondary disabled:opacity-40"
        >‹ prev</button>
        <span class="text-ink-muted">page {page + 1} / {pageCount}</span>
        <button
          type="button"
          on:click={() => (page = Math.min(pageCount - 1, page + 1))}
          disabled={page >= pageCount - 1}
          class="px-2 py-0.5 border border-line-hairline rounded-sm text-ink-secondary disabled:opacity-40"
        >next ›</button>
      </div>
    {/if}
  {/if}
</div>
