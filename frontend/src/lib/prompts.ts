import type {
  FindingResponse,
  FrListEntry,
  ScanSummary
} from '$lib/types';

export type GapScope = 'failed' | 'untested' | 'pending';

export interface BuildPromptArgs {
  scan: ScanSummary;
  frs: FrListEntry[];
}

export interface BuiltPrompt {
  title: string;
  buttonLabel: string;
  prompt: string;
  count: number;
  scope: GapScope;
}

export interface BuiltPrompts {
  failed?: BuiltPrompt;
  untested?: BuiltPrompt;
  pending?: BuiltPrompt;
}

const SCOPES: GapScope[] = ['failed', 'untested', 'pending'];

export function classifyGap(fr: FrListEntry): GapScope | null {
  if (!fr.is_gap) return null;
  if (fr.test_count === 0) return 'untested';
  if (fr.state === 'failed' || fr.state === 'blocked') return 'failed';
  if (fr.test_results.fail > 0) return 'failed';
  if (fr.test_results.pending > 0) return 'pending';
  return 'untested';
}

const PREAMBLE = (scan: ScanSummary): string =>
  [
    `Use the assurance-scan MCP server (already running — do NOT start services or install packages).`,
    `Propose changes as a table grouped by theme; wait for my approval before applying.`,
    ``,
    `Catalogue: ./fr-catalog.json`,
    `Reference run: ${scan.run_id}`,
    `Project ID: ${scan.project_id}`
  ].join('\n');

export function buildFixPrompts(args: BuildPromptArgs): BuiltPrompts {
  const result: BuiltPrompts = {};
  for (const scope of SCOPES) {
    const built = buildScopedPrompt(args, scope);
    if (built) result[scope] = built;
  }
  return result;
}

function buildScopedPrompt(args: BuildPromptArgs, scope: GapScope): BuiltPrompt | null {
  const { scan, frs } = args;
  const scopedFrs = frs.filter((fr) => classifyGap(fr) === scope);
  if (scopedFrs.length === 0) return null;

  const count = scopedFrs.length;
  const frIds = scopedFrs.map((fr) => fr.fr_id);
  const buttonLabel = `Fix ${count} ${scope}${count === 1 ? '' : 's'}`;
  const title = `Fix ${count} ${scope}${count === 1 ? '' : 's'} — paste into Claude Code`;

  const lines: string[] = [];
  lines.push(`${scopeHeader(scope, count)} for run ${scan.run_id}.`);
  lines.push('');
  lines.push(PREAMBLE(scan));

  if (scope === 'failed') {
    lines.push('');
    lines.push(`## Failed FRs — investigate failing tests`);
    lines.push(`For each FR below, call get_fr to read its failing test spec and reason, then propose the smallest fix per FR.`);
    lines.push('');
    lines.push(frIds.join(', '));
  } else if (scope === 'untested') {
    lines.push('');
    lines.push(`## Untested FRs — add tests`);
    lines.push(`For each FR below, call get_fr to read its required_evidence.all_of / any_of specs, then add a unit-test matching the name_pattern.`);
    lines.push('');
    lines.push(frIds.join(', '));
  } else {
    lines.push('');
    lines.push(`## Pending tests — verify`);
    lines.push(`These FRs have tests that didn't complete. Re-run start_scan and recheck.`);
    lines.push('');
    lines.push(frIds.join(', '));
  }

  lines.push('');
  lines.push(`After approval: apply the changes, call start_scan, and confirm every FR above transitions to 'passed'.`);

  return { title, buttonLabel, prompt: lines.join('\n'), count, scope };
}

function scopeHeader(scope: GapScope, count: number): string {
  if (scope === 'failed') return `Fix ${count} failing test${count === 1 ? '' : 's'}`;
  if (scope === 'untested') return `Add tests for ${count} untested FR${count === 1 ? '' : 's'}`;
  return `Verify ${count} pending test${count === 1 ? '' : 's'}`;
}

// ---------------------------------------------------------------------------
// Scanner-issues prompt (for the /fix page step 1)
// ---------------------------------------------------------------------------

export interface ScannerBuiltPrompt {
  title: string;
  buttonLabel: string;
  prompt: string;
  count: number;
}

export interface BuildScannerPromptArgs {
  scan: ScanSummary;
  findings: FindingResponse[];
  frs: FrListEntry[];
}

const BLOCKING_SEVERITIES = new Set(['CRITICAL', 'HIGH']);

export function buildScannerFixPrompt(args: BuildScannerPromptArgs): ScannerBuiltPrompt {
  const { scan, findings, frs } = args;

  const blocking = findings.filter((f) => BLOCKING_SEVERITIES.has(f.severity));
  const failingFrs = frs.filter((fr) => fr.state === 'failed').map((fr) => fr.fr_id);

  const count = blocking.length;
  const buttonLabel = `Fix ${count} scanner finding${count === 1 ? '' : 's'}`;
  const title = `Fix ${count} HIGH scanner finding${count === 1 ? '' : 's'} — paste into Claude Code`;

  const lines: string[] = [];
  lines.push(`Fix ${count} HIGH scanner finding${count === 1 ? '' : 's'} for run ${scan.run_id}.`);
  lines.push('');
  lines.push(PREAMBLE(scan));

  lines.push('');
  lines.push(`## Steps`);
  lines.push(`1. Call get_findings with severity=HIGH to retrieve the full list.`);
  lines.push(`2. Group findings by file; propose the smallest fix per finding as a table.`);
  lines.push(`3. Wait for my approval before applying.`);

  if (failingFrs.length > 0) {
    lines.push('');
    lines.push(`These findings currently fail: ${failingFrs.join(', ')}. Confirm they pass after the re-scan.`);
  }

  lines.push('');
  lines.push(`After approval: apply the changes, call start_scan, and confirm no HIGH findings remain.`);

  return {
    title,
    buttonLabel,
    prompt: lines.join('\n'),
    count
  };
}
