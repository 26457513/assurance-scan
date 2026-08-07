/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        severity: {
          CRITICAL: '#b91c1c',
          HIGH: '#dc2626',
          MEDIUM: '#d97706',
          LOW: '#65a30d',
          UNKNOWN: '#6b7280',
          INFO: '#6b7280'
        }
      }
    }
  },
  plugins: []
};
