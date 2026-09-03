<script lang="ts">
  import type { SetupBootstrap } from './models';

  export let bootstrap: SetupBootstrap;

  $: state = bootstrap.state;
  $: signedIn = state.kind !== 'signed_out';
  $: enabledRepositories = bootstrap.installations.reduce(
    (total, installation) => total + installation.enabled_repository_count,
    0
  );
  $: accessChosen = enabledRepositories > 0;
  $: confirmed =
    accessChosen &&
    state.kind !== 'approval_pending' &&
    state.kind !== 'access_stale' &&
    state.kind !== 'installation_suspended';
</script>

<ol class="access-steps" aria-label="GitHub access setup progress">
  <li class:complete={signedIn} class:active={!signedIn}>
    <span class="step-marker" aria-hidden="true">{signedIn ? '✓' : '1'}</span>
    <span class="step-copy">
      <strong>Sign in</strong>
      <small>{signedIn && 'identity' in state ? `Connected as @${state.identity.login}` : 'Use your GitHub identity'}</small>
    </span>
  </li>
  <li class:complete={accessChosen} class:active={signedIn && !accessChosen}>
    <span class="step-marker" aria-hidden="true">{accessChosen ? '✓' : '2'}</span>
    <span class="step-copy">
      <strong>Choose access</strong>
      <small>{accessChosen ? `${enabledRepositories} ${enabledRepositories === 1 ? 'repository' : 'repositories'} enabled` : 'Select organisations and repositories on GitHub'}</small>
    </span>
  </li>
  <li class:complete={confirmed} class:active={accessChosen && !confirmed}>
    <span class="step-marker" aria-hidden="true">{confirmed ? '✓' : '3'}</span>
    <span class="step-copy">
      <strong>Return automatically</strong>
      <small>{confirmed ? 'Access verified' : 'Assurance Scan confirms the selection'}</small>
    </span>
  </li>
</ol>

<style>
  .access-steps {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    margin-top: 1rem;
    border: 1px solid var(--border-hairline);
    background: var(--bg-inset);
  }

  li {
    position: relative;
    display: flex;
    min-width: 0;
    align-items: center;
    gap: .7rem;
    padding: .9rem;
    opacity: .52;
  }

  li + li { border-left: 1px solid var(--border-hairline); }
  li.active, li.complete { opacity: 1; }
  li.active { background: color-mix(in srgb, var(--path-github) 6%, transparent); }

  .step-marker {
    display: grid;
    width: 1.55rem;
    height: 1.55rem;
    flex: 0 0 auto;
    place-items: center;
    border: 1px solid var(--border-strong);
    border-radius: 50%;
    color: var(--text-muted);
    font: 600 .65rem 'Geist Mono', monospace;
  }

  .active .step-marker {
    border-color: var(--path-github);
    color: var(--path-github);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--path-github) 10%, transparent);
  }

  .complete .step-marker {
    border-color: var(--state-passed);
    background: var(--state-passed);
    color: var(--text-inverse);
  }

  .step-copy { display: grid; min-width: 0; gap: .22rem; }
  .step-copy strong { color: var(--text-primary); font-size: .74rem; font-weight: 600; }
  .step-copy small { color: var(--text-muted); font-size: .65rem; line-height: 1.35; }

  @media (max-width: 720px) {
    .access-steps { grid-template-columns: 1fr; }
    li + li { border-top: 1px solid var(--border-hairline); border-left: 0; }
  }
</style>
