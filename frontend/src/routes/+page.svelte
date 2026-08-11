<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';

  onMount(() => {
    goto('/scans', { replaceState: true });
  });
</script>

<div class="p-8 text-[12px] font-mono text-ink-muted">Redirecting…</div>
