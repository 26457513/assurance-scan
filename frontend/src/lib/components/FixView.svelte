<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import { buildScannerFixPrompt, buildFixPrompts, classifyGap } from '$lib/prompts';
  import FixSection from './FixSection.svelte';
  import StatePill from './StatePill.svelte';
  import CopyButton from './CopyButton.svelte';
  import PromptModal from './PromptModal.svelte';
  import { pushToast } from '$lib/stores/toasts';
  import type {
    FrListResponse,
    FindingsListResponse,
    FindingResponse,
    FindingAcceptance,
    ScanSummary
  } from '$lib/types';

  export let scan: ScanSummary;
  export let showDescription = true;

  let frList: FrListResponse | null = null;
  let findingsResp: FindingsListResponse | null = null;
  let acceptances: FindingAcceptance[] = [];
  let loading = true;
  let error: string | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let selectedFindings: Set<number> = new Set();
  let promptModalOpen = false;
  let promptText = '';
  let promptTitle = '';

  async function refresh() {
    try {
      const [fr, fi, acc] = await Promise.all([
        api.listFRs(scan.project_path),
        api.listFindings(scan.run_id),
        api.listAcceptedFindings(scan.project_path).catch(() => ({ acceptances: [] }))
      ]);
      frList = fr;
      findingsResp = fi;
      acceptances = acc.acceptances || [];
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    refresh();
    pollTimer = setInterval(refresh, 15000);
  });
  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  // Build accepted lookup: (scanner_kind, rule_id) → acceptance record
  let acceptedMap: Map<string, FindingAcceptance> = new Map();
  $: {
    acceptedMap = new Map();
    for (const a of acceptances) {
      if (a.active) acceptedMap.set(`${a.scanner_kind}|${a.rule_id}`, a);
    }
  }

  // HIGH/CRITICAL findings for the triage board
  $: highFindings = (findingsResp?.findings ?? []).filter(
    (f) => f.severity === 'HIGH' || f.severity === 'CRITICAL'
  );

  // FR-level data (for failing-tests + missing-tests sections)
  $: allFrs = frList?.frs ?? [];
  $: failingFrs = allFrs.filter((fr) => classifyGap(fr) === 'failed');
  $: missingFrs = allFrs.filter((fr) => classifyGap(fr) === 'untested');
  $: failingCount = failingFrs.length;
  $: missingCount = missingFrs.length;

  // Step locks (same as before)
  let forceUnlock2 = false;
  let forceUnlock3 = false;
  $: anyFailed = allFrs.some((fr) => fr.state === 'failed');
  $: scannerCount = anyFailed
    ? highFindings.filter((f) => !acceptedMap.has(`${f.scanner_kind}|${f.rule_id || ''}`)).length
    : 0;
  $: step1Done = scannerCount === 0;
  $: step2Done = failingCount === 0;
  $: step2Locked = !step1Done && !forceUnlock2;
  $: step3Locked = (!step1Done || !step2Done) && !forceUnlock3;
  $: currentStep = scannerCount > 0 ? 1 : failingCount > 0 ? 2 : missingCount > 0 ? 3 : 0;
  $: allClear = scannerCount === 0 && failingCount === 0 && missingCount === 0;

  // Prompt builders
  $: scannerPrompt = buildScannerFixPrompt({
    scan,
    findings: highFindings.filter((f) => !acceptedMap.has(`${f.scanner_kind}|${f.rule_id || ''}`)),
    frs: allFrs
  });
  $: frPrompts = buildFixPrompts({ scan, frs: allFrs });

  // Triage board: actionable findings (not accepted)
  $: actionableFindings = highFindings.filter((f) => !acceptedMap.has(`${f.scanner_kind}|${f.rule_id || ''}`));
  $: acceptedFindings = highFindings.filter((f) => acceptedMap.has(`${f.scanner_kind}|${f.rule_id || ''}`));
  $: selectedCount = selectedFindings.size;

  function toggleFinding(id: number) {
    if (selectedFindings.has(id)) selectedFindings.delete(id);
    else selectedFindings.add(id);
    selectedFindings = new Set(selectedFindings);
  }

  function scanLevel(scanner: string): 'code' | 'image' {
    if (['syft', 'grype', 'trivy-fs', 'trivy-image'].includes(scanner)) return 'image';
    return 'code';
  }

  function riskBadge(scanner: string): { label: string; color: string } {
    const level = scanLevel(scanner);
    if (level === 'image') return { label: 'UPSTREAM', color: 'var(--state-untested)' };
    if (scanner === 'semgrep' || scanner === 'gitleaks') return { label: 'REAL THREAT', color: 'var(--state-failed)' };
    if (scanner === 'trivy-config') return { label: 'INFRA', color: 'var(--state-blocked)' };
    return { label: 'UNASSESSED', color: 'var(--state-untested)' };
  }

  function heuristicAdvisory(f: FindingResponse): { fix: string; impact: string } {
    if (f.rule_id?.startsWith('DS-')) return {
      fix: 'Add USER directive to Dockerfile',
      impact: 'Docker socket access requires --group-add plumbing on every docker run'
    };
    if (f.scanner_kind === 'trivy-image') return {
      fix: 'Update Docker base image to a patched version',
      impact: 'May lose auto-update tracking; manual version bump needed'
    };
    if (f.scanner_kind === 'osv-scanner') return {
      fix: 'Upgrade the vulnerable dependency in requirements-server.txt',
      impact: 'Check for version constraints; may require framework upgrade'
    };
    if (f.scanner_kind === 'semgrep' || f.scanner_kind === 'gitleaks') return {
      fix: 'Edit the source file directly',
      impact: 'Low dependency risk — code change only'
    };
    if (f.scanner_kind === 'trivy-config') return {
      fix: 'Update Dockerfile or config file',
      impact: 'Low — config change, no dependency implications'
    };
    return { fix: 'Review finding and apply recommended fix', impact: 'Unknown — assess before applying' };
  }

  // Accept dialog state
  let acceptTarget: FindingResponse | null = null;
  let acceptDialogOpen = false;
  let acceptRationale = '';
  let acceptFixAssessment = '';
  let acceptInvalidation = '';

  function openAcceptDialog(f: FindingResponse) {
    acceptTarget = f;
    const h = heuristicAdvisory(f);
    acceptRationale = '';
    acceptFixAssessment = h.impact;
    acceptInvalidation = '';
    acceptDialogOpen = true;
  }

  async function doAccept() {
    if (!acceptTarget || !acceptRationale.trim()) return;
    try {
      await api.acceptFinding({
        project_path: scan.project_path,
        scanner_kind: acceptTarget.scanner_kind,
        rule_id: acceptTarget.rule_id || '',
        risk_level: 'not-applicable',
        rationale: acceptRationale,
        fix_assessment: acceptFixAssessment || null,
        invalidation_conditions: acceptInvalidation || null,
        accepted_by: 'user'
      });
      pushToast('success', `Accepted ${acceptTarget.rule_id || acceptTarget.scanner_kind}`);
      acceptDialogOpen = false;
      acceptTarget = null;
      await refresh();
    } catch (e) {
      pushToast('error', `Failed to accept: ${e}`);
    }
  }

  async function undoAcceptance(a: FindingAcceptance) {
    try {
      await api.unacceptFinding(a.id);
      pushToast('info', `Re-activated ${a.rule_id}`);
      await refresh();
    } catch (e) {
      pushToast('error', `Failed to undo: ${e}`);
    }
  }

  function generateFixPrompt() {
    const selected = highFindings.filter((f) => selectedFindings.has(f.id) && !acceptedMap.has(`${f.scanner_kind}|${f.rule_id || ''}`));
    if (selected.length === 0) return;
    const lines: string[] = [];
    lines.push(`Fix ${selected.length} HIGH finding${selected.length === 1 ? '' : 's'} for run ${scan.run_id}.`);
    lines.push('');
    lines.push('Use the assurance-scan MCP server (already running). Call get_findings with severity=HIGH to retrieve the full list.');
    lines.push('For each finding below, read the cited file and propose the smallest fix.');
    lines.push('');
    lines.push(`Catalogue: ./fr-catalog.json`);
    lines.push(`Reference run: ${scan.run_id}`);
    lines.push(`Project: ${scan.project_path}`);
    lines.push('');
    lines.push('## Findings to fix');
    const byFile = new Map<string, FindingResponse[]>();
    for (const f of selected) {
      const key = f.file_path || '<unknown>';
      if (!byFile.has(key)) byFile.set(key, []);
      byFile.get(key)!.push(f);
    }
    for (const [file, findings] of byFile) {
      lines.push('');
      lines.push(`### ${file}`);
      findings.forEach((f) => {
        const loc = f.line_start ? `:${f.line_start}` : '';
        lines.push(`- ${f.severity} ${f.rule_id || '(no rule)'} at ${loc}`);
        lines.push(`  ${f.message}`);
      });
    }
    lines.push('');
    lines.push('## Trade-off assessment');
    lines.push('For each finding above, assess:');
    lines.push('1. What the fix involves (package upgrade, code change, config update)');
    lines.push('2. What could break (dependency conflicts, API changes, build failures)');
    lines.push('3. Whether accepting is reasonable for this project\'s deployment model');
    lines.push('');
    lines.push('If accepting is reasonable, note the conditions that would invalidate the acceptance.');
    lines.push('');
    lines.push('After approval: apply the changes, call start_scan, and confirm no HIGH findings remain.');

    promptText = lines.join('\n');
    promptTitle = `Fix ${selected.length} selected finding${selected.length === 1 ? '' : 's'} — paste into Claude Code`;
    promptModalOpen = true;
  }
</script>

<div class="p-6 max-w-5xl">
  {#if showDescription && !allClear}
    <div class="mb-6">
      <div class="text-[12px] text-ink-secondary leading-relaxed max-w-2xl">
        Triage board: review each HIGH finding, accept non-exploitable ones as risks, and generate a
        fix prompt for the rest. Accepted findings persist across scans — undo if the threat model changes.
      </div>
    </div>
  {/if}

  {#if loading}
    <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else if error}
    <div class="text-[12px] text-state-failed font-mono">{error}</div>
  {:else if allClear}
    <div class="border border-line-hairline rounded-sm bg-surface-panel p-8 text-center"
      style="border-left: 2px solid var(--state-passed);">
      <div class="flex justify-center mb-4">
        <div class="w-10 h-10 rounded-sm flex items-center justify-center"
          style="background: color-mix(in srgb, var(--state-passed) 12%, transparent); color: var(--state-passed);">
          <svg viewBox="0 0 16 16" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 8.5l3 3 7-7" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </div>
      </div>
      <div class="text-[16px] text-ink-primary mb-1.5">All clear</div>
      <div class="text-[13px] text-ink-secondary leading-relaxed mb-4 max-w-md mx-auto">
        Catalogue is fully verified. Every FR is passed, accepted, or waived.
      </div>

      {#if highFindings.length > 0}
        <div class="max-w-2xl mx-auto mb-5 border border-line-hairline rounded-sm overflow-hidden text-left">
          <div class="px-3 py-1.5 bg-surface-inset border-b border-line-hairline font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted">
            {highFindings.length} HIGH findings — disposition summary
          </div>
          <div class="max-h-[240px] overflow-auto">
            {#each highFindings as f (f.id)}
              {@const key = `${f.scanner_kind}|${f.rule_id || ''}`}
              {@const accepted = acceptedMap.get(key)}
              {@const isWaived = f.scanner_kind === 'trivy-config' && (f.rule_id?.startsWith('DS-') || false)}
              <div class="grid grid-cols-[60px_minmax(0,1fr)_minmax(0,1.5fr)_minmax(70px,90px)] gap-2 px-3 py-1.5 border-b border-line-hairline last:border-0 items-start text-[11px]">
                <div class="font-mono shrink-0">
                  {#if accepted}
                    <span style="color: #F59E0B;">accepted</span>
                  {:else if isWaived}
                    <span class="text-state-waived">waived</span>
                  {:else}
                    <span class="text-state-passed">fixed</span>
                  {/if}
                </div>
                <div class="font-mono text-ink-muted truncate" title={f.rule_id || f.scanner_kind}>
                  {f.scanner_kind} · {(f.rule_id || '?').slice(0, 35)}
                </div>
                <div class="text-ink-muted leading-snug truncate" title={accepted?.rationale || (isWaived ? 'Docker socket architecture waiver' : 'Fixed in source')}>
                  {#if accepted}
                    {accepted.rationale}
                  {:else if isWaived}
                    Docker socket architecture waiver
                  {:else}
                    Fixed in source
                  {/if}
                </div>
                <div class="font-mono text-[10px] text-ink-muted truncate text-right">
                  {#if accepted}
                    {accepted.accepted_by}
                  {:else if isWaived}
                    agent:claude
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <a href="/scans" class="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.08em] px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-ink-primary transition-colors">
        <svg viewBox="0 0 12 12" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M6 2v8M2 6h8" stroke-linecap="round" /></svg>
        <span>Run a new scan</span>
      </a>
    </div>
  {:else}
    <!-- Triage Board -->
    {#if highFindings.length > 0}
      <section class="mb-6">
        <div class="flex items-center justify-between mb-3">
          <div>
            <div class="text-[14px] text-ink-primary">Triage Board</div>
            <div class="font-mono text-[11px] text-ink-muted mt-0.5">
              {highFindings.length} HIGH finding{highFindings.length === 1 ? '' : 's'}
              · {acceptedFindings.length} accepted
              · {actionableFindings.length} actionable
              {#if selectedCount > 0}· {selectedCount} selected{/if}
            </div>
          </div>
          {#if selectedCount > 0}
            <button type="button" on:click={generateFixPrompt}
              class="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.08em] rounded-sm px-2.5 py-1 border"
              style="color: var(--accent); border-color: color-mix(in srgb, var(--accent) 35%, transparent); background: color-mix(in srgb, var(--accent) 8%, transparent);">
              Fix {selectedCount} selected →
            </button>
          {/if}
        </div>

        <div class="space-y-3">
          <!-- Code-level findings -->
          {#if highFindings.filter((f) => scanLevel(f.scanner_kind) === 'code').length > 0}
            <div>
              <div class="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-muted mb-1.5">Code-level <span class="normal-case tracking-normal lowercase">— your source, configs, declared deps</span></div>
              <div class="space-y-1">
                {#each highFindings.filter((f) => scanLevel(f.scanner_kind) === 'code') as f (f.id)}
                  {@const key = `${f.scanner_kind}|${f.rule_id || ''}`}
                  {@const accepted = acceptedMap.get(key)}
                  <div class="border border-line-hairline rounded-sm bg-surface-panel px-3 py-2.5 {accepted ? 'opacity-50' : ''}">
                    <div class="flex items-start gap-3">
                      {#if !accepted}
                        <input type="checkbox" checked={selectedFindings.has(f.id)}
                          on:change={() => toggleFinding(f.id)}
                          class="mt-1 accent-[var(--accent)]" />
                      {:else}
                        <span class="mt-1 text-state-passed">
                          <svg viewBox="0 0 12 12" class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M2.5 6.5l2.5 2.5 4.5-5" stroke-linecap="round" stroke-linejoin="round" />
                          </svg>
                        </span>
                      {/if}
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                          <span class="font-mono text-[10px] uppercase tracking-[0.08em] px-1.5 py-0.5 rounded-sm border whitespace-nowrap"
                            style="color: {riskBadge(f.scanner_kind).color}; border-color: color-mix(in srgb, {riskBadge(f.scanner_kind).color} 30%, transparent); background: color-mix(in srgb, {riskBadge(f.scanner_kind).color} 8%, transparent);">
                            {riskBadge(f.scanner_kind).label}
                          </span>
                          <span class="font-mono text-[11px] text-ink-secondary truncate">{f.scanner_kind}</span>
                          <span class="font-mono text-[10px] text-ink-muted truncate" title={f.rule_id || ''}>{f.rule_id || '—'}</span>
                          {#if f.file_path}
                            <span class="font-mono text-[10px] text-ink-muted truncate" title={f.file_path}>{f.file_path}{#if f.line_start}:{f.line_start}{/if}</span>
                          {/if}
                        </div>
                        <div class="text-[12px] text-ink-secondary leading-snug">{f.message}</div>
                        {#if accepted}
                          <div class="mt-2 grid grid-cols-2 gap-3 max-w-lg">
                            <div>
                              <div class="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted mb-0.5">Accepted because</div>
                              <div class="text-[11px] text-ink-secondary leading-snug">{accepted.rationale}</div>
                            </div>
                            <div>
                              {#if accepted.fix_assessment}
                                <div class="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted mb-0.5">Fix impact</div>
                                <div class="text-[11px] text-ink-muted leading-snug">{accepted.fix_assessment}</div>
                              {/if}
                              {#if accepted.invalidation_conditions}
                                <div class="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted mt-1 mb-0.5">Invalidated when</div>
                                <div class="text-[11px] text-ink-muted leading-snug">{accepted.invalidation_conditions}</div>
                              {/if}
                            </div>
                          </div>
                          <div class="mt-2">
                            <button type="button" on:click={() => undoAcceptance(accepted)}
                              class="font-mono text-[10px] uppercase tracking-wide text-ink-muted hover:text-state-failed transition-colors">Undo</button>
                          </div>
                        {:else}
                          {@const h = heuristicAdvisory(f)}
                          <div class="mt-2 grid grid-cols-2 gap-3 max-w-lg">
                            <div>
                              <div class="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted mb-0.5">Fix</div>
                              <div class="text-[11px] text-ink-secondary leading-snug">{h.fix}</div>
                              <div class="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted mt-1 mb-0.5">Impact</div>
                              <div class="text-[11px] text-ink-muted leading-snug">{h.impact}</div>
                            </div>
                          </div>
                          <button type="button" on:click={() => openAcceptDialog(f)}
                            class="mt-2 font-mono text-[10px] uppercase tracking-wide text-ink-muted hover:text-accent transition-colors">
                            Accept as non-exploitable
                          </button>
                        {/if}
                      </div>
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {/if}

          <!-- Image-level findings -->
          {#if highFindings.filter((f) => scanLevel(f.scanner_kind) === 'image').length > 0}
            <div>
              <div class="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-muted mb-1.5">Image-level <span class="normal-case tracking-normal lowercase">— installed packages, base image, transitive deps</span></div>
              <div class="space-y-1">
                {#each highFindings.filter((f) => scanLevel(f.scanner_kind) === 'image') as f (f.id)}
                  {@const key = `${f.scanner_kind}|${f.rule_id || ''}`}
                  {@const accepted = acceptedMap.get(key)}
                  <div class="border border-line-hairline rounded-sm bg-surface-panel px-3 py-2.5 {accepted ? 'opacity-50' : ''}">
                    <div class="flex items-start gap-3">
                      {#if !accepted}
                        <input type="checkbox" checked={selectedFindings.has(f.id)}
                          on:change={() => toggleFinding(f.id)}
                          class="mt-1 accent-[var(--accent)]" />
                      {:else}
                        <span class="mt-1 text-state-passed">
                          <svg viewBox="0 0 12 12" class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M2.5 6.5l2.5 2.5 4.5-5" stroke-linecap="round" stroke-linejoin="round" />
                          </svg>
                        </span>
                      {/if}
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                          <span class="font-mono text-[10px] uppercase tracking-[0.08em] px-1.5 py-0.5 rounded-sm border whitespace-nowrap"
                            style="color: {riskBadge(f.scanner_kind).color}; border-color: color-mix(in srgb, {riskBadge(f.scanner_kind).color} 30%, transparent); background: color-mix(in srgb, {riskBadge(f.scanner_kind).color} 8%, transparent);">
                            {riskBadge(f.scanner_kind).label}
                          </span>
                          <span class="font-mono text-[11px] text-ink-secondary truncate">{f.scanner_kind}</span>
                          <span class="font-mono text-[10px] text-ink-muted truncate" title={f.rule_id || ''}>{f.rule_id || '—'}</span>
                          {#if f.file_path}
                            <span class="font-mono text-[10px] text-ink-muted truncate" title={f.file_path}>{f.file_path}{#if f.line_start}:{f.line_start}{/if}</span>
                          {/if}
                        </div>
                        <div class="text-[12px] text-ink-secondary leading-snug">{f.message}</div>
                        {#if accepted}
                          <div class="mt-2 grid grid-cols-2 gap-3 max-w-lg">
                            <div>
                              <div class="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted mb-0.5">Accepted because</div>
                              <div class="text-[11px] text-ink-secondary leading-snug">{accepted.rationale}</div>
                            </div>
                            <div>
                              {#if accepted.fix_assessment}
                                <div class="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted mb-0.5">Fix impact</div>
                                <div class="text-[11px] text-ink-muted leading-snug">{accepted.fix_assessment}</div>
                              {/if}
                              {#if accepted.invalidation_conditions}
                                <div class="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted mt-1 mb-0.5">Invalidated when</div>
                                <div class="text-[11px] text-ink-muted leading-snug">{accepted.invalidation_conditions}</div>
                              {/if}
                            </div>
                          </div>
                          <div class="mt-2">
                            <button type="button" on:click={() => undoAcceptance(accepted)}
                              class="font-mono text-[10px] uppercase tracking-wide text-ink-muted hover:text-state-failed transition-colors">Undo</button>
                          </div>
                        {:else}
                          {@const h = heuristicAdvisory(f)}
                          <div class="mt-2 grid grid-cols-2 gap-3 max-w-lg">
                            <div>
                              <div class="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted mb-0.5">Fix</div>
                              <div class="text-[11px] text-ink-secondary leading-snug">{h.fix}</div>
                              <div class="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted mt-1 mb-0.5">Impact</div>
                              <div class="text-[11px] text-ink-muted leading-snug">{h.impact}</div>
                            </div>
                          </div>
                          <button type="button" on:click={() => openAcceptDialog(f)}
                            class="mt-2 font-mono text-[10px] uppercase tracking-wide text-ink-muted hover:text-accent transition-colors">
                            Accept as non-exploitable
                          </button>
                        {/if}
                      </div>
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      </section>
    {/if}

    <!-- Failing Tests + Missing Tests (existing sections) -->
    {#if failingCount > 0 || missingCount > 0}
      <div class="space-y-3 pt-4 border-t border-line-hairline">
        {#if failingCount > 0}
          <FixSection title="Fix failing tests" count={failingCount}
            locked={step2Locked} lockReason="address triage board first"
            prompt={frPrompts.failed?.prompt ?? ''} promptTitle={frPrompts.failed?.title ?? ''}
            isCurrent={currentStep === 2} on:skip={() => (forceUnlock2 = true)} />
        {/if}
        {#if missingCount > 0}
          <FixSection title="Add missing tests" count={missingCount}
            locked={step3Locked} lockReason="address failing tests first"
            prompt={frPrompts.untested?.prompt ?? ''} promptTitle={frPrompts.untested?.title ?? ''}
            isCurrent={currentStep === 3} on:skip={() => (forceUnlock3 = true)} />
        {/if}
      </div>
    {/if}
  {/if}
</div>

{#if promptModalOpen}
  <PromptModal title={promptTitle} prompt={promptText} on:close={() => (promptModalOpen = false)} />
{/if}

{#if acceptDialogOpen && acceptTarget}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
    <button type="button" class="absolute inset-0 bg-black/65 backdrop-blur-[2px]" on:click={() => (acceptDialogOpen = false)} aria-label="Close"></button>
    <div role="dialog" aria-modal="true" class="relative w-full max-w-lg bg-surface-panel border border-line-strong rounded-md p-6" style="box-shadow: 0 24px 64px rgba(0,0,0,0.5);">
      <div class="text-[14px] text-ink-primary mb-1">Accept as non-exploitable</div>
      <div class="font-mono text-[11px] text-ink-muted mb-4">{acceptTarget.rule_id || acceptTarget.scanner_kind}</div>

      <div class="space-y-3">
        <div>
          <label for="accept-rationale" class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted block mb-1">Rationale <span class="text-state-failed">*</span></label>
          <textarea id="accept-rationale" bind:value={acceptRationale} rows="2"
            class="w-full bg-surface-inset border border-line-hairline rounded-sm px-2.5 py-1.5 text-[12px] text-ink-primary font-mono resize-none focus:outline-none focus:border-accent"
            placeholder="Why this finding is not exploitable in this project"></textarea>
        </div>
        <div>
          <label for="accept-fix-impact" class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted block mb-1">Fix impact <span class="text-ink-muted normal-case">(optional)</span></label>
          <textarea id="accept-fix-impact" bind:value={acceptFixAssessment} rows="2"
            class="w-full bg-surface-inset border border-line-hairline rounded-sm px-2.5 py-1.5 text-[12px] text-ink-primary font-mono resize-none focus:outline-none focus:border-accent"
            placeholder="What fixing would involve + what could break"></textarea>
        </div>
        <div>
          <label for="accept-invalidation" class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted block mb-1">Invalidated when <span class="text-ink-muted normal-case">(optional)</span></label>
          <textarea id="accept-invalidation" bind:value={acceptInvalidation} rows="2"
            class="w-full bg-surface-inset border border-line-hairline rounded-sm px-2.5 py-1.5 text-[12px] text-ink-primary font-mono resize-none focus:outline-none focus:border-accent"
            placeholder="Conditions that would make this acceptance invalid"></textarea>
        </div>
      </div>

      <div class="flex items-center justify-end gap-2 mt-5">
        <button type="button" on:click={() => (acceptDialogOpen = false)}
          class="font-mono text-[11px] uppercase tracking-[0.08em] px-3 py-1.5 rounded-sm border border-line-hairline text-ink-secondary hover:bg-surface-elevated transition-colors">
          Cancel
        </button>
        <button type="button" on:click={doAccept} disabled={!acceptRationale.trim()}
          class="font-mono text-[11px] uppercase tracking-[0.08em] px-3 py-1.5 rounded-sm border transition-colors disabled:opacity-40"
          style="color: var(--accent); border-color: color-mix(in srgb, var(--accent) 35%, transparent); background: color-mix(in srgb, var(--accent) 8%, transparent);">
          Accept
        </button>
      </div>
    </div>
  </div>
{/if}
