<script lang="ts">
  import { onMount } from 'svelte';
  import { pushToast } from '$lib/stores/toasts';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { loadCurrentUser } from '$lib/stores/currentUser';
  import { selectProject } from '$lib/stores/selectedProject';
  import type { ProjectSummary } from '$lib/types';

  let projects: ProjectSummary[] = [];
  let loading = true;
  let error: string | null = null;

  const PAGE_SIZE = 5;
  let page = 0;

  let editOpen = false;
  let editId: number | null = null;
  let selected = new Set<number>();
  let deleteModalOpen = false;
  $: selectedCount = selected.size;

  function toggleRow(projectId: number) {
    if (selected.has(projectId)) selected.delete(projectId);
    else selected.add(projectId);
    selected = new Set(selected);
  }

  async function confirmDelete() {
    const rows = projects.filter((p) => selected.has(p.id));
    for (const row of rows) {
      try {
        await api.deleteAllScans(row.id);
        await api.deleteProject(row.id);
      } catch (e) {
        pushToast('error', `Delete failed for ${row.tag}: ${e}`);
      }
    }
    selected = new Set();
    deleteModalOpen = false;
    pushToast('success', 'Projects deleted');
    loading = true;
    await load();
  }
  let editTag = '';
  let editPath = '';
  let editRepo = '';
  let editing = false;

  let editingProject: ProjectSummary | null = null;

  function openEdit(p: ProjectSummary) {
    editingProject = p;
    editId = p.id;
    editTag = p.tag;
    editPath = p.local_path ?? '';
    editRepo = p.github_repo ?? '';
    editOpen = true;
  }

  async function removeProject(p: ProjectSummary) {
    try {
      await api.deleteProject(p.id);
      pushToast('success', `Project "${p.tag}" removed`);
      editOpen = false;
      loading = true;
      await load();
    } catch (e) {
      pushToast('error', `Remove failed: ${e}`);
    }
  }

  async function saveEdit() {
    editing = true;
    try {
      if (editId != null) {
        await api.updateProject(editId, {
          tag: editTag.trim(),
          local_path: editPath.trim() || null,
          github_repo: editRepo.trim() || null
        });
      }
      pushToast('success', 'Project saved');
      editOpen = false;
      loading = true;
      await load();
    } catch (e) {
      pushToast('error', `Update failed: ${e}`);
    } finally {
      editing = false;
    }
  }

  $: pageCount = Math.max(1, Math.ceil(projects.length / PAGE_SIZE));
  $: visible = projects.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function open(p: ProjectSummary) {
    selectProject(p.id);
    goto(`/projects/${p.id}`);
  }

  async function load() {
    try {
      const data = await api.listProjects();
      projects = data.projects;
      loading = false;
    } catch (e) {
      error = String(e);
      loading = false;
    }
  }

  onMount(() => {
    void load();
    void loadCurrentUser();
  });

  function fmtDate(iso: string | null): string {
    if (!iso) return '—';
    const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    return m ? `${m[2]}/${m[3]} ${m[4]}:${m[5]}` : iso;
  }
</script>

<div class="p-6 max-w-6xl">
  <div class="flex items-start justify-between mb-4">
    <div>
      <div class="text-[15px] text-ink-primary mb-1">Projects</div>
      <div class="text-[12px] text-ink-secondary">
        Registered projects — select one to browse its scans and trends.
      </div>
    </div>
    <div class="flex items-center gap-2">
      {#if selectedCount > 0}
        <button
          type="button"
          on:click={() => (deleteModalOpen = true)}
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-sm border font-mono text-[11px] uppercase tracking-[0.1em] transition-colors"
          style="color: var(--state-failed); border-color: color-mix(in srgb, var(--state-failed) 35%, transparent); background: color-mix(in srgb, var(--state-failed) 8%, transparent);"
        >Delete {selectedCount} selected</button>
      {/if}
    </div>
  </div>

  {#if loading}
    <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else if error}
    <div class="text-[12px] text-state-failed font-mono">{error}</div>
  {:else if projects.length === 0}
    <div class="py-12 text-center text-[12px] text-ink-muted font-mono">
      No accessible projects. Install or update the GitHub App from Setup, or ask a repository administrator for access.
    </div>
  {:else}
    <div class="border border-line-hairline rounded-sm overflow-hidden bg-surface-panel">
      <div class="grid grid-cols-[26px_110px_minmax(0,1.6fr)_minmax(0,1fr)_70px_110px_32px] gap-3 px-4 py-2 bg-surface-inset border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted items-center">
        <div></div>
        <div>Project</div>
        <div>Local path</div>
        <div>GitHub repo</div>
        <div class="text-right">Runs</div>
        <div>Last scan</div>
        <div></div>
      </div>
      {#each visible as p (p.id)}
        <div
          role="button"
          tabindex="0"
          on:click={() => open(p)}
          on:keydown={(e) => e.key === 'Enter' && open(p)}
          class="w-full text-left grid grid-cols-[26px_110px_minmax(0,1.6fr)_minmax(0,1fr)_70px_110px_32px] gap-3 px-4 py-2 border-b border-line-hairline last:border-0 transition-colors hover:bg-surface-elevated font-mono text-[12px] items-center cursor-pointer"
        >
          {#if p.can_manage}
            <input
              type="checkbox"
              checked={selected.has(p.id)}
              on:click|stopPropagation={() => toggleRow(p.id)}
              class="cursor-pointer"
              aria-label="Select {p.tag}"
            />
          {:else}<span></span>{/if}
          <span class="text-ink-primary truncate">
            {p.tag}
          </span>
          <span class="text-ink-secondary truncate" title={p.local_path ?? ''}>{p.local_path ?? '—'}</span>
          <span class="text-ink-muted truncate" title={p.github_repo ?? ''}>
            {p.github_repo ?? '—'}
          </span>
          <span class="text-right text-ink-secondary tabular-nums">{p.run_count}</span>
          <span class="text-ink-muted">{fmtDate(p.last_scan_at)}</span>
          {#if p.can_manage}
            <button
              type="button"
              on:click|stopPropagation={() => openEdit(p)}
              title="Edit project"
              class="text-ink-secondary hover:text-accent transition-colors p-1"
            >
              <svg class="h-3.5 w-3.5" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.4">
                <path d="M10.2 2.2l1.6 1.6L4.4 11.2l-2 .4.4-2 7.4-7.4z" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          {:else}<span></span>{/if}
        </div>
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

  {#if deleteModalOpen}
    <div class="fixed inset-0 z-50 flex items-center justify-center p-6">
      <button type="button" class="absolute inset-0 bg-black/65 backdrop-blur-[2px]" on:click={() => (deleteModalOpen = false)} aria-label="Close"></button>
      <div class="relative border border-line-strong rounded-sm bg-surface-panel max-w-md w-full p-5">
        <div class="text-[13px] text-ink-primary mb-2 font-mono">Delete {selectedCount} project{selectedCount === 1 ? '' : 's'}?</div>
        <p class="text-[12px] text-ink-secondary leading-relaxed mb-5">
          This removes the project registration and <strong>all of its data from assurance-scan</strong> —
          scans, FR catalogue, mappings, waivers, and acceptances. Nothing is deleted from GitHub:
          CI scans return on the next <em>Retrieve from GitHub</em>, but local scans and the catalogue
          are gone for good.
        </p>
        <div class="flex justify-end gap-2">
          <button type="button" on:click={() => (deleteModalOpen = false)}
            class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary">Cancel</button>
          <button type="button" on:click={confirmDelete}
            class="px-3 py-1.5 rounded-sm text-[11px] font-mono uppercase tracking-[0.1em]"
            style="color: var(--state-failed); border: 1px solid color-mix(in srgb, var(--state-failed) 35%, transparent); background: color-mix(in srgb, var(--state-failed) 8%, transparent);">Delete</button>
        </div>
      </div>
    </div>
  {/if}

  {#if editOpen}
    <div class="fixed inset-0 z-50 flex items-center justify-center p-6">
      <button type="button" class="absolute inset-0 bg-black/65 backdrop-blur-[2px]" on:click={() => (editOpen = false)} aria-label="Close"></button>
      <div class="relative border border-line-strong rounded-sm bg-surface-panel max-w-md w-full p-5">
        <div class="text-[13px] text-ink-primary mb-4 font-mono">Edit project</div>
        <div class="space-y-3 mb-5">
          <div>
            <label class="block text-[11px] font-mono text-ink-secondary mb-1" for="ep-tag">Tag</label>
            <input id="ep-tag" type="text" bind:value={editTag}
              class="w-full px-2 py-1 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary" />
          </div>
          <div>
            <label class="block text-[11px] font-mono text-ink-secondary mb-1" for="ep-path">Local path / anchor</label>
            <input id="ep-path" type="text" bind:value={editPath}
              class="w-full px-2 py-1 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary" />
          </div>
          <div>
            <label class="block text-[11px] font-mono text-ink-secondary mb-1" for="ep-repo">GitHub repository (empty clears)</label>
            <input id="ep-repo" type="text" bind:value={editRepo} placeholder="org/project"
              class="w-full px-2 py-1 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary" />
          </div>
        </div>
        <div class="flex justify-between items-center gap-2">
          <button
            type="button"
            on:click={() => editingProject && removeProject(editingProject)}
            class="px-3 py-1.5 rounded-sm border text-[11px] font-mono uppercase tracking-[0.1em] transition-colors"
            style="color: var(--state-failed); border-color: color-mix(in srgb, var(--state-failed) 35%, transparent);"
            title="Removes the project registration from assurance-scan only — nothing is deleted from GitHub"
          >Remove project</button>
          <div class="flex gap-2">
            <button type="button" on:click={() => (editOpen = false)}
              class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary">Cancel</button>
            <button type="button" on:click={saveEdit} disabled={editing || !editTag.trim() || (!editPath.trim() && !editRepo.trim())}
              class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary disabled:opacity-50">{editing ? 'Saving…' : 'Save'}</button>
          </div>
        </div>
      </div>
    </div>
  {/if}

</div>
