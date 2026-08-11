<script lang="ts">
  import StatePill from './StatePill.svelte';
  import type { FrListEntry } from '$lib/types';

  export let fr: FrListEntry;
  let expanded = false;

  function toggle() {
    expanded = !expanded;
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggle();
    }
  }

  const COLS = 'grid-cols-[180px_minmax(0,1fr)_40px_60px_auto_24px]';
  const DL_COLS = 'grid-cols-[110px_minmax(0,1fr)]';

  const IMAGE_SCANNERS = ['grype', 'trivy-fs', 'syft'];
  const CODE_SCANNERS = ['semgrep', 'gitleaks', 'trivy-config', 'osv-scanner'];

  function frLevel(fr: FrListEntry): 'code' | 'image' | 'both' {
    // Derive from the FR's test types + scanner fields
    // unit/integration/e2e tests are always code-level
    // scanner-clean tests derive from the scanner field
    const hasCode = true; // all FRs have at least unit tests or code-level scanners
    const hasImage = fr.satisfies?.some((s) => s.row?.includes('IMAGE') || s.row?.includes('FS-VULN'))
      || fr.fr_id.includes('IMAGE-VULN')
      || fr.fr_id.includes('FS-VULN');
    if (hasImage && hasCode) return 'both';
    if (hasImage) return 'image';
    return 'code';
  }
</script>

<div class="border-b border-line-hairline last:border-0">
  <div
    class="grid {COLS} gap-3 px-4 py-2 hover:bg-surface-elevated transition-colors items-center cursor-pointer"
    on:click={toggle}
    on:keydown={onKeydown}
    role="button"
    tabindex="0"
  >
    <div class="font-mono text-[12px] truncate">
      <a
        href={`/frs/${fr.fr_id}`}
        on:click|stopPropagation
        class="text-ink-secondary hover:text-accent transition-colors"
      >{fr.fr_id}</a>
    </div>
    <div class="text-[13px] text-ink-primary truncate" title={fr.title}>{fr.title}</div>
    <div class="font-mono text-[10px] text-ink-muted">{frLevel(fr)}</div>
    <div class="font-mono text-[11px] text-ink-secondary tabular-nums text-right">
      {#if fr.test_count === 0}
        <span class="text-ink-muted">—</span>
      {:else}
        {fr.test_results.pass}/{fr.test_count}
      {/if}
    </div>
    <div class="flex justify-end"><StatePill state={fr.state} size="sm" /></div>
    <div class="text-ink-muted flex items-center justify-center">
      <svg class="h-3 w-3 transition-transform duration-150 {expanded ? 'rotate-180' : ''}" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M3 4.5l3 3 3-3" stroke-linecap="round" />
      </svg>
    </div>
  </div>
  {#if expanded}
    <div class="px-4 py-4 bg-surface-inset border-t border-line-hairline">
      <dl class="grid {DL_COLS} gap-x-4 gap-y-2.5">
        <dt class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted pt-[3px]">tests</dt>
        <dd class="font-mono text-[11px] text-ink-secondary">
          {#if fr.test_count === 0}
            <span class="text-ink-muted">none</span>
          {:else}
            <span class="text-state-passed">{fr.test_results.pass} pass</span>
            <span class="text-ink-muted"> · </span>
            <span class="text-state-failed">{fr.test_results.fail} fail</span>
            {#if fr.test_results.pending > 0}
              <span class="text-ink-muted"> · </span>
              <span class="text-state-pending">{fr.test_results.pending} pending</span>
            {/if}
            <span class="text-ink-muted ml-2">({fr.test_count} total)</span>
          {/if}
        </dd>

        {#if fr.satisfies.length > 0}
          <dt class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted pt-[3px]">satisfies</dt>
          <dd class="font-mono text-[11px] text-ink-secondary break-words">
            {fr.satisfies.map((s) => `${s.ruleset}:${s.row}`).join('  ·  ')}
          </dd>
        {/if}

        {#if fr.depends_on.length > 0}
          <dt class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted pt-[3px]">depends on</dt>
          <dd class="font-mono text-[11px] text-ink-secondary break-words">
            {#each fr.depends_on as d, i (i)}{#if i > 0}<span class="text-ink-muted mx-1">·</span>{/if}<a href={`/frs/${d}`} class="hover:text-accent">{d}</a>{/each}
          </dd>
        {/if}

        {#if fr.waiver_reason}
          <dt class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted pt-[3px]">waived because</dt>
          <dd class="text-[12px] text-ink-primary leading-[1.6] break-words">{fr.waiver_reason}</dd>

          <dt class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted pt-[3px]">waived by</dt>
          <dd class="font-mono text-[11px] text-ink-secondary">
            <span>{fr.waived_by ?? '—'}</span>
            {#if fr.waiver_expires_at}
              <span class="text-ink-muted ml-3">expires {new Date(fr.waiver_expires_at).toLocaleDateString()}</span>
            {:else}
              <span class="text-ink-muted ml-3">standing</span>
            {/if}
          </dd>
        {/if}
      </dl>
    </div>
  {/if}
</div>
