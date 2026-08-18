<script lang="ts">
  import SeverityBadge from './SeverityBadge.svelte';
  import { api } from '$lib/api';
  import type { FindingResponse } from '$lib/types';

  export let findings: FindingResponse[] = [];
  export let total = 0;
  export let bySeverity: Record<string, number> = {};
  // GitHub CI runs only: enables the source-peek code context.
  export let repo: string | null = null;
  export let commit: string | null = null;

  let activeSeverity: string | null = null;
  let expandedId: number | null = null;
  let groupMode = true;
  // Groups render closed by default; users open the files they care about.
  let expandedGroups = new Set<string>();

  const SEV_WEIGHT: Record<string, number> = {
    CRITICAL: 5, HIGH: 4, MEDIUM: 3, LOW: 2, INFO: 1, UNKNOWN: 0
  };

  function worstSev(fs: FindingResponse[]): string {
    return fs.reduce((a, f) => (SEV_WEIGHT[f.severity] ?? 0) > (SEV_WEIGHT[a] ?? 0) ? f.severity : a, 'UNKNOWN');
  }

  type Peek = { lines: { n: number; text: string }[]; highlight: number } | { unavailable: true };
  let peek: Peek | null = null;
  let peekLoading = false;
  const peekCache = new Map<number, Peek>();

  $: severities = Object.keys(bySeverity).filter((s) => bySeverity[s] > 0);
  $: filtered = activeSeverity ? findings.filter((f) => f.severity === activeSeverity) : findings;

  type Group = { key: string; fs: FindingResponse[]; worst: string };
  $: groups = (() => {
    if (!groupMode) return null;
    const by = new Map<string, FindingResponse[]>();
    for (const f of filtered) {
      const key = f.file_path || '(no location)';
      const list = by.get(key);
      if (list) list.push(f);
      else by.set(key, [f]);
    }
    const out: Group[] = [...by.entries()].map(([key, fs]) => ({ key, fs, worst: worstSev(fs) }));
    out.sort((a, b) => (SEV_WEIGHT[b.worst] ?? 0) - (SEV_WEIGHT[a.worst] ?? 0) || b.fs.length - a.fs.length);
    return out;
  })();

  type RenderRow = { type: 'group'; g: Group } | { type: 'finding'; f: FindingResponse };
  $: renderRows = (() => {
    if (!groups) return filtered.map((f) => ({ type: 'finding', f }) as RenderRow);
    const rows: RenderRow[] = [];
    for (const g of groups) {
      rows.push({ type: 'group', g });
      if (expandedGroups.has(g.key)) for (const f of g.fs) rows.push({ type: 'finding', f });
    }
    return rows;
  })();

  function toggleGroup(key: string) {
    if (expandedGroups.has(key)) expandedGroups.delete(key);
    else expandedGroups.add(key);
    expandedGroups = expandedGroups;
  }

  function toggle(f: FindingResponse) {
    expandedId = expandedId === f.id ? null : f.id;
    peek = null;
    if (expandedId === f.id && repo && commit && f.file_path) loadPeek(f);
  }

  async function loadPeek(f: FindingResponse) {
    if (peekCache.has(f.id)) {
      peek = peekCache.get(f.id)!;
      return;
    }
    peekLoading = true;
    try {
      const res = await api.githubSource(repo!, commit!, f.file_path!, f.line_start);
      const value: Peek = res.unavailable
        ? { unavailable: true }
        : { lines: res.lines ?? [], highlight: res.highlight ?? 0 };
      peekCache.set(f.id, value);
      peek = value;
    } catch {
      peek = { unavailable: true };
    } finally {
      peekLoading = false;
    }
  }

  const COLS = 'grid-cols-[72px_110px_minmax(0,1fr)_minmax(150px,240px)_20px]';

  // Severity as compact colored text — the pill badges eat space.
  const SEV_COLOR: Record<string, string> = {
    CRITICAL: 'var(--state-failed)',
    HIGH: 'var(--state-failed)',
    MEDIUM: 'var(--state-pending)',
    LOW: 'var(--ink-muted)',
    INFO: 'var(--ink-muted)',
    UNKNOWN: 'var(--ink-muted)'
  };
</script>

<div>
  <div class="flex items-center gap-1.5 mb-3 flex-wrap">
    <button
      type="button"
      on:click={() => (groupMode = false)}
      class="font-mono text-[11px] px-2 py-1 rounded-sm border transition-colors"
      class:border-line-strong={!groupMode}
      class:text-ink-primary={!groupMode}
      class:border-line-hairline={groupMode}
      class:text-ink-muted={groupMode}
    >Flat</button>
    <button
      type="button"
      on:click={() => (groupMode = true)}
      class="font-mono text-[11px] px-2 py-1 rounded-sm border transition-colors mr-2"
      class:border-line-strong={groupMode}
      class:text-ink-primary={groupMode}
      class:border-line-hairline={!groupMode}
      class:text-ink-muted={!groupMode}
    >By file</button>

  {#if severities.length > 0}
    <div class="flex items-center gap-1.5 flex-wrap">
      <button
        type="button"
        on:click={() => (activeSeverity = null)}
        class="font-mono text-[11px] px-2 py-1 rounded-sm border transition-colors"
        class:border-line-strong={activeSeverity === null}
        class:text-ink-primary={activeSeverity === null}
        class:border-line-hairline={activeSeverity !== null}
        class:text-ink-muted={activeSeverity !== null}
      >All ({total})</button>
      {#each severities as sev (sev)}
        <button
          type="button"
          on:click={() => (activeSeverity = activeSeverity === sev ? null : sev)}
          class="font-mono text-[11px] px-2 py-1 rounded-sm border transition-colors"
          class:border-line-strong={activeSeverity === sev}
          class:border-line-hairline={activeSeverity !== sev}
        >
          <SeverityBadge severity={sev} count={bySeverity[sev]} />
        </button>
      {/each}
    </div>
  {/if}
  </div>

  <div class="border border-line-hairline rounded-sm overflow-hidden bg-surface-panel">
    <div class="grid {COLS} gap-3 px-3 py-2 bg-surface-inset border-b border-line-hairline text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted items-center">
      <div>Sev</div>
      <div>Scanner</div>
      <div>Message</div>
      <div>Location</div>
      <div></div>
    </div>

    {#each renderRows as row (row.type === 'group' ? 'g:' + row.g.key : 'f:' + row.f.id)}
      {#if row.type === 'group'}
        <button
          type="button"
          on:click={() => toggleGroup(row.g.key)}
          class="w-full flex items-center gap-3 px-3 py-2 bg-surface-inset border-b border-line-hairline hover:bg-surface-elevated transition-colors"
        >
          <svg class="h-3 w-3 text-ink-muted transition-transform duration-150 {expandedGroups.has(row.g.key) ? '' : '-rotate-90'}" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M3 4.5l3 3 3-3" stroke-linecap="round" />
          </svg>
          <span class="font-mono text-[11px] text-ink-primary truncate flex-1 text-left">{row.g.key}</span>
          <span class="font-mono text-[10px] text-ink-muted tabular-nums shrink-0">{row.g.fs.length}</span>
          <span class="font-mono text-[10px] font-semibold tracking-[0.04em] shrink-0" style="color:{SEV_COLOR[row.g.worst] ?? 'var(--ink-muted)'}">{row.g.worst}</span>
        </button>
      {:else}
      {@const f = row.f}
      <div class="border-b border-line-hairline last:border-0">
        <button
          type="button"
          on:click={() => toggle(f)}
          class="w-full text-left grid {COLS} gap-3 px-3 py-2 hover:bg-surface-elevated transition-colors items-center"
        >
          <div class="font-mono text-[10px] font-semibold tracking-[0.04em] truncate" style="color:{SEV_COLOR[f.severity] ?? 'var(--ink-muted)'}">{f.severity}</div>
          <div class="font-mono text-[11px] text-ink-secondary truncate">{f.scanner_kind}</div>
          <div class="text-[12px] text-ink-primary truncate" title={f.message}>{f.message}</div>
          <div class="font-mono text-[11px] text-ink-muted truncate" title={f.file_path ?? ''}>
            {#if f.file_path}{f.file_path}{#if f.line_start}:{f.line_start}{/if}{:else}—{/if}
          </div>
          <div class="text-ink-muted flex items-center justify-center">
            <svg class="h-3 w-3 transition-transform duration-150 {expandedId === f.id ? 'rotate-180' : ''}" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M3 4.5l3 3 3-3" stroke-linecap="round" />
            </svg>
          </div>
        </button>
      {#if expandedId === f.id}
          <div class="px-3 py-4 bg-surface-inset border-t border-line-hairline">
            <dl class="grid grid-cols-[100px_minmax(0,1fr)] gap-x-4 gap-y-2.5">
              {#if f.rule_id}
                <dt class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted pt-[3px]">rule</dt>
                <dd class="font-mono text-[11px] text-ink-secondary break-all">{f.rule_id}</dd>
              {/if}
              {#if f.theme}
                <dt class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted pt-[3px]">theme</dt>
                <dd class="text-[12px] text-ink-primary break-words">{f.theme}</dd>
              {/if}
              {#if f.fix_strategy}
                <dt class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted pt-[3px]">fix strategy</dt>
                <dd class="font-mono text-[11px] text-ink-secondary">{f.fix_strategy}</dd>
              {/if}
              {#if f.compliance_tags.length > 0}
                <dt class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted pt-[3px]">tags</dt>
                <dd class="text-[11px] text-ink-secondary break-words leading-[1.6]">{f.compliance_tags.join('  ·  ')}</dd>
              {/if}
            </dl>
            {#if repo && commit && f.file_path}
              <div class="mt-3">
                {#if peekLoading}
                  <div class="font-mono text-[11px] text-ink-muted">loading source…</div>
                {:else if peek && 'unavailable' in peek}
                  <div class="font-mono text-[11px] text-ink-muted">source unavailable</div>
                {:else if peek}
                  <div class="border border-line-hairline rounded-sm overflow-hidden bg-surface-base font-mono text-[11px] leading-[1.7]">
                    {#each peek.lines as l (l.n)}
                      <div
                        class="flex"
                        class:bg-accent-subtle={l.n === peek.highlight}
                        style={l.n === peek.highlight ? 'box-shadow: inset 2px 0 0 var(--state-failed);' : ''}
                      >
                        <span class="w-12 shrink-0 text-right pr-3 text-ink-muted select-none tabular-nums">{l.n}</span>
                        <span class="whitespace-pre overflow-x-auto flex-1 pr-3 {l.n === peek.highlight ? 'text-ink-primary' : 'text-ink-secondary'}">{l.text}</span>
                      </div>
                    {/each}
                  </div>
                {/if}
              </div>
            {/if}
          </div>
      {/if}
      </div>
      {/if}
    {:else}
      <div class="px-3 py-8 text-center text-[12px] text-ink-muted font-mono">no findings</div>
    {/each}
  </div>
</div>
