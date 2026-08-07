<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { FrListEntry, FrListResponse } from '$lib/types';

  let data: FrListResponse | null = null;
  let loading = true;
  let error: string | null = null;
  let gapsOnly = false;
  let categoryFilter: string = '';

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
      pending: 'bg-yellow-50 text-yellow-800',
      untested: 'bg-gray-50 text-gray-600'
    }[state] ?? 'bg-gray-100 text-gray-700';
  }

  $: categories = data
    ? Array.from(new Set(data.frs.map((f) => f.category).filter(Boolean))).sort()
    : [];

  $: visibleFrs = data
    ? data.frs.filter((f) => {
        if (gapsOnly && !f.is_gap) return false;
        if (categoryFilter && f.category !== categoryFilter) return false;
        return true;
      })
    : [];
</script>

<section class="flex items-center justify-between mb-6">
  <h1 class="text-2xl font-semibold">FRs</h1>
  <div class="flex items-center gap-4 text-sm">
    {#if data}
      <span class="text-gray-600">
        <strong class="text-green-700">{data.summary.passed}</strong> passed ·
        <strong class="text-red-700">{data.summary.failed}</strong> failed ·
        <strong class="text-yellow-700">{data.summary.pending + data.summary.untested}</strong> pending ·
        <strong>{data.summary.gaps}</strong> gaps
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
{:else}
  <div class="flex flex-wrap gap-2 mb-4">
    <button
      class="px-3 py-1 text-xs rounded border {categoryFilter === ''
        ? 'bg-gray-900 text-white border-gray-900'
        : 'bg-white border-gray-300 hover:bg-gray-100'}"
      on:click={() => (categoryFilter = '')}>All categories</button>
    {#each categories as cat}
      <button
        class="px-3 py-1 text-xs rounded border font-mono {categoryFilter === cat
          ? 'bg-gray-900 text-white border-gray-900'
          : 'bg-white border-gray-300 hover:bg-gray-100'}"
        on:click={() => (categoryFilter = cat)}>{cat}</button>
    {/each}
  </div>

  <p class="text-xs text-gray-500 mb-3">
    Catalogue: <span class="font-mono">{data.catalogue.project}</span>
    {#if data.catalogue.catalogue_version}· v{data.catalogue.catalogue_version}{/if}
    · {data.catalogue.fr_count} FRs
    {#if data.run_id}
      · <a href="/scans/{data.run_id}" class="text-blue-700 hover:underline">latest run</a>
    {/if}
  </p>

  {#if visibleFrs.length === 0}
    <p class="text-gray-500">
      {gapsOnly || categoryFilter ? 'No FRs match the current filter.' : 'No FRs in catalogue.'}
    </p>
  {:else}
    <table class="w-full text-sm bg-white border border-gray-200">
      <thead class="bg-gray-100 text-xs uppercase text-gray-600">
        <tr>
          <th class="text-left px-3 py-2 w-40">FR</th>
          <th class="text-left px-3 py-2">Title</th>
          <th class="text-left px-3 py-2 w-24">Category</th>
          <th class="text-left px-3 py-2 w-28">State</th>
          <th class="text-center px-3 py-2 w-32">Tests</th>
          <th class="text-left px-3 py-2 w-48">Satisfies</th>
        </tr>
      </thead>
      <tbody>
        {#each visibleFrs as fr (fr.fr_id)}
          <tr
            class="border-t border-gray-200 hover:bg-gray-50 {fr.is_gap
              ? 'bg-yellow-50/30'
              : ''}"
          >
            <td class="px-3 py-2 font-mono text-xs">
              <a href={`/frs/${fr.fr_id}`} class="text-blue-700 hover:underline">{fr.fr_id}</a>
            </td>
            <td class="px-3 py-2">{fr.title}</td>
            <td class="px-3 py-2 text-xs font-mono text-gray-600">{fr.category || '—'}</td>
            <td class="px-3 py-2">
              <span
                class="px-2 py-0.5 rounded text-xs font-semibold {stateColor(fr.state)}"
              >{fr.state}</span>
            </td>
            <td class="px-3 py-2 text-center">
              {#if fr.test_count === 0}
                <span class="text-gray-400 text-xs">no tests</span>
              {:else}
                <div class="inline-flex gap-1 text-xs font-mono">
                  <span class="text-green-700">✓{fr.test_results.pass}</span>
                  {#if fr.test_results.fail > 0}
                    <span class="text-red-700">✗{fr.test_results.fail}</span>
                  {/if}
                  {#if fr.test_results.pending > 0}
                    <span class="text-yellow-700">⏳{fr.test_results.pending}</span>
                  {/if}
                  <span class="text-gray-400">/ {fr.test_count}</span>
                </div>
              {/if}
            </td>
            <td class="px-3 py-2 text-xs">
              {#each fr.satisfies.slice(0, 2) as s}
                <span
                  class="px-1.5 py-0.5 bg-blue-50 border border-blue-200 rounded mr-1 font-mono"
                >{s.ruleset}:{s.row}</span>
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
{/if}
