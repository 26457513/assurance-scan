<script lang="ts">
  // The standalone scans page is consolidated into the project view.
  import { goto } from '$app/navigation';
  goto('/projects', { replaceState: true });
</script>

<div class="p-6 text-[12px] text-ink-muted font-mono">Redirecting…</div>
