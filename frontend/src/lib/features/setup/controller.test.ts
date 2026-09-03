import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { SetupApi } from './api';
import { createSetupController, type SetupLocation } from './controller';
import type { SetupBootstrap, SetupRepository, SetupRepositoryPage } from './models';

const repository: SetupRepository = {
  github_repository_id: '90071992547409930',
  full_name: 'acme/service',
  default_branch: 'main',
  github_installation_id: '55',
  project_id: 7,
  permission: 'write',
  archived: false
};

function response(
  selection: SetupBootstrap['selection'] = { status: 'none', requested_repository_id: null }
): SetupBootstrap {
  return {
    version: 2,
    selection,
    state: {
      kind: 'repository_selection',
      identity: { github_user_id: '99', login: 'octocat', avatar_url: null }
    },
    installations: [],
    installations_next_cursor: null,
    machine_tokens: [],
    latest_local_run: null
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function fakeLocation(initial = 'https://scan.example/setup'): SetupLocation & { url: URL } {
  const holder = {
    url: new URL(initial),
    current() {
      return new URL(holder.url);
    },
    replace(url: URL) {
      holder.url = new URL(url);
    }
  };
  return holder;
}

function apiMock(): SetupApi {
  return {
    getBootstrap: vi.fn().mockResolvedValue(response()),
    listRepositories: vi.fn().mockResolvedValue({ repositories: [], next_cursor: null })
  };
}

describe('setup controller', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('loads only the repository explicitly selected in the URL', async () => {
    const api = apiMock();
    const location = fakeLocation(
      `https://scan.example/setup?github_repository_id=${repository.github_repository_id}`
    );
    vi.mocked(api.getBootstrap).mockResolvedValue(
      response({ status: 'stale', requested_repository_id: repository.github_repository_id })
    );
    const controller = createSetupController({ api, location });

    await controller.load();

    expect(api.getBootstrap).toHaveBeenCalledWith(repository.github_repository_id, expect.any(AbortSignal));
    expect(location.url.search).toBe('');
    expect(controller.snapshot()).toEqual(
      expect.objectContaining({
        phase: 'ready',
        selectedRepositoryId: null,
        announcement: 'Repository access changed. Choose another repository.'
      })
    );
  });

  it('updates selection and URL before dependent bootstrap completes', async () => {
    const api = apiMock();
    const next = deferred<SetupBootstrap>();
    vi.mocked(api.getBootstrap)
      .mockResolvedValueOnce(response())
      .mockReturnValueOnce(next.promise);
    const location = fakeLocation('https://scan.example/setup?tab=account&run_id=old');
    const controller = createSetupController({ api, location });
    await controller.load();

    const pending = controller.selectRepository(repository.github_repository_id);
    expect(location.url.search).toBe(`?github_repository_id=${repository.github_repository_id}`);
    expect(controller.snapshot()).toEqual(
      expect.objectContaining({
        phase: 'ready',
        selectedRepositoryId: repository.github_repository_id,
        refreshing: true,
        mutationsLocked: true
      })
    );

    next.resolve(response({ status: 'stale', requested_repository_id: repository.github_repository_id }));
    await pending;
  });

  it('removes obsolete setup query parameters without selecting a fallback repository', async () => {
    const api = apiMock();
    const location = fakeLocation('https://scan.example/setup?tab=agent&run_id=old#local');
    const controller = createSetupController({ api, location });

    await controller.load();

    expect(location.url.href).toBe('https://scan.example/setup');
    expect(api.getBootstrap).toHaveBeenCalledWith(null, expect.any(AbortSignal));
  });

  it('preserves a supported setup flow while removing unrelated query state', async () => {
    const api = apiMock();
    const location = fakeLocation('https://scan.example/setup?tab=local&run_id=old#token');
    const controller = createSetupController({ api, location });

    await controller.load();

    expect(location.url.href).toBe('https://scan.example/setup?tab=local');
    expect(api.getBootstrap).toHaveBeenCalledWith(null, expect.any(AbortSignal));
  });

  it('retains visible bootstrap data but locks mutation after a refresh failure', async () => {
    const api = apiMock();
    vi.mocked(api.getBootstrap)
      .mockResolvedValueOnce(response())
      .mockRejectedValueOnce(new Error('GitHub temporarily unavailable'));
    const controller = createSetupController({ api, location: fakeLocation() });
    await controller.load();

    await controller.retry();

    expect(controller.snapshot()).toEqual(
      expect.objectContaining({
        phase: 'failure',
        bootstrap: response(),
        mutationsLocked: true,
        error: 'GitHub temporarily unavailable'
      })
    );
  });

  it('debounces search and ignores an obsolete response even if abort is ignored', async () => {
    const api = apiMock();
    const oldSearch = deferred<SetupRepositoryPage>();
    const newSearch = deferred<SetupRepositoryPage>();
    vi.mocked(api.listRepositories)
      .mockReturnValueOnce(oldSearch.promise)
      .mockReturnValueOnce(newSearch.promise);
    const controller = createSetupController({ api, location: fakeLocation(), debounceMs: 250 });

    controller.searchRepositories('55', 'old');
    await vi.advanceTimersByTimeAsync(250);
    controller.searchRepositories('55', 'new');
    await vi.advanceTimersByTimeAsync(250);
    expect(api.listRepositories).toHaveBeenCalledTimes(2);

    oldSearch.resolve({ repositories: [{ ...repository, full_name: 'acme/old' }], next_cursor: null });
    await Promise.resolve();
    expect(controller.snapshot().repositories.query).toBe('new');

    newSearch.resolve({ repositories: [repository], next_cursor: 'page-2' });
    await Promise.resolve();
    expect(controller.snapshot().repositories).toEqual(
      expect.objectContaining({ phase: 'ready', query: 'new', repositories: [repository] })
    );
  });

  it('appends the next cursor page without replacing existing repository rows', async () => {
    const api = apiMock();
    const second = { ...repository, github_repository_id: '90071992547409931', full_name: 'acme/web' };
    vi.mocked(api.listRepositories)
      .mockResolvedValueOnce({ repositories: [repository], next_cursor: 'page-2' })
      .mockResolvedValueOnce({ repositories: [second], next_cursor: null });
    const controller = createSetupController({ api, location: fakeLocation(), debounceMs: 0 });

    controller.searchRepositories('55', 'acme');
    await vi.advanceTimersByTimeAsync(0);
    await vi.waitFor(() => expect(controller.snapshot().repositories.phase).toBe('ready'));
    await controller.loadMoreRepositories();

    expect(api.listRepositories).toHaveBeenLastCalledWith(
      '55',
      'acme',
      'page-2',
      expect.any(AbortSignal)
    );
    expect(controller.snapshot().repositories.repositories).toEqual([repository, second]);
  });
});
