<script lang="ts">
  import { api } from '$lib/api';
  import { createRequestGate } from '$lib/requestGate';
  import { selectScan } from '$lib/stores/selectedScan';
  import ScanResultsView from './ScanResultsView.svelte';
  import ProvenanceStrip from './ProvenanceStrip.svelte';
  import type { ProjectSummary, ScanStatus, ScanSummary } from '$lib/types';

  export let runId: string;

  let scan: ScanSummary | null = null;
  let status: ScanStatus | null = null;
  let project: ProjectSummary | null = null;
  let loading = true;
  let error: string | null = null;
  const scanGate = createRequestGate<string>();

  async function loadScan(targetRunId: string) {
    const ticket = scanGate.begin(targetRunId);
    if (!ticket) return;
    loading = true;
    try {
      const fetched: ScanStatus = await api.getScan(targetRunId);
      const fetchedProject = (await api.listProjects()).projects.find(
        (item) => item.id === fetched.project_id
      ) ?? null;
      if (!scanGate.isCurrent(ticket)) return;
      const fetchedScan: ScanSummary = {
        run_id: fetched.run_id,
        project_id: fetched.project_id,
        origin: fetched.origin,
        status: fetched.status,
        started_at: fetched.started_at,
        completed_at: fetched.completed_at,
        finding_count: 0,
        run_number: (fetched.options as Record<string, unknown>)?.run_number as number | undefined ?? undefined,
        display_title: (fetched.options as Record<string, unknown>)?.display_title as string | undefined ?? undefined
      };
      status = fetched;
      project = fetchedProject;
      scan = fetchedScan;
      selectScan(fetchedScan);
      error = null;
    } catch (e) {
      if (scanGate.isCurrent(ticket)) error = String(e);
    } finally {
      if (scanGate.isCurrent(ticket)) loading = false;
    }
  }

  $: runUrl = typeof status?.options?.run_url === 'string' ? status.options.run_url : null;
  $: runLabel = typeof status?.options?.run_number === 'number'
    ? `#${status.options.run_number}${status.options.display_title ? ' · ' + status.options.display_title : ''}`
    : runId;

  $: ghRepo = project?.github_repo ?? null;
  $: ghCommit = status?.commit_sha ?? null;

  // Reactive so switching rows in the scans list reloads the detail view
  // (the component is not remounted between selections).
  $: if (runId) void loadScan(runId);

</script>

<div class="border-b border-line-hairline">
  <div class="px-6 py-3 flex items-center gap-0.5 overflow-x-auto">
    <span class="flex-1"></span>
    {#if status?.git_branch}
      <span class="font-mono text-[11px] text-state-pending pr-2">
        {status.git_branch}{status.commit_sha ? ` @ ${status.commit_sha.slice(0, 8)}` : ''}
      </span>
    {/if}
    <span class="font-mono text-[11px] text-ink-muted pr-1" title={runId}>{runLabel}</span>
    {#if runUrl}
      <a
        href={runUrl}
        target="_blank"
        rel="noreferrer"
        title="Open the GitHub Actions run"
        class="ml-1 inline-flex items-center gap-1 font-mono text-[11px] text-ink-muted hover:text-accent pr-1 transition-colors"
      >GH<svg class="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4">
          <path d="M4 2h6v6M10 2L5.5 6.5M8 7v3H2V4h3" stroke-linecap="round" stroke-linejoin="round" />
        </svg></a>
    {/if}
  </div>
</div>

{#if status?.provenance}
  <ProvenanceStrip provenance={status.provenance} projectId={status.project_id} />
{/if}

<div>
  {#if loading}
    <div class="p-6 text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else if error}
    <div class="p-6 text-[12px] text-state-failed font-mono">{error}</div>
  {:else if scan}
    {#key scan.run_id}
      <div class="p-6">
        <ScanResultsView {scan} repo={ghRepo} commit={ghCommit} />
      </div>
    {/key}
  {/if}
</div>
