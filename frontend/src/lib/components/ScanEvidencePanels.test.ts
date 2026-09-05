import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

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
            finding_count: 0
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
            finding_count: 1
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
      inventory: {
        run_id: 'run-1',
        total: 2,
        packages: [
          {
            bom_ref: 'pkg:npm/svelte@5', name: 'svelte', version: '5.0.0', ecosystem: 'npm',
            component_type: 'library', purl: 'pkg:npm/svelte@5.0.0', licenses: ['MIT'],
            security_status: 'clear', highest_severity: null, finding_count: 0
          },
          {
            bom_ref: 'pkg:pypi/fastapi@1', name: 'fastapi', version: '1.0.0', ecosystem: 'pypi',
            component_type: 'library', purl: 'pkg:pypi/fastapi@1.0.0', licenses: ['BSD-3-Clause'],
            security_status: 'failing', highest_severity: 'HIGH', finding_count: 1
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
});
