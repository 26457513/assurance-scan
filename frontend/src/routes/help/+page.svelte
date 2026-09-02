<div class="help-page">
  <header><p>Operator guide</p><h1>Help</h1><span>How trusted scan results enter Assurance Scan.</span></header>
  <section><h2>GitHub Actions</h2><p>The standard workflow runs for pushes to the repository’s default branch, including the push created by merging a pull request. GitHub supplies a short-lived OIDC identity; no Assurance Scan secret is stored in the repository.</p></section>
  <section><h2>Local branches</h2><p>Use the verified local CLI for feature branches and work in progress. Local results remain private to the person whose upload token submitted them, while GitHub access is rechecked before each upload.</p></section>
  <section id="uploads"><h2>Upload troubleshooting</h2><p>Use the safe error code and request correlation ID shown in Setup. Retry only when the interface marks the failure as temporary; authentication, repository access, and invalid-bundle failures need correction first.</p></section>
</div>

<style>
  .help-page{width:min(100%,52rem);margin:auto;padding:2rem clamp(1rem,4vw,2.5rem) 4rem}header>p{color:var(--state-passed);font:600 .62rem 'Geist Mono',monospace;letter-spacing:.14em;text-transform:uppercase}h1{margin:.35rem 0 .55rem;font-size:2rem;letter-spacing:-.035em}header>span,p{color:var(--text-secondary);font-size:.8rem;line-height:1.65}section{display:grid;grid-template-columns:10rem 1fr;gap:1.5rem;border-top:1px solid var(--border-hairline);padding:1.25rem 0}section:first-of-type{margin-top:1.5rem}h2{color:var(--text-primary);font:.76rem 'Geist Mono',monospace}@media(max-width:560px){section{grid-template-columns:1fr;gap:.45rem}}
</style>
