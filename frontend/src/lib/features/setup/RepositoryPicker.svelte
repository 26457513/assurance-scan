<script lang="ts">
  import type { RepositorySearchState } from './controller';
  import type { GitHubInstallation } from './models';

  export let installations: GitHubInstallation[];
  export let search: RepositorySearchState;
  export let selectedRepositoryId: string | null;
  export let onSearch: (installationId: string, query: string) => void;
  export let onSelect: (repositoryId: string) => void;
  export let onMore: () => void;

  let installationId = '';
  let query = '';
  $: if (!installationId && installations.length) installationId = installations[0].github_installation_id;

  function changeInstallation(event: Event) {
    installationId = (event.currentTarget as HTMLSelectElement).value;
    query = '';
    onSearch(installationId, query);
  }

  function changeQuery(event: Event) {
    query = (event.currentTarget as HTMLInputElement).value;
    if (installationId) onSearch(installationId, query);
  }
</script>

<div class="repository-picker">
  <div class="picker-controls">
    <label>
      <span>Installation</span>
      <select value={installationId} on:change={changeInstallation}>
        {#each installations as installation (installation.github_installation_id)}
          <option value={installation.github_installation_id}>
            {installation.owner_login} · {installation.enabled_repository_count} enabled
          </option>
        {/each}
      </select>
    </label>
    <label>
      <span>Find a repository</span>
      <input type="search" value={query} on:input={changeQuery} placeholder="owner/repository" autocomplete="off" />
    </label>
  </div>
  <div class="repository-results" aria-busy={search.phase === 'loading'} aria-live="polite" aria-atomic="true">
    {#if search.phase === 'failure'}
      <p role="alert">Repository access could not be loaded. {search.error}</p>
    {:else if search.phase === 'idle'}
      <button class="load-repositories" type="button" on:click={() => onSearch(installationId, '')}>Show enabled repositories</button>
    {:else if search.repositories.length === 0 && search.phase === 'loading'}
      <p>Loading repositories…</p>
    {:else if search.repositories.length === 0}
      <p>No enabled repositories match this search.</p>
    {:else}
      <ul aria-label="Enabled repositories">
        {#each search.repositories as repository (repository.github_repository_id)}
          <li>
            <button
              type="button"
              aria-pressed={selectedRepositoryId === repository.github_repository_id}
              on:click={() => onSelect(repository.github_repository_id)}
            >
              <span><strong>{repository.full_name}</strong><small>{repository.default_branch} · {repository.permission}</small></span>
              <span aria-hidden="true">→</span>
            </button>
          </li>
        {/each}
      </ul>
      {#if search.nextCursor}
        <button class="load-more" type="button" on:click={onMore} disabled={search.phase === 'loading'}>Load more</button>
      {/if}
    {/if}
  </div>
</div>

<style>
  .repository-picker { border-top: 1px solid var(--border-hairline); margin-top: 1rem; padding-top: 1rem; }
  .picker-controls { display: grid; grid-template-columns: minmax(10rem,.7fr) minmax(12rem,1.3fr); gap: .75rem; }
  label { display: grid; gap: .35rem; }
  label > span { color: var(--text-muted); font: 600 .62rem/1.2 'Geist Mono',monospace; letter-spacing: .1em; text-transform: uppercase; }
  select,input { width: 100%; min-height: 2.6rem; border: 1px solid var(--border-strong); border-radius: 2px; background: var(--bg-inset); padding: .6rem .7rem; color: var(--text-primary); font: .72rem 'Geist Mono',monospace; }
  .repository-results { min-height: 4.7rem; padding-top: .65rem; }
  .repository-results p { padding: .75rem 0; color: var(--text-muted); font-size: .72rem; }
  ul { max-height: 16rem; overflow: auto; border: 1px solid var(--border-hairline); background: var(--bg-inset); }
  li:not(:last-child) { border-bottom: 1px solid var(--border-hairline); }
  li > button { display: flex; width: 100%; min-height: 3.2rem; align-items: center; justify-content: space-between; padding: .55rem .75rem; color: var(--text-secondary); text-align: left; }
  li > button:hover,li > button[aria-pressed='true'] { background: var(--bg-elevated); color: var(--path-github); }
  li > button span:first-child { display: grid; min-width: 0; gap: .2rem; }
  li > button strong { overflow: hidden; color: var(--text-primary); font: .72rem 'Geist Mono',monospace; text-overflow: ellipsis; }
  li > button small { color: var(--text-muted); font-size: .62rem; }
  .load-repositories,.load-more { min-height: 2.4rem; color: var(--path-github); font: 600 .65rem 'Geist Mono',monospace; }
  @media (max-width: 620px) { .picker-controls { grid-template-columns: 1fr; } }
</style>
