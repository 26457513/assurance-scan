<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { TrendsResponse } from '$lib/types';

  let data: TrendsResponse | null = null;
  let loading = true;
  let error: string | null = null;

  async function refresh() {
    try {
      data = await api.getTrends();
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    refresh();
  });

  $: maxTotal = data ? Math.max(1, ...data.runs.map((r) => r.total_findings)) : 1;
  $: severities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'];

  function severityColor(s: string): string {
    return {
      CRITICAL: 'bg-red-700',
      HIGH: 'bg-red-500',
      MEDIUM: 'bg-amber-500',
      LOW: 'bg-lime-600',
      UNKNOWN: 'bg-gray-400'
    }[s] ?? 'bg-gray-300';
  }

  function deltaColor(d: number): string {
    if (d > 0) return 'text-red-700';
    if (d < 0) return 'text-green-700';
    return 'text-gray-700';
  }

  function deltaLabel(d: number): string {
    if (d > 0) return `+${d}`;
    return String(d);
  }
</script>

<h1 class="text-2xl font-semibold mb-4">Trends</h1>

{#if loading}
  <p class="text-gray-500">Loading…</p>
{:else if error}
  <p class="text-red-700">{error}</p>
{:else if data}
  {#if data.delta}
    <div class="mb-6 p-4 bg-white border border-gray-200 rounded">
      <h2 class="text-xs uppercase text-gray-500 mb-1">Latest change vs previous run</h2>
      <div class="flex items-baseline gap-4">
        <span class="text-2xl font-semibold {deltaColor(data.delta.total_delta)}">
          {deltaLabel(data.delta.total_delta)} findings
        </span>
        <span class="text-sm text-gray-600">
          vs run <a href={`/scans/${data.delta.vs_run_id}`} class="font-mono text-blue-700 hover:underline">
            {data.delta.vs_run_id}
          </a>
        </span>
      </div>
      {#if Object.keys(data.delta.by_severity).length > 0}
        <div class="mt-2 flex gap-3 text-sm">
          {#each Object.entries(data.delta.by_severity) as [sev, n]}
            <span class="text-xs px-2 py-0.5 rounded bg-gray-100">
              {sev}: <span class={deltaColor(n)}>{deltaLabel(n)}</span>
            </span>
          {/each}
        </div>
      {/if}
    </div>
  {/if}

  {#if data.runs.length === 0}
    <p class="text-gray-500">No runs yet.</p>
  {:else}
    <h2 class="text-sm font-semibold uppercase text-gray-600 mb-3">Recent runs</h2>
    <div class="space-y-3">
      {#each data.runs as run (run.run_id)}
        <div class="bg-white border border-gray-200 rounded p-4">
          <div class="flex items-center justify-between mb-2">
            <a href={`/scans/${run.run_id}`} class="font-mono text-sm text-blue-700 hover:underline">
              {run.run_id}
            </a>
            <span class="text-xs text-gray-500">{run.started_at ? new Date(run.started_at).toLocaleString() : '—'}</span>
          </div>
          <div class="flex h-6 overflow-hidden rounded bg-gray-100">
            {#each severities as sev}
              {@const count = run.by_severity[sev] ?? 0}
              {#if count > 0}
                <div
                  class="{severityColor(sev)} flex items-center justify-center text-xs text-white font-semibold"
                  style="width: {(count / maxTotal) * 100}%"
                  title="{sev}: {count}"
                >{count}</div>
              {/if}
            {/each}
            {#if run.total_findings === 0}
              <div class="flex-1 flex items-center justify-center text-xs text-gray-500">no findings</div>
            {/if}
          </div>
          <div class="mt-2 flex justify-between text-xs text-gray-600">
            <span><strong>{run.total_findings}</strong> total</span>
            <span class="font-mono">{run.project_path}</span>
          </div>
        </div>
      {/each}
    </div>
  {/if}
{/if}
