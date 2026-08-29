import { describe, expect, it } from 'vitest';
import {
  SCANNER_DESCRIPTIONS,
  scannerCategory,
  summarizeScannerStatuses,
} from './scannerDescriptions';
import type { ScannerStatus } from './types';

const status = (kind: string, value = 'completed'): ScannerStatus => ({
  kind,
  status: value,
  started_at: null,
  completed_at: null,
  error_message: null,
});

describe('scanner presentation', () => {
  it('describes and categorizes persisted Assurance Scan artifacts', () => {
    expect(SCANNER_DESCRIPTIONS['assurance-scan/findings']).toBe('normalized findings bundle');
    expect(SCANNER_DESCRIPTIONS['assurance-scan/sarif']).toBe('unified SARIF report');
    expect(SCANNER_DESCRIPTIONS['assurance-scan/sbom']).toBe('CycloneDX software inventory');
    expect(scannerCategory('assurance-scan/sarif')).toBe('artifact');
    expect(scannerCategory('syft')).toBe('image');
    expect(scannerCategory('semgrep')).toBe('code');
  });

  it('keeps artifact completion separate from scanner health', () => {
    const summary = summarizeScannerStatuses([
      status('semgrep'),
      status('gitleaks', 'failed'),
      status('grype', 'running'),
      status('tribal', 'skipped'),
      status('assurance-scan/findings'),
      status('assurance-scan/sarif'),
      status('assurance-scan/sbom', 'failed'),
    ]);

    expect(summary).toEqual({
      total: 4,
      completed: 1,
      failed: 1,
      running: 1,
      pending: 1,
      artifactTotal: 3,
      artifactCompleted: 2,
    });
  });
});
