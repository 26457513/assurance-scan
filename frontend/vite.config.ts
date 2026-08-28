import { sveltekit } from '@sveltejs/kit/vite';
import { svelteTesting } from '@testing-library/svelte/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [sveltekit(), svelteTesting()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.ts'],
    clearMocks: true
  },
  server: {
    port: 5173,
    proxy: {
      // Forward API calls to the FastAPI backend during dev.
      '/api': 'http://127.0.0.1:8742',
      '/health': 'http://127.0.0.1:8742'
    }
  }
});
