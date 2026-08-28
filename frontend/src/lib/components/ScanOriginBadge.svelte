<script lang="ts">
  import type { ScanOrigin } from '$lib/types';

  export let origin: ScanOrigin;

  const labels: Record<ScanOrigin, string> = {
    'github-actions': 'GitHub Actions',
    local: 'Local',
    server: 'Server'
  };
</script>

<span
  class="inline-flex w-fit items-center rounded-sm border border-line-hairline bg-surface-inset px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.08em] text-ink-muted"
  data-origin={origin}
  title={`Scan origin: ${origin}`}
>
  {labels[origin]}
</span>
