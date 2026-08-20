<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { pushToast } from '$lib/stores/toasts';

  const TABS = [
    { id: 'admin', label: 'Admin' },
    { id: 'account', label: 'My account' },
    { id: 'about', label: 'About' }
  ] as const;
  $: tab = $page.url.searchParams.get('tab') ?? 'admin';

  function switchTab(id: string) {
    goto(`/setup?tab=${id}`, { noScroll: true });
  }

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
    <div class="text-[15px] text-ink-primary mb-1">Setup</div>
    <div class="text-[12px] text-ink-secondary">
      Administration, your account, and how the pieces fit together.
    </div>
  </div>

  <div class="border-b border-line-hairline mb-5 flex gap-0.5">
    {#each TABS as t (t.id)}
      <button
        type="button"
        on:click={() => switchTab(t.id)}
        class="relative px-3.5 py-2.5 text-[11px] font-mono uppercase tracking-[0.12em] transition-colors whitespace-nowrap"
        class:text-accent={tab === t.id}
        class:text-ink-muted={tab !== t.id}
      >
        {t.label}
        {#if tab === t.id}
          <span class="absolute left-0 right-0 -bottom-px h-[2px] bg-accent"></span>
        {/if}
      </button>
    {/each}
  </div>

  {#if tab === 'admin'}
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

      <div class="border border-line-hairline rounded-sm bg-surface-panel p-4 mb-4">
        <div class="text-[12px] text-ink-primary font-mono mb-1">Organisation credentials</div>
        <ul class="text-[11px] text-ink-muted leading-relaxed mb-3 list-disc pl-4">
          <li><strong class="text-ink-secondary">What it enables:</strong> automatic result ingestion, source peeks, and Scan now for every repo in the organisation — without it, the org's repos never appear.</li>
          <li>
            <strong class="text-ink-secondary">How:</strong>
            <ul class="mt-1 list-disc pl-4">
              <li>GitHub → your avatar → <strong class="text-ink-secondary">Settings</strong> → Developer settings → Personal access tokens → Fine-grained tokens → Generate <em>(tokens are always created under your personal GitHub settings — even org-owned ones; the org link comes from the next step)</em> (suggested name: <code class="text-ink-secondary">assurance-scan</code>)</li>
              <li>Resource owner = <strong class="text-ink-secondary">the organisation</strong> <em>(this is what makes it an org credential)</em> · all repositories · <code class="text-ink-secondary">Contents: Read</code> + <code class="text-ink-secondary">Actions: Read and write</code></li>
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
            type="text"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
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
        <div class="text-[12px] text-ink-muted font-mono mb-1">Administration — admin only</div>
        <p class="text-[11px] text-ink-muted leading-relaxed">
          Organisation credentials and user roles are managed by administrators.
        </p>
      </div>
    {/if}
  {:else if tab === 'account'}
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
          <li><strong class="text-ink-secondary">What it enables:</strong> Scan now on repos you can write to outside the registered organisations — personal repos, another org. Repos without the workflow are refused with setup guidance.</li>
          <li>
            <strong class="text-ink-secondary">How:</strong>
            <ul class="mt-1 list-disc pl-4">
              <li>GitHub → your avatar → <strong class="text-ink-secondary">Settings</strong> → Developer settings → Personal access tokens → Fine-grained tokens → Generate (suggested name: <code class="text-ink-secondary">assurance-scan</code>)</li>
              <li>Resource owner = your account · select the repositories you want to scan · <code class="text-ink-secondary">Contents: Read</code> + <code class="text-ink-secondary">Actions: Read and write</code></li>
              <li>Paste the token below — stored encrypted, verified on save</li>
            </ul>
          </li>
        </ul>
        <div class="flex gap-2">
          <input
            type="text"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
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
  {:else if tab === 'about'}
    <div class="border border-line-hairline rounded-sm bg-surface-panel p-4">
      <div class="text-[12px] text-ink-primary font-mono mb-3">How a scan happens</div>
      <ol class="text-[11px] text-ink-muted leading-relaxed list-decimal pl-4 space-y-2">
        <li><strong class="text-ink-secondary">A repo adopts the workflow</strong> — the stub (6 lines, from the public <code class="text-ink-secondary">assurance-scan-ci</code> repo) is added to <code class="text-ink-secondary">.github/workflows/</code> on its default branch. From then on, every push and PR scans automatically on that repo's own GitHub compute.</li>
        <li><strong class="text-ink-secondary">The workflow runs the scanners</strong> — the public orchestrator image drives semgrep, gitleaks, trivy, grype, osv-scanner and syft (plus a Trivy image scan when a Dockerfile is present). Results land in the repo's Actions summary, a PR comment, and an artifact (SARIF, SBOM, findings). Scans never fail the workflow.</li>
        <li><strong class="text-ink-secondary">This instance ingests the results</strong> — the poller fetches completed runs from every registered organisation every 60s (or instantly via <em>Retrieve from GitHub</em>). Findings, FR catalogues and compliance views live here.</li>
        <li><strong class="text-ink-secondary">On demand from the UI</strong> — <em>Scan now</em> dispatches the repo's own workflow on any branch or SHA, running on that repo's compute. Repos can also define <code class="text-ink-secondary">tribal-checks.json</code> (declarative assertions about files, sizes, content) which run as part of every scan.</li>
      </ol>
      <div class="text-[12px] text-ink-primary font-mono mt-5 mb-2">Connecting an agent</div>
      <p class="text-[11px] text-ink-muted leading-relaxed mb-1">
        Claude Code and other agents can drive scans and catalogues via the MCP server:
      </p>
      <pre class="font-mono text-[11px] text-ink-primary bg-surface-inset border border-line-hairline rounded-sm p-2 mt-1 overflow-x-auto">claude mcp add assurance-scan --transport http http://localhost:8742/mcp</pre>
    </div>
  {/if}
</div>
