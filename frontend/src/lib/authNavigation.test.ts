import { describe, expect, it } from 'vitest';

import { githubStartUrl } from './authNavigation';


describe('githubStartUrl', () => {
  it('preserves an internal return path', () => {
    expect(githubStartUrl('/projects?run_id=local-12')).toBe(
      '/auth/github/start?next=%2Fprojects%3Frun_id%3Dlocal-12'
    );
  });

  it.each([null, 'https://example.test', '//example.test']) (
    'rejects a non-local return path: %s',
    (path) => {
      expect(githubStartUrl(path)).toBe('/auth/github/start?next=%2F');
    }
  );
});
