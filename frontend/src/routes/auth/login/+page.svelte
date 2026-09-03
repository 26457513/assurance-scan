<script lang="ts">
  import { page } from '$app/stores';
  import { githubStartUrl } from '$lib/authNavigation';
  import AssuranceMark from '$lib/features/auth/AssuranceMark.svelte';
  import TrustFlowDiagram from '$lib/features/auth/TrustFlowDiagram.svelte';

  $: githubStart = githubStartUrl($page.url.searchParams.get('next'));
  $: signedOut = $page.url.searchParams.get('signed_out') === '1';
</script>

<svelte:head>
  <title>Sign in · Assurance Scan</title>
  <meta
    name="description"
    content="Automated assurance with GitHub-governed access and secure local scanning."
  />
</svelte:head>

<div class="login-page">
  <header class="brand-header">
    <a class="wordmark" href="/auth/login" aria-label="Assurance Scan sign in">
      <AssuranceMark size={74} />
      <span class="brand-copy">
        <strong>Assurance Scan</strong>
        <small>Continuous evidence for software teams</small>
      </span>
    </a>
    <div class="trust-status"><i></i> GitHub-governed access</div>
  </header>

  <main>
    <section class="introduction" aria-labelledby="login-heading">
      {#if signedOut}
        <p class="signed-out" role="status">Signed out of Assurance Scan</p>
      {/if}

      <h1 id="login-heading">Automated<br />Assurance</h1>
      <p class="lead">
        Turn every GitHub run and local branch scan into evidence your team can trust—without
        building another permissions system around your code.
      </p>

      <div class="sign-in-block">
        <a class="github-button" href={githubStart}>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path fill="currentColor" d="M12 .7a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2.24c-3.22.7-3.9-1.37-3.9-1.37-.52-1.34-1.28-1.7-1.28-1.7-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.57-.29-5.27-1.28-5.27-5.68 0-1.25.45-2.28 1.19-3.08-.12-.29-.52-1.46.11-3.04 0 0 .97-.31 3.16 1.18A10.9 10.9 0 0 1 12 6.13c.98 0 1.95.13 2.87.39 2.2-1.49 3.16-1.18 3.16-1.18.63 1.58.23 2.75.11 3.04.74.8 1.19 1.83 1.19 3.08 0 4.42-2.71 5.38-5.29 5.67.42.36.79 1.07.79 2.15v3.27c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .7Z" />
          </svg>
          <span>Continue with GitHub</span>
        </a>
        <p class="account-guidance">
          Choose the GitHub account with access to your repositories. Google or Apple sign-in on
          GitHub only works when already linked to a GitHub account.
        </p>
        <p class="first-visit"><strong>First visit?</strong> Setup takes under a minute: choose the organisations and repositories to connect on one GitHub screen. Your teammates only need to sign in.</p>
      </div>

      <dl class="assurance-points">
        <div>
          <dt>Identity</dt>
          <dd>GitHub verifies who you are</dd>
        </div>
        <div>
          <dt>Access</dt>
          <dd>Repository permissions decide what you see</dd>
        </div>
        <div>
          <dt>Privacy</dt>
          <dd>Local source stays on your machine</dd>
        </div>
      </dl>
    </section>

    <section class="diagram" aria-label="Assurance Scan trust workflow">
      <TrustFlowDiagram />
    </section>
  </main>

  <footer>
    <span>Passwords stay with GitHub.</span>
    <span>Local credentials are encrypted at rest.</span>
    <span>Only scan evidence reaches Assurance Scan.</span>
  </footer>
</div>

<style>
  :global(body) { overflow-x: hidden; }

  .login-page {
    position: relative;
    min-height: 100vh;
    overflow-x: clip;
    background:
      radial-gradient(circle at 78% 48%, rgba(88, 166, 255, 0.055), transparent 34%),
      radial-gradient(circle at 18% 80%, rgba(74, 222, 128, 0.045), transparent 30%),
      var(--bg-base);
  }

  .login-page::before {
    position: absolute;
    inset: 0;
    pointer-events: none;
    content: '';
    background-image:
      linear-gradient(rgba(255, 255, 255, 0.014) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255, 255, 255, 0.014) 1px, transparent 1px);
    background-size: 44px 44px;
    mask-image: linear-gradient(to bottom, black, transparent 86%);
  }

  .brand-header,
  main,
  footer {
    position: relative;
    z-index: 1;
    width: min(1500px, calc(100% - clamp(40px, 8vw, 128px)));
    margin-inline: auto;
  }

  .brand-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
    padding-block: clamp(24px, 4vh, 44px);
  }

  .wordmark {
    display: inline-flex;
    align-items: center;
    gap: 20px;
    color: var(--text-primary);
  }

  .brand-copy { display: grid; gap: 5px; }

  .brand-copy strong {
    font-size: clamp(27px, 2.6vw, 40px);
    font-weight: 590;
    letter-spacing: -0.052em;
    line-height: 1;
  }

  .brand-copy small {
    color: var(--text-muted);
    font-family: 'Geist Mono', ui-monospace, monospace;
    font-size: 10px;
    letter-spacing: 0.035em;
  }

  .trust-status {
    display: inline-flex;
    align-items: center;
    gap: 9px;
    color: var(--text-secondary);
    font-family: 'Geist Mono', ui-monospace, monospace;
    font-size: 11px;
  }

  .trust-status i {
    width: 8px;
    height: 8px;
    border: 1px solid var(--path-github);
    border-radius: 50%;
    box-shadow: 0 0 0 4px rgba(88, 166, 255, 0.08);
  }

  main {
    display: grid;
    grid-template-columns: minmax(330px, 0.72fr) minmax(570px, 1.28fr);
    align-items: center;
    gap: clamp(48px, 7vw, 112px);
    min-height: calc(100vh - 220px);
    padding-block: clamp(24px, 4vh, 56px);
  }

  .introduction { max-width: 520px; }

  .signed-out {
    width: fit-content;
    margin: 0 0 24px;
    padding: 7px 11px;
    border-left: 2px solid var(--accent);
    background: var(--accent-subtle);
    color: var(--text-primary);
    font-size: 12px;
  }

  h1 {
    margin: 0;
    color: var(--text-primary);
    font-size: clamp(60px, 7.4vw, 112px);
    font-weight: 530;
    letter-spacing: -0.078em;
    line-height: 0.82;
  }

  .lead {
    max-width: 500px;
    margin: clamp(34px, 5vh, 54px) 0 0;
    color: var(--text-secondary);
    font-size: clamp(16px, 1.35vw, 20px);
    line-height: 1.58;
  }

  .sign-in-block {
    margin-top: 36px;
    padding: 22px 0;
    border-block: 1px solid var(--border-hairline);
  }

  .github-button {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    width: min(100%, 350px);
    min-height: 52px;
    padding-inline: 22px;
    border: 1px solid var(--accent);
    border-radius: 4px;
    background: var(--accent);
    color: var(--text-inverse);
    font-size: 14px;
    font-weight: 680;
    transition: background-color 140ms ease, border-color 140ms ease, transform 140ms ease;
  }

  .github-button:hover {
    border-color: var(--accent-hover);
    background: var(--accent-hover);
    transform: translateY(-1px);
  }

  .github-button svg { width: 20px; height: 20px; }

  .account-guidance {
    max-width: 440px;
    margin: 14px 0 0;
    color: var(--text-muted);
    font-size: 11px;
    line-height: 1.6;
  }

  .first-visit {
    max-width: 440px;
    margin: 10px 0 0;
    color: var(--text-secondary);
    font-size: 11px;
    line-height: 1.55;
  }

  .first-visit strong { color: var(--text-primary); font-weight: 600; }

  .assurance-points {
    display: grid;
    gap: 13px;
    margin: 28px 0 0;
  }

  .assurance-points div {
    display: grid;
    grid-template-columns: 70px 1fr;
    gap: 14px;
    align-items: baseline;
  }

  dt {
    color: var(--accent);
    font-family: 'Geist Mono', ui-monospace, monospace;
    font-size: 10px;
  }

  dd {
    margin: 0;
    color: var(--text-secondary);
    font-size: 12px;
  }

  .diagram { min-width: 0; }

  footer {
    display: flex;
    flex-wrap: wrap;
    gap: 10px 32px;
    padding-block: 24px 30px;
    border-top: 1px solid var(--border-hairline);
    color: var(--text-muted);
    font-family: 'Geist Mono', ui-monospace, monospace;
    font-size: 9px;
  }

  @media (max-width: 1120px) {
    main {
      grid-template-columns: minmax(300px, 0.8fr) minmax(500px, 1.2fr);
      gap: 42px;
    }

    h1 { font-size: clamp(56px, 7vw, 78px); }
  }

  @media (max-width: 900px) {
    main { grid-template-columns: 1fr; }
    .introduction { max-width: 620px; }
    .diagram { margin-top: 10px; }
  }

  @media (max-width: 600px) {
    .brand-header,
    main,
    footer { width: min(100% - 32px, 1500px); }
    .brand-header { align-items: flex-start; }
    .wordmark { gap: 13px; }
    .brand-copy small,
    .trust-status { display: none; }
    h1 { font-size: clamp(54px, 18vw, 76px); }
    .lead { margin-top: 30px; }
    main { gap: 26px; padding-top: 34px; }
    .github-button { width: 100%; }
    footer { display: grid; gap: 8px; }
  }

  @media (prefers-reduced-motion: reduce) {
    .github-button { transition: none; }
    .github-button:hover { transform: none; }
  }
</style>
