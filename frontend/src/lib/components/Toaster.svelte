<script lang="ts">
  import { fly } from 'svelte/transition';
  import { toasts, dismissToast, type ToastKind } from '$lib/stores/toasts';

  const colorByKind: Record<ToastKind, string> = {
    info: 'var(--text-secondary)',
    success: 'var(--state-passed)',
    error: 'var(--state-failed)'
  };
</script>

<div class="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 items-end pointer-events-none">
  {#each $toasts as t (t.id)}
    <div
      transition:fly={{ y: 10, duration: 180 }}
      class="pointer-events-auto bg-surface-elevated border border-line-strong rounded-sm pl-3 pr-2 py-2 flex items-start gap-2.5 max-w-sm"
      style="box-shadow: 0 8px 24px rgba(0,0,0,0.4);"
    >
      <span class="mt-[3px] text-[10px] leading-none" style="color: {colorByKind[t.kind]}" aria-hidden="true">●</span>
      <span class="font-mono text-[12px] text-ink-primary leading-snug flex-1">{t.message}</span>
      <button
        type="button"
        on:click={() => dismissToast(t.id)}
        class="text-ink-muted hover:text-ink-primary -mr-0.5"
        aria-label="Dismiss"
      >
        <svg viewBox="0 0 12 12" class="h-3 w-3" stroke="currentColor" stroke-width="1.5" fill="none">
          <path d="M3 3l6 6M9 3l-6 6" stroke-linecap="round" />
        </svg>
      </button>
    </div>
  {/each}
</div>
