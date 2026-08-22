<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { mcpPrompt } from '$lib/agentPrompts';
  import CopyButton from './CopyButton.svelte';
  import StatePill from './StatePill.svelte';
  import TestCard from './TestCard.svelte';
  import type {
    FrListResponse,
    FrDetailResponse,
    ComplianceMatrixResponse,
    ScanSummary
  } from '$lib/types';

  export let scan: ScanSummary;
  $: mappingPrompt = mcpPrompt([
    { tool: 'get_workflow', args: { name: 'author-fr-compliance-map', parameters: JSON.stringify({ framework: 'ASVS' }) } },
    { tool: 'save_mapping', args: { project_path: scan.project_path } },
  ]);

  let groupBy: 'fr' | 'asvs' = 'fr';
  let frList: FrListResponse | null = null;
  let frDetails: Record<string, FrDetailResponse> = {};
  let complianceMatrix: ComplianceMatrixResponse | null = null;
  let loading = true;
  let error: string | null = null;

  // Per-node expansion state, keyed by a path string
  let expanded: Record<string, boolean> = {};

  function toggle(key: string) {
    expanded = { ...expanded, [key]: !expanded[key] };
  }

  async function load() {
    try {
      frList = await api.listFRs(scan.project_path);
      const details = await Promise.all(
        frList.frs.map((fr) => api.getFr(fr.fr_id, scan.run_id).catch(() => null))
      );
      frDetails = {};
      details.forEach((d, i) => {
        if (d && frList) frDetails[frList.frs[i].fr_id] = d;
      });
      try {
        complianceMatrix = await api.getComplianceMatrix('ASVS', scan.project_path);
      } catch (e) {
        complianceMatrix = null;
      }
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(load);

  $: frsSorted = frList
    ? [...frList.frs].sort((a, b) => a.fr_id.localeCompare(b.fr_id))
    : [];

  // For ASVS grouping — each row references FRs by id
  $: asvsGrouped = (() => {
    if (!complianceMatrix || !frList) return [];
    return complianceMatrix.rows.map((row) => ({
      row,
      frs: row.fr_ids
        .map((fid) => frList!.frs.find((f) => f.fr_id === fid))
        .filter((f): f is NonNullable<typeof f> => f !== undefined)
    }));
  })();

  const CONFIDENCE_COLORS: Record<string, string> = {
    high: 'var(--state-passed)',
    medium: 'var(--state-pending)',
    low: 'var(--state-untested)'
  };
</script>

<div class="p-6 max-w-6xl">
  <div class="flex items-start justify-between mb-5 gap-4">
    <div class="min-w-0">
      <div class="text-[14px] text-ink-primary mb-1">Evidence Tree</div>
      <div class="text-[12px] text-ink-secondary leading-relaxed max-w-2xl">
        Verification chain from {groupBy === 'fr' ? 'FR' : 'ASVS rule'} down to the individual
        tests and their results. Expand any node to see what verifies it and what the test produced.
      </div>
    </div>
    <div class="flex items-center gap-1 shrink-0">
      <button
        type="button"
        on:click={() => (groupBy = 'fr')}
        class="font-mono text-[11px] px-2.5 py-1 rounded-sm border transition-colors"
        class:border-line-strong={groupBy === 'fr'}
        class:text-ink-primary={groupBy === 'fr'}
        class:bg-surface-elevated={groupBy === 'fr'}
        class:border-line-hairline={groupBy !== 'fr'}
        class:text-ink-muted={groupBy !== 'fr'}
      >By FR</button>
      <button
        type="button"
        on:click={() => (groupBy = 'asvs')}
        class="font-mono text-[11px] px-2.5 py-1 rounded-sm border transition-colors"
        class:border-line-strong={groupBy === 'asvs'}
        class:text-ink-primary={groupBy === 'asvs'}
        class:bg-surface-elevated={groupBy === 'asvs'}
        class:border-line-hairline={groupBy !== 'asvs'}
        class:text-ink-muted={groupBy !== 'asvs'}
      >By ASVS</button>
    </div>
  </div>

  {#if loading}
    <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else if error}
    <div class="text-[12px] text-state-failed font-mono">{error}</div>
  {:else if groupBy === 'fr'}
    <div class="space-y-1.5">
      {#each frsSorted as fr (fr.fr_id)}
        {@const detail = frDetails[fr.fr_id]}
        {@const key = 'fr:' + fr.fr_id}
        {@const isOpen = expanded[key]}
        <div class="border border-line-hairline rounded-sm bg-surface-panel">
          <button
            type="button"
            on:click={() => toggle(key)}
            class="w-full text-left flex items-center gap-3 px-4 py-2.5 hover:bg-surface-elevated transition-colors"
          >
            <svg class="h-3 w-3 text-ink-muted shrink-0 transition-transform duration-150 {isOpen ? 'rotate-90' : ''}" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M4.5 3l3 3-3 3" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <span class="font-mono text-[12px] text-ink-primary shrink-0">{fr.fr_id}</span>
            <span class="text-[13px] text-ink-secondary truncate flex-1">{fr.title}</span>
            <span class="font-mono text-[10px] text-ink-muted shrink-0">{fr.test_count} test{fr.test_count === 1 ? '' : 's'}</span>
            <StatePill state={fr.state} size="sm" />
          </button>

          {#if isOpen && detail}
            <div class="px-4 pb-4 pt-1 border-t border-line-hairline bg-surface-inset">
              {#if detail.satisfies.length > 0}
                <div class="mt-3 mb-4">
                  <div class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted mb-1.5">Satisfies ASVS rows</div>
                  <div class="flex flex-wrap gap-1">
                    {#each detail.satisfies as s, i (i)}
                      <span class="font-mono text-[10px] px-1.5 py-0.5 rounded-sm border border-line-hairline text-ink-secondary">{s.ruleset}:{s.row}</span>
                    {/each}
                  </div>
                </div>
              {/if}

              <div class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted mb-1.5">Tests ({detail.tests.length})</div>
              {#if detail.tests.length === 0}
                <div class="text-[12px] text-ink-muted font-mono">No tests defined for this FR.</div>
              {:else}
                <div class="space-y-1">
                  {#each detail.tests as test (test.id)}
                    <TestCard {test} projectPath={scan.project_path} />
                  {/each}
                </div>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {:else if asvsGrouped.length === 0}
    <div class="py-16 text-center">
      <div class="text-[13px] text-ink-primary mb-2">No compliance framework mapped</div>
      <div class="text-[12px] text-ink-muted font-mono">Run the author-fr-compliance-map workflow to enable ASVS grouping:</div>
      <div class="flex items-center gap-2 mt-1">
        <pre class="flex-1 text-[10px] font-mono text-ink-secondary bg-surface-inset border border-line-hairline rounded-sm px-2 py-1.5 overflow-x-auto whitespace-pre">{mappingPrompt}</pre>
        <CopyButton text={mappingPrompt} />
      </div>
    </div>
  {:else}
    <div class="space-y-1.5">
      {#each asvsGrouped as g (g.row.row_id)}
        {@const rowKey = 'asvs:' + g.row.row_id}
        {@const rowOpen = expanded[rowKey]}
        <div class="border border-line-hairline rounded-sm bg-surface-panel">
          <button
            type="button"
            on:click={() => toggle(rowKey)}
            class="w-full text-left flex items-center gap-3 px-4 py-2.5 hover:bg-surface-elevated transition-colors"
          >
            <svg class="h-3 w-3 text-ink-muted shrink-0 transition-transform duration-150 {rowOpen ? 'rotate-90' : ''}" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M4.5 3l3 3-3 3" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <span class="font-mono text-[11px] text-ink-muted shrink-0 w-[110px]">{g.row.row_id}</span>
            <span class="text-[13px] text-ink-primary truncate flex-1">{g.row.title}</span>
            <span class="font-mono text-[10px] uppercase tracking-[0.1em] shrink-0" style="color: {CONFIDENCE_COLORS[g.row.confidence] ?? 'var(--state-untested)'}">{g.row.confidence}</span>
            <StatePill state={g.row.worst_state} size="sm" />
          </button>

          {#if rowOpen}
            <div class="px-4 pb-4 pt-1 border-t border-line-hairline bg-surface-inset">
              {#if g.row.rationale}
                <div class="mt-3 mb-4 text-[12px] text-ink-secondary leading-[1.6]">{g.row.rationale}</div>
              {/if}

              <div class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted mb-1.5">Mapped FRs ({g.frs.length})</div>
              {#if g.frs.length === 0}
                <div class="text-[12px] text-ink-muted font-mono">No FRs mapped to this row.</div>
              {:else}
                <div class="space-y-1">
                  {#each g.frs as fr (fr.fr_id)}
                    {@const detail = frDetails[fr.fr_id]}
                    {@const frKey = 'asvs:' + g.row.row_id + ':fr:' + fr.fr_id}
                    {@const frOpen = expanded[frKey]}
                    <div class="border border-line-hairline rounded-sm bg-surface-panel">
                      <button
                        type="button"
                        on:click={() => toggle(frKey)}
                        class="w-full text-left flex items-center gap-3 px-3 py-2 hover:bg-surface-elevated transition-colors"
                      >
                        <svg class="h-3 w-3 text-ink-muted shrink-0 transition-transform duration-150 {frOpen ? 'rotate-90' : ''}" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
                          <path d="M4.5 3l3 3-3 3" stroke-linecap="round" stroke-linejoin="round" />
                        </svg>
                        <span class="font-mono text-[12px] text-ink-primary shrink-0">{fr.fr_id}</span>
                        <span class="text-[12px] text-ink-secondary truncate flex-1">{fr.title}</span>
                        <StatePill state={fr.state} size="sm" />
                      </button>
                      {#if frOpen && detail}
                        <div class="px-3 pb-3 pt-1 border-t border-line-hairline bg-surface-inset">
                          {#if detail.tests.length === 0}
                            <div class="text-[12px] text-ink-muted font-mono mt-3">No tests defined for this FR.</div>
                          {:else}
                            <div class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted mb-1.5 mt-3">Tests ({detail.tests.length})</div>
                            <div class="space-y-1">
                              {#each detail.tests as test (test.id)}
                                <TestCard {test} projectPath={scan.project_path} />
                              {/each}
                            </div>
                          {/if}
                        </div>
                      {/if}
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
