import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AccessTopology from './AccessTopology.svelte';
import ActionsSetupLane from './ActionsSetupLane.svelte';
import GithubAccessFoundation from './GithubAccessFoundation.svelte';
import LocalSetupLane from './LocalSetupLane.svelte';
import RepositoryPicker from './RepositoryPicker.svelte';
import SetupExperience from './SetupExperience.svelte';
import type { RepositorySearchState } from './controller';
import type {
  ActionsReadiness,
  GitHubInstallation,
  SetupBootstrap,
  SetupRepository,
  SetupState
} from './models';

const identity = {
  github_user_id: '90071992547409930',
  login: 'octocat',
  avatar_url: null
};

const installation: GitHubInstallation = {
  github_installation_id: '55',
  github_owner_id: '77',
  owner_login: 'acme',
  account_type: 'Organization',
  repository_selection: 'selected',
  enabled_repository_count: 3,
  manage_url: 'https://github.com/settings/installations/55'
};

const repository: SetupRepository = {
  github_repository_id: '90071992547409931',
  full_name: 'acme/service',
  default_branch: 'trunk',
  github_installation_id: installation.github_installation_id,
  project_id: 7,
  permission: 'write',
  archived: false
};

const idleSearch: RepositorySearchState = {
  phase: 'idle',
  installationId: null,
  query: '',
  repositories: [],
  nextCursor: null
};

function bootstrap(state: SetupState): SetupBootstrap {
  const selected = state.kind === 'repository_ready' || state.kind === 'repository_ready_write';
  return {
    version: 2,
    selection: selected
      ? { status: 'selected', requested_repository_id: state.repository.github_repository_id }
      : { status: 'none', requested_repository_id: null },
    state,
    installations: state.kind === 'signed_out' || state.kind === 'github_connected' ? [] : [installation],
    installations_next_cursor: null,
    machine_tokens: [],
    latest_local_run: null
  };
}

function foundation(state: SetupState) {
  return render(GithubAccessFoundation, {
    bootstrap: bootstrap(state),
    repositories: idleSearch,
    selectedRepositoryId: null,
    onSearch: vi.fn(),
    onSelect: vi.fn(),
    onMore: vi.fn(),
    onClear: vi.fn(),
    onRetry: vi.fn()
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('Setup state presentation', () => {
  it.each<[string, SetupState, string]>([
    ['signed_out', { kind: 'signed_out', sign_in_url: '/login' }, 'Sign in with GitHub'],
    [
      'github_connected',
      { kind: 'github_connected', identity, install_url: 'https://github.com/apps/assurance-scan/installations/new' },
      'Install GitHub App'
    ],
    [
      'approval_pending',
      { kind: 'approval_pending', identity, request_url: 'https://github.com/settings/installations/55' },
      'View request on GitHub'
    ],
    [
      'installed_no_repositories',
      { kind: 'installed_no_repositories', identity, installation },
      'Manage repository access'
    ],
    ['repository_selection', { kind: 'repository_selection', identity }, 'Show enabled repositories'],
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
      'Choose another'
    ],
    [
      'repository_ready_write',
      {
        kind: 'repository_ready_write',
        identity,
        installation,
        repository,
        capabilities: { can_local_scan: true, can_manage: false },
        actions_readiness: { kind: 'no_scan' }
      },
      'Choose another'
    ],
    [
      'access_stale',
      { kind: 'access_stale', identity, last_repository: repository, retry_after_seconds: 30 },
      'Retry access check'
    ],
    [
      'installation_suspended',
      { kind: 'installation_suspended', identity, installation },
      'Manage GitHub App'
    ]
  ])('renders the %s state with its specific recovery or primary action', (kind, state, action) => {
    const { container } = foundation(state);
    expect(container.querySelector('[data-setup-state]')).toHaveAttribute('data-setup-state', kind);
    const actionElement = screen.getByText(action).closest('a,button');
    expect(actionElement).not.toBeNull();
  });

  it('shows the complete identity-to-team/private topology in text', () => {
    render(AccessTopology, {
      bootstrap: bootstrap({
        kind: 'repository_ready_write',
        identity,
        installation,
        repository,
        capabilities: { can_local_scan: true, can_manage: false },
        actions_readiness: { kind: 'no_scan' }
      })
    });

    expect(screen.getByRole('heading', { name: 'One identity. Two trusted scan paths.' })).toBeInTheDocument();
    expect(screen.getByText('@octocat')).toBeInTheDocument();
    expect(screen.getByText('1 available')).toBeInTheDocument();
    expect(screen.getByText('acme/service')).toBeInTheDocument();
    expect(screen.getByText('Team visible')).toBeInTheDocument();
    expect(screen.getByText('Private to you')).toBeInTheDocument();
  });
});

describe('Setup scan lanes', () => {
  it.each<[string, ActionsReadiness, string]>([
    ['no scan', { kind: 'no_scan' }, 'No scan received'],
    [
      'accepted',
      {
        kind: 'accepted',
        attempt_id: 'attempt-1',
        accepted_at: '2026-09-02T10:00:00Z',
        run_id: 'gh-1-2-1',
        actions_url: 'https://github.com/acme/service/actions/runs/2'
      },
      'Last upload accepted'
    ],
    [
      'rejected',
      {
        kind: 'rejected',
        attempt_id: 'attempt-2',
        attempted_at: '2026-09-02T10:05:00Z',
        safe_code: 'invalid_bundle',
        correlation_id: 'corr-123',
        troubleshooting_url: '/help/uploads#invalid_bundle',
        actions_url: 'https://github.com/acme/service/actions/runs/3'
      },
      'Last upload rejected'
    ]
  ])('renders %s readiness as textual live evidence', (_name, readiness, expected) => {
    const { container } = render(ActionsSetupLane, { repository, readiness });
    expect(screen.getByText(expected)).toBeInTheDocument();
    expect(container.querySelector('.readiness')).toHaveAttribute('aria-live', 'polite');
    expect(container.querySelector('section')).toHaveAttribute('data-lane-state', readiness.kind);
    if (readiness.kind === 'rejected') {
      expect(screen.getByText('invalid_bundle')).toBeInTheDocument();
      expect(screen.getByText('Request corr-123')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Open run' })).toBeInTheDocument();
    }
  });

  it('keeps local setup locked without write access and exposes no mutation control', () => {
    const { container } = render(LocalSetupLane, {
      repository: { ...repository, permission: 'read' },
      enabled: false,
      tokens: [],
      latestRun: null
    });
    expect(container.querySelector('section')).toHaveAttribute('data-lane-state', 'locked');
    expect(screen.getByText(/requires current GitHub write access/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Set up local scanning' })).not.toBeInTheDocument();
  });

  it('states private ownership, revalidation and bearer-token limits when local setup is enabled', () => {
    const { container } = render(LocalSetupLane, {
      repository,
      enabled: true,
      tokens: [
        {
          id: 'token-1',
          label: 'laptop',
          status: 'active',
          created_at: '2026-09-01T10:00:00Z',
          expires_at: '2026-12-01T10:00:00Z',
          last_used_at: null
        }
      ],
      latestRun: null
    });
    expect(container.querySelector('section')).toHaveAttribute('data-lane-state', 'ready');
    expect(screen.getByText('Only you can see local scan runs.')).toBeInTheDocument();
    expect(screen.getByText(/Repository access is rechecked before every upload/)).toBeInTheDocument();
    expect(screen.getByText(/do not prove which physical device holds a bearer token/)).toBeInTheDocument();
    expect(screen.getByText('1 active token')).toBeInTheDocument();
  });
});

describe('Repository picker and narrow layout structure', () => {
  it('uses native keyboard-operable controls and selected-state buttons', async () => {
    const onSelect = vi.fn();
    render(RepositoryPicker, {
      installations: [installation],
      search: {
        phase: 'ready',
        installationId: installation.github_installation_id,
        query: '',
        repositories: [repository],
        nextCursor: null
      },
      selectedRepositoryId: repository.github_repository_id,
      onSearch: vi.fn(),
      onSelect,
      onMore: vi.fn()
    });

    expect(screen.getByLabelText('Installation')).toBeInstanceOf(HTMLSelectElement);
    expect(screen.getByLabelText('Find a repository')).toHaveAttribute('type', 'search');
    expect(screen.getByRole('list', { name: 'Enabled repositories' })).toBeInTheDocument();
    const repositoryButton = screen.getByRole('button', { name: /acme\/service/ });
    expect(repositoryButton).toHaveAttribute('aria-pressed', 'true');
    repositoryButton.focus();
    await fireEvent.keyDown(repositoryButton, { key: 'Enter' });
    await fireEvent.click(repositoryButton);
    expect(onSelect).toHaveBeenCalledWith(repository.github_repository_id);
  });

  it('retains responsive regions and avoids fixed inline widths in the 360px composition', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes('/api/ci/workflow-template')) {
          return new Response(JSON.stringify({ filename: '.github/workflows/assurance-scan.yml', workflow: 'name: scan' }), { status: 200 });
        }
        return new Response(
          JSON.stringify({
            version: 2,
            selection: { status: 'none', requested_repository_id: null },
            state: { kind: 'signed_out', sign_in_url: '/login' },
            installations: [],
            installations_next_cursor: null,
            machine_tokens: [],
            latest_local_run: null
          }),
          { status: 200 }
        );
      })
    );
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 360 });

    const { container } = render(SetupExperience);
    await waitFor(() => expect(screen.getByRole('link', { name: 'Sign in with GitHub' })).toBeInTheDocument());

    expect(container.querySelector('[data-responsive-region="setup-experience"]')).toBeInTheDocument();
    expect(container.querySelector('[data-responsive-region="access-topology"]')).toBeInTheDocument();
    expect(container.querySelector('[data-responsive-region="scan-paths"]')).toBeInTheDocument();
    expect(container.querySelectorAll('[style*="width:"]')).toHaveLength(0);
  });
});
