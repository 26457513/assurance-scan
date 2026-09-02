export function githubStartUrl(requestedPath: string | null): string {
  const returnPath = requestedPath?.startsWith('/') && !requestedPath.startsWith('//')
    ? requestedPath
    : '/';
  return `/auth/github/start?next=${encodeURIComponent(returnPath)}`;
}
