<script lang="ts">
  import { api } from '$lib/api';
  import { selectedProject } from '$lib/stores/selectedProject';
  import { pushToast } from '$lib/stores/toasts';
  import type { TrendCommits, TrendsResponse } from '$lib/types';

  let data: TrendsResponse | null = null;
  let commits: TrendCommits | null = null;
  let branch = '';
  let loading = false;
  let error: string | null = null;

  $: project = $selectedProject;

  const SERIES = [
    { key: 'CRITICAL', label: 'critical', color: 'var(--state-failed)' },
    { key: 'HIGH', label: 'high', color: '#e6823a' },
    { key: 'MEDIUM', label: 'medium', color: 'var(--state-waived)' },
    { key: 'tribal', label: 'tribal', color: 'var(--accent)' }
  ] as const;

  async function refresh(requestedBranch: string | null = branch || null) {
    if (!project) {
      data = null;
      commits = null;
      return;
    }
    loading = true;
    try {
      let nextData = await api.getTrends(project, 100, requestedBranch ?? undefined);
      const availableBranches = nextData.branches;
      if (!requestedBranch || !availableBranches.includes(requestedBranch)) {
        const latestBranch = nextData.runs[nextData.runs.length - 1]?.git_branch;
        branch = latestBranch || availableBranches[0] || '';
        if (branch) nextData = await api.getTrends(project, 100, branch);
      }
      data = nextData;
      error = null;
    } catch (e) {
      error = String(e);
    } finally {
      loading = false;
    }
  }

  $: branches = data?.branches ?? [];

  async function refreshCommits() {
    if (!project || !branch) {
      commits = null;
      return;
    }
    try {
      commits = await api.getTrendCommits(project, branch);
    } catch {
      commits = null;
    }
  }

  $: if (project) refresh(null);
  $: if (project && branch) refreshCommits();

  $: runs = data?.runs ?? [];

  // ---- shared time axis -------------------------------------------------
  const W = 860;
  const H = 300;
  const PAD_L = 42;
  const PAD_R = 12;
  const PAD_T = 12;
  const PAD_B = 24;

  function ts(iso: string | null): number {
    return iso ? new Date(iso).getTime() : 0;
  }

  $: times = runs.map((r) => ts(r.started_at)).filter((t) => t > 0);
  $: tMin = times.length ? Math.min(...times) : 0;
  $: tMax = times.length ? Math.max(...times) : 1;
  $: span = Math.max(1, tMax - tMin);
  $: xpos = (t: number) => (tMax === tMin ? W / 2 : PAD_L + ((t - tMin) / span) * (W - PAD_L - PAD_R));

  $: yMax = runs.length
    ? Math.max(4, ...runs.map((r) => Math.max(
        r.by_severity['CRITICAL'] ?? 0,
        r.by_severity['HIGH'] ?? 0,
        r.by_severity['MEDIUM'] ?? 0,
        r.tribal ?? 0)))
    : 4;
  $: ypos = (v: number) => H - PAD_B - (v / yMax) * (H - PAD_T - PAD_B);

  function valueOf(r: { by_severity: Record<string, number>; tribal?: number }, key: string): number {
    return key === 'tribal' ? (r.tribal ?? 0) : (r.by_severity[key] ?? 0);
  }

  function pathFor(key: string): string {
    return runs
      .map((r, i) => `${i === 0 ? 'M' : 'L'}${xpos(ts(r.started_at)).toFixed(1)},${ypos(valueOf(r, key)).toFixed(1)}`)
      .join(' ');
  }

  $: yTicks = [0, Math.round(yMax / 2), yMax];
  $: xLabels = (() => {
    const out: { at: number; label: string }[] = [];
    const step = Math.max(1, Math.floor(runs.length / 6));
    runs.forEach((r, i) => {
      if (i % step === 0 && r.started_at) {
        out.push({ at: xpos(ts(r.started_at)), label: r.started_at.slice(5, 10) });
      }
    });
    return out;
  })();

  // ---- commits strip ----------------------------------------------------
  const CH = 54;
  $: commitDays = commits?.days ?? [];
  $: commitMax = commitDays.length ? Math.max(1, ...commitDays.map((d) => d.count)) : 1;
  $: commitBars = commitDays.map((d, i) => ({
    x: PAD_L + (i / Math.max(1, commitDays.length - 1)) * (W - PAD_L - PAD_R),
    h: (d.count / commitMax) * (CH - 8),
    tip: `${d.date} · ${d.count} commits`
  }));

  let posting = false;

  async function postDigest() {
    posting = true;
    try {
      const res = await api.postNotionDigest();
      pushToast('success', `Notion updated — ${res.projects} projects, ${res.critical} critical, ${res.high} high`);
    } catch (e) {
      pushToast('error', `Notion post failed: ${e}`);
    } finally {
      posting = false;
    }
  }
</script>

<div class="p-6 max-w-5xl">
  <div class="flex items-center justify-between mb-5">
    <div>
      <div class="text-[15px] text-ink-primary mb-1">Trends</div>
      <div class="text-[12px] text-ink-secondary">
        {#if project}
          <span class="font-mono">project #{project}</span>
          <span class="text-ink-muted"> · findings over scan history{branch ? ` · ${branch}` : ''}</span>
        {:else}
          Select a project in the top bar to see its trends.
        {/if}
      </div>
    </div>
    <div class="flex items-center gap-2">
      {#if branches.length > 1}
        <select
          bind:value={branch}
          on:change={() => refresh(branch)}
          class="px-2 py-1 border border-line-strong rounded-sm bg-surface-elevated font-mono text-[11px] text-ink-primary"
        >
          {#each branches as b (b)}<option value={b}>{b}</option>{/each}
        </select>
      {/if}
      <button
        type="button"
        on:click={postDigest}
        disabled={posting}
        title="Repaint the configured Notion page with the standup digest"
        class="px-3 py-1.5 rounded-sm border border-line-strong bg-surface-elevated hover:bg-surface-base hover:border-accent text-[11px] font-mono uppercase tracking-[0.1em] text-ink-primary transition-colors disabled:opacity-50"
      >{posting ? 'Posting…' : 'Post standup digest'}</button>
    </div>
  </div>

  {#if !project}
    <div class="border border-line-hairline rounded-sm bg-surface-panel p-10 text-center text-[12px] text-ink-muted font-mono">
      no project in focus
    </div>
  {:else if loading && !data}
    <div class="text-[12px] text-ink-muted font-mono">Loading…</div>
  {:else if error}
    <div class="text-[12px] font-mono" style="color: var(--state-failed)">{error}</div>
  {:else if runs.length === 0}
    <div class="border border-line-hairline rounded-sm bg-surface-panel p-10 text-center text-[12px] text-ink-muted font-mono">
      no scans{branch ? ` on ${branch}` : ''} yet
    </div>
  {:else}
    <div class="border border-line-hairline rounded-sm bg-surface-panel p-4">
      <div class="flex items-center gap-4 mb-2 px-1">
        {#each SERIES as s (s.key)}
          <span class="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-muted">
            <span class="w-2.5 h-[2px]" style="background: {s.color}"></span>{s.label}
          </span>
        {/each}
      </div>
      <svg viewBox="0 0 {W} {H}" class="w-full" role="img" aria-label="Findings over scan history">
        {#each yTicks as t (t)}
          <line x1={PAD_L} x2={W - PAD_R} y1={ypos(t)} y2={ypos(t)} stroke="var(--line-hairline)" stroke-width="1" />
          <text x={PAD_L - 6} y={ypos(t) + 3} text-anchor="end" fill="currentColor" class="text-ink-muted" font-size="9" font-family="monospace">{t}</text>
        {/each}
        {#each xLabels as l (l.at)}
          <text x={l.at} y={H - 6} text-anchor="middle" fill="currentColor" class="text-ink-muted" font-size="9" font-family="monospace">{l.label}</text>
        {/each}
        {#each SERIES as s (s.key)}
          <path d={pathFor(s.key)} fill="none" stroke={s.color} stroke-width="1.8" stroke-linejoin="round" />
          {#each runs as r (r.run_id)}
            <circle
              cx={xpos(ts(r.started_at))}
              cy={ypos(valueOf(r, s.key))}
              r="2.6"
              fill={s.color}
            ><title>{r.started_at?.slice(0, 10)} · {s.key} {valueOf(r, s.key)} · {r.run_id.slice(-6)}</title></circle>
          {/each}
        {/each}
      </svg>
    </div>

    {#if commits && commits.days.length}
      <div class="border border-line-hairline rounded-sm bg-surface-panel p-4 mt-4">
        <div class="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-muted mb-2 px-1">
          commits — {commits.branch ?? ''} · last 30 days{commits.repo ? ` · ${commits.repo}` : ''}
        </div>
        <svg viewBox="0 0 {W} {CH + 14}" class="w-full" role="img" aria-label="Commits per day">
          {#each commitBars as b (b.tip)}
            <rect x={b.x - 4} y={CH - b.h} width="8" height={b.h} fill="var(--accent)" opacity="0.55" rx="1"><title>{b.tip}</title></rect>
          {/each}
          <line x1={PAD_L} x2={W - PAD_R} y1={CH} y2={CH} stroke="var(--line-hairline)" />
        </svg>
      </div>
    {/if}
  {/if}
</div>
