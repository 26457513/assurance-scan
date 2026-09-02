import { describe, expect, it, vi } from 'vitest';

import { createSetupApi, SetupApiError } from './api';
import { SetupPayloadError } from './models';

const signedOut = {
  version: 2,
  selection: { status: 'none', requested_repository_id: null },
  state: { kind: 'signed_out', sign_in_url: '/login' },
  installations: [],
  installations_next_cursor: null,
  machine_tokens: [],
  latest_local_run: null
};

describe('setup API', () => {
  it('requests bootstrap with an exact string repository identifier and AbortSignal', async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(signedOut), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    );
    const api = createSetupApi(fetcher);
    const abort = new AbortController();

    await api.getBootstrap('90071992547409930', abort.signal);

    expect(fetcher).toHaveBeenCalledWith(
      '/api/v2/setup?github_repository_id=90071992547409930',
      expect.objectContaining({ credentials: 'same-origin', signal: abort.signal })
    );
  });

  it('encodes repository search and cursor parameters with the fixed page limit', async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ repositories: [], next_cursor: null }), { status: 200 })
    );
    const api = createSetupApi(fetcher);

    await api.listRepositories('42', 'name with spaces', 'cursor/value');

    const requested = new URL(fetcher.mock.calls[0][0], 'https://scan.example');
    expect(requested.pathname).toBe('/api/v2/setup/repositories');
    expect(Object.fromEntries(requested.searchParams)).toEqual({
      github_installation_id: '42',
      limit: '25',
      query: 'name with spaces',
      cursor: 'cursor/value'
    });
  });

  it('surfaces safe server errors and rejects malformed successful payloads', async () => {
    const rejected = createSetupApi(
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Access refresh failed' }), {
          status: 503,
          statusText: 'Unavailable'
        })
      )
    );
    await expect(rejected.getBootstrap(null)).rejects.toEqual(
      expect.objectContaining<Partial<SetupApiError>>({ status: 503, message: 'Access refresh failed' })
    );

    const malformed = createSetupApi(
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ version: 2 }), { status: 200 }))
    );
    await expect(malformed.getBootstrap(null)).rejects.toBeInstanceOf(SetupPayloadError);
  });

  it('explains when the feature-gated setup endpoint is unavailable', async () => {
    const api = createSetupApi(
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'not found' }), {
          status: 404,
          statusText: 'Not Found'
        })
      )
    );

    await expect(api.getBootstrap(null)).rejects.toEqual(
      expect.objectContaining<Partial<SetupApiError>>({
        status: 404,
        message: 'GitHub-backed setup is not enabled on this deployment.'
      })
    );
  });
});
