import type { SetupApi } from './api';
import type { SetupBootstrap, SetupRepository, SetupRepositoryPage } from './models';

export type RepositorySearchState =
  | { phase: 'idle'; installationId: null; query: ''; repositories: []; nextCursor: null }
  | {
      phase: 'loading';
      installationId: string;
      query: string;
      repositories: SetupRepository[];
      nextCursor: string | null;
    }
  | {
      phase: 'ready';
      installationId: string;
      query: string;
      repositories: SetupRepository[];
      nextCursor: string | null;
    }
  | {
      phase: 'failure';
      installationId: string;
      query: string;
      repositories: SetupRepository[];
      nextCursor: string | null;
      error: string;
    };

export type SetupControllerSnapshot =
  | {
      phase: 'idle' | 'loading';
      selectedRepositoryId: string | null;
      bootstrap: null;
      refreshing: false;
      mutationsLocked: true;
      error: null;
      announcement: string;
      repositories: RepositorySearchState;
    }
  | {
      phase: 'ready';
      selectedRepositoryId: string | null;
      bootstrap: SetupBootstrap;
      refreshing: boolean;
      mutationsLocked: boolean;
      error: null;
      announcement: string;
      repositories: RepositorySearchState;
    }
  | {
      phase: 'failure';
      selectedRepositoryId: string | null;
      bootstrap: SetupBootstrap | null;
      refreshing: false;
      mutationsLocked: true;
      error: string;
      announcement: string;
      repositories: RepositorySearchState;
    };

export interface SetupLocation {
  current(): URL;
  replace(url: URL): void;
}

export interface SetupController {
  subscribe(listener: (snapshot: SetupControllerSnapshot) => void): () => void;
  snapshot(): SetupControllerSnapshot;
  load(): Promise<void>;
  retry(): Promise<void>;
  selectRepository(repositoryId: string | null): Promise<void>;
  searchRepositories(installationId: string, query: string): void;
  loadMoreRepositories(): Promise<void>;
  dispose(): void;
}

export interface SetupControllerOptions {
  api: SetupApi;
  location?: SetupLocation;
  debounceMs?: number;
  schedule?: (callback: () => void, milliseconds: number) => ReturnType<typeof setTimeout>;
  cancelSchedule?: (timer: ReturnType<typeof setTimeout>) => void;
}

const EMPTY_REPOSITORIES: RepositorySearchState = {
  phase: 'idle',
  installationId: null,
  query: '',
  repositories: [],
  nextCursor: null
};

function browserLocation(): SetupLocation {
  return {
    current: () =>
      typeof window === 'undefined'
        ? new URL('http://localhost/setup')
        : new URL(window.location.href),
    replace: (url) => {
      if (typeof window !== 'undefined') window.history.replaceState({}, '', url);
    }
  };
}

function selectedRepositoryFromUrl(url: URL): string | null {
  const value = url.searchParams.get('github_repository_id');
  return value !== null && /^[1-9][0-9]*$/.test(value) ? value : null;
}

function setupUrl(location: SetupLocation, repositoryId: string | null): URL {
  const next = location.current();
  const tab = next.searchParams.get('tab');
  next.pathname = '/setup';
  next.search = '';
  next.hash = '';
  if (tab === 'github' || tab === 'local') next.searchParams.set('tab', tab);
  if (repositoryId !== null) next.searchParams.set('github_repository_id', repositoryId);
  return next;
}

function message(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return 'Setup could not be loaded';
}

function aborted(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (typeof error === 'object' && error !== null && 'name' in error && error.name === 'AbortError')
  );
}

export function createSetupController(options: SetupControllerOptions): SetupController {
  const location = options.location ?? browserLocation();
  const debounceMs = options.debounceMs ?? 250;
  const schedule = options.schedule ?? setTimeout;
  const cancelSchedule = options.cancelSchedule ?? clearTimeout;
  let selectedRepositoryId = selectedRepositoryFromUrl(location.current());
  let current: SetupControllerSnapshot = {
    phase: 'idle',
    selectedRepositoryId,
    bootstrap: null,
    refreshing: false,
    mutationsLocked: true,
    error: null,
    announcement: '',
    repositories: EMPTY_REPOSITORIES
  };
  const listeners = new Set<(snapshot: SetupControllerSnapshot) => void>();
  let bootstrapRequest: AbortController | null = null;
  let bootstrapRevision = 0;
  let repositoryRequest: AbortController | null = null;
  let repositoryRevision = 0;
  let searchTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  function publish(next: SetupControllerSnapshot): void {
    if (disposed) return;
    current = next;
    for (const listener of listeners) listener(current);
  }

  function withRepositories(repositories: RepositorySearchState): SetupControllerSnapshot {
    return { ...current, repositories } as SetupControllerSnapshot;
  }

  async function requestBootstrap(): Promise<void> {
    const normalizedUrl = setupUrl(location, selectedRepositoryId);
    if (normalizedUrl.href !== location.current().href) location.replace(normalizedUrl);
    bootstrapRequest?.abort();
    const request = new AbortController();
    bootstrapRequest = request;
    const revision = ++bootstrapRevision;
    const retained = current.bootstrap;
    if (retained) {
      publish({
        phase: 'ready',
        selectedRepositoryId,
        bootstrap: retained,
        refreshing: true,
        mutationsLocked: true,
        error: null,
        announcement: current.announcement,
        repositories: current.repositories
      });
    } else {
      publish({
        phase: 'loading',
        selectedRepositoryId,
        bootstrap: null,
        refreshing: false,
        mutationsLocked: true,
        error: null,
        announcement: current.announcement,
        repositories: current.repositories
      });
    }
    try {
      const bootstrap = await options.api.getBootstrap(selectedRepositoryId, request.signal);
      if (disposed || revision !== bootstrapRevision) return;
      let announcement = '';
      if (bootstrap.selection.status === 'stale') {
        selectedRepositoryId = null;
        location.replace(setupUrl(location, null));
        announcement = 'Repository access changed. Choose another repository.';
      } else if (bootstrap.selection.status === 'selected') {
        selectedRepositoryId = bootstrap.selection.requested_repository_id;
      } else {
        selectedRepositoryId = null;
      }
      publish({
        phase: 'ready',
        selectedRepositoryId,
        bootstrap,
        refreshing: false,
        mutationsLocked: bootstrap.state.kind === 'access_stale',
        error: null,
        announcement,
        repositories: current.repositories
      });
    } catch (error) {
      if (disposed || revision !== bootstrapRevision || aborted(error)) return;
      publish({
        phase: 'failure',
        selectedRepositoryId,
        bootstrap: retained,
        refreshing: false,
        mutationsLocked: true,
        error: message(error),
        announcement: 'Access could not be refreshed. Actions are temporarily disabled.',
        repositories: current.repositories
      });
    }
  }

  async function selectRepository(repositoryId: string | null): Promise<void> {
    if (repositoryId !== null && !/^[1-9][0-9]*$/.test(repositoryId)) {
      throw new Error('Repository identifier must be a positive decimal string');
    }
    selectedRepositoryId = repositoryId;
    location.replace(setupUrl(location, repositoryId));
    if (current.phase === 'ready') {
      publish({
        ...current,
        selectedRepositoryId,
        refreshing: true,
        mutationsLocked: true,
        announcement: repositoryId ? 'Loading repository setup.' : 'Repository selection cleared.'
      });
    }
    await requestBootstrap();
  }

  async function requestRepositoryPage(
    installationId: string,
    query: string,
    cursor: string | null,
    append: boolean
  ): Promise<void> {
    repositoryRequest?.abort();
    const request = new AbortController();
    repositoryRequest = request;
    const revision = ++repositoryRevision;
    const previous = current.repositories;
    const retained =
      append && previous.installationId === installationId && previous.query === query
        ? previous.repositories
        : [];
    publish(
      withRepositories({
        phase: 'loading',
        installationId,
        query,
        repositories: retained,
        nextCursor: append ? previous.nextCursor : null
      })
    );
    try {
      const page: SetupRepositoryPage = await options.api.listRepositories(
        installationId,
        query,
        cursor,
        request.signal
      );
      if (disposed || revision !== repositoryRevision) return;
      publish(
        withRepositories({
          phase: 'ready',
          installationId,
          query,
          repositories: append ? [...retained, ...page.repositories] : page.repositories,
          nextCursor: page.next_cursor
        })
      );
    } catch (error) {
      if (disposed || revision !== repositoryRevision || aborted(error)) return;
      publish(
        withRepositories({
          phase: 'failure',
          installationId,
          query,
          repositories: retained,
          nextCursor: append ? previous.nextCursor : null,
          error: message(error)
        })
      );
    }
  }

  function searchRepositories(installationId: string, query: string): void {
    if (!/^[1-9][0-9]*$/.test(installationId)) {
      throw new Error('Installation identifier must be a positive decimal string');
    }
    if (searchTimer) cancelSchedule(searchTimer);
    repositoryRequest?.abort();
    repositoryRevision += 1;
    const normalizedQuery = query.trim();
    publish(
      withRepositories({
        phase: 'loading',
        installationId,
        query: normalizedQuery,
        repositories: [],
        nextCursor: null
      })
    );
    searchTimer = schedule(() => {
      searchTimer = null;
      void requestRepositoryPage(installationId, normalizedQuery, null, false);
    }, debounceMs);
  }

  async function loadMoreRepositories(): Promise<void> {
    const repositories = current.repositories;
    if (
      repositories.phase !== 'ready' ||
      repositories.installationId === null ||
      repositories.nextCursor === null
    ) {
      return;
    }
    await requestRepositoryPage(
      repositories.installationId,
      repositories.query,
      repositories.nextCursor,
      true
    );
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      listener(current);
      return () => listeners.delete(listener);
    },
    snapshot: () => current,
    load: requestBootstrap,
    retry: requestBootstrap,
    selectRepository,
    searchRepositories,
    loadMoreRepositories,
    dispose() {
      disposed = true;
      bootstrapRevision += 1;
      repositoryRevision += 1;
      bootstrapRequest?.abort();
      repositoryRequest?.abort();
      if (searchTimer) cancelSchedule(searchTimer);
      searchTimer = null;
      listeners.clear();
    }
  };
}
