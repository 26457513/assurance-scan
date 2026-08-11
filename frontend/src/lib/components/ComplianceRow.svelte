<script lang="ts">
  import StatePill from './StatePill.svelte';
  import type { ComplianceRow as ComplianceRowT } from '$lib/types';

  export let row: ComplianceRowT;
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

  $: confidenceColor =
    row.confidence === 'high'
      ? 'var(--state-passed)'
      : row.confidence === 'medium'
        ? 'var(--state-pending)'
        : 'var(--state-untested)';

  const COLS = 'grid-cols-[120px_70px_minmax(0,1fr)_50px_60px_80px_auto_24px]';
  const DL_COLS = 'grid-cols-[120px_minmax(0,1fr)]';
</script>

<div class="border-b border-line-hairline last:border-0">
  <div
    class="grid {COLS} gap-3 px-4 py-2 hover:bg-surface-elevated transition-colors items-center cursor-pointer"
    on:click={toggle}
    on:keydown={onKeydown}
    role="button"
    tabindex="0"
  >
    <div class="font-mono text-[11px] text-ink-muted truncate" title={row.row_id}>{row.row_id}</div>
    <div class="font-mono text-[11px] text-ink-muted truncate">{row.section || '—'}</div>
    <div class="text-[13px] text-ink-primary truncate" title={row.title}>{row.title || row.row_id}</div>
    <div class="font-mono text-[10px] text-ink-muted">
      {#if row.fr_ids.some((f) => f.includes('IMAGE-VULN') || f.includes('FS-VULN'))}
        {#if row.fr_ids.some((f) => !f.includes('IMAGE-VULN') && !f.includes('FS-VULN'))}both{:else}image{/if}
      {:else}
        code
      {/if}
    </div>
    <div class="font-mono text-[11px] text-ink-secondary tabular-nums text-right" title={`${row.fr_ids.length} FR${row.fr_ids.length === 1 ? '' : 's'}`}>
      {row.fr_ids.length}
    </div>
    <div class="font-mono text-[10px] uppercase tracking-[0.1em]" style="color: {confidenceColor}">{row.confidence}</div>
    <div class="flex justify-end"><StatePill state={row.worst_state} size="sm" /></div>
    <div class="text-ink-muted flex items-center justify-center">
      <svg class="h-3 w-3 transition-transform duration-150 {expanded ? 'rotate-180' : ''}" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M3 4.5l3 3 3-3" stroke-linecap="round" />
      </svg>
    </div>
  </div>
  {#if expanded}
    <div class="px-4 py-4 bg-surface-inset border-t border-line-hairline">
      <dl class="grid {DL_COLS} gap-x-4 gap-y-2.5">
        {#if row.description}
          <dt class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted pt-[3px]">description</dt>
          <dd class="text-[12px] text-ink-primary leading-[1.6] break-words">{row.description}</dd>
        {/if}

        <dt class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted pt-[3px]">rationale</dt>
        <dd class="text-[12px] text-ink-primary leading-[1.6] break-words">{row.rationale}</dd>

        {#if row.fr_ids.length > 0}
          <dt class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted pt-[3px]">FRs</dt>
          <dd class="font-mono text-[11px] text-ink-secondary break-words">
            {#each row.fr_ids as fid, i (fid)}{#if i > 0}<span class="text-ink-muted mx-1">·</span>{/if}<a href={`/frs/${fid}`} class="hover:text-accent">{fid}</a>{/each}
          </dd>
        {/if}
      </dl>
    </div>
  {/if}
</div>
