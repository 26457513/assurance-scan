<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import FindingsTable from './FindingsTable.svelte';
  import ArtifactsPanel from './ArtifactsPanel.svelte';
  import SbomPackagesTable from './SbomPackagesTable.svelte';
  import ScanOriginBadge from './ScanOriginBadge.svelte';
  import type {
    ArtifactListResponse,
    ScanStatus,
    FindingsListResponse,
    ScanSummary,
    SbomPackageListResponse,
  } from '$lib/types';
  import {
    SCANNER_DESCRIPTIONS,
    scannerCategory,
    summarizeScannerStatuses,
  } from '$lib/scannerDescriptions';

  export let scan: ScanSummary;

  let detail: ScanStatus | null = null;
  let findings: FindingsListResponse | null = null;
  let artifacts: ArtifactListResponse | null = null;
  let inventory: SbomPackageListResponse | null = null;
  let inventoryLoading = false;
  let inventoryError: string | null = null;
  let activeSurface: 'findings' | 'packages' | 'artifacts' = 'findings';
  let loading = true;
  let error: string | null = null;
  let es: EventSource | null = null;

  async function refresh() {
    try {
      [detail, findings, artifacts] = await Promise.all([
        api.getScan(scan.run_id),
        api.listFindings(scan.run_id),
        api.listArtifacts(scan.run_id),
      ]);
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  async function openSurface(surface: typeof activeSurface) {
    activeSurface = surface;
    if (surface !== 'packages' || inventory || inventoryLoading) return;
    const sbomAvailable = artifacts?.artifacts.some((artifact) => artifact.name === 'sbom' && artifact.available);
    if (!sbomAvailable) {
      inventory = { run_id: scan.run_id, total: 0, packages: [] };
      return;
    }
    inventoryLoading = true;
    inventoryError = null;
    try {
      inventory = await api.listSbomPackages(scan.run_id);
    } catch (e) {
      inventoryError = String(e);
    } finally {
      inventoryLoading = false;
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

  $: scannerSummary = summarizeScannerStatuses(detail?.scanner_status ?? []);
  $: scannerStatuses = (detail?.scanner_status ?? [])
    .filter((status) => scannerCategory(status.kind) !== 'artifact')
    .sort((left, right) => left.kind.localeCompare(right.kind));
  $: artifactStatuses = (detail?.scanner_status ?? [])
    .filter((status) => scannerCategory(status.kind) === 'artifact')
    .sort((left, right) => left.kind.localeCompare(right.kind));
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
          <div class="flex items-center gap-2 text-ink-muted truncate">
            <span>#{detail.project_id}</span><ScanOriginBadge origin={detail.origin} />
          </div>
          <div style="color: {scannerColor(detail.status)}">{detail.status}</div>
          <div class="text-ink-muted">{fmtShort(detail.started_at)}</div>
          <div class="text-ink-muted tabular-nums">{fmtDuration()}</div>
        </div>
        <button
          type="button"
          class="w-full min-w-0 px-3 py-2 grid grid-cols-[auto_auto_minmax(0,1fr)_auto] items-center gap-3 text-left hover:bg-surface-elevated transition-colors"
          on:click={() => (scannersExpanded = !scannersExpanded)}
          aria-expanded={scannersExpanded}
        >
          <span class="text-[10px] uppercase tracking-[0.14em] text-ink-muted">Scanners</span>
          <svg class="h-3 w-3 text-ink-muted transition-transform duration-150 {scannersExpanded ? '' : '-rotate-90'}" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M3 4.5l3 3 3-3" stroke-linecap="round" />
          </svg>
          <span class="min-w-0 flex items-center gap-4 overflow-hidden whitespace-nowrap">
            {#if scannerSummary.total === 0}
              <span class="text-ink-muted">no scanners yet</span>
            {:else}
              <span style="color: var(--state-passed)">✓ {scannerSummary.completed} complete</span>
              {#if scannerSummary.failed > 0}
                <span style="color: var(--state-failed)">✕ {scannerSummary.failed} failed</span>
              {/if}
              {#if scannerSummary.running > 0}
                <span style="color: var(--accent)">▸ {scannerSummary.running} running</span>
              {/if}
              {#if scannerSummary.pending > 0}
                <span class="text-ink-muted">· {scannerSummary.pending} pending</span>
              {/if}
            {/if}
          </span>
          {#if scannerSummary.artifactTotal > 0}
            <span class="whitespace-nowrap border-l border-line-hairline pl-3 text-ink-muted">
              {scannerSummary.artifactCompleted}/{scannerSummary.artifactTotal} artifacts
            </span>
          {/if}
        </button>
        {#if scannersExpanded && detail}
          <div class="border-t border-line-hairline">
            <div class="px-3 py-1.5 bg-surface-inset text-[10px] text-ink-muted">
              Scanners ({scannerStatuses.length})
            </div>
            <div class="grid grid-cols-[minmax(0,1.1fr)_minmax(0,2fr)_110px_70px_90px] gap-3 px-3 py-1.5 bg-surface-inset text-[10px] uppercase tracking-[0.14em] text-ink-muted items-center">
              <div>Scanner</div>
              <div>Description</div>
              <div>Type</div>
              <div class="text-right">s</div>
              <div class="text-right">Status</div>
            </div>
            {#each scannerStatuses as s (s.kind)}
              <div
                class="grid grid-cols-[minmax(0,1.1fr)_minmax(0,2fr)_110px_70px_90px] gap-3 px-3 py-1.5 items-center border-t border-line-hairline first:border-t-0"
                title={s.error_message ?? ''}
              >
                <span class="text-ink-primary truncate">{s.kind}</span>
                <span class="text-ink-muted truncate" title={SCANNER_DESCRIPTIONS[s.kind] ?? ''}>{SCANNER_DESCRIPTIONS[s.kind] ?? '·'}</span>
                <span class="text-ink-muted">{scannerCategory(s.kind)}</span>
                <span class="text-right text-ink-muted tabular-nums">{s.duration_seconds ?? '·'}</span>
                <span class="text-right" style="color: {scannerColor(s.status)}">{s.status}</span>
              </div>
            {/each}
            {#if artifactStatuses.length > 0}
              <div class="px-3 py-1.5 border-t border-line-hairline bg-surface-inset text-[10px] text-ink-muted">
                Generated artifacts ({artifactStatuses.length})
              </div>
              {#each artifactStatuses as artifact (artifact.kind)}
                <div class="grid grid-cols-[minmax(0,1.1fr)_minmax(0,2fr)_110px_70px_90px] gap-3 px-3 py-1.5 items-center border-t border-line-hairline">
                  <span class="text-ink-primary truncate">{artifact.kind.replace('assurance-scan/', '')}</span>
                  <span class="text-ink-muted truncate">{SCANNER_DESCRIPTIONS[artifact.kind] ?? 'generated scan output'}</span>
                  <span class="text-ink-muted">artifact</span>
                  <span class="text-right text-ink-muted">·</span>
                  <span class="text-right" style="color: {scannerColor(artifact.status)}">{artifact.status}</span>
                </div>
              {/each}
            {/if}
          </div>
        {/if}
      </div>
    </section>

    <div class="mb-3 flex items-end gap-5 border-b border-line-hairline" role="tablist" aria-label="Scan evidence">
      <button
        type="button"
        role="tab"
        aria-selected={activeSurface === 'findings'}
        class="border-b-2 px-0.5 pb-2 font-mono text-[11px] transition-colors {activeSurface === 'findings' ? 'border-accent text-ink-primary' : 'border-transparent text-ink-muted hover:text-ink-primary'}"
        on:click={() => openSurface('findings')}
      >Findings <span class="tabular-nums">{findings?.total ?? 0}</span></button>
      <button
        type="button"
        role="tab"
        aria-selected={activeSurface === 'packages'}
        class="border-b-2 px-0.5 pb-2 font-mono text-[11px] transition-colors {activeSurface === 'packages' ? 'border-accent text-ink-primary' : 'border-transparent text-ink-muted hover:text-ink-primary'}"
        on:click={() => openSurface('packages')}
      >Packages {#if inventory}<span class="tabular-nums">{inventory.total}</span>{/if}</button>
      <button
        type="button"
        role="tab"
        aria-selected={activeSurface === 'artifacts'}
        class="border-b-2 px-0.5 pb-2 font-mono text-[11px] transition-colors {activeSurface === 'artifacts' ? 'border-accent text-ink-primary' : 'border-transparent text-ink-muted hover:text-ink-primary'}"
        on:click={() => openSurface('artifacts')}
      >Artifacts <span class="tabular-nums">{artifacts?.artifacts.length ?? 0}</span></button>
    </div>

    {#if activeSurface === 'findings' && findings}
      <section>
        <FindingsTable
          findings={findings.findings}
          total={findings.total}
          bySeverity={findings.by_severity}
          runId={scan.run_id}
        />
      </section>
    {:else if activeSurface === 'packages'}
      <section>
        {#if inventoryLoading}
          <div class="py-8 text-center font-mono text-[11px] text-ink-muted">Loading package inventory…</div>
        {:else if inventoryError}
          <div class="py-8 text-center font-mono text-[11px] text-state-failed">{inventoryError}</div>
        {:else if inventory}
          <SbomPackagesTable {inventory} runId={scan.run_id} />
        {/if}
      </section>
    {:else if activeSurface === 'artifacts' && artifacts}
      <section>
        <ArtifactsPanel {artifacts} />
      </section>
    {/if}
  </div>
{/if}
