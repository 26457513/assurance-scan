<script lang="ts">
  import { selectedScan } from '$lib/stores/selectedScan';
  import FixView from '$lib/components/FixView.svelte';
</script>

<div class="p-6 max-w-5xl">
  <div class="mb-6">
    <div class="text-[14px] text-ink-primary mb-2">Fix</div>
    {#if $selectedScan}
      <div class="text-[12px] text-ink-secondary leading-relaxed max-w-2xl">
        Showing the currently-selected scan
        <span class="font-mono text-ink-primary">{$selectedScan.run_id}</span>.
        <a href="/scans" class="text-accent hover:underline">Open a scan</a>
        to scope this view to a specific run, or use the scan selector in the header to switch.
      </div>
    {:else}
      <div class="text-[12px] text-ink-secondary leading-relaxed max-w-2xl">
        No scan selected. <a href="/scans" class="text-accent hover:underline">Open a scan</a>
        to see its fix workflow.
      </div>
    {/if}
  </div>

  {#if $selectedScan}
    {#key $selectedScan.run_id}
      <FixView scan={$selectedScan} showDescription={false} />
    {/key}
  {/if}
</div>
