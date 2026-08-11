/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        surface: {
          base: 'var(--bg-base)',
          panel: 'var(--bg-panel)',
          elevated: 'var(--bg-elevated)',
          inset: 'var(--bg-inset)'
        },
        ink: {
          primary: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          muted: 'var(--text-muted)',
          inverse: 'var(--text-inverse)'
        },
        line: {
          hairline: 'var(--border-hairline)',
          strong: 'var(--border-strong)'
        },
        accent: {
          DEFAULT: 'var(--accent)',
          hover: 'var(--accent-hover)',
          subtle: 'var(--accent-subtle)'
        },
        state: {
          passed: 'var(--state-passed)',
          failed: 'var(--state-failed)',
          pending: 'var(--state-pending)',
          untested: 'var(--state-untested)',
          blocked: 'var(--state-blocked)',
          waived: 'var(--state-waived)'
        },
        severity: {
          CRITICAL: 'var(--state-failed)',
          HIGH: '#FCA5A5',
          MEDIUM: 'var(--state-pending)',
          LOW: '#A3E635',
          UNKNOWN: 'var(--state-untested)',
          INFO: 'var(--state-untested)'
        }
      },
      fontFamily: {
        sans: ['Geist', 'ui-sans-serif', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        mono: ['Geist Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace']
      },
      borderRadius: {
        DEFAULT: '2px',
        sm: '2px',
        md: '3px',
        lg: '3px'
      }
    }
  },
  plugins: []
};
