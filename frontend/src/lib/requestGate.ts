/** Deduplicate reactive loads and reject stale asynchronous responses. */

export interface RequestTicket<Key> {
  readonly key: Key;
  readonly revision: number;
}

export interface RequestGate<Key> {
  begin(key: Key, options?: { force?: boolean }): RequestTicket<Key> | null;
  isCurrent(ticket: RequestTicket<Key>): boolean;
}

const UNSET = Symbol('unset-request-key');

export function createRequestGate<Key>(): RequestGate<Key> {
  let currentKey: Key | typeof UNSET = UNSET;
  let revision = 0;

  return {
    begin(key, options = {}) {
      if (!options.force && currentKey !== UNSET && Object.is(currentKey, key)) {
        return null;
      }
      currentKey = key;
      revision += 1;
      return { key, revision };
    },

    isCurrent(ticket) {
      return revision === ticket.revision && Object.is(currentKey, ticket.key);
    }
  };
}
