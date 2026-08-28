import type { ScanSummary } from '$lib/types';

export type ScanOriginFilter = 'all' | 'local' | 'github-actions';

export interface SameCommitComparison {
  local: ScanSummary;
  githubActions: ScanSummary;
}

export function filterScansByOrigin(
  scans: ScanSummary[],
  origin: ScanOriginFilter
): ScanSummary[] {
  if (origin === 'all') return scans;
  return scans.filter((scan) => scan.origin === origin);
}

export function sameCommitComparison(
  scans: ScanSummary[],
  scan: ScanSummary
): SameCommitComparison | null {
  if (!scan.commit_sha || (scan.origin !== 'local' && scan.origin !== 'github-actions')) {
    return null;
  }
  const counterpartOrigin = scan.origin === 'local' ? 'github-actions' : 'local';
  const counterpart = scans.find(
    (candidate) =>
      candidate.run_id !== scan.run_id &&
      candidate.origin === counterpartOrigin &&
      candidate.commit_sha === scan.commit_sha
  );
  if (!counterpart) return null;
  return scan.origin === 'local'
    ? { local: scan, githubActions: counterpart }
    : { local: counterpart, githubActions: scan };
}

export function shortCommit(commit: string | null | undefined): string {
  return commit ? commit.slice(0, 8) : '—';
}
