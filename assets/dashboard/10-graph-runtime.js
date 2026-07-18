// ===== Traceability graph =====
function setupGraph() {
  var graphDataEl = document.getElementById('graph-data');
  var canvas = document.getElementById('graph-canvas');
  var detailPanel = document.getElementById('graph-detail');
  var legendPanel = document.getElementById('graph-legend');
  var summaryPanel = document.getElementById('graph-summary');
  var banner = document.getElementById('graph-banner');
  if (!graphDataEl || !canvas) return;
  if (typeof d3 === 'undefined') {
    canvas.innerHTML = '<div class="empty-state">Graph library unavailable. Connect to the network or vendor D3 for offline reports; the rest of the dashboard is still usable.</div>';
    return;
  }

  var data;
  try { data = JSON.parse(graphDataEl.textContent || '{"nodes":[],"edges":[]}'); }
  catch (_) { return; }
  if (!data.nodes || !data.nodes.length) {
    canvas.innerHTML = '<div class="empty-state">No traceability links were found in this FR catalog.</div>';
    return;
  }

  var controls = {
    entryType: document.getElementById('graph-entry-type'),
    entryId: document.getElementById('graph-entry-id'),
    ruleset: document.getElementById('graph-ruleset-filter'),
    chapter: document.getElementById('graph-chapter-filter'),
    scanner: document.getElementById('graph-scanner-filter'),
    status: document.getElementById('graph-status-filter'),
    load: document.getElementById('graph-load-btn')
  };
  var graphDetailOpen = false;
  var graphSelectedDetailId = null;
  var softCap = (data.meta && data.meta.soft_cap) || 500;
  var nodeById = new Map(data.nodes.map(function(n) { return [n.id, n]; }));
  var adj = new Map();
  data.edges.forEach(function(e) {
    if (!adj.has(e.source)) adj.set(e.source, []);
    if (!adj.has(e.target)) adj.set(e.target, []);
    adj.get(e.source).push({node: e.target, edge: e});
    adj.get(e.target).push({node: e.source, edge: e});
  });

  var typeColors = {
    fr: '#56c7b7', file: '#b794f4', scanner_rule: '#f6ad55',
    ruleset_row: '#8fcbe8', domain: '#8fcbe8', evidence: '#718096', tbt: '#35d07f',
    process: '#8fcbe8', gate: '#ffd166', criterion: '#ff98a9', role: '#d2dfda',
    approval: '#ffd166', waiver: '#718096', compensating_control: '#f6ad55', decision: '#d2dfda',
    blueprint: '#b794f4', planning_artifact: '#c4d8e0'
  };
  var edgeColors = {
    satisfies: '#56c7b7',
    proves: '#35d07f',
    produced_by: '#718096',
    implements: '#b794f4',
    maps_to: '#56c7b7',
    requires: '#f6ad55',
    assigned_to: '#ffd166',
    blocks: '#ff98a9',
    evidences: '#718096',
    applies_to: '#8fcbe8',
    derived_from: '#b794f4',
    approved_by: '#ffd166',
    waived_by: '#718096',
    depends_on_process: '#8fcbe8'
  };
  var asvsChapterNames = {
    V1: 'Encoding and Injection Prevention',
    V2: 'Authentication',
    V3: 'Session Management',
    V4: 'Access Control',
    V5: 'Validation, Sanitization and Encoding',
    V6: 'Stored Cryptography',
    V7: 'Error Handling and Logging',
    V8: 'Data Protection',
    V9: 'Communications',
    V10: 'Malicious Code',
    V11: 'Business Logic',
    V12: 'File and Resources',
    V13: 'API and Web Service',
    V14: 'Configuration',
    V15: 'Requirements',
    V16: 'Architecture',
    V17: 'Supply Chain'
  };
  var nistFamilyNames = {
    AC: 'Access Control',
    AT: 'Awareness and Training',
    AU: 'Audit and Accountability',
    CA: 'Assessment, Authorization, and Monitoring',
    CM: 'Configuration Management',
    CP: 'Contingency Planning',
    IA: 'Identification and Authentication',
    IR: 'Incident Response',
    MA: 'Maintenance',
    MP: 'Media Protection',
    PE: 'Physical and Environmental Protection',
    PL: 'Planning',
    PM: 'Program Management',
    PS: 'Personnel Security',
    PT: 'PII Processing and Transparency',
    RA: 'Risk Assessment',
    SA: 'System and Services Acquisition',
    SC: 'System and Communications Protection',
    SI: 'System and Information Integrity',
    SR: 'Supply Chain Risk Management'
  };
  function esc(value) {
    return String(value || '').replace(/[&<>"']/g, function(ch) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch];
    });
  }
  function nodeText(n) {
    if (!n) return '';
    if (n.type === 'fr') return (n.fr_id || 'FR') + ' · ' + n.label;
    if (n.type === 'ruleset_row') return n.ruleset + ' ' + n.row;
    if (n.type === 'gate') return 'Gate ' + (n.sequence || '') + ' · ' + n.label;
    if (n.type === 'criterion') return n.criterion_id + ' · ' + n.label;
    if (n.type === 'role') return n.label;
    if (n.tbt) return n.tbt + ' · ' + (n.label || n.ref || 'test');
    return n.label || n.id;
  }
  function nodeKindLabel(n) {
    if (!n) return 'NODE';
    if (n.overviewSummary) return 'MORE';
    if (n.type === 'fr') return 'FR';
    if (n.type === 'ruleset_row') return n.ruleset || 'ROW';
    if (n.type === 'domain') return 'DOMAIN';
    if (n.type === 'process') return 'PROCESS';
    if (n.type === 'gate') return 'GATE';
    if (n.type === 'criterion') return 'CRITERION';
    if (n.type === 'role') return 'ROLE';
    if (n.type === 'scanner_rule') return 'SCANNER';
    if (n.type === 'file') return 'CODE';
    if (n.type === 'evidence') return (n.evidence_type || 'EVIDENCE').toUpperCase();
    if (n.type === 'tbt') return 'TEST';
    return String(n.type || 'NODE').toUpperCase();
  }
  function shortNodeLabel(n, maxLen) {
    var txt = nodeText(n);
    return txt.length > maxLen ? txt.substring(0, maxLen - 3) + '...' : txt;
  }
  function splitLabel(value, maxLen, maxLines) {
    var words = String(value || '').split(/\s+/).filter(Boolean);
    var lines = [];
    var current = '';
    words.forEach(function(word) {
      var parts = [];
      while (word.length > maxLen) {
        parts.push(word.slice(0, maxLen - 1) + '...');
        word = word.slice(maxLen - 1);
      }
      parts.push(word);
      parts.forEach(function(part) {
        if (!current) current = part;
        else if ((current + ' ' + part).length <= maxLen) current += ' ' + part;
        else { lines.push(current); current = part; }
      });
    });
    if (current) lines.push(current);
    if (!lines.length) lines = [''];
    if (lines.length > maxLines) {
      lines = lines.slice(0, maxLines);
      lines[lines.length - 1] = lines[lines.length - 1].replace(/\.*$/, '') + '...';
    }
    return lines;
  }
  function edgeLabel(type) {
    return String(type || '')
      .replace(/^requires_/, 'requires ')
      .replace(/_/g, ' ');
  }
  function isRulesetRowNode(n) {
    return n && n.type === 'ruleset_row';
  }
  function isTbtNode(n) {
    return n && n.type === 'tbt';
  }
  function isProofNode(n) {
    return n && (n.type === 'tbt' || n.type === 'scanner_rule' || n.type === 'evidence');
  }
  function showBanner(text) {
    if (!banner) return;
    banner.textContent = text || '';
    banner.hidden = !text;
  }
  function uniqueSorted(values) {
    return Array.from(new Set(values.filter(Boolean))).sort(function(a, b) {
      var an = Number(String(a).replace(/^[A-Za-z]+/, ''));
      var bn = Number(String(b).replace(/^[A-Za-z]+/, ''));
      if (!Number.isNaN(an) && !Number.isNaN(bn) && an !== bn) return an - bn;
      return String(a).localeCompare(String(b));
    });
  }
  function addOptions(select, values, allLabel) {
    if (!select) return;
    select.innerHTML = '<option value="">' + allLabel + '</option>';
    values.forEach(function(v) {
      var opt = document.createElement('option');
      opt.value = v;
      opt.textContent = select === controls.chapter ? chapterOptionLabel(v) : rulesetOptionLabel(v);
      select.appendChild(opt);
    });
  }
  function rulesetOptionLabel(value) {
    if (!value) return 'All compliance regimes';
    if (value === 'ASVS') return 'ASVS';
    if (value === 'NIST-800-53') return 'NIST 800-53';
    return value;
  }
  function chapterOptionLabel(value) {
    var selectedRuleset = controls.ruleset ? controls.ruleset.value : '';
    var chapter = value;
    var ruleset = selectedRuleset;
    if (!ruleset && String(value).indexOf(':') >= 0) {
      var parts = String(value).split(':');
      ruleset = parts[0];
      chapter = parts.slice(1).join(':');
    }
    var prefix = selectedRuleset ? '' : (ruleset ? rulesetOptionLabel(ruleset) + ' ' : '');
    if (ruleset === 'ASVS' && asvsChapterNames[chapter]) return prefix + chapter + ' · ' + asvsChapterNames[chapter];
    if (ruleset === 'NIST-800-53' && nistFamilyNames[chapter]) return prefix + chapter + ' · ' + nistFamilyNames[chapter];
    return prefix + chapter;
  }
  function chapterValueForNode(node) {
    if (!node || !node.chapter) return '';
    var ruleset = controls.ruleset ? controls.ruleset.value : '';
    return ruleset ? node.chapter : (node.ruleset || '') + ':' + node.chapter;
  }
  function chapterMatches(node, selectedChapter) {
    if (!selectedChapter) return true;
    return chapterValueForNode(node) === selectedChapter || node.chapter === selectedChapter;
  }
  function rowsForRuleset() {
    var ruleset = controls.ruleset ? controls.ruleset.value : '';
    return rowNodes.filter(function(n) { return !ruleset || n.ruleset === ruleset; });
  }
  function refreshChapterOptions() {
    if (!controls.chapter) return;
    var previous = controls.chapter.value;
    var ruleset = controls.ruleset ? controls.ruleset.value : '';
    var values = uniqueSorted(rowsForRuleset().map(function(n) { return ruleset ? n.chapter : chapterValueForNode(n); }));
    addOptions(controls.chapter, values, ruleset ? 'All chapters / families' : 'All chapters / families');
    if (previous && values.indexOf(previous) >= 0) controls.chapter.value = previous;
  }
  function addNodeOptions(select, nodes, emptyLabel) {
    if (!select) return;
    select.innerHTML = '';
    if (!nodes.length) {
      var opt = document.createElement('option');
      opt.value = '';
      opt.textContent = emptyLabel || 'No entries available';
      opt.disabled = true;
      opt.selected = true;
      select.appendChild(opt);
      return;
    }
    nodes.slice().sort(function(a, b) { return nodeText(a).localeCompare(nodeText(b)); }).forEach(function(n) {
      var opt = document.createElement('option');
      opt.value = n.id;
      opt.textContent = nodeText(n);
      select.appendChild(opt);
    });
  }
  function nodeMeta(node, key, fallback) {
    if (!node) return fallback;
    if (node[key] !== undefined && node[key] !== null && node[key] !== '') return node[key];
    if (node.metadata && node.metadata[key] !== undefined && node.metadata[key] !== null && node.metadata[key] !== '') return node.metadata[key];
    return fallback;
  }
  function isScannerEvidence(node) {
    return Boolean(node && node.type === 'evidence' && (
      nodeMeta(node, 'evidence_type', '') === 'scanner_result' ||
      String(node.id || '').indexOf('evidence:scanner:') === 0 ||
      String(node.id || '').indexOf('evidence:scanner-general:') === 0
    ));
  }
  function scannerEvidenceBlocks(record) {
    if (!record) return false;
    var status = String(nodeMeta(record, 'status', record.status || '')).toLowerCase();
    var role = String(nodeMeta(record, 'evidence_role', '')).toLowerCase();
    var effect = String(nodeMeta(record, 'assurance_effect', '')).toLowerCase();
    var mappingLevel = String(nodeMeta(record, 'mapping_level', '')).toLowerCase();
    return status === 'failed' && (
      role.indexOf('blocking') >= 0 ||
      effect.indexOf('blocking') >= 0 ||
      mappingLevel === 'compliance_row'
    );
  }

  var frNodes = data.nodes.filter(function(n) { return n.type === 'fr'; });
  var rowNodes = data.nodes.filter(function(n) { return isRulesetRowNode(n); });
  var scannerEvidenceNodes = data.nodes.filter(isScannerEvidence);
  var unmappedScannerEvidenceNodes = scannerEvidenceNodes.filter(function(n) {
    return nodeMeta(n, 'mapping_level', '') === 'general_finding' ||
      nodeMeta(n, 'traceability_strength', '') === 'unmapped' ||
      String(n.id || '').indexOf('evidence:scanner-general:') === 0;
  });
  var directScannerBlockerNodes = scannerEvidenceNodes.filter(scannerEvidenceBlocks);
  var mappedScannerEvidenceNodes = scannerEvidenceNodes.filter(function(n) {
    return nodeMeta(n, 'mapping_level', '') === 'compliance_row';
  });
  var domainScannerEvidenceNodes = scannerEvidenceNodes.filter(function(n) {
    return nodeMeta(n, 'mapping_level', '') === 'compliance_domain';
  });
  var processNodes = data.nodes.filter(function(n) { return n.type === 'process'; });
  var gateNodes = data.nodes.filter(function(n) { return n.type === 'gate'; });
  var criterionNodes = data.nodes.filter(function(n) { return n.type === 'criterion'; });

  function renderGraphSummary() {
    if (!summaryPanel) return;
    var tbtNodes = data.nodes.filter(isTbtNode);
    var evidenceNodes = data.nodes.filter(function(n) { return n.type === 'evidence'; });
    var activeFilters = [];
    if (controls.ruleset && controls.ruleset.value) activeFilters.push(rulesetOptionLabel(controls.ruleset.value));
    if (controls.chapter && controls.chapter.value) activeFilters.push(chapterOptionLabel(controls.chapter.value));
    if (controls.scanner && controls.scanner.value) activeFilters.push(controls.scanner.value);
    if (controls.status && controls.status.value) activeFilters.push(controls.status.value + ' evidence');
    function action(label, value, meta, actionName, tone) {
      return '<button type="button" class="graph-summary-item graph-summary-action graph-summary-' + esc(tone || 'default') + '" data-graph-summary-action="' + esc(actionName) + '">' +
        '<strong>' + esc(value) + '</strong><span>' + esc(label) + '</span>' + (meta ? '<em>' + esc(meta) + '</em>' : '') + '</button>';
    }
    function stat(label, value, meta, tone) {
      return '<div class="graph-summary-item graph-summary-' + esc(tone || 'default') + '">' +
        '<strong>' + esc(value) + '</strong><span>' + esc(label) + '</span>' + (meta ? '<em>' + esc(meta) + '</em>' : '') + '</div>';
    }
    summaryPanel.innerHTML =
      '<div class="graph-summary-copy"><strong>Runtime graph</strong><span>' +
      esc(data.nodes.length + ' nodes · ' + data.edges.length + ' edges' + (activeFilters.length ? ' · filters: ' + activeFilters.join(', ') : '')) +
      '</span></div>' +
      '<div class="graph-summary-grid">' +
      stat('Assurance chains', frNodes.length + ' FR', tbtNodes.length + ' TBT · ' + rowNodes.length + ' rows', 'chain') +
      stat('Evidence nodes', evidenceNodes.length, scannerEvidenceNodes.length + ' scanner-derived', 'evidence') +
      action('Direct blockers', directScannerBlockerNodes.length, 'failed mapped scanner evidence', 'scanner-blockers', directScannerBlockerNodes.length ? 'fail' : 'pass') +
      action('Mapped scanner', mappedScannerEvidenceNodes.length, domainScannerEvidenceNodes.length + ' domain signals', 'scanner-impact', 'scanner') +
      action('Unmapped scanner', unmappedScannerEvidenceNodes.length, 'inventory only', 'scanner-unmapped', unmappedScannerEvidenceNodes.length ? 'warn' : 'pass') +
      action('Complete overview', data.nodes.length, 'capped and clustered by stage', 'complete', 'default') +
      '</div>';
    summaryPanel.querySelectorAll('[data-graph-summary-action]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var actionName = btn.dataset.graphSummaryAction;
        if (actionName === 'scanner-blockers' || actionName === 'scanner-impact') {
          if (controls.entryType) controls.entryType.value = 'scannerImpact';
          if (controls.status && actionName === 'scanner-blockers') controls.status.value = 'failed';
        } else if (actionName === 'scanner-unmapped') {
          if (controls.entryType) controls.entryType.value = 'scannerUnmapped';
        } else if (actionName === 'complete') {
          if (controls.entryType) controls.entryType.value = 'complete';
        }
        populateEntries();
        renderCurrent();
      });
    });
  }
  addOptions(controls.ruleset, uniqueSorted(rowNodes.map(function(n) { return n.ruleset; })), 'All compliance regimes');
  refreshChapterOptions();
  addOptions(controls.scanner, uniqueSorted(data.nodes.filter(function(n) { return n.type === 'scanner_rule' || (n.type === 'evidence' && n.evidence_type === 'scanner_result'); }).map(function(n) { return n.scanner; })), 'All scanners');
  if (controls.entryType) {
    Array.from(controls.entryType.options).forEach(function(opt) {
      var count = opt.value === 'fr' ? frNodes.length :
        opt.value === 'row' ? rowNodes.length :
        opt.value === 'scannerImpact' ? scannerEvidenceNodes.length :
        opt.value === 'scannerUnmapped' ? unmappedScannerEvidenceNodes.length :
        opt.value === 'process' ? processNodes.length :
        opt.value === 'gate' ? gateNodes.length :
        opt.value === 'gateProof' ? gateNodes.length :
        opt.value === 'complete' ? data.nodes.length :
        opt.value === 'criterion' ? criterionNodes.length : 0;
      if (!count) opt.disabled = true;
      opt.textContent = opt.textContent.replace(/\s+\(\d+\)$/, '') + ' (' + count + ')';
    });
    if (controls.entryType.selectedOptions[0] && controls.entryType.selectedOptions[0].disabled) {
      var firstEnabled = Array.from(controls.entryType.options).find(function(opt) { return !opt.disabled; });
      if (firstEnabled) controls.entryType.value = firstEnabled.value;
    }
  }

  function populateEntries() {
    if (!controls.entryId) return;
    var entryType = controls.entryType ? controls.entryType.value : 'fr';
    var nodes = frNodes;
    if (entryType === 'row') {
      var selectedChapter = controls.chapter ? controls.chapter.value : '';
      nodes = rowsForRuleset().filter(function(n) { return chapterMatches(n, selectedChapter); });
    }
    else if (entryType === 'scannerImpact') nodes = scannerEvidenceNodes;
    else if (entryType === 'scannerUnmapped') nodes = unmappedScannerEvidenceNodes;
    else if (entryType === 'process') nodes = processNodes;
    else if (entryType === 'gate' || entryType === 'gateProof') nodes = gateNodes;
    else if (entryType === 'criterion') nodes = criterionNodes;
    if (entryType === 'complete') {
      controls.entryId.disabled = true;
      controls.entryId.innerHTML = '<option value="">All filtered nodes</option>';
      return;
    }
    controls.entryId.disabled = false;
    addNodeOptions(controls.entryId, nodes, 'No ' + entryType + ' entries available');
  }
  populateEntries();
  renderGraphSummary();

  function edgeKey(e) {
    var source = typeof e.source === 'object' ? e.source.id : e.source;
    var target = typeof e.target === 'object' ? e.target.id : e.target;
    return e.key || (source + '->' + target + ':' + e.type);
  }
  function sourceId(e) { return typeof e.source === 'object' ? e.source.id : e.source; }
  function targetId(e) { return typeof e.target === 'object' ? e.target.id : e.target; }

  function bfs(seedIds, maxDepth, fanout) {
    var visited = new Map();
    var edgeKeys = new Set();
    var queue = seedIds.filter(Boolean).map(function(id) {
      visited.set(id, 0);
      return {id: id, depth: 0};
    });
    while (queue.length) {
      var cur = queue.shift();
      if (cur.depth >= maxDepth) continue;
      var neighbors = (adj.get(cur.id) || []).slice(0, fanout);
      neighbors.forEach(function(nb) {
        edgeKeys.add(nb.edge.key || (nb.edge.source + '->' + nb.edge.target + ':' + nb.edge.type));
        if (!visited.has(nb.node)) {
          visited.set(nb.node, cur.depth + 1);
          queue.push({id: nb.node, depth: cur.depth + 1});
        }
      });
    }
    var nodes = data.nodes.filter(function(n) { return visited.has(n.id); });
    var nodeIds = new Set(nodes.map(function(n) { return n.id; }));
    var edges = data.edges.filter(function(e) {
      var source = sourceId(e);
      var target = targetId(e);
      return edgeKeys.has(edgeKey(e)) && nodeIds.has(source) && nodeIds.has(target);
    });
    return {nodes: nodes, edges: edges};
  }

  function rowProofGraph(focusId) {
    var focus = nodeById.get(focusId);
    if (!focus || !isRulesetRowNode(focus)) return applySoftCap(bfs([focusId], 3, 18));
    var keepNodes = new Set([focusId]);
    var keepEdges = new Set();
    var proofEdgeTypes = new Set(['requires', 'evidences', 'maps_to']);
    var rowToFrEdgeTypes = new Set(['satisfies', 'requires']);
    function addEdge(e) {
      keepEdges.add(edgeKey(e));
      keepNodes.add(sourceId(e));
      keepNodes.add(targetId(e));
    }
    var frIds = [];
    data.edges.forEach(function(e) {
      var s = sourceId(e), t = targetId(e);
      if (rowToFrEdgeTypes.has(e.type) && (s === focusId || t === focusId)) {
        var otherId = s === focusId ? t : s;
        var other = nodeById.get(otherId);
        if (other && other.type === 'fr') {
          addEdge(e);
          frIds.push(otherId);
        }
      }
    });

    frIds.forEach(function(frId) {
      data.edges.forEach(function(e) {
        var s = sourceId(e), t = targetId(e);
        if (s !== frId || !proofEdgeTypes.has(e.type)) return;
        var target = nodeById.get(t);
        if (!isProofNode(target)) return;
        addEdge(e);
      });
    });

    Array.from(keepNodes).forEach(function(nodeId) {
      var node = nodeById.get(nodeId);
      if (!(isProofNode(node) || isRulesetRowNode(node)) || node.type === 'evidence') return;
      data.edges.forEach(function(e) {
        if (sourceId(e) === nodeId && e.type === 'evidences') addEdge(e);
      });
    });

    var nodes = data.nodes.filter(function(n) { return keepNodes.has(n.id); });
    var edges = data.edges.filter(function(e) { return keepEdges.has(edgeKey(e)); });
    if (nodes.length <= 1) return applySoftCap(bfs([focusId], 2, 10));
    return {nodes: nodes, edges: edges};
  }

  function frProofGraph(focusId) {
    var focus = nodeById.get(focusId);
    if (!focus || focus.type !== 'fr') return applySoftCap(bfs([focusId], 2, 10));
    var keepNodes = new Set([focusId]);
    var keepEdges = new Set();
    var proofEdgeTypes = new Set(['satisfies', 'requires', 'evidences']);
    function addEdge(e) {
      keepEdges.add(edgeKey(e));
      keepNodes.add(sourceId(e));
      keepNodes.add(targetId(e));
    }
    function isFrProofNode(n) {
      return n && (isRulesetRowNode(n) || isProofNode(n));
    }
    data.edges.forEach(function(e) {
      var s = sourceId(e), t = targetId(e);
      if (s === focusId && proofEdgeTypes.has(e.type)) {
        var target = nodeById.get(t);
        if (isFrProofNode(target)) addEdge(e);
      } else if (t === focusId && e.type === 'satisfies') {
        var source = nodeById.get(s);
        if (isRulesetRowNode(source)) addEdge(e);
      }
    });
    Array.from(keepNodes).forEach(function(nodeId) {
      var node = nodeById.get(nodeId);
      if (!node || (node.type !== 'tbt' && node.type !== 'scanner_rule' && !isRulesetRowNode(node))) return;
      data.edges.forEach(function(e) {
        if (sourceId(e) === nodeId && e.type === 'evidences') addEdge(e);
      });
    });
    var nodes = data.nodes.filter(function(n) { return keepNodes.has(n.id); });
    var edges = data.edges.filter(function(e) { return keepEdges.has(edgeKey(e)); });
    if (nodes.length <= 1) return applySoftCap(bfs([focusId], 2, 10));
    return {nodes: nodes, edges: edges};
  }

  function scannerImpactGraph(focusId) {
    var scannerFilter = controls.scanner ? controls.scanner.value : '';
    var statusFilter = controls.status ? controls.status.value : '';
    var selected = focusId ? [nodeById.get(focusId)].filter(Boolean) : scannerEvidenceNodes.filter(function(n) {
      if (scannerFilter && n.scanner !== scannerFilter) return false;
      if (statusFilter && n.status !== statusFilter) return false;
      return true;
    }).slice(0, 16);
    var keepNodes = new Set();
    var impactLayers = new Map();
    var edgeKeys = new Set();
    var syntheticEdges = [];
    function addNode(id, layer) {
      var node = nodeById.get(id);
      if (!node) return null;
      keepNodes.add(id);
      if (layer !== undefined && !impactLayers.has(id)) impactLayers.set(id, layer);
      return node;
    }
    function addSynthetic(source, target, type) {
      if (!source || !target || source === target) return;
      var key = 'scanner-impact:' + source + '->' + target + ':' + type;
      if (edgeKeys.has(key)) return;
      edgeKeys.add(key);
      syntheticEdges.push({source: source, target: target, type: type, key: key});
    }
    function neighborsOf(id, predicate) {
      return (adj.get(id) || []).map(function(nb) { return nodeById.get(nb.node); }).filter(function(n) { return n && (!predicate || predicate(n)); });
    }
    function addRowImpact(row, sourceEvidenceId) {
      if (!row) return;
      addNode(row.id, 1);
      if (sourceEvidenceId) addSynthetic(sourceEvidenceId, row.id, 'maps_to');
      var frs = neighborsOf(row.id, function(n) { return n.type === 'fr'; });
      frs.forEach(function(fr) {
        addNode(fr.id, 3);
        addSynthetic(row.id, fr.id, 'satisfies');
      });
      var tests = neighborsOf(row.id, function(n) { return isTbtNode(n); });
      tests.forEach(function(test) {
        addNode(test.id, 2);
        addSynthetic(row.id, test.id, 'requires');
        frs.forEach(function(fr) {
          var linked = (adj.get(test.id) || []).some(function(nb) { return nb.node === fr.id; });
          if (linked) addSynthetic(test.id, fr.id, 'evidences');
        });
      });
    }
    selected.forEach(function(ev) {
      addNode(ev.id, 0);
      var rowOrDomains = neighborsOf(ev.id, function(n) { return isRulesetRowNode(n) || n.type === 'domain'; });
      var tests = neighborsOf(ev.id, function(n) {
        return isTbtNode(n);
      });
      rowOrDomains.forEach(function(row) {
        addRowImpact(row, ev.id);
      });
      tests.forEach(function(test) {
        addNode(test.id, 2);
        addSynthetic(ev.id, test.id, 'evidences');
        var rows = neighborsOf(test.id, function(n) { return isRulesetRowNode(n); });
        rows.forEach(function(row) {
          addRowImpact(row, ev.id);
        });
        var frs = neighborsOf(test.id, function(n) { return n.type === 'fr'; });
        frs.forEach(function(fr) {
          addNode(fr.id, 3);
          addSynthetic(test.id, fr.id, 'evidences');
        });
      });
    });
    var nodes = data.nodes.filter(function(n) { return keepNodes.has(n.id); }).map(function(n) {
      var copy = Object.assign({}, n);
      if (impactLayers.has(n.id)) copy.impactLayer = impactLayers.get(n.id);
      return copy;
    });
    if (!nodes.length) return {nodes: [], edges: [], mode: 'scannerImpact'};
    return {nodes: nodes, edges: syntheticEdges, mode: 'scannerImpact'};
  }

  function scannerUnmappedGraph(focusId) {
    var scannerFilter = controls.scanner ? controls.scanner.value : '';
    var selected = focusId ? [nodeById.get(focusId)].filter(Boolean) : unmappedScannerEvidenceNodes.filter(function(n) {
      return !scannerFilter || n.scanner === scannerFilter;
    });
    var nodes = selected.map(function(n) {
      var copy = Object.assign({}, n);
      copy.impactLayer = 0;
      return copy;
    });
    return {nodes: nodes, edges: [], mode: 'scannerUnmapped'};
  }

  function gateProofGraph(focusId) {
    var focus = nodeById.get(focusId);
    if (!focus || focus.type !== 'gate') return applySoftCap(bfs([focusId], 3, 18));
    var keepNodes = new Set([focusId]);
    var keepEdges = new Set();
    var lanes = new Map([[focusId, 'gate']]);
    function addNode(id, lane) {
      if (!id || !nodeById.has(id)) return;
      keepNodes.add(id);
      if (lane && !lanes.has(id)) lanes.set(id, lane);
    }
    function addEdge(e) {
      keepEdges.add(edgeKey(e));
      keepNodes.add(sourceId(e));
      keepNodes.add(targetId(e));
    }
    function laneForEvidence(n) {
      var t = String((n && n.evidence_type) || '').toLowerCase();
      if (t === 'approval') return 'roles';
      if (t === 'manual' || t === 'document' || t === 'screenshot') return 'manual';
      return 'technical';
    }
    function laneForNode(n) {
      if (!n) return 'technical';
      if (n.type === 'role') return 'roles';
      if (n.type === 'criterion') return 'manual';
      if (n.type === 'evidence') return laneForEvidence(n);
      if (isRulesetRowNode(n) || n.type === 'fr' || n.type === 'scanner_rule' || isTbtNode(n)) return 'technical';
      return 'manual';
    }
    var criteria = [];
    data.edges.forEach(function(e) {
      if (sourceId(e) !== focusId) return;
      var target = nodeById.get(targetId(e));
      if (!target) return;
      if (e.type === 'requires' && target.type === 'criterion') {
        addEdge(e);
        addNode(target.id, 'manual');
        criteria.push(target.id);
      } else if (e.type === 'assigned_to' && target.type === 'role') {
        addEdge(e);
        addNode(target.id, 'roles');
      }
    });
    data.edges.forEach(function(e) {
      if (targetId(e) === focusId) {
        var source = nodeById.get(sourceId(e));
        if (source && source.type === 'process') {
          addEdge(e);
          addNode(source.id, 'gate');
        }
      }
    });
    criteria.forEach(function(criterionId) {
      data.edges.forEach(function(e) {
        if (sourceId(e) !== criterionId) return;
        var target = nodeById.get(targetId(e));
        if (!target) return;
        var lane = laneForNode(target);
        addEdge(e);
        addNode(target.id, lane);
      });
    });
    Array.from(keepNodes).forEach(function(nodeId) {
      var n = nodeById.get(nodeId);
      if (!n || n.type !== 'fr') return;
      data.edges.forEach(function(e) {
        var s = sourceId(e), t = targetId(e);
        var target = nodeById.get(t);
        if (t === nodeId && e.type === 'satisfies') {
          addEdge(e);
          addNode(s, 'technical');
        } else if (s === nodeId && (e.type === 'requires' || e.type === 'evidences')) {
          if (target && isProofNode(target)) {
            addEdge(e);
            addNode(t, 'technical');
          }
        }
      });
    });
    Array.from(keepNodes).forEach(function(nodeId) {
      var n = nodeById.get(nodeId);
      if (!n || (n.type !== 'scanner_rule' && !isTbtNode(n))) return;
      data.edges.forEach(function(e) {
        if (sourceId(e) === nodeId && e.type === 'evidences') {
          addEdge(e);
          addNode(targetId(e), 'technical');
        }
      });
    });
    var nodes = data.nodes.filter(function(n) { return keepNodes.has(n.id); }).map(function(n) {
      n.gateLane = lanes.get(n.id) || laneForNode(n);
      return n;
    });
    var edges = data.edges.filter(function(e) { return keepEdges.has(edgeKey(e)); });
    if (nodes.length <= 1) return applySoftCap(bfs([focusId], 3, 18));
    return {nodes: nodes, edges: edges, mode: 'gateProof', focusId: focusId};
  }

  function seedsForFilters() {
    var ruleset = controls.ruleset ? controls.ruleset.value : '';
    var chapter = controls.chapter ? controls.chapter.value : '';
    var scanner = controls.scanner ? controls.scanner.value : '';
    var status = controls.status ? controls.status.value : '';
    var seeds = frNodes.filter(function(n) {
      if (status && n.evidence_status !== status) return false;
      if (ruleset || chapter) {
        var linkedToRuleScope = (adj.get(n.id) || []).some(function(nb) {
          var node = nodeById.get(nb.node);
          return isRulesetRowNode(node) &&
            (!ruleset || node.ruleset === ruleset) &&
            chapterMatches(node, chapter);
        });
        if (!linkedToRuleScope) return false;
      }
      if (scanner) {
        var linkedToScanner = (adj.get(n.id) || []).some(function(nb) {
          var node = nodeById.get(nb.node);
          return node && (node.type === 'scanner_rule' || isScannerEvidence(node)) && node.scanner === scanner;
        });
        if (!linkedToScanner) return false;
      }
      return true;
    }).map(function(n) { return n.id; });
    if (!seeds.length && status === 'failed') {
      seeds = frNodes.filter(function(n) {
        if (ruleset || chapter) {
          return (adj.get(n.id) || []).some(function(nb) {
            var node = nodeById.get(nb.node);
            return isRulesetRowNode(node) &&
              (!ruleset || node.ruleset === ruleset) &&
              chapterMatches(node, chapter);
          });
        }
        return true;
      }).slice(0, 12).map(function(n) { return n.id; });
    }
    if (!seeds.length && processNodes.length) {
      seeds = processNodes.slice(0, 8).map(function(n) { return n.id; });
    }
    return seeds;
  }

  function applySoftCap(sub) {
    if (sub.nodes.length <= softCap) {
      showBanner('');
      return sub;
    }
    var keep = new Set(sub.nodes.slice(0, softCap).map(function(n) { return n.id; }));
    showBanner('Displaying ' + softCap + ' of ' + sub.nodes.length + ' nodes. Narrow the filters to see the full graph.');
    return {
      nodes: sub.nodes.filter(function(n) { return keep.has(n.id); }),
      edges: sub.edges.filter(function(e) {
        var source = typeof e.source === 'object' ? e.source.id : e.source;
        var target = typeof e.target === 'object' ? e.target.id : e.target;
        return keep.has(source) && keep.has(target);
      }),
      mode: sub.mode,
      focusId: sub.focusId
    };
  }

  function completeGraph() {
    return {nodes: data.nodes.slice(), edges: data.edges.slice(), mode: 'complete'};
  }

  function selectedEntryGraph() {
    var id = controls.entryId ? controls.entryId.value : '';
    var entryType = controls.entryType ? controls.entryType.value : 'fr';
    if (entryType === 'complete') return completeGraph();
    if (entryType === 'scannerImpact') return scannerImpactGraph(id);
    if (entryType === 'scannerUnmapped') return scannerUnmappedGraph(id);
    if (entryType === 'gateProof') return gateProofGraph(id);
    if (entryType === 'row') return rowProofGraph(id);
    if (entryType === 'fr') return frProofGraph(id);
    return applySoftCap(bfs(id ? [id] : seedsForFilters(), 3, 18));
  }
  function filteredGraph() {
    return applySoftCap(bfs(seedsForFilters(), 2, 22));
  }
  function nodeLayer(n) {
    if (!n) return 2;
    if (n.impactLayer !== undefined) return n.impactLayer;
    if (isRulesetRowNode(n)) return 0;
    if (n.type === 'fr') return 1;
    if (n.type === 'process') return 0;
    if (n.type === 'gate') return 1;
    if (n.type === 'criterion' || n.type === 'role') return 2;
    if (n.type === 'file' || n.type === 'scanner_rule' || isTbtNode(n)) return 3;
    if (n.type === 'evidence') return 4;
    return 3;
  }
  function layerLabel(layer) {
    return ['Compliance / Process', 'FRs / Gates', 'Criteria / Roles', 'Controls / Tests / Code', 'Evidence'][layer] || 'Linked';
  }
  function impactLayerLabel(layer) {
    var entryType = controls.entryType ? controls.entryType.value : '';
    if (entryType === 'scannerUnmapped') return ['Unmapped scanner findings'][layer] || 'Linked';
    return ['Scanner evidence', 'ASVS row / domain', 'TBT / test', 'FR'][layer] || 'Linked';
  }
  function orderKey(n) {
    if (n.type === 'gate') return String(n.sequence || '').padStart(4, '0') + ' ' + nodeText(n);
    if (n.type === 'evidence') {
      var rank = n.status === 'missing' ? '0' :
        (n.evidence_type === 'result' ? '1' :
        (n.evidence_type === 'manual' || n.evidence_type === 'document' || n.evidence_type === 'screenshot' ? '3' : '2'));
      return rank + ' ' + nodeText(n);
    }
    return nodeText(n);
  }
  function nodeCardWidth(n) {
    if (!n) return 172;
    if (n.type === 'criterion') return 210;
    if (isRulesetRowNode(n)) return 178;
    if (n.type === 'fr') return 204;
    if (n.type === 'evidence') return 188;
    if (n.type === 'file') return 196;
    return 178;
  }
  function nodeCardHeight(n) {
    if (!n) return 62;
    if (n.type === 'criterion' || n.type === 'fr') return 68;
    if (n.type === 'file' || n.type === 'evidence') return 62;
    return 58;
  }
  function layoutLayered(nodes, width, height) {
    var byLayer = new Map();
    nodes.forEach(function(n) {
      n.cardW = nodeCardWidth(n);
      n.cardH = nodeCardHeight(n);
      var layer = nodeLayer(n);
      if (!byLayer.has(layer)) byLayer.set(layer, []);
      byLayer.get(layer).push(n);
    });
    var layers = Array.from(byLayer.keys()).sort(function(a, b) { return a - b; });
    var widest = Math.max.apply(null, nodes.map(function(n) { return n.cardW || 178; }).concat([178]));
    var leftPad = Math.max(112, widest / 2 + 22);
    var rightPad = Math.max(190, widest / 2 + 90);
    var topPad = 82;
    var rowGap = 102;
    var evidenceGap = 124;
    var maxRows = Math.max.apply(null, layers.map(function(layer) { return byLayer.get(layer).length; }).concat([1]));
    var neededHeight = Math.max(height, topPad + 56 + (maxRows - 1) * evidenceGap);
    var maxSlot = Math.max(0, layers.length - 1);
    var layerX = {};
    layers.forEach(function(layer, slot) {
      var bucket = byLayer.get(layer).sort(function(a, b) { return orderKey(a).localeCompare(orderKey(b)); });
      var x = maxSlot === 0 ? leftPad : leftPad + ((width - leftPad - rightPad) * slot / maxSlot);
      layerX[layer] = x;
      var startY = topPad;
      var gap = layer === 4 ? evidenceGap : rowGap;
      bucket.forEach(function(n, idx) {
        n.x = x;
        n.y = startY + idx * gap;
      });
    });
    return {height: neededHeight, layers: layers, maxLayer: maxSlot, leftPad: leftPad, rightPad: rightPad, layerX: layerX};
  }

  function layoutGateProof(subData, width, height) {
    var laneDefs = [
      {id: 'technical', label: 'Technical compliance proof', baseHeight: 172, perRow: 4},
      {id: 'manual', label: 'Manual process proof', baseHeight: 198, perRow: 3},
      {id: 'roles', label: 'Roles and approvals', baseHeight: 198, perRow: 3}
    ];
    subData.nodes.forEach(function(n) {
      n.cardW = nodeCardWidth(n);
      n.cardH = nodeCardHeight(n);
    });
    var laneLeft = 550;
    var colGap = 304;
    var rowGap = 116;
    var laneGap = 44;
    var laneTop = 96;
    var neededWidth = width;
    var lanes = [];
    var laneBuckets = new Map();
    laneDefs.forEach(function(lane) {
      var bucket = subData.nodes.filter(function(n) { return n.gateLane === lane.id; })
        .sort(function(a, b) {
          var rank;
          if (lane.id === 'manual') {
            rank = {criterion: 0, evidence: 1};
          } else if (lane.id === 'roles') {
            rank = {role: 0, evidence: 1};
          } else {
            rank = {ruleset_row: 0, compliance: 0, fr: 1, scanner: 2, test: 2, unit: 2, integration: 2, e2e: 2, load: 2, evidence: 3};
          }
          var ar = Object.prototype.hasOwnProperty.call(rank, a.type) ? rank[a.type] : 5;
          var br = Object.prototype.hasOwnProperty.call(rank, b.type) ? rank[b.type] : 5;
          return (ar - br) || orderKey(a).localeCompare(orderKey(b));
        });
      if (!bucket.length) return;
      var rows = Math.max(1, Math.ceil(bucket.length / lane.perRow));
      var laneHeight = Math.max(lane.baseHeight, 96 + (rows - 1) * rowGap + 92);
      lane.height = laneHeight;
      lane.y = laneTop + laneHeight / 2;
      laneBuckets.set(lane.id, bucket);
      lanes.push(lane);
      laneTop += laneHeight + laneGap;
    });
    if (!lanes.length) {
      lanes = [{id: 'manual', label: 'Gate proof', baseHeight: 198, perRow: 3, height: 198, y: 196}];
    }
    var neededHeight = Math.max(height, laneTop + 72);
    var firstLaneTop = lanes.length ? lanes[0].y - lanes[0].height / 2 : 96;
    var firstLaneCenter = lanes.length ? lanes[0].y : 260;
    var gateNodesLocal = subData.nodes.filter(function(n) { return n.gateLane === 'gate'; })
      .sort(function(a, b) { return (a.type === 'process' ? -1 : 1) - (b.type === 'process' ? -1 : 1); });
    gateNodesLocal.forEach(function(n, idx) {
      n.x = 208;
      if (gateNodesLocal.length > 1) {
        n.y = n.type === 'process' ? firstLaneTop + 120 : firstLaneTop + 232;
      } else {
        n.y = firstLaneCenter;
      }
    });
    lanes.forEach(function(lane) {
      var bucket = laneBuckets.get(lane.id) || [];
      var perRow = lane.perRow || 3;
      var nodeTop = lane.y - lane.height / 2 + 74;
      bucket.forEach(function(n, idx) {
        var col = idx % perRow;
        var row = Math.floor(idx / perRow);
        n.x = laneLeft + col * colGap;
        n.y = nodeTop + row * rowGap;
        neededWidth = Math.max(neededWidth, n.x + (n.cardW || 180) / 2 + 50);
        neededHeight = Math.max(neededHeight, n.y + (n.cardH || 60) / 2 + 58);
      });
    });
    return {mode: 'gateProof', lanes: lanes, laneLeft: laneLeft, height: neededHeight, width: neededWidth};
  }

  function detailHtml(d) {
    if (!d) return '';
    function statusClass(status) {
      var s = String(status || '').replace(/[^a-z0-9_-]/gi, '_').toLowerCase();
      return 'graph-status-' + s;
    }
    function listHtml(items, formatter) {
      if (!Array.isArray(items) || !items.length) return '';
      return '<ul class="graph-action-list">' + items.slice(0, 8).map(function(item) {
        return '<li>' + (formatter ? formatter(item) : esc(item)) + '</li>';
      }).join('') + (items.length > 8 ? '<li><em>and ' + (items.length - 8) + ' more</em></li>' : '') + '</ul>';
    }
    function codePills(items) {
      if (!Array.isArray(items) || !items.length) return '';
      return '<div class="graph-chip-row">' + items.slice(0, 12).map(function(item) {
        return '<code class="fw-fr-link">' + esc(item) + '</code>';
      }).join('') + '</div>';
    }
    function artifactText(item) {
      if (!item) return '';
      if (typeof item === 'string') return item;
      var label = item.path || item.locator || item.source || item.id || JSON.stringify(item);
      return item.schema_ref ? (label + ' · schema: ' + item.schema_ref) : label;
    }
    function sideEffectText(item) {
      if (!item) return '';
      if (typeof item === 'string') return esc(item);
      var parts = [];
      if (item.type) parts.push(esc(String(item.type).replace(/_/g, ' ')));
      if (item.target) parts.push('<code>' + esc(item.target) + '</code>');
      if (item.mode) parts.push('<span class="manual-evidence">' + esc(String(item.mode).replace(/_/g, ' ')) + '</span>');
      if (item.description) parts.push('<span>' + esc(item.description) + '</span>');
      return parts.join(' ') || esc(JSON.stringify(item));
    }
    function evidenceIoHtml(record) {
      if (!record) return '';
      var metadata = record.metadata && typeof record.metadata === 'object' ? record.metadata : {};
      var inputs = Array.isArray(record.inputs) ? record.inputs : (Array.isArray(metadata.inputs) ? metadata.inputs : []);
      var outputs = Array.isArray(record.outputs) ? record.outputs : (Array.isArray(metadata.outputs) ? metadata.outputs : []);
      var sideEffects = Array.isArray(record.side_effects) ? record.side_effects : (Array.isArray(metadata.side_effects) ? metadata.side_effects : []);
      var testActions = Array.isArray(record.test_actions) ? record.test_actions : (Array.isArray(metadata.test_actions) ? metadata.test_actions : []);
      var blocks = [];
      if (inputs.length) {
        blocks.push('<div><span class="graph-detail-label">Inputs</span>' + listHtml(inputs, function(item) {
          return '<code>' + esc(artifactText(item)) + '</code>';
        }) + '</div>');
      }
      if (outputs.length) {
        blocks.push('<div><span class="graph-detail-label">Outputs</span>' + listHtml(outputs, function(item) {
          return '<code>' + esc(artifactText(item)) + '</code>';
        }) + '</div>');
      }
      if (sideEffects.length) {
        blocks.push('<div><span class="graph-detail-label">Side effects</span>' + listHtml(sideEffects, sideEffectText) + '</div>');
      }
      if (testActions.length) {
        blocks.push('<div><span class="graph-detail-label">Test actions</span>' + listHtml(testActions, function(item) {
          if (!item || typeof item !== 'object') return esc(String(item));
          var parts = [];
          if (item.type) parts.push(esc(String(item.type).replace(/_/g, ' ')));
          if (item.name) parts.push('<strong>' + esc(item.name) + '</strong>');
          if (item.status) parts.push('<span class="graph-node-status ' + statusClass(item.status) + '">' + esc(item.status) + '</span>');
          if (item.target) parts.push('<code>' + esc(item.target) + '</code>');
          if (item.description) parts.push('<span>' + esc(item.description) + '</span>');
          return parts.join(' ');
        }) + '</div>');
      }
      return blocks.length ? '<div class="graph-detail-section graph-evidence-io-detail"><span class="graph-detail-label">Evidence I/O</span>' + blocks.join('') + '</div>' : '';
    }
    function evidenceSummary(records) {
      if (!Array.isArray(records) || !records.length) return '';
      return listHtml(records, function(record) {
        var bits = [];
        if (record.id) bits.push('<code>' + esc(record.id) + '</code>');
        if (record.type) bits.push(esc(record.type));
        if (record.status) bits.push('<span class="graph-node-status ' + statusClass(record.status) + '">' + esc(record.status) + '</span>');
        if (record.strength) bits.push(esc(record.strength));
        if (record.source_locator) bits.push('<code>' + esc(record.source_locator) + '</code>');
        return bits.join(' ');
      });
    }
    function nodeMeta(node, key, fallback) {
      if (!node) return fallback;
      if (node[key] !== undefined && node[key] !== null && node[key] !== '') return node[key];
      if (node.metadata && node.metadata[key] !== undefined && node.metadata[key] !== null && node.metadata[key] !== '') return node.metadata[key];
      return fallback;
    }
    function isScannerEvidence(node) {
      return Boolean(node && node.type === 'evidence' && (
        nodeMeta(node, 'evidence_type', '') === 'scanner_result' ||
        String(node.id || '').indexOf('evidence:scanner:') === 0
      ));
    }
    function scannerEvidenceFor(node) {
      var neighbors = adj.get(node.id) || [];
      var seen = new Set();
      var signals = [];
      neighbors.forEach(function(nb) {
        var n = nodeById.get(nb.node);
        if (!isScannerEvidence(n) || seen.has(n.id)) return;
        seen.add(n.id);
        signals.push(n);
      });
      return signals;
    }
    function scannerEvidenceSummary(records) {
      if (!Array.isArray(records) || !records.length) return '';
      return '<ul class="graph-action-list graph-scanner-evidence-list">' + records.slice(0, 10).map(function(record) {
        var scanner = nodeMeta(record, 'scanner', 'scanner');
        var status = nodeMeta(record, 'status', record.status || 'unknown');
        var row = nodeMeta(record, 'row', '');
        var role = nodeMeta(record, 'evidence_role', '');
        var strength = nodeMeta(record, 'evidence_strength', '');
        var matchedCount = Number(nodeMeta(record, 'matched_finding_count', 0) || 0);
        var reason = nodeMeta(record, 'scanner_reason', '');
        var locator = nodeMeta(record, 'source_locator', '');
        var bits = [
          '<strong>' + esc(scanner) + '</strong>',
          '<span class="graph-node-status ' + statusClass(status) + '">' + esc(status) + '</span>'
        ];
        if (row) bits.push('<code>' + esc(row) + '</code>');
        bits.push('<span>' + esc(matchedCount ? (matchedCount + ' mapped finding' + (matchedCount === 1 ? '' : 's')) : 'no mapped findings') + '</span>');
        if (role) bits.push(esc(role));
        if (strength) bits.push(esc(strength));
        if (locator) bits.push('<code>' + esc(locator) + '</code>');
        if (reason) bits.push('<span>' + esc(reason) + '</span>');
        return '<li>' + bits.join(' ') + '</li>';
      }).join('') + (records.length > 10 ? '<li><em>and ' + (records.length - 10) + ' more scanner signals</em></li>' : '') + '</ul>';
    }
    function scannerEvidenceBlocks(record) {
      if (!record) return false;
      var status = String(nodeMeta(record, 'status', record.status || '')).toLowerCase();
      var role = String(nodeMeta(record, 'evidence_role', '')).toLowerCase();
      var effect = String(nodeMeta(record, 'assurance_effect', '')).toLowerCase();
      var mappingLevel = String(nodeMeta(record, 'mapping_level', '')).toLowerCase();
      return status === 'failed' && (
        role.indexOf('blocking') >= 0 ||
        effect.indexOf('blocking') >= 0 ||
        mappingLevel === 'compliance_row'
      );
    }
    function scannerEvidenceNote(records) {
      var hasUnmapped = (records || []).some(function(record) {
        return nodeMeta(record, 'mapping_level', '') === 'general_finding' ||
          nodeMeta(record, 'traceability_strength', '') === 'unmapped';
      });
      if (hasUnmapped) {
        return '<p class="graph-detail-note">These scanner findings have no accepted direct compliance-row or compliance-domain mapping. They remain useful security inventory, but they are not FR/TBT assurance evidence until a reviewed mapping is added.</p>';
      }
      var hasBlocking = (records || []).some(scannerEvidenceBlocks);
      if (hasBlocking) {
        return '<p class="graph-detail-note">Direct failed scanner evidence is a compliance blocker for the mapped row. It is evaluated alongside bespoke FR/TBT test evidence, so a passing test does not cancel a direct scanner failure.</p>';
      }
      return '<p class="graph-detail-note">Only findings that match the scanner mapping selectors are attached to this compliance row. Scanner evidence is evaluated alongside project test evidence.</p>';
    }
    function isAssuranceControlNode(node) {
      return node && (
        node.type === 'waiver' ||
        node.type === 'compensating_control' ||
        node.type === 'decision'
      );
    }
    function assuranceControlDetail(node) {
      if (!isAssuranceControlNode(node)) return '';
      var heading = node.type === 'waiver' ? 'Waiver audit record' :
        node.type === 'compensating_control' ? 'Compensating control audit record' :
        'Decision audit record';
      var rows = [];
      function add(label, value, code) {
        if (value === undefined || value === null || value === '') return;
        rows.push('<dt>' + esc(label) + '</dt><dd>' + (code ? '<code>' + esc(value) + '</code>' : esc(value)) + '</dd>');
      }
      add('Status', node.status || node.readiness_status || '');
      add('Effect', node.status_effect || node.outcome || '');
      add('Scope', node.scope || '');
      add('Reason', node.reason || node.control_description || '');
      add('Approved by', node.approved_by || node.decided_by || '');
      add('Approved at', node.approved_at || node.decided_at || '');
      add('Review due', node.review_due_at || '');
      add('Expires', node.expires_at || '');
      add('Decision ref', node.decision_ref || '', true);
      add('Signature ref', node.signature_ref || '', true);
      if (!rows.length) return '';
      var note = node.type === 'decision'
        ? 'Decisions record human governance over a gate or criterion. They do not create technical evidence by themselves.'
        : 'Waivers and compensating controls are explicit audit records. They may change assurance rollup state, but they are not passing FR/TBT evidence.';
      return '<div class="graph-detail-section graph-assurance-control-detail"><span class="graph-detail-label">' + esc(heading) + '</span><dl class="graph-detail-grid">' + rows.join('') + '</dl><p class="graph-detail-note">' + esc(note) + '</p></div>';
    }
    function connectedComplianceNode(node) {
      var neighbors = adj.get(node.id) || [];
      for (var i = 0; i < neighbors.length; i++) {
        var n = nodeById.get(neighbors[i].node);
        if (isRulesetRowNode(n)) return n;
      }
      return isRulesetRowNode(node) ? node : null;
    }
    function gapHtml(node) {
      var rowNode = connectedComplianceNode(node);
      var rowLabel = rowNode ? ((rowNode.ruleset || 'Compliance') + ' ' + (rowNode.row || rowNode.id || 'row')) : (node.ref || node.row || 'this compliance row');
      var rowDesc = (rowNode && rowNode.description) || node.description || '';
      var chapter = rowNode && (rowNode.chapter || rowNode.section || rowNode.family);
      var level = rowNode && rowNode.level;
      var bits = [
        '<div class="graph-node-detail graph-gap-detail">',
        '<div class="graph-detail-heading"><span>Assessment gap</span><strong>' + esc(rowLabel) + '</strong></div>',
        '<div class="graph-chip-row"><span class="graph-node-status graph-status-missing">unaddressed</span><span class="graph-node-type">missing provenance chain</span></div>'
      ];
      var facts = [];
      if (level !== undefined && level !== null) facts.push(['Level', 'L' + String(level).replace(/^L/i, '')]);
      if (chapter) facts.push(['Section', esc(chapter)]);
      if (rowNode && rowNode.ruleset) facts.push(['Regime', esc(rowNode.ruleset)]);
      if (facts.length) {
        bits.push('<div class="graph-detail-section"><span class="graph-detail-label">Requirement</span><dl class="graph-detail-grid">');
        facts.forEach(function(pair) { bits.push('<dt>' + esc(pair[0]) + '</dt><dd>' + pair[1] + '</dd>'); });
        bits.push('</dl></div>');
      }
      if (rowDesc) bits.push('<div class="graph-detail-section"><span class="graph-detail-label">Requirement text</span><p>' + esc(rowDesc) + '</p></div>');
      bits.push('<div class="graph-detail-section"><span class="graph-detail-label">Why this is blocked</span><p>No FR currently claims this compliance row, so there is no FR -> TBT/test -> evidence chain to assess.</p></div>');
      bits.push('<div class="graph-detail-section"><span class="graph-detail-label">Next action</span><ol class="graph-action-list"><li>Define or map an FR that explicitly claims this row.</li><li>Add or identify a TBT for that FR.</li><li>Attach passing automated, manual, or document evidence to the TBT.</li></ol></div>');
      bits.push('</div>');
      return bits.join('');
    }
    if ((d.ghost && d.type === 'fr') || (isRulesetRowNode(d) && (adj.get(d.id) || []).some(function(nb) {
      var n = nodeById.get(nb.node);
      return n && n.ghost && n.type === 'fr';
    }))) {
      return gapHtml(d);
    }
    var bits = [
      '<div class="graph-node-detail">',
      '<div class="graph-detail-heading"><span>' + esc(nodeKindLabel(d)) + '</span><strong>' + esc(nodeText(d)) + '</strong></div>'
    ];
    bits.push('<div class="graph-chip-row"><span class="graph-node-type">' + esc(d.type) + '</span>');
    if (d.evidence_status) bits.push('<span class="graph-node-status ' + statusClass(d.evidence_status) + '">' + esc(d.evidence_status) + '</span>');
    if (d.status && !d.evidence_status) bits.push('<span class="graph-node-status ' + statusClass(d.status) + '">' + esc(d.status) + '</span>');
    if (d.ghost) bits.push('<span class="graph-node-status graph-status-missing">needed</span>');
    bits.push('</div>');
    if (d.description) bits.push('<div class="graph-detail-section"><span class="graph-detail-label">Context</span><p>' + esc(d.description) + '</p></div>');
    var controlDetail = assuranceControlDetail(d);
    if (controlDetail) bits.push(controlDetail);
    if (Array.isArray(d.reasons) && d.reasons.length) {
      bits.push('<div class="graph-detail-section"><span class="graph-detail-label">Resolved assurance</span>' + listHtml(d.reasons) + '</div>');
    }
    if (Array.isArray(d.tbts) && d.tbts.length) {
      bits.push('<div class="graph-detail-section"><span class="graph-detail-label">TBTs</span>' + codePills(d.tbts) + '</div>');
    }
    if (Array.isArray(d.frs) && d.frs.length) {
      bits.push('<div class="graph-detail-section"><span class="graph-detail-label">FRs</span>' + codePills(d.frs) + '</div>');
    }
    if (d.sufficiency && typeof d.sufficiency === 'object' && Object.keys(d.sufficiency).length) {
      var suffFields = [];
      Object.keys(d.sufficiency).forEach(function(key) {
        var value = d.sufficiency[key];
        if (Array.isArray(value)) value = value.join(', ');
        suffFields.push('<dt>' + esc(key.replace(/_/g, ' ')) + '</dt><dd>' + esc(String(value)) + '</dd>');
      });
      bits.push('<div class="graph-detail-section"><span class="graph-detail-label">Sufficiency policy</span><dl class="graph-detail-grid">' + suffFields.join('') + '</dl></div>');
    }
    if (Array.isArray(d.expected_evidence) && d.expected_evidence.length) {
      bits.push('<div class="graph-detail-section"><span class="graph-detail-label">Expected evidence</span>' + listHtml(d.expected_evidence, function(item) {
        var bits = [];
        if (item.type) bits.push(esc(item.type));
        if (item.strength) bits.push('<strong>' + esc(item.strength) + '</strong>');
        if (item.source) bits.push('<code>' + esc(item.source) + '</code>');
        return bits.join(' ') || esc(JSON.stringify(item));
      }) + '</div>');
    }
    if (d.evidence_summary && typeof d.evidence_summary === 'object') {
      var summary = d.evidence_summary;
      var summaryFields = [];
      if (summary.expected_count !== undefined) summaryFields.push(['Expected', esc(summary.expected_count)]);
      if (summary.observed_count !== undefined) summaryFields.push(['Observed', esc(summary.observed_count)]);
      if (summary.missing_required_count !== undefined) summaryFields.push(['Missing required', esc(summary.missing_required_count)]);
      if (summary.failed_count !== undefined) summaryFields.push(['Failed', esc(summary.failed_count)]);
      if (summaryFields.length) {
        bits.push('<div class="graph-detail-section"><span class="graph-detail-label">Evidence summary</span><dl class="graph-detail-grid">');
        summaryFields.forEach(function(pair) { bits.push('<dt>' + esc(pair[0]) + '</dt><dd>' + pair[1] + '</dd>'); });
        bits.push('</dl></div>');
      }
    }
    if (Array.isArray(d.resolved_evidence) && d.resolved_evidence.length) {
      bits.push('<div class="graph-detail-section"><span class="graph-detail-label">Observed evidence</span>' + evidenceSummary(d.resolved_evidence) + '</div>');
      d.resolved_evidence.slice(0, 3).forEach(function(record) {
        var io = evidenceIoHtml(record);
        if (io) bits.push(io);
      });
    }
    if (d.type === 'evidence') {
      var directIo = evidenceIoHtml(d);
      if (directIo) bits.push(directIo);
    }
    var scannerSignals = scannerEvidenceFor(d);
    if (scannerSignals.length) {
      var scannerLabel = scannerSignals.some(scannerEvidenceBlocks) ? 'Scanner blockers' : 'Mapped scanner evidence';
      bits.push('<div class="graph-detail-section"><span class="graph-detail-label">' + scannerLabel + '</span>' + scannerEvidenceSummary(scannerSignals) + scannerEvidenceNote(scannerSignals) + '</div>');
    } else if (isScannerEvidence(d)) {
      var selfScannerLabel = scannerEvidenceBlocks(d) ? 'Scanner blocker' : 'Mapped scanner evidence';
      bits.push('<div class="graph-detail-section"><span class="graph-detail-label">' + selfScannerLabel + '</span>' + scannerEvidenceSummary([d]) + scannerEvidenceNote([d]) + '</div>');
    }
    var fields = [];
    if (d.path) fields.push(['Path', '<code>' + esc(d.path) + '</code>']);
    if (d.tbt) fields.push(['TBT', '<code>' + esc(d.tbt) + '</code>']);
    if (d.ref && d.tbt) fields.push(['Reference', '<code>' + esc(d.ref) + '</code>']);
    if (d.source_locator) fields.push(['Source locator', '<code>' + esc(d.source_locator) + '</code>']);
    if (d.source_excerpt) fields.push(['Source excerpt', esc(d.source_excerpt)]);
    if (d.discovered_path) fields.push(['Discovered test', '<code>' + esc(d.discovered_path) + '</code>']);
    if (d.discovered_framework) fields.push(['Discovered framework', esc(d.discovered_framework)]);
    if (d.case_count !== undefined) fields.push(['Discovered cases', esc(d.case_count)]);
    if (d.assessment) fields.push(['Assessment', esc(d.assessment)]);
    if (d.safety) fields.push(['Safety', esc(d.safety)]);
    if (d.runner) fields.push(['Runner', esc(d.runner)]);
    if (d.scanner) fields.push(['Scanner', esc(d.scanner)]);
    if (d.rule) fields.push(['Rule', '<code>' + esc(d.rule) + '</code>']);
    if (d.ruleset) fields.push(['Ruleset', esc(d.ruleset)]);
    if (d.row) fields.push(['Row', '<code>' + esc(d.row) + '</code>']);
    if (d.party_type) fields.push(['Party type', esc(d.party_type)]);
    if (d.continuation_rule) fields.push(['Continuation rule', '<code>' + esc(d.continuation_rule) + '</code>']);
    if (fields.length) {
      bits.push('<div class="graph-detail-section"><span class="graph-detail-label">Details</span><dl class="graph-detail-grid">');
      fields.forEach(function(pair) { bits.push('<dt>' + esc(pair[0]) + '</dt><dd>' + pair[1] + '</dd>'); });
      bits.push('</dl></div>');
    }
    var neighbors = adj.get(d.id) || [];
    if (neighbors.length) {
      bits.push('<div class="graph-detail-section"><span class="graph-detail-label">Connected nodes</span><ol class="graph-trace-list">');
      neighbors.slice(0, 12).forEach(function(nb) {
        var n = nodeById.get(nb.node);
        if (n) bits.push('<li><span class="graph-edge-type">' + esc(edgeLabel(nb.edge.type)) + '</span> <span>' + esc(nodeText(n)) + '</span></li>');
      });
      if (neighbors.length > 12) bits.push('<li><em>and ' + (neighbors.length - 12) + ' more</em></li>');
      bits.push('</ol></div>');
    }
    bits.push('</div>');
    return bits.join('');
  }

  function renderDetail(d, targetPanel) {
    var panel = targetPanel || detailPanel;
    if (!panel || !d) return;
    if (targetPanel) {
      panel.innerHTML = detailHtml(d);
      return;
    }
    graphSelectedDetailId = d.id || null;
    panel.innerHTML = '<button type="button" class="graph-detail-x" aria-label="Close details">×</button>' + detailHtml(d);
    graphDetailOpen = true;
    panel.classList.add('is-open');
  }
  function closeDetail() {
    graphDetailOpen = false;
    graphSelectedDetailId = null;
    if (detailPanel) detailPanel.classList.remove('is-open');
  }
  if (detailPanel) {
    detailPanel.addEventListener('click', function(event) {
      if (event.target && event.target.classList && event.target.classList.contains('graph-detail-x')) {
        event.stopPropagation();
        closeDetail();
      }
    });
  }

  function edgePath(d) {
    var sourceNode = typeof d.source === 'object' ? d.source : nodeById.get(d.source);
    var targetNode = typeof d.target === 'object' ? d.target : nodeById.get(d.target);
    if (!sourceNode || !targetNode) return '';
    var sourceHalf = (sourceNode.cardW || nodeCardWidth(sourceNode)) / 2;
    var targetHalf = (targetNode.cardW || nodeCardWidth(targetNode)) / 2;
    var sourceHalfH = (sourceNode.cardH || nodeCardHeight(sourceNode)) / 2;
    var targetHalfH = (targetNode.cardH || nodeCardHeight(targetNode)) / 2;
    if (sourceNode.gateLane || targetNode.gateLane) {
      var laneDelta = Math.abs(targetNode.y - sourceNode.y);
      if (laneDelta > 86) {
        var downward = targetNode.y > sourceNode.y;
        var sxv = sourceNode.x;
        var syv = sourceNode.y + (downward ? sourceHalfH + 10 : -sourceHalfH - 10);
        var txv = targetNode.x;
        var tyv = targetNode.y - (downward ? targetHalfH + 14 : -targetHalfH - 14);
        var midY = syv + (tyv - syv) * 0.5;
        return 'M' + sxv + ',' + syv + ' L' + sxv + ',' + midY + ' L' + txv + ',' + midY + ' L' + txv + ',' + tyv;
      }
      var gLeftToRight = targetNode.x >= sourceNode.x;
      var sxo = sourceNode.x + (gLeftToRight ? sourceHalf + 12 : -sourceHalf - 12);
      var txo = targetNode.x - (gLeftToRight ? targetHalf + 16 : -targetHalf - 16);
      var midX = sxo + (txo - sxo) * 0.5;
      return 'M' + sxo + ',' + sourceNode.y + ' L' + midX + ',' + sourceNode.y + ' L' + midX + ',' + targetNode.y + ' L' + txo + ',' + targetNode.y;
    }
    var leftToRight = targetNode.x >= sourceNode.x;
    var sx = sourceNode.x + (leftToRight ? sourceHalf + 8 : -sourceHalf - 8);
    var sy = sourceNode.y;
    var tx = targetNode.x - (leftToRight ? targetHalf + 12 : -targetHalf - 12);
    var ty = targetNode.y;
    var dx = Math.max(36, Math.abs(tx - sx) * 0.42);
    var c1x = sx + (tx >= sx ? dx : -dx);
    var c2x = tx - (tx >= sx ? dx : -dx);
    return 'M' + sx + ',' + sy + ' C' + c1x + ',' + sy + ' ' + c2x + ',' + ty + ' ' + tx + ',' + ty;
  }

  function edgeLabelPoint(d, offset) {
    var sourceNode = typeof d.source === 'object' ? d.source : nodeById.get(d.source);
    var targetNode = typeof d.target === 'object' ? d.target : nodeById.get(d.target);
    if (!sourceNode || !targetNode) return {x: 0, y: 0};
    var x = (sourceNode.x + targetNode.x) / 2;
    var y = (sourceNode.y + targetNode.y) / 2 - (offset || 18);
    var minY = Math.min(sourceNode.y, targetNode.y) + 28;
    var maxY = Math.max(sourceNode.y, targetNode.y) - 28;
    if (Math.abs(sourceNode.y - targetNode.y) > 72) y = Math.max(minY, Math.min(maxY, y));
    return {x: x, y: y};
  }

  function drawEdgeLabels(svg, edges, maxLabels, compact) {
    var labels = svg.append('g').attr('class', 'graph-edge-labels').selectAll('g')
      .data(edges.filter(function(_, idx) { return idx < maxLabels; })).enter().append('g')
      .attr('transform', function(d, idx) {
        var point = edgeLabelPoint(d, compact ? 20 + (idx % 2) * 12 : 18 + (idx % 3) * 10);
        return 'translate(' + point.x + ',' + point.y + ')';
      });
    labels.append('rect')
      .attr('class', 'graph-edge-label-bg')
      .attr('x', function(d) { return -Math.min(96, edgeLabel(d.type).length * 4.7 + 10) / 2; })
      .attr('y', -9)
      .attr('width', function(d) { return Math.min(96, edgeLabel(d.type).length * 4.7 + 10); })
      .attr('height', 16)
      .attr('rx', 4);
    labels.append('text')
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'central')
      .text(function(d) {
        var label = edgeLabel(d.type);
        return label.length > 18 ? label.slice(0, 16) + '...' : label;
      });
    return labels;
  }

  function appendCardNodes(selection, focusId) {
    selection.each(function(d) {
      d.cardW = d.cardW || nodeCardWidth(d);
      d.cardH = d.cardH || nodeCardHeight(d);
    });
    selection.append('rect')
      .attr('class', function(d) { return 'graph-node-card' + (d.ghost ? ' graph-node-ghost' : ''); })
      .attr('x', function(d) { return -d.cardW / 2; })
      .attr('y', function(d) { return -d.cardH / 2; })
      .attr('width', function(d) { return d.cardW; })
      .attr('height', function(d) { return d.cardH; })
      .attr('rx', 7)
      .attr('stroke', function(d) { return d.id === focusId ? '#f2f7f5' : '#33434b'; });
    selection.append('rect')
      .attr('class', 'graph-node-rail')
      .attr('x', function(d) { return -d.cardW / 2; })
      .attr('y', function(d) { return -d.cardH / 2; })
      .attr('width', 5)
      .attr('height', function(d) { return d.cardH; })
      .attr('rx', 3)
      .attr('fill', function(d) { return typeColors[d.type] || '#718096'; });
    selection.append('text')
      .attr('class', 'graph-node-kind')
      .attr('x', function(d) { return -d.cardW / 2 + 13; })
      .attr('y', function(d) { return -d.cardH / 2 + 15; })
      .text(function(d) { return (d.ghost ? 'MISSING ' : '') + nodeKindLabel(d); });
    selection.append('text')
      .attr('class', 'graph-node-title')
      .attr('x', function(d) { return -d.cardW / 2 + 13; })
      .attr('y', function(d) { return -d.cardH / 2 + 33; })
      .each(function(d) {
        var maxChars = Math.max(18, Math.floor((d.cardW - 28) / 5.8));
        var lines = splitLabel(nodeText(d), maxChars, d.cardH > 62 ? 3 : 2);
        var text = d3.select(this);
        lines.forEach(function(line, idx) {
          text.append('tspan')
            .attr('x', -d.cardW / 2 + 13)
            .attr('dy', idx === 0 ? 0 : 11)
            .text(line);
        });
      });
  }

  function renderMiniTrace(container, focusId) {
    if (!container || !focusId) return;
    var localDetail = container.parentElement ? container.parentElement.querySelector('.mini-trace-detail') : null;
    if (!nodeById.has(focusId)) {
      container.innerHTML = '<div class="mini-trace-empty">No trace node found for this row.</div>';
      if (localDetail) localDetail.innerHTML = '<div class="mini-trace-empty">No graph context was generated for this row.</div>';
      return;
    }
    var subData = rowProofGraph(focusId);
    var width = Math.max(container.clientWidth || 720, 620);
    var height = Math.max(220, Math.min(460, 96 + Math.ceil(subData.nodes.length / 4) * 72));
    var layout = layoutLayered(subData.nodes, width, height);
    height = Math.min(Math.max(layout.height, height), 620);
    container.innerHTML = '';
    var miniSvg = d3.select(container).append('svg')
      .attr('class', 'mini-trace-svg')
      .attr('width', width)
      .attr('height', height)
      .attr('viewBox', [0, 0, width, height])
      .attr('role', 'img')
      .attr('aria-label', 'Focused trace chain');
    miniSvg.append('rect')
      .attr('class', 'graph-viewport-bg')
      .attr('x', 0).attr('y', 0)
      .attr('width', width).attr('height', height);
    var miniDefs = miniSvg.append('defs');
    Object.keys(edgeColors).forEach(function(ek) {
      miniDefs.append('marker').attr('id', 'mini-arrow-' + ek).attr('viewBox', '0 -5 10 10')
        .attr('refX', 10).attr('refY', 0).attr('markerWidth', 5).attr('markerHeight', 5)
        .attr('orient', 'auto').append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', edgeColors[ek]);
    });
    miniSvg.append('g').attr('class', 'graph-links').selectAll('path')
      .data(subData.edges).enter().append('path')
      .attr('stroke', function(d) { return edgeColors[d.type] || '#718096'; })
      .attr('stroke-width', 1.35).attr('stroke-opacity', 0.62)
      .attr('fill', 'none')
      .attr('d', edgePath)
      .attr('marker-end', function(d) { return 'url(#mini-arrow-' + d.type + ')'; });
    drawEdgeLabels(miniSvg, subData.edges, 12, true);
    var miniNodes = miniSvg.append('g').attr('class', 'graph-nodes mini-trace-nodes').selectAll('g')
      .data(subData.nodes).enter().append('g')
      .attr('tabindex', 0)
      .attr('role', 'button')
      .attr('aria-label', function(d) { return nodeText(d); })
      .attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; })
      .on('click', function(event, d) { event.stopPropagation(); renderDetail(d, localDetail); })
      .on('keydown', function(event, d) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          renderDetail(d, localDetail);
        }
      });
    appendCardNodes(miniNodes, focusId);
    renderDetail(nodeById.get(focusId), localDetail);
  }

  function renderCompleteGraph(subData) {
    canvas.innerHTML = '';
    canvas.classList.add('graph-canvas-complete');
    if (!subData.nodes.length) {
      canvas.innerHTML = '<div class="empty-state">No graph nodes match the current filters.</div>';
      return;
    }
    closeDetail();
    var sourceNodes = subData.nodes.map(function(n) { return Object.assign({}, n); });
    var sourceNodeIds = new Set(sourceNodes.map(function(n) { return n.id; }));
    var sourceLinks = subData.edges.filter(function(e) {
      return sourceNodeIds.has(sourceId(e)) && sourceNodeIds.has(targetId(e));
    }).map(function(e) {
      return {source: sourceId(e), target: targetId(e), type: e.type, key: edgeKey(e)};
    });

    var width = Math.max(canvas.clientWidth || 1040, 1040);
    var height = Math.max(Math.min(window.innerHeight ? window.innerHeight - 300 : 660, 760), 660);
    var clusterDefs = [
      {id: 'requirements', label: 'Functional requirements', x: width * 0.17, y: height * 0.31, color: '#56c7b7'},
      {id: 'compliance', label: 'Compliance / frameworks', x: width * 0.50, y: height * 0.29, color: '#8fcbe8'},
      {id: 'scanner', label: 'Scanner universe', x: width * 0.83, y: height * 0.31, color: '#ff98a9'},
      {id: 'tests', label: 'TBTs / tests', x: width * 0.17, y: height * 0.72, color: '#35d07f'},
      {id: 'evidence', label: 'Evidence / results', x: width * 0.50, y: height * 0.72, color: '#718096'},
      {id: 'governance', label: 'Governance / process', x: width * 0.83, y: height * 0.72, color: '#ffd166'}
    ];
    var clusterById = new Map(clusterDefs.map(function(c) { return [c.id, c]; }));
    function completeCluster(n) {
      if (isScannerEvidence(n) || n.type === 'scanner_rule') return 'scanner';
      if (isRulesetRowNode(n) || n.type === 'domain') return 'compliance';
      if (n.type === 'fr') return 'requirements';
      if (isTbtNode(n)) return 'tests';
      if (n.type === 'file' || n.type === 'test') return 'tests';
      if (n.type === 'evidence' || n.type === 'test_result') return 'evidence';
      if (n.type === 'process' || n.type === 'gate' || n.type === 'criterion' || n.type === 'role' || n.type === 'approval' || n.type === 'decision' || n.type === 'waiver' || n.type === 'compensating_control' || n.type === 'blueprint' || n.type === 'planning_artifact') return 'governance';
      return 'governance';
    }
    var degree = new Map();
    sourceLinks.forEach(function(e) {
      degree.set(e.source, (degree.get(e.source) || 0) + 1);
      degree.set(e.target, (degree.get(e.target) || 0) + 1);
    });
    var buckets = new Map();
    sourceNodes.forEach(function(n) {
      n.completeCluster = completeCluster(n);
      n.degree = degree.get(n.id) || 0;
      var bucket = buckets.get(n.completeCluster) || [];
      bucket.push(n);
      buckets.set(n.completeCluster, bucket);
    });
    clusterDefs.forEach(function(cluster) {
      var count = (buckets.get(cluster.id) || []).length;
      var maxClusterRadius = Math.max(78, Math.min(150, width * 0.115, height * 0.17));
      cluster.count = count;
      cluster.r = Math.max(64, Math.min(maxClusterRadius, 42 + Math.sqrt(Math.max(1, count)) * 7.2));
      cluster.x = Math.max(cluster.r + 22, Math.min(width - cluster.r - 22, cluster.x));
      cluster.y = Math.max(cluster.r + 32, Math.min(height - cluster.r - 24, cluster.y));
    });
    clusterDefs.forEach(function(cluster) {
      var bucket = (buckets.get(cluster.id) || []).slice().sort(function(a, b) {
        return (b.degree || 0) - (a.degree || 0) || String(a.id).localeCompare(String(b.id));
      });
      var goldenAngle = Math.PI * (3 - Math.sqrt(5));
      bucket.forEach(function(n, idx) {
        var maxDist = Math.max(10, cluster.r - radiusForNode(n) - 14);
        var ratio = bucket.length <= 1 ? 0 : idx / Math.max(1, bucket.length - 1);
        var distance = Math.sqrt(ratio) * maxDist;
        var angle = idx * goldenAngle;
        n.x = cluster.x + Math.cos(angle) * distance;
        n.y = cluster.y + 8 + Math.sin(angle) * distance * 0.88;
      });
    });
    var nodeByLocalId = new Map(sourceNodes.map(function(n) { return [n.id, n]; }));
    var links = sourceLinks.filter(function(e) { return nodeByLocalId.has(e.source) && nodeByLocalId.has(e.target); });
    showBanner('');
    var svg = d3.select(canvas).append('svg')
      .attr('class', 'graph-complete-svg')
      .attr('width', width).attr('height', height)
      .attr('viewBox', [0, 0, width, height])
      .attr('role', 'img')
      .attr('aria-label', 'Complete clustered traceability graph');
    svg.append('rect')
      .attr('class', 'graph-viewport-bg')
      .attr('x', 0).attr('y', 0)
      .attr('width', width).attr('height', height);
    var viewport = svg.append('g').attr('class', 'graph-force-viewport graph-complete-force');
    var clusterLayer = viewport.append('g').attr('class', 'graph-complete-clusters');
    clusterDefs.forEach(function(cluster) {
      clusterLayer.append('circle')
        .attr('class', 'graph-complete-cluster-halo')
        .attr('cx', cluster.x).attr('cy', cluster.y)
        .attr('r', cluster.r)
        .attr('stroke', cluster.color);
      var label = clusterLayer.append('g')
        .attr('class', 'graph-complete-cluster-label')
        .attr('transform', 'translate(' + cluster.x + ',' + Math.max(22, cluster.y - cluster.r - 10) + ')');
      label.append('rect')
        .attr('class', 'graph-complete-cluster-label-bg')
        .attr('x', -96).attr('y', -15)
        .attr('width', 192).attr('height', 31)
        .attr('rx', 5);
      label.append('text').attr('class', 'graph-complete-cluster-name').attr('text-anchor', 'middle').text(cluster.label);
      label.append('text').attr('class', 'graph-complete-cluster-count').attr('text-anchor', 'middle').attr('y', 13).text(cluster.count + ' nodes');
    });
    if (legendPanel) {
      legendPanel.hidden = true;
      legendPanel.innerHTML = '';
      legendPanel.classList.remove('graph-legend-compact');
    }
    var link = viewport.append('g').attr('class', 'graph-force-links graph-complete-links').selectAll('line')
      .data(links).enter().append('line')
      .attr('stroke', function(d) { return edgeColors[d.type] || '#718096'; })
      .attr('stroke-opacity', 0.12)
      .attr('stroke-width', function(d) {
        var source = nodeByLocalId.get(d.source);
        var target = nodeByLocalId.get(d.target);
        return (source && target && (source.status === 'failed' || target.status === 'failed')) ? 1.25 : 0.75;
      });
    function radiusForNode(n) {
      var r = 2.7 + Math.min(3.8, Math.sqrt(Math.max(0, n.degree)) * 0.62);
      if (n.status === 'failed') r += 1.4;
      if (n.status === 'missing') r += 0.8;
      if (n.type === 'fr' || isTbtNode(n)) r += 0.8;
      return Math.max(2.9, Math.min(8.2, r));
    }
    var node = viewport.append('g').attr('class', 'graph-force-nodes').selectAll('g')
      .data(sourceNodes).enter().append('g')
      .attr('tabindex', 0).attr('role', 'button')
      .attr('aria-label', function(d) { return nodeText(d); })
      .attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; });
    node.append('circle')
      .attr('r', radiusForNode)
      .attr('fill', function(d) { return typeColors[d.type] || '#8fcbe8'; })
      .attr('stroke', function(d) { return d.ghost ? '#ffd166' : '#10171b'; })
      .attr('stroke-width', function(d) { return d.ghost ? 2 : (d.status === 'failed' ? 2.2 : 1.2); });
    node.append('title').text(function(d) { return nodeKindLabel(d) + ': ' + nodeText(d); });
    function linkEndpoint(ref) {
      return typeof ref === 'object' ? ref : nodeByLocalId.get(ref);
    }
    function ticked() {
      sourceNodes.forEach(function(d) {
        var cluster = clusterById.get(d.completeCluster) || clusterById.get('governance');
        var dx = d.x - cluster.x;
        var dy = d.y - cluster.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        var maxDist = Math.max(12, cluster.r - radiusForNode(d) - 7);
        if (dist > maxDist) {
          d.x = cluster.x + (dx / dist) * maxDist;
          d.y = cluster.y + Math.max(-maxDist * 0.78, Math.min(maxDist, (dy / dist) * maxDist));
        }
        d.x = Math.max(18, Math.min(width - 18, d.x));
        d.y = Math.max(42, Math.min(height - 20, d.y));
      });
      link
        .attr('x1', function(d) { return (linkEndpoint(d.source) || {}).x || 0; })
        .attr('y1', function(d) { return (linkEndpoint(d.source) || {}).y || 0; })
        .attr('x2', function(d) { return (linkEndpoint(d.target) || {}).x || 0; })
        .attr('y2', function(d) { return (linkEndpoint(d.target) || {}).y || 0; });
      node.attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; });
    }

    node.call(d3.drag()
      .on('drag', function(event, d) {
        d.x = Math.max(18, Math.min(width - 18, event.x));
        d.y = Math.max(42, Math.min(height - 20, event.y));
        ticked();
      }));
    ticked();
    function highlight(d) {
      if (graphDetailOpen && graphSelectedDetailId === d.id) {
        node.attr('opacity', 1);
        link.attr('opacity', 0.12);
        closeDetail();
        return;
      }
      var neighbors = new Set([d.id]);
      links.forEach(function(e) {
        var source = typeof e.source === 'object' ? e.source.id : e.source;
        var target = typeof e.target === 'object' ? e.target.id : e.target;
        if (source === d.id) neighbors.add(target);
        if (target === d.id) neighbors.add(source);
      });
      node.attr('opacity', function(n) { return neighbors.has(n.id) ? 1 : 0.20; });
      link.attr('opacity', function(e) {
        var source = typeof e.source === 'object' ? e.source.id : e.source;
        var target = typeof e.target === 'object' ? e.target.id : e.target;
        return source === d.id || target === d.id ? 0.82 : 0.025;
      });
      renderDetail(d);
    }
    node.on('click', function(event, d) { event.stopPropagation(); highlight(d); });
    node.on('keydown', function(event, d) {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); highlight(d); }
    });
    svg.on('click', function() {
      node.attr('opacity', 1);
      link.attr('opacity', 0.12);
    });
    svg.call(d3.zoom().scaleExtent([0.35, 3]).on('zoom', function(event) {
      viewport.attr('transform', event.transform);
    }));
  }

  function renderGraph(subData, focusId) {
    canvas.innerHTML = '';
    canvas.classList.remove('graph-canvas-complete');
    if (legendPanel) {
      legendPanel.hidden = true;
      legendPanel.innerHTML = '';
      legendPanel.classList.remove('graph-legend-compact');
    }
    if (!subData.nodes.length) {
      canvas.innerHTML = '<div class="empty-state">No traceability chain matches the current filters.</div>';
      return;
    }
    if (subData.mode === 'complete') {
      renderCompleteGraph(subData);
      return;
    }
    var width = Math.max(canvas.clientWidth || 920, 900);
    var height = Math.max(canvas.clientHeight || 560, 560);
    var isGateProof = subData.mode === 'gateProof';
    var layout = isGateProof ? layoutGateProof(subData, Math.max(width, 1120), height) : layoutLayered(subData.nodes, width, height);
    width = layout.width || width;
    height = layout.height;
    var svg = d3.select(canvas).append('svg')
      .attr('width', width).attr('height', height)
      .attr('viewBox', [0, 0, width, height])
      .attr('role', 'img')
      .attr('aria-label', 'Traceability graph');
    svg.append('rect')
      .attr('class', 'graph-viewport-bg')
      .attr('x', 0).attr('y', 0)
      .attr('width', width).attr('height', height);
    var defs = svg.append('defs');
    Object.keys(edgeColors).forEach(function(ek) {
      defs.append('marker').attr('id', 'arrow-' + ek).attr('viewBox', '0 -5 10 10')
        .attr('refX', 10).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6)
        .attr('orient', 'auto').append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', edgeColors[ek]);
    });
    if (isGateProof) {
      var gateBand = svg.append('g').attr('class', 'graph-gate-proof-bands');
      gateBand.append('rect')
        .attr('class', 'graph-gate-band')
        .attr('x', 28).attr('y', 72)
        .attr('width', 352).attr('height', height - 128)
        .attr('rx', 8);
      gateBand.append('text')
        .attr('class', 'graph-layer-label')
        .attr('x', 204).attr('y', 52)
        .attr('text-anchor', 'middle')
        .text('Gate checkpoint');
      layout.lanes.forEach(function(lane) {
        var laneHeight = lane.height || 184;
        gateBand.append('rect')
          .attr('class', 'graph-proof-lane graph-proof-lane-' + lane.id)
          .attr('x', 410).attr('y', lane.y - laneHeight / 2)
          .attr('width', width - 444).attr('height', laneHeight)
          .attr('rx', 8);
        gateBand.append('text')
          .attr('class', 'graph-layer-label')
          .attr('x', 430).attr('y', lane.y - laneHeight / 2 + 24)
          .attr('text-anchor', 'start')
          .text(lane.label);
      });
    } else {
    var layerG = svg.append('g').attr('class', 'graph-layers');
    layout.layers.forEach(function(layer) {
      var x = layout.layerX && layout.layerX[layer] !== undefined
        ? layout.layerX[layer]
        : (layout.maxLayer === 0 ? width / 2 : layout.leftPad + ((width - layout.leftPad - layout.rightPad) * layer / layout.maxLayer));
      layerG.append('line')
        .attr('class', 'graph-layer-guide')
        .attr('x1', x).attr('x2', x)
        .attr('y1', 34).attr('y2', height - 24);
      layerG.append('text')
        .attr('class', 'graph-layer-label')
        .attr('x', x)
        .attr('y', 24)
        .attr('text-anchor', 'middle')
        .text(subData.mode === 'scannerImpact' ? impactLayerLabel(layer) : layerLabel(layer));
    });
    }

    var link = svg.append('g').attr('class', 'graph-links').selectAll('path')
      .data(subData.edges).enter().append('path')
      .attr('stroke', function(d) { return edgeColors[d.type] || '#718096'; })
      .attr('stroke-width', 1.4).attr('stroke-opacity', 0.48)
      .attr('fill', 'none')
      .attr('d', edgePath)
      .attr('marker-end', function(d) { return 'url(#arrow-' + d.type + ')'; });
    var edgeText = drawEdgeLabels(svg, subData.edges, isGateProof ? 12 : 56, isGateProof);
    var nodeWrap = svg.append('g').attr('class', 'graph-nodes').selectAll('g')
      .data(subData.nodes).enter().append('g').attr('tabindex', 0).attr('role', 'button')
      .attr('aria-label', function(d) { return nodeText(d); })
      .style('cursor', 'grab')
      .attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; })
      .call(d3.drag().on('drag', dragging).on('end', dragEnd));
    appendCardNodes(nodeWrap, focusId);

    function highlight(d) {
      if (graphDetailOpen && graphSelectedDetailId === d.id) {
        nodeWrap.attr('opacity', 1);
        link.attr('opacity', 0.48);
        edgeText.attr('opacity', 1);
        closeDetail();
        return;
      }
      var chain = bfs([d.id], 3, 18);
      var ids = new Set(chain.nodes.map(function(n) { return n.id; }));
      nodeWrap.attr('opacity', function(n) { return ids.has(n.id) ? 1 : 0.18; });
      link.attr('opacity', function(e) {
        var source = typeof e.source === 'object' ? e.source.id : e.source;
        var target = typeof e.target === 'object' ? e.target.id : e.target;
        return ids.has(source) && ids.has(target) ? 0.86 : 0.08;
      });
      edgeText.attr('opacity', function(e) {
        var source = typeof e.source === 'object' ? e.source.id : e.source;
        var target = typeof e.target === 'object' ? e.target.id : e.target;
        return ids.has(source) && ids.has(target) ? 0.9 : 0.05;
      });
      renderDetail(d);
    }
    nodeWrap.on('click', function(event, d) { event.stopPropagation(); highlight(d); });
    nodeWrap.on('keydown', function(event, d) {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); highlight(d); }
    });
    svg.on('click', function() {
      nodeWrap.attr('opacity', 1);
      link.attr('opacity', 0.48);
      edgeText.attr('opacity', 1);
    });
    if (detailPanel) detailPanel.classList.toggle('is-open', graphDetailOpen);

    function dragging(event, d) {
      var halfW = (d.cardW || nodeCardWidth(d)) / 2;
      var halfH = (d.cardH || nodeCardHeight(d)) / 2;
      d.x = Math.max(halfW + 18, Math.min(width - halfW - 18, event.x));
      d.y = Math.max(halfH + 40, Math.min(height - halfH - 24, event.y));
      d3.select(this).attr('transform', 'translate(' + d.x + ',' + d.y + ')');
      link.attr('d', edgePath);
      edgeText.attr('transform', function(e, idx) {
          var point = edgeLabelPoint(e, (isGateProof ? 24 + (idx % 2) * 16 : 18 + (idx % 3) * 10));
          return 'translate(' + point.x + ',' + point.y + ')';
        });
    }
    function dragEnd() {
      d3.select(this).style('cursor', 'grab');
    }
  }

  function graphReady() {
    return canvas && canvas.offsetParent !== null && canvas.clientWidth > 200;
  }
  function scheduleGraphRender(fn) {
    window.requestAnimationFrame(function() {
      window.requestAnimationFrame(fn);
    });
  }
  function renderFromControls() {
    if (!graphReady()) return;
    renderGraphSummary();
    renderGraph(selectedEntryGraph(), controls.entryId && controls.entryId.value);
  }
  function renderFiltered() {
    if (!graphReady()) return;
    renderGraphSummary();
    renderGraph(filteredGraph(), null);
  }
  function renderCurrent() {
    scheduleGraphRender(renderFromControls);
  }
  function openFr(frId) {
    var id = String(frId || '').startsWith('fr:') ? frId : 'fr:' + frId;
    if (controls.entryType) controls.entryType.value = 'fr';
    populateEntries();
    if (controls.entryId) controls.entryId.value = id;
    renderGraph(frProofGraph(id), id);
  }
  function openRows(rows) {
    if (!rows || !rows.length) return;
    var first = rows[0];
    var id = (first.ruleset || '') + ':' + (first.row || '');
    if (!nodeById.has(id)) return;
    if (controls.entryType) controls.entryType.value = 'row';
    populateEntries();
    if (controls.entryId) controls.entryId.value = id;
    renderGraph(rowProofGraph(id), id);
  }

  if (controls.entryType) controls.entryType.addEventListener('change', populateEntries);
  if (controls.load) controls.load.addEventListener('click', renderFromControls);
  if (controls.ruleset) controls.ruleset.addEventListener('change', function() {
    refreshChapterOptions();
    populateEntries();
    showBanner('Compliance regime changed. Use Apply to redraw the selected chain.');
  });
  [controls.chapter, controls.scanner, controls.status].forEach(function(control) {
    if (control) control.addEventListener('change', function() {
      if (control === controls.chapter) populateEntries();
      showBanner('Filters changed. Use Apply to redraw the selected chain.');
    });
  });

  if (controls.status && frNodes.length) controls.status.value = 'failed';
  function contextOptions() {
    var loadedRulesets = uniqueSorted(rowNodes.map(function(n) { return n.ruleset; })).map(function(value) {
      return {value: value, label: rulesetOptionLabel(value)};
    });
    return {
      rulesets: [{value: '', label: rulesetOptionLabel('')}].concat(loadedRulesets),
      chapters: controls.chapter ? Array.from(controls.chapter.options).map(function(option) {
        return {value: option.value, label: option.textContent};
      }) : [],
      ruleset: controls.ruleset ? controls.ruleset.value : '',
      chapter: controls.chapter ? controls.chapter.value : ''
    };
  }
  function setRuleset(value, quiet) {
    if (!controls.ruleset) return contextOptions();
    controls.ruleset.value = value || '';
    refreshChapterOptions();
    populateEntries();
    if (!quiet) showBanner('Compliance regime changed. Use Apply to redraw the selected chain.');
    return contextOptions();
  }
  function setChapter(value, quiet) {
    if (!controls.chapter) return contextOptions();
    controls.chapter.value = value || '';
    populateEntries();
    if (!quiet) showBanner('Chapter / family changed. Use Apply to redraw the selected chain.');
    return contextOptions();
  }
  window.asvsGraph = {
    openFr: openFr,
    openRows: openRows,
    refresh: renderFiltered,
    renderCurrent: renderCurrent,
    renderMiniTrace: renderMiniTrace,
    getContextOptions: contextOptions,
    setRuleset: setRuleset,
    setChapter: setChapter
  };
  if (graphReady()) renderCurrent();
}

function setupProcessFlow() {
  var dataEl = document.getElementById('process-flow-data');
  var canvas = document.getElementById('process-flow-canvas');
  var detail = document.getElementById('process-flow-detail');
  if (!dataEl || !canvas) return;
  if (typeof d3 === 'undefined') {
    canvas.innerHTML = '<div class="empty-state">Graph library unavailable. The process gate data is embedded in this report, but the interactive view could not render.</div>';
    return;
  }
  var data;
  try { data = JSON.parse(dataEl.textContent || '{"processes":[]}'); }
  catch (_) { return; }
  if (!data.processes || !data.processes.length) {
    canvas.innerHTML = '<div class="empty-state">No process gates were found for the flow view.</div>';
    return;
  }
  var profileControl = document.getElementById('process-profile-control');
  var frameworkOptionsDataEl = document.getElementById('framework-options-data');
  var processFlowByFramework = {};
  if (frameworkOptionsDataEl) {
    try {
      (JSON.parse(frameworkOptionsDataEl.textContent || '[]') || []).forEach(function(item) {
        if (item && item.id && item.process_flow && item.process_flow.processes && item.process_flow.processes.length) {
          processFlowByFramework[item.id] = item.process_flow;
        }
      });
    } catch (_) {}
  }
  var profiles = [];
  var selectedProfile = '';
  var selectedProcessId = '';
  var showLinkedFlows = false;
  var detailOpen = false;
  var selectedDetailKey = null;
  var showProfileControls = false;
  function applyProcessData(nextData, preferredProcessId) {
    if (nextData && nextData.processes && nextData.processes.length) data = nextData;
    profiles = data.profiles && data.profiles.length ? data.profiles : [{id: 'baseline', title: 'Baseline assurance'}];
    selectedProfile = data.selected_profile || profiles[0].id;
    if (preferredProcessId && (data.processes || []).some(function(process) { return process.id === preferredProcessId; })) {
      selectedProcessId = preferredProcessId;
    } else {
      selectedProcessId = data.selected_process || (data.processes[0] && data.processes[0].id) || '';
    }
    showProfileControls = profiles.length > 1 || (profiles[0] && profiles[0].id !== 'baseline');
  }
  applyProcessData(data);
  var statusColors = {met: '#35d07f', partial: '#8fcbe8', manual: '#ffd166', blocked: '#ff4d6d'};
  var statusLabels = {met: 'Met', partial: 'Partial', manual: 'Manual review', blocked: 'Blocked'};
  var transitionColors = {primary: '#8fcbe8', success: '#35d07f', warning: '#ffd166', danger: '#ff4d6d', muted: '#6b7f88'};
  function esc(value) {
    return String(value || '').replace(/[&<>"']/g, function(ch) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch];
    });
  }
  function splitText(value, maxLen, maxLines) {
    var words = String(value || '').split(/\s+/).filter(Boolean);
    var lines = [], current = '';
    words.forEach(function(word) {
      if (!current) current = word;
      else if ((current + ' ' + word).length <= maxLen) current += ' ' + word;
      else { lines.push(current); current = word; }
    });
    if (current) lines.push(current);
    if (!lines.length) lines = [''];
    if (lines.length > maxLines) {
      lines = lines.slice(0, maxLines);
      lines[lines.length - 1] = lines[lines.length - 1].replace(/\.*$/, '') + '...';
    }
    return lines;
  }
  function truncateText(value, maxLen) {
    value = String(value || '');
    if (value.length <= maxLen) return value;
    return value.slice(0, Math.max(0, maxLen - 3)).replace(/\s+$/, '') + '...';
  }
  function profileTitle(profileId) {
    var match = profiles.find(function(profile) { return profile.id === profileId; });
    return match ? (match.title || match.id) : profileId;
  }
  function itemProfiles(item) {
    return item && item.profiles && item.profiles.length ? item.profiles : [];
  }
  function appliesToProfile(item, profile) {
    var itemProfileList = itemProfiles(item);
    return !itemProfileList.length || itemProfileList.indexOf(profile) >= 0;
  }
  function outsideSelectedProfile(item) {
    var itemProfileList = itemProfiles(item);
    return itemProfileList.length && !appliesToProfile(item, selectedProfile);
  }
  function profilesLabel(item) {
    var itemProfileList = itemProfiles(item);
    var values = itemProfileList.length ? itemProfileList : profiles.map(function(profile) { return profile.id; });
    return values.map(profileTitle).join(', ');
  }
  function profileChip(item) {
    if (!showProfileControls) return '';
    return '<span class="gate-flow-profile-chip">' + esc(profilesLabel(item)) + '</span>';
  }
  function selectedProfileChip() {
    if (!showProfileControls) return '';
    return '<span class="gate-flow-profile-chip is-selected">' + esc(profileTitle(selectedProfile)) + '</span>';
  }
  function profileScopedLabel(label) {
    return showProfileControls ? label + ' for ' + profileTitle(selectedProfile) : label;
  }
  function closeProcessDetail() {
    detailOpen = false;
    selectedDetailKey = null;
    if (detail) detail.classList.remove('is-open');
  }
  function setDetail(key, html) {
    if (!detail) return;
    if (detailOpen && selectedDetailKey === key) {
      closeProcessDetail();
      return;
    }
    selectedDetailKey = key;
    detail.innerHTML = '<button type="button" class="graph-detail-x" aria-label="Close details">×</button>' + html;
    detailOpen = true;
    detail.classList.add('is-open');
  }
  if (detail) {
    detail.addEventListener('click', function(event) {
      if (event.target && event.target.classList && event.target.classList.contains('graph-detail-x')) {
        event.stopPropagation();
        closeProcessDetail();
      }
    });
  }
  function processById(processId) {
    return (data.processes || []).find(function(process) { return process.id === processId; }) || data.processes[0];
  }
  function selectedProcess() {
    return processById(selectedProcessId);
  }
  function linkedProcesses(processId) {
    return (data.process_links || []).filter(function(link) {
      return link.from_process === processId || link.to_process === processId;
    }).map(function(link) {
      var otherId = link.from_process === processId ? link.to_process : link.from_process;
      return {link: link, process: processById(otherId), direction: link.from_process === processId ? 'out' : 'in'};
    }).filter(function(item) { return item.process && item.process.id !== processId; });
  }
  function evidenceForProfile(criterion) {
    return (criterion.evidence || []).filter(function(ev) { return appliesToProfile(ev, selectedProfile); });
  }
  function criterionStatusForProfile(criterion) {
    var evidence = evidenceForProfile(criterion);
    var required = evidence.filter(function(ev) { return ev.required !== false; });
    if (!required.length) return 'manual';
    if (required.every(function(ev) { return ev.status === 'met'; })) return 'met';
    if (required.some(function(ev) { return ev.status === 'missing'; })) return 'blocked';
    return 'manual';
  }
  function gateStatsForProfile(gate) {
    var criteria = (gate.criteria || []).filter(function(criterion) { return appliesToProfile(criterion, selectedProfile); });
    var requiredCriteria = criteria.filter(function(criterion) { return criterion.required !== false; });
    var met = 0, manual = 0, blocked = 0;
    requiredCriteria.forEach(function(criterion) {
      var status = criterionStatusForProfile(criterion);
      if (status === 'met') met += 1;
      else if (status === 'blocked') blocked += 1;
      else manual += 1;
    });
    var missingRoles = (gate.roles || []).filter(function(role) {
      return appliesToProfile(role, selectedProfile) && role.required !== false && !role.assigned;
    }).length;
    var status = 'partial';
    if (blocked || missingRoles) status = 'blocked';
    else if (manual) status = 'manual';
    else if (requiredCriteria.length && met === requiredCriteria.length) status = 'met';
    return {status: status, met: met, required: requiredCriteria.length, missingRoles: missingRoles};
  }
  function detailMetric(label, value) {
    return '<div class="graph-detail-metric"><span>' + esc(label) + '</span><strong>' + esc(value) + '</strong></div>';
  }
  function detailSection(label, html, extraClass) {
    return '<div class="graph-detail-section ' + esc(extraClass || '') + '"><span class="graph-detail-label">' + esc(label) + '</span>' + html + '</div>';
  }
  function gateDetail(gate, process) {
    var stats = gateStatsForProfile(gate);
    var activeRoles = (gate.roles || []).filter(function(role) { return appliesToProfile(role, selectedProfile); });
    var roles = activeRoles.map(function(role) {
      return '<li class="' + (role.assigned ? 'role-ok' : 'role-missing') + '"><strong>' + esc(role.title) + '</strong> <span>' + esc(role.responsibility) + '</span> <em>' + esc(role.party || role.status || (role.required ? 'required' : 'optional')) + '</em></li>';
    }).join('');
    var blockers = (gate.blockers || []).map(function(b) { return '<li>' + esc(b) + '</li>'; }).join('');
    var criteriaInProfile = (gate.criteria || []).filter(function(criterion) { return appliesToProfile(criterion, selectedProfile); });
    var criteria = criteriaInProfile.map(function(criterion) {
      var criterionStatus = criterionStatusForProfile(criterion);
      var evidence = evidenceForProfile(criterion).map(function(ev) {
        return '<li class="' + (ev.status === 'met' ? 'evidence-ok' : ev.status === 'missing' ? 'evidence-missing' : 'evidence-manual') + '"><code>' + esc(ev.type) + '</code> ' + esc(ev.label || ev.ref) + ' ' + profileChip(ev) + '</li>';
      }).join('');
      return '<tr class="criterion-row criterion-' + esc(criterionStatus) + '">' +
        '<td><code>' + esc(criterion.id) + '</code></td>' +
        '<td><strong>' + esc(criterion.title) + '</strong> ' + profileChip(criterion) + '<div class="criterion-desc">' + esc(criterion.description || '') + '</div><ul class="evidence-list">' + evidence + '</ul></td>' +
        '<td><span class="gate-status gate-status-' + esc(criterionStatus) + '">' + esc(statusLabels[criterionStatus] || criterionStatus) + '</span></td>' +
        '</tr>';
    }).join('');
    var criteriaBlock = criteria ? detailSection('Criteria', '<table class="matrix process-criteria-table gate-flow-criteria"><thead><tr><th>Criterion</th><th>Evidence required</th><th>Status</th></tr></thead><tbody>' + criteria + '</tbody></table>') : '';
    var otherProfileCriteria = (gate.criteria || []).filter(outsideSelectedProfile).map(function(criterion) {
      return '<li><strong>' + esc(criterion.id) + '</strong> ' + esc(criterion.title) + ' ' + profileChip(criterion) + '</li>';
    }).join('');
    var otherProfileBlock = otherProfileCriteria ? detailSection('Other assurance profiles', '<ul class="gate-flow-other-profile-list">' + otherProfileCriteria + '</ul>') : '';
    var compliance = (gate.compliance_rules || []).filter(function(rule) { return appliesToProfile(rule, selectedProfile); }).map(function(rule) {
      var requiredLabel = rule.required ? 'required' : 'supporting';
      var criteriaRefs = (rule.criteria || []).filter(Boolean).join(', ');
      return '<tr>' +
        '<td><code>' + esc(rule.ruleset) + '</code><br><code>' + esc(rule.row) + '</code></td>' +
        '<td><strong>' + esc(rule.fr_id) + '</strong> ' + profileChip(rule) + '<div class="criterion-desc">' + esc(rule.fr_title || '') + '</div><div class="manual-evidence">' + esc(criteriaRefs ? 'Criteria: ' + criteriaRefs : '') + '</div></td>' +
        '<td><span class="graph-node-status graph-status-' + esc(rule.fr_status || 'missing') + '">' + esc(rule.fr_status || 'missing') + '</span><span class="graph-edge-type">' + esc(requiredLabel) + '</span></td>' +
        '</tr>';
    }).join('');
    var complianceBlock = compliance ? detailSection('Code compliance rules', '<table class="matrix gate-flow-compliance"><thead><tr><th>Rule</th><th>Mapped FR</th><th>Status</th></tr></thead><tbody>' + compliance + '</tbody></table>') : '';
    return '<div class="graph-node-detail process-inspector">' +
      '<div class="graph-detail-heading"><span>Gate checkpoint</span><strong>Gate ' + esc(gate.sequence) + ' · ' + esc(gate.title) + '</strong></div>' +
      '<div class="graph-chip-row">' + selectedProfileChip() + '<span class="graph-node-status graph-status-' + esc(stats.status) + '">' + esc(statusLabels[stats.status] || stats.status) + '</span><span class="graph-edge-type">' + esc(process.title) + '</span></div>' +
      detailSection('Summary', '<p>' + esc(gate.description || 'No gate description supplied.') + '</p>') +
      '<div class="graph-detail-metric-grid">' +
        detailMetric(profileScopedLabel('Mandatory criteria'), stats.met + '/' + stats.required) +
        detailMetric('Missing roles', stats.missingRoles) +
        detailMetric('Continuation', gate.continuation_rule || 'not specified') +
      '</div>' +
      detailSection('Required roles', '<ul class="gate-flow-role-list">' + roles + '</ul>') +
      complianceBlock +
      criteriaBlock +
      otherProfileBlock +
      (blockers ? detailSection('Blockers', '<ul class="gate-flow-blocker-list">' + blockers + '</ul>', 'graph-detail-section-blocked') : '') +
      '</div>';
  }
  function rolesDetail(gate, process) {
    var roles = (gate.roles || []).filter(function(role) { return appliesToProfile(role, selectedProfile); });
    var assigned = roles.filter(function(role) { return role.assigned; }).length;
    var items = roles.map(function(role) {
      return '<li class="' + (role.assigned ? 'role-ok' : 'role-missing') + '"><strong>' + esc(role.title || role.role) + '</strong> ' + profileChip(role) + ' <span>' + esc(role.responsibility || '') + '</span> <em>' + esc(role.party || role.status || (role.required ? 'required' : 'optional')) + '</em></li>';
    }).join('');
    return '<div class="graph-node-detail process-inspector">' +
      '<div class="graph-detail-heading"><span>Roles and approvals</span><strong>Gate ' + esc(gate.sequence) + ' · ' + esc(gate.title) + '</strong></div>' +
      '<div class="graph-chip-row">' + selectedProfileChip() + '<span class="graph-node-status graph-status-' + esc(gateStatsForProfile(gate).status) + '">' + esc(statusLabels[gateStatsForProfile(gate).status] || gateStatsForProfile(gate).status) + '</span><span class="graph-edge-type">' + esc(process.title) + '</span></div>' +
      '<div class="graph-detail-metric-grid">' +
        detailMetric(profileScopedLabel('Assigned roles'), assigned + '/' + roles.length) +
        detailMetric('Continuation', gate.continuation_rule || 'not specified') +
      '</div>' +
      detailSection('Required roles', '<ul class="gate-flow-role-list">' + items + '</ul>') + '</div>';
  }
  function roleDetail(role, gate, process) {
    return '<div class="graph-node-detail process-inspector">' +
      '<div class="graph-detail-heading"><span>Role</span><strong>' + esc(role.title || role.role) + '</strong></div>' +
      '<div class="graph-chip-row">' + selectedProfileChip() + '<span class="graph-node-status ' + (role.assigned ? 'graph-status-met' : 'graph-status-blocked') + '">' + esc(role.assigned ? 'Assigned' : 'Missing') + '</span><span class="graph-edge-type">Gate ' + esc(gate.sequence) + '</span><span class="graph-edge-type">' + esc(process.title) + '</span></div>' +
      detailSection('Responsibility', '<p>' + esc(role.responsibility || 'No responsibility text supplied.') + '</p>') +
      '<div class="graph-detail-metric-grid">' +
        detailMetric('Party / status', role.party || role.status || (role.required ? 'required' : 'optional')) +
        detailMetric('Role ID', role.role || '') +
        detailMetric('Gate', gate.title || gate.id) +
      '</div>' +
      (showProfileControls ? detailSection('Applies to', profileChip(role)) : '') + '</div>';
  }
  function setupProfileControl() {
    if (!profileControl) return;
    var hasGlobalProcessControl = Boolean(document.getElementById('global-process-select'));
    var processOptions = (data.processes || []).map(function(process) {
      return '<option value="' + esc(process.id) + '"' + (process.id === selectedProcessId ? ' selected' : '') + '>' + esc(process.title || process.id) + '</option>';
    }).join('');
    profileControl.innerHTML =
      (hasGlobalProcessControl
        ? '<select id="process-flow-select" class="graph-select process-flow-proxy" hidden>' + processOptions + '</select>'
        : '<label class="process-flow-field"><span>Gated flow</span><select id="process-flow-select" class="graph-select">' + processOptions + '</select></label>') +
      '<label class="process-flow-toggle"><input id="process-flow-linked-toggle" type="checkbox"' + (showLinkedFlows ? ' checked' : '') + '> Show linked flows</label>' +
      (showProfileControls ? '<span>Assurance profile</span>' + profiles.map(function(profile) {
        return '<button type="button" class="process-profile-btn' + (profile.id === selectedProfile ? ' active' : '') + '" data-profile="' + esc(profile.id) + '" aria-pressed="' + (profile.id === selectedProfile ? 'true' : 'false') + '">' + esc(profile.title || profile.id) + '</button>';
      }).join('') : '');
    var select = profileControl.querySelector('#process-flow-select');
    if (select) {
      select.addEventListener('change', function() {
        selectedProcessId = select.value;
        closeProcessDetail();
        renderCurrent();
      });
    }
    var linkedToggle = profileControl.querySelector('#process-flow-linked-toggle');
    if (linkedToggle) {
      linkedToggle.addEventListener('change', function() {
        showLinkedFlows = linkedToggle.checked;
        closeProcessDetail();
        renderCurrent();
      });
    }
    profileControl.querySelectorAll('[data-profile]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        selectedProfile = btn.dataset.profile;
        closeProcessDetail();
        renderCurrent();
      });
    });
  }
  function render() {
    if (!canvas.offsetParent || canvas.clientWidth < 200) return;
    setupProfileControl();
    canvas.innerHTML = '';
    var process = selectedProcess();
    if (!process) {
      canvas.innerHTML = '<div class="empty-state">No gated flow is selected.</div>';
      return;
    }
    var gateW = 260, gateH = 108;
    var roleW = 196, roleH = 38, hubR = 25;
    var outcomeW = 212, outcomeH = 54;
    var leftPad = 205, rightPad = 220, topPad = 96;
    var roleHubGap = 126, roleColumnGap = 238, roleRowGap = 58;
    var gates = (process.gates || []).slice().sort(function(a, b) { return (a.sequence || 0) - (b.sequence || 0); });
    var maxRoles = Math.max.apply(null, gates.map(function(gate) {
      return ((gate.roles || []).filter(function(role) { return appliesToProfile(role, selectedProfile); }).length || 1);
    }).concat([1]));
    var gateStep = Math.max(286, Math.min(390, maxRoles * roleRowGap + 92));
    var linked = linkedProcesses(process.id);
    var roleLaneX = leftPad + gateW / 2 + roleHubGap + roleColumnGap;
    var outcomeLaneX = roleLaneX + roleW / 2 + 300;
    var linkedLaneX = outcomeLaneX + outcomeW / 2 + 270;
    var width = Math.max(canvas.clientWidth || 860, linkedLaneX + (showLinkedFlows ? 260 : 70));
    var height = Math.max(680, topPad + Math.max(1, gates.length - 1) * gateStep + 220);
    var svg = d3.select(canvas).append('svg')
      .attr('width', width).attr('height', height)
      .attr('role', 'img')
      .attr('aria-label', 'Process gate flow');
    svg.append('rect').attr('class', 'graph-viewport-bg').attr('x', 0).attr('y', 0).attr('width', width).attr('height', height);
    var defs = svg.append('defs');
    defs.append('marker').attr('id', 'gate-flow-arrow').attr('viewBox', '0 -5 10 10')
      .attr('refX', 10).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6)
      .attr('orient', 'auto').append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#8fcbe8');
    var processX = leftPad;
    svg.append('text').attr('class', 'process-flow-process-label').attr('x', Math.max(24, processX - gateW / 2)).attr('y', 28).text(process.title || process.id);
    gates.forEach(function(gate, idx) {
      gate.x = processX;
      gate.y = topPad + idx * gateStep;
    });
    var nodeById = {};
    gates.forEach(function(gate) { nodeById[gate.id] = gate; });
    var outcomeById = {};
    (process.exit_outcomes || []).forEach(function(outcome) {
      delete outcome.x;
      delete outcome.y;
      outcomeById[outcome.id] = outcome;
    });
    var outcomeCounts = {};
    var transitions = (process.transitions || []).slice();
    if (!transitions.length) {
      transitions = gates.slice(0, -1).map(function(g, idx) {
        return {from: g.id, to: gates[idx + 1].id, label: 'Next gate', style: 'primary'};
      });
    }
    transitions.forEach(function(t) {
      var source = nodeById[t.from];
      var targetGate = nodeById[t.to];
      var targetOutcome = outcomeById[t.to];
      if (!source || (!targetGate && !targetOutcome)) return;
      if (targetOutcome && !targetOutcome.x) {
        var key = source.id;
        var count = outcomeCounts[key] || 0;
        outcomeCounts[key] = count + 1;
        targetOutcome.x = outcomeLaneX;
        targetOutcome.y = source.y + (count - .5) * 76;
      }
    });
    var visibleOutcomes = Object.keys(outcomeById).map(function(id) { return outcomeById[id]; }).filter(function(outcome) { return outcome.x; });
    var linkLayer = svg.append('g').attr('class', 'process-flow-links');
    transitions.forEach(function(t) {
      var source = nodeById[t.from];
      var target = nodeById[t.to] || outcomeById[t.to];
      if (!source || !target) return;
      var color = transitionColors[t.style || 'primary'] || '#8fcbe8';
      var sourceIsGate = Boolean(nodeById[t.from]);
      var targetIsGate = Boolean(nodeById[t.to]);
      var sx = source.x + (target.x > source.x ? gateW / 2 : 0);
      var sy = source.y + (targetIsGate ? gateH / 2 + 10 : 0);
      var tx = target.x - (target.x > source.x ? (targetIsGate ? 0 : outcomeW / 2) : 0);
      var ty = target.y - (targetIsGate ? gateH / 2 + 10 : 0);
      var path = targetIsGate
        ? 'M' + source.x + ',' + sy + ' C' + source.x + ',' + (sy + 50) + ' ' + target.x + ',' + (ty - 50) + ' ' + target.x + ',' + ty
        : 'M' + sx + ',' + sy + ' C' + (sx + 86) + ',' + sy + ' ' + (tx - 86) + ',' + ty + ' ' + tx + ',' + ty;
      linkLayer.append('path')
        .attr('d', path)
        .attr('fill', 'none').attr('stroke', color).attr('stroke-opacity', targetIsGate ? .48 : .58).attr('stroke-width', targetIsGate ? 1.5 : 1.35)
        .attr('marker-end', 'url(#gate-flow-arrow)');
      if (t.label && !targetIsGate) {
        linkLayer.append('text').attr('class', 'process-flow-transition-label')
          .attr('x', Math.min(tx - 38, (sx + tx) / 2)).attr('y', (sy + ty) / 2 - 10)
          .attr('text-anchor', 'middle').text(truncateText(t.label, 24));
      }
    });
      var gateG = svg.append('g').attr('class', 'process-flow-gates').selectAll('g')
        .data(gates).enter().append('g')
        .attr('tabindex', 0).attr('role', 'button')
        .attr('aria-label', function(d) { return 'Gate ' + d.sequence + ' ' + d.title; })
        .attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; })
        .on('click', function(event, d) { setDetail('gate:' + d.id, gateDetail(d, process)); })
        .on('keydown', function(event, d) { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setDetail('gate:' + d.id, gateDetail(d, process)); } });
      gateG.append('rect')
        .attr('class', 'process-flow-gate-card')
        .attr('x', -gateW / 2).attr('y', -gateH / 2)
        .attr('width', gateW).attr('height', gateH).attr('rx', 7)
        .attr('stroke', function(d) { return statusColors[gateStatsForProfile(d).status] || '#718096'; });
      gateG.append('rect')
        .attr('x', -gateW / 2).attr('y', -gateH / 2)
        .attr('width', 6).attr('height', gateH).attr('rx', 4)
        .attr('fill', function(d) { return statusColors[d.status] || '#718096'; });
      gateG.append('text').attr('class', 'process-flow-gate-kind').attr('x', -gateW / 2 + 18).attr('y', -gateH / 2 + 22)
        .text(function(d) { return 'GATE ' + (d.sequence || ''); });
      gateG.append('text').attr('class', 'process-flow-gate-title').attr('x', -gateW / 2 + 18).attr('y', -gateH / 2 + 49)
        .each(function(d) {
          var text = d3.select(this);
          splitText(d.title, 27, 3).forEach(function(line, lineIdx) {
            text.append('tspan').attr('x', -gateW / 2 + 18).attr('dy', lineIdx === 0 ? 0 : 15).text(line);
          });
        });
      gateG.append('text').attr('class', 'process-flow-status-label').attr('x', gateW / 2 - 14).attr('y', -gateH / 2 + 22)
        .attr('text-anchor', 'end')
        .text(function(d) { return statusLabels[gateStatsForProfile(d).status] || gateStatsForProfile(d).status; });
      var outcomeG = svg.append('g').attr('class', 'process-flow-outcomes').selectAll('g')
        .data(visibleOutcomes).enter().append('g')
        .attr('tabindex', 0).attr('role', 'button')
        .attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; })
        .on('click', function(event, d) {
          setDetail('outcome:' + d.id, '<div class="graph-node-detail"><div class="graph-detail-heading"><span>Outcome</span><strong>' + esc(d.title || d.id) + '</strong></div><div class="graph-chip-row"><span class="gate-flow-profile-chip">' + esc(d.authority_category || 'outcome') + '</span><span class="graph-edge-type">' + esc(d.status || 'outcome') + '</span></div><div class="graph-detail-section"><span class="graph-detail-label">Context</span><p>' + esc(d.description || '') + '</p></div></div>');
        });
      outcomeG.append('rect')
        .attr('class', 'process-flow-outcome-card')
        .attr('x', -outcomeW / 2).attr('y', -outcomeH / 2)
        .attr('width', outcomeW).attr('height', outcomeH).attr('rx', 7);
      outcomeG.append('text').attr('class', 'process-flow-gate-kind').attr('x', -outcomeW / 2 + 12).attr('y', -outcomeH / 2 + 17)
        .text(function(d) { return d.authority_category || 'OUTCOME'; });
      outcomeG.append('text').attr('class', 'process-flow-role-text').attr('x', -outcomeW / 2 + 12).attr('y', -2)
        .each(function(d) {
          var text = d3.select(this);
          splitText(d.title, 28, 2).forEach(function(line, lineIdx) {
            text.append('tspan').attr('x', -outcomeW / 2 + 12).attr('dy', lineIdx === 0 ? 0 : 12).text(line);
          });
        });
      var roleLayer = svg.append('g').attr('class', 'process-flow-roles');
      gates.forEach(function(gate) {
        var roles = (gate.roles || []).slice(0, 6);
        roles = roles.filter(function(role) { return appliesToProfile(role, selectedProfile); });
        if (!roles.length) return;
        var hubX = gate.x + gateW / 2 + roleHubGap;
        var hubY = gate.y;
        roleLayer.append('path')
          .attr('class', 'process-flow-role-link')
          .attr('d', 'M' + (gate.x + gateW / 2) + ',' + gate.y + ' C' + (gate.x + gateW / 2 + 36) + ',' + gate.y + ' ' + (hubX - 36) + ',' + hubY + ' ' + (hubX - hubR) + ',' + hubY)
          .attr('marker-end', 'url(#gate-flow-arrow)');
        var hub = roleLayer.append('g')
          .attr('class', 'process-flow-role-hub')
          .attr('tabindex', 0).attr('role', 'button')
          .attr('aria-label', 'Roles for gate ' + gate.sequence)
          .attr('transform', 'translate(' + hubX + ',' + hubY + ')')
          .on('click', function(event) { event.stopPropagation(); setDetail('roles:' + gate.id, rolesDetail(gate, process)); })
          .on('keydown', function(event) { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setDetail('roles:' + gate.id, rolesDetail(gate, process)); } });
        hub.append('circle').attr('r', hubR).attr('stroke', roles.every(function(r) { return r.assigned; }) ? '#35d07f' : '#ff4d6d');
        hub.append('text').attr('text-anchor', 'middle').attr('y', -2).text('ROLES');
        hub.append('text').attr('text-anchor', 'middle').attr('y', 10).text(roles.filter(function(r) { return r.assigned; }).length + '/' + roles.length);
        roles.forEach(function(role, ridx) {
          var roleX = hubX + roleColumnGap;
          var roleY = hubY + (ridx - (roles.length - 1) / 2) * roleRowGap;
          roleLayer.append('path')
            .attr('class', 'process-flow-role-link')
            .attr('d', 'M' + (hubX + hubR) + ',' + hubY + ' C' + (hubX + 42) + ',' + hubY + ' ' + (roleX - 42) + ',' + roleY + ' ' + (roleX - roleW / 2) + ',' + roleY)
            .attr('marker-end', 'url(#gate-flow-arrow)');
          var roleNode = roleLayer.append('g')
            .attr('class', 'process-flow-role-node')
            .attr('tabindex', 0).attr('role', 'button')
            .attr('aria-label', (role.title || role.role) + ' role')
            .attr('transform', 'translate(' + roleX + ',' + roleY + ')')
            .on('click', function(event) { event.stopPropagation(); setDetail('role:' + gate.id + ':' + (role.role || role.title || ridx), roleDetail(role, gate, process)); })
            .on('keydown', function(event) { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setDetail('role:' + gate.id + ':' + (role.role || role.title || ridx), roleDetail(role, gate, process)); } });
          roleNode.append('rect')
            .attr('x', -roleW / 2).attr('y', -roleH / 2)
            .attr('width', roleW).attr('height', roleH).attr('rx', 6)
            .attr('stroke', role.assigned ? '#35d07f' : '#ff4d6d');
          roleNode.append('text').attr('class', 'process-flow-role-text').attr('x', -roleW / 2 + 10).attr('y', -4)
            .text(truncateText(role.title || role.role, 27));
          roleNode.append('text').attr('class', 'process-flow-role-subtext').attr('x', -roleW / 2 + 10).attr('y', 12)
            .text(role.assigned ? 'ASSIGNED' : 'MISSING');
        });
      });
      if (showLinkedFlows && linked.length) {
        var linkedLayer = svg.append('g').attr('class', 'process-flow-linked');
        var linkX = linkedLaneX;
        linkedLayer.append('text').attr('class', 'process-flow-process-label').attr('x', linkX - 85).attr('y', 28).text('Linked flows');
        linked.forEach(function(item, idx) {
          var y = topPad + idx * 108;
          var card = linkedLayer.append('g')
            .attr('tabindex', 0).attr('role', 'button')
            .attr('transform', 'translate(' + linkX + ',' + y + ')')
            .on('click', function() { selectedProcessId = item.process.id; renderCurrent(); });
          card.append('rect').attr('class', 'process-flow-linked-card').attr('x', -95).attr('y', -34).attr('width', 190).attr('height', 68).attr('rx', 7);
          card.append('text').attr('class', 'process-flow-gate-kind').attr('x', -82).attr('y', -14).text(item.direction === 'out' ? 'NEXT FLOW' : 'SOURCE FLOW');
          card.append('text').attr('class', 'process-flow-role-text').attr('x', -82).attr('y', 4).text(truncateText(item.process.title || item.process.id, 28));
          card.append('text').attr('class', 'process-flow-role-subtext').attr('x', -82).attr('y', 19).text(truncateText(item.link.label || item.link.relationship || 'linked', 30));
          linkLayer.append('path')
            .attr('d', 'M' + (processX + gateW / 2 + 40) + ',' + y + ' C' + (processX + 330) + ',' + y + ' ' + (linkX - 155) + ',' + y + ' ' + (linkX - 95) + ',' + y)
            .attr('fill', 'none').attr('stroke', '#8fcbe8').attr('stroke-opacity', .34).attr('stroke-width', 1.2)
            .attr('marker-end', 'url(#gate-flow-arrow)');
        });
      }
    if (detail) detail.classList.toggle('is-open', detailOpen);
    canvas.scrollTop = 0;
    canvas.scrollLeft = 0;
  }
  function renderCurrent() {
    window.requestAnimationFrame(function() { window.requestAnimationFrame(render); });
  }
  function setProcess(processId) {
    if (processId && processById(processId)) selectedProcessId = processId;
    closeProcessDetail();
    renderCurrent();
  }
  function setFramework(frameworkId, preferredProcessId) {
    var nextData = processFlowByFramework[frameworkId || ''];
    if (!nextData) return false;
    applyProcessData(nextData, preferredProcessId || '');
    closeProcessDetail();
    renderCurrent();
    return true;
  }
  function getProcesses() {
    return (data.processes || []).map(function(process) {
      var label = process.title || process.id;
      label = label.replace(/^JSP\s*453\s+/i, '');
      return {value: process.id, label: label};
    });
  }
  window.asvsProcessFlow = {renderCurrent: renderCurrent, setProcess: setProcess, setFramework: setFramework, getProcesses: getProcesses};
  if (canvas.offsetParent) renderCurrent();
}

function setupGlobalContext() {
  var frameworkSelect = document.getElementById('global-framework-select');
  var processSelect = document.getElementById('global-process-select');
  var rulesetSelect = document.getElementById('global-ruleset-select');
  var chapterSelect = document.getElementById('global-chapter-select');
  if (!frameworkSelect || !processSelect || !rulesetSelect || !chapterSelect) return;
  if (window.asvsGlobalContext && window.asvsGlobalContext.ready) {
    window.asvsGlobalContext.sync();
    return;
  }
  function addOptions(select, options, emptyLabel) {
    select.innerHTML = '';
    if (!options.length) {
      var opt = document.createElement('option');
      opt.value = '';
      opt.textContent = emptyLabel || 'Not available';
      select.appendChild(opt);
      select.disabled = true;
      return;
    }
    select.disabled = false;
    options.forEach(function(item) {
      var opt = document.createElement('option');
      opt.value = item.value;
      opt.textContent = item.label;
      if (item.path) opt.dataset.path = item.path;
      if (item.imagePath) opt.dataset.imagePath = item.imagePath;
      if (item.frameworkId) opt.dataset.frameworkId = item.frameworkId;
      if (item.version) opt.dataset.version = item.version;
      if (item.selected) opt.selected = true;
      select.appendChild(opt);
    });
  }
  function graphOptions() {
    return window.asvsGraph && window.asvsGraph.getContextOptions ? window.asvsGraph.getContextOptions() : {rulesets: [], chapters: [], ruleset: '', chapter: ''};
  }
  function frameworkOptionsData() {
    var el = document.getElementById('framework-options-data');
    if (!el) return [];
    try { return JSON.parse(el.textContent || '[]') || []; } catch (_) { return []; }
  }
  function currentFrameworkOption() {
    var opt = frameworkSelect.options[frameworkSelect.selectedIndex];
    if (!opt) return null;
    return {
      value: opt.value || '',
      label: opt.textContent || '',
      path: opt.dataset.path || '',
      imagePath: opt.dataset.imagePath || '',
      frameworkId: opt.dataset.frameworkId || '',
      version: opt.dataset.version || ''
    };
  }
  function processOptionsForSelected() {
    var framework = currentFrameworkOption();
    var frameworkId = framework ? framework.frameworkId : '';
    var source = frameworkOptionsData().find(function(item) { return item.id === frameworkId || item.image_path === (framework ? framework.imagePath : ''); });
    if (source && Array.isArray(source.processes)) {
      return source.processes.map(function(process) { return {value: process.id, label: process.label || process.id}; });
    }
    return window.asvsProcessFlow && window.asvsProcessFlow.getProcesses ? window.asvsProcessFlow.getProcesses() : [];
  }
  function publishRuntimeContext() {
    var selectedFramework = frameworkSelect.options[frameworkSelect.selectedIndex];
    var selectedProcess = processSelect.options[processSelect.selectedIndex];
    var selectedRuleset = rulesetSelect.options[rulesetSelect.selectedIndex];
    var selectedChapter = chapterSelect.options[chapterSelect.selectedIndex];
    window.asvsRuntimeContext = {
      assurance_framework: {
        value: frameworkSelect.value || '',
        label: selectedFramework ? selectedFramework.textContent : '',
        path: selectedFramework ? (selectedFramework.dataset.path || '') : '',
        image_path: selectedFramework ? (selectedFramework.dataset.imagePath || '') : '',
        version: selectedFramework ? (selectedFramework.dataset.version || '') : ''
      },
      gated_flow: {
        value: processSelect.value || '',
        label: selectedProcess ? selectedProcess.textContent : ''
      },
      compliance_regime: {
        value: rulesetSelect.value || '',
        label: selectedRuleset ? selectedRuleset.textContent : ''
      },
      chapter_family: {
        value: chapterSelect.value || '',
        label: selectedChapter ? selectedChapter.textContent : ''
      }
    };
    if (window.asvsFrameworkTabs && window.asvsFrameworkTabs.applyRuntimeContext) {
      window.asvsFrameworkTabs.applyRuntimeContext(window.asvsRuntimeContext);
    }
    window.dispatchEvent(new CustomEvent('asvs-runtime-context-changed', {detail: window.asvsRuntimeContext}));
    return window.asvsRuntimeContext;
  }
  function syncChapters(preferred) {
    var opts = graphOptions();
    addOptions(chapterSelect, opts.chapters, 'All chapters / families');
    if (preferred && Array.from(chapterSelect.options).some(function(option) { return option.value === preferred; })) {
      chapterSelect.value = preferred;
    } else {
      chapterSelect.value = opts.chapter || '';
    }
  }
  function sync() {
    var flowData = {};
    var flowEl = document.getElementById('process-flow-data');
    if (flowEl) {
      try { flowData = JSON.parse(flowEl.textContent || '{}') || {}; } catch (_) { flowData = {}; }
    }
    var frameworkId = flowData.assurance_framework || '';
    var frameworkTitle = flowData.title || '';
    var frameworkLabel = frameworkTitle || frameworkId || 'Assurance framework';
    var frameworkOptions = frameworkOptionsData().map(function(item) {
      return {
        value: item.id || item.label || '',
        label: item.label || item.title || item.id || 'Assurance framework',
        path: item.path || '',
        imagePath: item.image_path || item.path || '',
        frameworkId: item.id || '',
        version: item.version || '',
        selected: Boolean(item.selected) || Boolean(frameworkId && item.id === frameworkId)
      };
    });
    if (!frameworkOptions.length) {
      frameworkOptions = [{value: frameworkId || frameworkLabel, label: frameworkLabel, frameworkId: frameworkId, selected: true}];
    }
    if (!frameworkOptions.some(function(item) { return item.selected; })) frameworkOptions[0].selected = true;
    addOptions(frameworkSelect, frameworkOptions, 'No framework');
    addOptions(processSelect, processOptionsForSelected(), 'No gated flow');
    var opts = graphOptions();
    addOptions(rulesetSelect, opts.rulesets, 'No compliance regime');
    rulesetSelect.value = opts.ruleset || '';
    syncChapters(opts.chapter);
    publishRuntimeContext();
  }
  frameworkSelect.addEventListener('change', function() {
    addOptions(processSelect, processOptionsForSelected(), 'No gated flow');
    if (window.asvsProcessFlow && window.asvsProcessFlow.setFramework) {
      window.asvsProcessFlow.setFramework(frameworkSelect.value, processSelect.value);
    } else if (window.asvsProcessFlow && window.asvsProcessFlow.setProcess) {
      window.asvsProcessFlow.setProcess(processSelect.value);
    }
    publishRuntimeContext();
  });
  processSelect.addEventListener('change', function() {
    if (window.asvsProcessFlow && window.asvsProcessFlow.setProcess) window.asvsProcessFlow.setProcess(processSelect.value);
    publishRuntimeContext();
  });
  rulesetSelect.addEventListener('change', function() {
    var opts = window.asvsGraph && window.asvsGraph.setRuleset ? window.asvsGraph.setRuleset(rulesetSelect.value, true) : graphOptions();
    syncChapters(opts.chapter);
    publishRuntimeContext();
  });
  chapterSelect.addEventListener('change', function() {
    if (window.asvsGraph && window.asvsGraph.setChapter) window.asvsGraph.setChapter(chapterSelect.value, true);
    publishRuntimeContext();
  });
  window.asvsGlobalContext = {ready: true, sync: sync, getContext: publishRuntimeContext};
  sync();
}
