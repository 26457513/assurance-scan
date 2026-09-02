<script lang="ts">
  import type { SetupBootstrap } from './models';

  export let bootstrap: SetupBootstrap;

  $: state = bootstrap.state;
  $: identityReady = state.kind !== 'signed_out';
  $: installationReady = bootstrap.installations.length > 0;
  $: repositoryReady = state.kind === 'repository_ready' || state.kind === 'repository_ready_write';
  $: repositoryName = 'repository' in state ? state.repository.full_name : 'Choose one';
  $: localReady = state.kind === 'repository_ready_write' && state.capabilities.can_local_scan;
</script>

<section class="topology" data-responsive-region="access-topology" aria-labelledby="access-topology-heading">
  <div class="topology-label">
    <span>Access topology</span>
    <h2 id="access-topology-heading">One identity. Two trusted scan paths.</h2>
  </div>
  <div class="topology-flow" role="list" aria-label="Assurance Scan access path">
    <div class:ready={identityReady} class="topology-node" role="listitem">
      <span class="node-state" aria-hidden="true"></span>
      <span class="node-copy"><small>Identity</small><strong>{identityReady && 'identity' in state ? `@${state.identity.login}` : 'GitHub'}</strong></span>
    </div>
    <span class="connector" aria-hidden="true"></span>
    <div class:ready={installationReady} class="topology-node" role="listitem">
      <span class="node-state" aria-hidden="true"></span>
      <span class="node-copy"><small>Installation</small><strong>{installationReady ? `${bootstrap.installations.length} available` : 'Required'}</strong></span>
    </div>
    <span class="connector" aria-hidden="true"></span>
    <div class:ready={repositoryReady} class="topology-node" role="listitem">
      <span class="node-state" aria-hidden="true"></span>
      <span class="node-copy"><small>Repository</small><strong>{repositoryName}</strong></span>
    </div>
    <span class="fork" aria-hidden="true"></span>
    <div class="topology-destinations" role="listitem">
      <div class:ready={repositoryReady} class="destination github">
        <small>GitHub Actions</small><strong>Team visible</strong>
      </div>
      <div class:ready={localReady} class="destination local">
        <small>Local CLI</small><strong>Private to you</strong>
      </div>
    </div>
  </div>
</section>

<style>
  .topology { display: grid; grid-template-columns: 12rem minmax(0, 1fr); border: 1px solid var(--border-hairline); background: var(--bg-inset); }
  .topology-label { display: flex; flex-direction: column; justify-content: center; gap: .35rem; border-right: 1px solid var(--border-hairline); padding: 1rem 1.25rem; }
  .topology-label span, small { color: var(--text-muted); font: 600 .58rem/1.2 'Geist Mono', monospace; letter-spacing: .13em; text-transform: uppercase; }
  .topology-label h2 { max-width: 10rem; color: var(--text-primary); font-size: .8rem; font-weight: 700; line-height: 1.35; }
  .topology-flow { display: grid; grid-template-columns: minmax(7rem,1fr) 1.5rem minmax(7rem,1fr) 1.5rem minmax(9rem,1.35fr) 2rem minmax(9rem,1fr); align-items: center; min-width: 0; padding: .75rem 1rem; }
  .topology-node { display: flex; align-items: center; min-width: 0; gap: .55rem; opacity: .55; }
  .topology-node.ready { opacity: 1; }
  .node-state { width: .55rem; height: .55rem; flex: 0 0 auto; border: 1px solid var(--border-strong); background: var(--bg-panel); }
  .ready .node-state { border-color: var(--state-passed); background: var(--state-passed); box-shadow: 0 0 0 3px color-mix(in srgb, var(--state-passed) 12%, transparent); }
  .node-copy { display: flex; min-width: 0; flex-direction: column; gap: .2rem; }
  .node-copy strong, .destination strong { overflow: hidden; color: var(--text-secondary); font: 500 .68rem/1.2 'Geist Mono', monospace; text-overflow: ellipsis; white-space: nowrap; }
  .connector { height: 1px; background: var(--border-strong); }
  .fork { height: 2.6rem; border-top: 1px solid var(--border-strong); border-right: 1px solid var(--border-strong); border-bottom: 1px solid var(--border-strong); }
  .topology-destinations { display: grid; gap: .45rem; }
  .destination { display: flex; min-width: 0; justify-content: space-between; gap: .5rem; border-left: 2px solid var(--border-strong); padding: .35rem .55rem; opacity: .55; }
  .destination.ready { opacity: 1; }
  .destination.github { border-left-color: var(--path-github); }
  .destination.local { border-left-color: var(--path-local); }
  @media (max-width: 900px) {
    .topology { grid-template-columns: 1fr; }
    .topology-label { border-right: 0; border-bottom: 1px solid var(--border-hairline); }
    .topology-label h2 { max-width: none; }
    .topology-flow { grid-template-columns: 1fr; gap: .55rem; }
    .connector { width: 1px; height: .65rem; margin-left: .25rem; }
    .fork { display: none; }
    .topology-destinations { grid-template-columns: 1fr 1fr; }
  }
  @media (max-width: 430px) { .topology-destinations { grid-template-columns: 1fr; } }
</style>
