<script lang="ts">
  export let size = 72;
</script>

<svg
  class="mark"
  width={size}
  height={size}
  viewBox="0 0 72 72"
  role="img"
  aria-label="Assurance Scan"
>
  <path class="outer" d="M36 3 63.7 19v32L36 69 8.3 51V19Z" />
  <path class="facet facet-a" d="M36 11 56.8 23v24L36 59 15.2 47V23Z" />
  <path class="facet facet-b" d="M36 20 49 27.5v15L36 50l-13-7.5v-15Z" />
  <path class="scan" d="M18 36h10l5 5 10.5-12H54" />
  <circle cx="18" cy="36" r="2.5" />
  <circle cx="54" cy="36" r="2.5" />
</svg>

<style>
  .mark {
    display: block;
    overflow: visible;
    filter: drop-shadow(0 0 18px rgba(74, 222, 128, 0.16));
  }

  path,
  circle {
    fill: none;
    vector-effect: non-scaling-stroke;
  }

  .outer {
    stroke: var(--accent);
    stroke-width: 1.8;
  }

  .facet {
    stroke-width: 1;
  }

  .facet-a { stroke: var(--path-github); opacity: 0.7; }
  .facet-b { stroke: var(--path-local); opacity: 0.72; }

  .scan {
    stroke: var(--text-primary);
    stroke-width: 2.4;
    stroke-linecap: round;
    stroke-linejoin: round;
  }

  circle {
    fill: var(--bg-panel);
    stroke: var(--accent);
    stroke-width: 1.4;
  }
</style>
