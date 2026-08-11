<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { severityMeta } from '$lib/state';
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

  function deltaColor(d: number): string {
    if (d > 0) return 'var(--state-failed)';
    if (d < 0) return 'var(--state-passed)';
    return 'var(--text-secondary)';
  }

  function deltaLabel(d: number): string {
    if (d > 0) return `+${d}`;
    return String(d);
  }
</script>

<div class="p-6 max-w-5xl">
  <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-4">Trends</div>

  {#if loading}
    <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else if error}
    <div class="text-[12px] text-state-failed font-mono">{error}</div>
  {:else if data}
    {#if data.delta}
      <div class="mb-6 p-4 border border-line-hairline rounded-sm bg-surface-panel">
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-2">Latest change vs previous run</div>
        <div class="flex items-baseline gap-4">
          <span class="text-[22px] font-medium tabular-nums" style="color: {deltaColor(data.delta.total_delta)}">
            {deltaLabel(data.delta.total_delta)}
          </span>
          <span class="text-[12px] text-ink-muted">
            findings vs <a href={`/scans/${data.delta.vs_run_id}`} class="font-mono text-ink-secondary hover:text-accent">{data.delta.vs_run_id}</a>
          </span>
        </div>
        {#if Object.keys(data.delta.by_severity).length > 0}
          <div class="mt-3 flex gap-3 flex-wrap">
            {#each Object.entries(data.delta.by_severity) as [sev, n]}
              <span class="font-mono text-[11px] px-2 py-0.5 rounded-sm border border-line-hairline">
                <span style="color: {severityMeta(sev).color}">{severityMeta(sev).label}</span>
                <span class="text-ink-muted mx-1">·</span>
                <span style="color: {deltaColor(n)}">{deltaLabel(n)}</span>
              </span>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    {#if data.runs.length === 0}
      <div class="text-[12px] text-ink-muted font-mono">No runs yet.</div>
    {:else}
      <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-3">Recent runs</div>
      <div class="space-y-2">
        {#each data.runs as run (run.run_id)}
          <div class="border border-line-hairline rounded-sm p-3 bg-surface-panel">
            <div class="flex items-center justify-between mb-2">
              <a href={`/scans/${run.run_id}`} class="font-mono text-[12px] text-ink-primary hover:text-accent transition-colors">
                {run.run_id}
              </a>
              <span class="font-mono text-[11px] text-ink-muted">{run.started_at ? new Date(run.started_at).toLocaleString() : '—'}</span>
            </div>
            <div class="flex h-5 overflow-hidden rounded-sm bg-surface-inset">
              {#each severities as sev}
                {@const count = run.by_severity[sev] ?? 0}
                {#if count > 0}
                  <div
                    class="flex items-center justify-center font-mono text-[10px] text-ink-primary"
                    style="width: {(count / maxTotal) * 100}%; background: color-mix(in srgb, {severityMeta(sev).color} 28%, transparent);"
                    title="{sev}: {count}"
                  >{count}</div>
                {/if}
              {/each}
              {#if run.total_findings === 0}
                <div class="flex-1 flex items-center justify-center font-mono text-[11px] text-ink-muted">no findings</div>
              {/if}
            </div>
            <div class="mt-2 flex justify-between font-mono text-[11px] text-ink-muted">
              <span><span class="text-ink-primary tabular-nums">{run.total_findings}</span> total</span>
              <span class="truncate ml-3">{run.project_path}</span>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</div>
