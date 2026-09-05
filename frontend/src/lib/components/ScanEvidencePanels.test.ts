import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import { api } from '$lib/api';
import ArtifactsPanel from './ArtifactsPanel.svelte';
import SbomPackagesTable from './SbomPackagesTable.svelte';

describe('scan evidence panels', () => {
  it('presents generated artifacts as downloads with retention context', () => {
    render(ArtifactsPanel, {
      artifacts: {
        run_id: 'run-1',
        retention_days: 30,
        artifacts: [{
          name: 'sarif',
          filename: 'results.sarif',
          description: 'Unified SARIF report',
          media_type: 'application/sarif+json',
          status: 'completed',
          available: true,
          size_bytes: 1536,
          content_hash: `sha256:${'a'.repeat(64)}`,
          created_at: '2026-09-01T10:00:00Z',
          expires_at: '2026-10-01T10:00:00Z',
          download_url: '/api/scans/run-1/artifacts/sarif'
        }]
      }
    });

    expect(screen.getByText('results.sarif')).toBeInTheDocument();
    expect(screen.getByText('1.5 KB')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Download' })).toHaveAttribute(
      'href',
      '/api/scans/run-1/artifacts/sarif'
    );
    expect(screen.getByText(/retained for 30 days/i)).toBeInTheDocument();
  });

  it('filters the package inventory across package metadata', async () => {
    render(SbomPackagesTable, {
      runId: 'run-1',
      inventory: {
        run_id: 'run-1',
        total: 2,
        packages: [
          {
            bom_ref: 'pkg:npm/svelte@5',
            name: 'svelte',
            version: '5.0.0',
            ecosystem: 'npm',
            component_type: 'library',
            purl: 'pkg:npm/svelte@5.0.0',
            licenses: ['MIT'],
            security_status: 'clear',
            highest_severity: null,
            finding_count: 0,
            finding_ids: []
          },
          {
            bom_ref: 'pkg:pypi/fastapi@1',
            name: 'fastapi',
            version: '1.0.0',
            ecosystem: 'pypi',
            component_type: 'library',
            purl: 'pkg:pypi/fastapi@1.0.0',
            licenses: ['BSD-3-Clause'],
            security_status: 'failing',
            highest_severity: 'HIGH',
            finding_count: 1,
            finding_ids: [42]
          }
        ]
      }
    });

    await fireEvent.input(screen.getByRole('searchbox', { name: 'Search packages' }), {
      target: { value: 'pypi' }
    });

    expect(screen.queryByText('svelte')).not.toBeInTheDocument();
    expect(screen.getByText('fastapi')).toBeInTheDocument();
    expect(screen.getByText('Failing')).toBeInTheDocument();
    expect(screen.getByText('HIGH')).toBeInTheDocument();
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
  });

  it('filters the package inventory by assessment status', async () => {
    render(SbomPackagesTable, {
      runId: 'run-1',
      inventory: {
        run_id: 'run-1',
        total: 2,
        packages: [
          {
            bom_ref: 'pkg:npm/svelte@5', name: 'svelte', version: '5.0.0', ecosystem: 'npm',
            component_type: 'library', purl: 'pkg:npm/svelte@5.0.0', licenses: ['MIT'],
            security_status: 'clear', highest_severity: null, finding_count: 0, finding_ids: []
          },
          {
            bom_ref: 'pkg:pypi/fastapi@1', name: 'fastapi', version: '1.0.0', ecosystem: 'pypi',
            component_type: 'library', purl: 'pkg:pypi/fastapi@1.0.0', licenses: ['BSD-3-Clause'],
            security_status: 'failing', highest_severity: 'HIGH', finding_count: 1, finding_ids: [42]
          }
        ]
      }
    });

    await fireEvent.click(screen.getByRole('button', { name: 'Failing (1)' }));

    expect(screen.queryByText('svelte')).not.toBeInTheDocument();
    expect(screen.getByText('fastapi')).toBeInTheDocument();
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Failing (1)' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('loads package finding evidence only when its row is expanded', async () => {
    const getFinding = vi.spyOn(api, 'getFinding').mockResolvedValueOnce({
      id: 42,
      finding_key: 'finding-42',
      run_id: 'run-1',
      scanner_kind: 'grype',
      rule_id: 'CVE-2026-0042',
      severity: 'HIGH',
      file_path: 'package-lock.json',
      line_start: null,
      line_end: null,
      message: 'fastapi 1.0.0 is vulnerable (fixed in 1.0.1).',
      theme: 'dependency',
      fix_strategy: 'dependency-update',
      compliance_tags: [],
      package_name: 'fastapi',
      package_version: '1.0.0',
      package_ecosystem: 'pypi',
      package_purl: 'pkg:pypi/fastapi@1.0.0'
    });
    render(SbomPackagesTable, {
      runId: 'run-1',
      inventory: {
        run_id: 'run-1',
        total: 1,
        packages: [{
          bom_ref: 'pkg:pypi/fastapi@1', name: 'fastapi', version: '1.0.0', ecosystem: 'pypi',
          component_type: 'library', purl: 'pkg:pypi/fastapi@1.0.0', licenses: ['BSD-3-Clause'],
          security_status: 'failing', highest_severity: 'HIGH', finding_count: 1, finding_ids: [42]
        }]
      }
    });

    expect(getFinding).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole('button', { name: 'Show findings for fastapi' }));

    expect(await screen.findByText('CVE-2026-0042')).toBeInTheDocument();
    expect(screen.getByText(/fixed in 1.0.1/i)).toBeInTheDocument();
    expect(screen.getByText('Location: package-lock.json')).toBeInTheDocument();
    expect(screen.getByText('Action: Upgrade this dependency.')).toBeInTheDocument();
    expect(getFinding).toHaveBeenCalledWith('run-1', 42);
    expect(screen.getByRole('button', { name: 'Hide findings for fastapi' })).toHaveAttribute(
      'aria-expanded',
      'true'
    );
  });
});
