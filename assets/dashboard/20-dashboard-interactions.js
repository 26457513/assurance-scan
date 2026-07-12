(function loadGraphLibrary() {
  const graphCanvas = document.getElementById('graph-canvas');
  if (!graphCanvas) return;
  let settled = false;
  const finish = () => {
    if (settled) return;
    settled = true;
    setupGraph();
    setupProcessFlow();
    setupGlobalContext();
  };
  const script = document.createElement('script');
  script.src = 'https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js';
  script.async = true;
  script.onload = finish;
  script.onerror = finish;
  document.head.appendChild(script);
  window.setTimeout(() => {
    if (!settled && script.parentNode) script.parentNode.removeChild(script);
    finish();
  }, 3000);
})();
let activeOverviewFilter = null;
let activeIssueTraceFilter = 'all';
function setOverviewFilter(filter, force) {
  const overview = document.querySelector('#tab-overview .overview-grid');
  if (!overview) return;
  const next = force ? filter : (activeOverviewFilter === filter ? null : filter);
  activeOverviewFilter = next;
  overview.dataset.activeFilter = next || '';
  document.querySelectorAll('[data-overview-section]').forEach(section => {
    if (section.dataset.overviewPersistent === 'true') {
      section.hidden = false;
      return;
    }
    section.hidden = Boolean(next) && section.dataset.overviewSection !== next;
  });
  document.querySelectorAll('[data-overview-group]').forEach(group => {
    const visibleChild = [...group.querySelectorAll('[data-overview-section]')].some(section => !section.hidden);
    group.hidden = Boolean(next) && !visibleChild;
  });
  document.querySelectorAll('[data-overview-filter]').forEach(action => {
    const selected = Boolean(next) && action.dataset.overviewFilter === next;
    action.classList.toggle('is-filtered', selected);
    action.setAttribute('aria-pressed', selected ? 'true' : 'false');
  });
}
function setIssueTraceFilter(filter) {
  activeIssueTraceFilter = filter || 'all';
  const isAll = activeIssueTraceFilter === 'all';
  document.querySelectorAll('[data-issue-trace-category]').forEach(row => {
    const matches = isAll || row.dataset.issueTraceCategory === activeIssueTraceFilter;
    row.hidden = !matches;
    if (!matches) {
      row.setAttribute('aria-expanded', 'false');
      row.classList.remove('is-selected');
      const detail = document.getElementById(row.dataset.findingToggle || '');
      if (detail) detail.hidden = true;
    }
  });
  document.querySelectorAll('[data-issue-trace-detail]').forEach(row => {
    const matches = isAll || row.dataset.issueTraceDetail === activeIssueTraceFilter;
    if (!matches) row.hidden = true;
  });
  document.querySelectorAll('.issue-summary-table').forEach(table => {
    const section = table.closest('[data-overview-section]');
    if (!section) return;
    const hasVisible = [...table.querySelectorAll('[data-issue-trace-category]')].some(row => !row.hidden);
    const overviewAllowsSection = !activeOverviewFilter || section.dataset.overviewSection === activeOverviewFilter;
    section.hidden = !hasVisible || !overviewAllowsSection;
  });
  document.querySelectorAll('[data-overview-persistent="true"]').forEach(section => {
    section.hidden = false;
  });
  document.querySelectorAll('[data-issue-trace-filter]').forEach(action => {
    const selected = action.dataset.issueTraceFilter === activeIssueTraceFilter;
    action.classList.toggle('is-filtered', selected);
    action.setAttribute('aria-pressed', selected ? 'true' : 'false');
  });
}
function showPanel(tabName) {
  document.body.dataset.activeTab = tabName;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  const btn = document.querySelector(`.tab-btn[data-tab="${tabName}"]`);
  if (btn) btn.classList.add('active');
  document.getElementById('tab-' + tabName).classList.add('active');
  if (tabName === 'graph' && window.asvsGraph && window.asvsGraph.renderCurrent) {
    window.asvsGraph.renderCurrent();
  }
  if (tabName === 'gateflow' && window.asvsProcessFlow && window.asvsProcessFlow.renderCurrent) {
    window.asvsProcessFlow.renderCurrent();
  }
  window.scrollTo({top: 0, behavior: 'smooth'});
}
document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => {
    showPanel(btn.dataset.tab);
    if (btn.dataset.tab === 'overview') setOverviewFilter('matrix', true);
  });
});
document.querySelectorAll('[data-overview-filter]').forEach(action => {
  function activateOverviewFilter() {
    const filter = action.dataset.overviewFilter;
    const wasActive = activeOverviewFilter === filter;
    showPanel('overview');
    if (!wasActive) setOverviewFilter(filter);
  }
  action.addEventListener('click', activateOverviewFilter);
  action.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      activateOverviewFilter();
    }
  });
});
setOverviewFilter('matrix', true);
document.querySelectorAll('[data-issue-trace-filter]').forEach(action => {
  function activateIssueTraceFilter() {
    showPanel('overview');
    setOverviewFilter('', true);
    setIssueTraceFilter(action.dataset.issueTraceFilter || 'all');
  }
  action.addEventListener('click', activateIssueTraceFilter);
  action.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      activateIssueTraceFilter();
    }
  });
});
document.querySelectorAll('[data-finding-toggle]').forEach(toggle => {
  function toggleFindingDetail(event) {
    if (event) event.stopPropagation();
    const row = document.getElementById(toggle.dataset.findingToggle);
    if (!row) return;
    const expanded = toggle.getAttribute('aria-expanded') === 'true';
    row.hidden = expanded;
    toggle.setAttribute('aria-expanded', expanded ? 'false' : 'true');
    toggle.classList.toggle('is-selected', !expanded);
  }
  toggle.addEventListener('click', toggleFindingDetail);
  toggle.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggleFindingDetail(event);
    }
  });
});
document.querySelectorAll('.evidence-row').forEach(row => {
  function toggleEvidenceDetail() {
    const detail = document.getElementById(row.dataset.evidenceDetail);
    if (!detail) return;
    const willOpen = detail.hidden;
    document.querySelectorAll('.evidence-row').forEach(item => {
      item.classList.toggle('is-selected', willOpen && item === row);
      item.setAttribute('aria-expanded', willOpen && item === row ? 'true' : 'false');
    });
    document.querySelectorAll('.evidence-detail-row').forEach(item => {
      item.hidden = true;
    });
    detail.hidden = !willOpen;
  }
  row.addEventListener('click', toggleEvidenceDetail);
  row.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggleEvidenceDetail();
    }
  });
});
function setupAssuranceTests() {
  const storageKey = `assurance-test-workflow:__RUN_ID__`;
  const nextStep = document.querySelector('.assurance-next-step');
  const commandEl = document.getElementById('assurance-next-command');
  const copyCommandBtn = document.getElementById('copy-assurance-command');
  const nextTitle = document.getElementById('assurance-next-title');
  const nextSubtitle = document.getElementById('assurance-next-subtitle');
  const nextMode = document.getElementById('assurance-next-mode');
  const pageTabs = [...document.querySelectorAll('[data-assurance-page-tab]')];
  const tabs = [...document.querySelectorAll('[data-assurance-state-tab]')];
  let activeState = 'map';
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(storageKey) || '{}') || {}; } catch (_) { saved = {}; }
  function shellQuote(value) {
    const text = String(value || '');
    if (!text) return "''";
    return "'" + text.replace(/'/g, "'\"'\"'") + "'";
  }
  function selectedDetail(input) {
    const row = input.closest('tr');
    if (!row || !row.dataset.assuranceTestDetail) return null;
    return document.getElementById(row.dataset.assuranceTestDetail);
  }
  function parseJsonList(value) {
    try {
      const parsed = JSON.parse(value || '[]');
      return Array.isArray(parsed) ? parsed.filter(Boolean) : [];
    } catch (_) {
      return [];
    }
  }
  function nativeSummaryFor(input) {
    return {
      pack_id: input.dataset.packId || input.dataset.nativePath || 'native-test',
      native_path: input.dataset.nativePath || '',
      pack_path: input.dataset.packPath || '',
      title: input.dataset.title || input.dataset.nativePath || input.dataset.packId || 'Native test',
      type: input.dataset.testType || 'test',
      source: input.dataset.source || '',
      status: input.dataset.status || '',
      assessment: input.dataset.assessment || '',
      test_names: parseJsonList(input.dataset.testNames)
    };
  }
  function mappingHypothesisFor(input) {
    const detail = selectedDetail(input);
    const controls = detail ? detail.querySelector('[data-map-controls]') : null;
    return {
      native_test: input.dataset.nativePath || input.dataset.packId || 'native-test',
      requested_operation: controls?.querySelector('[data-map-operation]')?.value || 'leave_unmapped',
      suggested_fr: controls?.querySelector('[data-map-fr]')?.value || '',
      suggested_tbt: controls?.querySelector('[data-map-tbt]')?.value || '',
      proposed_new_fr: controls?.querySelector('[data-map-new-fr]')?.value || '',
      proposed_new_tbt: controls?.querySelector('[data-map-new-tbt]')?.value || '',
      assessor_rationale: controls?.querySelector('[data-map-rationale]')?.value || '',
      confidence: controls?.querySelector('[data-map-confidence]')?.value || 'medium'
    };
  }
  function mapDecisionFor(input) {
    const detail = selectedDetail(input);
    const controls = detail ? detail.querySelector('[data-map-controls]') : null;
    const requestedOperation = controls?.querySelector('[data-map-operation]')?.value || 'leave_unmapped';
    const fr = controls?.querySelector('[data-map-fr]')?.value || '';
    const tbt = controls?.querySelector('[data-map-tbt]')?.value || '';
    const newFr = controls?.querySelector('[data-map-new-fr]')?.value || '';
    const newTbt = controls?.querySelector('[data-map-new-tbt]')?.value || '';
    const rationale = controls?.querySelector('[data-map-rationale]')?.value || 'Assessor hypothesis requires source inspection before this native test can be mapped.';
    const confidence = controls?.querySelector('[data-map-confidence]')?.value || 'medium';
    const native = nativeSummaryFor(input);
    let operation = requestedOperation;
    if (requestedOperation === 'map_native_test_to_existing_tbt' && (!fr || !tbt)) {
      operation = 'leave_unmapped';
    } else if (requestedOperation === 'create_tbt_under_existing_fr' && !fr) {
      operation = 'leave_unmapped';
    }
    const update = {
      operation,
      native_test: {
        pack_id: native.pack_id,
        native_path: native.native_path
      },
      review_status: 'proposed',
      source_basis: [
        {
          type: 'native_test',
          ref: native.native_path || native.pack_id
        }
      ],
      rationale,
      confidence
    };
    if (native.pack_path) update.native_test.pack_path = native.pack_path;
    if (native.test_names.length) update.native_test.test_names = native.test_names;
    if (operation === 'map_native_test_to_existing_tbt') {
      update.target = {fr, tbt};
    } else if (operation === 'create_tbt_under_existing_fr') {
      update.target = {fr};
      update.new_tbt = {
        id: newTbt || 'TBT-REVIEW-REQUIRED',
        title: 'Review required native-test TBT',
        type: native.type || 'test',
        evidence_policy: 'automated_required',
        proves: [fr],
        expected_evidence: ['JUnit testcase or equivalent execution evidence carrying the TBT id']
      };
    } else if (operation === 'create_new_fr_and_tbt') {
      update.new_fr = {
        id: newFr || 'FR-REVIEW-REQUIRED',
        title: 'Review required native-test FR',
        description: 'Assessor must define the functional requirement before applying this proposal.'
      };
      update.new_tbt = {
        id: newTbt || 'TBT-REVIEW-REQUIRED',
        type: native.type || 'test',
        title: 'Review required native-test TBT',
        evidence_policy: 'automated_required',
        proves: [newFr || 'FR-REVIEW-REQUIRED'],
        expected_evidence: ['JUnit testcase or equivalent execution evidence carrying the TBT id']
      };
    }
    return update;
  }
  function updateNextCommand() {
    if (!nextStep || !commandEl) return;
    function setPanel(title, subtitle, button) {
      if (nextTitle) nextTitle.textContent = title;
      if (nextSubtitle) nextSubtitle.textContent = subtitle;
      if (copyCommandBtn) copyCommandBtn.textContent = button;
    }
    const checked = [...document.querySelectorAll('[data-assurance-action]:checked')];
    const selectedStates = [...new Set(checked.map(input => input.dataset.state).filter(Boolean))];
    const requestedMode = nextMode?.value || 'auto';
    const promptState = requestedMode === 'auto'
      ? selectedStates.length === 1
        ? selectedStates[0]
        : activeState !== 'all'
          ? activeState
          : 'map'
      : requestedMode;
    const scopedChecked = checked.filter(input => input.dataset.state === promptState);
    if (!checked.length) {
      const hints = {
        all: 'Choose rows in the Workflow tab, then open TBT Prompts for the generated agent handoff.',
        map: 'Select native tests in the Workflow tab to generate a typed mapping prompt.',
        design: 'Select planned TBTs in the Workflow tab to generate a draft-test specification prompt.',
        approve: 'Select generated draft tests in the Workflow tab to generate the implementation/import prompt.',
        import: 'Select executed tests in the Workflow tab to generate an evidence import command.'
      };
      commandEl.textContent = hints[activeState] || hints.all;
      setPanel('TBT Prompts', 'Agent handoff generated from selected workflow rows', 'Copy prompt');
      return;
    }
    if (!scopedChecked.length) {
      const label = promptState.charAt(0).toUpperCase() + promptState.slice(1);
      commandEl.textContent = 'No selected ' + label + ' rows yet. Keep your existing selections, then select rows in the ' + label + ' workflow tab or change Prompt type.';
      setPanel('TBT Prompts: ' + label, 'Selections in other workflow tabs are preserved', 'Copy prompt');
      return;
    }
    const state = promptState;
    const sourceRepo = nextStep.dataset.sourceRepo || '/path/to/project';
    const sourceMount = nextStep.dataset.sourceMount || '/path/to';
    const frCatalog = nextStep.dataset.frCatalog || '/path/to/fr-catalog.json';
    const junitOutput = nextStep.dataset.junitOutput || '/path/to/approved-tbt-junit.xml';
    const reportDir = nextStep.dataset.reportDir || '/path/to/report';
    const assuranceTestPack = reportDir.replace(/\/$/, '') + '/generated-tests/VG_TEST_FRAMEWORK/manifest.json';
    const mappingProposalPath = reportDir.replace(/\/$/, '') + '/native-test-mapping-proposal.json';
    const mappingReviewPath = reportDir.replace(/\/$/, '') + '/native-test-mapping-review.md';
    const project = nextStep.dataset.project || 'target-project';
    const runId = nextStep.dataset.runId || '__RUN_ID__';
    const tbtList = scopedChecked.map(input => input.dataset.tbt).filter(Boolean).sort();
    const nativeList = scopedChecked.map(input => input.dataset.nativePath).filter(Boolean).sort();
    const dashboardScript = reportDir.replace(/\/reports\/[^/]+\/?$/, '/scripts/generate_dashboard.py');
    const dashboardRefreshCommand = 'python3 ' + shellQuote(dashboardScript) + ' --report-dir ' + shellQuote(reportDir);
    const dashboardHtml = reportDir.replace(/\/$/, '') + '/dashboard.html';
    const dashboardNavCheckCode = [
      'from pathlib import Path',
      'import re',
      'html = Path(' + JSON.stringify(dashboardHtml) + ').read_text(errors="ignore")',
      "tabs = re.findall(r'<button class=\"tab-btn\" data-tab=\"([^\"]+)\">', html)",
      'print("left view buttons:", len(tabs), tabs)',
      'raise SystemExit(0 if len(tabs) >= 7 else 1)'
    ].join('; ');
    const dashboardNavCheckCommand = 'python3 -c ' + shellQuote(dashboardNavCheckCode);
    function dashboardInspectionLines(kind) {
      const impact = {
        map: [
          '- Apply or save the accepted config update proposal through the config-update workflow.',
          '- Validate the proposal, render a human review brief, list selectable entries, then apply only reviewed selections to explicit reviewed output files.',
          '- Regenerate the current dashboard HTML for this same report using the exact refresh command below. Do not hand-edit dashboard.html or run a partial renderer.',
          '- Confirm mapped native tests no longer appear as unresolved Map rows, or remain explicitly review-required with rationale.'
        ],
        design: [
          '- Save the generated TBT specs/scaffolds into the report-local generated test pack.',
          '- Regenerate the current dashboard HTML for this same report.',
          '- Confirm selected TBTs move from Draft Tests for FR toward Review Agentic Tests, or remain blocked with assumptions recorded.'
        ],
        approve: [
          '- Save implemented approved tests under tests/asvs/ and update the report-local generated test pack metadata.',
          '- Regenerate the current dashboard HTML for this same report.',
          '- Confirm implemented tests are ready for Run Approved Tests and unresolved draft risks remain visible.'
        ],
        import: [
          '- Run the approved tests, then rerun the scan with the JUnit XML or supported evidence artifact imported.',
          '- Open the newly generated dashboard for that scan.',
          '- Confirm evidence changes are visible in Project FRs, Compliance Regime, Traceability Graph, and Evidence Files.'
        ]
      };
      return [
        '',
        'After completion: update and inspect dashboard impact',
        ...(impact[kind] || []),
        '- Inspect Project FR board lane counts, Project FR status, Compliance Regime status, Traceability Graph proof chain, and Evidence Files provenance.',
        '- Verify the left-side Views navigation still has all expected buttons; if the count drops, rerun the exact refresh command and do not report success.',
        '- Report what changed, which rows/TBTs/FRs moved state, and what remains blocked.',
        '',
        'Current-report dashboard refresh command, when no fresh scan is required:',
        dashboardRefreshCommand,
        '',
        'Post-refresh navigation sanity check:',
        dashboardNavCheckCommand
      ];
    }
    if (state === 'map') {
      setPanel('TBT Prompts', 'Agent handoff for typed native-test mapping', 'Copy mapping prompt');
      const nativeSummaries = scopedChecked.map(nativeSummaryFor);
      const mappingHypotheses = scopedChecked.map(mappingHypothesisFor);
      const nativeUpdates = scopedChecked.map(mapDecisionFor);
      const proposal = {
        schema_version: 1,
        mode: 'config_update_proposal',
        project,
        run_id: runId,
        source_inputs: [
          {path: 'fr-catalog.snapshot.json', kind: 'fr_catalog', used_for: 'Existing FR/TBT choices for native test mapping'},
          {path: 'generated-tests/VG_TEST_FRAMEWORK/manifest.json', kind: 'assurance_test_pack', used_for: 'Native test candidates requiring mapping'}
        ],
        fr_catalog_updates: [],
        compliance_mapping_pack_updates: [],
        assurance_framework_or_instance_updates: [],
        manual_evidence_updates: [],
        native_test_mapping_updates: nativeUpdates,
        uncertain_mappings: nativeUpdates
          .filter(update => update.operation === 'leave_unmapped' || update.operation === 'mark_not_assurance_relevant' || update.confidence === 'low')
          .map(update => ({
            kind: 'native_test_mapping',
            refs: [update.native_test.native_path || update.native_test.pack_id],
            candidates: [update.target?.fr, update.target?.tbt].filter(Boolean),
            question: 'Which FR/TBT, if any, does this native test actually prove after source inspection?',
            why: 'Native test mappings are assessor hypotheses until the test source and generated manifest context show a clear proof relationship.'
          })),
        review_required: [
          {
            item: 'native-test-mapping',
            question: 'Do the selected native tests really prove the proposed FR/TBT targets?',
            why: 'Native tests must be mapped by assessor review before they can become assurance evidence.'
          }
        ]
      };
      commandEl.textContent = [
        'Assurance Config Update Prompt',
        '',
        'Mission:',
        'Review the selected native test evidence and produce a typed config update proposal that maps each native test to the correct FR/TBT assurance chain.',
        '',
        'Context:',
        '- Project: ' + project,
        '- Scan run: ' + runId,
        '- Source repository: ' + sourceRepo,
        '- FR catalog: ' + frCatalog,
        '- Assurance test manifest: ' + reportDir + '/generated-tests/VG_TEST_FRAMEWORK/manifest.json',
        '- Copied/imported native tests are under: ' + reportDir + '/generated-tests/VG_TEST_FRAMEWORK/',
        '- Selected native tests: ' + (nativeList.join(', ') || 'none'),
        '',
        'Selected native-test manifest context:',
        JSON.stringify(nativeSummaries, null, 2),
        '',
        'Assessor hypotheses from the Map tab:',
        JSON.stringify(mappingHypotheses, null, 2),
        '',
        'Rules:',
        '1. Do not modify application source code.',
        '2. Do not invent product behaviour, endpoints, roles, data shapes, or evidence.',
        '3. Treat any selected FR/TBT or new FR/TBT id as an assessor hypothesis, not an accepted mapping.',
        '4. Inspect each selected native test source file and the generated test manifest before accepting, changing, or rejecting a mapping.',
        '5. Prefer mapping to an existing FR/TBT only when the test behaviour clearly proves that target.',
        '6. If the suggested target is wrong but another existing FR/TBT fits, propose that better existing target and explain the mismatch.',
        '7. Create a new TBT under an existing FR only when the FR is correct but no current TBT captures the evidence type.',
        '8. Create a new FR only when the native test proves a real product requirement that is absent from the catalog.',
        '9. Use leave_unmapped or mark_not_assurance_relevant when the proof relationship is unclear or absent.',
        '10. Preserve provenance: cite native path, copied pack path, manifest case names, rationale, confidence, and assumptions.',
        '11. Do not return the placeholder rationale unchanged. Every selected native test must end with a post-inspection disposition and a specific rationale.',
        '',
        'Expected output:',
        '- Return one JSON document matching config-update-proposal.schema.json.',
        '- Keep all ids stable and type-safe: FR ids use FR-xxx; TBT ids use TBT-xxx.',
        '- For new FR proposals include at minimum id, title, description, status/category if known, and the source basis.',
        '- For new TBT proposals include at minimum id, title, type, proves, evidence_policy, expected_evidence, and how JUnit or equivalent evidence will carry the TBT id.',
        '- Include review_required entries for every non-obvious or low-confidence mapping.',
        '- Return the JSON in the response and save the same JSON to the report-local proposal path below so the dashboard can display recommendations before any mapping is accepted.',
        '- Proposal path: ' + mappingProposalPath,
        '- Review brief path: ' + mappingReviewPath,
        '',
        'Draft proposal to review and refine:',
        '',
        JSON.stringify(proposal, null, 2),
        '',
        'Validation command:',
        'asvs-scanner validate-config-update ' + shellQuote(mappingProposalPath) + ' --fr-catalog ' + shellQuote(frCatalog),
        '',
        'Review and apply commands after validation:',
        'asvs-scanner review-config-update ' + shellQuote(mappingProposalPath) + ' --output ' + shellQuote(mappingReviewPath),
        'asvs-scanner apply-config-update ' + shellQuote(mappingProposalPath) + ' --list',
        'asvs-scanner apply-config-update ' + shellQuote(mappingProposalPath) + ' --select <section:index> --reviewed-by <name> --assurance-test-pack ' + shellQuote(assuranceTestPack) + ' --assurance-test-pack-out ' + shellQuote(assuranceTestPack),
        'For current-dashboard inspection, the assurance-test-pack output above intentionally replaces this report-local manifest after validation and human-reviewed selection.',
        'If selected entries affect other sections, add the matching reviewed input/output flags, such as --fr-catalog/--fr-catalog-out, --compliance-mapping-pack/--compliance-mapping-pack-out, --assurance-test-pack/--assurance-test-pack-out, or --assurance-instance/--assurance-instance-out.',
        ...dashboardInspectionLines('map')
      ].join('\n');
    } else if (state === 'design') {
      setPanel('TBT Prompts', 'Agent handoff to create FR/TBT draft tests', 'Copy create-tests prompt');
      commandEl.textContent = [
        'Assurance Test Specification Prompt',
        '',
        'Mission:',
        'Generate review-required draft tests/specifications for the selected planned TBTs by inspecting the project source and existing test patterns. This is a specification step only; it must not claim evidence, create ready-to-run tests, or modify product behaviour.',
        '',
        'Context:',
        '- Project: ' + project,
        '- Scan run: ' + runId,
        '- Report directory: ' + reportDir,
        '- FR catalog: ' + frCatalog,
        '- Selected TBTs: ' + (tbtList.join(', ') || 'none'),
        '- Existing test conventions: inspect package scripts, Jest/Vitest or integration-test config, existing tests, relevant application code, and runtime configuration before drafting.',
        '',
        'Rules:',
        '1. Use the FR catalog and report artifacts as the source of truth.',
        '2. Generate only review-required draft tests/specifications for the selected TBTs.',
        '3. Do not implement broad test suites or invent product endpoints, roles, data shapes, or expected behaviour.',
        '4. Prefer safe, non-destructive tests using disposable fixtures or mocks.',
        '5. Every generated draft test must keep the TBT id in the file name, test title, and future JUnit classname or testcase name.',
        '6. Mark each draft test as review_required until a human approves it. Skipped scaffolds are review artifacts, not executable assurance evidence.',
        '7. Do not count generated draft tests as passing evidence.',
        '8. Use tests/asvs/ as the ASVS-owned execution surface for generated tests and wrappers; do not duplicate existing native tests there unless writing a reviewed wrapper.',
        '9. Inspect the real implementation before drafting. If the codebase cannot currently support the FR/TBT behaviour, do not invent a test; report that the FR/TBT is not currently supported by observable project behaviour.',
        '10. If only part of the FR/TBT is supportable, create a review-required draft only for the observable portion and explicitly list the unsupported portions. Do not let a partial draft imply full FR/TBT coverage.',
        '11. For each selected TBT, report one disposition: draft_created_full, draft_created_partial_support, blocked_unsupported_by_project, blocked_insufficient_source_evidence, or blocked_needs_human_decision.',
        '',
        'Expected output:',
        '- Generate/update only the selected draft test files under the generated test pack, using tests/asvs/<type>/<TBT-ID>.assurance.test.js, for example tests/asvs/integration/TBT-016-ASVS-A.assurance.test.js.',
        '- Preserve provenance back to FR/TBT/ruleset rows.',
        '- Include the per-TBT disposition in the scaffold/spec metadata and in the final response.',
        '- Summarize inspected files, assumptions, unknowns, and any project-support gap that requires human review.',
        '- If unsupported, do not run promote-assurance-specs for that TBT. Persist or propose a blocked board-state update with lane=blocked, decision=blocked, and reviewer_note explaining the missing observable behaviour.',
        '- After draft tests are generated, rerun or refresh the dashboard to move supportable drafts into Review Agentic Tests.',
        '',
        'Blocked-state persistence when no scaffold should be generated:',
        '- Write or update project-fr-board-state.json through update-project-fr-board-state using the selected card id.',
        '- Keep source, tbt, frs, type, status, assessment, safety, pack_path, and discovery_rationale from the selected card.',
        '- Set lane to blocked, decision to blocked, and reviewer_note to the disposition plus the inspected-source reason.',
        '- Refresh the dashboard after saving the board state so the blocked reason is visible in the current report.',
        'Command template after writing blocked-board-state.json:',
        'asvs-scanner update-project-fr-board-state ' + shellQuote(reportDir) + ' --state-json blocked-board-state.json --strict --refresh-dashboard',
        '',
        'Command to generate selected draft tests only after source inspection confirms the FR/TBT is supportable:',
        'asvs-scanner promote-assurance-specs ' + shellQuote(reportDir) + ' \\',
        ...tbtList.map((tbt, idx) => '  --tbt ' + shellQuote(tbt) + (idx === tbtList.length - 1 ? '' : ' \\')),
        ...dashboardInspectionLines('design')
      ].join('\n');
    } else if (state === 'approve') {
      setPanel('TBT Prompts', 'Agent handoff to implement approved draft tests', 'Copy implementation prompt');
      commandEl.textContent = [
        'Approved Assurance Test Implementation Prompt',
        '',
        'Mission:',
        'Implement only the selected human-approved assurance draft tests so they become executable ASVS-owned tests. This step creates runnable tests; it must not claim evidence or import results.',
        '',
        'Context:',
        '- Project: ' + project,
        '- Source repository: ' + sourceRepo,
        '- Report directory: ' + reportDir,
        '- FR catalog: ' + frCatalog,
        '- Approved TBTs: ' + (tbtList.join(', ') || 'none'),
        '- Future JUnit output when the Run Approved Tests lane is used: ' + junitOutput,
        '',
        'Rules:',
        '1. Implement only selected generated draft tests that have been explicitly approved for implementation.',
        '2. Do not invent product endpoints, behaviour, roles, or data shapes.',
        '3. Use disposable fixtures and a safe/containerized test environment.',
        '4. Keep the TBT id in the file name, test title, and JUnit classname or testcase name.',
        '5. Do not modify product/application behaviour. Limit changes to ASVS-owned tests, wrappers, fixtures, mocks, or test harness configuration.',
        '6. Do not run destructive operations against real data or shared services.',
        '7. Keep ASVS-owned executable tests and wrappers under tests/asvs/; native project tests remain source-of-truth in their original paths.',
        '8. A selected card may still show review_required/needs_design at the start of this prompt. If it has decision: approve_for_implementation, treat that as human approval to implement only the approved scope.',
        '9. If a selected card lacks decision: approve_for_implementation or an explicit reviewer approval note, do not implement it; report the blocker instead.',
        '10. Remove describe.skip, test.skip, TODO(review-required), and review-only blockers only for the approved TBT scope. Preserve blocked notes for unsupported FR/TBT behaviour.',
        '11. Do not export or import JUnit evidence in this step; evidence belongs to the Run Approved Tests lane after the implemented test is reviewed as runnable.',
        '',
        'Expected output:',
        '- Implement the selected draft tests only under tests/asvs/ in the ASVS branch/worktree.',
        '- Update the report-local generated test pack metadata so implemented tests use status: ready_to_run, assessment: useful_as_is, and safety: non_destructive. Do not use status: executed until observed result evidence exists.',
        '- Run only lightweight local validation if needed to prove the test harness is wired; do not treat that as assurance evidence.',
        '- Report implemented tests, skipped/unimplemented tests, assumptions, and any manual follow-up.',
        '- Regenerate the current dashboard so implemented tests can move to Run Approved Tests.',
        '',
        'Selected rows/cards must include human approval:',
        '- Preferred review decision: approve_for_implementation.',
        '- If approval is only recorded in reviewer_note, cite it in the final report.',
        '- If no selected card is approved, stop and report that there is nothing safe to implement.',
        ...dashboardInspectionLines('approve')
      ].join('\n');
    } else if (state === 'import') {
      setPanel('Run Approved Tests', 'Fast isolated test run or full fresh scan', 'Copy command');
      const reportJunit = reportDir.replace(/\/$/, '') + '/reports/junit.xml';
      const runnerLines = [
        'docker run --rm -it \\',
        '  -v /var/run/docker.sock:/var/run/docker.sock \\',
        '  -v ' + shellQuote('/Users/jd/Development/asvs-scanner') + ':' + shellQuote('/opt/asvs-scanner') + ' \\',
        '  -v ' + shellQuote(sourceMount) + ':' + shellQuote(sourceMount) + ' \\',
        '  -w ' + shellQuote(sourceRepo) + ' \\',
        '  asvs-scanner:local run-approved-tests ' + shellQuote(reportDir) + ' \\',
        '  --source-repo ' + shellQuote(sourceRepo) + ' \\',
        '  --execution-mode docker \\',
        '  --test-container-image ' + shellQuote('node:20') + ' \\',
        '  --junit-out ' + shellQuote(reportJunit) + (tbtList.length ? ' \\' : '')
      ];
      tbtList.forEach((tbt, idx) => runnerLines.push('  --tbt ' + shellQuote(tbt) + (idx === tbtList.length - 1 ? '' : ' \\')));
      const refreshLines = [
        'docker run --rm -it --entrypoint python3 \\',
        '  -v /var/run/docker.sock:/var/run/docker.sock \\',
        '  -v ' + shellQuote('/Users/jd/Development/asvs-scanner') + ':' + shellQuote('/opt/asvs-scanner') + ' \\',
        '  -v ' + shellQuote(sourceMount) + ':' + shellQuote(sourceMount) + ' \\',
        '  -w ' + shellQuote(sourceRepo) + ' \\',
        '  asvs-scanner:local /opt/asvs-scanner/scripts/refresh-approved-test-evidence.py ' + shellQuote(reportDir) + ' \\',
        '  --junit-xml ' + shellQuote(reportJunit)
      ];
      const scanLines = [
        'docker run --rm -it \\',
        '  -e ASVS_IMAGE_BUILD_PARALLELISM=2 \\',
        '  -e ASVS_PARALLELISM=4 \\',
        '  -v /var/run/docker.sock:/var/run/docker.sock \\',
        '  -v ' + shellQuote(sourceMount) + ':' + shellQuote(sourceMount) + ' \\',
        '  -w ' + shellQuote(sourceRepo) + ' \\',
        '  asvs-scanner:local scan ' + shellQuote(sourceRepo) + ' \\',
        '  --fr-catalog ' + shellQuote(frCatalog) + ' \\',
        '  --junit-xml ' + shellQuote(reportJunit)
      ];
      const fastLines = runnerLines.slice();
      if (fastLines.length) fastLines[fastLines.length - 1] += ' && \\';
      commandEl.textContent = [
        'Run Approved Tests',
        '',
        'Fast path: run selected tests only and refresh this report',
        '',
        'This updates Project FRs, Compliance Regime, Traceability Graph, and Evidence Files from the selected test JUnit without rerunning the full scanner set.',
        '',
        ...fastLines,
        ...refreshLines,
        '',
        'Fresh scan path: run selected tests, then import the same JUnit into a new full scanner report',
        '',
        'Use this when you want a new immutable scan report and refreshed scanner outputs. Browser-only Kanban state will reset because this creates a new report.',
        '',
        ...scanLines,
        '',
        'The runner refuses non-ready tests and skipped scaffolds.'
      ].join('\n');
    } else {
      setPanel('TBT Prompts / command', 'No action generator for this state yet', 'Copy next step');
      commandEl.textContent = 'No automated next action is available for the selected workflow state yet.';
    }
  }
  function persist() {
    const next = {};
    document.querySelectorAll('[data-assurance-action]').forEach(input => {
      if (input.checked) next[input.dataset.assuranceAction] = true;
      const row = input.closest('tr');
      if (row) row.classList.toggle('is-approved', input.checked);
    });
    localStorage.setItem(storageKey, JSON.stringify(next));
    updateNextCommand();
  }
  document.querySelectorAll('[data-assurance-action]').forEach(input => {
    input.checked = Boolean(saved[input.dataset.assuranceAction]);
    const row = input.closest('tr');
    if (row) row.classList.toggle('is-approved', input.checked);
    input.addEventListener('click', event => event.stopPropagation());
    input.addEventListener('change', persist);
  });
  document.querySelectorAll('[data-map-fr]').forEach(frSelect => {
    const controls = frSelect.closest('[data-map-controls]');
    const tbtSelect = controls?.querySelector('[data-map-tbt]');
    if (!tbtSelect) return;
    function filterTbts() {
      const fr = frSelect.value || '';
      let firstVisible = '';
      [...tbtSelect.options].forEach(option => {
        const matches = !option.value || !fr || option.dataset.fr === fr;
        option.hidden = !matches;
        if (matches && option.value && !firstVisible) firstVisible = option.value;
      });
      if (tbtSelect.value && tbtSelect.selectedOptions[0]?.hidden) {
        tbtSelect.value = firstVisible || '';
      }
      updateNextCommand();
    }
    frSelect.addEventListener('change', filterTbts);
    filterTbts();
  });
  document.querySelectorAll('[data-map-controls] select, [data-map-controls] input, [data-map-controls] textarea').forEach(control => {
    control.addEventListener('input', updateNextCommand);
    control.addEventListener('change', updateNextCommand);
  });
  if (copyCommandBtn && commandEl) {
    copyCommandBtn.addEventListener('click', () => {
      const text = commandEl.textContent || '';
      if (!text || text.startsWith('Select one')) return;
      if (navigator.clipboard) navigator.clipboard.writeText(text).catch(() => {});
    });
  }
  if (nextMode) nextMode.addEventListener('change', updateNextCommand);
  pageTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.assurancePageTab || 'workflow';
      pageTabs.forEach(item => item.classList.toggle('active', item === tab));
      document.querySelectorAll('[data-assurance-page-pane]').forEach(pane => {
        pane.classList.toggle('active', pane.dataset.assurancePagePane === target);
      });
      updateNextCommand();
    });
  });
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      activeState = tab.dataset.assuranceStateTab || 'all';
      tabs.forEach(item => item.classList.toggle('active', item === tab));
      document.querySelectorAll('.assurance-test-row').forEach(row => {
        row.hidden = activeState !== 'all' && row.dataset.assuranceState !== activeState;
        const detail = document.getElementById(row.dataset.assuranceTestDetail);
        if (detail) detail.hidden = true;
      });
      updateNextCommand();
    });
  });
  document.querySelectorAll('.assurance-test-row').forEach(row => {
    function toggleDetail(event) {
      if (event && event.target && event.target.closest('[data-assurance-action]')) return;
      const detail = document.getElementById(row.dataset.assuranceTestDetail);
      if (!detail) return;
      const willOpen = detail.hidden;
      document.querySelectorAll('.assurance-test-row').forEach(item => {
        item.classList.toggle('is-selected', willOpen && item === row);
        item.setAttribute('aria-expanded', willOpen && item === row ? 'true' : 'false');
      });
      document.querySelectorAll('.assurance-test-detail-row').forEach(item => {
        item.hidden = true;
      });
      detail.hidden = !willOpen;
    }
    row.addEventListener('click', toggleDetail);
    row.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        toggleDetail(event);
      }
    });
  });
  updateNextCommand();
}
setupAssuranceTests();
function setupManualChecklist() {
  const scoreEl = document.getElementById('assurance-score');
  document.querySelectorAll('.manual-checklist').forEach(list => {
    const checks = [...list.querySelectorAll('[data-manual-check]')];
    if (!checks.length) return;
    const scope = list.dataset.manualScope || 'asvs';
    const storageKey = `manual-checks:${scope}:__RUN_ID__`;
    const progressEl = list.querySelector('.manual-progress');
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(storageKey) || '{}') || {}; } catch (_) { saved = {}; }
    if (Object.keys(saved).length) {
      checks.forEach(input => { input.checked = Boolean(saved[input.dataset.manualCheck]); });
    }
    function persist() {
      const next = {};
      checks.forEach(input => { if (input.checked) next[input.dataset.manualCheck] = true; });
      localStorage.setItem(storageKey, JSON.stringify(next));
    }
    function updateManualMetrics() {
      const total = checks.length;
      const done = checks.filter(input => input.checked).length;
      if (progressEl) progressEl.textContent = `${done}/${total}`;
      document.querySelectorAll(`[data-regime-assurance-score="${scope}"]`).forEach(metric => {
        const autoPct = Number(metric.dataset.autoPct || 0);
        const manualPct = total ? (done / total) * 100 : 100;
        const score = Math.round((0.7 * autoPct) + (0.3 * manualPct));
        const value = metric.querySelector('b');
        if (value) value.textContent = `${score}%`;
        metric.dataset.manualDone = String(done);
        metric.dataset.manualTotal = String(total);
        metric.dataset.tooltip = `Regime assurance score\n70% scan/evidence coverage + 30% manual completion\n\nScan/evidence coverage: ${Math.round(autoPct)}%\nManual completion: ${done}/${total}\nCurrent score: round(0.7 x scan + 0.3 x manual)`;
      });
      if (scope === 'asvs' && scoreEl) {
        const autoPct = Number(scoreEl.dataset.autoPct || 0);
        const score = Math.round((0.7 * autoPct) + (0.3 * (total ? (done / total) * 100 : 0)));
        scoreEl.textContent = `${score}%`;
        scoreEl.dataset.manualDone = String(done);
        scoreEl.dataset.manualTotal = String(total);
        scoreEl.dataset.tooltip = `ASVS traceability score\n70% automated assurance + 30% manual evidence\n\nAutomated assurance: ${autoPct}%\nPASS = 1, WARN = 0.5, FAIL = 0\n\nManual evidence: ${done}/${total}\nCurrent score: round(0.7 x ${autoPct}% + 0.3 x manual completion)`;
      }
    }
    checks.forEach(input => input.addEventListener('change', () => { persist(); updateManualMetrics(); }));
    list.querySelectorAll('[data-manual-select]').forEach(button => {
      button.addEventListener('click', () => {
        const checked = button.dataset.manualSelect === 'all';
        checks.forEach(input => { input.checked = checked; });
        persist();
        updateManualMetrics();
      });
    });
    updateManualMetrics();
  });
}
setupManualChecklist();
function setupTooltips() {
  const tableHeaderTooltips = {
    ID: 'ID\n\nStable identifier for this row, such as an FR, TBT, scanner finding, or evidence artifact.',
    Status: 'Status\n\nCurrent lifecycle or result state for this row.\n\nCommon FR values: in scope, draft, deferred, not applicable, retired.\n\nEvidence/test values may include passed, failed, partial, missing, manual review, approved, or planned.',
    Owner: 'Owner\n\nTeam, role, or party responsible for this requirement or activity.\n\nUsually assigned to a team or role such as auth-team, platform-team, security, assessor, approver, or reviewer. Blank/— means no owner has been assigned yet.',
    Refs: 'Refs\n\nCompact counts for related references.\n\nCode = implementation references.\nTBT = Test Basis records proving this FR.\nRules = mapped compliance requirements covered by the FR/TBT chain.',
    Assurance: 'Assurance\n\nCurrent assurance rollup based on required TBT evidence and blocking scanner signals.\n\nPassed = required evidence is observed.\nPartial = some evidence exists but coverage is incomplete.\nMissing/unproven = required evidence is absent.\nFailed = observed evidence or scanner signal blocks assurance.\nManual review = a human decision is required.',
    Type: 'Type\n\nEvidence, test, or artifact category.\n\nCommon values include unit, integration, e2e, test_result, scanner_result, document, approval, screenshot, and manual_note.',
    Artifact: 'Artifact\n\nFile or report artifact produced by the scan or assurance workflow.',
    Producer: 'Producer\n\nTool, workflow, or human process that created the artifact.',
    Supports: 'Supports\n\nFR, TBT, compliance row, or assurance item supported by this artifact.',
    Size: 'Size\n\nArtifact size on disk.',
    Hash: 'Hash\n\nContent hash used for provenance, audit, and future proof verification.',
    Severity: 'Severity\n\nScanner severity for the finding.\n\nTypical values are critical, high, medium, low, info, or unknown. Higher severity generally needs faster triage, even when not mapped to a compliance row.',
    Scanner: 'Scanner\n\nTool that produced the finding or evidence row.\n\nExamples include Semgrep, Gitleaks, Grype, Trivy, OSV Scanner, Syft, or an approved test runner.',
    Finding: 'Finding\n\nShort description of the issue or scanner result.\n\nFor dependency findings this is often the package/CVE/GHSA. For static analysis it may be a rule id or source location.',
    'Assurance trace': 'Assurance trace\n\nShows whether this scanner row maps to a compliance rule, FR/TBT chain, or remains general scanner evidence.\n\nMapped means it can affect a specific compliance requirement. Unmapped means it remains useful scanner evidence but is not tied to a project FR/TBT chain.',
    TBT: 'TBT\n\nTest Basis for Testing: the specific assurance test obligation for an FR.',
    Purpose: 'Purpose\n\nWhat this TBT, code reference, or evidence item is intended to prove.',
    Compliance: 'Compliance\n\nCompliance regime requirement mapped to this FR/TBT.\n\nExamples: ASVS v5.0.0-7.1.1 or NIST 800-53 family/control rows. A missing mapping means the TBT is project-only or still needs compliance mapping.',
    'Test state': 'Test state\n\nWhether a test exists, is approved for scan execution, or still needs work.\n\nCommon values: No test yet, Awaiting approval, Approved for scan, Evidence observed.',
    Evidence: 'Evidence\n\nObserved artifact or result currently available for this row.\n\nCommon states: observed, missing, passed, failed, partial, manual review. Evidence only counts when it is tied back to the expected FR/TBT proof chain.',
    Path: 'Path\n\nFile path for code, tests, or generated artifacts.',
    'Project item': 'Project item\n\nProject-local FR or TBT instantiated from a reusable blueprint.',
    'Blueprint item': 'Blueprint item\n\nReusable blueprint FR/TBT that this project item was derived from.',
    Version: 'Version\n\nVersion of the source blueprint, compliance regime, or artifact.\n\nExamples: asvs-5.0.0 for a blueprint, v5.0.0 for ASVS rows, or a scanner/ruleset version.',
    Review: 'Review\n\nHuman review state for the lineage or recommendation.\n\nCommon values: proposed, needs review, accepted, rejected, stale, or blank when no review workflow has touched it.',
    Scope: 'Scope\n\nWhether the compliance mapping applies to the FR or a specific TBT.\n\nFR means broad requirement mapping. TBT means a precise test basis maps to the compliance row.',
    Item: 'Item\n\nProject item that owns this mapping.',
    Regime: 'Regime\n\nCompliance regime, such as ASVS or NIST.',
    Requirement: 'Requirement\n\nSpecific compliance row or requirement identifier.',
    Relationship: 'Relationship\n\nHow the item relates to the compliance row.\n\nCommon values: satisfies, supporting, blocks, not applicable, mapped elsewhere, or mapping required.',
    Criterion: 'Criterion\n\nFramework gate criterion or condition.\n\nCriteria are gate-level checks that may require FR/TBT evidence, manual approval, waiver, or other artifacts.',
    'Evidence required': 'Evidence required\n\nEvidence expected to satisfy this criterion.\n\nMay be automated test evidence, scanner evidence, manual documents, approval records, waivers, or compensating controls.',
    Done: 'Done\n\nMarks whether the manual step has been completed.',
    'Manual step': 'Manual step\n\nHuman action required outside automated scanner evidence.',
    'What to verify': 'What to verify\n\nSpecific verification activity the reviewer should perform.',
    'Evidence to collect': 'Evidence to collect\n\nArtifact or note to capture as manual assurance evidence.'
  };
  document.querySelectorAll('table th').forEach(th => {
    const label = (th.textContent || '').trim().replace(/\s+/g, ' ');
    if (!label || th.dataset.tooltip) return;
    th.dataset.tooltip = tableHeaderTooltips[label] || `${label}\n\nColumn value for ${label.toLowerCase()}.`;
  });
  const tooltip = document.createElement('div');
  tooltip.className = 'ui-tooltip';
  tooltip.setAttribute('role', 'tooltip');
  document.body.appendChild(tooltip);
  const escapeHtml = value => String(value || '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[ch]));
  const renderTooltip = text => {
    const parts = String(text || '').split(/\n\s*\n/);
    if (parts.length <= 1) {
      tooltip.textContent = text;
      return;
    }
    const title = parts.shift();
    tooltip.innerHTML = '<strong>' + escapeHtml(title) + '</strong>' +
      parts.map(part => '<p>' + escapeHtml(part) + '</p>').join('');
  };
  const placeTooltip = (event, el) => {
    const rect = el.getBoundingClientRect();
    const sourceX = event && 'clientX' in event ? event.clientX : rect.left + rect.width / 2;
    const sourceY = event && 'clientY' in event ? event.clientY : rect.bottom;
    tooltip.style.left = '0px';
    tooltip.style.top = '0px';
    tooltip.classList.add('is-visible');
    const box = tooltip.getBoundingClientRect();
    let left = sourceX + 14;
    let top = sourceY + 16;
    if (el.closest('.assurance-workflow-tabs')) {
      left = rect.left + (rect.width / 2) - (box.width / 2);
      top = rect.bottom + 10;
      tooltip.classList.add('ui-tooltip-below-tab');
    } else {
      tooltip.classList.remove('ui-tooltip-below-tab');
    }
    if (left + box.width > window.innerWidth - 10) left = window.innerWidth - box.width - 10;
    if (top + box.height > window.innerHeight - 10) top = Math.max(10, sourceY - box.height - 18);
    tooltip.style.left = `${Math.max(10, left)}px`;
    tooltip.style.top = `${Math.max(10, top)}px`;
  };
  const showTooltip = (event) => {
    const el = event.currentTarget;
    const text = el.dataset.tooltip;
    if (!text) return;
    renderTooltip(text);
    placeTooltip(event, el);
  };
  const hideTooltip = () => tooltip.classList.remove('is-visible');
  document.querySelectorAll('[data-tooltip]').forEach(el => {
    const text = el.dataset.tooltip;
    if (!text) return;
    el.removeAttribute('title');
    el.classList.add('has-tooltip');
    el.addEventListener('mouseenter', showTooltip);
    el.addEventListener('mousemove', showTooltip);
    el.addEventListener('mouseleave', hideTooltip);
    el.addEventListener('focus', showTooltip);
    el.addEventListener('blur', hideTooltip);
  });
  window.addEventListener('scroll', hideTooltip, { passive: true });
}
setupTooltips();
function setupFrCatalog() {
  const card = document.querySelector('.fr-card');
  if (!card) return;
  const search = document.getElementById('fr-search');
  const catFilter = document.getElementById('fr-category-filter');
  const statusFilter = document.getElementById('fr-status-filter');

  // Populate category dropdown
  const cats = new Set();
  document.querySelectorAll('.fr-category-header').forEach(h => cats.add(h.dataset.category));
  [...cats].sort().forEach(c => {
    const opt = document.createElement('option');
    opt.value = c; opt.textContent = c;
    catFilter.appendChild(opt);
  });

  function applyFilters() {
    const q = (search.value || '').toLowerCase();
    const cat = catFilter.value;
    const st = statusFilter.value;
    document.querySelectorAll('.fr-row').forEach(row => {
      const rid = row.dataset.frId.toLowerCase();
      const titleCell = row.querySelector('td:nth-child(2)');
      const title = (titleCell ? titleCell.textContent : '').toLowerCase();
      const matchesSearch = !q || rid.includes(q) || title.includes(q);
      const matchesCat = !cat || row.dataset.category === cat;
      const matchesStatus = !st || row.dataset.status === st;
      const visible = matchesSearch && matchesCat && matchesStatus;
      row.classList.toggle('hidden-by-filter', !visible);
      const detail = document.querySelector('.fr-detail-row[data-fr-id="' + row.dataset.frId + '"]');
      if (detail) detail.classList.toggle('hidden-by-filter', !visible);
    });
    // Hide category headers whose all rows are hidden
    document.querySelectorAll('.fr-category-header').forEach(h => {
      let any = false;
      let n = h.nextElementSibling;
      while (n && !n.classList.contains('fr-category-header')) {
        if (n.classList.contains('fr-row') && !n.classList.contains('hidden-by-filter')) {
          any = true; break;
        }
        n = n.nextElementSibling;
      }
      h.classList.toggle('hidden-by-filter', !any);
    });
  }

  [search].forEach(el => el.addEventListener('input', applyFilters));
  [catFilter, statusFilter].forEach(el => el.addEventListener('change', applyFilters));

  // Click row to expand detail
  document.querySelectorAll('.fr-row').forEach(row => {
    row.addEventListener('click', () => {
      const detail = document.querySelector('.fr-detail-row[data-fr-id="' + row.dataset.frId + '"]');
      if (!detail) return;
      const isHidden = detail.hasAttribute('hidden');
      if (isHidden) detail.removeAttribute('hidden'); else detail.setAttribute('hidden', '');
      row.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
      if (isHidden) renderFrLocalGraph(detail);
    });
    row.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); row.click(); }
    });
  });
}
setupFrCatalog();

function renderFrLocalGraph(detail) {
  const graphHost = detail.querySelector('.fr-local-d3');
  if (!graphHost || graphHost.dataset.rendered === '1') return;
  if (typeof d3 === 'undefined') {
    const canvas = graphHost.querySelector('.fr-local-svg');
    if (canvas) canvas.innerHTML = '<div class="fr-local-empty">Graph library unavailable. The table below still shows the FR/TBT/evidence chain.</div>';
    window.setTimeout(() => renderFrLocalGraph(detail), 650);
    return;
  }
  const dataEl = graphHost.querySelector('.fr-local-graph-data');
  const canvas = graphHost.querySelector('.fr-local-svg');
  const context = graphHost.querySelector('.fr-local-context');
  if (!dataEl || !canvas || !context) return;
  let data;
  try { data = JSON.parse(dataEl.textContent || '{"nodes":[],"edges":[]}'); } catch (_) { return; }
  if (!data.nodes || !data.nodes.length) return;
  graphHost.dataset.rendered = '1';
  canvas.innerHTML = '';

  const width = Math.max(980, canvas.clientWidth || 980);
  const typeOrder = ['planning_artifact', 'blueprint', 'fr', 'tbt', 'ruleset_row', 'test', 'test_result', 'scanner_result'];
  const typeLabels = {
    planning_artifact: 'Plan',
    blueprint: 'Blueprint',
    fr: 'FR',
    tbt: 'TBT',
    ruleset_row: 'Compliance',
    test: 'Test',
    test_result: 'Evidence',
    scanner_result: 'Scan'
  };
  const typeColors = {
    planning_artifact: '#c4d8e0',
    blueprint: '#b794f4',
    fr: '#56c7b7',
    tbt: '#35d07f',
    ruleset_row: '#8fcbe8',
    test: '#b794f4',
    test_result: '#718096',
    scanner_result: '#ff98a9'
  };
  const grouped = new Map();
  typeOrder.forEach(type => grouped.set(type, []));
  data.nodes.forEach(node => {
    if (!grouped.has(node.type)) grouped.set(node.type, []);
    grouped.get(node.type).push(node);
  });
  const maxRows = Math.max(...[...grouped.values()].map(list => list.length), 1);
  const height = Math.max(250, 74 + maxRows * 74);
  const xByType = new Map();
  typeOrder.forEach((type, index) => {
    xByType.set(type, 58 + index * ((width - 116) / Math.max(typeOrder.length - 1, 1)));
  });
  const nodeById = new Map(data.nodes.map(node => [node.id, node]));
  data.nodes.forEach(node => {
    const list = grouped.get(node.type) || [];
    const index = list.indexOf(node);
    const band = height - 72;
    node.x = xByType.get(node.type) || width / 2;
    node.y = 44 + (list.length <= 1 ? band / 2 : index * (band / (list.length - 1)));
  });

  const svg = d3.select(canvas)
    .append('svg')
    .attr('viewBox', `0 0 ${width} ${height}`)
    .attr('role', 'img')
    .attr('aria-label', 'FR assurance graph');

  svg.append('g')
    .attr('class', 'fr-local-lanes')
    .selectAll('line')
    .data(typeOrder)
    .join('line')
    .attr('x1', type => xByType.get(type))
    .attr('x2', type => xByType.get(type))
    .attr('y1', 24)
    .attr('y2', height - 24);

  svg.append('g')
    .attr('class', 'fr-local-lane-labels')
    .selectAll('text')
    .data(typeOrder)
    .join('text')
    .attr('x', type => xByType.get(type))
    .attr('y', 16)
    .attr('text-anchor', 'middle')
    .text(type => typeLabels[type] || type);

  svg.append('g')
    .attr('class', 'fr-local-edges')
    .selectAll('path')
    .data(data.edges || [])
    .join('path')
    .attr('d', edge => {
      const source = nodeById.get(edge.source);
      const target = nodeById.get(edge.target);
      if (!source || !target) return '';
      const mid = (source.x + target.x) / 2;
      return `M${source.x},${source.y} C${mid},${source.y} ${mid},${target.y} ${target.x},${target.y}`;
    });

  const node = svg.append('g')
    .attr('class', 'fr-local-nodes')
    .selectAll('g')
    .data(data.nodes)
    .join('g')
    .attr('tabindex', 0)
    .attr('role', 'button')
    .attr('transform', d => `translate(${d.x},${d.y})`)
    .on('click', (_, d) => selectNode(d))
    .on('keydown', function(event, d) {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectNode(d);
      }
    });

  node.append('circle')
    .attr('r', 12)
    .attr('fill', d => typeColors[d.type] || '#8fcbe8')
    .attr('class', d => `fr-local-dot fr-local-dot-${String(d.status || 'unknown').replace(/[^a-zA-Z0-9_-]/g, '_')}`);

  node.append('text')
    .attr('class', 'fr-local-node-title')
    .attr('x', 0)
    .attr('y', 28)
    .attr('text-anchor', 'middle')
    .text(d => trimGraphText(d.title || d.id, 18));

  function trimGraphText(value, max) {
    value = String(value || '');
    return value.length > max ? value.slice(0, Math.max(0, max - 1)) + '…' : value;
  }

  function selectNode(nodeData) {
    graphHost.querySelectorAll('.fr-local-nodes g').forEach(el => el.classList.remove('is-selected'));
    const idx = data.nodes.indexOf(nodeData);
    const selected = graphHost.querySelectorAll('.fr-local-nodes g')[idx];
    if (selected) selected.classList.add('is-selected');
    const details = (nodeData.details || [])
      .filter(item => item && item.value)
      .map(item => `<dt>${escapeHtml(item.label || 'Detail')}</dt><dd>${escapeHtml(item.value)}</dd>`)
      .join('');
    context.innerHTML = `
      <div class="fr-local-context-head">
        <span>${escapeHtml(typeLabels[nodeData.type] || nodeData.type || 'Node')}</span>
        <strong>${escapeHtml(nodeData.title || nodeData.id)}</strong>
      </div>
      ${nodeData.subtitle ? `<p>${escapeHtml(nodeData.subtitle)}</p>` : ''}
      ${nodeData.status ? `<b class="fr-local-context-status">${escapeHtml(nodeData.status)}</b>` : ''}
      ${details ? `<dl>${details}</dl>` : '<span>No additional details.</span>'}
    `;
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[ch]));
  }

  selectNode(data.nodes[0]);
}
function setupRegimeTabs() {
  document.querySelectorAll('.fw-regime-tabs').forEach(group => {
    const buttons = [...group.querySelectorAll('.fw-regime-tab-btn')];
    buttons.forEach(button => {
      button.addEventListener('click', () => {
        const targetId = button.dataset.fwTabTarget;
        buttons.forEach(btn => {
          const active = btn === button;
          btn.classList.toggle('active', active);
          btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        group.querySelectorAll('.fw-regime-pane').forEach(pane => {
          pane.classList.toggle('active', pane.id === targetId);
        });
      });
    });
  });
}
setupRegimeTabs();
function setupFrameworkTabs() {
  document.querySelectorAll('[id^="tab-fw-"]').forEach(panel => {
    const card = panel.querySelector('.fw-card');
    if (!card) return;
    const prefix = card.querySelector('[id$="-search"]')?.id.replace('-search', '') || '';
    const search = document.getElementById(prefix + '-search');
    const groupFilter = document.getElementById(prefix + '-chapter-filter');
    const statusFilter = document.getElementById(prefix + '-status-filter');
    const showFiltered = document.getElementById(prefix + '-show-filtered');
    if (!search) return;

    // Populate group dropdown
    const groups = new Set();
    panel.querySelectorAll('.fw-group-header').forEach(h => groups.add(h.dataset.group));
    [...groups].sort().forEach(g => {
      const opt = document.createElement('option');
      opt.value = g; opt.textContent = g;
      groupFilter.appendChild(opt);
    });

    function applyFilters() {
      const q = (search.value || '').toLowerCase();
      const grp = groupFilter.value;
      const st = statusFilter.value;
      const showF = showFiltered?.checked || false;
      panel.querySelectorAll('.fw-row').forEach(row => {
        const groupHeader = panel.querySelector('.fw-group-header[data-group="' + row.dataset.group + '"]');
        const groupCollapsed = groupHeader?.classList.contains('fw-group-collapsed') || false;
        if (row.classList.contains('fw-row-filtered') && !showF) {
          row.dataset.filterMatch = '0';
          row.classList.add('hidden-by-filter');
          return;
        }
        const rid = row.dataset.rowId.toLowerCase();
        const searchable = (row.dataset.searchText || row.textContent || '').toLowerCase();
        const matchesSearch = !q || rid.includes(q) || searchable.includes(q);
        const matchesGroup = !grp || row.dataset.group === grp;
        const matchesStatus = !st || row.dataset.state === st;
        const visible = matchesSearch && matchesGroup && matchesStatus;
        row.dataset.filterMatch = visible ? '1' : '0';
        row.classList.toggle('hidden-by-filter', !visible || groupCollapsed);
        const detail = panel.querySelector('.fw-detail-row[data-row-id="' + row.dataset.rowId + '"]');
        if (detail) detail.classList.toggle('hidden-by-filter', !visible || groupCollapsed);
      });
      panel.querySelectorAll('.fw-group-header').forEach(h => {
        let any = false;
        let n = h.nextElementSibling;
        while (n && !n.classList.contains('fw-group-header')) {
          if (n.classList.contains('fw-row') && n.dataset.filterMatch === '1') { any = true; break; }
          n = n.nextElementSibling;
        }
        h.classList.toggle('hidden-by-filter', !any);
      });
    }

    [search, showFiltered].forEach(el => el?.addEventListener('input', applyFilters));
    [groupFilter, statusFilter].forEach(el => el?.addEventListener('change', applyFilters));

    panel.querySelectorAll('.fw-group-header').forEach(header => {
      function toggleGroup() {
        const collapsed = !header.classList.contains('fw-group-collapsed');
        header.classList.toggle('fw-group-collapsed', collapsed);
        header.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        applyFilters();
      }
      header.addEventListener('click', toggleGroup);
      header.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleGroup(); }
      });
    });

    panel.querySelectorAll('.fw-row').forEach(row => {
      row.addEventListener('click', () => {
        const detail = panel.querySelector('.fw-detail-row[data-row-id="' + row.dataset.rowId + '"]');
        if (!detail) return;
        const isHidden = detail.hasAttribute('hidden');
        if (isHidden) detail.removeAttribute('hidden'); else detail.setAttribute('hidden', '');
        row.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
        if (isHidden) {
          const mini = detail.querySelector('.mini-trace[data-trace-node]');
          const renderMini = () => {
            if (mini && window.asvsGraph && window.asvsGraph.renderMiniTrace) {
              window.asvsGraph.renderMiniTrace(mini, mini.dataset.traceNode);
              mini.dataset.rendered = '1';
            }
          };
          renderMini();
          if (mini && !mini.dataset.rendered) window.setTimeout(renderMini, 600);
        }
      });
      row.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); row.click(); }
      });
    });
    applyFilters();
  });
}
setupFrameworkTabs();
function setupReverseLookup() {
  const dataEl = document.getElementById('reverse-lookup-data');
  if (!dataEl) return;
  let lookup;
  try { lookup = new Map(JSON.parse(dataEl.textContent || '[]')); } catch (_) { return; }
  if (!lookup.size) return;

  // For each scanner name, build a list of [pattern, entry] pairs
  const byScanner = {};
  for (const [ref, entry] of lookup) {
    const colonIdx = ref.indexOf(':');
    if (colonIdx < 0) continue;
    const scanner = ref.substring(0, colonIdx);
    const pattern = ref.substring(colonIdx + 1);
    if (!byScanner[scanner]) byScanner[scanner] = [];
    byScanner[scanner].push([pattern, entry]);
  }

  // Simple glob matcher (no regex — avoids f-string brace conflicts)
  function globMatch(str, pat) {
    if (pat === '*') return true;
    if (pat.indexOf('*') < 0) return str === pat;
    const parts = pat.split('*');
    let idx = 0;
    for (let i = 0; i < parts.length; i++) {
      if (parts[i] === '') continue;
      idx = str.indexOf(parts[i], idx);
      if (idx < 0) return false;
      if (i === 0 && idx > 0) return false; // prefix must match start
      idx += parts[i].length;
    }
    // If last part non-empty, must match end
    const last = parts[parts.length - 1];
    if (last && idx !== str.length) return false;
    return true;
  }

  // Scan All Findings table rows for scanner rule_ids
  const findingTables = document.querySelectorAll('.finding-detail');
  findingTables.forEach(table => {
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(row => {
      const cells = row.querySelectorAll('td');
      if (cells.length < 3) return;
      // Scanner detail tables put rule IDs in different columns; prefer the first code cell.
      const codeEl = cells[0].querySelector('code') || cells[1].querySelector('code');
      if (!codeEl) return;
      const ruleId = codeEl.textContent.trim();

      // Try each scanner's patterns
      let matchedEntry = null;
      for (const [scanner, patterns] of Object.entries(byScanner)) {
        for (const [pattern, entry] of patterns) {
          if (globMatch(ruleId, pattern)) {
            matchedEntry = entry;
            break;
          }
        }
        if (matchedEntry) break;
      }

      if (matchedEntry && matchedEntry.compliance_rows.length > 0) {
        // Add impact badge to the last cell
        const lastCell = cells[cells.length - 1];
        const fwSet = new Set(matchedEntry.compliance_rows.map(r => r.ruleset));
        const fwList = [...fwSet].join(', ');
        const btn = document.createElement('button');
        btn.className = 'asvs-impact-btn';
        btn.textContent = `ASVS impact (${matchedEntry.compliance_rows.length})`;
        btn.title = `Threatens ${matchedEntry.compliance_rows.length} compliance row(s) via ${matchedEntry.fr_ids.join(', ')}`;
        btn.dataset.frIds = JSON.stringify(matchedEntry.fr_ids);
        btn.dataset.rows = JSON.stringify(matchedEntry.compliance_rows);
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (window.asvsGraph) {
            showPanel('graph');
            window.asvsGraph.openRows(matchedEntry.compliance_rows);
            return;
          }
          const rows = matchedEntry.compliance_rows;
          const fw = rows[0].ruleset;
          const tabId = 'fw-' + fw.toLowerCase().replace(/[-_]/g, '');
          // Switch to framework tab
          const btn2 = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
          if (btn2) btn2.click();
          // Highlight the affected rows
          setTimeout(() => {
            const panel = document.getElementById('tab-' + tabId);
            if (!panel) return;
            const rowIds = new Set(rows.map(r => r.row));
            panel.querySelectorAll('.fw-row').forEach(r => {
              if (rowIds.has(r.dataset.rowId)) {
                r.style.outline = '2px solid #ff4d6d';
                r.scrollIntoView({ behavior: 'smooth', block: 'center' });
              }
            });
          }, 100);
        });
        lastCell.appendChild(document.createElement('br'));
        lastCell.appendChild(btn);
      }
    });
  });
}
setupReverseLookup();
function setupReviewBoard() {
  const board = document.querySelector('[data-review-board]');
  if (!board) return;
  const reportDir = board.dataset.reportDir || 'reports/current';
  const manifest = board.dataset.manifest || (reportDir.replace(/\/$/, '') + '/generated-tests/VG_TEST_FRAMEWORK/manifest.json');
  const proposal = board.dataset.proposal || (reportDir.replace(/\/$/, '') + '/native-test-mapping-proposal.json');
  const commandEl = board.querySelector('[data-review-command]');
  const context = board.querySelector('[data-review-context]');
  const workspace = board.querySelector('.review-board-workspace');
  const promptMode = board.querySelector('[data-review-prompt-mode]');
  const promptDrawer = board.querySelector('[data-review-prompt-drawer]');
  const promptDrawerTitle = board.querySelector('[data-review-prompt-title]');
  const promptDrawerScope = board.querySelector('[data-review-prompt-scope]');
  const promptDrawerWarning = board.querySelector('[data-review-prompt-warning]');
  const promptDrawerBody = board.querySelector('[data-review-prompt-body]');
  const promptDrawerCopy = board.querySelector('[data-review-prompt-copy]');
  const promptDrawerClose = board.querySelector('[data-review-prompt-close]');
  const saveBoardStateBtn = board.querySelector('[data-review-board-save]');
  const storageKey = 'native-review-board:' + reportDir;
  let activeCard = null;
  let draggingCard = null;
  let promptOverride = null;
  let lastPromptCopyText = '';
  function shellQuote(value) {
    const text = String(value || '');
    if (!text) return "''";
    return "'" + text.replace(/'/g, "'\"'\"'") + "'";
  }
  function meaningfulText(value) {
    const text = String(value || '').trim();
    return text === '-' ? '' : text;
  }
  function cardData(card) {
    return {
      id: card.dataset.reviewCard,
      selector: card.dataset.selector || '',
      title: card.dataset.title || '',
      native_path: card.dataset.nativePath || '',
      tbt: card.dataset.tbt || '',
      frs: card.dataset.frs || '',
      fr_summary: card.dataset.frSummary || '',
      tbt_summary: card.dataset.tbtSummary || '',
      target: card.dataset.target || '',
      recommendation: card.dataset.recommendation || '',
      agentic_rationale: meaningfulText(card.dataset.agenticRationale),
      discovery_rationale: meaningfulText(card.dataset.discoveryRationale),
      rationale: meaningfulText(card.dataset.agenticRationale) || meaningfulText(card.dataset.discoveryRationale),
      reviewer_note: meaningfulText(card.dataset.reviewerNote),
      manual_test_path: card.dataset.manualTestPath || '',
      decision: card.dataset.reviewDecision || '',
      pack_path: card.dataset.packPath || '',
      source: card.dataset.source || '',
      safety: card.dataset.safety || '',
      assessment: card.dataset.assessment || '',
      type: card.dataset.type || 'test',
      status: card.dataset.status || '',
      confidence: card.dataset.confidence || ''
    };
  }
  function normaliseStoredCardState(value) {
    if (typeof value === 'string') return {lane: value};
    if (!value || typeof value !== 'object') return {};
    return value;
  }
  function readEmbeddedBoardDocument() {
    const script = board.querySelector('[data-review-board-state]');
    if (!script) return {};
    try {
      return JSON.parse(script.textContent || '{}') || {};
    } catch (_) {
      return {};
    }
  }
  function readEmbeddedBoardState() {
    const parsed = readEmbeddedBoardDocument();
    const out = {};
    (parsed.cards || []).forEach(card => {
      if (card && card.id) out[card.id] = normaliseStoredCardState(card);
    });
    return out;
  }
  function readLocalBoardState() {
    try {
      const parsed = JSON.parse(localStorage.getItem(storageKey) || '{}') || {};
      const out = {};
      Object.entries(parsed).forEach(([id, value]) => {
        out[id] = normaliseStoredCardState(value);
      });
      return out;
    } catch (_) {
      return {};
    }
  }
  let state = {...readEmbeddedBoardState(), ...readLocalBoardState()};
  const embeddedBoardDocument = readEmbeddedBoardDocument();
  function boardStateForCard(card) {
    const data = cardData(card);
    return {
      ...data,
      lane: laneOf(card),
      frs: String(data.frs || '').split(',').map(part => part.trim()).filter(Boolean),
      decision: card.dataset.reviewDecision || '',
      reviewer_note: meaningfulText(card.dataset.reviewerNote),
      manual_test_path: card.dataset.manualTestPath || ''
    };
  }
  function currentBoardStateDocument() {
    const generatedAt = new Date().toISOString();
    return {
      schema_version: 1,
      mode: 'project_fr_board_state',
      project: embeddedBoardDocument.project || inferProjectFromSourceRepo(inferSourceRepoFromReportDir(reportDir)),
      run_id: embeddedBoardDocument.run_id || (reportDir.match(/reports\/([^/]+)\/?$/) || [])[1] || 'current',
      generated_at: generatedAt,
      cards: [...board.querySelectorAll('[data-review-card]')].map(card => {
        const entry = boardStateForCard(card);
        entry.updated_at = generatedAt;
        return entry;
      })
    };
  }
  function saveState() {
    const next = {};
    board.querySelectorAll('[data-review-card]').forEach(card => {
      next[card.dataset.reviewCard] = boardStateForCard(card);
    });
    state = next;
    localStorage.setItem(storageKey, JSON.stringify(state));
  }
  function refreshBoardOutputs() {
    updateCommand();
  }
  function laneOf(card) {
    const lane = card.closest('[data-review-lane]');
    return lane ? lane.dataset.reviewLane : '';
  }
  function frForCard(card) {
    const targetFr = String(card.dataset.target || '').split('/').map(part => part.trim()).find(part => /^FR-\w+/i.test(part));
    const frs = String(card.dataset.frs || '').split(',').map(part => part.trim()).filter(Boolean);
    return targetFr || frs.find(part => /^FR-\w+/i.test(part)) || '';
  }
  function hasAppliedMapping(card) {
    if (!card) return false;
    const hasTbt = Boolean(String(card.dataset.tbt || '').trim());
    const frs = String(card.dataset.frs || '').split(',').map(part => part.trim()).filter(Boolean);
    return hasTbt || frs.length > 0;
  }
  function isOrphanTestCard(card) {
    return Boolean(card && (card.dataset.nativePath || card.dataset.packPath) && !hasAppliedMapping(card));
  }
  function testTypeLabel(card) {
    const raw = String(card.dataset.type || 'test').toLowerCase().replace(/[_-]+/g, ' ');
    const labels = {
      unit: 'Unit test',
      integration: 'Integration test',
      e2e: 'E2E test',
      load: 'Load test',
      scanner: 'Scanner test',
      document: 'Document test',
      manual: 'Manual test',
      test: 'Test'
    };
    return labels[raw] || raw.replace(/\b\w/g, ch => ch.toUpperCase()) || 'Test';
  }
  function displayLabelForCard(card) {
    const lane = laneOf(card);
    if (lane === 'map') return card.dataset.nativePath || card.dataset.title || card.dataset.reviewCard || 'Native test';
    const fr = frForCard(card);
    const tbt = String(card.dataset.tbt || '').trim();
    if (fr && tbt) return fr + ' -> ' + tbt;
    if (fr) return fr;
    return 'Awaiting FR/TBT';
  }
  function updateCardLabel(card) {
    const label = displayLabelForCard(card);
    const title = card.querySelector('.review-board-card-head strong');
    if (title) title.textContent = label;
    card.dataset.sortLabel = label;
  }
  function sortLane(dropzone) {
    if (!dropzone) return;
    const cards = [...dropzone.querySelectorAll('[data-review-card]')];
    cards
      .sort((a, b) => {
        const frCompare = (frForCard(a) || 'ZZZ').localeCompare(frForCard(b) || 'ZZZ', undefined, {numeric: true});
        if (frCompare) return frCompare;
        return displayLabelForCard(a).localeCompare(displayLabelForCard(b), undefined, {numeric: true});
      })
      .forEach(card => dropzone.appendChild(card));
  }
  function refreshCardLabelsAndOrder() {
    board.querySelectorAll('[data-review-card]').forEach(updateCardLabel);
    board.querySelectorAll('.review-board-dropzone').forEach(sortLane);
  }
  function refreshCounts() {
    board.querySelectorAll('[data-review-lane]').forEach(lane => {
      const count = lane.querySelectorAll('[data-review-card]').length;
      const badge = lane.querySelector('.review-board-lane-head b');
      if (badge) badge.textContent = String(count);
    });
  }
  function pickedCardsForLane(laneId) {
    return [...board.querySelectorAll(`[data-review-lane="${CSS.escape(laneId)}"] [data-review-card].is-picked`)];
  }
  function cardsForLane(laneId) {
    return [...board.querySelectorAll(`[data-review-lane="${CSS.escape(laneId)}"] [data-review-card]`)];
  }
  function setCardPicked(card, value) {
    card.classList.toggle('is-picked', value);
    const btn = card.querySelector('[data-review-card-pick]');
    if (btn) btn.setAttribute('aria-pressed', value ? 'true' : 'false');
  }
  function promptModeForLane(laneId) {
    if (laneId === 'map') return 'map';
    if (laneId === 'recommended') return 'reviewMappingBrief';
    if (laneId === 'specify') return 'specify';
    if (laneId === 'review') return 'review';
    if (laneId === 'import') return 'import';
    if (laneId === 'blocked') return 'blocked';
    return 'map';
  }
  function laneTitle(laneId) {
    const lane = board.querySelector(`[data-review-lane="${CSS.escape(laneId)}"]`);
    return lane?.querySelector('.review-board-lane-head strong')?.textContent || laneId;
  }
  function targetPartsForCardData(data) {
    const parts = String(data.target || '').split('/').map(part => part.trim()).filter(Boolean);
    return {
      fr: parts.find(part => /^FR-\w+/i.test(part)) || '',
      tbt: parts.find(part => /^TBT-\w+/i.test(part)) || ''
    };
  }
  function targetPartsForCard(card) {
    return targetPartsForCardData(cardData(card));
  }
  function setSelectOptions(select, options, selectedValue) {
    if (!select) return;
    select.innerHTML = '';
    options.forEach(option => {
      const el = document.createElement('option');
      el.value = option.value;
      el.textContent = option.label;
      select.appendChild(el);
    });
    select.value = selectedValue && options.some(option => option.value === selectedValue) ? selectedValue : options[0]?.value || '';
  }
  function inferSourceRepoFromReportDir(value) {
    const text = String(value || '');
    const match = text.match(/^(.*)\/([^/]+)-asvs-scan-[^/]+\/\.asvs-scanner\/runtime\/reports\/[^/]+\/?$/);
    if (!match) return '/path/to/project';
    const parent = match[1];
    const repo = match[2];
    return parent + '/' + repo;
  }
  function inferProjectFromSourceRepo(value) {
    return String(value || '').split('/').filter(Boolean).pop() || 'target-project';
  }
  function reviewBriefForLane(laneId, items) {
    const lines = [];
    if (laneId === 'recommended') {
      lines.push('Agentic Mapping Review Brief');
      lines.push('');
      lines.push('Purpose: human approval of agentic native-test mapping recommendations.');
      lines.push('');
      lines.push('Review checklist:');
      lines.push('- Confirm the native test behaviour actually proves the suggested FR/TBT.');
      lines.push('- Reject or send back to Map Orphan Tests if the rationale overclaims evidence.');
      lines.push('- Leave unmapped when the test is useful context but not assurance evidence.');
      lines.push('- Accept only when the target FR/TBT and provenance are clear.');
      lines.push('');
      lines.push('Cards to review:');
      items.forEach((item, idx) => {
        lines.push('');
        lines.push(String(idx + 1) + '. ' + (item.target || item.title || item.native_path || item.id));
        lines.push('   Native path: ' + (item.native_path || item.pack_path || '-'));
        lines.push('   Target: ' + (item.target || 'No FR/TBT target'));
        lines.push('   FR context: ' + (item.fr_summary || 'Awaiting FR/TBT mapping'));
        lines.push('   TBT context: ' + (item.tbt_summary || 'Awaiting TBT selection'));
        lines.push('   Agentic rationale: ' + (item.agentic_rationale || 'No agentic rationale recorded'));
        lines.push('   Confidence: ' + (item.confidence || 'unknown'));
      });
      lines.push('');
      lines.push('Human action: use the context pane to approve, block, or send cards back. Approved mappings move right into Draft Tests for FR.');
      return lines.join('\n');
    }
    lines.push('Agentic Test Review Brief');
    lines.push('');
    lines.push('Purpose: human approval of agent-generated or wrapper assurance test drafts before execution.');
    lines.push('');
    lines.push('Review checklist:');
    lines.push('- Confirm the draft test proves the stated TBT/FR, not merely related code.');
    lines.push('- Confirm the test is safe, non-destructive, and uses disposable fixtures or mocks.');
    lines.push('- Confirm the TBT id appears in the file name, test title, and future JUnit testcase/classname.');
    lines.push('- Reject or send back to Draft Tests for FR if behaviour, data, or assertions are unclear.');
    lines.push('');
    lines.push('Drafts to review:');
    items.forEach((item, idx) => {
      lines.push('');
      lines.push(String(idx + 1) + '. ' + (item.target || item.title || item.tbt || item.id));
      lines.push('   TBT: ' + (item.tbt || 'No TBT'));
      lines.push('   FRs: ' + (item.frs || 'No FR'));
      lines.push('   FR context: ' + (item.fr_summary || 'Awaiting FR/TBT mapping'));
      lines.push('   TBT context: ' + (item.tbt_summary || 'Awaiting TBT selection'));
      lines.push('   Pack path: ' + (item.pack_path || '-'));
      lines.push('   Type/status: ' + [item.type, item.status].filter(Boolean).join(' / '));
    });
    lines.push('');
    lines.push('Human action: approve safe drafts for implementation, or send unclear drafts back to Draft Tests for FR. Only implemented tests move to Run Approved Tests.');
    return lines.join('\n');
  }
  function applyStoredState() {
    Object.entries(state).forEach(([id, stored]) => {
      const cardState = normaliseStoredCardState(stored);
      const laneId = cardState.lane || '';
      const card = board.querySelector(`[data-review-card="${CSS.escape(id)}"]`);
      let normalizedLaneId = laneId === 'accepted' ? 'specify' : laneId;
      if (card && isManifestReadyToRun(card)) {
        normalizedLaneId = 'import';
      }
      if (card) {
        if (cardState.decision) card.dataset.reviewDecision = cardState.decision;
        if (cardState.reviewer_note) card.dataset.reviewerNote = cardState.reviewer_note;
        if (cardState.manual_test_path) card.dataset.manualTestPath = cardState.manual_test_path;
        if (cardState.target) card.dataset.target = cardState.target;
      }
      if (card && normalizedLaneId === 'recommended' && !hasAgenticMappingRecommendation(card)) {
        normalizedLaneId = isOrphanTestCard(card) ? 'map' : 'blocked';
      }
      if (card && normalizedLaneId === 'review' && !hasAgenticTestDraft(card)) {
        normalizedLaneId = 'specify';
      }
      if (card && normalizedLaneId === 'import') {
        if (hasAgenticTestDraft(card) && !hasGeneratedRunApproval(card)) {
          normalizedLaneId = 'review';
        } else if (!hasAgenticTestDraft(card) && !hasManualRunApproval(card)) {
          normalizedLaneId = 'specify';
        }
      }
      if (card && normalizedLaneId === 'map' && !isOrphanTestCard(card)) {
        normalizedLaneId = 'blocked';
      }
      const lane = board.querySelector(`[data-review-lane="${CSS.escape(normalizedLaneId)}"] .review-board-dropzone`);
      if (card && lane) {
        lane.appendChild(card);
        if (normalizedLaneId !== laneId) state[id] = {...cardState, lane: normalizedLaneId};
      }
    });
    saveState();
    refreshCardLabelsAndOrder();
    refreshCounts();
  }
  function selectedByLane() {
    const out = {};
    board.querySelectorAll('[data-review-card]').forEach(card => {
      const lane = laneOf(card);
      (out[lane] ||= []).push(cardData(card));
    });
    return out;
  }
  function closePromptDrawer() {
    if (promptDrawer) promptDrawer.hidden = true;
  }
  function selectCard(card) {
    closePromptDrawer();
    activeCard = card;
    board.querySelectorAll('[data-review-card]').forEach(item => item.classList.toggle('is-selected', item === card));
    if (!context) return;
    const empty = context.querySelector('.review-context-empty');
    const body = context.querySelector('.review-context-body');
    if (workspace) {
      const lanes = [...board.querySelectorAll('[data-review-lane]')];
      const lane = card.closest('[data-review-lane]');
      const laneIndex = lane ? lanes.indexOf(lane) : -1;
      workspace.classList.add('has-context');
      workspace.classList.toggle('context-left', laneIndex >= 3);
      workspace.classList.toggle('context-right', laneIndex < 3);
    }
    if (empty) empty.hidden = true;
    if (body) body.hidden = false;
    if (workspace) {
      const workspaceBox = workspace.getBoundingClientRect();
      const cardBox = card.getBoundingClientRect();
      const paneBox = context.getBoundingClientRect();
      const paneHeight = paneBox.height || context.offsetHeight || 0;
      const viewportPad = 12;
      const maxViewportTop = Math.max(viewportPad, window.innerHeight - paneHeight - viewportPad);
      const clampedViewportTop = Math.min(Math.max(cardBox.top, viewportPad), maxViewportTop);
      const maxWorkspaceTop = Math.max(0, workspace.scrollHeight - paneHeight);
      const paneTop = Math.min(Math.max(0, Math.round(clampedViewportTop - workspaceBox.top)), maxWorkspaceTop);
      workspace.style.setProperty('--review-context-top', paneTop + 'px');
    }
    const data = cardData(card);
    const meta = [card.dataset.type || 'test', card.dataset.status || '', card.dataset.confidence || ''].filter(Boolean).join(' · ');
    const isGeneratedDraft = isGeneratedDraftCard(card);
    const isPlannedTbt = isPlannedTbtCard(card);
    const isAgenticMapping = hasAgenticMappingRecommendation(card);
    const sourceLabel = context.querySelector('[data-review-context-source-label]');
    const testPathLabel = context.querySelector('[data-review-context-test-path-label]');
    const targetLabel = context.querySelector('[data-review-context-target-label]');
    context.querySelector('[data-review-context-title]').textContent = data.title || data.id;
    context.querySelector('[data-review-context-meta]').textContent = meta;
    if (sourceLabel) {
      sourceLabel.textContent = isGeneratedDraft ? 'Scaffold path' : isPlannedTbt ? 'Planned test path' : 'Native path';
    }
    if (testPathLabel) {
      testPathLabel.textContent = isGeneratedDraft ? 'Test source' : isPlannedTbt ? 'Planned path' : 'Test file path';
    }
    if (targetLabel) {
      targetLabel.textContent = isGeneratedDraft ? 'Review state' : isPlannedTbt ? 'Next action' : 'Recommendation';
    }
    context.querySelector('[data-review-context-native]').textContent = data.native_path || card.dataset.packPath || '-';
    context.querySelector('[data-review-context-test-path]').textContent = data.manual_test_path || data.pack_path || 'No test path specified';
    const targetParts = targetPartsForCardData(data);
    context.querySelector('[data-review-context-tbt]').textContent = data.tbt || (targetParts.tbt ? targetParts.tbt + ' (recommended)' : 'Awaiting map review');
    context.querySelector('[data-review-context-frs]').textContent = data.frs || (targetParts.fr ? targetParts.fr + ' (recommended)' : 'Awaiting map review');
    let targetText = data.target || data.recommendation || 'No recommendation yet';
    if (isGeneratedDraft) {
      targetText = data.safety === 'review_required' ? 'Review required' : 'Review generated draft';
      if (data.discovery_rationale && /partial|blocked|unsupported|not found/i.test(data.discovery_rationale)) {
        targetText = 'Review required: partial support';
      }
    } else if (isPlannedTbt) {
      targetText = 'Needs test design';
    }
    context.querySelector('[data-review-context-target]').textContent = targetText;
    context.querySelector('[data-review-context-fr-summary]').textContent = data.fr_summary || 'Awaiting FR/TBT mapping.';
    context.querySelector('[data-review-context-tbt-summary]').textContent = data.tbt_summary || 'Awaiting TBT selection.';
    const rationaleLabel = context.querySelector('[data-review-context-rationale-label]');
    const rationaleText = context.querySelector('[data-review-context-rationale]');
    if (rationaleLabel) {
      rationaleLabel.textContent = isGeneratedDraft ? 'Draft rationale' : isAgenticMapping ? 'Agentic rationale' : 'Discovery rationale';
    }
    if (rationaleText) rationaleText.textContent = data.agentic_rationale || data.discovery_rationale || 'No rationale recorded yet.';
    const op = context.querySelector('[data-review-map-operation]');
    const fr = context.querySelector('[data-review-map-fr]');
    const tbt = context.querySelector('[data-review-map-tbt]');
    const testPath = context.querySelector('[data-review-test-path]');
    const note = context.querySelector('[data-review-map-note]');
    const operationLabel = context.querySelector('[data-review-operation-label]');
    const frLabel = context.querySelector('[data-review-fr-label]');
    const tbtLabel = context.querySelector('[data-review-tbt-label]');
    const testPathInputLabel = context.querySelector('[data-review-test-path-input-label]');
    if (isGeneratedDraft) {
      const isExistingAsvs = isExistingAsvsCard(card);
      const isReviewScaffold = isReviewRequiredScaffold(card) && !isExistingAsvs;
      if (operationLabel) operationLabel.textContent = isReviewScaffold ? 'Review decision' : 'Run decision';
      if (frLabel) frLabel.textContent = 'FR';
      if (tbtLabel) tbtLabel.textContent = 'TBT';
      if (testPathInputLabel) testPathInputLabel.textContent = isReviewScaffold ? 'Draft test path' : isExistingAsvs ? 'Existing test path' : 'Approved test path';
      const generatedOptions = isReviewScaffold ? [
        {value: 'approve_for_implementation', label: 'Approve for implementation'},
        {value: 'send_back_to_review', label: 'Send back to review'},
        {value: 'blocked', label: 'Blocked'}
      ] : [
        {value: 'approve_to_run', label: 'Approved to run'},
        {value: 'send_back_to_review', label: 'Send back to review'},
        {value: 'blocked', label: 'Blocked'}
      ];
      setSelectOptions(op, generatedOptions, data.decision || (laneOf(card) === 'import' ? 'approve_to_run' : 'send_back_to_review'));
    } else {
      if (operationLabel) operationLabel.textContent = 'Mapping decision';
      if (frLabel) frLabel.textContent = 'Suggested FR';
      if (tbtLabel) tbtLabel.textContent = 'Suggested TBT';
      if (testPathInputLabel) testPathInputLabel.textContent = isPlannedTbt ? 'Manual test path' : 'Manual test path';
      setSelectOptions(op, [
        {value: 'accept_recommendation', label: 'Accept recommendation'},
        {value: 'remap_as_orphan', label: 'Clear mapping / remap as orphan'},
        {value: 'leave_unmapped', label: 'Leave unmapped'},
        {value: 'mark_not_assurance_relevant', label: 'Mark not assurance relevant'},
        {value: 'needs_new_tbt_fr', label: 'Needs new TBT/FR'},
        {value: 'blocked', label: 'Blocked'}
      ], data.decision || (data.selector ? 'accept_recommendation' : 'leave_unmapped'));
    }
    if (fr) fr.value = (data.target || '').split('/')[0]?.trim() || '';
    if (tbt) tbt.value = (data.target || '').split('/')[1]?.trim() || '';
    if (isGeneratedDraft) {
      if (fr) fr.value = data.frs || (data.target || '').split('/')[0]?.trim() || '';
      if (tbt) tbt.value = data.tbt || (data.target || '').split('/')[1]?.trim() || '';
    }
    if (testPath) testPath.value = data.manual_test_path || (isGeneratedDraft ? data.pack_path : '');
    if (note) note.value = data.reviewer_note || '';
  }
  function syncCardDecisionForLane(card, laneId) {
    if (!card) return;
    if (laneId === 'map' || laneId === 'recommended') {
      delete card.dataset.reviewDecision;
      return;
    }
    if (laneId === 'specify') {
      const targetParts = targetPartsForCard(card);
      const hasMappingTarget = Boolean(targetParts.fr || targetParts.tbt || card.dataset.recommendation || meaningfulText(card.dataset.agenticRationale));
      card.dataset.reviewDecision = hasMappingTarget ? 'accept_recommendation' : 'needs_new_tbt_fr';
      return;
    }
    if (laneId === 'review') {
      card.dataset.reviewDecision = 'send_back_to_review';
      return;
    }
    if (laneId === 'import') {
      card.dataset.reviewDecision = 'approve_to_run';
      return;
    }
    if (laneId === 'blocked') {
      card.dataset.reviewDecision = 'blocked';
    }
  }
  function moveCardToLane(card, laneId, options = {}) {
    const lane = board.querySelector(`[data-review-lane="${CSS.escape(laneId)}"] .review-board-dropzone`);
    if (!lane) return;
    if (options.syncDecision) syncCardDecisionForLane(card, laneId);
    lane.appendChild(card);
    state[card.dataset.reviewCard] = {...boardStateForCard(card), lane: laneId};
    saveState();
    refreshCardLabelsAndOrder();
    refreshCounts();
    refreshBoardOutputs();
  }
  function allowedDropLanes(card) {
    const current = laneOf(card);
    const flow = ['map', 'recommended', 'specify', 'review', 'import'];
    if (current === 'blocked') return flow.concat('blocked');
    const index = flow.indexOf(current);
    if (index < 0) return [current, 'blocked'];
    const allowed = new Set(flow.slice(0, index + 1));
    if (index + 1 < flow.length) allowed.add(flow[index + 1]);
    if (current === 'map') allowed.add('specify');
    allowed.add('blocked');
    return [...allowed];
  }
  function hasAgenticMappingRecommendation(card) {
    if (!card) return false;
    const targetParts = targetPartsForCard(card);
    const hasTarget = Boolean(targetParts.fr && targetParts.tbt);
    const hasOperation = Boolean(card.dataset.recommendation);
    const hasAgenticRationale = Boolean(meaningfulText(card.dataset.agenticRationale) || card.dataset.selector);
    return hasTarget && hasOperation && hasAgenticRationale;
  }
  function isPlannedTbtCard(card) {
    if (!card) return false;
    return String(card.dataset.source || '').toLowerCase() === 'planned_tbt' || String(card.dataset.status || '').toLowerCase() === 'planned';
  }
  function isGeneratedDraftCard(card) {
    if (!card) return false;
    const source = String(card.dataset.source || '').toLowerCase();
    return source === 'generated' || source === 'existing_asvs' || String(card.dataset.status || '').toLowerCase() === 'draft';
  }
  function isExistingAsvsCard(card) {
    return String(card?.dataset.source || '').toLowerCase() === 'existing_asvs';
  }
  function isReviewRequiredScaffold(card) {
    if (!card) return false;
    const source = String(card.dataset.source || '').toLowerCase();
    const safety = String(card.dataset.safety || '').toLowerCase();
    const assessment = String(card.dataset.assessment || '').toLowerCase();
    return (
      (source === 'generated' || source === 'existing_asvs') &&
      (safety === 'review_required' || assessment === 'needs_design')
    );
  }
  function hasPartialSupportScope(card) {
    if (!card) return false;
    const text = [
      card.dataset.agenticRationale,
      card.dataset.discoveryRationale,
      card.dataset.reviewerNote
    ].map(meaningfulText).join(' ');
    return /partial|blocked|unsupported|not found|not currently supported|missing/i.test(text);
  }
  function hasAgenticTestDraft(card) {
    if (!card) return false;
    const source = String(card.dataset.source || '').toLowerCase();
    const safety = String(card.dataset.safety || '').toLowerCase();
    const status = String(card.dataset.status || '').toLowerCase();
    if (isPlannedTbtCard(card)) return false;
    return (
      source === 'generated' ||
      source === 'existing_asvs' ||
      safety === 'review_required' ||
      status === 'draft'
    );
  }
  function isManifestReadyToRun(card) {
    if (!card) return false;
    const status = String(card.dataset.status || '').toLowerCase();
    const safety = String(card.dataset.safety || '').toLowerCase();
    return (status === 'ready_to_run' || status === 'executed') && safety === 'non_destructive';
  }
  function hasManualRunApproval(card) {
    if (!card || hasAgenticTestDraft(card)) return false;
    return Boolean(meaningfulText(card.dataset.manualTestPath) && meaningfulText(card.dataset.reviewerNote));
  }
  function hasGeneratedRunApproval(card) {
    if (!card || !hasAgenticTestDraft(card)) return false;
    if (isManifestReadyToRun(card)) return true;
    if (isReviewRequiredScaffold(card) && !isExistingAsvsCard(card)) return false;
    if (!meaningfulText(card.dataset.manualTestPath || card.dataset.packPath)) return false;
    if (isExistingAsvsCard(card) && card.dataset.reviewDecision !== 'approve_to_run') return false;
    if (isExistingAsvsCard(card) && !meaningfulText(card.dataset.reviewerNote)) return false;
    return !hasPartialSupportScope(card) || Boolean(meaningfulText(card.dataset.reviewerNote));
  }
  function canDropCard(card, laneId) {
    if (!card || !laneId) return false;
    if (laneId === 'map' && !isOrphanTestCard(card)) return false;
    if (laneId === 'recommended') {
      if (!hasAgenticMappingRecommendation(card)) return false;
    }
    if (laneId === 'review' && !hasAgenticTestDraft(card)) return false;
    if (laneId === 'import') {
      const current = laneOf(card);
      const allowedFromReview = current === 'review' && hasGeneratedRunApproval(card);
      const allowedManual = current === 'specify' && hasManualRunApproval(card);
      if (!allowedFromReview && !allowedManual) return false;
    }
    return allowedDropLanes(card).includes(laneId);
  }
  function clearDropState() {
    board.querySelectorAll('.review-board-lane').forEach(lane => {
      lane.classList.remove('is-over', 'is-blocked');
    });
  }
  function closeContext() {
    activeCard = null;
    board.querySelectorAll('[data-review-card]').forEach(item => item.classList.remove('is-selected'));
    if (workspace) {
      workspace.classList.remove('has-context', 'context-left', 'context-right');
      workspace.style.removeProperty('--review-context-top');
    }
    if (!context) return;
    const empty = context.querySelector('.review-context-empty');
    const body = context.querySelector('.review-context-body');
    if (empty) empty.hidden = false;
    if (body) body.hidden = true;
  }
  function updateCommand() {
    const lanes = selectedByLane();
    let map = lanes.map || [];
    let recommended = lanes.recommended || [];
    let specify = lanes.specify || [];
    let blocked = lanes.blocked || [];
    let review = lanes.review || [];
    let importLane = lanes.import || [];
    const lines = [];
    lastPromptCopyText = '';
    const mode = promptOverride?.mode || promptMode?.value || '';
    const action = promptOverride?.action || '';
    if (promptOverride?.items) {
      if (mode === 'map') {
        map = promptOverride.laneId === 'map' ? promptOverride.items : [];
        recommended = promptOverride.laneId === 'recommended' ? promptOverride.items : [];
      } else if (mode === 'specify') specify = promptOverride.items;
      else if (mode === 'review') review = promptOverride.items;
      else if (mode === 'import') importLane = promptOverride.items;
      else if (mode === 'blocked') blocked = promptOverride.items;
    }
    const runId = (reportDir.match(/reports\/([^/]+)\/?$/) || [])[1] || 'current';
    const frCatalog = reportDir.replace(/\/$/, '') + '/fr-catalog.snapshot.json';
    const assuranceTestPack = manifest;
    const mappingReviewPath = reportDir.replace(/\/$/, '') + '/native-test-mapping-review.md';
    const junitOutput = reportDir.replace(/\/$/, '') + '/approved-tbt-junit.xml';
    const dashboardScript = reportDir.replace(/\/reports\/[^/]+\/?$/, '/scripts/generate_dashboard.py');
    const refreshCommand = 'python3 ' + shellQuote(dashboardScript) + ' --report-dir ' + shellQuote(reportDir);
    const sourceRepo = inferSourceRepoFromReportDir(reportDir);
    const sourceMount = sourceRepo === '/path/to/project' ? '/path/to' : sourceRepo.replace(/\/[^/]+$/, '') || '/path/to';
    const project = inferProjectFromSourceRepo(sourceRepo);
    function selectedTbtList(items) {
      return [...new Set(items.map(card => card.tbt).filter(Boolean))].sort();
    }
    function selectedNativeList(items) {
      return [...new Set(items.map(card => card.native_path || card.title).filter(Boolean))].sort();
    }
    function nativeSummaryForCard(card) {
      return {
        pack_id: card.id || card.native_path || 'native-test',
        native_path: card.native_path || '',
        pack_path: card.pack_path || '',
        title: card.title || card.native_path || card.id || 'Native test',
        type: card.type || 'test',
        source: 'native',
        status: card.status || '',
        assessment: '',
        test_names: []
      };
    }
    function mappingHypothesisForCard(card) {
      const targetParts = String(card.target || '').split('/').map(part => part.trim()).filter(Boolean);
      return {
        native_test: card.native_path || card.id || 'native-test',
        requested_operation: card.decision || (card.selector ? 'map_native_test_to_existing_tbt' : 'leave_unmapped'),
        suggested_fr: targetParts.find(part => part.startsWith('FR-')) || '',
        suggested_tbt: targetParts.find(part => part.startsWith('TBT-')) || card.tbt || '',
        proposed_new_fr: '',
        proposed_new_tbt: '',
        assessor_rationale: card.reviewer_note || card.rationale || '',
        confidence: card.confidence || 'medium'
      };
    }
    function mapDecisionForCard(card) {
      const hypothesis = mappingHypothesisForCard(card);
      let operation = hypothesis.requested_operation;
      if (operation === 'accept_recommendation') operation = 'map_native_test_to_existing_tbt';
      if (operation === 'needs_new_tbt_fr') operation = hypothesis.suggested_fr ? 'create_tbt_under_existing_fr' : 'create_new_fr_and_tbt';
      if (operation === 'remap_as_orphan') operation = 'leave_unmapped';
      if (operation === 'blocked') operation = 'leave_unmapped';
      if (operation === 'map_native_test_to_existing_tbt' && (!hypothesis.suggested_fr || !hypothesis.suggested_tbt)) operation = 'leave_unmapped';
      const native = nativeSummaryForCard(card);
      const update = {
        operation,
        native_test: {
          pack_id: native.pack_id,
          native_path: native.native_path
        },
        review_status: 'proposed',
        source_basis: [
          {
            type: 'native_test',
            ref: native.native_path || native.pack_id
          }
        ],
        rationale: hypothesis.assessor_rationale || 'Assessor hypothesis requires source inspection before this native test can be mapped.',
        confidence: hypothesis.confidence || 'medium'
      };
      if (native.pack_path) update.native_test.pack_path = native.pack_path;
      if (operation === 'map_native_test_to_existing_tbt') {
        update.target = {fr: hypothesis.suggested_fr, tbt: hypothesis.suggested_tbt};
      } else if (operation === 'create_tbt_under_existing_fr') {
        update.target = {fr: hypothesis.suggested_fr};
        update.new_tbt = {
          id: hypothesis.proposed_new_tbt || 'TBT-REVIEW-REQUIRED',
          title: 'Review required native-test TBT',
          type: native.type || 'test',
          evidence_policy: 'automated_required',
          proves: [hypothesis.suggested_fr],
          expected_evidence: ['JUnit testcase or equivalent execution evidence carrying the TBT id']
        };
      } else if (operation === 'create_new_fr_and_tbt') {
        update.new_fr = {
          id: hypothesis.proposed_new_fr || 'FR-REVIEW-REQUIRED',
          title: 'Review required native-test FR',
          description: 'Assessor must define the functional requirement before applying this proposal.'
        };
        update.new_tbt = {
          id: hypothesis.proposed_new_tbt || 'TBT-REVIEW-REQUIRED',
          type: native.type || 'test',
          title: 'Review required native-test TBT',
          evidence_policy: 'automated_required',
          proves: [hypothesis.proposed_new_fr || 'FR-REVIEW-REQUIRED'],
          expected_evidence: ['JUnit testcase or equivalent execution evidence carrying the TBT id']
        };
      }
      return update;
    }
    function dashboardInspectionLines(kind) {
      const dashboardHtml = reportDir.replace(/\/$/, '') + '/dashboard.html';
      const dashboardNavCheckCode = [
        'from pathlib import Path',
        'import re',
        'html = Path(' + JSON.stringify(dashboardHtml) + ').read_text(errors="ignore")',
        "tabs = re.findall(r'<button class=\"tab-btn\" data-tab=\"([^\"]+)\">', html)",
        'print("left view buttons:", len(tabs), tabs)',
        'raise SystemExit(0 if len(tabs) >= 7 else 1)'
      ].join('; ');
      const impact = {
        map: [
          '- Apply or save the accepted config update proposal through the config-update workflow.',
          '- Validate the proposal, render a human review brief, list selectable entries, then apply only reviewed selections to explicit reviewed output files.',
          '- Regenerate the current dashboard HTML for this same report using the exact refresh command below. Do not hand-edit dashboard.html or run a partial renderer.',
          '- Confirm mapped native tests no longer appear as unresolved Map rows, or remain explicitly review-required with rationale.'
        ],
        design: [
          '- Save the generated TBT specs/scaffolds into the report-local generated test pack.',
          '- Regenerate the current dashboard HTML for this same report.',
          '- Confirm selected TBTs move from Draft Tests for FR toward Review Agentic Tests, or remain blocked with assumptions recorded.'
        ],
        approve: [
          '- Save implemented approved tests under tests/asvs/ and update the report-local generated test pack metadata.',
          '- Regenerate the current dashboard HTML for this same report.',
          '- Confirm implemented tests are ready for Run Approved Tests and unresolved draft risks remain visible.'
        ],
        import: [
          '- Rerun the scan with the JUnit XML or supported evidence artifact imported.',
          '- Open the newly generated dashboard for that scan.',
          '- Confirm evidence changes are visible in Project FRs, Compliance Regime, Traceability Graph, and Evidence Files.'
        ]
      };
      lines.push('');
      lines.push('After completion: update and inspect dashboard impact');
      (impact[kind] || []).forEach(line => lines.push(line));
      lines.push('- Inspect Project FR board lane counts, Project FR status, Compliance Regime status, Traceability Graph proof chain, and Evidence Files provenance.');
      lines.push('- Verify the left-side Views navigation still has all expected buttons; if the count drops, rerun the exact refresh command and do not report success.');
      lines.push('- Report what changed, which rows/TBTs/FRs moved state, and what remains blocked.');
      lines.push('');
      lines.push('Current-report dashboard refresh command, when no fresh scan is required:');
      lines.push(refreshCommand);
      lines.push('');
      lines.push('Post-refresh navigation sanity check:');
      lines.push('python3 -c ' + shellQuote(dashboardNavCheckCode));
    }
    function addRefreshLines(kind) {
      dashboardInspectionLines(kind);
    }
    function addMapPrompt(items) {
      const nativeList = selectedNativeList(items);
      const nativeSummaries = items.map(nativeSummaryForCard);
      const mappingHypotheses = items.map(mappingHypothesisForCard);
      const nativeUpdates = items.map(mapDecisionForCard);
      const draftProposal = {
        schema_version: 1,
        mode: 'config_update_proposal',
        project,
        run_id: runId,
        source_inputs: [
          {path: 'fr-catalog.snapshot.json', kind: 'fr_catalog', used_for: 'Existing FR/TBT choices for native test mapping'},
          {path: 'generated-tests/VG_TEST_FRAMEWORK/manifest.json', kind: 'assurance_test_pack', used_for: 'Native test candidates requiring mapping'}
        ],
        fr_catalog_updates: [],
        compliance_mapping_pack_updates: [],
        assurance_framework_or_instance_updates: [],
        manual_evidence_updates: [],
        native_test_mapping_updates: nativeUpdates,
        uncertain_mappings: nativeUpdates
          .filter(update => update.operation === 'leave_unmapped' || update.operation === 'mark_not_assurance_relevant' || update.confidence === 'low')
          .map(update => ({
            kind: 'native_test_mapping',
            refs: [update.native_test.native_path || update.native_test.pack_id],
            candidates: [update.target?.fr, update.target?.tbt].filter(Boolean),
            question: 'Which FR/TBT, if any, does this native test actually prove after source inspection?',
            why: 'Native test mappings are assessor hypotheses until the test source and generated manifest context show a clear proof relationship.'
          })),
        review_required: [
          {
            item: 'native-test-mapping',
            question: 'Do the selected native tests really prove the proposed FR/TBT targets?',
            why: 'Native tests must be mapped by assessor review before they can become assurance evidence.'
          }
        ]
      };
      lines.push('Assurance Config Update Prompt');
      lines.push('');
      lines.push('Mission:');
      lines.push('Review the selected native test evidence and produce a typed config update proposal that maps each native test to the correct FR/TBT assurance chain.');
      lines.push('');
      lines.push('Context:');
      lines.push('- Project: ' + project);
      lines.push('- Scan run: ' + runId);
      lines.push('- Source repository: ' + sourceRepo);
      lines.push('- FR catalog: ' + frCatalog);
      lines.push('- Assurance test manifest: ' + reportDir + '/generated-tests/VG_TEST_FRAMEWORK/manifest.json');
      lines.push('- Copied/imported native tests are under: ' + reportDir + '/generated-tests/VG_TEST_FRAMEWORK/');
      lines.push('- Selected native tests: ' + (nativeList.join(', ') || 'none'));
      lines.push('');
      lines.push('Selected native-test manifest context:');
      lines.push(JSON.stringify(nativeSummaries, null, 2));
      lines.push('');
      lines.push('Assessor hypotheses from the Map Orphan Tests lane:');
      lines.push(JSON.stringify(mappingHypotheses, null, 2));
      lines.push('');
      lines.push('Rules:');
      lines.push('1. Do not modify application source code.');
      lines.push('2. Do not invent product behaviour, endpoints, roles, data shapes, or evidence.');
      lines.push('3. Treat any selected FR/TBT or new FR/TBT id as an assessor hypothesis, not an accepted mapping.');
      lines.push('4. Inspect each selected native test source file and the generated test manifest before accepting, changing, or rejecting a mapping.');
      lines.push('5. Prefer mapping to an existing FR/TBT only when the test behaviour clearly proves that target.');
      lines.push('6. If the suggested target is wrong but another existing FR/TBT fits, propose that better existing target and explain the mismatch.');
      lines.push('7. Create a new TBT under an existing FR only when the FR is correct but no current TBT captures the evidence type.');
      lines.push('8. Create a new FR only when the native test proves a real product requirement that is absent from the catalog.');
      lines.push('9. Use leave_unmapped or mark_not_assurance_relevant when the proof relationship is unclear or absent.');
      lines.push('10. Preserve provenance: cite native path, copied pack path, manifest case names, rationale, confidence, and assumptions.');
      lines.push('11. Do not return the placeholder rationale unchanged. Every selected native test must end with a post-inspection disposition and a specific rationale.');
      lines.push('');
      lines.push('Expected output:');
      lines.push('- Return one JSON document matching config-update-proposal.schema.json.');
      lines.push('- Keep all ids stable and type-safe: FR ids use FR-xxx; TBT ids use TBT-xxx.');
      lines.push('- For new FR proposals include at minimum id, title, description, status/category if known, and the source basis.');
      lines.push('- For new TBT proposals include at minimum id, title, type, proves, evidence_policy, expected_evidence, and how JUnit or equivalent evidence will carry the TBT id.');
      lines.push('- Include review_required entries for every non-obvious or low-confidence mapping.');
      lines.push('- Return the JSON in the response and save the same JSON to the report-local proposal path below so the dashboard can display recommendations before any mapping is accepted.');
      lines.push('- Proposal path: ' + proposal);
      lines.push('- Review brief path: ' + mappingReviewPath);
      lines.push('');
      lines.push('Draft proposal to review and refine:');
      lines.push('');
      lines.push(JSON.stringify(draftProposal, null, 2));
      lines.push('');
      lines.push('Validation command:');
      lines.push('asvs-scanner validate-config-update ' + shellQuote(proposal) + ' --fr-catalog ' + shellQuote(frCatalog));
      lines.push('');
      lines.push('Review and apply commands after validation:');
      lines.push('asvs-scanner review-config-update ' + shellQuote(proposal) + ' --output ' + shellQuote(mappingReviewPath));
      lines.push('asvs-scanner apply-config-update ' + shellQuote(proposal) + ' --list');
      lines.push('asvs-scanner apply-config-update ' + shellQuote(proposal) + ' --select <section:index> --reviewed-by <name> --assurance-test-pack ' + shellQuote(assuranceTestPack) + ' --assurance-test-pack-out ' + shellQuote(assuranceTestPack));
      lines.push('For current-dashboard inspection, the assurance-test-pack output above intentionally replaces this report-local manifest after validation and human-reviewed selection.');
      lines.push('If selected entries affect other sections, add the matching reviewed input/output flags, such as --fr-catalog/--fr-catalog-out, --compliance-mapping-pack/--compliance-mapping-pack-out, --assurance-test-pack/--assurance-test-pack-out, or --assurance-instance/--assurance-instance-out.');
      addRefreshLines('map');
    }
    function addSpecifyPrompt(items) {
      const tbtList = selectedTbtList(items);
      lines.push('Assurance Test Specification Prompt');
      lines.push('');
      lines.push('Mission:');
      lines.push('Generate review-required draft tests/specifications for the selected planned TBTs by inspecting the project source and existing test patterns. This is a specification step only; it must not claim evidence, create ready-to-run tests, or modify product behaviour.');
      lines.push('');
      lines.push('Context:');
      lines.push('- Scan run: ' + runId);
      lines.push('- Source repository: ' + sourceRepo);
      lines.push('- Report directory: ' + reportDir);
      lines.push('- FR catalog: ' + frCatalog);
      lines.push('- Selected TBTs: ' + (tbtList.join(', ') || 'none'));
      lines.push('- Existing test conventions: inspect package scripts, Jest/Vitest or integration-test config, existing tests, relevant application code, and runtime configuration before drafting.');
      lines.push('');
      lines.push('Selected board cards:');
      lines.push(JSON.stringify(items, null, 2));
      lines.push('');
      lines.push('Rules:');
      lines.push('1. Use the FR catalog and report artifacts as the source of truth.');
      lines.push('2. Generate only review-required draft tests/specifications for the selected TBTs.');
      lines.push('3. Do not implement broad test suites or invent product endpoints, roles, data shapes, or expected behaviour.');
      lines.push('4. Prefer safe, non-destructive tests using disposable fixtures or mocks.');
      lines.push('5. Every generated draft test must keep the TBT id in the file name, test title, and future JUnit classname or testcase name.');
      lines.push('6. Mark each draft test as review_required until a human approves it. Skipped scaffolds are review artifacts, not executable assurance evidence.');
      lines.push('7. Do not count generated draft tests as passing evidence.');
      lines.push('8. Use tests/asvs/ as the ASVS-owned execution surface for generated tests and wrappers; do not duplicate existing native tests there unless writing a reviewed wrapper.');
      lines.push('9. Inspect the real implementation before drafting. If the codebase cannot currently support the FR/TBT behaviour, do not invent a test; report that the FR is not currently supported by the project and explain the missing implementation, endpoint, configuration, or observable behaviour.');
      lines.push('10. If there is not enough source evidence to create a safe review draft, do not create a runnable test scaffold. Report the blocked disposition clearly so a reviewer can move the card to Blocked or adjust the FR/TBT.');
      lines.push('11. For each selected TBT, report one disposition: draft_created_full, draft_created_partial_support, blocked_unsupported_by_project, blocked_insufficient_source_evidence, or blocked_needs_human_decision.');
      lines.push('12. If only part of the FR/TBT is supportable, create a review-required draft only for the observable portion and explicitly list the unsupported portions. Do not let a partial draft imply full FR/TBT coverage.');
      lines.push('');
      lines.push('Expected output:');
      lines.push('- Generate/update only the selected draft test files under the generated test pack, using tests/asvs/<type>/<TBT-ID>.assurance.test.js, for example tests/asvs/integration/TBT-016-ASVS-A.assurance.test.js.');
      lines.push('- Preserve provenance back to FR/TBT/ruleset rows.');
      lines.push('- Include the per-TBT disposition in the scaffold/spec metadata and in the final response.');
      lines.push('- Summarize inspected files, assumptions, unknowns, and any project-support gap that requires human review.');
      lines.push('- For partial support, list the observable behaviour covered by the draft and the unsupported FR/TBT behaviours that remain blocked.');
      lines.push('- If the FR/TBT is not currently supported by the project, explicitly say so, do not run promote-assurance-specs for that TBT, and persist or propose a blocked board-state update rather than creating false assurance coverage.');
      lines.push('- After draft tests are generated, rerun or refresh the dashboard to move them into Review Agentic Tests.');
      lines.push('');
      lines.push('Order of operations:');
      lines.push('1. Inspect the source repository first.');
      lines.push('2. Identify the actual implementation, configuration, existing tests, and safe test harness for each selected FR/TBT.');
      lines.push('3. Decide whether each selected FR/TBT is currently supportable by observable project behaviour.');
      lines.push('4. Only run promote-assurance-specs or write a draft scaffold if the implementation can support a safe review-required test/specification.');
      lines.push('5. If unsupported, do not generate a runnable scaffold; report a blocked disposition explaining that the FR/TBT is not currently supported by observable project behaviour.');
      lines.push('');
      lines.push('Blocked-state persistence when no scaffold should be generated:');
      lines.push('- Write or update project-fr-board-state.json through update-project-fr-board-state using the selected card id.');
      lines.push('- Keep source, tbt, frs, type, status, assessment, safety, pack_path, and discovery_rationale from the selected card.');
      lines.push('- Set lane to blocked, decision to blocked, and reviewer_note to the disposition plus the inspected-source reason.');
      lines.push('- Refresh the dashboard after saving the board state so the blocked reason is visible in the current report.');
      lines.push('Command template after writing blocked-board-state.json:');
      lines.push('asvs-scanner update-project-fr-board-state ' + shellQuote(reportDir) + ' --state-json blocked-board-state.json --strict --refresh-dashboard');
      lines.push('');
      lines.push('Command to generate selected draft tests only after source inspection confirms the FR/TBT is supportable:');
      lines.push('asvs-scanner promote-assurance-specs ' + shellQuote(reportDir) + (tbtList.length ? ' \\' : ''));
      tbtList.forEach((tbt, idx) => lines.push('  --tbt ' + shellQuote(tbt) + (idx === tbtList.length - 1 ? '' : ' \\')));
      addRefreshLines('design');
    }
    function addReviewPrompt(items) {
      const tbtList = selectedTbtList(items);
      lines.push('Approved Assurance Test Implementation Prompt');
      lines.push('');
      lines.push('Mission:');
      lines.push('Implement only the selected human-approved assurance draft tests so they become executable ASVS-owned tests. This step creates runnable tests; it must not claim evidence or import results.');
      lines.push('');
      lines.push('Context:');
      lines.push('- Project: ' + project);
      lines.push('- Source repository: ' + sourceRepo);
      lines.push('- Report directory: ' + reportDir);
      lines.push('- FR catalog: ' + frCatalog);
      lines.push('- Approved TBTs: ' + (tbtList.join(', ') || 'none'));
      lines.push('- Future JUnit output when the Run Approved Tests lane is used: ' + junitOutput);
      lines.push('');
      lines.push('Selected board cards:');
      lines.push(JSON.stringify(items, null, 2));
      lines.push('');
      lines.push('Rules:');
      lines.push('1. Implement only selected generated draft tests that have been explicitly approved for implementation.');
      lines.push('2. Do not invent product endpoints, behaviour, roles, or data shapes.');
      lines.push('3. Use disposable fixtures and a safe/containerized test environment.');
      lines.push('4. Keep the TBT id in the file name, test title, and JUnit classname or testcase name.');
      lines.push('5. Do not modify product/application behaviour. Limit changes to ASVS-owned tests, wrappers, fixtures, mocks, or test harness configuration.');
      lines.push('6. Do not run destructive operations against real data or shared services.');
      lines.push('7. Keep ASVS-owned executable tests and wrappers under tests/asvs/; native project tests remain source-of-truth in their original paths.');
      lines.push('8. A selected card may still show review_required/needs_design at the start of this prompt. If it has decision: approve_for_implementation, treat that as human approval to implement only the approved scope.');
      lines.push('9. If a selected card lacks decision: approve_for_implementation or an explicit reviewer approval note, do not implement it; report the blocker instead.');
      lines.push('10. Remove describe.skip, test.skip, TODO(review-required), and review-only blockers only for the approved TBT scope. Preserve blocked notes for unsupported FR/TBT behaviour.');
      lines.push('11. Do not export or import JUnit evidence in this step; evidence belongs to the Run Approved Tests lane after the implemented test is reviewed as runnable.');
      lines.push('');
      lines.push('Expected output:');
      lines.push('- Implement the selected draft tests only under tests/asvs/ in the ASVS branch/worktree.');
      lines.push('- Update the report-local generated test pack metadata so implemented tests use status: ready_to_run, assessment: useful_as_is, and safety: non_destructive. Do not use status: executed until observed result evidence exists.');
      lines.push('- Run only lightweight local validation if needed to prove the test harness is wired; do not treat that as assurance evidence.');
      lines.push('- Report implemented tests, skipped/unimplemented tests, assumptions, and any manual follow-up.');
      lines.push('- Regenerate the current dashboard so implemented tests can move to Run Approved Tests.');
      lines.push('');
      lines.push('Selected board cards must include human approval:');
      lines.push('- Preferred review decision: approve_for_implementation.');
      lines.push('- If approval is only recorded in reviewer_note, cite it in the final report.');
      lines.push('- If no selected card is approved, stop and report that there is nothing safe to implement.');
      addRefreshLines('approve');
    }
    function addImportPrompt(items) {
      const tbtList = selectedTbtList(items);
      const hasReviewedExistingAsvs = items.some(item => String(item.source || '').toLowerCase() === 'existing_asvs');
      const runnerLines = [
        'docker run --rm -it \\',
        '  -v /var/run/docker.sock:/var/run/docker.sock \\',
        '  -v ' + shellQuote('/Users/jd/Development/asvs-scanner') + ':' + shellQuote('/opt/asvs-scanner') + ' \\',
        '  -v ' + shellQuote(sourceMount) + ':' + shellQuote(sourceMount) + ' \\',
        '  -w ' + shellQuote(sourceRepo) + ' \\',
        '  asvs-scanner:local run-approved-tests ' + shellQuote(reportDir) + ' \\',
        '  --source-repo ' + shellQuote(sourceRepo) + ' \\',
        '  --execution-mode docker \\',
        '  --test-container-image ' + shellQuote('node:20') + ' \\',
        '  --junit-out ' + shellQuote(reportDir.replace(/\/$/, '') + '/reports/junit.xml') + (hasReviewedExistingAsvs || tbtList.length ? ' \\' : '')
      ];
      if (hasReviewedExistingAsvs) {
        runnerLines.push('  --allow-reviewed-existing-asvs' + (tbtList.length ? ' \\' : ''));
      }
      tbtList.forEach((tbt, idx) => runnerLines.push('  --tbt ' + shellQuote(tbt) + (idx === tbtList.length - 1 ? '' : ' \\')));
      const refreshLines = [
        'docker run --rm -it --entrypoint python3 \\',
        '  -v /var/run/docker.sock:/var/run/docker.sock \\',
        '  -v ' + shellQuote('/Users/jd/Development/asvs-scanner') + ':' + shellQuote('/opt/asvs-scanner') + ' \\',
        '  -v ' + shellQuote(sourceMount) + ':' + shellQuote(sourceMount) + ' \\',
        '  -w ' + shellQuote(sourceRepo) + ' \\',
        '  asvs-scanner:local /opt/asvs-scanner/scripts/refresh-approved-test-evidence.py ' + shellQuote(reportDir) + ' \\',
        '  --junit-xml ' + shellQuote(reportDir.replace(/\/$/, '') + '/reports/junit.xml')
      ];
      const importLines = [
        'docker run --rm -it \\',
        '  -e ASVS_IMAGE_BUILD_PARALLELISM=2 \\',
        '  -e ASVS_PARALLELISM=4 \\',
        '  -v /var/run/docker.sock:/var/run/docker.sock \\',
        '  -v ' + shellQuote(sourceMount) + ':' + shellQuote(sourceMount) + ' \\',
        '  -w ' + shellQuote(sourceRepo) + ' \\',
        '  asvs-scanner:local scan ' + shellQuote(sourceRepo) + ' \\',
        '  --fr-catalog ' + shellQuote(frCatalog) + ' \\',
        '  --junit-xml ' + shellQuote(reportDir.replace(/\/$/, '') + '/reports/junit.xml')
      ];
      const fastLines = runnerLines.slice();
      if (fastLines.length) fastLines[fastLines.length - 1] = fastLines[fastLines.length - 1] + ' && \\';
      const fastCommand = fastLines.concat(refreshLines).join('\n');
      const freshCommand = importLines.join('\n');
      lastPromptCopyText = action === 'fresh-scan' ? freshCommand : fastCommand;
      lines.push('Run Approved Tests');
      lines.push('');
      if (action === 'fresh-scan') {
        lines.push('Import evidence / fresh scan');
        lines.push('');
        lines.push('Use this after reports/junit.xml already exists and you want a new immutable scan report with the observed JUnit imported into the assurance graph.');
        lines.push('');
        importLines.forEach(line => lines.push(line));
        lines.push('');
        lines.push('This creates a new report directory and browser-only Kanban state resets because it is a fresh scan.');
      } else if (action === 'run-only') {
        lines.push('Run tests only');
        lines.push('');
        lines.push('Use this to run the selected TBT tests and refresh this report without rerunning Semgrep, Trivy, image scans, or other scanner outputs.');
        lines.push('');
        fastCommand.split('\n').forEach(line => lines.push(line));
        lines.push('');
        lines.push('This writes reports/junit.xml, refreshes evidence-bundle.json/dashboard.html in this report, and preserves the current board state.');
      } else {
        lines.push('Fast path: run selected tests only and refresh this report');
        lines.push('');
        lines.push('Use this when you want to see the selected TBT evidence update in Project FRs, Compliance Regime, Traceability Graph, and Evidence Files without rerunning Semgrep/Trivy/etc.');
        lines.push('');
        fastCommand.split('\n').forEach(line => lines.push(line));
        lines.push('');
        lines.push('Fresh scan path: run selected tests, then import their JUnit into a new full scanner report');
        lines.push('');
        lines.push('Use this when you want a new immutable scan report with scanner outputs refreshed as well.');
        lines.push('');
        importLines.forEach(line => lines.push(line));
        lines.push('');
        lines.push('The copy button copies the fast path. The runner refuses non-ready tests and skipped scaffolds. The fresh scan path resets browser-only Kanban state because it creates a new report.');
      }
    }
    function addBlockedPrompt(items) {
      lines.push('Blocked / Review Required Prompt');
      lines.push('');
      lines.push('Mission:');
      lines.push('Record why these assurance cards cannot advance and identify the missing evidence, source inspection, product decision, or safer test design needed.');
      lines.push('');
      lines.push('Selected board cards:');
      lines.push(JSON.stringify(items, null, 2));
      addRefreshLines('map');
    }
    if (mode === 'map') addMapPrompt(map.concat(recommended));
    else if (mode === 'specify') addSpecifyPrompt(specify);
    else if (mode === 'review') addReviewPrompt(review);
    else if (mode === 'import') addImportPrompt(importLane);
    else if (mode === 'blocked') addBlockedPrompt(blocked);
    else return '';
    lines.push('');
    lines.push('Tip: moving a card only changes this board state in your browser. Assurance changes happen only after the generated prompt or command is run and a refreshed scan/dashboard is produced.');
    const text = lines.join('\n');
    if (commandEl) commandEl.textContent = text;
    return text;
  }
  function emptyLaneMessage(laneId, title) {
    const messages = {
      map: [
        'This lane is empty.',
        '',
        'If you run this prompt now, the agent has no existing/native tests to inspect, so no FR/TBT mapping proposal will be produced.',
        '',
        'Move unmapped native tests into this lane first.'
      ],
      recommended: [
        'This lane is empty.',
        '',
        'If you open this review now, there are no agent mapping recommendations for a human to approve.',
        '',
        'Run the Map Orphan Tests prompt, then move agent-recommended mappings into this lane.'
      ],
      specify: [
        'This lane is empty.',
        '',
        'If you run this prompt now, the agent has no FR/TBT cards to create tests for, so no draft tests will be produced.',
        '',
        'Move reviewed mappings or missing-coverage cards into this lane first.'
      ],
      review: [
        'This lane is empty.',
        '',
        'If you open this review now, there are no agent-generated draft tests for a human to approve.',
        '',
        'Run the Draft Tests for FR prompt, then move generated drafts with review-required test files into this lane.'
      ],
      import: [
        'This lane is empty.',
        '',
        'Run Approved Tests has two paths once at least one ready_to_run card is here:',
        '',
        'Fast path: run selected tests only and refresh this report.',
        '- Writes reports/junit.xml.',
        '- Refreshes evidence-bundle.json, dashboard-payload.json, dashboard.html, Project FRs, Compliance Regime, Traceability Graph, and Evidence Files.',
        '- Does not rerun Semgrep, Trivy, image scans, or other scanner outputs.',
        '',
        'Fresh scan path: run selected tests, then import their JUnit into a new full scanner report.',
        '- Creates a new report directory.',
        '- Refreshes scanner outputs as well as the JUnit-backed assurance graph.',
        '- Browser-only Kanban state resets because it is a new report.',
        '',
        'No command is shown yet because the runner requires at least one selected TBT. Move approved agentic drafts here after review, or manually approved cards after adding a test file path and reviewer rationale.'
      ],
      blocked: [
        'This lane is empty.',
        '',
        'If you run this prompt now, there are no blocked cards for the agent to diagnose.',
        '',
        'Move cards here only when they cannot advance without more evidence, source inspection, or a product decision.'
      ]
    };
    return (messages[laneId] || ['This lane is empty.', '', 'No useful action can run until cards are moved into ' + title + '.']).join('\n');
  }
  function openLanePrompt(laneId, action = '') {
    if (!promptDrawer || !promptDrawerBody) return;
    closeContext();
    const mode = promptModeForLane(laneId);
    const picked = pickedCardsForLane(laneId);
    const all = cardsForLane(laneId);
    const scopedCards = picked.length ? picked : all;
    const scopedItems = scopedCards.map(cardData);
    const title = laneTitle(laneId);
    const usingSelected = picked.length > 0;
    if (!scopedItems.length) {
      delete promptDrawer.dataset.copyText;
      promptDrawerBody.textContent = emptyLaneMessage(laneId, title);
      if (promptDrawerTitle) promptDrawerTitle.textContent = title + ' is empty';
      if (promptDrawerScope) promptDrawerScope.textContent = 'No cards are available in this lane.';
      if (promptDrawerWarning) {
        promptDrawerWarning.hidden = false;
        promptDrawerWarning.textContent = 'No prompt, review brief, or command will be useful until this lane contains cards.';
      }
      if (promptDrawerCopy) promptDrawerCopy.textContent = 'Copy note';
      promptDrawer.hidden = false;
      return;
    }
    if (mode === 'reviewMappingBrief') {
      delete promptDrawer.dataset.copyText;
      promptDrawerBody.textContent = reviewBriefForLane(laneId, scopedItems);
      if (promptDrawerTitle) promptDrawerTitle.textContent = title + ' Review';
      if (promptDrawerScope) {
        promptDrawerScope.textContent = (usingSelected ? 'Reviewing ' + scopedItems.length + ' selected card' : 'Reviewing all ' + scopedItems.length + ' card') + (scopedItems.length === 1 ? '' : 's') + ' from this lane.';
      }
      if (promptDrawerWarning) promptDrawerWarning.hidden = true;
      if (promptDrawerCopy) promptDrawerCopy.textContent = 'Copy review brief';
      promptDrawer.hidden = false;
      return;
    }
    promptOverride = {mode, laneId, action, items: scopedItems};
    const promptText = updateCommand();
    promptOverride = null;
    promptDrawerBody.textContent = promptText || '';
    if (lastPromptCopyText) promptDrawer.dataset.copyText = lastPromptCopyText;
    else delete promptDrawer.dataset.copyText;
    if (promptDrawerTitle) {
      promptDrawerTitle.textContent = laneId === 'import' && action === 'run-only'
        ? title + ': Tests only'
        : laneId === 'import' && action === 'fresh-scan'
        ? title + ': Full scan'
        : title + ' Prompt';
    }
    if (promptDrawerCopy) promptDrawerCopy.textContent = laneId === 'import' ? 'Copy command' : 'Copy prompt';
    if (promptDrawerScope) {
      promptDrawerScope.textContent = (usingSelected ? 'Using ' + scopedItems.length + ' selected card' : 'Using all ' + scopedItems.length + ' card') + (scopedItems.length === 1 ? '' : 's') + ' from this lane.';
    }
    if (promptDrawerWarning) {
      const isLargeSpecify = laneId === 'specify' && scopedItems.length > 8;
      promptDrawerWarning.hidden = !isLargeSpecify;
      if (isLargeSpecify) promptDrawerWarning.textContent = 'Large prompt: ' + scopedItems.length + ' TBTs selected. Consider selecting 3-5 related cards for a focused agent session.';
    }
    promptDrawer.hidden = false;
  }
  function boardStateSaveCommand() {
    const sourceRepo = inferSourceRepoFromReportDir(reportDir);
    const sourceMount = sourceRepo === '/path/to/project' ? '/path/to' : sourceRepo.replace(/\/[^/]+$/, '') || '/path/to';
    const payload = JSON.stringify(currentBoardStateDocument(), null, 2);
    return [
      'docker run --rm -i \\',
      '  -v /var/run/docker.sock:/var/run/docker.sock \\',
      '  -v ' + shellQuote('/Users/jd/Development/asvs-scanner') + ':' + shellQuote('/opt/asvs-scanner') + ' \\',
      '  -v ' + shellQuote(sourceMount) + ':' + shellQuote(sourceMount) + ' \\',
      '  -w ' + shellQuote(sourceRepo) + ' \\',
      '  asvs-scanner:local update-project-fr-board-state ' + shellQuote(reportDir) + ' \\',
      '  --state-json - \\',
      '  --strict \\',
      "  --refresh-dashboard <<'JSON'",
      payload,
      'JSON'
    ].join('\n');
  }
  function openBoardStateSaveCommand() {
    if (!promptDrawer || !promptDrawerBody) return;
    closeContext();
    const command = boardStateSaveCommand();
    promptDrawerBody.textContent = [
      'Save Project FR Board State',
      '',
      'Run this command to persist the current Kanban lanes, decisions, reviewer notes, targets, and manual test paths into project-fr-board-state.json.',
      '',
      command,
      '',
      'After it completes, reload this dashboard tab. The persisted state is hash-recorded in the report manifest and will survive dashboard regeneration.'
    ].join('\n');
    promptDrawer.dataset.copyText = command;
    if (promptDrawerTitle) promptDrawerTitle.textContent = 'Save Board State';
    if (promptDrawerScope) promptDrawerScope.textContent = 'Persists all cards currently visible on the Project FR board.';
    if (promptDrawerWarning) promptDrawerWarning.hidden = true;
    if (promptDrawerCopy) promptDrawerCopy.textContent = 'Copy command';
    promptDrawer.hidden = false;
  }
  board.querySelectorAll('[data-review-board-tab]').forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.reviewBoardTab;
      board.querySelectorAll('[data-review-board-tab]').forEach(item => item.classList.toggle('active', item === tab));
      board.querySelectorAll('[data-review-board-pane]').forEach(pane => {
        pane.classList.toggle('active', pane.dataset.reviewBoardPane === target);
      });
    });
  });
  if (promptMode) {
    promptMode.addEventListener('change', updateCommand);
  }
  board.querySelectorAll('[data-review-lane-prompt]').forEach(btn => {
    btn.addEventListener('click', event => {
      event.stopPropagation();
      openLanePrompt(btn.dataset.reviewLanePrompt || '', btn.dataset.reviewLaneAction || '');
    });
  });
  if (saveBoardStateBtn) {
    saveBoardStateBtn.addEventListener('click', event => {
      event.stopPropagation();
      saveState();
      openBoardStateSaveCommand();
    });
  }
  board.querySelectorAll('[data-review-card]').forEach(card => {
    const pickBtn = card.querySelector('[data-review-card-pick]');
    if (pickBtn) {
      pickBtn.setAttribute('aria-pressed', 'false');
      pickBtn.addEventListener('click', event => {
        event.stopPropagation();
        setCardPicked(card, !card.classList.contains('is-picked'));
      });
    }
    card.addEventListener('click', () => {
      if (activeCard === card) closeContext();
      else selectCard(card);
    });
    card.addEventListener('dragstart', event => {
      updateCardLabel(card);
      card.classList.add('is-dragging');
      draggingCard = card;
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', card.dataset.reviewCard || '');
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('is-dragging');
      draggingCard = null;
      clearDropState();
    });
  });
  board.querySelectorAll('[data-review-lane]').forEach(lane => {
    const dropzone = lane.querySelector('.review-board-dropzone');
    lane.addEventListener('dragover', event => {
      if (!draggingCard) return;
      event.preventDefault();
      const allowed = canDropCard(draggingCard, lane.dataset.reviewLane);
      event.dataTransfer.dropEffect = allowed ? 'move' : 'none';
      lane.classList.toggle('is-over', allowed);
      lane.classList.toggle('is-blocked', !allowed);
    });
    lane.addEventListener('dragleave', event => {
      if (!lane.contains(event.relatedTarget)) lane.classList.remove('is-over', 'is-blocked');
    });
    lane.addEventListener('drop', event => {
      event.preventDefault();
      lane.classList.remove('is-over', 'is-blocked');
      const id = event.dataTransfer.getData('text/plain');
      const card = board.querySelector(`[data-review-card="${CSS.escape(id)}"]`);
      if (!card || !dropzone) return;
      if (!canDropCard(card, lane.dataset.reviewLane)) {
        lane.classList.add('is-blocked');
        window.setTimeout(() => lane.classList.remove('is-blocked'), 520);
        selectCard(card);
        return;
      }
      moveCardToLane(card, lane.dataset.reviewLane, {syncDecision: true});
      selectCard(card);
    });
  });
  const applyContextBtn = context ? context.querySelector('[data-review-apply-context]') : null;
  const closeContextBtn = context ? context.querySelector('[data-review-context-close]') : null;
  if (closeContextBtn) closeContextBtn.addEventListener('click', closeContext);
  if (applyContextBtn) {
    applyContextBtn.addEventListener('click', () => {
      if (!activeCard || !context) return;
      const decision = context.querySelector('[data-review-map-operation]')?.value || 'leave_unmapped';
      const fr = context.querySelector('[data-review-map-fr]')?.value || '';
      const tbt = context.querySelector('[data-review-map-tbt]')?.value || '';
      const testPath = context.querySelector('[data-review-test-path]')?.value || '';
      const note = context.querySelector('[data-review-map-note]')?.value || '';
      activeCard.dataset.reviewDecision = decision;
      activeCard.dataset.reviewerNote = note;
      activeCard.dataset.manualTestPath = testPath;
      if (fr || tbt) activeCard.dataset.target = [fr, tbt].filter(Boolean).join(' / ');
      refreshCardLabelsAndOrder();
      const targetBox = activeCard.querySelector('.review-board-card-target');
      if (targetBox) targetBox.textContent = activeCard.dataset.target || decision.replace(/_/g, ' ');
      const laneMap = {
        accept_recommendation: 'specify',
        remap_as_orphan: 'map',
        leave_unmapped: 'blocked',
        mark_not_assurance_relevant: 'blocked',
        needs_new_tbt_fr: 'specify',
        approve_for_implementation: 'review',
        approve_to_run: 'import',
        send_back_to_review: 'review',
        blocked: 'blocked'
      };
      const nextLane = laneMap[decision] || 'blocked';
      if (nextLane === 'import' && !canDropCard(activeCard, 'import')) {
        activeCard.dataset.reviewDecision = 'send_back_to_review';
        moveCardToLane(activeCard, 'review');
      } else {
        moveCardToLane(activeCard, nextLane);
      }
      closeContext();
      refreshBoardOutputs();
    });
  }
  if (promptDrawerClose && promptDrawer) {
    promptDrawerClose.addEventListener('click', closePromptDrawer);
  }
  if (promptDrawerCopy && promptDrawerBody) {
    promptDrawerCopy.addEventListener('click', () => {
      const text = promptDrawer.dataset.copyText || promptDrawerBody.textContent || '';
      const done = () => {
        const original = promptDrawerCopy.textContent;
        promptDrawerCopy.textContent = 'Copied';
        setTimeout(() => { promptDrawerCopy.textContent = original; }, 1400);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done).catch(done);
      else done();
    });
  }
  applyStoredState();
  updateCommand();
}
setupReviewBoard();
function copyPrompt(bodyId, btn) {
  btn = btn || document.querySelector('.copy-btn');
  const label = btn.querySelector('.btn-label');
  const original = label.textContent;
  const body = document.getElementById(bodyId || 'fix-prompt-body');
  const text = body ? body.innerText : '';
  const done = () => { label.textContent = 'Copied'; btn.classList.add('copied'); setTimeout(() => { label.textContent = original; btn.classList.remove('copied'); }, 1600); };
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(done).catch(fallback);
  else fallback();
  function fallback() { const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); done(); }
}
