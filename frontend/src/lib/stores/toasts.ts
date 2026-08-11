import { writable } from 'svelte/store';

export type ToastKind = 'info' | 'success' | 'error';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  ts: number;
}

let nextId = 1;

export const toasts = writable<Toast[]>([]);

export function pushToast(kind: ToastKind, message: string): void {
  const id = nextId++;
  toasts.update((list) => [...list, { id, kind, message, ts: Date.now() }]);
  setTimeout(() => {
    toasts.update((list) => list.filter((t) => t.id !== id));
  }, 3500);
}

export function dismissToast(id: number): void {
  toasts.update((list) => list.filter((t) => t.id !== id));
}
