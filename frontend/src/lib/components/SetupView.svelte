<script lang="ts">
  import CopyButton from './CopyButton.svelte';

  const STEPS = [
    {
      n: 1,
      title: 'Generate FR Catalogue',
      desc: 'Explore your codebase and draft a Functional Requirements catalogue. Each FR describes a capability with test specs and scanner coverage.',
      prompt: 'Run the generate-fr-catalogue workflow from the assurance-scan MCP server. Use project_path="." (or your project path).',
      output: 'fr-catalog.json'
    },
    {
      n: 2,
      title: 'Generate Compliance Mapping',
      desc: 'Map every ASVS row to your FRs. Appropriate rows get satisfied_by + test_refs; inappropriate rows get rationale for why they don\'t apply.',
      prompt: 'Run the propose-compliance-mapping workflow from the assurance-scan MCP server.',
      output: 'fr-compliance-mapping.json'
    },
    {
      n: 3,
      title: 'Run Initial Scan',
      desc: 'Scan the project with all scanners (semgrep, gitleaks, trivy, osv-scanner, grype, syft). First run takes ~3-5 min for DB downloads.',
      prompt: 'Use the assurance-scan MCP server. Call start_scan with fr_catalog_path="./fr-catalog.json". Poll get_scan_status until status is "completed". Then call get_findings and get_gap_analysis.',
      output: 'Scan results + gap analysis'
    },
    {
      n: 4,
      title: 'Review & Fix Gaps',
      desc: 'Address failed FRs (fix scanner findings) and untested FRs (write unit tests). Re-scan after each batch of fixes.',
      prompt: 'Use the assurance-scan MCP server. Call get_gap_analysis on the latest run. For each failed FR, call close-gap-via-config. For each untested FR, call close-gap-via-test. After fixing, call start_scan to verify.',
      output: 'All FRs passed or waived'
    }
  ];
</script>

<div class="p-6 max-w-3xl">
  <div class="mb-8">
    <div class="text-[18px] text-ink-primary mb-2">Project Setup</div>
    <div class="text-[12px] text-ink-secondary leading-relaxed max-w-xl">
      Four-step pipeline to take a new project from zero code to a fully verified
      assurance posture. Each step produces a reviewable artefact. Run them in order,
      pasting the prompt into Claude Code (or your agent of choice).
    </div>
  </div>

  <div class="relative">
    <!-- Vertical connector line -->
    <div class="absolute left-[19px] top-[40px] bottom-[40px] w-px bg-line-hairline"></div>

    {#each STEPS as step (step.n)}
      <div class="relative flex gap-5 pb-8 last:pb-0">
        <!-- Step number badge -->
        <div class="shrink-0 w-10 h-10 rounded-sm border border-line-strong bg-surface-panel flex items-center justify-center font-mono text-[14px] text-ink-primary z-10">
          {step.n}
        </div>

        <!-- Step content -->
        <div class="flex-1 min-w-0 pt-1">
          <div class="text-[14px] text-ink-primary mb-1">{step.title}</div>
          <div class="text-[12px] text-ink-secondary leading-relaxed mb-3">{step.desc}</div>

          <!-- Prompt box -->
          <div class="border border-line-hairline rounded-sm bg-surface-inset p-3 mb-2">
            <div class="flex items-start justify-between gap-3">
              <div class="flex-1 min-w-0">
                <div class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted mb-1.5">Paste into Claude Code</div>
                <div class="font-mono text-[11px] text-ink-secondary leading-[1.6] break-words">{step.prompt}</div>
              </div>
              <div class="shrink-0">
                <CopyButton text={step.prompt} label="Copy" />
              </div>
            </div>
          </div>

          <!-- Output indicator -->
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

  <!-- All-in-one shortcut -->
  <div class="mt-6 pt-6 border-t border-line-hairline">
    <div class="text-[13px] text-ink-primary mb-2">All-in-one shortcut</div>
    <div class="text-[12px] text-ink-secondary leading-relaxed mb-3">
      If you already have a catalogue and mapping, the <code class="font-mono text-ink-primary">setup-project</code>
      workflow handles validation, scanning, and gap analysis in one call.
    </div>
    <div class="border border-line-hairline rounded-sm bg-surface-inset p-3">
      <div class="flex items-start justify-between gap-3">
        <div class="flex-1 min-w-0">
          <div class="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted mb-1.5">Paste into Claude Code</div>
          <div class="font-mono text-[11px] text-ink-secondary leading-[1.6]">Run the setup-project workflow from the assurance-scan MCP server.</div>
        </div>
        <div class="shrink-0">
          <CopyButton text="Run the setup-project workflow from the assurance-scan MCP server." label="Copy" />
        </div>
      </div>
    </div>
  </div>
</div>
