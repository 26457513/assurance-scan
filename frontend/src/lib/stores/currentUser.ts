import { writable } from 'svelte/store';
import { api } from '$lib/api';

export type CurrentUser = { email: string; role: string };

export const currentUser = writable<CurrentUser | null>(null);
export const currentUserResolved = writable(false);

let pending: Promise<CurrentUser | null> | null = null;

export function isPrivilegedUser(user: CurrentUser | null): boolean {
  // Auth-off and valid Basic Auth sessions are local operator sessions and
  // deliberately have no User row.
  return user === null || user.role === 'admin' || user.role === 'superuser';
}

export function loadCurrentUser(): Promise<CurrentUser | null> {
  if (pending) return pending;
  pending = api.me()
    .then((user) => {
      currentUser.set(user);
      return user;
    })
    .catch(() => {
      currentUser.set(null);
      return null;
    })
    .finally(() => currentUserResolved.set(true));
  return pending;
}
