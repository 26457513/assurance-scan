<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { pushToast } from '$lib/stores/toasts';

  let loading = true;
  let configured = false;
  let login = '';
  let newToken = '';
  let saving = false;

  let orgs: { name: string; login: string | null; created_at: string }[] = [];
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
    <div class="text-[12px] text-ink-primary font-mono mb-1">Organisation credentials — what the server uses</div>
    <p class="text-[11px] text-ink-muted leading-relaxed mb-2">
      The server needs its own read access to an organisation before it can do
      anything with that org's repositories: <strong class="text-ink-secondary">ingesting scan
      results automatically</strong> (polling every run, every repo — no user needs to
      be logged in) and <strong class="text-ink-secondary">source peeks</strong> (showing code context
      behind findings). Without an org credential, repos in that org never
      appear in the dashboard regardless of who is signed in.
    </p>
    <p class="text-[11px] text-ink-muted leading-relaxed mb-3">
      Created by an org admin as a fine-grained PAT: resource owner = the
      organisation, all repositories, <code class="text-ink-secondary">Contents: Read</code> +
      <code class="text-ink-secondary">Actions: Read and write</code> (the write scope additionally
      enables the Scan now button on that org's repos). Stored encrypted,
      verified on save.
    </p>
    {#if orgs.length > 0}
      <div class="mb-3">
        {#each orgs as o (o.name)}
          <div class="flex items-center justify-between py-1.5 border-b border-line-hairline last:border-0">
            <span class="font-mono text-[12px] text-ink-primary">{o.name}</span>
            <button
              type="button"
              on:click={() => removeOrg(o.name)}
              class="text-[10px] font-mono uppercase tracking-[0.1em] px-2 py-0.5 border rounded-sm transition-colors"
              style="color: var(--state-failed); border-color: color-mix(in srgb, var(--state-failed) 35%, transparent);"
            >Remove</button>
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
      <div class="text-[12px] text-ink-secondary mb-1 font-mono">Personal token — what you as a user add</div>
      <p class="text-[11px] text-ink-muted leading-relaxed mb-2">
        Your personal token extends scanning to repositories <strong class="text-ink-secondary">your
        GitHub account can write to outside the registered organisations</strong> —
        personal repos, another org you belong to. Scan now on those repos
        dispatches their workflow under your identity.
      </p>
      <p class="text-[11px] text-ink-muted leading-relaxed mb-3">
        Create a fine-grained PAT (GitHub → Settings → Developer settings →
        Fine-grained tokens) with <code class="text-ink-secondary">Contents: Read</code> and
        <code class="text-ink-secondary">Actions: Read and write</code> on the repositories you want
        to scan. Verified against GitHub, stored encrypted. Repos without the
        assurance-scan workflow are refused with setup guidance.
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
