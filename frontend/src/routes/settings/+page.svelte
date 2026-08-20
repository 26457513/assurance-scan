<script lang="ts">
  // Settings merged into /setup; keep the route for old links.
  import { goto } from '$app/navigation';
  goto('/setup', { replaceState: true });
</script>

<div class="p-6 text-[12px] text-ink-muted font-mono">Redirecting…</div>
