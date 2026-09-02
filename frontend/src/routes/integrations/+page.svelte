<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { api } from '$lib/api';
  import CopyButton from '$lib/components/CopyButton.svelte';

  let active = false;
  let generatedAt: string | null = null;
  let command = '';
  let token = '';
  let loading = true;
  let error = '';

  async function load() { try { const status=await api.getMcpTokenStatus(); active=status.has_token; generatedAt=status.generated_at; } catch(cause){error=cause instanceof Error?cause.message:String(cause)} finally{loading=false} }
  async function generate() { error=''; try { const result=await api.previewMcpToken(); token=result.token; command=result.command; } catch(cause){error=cause instanceof Error?cause.message:String(cause)} }
  async function activate() { try { await api.applyMcpToken(token); active=true; generatedAt=new Date().toISOString(); token=''; command=''; } catch(cause){error=cause instanceof Error?cause.message:String(cause)} }
  async function revoke() { try { await api.revokeMcpToken(); active=false; generatedAt=null; command=''; token=''; } catch(cause){error=cause instanceof Error?cause.message:String(cause)} }
  onMount(load);
  onDestroy(() => { token=''; command=''; });
</script>

<div class="utility-page">
  <header><p>Developer tools</p><h1>Integrations</h1><span>Connect an MCP-capable coding agent to the projects and scans your account can already access.</span></header>
  <section aria-labelledby="agent-heading">
    <div class="section-heading"><div><p>MCP</p><h2 id="agent-heading">Coding agent connection</h2></div><span class:active>{loading?'Checking…':active?'Active':'Not connected'}</span></div>
    <p class="description">The token follows your account permissions. It cannot reveal a repository or another user’s private local run that you cannot see in the interface.</p>
    {#if token}<div class="reveal" aria-live="polite"><strong>Review before activating</strong><p>This token is shown once. Copy the command, then activate it.</p><code>{command}</code><div><CopyButton text={command} label="Copy command"/><button type="button" on:click={activate}>Activate token</button><button type="button" on:click={()=>{token='';command=''}}>Discard</button></div></div>{/if}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    <div class="actions">{#if active}<small>{generatedAt?`Generated ${generatedAt.slice(0,10)}`:'Active token'}</small><button type="button" on:click={generate}>Rotate token</button><button class="danger" type="button" on:click={revoke}>Revoke</button>{:else}<button type="button" on:click={generate}>Generate connection</button>{/if}</div>
  </section>
</div>

<style>
  .utility-page{width:min(100%,60rem);margin:auto;padding:2rem clamp(1rem,4vw,2.5rem)}header>p,.section-heading p{color:var(--state-passed);font:600 .62rem 'Geist Mono',monospace;letter-spacing:.14em;text-transform:uppercase}h1{margin:.35rem 0 .55rem;font-size:2rem;letter-spacing:-.035em}header>span,.description{color:var(--text-secondary);font-size:.78rem;line-height:1.55}section{margin-top:1.5rem;border:1px solid var(--border-hairline);background:var(--bg-panel);padding:1.2rem}.section-heading{display:flex;align-items:center;justify-content:space-between;gap:1rem}.section-heading h2{margin-top:.25rem;font-size:1rem}.section-heading>span{border:1px solid var(--border-strong);padding:.3rem .45rem;color:var(--text-muted);font:.62rem 'Geist Mono',monospace;text-transform:uppercase}.section-heading>span.active{border-color:color-mix(in srgb,var(--state-passed) 35%,transparent);color:var(--state-passed)}.description{margin-top:.8rem}.reveal{margin-top:1rem;border-left:2px solid var(--path-local);background:var(--bg-inset);padding:.8rem}.reveal strong{color:var(--path-local);font:.68rem 'Geist Mono',monospace;text-transform:uppercase}.reveal p{margin:.25rem 0 .65rem;color:var(--text-secondary);font-size:.7rem}.reveal code{display:block;overflow:auto;border:1px solid var(--border-hairline);padding:.65rem;color:var(--text-primary);font-size:.64rem;white-space:pre}.reveal>div,.actions{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem;margin-top:.7rem}.actions small{margin-right:auto;color:var(--text-muted)}button{min-height:2.5rem;border:1px solid var(--border-strong);padding:.5rem .7rem;color:var(--text-primary);font:.65rem 'Geist Mono',monospace}.danger,.error{color:var(--state-failed)}
</style>
