const STORAGE_KEY = 'outcome-gate-state-v1';
const app = document.querySelector('#app');
const objectiveDialog = document.querySelector('#objectiveDialog');
const transitionDialog = document.querySelector('#transitionDialog');
const routeDialog = document.querySelector('#routeDialog');
const routeEvidenceDialog = document.querySelector('#routeEvidenceDialog');
const baselineEvidenceDialog = document.querySelector('#baselineEvidenceDialog');
const state = loadState();
let activeView = 'objective';
let signatures = [];
let pendingRouteResult = null;

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const data = JSON.parse(raw);
      if (data?.schemaVersion === 1 && Array.isArray(data.objectives)) {
        data.objectives.forEach((objective) => { if (objective.decisionTraceRequired === undefined) objective.decisionTraceRequired = true; });
        return data;
      }
    }
  } catch (error) {
    console.warn('Could not load saved state', error);
  }
  return { schemaVersion: 1, runtime: { name: 'shadow', version: '4.2' }, objectives: [], activeId: null };
}

function persist() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function activeObjective() {
  return state.objectives.find((item) => item.id === state.activeId) || null;
}

function lastOf(items) { return items && items.length ? items[items.length - 1] : null; }

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

function safeUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' ? url.href : '';
  } catch { return ''; }
}

function fmtDate(value) {
  try { return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(value)); }
  catch { return 'Date unavailable'; }
}

function compareValue(value, operator, target) {
  if (operator === 'contains') return String(value).toLocaleLowerCase().includes(String(target).toLocaleLowerCase());
  const leftNumber = Number(value);
  const rightNumber = Number(target);
  const numeric = String(value).trim() !== '' && String(target).trim() !== '' && Number.isFinite(leftNumber) && Number.isFinite(rightNumber);
  const left = numeric ? leftNumber : String(value).trim();
  const right = numeric ? rightNumber : String(target).trim();
  if (operator === 'gte') return numeric && left >= right;
  if (operator === 'lte') return numeric && left <= right;
  return left === right;
}

function checkDecisionTrace(trace) {
  const violations = [];
  if (!trace || typeof trace !== 'object' || Array.isArray(trace)) return ['K-0 decision trace is missing or not an object'];
  const licenses = new Set(['TOOL', 'MEMORY', 'STATED', 'INFERENCE', 'UNKNOWN']);
  if (!Array.isArray(trace.options)) violations.push('K-0 options must be a list');
  const options = Array.isArray(trace.options) ? trace.options : [];
  if (options.length < 2) violations.push('K-3 decision trace must compare at least two actual options');
  for (const option of options) {
    if (!option || typeof option !== 'object' || Array.isArray(option)) { violations.push('K-0 each option must be an object'); continue; }
    if (!Array.isArray(option.evidence)) { violations.push(`K-0 ${option.id}: evidence must be a list`); continue; }
    const rows = Array.isArray(option.evidence) ? option.evidence : [];
    let sum = 0;
    for (const row of rows) {
      if (!row || typeof row !== 'object' || Array.isArray(row)) { violations.push(`K-0 ${option.id}: each evidence row must be an object`); continue; }
      const weight = Number(row.weight ?? 0);
      if (!licenses.has(row.license)) violations.push(`K-0 ${option.id}: invalid evidence license`);
      if (!Number.isFinite(weight)) violations.push(`K-0 ${option.id}: evidence weight must be finite`);
      else { sum += weight; if (row.license === 'UNKNOWN' && Math.abs(weight) > 1e-9) violations.push(`K-1 ${option.id}: UNKNOWN evidence carries weight`); }
    }
    if (Number.isFinite(Number(option.total_weight)) && Math.abs(Number(option.total_weight) - sum) > 1e-6) violations.push(`K-2 ${option.id}: total differs from licensed evidence sum`);
  }
  const baselineRows = new Set(Array.isArray(trace.baseline_rows) ? trace.baseline_rows : []);
  if (!baselineRows.has('continuation') || !baselineRows.has('delay')) violations.push('K-3 comparison omits continuation or delay');
  if (trace.boundary != null) {
    if (!String(trace.boundary.blocker || '').trim()) violations.push('K-4 boundary has no named blocker');
    if (!Array.isArray(trace.boundary.routes_evaluated) || !trace.boundary.routes_evaluated.some((route) => String(route).trim())) violations.push('K-4 boundary has no evaluated materially different route');
  }
  const superseded = new Set(Array.isArray(trace.superseded_premises) ? trace.superseded_premises : []);
  for (const option of options) {
    const cited = (Array.isArray(option.evidence) ? option.evidence : []).map((row) => row.premise).filter((premise) => superseded.has(premise));
    if (cited.length && !option.recomputed) violations.push(`K-5 ${option.id}: dependent conclusion was not recomputed`);
  }
  return violations;
}

function outcome(obj) {
  if (!obj) return { label: 'No objective', kind: 'blocked', changed: false, targetMet: false, pass: false };
  const current = lastOf(obj.observations)?.value ?? obj.baseline.value;
  const changed = String(current).trim() !== String(obj.baseline.value).trim();
  const targetMet = compareValue(current, obj.target.operator, obj.target.value);
  const last = lastOf(obj.observations);
  const evidenceReady = Boolean(obj.baseline.sourceConfirmed && obj.baseline.evidence?.sha256 && last?.evidence?.sha256 && last?.sourceConfirmed && obj.baseline.evidence.sha256 !== last.evidence.sha256);
  const kernelViolations = obj.decisionTraceRequired ? checkDecisionTrace(obj.decisionTrace) : [];
  const pass = changed && targetMet && evidenceReady && kernelViolations.length === 0;
  if (pass) return { label: 'PASS · changed state + target met + before/after evidence', kind: 'pass', changed, targetMet, pass };
  if (changed && targetMet && evidenceReady && kernelViolations.length) return { label: `OPEN · decision trace needs ${kernelViolations.length} K-1..K-5 fix${kernelViolations.length === 1 ? '' : 'es'}`, kind: 'open', changed, targetMet, pass };
  if (!changed) return { label: 'BLOCKED · no verified state change yet', kind: 'blocked', changed, targetMet, pass };
  if (!targetMet) return { label: 'OPEN · state changed, target still unmet', kind: 'open', changed, targetMet, pass };
  return { label: 'OPEN · target reached, evidence gate incomplete', kind: 'open', changed, targetMet, pass };
}

function targetText(obj) {
  const op = { eq: 'equals', gte: 'at least', lte: 'at most', contains: 'contains' }[obj.target.operator] || obj.target.operator;
  return `${op} ${obj.target.value}${obj.unit ? ` ${obj.unit}` : ''}`;
}

function render() {
  document.querySelectorAll('.nav-item').forEach((button) => button.classList.toggle('active', button.dataset.view === activeView));
  const obj = activeObjective();
  if (!obj) {
    app.innerHTML = document.querySelector('#emptyObjective').innerHTML;
    document.querySelector('#newObjectiveBtn').addEventListener('click', () => openObjectiveDialog());
    return;
  }
  if (activeView === 'discover') renderDiscover(obj);
  else if (activeView === 'verify') renderVerify(obj);
  else renderObjective(obj);
}

function renderObjective(obj) {
  const result = outcome(obj);
  const current = lastOf(obj.observations)?.value ?? obj.baseline.value;
  const baselineUrl = safeUrl(obj.baseline.evidence?.url);
  const timeline = [
    `<div class="timeline-row"><span class="timeline-marker"></span><span class="timeline-date">${escapeHtml(fmtDate(obj.createdAt))}</span><span class="timeline-description"><strong>Starting state</strong><span>${escapeHtml(obj.baseline.value)}${obj.unit ? ` ${escapeHtml(obj.unit)}` : ''}</span></span>${baselineUrl ? `<a class="timeline-link" href="${escapeHtml(baselineUrl)}" target="_blank" rel="noopener">View starting proof</a>` : '<span class="timeline-pending">Proof not added</span>'}</div>`,
    ...obj.observations.map((entry) => `<div class="timeline-row"><span class="timeline-marker"></span><span class="timeline-date">${escapeHtml(fmtDate(entry.at))}</span><span class="timeline-description"><strong>Observed state change</strong><span>${escapeHtml(entry.value)}${obj.unit ? ` ${escapeHtml(obj.unit)}` : ''} · ${escapeHtml(entry.evidence.note)}</span></span><a class="timeline-link" href="${escapeHtml(safeUrl(entry.evidence.url))}" target="_blank" rel="noopener">View evidence</a></div>`),
    `<div class="timeline-row"><span class="timeline-marker"></span><span class="timeline-date">Target</span><span class="timeline-description"><strong>${escapeHtml(targetText(obj))}</strong><span>${result.targetMet ? 'Target condition met' : 'Target condition not met'}</span></span></div>`,
  ].join('');
  const nextEvidence = lastOf(obj.observations)?.evidence;
  app.innerHTML = `
    <div class="page-heading">
      <div><h1>Objective</h1><p class="subhead">The target is frozen. Only measured state transitions move this record forward.</p></div>
      <div class="heading-actions"><span class="status ${result.kind}">${escapeHtml(result.label)}</span><button class="primary-button" id="recordTransitionBtn" ${result.pass ? 'disabled' : ''} type="button">Record state change</button></div>
    </div>
    <section class="objective-panel">
      <div>
        <div class="objective-title">${escapeHtml(obj.statement)}</div>
        <div class="facts">
          <span class="fact-label">Objective</span><span class="fact-value"><strong>Frozen · v${obj.revision}</strong></span>
          <span class="fact-label">Current state</span><span class="fact-value">${escapeHtml(current)}${obj.unit ? ` ${escapeHtml(obj.unit)}` : ''}</span>
          <span class="fact-label">Desired state</span><span class="fact-value">${escapeHtml(targetText(obj))}</span>
          <span class="fact-label">Next transition</span><span class="fact-value">${escapeHtml(obj.nextAction)}</span>
          <span class="fact-label">Current blocker</span><span class="fact-value">${escapeHtml(obj.blocker)}</span>
          <span class="fact-label">Done means</span><span class="fact-value">The measured state changes to your target, with proof of both states.</span>
        </div>
      </div>
      <div class="rule-stack">
        <div class="alert-box"><strong>${escapeHtml(result.label)}</strong><p>A run, a clean scan, a file, or a status message cannot satisfy the state-change gate.</p></div>
        <div class="rule-box"><strong>Pass rule · shadow v4.2</strong><p>PASS requires a changed measured value, the frozen target condition, and before/after evidence. The artifact hashes establish which files were supplied; they do not certify that a source is truthful.</p></div>
      </div>
    </section>
    <section class="section">
      <div class="section-header"><div><h2>State transition log</h2><p>${obj.observations.length} observed change${obj.observations.length === 1 ? '' : 's'} recorded</p></div></div>
      <div class="timeline">${timeline}</div>
    </section>
    <section class="section">
      <div class="section-header"><div><h2>Proof of the change</h2><p>Starting proof is needed before the objective can pass. Add after-proof when you record a change.</p></div></div>
      <div class="evidence-grid">
        <div class="evidence-card ${obj.baseline.evidence?.sha256 ? '' : 'evidence-missing'}"><div><strong>Starting value · ${escapeHtml(obj.baseline.value)}${obj.unit ? ` ${escapeHtml(obj.unit)}` : ''}</strong><span>${escapeHtml(obj.baseline.evidence?.filename || 'Starting proof has not been added yet.')}</span></div>${obj.baseline.evidence?.sha256 ? '<span class="evidence-arrow">Proof saved</span>' : '<button class="quiet-button" id="addBaselineEvidenceBtn" type="button">Add starting proof</button>'}</div>
        <div class="evidence-card"><div><strong>Current value · ${escapeHtml(current)}${obj.unit ? ` ${escapeHtml(obj.unit)}` : ''}</strong><span>${escapeHtml(nextEvidence?.filename || 'Add proof after a real state change.')}</span></div><span class="evidence-arrow">${nextEvidence?.sha256 ? 'Proof saved' : 'Not recorded'}</span></div>
      </div>
    </section>`;
  document.querySelector('#recordTransitionBtn')?.addEventListener('click', () => openTransitionDialog(obj));
  document.querySelector('#addBaselineEvidenceBtn')?.addEventListener('click', openBaselineEvidenceDialog);
}

function generationLocked(obj) {
  const routes = obj.routes.filter((route) => route.generation === obj.generation);
  const top = routes.filter((route) => route.selected);
  return top.length === 2 && top.every((route) => route.status === 'executed_no_advance' || route.status === 'falsified');
}

function renderDiscover(obj) {
  const locked = generationLocked(obj);
  const currentRoutes = obj.routes.filter((route) => route.generation === obj.generation);
  const selectedCount = currentRoutes.filter((route) => route.selected).length;
  const readyToExecute = currentRoutes.length >= 5 && selectedCount === 2 && obj.searchStartedAfterDivergence === true;
  const routeCards = currentRoutes.map((route, index) => `<article class="route">
    <div class="route-head"><div><span class="route-number">GEN ${obj.generation} · ROUTE ${index + 1}</span><h3>${escapeHtml(route.domain)}</h3></div><span class="status ${route.status === 'executed_advanced' ? 'pass' : route.status === 'executed_no_advance' || route.status === 'falsified' ? 'blocked' : 'open'}">${escapeHtml(route.status.replace(/_/g, ' '))}</span></div>
    <dl><dt>Native solution</dt><dd>${escapeHtml(route.nativeSolution)}</dd><dt>Objective mapping</dt><dd>${escapeHtml(route.mapping)}</dd><dt>Attacks</dt><dd>${escapeHtml(route.attacks)}</dd><dt>Reachability variable</dt><dd>${escapeHtml(route.variable)}</dd><dt>Discriminator</dt><dd>${escapeHtml(route.discriminator)}</dd><dt>Rejects if</dt><dd>${escapeHtml(route.rejectsIf)}</dd><dt>Supports if</dt><dd>${escapeHtml(route.supportsIf)}</dd></dl>
    <div class="route-actions"><label class="check-label"><input type="checkbox" data-route-selected="${escapeHtml(route.id)}" ${route.selected ? 'checked' : ''} ${locked || route.status !== 'proposed' ? 'disabled' : ''}> Select as one of exactly two</label><select aria-label="Route result" data-route-status="${escapeHtml(route.id)}" ${!readyToExecute || !route.selected || route.status !== 'proposed' ? 'disabled' : ''}><option value="proposed">Not executed</option><option value="executed_advanced">Executed · target advanced</option><option value="executed_no_advance">Executed · no target advance</option><option value="falsified">Executed · falsified</option></select></div>
    ${route.evidence ? `<p class="form-note">Execution record: ${escapeHtml(route.evidence.note)} · <a href="${escapeHtml(safeUrl(route.evidence.url))}" target="_blank" rel="noopener">evidence link</a></p>` : ''}
  </article>`).join('');
  app.innerHTML = `
    <div class="page-heading"><div><h1>Discover</h1><p class="subhead">Keep the end state fixed; change representations and mechanisms until a route changes reachability.</p></div><div class="heading-actions"><span class="status ${locked ? 'blocked' : 'open'}">${locked ? 'GENERATION LOCKED · REASSESS BLOCKER' : `GENERATION ${obj.generation} · ${currentRoutes.length}/5 fields · ${selectedCount}/2 routes`}</span><button class="primary-button" id="addRouteBtn" ${locked || currentRoutes.length >= 5 ? 'disabled' : ''} type="button">Add route</button></div></div>
    <div class="objective-panel"><div><h2>${escapeHtml(obj.statement)}</h2><p class="section-copy">Current blocker: ${escapeHtml(obj.blocker)}</p></div><div class="rule-box"><strong>Runtime v4.2 gate</strong><p>Select exactly two materially different routes. If both execute without target advance, this generation expires. A new generation needs a blocker reassessment grounded in both results.</p></div></div>
    ${locked ? `<div class="generation-lock"><strong>Old route list is locked.</strong> Record the shared failure pattern and a revised blocker before opening a fresh generation.</div><div class="evidence-controls"><input id="reassessedBlocker" placeholder="Reassessed blocker based on both executed results"><input id="reassessmentEvidence" type="url" placeholder="HTTPS evidence link for the reassessment"><button class="primary-button" id="newGenerationBtn" type="button">Open fresh generation</button></div>` : ''}
    ${!locked ? `<label class="check-label"><input type="checkbox" id="divergenceOrderCheck" ${obj.searchStartedAfterDivergence ? 'checked' : ''} ${currentRoutes.length < 5 || selectedCount !== 2 ? 'disabled' : ''}> I registered five candidate fields and selected two distinct routes before starting solver/search work.</label>` : ''}
    ${!readyToExecute && !locked ? `<p class="form-note">Execution stays disabled until five candidate fields are documented, exactly two materially distinct routes are selected, and the order check is recorded.</p>` : ''}
    <div class="route-list">${routeCards || '<p class="section-copy">No routes recorded in this generation yet. A route must name a foreign mechanism, the assumption it attacks, and an executable discriminator.</p>'}</div>
    <section class="section"><div class="section-header"><div><h2>Next execution packet</h2><p>Copy the frozen objective and current state into the execution environment.</p></div><button class="quiet-button" id="copyPacketBtn" type="button">Copy packet</button></div><textarea class="packet" readonly>${escapeHtml(buildPacket(obj))}</textarea></section>`;
  document.querySelector('#addRouteBtn')?.addEventListener('click', () => routeDialog.showModal());
  document.querySelector('#divergenceOrderCheck')?.addEventListener('change', (event) => { obj.searchStartedAfterDivergence = event.currentTarget.checked; persist(); render(); });
  document.querySelectorAll('[data-route-selected]').forEach((checkbox) => checkbox.addEventListener('change', () => {
    const route = obj.routes.find((item) => item.id === checkbox.dataset.routeSelected);
    if (!route) return;
    const count = currentRoutes.filter((item) => item.selected).length;
    if (checkbox.checked && count >= 2) { checkbox.checked = false; return toast('Select exactly two routes per generation.'); }
    const other = currentRoutes.find((item) => item.selected && item.id !== route.id);
    if (checkbox.checked && other && (other.domain.trim().toLowerCase() === route.domain.trim().toLowerCase() || other.attacks.trim().toLowerCase() === route.attacks.trim().toLowerCase())) {
      checkbox.checked = false; return toast('The two selected routes must use different fields and attack different assumptions.');
    }
    route.selected = checkbox.checked;
    persist(); render();
  }));
  document.querySelectorAll('[data-route-status]').forEach((select) => select.addEventListener('change', () => {
    const route = obj.routes.find((item) => item.id === select.dataset.routeStatus);
    if (!route) return;
    if (!readyToExecute || !route.selected) return toast('Complete five fields and select exactly two routes before execution.');
    pendingRouteResult = { routeId: route.id, status: select.value };
    select.value = 'proposed';
    routeEvidenceDialog.showModal();
  }));
  document.querySelector('#newGenerationBtn')?.addEventListener('click', () => {
    const nextBlocker = document.querySelector('#reassessedBlocker').value.trim();
    const evidenceUrl = safeUrl(document.querySelector('#reassessmentEvidence').value.trim());
    if (!nextBlocker || !evidenceUrl) return toast('Add the evidence-based blocker reassessment and its HTTPS evidence link first.');
    const retiredGeneration = obj.generation;
    const retiredBlocker = obj.blocker;
    obj.generation += 1;
    obj.blocker = nextBlocker;
    obj.searchStartedAfterDivergence = false;
    obj.generationHistory.push({ generation: retiredGeneration, childGeneration: retiredGeneration + 1, retiredAt: new Date().toISOString(), blockerBefore: retiredBlocker, blockerAfter: nextBlocker, reassessmentEvidenceUrl: evidenceUrl, topRoutes: currentRoutes.filter((route) => route.selected).map((route) => route.id), routes: currentRoutes.map((route) => ({ id: route.id, selected: route.selected, domain: route.domain, attacks: route.attacks, status: route.status, evidence: route.evidence })) });
    persist(); render();
  });
  document.querySelector('#copyPacketBtn').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(buildPacket(obj)); toast('Execution packet copied.'); }
    catch { toast('Clipboard unavailable. Select and copy the packet text below.'); }
  });
}

function buildPacket(obj) {
  const current = lastOf(obj.observations)?.value ?? obj.baseline.value;
  const selected = obj.routes.filter((route) => route.generation === obj.generation && route.selected);
  return [
    'FROZEN OBJECTIVE', obj.statement,
    `Target: ${obj.target.operator} ${obj.target.value}${obj.unit ? ` ${obj.unit}` : ''}`,
    `Measured state: ${current}${obj.unit ? ` ${obj.unit}` : ''}`,
    `State changed from baseline: ${String(current).trim() !== String(obj.baseline.value).trim()}`,
    `Current blocker: ${obj.blocker}`,
    `Next transition: ${obj.nextAction}`,
    `Shadow runtime: v4.2 · divergence generation ${obj.generation}`,
    'Pass only after an actual external state change meets the frozen target and has before/after evidence. Tool runs, code, and claims alone are not passes.',
    'Keep the objective fixed. If blocked, identify the variable that changes reachability; generate materially different routes and execute a discriminator.',
    `Selected routes: ${selected.length === 2 ? selected.map((route) => `${route.domain}: ${route.discriminator}; rejects if ${route.rejectsIf}; supports if ${route.supportsIf}`).join(' | ') : 'none yet; complete route selection first.'}`,
    'Do not stop while an eligible executable next transition remains. Update the durable state after every executed result.',
  ].join('\n');
}

function renderVerify(obj) {
  app.innerHTML = `
    <div class="page-heading"><div><h1>Verify</h1><p class="subhead">Check a proposed response against the deterministic signature set and the objective-state gate.</p></div><span class="status ${outcome(obj).kind}">${escapeHtml(outcome(obj).label)}</span></div>
    <div class="verify-grid">
      <section class="verify-panel"><h2>Response scan</h2><p class="section-copy">Pattern matches are deterministic. A clean scan does not prove that the objective advanced.</p><textarea id="draftText" placeholder="Paste a proposed response to scan"></textarea><div class="evidence-controls"><label class="check-label"><input type="checkbox" id="timeToolFlag"> Time tool ran in this same response</label><label class="check-label"><input type="checkbox" id="managementFlag"> Management explicitly requested in this turn</label><button class="primary-button" id="scanBtn" type="button">Scan text</button></div><div id="scanResult" class="hit-list"></div></section>
      <section class="verify-panel"><h2>Objective gate</h2><p class="section-copy">A process event alone can’t produce PASS. The record must show an actual measured transition to the frozen target.</p><div class="rule-box"><strong>Current test</strong><p>Before: ${escapeHtml(obj.baseline.value)}${obj.unit ? ` ${escapeHtml(obj.unit)}` : ''}<br>After: ${escapeHtml(lastOf(obj.observations)?.value ?? obj.baseline.value)}${obj.unit ? ` ${escapeHtml(obj.unit)}` : ''}<br>Target: ${escapeHtml(targetText(obj))}</p></div><div class="rule-box"><strong>Evidence state</strong><p>Baseline artifact: ${obj.baseline.evidence?.sha256 ? 'SHA-256 present' : 'missing'}<br>After artifact: ${lastOf(obj.observations)?.evidence?.sha256 ? 'SHA-256 present' : 'missing'}<br>Source checked by user: ${lastOf(obj.observations)?.sourceConfirmed ? 'yes' : 'no'}</p></div><button class="quiet-button" id="exportBtn2" type="button">Export objective record</button></section>
    </div>
    <section class="verify-panel kernel-panel"><h2>Decision kernel · K-1 to K-5</h2><p class="section-copy">Compare at least two real options. Use TOOL, MEMORY, STATED, INFERENCE, or UNKNOWN for each evidence license. UNKNOWN has zero weight; totals must equal licensed evidence. Include continuation and delay. If asserting a boundary, name its blocker and evaluated routes. Mark conclusions for recomputation when their premises are superseded.</p><textarea id="decisionTrace" aria-label="Decision trace JSON" placeholder='{"decision":"...","options":[{"id":"...","incumbent":false,"evidence":[{"claim":"...","license":"STATED","weight":0,"premise":"..."}],"total_weight":0},{"id":"...","incumbent":true,"evidence":[],"total_weight":0}],"baseline_rows":["continuation","delay"],"boundary":null,"superseded_premises":[]}>${obj.decisionTrace ? escapeHtml(JSON.stringify(obj.decisionTrace, null, 2)) : ''}</textarea><div class="evidence-controls"><button class="primary-button" id="saveDecisionTrace" type="button">Validate and save trace</button><span class="form-note">A valid trace is required before PASS. The check validates structure; it cannot prove an evidence license is truthful.</span></div><div id="kernelResult" class="hit-list"></div></section>`;
  document.querySelector('#scanBtn').addEventListener('click', () => {
    const hits = scanText(document.querySelector('#draftText').value, { tool_time_called: document.querySelector('#timeToolFlag').checked, management_requested: document.querySelector('#managementFlag').checked });
    const target = document.querySelector('#scanResult');
    target.innerHTML = hits.length ? hits.map((hit) => `<div class="hit"><strong>${escapeHtml(hit.sig)} · ${escapeHtml(hit.name)}</strong>${escapeHtml(hit.match)}</div>`).join('') : '<div class="clean-message">No configured signature matched. This is not an objective PASS.</div>';
  });
  document.querySelector('#exportBtn2').addEventListener('click', exportState);
  document.querySelector('#saveDecisionTrace').addEventListener('click', () => {
    let trace;
    try { trace = JSON.parse(document.querySelector('#decisionTrace').value); }
    catch { return toast('Decision trace is not valid JSON.'); }
    const violations = checkDecisionTrace(trace);
    const result = document.querySelector('#kernelResult');
    if (violations.length) {
      result.innerHTML = violations.map((message) => `<div class="hit">${escapeHtml(message)}</div>`).join('');
      return;
    }
    obj.decisionTrace = trace;
    obj.decisionTraceRequired = true;
    persist(); render(); toast('K-1..K-5 trace passed and was saved.');
  });
}

async function loadSignatures() {
  try {
    const response = await fetch('./signatures.json', { cache: 'no-store' });
    if (response.ok) signatures = await response.json();
  } catch { signatures = []; }
}

function scanText(text, flags) {
  if (!text.trim()) return [];
  const hits = [];
  const exceptions = [/\[TOOL\]/i, /\[MEMORY\]/i, /\[STATED\]/i, /\[INFERENCE\]/i, /\[SAMPLE:/i, /tool call(?:ed|s)? (?:above|in this message|already made)/i, /if\s+\w+.*(?:occurs|happens|fires|triggers)/i, /["“].*["”]/];
  text.split(/\r?\n/).forEach((line, index) => {
    if (exceptions.some((pattern) => pattern.test(line))) return;
    for (const signature of signatures) {
      if (signature.suppressor_flag && flags[signature.suppressor_flag]) continue;
      for (const source of signature.patterns || []) {
        try {
          const match = new RegExp(source, 'i').exec(line);
          if (match) hits.push({ sig: signature.sig_id, name: signature.name, match: match[0], line: index + 1 });
        } catch (error) { console.warn('Invalid signature pattern', error); }
      }
    }
  });
  // SIG-7 is structural, so it is deliberately evaluated across paragraphs.
  const paragraphs = text.split(/\n\s*\n/).filter((part) => part.trim());
  const opener = /\b(?:Yes|Fair|That'?s (?:right|fair|true)|You'?re right|Agreed|Correct)\b[,.]?/i;
  const contrast = /\b(?:but|however|though)\b/i;
  const concrete = /\d|`[^`]+`|\bSIG-\d|\bfilter\.py\b|\bexit code\b|\bcase \d+\b|\bthat message\b|\bwhat I (?:said|wrote)\b|\babove\b/i;
  const abstract = /\bboundary\b|\bnuance\b|\bframework\b|\bstructurally\b|\bphilosophically\b|\bin general\b|\bautomatically\b|\bunfalsifiable\b|\bby default\b/i;
  paragraphs.forEach((paragraph, index) => {
    const lead = opener.exec(paragraph);
    if (!lead || lead.index > 5) return;
    const window = `${paragraph.slice(lead.index + lead[0].length)} ${paragraphs[index + 1] || ''}`;
    const split = contrast.exec(window);
    if (split && abstract.test(window.slice(split.index + split[0].length)) && !concrete.test(window.slice(split.index + split[0].length))) {
      hits.push({ sig: 'SIG-7', name: 'concede_retreat', match: paragraph.slice(0, 120), line: text.slice(0, text.indexOf(paragraph)).split('\n').length });
    }
  });
  return hits;
}

function openObjectiveDialog() {
  document.querySelector('#objectiveForm').reset();
  document.querySelector('#objectiveDialogTitle').textContent = 'Set an objective';
  objectiveDialog.showModal();
}

function openBaselineEvidenceDialog() {
  document.querySelector('#baselineEvidenceForm').reset();
  document.querySelector('#baselineEvidenceDialog').showModal();
}

function openTransitionDialog(obj) {
  const current = lastOf(obj.observations)?.value ?? obj.baseline.value;
  document.querySelector('#transitionForm').reset();
  document.querySelector('#transitionBefore').textContent = `Current measured state: ${current}${obj.unit ? ` ${obj.unit}` : ''}. Record a new observed value and evidence.`;
  transitionDialog.showModal();
}

async function fileEvidence(file) {
  if (!file) return null;
  const bytes = await file.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  const hash = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  return { filename: file.name, mimeType: file.type || 'application/octet-stream', size: file.size, sha256: hash };
}

function id() { return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`; }

document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', () => { activeView = button.dataset.view; render(); }));
document.querySelector('#importBtn').addEventListener('click', () => document.querySelector('#importFile').click());
document.querySelector('#importFile').addEventListener('change', importState);
document.querySelector('#exportBtn').addEventListener('click', exportState);
document.querySelector('#cancelObjective').addEventListener('click', () => objectiveDialog.close());
document.querySelector('#cancelBaselineEvidence').addEventListener('click', () => baselineEvidenceDialog.close());
document.querySelector('#cancelBaselineEvidence2').addEventListener('click', () => baselineEvidenceDialog.close());
document.querySelector('#cancelTransition').addEventListener('click', () => transitionDialog.close());
document.querySelector('#cancelRoute').addEventListener('click', () => routeDialog.close());
document.querySelector('#cancelRouteEvidence').addEventListener('click', () => { pendingRouteResult = null; routeEvidenceDialog.close(); });

document.querySelector('#objectiveForm').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const baseline = String(form.get('baseline')).trim();
  const target = String(form.get('target')).trim();
  const old = activeObjective();
  if (old) old.archivedAt = new Date().toISOString();
  const obj = {
    id: id(), revision: old ? old.revision + 1 : 1, createdAt: new Date().toISOString(),
    statement: String(form.get('statement')).trim(), unit: String(form.get('unit') || '').trim(),
    target: { operator: String(form.get('operator') || 'eq'), value: target },
    blocker: 'Not identified yet. Discover what is preventing the target.',
    nextAction: 'Identify the current blocker and choose the next executable step.',
    baseline: { value: baseline, sourceConfirmed: false, evidence: null },
    observations: [], generation: 1, routes: [], generationHistory: [], decisionTraceRequired: true, decisionTrace: null,
  };
  state.objectives.push(obj);
  state.activeId = obj.id;
  persist(); objectiveDialog.close(); activeView = 'objective'; render(); toast('Objective saved. Add starting proof from the Objective screen.');
});

document.querySelector('#baselineEvidenceForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const obj = activeObjective();
  if (!obj) return;
  const form = new FormData(event.currentTarget);
  const url = safeUrl(form.get('baselineEvidence'));
  if (!url) return toast('Use an HTTPS link for the starting-state source.');
  const evidence = await fileEvidence(form.get('baselineEvidenceFile'));
  if (!evidence || !form.get('baselineSourceConfirmed')) return toast('Attach proof and confirm it shows the recorded starting value.');
  obj.baseline.evidence = { ...evidence, url };
  obj.baseline.sourceConfirmed = true;
  persist(); baselineEvidenceDialog.close(); render(); toast('Starting proof saved.');
});

document.querySelector('#transitionForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const obj = activeObjective();
  if (!obj) return;
  const form = new FormData(event.currentTarget);
  const current = lastOf(obj.observations)?.value ?? obj.baseline.value;
  const after = String(form.get('after')).trim();
  if (after === String(current).trim()) return toast('No state change: the measured value is unchanged.');
  const url = safeUrl(form.get('evidenceUrl'));
  if (!url) return toast('Use an HTTPS link for the after-state evidence.');
  const evidence = await fileEvidence(form.get('evidenceFile'));
  obj.observations.push({ id: id(), at: new Date().toISOString(), before: current, value: after, sourceConfirmed: Boolean(form.get('sourceConfirmed')), evidence: { ...evidence, url, note: String(form.get('evidenceNote')).trim() } });
  persist(); transitionDialog.close(); render(); toast('Observed state change saved.');
});

document.querySelector('#routeForm').addEventListener('submit', (event) => {
  event.preventDefault();
  const obj = activeObjective();
  if (!obj) return;
  if (generationLocked(obj)) return toast('Reassess the blocker and open a new generation first.');
  const routes = obj.routes.filter((route) => route.generation === obj.generation);
  if (routes.length >= 5) return toast('This generation already has five candidate routes.');
  const form = new FormData(event.currentTarget);
  obj.routes.push({ id: id(), generation: obj.generation, domain: String(form.get('domain')).trim(), nativeSolution: String(form.get('nativeSolution')).trim(), mapping: String(form.get('mapping')).trim(), attacks: String(form.get('attacks')).trim(), variable: String(form.get('variable')).trim(), discriminator: String(form.get('discriminator')).trim(), rejectsIf: String(form.get('rejectsIf')).trim(), supportsIf: String(form.get('supportsIf')).trim(), status: 'proposed', selected: false });
  persist(); routeDialog.close(); render(); toast('Candidate route saved.');
});

document.querySelector('#routeEvidenceForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!pendingRouteResult) return routeEvidenceDialog.close();
  const obj = activeObjective();
  const route = obj?.routes.find((item) => item.id === pendingRouteResult.routeId);
  const form = new FormData(event.currentTarget);
  const url = safeUrl(form.get('url'));
  const note = String(form.get('note')).trim();
  const artifact = await fileEvidence(form.get('file'));
  if (!route || !url || !note || !artifact || !form.get('sourceConfirmed')) return toast('Route result needs an HTTPS link, artifact, observation, and source attestation.');
  route.evidence = { ...artifact, url, note, sourceConfirmed: true };
  route.status = pendingRouteResult.status;
  route.executedAt = new Date().toISOString();
  route.targetAdvanced = route.status === 'executed_advanced';
  pendingRouteResult = null;
  persist(); event.currentTarget.reset(); routeEvidenceDialog.close(); render(); toast('Route execution evidence saved.');
});

function exportState() {
  const obj = activeObjective();
  const latest = lastOf(obj?.observations) || null;
  const current = latest?.value ?? obj?.baseline.value ?? null;
  const selected = obj?.routes.filter((route) => route.generation === obj.generation && route.selected) || [];
  const gateRecord = {
    schema_version: 1,
    status: obj && outcome(obj).pass ? 'PASS' : 'OPEN',
    finalizing: false,
    requires_decision_trace: Boolean(obj?.decisionTraceRequired),
    ...(obj?.decisionTrace ? { decision_trace: obj.decisionTrace } : {}),
    requires_divergence_protocol: Boolean(obj && !outcome(obj).pass && obj.routes.some((route) => route.generation === obj.generation)),
    generation_history: obj?.generationHistory || [],
    objective: obj ? {
      id: obj.id, statement: obj.statement, baseline_value: obj.baseline.value, current_value: current,
      target: { operator: obj.target.operator, value: obj.target.value },
      next_action: { executable: true, action: obj.nextAction },
      completion_claimed: Boolean(obj.completionClaimed),
      evidence_before: { kind: 'external_artifact', uri: obj.baseline.evidence.url, sha256: obj.baseline.evidence.sha256, source_checked: Boolean(obj.baseline.sourceConfirmed) },
      ...(latest ? { evidence_after: { kind: 'external_artifact', uri: latest.evidence.url, sha256: latest.evidence.sha256, source_checked: Boolean(latest.sourceConfirmed) } } : {}),
    } : {},
    ...(obj && obj.routes.some((route) => route.generation === obj.generation) ? { divergence_protocol: {
      generation: obj.generation,
      fields: obj.routes.filter((route) => route.generation === obj.generation).map((route) => ({
        id: route.id, field: route.domain, unrelated_to_native_domain: Boolean(route.domain), native_solution: route.nativeSolution,
        mapping_to_objective_state: route.mapping, attacks_assumption: route.attacks, reachability_variable: route.variable,
        discriminator: { execution_plan: route.discriminator, rejects_route_if: route.rejectsIf, supports_route_if: route.supportsIf },
      })),
      top_routes: selected.map((route) => route.id), inherited_assumptions: [], eliminations: [],
      solver_or_search_started_after_divergence: Boolean(obj.searchStartedAfterDivergence),
      post_two_route_transition: {
        executed_results: selected.filter((route) => route.status !== 'proposed').map((route) => ({
          route_id: route.id, executed: true,
          outcome: route.status === 'executed_no_advance' ? 'no_target_advance' : route.status === 'falsified' ? 'falsified' : 'target_advanced',
          failure_signature: route.status === 'executed_advanced' ? null : route.attacks,
          evidence: route.evidence,
        })),
      ...(lastOf(obj.generationHistory)?.generation === obj.generation ? { blocker_reassessment: { performed: true, evidence: lastOf(obj.generationHistory).reassessmentEvidenceUrl }, next_action: { type: 'child_divergence' } } : {}),
      },
    } } : {}),
    browser_state: state,
  };
  const blob = new Blob([JSON.stringify(gateRecord, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = `outcome-gate-${new Date().toISOString().slice(0, 10)}.json`; link.click();
  URL.revokeObjectURL(url);
  toast('State snapshot downloaded.');
}

async function importState(event) {
  const file = event.currentTarget.files?.[0];
  if (!file) return;
  try {
    const parsed = JSON.parse(await file.text());
    const imported = parsed.browser_state || parsed;
    if (imported.schemaVersion !== 1 || !Array.isArray(imported.objectives)) throw new Error('Unsupported state file.');
    state.schemaVersion = 1; state.runtime = { name: 'shadow', version: '4.2' };
    state.objectives = imported.objectives; state.activeId = imported.activeId || lastOf(imported.objectives)?.id || null;
    persist(); activeView = 'objective'; render(); toast('State snapshot imported.');
  } catch (error) { toast(`Import failed: ${error.message}`); }
  event.currentTarget.value = '';
}

function toast(message) {
  const old = document.querySelector('.toast'); old?.remove();
  const node = document.createElement('div'); node.className = 'toast'; node.textContent = message;
  document.body.append(node); setTimeout(() => node.remove(), 3000);
}

loadSignatures().then(render);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('./service-worker.js').catch((error) => console.warn('Offline shell unavailable', error));
