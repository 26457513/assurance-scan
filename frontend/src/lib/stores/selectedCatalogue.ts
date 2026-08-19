import { writable } from 'svelte/store';

export interface SelectedCatalogue {
  snapshot_id: string;
  version: string | null;
  tag: string | null;
  fr_count: number;
}

export const selectedCatalogue = writable<SelectedCatalogue | null>(null);

export function selectCatalogue(c: SelectedCatalogue | null): void {
  selectedCatalogue.set(c);
}
