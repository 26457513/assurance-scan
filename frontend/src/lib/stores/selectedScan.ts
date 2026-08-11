import { writable, derived, type Readable } from 'svelte/store';
import type { ScanSummary } from '$lib/types';

export const selectedScan = writable<ScanSummary | null>(null);

export const selectedScanRunId: Readable<string | null> = derived(
  selectedScan,
  ($s) => $s?.run_id ?? null
);

export function selectScan(scan: ScanSummary | null): void {
  selectedScan.set(scan);
}
