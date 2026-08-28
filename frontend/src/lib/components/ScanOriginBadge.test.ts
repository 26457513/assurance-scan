import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import ScanOriginBadge from './ScanOriginBadge.svelte';

describe('ScanOriginBadge', () => {
  it.each([
    ['github-actions', 'GitHub Actions'],
    ['local', 'Local'],
    ['server', 'Server']
  ] as const)('labels the %s origin explicitly', (origin, label) => {
    render(ScanOriginBadge, { origin });
    expect(screen.getByText(label)).toHaveAttribute('data-origin', origin);
  });
});
