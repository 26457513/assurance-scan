import { describe, expect, it } from 'vitest';

import { selectedRunFromUrl, urlForSelectedRun } from './scanSelectionUrl';

describe('scan selection URLs', () => {
  it('uses one canonical project-page parameter', () => {
    const current = new URL('http://localhost/projects/7?run_id=old&origin=local');
    expect(urlForSelectedRun(current, 'new run')).toBe(
      '/projects/7?origin=local&run=new+run'
    );
  });

  it('reads legacy project links but prefers the canonical parameter', () => {
    expect(selectedRunFromUrl(new URL('http://localhost/projects/7?run_id=legacy'))).toBe(
      'legacy'
    );
    expect(
      selectedRunFromUrl(new URL('http://localhost/projects/7?run=canonical&run_id=legacy'))
    ).toBe('canonical');
  });

  it('updates scan detail paths and keeps the global parameter elsewhere', () => {
    expect(urlForSelectedRun(new URL('http://localhost/scans/old'), 'new')).toBe(
      '/scans/new?run_id=new'
    );
    expect(urlForSelectedRun(new URL('http://localhost/trends'), 'new')).toBe(
      '/trends?run_id=new'
    );
  });
});
