<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import LocalScanSetupPanel from '$lib/components/LocalScanSetupPanel.svelte';
  import ActionsSetupLane from './ActionsSetupLane.svelte';
  import GithubAccessFoundation from './GithubAccessFoundation.svelte';
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
  let installOutcome: 'ready' | 'approval_requested' | null = null;
  let activeTab: 'github' | 'local' = 'github';

  function tabFromLocation(): 'github' | 'local' {
    if (typeof window === 'undefined') return 'github';
    return new URL(window.location.href).searchParams.get('tab') === 'local' ? 'local' : 'github';
  }

  function selectTab(tab: 'github' | 'local') {
    activeTab = tab;
    const url = new URL(window.location.href);
    url.pathname = '/setup';
    url.searchParams.set('tab', tab);
    url.hash = '';
    window.history.replaceState({}, '', url);
  }

  onMount(() => {
    activeTab = tabFromLocation();
    const outcome = new URL(window.location.href).searchParams.get('github_install');
    installOutcome = outcome === 'ready' || outcome === 'approval_requested' ? outcome : null;
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
  $: signedIn = Boolean(state && state.kind !== 'signed_out');
</script>

<div class="setup-experience" data-responsive-region="setup-experience">
  <header class="page-intro">
    <div><p>Trust configuration</p><h1>Connect code to evidence</h1></div>
    <p>Choose where results come from and let existing GitHub access decide who can see them.</p>
  </header>

  <div class="announcer sr-only" aria-live="polite">{snapshot.announcement}</div>

  <div class="flow-tabs" role="tablist" aria-label="Setup workflow">
    <button
      id="github-setup-tab"
      type="button"
      role="tab"
      aria-selected={activeTab === 'github'}
      aria-controls="github-setup-panel"
      class:active={activeTab === 'github'}
      on:click={() => selectTab('github')}
    >
      <span>GitHub Actions</span>
      <small>Organisation access and automatic default-branch scans</small>
    </button>
    <button
      id="local-setup-tab"
      type="button"
      role="tab"
      aria-selected={activeTab === 'local'}
      aria-controls="local-setup-panel"
      class:active={activeTab === 'local'}
      on:click={() => selectTab('local')}
    >
      <span>Local CLI</span>
      <small>Private branch scans authenticated with a machine token</small>
    </button>
  </div>

  {#if activeTab === 'github' && installOutcome === 'ready'}
    <div class="return-notice success" role="status"><span aria-hidden="true">✓</span><div><strong>GitHub access connected</strong><p>Your selected organisations and repositories are ready. GitHub permissions now control who can see each project.</p></div></div>
  {:else if activeTab === 'github' && installOutcome === 'approval_requested'}
    <div class="return-notice" role="status"><span aria-hidden="true">…</span><div><strong>Approval requested</strong><p>An organisation owner must approve the GitHub App. This page will show the repositories after approval.</p></div></div>
  {/if}

  {#if snapshot.phase === 'loading' || snapshot.phase === 'idle'}
    <SetupSkeleton />
  {:else if snapshot.phase === 'failure' && !bootstrap}
    <SetupFailure message={snapshot.error} onRetry={() => void controller.retry()} />
  {:else if bootstrap}
    <div class:refreshing={snapshot.phase === 'ready' && snapshot.refreshing} class="setup-content" aria-busy={snapshot.phase === 'ready' && snapshot.refreshing}>
      {#if snapshot.phase === 'failure'}
        <SetupFailure message={snapshot.error} onRetry={() => void controller.retry()} />
      {/if}
      {#if activeTab === 'github'}
        <div id="github-setup-panel" role="tabpanel" aria-labelledby="github-setup-tab" class="flow-panel">
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
          {#if repository}
            <div class="github-lane" data-responsive-region="github-scan-path" aria-label="GitHub scan path">
              <ActionsSetupLane {repository} {readiness} {workflow} {workflowFilename} {workflowError} />
            </div>
          {/if}
        </div>
      {:else}
        <div id="local-setup-panel" role="tabpanel" aria-labelledby="local-setup-tab" class="flow-panel">
          {#if !signedIn && state?.kind === 'signed_out'}
            <section class="local-sign-in" aria-labelledby="local-sign-in-heading">
              <div class="auth-key" aria-hidden="true">•••</div>
              <div>
                <h2 id="local-sign-in-heading">Sign in before creating a machine token</h2>
                <p>Your browser session identifies your Assurance Scan account. The CLI then uses a separate upload-only token stored on this machine.</p>
              </div>
              <a href="/auth/login?next=%2Fsetup%3Ftab%3Dlocal">Sign in with GitHub</a>
            </section>
          {:else}
            <section class="local-boundary" aria-label="Local authentication boundary">
              <strong>Separate local authentication</strong>
              <p>Install the verified wrapper before creating a token. Source stays on your machine; only normalized evidence and repository metadata are uploaded to your private scan history.</p>
            </section>
            <LocalScanSetupPanel />
          {/if}
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .setup-experience { width: min(100%,78rem); margin: 0 auto; padding: 2rem clamp(1rem,3vw,2.5rem) 4rem; }
  .page-intro { display: grid; grid-template-columns: 1fr minmax(18rem,30rem); align-items: end; gap: 2rem; margin-bottom: 1.4rem; }
  .page-intro > div > p { margin-bottom: .4rem; color: var(--state-passed); font: 600 .62rem 'Geist Mono',monospace; letter-spacing: .15em; text-transform: uppercase; }
  h1 { color: var(--text-primary); font-size: clamp(1.55rem,3vw,2.4rem); font-weight: 520; letter-spacing: -.035em; line-height: 1; }
  .page-intro > p { color: var(--text-secondary); font-size: .82rem; line-height: 1.55; }
  .flow-tabs { display: grid; grid-template-columns: 1fr 1fr; margin-bottom: 1rem; border: 1px solid var(--border-hairline); background: var(--bg-inset); }
  .flow-tabs button { position: relative; display: grid; min-width: 0; gap: .24rem; border: 0; padding: 1rem 1.1rem; text-align: left; color: var(--text-muted); }
  .flow-tabs button + button { border-left: 1px solid var(--border-hairline); }
  .flow-tabs button::after { position: absolute; right: 0; bottom: -1px; left: 0; height: 2px; content: ''; background: transparent; }
  .flow-tabs button.active { background: var(--bg-panel); color: var(--text-primary); }
  .flow-tabs button.active::after { background: var(--path-local); }
  .flow-tabs button:first-child.active::after { background: var(--state-passed); }
  .flow-tabs button:focus-visible { z-index: 1; outline: 2px solid var(--accent); outline-offset: -3px; }
  .flow-tabs span { font-size: .88rem; font-weight: 620; }
  .flow-tabs small { overflow: hidden; color: var(--text-secondary); font-size: .68rem; line-height: 1.4; text-overflow: ellipsis; }
  .setup-content { display: grid; gap: 1rem; transition: opacity 140ms ease; }
  .setup-content.refreshing { opacity: .72; }
  .return-notice { display: flex; align-items: flex-start; gap: .75rem; margin-bottom: 1rem; border: 1px solid color-mix(in srgb,var(--path-local) 38%,var(--border-hairline)); background: color-mix(in srgb,var(--path-local) 6%,var(--bg-panel)); padding: .9rem 1rem; }
  .return-notice.success { border-color: color-mix(in srgb,var(--state-passed) 38%,var(--border-hairline)); background: color-mix(in srgb,var(--state-passed) 6%,var(--bg-panel)); }
  .return-notice > span { color: var(--path-local); font: 700 .75rem 'Geist Mono',monospace; }
  .return-notice.success > span { color: var(--state-passed); }
  .return-notice strong { color: var(--text-primary); font-size: .78rem; }
  .return-notice p { margin-top: .18rem; color: var(--text-secondary); font-size: .7rem; line-height: 1.5; }
  .flow-panel,.github-lane { display: grid; gap: 1rem; }
  .local-boundary { display: grid; grid-template-columns: minmax(10rem,.42fr) 1fr; gap: 1rem; border-left: 2px solid var(--path-local); background: var(--bg-inset); padding: .9rem 1rem; }
  .local-boundary strong { color: var(--text-primary); font-size: .76rem; }
  .local-boundary p { max-width: 52rem; color: var(--text-secondary); font-size: .7rem; line-height: 1.55; }
  .local-sign-in { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 1rem; border: 1px solid var(--border-hairline); border-top: 2px solid var(--path-local); background: var(--bg-panel); padding: 1.2rem; }
  .auth-key { display: grid; width: 2.2rem; height: 2.2rem; place-items: center; border: 1px solid var(--path-local); color: var(--path-local); font-weight: 700; letter-spacing: .14em; }
  .local-sign-in h2 { color: var(--text-primary); font-size: .85rem; }
  .local-sign-in p { max-width: 42rem; margin-top: .25rem; color: var(--text-secondary); font-size: .7rem; line-height: 1.5; }
  .local-sign-in a { border: 1px solid var(--border-strong); padding: .55rem .75rem; color: var(--text-primary); font-size: .7rem; font-weight: 620; }
  .local-sign-in a:hover { border-color: var(--path-local); color: var(--path-local); }
  @media (max-width: 820px) { .page-intro { grid-template-columns: 1fr; gap: .7rem; } }
  @media (max-width: 620px) { .flow-tabs { grid-template-columns: 1fr; } .flow-tabs button + button { border-top: 1px solid var(--border-hairline); border-left: 0; } .local-boundary { grid-template-columns: 1fr; gap: .35rem; } .local-sign-in { grid-template-columns: auto 1fr; } .local-sign-in a { grid-column: 1 / -1; text-align: center; } }
  @media (max-width: 420px) { .setup-experience { padding-inline: .75rem; } }
  @media (prefers-reduced-motion: reduce) { .setup-content { transition: none; } }
</style>
