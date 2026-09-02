<script lang="ts">
  import CopyButton from '$lib/components/CopyButton.svelte';
  import type { ActionsReadiness, SetupRepository } from './models';

  export let repository: SetupRepository | null;
  export let readiness: ActionsReadiness | null;
  export let workflow = '';
  export let workflowFilename = '.github/workflows/assurance-scan.yml';
  export let workflowError = '';

  let expanded = false;

  function downloadWorkflow() {
    if (!workflow) return;
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([workflow], { type: 'text/yaml;charset=utf-8' }));
    link.download = 'assurance-scan.yml';
    link.click();
    URL.revokeObjectURL(link.href);
  }
</script>

<section
  class:locked={!repository}
  class="scan-lane github"
  data-lane-state={repository ? readiness?.kind ?? 'no_scan' : 'locked'}
  aria-labelledby="actions-lane-heading"
>
  <header>
    <div><p>Primary · team workflow</p><h2 id="actions-lane-heading">GitHub Actions</h2></div>
    <span class="visibility">Team visible</span>
  </header>
  {#if !repository}
    <p class="lane-intro">Choose an enabled repository to generate its standard workflow.</p>
  {:else}
    <p class="lane-intro">Every push to <strong>{repository.default_branch}</strong> is scanned, including pushes created when pull requests merge. Feature branches do not run this workflow.</p>
    <div class="readiness" aria-live="polite" aria-atomic="true">
      {#if !readiness || readiness.kind === 'no_scan'}
        <span class="status idle">No scan received</span><small>Add the workflow, then push to the default branch.</small>
      {:else if readiness.kind === 'accepted'}
        <span class="status accepted">Last upload accepted</span><a href={`/scans/${readiness.run_id}`}>View scan</a><time datetime={readiness.accepted_at}>{new Date(readiness.accepted_at).toLocaleString()}</time>
      {:else}
        <span class="status rejected">Last upload rejected</span><code>{readiness.safe_code}</code><a href={readiness.troubleshooting_url}>Troubleshoot</a><time datetime={readiness.attempted_at}>{new Date(readiness.attempted_at).toLocaleString()}</time><small>Request {readiness.correlation_id}</small>
        {#if readiness.actions_url}<a href={readiness.actions_url}>Open run</a>{/if}
      {/if}
    </div>
    <div class="workflow-actions">
      <button type="button" on:click={() => (expanded = !expanded)} aria-expanded={expanded}>{expanded ? 'Hide workflow' : 'Review workflow'}</button>
      {#if workflow}<CopyButton text={workflow} label="Copy workflow" /><button type="button" on:click={downloadWorkflow}>Download</button>{/if}
      <a href={`https://github.com/${repository.full_name}/actions`}>Open Actions</a>
    </div>
    {#if expanded}
      <div class="workflow"><div>{workflowFilename}</div>{#if workflowError}<p role="alert">Workflow unavailable: {workflowError}</p>{:else}<pre>{workflow || 'Loading verified workflow…'}</pre>{/if}</div>
    {/if}
  {/if}
</section>

<style>
  .scan-lane { min-width: 0; border: 1px solid var(--border-hairline); border-top: 2px solid var(--path-github); background: var(--bg-panel); padding: 1.1rem; }
  .scan-lane.locked { opacity: .62; }
  header { display: flex; justify-content: space-between; gap: 1rem; }
  header p,.visibility { color: var(--path-github); font: 600 .58rem 'Geist Mono',monospace; letter-spacing: .12em; text-transform: uppercase; }
  h2 { margin-top: .2rem; color: var(--text-primary); font-size: 1rem; }
  .visibility { color: var(--text-muted); }
  .lane-intro { min-height: 3rem; margin-top: .8rem; color: var(--text-secondary); font-size: .74rem; line-height: 1.55; }
  .lane-intro strong { color: var(--text-primary); font-family: 'Geist Mono',monospace; }
  .readiness { display: flex; min-height: 2.8rem; flex-wrap: wrap; align-items: center; gap: .55rem; border-block: 1px solid var(--border-hairline); padding: .65rem 0; color: var(--text-muted); font: .63rem 'Geist Mono',monospace; }
  .status { border: 1px solid var(--border-strong); padding: .28rem .45rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: .06em; }
  .status.accepted { border-color: color-mix(in srgb,var(--state-passed) 40%,transparent); color: var(--state-passed); }
  .status.rejected { border-color: color-mix(in srgb,var(--state-failed) 45%,transparent); color: var(--state-failed); }
  .readiness a { color: var(--path-github); }
  .workflow-actions { display: flex; flex-wrap: wrap; gap: .5rem; padding-top: .8rem; }
  button,.workflow-actions a { min-height: 2.4rem; display: inline-flex; align-items: center; border: 1px solid var(--border-strong); padding: .48rem .65rem; color: var(--text-secondary); font: 600 .62rem 'Geist Mono',monospace; }
  button:hover,.workflow-actions a:hover { border-color: var(--path-github); color: var(--path-github); }
  .workflow { margin-top: .75rem; border: 1px solid var(--border-hairline); background: var(--bg-inset); }
  .workflow > div { border-bottom: 1px solid var(--border-hairline); padding: .45rem .65rem; color: var(--text-muted); font: .6rem 'Geist Mono',monospace; }
  pre,.workflow p { max-height: 22rem; overflow: auto; padding: .75rem; color: var(--text-secondary); font: .62rem/1.55 'Geist Mono',monospace; white-space: pre; }
</style>
