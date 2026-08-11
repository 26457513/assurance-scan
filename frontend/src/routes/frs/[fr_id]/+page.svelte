<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import { selectedScanRunId } from '$lib/stores/selectedScan';
  import StatePill from '$lib/components/StatePill.svelte';
  import type { FrDetailResponse, FrHistoryResponse, TestSpecWithResult } from '$lib/types';

  let detail: FrDetailResponse | null = null;
  let history: FrHistoryResponse | null = null;
  let loading = true;
  let error: string | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  const frId = $page.params.fr_id ?? '';

  async function refresh() {
    try {
      detail = await api.getFr(frId, $selectedScanRunId ?? undefined);
      history = await api.getFrHistory(frId);
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    refresh();
    pollTimer = setInterval(refresh, 10000);
  });
  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  // Refetch when scan changes
  $: if ($selectedScanRunId) refresh();

  function resultColor(result: string): string {
    return result === 'pass'
      ? 'var(--state-passed)'
      : result === 'fail'
        ? 'var(--state-failed)'
        : 'var(--state-pending)';
  }

  function testTypeLabel(test: TestSpecWithResult): string {
    const bits: string[] = [test.type];
    if (test.scanner) bits.push(test.scanner);
    if (test.severity_floor) bits.push(`≥ ${test.severity_floor}`);
    if (test.rule_pattern) bits.push(`/${test.rule_pattern}/`);
    if (test.name_pattern) bits.push(test.name_pattern);
    if (test.format) bits.push(test.format);
    return bits.join(' · ');
  }
</script>

{#if loading}
  <div class="p-6 text-[12px] text-ink-muted font-mono">Loading…</div>
{:else if error}
  <div class="p-6 text-[12px] text-state-failed font-mono">{error}</div>
{:else if detail}
  <div class="p-6 max-w-4xl">
    <div class="mb-6">
      <a href="/frs" class="text-[11px] font-mono text-ink-muted hover:text-accent transition-colors">← Catalogue</a>
      <h1 class="text-[20px] font-medium tracking-tight text-ink-primary mt-3">{detail.title}</h1>
      <div class="font-mono text-[12px] text-ink-secondary mt-1">{detail.fr_id}</div>
      <div class="flex items-center gap-3 mt-4">
        <StatePill state={detail.state} />
        {#if detail.category}
          <span class="font-mono text-[11px] px-2 py-0.5 rounded-sm border border-line-hairline text-ink-secondary">{detail.category}</span>
        {/if}
        <span class="font-mono text-[11px] text-ink-muted">run <span class="text-ink-secondary">{detail.run_id}</span></span>
      </div>
      {#if detail.description}
        <p class="mt-4 text-[13px] text-ink-secondary leading-relaxed">{detail.description}</p>
      {/if}
    </div>

    <section class="mb-8">
      <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-3">Tests · {detail.tests.length}</div>
      {#if detail.tests.length === 0}
        <div class="border border-line-hairline rounded-sm p-4 bg-surface-inset">
          <div class="text-[12px] text-ink-primary mb-1">No tests defined.</div>
          <div class="text-[12px] text-ink-muted">This FR is <span class="text-ink-secondary">untested</span> — add at least one test (unit-test, scanner-clean, manual-attestation) to the catalogue.</div>
        </div>
      {:else}
        <div class="space-y-1.5">
          {#each detail.tests as test (test.id)}
            <div class="border border-line-hairline rounded-sm p-3 bg-surface-panel">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0 flex-1">
                  <div class="font-mono text-[11px] text-ink-secondary">{test.id}</div>
                  <div class="font-mono text-[11px] text-ink-muted mt-0.5 break-all">{testTypeLabel(test)}</div>
                  {#if test.description}
                    <div class="text-[12px] text-ink-secondary mt-1">{test.description}</div>
                  {/if}
                </div>
                <span class="font-mono text-[12px] whitespace-nowrap" style="color: {resultColor(test.result)}">
                  {test.result}
                </span>
              </div>
              {#if Object.keys(test.detail).length > 0}
                <details class="mt-2">
                  <summary class="text-[11px] text-ink-muted cursor-pointer font-mono">detail</summary>
                  <pre class="text-[11px] font-mono text-ink-secondary bg-surface-inset p-2 rounded-sm mt-1 overflow-x-auto">{JSON.stringify(test.detail, null, 2)}</pre>
                </details>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </section>

    {#if detail.implemented_by.length}
      <section class="mb-6">
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-2">Implemented by</div>
        <div class="font-mono text-[11px] text-ink-secondary space-y-0.5">
          {#each detail.implemented_by as ref}
            <div>{ref.kind}: <span class="text-accent">{ref.ref}</span></div>
          {/each}
        </div>
      </section>
    {/if}

    {#if detail.satisfies.length}
      <section class="mb-6">
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-2">Satisfies</div>
        <div class="flex flex-wrap gap-1">
          {#each detail.satisfies as s}
            <a
              href={`/compliance?framework=${encodeURIComponent(s.ruleset)}`}
              class="font-mono text-[11px] px-2 py-0.5 rounded-sm border border-line-hairline text-ink-secondary hover:text-accent hover:border-line-strong transition-colors"
            >{s.ruleset}:{s.row}</a>
          {/each}
        </div>
      </section>
    {/if}

    {#if detail.depends_on.length}
      <section class="mb-6">
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-2">Depends on</div>
        <div class="flex flex-wrap gap-1">
          {#each detail.depends_on as d}
            <a
              href={`/frs/${d}`}
              class="font-mono text-[11px] px-2 py-0.5 rounded-sm border border-line-hairline text-ink-secondary hover:text-accent hover:border-line-strong transition-colors"
            >{d}</a>
          {/each}
        </div>
      </section>
    {/if}

    {#if Object.keys(detail.reason).length > 0}
      <section class="mb-6">
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-2">Computation reason</div>
        <pre class="text-[11px] font-mono text-ink-secondary bg-surface-inset border border-line-hairline rounded-sm p-3 overflow-x-auto">{JSON.stringify(detail.reason, null, 2)}</pre>
      </section>
    {/if}

    {#if detail.waiver_reason}
      <section class="mb-6">
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-2">Waiver rationale</div>
        <div class="border-l-2 pl-4 py-2" style="border-color: var(--state-waived);">
          <div class="text-[13px] text-ink-primary leading-relaxed">{detail.waiver_reason}</div>
          <div class="flex items-center gap-3 mt-3 font-mono text-[11px] text-ink-muted">
            <span>waived by <span class="text-ink-secondary">{detail.waived_by ?? '—'}</span></span>
            {#if detail.waiver_expires_at}
              <span>· expires {new Date(detail.waiver_expires_at).toLocaleDateString()}</span>
            {:else}
              <span>· standing (no expiry)</span>
            {/if}
          </div>
        </div>
      </section>
    {/if}

    {#if history && history.history.length > 1}
      <section>
        <div class="text-[10px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-2">State across runs</div>
        <div class="border border-line-hairline rounded-sm overflow-hidden bg-surface-panel">
          {#each history.history as h (h.run_id)}
            <div class="grid grid-cols-[minmax(0,200px)_auto_1fr] gap-3 px-3 py-2 border-b border-line-hairline last:border-0 items-center">
              <a href={`/scans/${h.run_id}`} class="font-mono text-[11px] text-ink-secondary hover:text-accent truncate">{h.run_id}</a>
              <StatePill state={h.state} size="sm" />
              <span class="font-mono text-[11px] text-ink-muted text-right">{h.computed_at ? new Date(h.computed_at).toLocaleString() : '—'}</span>
            </div>
          {/each}
        </div>
      </section>
    {/if}
  </div>
{/if}
