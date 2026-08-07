<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { ScanSummary } from '$lib/types';

  let scans: ScanSummary[] = [];
  let loading = true;
  let error: string | null = null;

  async function refresh() {
    try {
      scans = await api.listScans();
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  });

  function fmtDate(s: string): string {
    return new Date(s).toLocaleString();
  }
</script>

<section class="flex items-center justify-between mb-6">
  <h1 class="text-2xl font-semibold">Scans</h1>
  <button class="px-3 py-1.5 bg-gray-900 text-white rounded text-sm" on:click={refresh}>
    Refresh
  </button>
</section>

{#if loading}
  <p class="text-gray-500">Loading…</p>
{:else if error}
  <p class="text-red-700">{error}</p>
{:else if scans.length === 0}
  <p class="text-gray-500">No scans yet. Start one via <code>POST /api/scans</code>.</p>
{:else}
  <table class="w-full text-sm bg-white border border-gray-200">
    <thead class="bg-gray-100 text-gray-600 uppercase text-xs">
      <tr>
        <th class="text-left px-3 py-2">Run</th>
        <th class="text-left px-3 py-2">Project</th>
        <th class="text-left px-3 py-2">Status</th>
        <th class="text-left px-3 py-2">Started</th>
        <th class="text-right px-3 py-2">Findings</th>
      </tr>
    </thead>
    <tbody>
      {#each scans as scan (scan.run_id)}
        <tr class="border-t border-gray-200 hover:bg-gray-50">
          <td class="px-3 py-2 font-mono text-xs">
            <a href={`/scans/${scan.run_id}`} class="text-blue-700 hover:underline">
              {scan.run_id}
            </a>
          </td>
          <td class="px-3 py-2 font-mono text-xs truncate max-w-xs">{scan.project_path}</td>
          <td class="px-3 py-2">{scan.status}</td>
          <td class="px-3 py-2 text-xs text-gray-600">{fmtDate(scan.started_at)}</td>
          <td class="px-3 py-2 text-right">{scan.finding_count}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
