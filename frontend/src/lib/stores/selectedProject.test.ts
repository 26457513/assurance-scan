import { get } from 'svelte/store';
import { beforeEach, describe, expect, it } from 'vitest';

import { selectedProject, selectProject } from './selectedProject';

describe('selected project store', () => {
  beforeEach(() => selectProject(null));

  it('updates and clears the current project', () => {
    selectProject(42);
    expect(get(selectedProject)).toBe(42);

    selectProject(null);
    expect(get(selectedProject)).toBeNull();
  });

  it('keeps numeric identity without path aliases', () => {
    selectProject(17);
    expect(get(selectedProject)).toBe(17);
  });
});
