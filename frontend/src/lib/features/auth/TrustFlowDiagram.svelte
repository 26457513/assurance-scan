<figure class="trust-map" aria-labelledby="trust-map-title">
  <div class="map-heading">
    <div>
      <h2 id="trust-map-title">One trust model. Two evidence paths.</h2>
      <p>Source stays where you choose. Verified results arrive in one assurance record.</p>
    </div>
    <span class="live-key"><i></i> verified flow</span>
  </div>

  <svg viewBox="0 0 760 445" role="img" aria-labelledby="flow-title flow-description">
    <title id="flow-title">GitHub and local scan trust workflow</title>
    <desc id="flow-description">
      Code can be pushed normally to a GitHub repository and scanned by GitHub Actions using OIDC,
      or scanned locally in an isolated signed container. Only local findings leave the machine.
      GitHub repository access determines which hosted results the user can see.
    </desc>

    <defs>
      <pattern id="grid" width="22" height="22" patternUnits="userSpaceOnUse">
        <path d="M22 0H0V22" fill="none" stroke="var(--border-hairline)" stroke-width="0.7" />
      </pattern>
      <marker id="arrow-blue" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M0 0 10 5 0 10Z" fill="var(--path-github)" />
      </marker>
      <marker id="arrow-green" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M0 0 10 5 0 10Z" fill="var(--accent)" />
      </marker>
      <marker id="arrow-amber" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M0 0 10 5 0 10Z" fill="var(--path-local)" />
      </marker>
    </defs>

    <rect class="grid" width="760" height="445" rx="10" />
    <rect class="local-boundary" x="24" y="246" width="476" height="174" rx="9" />
    <text class="boundary-label" x="42" y="272">Local security boundary · source never uploaded</text>

    <path class="route blue" d="M158 319 C172 238 184 160 245 130" marker-end="url(#arrow-blue)" />
    <path class="signal blue-signal" d="M158 319 C172 238 184 160 245 130" />
    <text class="route-label" x="112" y="220" transform="rotate(-61 112 220)">your normal push</text>

    <path class="route blue" d="M405 130 C490 130 512 153 565 205" marker-end="url(#arrow-blue)" />
    <path class="signal blue-signal delay-one" d="M405 130 C490 130 512 153 565 205" />
    <text class="route-label blue-copy" x="446" y="113">OIDC proof + results</text>

    <path class="route amber" d="M188 336H278" marker-end="url(#arrow-amber)" />
    <path class="signal amber-signal delay-two" d="M188 336H278" />

    <path class="route green" d="M448 336 C505 336 520 288 565 258" marker-end="url(#arrow-green)" />
    <path class="signal green-signal delay-three" d="M448 336 C505 336 520 288 565 258" />
    <text class="route-label green-copy" x="475" y="327">findings only</text>

    <g class="node github-node" transform="translate(245 79)">
      <rect width="160" height="102" rx="7" />
      <circle cx="27" cy="27" r="10" />
      <path class="github-glyph" d="M27 20.5a6.5 6.5 0 0 0-2.05 12.66c.33.06.45-.14.45-.32v-1.26c-1.82.4-2.2-.77-2.2-.77-.3-.76-.73-.96-.73-.96-.59-.4.05-.4.05-.4.65.05 1 .68 1 .68.58 1 1.52.7 1.9.54.05-.42.22-.71.41-.87-1.45-.16-2.98-.72-2.98-3.2 0-.72.26-1.3.68-1.74-.07-.17-.29-.83.06-1.72 0 0 .55-.18 1.79.67a6.2 6.2 0 0 1 3.24 0c1.24-.85 1.79-.67 1.79-.67.35.9.13 1.55.06 1.72.42.45.67 1.02.67 1.74 0 2.5-1.53 3.04-2.99 3.2.24.2.45.6.45 1.21v1.85c0 .18.12.38.45.32A6.5 6.5 0 0 0 27 20.5Z" />
      <text class="node-kicker" x="48" y="23">GitHub</text>
      <text class="node-title" x="18" y="60">Repository + Actions</text>
      <text class="node-detail" x="18" y="82">identity · permissions · OIDC</text>
    </g>

    <g class="node machine-node" transform="translate(42 292)">
      <rect width="146" height="88" rx="7" />
      <rect class="machine-screen" x="18" y="18" width="31" height="22" rx="2" />
      <path class="machine-screen" d="M13 47h41M26 40v7M41 40v7" />
      <text class="node-title" x="65" y="31">Local machine</text>
      <text class="node-detail" x="65" y="51">your branch</text>
      <text class="node-state amber-copy" x="18" y="70">CODE PRESENT</text>
    </g>

    <g class="node container-node" transform="translate(278 292)">
      <rect width="170" height="88" rx="7" />
      <path class="cube" d="m24 20 13-7 13 7v15l-13 8-13-8Zm0 0 13 8 13-8M37 28v15" />
      <text class="node-title" x="62" y="29">Signed container</text>
      <text class="node-detail" x="62" y="50">isolated local scan</text>
      <text class="node-state green-copy" x="18" y="70">SOURCE CONTAINED</text>
    </g>

    <g class="node assurance-node" transform="translate(565 174)">
      <path class="assurance-shell" d="M75 0 145 40v80l-70 40-70-40V40Z" />
      <path class="assurance-core" d="M75 29 120 55v50l-45 26-45-26V55Z" />
      <path class="assurance-check" d="m53 80 14 14 31-35" />
      <text class="assurance-title" x="75" y="184">Assurance Scan</text>
      <text class="assurance-detail" x="75" y="204">scoped evidence</text>
    </g>

    <g class="access-proof" transform="translate(533 50)">
      <path d="M0 26h113" />
      <circle cx="0" cy="26" r="4" />
      <circle cx="113" cy="26" r="4" />
      <text x="56" y="11">GitHub access decides what you see</text>
    </g>
  </svg>

  <div class="mobile-map" aria-label="GitHub and local evidence paths">
    <section class="mobile-lane github-lane">
      <h3>GitHub-hosted</h3>
      <div class="mobile-flow">
        <div class="mobile-node"><strong>Repository</strong><span>GitHub access</span></div>
        <i class="mobile-link blue-link" aria-hidden="true"></i>
        <div class="mobile-node"><strong>Actions</strong><span>OIDC proof</span></div>
        <i class="mobile-link blue-link delay-one" aria-hidden="true"></i>
        <div class="mobile-node destination"><strong>Assurance</strong><span>scoped results</span></div>
      </div>
    </section>

    <section class="mobile-lane local-lane">
      <h3>Local · source stays here</h3>
      <div class="mobile-flow">
        <div class="mobile-node"><strong>Machine</strong><span>your branch</span></div>
        <i class="mobile-link amber-link" aria-hidden="true"></i>
        <div class="mobile-node"><strong>Container</strong><span>isolated scan</span></div>
        <i class="mobile-link green-link delay-two" aria-hidden="true"></i>
        <div class="mobile-node destination"><strong>Assurance</strong><span>findings only</span></div>
      </div>
    </section>
  </div>

  <figcaption>
    <span><i class="github-dot"></i> GitHub-hosted: repository permissions + short-lived OIDC</span>
    <span><i class="local-dot"></i> Local: signed container + encrypted local credential</span>
  </figcaption>
</figure>

<style>
  .trust-map {
    min-width: 0;
    margin: 0;
    border: 1px solid var(--border-strong);
    border-radius: 12px;
    background: rgba(10, 11, 13, 0.82);
    box-shadow: 0 26px 80px rgba(0, 0, 0, 0.34);
    overflow: hidden;
  }

  .map-heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 24px;
    padding: 24px 26px 20px;
    border-bottom: 1px solid var(--border-hairline);
  }

  h2,
  p { margin: 0; }

  h2 {
    font-size: clamp(17px, 1.8vw, 23px);
    font-weight: 550;
    letter-spacing: -0.035em;
  }

  .map-heading p {
    max-width: 520px;
    margin-top: 7px;
    color: var(--text-secondary);
    font-size: 12px;
    line-height: 1.55;
  }

  .live-key {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    flex: none;
    color: var(--text-muted);
    font-family: 'Geist Mono', ui-monospace, monospace;
    font-size: 10px;
  }

  .live-key i {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 10px rgba(74, 222, 128, 0.7);
  }

  svg {
    display: block;
    width: 100%;
    height: auto;
  }

  .mobile-map { display: none; }

  .grid { fill: url(#grid); }

  .local-boundary {
    fill: rgba(251, 191, 36, 0.025);
    stroke: var(--path-local);
    stroke-width: 1;
    stroke-dasharray: 4 6;
    opacity: 0.64;
  }

  text { font-family: 'Geist', ui-sans-serif, sans-serif; }

  .boundary-label,
  .route-label,
  .node-kicker,
  .node-detail,
  .node-state,
  .assurance-detail,
  .access-proof text {
    font-family: 'Geist Mono', ui-monospace, monospace;
  }

  .boundary-label { fill: var(--path-local); font-size: 10px; opacity: 0.82; }
  .route-label { fill: var(--text-muted); font-size: 9px; }
  .blue-copy { fill: var(--path-github); }
  .green-copy { fill: var(--accent); }
  .amber-copy { fill: var(--path-local); }

  .route,
  .signal {
    fill: none;
    stroke-width: 1.5;
    stroke-linecap: round;
  }

  .route.blue { stroke: var(--path-github); opacity: 0.42; }
  .route.green { stroke: var(--accent); opacity: 0.45; }
  .route.amber { stroke: var(--path-local); opacity: 0.46; }

  .signal {
    stroke-dasharray: 2 18;
    stroke-width: 3;
    animation: evidence-flow 2.6s linear infinite;
  }

  .blue-signal { stroke: var(--path-github); }
  .green-signal { stroke: var(--accent); }
  .amber-signal { stroke: var(--path-local); }
  .delay-one { animation-delay: -0.65s; }
  .delay-two { animation-delay: -1.3s; }
  .delay-three { animation-delay: -1.95s; }

  .node > rect {
    fill: rgba(22, 24, 28, 0.97);
    stroke-width: 1;
  }

  .github-node > rect { stroke: rgba(88, 166, 255, 0.64); }
  .machine-node > rect { stroke: rgba(251, 191, 36, 0.58); }
  .container-node > rect { stroke: rgba(74, 222, 128, 0.6); }
  .github-node circle { fill: rgba(88, 166, 255, 0.12); stroke: var(--path-github); }
  .github-glyph { fill: var(--path-github); }
  .machine-screen,
  .cube { fill: none; stroke: var(--path-local); stroke-width: 1.3; stroke-linejoin: round; }
  .cube { stroke: var(--accent); }

  .node-kicker { fill: var(--path-github); font-size: 9px; }
  .node-title { fill: var(--text-primary); font-size: 12px; font-weight: 570; }
  .node-detail { fill: var(--text-secondary); font-size: 9px; }
  .node-state { font-size: 8px; letter-spacing: 0.09em; }

  .assurance-shell { fill: rgba(74, 222, 128, 0.035); stroke: var(--accent); stroke-width: 1.4; }
  .assurance-core { fill: var(--bg-panel); stroke: rgba(74, 222, 128, 0.43); }
  .assurance-check { fill: none; stroke: var(--text-primary); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
  .assurance-title { fill: var(--text-primary); font-size: 13px; font-weight: 600; text-anchor: middle; }
  .assurance-detail { fill: var(--accent); font-size: 9px; text-anchor: middle; }

  .access-proof path { fill: none; stroke: var(--path-github); stroke-width: 1; stroke-dasharray: 3 5; opacity: 0.68; }
  .access-proof circle { fill: var(--bg-inset); stroke: var(--path-github); }
  .access-proof text { fill: var(--path-github); font-size: 9px; text-anchor: middle; }

  figcaption {
    display: flex;
    flex-wrap: wrap;
    gap: 10px 24px;
    padding: 14px 26px 18px;
    border-top: 1px solid var(--border-hairline);
    color: var(--text-muted);
    font-size: 10px;
    line-height: 1.5;
  }

  figcaption span { display: inline-flex; align-items: center; gap: 7px; }
  figcaption i { width: 6px; height: 6px; border-radius: 50%; }
  .github-dot { background: var(--path-github); }
  .local-dot { background: var(--path-local); }

  @keyframes evidence-flow {
    to { stroke-dashoffset: -40; }
  }

  @keyframes mobile-evidence {
    from { left: -5px; }
    to { left: 100%; }
  }

  @media (max-width: 720px) {
    .map-heading { padding: 20px; }
    .live-key { display: none; }
    figcaption { padding-inline: 20px; }
  }

  @media (max-width: 560px) {
    svg { display: none; }

    .mobile-map {
      display: grid;
      gap: 14px;
      padding: 18px 16px;
      background-image:
        linear-gradient(rgba(255, 255, 255, 0.018) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, 0.018) 1px, transparent 1px);
      background-size: 22px 22px;
    }

    .mobile-lane {
      padding: 13px;
      border: 1px solid rgba(88, 166, 255, 0.42);
      border-radius: 7px;
      background: rgba(14, 15, 17, 0.9);
    }

    .local-lane {
      border-color: rgba(251, 191, 36, 0.42);
      border-style: dashed;
    }

    h3 {
      margin: 0 0 11px;
      color: var(--path-github);
      font-family: 'Geist Mono', ui-monospace, monospace;
      font-size: 9px;
      font-weight: 500;
    }

    .local-lane h3 { color: var(--path-local); }

    .mobile-flow {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 20px minmax(0, 1fr) 20px minmax(0, 1fr);
      align-items: center;
    }

    .mobile-node {
      display: grid;
      min-height: 58px;
      place-content: center;
      gap: 4px;
      padding: 8px 5px;
      border: 1px solid var(--border-strong);
      border-radius: 4px;
      background: var(--bg-panel);
      text-align: center;
    }

    .mobile-node strong {
      color: var(--text-primary);
      font-size: 10px;
      font-weight: 570;
    }

    .mobile-node span {
      color: var(--text-muted);
      font-size: 8px;
      line-height: 1.3;
    }

    .mobile-node.destination { border-color: rgba(74, 222, 128, 0.5); }

    .mobile-link {
      position: relative;
      display: block;
      height: 1px;
      overflow: hidden;
      background: var(--path-github);
      color: var(--path-github);
      opacity: 0.72;
    }

    .mobile-link::after {
      position: absolute;
      top: -1px;
      width: 5px;
      height: 3px;
      border-radius: 50%;
      background: currentcolor;
      box-shadow: 0 0 7px currentcolor;
      content: '';
      animation: mobile-evidence 1.8s linear infinite;
    }

    .amber-link {
      color: var(--path-local);
      background: var(--path-local);
    }

    .green-link {
      color: var(--accent);
      background: var(--accent);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .signal { animation: none; stroke-dasharray: 5 12; }
    .mobile-link::after { animation: none; }
  }
</style>
