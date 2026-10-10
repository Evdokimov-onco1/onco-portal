'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const stamp = () => 'date';
const state = {
  completionLoadId: undefined,
  user: { id: 'student-a', role: 'student' },
  module: { id: 'M01', materials: { version: 'mv1' }, opened: {} },
  panel: 'progress',
  pending: {},
  edits: {},
  dirty: new Set(),
  teacherTab: 'answers',
};
const sandbox = { state, esc, stamp, api: async () => ({}), action: async (_, fn) => fn(), notify: () => {}, student: () => {}, teacher: () => {}, safeLeave: () => true, module: { exports: {} } };
vm.createContext(sandbox);
const src = fs.readFileSync(path.join(__dirname, 'web', 'completion.js'), 'utf8');
vm.runInContext(src + '\nmodule.exports={checkPanel,completionStatusLabel,shouldApplyCompletionResponse,shouldApplyTeacherCompletion,shouldApplyTeacherApp,invalidateCompletionLoads,nextCompletionLoadId};', sandbox);
const { checkPanel, completionStatusLabel, shouldApplyCompletionResponse, shouldApplyTeacherCompletion, shouldApplyTeacherApp, invalidateCompletionLoads, nextCompletionLoadId } = sandbox.module.exports;

assert.strictEqual(checkPanel.lecture, 'materials');
assert.strictEqual(checkPanel.tumor_board, 'practice');
assert.strictEqual(completionStatusLabel.completed, 'Модуль подтверждён');

const teacherId = nextCompletionLoadId();
assert.strictEqual(teacherId, 1);
assert.strictEqual(Number.isFinite(state.completionLoadId), true);
state.user = { id: 'teacher', role: 'teacher' };
state.teacherTab = 'completion';
assert.strictEqual(shouldApplyTeacherCompletion(teacherId, 'teacher'), true);
state.teacherTab = 'answers';
assert.strictEqual(shouldApplyTeacherCompletion(teacherId, 'teacher'), false);

state.user = { id: 'student-a', role: 'student' };
state.panel = 'progress';
const loadId = nextCompletionLoadId();
state.completionLoadId = loadId;
assert.strictEqual(shouldApplyCompletionResponse(loadId, 'student-a', 'M01'), true);
state.panel = 'materials';
assert.strictEqual(shouldApplyCompletionResponse(loadId, 'student-a', 'M01'), false);
state.panel = 'progress';
state.module.id = 'M02';
assert.strictEqual(shouldApplyCompletionResponse(loadId, 'student-a', 'M01'), false);

delete state.completionLoadId;
invalidateCompletionLoads();
assert.strictEqual(state.completionLoadId, 1);
assert.strictEqual(shouldApplyCompletionResponse(loadId, 'student-a', 'M02'), false);

console.log('pilot/test_completion_ui.js: ok');
