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
      image: 'ghcr.io/26457513/assurance-scan-ci:latest',
      uploader_image: 'ghcr.io/26457513/assurance-scan-ci-upload:latest',
      workflow: WORKFLOW
    });

    const { container } = render(CiWorkflowSetupPanel);

    expect(await screen.findByText('.github/workflows/assurance-scan.yml')).toBeInTheDocument();
    expect(container.textContent).toContain('ghcr.io/26457513/assurance-scan-ci:latest');
    expect(container.textContent).toContain('Pin when required');
    expect(api.getCiWorkflowTemplate).toHaveBeenCalledWith();
  });

  it('copies the branch-independent workflow', async () => {
    const getTemplate = vi.spyOn(api, 'getCiWorkflowTemplate').mockResolvedValue({
      filename: '.github/workflows/assurance-scan.yml',
      image: 'ghcr.io/26457513/assurance-scan-ci:latest',
      uploader_image: 'ghcr.io/26457513/assurance-scan-ci-upload:latest',
      workflow: WORKFLOW
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText }
    });
    render(CiWorkflowSetupPanel);
    await waitFor(() => expect(getTemplate).toHaveBeenCalledWith());
    await fireEvent.click(screen.getByRole('button', { name: 'Copy workflow' }));

    expect(writeText).toHaveBeenCalledWith(WORKFLOW);
  });
});
