import { describe, expect, it } from 'vitest';

import { isPrivilegedUser } from './currentUser';

describe('current user navigation policy', () => {
  it('shows advanced navigation only to privileged roles', () => {
    expect(isPrivilegedUser({ id: 1, login: 'user', role: 'user' })).toBe(false);
    expect(isPrivilegedUser({ id: 2, login: 'admin', role: 'admin' })).toBe(true);
    expect(isPrivilegedUser({ id: 3, login: 'super', role: 'superuser' })).toBe(true);
  });

  it('does not treat an unresolved identity as privileged', () => {
    expect(isPrivilegedUser(null)).toBe(false);
  });
});
