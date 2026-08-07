<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import type { FrDetailResponse, FrHistoryResponse, TestSpecWithResult } from '$lib/types';

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
      passed: 'bg-green-100 text-green-800',
      failed: 'bg-red-100 text-red-800',
      'manual-review': 'bg-amber-100 text-amber-800',
      blocked: 'bg-orange-100 text-orange-800',
      waived: 'bg-purple-100 text-purple-800',
      pending: 'bg-yellow-50 text-yellow-800',
      untested: 'bg-gray-50 text-gray-600'
    }[state] ?? 'bg-gray-100 text-gray-700';
  }

  function resultColor(result: string): string {
    return {
      pass: 'text-green-700',
      fail: 'text-red-700',
      pending: 'text-yellow-700'
    }[result] ?? 'text-gray-700';
  }

  function resultIcon(result: string): string {
    return { pass: '✓', fail: '✗', pending: '⏳' }[result] ?? '?';
  }

  function testTypeLabel(test: TestSpecWithResult): string {
    const bits = [test.type];
    if (test.scanner) bits.push(test.scanner);
    if (test.severity_floor) bits.push(`≥ ${test.severity_floor}`);
    if (test.rule_pattern) bits.push(`/${test.rule_pattern}/`);
    if (test.name_pattern) bits.push(test.name_pattern);
    if (test.format) bits.push(test.format);
    return bits.join(' · ');
  }
</script>

{#if loading}
  <p class="text-gray-500">Loading…</p>
{:else if error}
  <p class="text-red-700">{error}</p>
{:else if detail}
  <header class="mb-6">
    <a href="/frs" class="text-sm text-blue-700 hover:underline">← All FRs</a>
    <h1 class="text-2xl font-semibold mt-2">{detail.title}</h1>
    <p class="text-sm font-mono text-gray-600 mt-1">{detail.fr_id}</p>
    <div class="mt-3 flex items-center gap-3 text-sm">
      <span class="px-2 py-1 bg-gray-100 rounded font-semibold {stateColor(detail.state)}">
        {detail.state}
      </span>
      {#if detail.category}
        <span class="px-2 py-1 bg-gray-100 rounded text-xs font-mono">{detail.category}</span>
      {/if}
      <span class="text-gray-600">run <span class="font-mono">{detail.run_id}</span></span>
    </div>
    {#if detail.description}
      <p class="mt-3 text-gray-700">{detail.description}</p>
    {/if}
  </header>

  <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
    <section>
      <h2 class="text-sm font-semibold uppercase text-gray-600 mb-3">
        Tests ({detail.tests.length})
      </h2>
      {#if detail.tests.length === 0}
        <p class="text-gray-500 text-sm bg-gray-50 border border-gray-200 rounded p-3">
          No tests defined. This FR is <strong>untested</strong> — add at least one test
          (e.g. a unit-test, scanner-clean, or manual-attestation) to the catalogue.
        </p>
      {:else}
        <ul class="space-y-2">
          {#each detail.tests as test (test.id)}
            <li class="border border-gray-200 rounded p-3 bg-white text-sm">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0 flex-1">
                  <div class="font-mono text-xs text-gray-700">{test.id}</div>
                  <div class="font-mono text-xs text-gray-500 mt-0.5 break-all">
                    {testTypeLabel(test)}
                  </div>
                  {#if test.description}
                    <p class="text-xs text-gray-600 mt-1">{test.description}</p>
                  {/if}
                </div>
                <span class="font-semibold text-sm whitespace-nowrap {resultColor(test.result)}">
                  {resultIcon(test.result)} {test.result}
                </span>
              </div>
              {#if Object.keys(test.detail).length > 0}
                <details class="mt-2">
                  <summary class="text-xs text-gray-500 cursor-pointer">detail</summary>
                  <pre class="text-xs bg-gray-50 p-2 rounded mt-1 overflow-x-auto">{JSON.stringify(test.detail, null, 2)}</pre>
                </details>
              {/if}
            </li>
          {/each}
        </ul>
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
            <a
              href={`/compliance/${s.ruleset}`}
              class="text-xs px-2 py-0.5 bg-blue-50 border border-blue-200 rounded hover:bg-blue-100 font-mono"
            >{s.ruleset}:{s.row}</a>
          {/each}
        </div>
      {/if}

      {#if detail.depends_on.length}
        <h3 class="text-xs uppercase text-gray-500 mt-5 mb-1">Depends on</h3>
        <div class="flex flex-wrap gap-1">
          {#each detail.depends_on as d}
            <a
              href={`/frs/${d}`}
              class="text-xs px-2 py-0.5 bg-gray-100 border border-gray-200 rounded hover:bg-gray-200 font-mono"
            >{d}</a>
          {/each}
        </div>
      {/if}
    </section>

    <section>
      <h2 class="text-sm font-semibold uppercase text-gray-600 mb-3">Computation Reason</h2>
      {#if Object.keys(detail.reason).length > 0}
        <pre class="text-xs bg-gray-50 border border-gray-200 rounded p-3 overflow-x-auto">{JSON.stringify(detail.reason, null, 2)}</pre>
      {:else}
        <p class="text-gray-500 text-sm">No reason recorded.</p>
      {/if}

      {#if history && history.history.length > 1}
        <h2 class="text-sm font-semibold uppercase text-gray-600 mt-8 mb-3">State Across Runs</h2>
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
                <td class="px-3 py-2 {stateColor(h.state)} font-semibold">
                  <span class="px-2 py-0.5 rounded text-xs">{h.state}</span>
                </td>
                <td class="px-3 py-2 text-xs text-gray-600">
                  {h.computed_at ? new Date(h.computed_at).toLocaleString() : '—'}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>
  </div>
{/if}
