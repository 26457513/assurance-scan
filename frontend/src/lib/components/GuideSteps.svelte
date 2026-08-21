<script lang="ts">
  export let steps: { title: string; detail?: string }[] = [];
</script>

<ol class="space-y-3">
  {#each steps as s, i (i)}
    <li class="flex gap-3 items-start">
      <span
        class="shrink-0 w-5 h-5 rounded-full border border-line-strong bg-surface-elevated font-mono text-[10px] text-ink-secondary flex items-center justify-center mt-px"
      >{i + 1}</span>
      <div class="min-w-0">
        <div class="text-[12px] text-ink-primary leading-snug">{s.title}</div>
        {#if s.detail}
          <div class="text-[11px] text-ink-muted leading-relaxed mt-0.5">{@html s.detail}</div>
        {/if}
      </div>
    </li>
  {/each}
</ol>
