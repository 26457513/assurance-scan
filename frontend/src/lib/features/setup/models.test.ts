import { describe, expect, it } from 'vitest';

import { parseSetupBootstrap, parseSetupRepositoryPage, SetupPayloadError } from './models';

const identity = {
  github_user_id: '90071992547409930',
  login: 'octocat',
  avatar_url: null
};

const installation = {
  github_installation_id: '80000000000000001',
  github_owner_id: '70000000000000001',
  owner_login: 'acme',
  account_type: 'Organization',
  repository_selection: 'selected',
  enabled_repository_count: 3,
  manage_url: 'https://github.com/settings/installations/80000000000000001'
};

const repository = {
  github_repository_id: '60000000000000001',
  full_name: 'acme/service',
  default_branch: 'main',
  github_installation_id: installation.github_installation_id,
  project_id: 7,
  permission: 'write',
  archived: false
};

function bootstrap(state: Record<string, unknown>, selection: Record<string, unknown>) {
  return {
    version: 2,
    selection,
    state,
    installations: state.kind === 'signed_out' || state.kind === 'github_connected' ? [] : [installation],
    installations_next_cursor: null,
    machine_tokens: state.kind === 'signed_out' ? [] : [],
    latest_local_run: null
  };
}

describe('setup payload parser', () => {
  it.each([
    [
      'signed_out',
      { kind: 'signed_out', sign_in_url: '/auth/login?next=/setup' },
      { status: 'none', requested_repository_id: null },
    ],
    [
      'github_connected',
      { kind: 'github_connected', identity, install_url: 'https://github.com/apps/assurance-scan/installations/new' },
      { status: 'none', requested_repository_id: null }
    ],
    [
      'approval_pending',
      { kind: 'approval_pending', identity, request_url: 'https://github.com/settings/installations/1' },
      { status: 'none', requested_repository_id: null }
    ],
    [
      'installed_no_repositories',
      {
        kind: 'installed_no_repositories',
        identity,
        installation: { ...installation, enabled_repository_count: 0 }
      },
      { status: 'none', requested_repository_id: null }
    ],
    [
      'repository_selection',
      { kind: 'repository_selection', identity },
      { status: 'none', requested_repository_id: null }
    ],
    [
      'repository_ready',
      {
        kind: 'repository_ready',
        identity,
        installation,
        repository: { ...repository, permission: 'read' },
        capabilities: { can_local_scan: false, can_manage: false },
        actions_readiness: { kind: 'no_scan' }
      },
      { status: 'selected', requested_repository_id: repository.github_repository_id }
    ],
    [
      'repository_ready_write',
      {
        kind: 'repository_ready_write',
        identity,
        installation,
        repository,
        capabilities: { can_local_scan: true, can_manage: false },
        actions_readiness: {
          kind: 'accepted',
          attempt_id: 'attempt-1',
          accepted_at: '2026-09-02T10:00:00Z',
          run_id: 'gh-1-2-1',
          actions_url: 'https://github.com/acme/service/actions/runs/2'
        }
      },
      { status: 'selected', requested_repository_id: repository.github_repository_id }
    ],
    [
      'access_stale',
      { kind: 'access_stale', identity, last_repository: repository, retry_after_seconds: 30 },
      { status: 'stale', requested_repository_id: repository.github_repository_id }
    ],
    [
      'installation_suspended',
      { kind: 'installation_suspended', identity, installation },
      { status: 'none', requested_repository_id: null }
    ]
  ])('parses the %s state without losing large GitHub identifiers', (_name, state, selection) => {
    const parsed = parseSetupBootstrap(bootstrap(state, selection));
    expect(parsed.state.kind).toBe(state.kind);
    if (state.kind === 'signed_out' || state.kind === 'github_connected') {
      expect(parsed.installations).toEqual([]);
    } else {
      expect(parsed.installations[0]?.github_installation_id).toBe(installation.github_installation_id);
    }
  });

  it('parses rejected readiness with only safe recovery evidence', () => {
    const value = bootstrap(
      {
        kind: 'repository_ready_write',
        identity,
        installation,
        repository,
        capabilities: { can_local_scan: true, can_manage: false },
        actions_readiness: {
          kind: 'rejected',
          attempt_id: 'attempt-2',
          attempted_at: '2026-09-02T10:00:00Z',
          safe_code: 'invalid_bundle',
          correlation_id: 'corr-1',
          troubleshooting_url: '/help/uploads#invalid_bundle',
          actions_url: null
        }
      },
      { status: 'selected', requested_repository_id: repository.github_repository_id }
    );
    const parsed = parseSetupBootstrap(value);
    expect(parsed.state.kind).toBe('repository_ready_write');
    if (parsed.state.kind === 'repository_ready_write') {
      expect(parsed.state.actions_readiness.kind).toBe('rejected');
    }
  });

  it('rejects unknown fields and impossible state combinations', () => {
    const value = bootstrap(
      {
        kind: 'repository_ready_write',
        identity,
        installation,
        repository,
        capabilities: { can_local_scan: false, can_manage: false },
        actions_readiness: { kind: 'no_scan' },
        secret: 'must not be accepted'
      },
      { status: 'selected', requested_repository_id: repository.github_repository_id }
    );
    expect(() => parseSetupBootstrap(value)).toThrow(SetupPayloadError);

    delete value.state.secret;
    expect(() => parseSetupBootstrap(value)).toThrow(/can_local_scan/);
  });

  it('rejects a selected repository that differs from the active state', () => {
    const value = bootstrap(
      {
        kind: 'repository_ready_write',
        identity,
        installation,
        repository,
        capabilities: { can_local_scan: true, can_manage: false },
        actions_readiness: { kind: 'no_scan' }
      },
      { status: 'selected', requested_repository_id: '123' }
    );
    expect(() => parseSetupBootstrap(value)).toThrow(/consistent with the active repository/);
  });

  it('parses a unique repository page and rejects duplicate numeric identities', () => {
    const parsed = parseSetupRepositoryPage({ repositories: [repository], next_cursor: 'next' });
    expect(parsed.repositories[0].github_repository_id).toBe(repository.github_repository_id);
    expect(parsed.next_cursor).toBe('next');

    expect(() =>
      parseSetupRepositoryPage({ repositories: [repository, repository], next_cursor: null })
    ).toThrow(/duplicate repository identifiers/);
  });
});
