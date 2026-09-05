<script lang="ts">
  import type { SbomPackageListResponse } from '$lib/types';

  export let inventory: SbomPackageListResponse;

  let query = '';
  $: normalizedQuery = query.trim().toLowerCase();
  $: packages = normalizedQuery
    ? inventory.packages.filter((item) =>
        [item.name, item.version, item.ecosystem, item.component_type, item.purl, ...item.licenses]
          .some((value) => value?.toLowerCase().includes(normalizedQuery)))
    : inventory.packages;

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
</script>

<div class="mb-2.5 flex items-center justify-between gap-3">
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
  {#each packages as item (item.bom_ref ?? `${item.name}:${item.version ?? ''}`)}
    <div class="grid min-w-[1040px] grid-cols-[minmax(180px,1.4fr)_120px_100px_90px_minmax(140px,1fr)_110px_90px_70px] gap-3 px-3 py-2 border-b border-line-hairline last:border-b-0 items-center">
      <div class="text-ink-primary truncate" title={item.purl ?? item.name}>{item.name}</div>
      <div class="text-ink-muted truncate" title={item.version ?? ''}>{item.version ?? '—'}</div>
      <div class="text-ink-muted">{item.ecosystem ?? '—'}</div>
      <div class="text-ink-muted">{item.component_type ?? '—'}</div>
      <div class="text-ink-muted truncate" title={item.licenses.join(', ')}>{item.licenses.join(', ') || 'Not declared'}</div>
      <div style="color: {statusColor[item.security_status]}">{statusLabel[item.security_status]}</div>
      <div class="text-ink-muted">{item.highest_severity ?? '—'}</div>
      <div class="text-right tabular-nums" class:text-state-failed={item.finding_count > 0} class:text-ink-muted={item.finding_count === 0}>{item.finding_count}</div>
    </div>
  {:else}
    <div class="px-3 py-8 text-center text-ink-muted">
      {normalizedQuery ? 'No packages match this search.' : 'The SBOM contains no package components.'}
    </div>
  {/each}
</div>
<p class="mt-2 text-[11px] text-ink-muted">
  Clear means Grype completed and no structured package finding matched this component. Not assessed means that assurance could not be established. Full details remain under Findings.
</p>
