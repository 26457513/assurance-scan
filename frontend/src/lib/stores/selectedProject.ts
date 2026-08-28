import { writable } from 'svelte/store';

export const selectedProject = writable<number | null>(null);

export function selectProject(projectId: number | null): void {
  selectedProject.set(projectId);
}
