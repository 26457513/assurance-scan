import { describe, expect, it } from 'vitest';

import { isPrivilegedUser } from './currentUser';

describe('current user navigation policy', () => {
  it('shows advanced navigation only to privileged roles', () => {
    expect(isPrivilegedUser({ email: 'user@example.test', role: 'user' })).toBe(false);
    expect(isPrivilegedUser({ email: 'admin@example.test', role: 'admin' })).toBe(true);
    expect(isPrivilegedUser({ email: 'super@example.test', role: 'superuser' })).toBe(true);
  });

  it('preserves advanced navigation for local operator sessions', () => {
    expect(isPrivilegedUser(null)).toBe(true);
  });
});
