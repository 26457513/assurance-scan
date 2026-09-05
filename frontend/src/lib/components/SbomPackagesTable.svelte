<script lang="ts">
  import { api } from '$lib/api';
  import { severityMeta } from '$lib/state';
  import type { FindingResponse, SbomPackage, SbomPackageListResponse } from '$lib/types';

  export let inventory: SbomPackageListResponse;
  export let runId: string;

  type PackageStatus = SbomPackageListResponse['packages'][number]['security_status'];

  let query = '';
  let activeStatus: PackageStatus | null = null;
  let expandedPackageKey: string | null = null;
  let loadingPackageKey: string | null = null;
  let detailError: string | null = null;
  let findingCache: Record<number, FindingResponse> = {};
  $: normalizedQuery = query.trim().toLowerCase();
  $: statusCounts = inventory.packages.reduce<Record<PackageStatus, number>>(
    (counts, item) => {
      counts[item.security_status] += 1;
      return counts;
    },
    { failing: 0, finding: 0, clear: 0, not_assessed: 0 }
  );
  $: packages = inventory.packages.filter((item) => {
    const matchesStatus = activeStatus === null || item.security_status === activeStatus;
    const matchesQuery = !normalizedQuery ||
      [item.name, item.version, item.ecosystem, item.component_type, item.purl, ...item.licenses]
        .some((value) => value?.toLowerCase().includes(normalizedQuery));
    return matchesStatus && matchesQuery;
  });

  const statusLabel = {
    failing: 'Failing',
    finding: 'Finding',
    clear: 'Clear',
    not_assessed: 'Not assessed'
  } as const;

  const statusColor = {
    failing: 'var(--state-failed)',
    finding: 'var(--state-pending)',
    clear: 'var(--state-passed)',
    not_assessed: 'var(--state-untested)'
  } as const;

  const statusOrder: PackageStatus[] = ['failing', 'finding', 'clear', 'not_assessed'];

  function packageKey(item: SbomPackage): string {
    return item.bom_ref ?? item.purl ?? `${item.name}:${item.version ?? ''}:${item.ecosystem ?? ''}`;
  }

  function packageFindings(item: SbomPackage): FindingResponse[] {
    return item.finding_ids.flatMap((findingId) => findingCache[findingId] ?? []);
  }

  async function togglePackage(item: SbomPackage) {
    const key = packageKey(item);
    if (expandedPackageKey === key) {
      expandedPackageKey = null;
      detailError = null;
      return;
    }
    expandedPackageKey = key;
    detailError = null;
    const missingIds = item.finding_ids.filter((findingId) => !findingCache[findingId]);
    if (missingIds.length === 0) return;

    loadingPackageKey = key;
    try {
      const loaded = await Promise.all(
        missingIds.map((findingId) => api.getFinding(runId, findingId))
      );
      findingCache = {
        ...findingCache,
        ...Object.fromEntries(loaded.map((finding) => [finding.id, finding]))
      };
    } catch {
      if (expandedPackageKey === key) {
        detailError = 'Finding details could not be loaded. Try again.';
      }
    } finally {
      if (loadingPackageKey === key) loadingPackageKey = null;
    }
  }

  function actionLabel(finding: FindingResponse): string {
    return finding.fix_strategy === 'dependency-update'
      ? 'Upgrade this dependency.'
      : 'Review the advisory and package configuration.';
  }
</script>

<div class="mb-2.5 space-y-2">
  <div class="flex items-center justify-between gap-3">
    <label class="relative block w-full max-w-sm">
      <span class="sr-only">Search packages</span>
      <input
        bind:value={query}
        type="search"
        placeholder="Search package, version, ecosystem or licence"
        class="w-full rounded-sm border border-line-hairline bg-surface-inset px-3 py-2 font-mono text-[11px] text-ink-primary outline-none focus:border-accent"
      />
    </label>
    <span class="whitespace-nowrap font-mono text-[11px] text-ink-muted">{packages.length} of {inventory.total}</span>
  </div>
  <div class="flex flex-wrap items-center gap-1.5" aria-label="Filter packages by status">
    <button
      type="button"
      aria-pressed={activeStatus === null}
      on:click={() => (activeStatus = null)}
      class="rounded-sm border px-2 py-1 font-mono text-[11px] transition-colors"
      class:border-line-strong={activeStatus === null}
      class:text-ink-primary={activeStatus === null}
      class:border-line-hairline={activeStatus !== null}
      class:text-ink-muted={activeStatus !== null}
    >All ({inventory.total})</button>
    {#each statusOrder as status (status)}
      <button
        type="button"
        aria-pressed={activeStatus === status}
        on:click={() => (activeStatus = activeStatus === status ? null : status)}
        class="rounded-sm border px-2 py-1 font-mono text-[11px] transition-colors"
        class:border-line-strong={activeStatus === status}
        class:border-line-hairline={activeStatus !== status}
        style="color: {statusColor[status]}"
      >{statusLabel[status]} ({statusCounts[status]})</button>
    {/each}
  </div>
</div>

<div class="border border-line-hairline rounded-sm overflow-x-auto bg-surface-panel font-mono text-[11px]">
  <div class="grid min-w-[1040px] grid-cols-[minmax(180px,1.4fr)_120px_100px_90px_minmax(140px,1fr)_110px_90px_70px] gap-3 px-3 py-2 bg-surface-inset border-b border-line-hairline text-[10px] text-ink-muted items-center">
    <div>Package</div>
    <div>Version</div>
    <div>Ecosystem</div>
    <div>Type</div>
    <div>Licence</div>
    <div>Status</div>
    <div>Highest</div>
    <div class="text-right">Findings</div>
  </div>
  {#each packages as item (packageKey(item))}
    <div class="grid min-w-[1040px] grid-cols-[minmax(180px,1.4fr)_120px_100px_90px_minmax(140px,1fr)_110px_90px_70px] gap-3 px-3 py-2 border-b border-line-hairline last:border-b-0 items-center">
      <div class="text-ink-primary truncate" title={item.purl ?? item.name}>{item.name}</div>
      <div class="text-ink-muted truncate" title={item.version ?? ''}>{item.version ?? '—'}</div>
      <div class="text-ink-muted">{item.ecosystem ?? '—'}</div>
      <div class="text-ink-muted">{item.component_type ?? '—'}</div>
      <div class="text-ink-muted truncate" title={item.licenses.join(', ')}>{item.licenses.join(', ') || 'Not declared'}</div>
      <div style="color: {statusColor[item.security_status]}">{statusLabel[item.security_status]}</div>
      <div class="text-ink-muted">{item.highest_severity ?? '—'}</div>
      <div class="text-right tabular-nums">
        {#if item.finding_ids.length > 0}
          <button
            type="button"
            aria-label={`${expandedPackageKey === packageKey(item) ? 'Hide' : 'Show'} findings for ${item.name}`}
            aria-expanded={expandedPackageKey === packageKey(item)}
            on:click={() => togglePackage(item)}
            class="inline-flex min-w-10 items-center justify-end gap-1 rounded-sm text-state-failed outline-none focus-visible:ring-1 focus-visible:ring-accent"
          >{item.finding_count}<span aria-hidden="true">{expandedPackageKey === packageKey(item) ? '▴' : '▾'}</span></button>
        {:else}
          <span class="text-ink-muted">{item.finding_count}</span>
        {/if}
      </div>
    </div>
    {#if expandedPackageKey === packageKey(item)}
      <div class="min-w-[1040px] border-b border-line-hairline bg-surface-inset px-3 py-3">
        {#if loadingPackageKey === packageKey(item)}
          <p class="text-ink-muted">Loading finding evidence…</p>
        {:else if detailError}
          <p class="text-state-failed">{detailError}</p>
        {:else}
          <div class="grid gap-2">
            {#each packageFindings(item) as finding (finding.id)}
              <article
                class="border-l-2 bg-surface-panel px-3 py-2.5"
                style="border-color: {severityMeta(finding.severity).color}"
              >
                <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <strong style="color: {severityMeta(finding.severity).color}">{finding.severity}</strong>
                  <span class="text-ink-primary">{finding.rule_id ?? 'Package finding'}</span>
                  <span class="text-ink-muted">{finding.scanner_kind}</span>
                </div>
                <p class="mt-1 max-w-[80ch] font-sans text-[12px] leading-5 text-ink-secondary">{finding.message}</p>
                <div class="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-ink-muted">
                  <span>Location: {finding.file_path ?? 'package metadata'}</span>
                  <span>Action: {actionLabel(finding)}</span>
                </div>
              </article>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  {:else}
    <div class="px-3 py-8 text-center text-ink-muted">
      {normalizedQuery || activeStatus ? 'No packages match these filters.' : 'The SBOM contains no package components.'}
    </div>
  {/each}
</div>
<p class="mt-2 text-[11px] text-ink-muted">
  Clear means Grype completed and no structured package finding matched this component. Not assessed means that assurance could not be established. All findings remain available under Findings.
</p>
