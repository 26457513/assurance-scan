import type { ScannerStatus } from '$lib/types';

// Mirror of the backend result-builder descriptions, plus persisted result artifacts.
export const SCANNER_DESCRIPTIONS: Record<string, string> = {
  semgrep: 'static code analysis',
  gitleaks: 'hardcoded secrets',
  'trivy-fs': 'dependency CVEs (fs)',
  'trivy-config': 'Dockerfile/IaC misconfig',
  'trivy-image': 'image CVEs',
  syft: 'SBOM inventory',
  grype: 'dependency CVEs',
  'osv-scanner': 'dependency CVEs (OSV)',
  tribal: 'repo-defined checks',
  'project-tests': 'project test suite',
  'assurance-scan/findings': 'normalized findings bundle',
  'assurance-scan/sarif': 'unified SARIF report',
  'assurance-scan/sbom': 'CycloneDX software inventory',
};

export type ScannerCategory = 'code' | 'image' | 'artifact';

const IMAGE_SCANNERS = new Set(['syft', 'grype', 'trivy-fs', 'trivy-image']);

export function scannerCategory(scanner: string): ScannerCategory {
  if (scanner.startsWith('assurance-scan/')) return 'artifact';
  if (IMAGE_SCANNERS.has(scanner)) return 'image';
  return 'code';
}

export interface ScannerStatusSummary {
  total: number;
  completed: number;
  failed: number;
  running: number;
  pending: number;
  artifactTotal: number;
  artifactCompleted: number;
}

export function summarizeScannerStatuses(statuses: ScannerStatus[]): ScannerStatusSummary {
  const scanners = statuses.filter((status) => scannerCategory(status.kind) !== 'artifact');
  const artifacts = statuses.filter((status) => scannerCategory(status.kind) === 'artifact');
  const count = (items: ScannerStatus[], value: string) =>
    items.filter((item) => item.status === value).length;
  const completed = count(scanners, 'completed');
  const failed = count(scanners, 'failed');
  const running = count(scanners, 'running');
  return {
    total: scanners.length,
    completed,
    failed,
    running,
    pending: Math.max(0, scanners.length - completed - failed - running),
    artifactTotal: artifacts.length,
    artifactCompleted: count(artifacts, 'completed'),
  };
}
