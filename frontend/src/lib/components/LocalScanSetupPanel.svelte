<script lang="ts">
  import { onMount } from 'svelte';

  import CopyButton from './CopyButton.svelte';

  let serverUrl = 'https://scan.example.com';
  let wrapperSha = 'loading…';

  onMount(async () => {
    serverUrl = window.location.origin;
    try {
      const response = await fetch('/api/v2/cli/releases/wrapper.sha256');
      if (response.ok) wrapperSha = (await response.text()).trim();
    } catch {
      wrapperSha = 'unavailable';
    }
  });

  $: installCommand = `mkdir -p "$HOME/.local/bin"
tmp_wrapper=$(mktemp "\${TMPDIR:-/tmp}/assurance-scan.XXXXXX")
curl -fsS ${serverUrl}/api/v2/cli/releases/wrapper -o "$tmp_wrapper"
echo "${wrapperSha}  $tmp_wrapper" | { command -v sha256sum >/dev/null && sha256sum -c - || shasum -a 256 -c -; }
install -m 0755 "$tmp_wrapper" "$HOME/.local/bin/assurance-scan" && rm -f "$tmp_wrapper"`;
  $: loginCommand = `assurance-scan auth login --url ${serverUrl}`;
  const scanCommand = 'assurance-scan scan';
  const retryCommand = 'assurance-scan upload --retry REQUEST_ID';
  const cacheCommand = 'assurance-scan cache list';
  const pruneCommand = 'assurance-scan cache prune';
  const logoutCommand = 'assurance-scan auth logout';
  $: wrapperReady = /^[0-9a-f]{64}$/.test(wrapperSha);
</script>

<section id="local-scanner-setup" class="local-runbook" aria-labelledby="local-scan-setup-heading">
  <div class="flex flex-wrap items-start justify-between gap-4 border-b border-line-hairline p-5">
    <div>
      <div class="text-[9px] font-mono uppercase tracking-[0.16em] text-accent mb-1">Local scanner · container workflow</div>
      <h2 id="local-scan-setup-heading" class="text-[13px] text-ink-primary font-mono mb-1">
        Install once. Scan any branch.
      </h2>
      <p class="text-[11px] text-ink-muted leading-relaxed max-w-xl">
        Install the small verified wrapper, enroll this machine once, then use one command from any
        registered Git repository. The wrapper keeps the container trust checks out of your way.
      </p>
    </div>
    <div class="trust-seal" aria-label="Verified release policy">
      <span aria-hidden="true">✓</span>
      Signed image · immutable digest
    </div>
  </div>

  <ol class="runbook-steps">
    <li class="runbook-step">
      <div class="runbook-marker" aria-hidden="true">1</div>
      <div class="min-w-0 flex-1">
        <div class="flex items-baseline justify-between gap-3 mb-2">
          <div>
            <h3 class="text-[11px] font-mono text-ink-primary">Install the host wrapper</h3>
            <p class="text-[10px] text-ink-muted mt-0.5">Works on supported macOS and Linux hosts.</p>
          </div>
          {#if wrapperReady}
            <CopyButton text={installCommand} label="Copy install" copiedLabel="Install copied" />
          {:else}
            <span class="text-[9px] font-mono uppercase tracking-[0.1em] text-ink-muted">Preparing…</span>
          {/if}
        </div>
        <pre class="command-block">{installCommand}</pre>
        <p class="text-[10px] text-ink-muted leading-relaxed mt-2 break-all">
          Expected SHA-256: <code>{wrapperSha}</code>. The wrapper verifies the signed release
          manifest and image before it runs an immutable digest.
        </p>
      </div>
    </li>

    <li class="runbook-step">
      <div class="runbook-marker" aria-hidden="true">2</div>
      <div class="min-w-0 flex-1">
        <div class="flex items-baseline justify-between gap-3 mb-1">
          <h3 class="text-[11px] font-mono text-ink-primary">Create an upload token</h3>
          <span class="text-[9px] font-mono uppercase tracking-[0.1em] text-ink-muted">in this page</span>
        </div>
        <p class="text-[11px] text-ink-muted leading-relaxed">
          Use a machine label such as “work laptop”, copy the token when it appears, and leave this
          page open. It is shown once and can only upload scans.
        </p>
      </div>
    </li>

    <li class="runbook-step">
      <div class="runbook-marker" aria-hidden="true">3</div>
      <div class="min-w-0 flex-1">
        <div class="flex items-baseline justify-between gap-3 mb-2">
          <h3 class="text-[11px] font-mono text-ink-primary">Enroll this machine once</h3>
          <CopyButton text={loginCommand} label="Copy login" copiedLabel="Login copied" />
        </div>
        <pre class="command-block">{loginCommand}</pre>
        <p class="text-[10px] text-ink-muted leading-relaxed mt-2">
          Saved as <code>$HOME/.config/assurance-scan/config.json</code> with file mode
          <code>0600</code>; its directory is <code>0700</code>. The CLI validates this account and
          refuses symlinked, group-readable, or other-user-owned credentials.
        </p>
      </div>
    </li>

    <li class="runbook-step">
      <div class="runbook-marker" aria-hidden="true">4</div>
      <div class="min-w-0 flex-1">
        <div class="flex items-baseline justify-between gap-3 mb-2">
          <div>
            <h3 class="text-[11px] font-mono text-ink-primary">Scan from the repository root</h3>
            <p class="text-[10px] text-ink-muted mt-0.5">The repository must already be registered under Projects.</p>
          </div>
          <CopyButton text={scanCommand} label="Copy scan" copiedLabel="Scan copied" />
        </div>
        <pre class="command-block">{scanCommand}</pre>
        <p class="text-[10px] text-ink-muted leading-relaxed mt-2">
          The wrapper checks for a signed update once per day, rejects remote Docker contexts, and
          shares only this run's read-only source snapshot with the pinned scanner containers.
        </p>
      </div>
    </li>
  </ol>

  <div class="grid gap-px border-t border-line-hairline bg-line-hairline sm:grid-cols-3">
    <div class="bg-surface-panel p-4">
      <div class="flex items-center justify-between gap-2 mb-2">
        <h3 class="text-[10px] font-mono uppercase tracking-[0.11em] text-ink-secondary">Retry an upload</h3>
        <CopyButton text={retryCommand} label="Copy" />
      </div>
      <p class="text-[10px] text-ink-muted leading-relaxed mb-2">
        Replace <code>REQUEST_ID</code> with the ID printed after a failed upload. The exact saved
        bundle is retried without rescanning.
      </p>
      <code class="text-[9px] text-ink-secondary font-mono">upload --retry REQUEST_ID</code>
    </div>
    <div class="bg-surface-panel p-4">
      <div class="flex items-center justify-between gap-2 mb-2">
        <h3 class="text-[10px] font-mono uppercase tracking-[0.11em] text-ink-secondary">Inspect the outbox</h3>
        <div class="flex gap-1">
          <CopyButton text={cacheCommand} label="Copy list" />
          <CopyButton text={pruneCommand} label="Copy prune" />
        </div>
      </div>
      <p class="text-[10px] text-ink-muted leading-relaxed mb-2">
        Bundles live under <code>$HOME/.cache/assurance-scan</code>. List retained request IDs or
        safely clean the seven-day, 1 GiB outbox without deleting an active request.
      </p>
      <code class="text-[9px] text-ink-secondary font-mono">cache list · cache prune</code>
    </div>
    <div class="bg-surface-panel p-4">
      <div class="flex items-center justify-between gap-2 mb-2">
        <h3 class="text-[10px] font-mono uppercase tracking-[0.11em] text-ink-secondary">Remove access</h3>
        <CopyButton text={logoutCommand} label="Copy" />
      </div>
      <p class="text-[10px] text-ink-muted leading-relaxed mb-2">
        Revoke the token above to stop future uploads immediately. Then run logout to remove the
        local credential while preserving the non-secret installation ID.
      </p>
      <code class="text-[9px] text-ink-secondary font-mono">auth logout</code>
    </div>
  </div>

  <div class="border-t border-line-hairline bg-surface-inset px-5 py-4" aria-label="Local scan data and retention">
    <div class="text-[9px] font-mono uppercase tracking-[0.14em] text-ink-muted mb-3">Data boundary & retention</div>
    <div class="grid gap-4 sm:grid-cols-3">
      <div>
        <h3 class="text-[10px] font-mono text-ink-secondary mb-1">Uploaded</h3>
        <p class="text-[10px] text-ink-muted leading-relaxed">
          Repository metadata, normalized findings, SARIF, and the CycloneDX SBOM. The source
          snapshot and absolute host paths are not uploaded.
        </p>
      </div>
      <div>
        <h3 class="text-[10px] font-mono text-ink-secondary mb-1">Isolated</h3>
        <p class="text-[10px] text-ink-muted leading-relaxed">
          The upload token stays in the outer CLI and is never passed to scanner containers.
          Semgrep, Gitleaks, and Syft run with no network; vulnerability tools use bridge networking
          so they can refresh their databases.
        </p>
      </div>
      <div>
        <h3 class="text-[10px] font-mono text-ink-secondary mb-1">Retained</h3>
        <p class="text-[10px] text-ink-muted leading-relaxed">
          Raw artifacts: 30 days. Normalized runs and findings: 365 days. Inactive-token audit:
          400 days. Deleting a run or project removes its scan data; a content-free request
          tombstone can remain for 30 days to prevent unsafe retry reuse.
        </p>
      </div>
    </div>
  </div>

  <p class="border-t border-line-hairline px-5 py-3 text-[10px] text-ink-muted leading-relaxed">
    Run <code>assurance-scan doctor</code> to inspect the verified CLI digest and local Docker
    endpoint, or <code>assurance-scan update</code> to force a signed update check. Native Windows
    and WSL 2 are not v1 targets.
  </p>
</section>

<style>
  .local-runbook {
    margin-top: 1rem;
    overflow: hidden;
    border: 1px solid var(--border-hairline);
    border-radius: 2px;
    background: var(--bg-panel);
  }

  .runbook-steps {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .runbook-step {
    position: relative;
    display: flex;
    gap: 0.875rem;
    padding: 1rem 1.25rem;
    border-bottom: 1px solid var(--border-hairline);
  }

  .runbook-step:not(:last-child)::after {
    position: absolute;
    top: 2.25rem;
    bottom: -0.75rem;
    left: 1.84rem;
    width: 1px;
    content: '';
    background: color-mix(in srgb, var(--accent) 30%, var(--border-hairline));
  }

  .runbook-marker {
    z-index: 1;
    display: grid;
    width: 1.25rem;
    height: 1.25rem;
    flex: 0 0 auto;
    place-items: center;
    border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--border-hairline));
    border-radius: 999px;
    background: var(--bg-inset);
    color: var(--accent);
    font-family: 'Geist Mono', ui-monospace, monospace;
    font-size: 0.6rem;
  }

  .trust-seal {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    border: 1px solid color-mix(in srgb, var(--accent) 35%, var(--border-hairline));
    border-radius: 999px;
    background: color-mix(in srgb, var(--accent) 7%, var(--bg-panel));
    padding: 0.35rem 0.65rem;
    color: var(--text-muted);
    font-family: 'Geist Mono', ui-monospace, monospace;
    font-size: 0.5625rem;
    letter-spacing: 0.07em;
    text-transform: uppercase;
  }

  .trust-seal span {
    color: var(--accent);
  }

  .command-block {
    max-height: 15rem;
    overflow: auto;
    border: 1px solid var(--border-hairline);
    border-left: 2px solid color-mix(in srgb, var(--accent) 60%, transparent);
    border-radius: 2px;
    background: var(--bg-inset);
    padding: 0.75rem;
    color: var(--text-secondary);
    font-family: 'Geist Mono', ui-monospace, monospace;
    font-size: 0.625rem;
    line-height: 1.55;
    white-space: pre;
  }

  @media (max-width: 640px) {
    .runbook-step { padding-inline: 1rem; }
    .runbook-step:not(:last-child)::after { left: 1.59rem; }
  }
</style>
