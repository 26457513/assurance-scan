import { describe, expect, it } from 'vitest';

import { createRequestGate } from './requestGate';

describe('request gate', () => {
  it('deduplicates the same reactive key', () => {
    const gate = createRequestGate<number>();
    expect(gate.begin(7)).not.toBeNull();
    expect(gate.begin(7)).toBeNull();
    expect(gate.begin(8)).not.toBeNull();
  });

  it('marks an older asynchronous request as stale', () => {
    const gate = createRequestGate<number>();
    const first = gate.begin(7)!;
    const second = gate.begin(8)!;
    expect(gate.isCurrent(first)).toBe(false);
    expect(gate.isCurrent(second)).toBe(true);
  });

  it('allows an explicit refresh while invalidating the previous response', () => {
    const gate = createRequestGate<number>();
    const first = gate.begin(7)!;
    const refresh = gate.begin(7, { force: true })!;
    expect(gate.isCurrent(first)).toBe(false);
    expect(gate.isCurrent(refresh)).toBe(true);
  });
});
