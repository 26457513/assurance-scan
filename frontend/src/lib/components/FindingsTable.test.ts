import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

const { findingSourceContext } = vi.hoisted(() => ({
  findingSourceContext: vi.fn()
}));

vi.mock('$lib/api', () => ({
  api: { findingSourceContext }
}));

import FindingsTable from './FindingsTable.svelte';

const finding = {
  id: 7,
  finding_key: '5f874412-d500-5c0c-a7f2-4758f022af4a',
  run_id: 'local-1',
  scanner_kind: 'semgrep',
  rule_id: 'python.test',
  severity: 'HIGH' as const,
  file_path: 'src/app.py',
  line_start: 2,
  line_end: 2,
  message: 'unsafe call',
  theme: 'code',
  fix_strategy: 'code-change',
  compliance_tags: [],
  package_name: null,
  package_version: null,
  package_ecosystem: null,
  package_purl: null
};

describe('FindingsTable source context', () => {
  it('orders Medium before Low regardless of API key order', () => {
    render(FindingsTable, {
      findings: [],
      total: 5,
      bySeverity: { LOW: 3, MEDIUM: 2 },
      runId: 'local-1'
    });

    const buttons = screen.getAllByRole('button');
    expect(buttons.indexOf(screen.getByRole('button', { name: /MED/ }))).toBeLessThan(
      buttons.indexOf(screen.getByRole('button', { name: /LOW/ }))
    );
  });

  it('renders uploaded snapshot context without interpreting source as HTML', async () => {
    findingSourceContext.mockResolvedValue({
      available: true,
      provider: 'snapshot',
      path: 'src/app.py',
      window_start: 1,
      window_end: 2,
      highlight_start: 2,
      highlight_end: 2,
      highlight_truncated: false,
      lines: [
        { number: 1, text: '<img src=x onerror=alert(1)>', truncated: false },
        { number: 2, text: 'danger()', truncated: false }
      ],
      source_hash: 'a'.repeat(64),
      redaction_version: 1,
      redaction_changed: true,
      unavailable_reason: null
    });
    const { container } = render(FindingsTable, {
      findings: [finding],
      total: 1,
      bySeverity: { HIGH: 1 },
      runId: 'local-1'
    });

    await fireEvent.click(screen.getByRole('button', { name: /src\/app.py/ }));
    await fireEvent.click(screen.getByRole('button', { name: /unsafe call/ }));

    await waitFor(() => expect(findingSourceContext).toHaveBeenCalledWith('local-1', 7));
    expect(screen.getByText('captured from scanned snapshot')).toBeInTheDocument();
    expect(screen.getByText('· sensitive text redacted')).toBeInTheDocument();
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
  });

  it('explains why historical context is unavailable', async () => {
    findingSourceContext.mockResolvedValue({
      available: false,
      provider: null,
      path: null,
      window_start: null,
      window_end: null,
      highlight_start: null,
      highlight_end: null,
      highlight_truncated: false,
      lines: [],
      source_hash: null,
      redaction_version: null,
      redaction_changed: false,
      unavailable_reason: 'not_uploaded'
    });
    render(FindingsTable, {
      findings: [finding],
      total: 1,
      bySeverity: { HIGH: 1 },
      runId: 'gh-1'
    });

    await fireEvent.click(screen.getByRole('button', { name: /src\/app.py/ }));
    await fireEvent.click(screen.getByRole('button', { name: /unsafe call/ }));

    expect(await screen.findByText('This scan predates uploaded source context.')).toBeInTheDocument();
  });

  it('explains that dependency findings can be manifest scoped', async () => {
    findingSourceContext.mockResolvedValue({
      available: false,
      provider: null,
      path: 'package-lock.json',
      window_start: null,
      window_end: null,
      highlight_start: null,
      highlight_end: null,
      highlight_truncated: false,
      lines: [],
      source_hash: null,
      redaction_version: null,
      redaction_changed: false,
      unavailable_reason: 'missing_line'
    });
    const dependencyFinding = {
      ...finding,
      scanner_kind: 'osv-scanner',
      rule_id: 'GHSA-test',
      file_path: 'package-lock.json',
      line_start: null,
      line_end: null,
      message: 'dependency vulnerability',
      theme: 'dependency',
      fix_strategy: 'dependency-update'
    };
    render(FindingsTable, {
      findings: [dependencyFinding],
      total: 1,
      bySeverity: { HIGH: 1 },
      runId: 'local-1'
    });

    await fireEvent.click(screen.getByRole('button', { name: /package-lock.json/ }));
    await fireEvent.click(screen.getByRole('button', { name: /dependency vulnerability/ }));

    expect(
      await screen.findByText(
        'This dependency finding applies to the manifest as a whole; the scanner does not identify a single source line.'
      )
    ).toBeInTheDocument();
  });

  it('retains the scanner-specific missing-line message for code findings', async () => {
    findingSourceContext.mockResolvedValue({
      available: false,
      provider: null,
      path: 'src/app.py',
      window_start: null,
      window_end: null,
      highlight_start: null,
      highlight_end: null,
      highlight_truncated: false,
      lines: [],
      source_hash: null,
      redaction_version: null,
      redaction_changed: false,
      unavailable_reason: 'missing_line'
    });
    render(FindingsTable, {
      findings: [{ ...finding, line_start: null, line_end: null }],
      total: 1,
      bySeverity: { HIGH: 1 },
      runId: 'local-1'
    });

    await fireEvent.click(screen.getByRole('button', { name: /src\/app.py/ }));
    await fireEvent.click(screen.getByRole('button', { name: /unsafe call/ }));

    expect(await screen.findByText('The scanner did not report a source line.')).toBeInTheDocument();
  });

  it.each([
    [
      'misconfiguration',
      'trivy-config',
      'This configuration finding applies to the file as a whole or to a missing directive; there is no single source line.'
    ],
    [
      'tribal',
      'tribal',
      'This project policy finding applies to the file or repository as a whole; there is no single source line.'
    ]
  ])('explains file-scoped %s findings', async (theme, scannerKind, expected) => {
    findingSourceContext.mockResolvedValue({
      available: false,
      provider: null,
      path: 'Dockerfile',
      window_start: null,
      window_end: null,
      highlight_start: null,
      highlight_end: null,
      highlight_truncated: false,
      lines: [],
      source_hash: null,
      redaction_version: null,
      redaction_changed: false,
      unavailable_reason: 'missing_line'
    });
    render(FindingsTable, {
      findings: [{
        ...finding,
        scanner_kind: scannerKind,
        file_path: 'Dockerfile',
        line_start: null,
        line_end: null,
        message: 'file-scoped finding',
        theme
      }],
      total: 1,
      bySeverity: { HIGH: 1 },
      runId: 'local-1'
    });

    await fireEvent.click(screen.getByRole('button', { name: /Dockerfile/ }));
    await fireEvent.click(screen.getByRole('button', { name: /file-scoped finding/ }));

    expect(await screen.findByText(expected)).toBeInTheDocument();
  });
});
