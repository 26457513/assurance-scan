<script lang="ts">
  export let text: string;
  export let label = 'Copy';
  export let copiedLabel = 'Copied';

  let copied = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => (copied = false), 1500);
    } catch (e) {
      console.error('clipboard write failed', e);
    }
  }
</script>

<button
  type="button"
  on:click={copy}
  class="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wide rounded-sm border border-line-strong px-2.5 py-1 transition-colors duration-150 hover:bg-surface-elevated"
  class:text-accent={copied}
>
  {#if copied}
    <svg viewBox="0 0 12 12" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M2.5 6.5l2.5 2.5 4.5-5" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    <span>{copiedLabel}</span>
  {:else}
    <svg viewBox="0 0 12 12" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="1.3">
      <rect x="3.5" y="3.5" width="6" height="6" rx="0.5" />
      <path d="M2 8V2.5C2 2.224 2.224 2 2.5 2H8" stroke-linecap="round" />
    </svg>
    <span>{label}</span>
  {/if}
</button>
