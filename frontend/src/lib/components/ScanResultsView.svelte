<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import FindingsTable from './FindingsTable.svelte';
  import type { ScanStatus, FindingsListResponse, ScanSummary } from '$lib/types';
  import { SCANNER_DESCRIPTIONS } from '$lib/scannerDescriptions';

  export let scan: ScanSummary;
  export let repo: string | null = null;
  export let commit: string | null = null;

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

  function fmtShort(iso: string | null): string {
    if (!iso) return '—';
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function fmtDuration(): string {
    if (!detail?.completed_at) return '—';
    const secs = Math.max(1, Math.round((new Date(detail.completed_at).getTime() - new Date(detail.started_at).getTime()) / 1000));
    return secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${secs % 60}s`;
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
  let scannersExpanded = false;
</script>

{#if loading}
  <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
{:else if error}
  <div class="text-[12px] text-state-failed font-mono">{error}</div>
{:else if detail}
  <div class="max-w-6xl">
    <section class="mb-5">
      <div class="border border-line-hairline rounded-sm overflow-hidden bg-surface-panel font-mono text-[11px]">
        <div class="grid grid-cols-[minmax(0,1.1fr)_minmax(0,1.4fr)_90px_100px_80px] gap-3 px-3 py-1.5 bg-surface-inset border-b border-line-hairline text-[10px] uppercase tracking-[0.14em] text-ink-muted items-center">
          <div>Run</div>
          <div>Project</div>
          <div>Status</div>
          <div>Started</div>
          <div>Duration</div>
        </div>
        <div class="grid grid-cols-[minmax(0,1.1fr)_minmax(0,1.4fr)_90px_100px_80px] gap-3 px-3 py-2 items-center border-b border-line-hairline">
          <div class="text-ink-primary truncate" title={detail.run_id}>{detail.run_id}</div>
          <div class="text-ink-muted truncate" title={detail.project_path}>{detail.project_path}</div>
          <div style="color: {scannerColor(detail.status)}">{detail.status}</div>
          <div class="text-ink-muted">{fmtShort(detail.started_at)}</div>
          <div class="text-ink-muted tabular-nums">{fmtDuration()}</div>
        </div>
        <button
          type="button"
          class="w-full px-3 py-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-left hover:bg-surface-elevated transition-colors"
          on:click={() => (scannersExpanded = !scannersExpanded)}
          aria-expanded={scannersExpanded}
        >
          <span class="text-[10px] uppercase tracking-[0.14em] text-ink-muted">Scanners</span>
          <svg class="h-3 w-3 text-ink-muted transition-transform duration-150 {scannersExpanded ? '' : '-rotate-90'}" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M3 4.5l3 3 3-3" stroke-linecap="round" />
          </svg>
          {#each codeScanners as s (s.kind)}
            <span
              class="truncate"
              style="color: {scannerColor(s.status)}"
              title={s.error_message ?? s.status}
            >{s.status === 'completed' ? '✓' : s.status === 'failed' ? '✗' : s.status === 'running' ? '▸' : '·'} {s.kind}</span>
          {/each}
          {#if codeScanners.length > 0 && imageScanners.length > 0}
            <span class="text-ink-muted">|</span>
          {/if}
          {#each imageScanners as s (s.kind)}
            <span
              class="truncate"
              style="color: {scannerColor(s.status)}"
              title={s.error_message ?? s.status}
            >{s.status === 'completed' ? '✓' : s.status === 'failed' ? '✗' : s.status === 'running' ? '▸' : '·'} {s.kind}</span>
          {/each}
          {#if codeScanners.length === 0 && imageScanners.length === 0}
            <span class="text-ink-muted">no scanners yet</span>
          {/if}
        </button>
        {#if scannersExpanded && detail}
          {@const allScanners = [...detail.scanner_status].sort((a, b) => a.kind.localeCompare(b.kind))}
          <div class="border-t border-line-hairline">
            <div class="grid grid-cols-[minmax(0,1.1fr)_minmax(0,2fr)_110px_90px] gap-3 px-3 py-1.5 bg-surface-inset text-[10px] uppercase tracking-[0.14em] text-ink-muted items-center">
              <div>Scanner</div>
              <div>Description</div>
              <div>Level</div>
              <div class="text-right">Status</div>
            </div>
            {#each allScanners as s (s.kind)}
              <div
                class="grid grid-cols-[minmax(0,1.1fr)_minmax(0,2fr)_110px_90px] gap-3 px-3 py-1.5 items-center border-t border-line-hairline first:border-t-0"
                title={s.error_message ?? ''}
              >
                <span class="text-ink-primary truncate">{s.kind}</span>
                <span class="text-ink-muted truncate">{SCANNER_DESCRIPTIONS[s.kind] ?? '·'}</span>
                <span class="text-ink-muted">{scanLevel(s.kind)}</span>
                <span class="text-right" style="color: {scannerColor(s.status)}">{s.status}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    </section>

    {#if findings}
      <section>
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-2.5">
          Findings · {findings.total}
        </div>
        <FindingsTable findings={findings.findings} total={findings.total} bySeverity={findings.by_severity} {repo} {commit} />
      </section>
    {/if}
  </div>
{/if}
