import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from './api';

const fetchMock = vi.fn();

describe('numeric project API contracts', () => {
  beforeEach(() => {
    fetchMock.mockReset().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    ));
    vi.stubGlobal('fetch', fetchMock);
  });

  it('scopes scan listing by project_id', async () => {
    await api.listScans(42, 200);

    expect(fetchMock).toHaveBeenCalledWith('/api/scans?project_id=42&limit=200', undefined);
  });

  it('registers canonical project fields without path aliases', async () => {
    await api.createProject('Assurance Scan', '/work/assurance-scan', '26457513/assurance-scan', 'main');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/projects',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          tag: 'Assurance Scan',
          local_path: '/work/assurance-scan',
          github_repo: '26457513/assurance-scan',
          default_scan_ref: 'main'
        })
      })
    );
  });

  it('scopes immutable child resources to their project', async () => {
    await api.getFr('FR-001', 42, 'run-7');
    await api.getCatalogueVersion(42, 'cat-1');

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/frs/FR-001?project_id=42&run_id=run-7',
      undefined
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/catalogue/versions/cat-1?project_id=42',
      undefined
    );
  });
});
