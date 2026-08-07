<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import type { ScanStatus, FindingsListResponse } from '$lib/types';

  let scan: ScanStatus | null = null;
  let findings: FindingsListResponse | null = null;
  let loading = true;
  let error: string | null = null;
  let severityFilter: string | null = null;
  let es: EventSource | null = null;

  const runId = $page.params.run_id;

  async function refresh() {
    try {
      scan = await api.getScan(runId);
      findings = await api.listFindings(runId, severityFilter ?? undefined);
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function connectSSE() {
    es = new EventSource(`/api/scans/${runId}/stream`);
    es.addEventListener('scanner_started', (e) => {
      const payload = JSON.parse((e as MessageEvent).data);
      if (scan) {
        const existing = scan.scanner_status.find((s) => s.kind === payload.scanner);
        if (existing) existing.status = 'running';
        scan = scan; // trigger reactivity
      }
    });
    es.addEventListener('scanner_completed', (e) => {
      const payload = JSON.parse((e as MessageEvent).data);
      if (scan) {
        const existing = scan.scanner_status.find((s) => s.kind === payload.scanner);
        if (existing) {
          existing.status = payload.status;
          existing.error_message = payload.error_message ?? null;
        }
        scan = scan;
      }
      refresh(); // findings list updates as scanners complete
    });
    es.addEventListener('scan_completed', () => {
      es?.close();
      es = null;
      refresh();
    });
    es.onerror = () => {
      // Fall back to polling if SSE fails.
      es?.close();
      es = null;
      setTimeout(refresh, 5000);
    };
  }

  onMount(() => {
    refresh().then(() => {
      if (scan && (scan.status === 'running' || scan.status === 'queued')) {
        connectSSE();
      }
    });
  });

  onDestroy(() => {
    es?.close();
  });

  $: if (severityFilter) refresh();

  function fmtDate(s: string | null): string {
    return s ? new Date(s).toLocaleString() : '—';
  }

  function severityClass(s: string): string {
    return `text-severity-${s ?? 'UNKNOWN'}`;
  }
</script>

{#if loading}
  <p class="text-gray-500">Loading…</p>
{:else if error}
  <p class="text-red-700">{error}</p>
{:else if scan}
  <header class="mb-6">
    <a href="/" class="text-sm text-blue-700 hover:underline">← All scans</a>
    <h1 class="text-2xl font-semibold mt-2 font-mono text-base">{scan.run_id}</h1>
    <p class="text-sm text-gray-600 mt-1">
      <span class="font-mono">{scan.project_path}</span>
      · <span class="font-semibold">{scan.status}</span>
      {#if scan.started_at}· started {fmtDate(scan.started_at)}{/if}
      {#if scan.completed_at}· completed {fmtDate(scan.completed_at)}{/if}
    </p>
  </header>

  <section class="mb-8">
    <h2 class="text-sm font-semibold uppercase text-gray-600 mb-2">Scanners</h2>
    <div class="flex flex-wrap gap-2">
      {#each scan.scanner_status as s (s.kind)}
        <div class="px-3 py-1.5 border border-gray-200 rounded text-sm bg-white">
          <span class="font-mono">{s.kind}</span>
          <span class="text-gray-500 ml-2">·</span>
          <span
            class="ml-1 {s.status === 'completed'
              ? 'text-green-700'
              : s.status === 'failed'
                ? 'text-red-700'
                : s.status === 'running'
                  ? 'text-blue-700'
                  : 'text-gray-600'}"
          >
            {s.status}
            {#if s.status === 'running'}<span class="animate-pulse">▌</span>{/if}
          </span>
          {#if s.error_message}
            <span class="block text-xs text-red-700 mt-1">{s.error_message}</span>
          {/if}
        </div>
      {:else}
        <p class="text-gray-500 text-sm">No scanners yet — scan may be initializing.</p>
      {/each}
    </div>
  </section>

  {#if findings}
    <section>
      <header class="flex items-center justify-between mb-3">
        <h2 class="text-sm font-semibold uppercase text-gray-600">
          Findings ({findings.total})
        </h2>
        <div class="flex gap-1 text-xs">
          <button
            class="px-2 py-1 border rounded {severityFilter === null ? 'bg-gray-900 text-white' : 'bg-white'}"
            on:click={() => (severityFilter = null)}>All</button>
          {#each ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as sev}
            <button
              class="px-2 py-1 border rounded {severityFilter === sev ? 'bg-gray-900 text-white' : 'bg-white'}"
              on:click={() => (severityFilter = sev)}>{sev}</button>
          {/each}
        </div>
      </header>

      {#if findings.findings.length === 0}
        <p class="text-gray-500">No findings match this filter.</p>
      {:else}
        <table class="w-full text-sm bg-white border border-gray-200">
          <thead class="bg-gray-100 text-xs uppercase text-gray-600">
            <tr>
              <th class="text-left px-3 py-2 w-24">Severity</th>
              <th class="text-left px-3 py-2 w-28">Scanner</th>
              <th class="text-left px-3 py-2">File:Line</th>
              <th class="text-left px-3 py-2">Message</th>
            </tr>
          </thead>
          <tbody>
            {#each findings.findings as f (f.id)}
              <tr class="border-t border-gray-200">
                <td class="px-3 py-2 font-semibold {severityClass(f.severity)}">{f.severity}</td>
                <td class="px-3 py-2 font-mono text-xs">{f.scanner_kind}</td>
                <td class="px-3 py-2 font-mono text-xs">
                  {#if f.file_path}{f.file_path}:{f.line_start ?? '?'}{/if}
                </td>
                <td class="px-3 py-2">{f.message}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>
  {/if}
{/if}
