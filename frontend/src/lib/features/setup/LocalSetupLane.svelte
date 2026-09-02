<script lang="ts">
  import LocalScanSetupPanel from '$lib/components/LocalScanSetupPanel.svelte';
  import ScanTokensPanel from '$lib/components/ScanTokensPanel.svelte';
  import type { LocalRunSummary, MachineTokenSummary, SetupRepository } from './models';

  export let repository: SetupRepository | null;
  export let enabled = false;
  export let tokens: MachineTokenSummary[] = [];
  export let latestRun: LocalRunSummary | null = null;

  let expanded = false;
  $: activeTokens = tokens.filter((token) => token.status === 'active').length;
</script>

<section
  class:locked={!enabled}
  class="scan-lane local"
  data-lane-state={enabled ? 'ready' : 'locked'}
  aria-labelledby="local-lane-heading"
>
  <header>
    <div><p>Developer workflow</p><h2 id="local-lane-heading">Local CLI</h2></div>
    <span class="visibility">Private to you</span>
  </header>
  {#if !repository}
    <p class="lane-intro">Choose an enabled repository with write access to configure private local scans.</p>
  {:else if !enabled}
    <p class="lane-intro">Local scanning requires current GitHub write access to <strong>{repository.full_name}</strong>.</p>
  {:else}
    <p class="lane-intro"><strong>Only you can see local scan runs.</strong> Repository access is rechecked before every upload.</p>
    <div class="local-evidence">
      <span>{activeTokens} active {activeTokens === 1 ? 'token' : 'tokens'}</span>
      {#if latestRun}
        <a href={`/scans/${latestRun.run_id}`}>{latestRun.display_title} · {latestRun.branch ?? 'detached'}</a>
      {:else}
        <small>No private local upload received for this repository.</small>
      {/if}
    </div>
    <div class="bearer-note">
      Machine labels help you recognise tokens; they do not prove which physical device holds a bearer token.
    </div>
    <button class="configure" type="button" on:click={() => (expanded = !expanded)} aria-expanded={expanded}>
      {expanded ? 'Hide local setup' : 'Set up local scanning'}
    </button>
    {#if expanded}
      <div class="expanded-setup">
        <ScanTokensPanel />
        <LocalScanSetupPanel />
      </div>
    {/if}
  {/if}
</section>

<style>
  .scan-lane { min-width: 0; border: 1px solid var(--border-hairline); border-top: 2px solid var(--path-local); background: var(--bg-panel); padding: 1.1rem; }
  .scan-lane.locked { opacity: .62; }
  header { display: flex; justify-content: space-between; gap: 1rem; }
  header p,.visibility { color: var(--path-local); font: 600 .58rem 'Geist Mono',monospace; letter-spacing: .12em; text-transform: uppercase; }
  h2 { margin-top: .2rem; color: var(--text-primary); font-size: 1rem; }
  .visibility { color: var(--text-muted); }
  .lane-intro { min-height: 3rem; margin-top: .8rem; color: var(--text-secondary); font-size: .74rem; line-height: 1.55; }
  .lane-intro strong { color: var(--text-primary); }
  .local-evidence { display: flex; min-height: 2.8rem; flex-wrap: wrap; align-items: center; gap: .6rem; border-block: 1px solid var(--border-hairline); padding: .65rem 0; color: var(--text-muted); font: .63rem 'Geist Mono',monospace; }
  .local-evidence > span { border: 1px solid color-mix(in srgb,var(--path-local) 35%,var(--border-strong)); padding: .28rem .45rem; color: var(--path-local); text-transform: uppercase; }
  .local-evidence a { color: var(--text-primary); }
  .configure { min-height: 2.4rem; margin-top: .8rem; border: 1px solid var(--border-strong); padding: .48rem .65rem; color: var(--text-secondary); font: 600 .62rem 'Geist Mono',monospace; }
  .configure:hover { border-color: var(--path-local); color: var(--path-local); }
  .expanded-setup { margin: 1rem -1.1rem -1.1rem; border-top: 1px solid var(--border-hairline); padding: 0 1.1rem 1.1rem; }
  .bearer-note { border-left: 2px solid var(--path-local); margin-top: .8rem; padding: .55rem .7rem; background: var(--bg-inset); color: var(--text-secondary); font-size: .68rem; line-height: 1.45; }
  .expanded-setup :global(.token-panel) { margin-top: 1rem; }
</style>
