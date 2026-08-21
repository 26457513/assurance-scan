<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import GuideSteps from '$lib/components/GuideSteps.svelte';
  import CopyButton from '$lib/components/CopyButton.svelte';
  import { pushToast } from '$lib/stores/toasts';

  const ORG_STEPS = [
    {
      title: 'Create a fine-grained PAT',
      detail: 'GitHub → your avatar → <em>Settings</em> → <em>Developer settings</em> → <em>Personal access tokens</em>. Tokens always live under your personal settings — even org-owned ones. Suggested name: <code>assurance-scan</code>.'
    },
    {
      title: 'Scope it to the organisation',
      detail: 'Resource owner = <strong>the organisation</strong> · All repositories. The resource owner is what makes this an org credential.'
    },
    {
      title: 'Grant permissions',
      detail: ['<code>Contents: Read</code>', '<code>Actions: Read and write</code>']
    },
    {
      title: 'Add it below',
      detail: 'Stored encrypted. Verified against the org on save — repos appear once the token can read them.'
    }
  ];

  const ACCOUNT_STEPS = [
    {
      title: 'Create a fine-grained PAT',
      detail: 'GitHub → your avatar → <em>Settings</em> → <em>Developer settings</em> → <em>Personal access tokens</em>. Suggested name: <code>assurance-scan</code>.'
    },
    {
      title: 'Scope it to your account',
      detail: 'Resource owner = <strong>your account</strong> · select the repositories you want to scan.'
    },
    {
      title: 'Grant permissions',
      detail: ['<code>Contents: Read</code>', '<code>Actions: Read and write</code>']
    },
    {
      title: 'Paste it below',
      detail: 'Stored encrypted. Verified on save.'
    }
  ];

  const MCP_COMMANDS = [
    {
      label: 'This instance (local)',
      url: 'claude mcp add assurance-scan --transport http --header "Authorization: Bearer $MCP_TOKEN" http://localhost:8742/mcp'
    },
    {
      label: 'Hosted (scan.squease.ai)',
      url: 'claude mcp add assurance-scan --transport http --header "Authorization: Bearer $MCP_TOKEN" https://scan.squease.ai/mcp'
    }
  ];

  const AGENT_PROMPTS = [
    'What are the critical findings in the latest scan on tapestry-mono?',
    'What approaches do you recommend to address the critical issues in tapestry-mono?',
    'Generate an FR catalogue for this project and save it.',
    'Map our FRs against ASVS and save the compliance mapping.',
    'Scan the current project and propose fixes for every gap.',
    'Write a unit test for FR-003.'
  ];

  const WORKFLOW_GROUPS = [
    {
      label: 'Setup',
      workflows: [
        { name: 'setup-project', detail: 'Zero-to-dashboard for a new project: catalogue (created if missing), initial scan, compliance mapping, gap summary.' }
      ]
    },
    {
      label: 'Scan',
      workflows: [
        { name: 'scan-project', detail: 'Scan the project, then propose a fix for every gap. The most common starting point.' },
        { name: 'scan-refresh', detail: 'Refresh scanner vulnerability DBs and re-scan — for scanners failing on missing databases.' }
      ]
    },
    {
      label: 'Author',
      workflows: [
        { name: 'author-fr-catalogue', detail: 'Explore the codebase, reverse-engineer its capabilities, draft the FR catalogue with test specs, save it.' },
        { name: 'author-fr-compliance-map', detail: 'Read the FR catalogue and the regime pack, map every row (satisfied or not-applicable with rationale), save it.' }
      ]
    },
    {
      label: 'Advise',
      workflows: [
        { name: 'advise-remediation', detail: 'Pull a repository’s latest detailed findings and recommend prioritised approaches for the critical/high clusters.' }
      ]
    },
    {
      label: 'Fix',
      workflows: [
        { name: 'code-fr-test', detail: 'Write a unit test for an untested FR, matching the catalogue’s name_pattern.' },
        { name: 'code-finding-fix', detail: 'Fix a config or code issue so a scanner stops reporting a finding.' }
      ]
    }
  ];

  const AGENT_STEPS = [
    {
      title: 'Connect once per machine',
      detail: 'Run the command above in your terminal. Claude Code (and any MCP-capable agent) then sees the assurance-scan tools.'
    },
    {
      title: 'The agent starts with bootstrap',
      detail: 'Given a project path, <code>bootstrap</code> reports its catalogues, mappings and recent scans — plus the recommended next steps.'
    },
    {
      title: 'Ask in plain language',
      detail: 'Questions route to tools (<code>get_project_findings</code>, <code>get_gap_analysis</code>, <code>list_scans</code>…); authoring tasks route to the workflows below.'
    },
    {
      title: 'Artifacts land in this instance',
      detail: 'Catalogues and mappings are saved straight to the DB via <code>save_catalogue</code> / <code>save_mapping</code> — no files to copy around.'
    }
  ];

  const PIPELINE_STEPS = [
    {
      title: 'A repo adopts the workflow',
      detail: 'The 6-line stub (from the public <code>assurance-scan-ci</code> repo) goes into <code>.github/workflows/</code> on the default branch. Every push and PR then scans automatically — on that repo’s own GitHub compute.'
    },
    {
      title: 'The workflow runs the scanners',
      detail: 'semgrep, gitleaks, trivy, grype, osv-scanner and syft, plus a Trivy image scan when a Dockerfile is present. Results land in the Actions summary, a PR comment, and an artifact. Scans never fail the workflow.'
    },
    {
      title: 'This instance ingests the results',
      detail: 'The poller fetches completed runs from every registered organisation every 60s — or instantly via <em>Retrieve from GitHub</em>.'
    },
    {
      title: 'On demand from the UI',
      detail: '<em>Scan now</em> dispatches the repo’s own workflow on any branch or SHA. Repos can also define <code>tribal-checks.json</code> — declarative assertions checked as part of every scan.'
    }
  ];

  const TABS = [
    { id: 'admin', label: 'Admin' },
    { id: 'account', label: 'My account' },
    { id: 'agent', label: 'Agent' },
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
    try {
      const st = await api.getMcpTokenStatus();
      mcpHasToken = st.has_token;
      mcpGeneratedAt = st.generated_at;
    } catch {
      mcpHasToken = false;
    }
  }

  let mcpHasToken = false;
  let mcpGeneratedAt: string | null = null;
  let mcpCommand = '';

  async function rotateMcp() {
    try {
      const res = await api.rotateMcpToken();
      mcpHasToken = true;
      mcpGeneratedAt = new Date().toISOString();
      mcpCommand = res.command;
      pushToast('success', 'MCP token generated — copy the command now, it is shown once');
    } catch (e) {
      pushToast('error', `Token generation failed: ${e}`);
    }
  }

  async function revokeMcp() {
    try {
      await api.revokeMcpToken();
      mcpHasToken = false;
      mcpGeneratedAt = null;
      mcpCommand = '';
      pushToast('success', 'MCP token revoked');
    } catch (e) {
      pushToast('error', `Revoke failed: ${e}`);
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

      <div class="border border-line-hairline rounded-sm bg-surface-panel p-5 mb-4">
        <div class="text-[12px] text-ink-primary font-mono mb-1">Organisation credentials</div>
        <p class="text-[11px] text-ink-muted leading-relaxed mb-4">
          Registers an organisation so every repo in it can be polled, scanned on demand, and
          source-peeked. Without a credential, an org’s repos never appear.
        </p>
        <div class="mb-4"><GuideSteps steps={ORG_STEPS} /></div>
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
      <div class="border border-line-hairline rounded-sm bg-surface-panel p-5">
        <div class="text-[12px] text-ink-secondary mb-1 font-mono">Personal token</div>
        <p class="text-[11px] text-ink-muted leading-relaxed mb-4">
          Enables <em>Scan now</em> on repos you can write to outside the registered
          organisations — personal repos, another org. Repos without the workflow are refused
          with setup guidance.
        </p>
        <div class="mb-4"><GuideSteps steps={ACCOUNT_STEPS} /></div>
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

    <div class="border border-line-hairline rounded-sm bg-surface-panel p-5 mt-4">
      <div class="text-[12px] text-ink-primary font-mono mb-1">MCP token</div>
      <p class="text-[11px] text-ink-muted leading-relaxed mb-3">
        Your personal bearer token for connecting agents (Claude Code) to this instance's MCP
        server. Shown once at generation — regenerate if you lose it.
      </p>
      {#if mcpCommand}
        <div class="mb-3">
          <div class="text-[10px] font-mono uppercase tracking-[0.12em] text-ink-muted mb-1">
            Run this locally — token shown once
          </div>
          <div class="flex items-center gap-2">
            <pre class="flex-1 text-[10px] font-mono text-ink-primary bg-surface-inset border border-line-hairline rounded-sm px-2 py-1.5 overflow-x-auto whitespace-pre">{mcpCommand}</pre>
            <CopyButton text={mcpCommand} />
          </div>
        </div>
      {/if}
      <div class="flex items-center gap-2">
        {#if mcpHasToken}
          <span class="text-[11px] font-mono text-ink-muted">
            active{mcpGeneratedAt ? ` · generated ${mcpGeneratedAt.slice(0, 10)}` : ''}
          </span>
          <span class="flex-1"></span>
          <button
            type="button"
            on:click={rotateMcp}
            class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors"
          >Regenerate</button>
          <button
            type="button"
            on:click={revokeMcp}
            class="px-3 py-1.5 rounded-sm border transition-colors font-mono text-[11px] uppercase tracking-[0.1em]"
            style="color: var(--state-failed); border-color: color-mix(in srgb, var(--state-failed) 35%, transparent);"
          >Revoke</button>
        {:else}
          <button
            type="button"
            on:click={rotateMcp}
            class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors"
          >Generate token</button>
        {/if}
      </div>
    </div>
  {:else if tab === 'agent'}
    <div class="border border-line-hairline rounded-sm bg-surface-panel p-5 mb-4">
      <div class="text-[12px] text-ink-primary font-mono mb-1">Connect an agent</div>
      <p class="text-[11px] text-ink-muted leading-relaxed mb-4">
        Claude Code and other MCP-capable agents can drive scans, catalogues and mappings — and
        answer questions about your scan history — straight from the terminal.
      </p>
      {#each MCP_COMMANDS as c (c.label)}
        <div class="mb-2">
          <div class="text-[10px] font-mono uppercase tracking-[0.12em] text-ink-muted mb-1">{c.label}</div>
          <div class="flex items-center gap-2">
            <pre class="flex-1 text-[11px] font-mono text-ink-primary bg-surface-inset border border-line-hairline rounded-sm px-2 py-1.5 overflow-x-auto whitespace-pre">{c.url}</pre>
            <CopyButton text={c.url} />
          </div>
        </div>
      {/each}
      <p class="text-[11px] text-ink-muted leading-relaxed mt-3">
        Replace <code class="text-ink-secondary">$MCP_TOKEN</code> with the <code class="text-ink-secondary">MCP_TOKEN</code>
        from the server’s <code class="text-ink-secondary">.env</code> — MCP clients authenticate with it as a bearer
        token; the browser login doesn’t apply to them.
      </p>
    </div>

    <div class="border border-line-hairline rounded-sm bg-surface-panel p-5 mb-4">
      <div class="text-[12px] text-ink-primary font-mono mb-1">Ask it anything</div>
      <p class="text-[11px] text-ink-muted leading-relaxed mb-3">
        Paste any of these into Claude Code with the agent connected:
      </p>
      {#each AGENT_PROMPTS as p (p)}
        <div class="flex items-center gap-2 py-1 border-b border-line-hairline last:border-0">
          <span class="flex-1 font-mono text-[11px] text-ink-secondary truncate">“{p}”</span>
          <CopyButton text={p} label="Copy" />
        </div>
      {/each}
    </div>

    <div class="border border-line-hairline rounded-sm bg-surface-panel p-5 mb-4">
      <div class="text-[12px] text-ink-primary font-mono mb-4">How it works</div>
      <GuideSteps steps={AGENT_STEPS} />
    </div>

    <div class="border border-line-hairline rounded-sm bg-surface-panel p-5">
      <div class="text-[12px] text-ink-primary font-mono mb-3">Workflows the agent can run</div>
      <div class="as-table text-[11px]">
        <div class="as-head grid grid-cols-[110px_210px_minmax(0,1fr)] gap-3">
          <div>Category</div>
          <div>Workflow</div>
          <div>What it does</div>
        </div>
        {#each WORKFLOW_GROUPS as g (g.label)}
          {#each g.workflows as w, i (w.name)}
            <div class="as-row grid grid-cols-[110px_210px_minmax(0,1fr)] gap-3 px-3 py-2 items-center">
              {#if i === 0}
                <span class="font-mono text-[10px] uppercase tracking-[0.12em] text-accent">{g.label}</span>
              {:else}
                <span></span>
              {/if}
              <span class="font-mono text-ink-primary truncate">{w.name}</span>
              <span class="text-ink-muted leading-relaxed">{w.detail}</span>
            </div>
          {/each}
        {/each}
      </div>
    </div>
  {:else if tab === 'about'}
    <div class="border border-line-hairline rounded-sm bg-surface-panel p-5">
      <div class="text-[12px] text-ink-primary font-mono mb-4">How a scan happens</div>
      <GuideSteps steps={PIPELINE_STEPS} />
    </div>
  {/if}
</div>
