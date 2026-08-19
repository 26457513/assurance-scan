<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { pushToast } from '$lib/stores/toasts';

  let loading = true;
  let configured = false;
  let login = '';
  let newToken = '';
  let saving = false;

  async function load() {
    try {
      const res = await api.getGithubToken();
      configured = res.configured;
      login = res.login ?? '';
    } catch {
      configured = false;
    } finally {
      loading = false;
    }
  }
  onMount(load);

  async function save() {
    saving = true;
    try {
      const res = await api.putGithubToken(newToken.trim());
      configured = true;
      login = res.login;
      newToken = '';
      pushToast('success', `GitHub token saved for @${res.login}`);
    } catch (e) {
      pushToast('error', `Token rejected: ${e}`);
    } finally {
      saving = false;
    }
  }

  async function remove() {
    try {
      await api.deleteGithubToken();
      configured = false;
      login = '';
      pushToast('success', 'GitHub token removed');
    } catch (e) {
      pushToast('error', `Remove failed: ${e}`);
    }
  }
</script>

<div class="p-6 max-w-2xl">
  <div class="mb-5">
    <div class="text-[15px] text-ink-primary mb-1">Settings</div>
    <div class="text-[12px] text-ink-secondary">
      Your GitHub connection — used to scan repositories your account can read.
    </div>
  </div>

  {#if loading}
    <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else if configured}
    <div class="border border-line-hairline rounded-sm bg-surface-panel p-4 mb-4">
      <div class="text-[12px] text-ink-primary font-mono mb-1">GitHub: @{login}</div>
      <div class="text-[11px] text-ink-muted font-mono mb-3">
        Token stored encrypted. Scan any repository this account can read from any project page.
      </div>
      <button
        type="button"
        on:click={remove}
        class="px-3 py-1.5 rounded-sm border transition-colors font-mono text-[11px] uppercase tracking-[0.1em]"
        style="color: var(--state-failed); border-color: color-mix(in srgb, var(--state-failed) 35%, transparent);"
      >Remove token</button>
    </div>
  {:else}
    <div class="border border-line-hairline rounded-sm bg-surface-panel p-4">
      <div class="text-[12px] text-ink-secondary mb-1 font-mono">Add a GitHub token</div>
      <p class="text-[11px] text-ink-muted leading-relaxed mb-3">
        Create a fine-grained PAT (Settings → Developer settings → Fine-grained tokens) with
        <code class="text-ink-secondary">Contents: Read-only</code> on the repositories you want to scan.
        It is verified against GitHub, stored encrypted, and used only to fetch code for scans you start.
      </p>
      <div class="flex gap-2">
        <input
          type="password"
          bind:value={newToken}
          placeholder="github_pat_…"
          class="flex-1 px-2 py-1 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary"
        />
        <button
          type="button"
          on:click={save}
          disabled={saving || !newToken.trim()}
          class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors disabled:opacity-50"
        >{saving ? 'Verifying…' : 'Save token'}</button>
      </div>
    </div>
  {/if}
</div>
