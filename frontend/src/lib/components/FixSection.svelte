<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import PromptModal from './PromptModal.svelte';

  export let step: number | null = null;
  export let title: string;
  export let count: number;
  export let locked = false;
  export let lockReason = '';
  export let prompt: string;
  export let promptTitle: string;
  export let isCurrent = false;

  const dispatch = createEventDispatcher<{ skip: void }>();

  let open = false;

  function open_() {
    if (locked || count === 0) return;
    open = true;
  }

  $: complete = !locked && count === 0;
</script>

<section
  class="border rounded-sm bg-surface-panel transition-opacity duration-200"
  class:border-line-hairline={!isCurrent || complete}
  class:border-accent={isCurrent && !complete}
  class:opacity-50={locked}
>
  <header class="px-5 py-4 flex items-center gap-4">
    <!-- Status indicator (only shows when there's a meaningful state) -->
    {#if complete}
      <div class="w-7 h-7 rounded-sm border border-line-hairline flex items-center justify-center font-mono text-[12px] shrink-0 text-ink-muted">
        ✓
      </div>
    {:else if locked}
      <div class="w-7 h-7 rounded-sm border border-line-hairline flex items-center justify-center font-mono text-[12px] shrink-0 text-ink-muted">
        🔒
      </div>
    {:else if step !== null}
      <div
        class="w-7 h-7 rounded-sm border flex items-center justify-center font-mono text-[12px] shrink-0"
        class:border-accent={isCurrent}
        class:bg-accent-subtle={isCurrent}
        class:text-accent={isCurrent}
        class:border-line-strong={!isCurrent}
        class:text-ink-primary={!isCurrent}
      >
        {step}
      </div>
    {/if}


    <!-- Title + count -->
    <div class="flex-1 min-w-0">
      <div class="text-[14px] text-ink-primary">{title}</div>
      <div class="font-mono text-[11px] text-ink-muted mt-0.5">
        {#if complete}
          complete · nothing to do
        {:else if locked}
          {count} item{count === 1 ? '' : 's'} waiting
        {:else}
          {count} item{count === 1 ? '' : 's'}
        {/if}
      </div>
    </div>

    <!-- Right-side action -->
    {#if locked}
      <div class="flex items-center gap-3 shrink-0">
        <span class="font-mono text-[11px] text-ink-muted hidden sm:inline">{lockReason}</span>
        <button
          type="button"
          on:click={() => dispatch('skip')}
          class="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-muted hover:text-accent transition-colors"
          title="Unlock this section without completing the previous step"
        >Skip →</button>
      </div>
    {:else if complete}
      <span class="font-mono text-[11px] text-state-passed shrink-0">✓ done</span>
    {:else}
      <button
        type="button"
        on:click={open_}
        class="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.08em] rounded-sm px-2.5 py-1 border transition-colors hover:bg-surface-elevated shrink-0"
        style="color: var(--accent); border-color: color-mix(in srgb, var(--accent) 35%, transparent); background: color-mix(in srgb, var(--accent) 8%, transparent);"
      >
        <svg viewBox="0 0 12 12" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="1.4">
          <path d="M2.5 6h7M7 3l2.5 3-2.5 3" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <span>Copy prompt</span>
      </button>
    {/if}
  </header>
</section>

{#if open}
  <PromptModal title={promptTitle} prompt={prompt} on:close={() => (open = false)} />
{/if}
