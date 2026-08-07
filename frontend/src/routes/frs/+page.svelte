<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { FrListResponse } from '$lib/types';

  let data: FrListResponse | null = null;
  let loading = true;
  let error: string | null = null;
  let gapsOnly = false;

  async function refresh() {
    try {
      data = await api.listFRs();
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    refresh();
    const interval = setInterval(refresh, 10000);
    return () => clearInterval(interval);
  });

  function stateColor(state: string): string {
    return {
      passed: 'bg-green-100 text-green-800',
      failed: 'bg-red-100 text-red-800',
      'manual-review': 'bg-amber-100 text-amber-800',
      blocked: 'bg-orange-100 text-orange-800',
      waived: 'bg-purple-100 text-purple-800',
      'has-evidence': 'bg-blue-100 text-blue-800',
      'to-be-tested': 'bg-yellow-50 text-yellow-800',
      untested: 'bg-gray-50 text-gray-600'
    }[state] ?? 'bg-gray-100 text-gray-700';
  }

  $: visibleFrs = data
    ? data.frs.filter((f) => !gapsOnly || f.is_gap)
    : [];
</script>

<section class="flex items-center justify-between mb-6">
  <h1 class="text-2xl font-semibold">FRs</h1>
  <div class="flex items-center gap-4 text-sm">
    {#if data}
      <span class="text-gray-600">
        <strong>{data.summary.passed}</strong> passed ·
        <strong class="text-red-700">{data.summary.failed}</strong> failed ·
        <strong class="text-yellow-700">{data.summary.gaps}</strong> gaps
      </span>
    {/if}
    <label class="flex items-center gap-1 cursor-pointer">
      <input type="checkbox" bind:checked={gapsOnly} />
      Gaps only
    </label>
    <button class="px-3 py-1.5 bg-gray-900 text-white rounded text-sm" on:click={refresh}>
      Refresh
    </button>
  </div>
</section>

{#if loading}
  <p class="text-gray-500">Loading…</p>
{:else if error}
  <p class="text-red-700">{error}</p>
{:else if !data?.catalogue}
  <p class="text-gray-500">No FR catalogue loaded yet. Run a scan with <code>fr_catalog_path</code> set.</p>
{:else if visibleFrs.length === 0}
  <p class="text-gray-500">{gapsOnly ? 'No gaps — all FRs in a non-gap state.' : 'No FRs in catalogue.'}</p>
{:else}
  <p class="text-xs text-gray-500 mb-3">
    Catalogue: <span class="font-mono">{data.catalogue.project}</span>
    {#if data.catalogue.catalogue_version}· v{data.catalogue.catalogue_version}{/if}
    · <a href="/scans/{data.run_id}" class="text-blue-700 hover:underline">latest run</a>
  </p>

  <table class="w-full text-sm bg-white border border-gray-200">
    <thead class="bg-gray-100 text-xs uppercase text-gray-600">
      <tr>
        <th class="text-left px-3 py-2 w-32">FR</th>
        <th class="text-left px-3 py-2">Title</th>
        <th class="text-left px-3 py-2 w-32">State</th>
        <th class="text-center px-3 py-2 w-32">Required</th>
        <th class="text-center px-3 py-2 w-24">Evidence</th>
        <th class="text-left px-3 py-2 w-48">Satisfies</th>
      </tr>
    </thead>
    <tbody>
      {#each visibleFrs as fr (fr.fr_id)}
        <tr class="border-t border-gray-200 hover:bg-gray-50 {fr.is_gap ? 'bg-yellow-50/30' : ''}">
          <td class="px-3 py-2 font-mono text-xs">
            <a href={`/frs/${fr.fr_id}`} class="text-blue-700 hover:underline">{fr.fr_id}</a>
          </td>
          <td class="px-3 py-2">{fr.title}</td>
          <td class="px-3 py-2">
            <span class="px-2 py-0.5 rounded text-xs font-semibold {stateColor(fr.state)}">
              {fr.state}
            </span>
          </td>
          <td class="px-3 py-2 text-center text-xs">
            {#if fr.required_evidence_counts.total === 0}
              <span class="text-gray-400">—</span>
            {:else}
              <span title="all_of / any_of / none_of">
                {fr.required_evidence_counts.all_of}/{fr.required_evidence_counts.any_of}/{fr.required_evidence_counts.none_of}
              </span>
            {/if}
          </td>
          <td class="px-3 py-2 text-center">
            {#if fr.evidence_count > 0}
              <span class="text-blue-700 font-semibold">{fr.evidence_count}</span>
            {:else}
              <span class="text-gray-400">0</span>
            {/if}
          </td>
          <td class="px-3 py-2 text-xs">
            {#each fr.satisfies.slice(0, 2) as s}
              <span class="px-1.5 py-0.5 bg-blue-50 border border-blue-200 rounded mr-1 font-mono">{s}</span>
            {/each}
            {#if fr.satisfies.length > 2}
              <span class="text-gray-500">+{fr.satisfies.length - 2}</span>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
