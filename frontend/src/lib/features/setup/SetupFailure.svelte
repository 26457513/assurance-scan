<script lang="ts">
  export let message: string;
  export let onRetry: () => void;
</script>

<section class="setup-failure" role="alert" aria-labelledby="setup-failure-heading">
  <div aria-hidden="true">!</div>
  <span><strong id="setup-failure-heading">Setup state could not be verified</strong><small>{message}</small></span>
  <button type="button" on:click={onRetry}>Retry setup</button>
</section>

<style>
  .setup-failure { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: .8rem; border: 1px solid color-mix(in srgb,var(--state-failed) 45%,var(--border-hairline)); background: var(--bg-panel); padding: 1rem; }
  .setup-failure > div { display: grid; width: 1.6rem; height: 1.6rem; place-items: center; border: 1px solid var(--state-failed); color: var(--state-failed); font: 700 .75rem 'Geist Mono',monospace; }
  span { display: grid; gap: .2rem; }
  strong { color: var(--text-primary); font-size: .78rem; }
  small { color: var(--text-secondary); font-size: .7rem; line-height: 1.45; }
  button { min-height: 2.5rem; border: 1px solid var(--border-strong); padding: .5rem .75rem; color: var(--text-primary); font: 600 .65rem 'Geist Mono',monospace; }
  @media (max-width: 520px) { .setup-failure { grid-template-columns: auto 1fr; } button { grid-column: 1 / -1; } }
</style>
