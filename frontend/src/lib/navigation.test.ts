import { describe, expect, it } from 'vitest';

import { visibleNavigation } from './navigation';

describe('sidebar navigation policy', () => {
  it('limits standard users to the core scan workflow', () => {
    expect(visibleNavigation(false).map((item) => item.label)).toEqual([
      'Setup',
      'Projects',
      'Scans',
      'Trends'
    ]);
  });

  it('keeps the advanced workflow available to privileged users', () => {
    expect(visibleNavigation(true).map((item) => item.label)).toEqual([
      'Setup',
      'Projects',
      'Scans',
      'Trends',
      'Regimes',
      'FRs',
      'Compliance',
      'Fix'
    ]);
  });
});
