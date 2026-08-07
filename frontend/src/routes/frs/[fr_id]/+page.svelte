<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import type { FrDetailResponse, FrHistoryResponse } from '$lib/types';

  let detail: FrDetailResponse | null = null;
  let history: FrHistoryResponse | null = null;
  let loading = true;
  let error: string | null = null;

  const frId = $page.params.fr_id;

  async function refresh() {
    try {
      detail = await api.getFr(frId);
      history = await api.getFrHistory(frId);
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
      passed: 'text-green-700',
      failed: 'text-red-700',
      'manual-review': 'text-amber-700',
      'has-evidence': 'text-blue-700',
      'to-be-tested': 'text-gray-700',
      untested: 'text-gray-500',
      waived: 'text-purple-700',
      blocked: 'text-orange-700'
    }[state] ?? 'text-gray-700';
  }

  function specLabel(spec: { type: string; source_kind?: string; rule_id?: string; name_pattern?: string }): string {
    const bits = [spec.type];
    if (spec.source_kind) bits.push(spec.source_kind);
    if (spec.rule_id) bits.push(spec.rule_id);
    if (spec.name_pattern) bits.push(spec.name_pattern);
    return bits.join(' · ');
  }

  $: evidenceBySpec = (detail?.evidence ?? []).reduce<Record<string, typeof detail.evidence>>((acc, e) => {
    const key = `${e.type}|${(e.source as Record<string, string>).kind ?? ''}|${(e.source as Record<string, string>).rule_id ?? ''}`;
    (acc[key] ??= []).push(e);
    return acc;
  }, {});
</script>

{#if loading}
  <p class="text-gray-500">Loading…</p>
{:else if error}
  <p class="text-red-700">{error}</p>
{:else if detail}
  <header class="mb-6">
    <a href="/" class="text-sm text-blue-700 hover:underline">← All scans</a>
    <h1 class="text-2xl font-semibold mt-2">{detail.title}</h1>
    <p class="text-sm font-mono text-gray-600 mt-1">{detail.fr_id}</p>
    <div class="mt-3 flex items-center gap-3 text-sm">
      <span class="px-2 py-1 bg-gray-100 rounded font-semibold {stateColor(detail.state)}">
        {detail.state}
      </span>
      <span class="text-gray-600">run <span class="font-mono">{detail.run_id}</span></span>
    </div>
    {#if detail.description}
      <p class="mt-3 text-gray-700">{detail.description}</p>
    {/if}
  </header>

  <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
    <section>
      <h2 class="text-sm font-semibold uppercase text-gray-600 mb-3">Required Evidence</h2>
      {#if !detail.required_evidence.all_of?.length && !detail.required_evidence.any_of?.length && !detail.required_evidence.none_of?.length}
        <p class="text-gray-500 text-sm">No required_evidence defined.</p>
      {:else}
        {#if detail.required_evidence.all_of?.length}
          <h3 class="text-xs uppercase text-gray-500 mt-3 mb-1">All of</h3>
          <ul class="space-y-1 text-sm">
            {#each detail.required_evidence.all_of as spec (specLabel(spec))}
              <li class="font-mono text-xs bg-gray-50 border border-gray-200 rounded px-2 py-1">
                {specLabel(spec)}
              </li>
            {/each}
          </ul>
        {/if}
        {#if detail.required_evidence.any_of?.length}
          <h3 class="text-xs uppercase text-gray-500 mt-3 mb-1">Any of</h3>
          <ul class="space-y-1 text-sm">
            {#each detail.required_evidence.any_of as spec (specLabel(spec))}
              <li class="font-mono text-xs bg-gray-50 border border-gray-200 rounded px-2 py-1">
                {specLabel(spec)}
              </li>
            {/each}
          </ul>
        {/if}
        {#if detail.required_evidence.none_of?.length}
          <h3 class="text-xs uppercase text-gray-500 mt-3 mb-1">None of</h3>
          <ul class="space-y-1 text-sm">
            {#each detail.required_evidence.none_of as spec (specLabel(spec))}
              <li class="font-mono text-xs bg-red-50 border border-red-200 rounded px-2 py-1">
                {specLabel(spec)}
              </li>
            {/each}
          </ul>
        {/if}
      {/if}

      {#if detail.implemented_by.length}
        <h3 class="text-xs uppercase text-gray-500 mt-5 mb-1">Implemented by</h3>
        <ul class="text-xs font-mono space-y-1">
          {#each detail.implemented_by as ref}
            <li>{ref.kind}: <span class="text-blue-700">{ref.ref}</span></li>
          {/each}
        </ul>
      {/if}

      {#if detail.satisfies.length}
        <h3 class="text-xs uppercase text-gray-500 mt-5 mb-1">Satisfies</h3>
        <div class="flex flex-wrap gap-1">
          {#each detail.satisfies as s}
            <span class="text-xs px-2 py-0.5 bg-blue-50 border border-blue-200 rounded">{s}</span>
          {/each}
        </div>
      {/if}

      {#if detail.depends_on.length}
        <h3 class="text-xs uppercase text-gray-500 mt-5 mb-1">Depends on</h3>
        <div class="flex flex-wrap gap-1">
          {#each detail.depends_on as d}
            <a href={`/frs/${d}`}
               class="text-xs px-2 py-0.5 bg-gray-100 border border-gray-200 rounded hover:bg-gray-200 font-mono">
              {d}
            </a>
          {/each}
        </div>
      {/if}
    </section>

    <section>
      <h2 class="text-sm font-semibold uppercase text-gray-600 mb-3">Collected Evidence</h2>
      {#if detail.evidence.length === 0}
        <p class="text-gray-500 text-sm">No evidence collected in this run.</p>
      {:else}
        <ul class="space-y-2">
          {#each detail.evidence as e (e.id)}
            <li class="border border-gray-200 rounded p-3 bg-white text-sm">
              <div class="flex items-center gap-2">
                <span class="font-mono text-xs px-1.5 py-0.5 bg-gray-100 rounded">{e.type}</span>
                <span class="text-xs {(e.result === 'pass') ? 'text-green-700' : 'text-red-700'}">{e.result}</span>
              </div>
              {#if e.notes}
                <p class="text-xs text-gray-700 mt-2">{e.notes}</p>
              {/if}
              <p class="text-xs text-gray-500 mt-1">collected {e.collected_at ? new Date(e.collected_at).toLocaleString() : '—'}</p>
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  </div>

  {#if history && history.history.length > 1}
    <section class="mt-10">
      <h2 class="text-sm font-semibold uppercase text-gray-600 mb-3">State Across Runs</h2>
      <table class="w-full text-sm bg-white border border-gray-200">
        <thead class="bg-gray-100 text-xs uppercase text-gray-600">
          <tr>
            <th class="text-left px-3 py-2">Run</th>
            <th class="text-left px-3 py-2">State</th>
            <th class="text-left px-3 py-2">Computed</th>
          </tr>
        </thead>
        <tbody>
          {#each history.history as h (h.run_id)}
            <tr class="border-t border-gray-200">
              <td class="px-3 py-2 font-mono text-xs">
                <a href={`/scans/${h.run_id}`} class="text-blue-700 hover:underline">{h.run_id}</a>
              </td>
              <td class="px-3 py-2 {stateColor(h.state)} font-semibold">{h.state}</td>
              <td class="px-3 py-2 text-xs text-gray-600">
                {h.computed_at ? new Date(h.computed_at).toLocaleString() : '—'}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </section>
  {/if}
{/if}
