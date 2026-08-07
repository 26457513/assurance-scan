<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type {
    ComplianceListResponse,
    ComplianceMatrixResponse,
    ComplianceFrameworkSummary,
    ComplianceRow
  } from '$lib/types';

  let frameworks: ComplianceFrameworkSummary[] = [];
  let selected: string | null = null;
  let matrix: ComplianceMatrixResponse | null = null;
  let loading = true;
  let error: string | null = null;
  let expandedRow: string | null = null;

  async function loadFrameworks() {
    const data: ComplianceListResponse = await api.listComplianceFrameworks();
    frameworks = data.frameworks;
    if (!selected && frameworks.length) {
      selected = frameworks[0].id;
      await loadMatrix();
    }
  }

  async function loadMatrix() {
    if (!selected) return;
    loading = true;
    try {
      matrix = await api.getComplianceMatrix(selected);
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    loadFrameworks().catch((e) => (error = String(e))).finally(() => (loading = false));
  });

  $: if (selected) loadMatrix();

  function stateColor(state: string): string {
    return {
      passed: 'bg-green-100 text-green-800',
      failed: 'bg-red-100 text-red-800',
      pending: 'bg-yellow-50 text-yellow-800',
      blocked: 'bg-orange-100 text-orange-800',
      waived: 'bg-purple-100 text-purple-800',
      untested: 'bg-gray-50 text-gray-600'
    }[state] ?? 'bg-gray-100 text-gray-700';
  }

  function confidenceColor(conf: string): string {
    return {
      high: 'bg-green-50 text-green-700 border-green-200',
      medium: 'bg-yellow-50 text-yellow-700 border-yellow-200',
      low: 'bg-red-50 text-red-700 border-red-200'
    }[conf] ?? 'bg-gray-50 text-gray-700 border-gray-200';
  }

  function toggleRow(rowId: string) {
    expandedRow = expandedRow === rowId ? null : rowId;
  }
</script>

<section class="mb-6">
  <h1 class="text-2xl font-semibold mb-4">Compliance</h1>
  {#if frameworks.length === 0 && !loading}
    <p class="text-gray-500">No compliance frameworks mapped yet. Run the <code>propose-compliance-mapping</code> workflow to create a mapping.</p>
  {:else}
    <div class="flex flex-wrap gap-2 mb-6">
      {#each frameworks as fw (fw.id)}
        <button
          on:click={() => (selected = fw.id)}
          class="px-3 py-1.5 text-sm rounded border {selected === fw.id
            ? 'bg-gray-900 text-white border-gray-900'
            : 'bg-white border-gray-300 hover:bg-gray-100'}"
        >
          {fw.id}
          <span class="ml-2 text-xs opacity-70">({fw.rows} rows)</span>
        </button>
      {/each}
    </div>
  {/if}
</section>

{#if loading && selected}
  <p class="text-gray-500">Loading {selected}…</p>
{:else if error}
  <p class="text-red-700">{error}</p>
{:else if matrix}
  <!-- Summary badges -->
  <section class="mb-4 flex flex-wrap gap-2 text-sm">
    {#each Object.entries(matrix.summary) as [state, count]}
      {#if count > 0}
        <span class="px-2 py-0.5 rounded {stateColor(state)}">
          {state}: {count}
        </span>
      {/if}
    {/each}
    <span class="px-2 py-0.5 rounded bg-gray-100 text-gray-600">
      {matrix.row_count} rows mapped
    </span>
  </section>

  <!-- Mapping table -->
  <div class="space-y-2">
    {#each matrix.rows as row (row.row_id)}
      <div class="border border-gray-200 rounded bg-white overflow-hidden">
        <!-- Row header (click to expand) -->
        <button
          on:click={() => toggleRow(row.row_id)}
          class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
        >
          <!-- State badge -->
          <span class="px-2 py-0.5 rounded text-xs font-semibold whitespace-nowrap {stateColor(row.worst_state)}">
            {row.worst_state}
          </span>

          <!-- ASVS row info -->
          <div class="flex-1 min-w-0">
            <div class="flex items-baseline gap-2">
              <span class="font-mono text-xs text-gray-500">{row.section}</span>
              <span class="font-semibold text-sm truncate">{row.title}</span>
            </div>
            <div class="font-mono text-xs text-gray-400">{row.row_id}</div>
          </div>

          <!-- Confidence badge -->
          <span class="px-2 py-0.5 rounded text-xs border whitespace-nowrap {confidenceColor(row.confidence)}">
            {row.confidence}
          </span>

          <!-- FR count -->
          <span class="text-xs text-gray-500 whitespace-nowrap">
            {row.fr_ids.length} FR{row.fr_ids.length !== 1 ? 's' : ''}
          </span>

          <!-- Expand indicator -->
          <span class="text-gray-400 text-sm">
            {expandedRow === row.row_id ? '▲' : '▼'}
          </span>
        </button>

        <!-- Expanded detail -->
        {#if expandedRow === row.row_id}
          <div class="px-4 py-3 border-t border-gray-100 bg-gray-50 space-y-3">
            <!-- Description -->
            {#if row.description}
              <p class="text-sm text-gray-600">{row.description}</p>
            {/if}

            <!-- Rationale -->
            {#if row.rationale}
              <div>
                <h4 class="text-xs uppercase text-gray-500 mb-1">Mapping Rationale</h4>
                <p class="text-sm text-gray-700">{row.rationale}</p>
              </div>
            {/if}

            <!-- FR mapping -->
            <div>
              <h4 class="text-xs uppercase text-gray-500 mb-1">Satisfied by</h4>
              <div class="flex flex-wrap gap-2">
                {#each row.fr_ids as frId}
                  {@const frState = row.fr_states[frId] || 'untested'}
                  <a
                    href={`/frs/${frId}`}
                    class="inline-flex items-center gap-1.5 px-2 py-1 rounded border text-xs hover:bg-gray-100
                    {frState === 'passed' ? 'border-green-200 bg-green-50' :
                     frState === 'failed' ? 'border-red-200 bg-red-50' :
                     'border-gray-200 bg-white'}"
                  >
                    <span class="font-mono">{frId}</span>
                    <span class="text-gray-400">·</span>
                    <span class="{frState === 'passed' ? 'text-green-700' : frState === 'failed' ? 'text-red-700' : 'text-gray-500'}">
                      {frState}
                    </span>
                  </a>
                {/each}
              </div>
            </div>
          </div>
        {/if}
      </div>
    {/each}
  </div>
{/if}
