<script lang="ts">
  import ScanOriginBadge from './ScanOriginBadge.svelte';
  import { shortCommit, type SameCommitComparison } from '$lib/scanProvenance';

  export let comparison: SameCommitComparison;
  export let onOpen: (runId: string) => void;
  export let onClose: () => void;

  $: commit = comparison.local.commit_sha;
</script>

<section
  class="mb-5 border border-line-strong rounded-sm bg-surface-panel"
  aria-labelledby="same-commit-comparison-title"
>
  <div class="flex flex-wrap items-start justify-between gap-3 border-b border-line-hairline px-4 py-3">
    <div>
      <div id="same-commit-comparison-title" class="font-mono text-[11px] uppercase tracking-[0.12em] text-ink-primary">
        Same commit comparison
      </div>
      <div class="mt-1 font-mono text-[10px] text-ink-muted">
        Local and GitHub Actions runs for <span class="text-ink-secondary" title={commit ?? ''}>{shortCommit(commit)}</span>
        in this project.
      </div>
    </div>
    <button
      type="button"
      on:click={onClose}
      class="px-2 py-1 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-muted hover:text-ink-primary"
      aria-label="Close same commit comparison"
    >Close</button>
  </div>

  <div class="grid gap-px bg-line-hairline sm:grid-cols-2">
    {#each [comparison.local, comparison.githubActions] as scan (scan.run_id)}
      <div class="bg-surface-panel p-4">
        <div class="mb-3 flex items-center justify-between gap-2">
          <ScanOriginBadge origin={scan.origin} />
          <span class={scan.status === 'completed' ? 'text-state-passed' : scan.status === 'failed' ? 'text-state-failed' : 'text-state-pending'}>
            <span class="font-mono text-[10px] uppercase tracking-[0.08em]">{scan.status}</span>
          </span>
        </div>
        <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-[10px]">
          <dt class="text-ink-muted">Run</dt>
          <dd class="truncate text-ink-secondary" title={scan.run_id}>{scan.run_id}</dd>
          <dt class="text-ink-muted">Branch</dt>
          <dd class="truncate text-ink-secondary">{scan.git_branch ?? 'Detached HEAD'}</dd>
          <dt class="text-ink-muted">Findings</dt>
          <dd class="text-ink-secondary tabular-nums">{scan.finding_count}</dd>
          <dt class="text-ink-muted">Working tree</dt>
          <dd class={scan.working_tree_dirty === true ? 'text-state-pending' : 'text-ink-secondary'}>
            {scan.working_tree_dirty === true ? 'Dirty — includes local changes' : scan.working_tree_dirty === false ? 'Clean' : 'Unknown'}
          </dd>
        </dl>
        <button
          type="button"
          on:click={() => onOpen(scan.run_id)}
          class="mt-3 rounded-sm border border-line-hairline px-2 py-1 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary"
        >Open run</button>
      </div>
    {/each}
  </div>
</section>
