import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import CopyButton from './CopyButton.svelte';

describe('CopyButton', () => {
  it('copies the supplied text and confirms the action', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText }
    });

    render(CopyButton, {
      text: 'scan-token',
      label: 'Copy token',
      copiedLabel: 'Token copied'
    });

    await fireEvent.click(screen.getByRole('button', { name: 'Copy token' }));

    expect(writeText).toHaveBeenCalledWith('scan-token');
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Token copied' })).toBeInTheDocument();
    });
  });
});
