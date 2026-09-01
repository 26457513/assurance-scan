<script lang="ts">
  import { api } from '$lib/api';
  import { createRequestGate } from '$lib/requestGate';
  import { selectedProject } from '$lib/stores/selectedProject';
  import { selectCatalogue, selectedCatalogue } from '$lib/stores/selectedCatalogue';
  import type { CatalogueVersion } from '$lib/types';

  let open = false;
  let versions: CatalogueVersion[] = [];
  const versionsGate = createRequestGate<number | null>();

  $: void loadVersions($selectedProject);

  async function loadVersions(projectId: number | null) {
    const ticket = versionsGate.begin(projectId);
    if (!ticket) return;
    selectCatalogue(null);
    if (projectId == null) {
      versions = [];
      return;
    }
    try {
      const data = await api.listCatalogueVersions(projectId);
      if (!versionsGate.isCurrent(ticket)) return;
      versions = data.versions;
      if (versions.length) {
        const v = versions[0];
        selectCatalogue({ snapshot_id: v.snapshot_id, version: v.version ?? null, tag: v.tag ?? null, fr_count: v.fr_count });
      }
    } catch {
      if (versionsGate.isCurrent(ticket)) versions = [];
    }
  }

  function pick(v: CatalogueVersion) {
    open = false;
    selectCatalogue({ snapshot_id: v.snapshot_id, version: v.version ?? null, tag: v.tag ?? null, fr_count: v.fr_count });
  }

  function shortLabel(v: { version?: string | null }): string {
    return v.version ?? '(unversioned)';
  }
</script>

<div class="relative">
  <button
    type="button"
    on:click={() => (open = !open)}
    disabled={!versions.length}
    class="flex items-center gap-2 px-2.5 py-1.5 rounded-sm border border-line-hairline hover:border-line-strong hover:bg-surface-elevated transition-colors disabled:opacity-50"
    title={$selectedCatalogue ? `FR catalogue ${$selectedCatalogue.version ?? ''}` : 'no FR catalogue for this project'}
  >
    <span class="font-mono text-[12px] text-ink-primary">
      {#if $selectedCatalogue}{$selectedCatalogue.tag ?? shortLabel($selectedCatalogue)} · {$selectedCatalogue.fr_count} FRs{:else}no catalogue{/if}
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
      class="absolute top-full left-0 mt-1 w-[460px] max-w-[calc(100vw-2rem)] max-h-[380px] bg-surface-panel border border-line-strong rounded-md overflow-hidden z-50 flex flex-col"
      style="box-shadow: 0 12px 32px rgba(0,0,0,0.4);"
    >
      <div class="px-3 py-2 border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted">
        FR catalogue versions
      </div>
      <div class="overflow-auto">
        {#each versions as v (v.snapshot_id)}
          <button
            type="button"
            on:click={() => pick(v)}
            class="w-full text-left px-3 py-2 hover:bg-surface-elevated transition-colors border-b border-line-hairline last:border-0 flex items-center justify-between gap-3"
            class:bg-accent-subtle={$selectedCatalogue?.snapshot_id === v.snapshot_id}
          >
            <div class="font-mono text-[12px] text-ink-primary truncate">{v.tag ?? shortLabel(v)}</div>
            <div class="text-[11px] text-ink-muted font-mono whitespace-nowrap">
              {v.fr_count} FRs · {shortLabel(v)}
            </div>
          </button>
        {:else}
          <div class="px-3 py-10 text-center text-[12px] text-ink-muted font-mono">
            no catalogues for this project
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>
