export type NavigationItem = {
  href: string;
  label: string;
  glyph: string;
  match: string;
  scoped: boolean;
  divider: boolean;
  privileged: boolean;
};

export const navigationItems: readonly NavigationItem[] = [
  { href: '/setup', label: 'Setup', glyph: '⚙', match: '/setup', scoped: false, divider: true, privileged: false },
  { href: '/projects', label: 'Projects', glyph: '❏', match: '/projects', scoped: false, divider: false, privileged: false },
  { href: '', label: 'Scans', glyph: '⌗', match: '', scoped: true, divider: false, privileged: false },
  { href: '/trends', label: 'Trends', glyph: '↗', match: '/trends', scoped: true, divider: true, privileged: false },
  { href: '/regimes', label: 'Regimes', glyph: '§', match: '/regimes', scoped: false, divider: false, privileged: true },
  { href: '/frs', label: 'FRs', glyph: '☰', match: '/frs', scoped: true, divider: false, privileged: true },
  { href: '/compliance', label: 'Compliance', glyph: '⚖', match: '/compliance', scoped: true, divider: false, privileged: true },
  { href: '/fix', label: 'Fix', glyph: '⚑', match: '/fix', scoped: false, divider: true, privileged: true },
  { href: '/admin', label: 'Admin', glyph: '⌁', match: '/admin', scoped: false, divider: false, privileged: true }
];

export function visibleNavigation(privileged: boolean): readonly NavigationItem[] {
  return navigationItems.filter((item) => !item.privileged || privileged);
}
