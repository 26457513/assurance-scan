<script lang="ts">
  import { stateMeta } from '$lib/state';

  export let state: string;
  export let size: 'sm' | 'md' = 'md';
  export let showGlyph = true;

  $: meta = stateMeta(state);
  $: pad = size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-[11px]';
</script>

<span
  class="inline-flex items-center gap-1 font-mono uppercase tracking-wide rounded-sm border whitespace-nowrap {pad}"
  style="color: {meta.color}; background: color-mix(in srgb, {meta.color} 10%, transparent); border-color: color-mix(in srgb, {meta.color} 28%, transparent);"
>
  {#if showGlyph}<span aria-hidden="true" class="text-[0.85em]">{meta.glyph}</span>{/if}
  <span>{meta.label}</span>
</span>
