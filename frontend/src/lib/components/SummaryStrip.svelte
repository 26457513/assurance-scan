<script lang="ts">
  import StatePill from './StatePill.svelte';
  import type { FrListSummary } from '$lib/types';

  type Entry = { state: string; count: number };

  export let summary: FrListSummary | Record<string, number>;

  let entries: Entry[] = [];

  function compute(s: FrListSummary | Record<string, number>) {
    if (s && typeof s === 'object' && 'total' in s) {
      const fr = s as FrListSummary;
      entries = [
        { state: 'passed', count: fr.passed },
        { state: 'failed', count: fr.failed },
        { state: 'untested', count: fr.untested },
        { state: 'pending', count: fr.pending },
        { state: 'blocked', count: fr.blocked },
        { state: 'waived', count: fr.waived }
      ];
    } else {
      entries = Object.entries(s as Record<string, number>).map(([state, count]) => ({
        state,
        count: count as number
      }));
    }
  }

  $: compute(summary);
</script>

<div class="flex items-center gap-3 flex-wrap">
  {#each entries as e (e.state)}
    {#if e.count > 0}
      <div class="flex items-center gap-1.5">
        <span class="font-mono text-[13px] tabular-nums text-ink-primary">{e.count}</span>
        <StatePill state={e.state} size="sm" />
      </div>
    {/if}
  {/each}
</div>
