import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import LocalScanSetupPanel from './LocalScanSetupPanel.svelte';

describe('LocalScanSetupPanel', () => {
  it('shows the complete token, enrollment, scan, and recovery path', () => {
    const { container } = render(LocalScanSetupPanel);

    expect(screen.getByText('Install the host wrapper')).toBeInTheDocument();
    expect(screen.getByText('Create an upload token')).toBeInTheDocument();
    expect(screen.getByText('Enroll this machine once')).toBeInTheDocument();
    expect(screen.getByText('Scan from the repository root')).toBeInTheDocument();
    expect(screen.getByText('Retry an upload')).toBeInTheDocument();
    expect(screen.getByText('Inspect the outbox')).toBeInTheDocument();
    expect(screen.getByText('Remove access')).toBeInTheDocument();
    expect(container.textContent).toContain('$HOME/.config/assurance-scan/config.json');
    expect(container.textContent).toContain('0600');
    expect(container.textContent).toContain('assurance-scan scan');
    expect(container).toHaveTextContent(/signed release\s+manifest/);
    expect(container.textContent).toContain('cache prune');
    expect(container.textContent).toContain('Raw artifacts: 30 days');
    expect(container.textContent).toContain('Normalized runs and findings: 365 days');
    expect(container).toHaveTextContent(/Inactive-token audit:\s*400 days/);
    expect(container.textContent).toContain('never passed to scanner containers');
    expect(container).toHaveTextContent(/source\s+snapshot and absolute host paths are not uploaded/);
    const content = container.textContent ?? '';
    expect(content.indexOf('Install the host wrapper')).toBeLessThan(
      content.indexOf('Create an upload token')
    );
    expect(content.indexOf('Create an upload token')).toBeLessThan(
      content.indexOf('Enroll this machine once')
    );
  });

  it('offers one qualified command across supported hosts', () => {
    const { container } = render(LocalScanSetupPanel);
    expect(screen.getByText(/Native Windows and WSL 2 are not v1 targets/)).toBeInTheDocument();
    expect(screen.getByLabelText('Verified release policy')).toHaveTextContent('immutable digest');
    expect(container.textContent).not.toContain('docker run --rm -it --pull=always');
  });

  it('copies the full one-command scan invocation', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText }
    });
    render(LocalScanSetupPanel);

    await fireEvent.click(screen.getByRole('button', { name: 'Copy scan' }));
    expect(writeText).toHaveBeenCalledTimes(1);
    const copied = writeText.mock.calls[0][0] as string;
    expect(copied).toBe('assurance-scan scan');
    expect(copied).not.toContain('asu_v1_');
  });
});
