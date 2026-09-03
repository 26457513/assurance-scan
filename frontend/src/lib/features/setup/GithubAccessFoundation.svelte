<script lang="ts">
  import type { RepositorySearchState } from './controller';
  import type { SetupBootstrap } from './models';
  import GithubAccessSteps from './GithubAccessSteps.svelte';
  import RepositoryPicker from './RepositoryPicker.svelte';

  export let bootstrap: SetupBootstrap;
  export let repositories: RepositorySearchState;
  export let selectedRepositoryId: string | null;
  export let onSearch: (installationId: string, query: string) => void;
  export let onSelect: (repositoryId: string) => void;
  export let onMore: () => void;
  export let onClear: () => void;
  export let onRetry: () => void;

  $: state = bootstrap.state;
  $: ready = state.kind === 'repository_ready' || state.kind === 'repository_ready_write';
  $: enabledRepositories = bootstrap.installations.reduce(
    (total, installation) => total + installation.enabled_repository_count,
    0
  );
</script>

<section class="foundation" data-setup-state={state.kind} aria-labelledby="github-foundation-heading">
  <header>
    <div>
      <p class="eyebrow">Usually under one minute</p>
      <h2 id="github-foundation-heading">Connect the organisations and repositories you choose</h2>
      <p class="foundation-summary">An owner installs the GitHub App once. Teammates only sign in; their existing GitHub repository access controls what they see.</p>
    </div>
    {#if state.kind !== 'signed_out' && 'identity' in state}
      <div class="identity-evidence"><span aria-hidden="true">✓</span><span>Connected as <strong>@{state.identity.login}</strong></span></div>
    {/if}
  </header>

  <GithubAccessSteps {bootstrap} />

  {#if state.kind === 'signed_out'}
    <div class="foundation-action"><p>Sign in with the GitHub account you use for the repositories you want to scan.</p><a class="primary" href={state.sign_in_url}>Sign in with GitHub</a></div>
  {:else if state.kind === 'github_connected'}
    <div class="foundation-action">
      <div class="action-copy">
        <p>Your identity is connected. On GitHub, choose your personal account or organisation, select <strong>Only select repositories</strong>, then press <strong>Install</strong> or <strong>Save</strong>.</p>
        <small>GitHub opens in a new tab and should return that tab to Assurance Scan. If it does not, come back to this tab and check access.</small>
      </div>
      <div class="handoff-actions">
        <a class="primary" href={state.install_url} target="_blank" rel="noopener">Open GitHub to choose access <span aria-hidden="true">↗</span></a>
        <button type="button" on:click={onRetry}>Check GitHub access</button>
      </div>
    </div>
  {:else if state.kind === 'approval_pending'}
    <div class="foundation-action"><div class="action-copy"><p>Your request was sent to the organisation owner.</p><small>No further setup is needed until they approve it in GitHub.</small></div><a href={state.request_url} target="_blank" rel="noopener">View approval request <span aria-hidden="true">↗</span></a></div>
  {:else if state.kind === 'installed_no_repositories'}
    <div class="foundation-action"><div class="action-copy"><p>Assurance Scan is installed for <strong>{state.installation.owner_login}</strong>, but no repositories were selected.</p><small>GitHub opens in a new tab. Select at least one repository, save, then return here.</small></div><a class="primary" href={state.installation.manage_url} target="_blank" rel="noopener">Select repositories <span aria-hidden="true">↗</span></a></div>
  {:else if state.kind === 'installation_suspended'}
    <div class="foundation-action danger"><p>The GitHub App installation is suspended. Scan setup is locked until it is restored.</p><a href={state.installation.manage_url} target="_blank" rel="noopener">Manage GitHub App <span aria-hidden="true">↗</span></a></div>
  {:else if state.kind === 'access_stale'}
    <div class="foundation-action danger"><p>GitHub access could not be refreshed. The last selection is shown only as stale evidence; setup actions are locked.</p><button type="button" on:click={onRetry}>Retry access check</button></div>
  {:else}
    {#if !ready}
      <div class="access-confirmed" role="status">
        <span aria-hidden="true">✓</span>
        <p><strong>GitHub access verified.</strong> {enabledRepositories} {enabledRepositories === 1 ? 'repository is' : 'repositories are'} available. Choose one below to configure its scan paths.</p>
        <a href="/api/v2/github/install/start" target="_blank" rel="noopener">Add another organisation <span aria-hidden="true">↗</span></a>
      </div>
    {/if}
    {#if state.kind === 'repository_ready' || state.kind === 'repository_ready_write'}
      <div class="selected-repository">
        <div><span>Active repository</span><strong>{state.repository.full_name}</strong><small>{state.repository.default_branch} · {state.repository.permission} access</small></div>
        <div class="selected-actions"><a href={state.installation.manage_url} target="_blank" rel="noopener">Change access <span aria-hidden="true">↗</span></a><a href="/api/v2/github/install/start" target="_blank" rel="noopener">Add organisation <span aria-hidden="true">↗</span></a><button type="button" on:click={onClear}>Choose another</button></div>
      </div>
    {/if}
    {#if !ready || repositories.phase !== 'idle'}
      <RepositoryPicker
        installations={bootstrap.installations}
        search={repositories}
        {selectedRepositoryId}
        {onSearch}
        {onSelect}
        {onMore}
      />
    {/if}
  {/if}
</section>

<style>
  .foundation { border: 1px solid var(--border-hairline); background: var(--bg-panel); padding: 1.25rem; }
  header { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
  .eyebrow { margin-bottom: .3rem; color: var(--path-github); font: 600 .6rem 'Geist Mono',monospace; letter-spacing: .14em; text-transform: uppercase; }
  h2 { max-width: 35rem; color: var(--text-primary); font-size: 1rem; font-weight: 520; line-height: 1.35; }
  .foundation-summary { max-width: 45rem; margin-top: .35rem; color: var(--text-secondary); font-size: .72rem; line-height: 1.5; }
  .identity-evidence { display: flex; align-items: center; gap: .45rem; color: var(--text-secondary); font: .68rem 'Geist Mono',monospace; }
  .identity-evidence > span:first-child { color: var(--state-passed); }
  .identity-evidence strong { color: var(--text-primary); }
  .foundation-action { display: flex; align-items: center; justify-content: space-between; gap: 1rem; border-top: 1px solid var(--border-hairline); margin-top: 1rem; padding-top: 1rem; }
  .foundation-action p { max-width: 40rem; color: var(--text-secondary); font-size: .76rem; line-height: 1.55; }
  .foundation-action p strong { color: var(--text-primary); font-weight: 600; }
  .action-copy { display: grid; gap: .35rem; }
  .action-copy small { max-width: 42rem; color: var(--text-muted); font-size: .66rem; line-height: 1.5; }
  .handoff-actions { display: grid; min-width: 13rem; gap: .45rem; }
  .foundation-action.danger { border-top-color: color-mix(in srgb,var(--state-failed) 35%,var(--border-hairline)); }
  a,button { min-height: 2.5rem; display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--border-strong); border-radius: 2px; padding: .55rem .8rem; color: var(--text-primary); font: 600 .65rem 'Geist Mono',monospace; white-space: nowrap; }
  a:hover,button:hover { border-color: var(--path-github); }
  .primary { border-color: var(--path-github); background: color-mix(in srgb,var(--path-github) 10%,var(--bg-panel)); color: var(--path-github); }
  .access-confirmed { display: flex; align-items: center; gap: .75rem; border-top: 1px solid var(--border-hairline); margin-top: 1rem; padding-top: 1rem; }
  .access-confirmed > span { display: grid; width: 1.6rem; height: 1.6rem; flex: 0 0 auto; place-items: center; border-radius: 50%; background: var(--state-passed); color: var(--text-inverse); font-size: .7rem; }
  .access-confirmed p { flex: 1; color: var(--text-secondary); font-size: .72rem; line-height: 1.5; }
  .access-confirmed strong { color: var(--text-primary); }
  .selected-repository { display: flex; align-items: center; justify-content: space-between; gap: 1rem; border-top: 1px solid var(--border-hairline); margin-top: 1rem; padding-top: 1rem; }
  .selected-repository > div:first-child { display: grid; min-width: 0; gap: .2rem; }
  .selected-repository span,.selected-repository small { color: var(--text-muted); font: 600 .6rem 'Geist Mono',monospace; letter-spacing: .08em; text-transform: uppercase; }
  .selected-repository strong { overflow: hidden; color: var(--text-primary); font: .85rem 'Geist Mono',monospace; text-overflow: ellipsis; }
  .selected-actions { display: flex; gap: .5rem; }
  @media (max-width: 660px) { header,.foundation-action,.selected-repository,.access-confirmed { align-items: stretch; flex-direction: column; } .identity-evidence { align-self: flex-start; } .handoff-actions { min-width: 0; } .selected-actions { display: grid; grid-template-columns: repeat(3,1fr); } }
  @media (max-width: 420px) { .selected-actions { grid-template-columns: 1fr; } }
</style>
