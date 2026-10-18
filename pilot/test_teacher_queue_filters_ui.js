'use strict';
// Unit checks for the teacher review-queue filters in web/app.js.
const assert = require('node:assert/strict');
// vm arrays/objects have another realm's prototypes; compare their JSON values.
const same = (actual, expected, message) => assert.deepStrictEqual(
  JSON.parse(JSON.stringify(actual)), JSON.parse(JSON.stringify(expected)), message);
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const appEl = { innerHTML: '', textContent: '', hidden: false };
const regionEl = { innerHTML: '', querySelectorAll: () => [] };
const countEl = { textContent: '' };
const sandbox = {
  document: {
    querySelector: s => ({ '#app': appEl, '#identity': {}, '#notice': {}, '#queueResults': regionEl, '#queueCount': countEl })[s] || null,
    querySelectorAll: () => [],
  },
  window: { addEventListener: () => {}, history: { replaceState: () => {} } },
  location: { search: '', hash: '', pathname: '/' },
  history: { replaceState: () => {} },
  URLSearchParams,
  console,
  module: { exports: {} },
};
vm.createContext(sandbox);
const src = fs.readFileSync(path.join(__dirname, 'web', 'app.js'), 'utf8');
vm.runInContext(src + '\nmodule.exports={state,queueFilters,resetQueueFilters,queueNorm,moduleTitle,queueLatestRows,queueFilterRows,queueCountText,queueItemMarkup,queueResultsMarkup,refreshQueueResults,QUEUE_FILTER_DEFAULTS};', sandbox);
const {
  state, queueFilters, resetQueueFilters, queueNorm, moduleTitle,
  queueLatestRows, queueFilterRows, queueCountText, queueItemMarkup,
  queueResultsMarkup, refreshQueueResults, QUEUE_FILTER_DEFAULTS,
} = sandbox.module.exports;

state.user = { id: 'teacher', role: 'teacher' };
state.modules = [{ id: 'M01', title: 'Опухоли <test>' }, { id: 'M02', title: 'Лучевая терапия' }];

const rev = d => ({ decision: d, comment: 'c', created_at: '2026-10-10T10:00:00Z' });
// Server returns newest submissions first (id DESC); dedup must keep the first row per key.
const queue = [
  { id: 9, student: 's1', student_name: 'Ординатор А', module: 'M01', case: 'C1', version: 'v1', answer: 'newest', created_at: '2026-10-15T09:00:00Z', reviews: [] },
  { id: 5, student: 's1', student_name: 'Ординатор А', module: 'M01', case: 'C1', version: 'v1', answer: 'older', created_at: '2026-10-10T09:00:00Z', reviews: [rev('returned')] },
  { id: 7, student: 's2', student_name: 'Ординатор Б', module: 'M02', case: 'C2', version: 'v1', answer: 'waiting long', created_at: '2026-09-20T09:00:00Z', reviews: [] },
  { id: 6, student: 's2', student_name: 'Ординатор Б', module: 'M02', case: 'C3', version: 'v1', answer: 'broken date', created_at: 'не-дата', reviews: [] },
  { id: 8, student: 's3', student_name: 'Ординатор <img onerror=bad>', module: 'M02', case: 'C1', version: 'v1', answer: 'done', created_at: '2026-10-14T09:00:00Z', reviews: [rev('accepted')] },
];

// --- dedup: latest row per student/module/case/version ---
const latestRows = queueLatestRows(queue);
same(latestRows.map(a => a.id), [9, 7, 6, 8]);
assert.strictEqual(latestRows.length, 4);

// --- status filtering ---
same(queueFilterRows(latestRows, { status: 'pending' }).map(a => a.id), [7, 9, 6]);
same(queueFilterRows(latestRows, { status: 'accepted' }).map(a => a.id), [8]);
same(queueFilterRows(latestRows, { status: 'returned' }).map(a => a.id), []);
assert.strictEqual(queueFilterRows(latestRows, { status: 'all' }).length, 4);

// --- sort: oldest waiting first, does not mutate input, bad dates last ---
const all = queueFilterRows(latestRows, { status: 'all' });
same(all.map(a => a.id), [7, 8, 9, 6]);
same(latestRows.map(a => a.id), [9, 7, 6, 8], 'sorting must not mutate the source array');
const newest = queueFilterRows(latestRows, { status: 'all', sort: 'newest' });
same(newest.map(a => a.id), [9, 8, 7, 6]);

// --- search: case- and space-insensitive, student name + module id/title ---
same(queueFilterRows(latestRows, { status: 'all', query: ' ОРДИНАТОР   А ' }).map(a => a.id), [9]);
same(queueFilterRows(latestRows, { status: 'all', query: 'm02' }).map(a => a.id), [7, 8, 6]);
same(queueFilterRows(latestRows, { status: 'all', query: 'лучевая' }).map(a => a.id), [7, 8, 6]);
same(queueFilterRows(latestRows, { status: 'all', query: 'опухоли' }).map(a => a.id), [9]);
assert.strictEqual(queueNorm(' А  Б '), 'аб');

// --- search combines with status and module filters ---
same(queueFilterRows(latestRows, { status: 'pending', module: 'M02', query: 'ординатор б' }).map(a => a.id), [7, 6]);
same(queueFilterRows(latestRows, { status: 'accepted', query: 'ординатор б' }).map(a => a.id), []);

// --- unsafe text is escaped in row markup ---
const item = queueItemMarkup(queue[4]);
assert.ok(!item.includes('<img'));
assert.ok(item.includes('&lt;img'));
const itemM01 = queueItemMarkup(queue[0]);
assert.ok(!itemM01.includes('Опухоли <test>'), 'module title must be escaped');
assert.ok(itemM01.includes('Опухоли &lt;test&gt;'));

// --- empty states differ: nothing submitted vs. nothing matched ---
assert.ok(queueResultsMarkup([], false).includes('Отправленных работ пока нет'));
const noMatch = queueResultsMarkup([], true);
assert.ok(noMatch.includes('ничего не найдено'));
assert.ok(noMatch.includes('Сбросить фильтры'));
assert.strictEqual(queueCountText(2, 5), 'Показано работ: 2 из 5');

// --- filters: defaults, persistence on same user, reset and user change ---
let f = queueFilters();
same({ status: f.status, query: f.query, module: f.module, sort: f.sort }, QUEUE_FILTER_DEFAULTS);
f.query = 'x'; f.module = 'M01'; f.status = 'all'; f.sort = 'newest';
assert.strictEqual(queueFilters(), f, 'filters persist while the same user keeps working');
resetQueueFilters();
f = queueFilters();
same({ status: f.status, query: f.query, module: f.module, sort: f.sort }, QUEUE_FILTER_DEFAULTS);
f.query = 'x';
state.user = { id: 'other-teacher', role: 'teacher' };
assert.strictEqual(queueFilters().query, '', 'a different signed-in user must not inherit filters');
state.user = { id: 'teacher', role: 'teacher' };

// --- live refresh touches only the queue subregion, not the whole page ---
state.queueFilters = null;
const ff = queueFilters();
ff.query = 'ординатор б';
ff.status = 'pending';
const before = appEl.innerHTML;
refreshQueueResults(queueLatestRows(queue));
assert.strictEqual(appEl.innerHTML, before, 'refreshQueueResults must not rewrite #app');
assert.strictEqual(countEl.textContent, 'Показано работ: 2 из 4');
assert.ok(regionEl.innerHTML.includes('data-review="7"'));
assert.ok(!regionEl.innerHTML.includes('data-review="9"'));
ff.query = 'zzz';
refreshQueueResults(queueLatestRows(queue));
assert.ok(regionEl.innerHTML.includes('ничего не найдено'));
assert.strictEqual(countEl.textContent, 'Показано работ: 0 из 4');

console.log('pilot/test_teacher_queue_filters_ui.js: ok');
