'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const state = { edits: {}, user: { id: 'teacher', role: 'teacher' }, teacherTab: 'completion', completionLoadId: 1 };
const sandbox = {
  state,
  esc,
  stamp: () => '',
  api: async () => ({}),
  action: async (_, fn) => fn(),
  notify: () => {},
  student: () => {},
  teacher: () => {},
  safeLeave: () => true,
  teacherCompletionView: () => {},
  document: { querySelector: () => null },
  module: { exports: {} },
};
vm.createContext(sandbox);
const src = fs.readFileSync(path.join(__dirname, 'web', 'completion.js'), 'utf8');
vm.runInContext(src + '\nmodule.exports={lectureCoverageStatusLabel,lectureCoverageFilterModules,lectureCoverageListMarkup,lectureCoverageOverviewMarkup,lectureCoverageLiveCountText,refreshLectureCoverageResults,wireLectureCoverageOverview,focusCompletionLectureBindingSection};', sandbox);
const {
  lectureCoverageStatusLabel,
  lectureCoverageFilterModules,
  lectureCoverageListMarkup,
  lectureCoverageOverviewMarkup,
  lectureCoverageLiveCountText,
  refreshLectureCoverageResults,
  wireLectureCoverageOverview,
  focusCompletionLectureBindingSection,
} = sandbox.module.exports;

const rows = [
  { module: 'M01', title: 'Alpha', year: '1', status: 'bound', candidate_count: 1 },
  { module: 'M02', title: 'Beta <unsafe>', year: '2', status: 'missing', candidate_count: 0 },
  { module: 'M03', title: 'Gamma', year: '1', status: 'candidates', candidate_count: 2 },
];
const overview = { modules: rows, summary: { total: 3, bound: 1, candidates: 1, missing: 1 } };

assert.strictEqual(lectureCoverageFilterModules(rows, 'all', '').length, 3);
assert.strictEqual(lectureCoverageFilterModules(rows, 'bound', '').length, 1);
assert.strictEqual(lectureCoverageFilterModules(rows, 'missing', 'beta')[0].module, 'M02');
assert.strictEqual(lectureCoverageFilterModules(rows, 'all', 'm03')[0].module, 'M03');

const list = lectureCoverageListMarkup(rows.filter(r => r.module === 'M02'));
assert.ok(list.includes('&lt;unsafe&gt;'));
assert.ok(!list.includes('<unsafe>'));

const errHtml = lectureCoverageOverviewMarkup(null, 'Network fail', 'all', '');
assert.ok(errHtml.includes('Network fail'));
assert.ok(errHtml.includes('lectureCoverageRetry'));

const overviewHtml = lectureCoverageOverviewMarkup(overview, null, 'all', '');
assert.ok(overviewHtml.includes('lectureCoverageResultsRegion'));
assert.ok(overviewHtml.includes('aria-live="polite"'));
assert.strictEqual(lectureCoverageStatusLabel.bound, 'Привязана');
assert.strictEqual(lectureCoverageLiveCountText(rows, 2), 'Показано модулей: 2 из 3.');

const doc = { activeElement: null };
function makeEl(tag, props = {}) {
  const el = {
    tagName: tag.toUpperCase(),
    id: props.id || '',
    className: props.className || '',
    classList: { contains: c => (props.className || '').split(/\s+/).includes(c) },
    value: props.value ?? '',
    textContent: props.textContent ?? '',
    dataset: props.dataset || {},
    children: [],
    parentNode: null,
    listeners: {},
    _inner: '',
    appendChild(c) { c.parentNode = this; this.children.push(c); return c; },
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    dispatchInput() { for (const fn of this.listeners.input || []) fn({ target: this }); },
    dispatchChange() { for (const fn of this.listeners.change || []) fn({ target: this }); },
    focus() { doc.activeElement = this; },
    contains(node) {
      if (node === this) return true;
      return this.children.some(c => c.contains?.(node));
    },
    closest(sel) {
      let n = this;
      while (n) {
        if (sel === '.completion-lecture-overview' && n.className?.includes('completion-lecture-overview')) return n;
        if (sel === '.lecture-coverage-open' && n.className?.includes('lecture-coverage-open')) return n;
        n = n.parentNode;
      }
      return null;
    },
    get innerHTML() { return this._inner; },
    set innerHTML(html) { this._inner = html; },
  };
  Object.defineProperty(el, 'outerHTML', { get() { return `<${tag}>`; } });
  return el;
}

function query(root, sel) {
  if (sel.startsWith('#') && root.id === sel.slice(1)) return root;
  if (sel === '.completion-lecture-overview' && root.className?.includes('completion-lecture-overview')) return root;
  for (const c of root.children) {
    const hit = query(c, sel);
    if (hit) return hit;
  }
  return null;
}

function queryAll(root, sel) {
  const out = [];
  if (sel === '.lecture-coverage-open' && root.className?.includes('lecture-coverage-open')) out.push(root);
  for (const c of root.children) out.push(...queryAll(c, sel));
  return out;
}

function wireNode(el) {
  el.querySelector = s => query(el, s);
  el.querySelectorAll = s => queryAll(el, s);
  el.children.forEach(wireNode);
  return el;
}

const block = wireNode(makeEl('section', { className: 'paper completion-lecture-overview' }));
const statusEl = wireNode(makeEl('select', { id: 'lectureCoverageStatus', value: 'all' }));
const searchEl = wireNode(makeEl('input', { id: 'lectureCoverageSearch', value: '' }));
const liveEl = wireNode(makeEl('p', { id: 'lectureCoverageLive' }));
const resultsEl = wireNode(makeEl('div', { id: 'lectureCoverageResults' }));
[statusEl, searchEl, liveEl, resultsEl].forEach(n => block.appendChild(n));
const pane = wireNode(makeEl('div', { id: 'teacher-completion-pane' }));
pane.appendChild(block);
pane.closest = sel => (sel === '#teacher-completion-pane' ? pane : null);

refreshLectureCoverageResults(block, overview, 'all', '');
wireLectureCoverageOverview(pane, overview, 1, 'teacher');
const searchRef = pane.querySelector('#lectureCoverageSearch');
searchRef.focus();
for (const ch of 'm0') {
  searchRef.value += ch;
  searchRef.dispatchInput();
}
searchRef.value += '3';
searchRef.dispatchInput();
assert.strictEqual(pane.querySelector('#lectureCoverageSearch'), searchRef);
assert.strictEqual(doc.activeElement, searchRef);
assert.ok(resultsEl.innerHTML.includes('M03'));
assert.ok(!resultsEl.innerHTML.includes('M01'));
assert.strictEqual(liveEl.textContent, 'Показано модулей: 1 из 3.');
statusEl.value = 'candidates';
statusEl.dispatchChange();
assert.ok(resultsEl.innerHTML.includes('M03'));
assert.strictEqual(liveEl.textContent, 'Показано модулей: 1 из 3.');

const binding = wireNode(makeEl('h2', { id: 'completionLectureBinding' }));
binding.scrollIntoView = () => { binding.scrolled = true; };
sandbox.document.querySelector = sel => (sel === '#completionLectureBinding' ? binding : null);
focusCompletionLectureBindingSection(1, 'teacher', true);
assert.strictEqual(state.focusCompletionLectureBinding, undefined);
assert.strictEqual(binding.scrolled, true);
assert.strictEqual(doc.activeElement, binding);

console.log('pilot/test_lecture_coverage_ui.js: ok');

const bindingError = vm.runInContext("lectureBindingStatusMarkup(null,'Network unavailable','')", sandbox);
assert.ok(bindingError.includes('lectureBindingRetry'));
assert.ok(!bindingError.includes('Привязки нет'));
assert.ok(!bindingError.includes('Нет допустимых'));
const malicious = lectureCoverageListMarkup([{module:'M99',title:'Safe',status:'missing',year:1,candidate_count:'<img onerror=bad>'}]);
assert.ok(!malicious.includes('<img'));
assert.ok(malicious.includes('&lt;img'));
