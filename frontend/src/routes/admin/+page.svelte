<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { pushToast } from '$lib/stores/toasts';

  type Account = { id: number; login: string; role: string; last_login_at: string | null };
  let users: Account[] = [];
  let loading = true;
  let error = '';
  let saving = '';

  async function load() {
    loading = true;
    error = '';
    try { users = (await api.listUsers()).users; }
    catch (cause) { error = cause instanceof Error ? cause.message : String(cause); }
    finally { loading = false; }
  }

  async function setRole(account: Account, event: Event) {
    saving = String(account.id);
    const role = (event.currentTarget as HTMLSelectElement).value;
    try { await api.setUserRole(account.id, role); pushToast('success', `@${account.login} → ${role}`); await load(); }
    catch (cause) { pushToast('error', `Role change failed: ${cause}`); }
    finally { saving = ''; }
  }

  onMount(load);
</script>

<div class="utility-page">
  <header><p>Restricted controls</p><h1>Administration</h1><span>Application roles affect administrative surfaces only. They never bypass GitHub repository access.</span></header>
  <section aria-labelledby="accounts-heading">
    <div class="section-heading"><div><p>Accounts</p><h2 id="accounts-heading">Interface roles</h2></div><button type="button" on:click={load}>Refresh</button></div>
    {#if loading}<p class="state">Loading accounts…</p>
    {:else if error}<p class="state error" role="alert">Accounts could not be loaded. {error}</p>
    {:else}<div class="rows">{#each users as user (user.id)}<div class="row"><span><strong>@{user.login}</strong><small>{user.last_login_at ? `Last active ${user.last_login_at.slice(0,10)}` : 'No recorded login'}</small></span>{#if user.role === 'admin'}<code>admin · protected</code>{:else}<label><span class="sr-only">Role for {user.login}</span><select value={user.role} disabled={saving === String(user.id)} on:change={(event) => setRole(user,event)}><option value="user">user</option><option value="superuser">superuser</option></select></label>{/if}</div>{/each}</div>{/if}
  </section>
</div>

<style>
  .utility-page{width:min(100%,60rem);margin:auto;padding:2rem clamp(1rem,4vw,2.5rem)}header>p,.section-heading p{color:var(--state-passed);font:600 .62rem 'Geist Mono',monospace;letter-spacing:.14em;text-transform:uppercase}h1{margin:.35rem 0 .55rem;font-size:2rem;letter-spacing:-.035em}header>span{color:var(--text-secondary);font-size:.8rem}section{margin-top:1.5rem;border:1px solid var(--border-hairline);background:var(--bg-panel);padding:1.2rem}.section-heading{display:flex;align-items:center;justify-content:space-between}.section-heading h2{margin-top:.25rem;font-size:1rem}.section-heading button,select{min-height:2.5rem;border:1px solid var(--border-strong);background:var(--bg-inset);padding:.5rem .7rem;color:var(--text-primary);font:.68rem 'Geist Mono',monospace}.rows{margin-top:1rem;border-top:1px solid var(--border-hairline)}.row{display:flex;min-height:3.4rem;align-items:center;justify-content:space-between;gap:1rem;border-bottom:1px solid var(--border-hairline)}.row>span{display:grid;gap:.2rem}.row strong{font:.73rem 'Geist Mono',monospace}.row small,.state{color:var(--text-muted);font-size:.68rem}.row code{color:var(--text-muted);font-size:.65rem}.error{color:var(--state-failed)}@media(max-width:520px){.row{align-items:stretch;flex-direction:column;padding:.7rem 0}select{width:100%}}
</style>
