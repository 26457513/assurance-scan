import { writable } from 'svelte/store';

export const selectedProject = writable<string | null>(null);

export function selectProject(path: string | null): void {
  selectedProject.set(path);
}

export const projectSlug = (path: string) => encodeURIComponent(path);
export const slugToProject = (slug: string) => decodeURIComponent(slug);
