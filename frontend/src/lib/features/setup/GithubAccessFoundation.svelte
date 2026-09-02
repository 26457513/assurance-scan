<script lang="ts">
  import type { RepositorySearchState } from './controller';
  import type { SetupBootstrap } from './models';
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
</script>

<section class="foundation" data-setup-state={state.kind} aria-labelledby="github-foundation-heading">
  <header>
    <div>
      <p class="eyebrow">GitHub access foundation</p>
      <h2 id="github-foundation-heading">Let GitHub decide who can see each repository</h2>
    </div>
    {#if state.kind !== 'signed_out' && 'identity' in state}
      <div class="identity-evidence"><span aria-hidden="true">✓</span><span>Connected as <strong>@{state.identity.login}</strong></span></div>
    {/if}
  </header>

  {#if state.kind === 'signed_out'}
    <div class="foundation-action"><p>Sign in with GitHub to use repository access you already manage there.</p><a class="primary" href={state.sign_in_url}>Sign in with GitHub</a></div>
  {:else if state.kind === 'github_connected'}
    <div class="foundation-action"><p>Your GitHub identity is connected. Install the App on the repositories Assurance Scan may receive results from.</p><a class="primary" href={state.install_url}>Install GitHub App</a></div>
  {:else if state.kind === 'approval_pending'}
    <div class="foundation-action"><p>An organisation owner must approve the installation before repositories become available.</p><a href={state.request_url}>View request on GitHub</a></div>
  {:else if state.kind === 'installed_no_repositories'}
    <div class="foundation-action"><p>The App is installed for {state.installation.owner_login}, but no repositories are enabled.</p><a href={state.installation.manage_url}>Manage repository access</a></div>
  {:else if state.kind === 'installation_suspended'}
    <div class="foundation-action danger"><p>The GitHub App installation is suspended. Scan setup is locked until it is restored.</p><a href={state.installation.manage_url}>Manage GitHub App</a></div>
  {:else if state.kind === 'access_stale'}
    <div class="foundation-action danger"><p>GitHub access could not be refreshed. The last selection is shown only as stale evidence; setup actions are locked.</p><button type="button" on:click={onRetry}>Retry access check</button></div>
  {:else}
    {#if state.kind === 'repository_ready' || state.kind === 'repository_ready_write'}
      <div class="selected-repository">
        <div><span>Active repository</span><strong>{state.repository.full_name}</strong><small>{state.repository.default_branch} · {state.repository.permission} access</small></div>
        <div class="selected-actions"><a href={state.installation.manage_url}>Manage on GitHub</a><button type="button" on:click={onClear}>Choose another</button></div>
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
  .identity-evidence { display: flex; align-items: center; gap: .45rem; color: var(--text-secondary); font: .68rem 'Geist Mono',monospace; }
  .identity-evidence > span:first-child { color: var(--state-passed); }
  .identity-evidence strong { color: var(--text-primary); }
  .foundation-action { display: flex; align-items: center; justify-content: space-between; gap: 1rem; border-top: 1px solid var(--border-hairline); margin-top: 1rem; padding-top: 1rem; }
  .foundation-action p { max-width: 40rem; color: var(--text-secondary); font-size: .76rem; line-height: 1.55; }
  .foundation-action.danger { border-top-color: color-mix(in srgb,var(--state-failed) 35%,var(--border-hairline)); }
  a,button { min-height: 2.5rem; display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--border-strong); border-radius: 2px; padding: .55rem .8rem; color: var(--text-primary); font: 600 .65rem 'Geist Mono',monospace; white-space: nowrap; }
  a:hover,button:hover { border-color: var(--path-github); }
  .primary { border-color: var(--path-github); background: color-mix(in srgb,var(--path-github) 10%,var(--bg-panel)); color: var(--path-github); }
  .selected-repository { display: flex; align-items: center; justify-content: space-between; gap: 1rem; border-top: 1px solid var(--border-hairline); margin-top: 1rem; padding-top: 1rem; }
  .selected-repository > div:first-child { display: grid; min-width: 0; gap: .2rem; }
  .selected-repository span,.selected-repository small { color: var(--text-muted); font: 600 .6rem 'Geist Mono',monospace; letter-spacing: .08em; text-transform: uppercase; }
  .selected-repository strong { overflow: hidden; color: var(--text-primary); font: .85rem 'Geist Mono',monospace; text-overflow: ellipsis; }
  .selected-actions { display: flex; gap: .5rem; }
  @media (max-width: 660px) { header,.foundation-action,.selected-repository { align-items: stretch; flex-direction: column; } .identity-evidence { align-self: flex-start; } .selected-actions { display: grid; grid-template-columns: 1fr 1fr; } }
  @media (max-width: 420px) { .selected-actions { grid-template-columns: 1fr; } }
</style>
