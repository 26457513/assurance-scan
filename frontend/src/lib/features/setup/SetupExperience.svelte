<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import AccessTopology from './AccessTopology.svelte';
  import ActionsSetupLane from './ActionsSetupLane.svelte';
  import GithubAccessFoundation from './GithubAccessFoundation.svelte';
  import LocalSetupLane from './LocalSetupLane.svelte';
  import SetupFailure from './SetupFailure.svelte';
  import SetupSkeleton from './SetupSkeleton.svelte';
  import { createSetupApi } from './api';
  import { createSetupController, type SetupControllerSnapshot } from './controller';

  const controller = createSetupController({ api: createSetupApi() });
  let snapshot: SetupControllerSnapshot = controller.snapshot();
  let unsubscribe: (() => void) | null = null;
  let workflow = '';
  let workflowFilename = '.github/workflows/assurance-scan.yml';
  let workflowError = '';

  onMount(() => {
    unsubscribe = controller.subscribe((value) => (snapshot = value));
    void controller.load();
    void loadWorkflow();
  });

  onDestroy(() => {
    unsubscribe?.();
    controller.dispose();
  });

  async function loadWorkflow() {
    try {
      const response = await fetch('/api/ci/workflow-template', { headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const payload = (await response.json()) as { filename?: unknown; workflow?: unknown };
      if (typeof payload.workflow !== 'string' || typeof payload.filename !== 'string') throw new Error('invalid workflow response');
      workflow = payload.workflow;
      workflowFilename = payload.filename;
    } catch (error) {
      workflowError = error instanceof Error ? error.message : 'workflow unavailable';
    }
  }

  $: bootstrap = snapshot.bootstrap;
  $: state = bootstrap?.state;
  $: repository = state?.kind === 'repository_ready' || state?.kind === 'repository_ready_write' ? state.repository : null;
  $: readiness = state?.kind === 'repository_ready' || state?.kind === 'repository_ready_write' ? state.actions_readiness : null;
  $: localEnabled = state?.kind === 'repository_ready_write' && state.capabilities.can_local_scan;
</script>

<div class="setup-experience" data-responsive-region="setup-experience">
  <header class="page-intro">
    <div><p>Trust configuration</p><h1>Connect code to evidence</h1></div>
    <p>Choose where results come from and let existing GitHub access decide who can see them.</p>
  </header>

  <div class="announcer sr-only" aria-live="polite">{snapshot.announcement}</div>

  {#if snapshot.phase === 'loading' || snapshot.phase === 'idle'}
    <SetupSkeleton />
  {:else if snapshot.phase === 'failure' && !bootstrap}
    <SetupFailure message={snapshot.error} onRetry={() => void controller.retry()} />
  {:else if bootstrap}
    <div class:refreshing={snapshot.phase === 'ready' && snapshot.refreshing} class="setup-content" aria-busy={snapshot.phase === 'ready' && snapshot.refreshing}>
      {#if snapshot.phase === 'failure'}
        <SetupFailure message={snapshot.error} onRetry={() => void controller.retry()} />
      {/if}
      <AccessTopology {bootstrap} />
      <GithubAccessFoundation
        {bootstrap}
        repositories={snapshot.repositories}
        selectedRepositoryId={snapshot.selectedRepositoryId}
        onSearch={(installationId, query) => controller.searchRepositories(installationId, query)}
        onSelect={(repositoryId) => void controller.selectRepository(repositoryId)}
        onMore={() => void controller.loadMoreRepositories()}
        onClear={() => void controller.selectRepository(null)}
        onRetry={() => void controller.retry()}
      />
      <div class="scan-paths" data-responsive-region="scan-paths" aria-label="Scan paths">
        <ActionsSetupLane {repository} {readiness} {workflow} {workflowFilename} {workflowError} />
        <LocalSetupLane {repository} enabled={localEnabled} tokens={bootstrap.machine_tokens} latestRun={bootstrap.latest_local_run} />
      </div>
    </div>
  {/if}
</div>

<style>
  .setup-experience { width: min(100%,78rem); margin: 0 auto; padding: 2rem clamp(1rem,3vw,2.5rem) 4rem; }
  .page-intro { display: grid; grid-template-columns: 1fr minmax(18rem,30rem); align-items: end; gap: 2rem; margin-bottom: 1.4rem; }
  .page-intro > div > p { margin-bottom: .4rem; color: var(--state-passed); font: 600 .62rem 'Geist Mono',monospace; letter-spacing: .15em; text-transform: uppercase; }
  h1 { color: var(--text-primary); font-size: clamp(1.55rem,3vw,2.4rem); font-weight: 520; letter-spacing: -.035em; line-height: 1; }
  .page-intro > p { color: var(--text-secondary); font-size: .82rem; line-height: 1.55; }
  .setup-content { display: grid; gap: 1rem; transition: opacity 140ms ease; }
  .setup-content.refreshing { opacity: .72; }
  .scan-paths { display: grid; grid-template-columns: minmax(0,1.35fr) minmax(20rem,1fr); gap: 1rem; align-items: start; }
  @media (max-width: 820px) { .page-intro { grid-template-columns: 1fr; gap: .7rem; } .scan-paths { grid-template-columns: 1fr; } }
  @media (max-width: 420px) { .setup-experience { padding-inline: .75rem; } }
  @media (prefers-reduced-motion: reduce) { .setup-content { transition: none; } }
</style>
