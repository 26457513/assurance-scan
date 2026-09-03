<script lang="ts">
  import { page } from '$app/stores';
  import { githubStartUrl } from '$lib/authNavigation';

  $: githubStart = githubStartUrl($page.url.searchParams.get('next'));
  $: signedOut = $page.url.searchParams.get('signed_out') === '1';
</script>

<svelte:head>
  <title>Sign in · Assurance Scan</title>
  <meta
    name="description"
    content="Sign in to Assurance Scan with your existing GitHub identity and repository access."
  />
</svelte:head>

<div class="login-page">
  <section class="identity" aria-labelledby="login-heading">
    <a class="wordmark" href="/auth/login" aria-label="Assurance Scan sign in">
      <span aria-hidden="true">⬡</span>
      <span>Assurance Scan</span>
    </a>

    <div class="identity-copy">
      <p class="context">Code assurance, tied to the repositories you already trust.</p>
      <h1 id="login-heading">One identity.<br />The right evidence.</h1>
      <p class="explanation">
        Your GitHub access decides which organisations, repositories and scan results you can see.
      </p>
    </div>

    <div class="trust-path" aria-label="How access works">
      <div><span>GitHub identity</span><strong>verified</strong></div>
      <div><span>Repository access</span><strong>respected</strong></div>
      <div><span>Scan evidence</span><strong>scoped</strong></div>
    </div>
  </section>

  <section class="action" aria-label="Sign in">
    <div class="action-inner">
      {#if signedOut}
        <p class="signed-out" role="status">Signed out of Assurance Scan</p>
      {/if}
      <h2>Continue to your workspace</h2>
      <p>
        Use the GitHub account that has access to the repositories you want to review.
      </p>

      <a class="github-button" href={githubStart}>
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path fill="currentColor" d="M12 .7a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2.24c-3.22.7-3.9-1.37-3.9-1.37-.52-1.34-1.28-1.7-1.28-1.7-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.57-.29-5.27-1.28-5.27-5.68 0-1.25.45-2.28 1.19-3.08-.12-.29-.52-1.46.11-3.04 0 0 .97-.31 3.16 1.18A10.9 10.9 0 0 1 12 6.13c.98 0 1.95.13 2.87.39 2.2-1.49 3.16-1.18 3.16-1.18.63 1.58.23 2.75.11 3.04.74.8 1.19 1.83 1.19 3.08 0 4.42-2.71 5.38-5.29 5.67.42.36.79 1.07.79 2.15v3.27c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .7Z" />
        </svg>
        <span>Continue with GitHub</span>
      </a>

      <div class="boundary">
        <span class="boundary-mark" aria-hidden="true"></span>
        <p>
          Your password stays with GitHub. Assurance Scan receives your verified GitHub identity
          and authorised repository access.
        </p>
      </div>

      <p class="provider-note">
        On GitHub, choose your existing GitHub account. Google or Apple sign-in only works there
        when that identity is already linked to a GitHub account.
      </p>
    </div>

    <p class="footnote">Access changes in GitHub are reflected in Assurance Scan.</p>
  </section>
</div>

<style>
  .login-page {
    min-height: 100%;
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) minmax(360px, 0.8fr);
    background: var(--bg-base);
  }

  .identity,
  .action {
    min-height: 100vh;
    padding: clamp(28px, 5vw, 72px);
  }

  .identity {
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--border-hairline);
    background:
      linear-gradient(90deg, transparent 0 49.9%, rgba(74, 222, 128, 0.05) 50%, transparent 50.1%),
      var(--bg-panel);
  }

  .wordmark {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    width: fit-content;
    color: var(--text-primary);
    font-size: 14px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }

  .wordmark span:first-child {
    color: var(--accent);
    font-size: 18px;
  }

  .identity-copy {
    max-width: 660px;
    margin: auto 0;
  }

  .context {
    max-width: 480px;
    margin: 0 0 28px;
    color: var(--accent);
    font-size: 13px;
  }

  h1 {
    margin: 0;
    color: var(--text-primary);
    font-size: clamp(44px, 6vw, 86px);
    font-weight: 520;
    letter-spacing: -0.065em;
    line-height: 0.94;
  }

  .explanation {
    max-width: 540px;
    margin: 34px 0 0;
    color: var(--text-secondary);
    font-size: clamp(16px, 1.4vw, 19px);
    line-height: 1.6;
  }

  .trust-path {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    border-top: 1px solid var(--border-strong);
  }

  .trust-path div {
    display: grid;
    gap: 5px;
    padding: 18px 18px 0 0;
    border-right: 1px solid var(--border-hairline);
  }

  .trust-path div + div {
    padding-left: 18px;
  }

  .trust-path div:last-child {
    border-right: 0;
  }

  .trust-path span,
  .trust-path strong {
    font-size: 12px;
    font-weight: 450;
  }

  .trust-path span { color: var(--text-muted); }
  .trust-path strong { color: var(--text-primary); }

  .action {
    display: flex;
    flex-direction: column;
    justify-content: center;
    background: var(--bg-base);
  }

  .action-inner {
    width: min(100%, 440px);
    margin: auto;
  }

  h2 {
    margin: 0;
    color: var(--text-primary);
    font-size: clamp(25px, 3vw, 34px);
    font-weight: 520;
    letter-spacing: -0.035em;
  }

  .action-inner > p {
    margin: 14px 0 30px;
    color: var(--text-secondary);
    font-size: 15px;
    line-height: 1.6;
  }

  .action-inner > .signed-out {
    width: fit-content;
    margin: 0 0 22px;
    padding: 7px 10px;
    border-left: 2px solid var(--accent);
    background: var(--accent-subtle);
    color: var(--text-primary);
    font-size: 12px;
    line-height: 1.4;
  }

  .github-button {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    min-height: 50px;
    padding: 0 20px;
    border: 1px solid var(--accent);
    border-radius: 3px;
    background: var(--accent);
    color: var(--text-inverse);
    font-size: 14px;
    font-weight: 650;
    transition: background-color 140ms ease, border-color 140ms ease;
  }

  .github-button:hover {
    border-color: var(--accent-hover);
    background: var(--accent-hover);
  }

  .github-button svg {
    width: 19px;
    height: 19px;
  }

  .boundary {
    display: grid;
    grid-template-columns: 8px 1fr;
    gap: 13px;
    margin-top: 24px;
    padding-top: 20px;
    border-top: 1px solid var(--border-hairline);
  }

  .boundary-mark {
    width: 7px;
    height: 7px;
    margin-top: 6px;
    border: 1px solid var(--accent);
    transform: rotate(45deg);
  }

  .boundary p,
  .provider-note,
  .footnote {
    margin: 0;
    color: var(--text-muted);
    font-size: 12px;
    line-height: 1.6;
  }

  .action-inner > .provider-note {
    margin: 18px 0 0;
    color: var(--text-secondary);
  }

  .footnote {
    width: min(100%, 440px);
    margin: auto auto 0;
  }

  @media (max-width: 820px) {
    .login-page { grid-template-columns: 1fr; }
    .identity,
    .action { min-height: auto; }
    .identity { min-height: 52vh; border-right: 0; border-bottom: 1px solid var(--border-hairline); }
    .identity-copy { margin: 12vh 0; }
    .action { min-height: 48vh; }
    .footnote { margin-top: 64px; }
  }

  @media (max-width: 520px) {
    .identity,
    .action { padding: 24px; }
    .identity-copy { margin: 72px 0; }
    .trust-path { grid-template-columns: 1fr; }
    .trust-path div,
    .trust-path div + div { padding: 12px 0; border-right: 0; border-bottom: 1px solid var(--border-hairline); }
    .trust-path div:last-child { border-bottom: 0; }
    .action { padding-block: 56px 24px; }
  }

  @media (prefers-reduced-motion: reduce) {
    .github-button { transition: none; }
  }
</style>
