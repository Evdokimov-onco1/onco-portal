'use strict';
// Node DOM/media-stub check: real handlers of wireSuggestedPlayer and
// wireVideoFeedback — metadata seek, stale callback, explicit play with
// deferred rejection after switching, open-recording via /api/resources/open,
// ready-gated capture, media error fallback, Blob contents/click.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function makeEl(tag, props = {}) {
  const el = {
    tagName: tag.toUpperCase(),
    className: props.className || '',
    dataset: props.dataset || {},
    hidden: props.hidden ?? false,
    value: props.value ?? '',
    textContent: '',
    children: [],
    listeners: {},
    _q: props.q || {},
    addEventListener(t, f) { (el.listeners[t] ||= []).push(f); },
    removeEventListener(t, f) { el.listeners[t] = (el.listeners[t] || []).filter(x => x !== f); },
    dispatch(t) { for (const f of (el.listeners[t] || []).slice()) f({ target: el }); },
    querySelector(s) { return el._q[s] || null; },
    closest(s) { let n = el; while (n) { if (s.startsWith('.') && n.className.split(/\s+/).includes(s.slice(1))) return n; n = n.parent; } return null; },
    appendChild(c) { c.parent = el; el.children.push(c); return c; },
    remove() { el.removed = true; },
    click() { el.clicked = (el.clicked || 0) + 1; },
  };
  return el;
}

const ITEMS = [
  { id: 'suggested-L1', lecture_id: 'L1', video_id: 'V1', kind: 'suggested_video', title: 'Лекция один', speaker: 'Спикер 1', url: 'https://youtube.test/v1?t=10s', mp4_url: 'https://video.test/v1.mp4', launch_offset_seconds: 10, boundary_status: 'provisional', truncation_risk: false },
  { id: 'suggested-L2', lecture_id: 'L2', video_id: 'V1', kind: 'suggested_video', title: 'Лекция два', speaker: 'Спикер 2', url: 'https://youtube.test/v1?t=30s', mp4_url: 'https://video.test/v1.mp4', launch_offset_seconds: 30, boundary_status: 'provisional', truncation_risk: true, truncation_warning: 'Possible cut' },
];

const video = makeEl('video');
video.isConnected = true;
video.currentTime = 0;
video.pause = () => { video.paused = true; };
video.load = () => { video.loadCalls = (video.loadCalls || 0) + 1; };
video.fireMeta = () => { for (const f of (video.listeners['loadedmetadata'] || []).slice()) f(); };
video.fireError = () => { for (const f of (video.listeners['error'] || []).slice()) f(); };

const status = makeEl('p');
const warn = makeEl('p', { hidden: true });
const go = makeEl('button', { hidden: true });
const section = makeEl('div', { className: 'suggested-player', q: { 'video': video, '[data-vplayer-status]': status, '[data-vplayer-go]': go, '[data-vplayer-warn]': warn } });

const timeInput = makeEl('input');
const commentInput = makeEl('textarea');
const box = makeEl('details', { className: 'video-feedback', q: { '.vfb-time': timeInput, '.vfb-comment': commentInput } });
const playB1 = makeEl('button', { dataset: { vplay: 'suggested-L1' } });
const playB2 = makeEl('button', { dataset: { vplay: 'suggested-L2' } });
const capB = makeEl('button', { dataset: { vcap: 'suggested-L1' } });
const capB2 = makeEl('button', { dataset: { vcap: 'suggested-L2' } });
const dlB = makeEl('button', { dataset: { vfb: 'suggested-L1' } });
capB.parent = box; capB2.parent = box; dlB.parent = box;

const created = [];
const notices = [];
const blobs = [];
const revoked = [];
const timers = [];
const apiCalls = [];
const apiResolvers = [];
const registry = { '[data-vplay]': [playB1, playB2], '[data-vcap]': [capB, capB2], '[data-vfb]': [dlB] };

const sandbox = {
  esc,
  state: { user: { id: 'student-a', role: 'student' }, module: { id: 'M49', opened: {}, materials: { version: 'matv1', faculty_videos: ITEMS } } },
  notify: (msg, err) => notices.push({ msg, err }),
  api: (p, b) => { apiCalls.push({ p, b }); return new Promise(r => apiResolvers.push(r)); },
  document: {
    querySelector: s => (s === '[data-suggested-player]' ? section : null),
    querySelectorAll: s => registry[s] || [],
    createElement: t => { const e = makeEl(t); created.push(e); return e; },
    body: makeEl('body'),
  },
  window: { history: { replaceState: () => {} } },
  URL: { createObjectURL: b => { blobs.push(b); return 'blob:test-' + blobs.length; }, revokeObjectURL: u => revoked.push(u) },
  Blob: class { constructor(parts, opts) { this.parts = parts; this.opts = opts; } },
  setTimeout: fn => { timers.push(fn); return 1; },
  start: () => {},
  module: { exports: {} },
};
vm.createContext(sandbox);
const src = fs.readFileSync(path.join(__dirname, 'web', 'learning.js'), 'utf8');
vm.runInContext(src + '\nmodule.exports={formatTimecode,parseTimecode,videoFeedbackPayload,suggestedVideoMarkup,wireSuggestedPlayer,wireVideoFeedback};', sandbox);
const { formatTimecode, parseTimecode, videoFeedbackPayload, suggestedVideoMarkup, wireSuggestedPlayer, wireVideoFeedback } = sandbox.module.exports;

// --- pure helpers ------------------------------------------------------------
assert.strictEqual(parseTimecode('83'), 83);
assert.strictEqual(parseTimecode('1:23'), 83);
assert.strictEqual(parseTimecode('1:02:03'), 3723);
assert.strictEqual(parseTimecode('1:99'), null);
assert.strictEqual(parseTimecode('abc'), null);
assert.strictEqual(parseTimecode(''), null);
assert.strictEqual(parseTimecode('Infinity'), null);
assert.strictEqual(formatTimecode(83), '1:23');
assert.strictEqual(formatTimecode(3686), '61:26');

const payload = videoFeedbackPayload('M49', ITEMS[0], 75, '  текст  ');
assert.strictEqual(payload.schema, 'onco-video-feedback/v1');
assert.strictEqual(payload.timecode_seconds, 75);
assert.strictEqual(payload.comment, 'текст');
for (const key of Object.keys(payload)) {
  assert.ok(!/user|student|teacher|name|login|account/i.test(key), 'PII-like key: ' + key);
}

const html = suggestedVideoMarkup(ITEMS[1]);
assert.ok(html.includes('предварительно сопоставлен'));
assert.ok(html.includes('Possible cut'));
assert.ok(html.includes('data-vplay="suggested-L2"'));
assert.ok(html.includes('data-vcap="suggested-L2"'));
assert.ok(html.includes('data-vfb="suggested-L2"'));
assert.ok(html.includes('YouTube'));

async function main() {
  // --- player: select → metadata → seek → ready ------------------------------
  wireSuggestedPlayer();
  wireVideoFeedback();
  assert.strictEqual(section._vidSeq, 0);
  assert.strictEqual(section._vidReady, false);

  playB1.dispatch('click');
  assert.strictEqual(video.src, 'https://video.test/v1.mp4');
  assert.strictEqual(video.loadCalls, 1);
  assert.strictEqual(video.paused, true);
  assert.strictEqual(warn.hidden, true);

  // open is recorded through the existing API with captured context
  assert.strictEqual(apiCalls.length, 1);
  assert.strictEqual(apiCalls[0].p, '/api/resources/open');
  assert.strictEqual(apiCalls[0].b.module, 'M49');
  assert.strictEqual(apiCalls[0].b.version, 'matv1');
  assert.strictEqual(apiCalls[0].b.resource, 'suggested-L1');
  apiResolvers[0]({ saved: true, url: ITEMS[0].url });
  await Promise.resolve(); await Promise.resolve();
  assert.ok(sandbox.state.module.opened['suggested-L1'], 'open marked after API success');

  // capture is refused before metadata: lecture selected but not ready yet
  timeInput.value = '';
  capB.dispatch('click');
  assert.strictEqual(timeInput.value, '');
  assert.ok(notices.at(-1).err);

  video.fireMeta();
  assert.strictEqual(video.currentTime, 10);
  assert.strictEqual(section._vidReady, true);
  assert.strictEqual(go.hidden, false);
  assert.ok((video.playCalls || 0) === 0, 'no autoplay before explicit user launch');

  // capture allowed once metadata+seek completed
  video.currentTime = 75;
  capB.dispatch('click');
  assert.strictEqual(timeInput.value, '1:15');

  // truncation warning of the selected lecture shows near the shared player
  playB2.dispatch('click');
  assert.strictEqual(warn.hidden, false);
  assert.strictEqual(warn.textContent, 'Possible cut');
  assert.strictEqual(section._vidReady, false, 'ready resets on lecture switch');
  video.fireMeta();
  assert.strictEqual(video.currentTime, 30);
  assert.strictEqual(section._vidReady, true);
  playB1.dispatch('click');
  assert.strictEqual(warn.hidden, true);
  video.fireMeta();
  assert.strictEqual(video.currentTime, 10);

  // stale metadata does not move the playhead
  video.currentTime = 999;
  video.isConnected = false;
  playB2.dispatch('click');
  video.fireMeta();
  assert.strictEqual(video.currentTime, 999);
  video.isConnected = true;

  // deferred play rejection after switching must not overwrite new status
  let rejectPlay;
  video.play = () => new Promise((_, rej) => { rejectPlay = rej; });
  video.fireMeta(); // seek to L2 offset, ready
  go.dispatch('click');
  playB1.dispatch('click'); // user switched lecture before rejection
  const statusAfterSwitch = status.textContent;
  rejectPlay(new Error('aborted'));
  await Promise.resolve(); await Promise.resolve();
  assert.strictEqual(status.textContent, statusAfterSwitch, 'stale play error kept new lecture status');
  assert.ok(!status.textContent.includes('Не удалось запустить'));

  // current play rejection (no switch) shows the fallback
  video.fireMeta();
  go.dispatch('click');
  rejectPlay(new Error('aborted'));
  await Promise.resolve(); await Promise.resolve();
  assert.ok(status.textContent.includes('Не удалось запустить запись'));

  // media error shows a clear fallback and drops readiness
  section._vidReady = true;
  video.fireError();
  assert.strictEqual(section._vidReady, false);
  assert.strictEqual(go.hidden, true);
  assert.ok(status.textContent.includes('YouTube'));

  // stale open-marking: module changed before API resolves → nothing marked
  const moduleB = { id: 'M50', opened: {}, materials: { version: 'matv1', faculty_videos: ITEMS } };
  const realModule = sandbox.state.module;
  sandbox.state.module = moduleB;
  playB1.dispatch('click'); // click happened while M50 shown; items still resolve
  apiResolvers.at(-1)({ saved: true });
  sandbox.state.module = realModule;
  await Promise.resolve(); await Promise.resolve();
  assert.strictEqual(moduleB.opened['suggested-L1'], undefined);

  // capture for a different lecture is refused (context is not silently carried)
  timeInput.value = '';
  capB2.dispatch('click');
  assert.strictEqual(timeInput.value, '');
  assert.ok(notices.at(-1).err);

  // empty / whitespace comment rejected, nothing downloaded
  timeInput.value = '1:15';
  commentInput.value = '   ';
  const blobCount = blobs.length;
  dlB.dispatch('click');
  assert.strictEqual(blobs.length, blobCount);
  assert.ok(notices.at(-1).msg.includes('комментарий'));

  // invalid time rejected
  commentInput.value = 'нужна сверка';
  timeInput.value = 'не время';
  dlB.dispatch('click');
  assert.strictEqual(blobs.length, blobCount);
  assert.ok(notices.at(-1).msg.includes('таймкод'));

  // valid input → Blob payload, anchor appended/clicked/removed, deferred revoke
  timeInput.value = '1:15';
  dlB.dispatch('click');
  assert.strictEqual(blobs.length, blobCount + 1);
  const saved = JSON.parse(blobs.at(-1).parts[0]);
  assert.strictEqual(saved.module, 'M49');
  assert.strictEqual(saved.lecture_id, 'L1');
  assert.strictEqual(saved.video_id, 'V1');
  assert.strictEqual(saved.timecode_seconds, 75);
  assert.strictEqual(saved.comment, 'нужна сверка');
  const anchor = created.at(-1);
  assert.strictEqual(anchor.tagName, 'A');
  assert.strictEqual(anchor.download, 'video-feedback-M49-L1.json');
  assert.strictEqual(anchor.clicked, 1);
  assert.strictEqual(anchor.removed, true);
  assert.ok(notices.at(-1).msg.includes('Скачивание запрошено'));
  assert.ok(!/сохранено/i.test(notices.at(-1).msg));
  assert.strictEqual(revoked.length, 0);
  for (const t of timers.splice(0)) t();
  assert.strictEqual(revoked.length, 1);
}

main().then(() => console.log('pilot/test_video_feedback_ui.js: ok'))
  .catch(e => { console.error(e); process.exit(1); });
