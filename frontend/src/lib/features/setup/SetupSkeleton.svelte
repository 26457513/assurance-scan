<div class="skeleton" data-responsive-region="setup-skeleton" aria-label="Loading setup" aria-busy="true">
  <div class="line title"></div><div class="line subtitle"></div><div class="block topology"></div><div class="block foundation"></div><div class="lanes"><div class="block"></div><div class="block"></div></div>
</div>

<style>
  .skeleton { display: grid; gap: 1rem; }
  .line,.block { background: var(--bg-panel); animation: breathe 1.2s ease-in-out infinite alternate; }
  .title { width: 14rem; height: 1.7rem; }.subtitle { width: min(34rem,80%); height: .8rem; }.topology { height: 7rem; }.foundation { height: 12rem; }.lanes { display:grid;grid-template-columns:1.4fr 1fr;gap:1rem; }.lanes .block { height: 14rem; }
  @keyframes breathe { from { opacity: .65; } to { opacity: 1; } }
  @media (max-width:760px) { .lanes { grid-template-columns:1fr; } }
  @media (prefers-reduced-motion: reduce) { .line,.block { animation: none; } }
</style>
