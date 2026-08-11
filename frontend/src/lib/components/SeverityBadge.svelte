<script lang="ts">
  import { severityMeta } from '$lib/state';

  export let severity: string;
  export let count: number | null = null;

  $: meta = severityMeta(severity);
</script>

<span
  class="inline-flex items-center gap-1.5 font-mono text-[11px] tracking-wide whitespace-nowrap"
  style="color: {meta.color};"
  title={severity}
>
  {#if count !== null}
    <span class="text-ink-primary font-medium tabular-nums">{count}</span>
  {/if}
  <span class="opacity-80">{meta.label}</span>
</span>
