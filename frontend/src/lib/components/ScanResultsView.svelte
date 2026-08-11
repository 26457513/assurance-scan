<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import FindingsTable from './FindingsTable.svelte';
  import StatePill from './StatePill.svelte';
  import type { ScanStatus, FindingsListResponse, ScanSummary } from '$lib/types';

  export let scan: ScanSummary;

  let detail: ScanStatus | null = null;
  let findings: FindingsListResponse | null = null;
  let loading = true;
  let error: string | null = null;
  let es: EventSource | null = null;

  async function refresh() {
    try {
      detail = await api.getScan(scan.run_id);
      findings = await api.listFindings(scan.run_id);
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  function connectSSE() {
    es = new EventSource(`/api/scans/${scan.run_id}/stream`);
    es.addEventListener('scanner_started', (e) => {
      const payload = JSON.parse((e as MessageEvent).data);
      if (detail) {
        const existing = detail.scanner_status.find((s) => s.kind === payload.scanner);
        if (existing) existing.status = 'running';
        detail = detail;
      }
    });
    es.addEventListener('scanner_completed', (e) => {
      const payload = JSON.parse((e as MessageEvent).data);
      if (detail) {
        const existing = detail.scanner_status.find((s) => s.kind === payload.scanner);
        if (existing) {
          existing.status = payload.status;
          existing.error_message = payload.error_message ?? null;
        }
        detail = detail;
      }
      refresh();
    });
    es.addEventListener('scan_completed', () => {
      es?.close();
      es = null;
      refresh();
    });
    es.onerror = () => {
      es?.close();
      es = null;
      setTimeout(refresh, 5000);
    };
  }

  onMount(() => {
    refresh().then(() => {
      if (detail && (detail.status === 'running' || detail.status === 'queued')) {
        connectSSE();
      }
    });
  });
  onDestroy(() => {
    es?.close();
  });

  function fmtDate(s: string | null): string {
    return s ? new Date(s).toLocaleString() : '—';
  }

  $: scannerColor = (status: string) =>
    status === 'completed'
      ? 'var(--state-passed)'
      : status === 'failed'
        ? 'var(--state-failed)'
        : status === 'running'
          ? 'var(--accent)'
          : 'var(--state-untested)';

  function scanLevel(scanner: string): 'code' | 'image' {
    if (['syft', 'grype', 'trivy-fs'].includes(scanner)) return 'image';
    return 'code';
  }

  $: codeScanners = detail?.scanner_status.filter((s) => scanLevel(s.kind) === 'code') ?? [];
  $: imageScanners = detail?.scanner_status.filter((s) => scanLevel(s.kind) === 'image') ?? [];
</script>

{#if loading}
  <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
{:else if error}
  <div class="text-[12px] text-state-failed font-mono">{error}</div>
{:else if detail}
  <div class="max-w-6xl">
    <div class="mb-6">
      <div class="font-mono text-[13px] text-ink-primary break-all">{detail.run_id}</div>
      <div class="font-mono text-[11px] text-ink-muted mt-1 truncate">{detail.project_path}</div>
      <div class="flex items-center gap-3 mt-3 text-[11px] font-mono text-ink-secondary">
        <StatePill state={detail.status} size="sm" />
        {#if detail.started_at}<span>started {fmtDate(detail.started_at)}</span>{/if}
        {#if detail.completed_at}<span>· completed {fmtDate(detail.completed_at)}</span>{/if}
      </div>
    </div>

    <section class="mb-8">
      <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-2.5">Scanners</div>

      {#if codeScanners.length > 0}
        <div class="mb-3">
          <div class="font-mono text-[9px] uppercase tracking-[0.12em] text-ink-muted mb-1.5">Code-level</div>
          <div class="flex flex-wrap gap-1.5">
            {#each codeScanners as s (s.kind)}
              <div class="px-2.5 py-1 border border-line-hairline rounded-sm bg-surface-panel flex items-center gap-2">
                <span class="font-mono text-[11px] text-ink-primary">{s.kind}</span>
                <span class="text-ink-muted text-[11px]">·</span>
                <span class="font-mono text-[11px]" style="color: {scannerColor(s.status)}">
                  {s.status}
                  {#if s.status === 'running'}<span class="pulse-dot">▌</span>{/if}
                </span>
                {#if s.error_message}
                  <span class="block text-[10px] text-state-failed mt-0.5 font-mono">{s.error_message}</span>
                {/if}
              </div>
            {/each}
          </div>
        </div>
      {/if}

      {#if imageScanners.length > 0}
        <div>
          <div class="font-mono text-[9px] uppercase tracking-[0.12em] text-ink-muted mb-1.5">Image-level</div>
          <div class="flex flex-wrap gap-1.5">
            {#each imageScanners as s (s.kind)}
              <div class="px-2.5 py-1 border border-line-hairline rounded-sm bg-surface-panel flex items-center gap-2">
                <span class="font-mono text-[11px] text-ink-primary">{s.kind}</span>
                <span class="text-ink-muted text-[11px]">·</span>
                <span class="font-mono text-[11px]" style="color: {scannerColor(s.status)}">
                  {s.status}
                  {#if s.status === 'running'}<span class="pulse-dot">▌</span>{/if}
                </span>
                {#if s.error_message}
                  <span class="block text-[10px] text-state-failed mt-0.5 font-mono">{s.error_message}</span>
                {/if}
              </div>
            {/each}
          </div>
        </div>
      {/if}

      {#if codeScanners.length === 0 && imageScanners.length === 0}
        <div class="text-[11px] text-ink-muted font-mono">No scanners yet — scan may be initializing.</div>
      {/if}
    </section>

    {#if findings}
      <section>
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-2.5">
          Findings · {findings.total}
        </div>
        <FindingsTable findings={findings.findings} total={findings.total} bySeverity={findings.by_severity} />
      </section>
    {/if}
  </div>
{/if}
