/** Keep scan selection URLs canonical across project and non-project pages. */

const PROJECT_PATH = /^\/projects\/[^/]+$/;
const SCAN_PATH = /^\/scans\/[^/]+$/;

export function selectedRunFromUrl(url: URL): string | null {
  if (PROJECT_PATH.test(url.pathname)) {
    return url.searchParams.get('run') ?? url.searchParams.get('run_id');
  }
  return url.searchParams.get('run_id');
}

export function urlForSelectedRun(source: URL, runId: string): string {
  const url = new URL(source);
  if (SCAN_PATH.test(url.pathname)) {
    url.pathname = `/scans/${encodeURIComponent(runId)}`;
  }
  if (PROJECT_PATH.test(url.pathname)) {
    url.searchParams.set('run', runId);
    url.searchParams.delete('run_id');
  } else {
    url.searchParams.set('run_id', runId);
    url.searchParams.delete('run');
  }
  return `${url.pathname}?${url.searchParams.toString()}`;
}
