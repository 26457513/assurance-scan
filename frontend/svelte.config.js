import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      // SPA mode: one index.html, all routing client-side.
      fallback: 'index.html'
    }),
    paths: {
      // FastAPI serves the built app at /, so the base is empty.
      base: ''
    }
  }
};

export default config;
