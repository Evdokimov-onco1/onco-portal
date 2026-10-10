'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, 'web', 'practice.js'), 'utf8');
const state = {
  practiceLoadId: 0,
  user: { id: 'student-a' },
  module: { id: 'M01' },
  dirty: new Set(['act1']),
  edits: { act1: 'local draft' },
  practice: { module: 'M01', drafts: { act1: 'server draft' } },
};
const sandbox = { state, module: { exports: {} } };
vm.createContext(sandbox);
vm.runInContext(src + '\nmodule.exports={pLastEv,pStatusText,shouldApplyPracticeResponse,mergePracticeServerData,invalidatePracticeLoads};', sandbox);
const { pLastEv, pStatusText, shouldApplyPracticeResponse, mergePracticeServerData, invalidatePracticeLoads } = sandbox.module.exports;

const activity = {
  attempts: [
    { id: 2, logbook: [] },
    { id: 1, logbook: [{ decision: 'accepted' }] },
  ],
};
assert.strictEqual(pLastEv(activity), null);
assert.strictEqual(pStatusText(activity), 'Отправлено · ждёт отметки');

const loadId = 3;
state.practiceLoadId = 3;
assert.strictEqual(shouldApplyPracticeResponse(loadId, 'student-a', 'M01'), true);
state.user.id = 'student-b';
assert.strictEqual(shouldApplyPracticeResponse(loadId, 'student-a', 'M01'), false);
state.user.id = 'student-a';
invalidatePracticeLoads();
assert.strictEqual(shouldApplyPracticeResponse(loadId, 'student-a', 'M01'), false);

state.practiceLoadId = 5;
state.user = { id: 'student-a' };
state.module = { id: 'M01' };
mergePracticeServerData({ module: 'M01', version: 'v1', activities: [], drafts: { act1: 'fresh server' } });
assert.strictEqual(state.practice.drafts.act1, 'local draft');

console.log('pilot/test_practice_ui.js: ok');
