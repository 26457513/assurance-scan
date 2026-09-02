import {
  parseSetupBootstrap,
  parseSetupRepositoryPage,
  type SetupBootstrap,
  type SetupRepositoryPage
} from './models';

export class SetupApiError extends Error {
  constructor(
    readonly status: number,
    message: string
  ) {
    super(message);
    this.name = 'SetupApiError';
  }
}

export interface SetupApi {
  getBootstrap(repositoryId: string | null, signal?: AbortSignal): Promise<SetupBootstrap>;
  listRepositories(
    installationId: string,
    query: string,
    cursor: string | null,
    signal?: AbortSignal
  ): Promise<SetupRepositoryPage>;
}

async function responseJson(response: Response): Promise<unknown> {
  if (!response.ok) {
    if (response.status === 404) {
      throw new SetupApiError(
        response.status,
        'GitHub-backed setup is not enabled on this deployment.'
      );
    }
    let detail = `${response.status} ${response.statusText}`.trim();
    try {
      const body = (await response.json()) as unknown;
      if (typeof body === 'object' && body !== null && 'detail' in body) {
        const candidate = (body as { detail?: unknown }).detail;
        if (typeof candidate === 'string' && candidate) detail = candidate;
      }
    } catch {
      // The status remains safe and actionable when the server body is not JSON.
    }
    throw new SetupApiError(response.status, detail);
  }
  return response.json() as Promise<unknown>;
}

export function createSetupApi(fetcher: typeof fetch = fetch): SetupApi {
  return {
    async getBootstrap(repositoryId, signal) {
      const parameters = new URLSearchParams();
      if (repositoryId !== null) parameters.set('github_repository_id', repositoryId);
      const suffix = parameters.size ? `?${parameters}` : '';
      const response = await fetcher(`/api/v2/setup${suffix}`, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
        signal
      });
      return parseSetupBootstrap(await responseJson(response));
    },

    async listRepositories(installationId, query, cursor, signal) {
      const parameters = new URLSearchParams({
        github_installation_id: installationId,
        limit: '25'
      });
      if (query) parameters.set('query', query);
      if (cursor !== null) parameters.set('cursor', cursor);
      const response = await fetcher(`/api/v2/setup/repositories?${parameters}`, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
        signal
      });
      return parseSetupRepositoryPage(await responseJson(response));
    }
  };
}
