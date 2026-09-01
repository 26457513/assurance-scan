import { describe, expect, it } from 'vitest';

import type { ScanSummary } from '$lib/types';
import {
  filterScansByOrigin,
  sameCommitComparison,
  scanRunLabel,
  shortCommit
} from './scanProvenance';

function scan(overrides: Partial<ScanSummary>): ScanSummary {
  return {
    run_id: 'run',
    project_id: 7,
    origin: 'local',
    status: 'completed',
    started_at: '2026-08-28T12:00:00Z',
    completed_at: '2026-08-28T12:01:00Z',
    finding_count: 2,
    commit_sha: 'a'.repeat(40),
    ...overrides
  };
}

describe('scan provenance helpers', () => {
  const local = scan({ run_id: 'local-1', origin: 'local', working_tree_dirty: true });
  const actions = scan({ run_id: 'gh-1', origin: 'github-actions' });
  const server = scan({ run_id: 'server-1', origin: 'server' });

  it('filters only the explicit local and GitHub Actions origins', () => {
    expect(filterScansByOrigin([local, actions, server], 'all')).toHaveLength(3);
    expect(filterScansByOrigin([local, actions, server], 'local')).toEqual([local]);
    expect(filterScansByOrigin([local, actions, server], 'github-actions')).toEqual([actions]);
  });

  it('pairs local and Actions runs only when their full commit matches', () => {
    expect(sameCommitComparison([local, actions], local)).toEqual({
      local,
      githubActions: actions
    });
    expect(
      sameCommitComparison([local, scan({ run_id: 'gh-other', origin: 'github-actions', commit_sha: 'b'.repeat(40) })], local)
    ).toBeNull();
  });

  it('renders compact commits without inventing missing provenance', () => {
    expect(shortCommit('abcdef0123456789')).toBe('abcdef01');
  expect(shortCommit(null)).toBe('—');
});

it('uses a compact label for local UUID run IDs', () => {
  expect(
    scanRunLabel({
      run_id: 'local-fae737da-9c1a-48de-bda9-1e5ff18de251',
      project_id: 6,
      origin: 'local',
      status: 'completed',
      started_at: '2026-09-01T09:58:00Z',
      completed_at: '2026-09-01T09:58:01Z',
      finding_count: 12
    })
  ).toBe('Local · fae737da');
});

it('uses the persisted local sequence and machine label when available', () => {
  expect(
    scanRunLabel({
      run_id: 'local-fae737da-9c1a-48de-bda9-1e5ff18de251',
      project_id: 6,
      origin: 'local',
      status: 'completed',
      started_at: '2026-09-01T09:58:00Z',
      completed_at: '2026-09-01T09:58:01Z',
      finding_count: 12,
      run_number: 3,
      display_title: 'macmini2'
    })
  ).toBe('#3 · macmini2');
});
});
