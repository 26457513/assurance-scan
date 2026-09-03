import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import TrustFlowDiagram from './TrustFlowDiagram.svelte';

describe('TrustFlowDiagram', () => {
  it('explains both evidence paths and the local source boundary', () => {
    render(TrustFlowDiagram);

    expect(screen.getByText('One trust model. Two evidence paths.')).toBeInTheDocument();
    expect(screen.getByText('GitHub-hosted')).toBeInTheDocument();
    expect(screen.getByText('Local · source stays here')).toBeInTheDocument();
    expect(screen.getByText('GitHub access decides what you see')).toBeInTheDocument();
    expect(screen.getByText('SOURCE CONTAINED')).toBeInTheDocument();
  });
});
