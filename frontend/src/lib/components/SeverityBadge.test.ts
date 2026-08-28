import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import SeverityBadge from './SeverityBadge.svelte';

describe('SeverityBadge', () => {
  it('renders the stable abbreviated severity label and optional count', () => {
    render(SeverityBadge, { severity: 'CRITICAL', count: 7 });

    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('CRIT')).toBeInTheDocument();
    expect(screen.getByTitle('CRITICAL')).toHaveStyle('color: var(--state-failed)');
  });

  it('preserves an unknown severity label', () => {
    render(SeverityBadge, { severity: 'CUSTOM' });

    expect(screen.getByText('CUSTOM')).toBeInTheDocument();
  });
});
