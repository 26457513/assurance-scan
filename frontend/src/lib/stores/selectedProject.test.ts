import { get } from 'svelte/store';
import { beforeEach, describe, expect, it } from 'vitest';

import {
  projectSlug,
  selectedProject,
  selectProject,
  slugToProject
} from './selectedProject';

describe('selected project store', () => {
  beforeEach(() => selectProject(null));

  it('updates and clears the current project', () => {
    selectProject('github:26457513/assurance-scan');
    expect(get(selectedProject)).toBe('github:26457513/assurance-scan');

    selectProject(null);
    expect(get(selectedProject)).toBeNull();
  });

  it('round-trips project identities used in routes', () => {
    const identity = 'github:26457513/project with spaces';
    expect(slugToProject(projectSlug(identity))).toBe(identity);
  });
});
