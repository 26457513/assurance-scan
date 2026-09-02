export type GitHubPermission = 'read' | 'triage' | 'write' | 'maintain' | 'admin';

export interface GitHubIdentity {
  github_user_id: string;
  login: string;
  avatar_url: string | null;
}

export interface GitHubInstallation {
  github_installation_id: string;
  github_owner_id: string;
  owner_login: string;
  account_type: 'User' | 'Organization';
  repository_selection: 'all' | 'selected';
  enabled_repository_count: number;
  manage_url: string;
}

export interface SetupRepository {
  github_repository_id: string;
  full_name: string;
  default_branch: string;
  github_installation_id: string;
  project_id: number;
  permission: GitHubPermission;
  archived: boolean;
}

export interface RepositoryCapabilities {
  can_local_scan: boolean;
  can_manage: boolean;
}

export type ActionsReadiness =
  | { kind: 'no_scan' }
  | {
      kind: 'accepted';
      attempt_id: string;
      accepted_at: string;
      run_id: string;
      actions_url: string;
    }
  | {
      kind: 'rejected';
      attempt_id: string;
      attempted_at: string;
      safe_code: string;
      correlation_id: string;
      troubleshooting_url: string;
      actions_url: string | null;
    };

export interface MachineTokenSummary {
  id: string;
  label: string;
  status: 'active' | 'expired' | 'revoked';
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
}

export interface LocalRunSummary {
  run_id: string;
  display_title: string;
  branch: string | null;
  commit_sha: string;
  dirty: boolean;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  started_at: string;
}

export type SetupState =
  | { kind: 'signed_out'; sign_in_url: string }
  | { kind: 'github_connected'; identity: GitHubIdentity; install_url: string }
  | { kind: 'approval_pending'; identity: GitHubIdentity; request_url: string }
  | {
      kind: 'installed_no_repositories';
      identity: GitHubIdentity;
      installation: GitHubInstallation;
    }
  | { kind: 'repository_selection'; identity: GitHubIdentity }
  | {
      kind: 'repository_ready';
      identity: GitHubIdentity;
      installation: GitHubInstallation;
      repository: SetupRepository;
      capabilities: RepositoryCapabilities;
      actions_readiness: ActionsReadiness;
    }
  | {
      kind: 'repository_ready_write';
      identity: GitHubIdentity;
      installation: GitHubInstallation;
      repository: SetupRepository;
      capabilities: RepositoryCapabilities;
      actions_readiness: ActionsReadiness;
    }
  | {
      kind: 'access_stale';
      identity: GitHubIdentity;
      last_repository: SetupRepository | null;
      retry_after_seconds: number | null;
    }
  | {
      kind: 'installation_suspended';
      identity: GitHubIdentity;
      installation: GitHubInstallation;
    };

export type SetupSelection =
  | { status: 'none'; requested_repository_id: null }
  | { status: 'stale'; requested_repository_id: string }
  | { status: 'selected'; requested_repository_id: string };

export interface SetupBootstrap {
  version: 2;
  selection: SetupSelection;
  state: SetupState;
  installations: GitHubInstallation[];
  installations_next_cursor: string | null;
  machine_tokens: MachineTokenSummary[];
  latest_local_run: LocalRunSummary | null;
}

export interface SetupRepositoryPage {
  repositories: SetupRepository[];
  next_cursor: string | null;
}

export class SetupPayloadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SetupPayloadError';
  }
}

type JsonObject = Record<string, unknown>;

function fail(path: string, expected: string): never {
  throw new SetupPayloadError(`${path} must be ${expected}`);
}

function object(value: unknown, path: string): JsonObject {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return fail(path, 'an object');
  }
  return value as JsonObject;
}

function exact(value: JsonObject, allowed: readonly string[], path: string): void {
  const allowedKeys = new Set(allowed);
  const unexpected = Object.keys(value).find((key) => !allowedKeys.has(key));
  if (unexpected) fail(`${path}.${unexpected}`, 'absent');
}

function string(value: unknown, path: string): string {
  if (typeof value !== 'string' || value.length === 0) return fail(path, 'a non-empty string');
  return value;
}

function nullableString(value: unknown, path: string): string | null {
  return value === null ? null : string(value, path);
}

function decimalId(value: unknown, path: string): string {
  const result = string(value, path);
  if (!/^[1-9][0-9]*$/.test(result)) return fail(path, 'a positive decimal identifier string');
  return result;
}

function number(value: unknown, path: string, minimum = 0): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum) {
    return fail(path, `a safe integer >= ${minimum}`);
  }
  return value;
}

function boolean(value: unknown, path: string): boolean {
  if (typeof value !== 'boolean') return fail(path, 'a boolean');
  return value;
}

function literal<T extends string>(value: unknown, values: readonly T[], path: string): T {
  if (typeof value !== 'string' || !values.includes(value as T)) {
    return fail(path, `one of ${values.join(', ')}`);
  }
  return value as T;
}

function nullable<T>(value: unknown, parser: (item: unknown, path: string) => T, path: string): T | null {
  return value === null ? null : parser(value, path);
}

function array<T>(value: unknown, parser: (item: unknown, path: string) => T, path: string): T[] {
  if (!Array.isArray(value)) return fail(path, 'an array');
  return value.map((item, index) => parser(item, `${path}[${index}]`));
}

function identity(value: unknown, path: string): GitHubIdentity {
  const item = object(value, path);
  exact(item, ['github_user_id', 'login', 'avatar_url'], path);
  return {
    github_user_id: decimalId(item.github_user_id, `${path}.github_user_id`),
    login: string(item.login, `${path}.login`),
    avatar_url: nullableString(item.avatar_url, `${path}.avatar_url`)
  };
}

function installation(value: unknown, path: string): GitHubInstallation {
  const item = object(value, path);
  exact(
    item,
    [
      'github_installation_id',
      'github_owner_id',
      'owner_login',
      'account_type',
      'repository_selection',
      'enabled_repository_count',
      'manage_url'
    ],
    path
  );
  return {
    github_installation_id: decimalId(item.github_installation_id, `${path}.github_installation_id`),
    github_owner_id: decimalId(item.github_owner_id, `${path}.github_owner_id`),
    owner_login: string(item.owner_login, `${path}.owner_login`),
    account_type: literal(item.account_type, ['User', 'Organization'], `${path}.account_type`),
    repository_selection: literal(item.repository_selection, ['all', 'selected'], `${path}.repository_selection`),
    enabled_repository_count: number(item.enabled_repository_count, `${path}.enabled_repository_count`),
    manage_url: string(item.manage_url, `${path}.manage_url`)
  };
}

function repository(value: unknown, path: string): SetupRepository {
  const item = object(value, path);
  exact(
    item,
    [
      'github_repository_id',
      'full_name',
      'default_branch',
      'github_installation_id',
      'project_id',
      'permission',
      'archived'
    ],
    path
  );
  return {
    github_repository_id: decimalId(item.github_repository_id, `${path}.github_repository_id`),
    full_name: string(item.full_name, `${path}.full_name`),
    default_branch: string(item.default_branch, `${path}.default_branch`),
    github_installation_id: decimalId(item.github_installation_id, `${path}.github_installation_id`),
    project_id: number(item.project_id, `${path}.project_id`, 1),
    permission: literal(
      item.permission,
      ['read', 'triage', 'write', 'maintain', 'admin'],
      `${path}.permission`
    ),
    archived: boolean(item.archived, `${path}.archived`)
  };
}

function capabilities(value: unknown, path: string): RepositoryCapabilities {
  const item = object(value, path);
  exact(item, ['can_local_scan', 'can_manage'], path);
  return {
    can_local_scan: boolean(item.can_local_scan, `${path}.can_local_scan`),
    can_manage: boolean(item.can_manage, `${path}.can_manage`)
  };
}

function readiness(value: unknown, path: string): ActionsReadiness {
  const item = object(value, path);
  const kind = literal(item.kind, ['no_scan', 'accepted', 'rejected'], `${path}.kind`);
  if (kind === 'no_scan') {
    exact(item, ['kind'], path);
    return { kind };
  }
  if (kind === 'accepted') {
    exact(item, ['kind', 'attempt_id', 'accepted_at', 'run_id', 'actions_url'], path);
    return {
      kind,
      attempt_id: string(item.attempt_id, `${path}.attempt_id`),
      accepted_at: string(item.accepted_at, `${path}.accepted_at`),
      run_id: string(item.run_id, `${path}.run_id`),
      actions_url: string(item.actions_url, `${path}.actions_url`)
    };
  }
  exact(
    item,
    [
      'kind',
      'attempt_id',
      'attempted_at',
      'safe_code',
      'correlation_id',
      'troubleshooting_url',
      'actions_url'
    ],
    path
  );
  return {
    kind,
    attempt_id: string(item.attempt_id, `${path}.attempt_id`),
    attempted_at: string(item.attempted_at, `${path}.attempted_at`),
    safe_code: string(item.safe_code, `${path}.safe_code`),
    correlation_id: string(item.correlation_id, `${path}.correlation_id`),
    troubleshooting_url: string(item.troubleshooting_url, `${path}.troubleshooting_url`),
    actions_url: nullableString(item.actions_url, `${path}.actions_url`)
  };
}

function machineToken(value: unknown, path: string): MachineTokenSummary {
  const item = object(value, path);
  exact(item, ['id', 'label', 'status', 'created_at', 'expires_at', 'last_used_at'], path);
  return {
    id: string(item.id, `${path}.id`),
    label: string(item.label, `${path}.label`),
    status: literal(item.status, ['active', 'expired', 'revoked'], `${path}.status`),
    created_at: string(item.created_at, `${path}.created_at`),
    expires_at: string(item.expires_at, `${path}.expires_at`),
    last_used_at: nullableString(item.last_used_at, `${path}.last_used_at`)
  };
}

function localRun(value: unknown, path: string): LocalRunSummary {
  const item = object(value, path);
  exact(item, ['run_id', 'display_title', 'branch', 'commit_sha', 'dirty', 'status', 'started_at'], path);
  return {
    run_id: string(item.run_id, `${path}.run_id`),
    display_title: string(item.display_title, `${path}.display_title`),
    branch: nullableString(item.branch, `${path}.branch`),
    commit_sha: string(item.commit_sha, `${path}.commit_sha`),
    dirty: boolean(item.dirty, `${path}.dirty`),
    status: literal(
      item.status,
      ['queued', 'running', 'completed', 'failed', 'cancelled'],
      `${path}.status`
    ),
    started_at: string(item.started_at, `${path}.started_at`)
  };
}

function readyState(
  item: JsonObject,
  path: string,
  kind: 'repository_ready' | 'repository_ready_write'
): Extract<SetupState, { kind: typeof kind }> {
  exact(
    item,
    ['kind', 'identity', 'installation', 'repository', 'capabilities', 'actions_readiness'],
    path
  );
  const result = {
    kind,
    identity: identity(item.identity, `${path}.identity`),
    installation: installation(item.installation, `${path}.installation`),
    repository: repository(item.repository, `${path}.repository`),
    capabilities: capabilities(item.capabilities, `${path}.capabilities`),
    actions_readiness: readiness(item.actions_readiness, `${path}.actions_readiness`)
  } as Extract<SetupState, { kind: typeof kind }>;
  if (result.repository.github_installation_id !== result.installation.github_installation_id) {
    fail(`${path}.repository.github_installation_id`, 'the active installation identifier');
  }
  const writePermissions: readonly GitHubPermission[] = ['write', 'maintain', 'admin'];
  if (kind === 'repository_ready_write') {
    if (!result.capabilities.can_local_scan || !writePermissions.includes(result.repository.permission)) {
      fail(`${path}.capabilities.can_local_scan`, 'true for a write-capable repository');
    }
  } else if (
    result.capabilities.can_local_scan ||
    writePermissions.includes(result.repository.permission)
  ) {
    fail(path, 'a read-only repository state with local scanning disabled');
  }
  if (result.capabilities.can_manage !== (result.repository.permission === 'admin')) {
    fail(`${path}.capabilities.can_manage`, 'true exactly for repository admin access');
  }
  return result;
}

function state(value: unknown, path: string): SetupState {
  const item = object(value, path);
  const kind = literal(
    item.kind,
    [
      'signed_out',
      'github_connected',
      'approval_pending',
      'installed_no_repositories',
      'repository_selection',
      'repository_ready',
      'repository_ready_write',
      'access_stale',
      'installation_suspended'
    ],
    `${path}.kind`
  );
  switch (kind) {
    case 'signed_out':
      exact(item, ['kind', 'sign_in_url'], path);
      return { kind, sign_in_url: string(item.sign_in_url, `${path}.sign_in_url`) };
    case 'github_connected':
      exact(item, ['kind', 'identity', 'install_url'], path);
      return {
        kind,
        identity: identity(item.identity, `${path}.identity`),
        install_url: string(item.install_url, `${path}.install_url`)
      };
    case 'approval_pending':
      exact(item, ['kind', 'identity', 'request_url'], path);
      return {
        kind,
        identity: identity(item.identity, `${path}.identity`),
        request_url: string(item.request_url, `${path}.request_url`)
      };
    case 'installed_no_repositories': {
      exact(item, ['kind', 'identity', 'installation'], path);
      const installed = installation(item.installation, `${path}.installation`);
      if (installed.enabled_repository_count !== 0) {
        fail(`${path}.installation.enabled_repository_count`, '0');
      }
      return {
        kind,
        identity: identity(item.identity, `${path}.identity`),
        installation: installed
      };
    }
    case 'repository_selection':
      exact(item, ['kind', 'identity'], path);
      return { kind, identity: identity(item.identity, `${path}.identity`) };
    case 'repository_ready':
    case 'repository_ready_write':
      return readyState(item, path, kind);
    case 'access_stale':
      exact(item, ['kind', 'identity', 'last_repository', 'retry_after_seconds'], path);
      return {
        kind,
        identity: identity(item.identity, `${path}.identity`),
        last_repository: nullable(item.last_repository, repository, `${path}.last_repository`),
        retry_after_seconds:
          item.retry_after_seconds === null
            ? null
            : number(item.retry_after_seconds, `${path}.retry_after_seconds`)
      };
    case 'installation_suspended':
      exact(item, ['kind', 'identity', 'installation'], path);
      return {
        kind,
        identity: identity(item.identity, `${path}.identity`),
        installation: installation(item.installation, `${path}.installation`)
      };
  }
}

function selection(value: unknown, path: string): SetupSelection {
  const item = object(value, path);
  const status = literal(item.status, ['none', 'stale', 'selected'], `${path}.status`);
  exact(item, ['status', 'requested_repository_id'], path);
  if (status === 'none') {
    if (item.requested_repository_id !== null) fail(`${path}.requested_repository_id`, 'null');
    return { status, requested_repository_id: null };
  }
  return {
    status,
    requested_repository_id: decimalId(item.requested_repository_id, `${path}.requested_repository_id`)
  };
}

export function parseSetupBootstrap(value: unknown): SetupBootstrap {
  const item = object(value, '$');
  exact(
    item,
    [
      'version',
      'selection',
      'state',
      'installations',
      'installations_next_cursor',
      'machine_tokens',
      'latest_local_run'
    ],
    '$'
  );
  if (item.version !== 2) fail('$.version', '2');
  const parsed: SetupBootstrap = {
    version: 2,
    selection: selection(item.selection, '$.selection'),
    state: state(item.state, '$.state'),
    installations: array(item.installations, installation, '$.installations'),
    installations_next_cursor: nullableString(
      item.installations_next_cursor,
      '$.installations_next_cursor'
    ),
    machine_tokens: array(item.machine_tokens, machineToken, '$.machine_tokens'),
    latest_local_run: nullable(item.latest_local_run, localRun, '$.latest_local_run')
  };

  const installationIds = new Set<string>();
  for (const entry of parsed.installations) {
    if (installationIds.has(entry.github_installation_id)) {
      fail('$.installations', 'free of duplicate installation identifiers');
    }
    installationIds.add(entry.github_installation_id);
  }

  if (parsed.selection.status === 'selected') {
    if (
      (parsed.state.kind !== 'repository_ready' && parsed.state.kind !== 'repository_ready_write') ||
      parsed.state.repository.github_repository_id !== parsed.selection.requested_repository_id
    ) {
      fail('$.selection', 'consistent with the active repository state');
    }
  } else if (
    parsed.state.kind === 'repository_ready' ||
    parsed.state.kind === 'repository_ready_write'
  ) {
    fail('$.selection.status', 'selected for an active repository state');
  }
  if (parsed.selection.status !== 'selected' && parsed.latest_local_run !== null) {
    fail('$.latest_local_run', 'null without an active repository');
  }
  if (parsed.state.kind === 'signed_out') {
    if (
      parsed.selection.status !== 'none' ||
      parsed.installations.length ||
      parsed.machine_tokens.length
    ) {
      fail('$', 'free of account data while signed out');
    }
  }
  if (parsed.state.kind === 'github_connected' && parsed.installations.length !== 0) {
    fail('$.installations', 'empty before a GitHub App installation exists');
  }
  if (parsed.state.kind === 'repository_selection' && parsed.installations.length === 0) {
    fail('$.installations', 'non-empty while choosing an enabled repository');
  }
  if (
    (parsed.state.kind === 'repository_ready' || parsed.state.kind === 'repository_ready_write') &&
    !installationIds.has(parsed.state.installation.github_installation_id)
  ) {
    fail('$.state.installation', 'present in the installation summaries');
  }
  return parsed;
}

export function parseSetupRepositoryPage(value: unknown): SetupRepositoryPage {
  const item = object(value, '$');
  exact(item, ['repositories', 'next_cursor'], '$');
  const repositories = array(item.repositories, repository, '$.repositories');
  const seen = new Set<string>();
  for (const entry of repositories) {
    if (seen.has(entry.github_repository_id)) {
      fail('$.repositories', 'free of duplicate repository identifiers');
    }
    seen.add(entry.github_repository_id);
  }
  return {
    repositories,
    next_cursor: nullableString(item.next_cursor, '$.next_cursor')
  };
}
