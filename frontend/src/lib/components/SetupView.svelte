<script lang="ts">
  import CopyButton from './CopyButton.svelte';

  const STEPS = [
    {
      n: 1,
      title: 'Generate FR Catalogue',
      desc: 'Explore your codebase and draft a Functional Requirements catalogue with test specs and scanner coverage.',
      where: 'FRs tab',
      href: '#',
      output: 'fr-catalogue (stored in DB)'
    },
    {
      n: 2,
      title: 'Generate Compliance Mapping',
      desc: 'Map every ASVS row to your FRs — applicable rows with test_refs + rationale, N/A rows with explanation.',
      where: 'Compliance tab',
      href: '#',
      output: 'compliance mapping (stored in DB)'
    },
    {
      n: 3,
      title: 'Run Initial Scan',
      desc: 'Scan with all 9 scanners (semgrep, gitleaks, trivy, osv, grype, syft, trivy-image). First run ~3-5 min.',
      where: 'Scans tab',
      href: '/scans',
      output: 'Scan results + gap analysis'
    },
    {
      n: 4,
      title: 'Review & Fix Gaps',
      desc: 'Triage HIGH findings (fix vs accept), write unit tests for untested FRs, re-scan to verify.',
      where: 'Fix tab',
      href: '#',
      output: 'All FRs passed, accepted, or waived'
    }
  ];
</script>

<div class="p-6 max-w-3xl">
  <div class="mb-6">
    <div class="text-[18px] text-ink-primary mb-2">Project Setup</div>
    <div class="text-[12px] text-ink-secondary leading-relaxed max-w-xl">
      Four-step pipeline from zero to a verified assurance posture. Each step has its own
      onboarding prompt on the relevant tab — go there to get started.
    </div>
  </div>

  <!-- Prerequisites -->
  <div class="mb-6 border border-line-hairline rounded-sm bg-surface-panel p-4">
    <div class="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-muted mb-2">Prerequisites</div>
    <dl class="grid grid-cols-[110px_minmax(0,1fr)] gap-x-4 gap-y-2 text-[12px]">
      <dt class="font-mono text-ink-secondary">Docker</dt>
      <dd class="text-ink-muted">Required — scanners run as sibling containers</dd>
      <dt class="font-mono text-ink-secondary">Server running</dt>
      <dd class="text-ink-muted">This dashboard means it's up</dd>
      <dt class="font-mono text-ink-secondary">MCP registered</dt>
      <dd class="text-ink-secondary">
        Claude Code needs the MCP server registered. Run this once per machine:
        <pre class="font-mono text-[11px] text-ink-primary bg-surface-inset border border-line-hairline rounded-sm p-2 mt-1.5 overflow-x-auto">claude mcp add assurance-scan --transport http http://127.0.0.1:8742/mcp</pre>
      </dd>
    </dl>
  </div>

  <!-- Pipeline overview -->
  <div class="relative">
    <div class="absolute left-[19px] top-[40px] bottom-[40px] w-px bg-line-hairline"></div>

    {#each STEPS as step (step.n)}
      <div class="relative flex gap-5 pb-6 last:pb-0">
        <div class="shrink-0 w-10 h-10 rounded-sm border border-line-strong bg-surface-panel flex items-center justify-center font-mono text-[14px] text-ink-primary z-10">
          {step.n}
        </div>

        <div class="flex-1 min-w-0 pt-1">
          <div class="flex items-baseline justify-between gap-3 mb-1">
            <div class="text-[14px] text-ink-primary">{step.title}</div>
            <span class="font-mono text-[10px] uppercase tracking-wide text-accent whitespace-nowrap shrink-0">{step.where}</span>
          </div>
          <div class="text-[12px] text-ink-secondary leading-relaxed mb-2">{step.desc}</div>
          <div class="flex items-center gap-2 font-mono text-[10px] text-ink-muted">
            <svg class="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.3">
              <path d="M2.5 6h7M7 3l2.5 3-2.5 3" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <span>produces: <span class="text-ink-secondary">{step.output}</span></span>
          </div>
        </div>
      </div>
    {/each}
  </div>

  <div class="mt-6 pt-5 border-t border-line-hairline text-[11px] text-ink-muted leading-relaxed max-w-xl">
    Each tab shows its own onboarding prompt when the artefact is missing —
    no need to come back here once you know the pipeline.
    Go to the <span class="text-accent">FRs</span> tab first to generate the catalogue.
  </div>
</div>
