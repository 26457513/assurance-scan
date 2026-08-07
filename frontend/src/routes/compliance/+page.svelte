<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type {
    ComplianceListResponse,
    ComplianceMatrixResponse,
    ComplianceFrameworkSummary
  } from '$lib/types';

  let frameworks: ComplianceFrameworkSummary[] = [];
  let selected: string | null = null;
  let matrix: ComplianceMatrixResponse | null = null;
  let loading = true;
  let error: string | null = null;

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
      'manual-review': 'bg-amber-100 text-amber-800',
      blocked: 'bg-orange-100 text-orange-800',
      waived: 'bg-purple-100 text-purple-800',
      'has-evidence': 'bg-blue-100 text-blue-800',
      'to-be-tested': 'bg-gray-100 text-gray-700',
      untested: 'bg-gray-50 text-gray-500'
    }[state] ?? 'bg-gray-100 text-gray-700';
  }
</script>

<section class="mb-6">
  <h1 class="text-2xl font-semibold mb-4">Compliance</h1>
  {#if frameworks.length === 0 && !loading}
    <p class="text-gray-500">No compliance frameworks referenced by any FR catalogue yet.</p>
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
  <section class="mb-4 flex gap-4 text-sm">
    {#each Object.entries(matrix.summary) as [state, count]}
      {#if count > 0}
        <span class="px-2 py-0.5 rounded {stateColor(state)}">
          {state}: {count}
        </span>
      {/if}
    {/each}
  </section>

  <table class="w-full text-sm bg-white border border-gray-200">
    <thead class="bg-gray-100 text-xs uppercase text-gray-600">
      <tr>
        <th class="text-left px-3 py-2 w-48">Row</th>
        <th class="text-left px-3 py-2 w-32">State</th>
        <th class="text-left px-3 py-2">FRs</th>
      </tr>
    </thead>
    <tbody>
      {#each matrix.rows as row (row.row_id)}
        <tr class="border-t border-gray-200 hover:bg-gray-50">
          <td class="px-3 py-2 font-mono text-xs">{row.row_id}</td>
          <td class="px-3 py-2">
            <span class="px-2 py-0.5 rounded text-xs font-semibold {stateColor(row.worst_state)}">
              {row.worst_state}
            </span>
          </td>
          <td class="px-3 py-2">
            {#each row.fr_ids as fr_id}
              <a
                href={`/frs/${fr_id}`}
                class="text-xs font-mono text-blue-700 hover:underline mr-2"
              >{fr_id}</a>
            {/each}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
