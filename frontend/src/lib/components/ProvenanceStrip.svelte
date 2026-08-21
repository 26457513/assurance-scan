<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { CatalogueDriftResponse, ScanProvenance } from '$lib/types';

  export let provenance: ScanProvenance;
  export let projectPath: string;

  const short = (hash: string | null | undefined) => (hash ? `${hash.slice(0, 8)}…` : null);

  let drift: CatalogueDriftResponse | null = null;
  let copied = false;

  $: cat = provenance.catalogue;
  $: cur = provenance.current_catalogue;
  $: catStale = provenance.catalogue_stale === true;
  $: mapStale = provenance.mapping_stale === true;
  $: codeMoved = drift?.code_moved === true;
  $: driftedCount = drift?.drifted_fr_ids.length ?? 0;
  $: driftTitle =
    [
      ...(drift?.missing_files ?? []).map((m) => `${m.fr_id}: ${m.ref}`),
      ...(drift?.unresolved_patterns ?? []).map(
        (u) => `${u.fr_id}/${u.test_id}: ${u.name_pattern}`
      )
    ].join('\n') || 'no drift';

  onMount(async () => {
    try {
      drift = await api.getCatalogueDrift(projectPath);
    } catch {
      drift = null;
    }
  });

  async function copyRegenerate() {
    const cmd = `Run the author-fr-catalogue workflow from the assurance-scan MCP server. Use project_path="${projectPath}".`;
    try {
      await navigator.clipboard.writeText(cmd);
      copied = true;
      setTimeout(() => (copied = false), 2000);
    } catch {
      window.prompt('Copy this into your agent session:', cmd);
    }
  }
</script>

<div class="px-6 py-2 border-b border-line-hairline flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] font-mono text-ink-muted">
  <span>
    catalogue:
    {#if cat}
      v{cat.version ?? '?'} <span class="opacity-60">{short(cat.content_hash)}</span>
    {:else}
      <span class="opacity-60">none pinned</span>
    {/if}
  </span>

  <span>
    mapping:
    {#if provenance.mapping_hash}
      <span class="opacity-60">{short(provenance.mapping_hash)}</span>
    {:else}
      <span class="opacity-60">none</span>
    {/if}
  </span>

  {#if drift}
    <span>
      code:
      {#if drift.snapshot_commit && drift.current_commit}
        <span class="opacity-60">{short(drift.snapshot_commit)} → {short(drift.current_commit)}</span>
      {:else if drift.current_commit}
        <span class="opacity-60" title="snapshot predates commit pinning">unknown → {short(drift.current_commit)}</span>
      {:else}
        <span class="opacity-60">not a git repo</span>
      {/if}
    </span>
  {/if}

  {#if catStale}
    <span class="px-1.5 py-0.5 border border-state-pending text-state-pending uppercase tracking-[0.1em]" title={`run used v${cat?.version ?? '?'}; current is v${cur?.version ?? '?'}`}>
      stale — re-scan
    </span>
    {#if cur}
      <span>current: v{cur.version ?? '?'} <span class="opacity-60">{short(cur.content_hash)}</span></span>
    {/if}
  {/if}

  {#if mapStale}
    <span class="px-1.5 py-0.5 border border-state-pending text-state-pending uppercase tracking-[0.1em]">
      mapping changed — re-scan
    </span>
  {/if}

  {#if codeMoved && !catStale}
    <span class="px-1.5 py-0.5 border border-state-pending text-state-pending uppercase tracking-[0.1em]" title="codebase commit differs from the commit the catalogue was generated against">
      code moved
    </span>
  {/if}

  {#if driftedCount > 0}
    <span class="px-1.5 py-0.5 border border-state-failed text-state-failed uppercase tracking-[0.1em]" title={driftTitle}>
      drift: {driftedCount} FR{driftedCount === 1 ? '' : 's'}
    </span>
  {/if}

  {#if driftedCount > 0 || codeMoved}
    <button
      type="button"
      on:click={copyRegenerate}
      class="px-2 py-0.5 border border-accent text-accent uppercase tracking-[0.1em] hover:bg-accent-subtle transition-colors"
      title="Copies the agent command that regenerates the catalogue via the assurance-scan MCP workflow"
    >
      {copied ? 'copied ✓' : 'regenerate catalogue'}
    </button>
  {/if}
</div>
