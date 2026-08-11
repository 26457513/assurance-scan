export interface StateMeta {
  label: string;
  glyph: string;
  color: string;
}

export const STATE_META: Record<string, StateMeta> = {
  // FR states
  passed:   { label: 'passed',   glyph: '✓', color: 'var(--state-passed)' },
  failed:   { label: 'failed',   glyph: '✕', color: 'var(--state-failed)' },
  pending:  { label: 'pending',  glyph: '◐', color: 'var(--state-pending)' },
  untested: { label: 'untested', glyph: '○', color: 'var(--state-untested)' },
  blocked:  { label: 'blocked',  glyph: '!', color: 'var(--state-blocked)' },
  waived:   { label: 'waived',   glyph: '〜', color: 'var(--state-waived)' },
  accepted: { label: 'accepted', glyph: '◑', color: '#F59E0B' },
  'n/a':    { label: 'n/a',      glyph: '—', color: 'var(--text-muted)' },
  // Scan execution statuses
  queued:    { label: 'queued',    glyph: '◌', color: 'var(--text-muted)' },
  running:   { label: 'running',   glyph: '▶', color: 'var(--accent)' },
  completed: { label: 'completed', glyph: '✓', color: 'var(--state-passed)' },
  cancelled: { label: 'cancelled', glyph: '⊘', color: 'var(--text-muted)' }
};

export function stateMeta(state: string): StateMeta {
  return (
    STATE_META[state] ?? {
      label: state || 'unknown',
      glyph: '?',
      color: 'var(--state-untested)'
    }
  );
}

export interface SeverityMeta {
  label: string;
  color: string;
}

export const SEVERITY_META: Record<string, SeverityMeta> = {
  CRITICAL: { label: 'CRIT', color: 'var(--state-failed)' },
  HIGH:     { label: 'HIGH', color: '#FCA5A5' },
  MEDIUM:   { label: 'MED',  color: 'var(--state-pending)' },
  LOW:      { label: 'LOW',  color: '#A3E635' },
  UNKNOWN:  { label: 'UNK',  color: 'var(--state-untested)' },
  INFO:     { label: 'INFO', color: 'var(--state-untested)' }
};

export function severityMeta(severity: string): SeverityMeta {
  return SEVERITY_META[severity] ?? { label: severity, color: 'var(--state-untested)' };
}
