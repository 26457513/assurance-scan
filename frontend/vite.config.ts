import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    port: 5173,
    proxy: {
      // Forward API calls to the FastAPI backend during dev.
      '/api': 'http://127.0.0.1:8742',
      '/health': 'http://127.0.0.1:8742'
    }
  }
});
