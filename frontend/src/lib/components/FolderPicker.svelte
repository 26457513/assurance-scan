<script lang="ts">
  import { onMount, createEventDispatcher } from 'svelte';
  import { api } from '$lib/api';
  import type { FoldersResponse } from '$lib/types';

  const dispatch = createEventDispatcher<{
    select: string;
    cancel: void;
  }>();

  export let initialPath: string | null = null;

  let current: FoldersResponse | null = null;
  let loading = true;
  let error: string | null = null;

  // Path segments derived from `current.path` for the breadcrumb.
  $: segments = current ? buildSegments(current.path, current.root) : [];
  $: atRoot = current ? !current.can_go_up : false;

  function buildSegments(pathStr: string, rootStr: string): { label: string; path: string; clickable: boolean }[] {
    // Show the root as "~/Development" (last segment of the root) so the
    // breadcrumb is short, then every segment under it.
    const root = rootStr.replace(/\/$/, '');
    const rootName = root.split('/').filter(Boolean).pop() ?? root;
    const segs: { label: string; path: string; clickable: boolean }[] = [
      { label: `~/${rootName}`, path: root, clickable: true },
    ];
    if (pathStr === root) return segs;

    const rel = pathStr.slice(root.length).replace(/^\/+/, '');
    if (!rel) return segs;
    let acc = root;
    for (const part of rel.split('/').filter(Boolean)) {
      acc = `${acc}/${part}`;
      segs.push({ label: part, path: acc, clickable: true });
    }
    return segs;
  }

  async function load(target?: string) {
    loading = true;
    error = null;
    try {
      current = await api.listFolders(target);
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function navigate(path: string) {
    load(path);
  }

  function goUp() {
    if (current?.can_go_up) {
      const parent = current.path.split('/').slice(0, -1).join('/') || '/';
      load(parent);
    }
  }

  function select() {
    if (current) dispatch('select', current.path);
  }

  onMount(() => {
    load(initialPath ?? undefined);
  });
</script>

<div class="border border-line-hairline rounded-sm bg-surface-inset">
  <!-- Breadcrumb -->
  <div class="flex items-center gap-1 px-3 py-2 border-b border-line-hairline bg-surface-panel">
    <button
      type="button"
      on:click={goUp}
      disabled={!current?.can_go_up}
      class="font-mono text-[11px] text-ink-muted hover:text-accent disabled:opacity-30 disabled:hover:text-ink-muted transition-colors px-1"
      title="Up one level"
    >
      <svg viewBox="0 0 12 12" class="h-3.5 w-3.5 inline-block" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M6 9.5V3M3 5.5l3-3 3 3" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>
    <div class="flex items-center gap-0.5 flex-wrap min-w-0">
      {#each segments as seg, i (seg.path)}
        {#if i > 0}
          <span class="text-ink-muted font-mono text-[11px] opacity-60">/</span>
        {/if}
        <button
          type="button"
          on:click={() => navigate(seg.path)}
          class="font-mono text-[11px] transition-colors truncate
            {i === segments.length - 1 ? 'text-ink-primary' : 'text-ink-secondary hover:text-accent'}"
          title={seg.path}
        >
          {seg.label}
        </button>
      {/each}
    </div>
  </div>

  <!-- Folder list -->
  <div class="max-h-72 overflow-y-auto">
    {#if loading}
      <div class="px-3 py-6 text-center font-mono text-[11px] text-ink-muted">Loading…</div>
    {:else if error}
      <div class="px-3 py-6 text-center font-mono text-[11px] text-state-failed">{error}</div>
    {:else if !current || current.folders.length === 0}
      <div class="px-3 py-6 text-center font-mono text-[11px] text-ink-muted">
        No subfolders here
        {#if atRoot}
          <div class="mt-1 text-[10px] text-ink-muted opacity-70">Hidden directories (.git, node_modules, etc.) are filtered out</div>
        {/if}
      </div>
    {:else}
      {#each current.folders as folder (folder.path)}
        <button
          type="button"
          on:click={() => navigate(folder.path)}
          on:dblclick={() => dispatch('select', folder.path)}
          class="w-full flex items-center gap-2 px-3 py-1.5 text-left transition-colors duration-100 hover:bg-surface-elevated border-b border-line-hairline last:border-0 group"
        >
          <svg viewBox="0 0 12 12" class="h-3.5 w-3.5 text-ink-muted group-hover:text-accent shrink-0 transition-colors" fill="none" stroke="currentColor" stroke-width="1.3">
            <path d="M1.5 3.5C1.5 3 1.7 2.8 2 2.8h2.5l1 1H10c.3 0 .5.2.5.5v5.4c0 .3-.2.5-.5.5H2c-.3 0-.5-.2-.5-.5V3.5z" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span class="font-mono text-[12px] text-ink-primary truncate flex-1">{folder.name}</span>
          <svg viewBox="0 0 12 12" class="h-3 w-3 text-ink-muted group-hover:text-accent shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M4 2.5l3.5 3.5L4 9.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      {/each}
    {/if}
  </div>
</div>

<div class="flex items-center justify-between gap-2 mt-3">
  <div class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted truncate">
    Selected: <span class="text-ink-secondary normal-case tracking-normal">{current?.path ?? '—'}</span>
  </div>
  <div class="flex items-center gap-2 shrink-0">
    <button
      type="button"
      on:click={() => dispatch('cancel')}
      class="font-mono text-[11px] uppercase tracking-[0.08em] px-3 py-1.5 rounded-sm border border-line-hairline text-ink-secondary hover:bg-surface-elevated transition-colors"
    >
      Cancel
    </button>
    <button
      type="button"
      on:click={select}
      disabled={!current || loading}
      class="font-mono text-[11px] uppercase tracking-[0.08em] px-3 py-1.5 rounded-sm border transition-colors disabled:opacity-40"
      style="color: var(--accent); border-color: color-mix(in srgb, var(--accent) 35%, transparent); background: color-mix(in srgb, var(--accent) 8%, transparent);"
    >
      Use this folder
    </button>
  </div>
</div>
