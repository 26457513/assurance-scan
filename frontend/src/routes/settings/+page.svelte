<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { pushToast } from '$lib/stores/toasts';

  let loading = true;
  let configured = false;
  let login = '';
  let newToken = '';
  let saving = false;

  let orgs: { name: string; login: string | null; created_at: string | null; home?: boolean }[] = [];
  let me: { email: string; role: string } | null = null;
  let users: { email: string; role: string; last_login_at: string | null }[] = [];
  let roleSaving = '';

  $: isAdmin = me?.role === 'admin' || me?.role === 'superuser';

  async function loadUsers() {
    // Read me directly — the derived isAdmin may not have propagated yet
    // when this is called imperatively right after the await in onMount.
    if (me?.role !== 'admin' && me?.role !== 'superuser') return;
    try {
      users = (await api.listUsers()).users;
    } catch {
      users = [];
    }
  }

  function onRoleChange(email: string, ev: Event) {
    setRole(email, (ev.target as HTMLSelectElement).value);
  }

  async function setRole(email: string, role: string) {
    roleSaving = email;
    try {
      await api.setUserRole(email, role);
      pushToast('success', `${email} → ${role}`);
      await loadUsers();
    } catch (e) {
      pushToast('error', `Role change failed: ${e}`);
    } finally {
      roleSaving = '';
    }
  }
  let newOrg = '';
  let newOrgToken = '';
  let orgSaving = false;

  async function loadOrgs() {
    try {
      orgs = (await api.listOrgs()).orgs;
    } catch {
      orgs = [];
    }
  }

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
  onMount(async () => {
    try {
      me = await api.me();
    } catch {
      me = null;
    }
    load();
    loadOrgs();
    loadUsers();
  });

  async function addOrg() {
    orgSaving = true;
    try {
      const res = await api.putOrg(newOrg.trim(), newOrgToken.trim());
      pushToast('success', `Organisation ${res.name} registered — ${res.repos_visible} repos visible`);
      newOrg = '';
      newOrgToken = '';
      await loadOrgs();
    } catch (e) {
      pushToast('error', `Registration failed: ${e}`);
    } finally {
      orgSaving = false;
    }
  }

  async function removeOrg(name: string) {
    try {
      await api.deleteOrg(name);
      pushToast('success', `Organisation ${name} removed`);
      await loadOrgs();
    } catch (e) {
      pushToast('error', `Remove failed: ${e}`);
    }
  }

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

  {#if isAdmin}
  <div class="border border-line-hairline rounded-sm bg-surface-panel p-4 mb-4">
    <div class="text-[12px] text-ink-primary font-mono mb-1">Users</div>
    <p class="text-[11px] text-ink-muted leading-relaxed mb-3">
      Roles: <code class="text-ink-secondary">user</code> (default) ·
      <code class="text-ink-secondary">superuser</code> (delegated admin, revocable) ·
      <code class="text-ink-secondary">admin</code> (protected, cannot be changed here).
      Users appear after their first login.
    </p>
    {#each users as u (u.email)}
      <div class="flex items-center justify-between py-1.5 border-b border-line-hairline last:border-0 gap-3">
        <div class="min-w-0 flex-1">
          <div class="font-mono text-[12px] text-ink-primary truncate">{u.email}</div>
          <div class="text-[10px] text-ink-muted font-mono">
            {u.last_login_at ? 'last login ' + u.last_login_at.slice(0, 10) : 'never logged in'}
          </div>
        </div>
        {#if u.role === 'admin'}
          <span class="font-mono text-[11px] text-ink-muted px-2 py-0.5 border border-line-hairline rounded-sm">admin (protected)</span>
        {:else}
          <select
            value={u.role}
            on:change={(e) => onRoleChange(u.email, e)}
            disabled={roleSaving === u.email}
            class="px-2 py-1 border border-line-strong rounded-sm bg-surface-elevated font-mono text-[11px] text-ink-primary"
          >
            <option value="user">user</option>
            <option value="superuser">superuser</option>
          </select>
        {/if}
      </div>
    {/each}
  </div>
  {/if}

  {#if isAdmin}
  <div class="border border-line-hairline rounded-sm bg-surface-panel p-4 mb-4">
    <div class="text-[12px] text-ink-primary font-mono mb-1">Organisation credentials</div>
    <ul class="text-[11px] text-ink-muted leading-relaxed mb-3 list-disc pl-4">
      <li><strong class="text-ink-secondary">What it enables:</strong> automatic result ingestion, source peeks, and Scan now for every repo in the organisation — without it, the org's repos never appear.</li>
      <li>
        <strong class="text-ink-secondary">How:</strong>
        <ul class="mt-1 list-disc pl-4">
          <li>GitHub → your avatar → <strong class="text-ink-secondary">Settings</strong> → Developer settings → Personal access tokens → Fine-grained tokens → Generate (suggested name: <code class="text-ink-secondary">assurance-scan</code>)</li>
          <li>Resource owner = the org · all repositories · <code class="text-ink-secondary">Contents: Read</code> + <code class="text-ink-secondary">Actions: Read and write</code></li>
          <li>Paste the token below — stored encrypted, verified on save</li>
        </ul>
      </li>
    </ul>
    {#if orgs.length > 0}
      <div class="mb-3">
        {#each orgs as o (o.name)}
          <div class="flex items-center justify-between py-1.5 border-b border-line-hairline last:border-0">
            <span class="font-mono text-[12px] text-ink-primary flex items-center gap-2">
              {o.name}
              {#if o.home}
                <span class="text-[9px] uppercase tracking-[0.1em] px-1.5 py-0.5 rounded-sm border" style="color: var(--accent); border-color: color-mix(in srgb, var(--accent) 35%, transparent);">home</span>
              {/if}
            </span>
            {#if o.home}
              <span class="text-[10px] font-mono text-ink-muted">configured via server .env</span>
            {:else}
              <button
                type="button"
                on:click={() => removeOrg(o.name)}
                class="text-[10px] font-mono uppercase tracking-[0.1em] px-2 py-0.5 border rounded-sm transition-colors"
                style="color: var(--state-failed); border-color: color-mix(in srgb, var(--state-failed) 35%, transparent);"
              >Remove</button>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
    <div class="flex gap-2">
      <input
        type="text"
        bind:value={newOrg}
        placeholder="organisation name"
        class="w-44 px-2 py-1 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary"
      />
      <input
        type="password"
        bind:value={newOrgToken}
        placeholder="org PAT (Contents:Read, Actions:Read+Write)"
        class="flex-1 px-2 py-1 border border-line-hairline rounded-sm bg-surface-base font-mono text-[11px] text-ink-primary"
      />
      <button
        type="button"
        on:click={addOrg}
        disabled={orgSaving || !newOrg.trim() || !newOrgToken.trim()}
        class="px-3 py-1 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[10px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors disabled:opacity-50"
      >{orgSaving ? 'Verifying…' : 'Add org'}</button>
    </div>
  </div>
  {:else}
  <div class="border border-line-hairline rounded-sm bg-surface-panel p-4 mb-4 opacity-60">
    <div class="text-[12px] text-ink-muted font-mono mb-1">Organisation credentials — admin only</div>
    <p class="text-[11px] text-ink-muted leading-relaxed">
      Organisation credentials are managed by administrators. Ask one to register an organisation.
    </p>
  </div>
  {/if}

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
      <div class="text-[12px] text-ink-secondary mb-1 font-mono">Personal token</div>
      <ul class="text-[11px] text-ink-muted leading-relaxed mb-3 list-disc pl-4">
        <li><strong class="text-ink-secondary">What it enables:</strong> Scan now on repos you can write to outside the registered organisations — personal repos, another org.</li>
        <li><strong class="text-ink-secondary">How:</strong> fine-grained PAT with <code class="text-ink-secondary">Contents: Read</code> + <code class="text-ink-secondary">Actions: Read and write</code> on the repos you want to scan.</li>
        <li><strong class="text-ink-secondary">Safety:</strong> verified, stored encrypted; repos without the workflow are refused with setup guidance.</li>
      </ul>
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
