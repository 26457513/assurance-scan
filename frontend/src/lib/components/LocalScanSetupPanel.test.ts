import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import LocalScanSetupPanel from './LocalScanSetupPanel.svelte';

describe('LocalScanSetupPanel', () => {
  it('shows the complete token, enrollment, scan, and recovery path', () => {
    const { container } = render(LocalScanSetupPanel);

    expect(screen.getByText('Create an upload token')).toBeInTheDocument();
    expect(screen.getByText('Enroll this machine once')).toBeInTheDocument();
    expect(screen.getByText('Scan from the repository root')).toBeInTheDocument();
    expect(screen.getByText('Retry an upload')).toBeInTheDocument();
    expect(screen.getByText('Inspect the outbox')).toBeInTheDocument();
    expect(screen.getByText('Remove access')).toBeInTheDocument();
    expect(container.textContent).toContain('$HOME/.config/assurance-scan/config.json');
    expect(container.textContent).toContain('0600');
    expect(container.textContent).toContain('--pull=always');
    expect(container.textContent).toContain('cache prune');
    expect(container.textContent).toContain('Raw artifacts: 30 days');
    expect(container.textContent).toContain('Normalized runs and findings: 365 days');
    expect(container).toHaveTextContent(/Inactive-token audit:\s*400 days/);
    expect(container.textContent).toContain('never passed to scanner containers');
    expect(container).toHaveTextContent(/source\s+snapshot and absolute host paths are not uploaded/);
  });

  it('states the qualified platforms without inventing different commands', () => {
    const { container } = render(LocalScanSetupPanel);
    expect(container.textContent).toContain('macOS · Linux');
    expect(screen.getByText(/Native Windows and WSL 2 are not v1 targets/)).toBeInTheDocument();
    expect(container.textContent).not.toContain("stat -c '%g'");
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
    expect(copied).toContain('ghcr.io/26457513/assurance-scan-cli:stable scan');
    expect(copied).toContain('-v "$PWD:$PWD:ro"');
    expect(copied).not.toContain('asu_v1_');
  });
});
