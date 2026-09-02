import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from '$lib/api';
import CiWorkflowSetupPanel from './CiWorkflowSetupPanel.svelte';


const WORKFLOW = `name: assurance-scan
on:
  push:
    branches: [main]
jobs:
  scan:
    steps:
      - run: ghcr.io/26457513/assurance-scan-ci:latest
`;


afterEach(() => {
  vi.restoreAllMocks();
});


describe('CiWorkflowSetupPanel', () => {
  it('loads and presents the complete standard workflow', async () => {
    vi.spyOn(api, 'getCiWorkflowTemplate').mockResolvedValue({
      filename: '.github/workflows/assurance-scan.yml',
      default_branch: 'main',
      image: 'ghcr.io/26457513/assurance-scan-ci:latest',
      workflow: WORKFLOW
    });

    const { container } = render(CiWorkflowSetupPanel);

    expect(await screen.findByText('.github/workflows/assurance-scan.yml')).toBeInTheDocument();
    expect(container.textContent).toContain('ghcr.io/26457513/assurance-scan-ci:latest');
    expect(container.textContent).toContain('Pin when required');
    expect(api.getCiWorkflowTemplate).toHaveBeenCalledWith('main');
  });

  it('regenerates and copies the workflow for a changed default branch', async () => {
    const getTemplate = vi.spyOn(api, 'getCiWorkflowTemplate').mockImplementation(async (requestedBranch) => ({
      filename: '.github/workflows/assurance-scan.yml',
      default_branch: requestedBranch ?? 'main',
      image: 'ghcr.io/26457513/assurance-scan-ci:latest',
      workflow: WORKFLOW.replace('[main]', `[${requestedBranch ?? 'main'}]`)
    }));
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText }
    });
    render(CiWorkflowSetupPanel);
    await waitFor(() => expect(getTemplate).toHaveBeenCalledWith('main'));

    const branch = screen.getByRole('textbox', { name: 'Default branch' });
    await fireEvent.input(branch, { target: { value: 'trunk' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Update file' }));
    await waitFor(() => expect(getTemplate).toHaveBeenCalledWith('trunk'));
    await fireEvent.click(screen.getByRole('button', { name: 'Copy workflow' }));

    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('branches: [trunk]'));
  });
});
