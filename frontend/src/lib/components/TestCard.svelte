<script lang="ts">
  import StatePill from './StatePill.svelte';
  import { api } from '$lib/api';
  import type { TestSpecWithResult, TestSourceResponse } from '$lib/types';

  export let test: TestSpecWithResult;
  export let projectId: number | null = null;

  let expanded = false;
  let inputExampleOpen = false;
  let outputExampleOpen = false;
  let actualOutputOpen = true;
  let rawDetailOpen = false;
  let sourceVisible = false;
  let source: TestSourceResponse | null = null;
  let sourceLoading = false;
  let sourceError: string | null = null;

  /**
   * Parse the matcher's `detail` dict into prose. The matcher emits a small
   * set of known shapes (see server/state/matcher.py); when we recognise one,
   * render it as a sentence. Unknown shapes fall back to raw JSON.
   */
  function summarizeDetail(detail: Record<string, unknown> | null): string | null {
    if (!detail || Object.keys(detail).length === 0) return null;

    // Unit/integration/e2e tests — _eval_test_suite
    if ('matched_count' in detail) {
      const total = Number(detail.matched_count);
      if ('failed_count' in detail) {
        const failed = Number(detail.failed_count);
        const passed = total - failed;
        const names = (detail.failed_names as string[] | undefined) ?? [];
        let namesText = '';
        if (names.length > 0) {
          namesText = ': ' + names.join(', ');
          if (failed > names.length) namesText += ` (+${failed - names.length} more)`;
        }
        return `${total} test case${total === 1 ? '' : 's'} ran · ${passed} passed, ${failed} failed${namesText}`;
      }
      return `${total} test case${total === 1 ? '' : 's'} ran · all passed`;
    }

    // Scanner-clean pass — _eval_scanner_clean (clean)
    if ('total_findings' in detail && 'scanner' in detail && !('finding_count' in detail)) {
      const scanner = detail.scanner;
      const total = Number(detail.total_findings);
      return `${scanner}: ${total} finding${total === 1 ? '' : 's'} produced · 0 matched the failure filter`;
    }

    // Scanner-clean fail — _eval_scanner_clean (violations)
    if ('finding_count' in detail && 'scanner' in detail) {
      const scanner = detail.scanner;
      const n = Number(detail.finding_count);
      const rules = (detail.sample_rule_ids as string[] | undefined) ?? [];
      const files = (detail.sample_files as string[] | undefined) ?? [];
      const bits: string[] = [];
      if (rules.length > 0) {
        let r = rules.join(', ');
        if (n > rules.length) r += ` (+${n - rules.length} more)`;
        bits.push(`rules: ${r}`);
      }
      if (files.length > 0) bits.push(`files: ${files.join(', ')}`);
      const tail = bits.length ? ' · ' + bits.join(' · ') : '';
      return `${scanner}: ${n} matching finding${n === 1 ? '' : 's'}${tail}`;
    }

    // Manual attestation — _eval_manual
    if ('attestation_count' in detail) {
      const n = Number(detail.attestation_count);
      return `${n} attestation${n === 1 ? '' : 's'} on file`;
    }

    // Note-only (pending, no name_pattern, unknown type, etc.)
    if ('note' in detail && Object.keys(detail).length === 1) {
      return String(detail.note);
    }

    // Unknown shape — let the caller fall back to raw JSON.
    return null;
  }

  function toggle() {
    expanded = !expanded;
  }

  async function toggleSource() {
    if (sourceVisible) {
      sourceVisible = false;
      return;
    }
    if (projectId == null || !test.name_pattern) return;
    sourceLoading = true;
    sourceError = null;
    try {
      source = await api.getTestSource(test.name_pattern, projectId);
      sourceVisible = true;
    } catch (e) {
      sourceError = String(e);
    } finally {
      sourceLoading = false;
    }
  }

  function resultState(result: string): string {
    if (result === 'pass') return 'passed';
    if (result === 'fail') return 'failed';
    return 'pending';
  }

  const TEST_TYPE_COLORS: Record<string, string> = {
    'unit-test': '#22D3EE',
    'integration-test': '#A78BFA',
    'e2e-test': '#F472B6',
    'scanner-clean': '#FBBF24',
    'scanner-clean-by-rule': '#FB923C',
    'scanner-clean-by-severity': '#FBBF24',
    'scanner-finds': '#FBBF24',
    'manual-attestation': '#9BA1AB',
    'imported': '#5C636F'
  };

  const SIDE_EFFECT_COLORS: Record<string, string> = {
    'none': 'var(--state-untested)',
    'db-write': 'var(--state-pending)',
    'db-read': 'var(--state-passed)',
    'fs-write': 'var(--state-pending)',
    'fs-read': 'var(--state-passed)',
    'docker': '#A78BFA',
    'network': 'var(--state-blocked)',
    'memory': '#22D3EE'
  };

  $: typeColor = TEST_TYPE_COLORS[test.type] ?? 'var(--state-untested)';
  $: hasActualOutput = Object.keys(test.detail || {}).length > 0;
  $: testLevel = (() => {
    if (test.type === 'unit-test' || test.type === 'integration-test' || test.type === 'e2e-test') return 'code';
    if (test.scanner && ['grype', 'trivy-fs', 'syft'].includes(test.scanner)) return 'image';
    return 'code';
  })();
  $: canShowSource = projectId != null && !!test.name_pattern && test.name_pattern.includes('::');
  $: sourceLines = source ? source.content.split('\n') : [];
  $: inputEntries = test.display?.input ? Object.entries(test.display.input) : [];
  $: outputEntries = test.display?.output ? Object.entries(test.display.output) : [];
  $: actualColor = test.result === 'pass' ? 'var(--state-passed)' : test.result === 'fail' ? 'var(--state-failed)' : 'var(--state-pending)';
  $: detailSummary = summarizeDetail(test.detail as Record<string, unknown> | null);
  $: hasRawFallback = detailSummary === null && hasActualOutput;
</script>

<div class="border border-line-hairline rounded-sm bg-surface-base">
  <button
    type="button"
    on:click={toggle}
    class="w-full text-left flex items-center gap-3 px-3 py-2 hover:bg-surface-elevated transition-colors"
  >
    <svg
      class="h-3 w-3 text-ink-muted shrink-0 transition-transform duration-150 {expanded ? 'rotate-90' : ''}"
      viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5"
    >
      <path d="M4.5 3l3 3-3 3" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    <span class="font-mono text-[11px] text-ink-primary shrink-0">{test.id}</span>
    <span
      class="font-mono text-[10px] uppercase tracking-[0.08em] px-1.5 py-0.5 rounded-sm border shrink-0 whitespace-nowrap"
      style="color: {typeColor}; border-color: color-mix(in srgb, {typeColor} 30%, transparent); background: color-mix(in srgb, {typeColor} 8%, transparent);"
    >{test.type}</span>
    <span
      class="font-mono text-[9px] uppercase tracking-wide px-1 py-0.5 rounded-sm border shrink-0"
      style="color: {testLevel === 'image' ? 'var(--state-untested)' : 'var(--accent)'}; border-color: color-mix(in srgb, {testLevel === 'image' ? 'var(--state-untested)' : 'var(--accent)'} 30%, transparent);"
    >{testLevel}</span>
    <span class="flex-1"></span>
    <StatePill state={resultState(test.result)} size="sm" />
  </button>

  {#if expanded}
    <div class="px-3 pb-3 pt-1 border-t border-line-hairline">

      {#if test.description}
        <div class="mt-3 mb-4 text-[12px] text-ink-primary leading-[1.6]">{test.description}</div>
      {/if}

      {#if inputEntries.length > 0 || test.display?.input_example !== undefined}
        <section class="mb-4">
          <div class="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-muted mb-2">Input <span class="normal-case tracking-normal lowercase">(function arguments — contract)</span></div>
          {#if inputEntries.length > 0}
            <dl class="grid grid-cols-[minmax(0,140px)_minmax(0,1fr)] gap-x-3 gap-y-1 mb-2">
              {#each inputEntries as [key, value] (key)}
                <dt class="font-mono text-[11px] text-ink-secondary break-all">{key}</dt>
                <dd class="font-mono text-[11px] text-ink-muted break-words leading-[1.6]">{typeof value === 'string' ? value : JSON.stringify(value)}</dd>
              {/each}
            </dl>
          {/if}
          {#if test.display?.input_example !== undefined}
            <button
              type="button"
              on:click={() => (inputExampleOpen = !inputExampleOpen)}
              class="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-secondary hover:text-accent transition-colors"
            >
              {inputExampleOpen ? '− hide example' : '+ show example payload'}
            </button>
            {#if inputExampleOpen}
              <pre class="font-mono text-[10px] text-ink-secondary bg-surface-inset border border-line-hairline rounded-sm p-2 mt-2 overflow-x-auto leading-[1.5]">{JSON.stringify(test.display?.input_example, null, 2)}</pre>
            {/if}
          {/if}
        </section>
      {/if}

      {#if outputEntries.length > 0 || test.display?.output_example !== undefined}
        <section class="mb-4">
          <div class="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-muted mb-2">Output <span class="text-ink-muted normal-case tracking-normal lowercase">(function return — contract)</span></div>
          {#if outputEntries.length > 0}
            <dl class="grid grid-cols-[minmax(0,140px)_minmax(0,1fr)] gap-x-3 gap-y-1 mb-2">
              {#each outputEntries as [key, value] (key)}
                <dt class="font-mono text-[11px] text-ink-secondary break-all">{key}</dt>
                <dd class="font-mono text-[11px] text-ink-muted break-words leading-[1.6]">{typeof value === 'string' ? value : JSON.stringify(value)}</dd>
              {/each}
            </dl>
          {/if}
          {#if test.display?.output_example !== undefined}
            <button
              type="button"
              on:click={() => (outputExampleOpen = !outputExampleOpen)}
              class="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-secondary hover:text-accent transition-colors"
            >
              {outputExampleOpen ? '− hide example' : '+ show example payload'}
            </button>
            {#if outputExampleOpen}
              <pre class="font-mono text-[10px] text-ink-secondary bg-surface-inset border border-line-hairline rounded-sm p-2 mt-2 overflow-x-auto leading-[1.5]">{JSON.stringify(test.display?.output_example, null, 2)}</pre>
            {/if}
          {/if}
        </section>
      {/if}

      {#if hasActualOutput}
        <section class="mb-4">
          <div class="flex items-center justify-between mb-2">
            <div class="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-muted">Test evaluation <span class="normal-case tracking-normal lowercase">(matcher context — how this spec was evaluated)</span></div>
            <button
              type="button"
              on:click={() => (actualOutputOpen = !actualOutputOpen)}
              class="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-secondary hover:text-accent transition-colors"
            >
              {actualOutputOpen ? '− hide' : '+ show'}
            </button>
          </div>
          {#if actualOutputOpen}
            <div
              class="bg-surface-inset rounded-sm py-2.5 px-3"
              style="border-left: 2px solid {actualColor}; border-top: 1px solid var(--border-hairline); border-right: 1px solid var(--border-hairline); border-bottom: 1px solid var(--border-hairline);"
            >
              {#if detailSummary}
                <div class="text-[12px] text-ink-primary leading-[1.6] break-words">{detailSummary}</div>
                <button
                  type="button"
                  on:click={() => (rawDetailOpen = !rawDetailOpen)}
                  class="mt-2 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-muted hover:text-accent transition-colors"
                >
                  {rawDetailOpen ? '− hide raw' : '+ show raw'}
                </button>
                {#if rawDetailOpen}
                  <pre class="font-mono text-[10px] text-ink-muted mt-2 overflow-x-auto leading-[1.5]">{JSON.stringify(test.detail, null, 2)}</pre>
                {/if}
              {:else}
                <pre class="font-mono text-[10px] text-ink-secondary overflow-x-auto leading-[1.5]">{JSON.stringify(test.detail, null, 2)}</pre>
              {/if}
            </div>
          {/if}
        </section>
      {/if}

      {#if test.display?.side_effect && test.display.side_effect.length > 0}
        <section class="mb-4">
          <div class="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-muted mb-2">Side effect</div>
          <div class="flex flex-wrap gap-1.5">
            {#each test.display.side_effect as effect (effect)}
              {@const color = SIDE_EFFECT_COLORS[effect] ?? 'var(--state-untested)'}
              <span
                class="font-mono text-[10px] uppercase tracking-[0.08em] px-1.5 py-0.5 rounded-sm border whitespace-nowrap"
                style="color: {color}; border-color: color-mix(in srgb, {color} 30%, transparent); background: color-mix(in srgb, {color} 8%, transparent);"
              >{effect}</span>
            {/each}
          </div>
        </section>
      {/if}

      <div class="border-t border-line-hairline pt-3">
        <dl class="grid grid-cols-[110px_minmax(0,1fr)] gap-x-4 gap-y-2">
          <dt class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted pt-[2px]">name pattern</dt>
          <dd class="font-mono text-[11px] text-ink-muted break-all">{test.name_pattern || '—'}</dd>
        </dl>
      </div>

      {#if canShowSource}
        <div class="mt-3 pt-3 border-t border-line-hairline">
          <button
            type="button"
            on:click={toggleSource}
            disabled={sourceLoading}
            class="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-secondary hover:text-accent transition-colors disabled:opacity-50"
          >
            {#if sourceLoading}loading…{:else if sourceVisible}hide source{:else}view source{/if}
          </button>

          {#if sourceError}
            <div class="mt-2 text-[11px] text-state-failed font-mono">{sourceError}</div>
          {/if}

          {#if sourceVisible && source}
            <div class="mt-2">
              <div class="font-mono text-[10px] text-ink-muted mb-1.5">
                {source.path}  ·  {source.line_count} lines  ·  {source.language}
              </div>
              <div class="border border-line-hairline rounded-sm bg-surface-inset max-h-[480px] overflow-auto">
                <pre class="font-mono text-[11px] leading-[1.6] py-2"><code>{#each sourceLines as line, i (i)}<span class="grid grid-cols-[44px_1fr]"><span class="text-ink-muted select-none pr-3 text-right border-r border-line-hairline mr-3">{i + 1}</span><span class="text-ink-secondary whitespace-pre">{line || ' '}</span></span>{/each}</code></pre>
              </div>
            </div>
          {/if}
        </div>
      {/if}
    </div>
  {/if}
</div>
