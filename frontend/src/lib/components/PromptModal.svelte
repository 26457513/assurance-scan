<script lang="ts">
  import { createEventDispatcher, onMount, onDestroy } from 'svelte';
  import CopyButton from './CopyButton.svelte';

  export let title = 'Prompt';
  export let prompt = '';

  const dispatch = createEventDispatcher<{ close: void }>();

  function close() {
    dispatch('close');
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    }
  }

  onMount(() => {
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
  });

  onDestroy(() => {
    document.removeEventListener('keydown', onKey);
    document.body.style.overflow = '';
  });
</script>

<div class="fixed inset-0 z-50 flex items-center justify-center p-4">
  <button
    type="button"
    class="absolute inset-0 bg-black/65 backdrop-blur-[2px]"
    on:click={close}
    aria-label="Close modal"
  ></button>

  <div
    role="dialog"
    aria-modal="true"
    aria-label={title}
    class="relative w-full max-w-3xl max-h-[85vh] bg-surface-panel border border-line-strong rounded-md flex flex-col"
    style="box-shadow: 0 24px 64px rgba(0,0,0,0.5), 0 0 0 1px var(--border-strong);"
  >
    <header class="flex items-center justify-between px-5 py-3.5 border-b border-line-hairline">
      <h2 class="text-sm font-medium tracking-tight text-ink-primary">{title}</h2>
      <div class="flex items-center gap-2">
        <CopyButton text={prompt} label="Copy prompt" />
        <button
          type="button"
          on:click={close}
          class="text-ink-muted hover:text-ink-primary p-1 rounded-sm hover:bg-surface-elevated transition-colors"
          aria-label="Close"
        >
          <svg viewBox="0 0 12 12" class="h-3.5 w-3.5" stroke="currentColor" stroke-width="1.6" fill="none">
            <path d="M3 3l6 6M9 3l-6 6" stroke-linecap="round" />
          </svg>
        </button>
      </div>
    </header>

    <div class="px-5 py-2 text-[10px] text-ink-muted font-mono uppercase tracking-[0.12em] border-b border-line-hairline bg-surface-inset">
      Paste into Claude Code · do not edit
    </div>

    <div class="flex-1 overflow-auto p-5 bg-surface-inset">
      <pre class="font-mono text-[12px] leading-[1.65] text-ink-secondary whitespace-pre-wrap break-words">{prompt}</pre>
    </div>
  </div>
</div>
