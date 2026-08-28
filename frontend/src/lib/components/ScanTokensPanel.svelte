<script lang="ts">
  import { onMount } from 'svelte';

  import { api } from '$lib/api';
  import type { ScanToken, ScanTokenExpiryDays } from '$lib/types';

  import CopyButton from './CopyButton.svelte';

  const EXPIRY_OPTIONS: { days: ScanTokenExpiryDays; label: string }[] = [
    { days: 30, label: '30 days' },
    { days: 90, label: '90 days' },
    { days: 180, label: '180 days' }
  ];

  let tokens: ScanToken[] = [];
  let csrfToken = '';
  let loading = true;
  let loadError = '';
  let label = '';
  let expiryDays: ScanTokenExpiryDays = 90;
  let creating = false;
  let createError = '';
  let revealedToken = '';
  let revokeCandidate = '';
  let revoking = '';
  let revokeError = '';

  function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
  }

  function formatDate(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    }).format(date);
  }

  function tokenState(token: ScanToken): 'active' | 'expired' | 'revoked' {
    if (token.revoked_at) return 'revoked';
    if (new Date(token.expires_at).getTime() <= Date.now()) return 'expired';
    return 'active';
  }

  async function loadTokens() {
    loadError = '';
    try {
      const response = await api.listScanTokens();
      tokens = response.tokens;
      csrfToken = response.csrf_token;
    } catch (error) {
      loadError = errorMessage(error);
    } finally {
      loading = false;
    }
  }

  async function createToken() {
    const cleanLabel = label.trim();
    if (!cleanLabel || creating) return;

    creating = true;
    createError = '';
    revealedToken = '';
    try {
      const response = await api.createScanToken(cleanLabel, expiryDays, csrfToken);
      revealedToken = response.token;
      label = '';
      await loadTokens();
    } catch (error) {
      createError = errorMessage(error);
    } finally {
      creating = false;
    }
  }

  async function revokeToken(tokenId: string) {
    if (revoking) return;

    revoking = tokenId;
    revokeError = '';
    try {
      await api.revokeScanToken(tokenId, csrfToken);
      revokeCandidate = '';
      await loadTokens();
    } catch (error) {
      revokeError = errorMessage(error);
    } finally {
      revoking = '';
    }
  }

  onMount(loadTokens);
</script>

<section class="border border-line-hairline rounded-sm bg-surface-panel p-5 mt-4" aria-labelledby="scan-token-heading">
  <div class="flex items-start justify-between gap-4 mb-4">
    <div>
      <h2 id="scan-token-heading" class="text-[12px] text-ink-primary font-mono mb-1">
        Local scan tokens
      </h2>
      <p class="text-[11px] text-ink-muted leading-relaxed max-w-xl">
        Give the local scanner permission to upload results from one machine. Tokens can only
        upload scans; they cannot read projects or manage your account.
      </p>
    </div>
    <span class="shrink-0 text-[9px] font-mono uppercase tracking-[0.12em] text-accent border border-accent/30 bg-accent/10 rounded-sm px-2 py-1">
      upload only
    </span>
  </div>

  <form class="grid grid-cols-[minmax(0,1fr)_110px_auto] gap-2 items-end mb-4" on:submit|preventDefault={createToken}>
    <label class="block min-w-0">
      <span class="block text-[10px] font-mono uppercase tracking-[0.1em] text-ink-muted mb-1">Machine label</span>
      <input
        type="text"
        bind:value={label}
        maxlength="64"
        autocomplete="off"
        placeholder="e.g. work laptop"
        aria-label="Machine label"
        class="w-full px-2.5 py-1.5 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary placeholder:text-ink-muted focus:outline-none focus:border-accent"
      />
    </label>
    <label class="block">
      <span class="block text-[10px] font-mono uppercase tracking-[0.1em] text-ink-muted mb-1">Expires</span>
      <select
        bind:value={expiryDays}
        aria-label="Token expiry"
        class="w-full px-2 py-1.5 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary focus:outline-none focus:border-accent"
      >
        {#each EXPIRY_OPTIONS as option (option.days)}
          <option value={option.days}>{option.label}</option>
        {/each}
      </select>
    </label>
    <button
      type="submit"
      disabled={creating || !label.trim() || !csrfToken}
      class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors disabled:opacity-50"
    >{creating ? 'Creating…' : 'Create token'}</button>
  </form>

  {#if createError}
    <p role="alert" class="text-[11px] font-mono mb-4" style="color: var(--state-failed);">
      Token creation failed: {createError}
    </p>
  {/if}

  {#if revealedToken}
    <div class="credential-strip mb-5 p-3 border rounded-sm" role="status" aria-live="polite">
      <div class="flex items-start justify-between gap-4 mb-2">
        <div>
          <div class="text-[10px] font-mono uppercase tracking-[0.12em] mb-1" style="color: var(--state-pending);">
            Save this token now
          </div>
          <p class="text-[11px] text-ink-secondary leading-relaxed">
            This is the only time the full token will be shown. Copy it before closing this panel.
          </p>
        </div>
        <CopyButton text={revealedToken} label="Copy token" copiedLabel="Token copied" />
      </div>
      <code class="block overflow-x-auto whitespace-nowrap bg-surface-inset border border-line-hairline rounded-sm px-3 py-2 text-[11px] text-ink-primary font-mono select-all">
        {revealedToken}
      </code>
      <div class="flex justify-end mt-2">
        <button
          type="button"
          on:click={() => (revealedToken = '')}
          class="text-[10px] font-mono uppercase tracking-[0.1em] text-ink-secondary hover:text-ink-primary transition-colors"
        >I have saved it</button>
      </div>
    </div>
  {/if}

  <div class="border-t border-line-hairline pt-3">
    <div class="text-[10px] font-mono uppercase tracking-[0.12em] text-ink-muted mb-2">
      Issued tokens
    </div>

    {#if loading}
      <div class="text-[11px] text-ink-muted font-mono py-2">Loading tokens…</div>
    {:else if loadError}
      <div class="flex items-center justify-between gap-3 py-2">
        <p role="alert" class="text-[11px] font-mono" style="color: var(--state-failed);">
          Could not load tokens: {loadError}
        </p>
        <button type="button" on:click={loadTokens} class="text-[10px] font-mono uppercase tracking-[0.1em] text-ink-secondary hover:text-ink-primary">
          Retry
        </button>
      </div>
    {:else if tokens.length === 0}
      <p class="text-[11px] text-ink-muted leading-relaxed py-2">
        No local scan tokens yet. Create one for the machine that will run scans.
      </p>
    {:else}
      <div class="as-table">
        <div class="as-head grid grid-cols-[minmax(0,1fr)_88px_110px_100px_150px] gap-3">
          <div>Label</div>
          <div>Status</div>
          <div>Expires</div>
          <div>Last used</div>
          <div class="text-right">Action</div>
        </div>
        {#each tokens as token (token.id)}
          {@const state = tokenState(token)}
          <div class="as-row grid grid-cols-[minmax(0,1fr)_88px_110px_100px_150px] gap-3 px-3 py-2.5 text-[11px]">
            <div class="min-w-0">
              <div class="text-ink-primary truncate">{token.label}</div>
              <div class="text-[9px] text-ink-muted mt-0.5">created {formatDate(token.created_at)}</div>
            </div>
            <div>
              <span
                class="inline-flex px-1.5 py-0.5 border rounded-sm text-[9px] uppercase tracking-[0.1em]"
                class:text-accent={state === 'active'}
                class:text-ink-muted={state !== 'active'}
                class:border-line-strong={state !== 'active'}
                style:border-color={state === 'active' ? 'color-mix(in srgb, var(--accent) 30%, transparent)' : undefined}
              >{state}</span>
            </div>
            <div class="text-ink-secondary">{formatDate(token.expires_at)}</div>
            <div class="text-ink-muted">{token.last_used_at ? formatDate(token.last_used_at) : 'Never'}</div>
            <div class="flex items-center justify-end gap-2">
              {#if state === 'active' && revokeCandidate === token.id}
                <button
                  type="button"
                  on:click={() => (revokeCandidate = '')}
                  class="text-[9px] uppercase tracking-[0.08em] text-ink-muted hover:text-ink-primary"
                >Cancel</button>
                <button
                  type="button"
                  on:click={() => revokeToken(token.id)}
                  disabled={revoking === token.id}
                  class="text-[9px] uppercase tracking-[0.08em] disabled:opacity-50"
                  style="color: var(--state-failed);"
                >{revoking === token.id ? 'Revoking…' : 'Confirm revoke'}</button>
              {:else if state === 'active'}
                <button
                  type="button"
                  on:click={() => (revokeCandidate = token.id)}
                  class="text-[9px] uppercase tracking-[0.08em] text-ink-muted hover:text-ink-primary"
                >Revoke</button>
              {:else if token.revoked_at}
                <span class="text-[9px] text-ink-muted">{formatDate(token.revoked_at)}</span>
              {:else}
                <span class="text-[9px] text-ink-muted">—</span>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}

    {#if revokeError}
      <p role="alert" class="text-[11px] font-mono mt-2" style="color: var(--state-failed);">
        Token revocation failed: {revokeError}
      </p>
    {/if}
  </div>
</section>

<style>
  .credential-strip {
    border-color: color-mix(in srgb, var(--state-pending) 38%, transparent);
    background:
      linear-gradient(110deg, color-mix(in srgb, var(--state-pending) 7%, transparent), transparent 62%),
      var(--bg-panel);
  }

  @media (max-width: 720px) {
    form {
      grid-template-columns: 1fr;
    }

    .as-table {
      overflow-x: auto;
    }

    .as-head,
    .as-row {
      min-width: 640px;
    }
  }
</style>
