import { describe, expect, it } from 'vitest';

import { severityMeta, stateMeta } from './state';

describe('state metadata', () => {
  it('keeps the established labels and glyphs for known states', () => {
    expect(stateMeta('passed')).toEqual({
      label: 'passed',
      glyph: '✓',
      color: 'var(--state-passed)'
    });
    expect(severityMeta('CRITICAL')).toEqual({
      label: 'CRIT',
      color: 'var(--state-failed)'
    });
  });

  it('renders unknown values without discarding their source label', () => {
    expect(stateMeta('reviewing')).toMatchObject({ label: 'reviewing', glyph: '?' });
    expect(severityMeta('CUSTOM')).toMatchObject({ label: 'CUSTOM' });
  });
});
