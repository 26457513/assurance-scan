<script lang="ts">
  import type { ArtifactListResponse } from '$lib/types';

  export let artifacts: ArtifactListResponse;

  function formatBytes(value: number | null): string {
    if (value == null) return '—';
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }

  function formatDate(value: string | null): string {
    if (!value) return '—';
    return new Intl.DateTimeFormat(undefined, {
      day: '2-digit', month: 'short', year: 'numeric'
    }).format(new Date(value));
  }
</script>

<div class="border border-line-hairline rounded-sm overflow-x-auto bg-surface-panel font-mono text-[11px]">
  <div class="grid min-w-[820px] grid-cols-[180px_minmax(190px,1fr)_90px_150px_120px_90px] gap-3 px-3 py-2 bg-surface-inset border-b border-line-hairline text-[10px] text-ink-muted items-center">
    <div>File</div>
    <div>Purpose</div>
    <div>Size</div>
    <div>SHA-256</div>
    <div>Available until</div>
    <div class="text-right">Action</div>
  </div>
  {#each artifacts.artifacts as artifact (artifact.name)}
    <div class="grid min-w-[820px] grid-cols-[180px_minmax(190px,1fr)_90px_150px_120px_90px] gap-3 px-3 py-2.5 border-b border-line-hairline last:border-b-0 items-center">
      <div class="text-ink-primary truncate" title={artifact.filename}>{artifact.filename}</div>
      <div class="text-ink-muted truncate" title={artifact.description}>{artifact.description}</div>
      <div class="text-ink-muted tabular-nums">{formatBytes(artifact.size_bytes)}</div>
      <div class="text-ink-muted truncate" title={artifact.content_hash ?? ''}>{artifact.content_hash?.replace('sha256:', '').slice(0, 12) ?? '—'}</div>
      <div class="text-ink-muted">{formatDate(artifact.expires_at)}</div>
      <div class="text-right">
        {#if artifact.available && artifact.download_url}
          <a class="text-accent hover:underline" href={artifact.download_url}>Download</a>
        {:else}
          <span class="text-ink-muted" title="The raw artifact retention period has ended">Expired</span>
        {/if}
      </div>
    </div>
  {:else}
    <div class="px-3 py-8 text-center text-ink-muted">No generated artifacts were published for this scan.</div>
  {/each}
</div>
<p class="mt-2 text-[11px] text-ink-muted">
  Raw artifacts are retained for {artifacts.retention_days} days. Normalized findings remain available with the scan history.
</p>
