import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ScanToken } from '$lib/types';

import ScanTokensPanel from './ScanTokensPanel.svelte';

const apiMocks = vi.hoisted(() => ({
  listScanTokens: vi.fn(),
  createScanToken: vi.fn(),
  revokeScanToken: vi.fn()
}));

vi.mock('$lib/api', () => ({ api: apiMocks }));

const activeToken: ScanToken = {
  id: 'token-active',
  label: 'Work laptop',
  scope: 'scans:upload',
  status: 'active',
  created_at: '2026-08-01T09:00:00Z',
  expires_at: '2026-11-01T09:00:00Z',
  last_used_at: null,
  revoked_at: null
};

describe('ScanTokensPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date('2026-08-28T10:00:00Z'));
    apiMocks.listScanTokens.mockReset().mockResolvedValue({
      tokens: [activeToken],
      csrf_token: 'csrf-value',
      creation_enabled: true
    });
    apiMocks.createScanToken.mockReset();
    apiMocks.revokeScanToken.mockReset();
  });

  it('shows token lifecycle information and revokes only after confirmation', async () => {
    apiMocks.revokeScanToken.mockResolvedValue({ status: 'revoked' });
    render(ScanTokensPanel);

    expect(await screen.findByText('Work laptop')).toBeInTheDocument();
    expect(screen.getByText('active')).toBeInTheDocument();
    expect(screen.getByText('Never')).toBeInTheDocument();

    await fireEvent.click(screen.getByRole('button', { name: 'Revoke Work laptop' }));
    expect(apiMocks.revokeScanToken).not.toHaveBeenCalled();

    await fireEvent.click(screen.getByRole('button', { name: 'Confirm revoke Work laptop' }));
    await waitFor(() => {
      expect(apiMocks.revokeScanToken).toHaveBeenCalledWith('token-active', 'csrf-value');
    });
  });

  it('creates a labelled token with the selected expiry and reveals its secret once', async () => {
    apiMocks.createScanToken.mockResolvedValue({ token: 'asu_v1_selector.one-time-secret' });
    render(ScanTokensPanel);

    await screen.findByText('Work laptop');
    await fireEvent.input(screen.getByLabelText('Machine label'), {
      target: { value: 'Travel laptop' }
    });
    await fireEvent.change(screen.getByLabelText('Token expiry'), {
      target: { value: '180' }
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Create token' }));

    await waitFor(() => {
      expect(apiMocks.createScanToken).toHaveBeenCalledWith(
        'Travel laptop',
        180,
        'csrf-value'
      );
    });
    expect(await screen.findByText('asu_v1_selector.one-time-secret')).toBeInTheDocument();
    expect(screen.getByText('Save this token now')).toBeInTheDocument();

    await fireEvent.click(screen.getByRole('button', { name: 'I have saved it' }));
    expect(screen.queryByText('asu_v1_selector.one-time-secret')).not.toBeInTheDocument();
  });

  it('shows nearing-expiry, last-used, expired, and revoked audit states', async () => {
    apiMocks.listScanTokens.mockResolvedValue({
      csrf_token: 'csrf-value',
      creation_enabled: true,
      tokens: [
        {
          ...activeToken,
          id: 'token-soon',
          label: 'Travel laptop',
          expires_at: '2026-09-04T10:00:00Z',
          last_used_at: '2026-08-27T14:30:00Z'
        },
        {
          ...activeToken,
          id: 'token-expired',
          label: 'Old workstation',
          status: 'expired',
          expires_at: '2026-08-20T10:00:00Z'
        },
        {
          ...activeToken,
          id: 'token-revoked',
          label: 'Retired laptop',
          status: 'revoked',
          revoked_at: '2026-08-25T08:00:00Z'
        }
      ]
    });

    render(ScanTokensPanel);

    expect(await screen.findByText('Travel laptop')).toBeInTheDocument();
    expect(screen.getByText('expires soon')).toBeInTheDocument();
    expect(screen.getByText('Expires in 7 days')).toBeInTheDocument();
    expect(screen.getByText('expired')).toBeInTheDocument();
    expect(screen.getByText('revoked')).toBeInTheDocument();
    expect(screen.getAllByText('Last used')).toHaveLength(3);
    expect(screen.getByRole('table', { name: 'Issued local scan tokens' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Revoke Travel laptop' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Revoke Old workstation' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Revoke Retired laptop' })).not.toBeInTheDocument();
  });

  it('explains a disabled rollout while preserving token revocation', async () => {
    apiMocks.listScanTokens.mockResolvedValue({
      tokens: [activeToken],
      csrf_token: 'csrf-value',
      creation_enabled: false
    });
    apiMocks.revokeScanToken.mockResolvedValue({ status: 'revoked' });
    render(ScanTokensPanel);

    expect(
      await screen.findByText(/Token creation is not enabled for this account/)
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Machine label')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Create token' })).toBeDisabled();
    await fireEvent.click(screen.getByRole('button', { name: 'Revoke Work laptop' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Confirm revoke Work laptop' }));
    await waitFor(() => {
      expect(apiMocks.revokeScanToken).toHaveBeenCalledWith('token-active', 'csrf-value');
    });
  });
});
