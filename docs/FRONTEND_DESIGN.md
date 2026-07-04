# Frontend Design: FR-Driven Traceability Dashboard

## Status

**Draft.** Companion to [FR_TRACEABILITY_PIVOT.md](FR_TRACEABILITY_PIVOT.md). That doc defines the data model and backend; this doc defines what the user sees and how they work with it. Backend Phase 1 implementation should be shaped by this design, not the other way round.

## Why this doc exists

Auditors don't care about JSON schemas or scanner parsers. They care about answering questions quickly: "Is this control covered?", "Show me the evidence", "What's at risk if this code changes?". The frontend is the product. Backend exists to serve it.

This doc fixes the UX before code lands, so the backend gets built once — to the right shape — instead of reactively.

## Information architecture

Top-level navigation, left to right:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ [Overview] [FR Catalog] [ASVS] [NIST 800-53] [Findings] [Graph] [Fix]   │
└─────────────────────────────────────────────────────────────────────────┘
```

**4 fixed tabs + one per framework in scope.** A project scoped to ASVS only sees 5 tabs total; a project with ASVS+NIST+PCI sees 7. Framework tabs appear dynamically based on the project's `scope` block.

| Tab | Purpose | Who lives here |
|---|---|---|
| **Overview** | Headline KPIs, scan metadata, quick orientation | Everyone (first stop) |
| **FR Catalog** | Project's functional requirements, hierarchical, with code/test/evidence counts | Engineers, product |
| **ASVS** (or whichever frameworks are in scope) | One tab per framework, compliance row state machine | Auditors, security |
| **NIST 800-53** | Same shape as ASVS tab, different framework | Auditors, security |
| **Findings** | All scanner findings, with "Find ASVS impact" button per row | Engineers (triage) |
| **Graph** | D3 traceability graph, entry-point driven | Auditors (walkthroughs), engineers (exploration) |
| **Fix** | Agent prompt for fixing findings | Engineers (action) |

**Tab visibility rules:**
- Overview, Findings, Fix: always visible
- FR Catalog: visible only when `--fr-catalog` was supplied
- Framework tabs (ASVS, NIST, etc.): one per framework in the project's `scope` block. Hidden if no FR catalog or framework not in scope.
- Graph: visible only when `--fr-catalog` was supplied (no FR data = no graph)

**Cross-tab navigation** — every tab can deep-link to every other tab via URL hash:

```
dashboard.html#asvs/row/v5.0.0-6.1.1                  ← jump to ASVS row
dashboard.html#fr/FR-AUTH-OAUTH                        ← jump to FR
dashboard.html#findings/filter/src/auth/oauth.ts       ← findings for a file
dashboard.html#graph/center/FR-AUTH-OAUTH?depth=3      ← graph centered on FR
```

Hash state survives refresh. Auditors send each other URLs that land exactly on the view they're discussing.

## Per-tab design

### Overview tab

Existing tab structure retained (scan metadata, severity panel, KPI tiles). **Add:**

- **Multi-framework Coverage KPIs** — one tile per framework in scope, each showing "X of Y in-scope rows satisfied (Z unaddressed, W N/A)"
- **FR Catalog KPI** — "N functional requirements, M with code references, K with test coverage"
- **Quick-link tiles** — "12 unaddressed ASVS rows" → click jumps to ASVS tab pre-filtered to amber

### FR Catalog tab

The project's requirements, rendered as a collapsible tree (matching the `parent` hierarchy):

```
▼ FR-AUTH — User authentication                              [12 files] [3 tests] [satisfies 4 rows]
  ▼ FR-AUTH-OAUTH — OAuth 2.0 login flow                     [2 files]  [5 tests] [satisfies 2 rows]
    • FR-AUTH-OAUTH-VERIFY — OAuth token verification        [1 symbol] [1 test]
  ▼ FR-AUTH-SESSION — Session management                     [3 files]  [4 tests]
  ▼ FR-AUTH-RATE — Rate limiting                             [1 file]   [2 tests]
▶ FR-EXPORT — Data export                                    [4 files]  [3 tests]
▶ FR-AUDIT — Audit logging                                   [8 files]  [6 tests]
```

Each row shows: status badge (active/draft/deprecated), category tag, code/test/satisfies counts. Click a row → expands detail panel with:

- Full description text
- `implemented_by` references (clickable to file viewer or graph)
- `verified_by` references (clickable to test results or scanner finding)
- `satisfies` references (clickable to framework tab)
- `evidence` artifacts (clickable to file)
- Owner, status

**Top filter bar:**
- Free-text search by FR ID or title
- Category dropdown (auto-populated)
- Status filter (active/draft/deprecated/proposed)
- "Show only FRs with coverage gaps" toggle (FRs with code but no tests, or with tests but no compliance rows)

### Per-framework Compliance Matrix tabs

One tab per framework in the project's `scope`. Each shows:

**Top:**
- Scope header: "ASVS L1+L2 · 253 in-scope rows"
- Summary tiles: satisfied / failed / unaddressed / not-applicable / out-of-scope counts
- ASVS Coverage KPI: "X of Y applicable covered"

**Filter bar:**
- Free-text search by row ID
- Chapter/family dropdown (auto-populated)
- Status filter (satisfied/failed/unaddressed/NA/out-of-scope)
- Level filter (L1/L2/L3 or framework-specific equivalent)
- Culprit location filter (file path or URL)

**Table:**
- Grouped by chapter/family (collapsible)
- Columns: traffic light | row ID | section | level | requirement (truncated) | satisfies FR count | CSV status
- Click row → expandable detail with FR claim, code references, test results, evidence

**State colours (4 + filtered):**
- 🟢 Satisfied (green fill)
- 🔴 Failed (red fill) — actual evidence failure
- 🟡 Unaddressed (amber fill) — coverage gap, in scope but no FR
- ⚪ N/A (diagonal-stripe grey) — explicitly out of scope with reason
- Greyed out — filtered by scope profile (hidden by default, toggle to show)

### Findings tab

Existing tab structure retained. **Add per-finding button:**

- **"Find ASVS impact"** — clicks → jumps to Graph tab with this finding centered, walks outward to FRs and compliance rows. Answers "what compliance rows are threatened by this finding?"

### Graph tab

The centerpiece. See dedicated section below.

### Fix tab

Existing tab. No changes.

## The Graph tab — full design

### Entry points (not a blank canvas)

When the user opens the Graph tab, they see a sidebar of entry points (not an empty graph). Five options match the five auditor workflows:

```
Graph entry points
─────────────────
[1] Prove a compliance row        → opens row picker
[2] Blast radius of a finding     → opens finding picker
[3] Show coverage gaps            → loads all unaddressed rows
[4] Walk through an FR            → opens FR picker
[5] Cross-framework equivalents   → opens row picker, highlights equivalents
```

Plus: a search box for direct node lookup by ID.

Selecting an entry point loads the relevant subgraph. The user is never staring at empty canvas wondering what to do.

### Visual encoding

| Encoding | Meaning |
|---|---|
| **Node colour (fill)** | Status: green=pass, red=fail, amber=unaddressed, grey=stale/filtered, NA pattern |
| **Node shape** | Type: circle=FR, square=file, diamond=test, hexagon=compliance row, triangle=scanner finding, star=evidence artifact |
| **Node size** | Criticality: compliance rows sized by level (L1 largest), FRs sized by activity (test count), files/tests uniform |
| **Node ring/halo** | "Needs attention" marker — adds a red dashed ring OUTSIDE the fill colour. Used for orphans, stale evidence, manual evidence missing. |
| **Edge colour** | Type, drawn from a distinct palette so edges don't blend with node fills: teal=satisfies, lavender=implements, gold=verified_by, slate=evidenced_by. (Node fills stay in the green/red/amber/grey status range; edges use a separate hue range so they're always visible against any node colour.) |
| **Edge style** | Strength: solid=high confidence (exact rule match, direct file ref), dashed=medium (glob match, scanner wildcard), dotted=low/manual (human-curated evidence, fallback patterns) |
| **Edge thickness** | Criticality: thicker for primary mappings (the FR's main implementation), thinner for secondary/tangential |

This two-layer encoding (fill + ring) preserves semantic information. Red fill always means "failed evidence". Red ring always means "needs attention for some other reason". Auditors can read both signals independently.

### Interactions

| Action | Result |
|---|---|
| **Click node** | Highlight full traceability chain in both directions (BFS). Dim unrelated nodes to 20% opacity. Show detail panel on the right. |
| **Click same node again** | Dismiss highlight. |
| **Click edge** | Highlight that edge's两端 nodes + dim others. Show edge metadata (type, strength, source) in detail panel. |
| **Double-click node** | Expand one level (load direct neighbours not yet rendered). |
| **Shift-click node** | Add to current selection (multi-select for comparison). |
| **Right-click node** | Context menu: "Show in [tab]", "Export chain as PDF", "Add annotation", "Find equivalents". |
| **Hover node** | Tooltip with: ID, title, status, satisfies/implemented/verified counts. |
| **Drag node** | Reposition. Persists in browser localStorage for this scan + user. |
| **Scroll/pinch** | Zoom. |
| **Drag canvas** | Pan. |

**Fan-out cap:** when a node has >10 connections (e.g. shared utility file), only the first 10 edges render. Banner shows "Showing 10 of 27 connections — click to expand all". Prevents hairballs.

**Audit mode toggle:** when enabled, locks the graph to a single compliance row + its chain. Prev/Next buttons step through the chain systematically (compliance row → FR → code → test → evidence → back). Designed for systematic walkthroughs without getting lost. Auto-disables "drag to reposition" to keep layout stable.

### Layout modes (switchable)

| Mode | When to use |
|---|---|
| **Force-directed** (default) | Exploration — let relationships determine position |
| **Hierarchical** | Audit walkthroughs — compliance rows at top, FRs below, code below that, tests at bottom. Top-down tree. |
| **Concentric** | Cross-framework equivalence — FRs in center, compliance rows around perimeter grouped by framework |
| **Sankey** | Flow visualisation — shows how many compliance rows each FR satisfies, how many files each FR claims |

Switch via toolbar dropdown. Mode persists per user in localStorage.

### Power features

| Feature | What it does | Persistence |
|---|---|---|
| **Annotations** | Click any node → "Add note". Free-text comment with reviewer name + date. | localStorage (browser) per scan + user. Phase 2 candidate: server-side. |
| **Filter presets** | Save current filter state as named preset ("ASVS L2 + only failing"). One-click recall. | localStorage per user. |
| **Deep-linking** | URL hash encodes current view (`#graph/center/<node>?depth=N&layout=force`). Send to colleague, they see exactly your view. | URL itself. |
| **Time travel** | Compare two scans. Highlight what changed: new findings pulse red on first appearance, newly-satisfied rows pulse green, stale evidence gets a clock icon. | Requires backend retention of historical scan data — see Backend Implications. |
| **Export** | PNG / SVG of current subgraph. PDF of full chain with evidence list and reviewer notes. Drop into audit report. | Downloads to user's machine. |
| **Keyboard nav** | `g` then `f` = jump to FR search; `/` = focus filter; `e` = export; `?` = help; arrows = navigate selection; Enter = expand. | Always available. |
| **Coverage heatmap** | Alternative view (not a graph) — chapter × framework grid showing % coverage per cell. Click a cell → filters the table view. | Always available as a separate sub-view. |

## Failure modes — empty, loading, error states

The doc so far describes happy paths. Real users hit failures. Each needs a defined UI:

**Empty states** (data is valid but absent):

| Situation | UI |
|---|---|
| FR Catalog tab, project has zero FRs | Friendly message: "No functional requirements defined. Add an FR to fr-catalog.json and rescan." Link to schema doc. |
| Framework tab, no FR catalog supplied | "Supply `--fr-catalog <path>` to enable the FR-driven view. Without it, this tab shows scanner-driven status only." |
| Framework tab, framework snapshot missing | "Framework snapshot for X not bundled in this image. Run scripts/build-mapping-sources.py --only X and rebuild." |
| Graph tab, no entry point selected | Sidebar of 5 entry points (default). Centre canvas shows "Pick an entry point or search for a node." |
| Graph subgraph, no nodes match | "No nodes match this filter. Try widening scope or clearing the search." |

**Loading states:**

| Operation | UI |
|---|---|
| Initial dashboard load (>500ms) | Skeleton screens per tab (grey placeholder boxes with subtle pulse). Avoid spinners — they feel slow. |
| Framework tab data parsing (>200ms) | Inline skeleton rows in the table. |
| Graph subgraph computation (>300ms) | Centre canvas shows "Building graph..." with a progress bar for large subgraphs. |

**Error states:**

| Failure | UI |
|---|---|
| JSON Schema validation failure | Red banner at top: "FR catalog invalid: [error message]. Fix and rescan." Dashboard still loads with other tabs functional. |
| Malformed JUnit XML | Amber banner on FR Catalog: "JUnit XML parse error: [details]. Test evidence unavailable for this scan." |
| Missing scanner output | Per-scanner row in Findings shows "output missing" badge. Doesn't break the dashboard. |
| D3 CDN unreachable | Graph tab shows: "Graph unavailable (offline). Other tabs work normally. Vendor the library for airgapped scans." Other tabs unaffected. |
| FR catalog references missing file | Per-reference inline warning: "⚠ docs/auth-design.md not found" with red ring on the FR node. |
| Stale FR catalog (code/test paths no longer exist) | Per-FR warning: "5 of 8 implemented_by paths no longer exist in the codebase. Update the FR catalog." |

The principle: **dashboard never fully fails.** Each failure is localised, explained, and actionable. The user always has something to look at.

## Mobile and responsive behaviour

Existing dashboard has mobile breakpoints. New tabs need explicit decisions:

| Tab | Mobile (≤760px) | Tablet (760-1100px) | Desktop (>1100px) |
|---|---|---|---|
| Overview | Stacked KPIs (3-col grid) | 4-col KPIs | 6-col KPIs |
| FR Catalog | Tree + collapsible detail panel (full width) | Same | Tree + side detail panel |
| Framework tabs | Table with horizontal scroll; filter bar collapses to hamburger | Filter bar visible | Filter bar visible |
| Findings | Existing behaviour | Existing | Existing |
| Graph | **"Use desktop to view graph" message.** D3 force layout is unusable on touch — too easy to mis-tap nodes, no hover state, gestures conflict with page scroll. | Limited: tap-to-select only, no drag-rearrange, no multi-select | Full features |
| Fix | Existing | Existing | Existing |

Graph tab on mobile is a deliberate non-feature. Auditors don't review on phones; engineers triaging on phones use the Findings tab. Saves implementation effort and avoids a broken UX.

## Time travel — comparing scans

Time travel lets auditors see what changed between two scans. Backend retention flagged (keep last 5 scans per project). The UX:

**Scan picker** (top of dashboard, dropdown):

```
[Scan: 2026-07-04 14:32 (latest) ▾]
  ─────────────────────────────────
   2026-07-04 14:32 (latest) ✓
   2026-07-03 09:20
   2026-07-02 11:29
   2026-07-01 18:46
  ─────────────────────────────────
   Compare two scans...    → opens comparison mode
```

**Comparison mode** (selected scan vs another):

- Side-by-side view OR overlay (toggle)
- Changes highlighted:
  - New findings: pulse red on first appearance
  - Newly-satisfied compliance rows: pulse green
  - Newly-N/A rows: amber flash with reason
  - Newly-failing rows: red flash with finding reference
  - Stale evidence (manual artifacts older than 90 days): clock icon
- Filter: "Show only changes" hides everything that didn't change between the two scans
- Export: PDF of the diff with explanations, drop into audit report

**FR catalog versioning:**

Each scan retains the FR catalog snapshot that was active at scan time, copied into the scan's report directory (`<report-dir>/fr-catalog.snapshot.json`). When comparing two scans:

- If FR definitions are identical → full time travel works (compare everything)
- If FRs were added/removed → those FRs flagged as "added in scan B" or "removed in scan B"; comparison still works for shared FRs
- If FR definitions changed (same ID, different content) → marked as "FR definition changed"; comparison shows old + new side-by-side for that FR

This means time travel works even when the project's FR catalog evolves. No "scans are incompatible" failures.

**Cross-scan navigation:**

Scan picker dropdown works in every tab. Switching scan reloads the current tab with that scan's data, preserving filter state. URL hash encodes the active scan: `dashboard.html?scan=20260704T1432Z#asvs/row/v5.0.0-6.1.1`.

## Visual design tokens

Existing dashboard palette retained. New tokens added:

```css
/* Traffic light fills */
--status-pass: #35d07f;
--status-fail: #ff4d6d;
--status-unaddressed: #ffd166;
--status-na: repeating-linear-gradient(45deg, #718096, #718096 4px, #3a4750 4px, #3a4750 8px);
--status-filtered: #2a343b;

/* Attention ring (separate from fill semantics) */
--attention-ring: #ff4d6d;  /* red dashed */
--attention-ring-stale: #ffd166;  /* amber dashed */

/* Node type shapes (SVG paths) */
--shape-fr: circle;
--shape-file: square;
--shape-test: diamond;
--shape-compliance: hexagon;
--shape-finding: triangle;
--shape-evidence: star;

/* Edge styles — distinct hue range from node fills to preserve visibility */
--edge-satisfies: #56c7b7;   /* teal */
--edge-implements: #b794f4;  /* lavender */
--edge-verified-by: #f6ad55; /* gold */
--edge-evidenced-by: #718096;/* slate */

/* Edge line styles — strength encoding */
--edge-strong: solid;       /* high confidence: exact rule match, direct file ref */
--edge-medium: dashed 4,2;  /* medium: glob match, scanner wildcard */
--edge-weak: dotted 2,3;    /* low/manual: human-curated, fallback patterns */
```

## Frontend engineering

### JavaScript architecture

Current dashboard uses inline `<script>` blocks (one per tab's logic). The pivot adds D3 + multi-tab state + filter persistence — inline becomes unmaintainable past ~1000 lines.

**Decision:** extract to a separate `dashboard.js` file (or `dashboard.mjs` for ES modules). The HTML generator emits a small bootstrap script that loads `dashboard.js` and passes the embedded JSON data via a `<script type="application/json">` block. No build step, no transpilation, no npm.

**Module structure:**
```
scripts/generate-dashboard.py        # generates HTML + embedded JSON
  ↓ emits
dashboard.html
  ├── <style>...</style>
  ├── <script type="application/json" id="dashboard-data">{...}</script>
  ├── <script src="assets/dashboard.js" defer></script>
  └── <script>bootstrap()</script>
```

`assets/dashboard.js` (~2000-3000 lines realistic; 1500 was optimistic) structured as:
```
dashboard.js
├── state/             # cross-tab state management
│   ├── filters.js
│   ├── selection.js
│   └── persistence.js  # localStorage
├── tabs/
│   ├── overview.js
│   ├── fr-catalog.js
│   ├── compliance-matrix.js  # parameterised by framework
│   ├── findings.js
│   └── graph.js
├── graph/
│   ├── render.js      # D3 force layout
│   ├── interactions.js
│   ├── layouts.js     # force, hierarchical, concentric, sankey
│   └── presets.js     # saved filter/view state
├── components/        # shared UI components
│   ├── traffic-light.js
│   ├── filter-bar.js
│   └── detail-panel.js
└── utils/
    ├── url-hash.js    # deep-linking
    ├── keyboard.js    # keyboard shortcuts
    └── export.js      # PNG/SVG/PDF
```

Vendoring D3: load from CDN (`https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js`) with a graceful fallback message if offline. Could vendor locally in Phase 6 if airgapped scans need it.

**JS bundle budget:** ~500KB total (D3 ~270KB + dashboard.js ~200KB + minor deps). CI checks bundle size on every PR; >10% increase requires reviewer sign-off. Prevents drift toward heavy dependencies.

**JS unit tests:** `tests/js/` directory with Vitest (fast, native ES module support). Coverage targets:
- `state/` modules: 90% (filter logic, selection, persistence — high-value logic)
- `utils/` modules: 80% (URL hash routing, keyboard, export)
- `graph/` modules: 60% (D3 interactions hard to unit test; integration-tested via snapshot)
- `tabs/` and `components/`: snapshot tests in `tests/fixtures/expected-*.html` cover regressions

### Cross-tab state

| State | Scope | Persistence |
|---|---|---|
| Active tab | Per session | URL hash |
| Active filter (per tab) | Per tab | URL hash + localStorage |
| Selected node/row | Per tab | URL hash |
| Filter presets | Per user | localStorage |
| Annotations | Per user per scan | localStorage |
| Custom node positions (graph) | Per user per scan | localStorage |

Switching tabs preserves per-tab filters (ASVS tab filter doesn't bleed into NIST tab). Returning to a tab restores its previous filter.

### Performance budget

| Operation | Target | Strategy |
|---|---|---|
| Initial dashboard load | <3s | Lazy-load per-tab JS; embed JSON data as compressed `<script>` block; render only the active tab |
| Compliance Matrix render (1000+ rows) | <1s | Virtualised table (only render visible rows); precomputed filter indices |
| Graph tab first paint | <1s | Entry-point picker renders instantly; subgraph loads on selection |
| Graph node click highlight | <100ms | BFS over precomputed adjacency list; CSS transitions for dim/highlight |
| Framework tab switch | <500ms | Pre-rendered table data per framework; CSS `display: none` for inactive tabs |

If targets aren't met, optimisations to try (in order):
1. Move JSON data to a separate `.json` file, fetch on tab activation
2. Web Worker for graph BFS
3. Precomputed adjacency indices for common queries
4. Pagination for very large compliance frameworks (NIST 800-53 has 1196 rows — paginate at 200)

### Accessibility

- **All traffic light states have aria-label text** ("fail", "manual", "pass", "no coverage", "not applicable"). Colour is never the sole signal.
- **NA vs filtered badges** have distinct text labels AND distinct visuals (diagonal stripe vs solid grey).
- **Table rows are keyboard-navigable** (`tab` moves between rows, `enter` expands). Filter controls reachable via keyboard.
- **Graph nodes are keyboard-navigable** — arrow keys move between connected nodes, Enter selects, Esc dismisses highlight. Visual focus indicator obvious.
- **Annotations and notes** are aria-live regions; screen readers announce updates.
- **No reliance on colour alone** anywhere — every status also has shape (graph) or text label (table).

### Snapshot tests

Snapshot test infrastructure (`tests/fixtures/sample-scan/` + `scripts/test_dashboard_snapshot.py`):
- One committed fixture scan with FR catalog, scanner outputs, JUnit XML
- Dashboard HTML generated from fixture on every test run
- Snapshot file (`tests/fixtures/expected-dashboard.html`) committed
- Test diffs current render against snapshot — any rendering regression fails CI
- Snapshot updates are explicit (`--update-snapshot` flag) and reviewed in PRs

Catches unintended changes: CSS regressions, tab visibility bugs, JS errors that break rendering.

## Backend implications (frontend features that drive backend work)

Each frontend feature implies specific backend support. Listing here so backend Phase 1+ plans can pick them up:

| Frontend feature | Backend implication |
|---|---|
| Time travel (compare scans) | Retain historical scan data, not just current. Need a scan archive structure. |
| Annotations | Persistence layer. localStorage OK for v1; server-side for shared annotations is Phase X. |
| Cross-framework equivalents | Derived view linking compliance rows that share FRs. Compute at scan time, embed in dashboard JSON. |
| Filter presets | Per-user state. localStorage only (no backend needed). |
| Deep-linking | URL hash routing — purely frontend, no backend. |
| Coverage heatmap | Per-chapter × per-framework coverage matrix. Compute at scan time, embed in JSON. |
| Audit mode step-through | Ordered traversal of compliance row's chain. Compute chain order at scan time. |
| Export to PDF | Server-side rendering if we want pixel-perfect; otherwise client-side jsPDF. Default client-side. |
| Findings "Find ASVS impact" | Reverse lookup from scanner finding rule_id → FRs with matching `verified_by: scanner` patterns. Compute at scan time. |

**Two backend additions worth flagging early:**
1. **Scan history retention** — keep last 5 scans per project (configurable). Each scan retains: `evidence-manifest.json`, `dashboard-data.json` (the embedded JSON), and `fr-catalog.snapshot.json` (the FR catalog at scan time). Time travel reads these. Comparison mode handles added/removed/changed FRs gracefully.
2. **Derived cross-framework index** — `data/derived/equivalences.json` computed at scan time, listing groups of `(framework, row)` tuples that share FRs. The Graph tab's "cross-framework equivalents" workflow reads this.

## Phased delivery

Frontend ships in slices, each independently useful. **MVP = Phases 1-2** (FR Catalog + at least one framework tab working end-to-end). Graph and power features build on that foundation.

| Phase | Frontend slice | Backend dependency |
|---|---|---|
| **1** (MVP) | FR Catalog tab + ASVS framework tab working end-to-end. Cross-tab deep-linking. Empty/loading/error states. Mobile responsive for non-graph tabs. | FR catalog parser + `--fr-catalog` flag + scanner integration into `verified_by` |
| **2** (MVP) | Findings "Find ASVS impact" button. Reverse lookup from finding → compliance rows. | Reverse lookup index |
| **3** | Additional framework tabs (NIST 800-53, etc.). Filter presets. Coverage heatmap on Overview. | Multi-framework loaders |
| **4** | Graph tab MVP: force-directed only, two entry points (FR picker, compliance row picker), click highlight, fan-out cap. Desktop-only. | None new — uses existing JSON data |
| **5** | Graph power features: hierarchical + concentric + Sankey layouts, audit mode, deep-linking to graph state, keyboard nav, PNG/SVG export | None new |
| **6** | Time travel: scan picker, comparison mode, FR catalog snapshot retention, diff highlighting | Scan history retention (keep last 5 scans) |
| **7** | Annotations (localStorage), PDF export, cross-framework equivalents view, coverage heatmap as standalone view | Derived cross-framework index |
| **8** | Polish: a11y pass full audit, snapshot test infrastructure, performance tuning against budgets, JS unit test coverage targets, light mode, print stylesheet | None |

**MVP definition:** Phases 1-2 deliver the irreducible core — a dashboard where an auditor can see their FRs, see their compliance coverage, and click a finding to see what it threatens. After Phase 2, the platform is genuinely useful even without the graph or time travel.

**Effort estimate:** MVP (1-2) is ~2-3 weeks. Full vision (3-8) is ~6-8 weeks additional. Total ~8-11 weeks of focused frontend work, parallel to backend phases where possible.

## Open decisions

1. **D3 version** — v7 (latest stable, broadest compatibility) vs v6 (smaller bundle). Default v7.
2. **Module format** — ES modules (`.mjs`, native browser support, no build step) vs IIFE (broader compat, no `type="module"` needed). Default ES modules.
3. **D3 vendored vs CDN.** CDN saves ~250KB from the image; vendor guarantees offline scans work. Default CDN with offline fallback message; revisit if airgapped audits need it.
4. **PDF export — client-side (jsPDF) vs server-side (puppeteer in image).** Client-side is simpler but lower fidelity. Default client-side; revisit if audit reports need pixel-perfect.
5. **Annotation persistence — localStorage vs IndexedDB.** localStorage is simpler, 5MB limit; IndexedDB scales but adds complexity. Default localStorage; revisit when annotation volume exceeds limits.

## Decision needed before proceeding

- ✅ Color = status, shape = type (decided)
- ✅ Red rings for "needs attention", red fill reserved for failures (decided)
- ✅ Initial graph view = entry-point picker, not blank canvas (decided)
- ✅ Fan-out cap with "showing N of M" expansion (decided)
- ✅ Audit mode toggle included (decided)

**No remaining blockers.** Phase 1 implementation (parser + flag + basic FR Catalog tab) can start.
