import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import type { ScanSummary } from '$lib/types';
import ScanCommitComparison from './ScanCommitComparison.svelte';

function scan(runId: string, origin: 'local' | 'github-actions'): ScanSummary {
  return {
    run_id: runId,
    project_id: 9,
    origin,
    status: 'completed',
    started_at: '2026-08-28T12:00:00Z',
    completed_at: '2026-08-28T12:01:00Z',
    finding_count: origin === 'local' ? 3 : 1,
    git_branch: 'feature/local-scan',
    commit_sha: 'abcdef0123456789abcdef0123456789abcdef01',
    working_tree_dirty: origin === 'local'
  };
}

describe('ScanCommitComparison', () => {
  it('makes a same-commit local versus Actions comparison explicit and actionable', async () => {
    const onOpen = vi.fn();
    const onClose = vi.fn();
    render(ScanCommitComparison, {
      comparison: {
        local: scan('local-1', 'local'),
        githubActions: scan('gh-1', 'github-actions')
      },
      onOpen,
      onClose
    });

    expect(screen.getByText('Same commit comparison')).toBeInTheDocument();
    expect(screen.getByText('Dirty — includes local changes')).toBeInTheDocument();
    expect(screen.getByText('GitHub Actions')).toBeInTheDocument();
    const openButtons = screen.getAllByRole('button', { name: 'Open run' });
    await fireEvent.click(openButtons[1]);
    expect(onOpen).toHaveBeenCalledWith('gh-1');
    await fireEvent.click(screen.getByRole('button', { name: 'Close same commit comparison' }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
