<script lang="ts">
  import { onMount } from 'svelte';

  import { api } from '$lib/api';
  import CopyButton from './CopyButton.svelte';

  let workflow = '';
  let filename = '.github/workflows/assurance-scan.yml';
  let image = 'ghcr.io/26457513/assurance-scan-ci:latest';
  let loading = true;
  let error = '';

  async function generateWorkflow() {
    loading = true;
    error = '';
    try {
      const response = await api.getCiWorkflowTemplate();
      workflow = response.workflow;
      filename = response.filename;
      image = response.image;
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading = false;
    }
  }

  onMount(generateWorkflow);
</script>

<section class="border border-line-hairline rounded-sm bg-surface-panel mb-4" aria-labelledby="ci-workflow-heading">
  <div class="flex flex-wrap items-start justify-between gap-4 border-b border-line-hairline p-5">
    <div class="min-w-0">
      <div class="text-[9px] font-mono uppercase tracking-[0.16em] text-accent mb-1">
        GitHub scanner · repository workflow
      </div>
      <h2 id="ci-workflow-heading" class="text-[13px] text-ink-primary font-mono mb-1">
        Add one complete workflow file
      </h2>
      <p class="text-[11px] text-ink-muted leading-relaxed max-w-xl">
        Copy this file into each repository. GitHub scans accepted pushes to the default branch;
        developers scan feature branches locally before merge.
      </p>
    </div>
    <div class="border border-line-strong rounded-sm bg-surface-inset px-2.5 py-1 text-[9px] font-mono uppercase tracking-[0.1em] text-ink-muted">
      Default branch pushes
    </div>
  </div>

  <div class="p-5">
    <div class="border border-line-hairline rounded-sm bg-surface-inset overflow-hidden">
      <div class="flex items-center justify-between gap-3 px-3 py-2 border-b border-line-hairline">
        <code class="text-[10px] font-mono text-ink-secondary truncate">{filename}</code>
        {#if workflow}
          <CopyButton text={workflow} label="Copy workflow" />
        {/if}
      </div>
      {#if error}
        <div class="px-3 py-4 text-[11px] font-mono" style="color: var(--state-failed);">
          Workflow unavailable: {error}
        </div>
      {:else if workflow}
        <pre class="max-h-80 overflow-auto whitespace-pre p-3 text-[10px] leading-relaxed font-mono text-ink-primary">{workflow}</pre>
      {:else}
        <div class="px-3 py-4 text-[11px] font-mono text-ink-muted">Loading workflow…</div>
      {/if}
    </div>

    <div class="mt-3 grid gap-1 text-[10px] leading-relaxed font-mono text-ink-muted">
      <div>Default image: <code class="text-ink-secondary">{image}</code></div>
      <div>The job follows GitHub’s current default branch automatically; the file does not need regenerating after a branch rename.</div>
      <div>Pin when required: replace <code class="text-ink-secondary">:latest</code> with an approved <code class="text-ink-secondary">:vX.Y.Z</code> or <code class="text-ink-secondary">@sha256:&lt;digest&gt;</code>.</div>
      <div>The workflow writes a safe job summary, retains a bounded diagnostic bundle for seven days, and pushes the result here with GitHub OIDC. No secret is required.</div>
    </div>
  </div>
</section>
